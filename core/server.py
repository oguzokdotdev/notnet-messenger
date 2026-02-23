import socket
import threading
import time
import json
from typing import Callable, Dict, List, Optional, Tuple

from .protocol import (
    PROTOCOL_VERSION,
    encode_line,
    split_lines,
    parse_hello,
    make_protocol_ok,
    make_protocol_mismatch,
)

class NotNetServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 55555):
        self.host = host
        self.port = port

        self.server_socket: Optional[socket.socket] = None
        self.clients: Dict[socket.socket, Tuple[str, Tuple[str, int]]] = {}
        self._lock = threading.Lock()
        self._running = False
        self._started_at: Optional[float] = None

        self.on_log: Optional[Callable[[str, str], None]] = None
        self.on_clients: Optional[Callable[[List[Tuple[str, str]]], None]] = None

    @property
    def started_at(self) -> Optional[float]:
        return self._started_at

    @property
    def running(self) -> bool:
        return self._running

    def _emit_log(self, text: str, kind: str = "info"):
        cb = self.on_log
        if cb:
            cb(text, kind)
        else:
            print(text)

    def _send_line(self, conn: socket.socket, line: str):
        conn.sendall(encode_line(line))

    def _collect_clients_for_ui(self) -> List[Tuple[str, str]]:
        with self._lock:
            items = [(u, f"{a[0]}:{a[1]}") for _, (u, a) in self.clients.items()]
        items.sort(key=lambda x: x[0].lower())
        return items

    def _broadcast_clients_list(self):
        items = self._collect_clients_for_ui()
        usernames = [u for u, _ in items]
        self._broadcast("@CLIENTS " + json.dumps(usernames, ensure_ascii=False))

    def _emit_clients(self):
        items = self._collect_clients_for_ui()

        cb = self.on_clients
        if cb:
            cb(items)

        # отправляем клиентам список пользователей
        self._broadcast_clients_list()

    def _drop_client(self, conn: socket.socket):
        with self._lock:
            self.clients.pop(conn, None)
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass

    def _broadcast(self, line: str, exclude: Optional[socket.socket] = None):
        data = encode_line(line)

        with self._lock:
            conns = list(self.clients.keys())

        dead = []
        for conn in conns:
            if conn is exclude:
                continue
            try:
                conn.sendall(data)
            except OSError:
                dead.append(conn)

        if dead:
            for conn in dead:
                self._drop_client(conn)
            # важно: один апдейт списка, без рекурсий
            self._emit_clients()

    def _username_taken(self, username: str) -> bool:
        target = username.casefold()
        with self._lock:
            return any(u.casefold() == target for u, _ in self.clients.values())

    def start(self):
        if self._running:
            return

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            s.bind((self.host, self.port))
            s.listen()
            s.settimeout(0.5)
        except OSError as e:
            # важно: не оставляем сокет висеть и не делаем вид, что сервер запущен
            try:
                s.close()
            except OSError:
                pass

            self.server_socket = None
            self._running = False
            self._started_at = None

            if getattr(e, "errno", None) == 98:
                self._emit_log(
                    f"[!] Port {self.port} is already in use (server not started).",
                    "error",
                )
            else:
                self._emit_log(f"[!] Server failed to start: {e}", "error")

            # чтобы UI сразу обновил список/состояние
            self._emit_clients()
            return

        self.server_socket = s
        self._running = True
        self._started_at = time.time()
        self._emit_log(f"NotNet Server running on {self.host}:{self.port}", "info")

        try:
            while self._running:
                try:
                    conn, addr = s.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                t = threading.Thread(
                    target=self._handle_client, args=(conn, addr), daemon=True
                )
                t.start()
        finally:
            # если поток умер сам — подчистим состояние
            self._running = False
            self._started_at = None
            if self.server_socket is s:
                self.server_socket = None
            try:
                s.close()
            except OSError:
                pass
            self._emit_clients()


    def stop(self):
        # если сервер не запущен — не пишем "stopped" как будто он реально работал
        if not self._running and self.server_socket is None:
            self._emit_log("Server is not running", "info")
            return

        self._running = False
        self._started_at = None

        s = self.server_socket
        self.server_socket = None
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

        with self._lock:
            conns = list(self.clients.keys())

        # сначала пытаемся мягко предупредить
        for conn in conns:
            try:
                self._send_line(conn, "@SERVER_CLOSED")
            except OSError:
                pass

        # затем закрываем
        for conn in conns:
            self._drop_client(conn)

        self._emit_clients()
        self._emit_log("Server stopped", "warn")
        
    def kick(self, username: str) -> bool:
        target: Optional[socket.socket] = None
        with self._lock:
            for conn, (u, _) in self.clients.items():
                if u == username:
                    target = conn
                    break

        if target is None:
            return False

        # убрать из списка сразу — чтобы не было гонок и “мнимых” клиентов
        with self._lock:
            self.clients.pop(target, None)

        try:
            self._send_line(target, "@KICK")
        except OSError:
            pass

        # закрытие
        try:
            target.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            target.close()
        except OSError:
            pass

        self._emit_log(f"[!] {username} kicked", "warn")
        self._emit_clients()
        return True

    def _recv_line_handshake(self, conn: socket.socket, buffer: str = ""):
        conn.settimeout(None)

        while "\n" not in buffer:
            chunk = conn.recv(1024)
            if not chunk:
                raise ConnectionError("connection closed during handshake")
            buffer += chunk.decode("utf-8", errors="replace")

        line, buffer = buffer.split("\n", 1)
        return line, buffer

    def _handle_client(self, conn: socket.socket, addr):
        username: Optional[str] = None
        buffer = ""

        try:
            hello_line, buffer = self._recv_line_handshake(conn)
            try:
                client_ver = parse_hello((hello_line or "").strip())
            except Exception:
                try:
                    self._send_line(conn, "@ERR bad_hello")
                except OSError:
                    pass
                self._drop_client(conn)
                return

            if client_ver != PROTOCOL_VERSION:
                try:
                    self._send_line(conn, make_protocol_mismatch(PROTOCOL_VERSION, client_ver))
                except OSError:
                    pass
                self._drop_client(conn)
                self._emit_log(
                    f"[!] Protocol mismatch from {addr} (client={client_ver}, server={PROTOCOL_VERSION})",
                    "warn",
                )
                return

            try:
                self._send_line(conn, make_protocol_ok(PROTOCOL_VERSION))
            except OSError:
                pass

            username_line, buffer = self._recv_line_handshake(conn, buffer=buffer)
            username = (username_line or "").strip()

            if not username:
                try:
                    self._send_line(conn, "@ERR username_empty")
                except OSError:
                    pass
                self._drop_client(conn)
                return

            if username.casefold() == "server":
                try:
                    self._send_line(conn, "@ERR username_reserved")
                except OSError:
                    pass
                self._drop_client(conn)
                return

            if self._username_taken(username):
                try:
                    self._send_line(conn, "@ERR username_taken")
                except OSError:
                    pass
                self._drop_client(conn)
                return

            with self._lock:
                self.clients[conn] = (username, addr)

            self._send_line(conn, "@OK")
            self._emit_log(f"[+] {username} connected from {addr}", "connect")
            self._emit_clients()
            self._broadcast(f"* {username} joined", exclude=None)

            while self._running:
                lines, buffer = split_lines(buffer)
                for raw_line in lines:
                    text = raw_line.strip()
                    if not text:
                        continue
                    self._emit_log(f"{username}: {text}", "chat")
                    self._broadcast(f"{username}: {text}")

                chunk = conn.recv(1024)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")

        except Exception as e:
            self._emit_log(f"[!] client error {addr}: {e}", "error")
        finally:
            with self._lock:
                self.clients.pop(conn, None)

            try:
                conn.close()
            except OSError:
                pass

            self._emit_clients()
            if username:
                self._emit_log(f"[-] {username} disconnected", "disconnect")
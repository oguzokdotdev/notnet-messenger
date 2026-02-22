import socket
import threading
import time
import json
from typing import Callable, Dict, List, Optional, Tuple

from .protocol import encode_line, split_lines


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
        s.bind((self.host, self.port))
        s.listen()
        s.settimeout(0.5)

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
            self._running = False

    def stop(self):
        self._running = False

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

    def _recv_line_handshake(self, conn: socket.socket, limit: int = 256) -> Tuple[str, str]:
        """
        Читает до первой '\n' (handshake username).
        Возвращает (first_line, rest_buffer)
        """
        buffer = ""
        while "\n" not in buffer:
            chunk = conn.recv(1024)
            if not chunk:
                return "", ""
            buffer += chunk.decode("utf-8", errors="replace")
            if len(buffer) > limit:
                # слишком длинное имя/мусор
                return "", ""
        line, rest = buffer.split("\n", 1)
        return line, rest

    def _handle_client(self, conn: socket.socket, addr):
        username: Optional[str] = None
        buffer = ""

        try:
            username_line, buffer = self._recv_line_handshake(conn)
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

            # основной цикл
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
            # убрать из клиентов, закрыть
            with self._lock:
                self.clients.pop(conn, None)

            try:
                conn.close()
            except OSError:
                pass

            self._emit_clients()
            if username:
                self._emit_log(f"[-] {username} disconnected", "disconnect")
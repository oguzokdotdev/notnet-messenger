import socket
import threading
import json
from typing import Callable, Optional

from .protocol import (
    encode_line,
    split_lines,
    PROTOCOL_VERSION,
    make_hello,
)


class NotNetClient:
    def __init__(self):
        self.sock: Optional[socket.socket] = None
        self.username: Optional[str] = None

        self._running = False
        self._receiver_thread: Optional[threading.Thread] = None
        self._buffer = ""
        self._disconnect_reason = "connection lost"
        self._disconnect_notified = False
        self._close_lock = threading.Lock()

        self.on_line: Optional[Callable[[str], None]] = None
        self.on_disconnect: Optional[Callable[[str], None]] = None
        self.on_clients: Optional[Callable[[list], None]] = None

    @property
    def running(self) -> bool:
        return self._running

    def connect(self, host: str, port: int, username: str):
        if self._running:
            raise RuntimeError("Client already connected")

        username = username.strip()
        if not username:
            raise ValueError("Username is empty")

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((host, port))

        self.sock = s
        self.username = username

        self.sock.sendall(encode_line(make_hello(PROTOCOL_VERSION)))

        handshake_buffer = ""
        while "\n" not in handshake_buffer:
            data = self.sock.recv(1024)
            if not data:
                raise ConnectionError("Server closed connection during handshake")
            handshake_buffer += data.decode("utf-8", errors="replace")

        line, rest = handshake_buffer.split("\n", 1)
        line = line.strip()
        handshake_buffer = rest

        if line.startswith("ERR PROTOCOL_MISMATCH"):
            self._force_close()
            raise ConnectionError(line)

        if line != f"OK PROTOCOL {PROTOCOL_VERSION}":
            self._force_close()
            raise ConnectionError("Invalid server protocol handshake response")

        self.sock.sendall(encode_line(self.username))

        while "\n" not in handshake_buffer:
            data = self.sock.recv(1024)
            if not data:
                raise ConnectionError("Server closed connection during handshake")
            handshake_buffer += data.decode("utf-8", errors="replace")

        line, rest = handshake_buffer.split("\n", 1)
        line = line.strip()
        self._buffer = rest

        if line.startswith("@ERR "):
            code = line[5:].strip()
            self._force_close()

            if code == "username_reserved":
                raise ValueError('Username "SERVER" is reserved')
            if code == "username_taken":
                raise ValueError("Username already in use")
            if code == "username_empty":
                raise ValueError("Username is empty")
            if code == "bad_hello":
                raise ConnectionError("Bad protocol hello")
            raise ConnectionError(f"Server rejected connection: {code}")

        if line != "@OK":
            self._force_close()
            raise ConnectionError("Invalid server handshake response")

        self.sock.settimeout(None)

        self._running = True
        self._disconnect_notified = False
        self._disconnect_reason = "connection lost"
        self._buffer = self._buffer or ""

        self._receiver_thread = threading.Thread(target=self._receiver_loop, daemon=True)
        self._receiver_thread.start()

    def send(self, text: str):
        if not self._running or not self.sock:
            raise RuntimeError("Client is not connected")

        msg = text.rstrip("\n")
        self.sock.sendall(encode_line(msg))

    def disconnect(self, reason: str = "connection lost"):
        self._disconnect_reason = reason
        self._running = False
        self._force_close()

    def _force_close(self):
        # закрываем сокет один раз, потокобезопасно
        with self._close_lock:
            s = self.sock
            self.sock = None
            if s is None:
                return
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

    def _handle_protocol_line(self, line: str) -> bool:
        if line == "@KICK":
            self.disconnect("kicked by server")
            return True

        if line == "@SERVER_CLOSED":
            self.disconnect("server closed")
            return True

        if line.startswith("@CLIENTS "):
            payload = line[len("@CLIENTS "):].strip()
            try:
                data = json.loads(payload)
                if isinstance(data, list) and self.on_clients:
                    self.on_clients([str(x) for x in data])
            except Exception:
                pass
            return True

        if line == "@OK" or line.startswith("@ERR "):
            return True

        return False

    def _receiver_loop(self):
        reason = "connection lost"

        try:
            while self._running:
                s = self.sock
                if s is None:
                    break

                if "\n" not in self._buffer:
                    data = s.recv(1024)
                    if not data:
                        reason = "connection lost"
                        break
                    self._buffer += data.decode("utf-8", errors="replace")

                lines, self._buffer = split_lines(self._buffer)
                for line in lines:
                    if self._handle_protocol_line(line):
                        reason = self._disconnect_reason
                        if not self._running:
                            return
                        continue

                    cb = self.on_line
                    if cb:
                        cb(line)

        except Exception:
            reason = "connection lost"
        finally:
            final_reason = self._disconnect_reason or reason
            self._running = False
            self._force_close()

            cb = self.on_disconnect
            if cb and not self._disconnect_notified:
                self._disconnect_notified = True
                cb(final_reason)
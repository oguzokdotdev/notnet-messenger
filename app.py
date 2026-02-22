import sys, os
import threading
import time
import socket

from PySide6.QtCore import QObject, Signal, Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication, QTextCursor, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget,
    QListWidget, QListWidgetItem, QTextEdit, QMessageBox,
    QLineEdit, QToolButton, QMenu, QFileDialog
)

from core.server import NotNetServer
from core.client import NotNetClient


def _resource_path(rel_path: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel_path)

def load_app_fonts():
    font_path = _resource_path("assets/fonts/JetBrainsMono-Regular.ttf")
    if os.path.exists(font_path):
        QFontDatabase.addApplicationFont(font_path)

class BigButton(QPushButton):
    def __init__(self, text):
        super().__init__(text)
        self.setMinimumHeight(70)


class StartPage(QWidget):
    def __init__(self, go_server, go_client):
        super().__init__()

        outer = QVBoxLayout(self)
        outer.setSpacing(0)
        outer.setContentsMargins(24, 24, 24, 24)

        outer.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(0)
        row.addStretch(1)

        card = QWidget()
        card.setObjectName("startCard")
        card.setFixedWidth(360)

        layout = QVBoxLayout(card)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel("Choose mode:")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        btn_server = QPushButton("Server")
        btn_client = QPushButton("Client")

        for b in (btn_server, btn_client):
            b.setMinimumHeight(54)

        btn_server.clicked.connect(go_server)
        btn_client.clicked.connect(go_client)

        layout.addWidget(btn_server)
        layout.addWidget(btn_client)

        row.addWidget(card, 0)
        row.addStretch(1)

        outer.addLayout(row)
        outer.addStretch(1)

        self.setStyleSheet(self._css())

    def _css(self) -> str:
        return """
        QLabel#sectionTitle { font-size: 12pt; font-weight: 650; margin-bottom: 6px; }
        QWidget#startCard {
            border-radius: 14px;
            border: 1px solid rgba(148,163,184,0.18);
            background: rgba(2,6,23,0.15);
        }
        QPushButton {
            padding: 10px 12px;
            border-radius: 10px;
            background: rgba(148,163,184,0.14);
            border: 1px solid rgba(148,163,184,0.20);
        }
        QPushButton:hover { background: rgba(148,163,184,0.22); }
        """


class ServerBridge(QObject):
    log = Signal(str, str)
    clients = Signal(list)


class ServerPage(QWidget):
    def __init__(self, go_back):
        super().__init__()

        self.server = NotNetServer()
        self.server_thread = None
        self._started_at_ts = None

        self.bridge = ServerBridge()
        self.server.on_log = lambda text, kind="info": self.bridge.log.emit(text, kind)
        self.server.on_clients = lambda items: self.bridge.clients.emit(items)

        self.bridge.log.connect(self._append_log)
        self.bridge.clients.connect(self._set_clients)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        top = QHBoxLayout()
        back = QPushButton("← Back")
        back.clicked.connect(go_back)
        top.addWidget(back)
        top.addStretch(1)
        layout.addLayout(top)

        title = QLabel("Server mode")
        title.setObjectName("title")
        layout.addWidget(title)

        ip_row = QHBoxLayout()
        ip_row.setSpacing(10)

        self.lbl_addr = QLabel(self._format_addr())
        self.lbl_addr.setObjectName("addr")
        self.lbl_addr.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.btn_copy = QPushButton("Copy")
        self.btn_copy.clicked.connect(self._copy_addr)

        self.lbl_uptime = QLabel("Uptime: 00:00:00")
        self.lbl_uptime.setObjectName("uptime")

        ip_row.addWidget(self.lbl_addr, 0)
        ip_row.addWidget(self.btn_copy, 0)
        ip_row.addStretch(1)
        ip_row.addWidget(self.lbl_uptime, 0)
        layout.addLayout(ip_row)

        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)

        controls.addWidget(self.btn_start)
        controls.addWidget(self.btn_stop)
        controls.addStretch(1)
        layout.addLayout(controls)

        mid = QHBoxLayout()
        mid.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(8)

        clients_title = QLabel("Clients")
        clients_title.setObjectName("sectionTitle")
        left.addWidget(clients_title)

        self.list_clients = QListWidget()
        self.list_clients.setObjectName("clientsList")
        left.addWidget(self.list_clients, 1)

        kick_row = QHBoxLayout()
        kick_row.setSpacing(10)

        self.btn_kick = QPushButton("Kick")
        self.btn_kick.setEnabled(False)
        self.btn_kick.clicked.connect(self._kick_selected)

        kick_row.addWidget(self.btn_kick)
        kick_row.addStretch(1)
        left.addLayout(kick_row)

        right = QVBoxLayout()
        right.setSpacing(8)

        log_header = QHBoxLayout()
        log_header.setSpacing(6)

        log_title = QLabel("Log")
        log_title.setObjectName("sectionTitle")

        self.log_menu_btn = QToolButton()
        self.log_menu_btn.setText("⋯")
        self.log_menu_btn.setPopupMode(QToolButton.InstantPopup)

        menu = QMenu(self)
        menu.addAction("Export log", self._export_log)
        menu.addAction("Clear log", self._clear_log)

        self.log_menu_btn.setMenu(menu)

        log_header.addWidget(log_title)
        log_header.addStretch(1)
        log_header.addWidget(self.log_menu_btn)

        right.addLayout(log_header)

        self.log = QTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setAcceptRichText(True)
        right.addWidget(self.log, 1)

        broadcast_row = QHBoxLayout()
        broadcast_row.setSpacing(8)

        self.input_broadcast = QLineEdit()
        self.input_broadcast.setPlaceholderText("Broadcast as SERVER...")
        self.input_broadcast.returnPressed.connect(self._send_broadcast)

        self.btn_broadcast = QPushButton("Send")
        self.btn_broadcast.clicked.connect(self._send_broadcast)

        broadcast_row.addWidget(self.input_broadcast, 1)
        broadcast_row.addWidget(self.btn_broadcast, 0)

        right.addLayout(broadcast_row)

        mid.addLayout(left, 1)
        mid.addLayout(right, 2)
        layout.addLayout(mid, 1)

        self.btn_start.clicked.connect(self._start_server)
        self.btn_stop.clicked.connect(self._stop_server)
        self.list_clients.itemSelectionChanged.connect(self._on_client_select)

        self.uptime_timer = QTimer(self)
        self.uptime_timer.setInterval(1000)
        self.uptime_timer.timeout.connect(self._tick_uptime)

        self.setStyleSheet(self._css())

    def _format_addr(self) -> str:
        ip = self._get_local_ip()
        return f"{ip}:{self.server.port}"

    def _get_local_ip(self) -> str:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            if s:
                try:
                    s.close()
                except OSError:
                    pass

    def _copy_addr(self):
        QGuiApplication.clipboard().setText(self.lbl_addr.text())
        self._append_log("Copied address to clipboard", "info")

    def _start_server(self):
        if self.server_thread and self.server_thread.is_alive():
            return

        self.lbl_addr.setText(self._format_addr())
        self._started_at_ts = time.time()

        self.server_thread = threading.Thread(target=self.server.start, daemon=True)
        self.server_thread.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.uptime_timer.start()
        self._tick_uptime()

    def _stop_server(self):
        self.server.stop()

        t = self.server_thread
        if t and t.is_alive():
            threading.Thread(target=t.join, kwargs={"timeout": 2.0}, daemon=True).start()

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.uptime_timer.stop()
        self.lbl_uptime.setText("Uptime: 00:00:00")
        self._started_at_ts = None

    def _tick_uptime(self):
        if not self._started_at_ts:
            self.lbl_uptime.setText("Uptime: 00:00:00")
            return
        sec = int(time.time() - self._started_at_ts)
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        self.lbl_uptime.setText(f"Uptime: {h:02d}:{m:02d}:{s:02d}")

    def _set_clients(self, items):
        selected = self.list_clients.currentItem().text() if self.list_clients.currentItem() else None
        self.list_clients.clear()
        for username, addr in items:
            it = QListWidgetItem(f"{username}  ·  {addr}")
            it.setData(Qt.UserRole, username)
            self.list_clients.addItem(it)
            if selected and it.text() == selected:
                it.setSelected(True)

        self.btn_kick.setEnabled(self.list_clients.currentItem() is not None)

    def _on_client_select(self):
        self.btn_kick.setEnabled(self.list_clients.currentItem() is not None)

    def _kick_selected(self):
        item = self.list_clients.currentItem()
        if not item:
            return
        username = item.data(Qt.UserRole)
        ok = self.server.kick(username)
        if not ok:
            QMessageBox.information(self, "Kick", "Client not found (maybe already disconnected).")

    def _append_log(self, text: str, kind: str = "info"):
        ts = time.strftime("%H:%M:%S", time.localtime())
        kind = kind or "info"

        if kind == "connect":
            color = "#22c55e"
            msg = self._esc(text)
        elif kind == "disconnect":
            color = "#ef4444"
            msg = self._esc(text)
        elif kind == "chat":
            color = "#cbd5e1"
            msg = self._format_chat(text)
        elif kind == "warn":
            color = "#f59e0b"
            msg = self._esc(text)
        elif kind == "error":
            color = "#f87171"
            msg = self._esc(text)
        else:
            color = "#94a3b8"
            msg = self._esc(text)

        line = (
            f'<span style="color:#64748b;">[{ts}]</span> '
            f'<span style="color:{color};">{msg}</span>'
        )

        self.log.moveCursor(QTextCursor.End)
        self.log.insertHtml(line)
        self.log.insertPlainText("\n")
        self.log.moveCursor(QTextCursor.End)

    def _send_broadcast(self):
        text = self.input_broadcast.text().strip()
        if not text or not self.server.running:
            return

        message = f"SERVER: {text}"
        self.server._broadcast(message)

        self._append_log(message, "chat")
        self.input_broadcast.clear()

    def _clear_log(self):
        self.log.clear()

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export log",
            "notnet_session.log",
            "Log files (*.log)"
        )

        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log.toPlainText())
            self._append_log("Log exported successfully", "info")
        except Exception as e:
            self._append_log(f"Export failed: {e}", "error")

    def _format_chat(self, text: str) -> str:
        if ":" not in text:
            return self._esc(text)
        user, msg = text.split(":", 1)
        user = self._esc(user.strip())
        msg = self._esc(msg.lstrip())
        return f'<span style="color:#60a5fa; font-weight:600;">{user}</span><span style="color:#64748b;">:</span> {msg}'

    def _esc(self, s: str) -> str:
        return (
            s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&#39;")
        )

    def _css(self) -> str:
        return """
        QWidget { font-size: 11pt; }
        QLabel#title { font-size: 16pt; font-weight: 700; margin-bottom: 4px; }
        QLabel#sectionTitle { font-size: 12pt; font-weight: 650; margin-top: 6px; }
        QLabel#addr { font-family: monospace; font-size: 11pt; padding: 8px 10px; border-radius: 10px; background: rgba(148,163,184,0.12); }
        QLabel#uptime { color: rgba(226,232,240,0.85); }
        QPushButton { padding: 8px 12px; border-radius: 10px; background: rgba(148,163,184,0.14); border: 1px solid rgba(148,163,184,0.20); }
        QPushButton:hover { background: rgba(148,163,184,0.22); }
        QPushButton:disabled { opacity: 0.45; }
        QListWidget#clientsList { border-radius: 12px; padding: 8px; border: 1px solid rgba(148,163,184,0.18); background: rgba(2,6,23,0.15); }
        QListWidget#clientsList::item { padding: 6px 8px; border-radius: 8px; }
        QListWidget#clientsList::item:selected { background: rgba(96,165,250,0.25); }
        QTextEdit#log { border-radius: 12px; padding: 10px; border: 1px solid rgba(148,163,184,0.18); background: rgba(2,6,23,0.15); }
        QLineEdit { padding: 8px 10px; border-radius: 10px; border: 1px solid rgba(148,163,184,0.20); background: rgba(2,6,23,0.25); }
        QLineEdit:focus { border: 1px solid #60a5fa; }
        QToolButton { padding: 4px 8px; border-radius: 8px; background: rgba(148,163,184,0.14); border: 1px solid rgba(148,163,184,0.20); }
        QToolButton:hover { background: rgba(148,163,184,0.22); }
        """


class ClientBridge(QObject):
    line = Signal(str)
    disconnected = Signal(str)
    users = Signal(list)


class ClientPage(QWidget):
    def __init__(self, go_back):
        super().__init__()
        self._go_back_cb = go_back

        self.client = NotNetClient()
        self.bridge = ClientBridge()

        self.client.on_line = lambda line: self.bridge.line.emit(line)
        self.client.on_disconnect = lambda reason: self.bridge.disconnected.emit(reason)
        self.client.on_clients = lambda users: self.bridge.users.emit(users)

        self.bridge.line.connect(self._append_chat_line)
        self.bridge.disconnected.connect(self._on_disconnected)
        self.bridge.users.connect(self._set_users)

        self._messages_sent = 0
        self._messages_received = 0
        self._connected = False

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(24, 24, 24, 24)

        top = QHBoxLayout()
        back = QPushButton("← Back")
        back.clicked.connect(self._go_back)
        top.addWidget(back)
        top.addStretch(1)
        root.addLayout(top)

        title = QLabel("Client mode")
        title.setObjectName("title")
        root.addWidget(title)

        self.views = QStackedWidget()
        root.addWidget(self.views, 1)

        self._build_connect_view()
        self._build_chat_view()

        self.views.addWidget(self.connect_view)
        self.views.addWidget(self.chat_view)

        self.setStyleSheet(self._css())
        self._show_connect_view()

    def ensure_view(self):
        if self._connected:
            self.views.setCurrentWidget(self.chat_view)
        else:
            self.views.setCurrentWidget(self.connect_view)

    def _build_connect_view(self):
        self.connect_view = QWidget()
        outer = QVBoxLayout(self.connect_view)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addStretch(1)

        center_row = QHBoxLayout()
        center_row.setSpacing(0)
        center_row.addStretch(1)

        card = QWidget()
        card.setObjectName("connectCard")
        card.setFixedWidth(420)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(10)

        card_title = QLabel("Connect to server")
        card_title.setObjectName("sectionTitle")
        card_layout.addWidget(card_title)

        self.input_ip = QLineEdit()
        self.input_ip.setPlaceholderText("IP")
        self.input_ip.setText("127.0.0.1")

        self.input_port = QLineEdit()
        self.input_port.setPlaceholderText("PORT")
        self.input_port.setText("55555")

        self.input_username = QLineEdit()
        self.input_username.setPlaceholderText("Username")

        self.input_ip.returnPressed.connect(self._try_connect)
        self.input_port.returnPressed.connect(self._try_connect)
        self.input_username.returnPressed.connect(self._try_connect)

        card_layout.addWidget(QLabel("IP"))
        card_layout.addWidget(self.input_ip)

        card_layout.addWidget(QLabel("PORT"))
        card_layout.addWidget(self.input_port)

        card_layout.addWidget(QLabel("Username"))
        card_layout.addWidget(self.input_username)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self._try_connect)
        card_layout.addWidget(self.btn_connect)

        self.lbl_connect_hint = QLabel('Username "SERVER" is reserved')
        self.lbl_connect_hint.setObjectName("muted")
        card_layout.addWidget(self.lbl_connect_hint)

        center_row.addWidget(card, 0)
        center_row.addStretch(1)

        outer.addLayout(center_row)
        outer.addStretch(1)

    def _build_chat_view(self):
        self.chat_view = QWidget()
        layout = QHBoxLayout(self.chat_view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(8)

        chat_title = QLabel("Chat")
        chat_title.setObjectName("sectionTitle")
        left.addWidget(chat_title)

        self.chat_log = QTextEdit()
        self.chat_log.setObjectName("log")
        self.chat_log.setReadOnly(True)
        self.chat_log.setAcceptRichText(True)
        left.addWidget(self.chat_log, 1)

        send_row = QHBoxLayout()
        send_row.setSpacing(8)

        self.input_message = QLineEdit()
        self.input_message.setPlaceholderText("Type message...")
        self.input_message.returnPressed.connect(self._send_message)

        self.btn_send = QPushButton("Send")
        self.btn_send.clicked.connect(self._send_message)

        send_row.addWidget(self.input_message, 1)
        send_row.addWidget(self.btn_send, 0)
        left.addLayout(send_row)

        right = QVBoxLayout()
        right.setSpacing(8)

        info_title = QLabel("Connection")
        info_title.setObjectName("sectionTitle")
        right.addWidget(info_title)

        self.lbl_addr = QLabel("0.0.0.0:00000")
        self.lbl_addr.setObjectName("addr")
        self.lbl_addr.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.addWidget(self.lbl_addr)

        self.lbl_self = QLabel("You: —")
        self.lbl_self.setObjectName("muted")
        right.addWidget(self.lbl_self)

        self.lbl_status = QLabel("Status: offline")
        self.lbl_status.setObjectName("muted")
        right.addWidget(self.lbl_status)

        self.lbl_stats = QLabel("Sent: 0 · Received: 0")
        self.lbl_stats.setObjectName("muted")
        right.addWidget(self.lbl_stats)

        users_title = QLabel("Users")
        users_title.setObjectName("sectionTitle")
        right.addWidget(users_title)

        self.list_users = QListWidget()
        self.list_users.setObjectName("clientsList")
        right.addWidget(self.list_users, 1)

        actions_title = QLabel("Actions")
        actions_title.setObjectName("sectionTitle")
        right.addWidget(actions_title)

        self.btn_logout = QPushButton("Logout")
        self.btn_logout.clicked.connect(self._logout)
        right.addWidget(self.btn_logout)

        layout.addLayout(left, 2)
        layout.addLayout(right, 1)

    def _show_connect_view(self):
        self.views.setCurrentWidget(self.connect_view)
        self.input_message.clear()
        self.list_users.clear()
        self.chat_log.clear()
        self._messages_sent = 0
        self._messages_received = 0
        self._update_stats()
        self._connected = False
        self.lbl_status.setText("Status: offline")

    def _show_chat_view(self):
        self.views.setCurrentWidget(self.chat_view)
        self.input_message.setFocus()

    def _go_back(self):
        self._go_back_cb()

    def _try_connect(self):
        ip = self.input_ip.text().strip()
        port_text = self.input_port.text().strip()
        username = self.input_username.text().strip()

        if not ip:
            QMessageBox.warning(self, "Connect", "IP is empty.")
            return

        if not port_text.isdigit():
            QMessageBox.warning(self, "Connect", "PORT must be a number.")
            return

        port = int(port_text)
        if not (1 <= port <= 65535):
            QMessageBox.warning(self, "Connect", "PORT must be in range 1..65535.")
            return

        if not username:
            QMessageBox.warning(self, "Connect", "Username is empty.")
            return

        if username.casefold() == "server":
            QMessageBox.warning(self, "Connect", 'Username "SERVER" is reserved.')
            return

        self.btn_connect.setEnabled(False)

        try:
            self.client.connect(ip, port, username)
        except Exception as e:
            QMessageBox.warning(self, "Connect failed", str(e))
            self.btn_connect.setEnabled(True)
            return

        self.btn_connect.setEnabled(True)
        self._connected = True

        self.lbl_addr.setText(f"{ip}:{port}")
        self.lbl_self.setText(f"You: {username}")
        self.lbl_status.setText("Status: connected")
        self._update_stats()

        self._show_chat_view()
        self._append_system_line(f"Connected to {ip}:{port}")

    def _logout(self):
        if self._connected:
            self.client.disconnect("logged out")
            self._append_system_line("Logged out")
        self._show_connect_view()

    def _on_disconnected(self, reason: str):
        if not self._connected:
            return

        self._connected = False
        self.lbl_status.setText("Status: offline")
        self._append_system_line(f"Disconnected: {reason}")
        QMessageBox.information(self, "Disconnected", f"Connection closed: {reason}")
        self._show_connect_view()

    def _send_message(self):
        if not self._connected:
            return

        text = self.input_message.text().strip()
        if not text:
            return

        try:
            self.client.send(text)
        except Exception as e:
            QMessageBox.warning(self, "Send failed", str(e))
            return

        self._messages_sent += 1
        self._update_stats()
        self.input_message.clear()

    def _set_users(self, users):
        current = self.list_users.currentItem().text() if self.list_users.currentItem() else None
        self.list_users.clear()

        me = (self.client.username or "").casefold()
        for username in users:
            label = username
            if str(username).casefold() == me:
                label = f"{username} (you)"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, username)
            self.list_users.addItem(item)
            if current and label == current:
                item.setSelected(True)

    def _append_chat_line(self, line: str):
        if not self._connected:
            return

        self._messages_received += 1
        self._update_stats()

        ts = time.strftime("%H:%M:%S", time.localtime())
        text = line.strip()

        if text.startswith("* "):
            color = "#f59e0b"
            msg = self._esc(text)
        elif ":" in text:
            user, msg_text = text.split(":", 1)
            user = self._esc(user.strip())
            msg_text = self._esc(msg_text.lstrip())
            color = "#cbd5e1"
            msg = f'<span style="color:#60a5fa; font-weight:600;">{user}</span><span style="color:#64748b;">:</span> {msg_text}'
        else:
            color = "#cbd5e1"
            msg = self._esc(text)

        line_html = (
            f'<span style="color:#64748b;">[{ts}]</span> '
            f'<span style="color:{color};">{msg}</span>'
        )

        self.chat_log.moveCursor(QTextCursor.End)
        self.chat_log.insertHtml(line_html)
        self.chat_log.insertPlainText("\n")
        self.chat_log.moveCursor(QTextCursor.End)

    def _append_system_line(self, text: str):
        ts = time.strftime("%H:%M:%S", time.localtime())
        line_html = (
            f'<span style="color:#64748b;">[{ts}]</span> '
            f'<span style="color:#94a3b8;">{self._esc(text)}</span>'
        )
        self.chat_log.moveCursor(QTextCursor.End)
        self.chat_log.insertHtml(line_html)
        self.chat_log.insertPlainText("\n")
        self.chat_log.moveCursor(QTextCursor.End)

    def _update_stats(self):
        self.lbl_stats.setText(f"Sent: {self._messages_sent} · Received: {self._messages_received}")

    def _esc(self, s: str) -> str:
        return (
            s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&#39;")
        )

    def _css(self) -> str:
        return """
        QWidget { font-size: 11pt; }
        QLabel#title { font-size: 16pt; font-weight: 700; margin-bottom: 4px; }
        QLabel#sectionTitle { font-size: 12pt; font-weight: 650; margin-top: 6px; }
        QLabel#addr {
            font-family: monospace;
            font-size: 11pt;
            padding: 8px 10px;
            border-radius: 10px;
            background: rgba(148,163,184,0.12);
        }
        QLabel#muted { color: rgba(226,232,240,0.78); }
        QWidget#connectCard {
            border-radius: 14px;
            border: 1px solid rgba(148,163,184,0.18);
            background: rgba(2,6,23,0.15);
        }
        QPushButton {
            padding: 8px 12px;
            border-radius: 10px;
            background: rgba(148,163,184,0.14);
            border: 1px solid rgba(148,163,184,0.20);
        }
        QPushButton:hover { background: rgba(148,163,184,0.22); }
        QPushButton:disabled { opacity: 0.45; }
        QListWidget#clientsList {
            border-radius: 12px;
            padding: 8px;
            border: 1px solid rgba(148,163,184,0.18);
            background: rgba(2,6,23,0.15);
        }
        QListWidget#clientsList::item {
            padding: 6px 8px;
            border-radius: 8px;
        }
        QListWidget#clientsList::item:selected {
            background: rgba(96,165,250,0.25);
        }
        QTextEdit#log {
            border-radius: 12px;
            padding: 10px;
            border: 1px solid rgba(148,163,184,0.18);
            background: rgba(2,6,23,0.15);
        }
        QLineEdit {
            padding: 8px 10px;
            border-radius: 10px;
            border: 1px solid rgba(148,163,184,0.20);
            background: rgba(2,6,23,0.25);
        }
        QLineEdit:focus { border: 1px solid #60a5fa; }
        """


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NotNet")

        self.resize(900, 560)
        self.setMinimumSize(520, 360)

        self.setFont(QFont("JetBrains Mono", 11))
        self.setStyleSheet("""
            QWidget {
                background-color: #0f1115;
                color: #e6edf3;
                font-family: "JetBrains Mono";
                font-size: 11pt;
            }
            QPushButton {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 12px;
            }
            QPushButton:hover { background-color: #1f242d; }
            QPushButton:pressed { background-color: #0d1117; }
        """)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.start_page = StartPage(self.show_server, self.show_client)
        self.server_page = ServerPage(self.show_start)
        self.client_page = ClientPage(self.show_start)

        self.stack.addWidget(self.start_page)
        self.stack.addWidget(self.server_page)
        self.stack.addWidget(self.client_page)

        self.show_start()

    def _fit_to_current_page(self):
        w = self.stack.currentWidget()
        if not w:
            return

        hint = w.sizeHint()
        ww = max(hint.width() + 40, self.minimumWidth())
        hh = max(hint.height() + 40, self.minimumHeight())

        if self.width() < ww or self.height() < hh:
            self.resize(max(self.width(), ww), max(self.height(), hh))

    def show_start(self):
        self.stack.setCurrentWidget(self.start_page)
        QTimer.singleShot(0, self._fit_to_current_page)

    def show_server(self):
        self.stack.setCurrentWidget(self.server_page)
        QTimer.singleShot(0, self._fit_to_current_page)

    def show_client(self):
        self.client_page.ensure_view()
        self.stack.setCurrentWidget(self.client_page)
        QTimer.singleShot(0, self._fit_to_current_page)

    def closeEvent(self, event):
        try:
            if self.client_page.client.running:
                self.client_page.client.disconnect("app closed")
        except Exception:
            pass

        try:
            if self.server_page.server.running:
                self.server_page.server.stop()
        except Exception:
            pass

        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    load_app_fonts()
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
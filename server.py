import socket
import threading

HOST = "0.0.0.0"
PORT = 55555

clients = {}  # conn -> username
lock = threading.Lock()


def broadcast(message: str, exclude_conn=None):
    """Отправить сообщение всем подключённым клиентам (кроме exclude_conn, если задан)."""
    data = (message + "\n").encode("utf-8")
    with lock:
        dead = []
        for conn in clients.keys():
            if conn is exclude_conn:
                continue
            try:
                conn.sendall(data)
            except OSError:
                dead.append(conn)

        # если кто-то отвалился — чистим
        for conn in dead:
            clients.pop(conn, None)
            try:
                conn.close()
            except OSError:
                pass


def handle_client(conn: socket.socket, addr):
    """
    Логика на одного клиента в отдельном потоке:
    1) первым сообщением получает username
    2) потом в цикле читает строки и рассылает всем
    """
    try:
        # читаем имя (одна строка)
        username = conn.recv(1024).decode("utf-8").strip()
        if not username:
            conn.close()
            return

        with lock:
            clients[conn] = username

        print(f"[+] {username} connected from {addr}")
        broadcast(f"* {username} joined", exclude_conn=None)

        buffer = ""
        while True:
            chunk = conn.recv(1024)
            if not chunk:
                break  # клиент отключился

            buffer += chunk.decode("utf-8")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                text = line.strip()
                if not text:
                    continue

                msg = f"{username}: {text}"
                print(msg)
                broadcast(msg, exclude_conn=None)

    except Exception as e:
        print(f"[!] client error {addr}: {e}")

    finally:
        with lock:
            username = clients.pop(conn, None)
        try:
            conn.close()
        except OSError:
            pass

        if username:
            print(f"[-] {username} disconnected")
            broadcast(f"* {username} left", exclude_conn=None)


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()

    print(f"NotNet Server running on {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()


if __name__ == "__main__":
    main()

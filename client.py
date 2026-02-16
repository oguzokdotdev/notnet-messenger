import socket
import threading

PORT = 55555

def receiver(sock: socket.socket):
    """Поток, который постоянно слушает входящие сообщения и печатает их."""
    buffer = ""
    while True:
        try:
            data = sock.recv(1024)
            if not data:
                print("\n[disconnected]")
                break

            buffer += data.decode("utf-8")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                print(line)

        except OSError:
            break


def main():
    print("NotNet v0.1 [CLIENT]")

    host = input("Server IP (for same PC: 127.0.0.1):\n> ").strip()
    username = input("Enter your username:\n> ").strip()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, PORT))

    # первым сообщением отправляем имя (одна строка)
    sock.sendall((username + "\n").encode("utf-8"))

    print(f"Log in as {username}")
    print("Type /logout to exit")

    # запускаем поток приёма сообщений
    t = threading.Thread(target=receiver, args=(sock,), daemon=True)
    t.start()

    # основной поток: ввод -> send
    while True:
        text = input("> ")
        if text.strip().lower() == "/logout":
            break

        sock.sendall((text + "\n").encode("utf-8"))

    sock.close()


if __name__ == "__main__":
    main()

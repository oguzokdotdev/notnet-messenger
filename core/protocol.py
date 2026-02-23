DELIMITER = "\n"

PROTOCOL_VERSION = 1
HELLO_PREFIX = "HELLO"


def encode_line(text: str) -> bytes:
    return (text + DELIMITER).encode("utf-8")


def split_lines(buffer: str):
    lines = []
    while DELIMITER in buffer:
        line, buffer = buffer.split(DELIMITER, 1)
        lines.append(line)
    return lines, buffer


def make_hello(version: int = PROTOCOL_VERSION) -> str:
    return f"{HELLO_PREFIX} {version}"


def parse_hello(line: str) -> int:
    line = (line or "").strip()
    parts = line.split()
    if len(parts) != 2 or parts[0] != HELLO_PREFIX:
        raise ValueError("invalid hello")
    return int(parts[1])


def make_protocol_mismatch(server_version: int, client_version: int) -> str:
    return f"ERR PROTOCOL_MISMATCH server={server_version} client={client_version}"


def make_protocol_ok(server_version: int) -> str:
    return f"OK PROTOCOL {server_version}"
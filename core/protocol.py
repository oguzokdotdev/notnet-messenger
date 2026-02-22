DELIMITER = "\n"


def encode_line(text: str) -> bytes:
    return (text + DELIMITER).encode("utf-8")


def split_lines(buffer: str):
    lines = []
    while DELIMITER in buffer:
        line, buffer = buffer.split(DELIMITER, 1)
        lines.append(line)
    return lines, buffer
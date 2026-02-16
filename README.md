# NotNet

Minimal local network messenger without external servers.

NotNet is a simple LAN-based messenger designed for small groups.
No accounts. No cloud. No external servers.
Just devices talking inside the same network.

---

## Features (v0.1.0)

- Host/client architecture
- Multiple clients supported
- Real-time message delivery
- Join/leave notifications
- CLI interface
- Works inside a local network (LAN)

---

## How It Works

One device runs the server.
Other devices connect as clients using the server's local IP address.

All messages are handled by the host and broadcast to connected clients.

---

## Installation

Python 3.10+ required.

Clone the repository:

```bash
git clone https://github.com/oguzokdotdev/notnet-messenger.git
cd notnet-messenger
```

---

## Usage

### Start the server

```bash
python3 server.py
```

### Start a client

```bash
python3 client.py
```
If running on the same machine, use:
```
127.0.0.1
```
If running on another device in the same LAN, use the server's local IP address (e.g. 192.168.0.12).

---

## Commands
```
/logout
```
Disconnect from the server

---

## Roadmap
- Message timestamps & CLI customization
- User commands
- Encryption
- GUI interface
- Voice calls (still in LAN)
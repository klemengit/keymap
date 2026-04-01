"""keymenu-toggle — send TOGGLE to the running keymenu daemon."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

SOCKET_PATH = Path("/tmp/keymenu.sock")


def main() -> None:
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(SOCKET_PATH))
        sock.sendall(b"TOGGLE\n")
        sock.close()
    except ConnectionRefusedError:
        print("keymenu daemon is not running", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("keymenu daemon is not running", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Failed to contact keymenu daemon: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

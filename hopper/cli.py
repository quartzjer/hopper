import sys
from pathlib import Path

from blessed import Terminal
from platformdirs import user_data_dir

DATA_DIR = Path(user_data_dir("hopper"))
SOCKET_PATH = DATA_DIR / "server.sock"


def cmd_up() -> int:
    """Start the server."""
    from hopper.server import start_server

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    start_server(SOCKET_PATH)
    return 0


def cmd_ping() -> int:
    """Ping the server."""
    from hopper.client import ping

    if ping(SOCKET_PATH):
        print("pong")
        return 0
    else:
        print("failed to connect")
        return 1


def cmd_tui() -> int:
    """Run the TUI (default command)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    term = Terminal()
    print(term.clear)
    print(term.bold("hopper") + " - TUI for managing coding agents")
    print()
    print("Press any key to exit...")
    with term.cbreak():
        term.inkey()
    return 0


def main() -> int:
    """Main entry point with command dispatch."""
    args = sys.argv[1:]

    if not args:
        return cmd_tui()

    command = args[0]

    if command == "up":
        return cmd_up()
    elif command == "ping":
        return cmd_ping()
    else:
        print(f"unknown command: {command}")
        return 1

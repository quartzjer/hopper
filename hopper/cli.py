from pathlib import Path

from blessed import Terminal
from platformdirs import user_data_dir

DATA_DIR = Path(user_data_dir("hopper"))


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    term = Terminal()
    print(term.clear)
    print(term.bold("hopper") + " - TUI for managing coding agents")
    print()
    print("Press any key to exit...")
    with term.cbreak():
        term.inkey()

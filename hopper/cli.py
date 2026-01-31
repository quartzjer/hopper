from blessed import Terminal


def main():
    term = Terminal()
    print(term.clear)
    print(term.bold("hopper") + " - TUI for managing coding agents")
    print()
    print("Press any key to exit...")
    with term.cbreak():
        term.inkey()

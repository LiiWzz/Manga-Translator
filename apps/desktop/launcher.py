"""PyInstaller entry point. Import the API only after desktop storage is set up."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test-result", type=Path)
    arguments = parser.parse_args()
    if arguments.self_test_result:
        from app.desktop_smoke import self_test

        return self_test(arguments.self_test_result)
    from app.desktop_ui import main as desktop_main

    return desktop_main()


if __name__ == "__main__":
    raise SystemExit(main())

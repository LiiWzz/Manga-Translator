"""Wait for windowed frozen executables and verify their safe self-test report."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="manga-bundle-report-") as directory:
        result = Path(directory) / "result.json"
        completed = subprocess.run([str(args.executable.resolve()), "--self-test-result", str(result)], timeout=90)
        if completed.returncode or not result.is_file():
            raise SystemExit("Frozen desktop acceptance failed before reporting")
        report = json.loads(result.read_text(encoding="utf-8"))
        if report.get("status") != "ok":
            raise SystemExit("Frozen desktop acceptance failed: " + str(report.get("check", "unknown")))
        print("Frozen desktop acceptance passed: " + ", ".join(report["checks"]))


if __name__ == "__main__":
    main()

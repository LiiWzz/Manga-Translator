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
        if not result.is_file():
            raise SystemExit(f"Frozen desktop acceptance failed before reporting (exit {completed.returncode})")
        report = json.loads(result.read_text(encoding="utf-8"))
        if report.get("status") != "ok":
            # Only app-owned categories/class names, never exception messages
            # or a provider/account payload, are allowed in this report.
            raise SystemExit("Frozen desktop acceptance failed: " + json.dumps(report))
        if completed.returncode:
            raise SystemExit(f"Frozen desktop acceptance exited unexpectedly ({completed.returncode})")
        print("Frozen desktop acceptance passed: " + ", ".join(report["checks"]))


if __name__ == "__main__":
    main()

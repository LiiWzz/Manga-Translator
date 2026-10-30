"""Build on each target OS; allowlisted resources only, no .env or local state."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "desktop")
    args = parser.parse_args()
    if sys.platform not in {"darwin", "win32"}:
        parser.error("Build desktop bundles on Windows or macOS")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit("Choose a new, empty --output directory; existing files are never bundled")
    output.mkdir(parents=True, exist_ok=True)
    work = output / "work"
    work.mkdir(exist_ok=True)
    resources = work / "resources"
    resources.mkdir(exist_ok=True)
    from app.desktop_runtime import export_extension

    extension = export_extension(ROOT / "apps" / "extension", resources / "extension")
    icon = work / ("reader.icns" if sys.platform == "darwin" else "reader.ico")
    from PIL import Image

    with Image.open(ROOT / "apps" / "extension" / "icons" / "icon-128.png") as image:
        image.save(icon)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "MangaThaiReader", "--icon", str(icon), "--noupx",
        "--distpath", str(output / "app"), "--workpath", str(work / "pyinstaller"),
        "--specpath", str(work), "--paths", str(ROOT / "apps" / "api"),
        "--add-data", f"{extension}:bundled_extension",
        "--collect-data", "pythainlp", "--collect-data", "certifi",
        "--copy-metadata", "pythainlp", "--exclude-module", "pytest",
        "--hidden-import", "uvicorn.loops.asyncio",
        "--hidden-import", "uvicorn.protocols.http.h11_impl",
        "--hidden-import", "uvicorn.lifespan.on",
    ]
    if sys.platform == "darwin":
        command.extend(["--osx-bundle-identifier", "io.mangathaireader.companion"])
    command.append(str(ROOT / "apps" / "desktop" / "launcher.py"))
    subprocess.run(command, cwd=ROOT, check=True)

    # Distribute only the .app/onedir output and this guide, never the working
    # directory or a recursive archive of the repository/build machine.
    release = output / "release"
    release.mkdir(exist_ok=True)
    name = "MangaThaiReader.app" if sys.platform == "darwin" else "MangaThaiReader"
    destination = release / name
    shutil.copytree(output / "app" / name, destination, symlinks=True)
    shutil.copyfile(ROOT / "apps" / "desktop" / "START_HERE.html", release / "START_HERE.html")
    system = "macos" if sys.platform == "darwin" else "windows"
    archive = output / f"MangaThaiReader-{system}-{platform.machine().lower()}.zip"
    if sys.platform == "darwin":
        # ditto preserves the symlinks, executable bits and resource structure
        # inside a PyInstaller .app; a generic zip writer does not.
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", str(release), str(archive)], check=True)
    else:
        shutil.make_archive(str(archive.with_suffix("")), "zip", release)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n", encoding="utf-8")
    (output / "bundle.json").write_text(json.dumps({"archive": str(archive), "app": str(destination)}), encoding="utf-8")
    print(f"Desktop bundle: {archive}")


if __name__ == "__main__":
    main()

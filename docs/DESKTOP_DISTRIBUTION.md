# Sharing Manga Thai Reader with friends

The desktop companion starts the existing single-user API on **127.0.0.1:8000**
and stops it when its window closes. Friends need Chrome plus the app, with no
Python, Docker, terminal commands or shared server. Each person connects their own
account. It does not install a background service or change Chrome permissions.

## First use

1. Unzip the matching Windows x64, Mac Apple Silicon, or Mac Intel bundle. Keep
   the complete Windows app folder together; move the Mac `.app` to Applications.
2. Open the app. It automatically starts in mock mode on first use, showing demo
   dialogue without reading images or contacting a translation provider.
3. Click **เปิดโฟลเดอร์ extension**. In Chrome, open `chrome://extensions`, enable
   Developer mode, click **Load unpacked**, and select the folder the app opened.
   This is a manual installation until a separate Chrome Web Store release exists.
4. Open the extension's Options. In the app click **สร้างรหัสจับคู่**, copy the code
   into Options, and explicitly grant translation and Settings management.
5. To translate real images, stop the gateway in the app, select **ใช้ ChatGPT**,
   and start it again. In Options, click **จัดการการเชื่อมต่อ**, connect your own
   account, review plan-use consent, and select an available vision-capable model.
6. Open an authorized manga page, open Reader from the Chrome toolbar, and request
   a translation. Real account eligibility, model support and quota still apply.

Later sessions need only the open desktop app and the extension. The app remembers
the selected mode; pairing, account and model survive restart. Switching modes
requires a full stop before starting again. Keep the window open while reading.

## Data and updates

- Windows: `%LOCALAPPDATA%\MangaThaiReader`.
- macOS: `~/Library/Application Support/MangaThaiReader`.
- `auth/` contains the existing local account/pairing store; `desktop.json` stores
  only the mode. This is separate from Docker's volume and the source API's default
  directory. No credentials or `.env` files are copied from the build machine.
- Credentials retain the existing local plaintext storage design. POSIX uses
  owner-only files/directories; Windows uses the current user's Local AppData
  location and inherited filesystem access. No OS keychain integration is added.
- The exported `extension/` directory has a stable path so moving the app/archive
  does not change the unpacked extension ID. Translation cache/corrections remain
  in the Chrome profile. Do not delete the data folder as part of an update.
- To update: close the old app, replace the executable/app folder, open the new
  app, click **เปิดโฟลเดอร์ extension** to refresh the files, then click **Reload**
  for the existing unpacked extension in Chrome.
- If port 8000 is occupied, the app refuses to start. Stop the old companion or
  Docker backend first; it never pairs with or manages an unknown existing server.

## Building and downloading test bundles

The **Desktop companion** GitHub Actions workflow builds on each native OS:
Windows x64, macOS arm64, and macOS x64. It runs desktop tests, freezes Python/Qt,
bundles allowlisted extension resources, and checks the actual frozen executable
using local mock translation and temporary credentials. Download the matching ZIP
and SHA-256 file from its Actions artifacts. It does not create a public release,
upload credentials, publish to the Chrome Web Store, or merge a PR.

Maintainer build (run on the OS/architecture being distributed):

```sh
python -m venv .venv
# Activate the venv with your OS's command, then:
python -m pip install -e 'apps/api[desktop,bundle,test]'
python scripts/build_desktop.py
```

Smoke check:

```sh
# Windows:
python scripts/smoke_desktop.py dist/desktop/release/MangaThaiReader/MangaThaiReader.exe
# macOS:
python scripts/smoke_desktop.py dist/desktop/release/MangaThaiReader.app/Contents/MacOS/MangaThaiReader
```

Use a fresh `--output` directory when rebuilding. Smoke checks use an ephemeral
loopback port, temporary account storage, and the mock provider, and leave an
existing production API/account untouched. They exercise Qt startup, extension
export, TLS/Thai data, protected routes, pairing/reuse rejection, Reader mock
translation, Settings authority and graceful shutdown. No real provider calls.

Implementation references: [PyInstaller native OS builds and windowed bundles](https://pyinstaller.org/en/stable/usage.html#supporting-multiple-operating-systems)
and [GitHub hosted runner OS/architectures](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

## Distribution status

These are test bundles, not signed installers. Apple Developer ID signing
and notarization, Windows code signing, and Chrome Web Store publication are not
configured. OS download protections may block unsigned apps; do not disable those
protections to distribute a test. Signing requires publisher accounts/certificates
that are outside this code change. The `.app` receives PyInstaller's ad-hoc
signature, which is not a Developer ID signature.

The standalone bundle supports the current Vision Reader. It does not bundle the
Tesseract executable or Thai raster fonts required by the historical overlay/OCR
endpoints. Chrome installation, live sign-in and real translation still need
acceptance on clean Windows, Mac Intel and Mac Apple Silicon machines before
calling this release ready to share broadly.

# Job Finder for macOS

A Mac app that runs the Job Finder server on your Mac and shows the web app in its own window.
The `job-finder` command line tool keeps working exactly as before; the app is for people who prefer not to use a terminal.

## Install

1. Download `Job-Finder-<version>-arm64.dmg` from the latest GitHub release (or from a "Build Mac app" run).
2. Open it and drag **Job Finder** to Applications.
3. The app is not signed yet, so macOS blocks the first launch. **Right-click the app, choose Open, then Open again.**
   (If macOS still refuses: System Settings, Privacy & Security, "Open Anyway".)

Apple Silicon (M1 and later) only for now.

## Where things live

Everything you create is in `~/Library/Application Support/Job Finder`, not inside the app:

| File or folder | What it is |
|---|---|
| `.env` | Settings and API keys. Menu **Job Finder, Edit settings (.env)** opens it. Created from the example on first launch, readable only by you. |
| `data/`, `output/`, `applications_tracker/` | Your profile, tailored resumes and application history |
| `browsers/` | The Chromium the page scraper uses, downloaded once on first launch |

Deleting or updating the app does not touch this folder.

## Notes

- The server listens on `127.0.0.1:8000` (only this Mac). The Chrome extension and the web app expect that address. If 8000 is taken by something else, the app picks another port and the extension's one-click sync will not work on it.
- Auto-apply drives your installed Google Chrome. Install Chrome first.
- Resume PDFs need `tectonic`: `brew install tectonic`.
- Quit the app with Cmd+Q to stop the server.

## Build it yourself

```bash
macapp/build_mac.sh        # needs Python 3.12, Node 20, Xcode command line tools
```

This produces `dist-mac/Job Finder.app` and a `.dmg`. CI does the same with `.github/workflows/build_mac_app.yml`.

For development, without building:

```bash
pip install -r backend/requirements.txt -r macapp/requirements-app.txt
python macapp/job_finder_app.py            # window
python macapp/job_finder_app.py --check    # start, load the page, exit
```

## Not done yet

- Signing and notarization (needs an Apple Developer account), so the first-launch warning goes away.
- Automatic updates.
- Intel Macs.

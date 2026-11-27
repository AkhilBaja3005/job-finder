# Job Finder for macOS

A Mac app for the **job search and auto-apply** part of Job Finder. Pick the roles, location and limits, press Start, and
watch the agent search, filter, tailor and fill applications. It runs the same `job-finder scan` as the command line tool,
so the results are identical. You do not need a terminal.

## Install

### Option 1: Terminal (no Gatekeeper quarantine warning)

```bash
curl -fsSL https://raw.githubusercontent.com/AkhilBaja3005/job-finder/main/macapp/install_mac.sh | bash
```

### Option 2: `.dmg` download

1. Download `Job-Finder-<version>-arm64.dmg` from the latest GitHub release (or from a "Build Mac app" run).
2. Open it and drag **Job Finder** to Applications.
3. The app is not signed yet, so macOS blocks the first launch. **Right-click the app, choose Open, then Open again.**
   (If macOS still refuses: System Settings, Privacy & Security, "Open Anyway".)

Apple Silicon (M1 and later) only for now. Install Google Chrome first: the agent drives it.

## First run

The Run screen shows a short checklist until you are set up:

1. **Add an AI key** (Settings, AI providers). Gemini has a free tier.
2. **Create your profile** from your resume, or in Settings choose **Change…** and pick the folder your command line tool already uses.
3. **Connect Supabase** (optional).

Start with **Practice run**: the agent fills every form but never presses Submit. When it looks right, switch to **Apply for real**; the app asks you to confirm, showing the roles, location and limit.

## The window

| Screen | What it does |
|---|---|
| **Run** | Roles (type and press Return), location, how recent, practice or real. **Advanced** has the minimum ATS score, a limit, title keywords, sites to skip, and which AI drives the browser. Activity shows progress, counts, and the live log. |
| **Applications** | Every job recorded, with status, ATS match and a cloud mark for rows in your Supabase project. Search, filter, sort, open the job page, **Sync now**. |
| **Settings** | Your folder, profile, AI keys, Supabase, the scraper browser, updates and log files. |

Shortcuts: Cmd+Return start or stop, Cmd+. stop, Cmd+1/2/3 switch screens, Cmd+, settings. The usual Edit shortcuts (copy, paste, select all, undo) work in every field.

The app also: remembers its window size, opens only once, shows a notification when a run ends, checks GitHub for a newer version (it only reads the public releases page), and keeps its own log plus one log per run in `~/Library/Logs/Job Finder`.

The page's first-run download of the page scraper's browser (about 150 MB) happens in the background with a status banner and a Retry button.

## Supabase

If your folder's `.env` has `SUPABASE_URL` and a key (`SUPABASE_SERVICE_KEY`, or `SUPABASE_KEY`), the app uses your project:

- The sidebar shows **Synced with Supabase** (or "Supabase unreachable", or "Local only").
- **Applications** shows your project's list merged with the local tracker.
- Every scan already records to Supabase as it goes. When a run ends the app also adds any local application the project does not have yet. **Sync now** does the same on demand. Sync only adds missing rows; it never changes or deletes any.
- If the project cannot be reached, the app shows the local list and keeps working.

## Where things live

The app uses your Job Finder folder: by default `~/Library/Application Support/Job Finder`, or the one you chose.

| File or folder | What it is |
|---|---|
| `.env` | Settings and API keys, readable only by you (menu **Job Finder, Edit settings**) |
| `candidate_profile.json` | Your profile and search settings. The Scan form saves its fields here. |
| `applications_tracker/` | The application history shown under Results |
| `browsers/` (app folder only) | The Chromium the page scraper uses, downloaded once on first launch |

Deleting or updating the app does not touch these.

## Run the command line tool from the app

The app bundle can also run the command line tool directly, which is what the window does for each run:

```bash
"/Applications/Job Finder.app/Contents/MacOS/Job Finder" --cli scan --dry-run --limit 3
```

## Build it yourself

```bash
macapp/build_mac.sh        # needs Python 3.12 and the Xcode command line tools
```

This produces `dist-mac/Job Finder.app` and a `.dmg`. CI does the same with `.github/workflows/build_mac_app.yml`, then opens the built app's real window and checks that the page and the Python bridge came up (`JOB_FINDER_APP_SELFTEST=1`).

## Working on the window

The window is plain HTML, CSS and JavaScript in `macapp/panel/` (no build step). To work on it in a normal browser, serve that folder and open the mock:

```bash
cd macapp/panel && python3 -m http.server 8777
# open http://127.0.0.1:8777/dev/index.html  (add ?fresh, ?local, ?empty or ?update to see other states)
```

`dev/mock-api.js` stands in for the Python side and is not shipped. To run the real app from source:

```bash
pip install -r backend/requirements.txt -r macapp/requirements-app.txt
python macapp/job_finder_app.py
```

## Not done yet

- Signing and notarization (needs an Apple Developer account), so the first-launch warning goes away.
- Automatic updates.
- Intel Macs.
- A scheduler (run every morning). For now start a run from the window, or use the command line tool with cron.

## Windows

The same app runs on Windows 10 and 11 (it uses the WebView2 runtime that Windows already includes).

```powershell
macapp\build_windows.ps1        # needs Python 3.11 or 3.12; makes dist-win\Job Finder\Job Finder.exe and a zip
```

Windows differences: settings and logs live in `%APPDATA%\Job Finder` and `%LOCALAPPDATA%\Job Finder\Logs`; the daily run uses
Task Scheduler instead of launchd; there are no desktop notifications yet. The app is not code-signed, so SmartScreen may say
"Windows protected your PC": choose More info, then Run anyway.

## Automatic builds

`.github/workflows/build_desktop_apps.yml` builds the Mac app (Apple Silicon and Intel) and the Windows app:

- on every pull request and every push to `main` that touches `macapp/`, `backend/`, `job_finder/`, `applications_tracker/` or
  `pyproject.toml`, and runs a smoke test of each built app (the real window opens and the page must load);
- on a push to `main`, refreshes the `desktop-latest` pre-release with `Job-Finder-arm64.dmg`, `Job-Finder-x86_64.dmg` and
  `Job-Finder-windows.zip`. These names never change, which is what the website's download buttons link to;
- on a published GitHub release, attaches the versioned files to it.

### Signing and notarizing the Mac app (optional)
Needs an Apple Developer account. Add these repository secrets and the next build signs and notarizes by itself:

| Secret | What |
|---|---|
| `APPLE_CERT_P12_BASE64` | your "Developer ID Application" certificate exported as .p12, base64-encoded |
| `APPLE_CERT_PASSWORD` | the password you set when exporting it |
| `APPLE_SIGN_IDENTITY` | e.g. `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_ID`, `APPLE_TEAM_ID` | your Apple ID email and 10-character team id |
| `APPLE_APP_PASSWORD` | an app-specific password from appleid.apple.com |

Without them the Mac builds are unsigned and users right-click, Open the first time.

## Docked browser

Setting: Run, Advanced, Browser window, "Dock beside this window". The agent's Chrome opens against the right edge of the app window and follows it when it moves or resizes (`macapp/browser_dock.py`, through CDP `Browser.setWindowBounds`, same on Mac and Windows). It is not embedded: pywebview uses WKWebView on macOS, which has no DevTools protocol for browser-use, and Google blocks sign-in inside embedded web views. Off by default; with it off, or with a hidden run, Chrome opens as before.

### Preparing the release automatically

Actions, **Prepare release**, Run workflow (patch, minor, major or an exact version) does step 1 for you: it bumps the four version files, writes the `CHANGELOG.md` entry from the PR titles merged since the last tag (`feat:` under Added, `fix:` under Fixed, the rest under Changed; `ci:`, `test:`, `docs:`, `chore:` and merge commits are left out) and opens a `release/X.Y.Z` PR. Merge it, then run **Release**.
It needs the repository secret `RELEASE_TOKEN`: a fine-grained personal access token for this repository only, with Contents and Pull requests set to read and write (GitHub, Settings, Developer settings, Personal access tokens). The built-in token is not enough because pull requests it opens do not start the required checks. The same script runs locally: `python scripts/bump_version.py patch --dry-run`.

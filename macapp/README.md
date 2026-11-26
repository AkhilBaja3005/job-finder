# Job Finder for macOS

A Mac app for the **job search and auto-apply** part of Job Finder. Pick the roles, location and limits, press Start, and
watch the agent search, filter, tailor and fill applications. It runs the same `job-finder scan` as the command line tool,
so the results are identical. You do not need a terminal.

## Install

1. Download `Job-Finder-<version>-arm64.dmg` from the latest GitHub release (or from a "Build Mac app" run).
2. Open it and drag **Job Finder** to Applications.
3. The app is not signed yet, so macOS blocks the first launch. **Right-click the app, choose Open, then Open again.**
   (If macOS still refuses: System Settings, Privacy & Security, "Open Anyway".)

Apple Silicon (M1 and later) only for now. Install Google Chrome first: the agent drives it.

## First run

1. **Settings, AI keys:** paste at least one key (Gemini is free to start).
2. **Settings, Your folder:** if you already use the command line tool, choose **Use my existing Job Finder folder** and
   pick the folder that has your `candidate_profile.json` and `.env`. Otherwise use **Build profile from my resume** to
   create a profile from a PDF.
3. **Scan:** set the roles and limits. Leave it on **Practice run** first: the agent fills every form but never presses Submit.
4. When the practice run looks right, switch to **Apply for real**. The app asks you to confirm before it starts.

## The screens

| Screen | What it does |
|---|---|
| Scan | Roles, location, how recent, minimum ATS score, title keywords, sites to skip, how many applications, and which AI drives the browser. Live log and counters (checked, submitted, need your review, skipped). Stop ends the run. |
| Results | Every job the agent recorded, newest first, with its status and ATS score. "Open" shows the job page. |
| Settings | Your folder, your profile, and your AI keys. |

Closing the window stops a run that is still going. The browser window the agent opened stays open so you can review
the forms it filled.

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

This produces `dist-mac/Job Finder.app` and a `.dmg`. CI does the same with `.github/workflows/build_mac_app.yml`.

For development, without building:

```bash
pip install -r backend/requirements.txt -r macapp/requirements-app.txt
python macapp/job_finder_app.py
```

## Not done yet

- Signing and notarization (needs an Apple Developer account), so the first-launch warning goes away.
- Automatic updates.
- Intel Macs.
- A scheduler (run every morning). For now start a run from the window, or use the command line tool with cron.

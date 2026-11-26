# Privacy

*Draft written from how the software works. It is not legal advice; have it reviewed before you rely on it.*

Job Finder has three parts: the Mac app and command line tool that run on your computer, the website and server at
job-finder.space, and the Chrome extension.

## What stays on your computer
The Mac app and `job-finder` command keep these in your Job Finder folder: your profile (`candidate_profile.json`), your
`.env` (API keys, readable only by you), the application tracker, run logs and screenshots. They are not uploaded unless
you turn on a sync option below.

## What the server stores (only if you sign in or use a sync code)
- Your email address and your sync code.
- Your resume data and application history (job title, company, link, score, status).
- An optional API key you save for the AI provider. It is stored encrypted and is never shown back in full.
- Sign-in sessions.

The server is a Hugging Face Space; the database is Supabase. The database is locked with row-level security so only the
server can read it.

## What is sent to AI providers
When the software writes a cover letter, tailors a resume or fills a form, the relevant resume text and job description
are sent to the provider you chose (Google Gemini, Anthropic Claude or OpenAI), using your key or, on the website, the
server's key. Those providers handle the data under their own terms.

## The Mac app's sync code
If you enter a sync code in the Mac app, it uploads the application list (job title, company, link, score, status) to your
account. It never uploads API keys, your resume file or your profile.

## Your controls
- **Export:** the website's extension panel has "Export my data" (JSON, saved API keys left out).
- **Delete:** "Delete my account" removes your account, resumes and application history from the server.
- **Local data:** delete your Job Finder folder to remove everything on your computer.
- **Reset the sync code:** "New key" on the website makes the old code stop working.

## Problem reports
The Mac app's "Report a problem" only copies a short report to your clipboard and opens an email. API keys and your home
folder path are removed from it. Nothing is sent until you press send.

## Contact
hello@job-finder.space

# Senpilot Regulatory Document Agent

Agent that watches an inbox for requests like "give me Other Documents from
M12205", fetches up to `MAX_DOCS` of the requested documents from the UARB
FileMaker WebDirect portal (https://uarb.novascotia.ca/fmi/webd/UARB15),
zips them, and emails the ZIP back with a metadata/count summary.

Verified end-to-end against the live site, including a real matter (M12205)
and a real inbound/outbound email round trip.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # then fill in GMAIL_ADDRESS / GMAIL_APP_PASSWORD
```

Gmail App Password: enable 2-Step Verification on the agent's Gmail account,
then generate one at https://myaccount.google.com/apppasswords. A regular
Gmail password will fail IMAP/SMTP login (`AUTHENTICATIONFAILED`).

## Run

```bash
python3 main.py
```

Polls the inbox every `POLL_INTERVAL_SECONDS` (default 30s) for unseen mail,
processes each as a request, and sends a reply with a ZIP attachment.

To keep it running independent of your terminal session:

```bash
nohup python3 -u main.py > agent.log 2>&1 &
disown
```

## Known site behavior worth knowing

The UARB portal is a FileMaker WebDirect app with some real quirks, all
handled in `scraper.py` (see its module docstring for the full detail):

- No native HTML `<input>` elements exist anywhere on the page; fields are
  custom widgets that need a settle delay plus verify-and-retry text entry.
- Occasionally, large documents (one verified case was a PDF declaring
  itself ~46MB) come back **silently truncated** — the browser reports no
  error, but the saved file is a partial prefix. The agent detects this via
  the PDF's own declared length and skips documents that don't come through
  complete, rather than shipping a corrupt file. The reply email's
  "downloaded N out of M" count reflects only genuinely-complete files.
- `MAX_DOWNLOAD_ATTEMPTS` in `scraper.py` controls how many times a
  truncated download is retried before being skipped (currently 1, for
  faster replies; raise it to trade speed for a better chance of eventually
  getting a flaky large file).

## Project layout

- `parser.py` — extracts matter number + document type from the inbound
  email's subject/body.
- `scraper.py` — Playwright automation against the UARB portal (search,
  metadata/count extraction, tab navigation, download loop).
- `zipper.py` — zips downloaded files.
- `summary.py` — composes the reply email body from scrape results.
- `emailer.py` — IMAP fetch of unseen requests (only marks a message Seen
  after it's successfully handled, so a crash leaves it for retry rather
  than losing it), SMTP send of replies.
- `main.py` — polling loop tying it all together.

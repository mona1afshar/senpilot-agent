import os
from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
MAX_DOCS = int(os.environ.get("MAX_DOCS", "10"))
PLAYWRIGHT_HEADLESS = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() == "true"

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
OUTBOX_DIR = os.path.join(BASE_DIR, "outbox")

UARB_URL = "https://uarb.novascotia.ca/fmi/webd/UARB15"

DOC_TYPES = ["Exhibits", "Key Documents", "Other Documents", "Transcripts", "Recordings"]

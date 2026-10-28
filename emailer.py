import email as email_module
import imaplib
import smtplib
import traceback
from email.message import EmailMessage
from email.utils import parseaddr

from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD, IMAP_HOST, SMTP_HOST, SMTP_PORT


def process_unseen_requests(handler) -> None:
    """Fetch each unseen message and call handler(msg); a message is only marked
    Seen if handler(msg) returns without raising. A crash mid-processing (e.g. the
    scraper hitting a live-site error) therefore leaves the message unseen so it's
    retried on the next poll, instead of being silently lost.
    """
    with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
        imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN")
        for num in data[0].split():
            # BODY.PEEK[] (not RFC822) -- a plain RFC822/BODY[] fetch marks the
            # message \Seen as a side effect of the fetch itself, regardless of
            # the later explicit STORE call below -- confirmed live: a message
            # still vanished from UNSEEN even after a handler crash with the
            # STORE already made conditional on success.
            _, msg_data = imap.fetch(num, "(BODY.PEEK[])")
            raw_email = msg_data[0][1]
            msg = email_module.message_from_bytes(raw_email)
            body = _extract_plain_body(msg)
            parsed = {
                "message_id": msg.get("Message-ID", ""),
                "from_address": parseaddr(msg.get("From", ""))[1],
                "subject": msg.get("Subject", ""),
                "body": body,
            }

            try:
                handler(parsed)
            except Exception:
                traceback.print_exc()
                continue  # leave unseen for retry next poll

            imap.store(num, "+FLAGS", "\\Seen")


def _extract_plain_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(errors="replace")
        return ""
    return msg.get_payload(decode=True).decode(errors="replace")


def send_reply(to_address: str, subject: str, body: str, attachment_path: str | None) -> None:
    msg = EmailMessage()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body)

    if attachment_path:
        with open(attachment_path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="application",
                subtype="zip",
                filename=attachment_path.split("/")[-1],
            )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)

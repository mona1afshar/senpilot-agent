import os
import time
import traceback

from config import MAX_DOCS, OUTBOX_DIR, POLL_INTERVAL_SECONDS
from emailer import process_unseen_requests, send_reply
from parser import UnparseableRequest, parse_request_text
from scraper import run_scrape
from summary import build_reply_body
from zipper import zip_files


def handle_message(msg: dict) -> None:
    from_address = msg["from_address"]
    print(f"Processing request from {from_address}: {msg['subject']!r}")

    try:
        matter_number, doc_type = parse_request_text(msg["subject"], msg["body"])
    except UnparseableRequest as e:
        send_reply(
            from_address,
            "Re: " + msg["subject"],
            f"Sorry, I couldn't process that request: {e}",
            attachment_path=None,
        )
        return

    result = run_scrape(matter_number, doc_type, MAX_DOCS)

    zip_path = os.path.join(OUTBOX_DIR, f"{matter_number}_{doc_type.replace(' ', '_')}.zip")
    zip_files(result.downloaded_files, zip_path)

    body = build_reply_body(matter_number, result)
    send_reply(from_address, f"Re: {msg['subject']}", body, zip_path)
    print(f"Replied to {from_address} for {matter_number} with {len(result.downloaded_files)} files.")


def main_loop() -> None:
    print("Senpilot regulatory agent started. Polling inbox...")
    while True:
        try:
            process_unseen_requests(handle_message)
        except Exception:
            traceback.print_exc()
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main_loop()

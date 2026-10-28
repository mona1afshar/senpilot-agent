"""
Playwright automation for the UARB FileMaker WebDirect portal
(https://uarb.novascotia.ca/fmi/webd/UARB15).

Every selector below was confirmed by live-inspecting the real site's DOM
(via browser devtools-style JS execution against M12205 and M12383), not
guessed. Key findings that shape this module:

- There are NO native <input>/<textarea> elements anywhere on the page --
  FileMaker WebDirect renders fully custom widgets. Text entry only works by
  clicking a field's container div to activate it, then sending real
  keyboard events (page.keyboard.type), never Playwright's .fill().
- Record fields (matter number, title, type, category, dates, outcome...)
  are rendered with a STABLE per-field CSS class (e.g. "fm_object_286" for
  Matter No) that stays attached to the same field across different matter
  records -- confirmed by loading M12383 then M12205 and reading the same
  classes. These are hardcoded in FIELD_CLASSES/TITLE_FIELD_CLASS below.
- The page has THREE elements with the exact text "Search" (a nav tab, the
  matter-number box's own button, and the "Enter Search Criteria" form's
  button) all sitting in the same DOM ancestor, so proximity-via-ancestor
  does not disambiguate them -- confirmed live, it resolved to all three.
  Instead the one nearest the matter-number field by Y-coordinate is used.
- Interacting with the field immediately after page load silently fails
  (document.activeElement stays <body>, and even once focused, typed text
  can race the page's own async init and snap back to the placeholder) --
  confirmed live. A fixed settle delay plus a verify-and-retry fill loop
  are both required, not just one or the other.
- Tab labels already embed their counts as literal text, e.g. "Exhibits -
  13", so counts are read directly from the tab text (no separate count
  lookup needed).
- The document list is VIRTUALIZED: only ~9 rows exist in the DOM at once,
  regardless of the tab's total count. Scrolling the list removes rows that
  scroll out and renders new ones in. The download loop therefore scrolls
  and re-queries in rounds, deduping on the downloaded filename (row-ID
  formats aren't uniform across tabs -- see _download_documents).
- Files can be large (one verified Exhibit PDF was 26MB) and the server
  serves them slowly, so a download can legitimately take well over 15s --
  confirmed live. expect_download() needs a generous timeout for that.
- Separately, very large files (one verified case: a PDF whose own header
  declares it should be ~46MB) can come back SILENTLY TRUNCATED -- Chromium
  reports no failure (download.failure() is None) and the download event
  fires normally, but the saved file is a partial prefix. Confirmed live
  across multiple isolated single-download attempts: each truncated at a
  DIFFERENT byte count (6.75-7.0MB), never reaching the declared length --
  this points to a hard server/proxy-side cap or timeout for oversized
  files, not a bug in the click sequence (closing the modal immediately
  after was tested and ruled out as the cause). Linearized PDFs declare
  their true length in the `/Linearized` dictionary's `/L` field, so that's
  used as a ground truth to detect this and retry with a fresh modal (the
  modal's download button permanently disables itself after one click, so
  a retry must reopen it, not re-click the same button) -- see
  _is_pdf_probably_complete and MAX_DOWNLOAD_ATTEMPTS. A document that still
  fails after retries is skipped rather than shipped corrupt; the reply
  email's "downloaded N out of M" count reflects only genuinely-complete
  files.
- Clicking "GO GET IT" does not download anything by itself -- it opens a
  ".fm-modal-dialog" containing a ".fm-download-button" (labeled with the
  real filename, e.g. "102674.pdf"); THAT click triggers the actual browser
  download. The modal must then be dismissed via its "Close" button before
  the next row's "GO GET IT" can be used.
"""

import os
import re
from datetime import datetime

from playwright.sync_api import Page, sync_playwright

from config import DOC_TYPES, DOWNLOAD_DIR, PLAYWRIGHT_HEADLESS, UARB_URL
from models import MatterMetadata, ScrapeResult

MATTER_NUMBER_FIELD_CLASS = "fm_object_254"

FIELD_CLASSES = {
    "matter_no": "fm_object_286",
    "category": "fm_object_287",
    "status": "fm_object_289",
    "date_received": "fm_object_292",
    "date_final_submissions": "fm_object_294",
    "outcome": "fm_object_295",
    "type": "fm_object_298",
}
TITLE_FIELD_CLASS = "csFM-4BAC3292-04BC-FC44-A278-B61F356EAB45"

TAB_LABEL_RE = {dt: re.compile(rf"^{re.escape(dt)}\s*-\s*(\d+)$") for dt in DOC_TYPES}
DOWNLOAD_TIMEOUT_MS = 120_000
MAX_DOWNLOAD_ATTEMPTS = 1
GO_GET_IT_RE = re.compile("GO GET IT", re.I)
PDF_LINEARIZED_LENGTH_RE = re.compile(rb"/L\s+(\d+)")


def run_scrape(matter_number: str, doc_type: str, max_docs: int) -> ScrapeResult:
    matter_download_dir = os.path.join(DOWNLOAD_DIR, matter_number)
    os.makedirs(matter_download_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
        page = browser.new_page(accept_downloads=True)
        try:
            page.goto(UARB_URL, wait_until="networkidle")
            _search_matter(page, matter_number)

            metadata = _extract_metadata(page)
            counts_by_type = _extract_counts(page)

            downloaded_files = _download_documents(
                page, doc_type, max_docs, matter_download_dir, counts_by_type.get(doc_type, 0)
            )
        finally:
            browser.close()

    return ScrapeResult(
        metadata=metadata,
        counts_by_type=counts_by_type,
        downloaded_files=downloaded_files,
        requested_doc_type=doc_type,
    )


def _search_matter(page: Page, matter_number: str) -> None:
    # The page keeps doing async setup well past "networkidle" (FileMaker WebDirect
    # runs over a persistent websocket) -- interacting too early leaves the field
    # unfocused (document.activeElement stays <body>). Confirmed live: a fixed wait
    # plus explicit visibility check is needed before the field will accept input.
    page.wait_for_timeout(4000)
    field = page.locator(f".{MATTER_NUMBER_FIELD_CLASS}")
    field.wait_for(state="visible", timeout=15000)

    _fill_field_verified(page, field, matter_number)
    _click_search_button_near(page, field)

    page.locator(f".{TITLE_FIELD_CLASS}").first.wait_for(state="visible", timeout=15000)
    page.wait_for_timeout(500)


def _fill_field_verified(page: Page, field, text: str, attempts: int = 6) -> None:
    # Typing can silently lose the race against the field's own async init and land
    # back on the placeholder text -- confirmed live (it took a 2nd attempt even with
    # a 4s pre-wait). Retry until the field actually reflects what was typed.
    for _ in range(attempts):
        field.click()
        page.keyboard.type(text)
        page.wait_for_timeout(400)
        if text in field.first.inner_text().strip():
            return
        page.wait_for_timeout(400)
    raise RuntimeError(f"Could not get {text!r} to register in the matter-number field")


def _click_search_button_near(page: Page, field) -> None:
    # The page has THREE elements whose exact text is "Search": a top nav tab, the
    # "Go Directly to Matter" box's own button, and the "Enter Search Criteria" form's
    # button at the bottom -- confirmed live via bounding boxes. DOM-proximity scoping
    # (closest ancestor) did NOT narrow it down (all three sat in the same ancestor),
    # so instead pick whichever "Search" button is vertically closest to the field.
    field_box = field.bounding_box()
    buttons = page.get_by_role("button", name="Search", exact=True)
    best_index, best_distance = 0, None
    for i in range(buttons.count()):
        button_box = buttons.nth(i).bounding_box()
        if not button_box:
            continue
        distance = abs(button_box["y"] - field_box["y"])
        if best_distance is None or distance < best_distance:
            best_distance, best_index = distance, i
    buttons.nth(best_index).click()


def _inner_text_nonempty(page: Page, locator, timeout_ms: int = 10000, interval_ms: int = 250) -> str:
    # locator.inner_text() only waits for the element to be ATTACHED, not for its
    # text to be populated -- confirmed live: reading these fields right after the
    # title field became "visible" returned empty strings even though the element
    # existed. Poll until content actually shows up (or give up and return "").
    elapsed = 0
    text = ""
    while elapsed <= timeout_ms:
        text = locator.first.inner_text().strip()
        if text:
            return text
        page.wait_for_timeout(interval_ms)
        elapsed += interval_ms
    return text


def _is_pdf_probably_complete(path: str) -> bool:
    # Linearized PDFs (the common case for web-served documents) declare their own
    # true byte length in the `/L` field of the `/Linearized` dictionary, near the
    # top of the file -- a ground truth independent of however the download itself
    # got cut short. Not a linearized PDF (no match) -- accept it; we have no basis
    # to doubt it.
    try:
        with open(path, "rb") as f:
            header = f.read(4096)
    except OSError:
        return False
    match = PDF_LINEARIZED_LENGTH_RE.search(header)
    if not match:
        return True
    declared_length = int(match.group(1))
    return os.path.getsize(path) >= declared_length


def _extract_metadata(page: Page) -> MatterMetadata:
    values = {
        key: _inner_text_nonempty(page, page.locator(f".{cls}"))
        for key, cls in FIELD_CLASSES.items()
    }
    title = _inner_text_nonempty(page, page.locator(f".{TITLE_FIELD_CLASS}"))

    return MatterMetadata(
        title=title,
        type=values["type"],
        category=values["category"],
        status=values["status"],
        outcome=values["outcome"],
        initial_filing_date=_format_date(values["date_received"]),
        final_filing_date=_format_date(values["date_final_submissions"]),
    )


def _format_date(mmddyyyy: str) -> str | None:
    mmddyyyy = mmddyyyy.strip()
    if not mmddyyyy:
        return None
    dt = datetime.strptime(mmddyyyy, "%m/%d/%Y")
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def _extract_counts(page: Page) -> dict[str, int]:
    counts = {}
    for doc_type, pattern in TAB_LABEL_RE.items():
        label = page.get_by_text(pattern).first.inner_text().strip()
        counts[doc_type] = int(label.rsplit("-", 1)[1].strip())
    return counts


def _click_tab(page: Page, doc_type: str) -> None:
    page.get_by_text(TAB_LABEL_RE[doc_type]).first.click()
    # Row content loads async after the tab click; wait for at least the first
    # "GO GET IT" button to actually appear rather than a fixed guessed delay.
    page.get_by_role("button", name=GO_GET_IT_RE).first.wait_for(state="visible", timeout=10000)
    page.wait_for_timeout(500)


def _download_row(page: Page, go_get_it_locator, index: int, dest_dir: str) -> tuple[str | None, str | None]:
    """Attempts one row's download up to MAX_DOWNLOAD_ATTEMPTS times, re-opening the
    modal fresh each attempt -- its download button permanently disables itself after
    one click (confirmed live), so a retry means reopening the modal, not re-clicking
    the same disabled button. Returns (suggested_filename, dest_path); dest_path is
    None if every attempt came back truncated (see _is_pdf_probably_complete).
    """
    filename = None
    for _ in range(MAX_DOWNLOAD_ATTEMPTS):
        # force=True: after scrolling, Playwright's auto-scroll-into-view can land a
        # row right under the page's fixed header banner, which then visually (not
        # logically) covers the button and blocks a normal click -- confirmed live
        # ("iwps_header ... subtree intercepts pointer events"). The button itself is
        # the correct, real target, just temporarily obscured.
        go_get_it_locator.nth(index).click(force=True)

        modal = page.locator(".fm-modal-dialog")
        modal.wait_for(state="visible", timeout=10000)
        download_button = modal.locator(".fm-download-button")
        # The modal appears before its button's filename text is populated -- same
        # async-render lag seen elsewhere on this site. Clicking too early produces
        # a dead click.
        _inner_text_nonempty(page, download_button, timeout_ms=10000)

        # Files can be large (one verified exhibit was 26MB) and the server generates/
        # serves them slowly -- confirmed live, a single download took well over 15s.
        with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as dl_info:
            download_button.click()
        download = dl_info.value
        filename = download.suggested_filename
        candidate_path = os.path.join(dest_dir, filename)
        download.save_as(candidate_path)

        modal.get_by_role("button", name="Close", exact=True).click()
        modal.wait_for(state="hidden", timeout=10000)

        if _is_pdf_probably_complete(candidate_path):
            return filename, candidate_path

    return filename, None


def _download_documents(
    page: Page, doc_type: str, max_docs: int, dest_dir: str, available_count: int
) -> list[str]:
    if available_count == 0 or max_docs == 0:
        return []

    _click_tab(page, doc_type)

    # Row identifiers are NOT uniform across tabs -- confirmed live: "Other Documents"
    # rows show 6-digit Doc Nos (e.g. "102674") but "Exhibits" rows show letter-coded
    # Exhibit Nos (e.g. "H-4(C)-i"), so no single regex can pre-identify a row before
    # clicking it. Also confirmed: a row's "GO GET IT" button does NOT disable or
    # disappear after a successful download, so the visible button count can't signal
    # "already done" either. Dedupe on the actual downloaded filename instead, which
    # Playwright reports post-download regardless of row ID format.
    seen_filenames: set[str] = set()
    downloaded_paths: list[str] = []
    stall_rounds = 0

    while len(downloaded_paths) < max_docs and stall_rounds < 4:
        go_get_it_locator = page.get_by_role("button", name=GO_GET_IT_RE)
        visible_count = go_get_it_locator.count()

        progressed = False
        for i in range(visible_count):
            if len(downloaded_paths) >= max_docs:
                break

            try:
                filename, dest_path = _download_row(page, go_get_it_locator, i, dest_dir)
            except Exception as e:
                # A single row's unexpected failure (e.g. a stale/off-viewport element
                # after a long stretch of prior retries -- confirmed live after ~15+
                # minutes of retrying large files) must not discard everything already
                # downloaded. Abandon this scroll round; the outer loop re-queries
                # fresh locators next round rather than continuing with stale indices.
                print(f"  Row {i} failed unexpectedly ({type(e).__name__}: {e}); retrying after rescrolling.")
                break

            if filename in seen_filenames:
                continue  # same row re-offered this round; already handled
            seen_filenames.add(filename)
            progressed = True

            if dest_path is None:
                print(
                    f"  Skipping {filename}: kept arriving truncated after "
                    f"{MAX_DOWNLOAD_ATTEMPTS} attempts (likely too large for this server)."
                )
                continue

            downloaded_paths.append(dest_path)

        stall_rounds = 0 if progressed else stall_rounds + 1

        if len(downloaded_paths) < max_docs:
            page.mouse.wheel(0, 700)
            page.wait_for_timeout(800)

    return downloaded_paths

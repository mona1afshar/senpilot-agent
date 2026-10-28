from models import ScrapeResult

_SINGULAR = {
    "Exhibits": "Exhibit",
    "Key Documents": "Key Document",
    "Other Documents": "Other Document",
    "Transcripts": "Transcript",
    "Recordings": "Recording",
}


def _count_phrase(doc_type: str, count: int) -> str:
    if count == 0:
        return f"no {doc_type}"
    if count == 1:
        return f"1 {_SINGULAR[doc_type]}"
    return f"{count} {doc_type}"


def build_reply_body(matter_number: str, result: ScrapeResult) -> str:
    m = result.metadata

    relates_to = ""
    if m.category and m.type:
        relates_to = f" It relates to {m.category} within the {m.type} category."
    elif m.category or m.type:
        relates_to = f" It relates to {m.category or m.type}."

    filing_line = ""
    if m.initial_filing_date or m.final_filing_date:
        filing_line = (
            f"The matter had an initial filing on {m.initial_filing_date or 'an unknown date'} "
            f"and a final filing on {m.final_filing_date or 'an unknown date'}. "
        )

    phrases = [_count_phrase(dt, result.counts_by_type.get(dt, 0)) for dt in result.counts_by_type]
    counts_line = "I found " + ", ".join(phrases[:-1])
    if len(phrases) > 1:
        counts_line += f", and {phrases[-1]}."
    else:
        counts_line += "."

    requested_count = result.counts_by_type.get(result.requested_doc_type, 0)
    downloaded_count = len(result.downloaded_files)
    download_line = (
        f"I downloaded {downloaded_count} out of the {requested_count} "
        f"{result.requested_doc_type} and am attaching them as a ZIP here."
    )

    lines = [
        "Hi,",
        "",
        f"{matter_number} is about the {m.title or 'details unavailable'}.{relates_to}",
        filing_line + counts_line,
        download_line,
    ]
    return "\n".join(line for line in lines if line)

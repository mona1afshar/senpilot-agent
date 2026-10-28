import re

from config import DOC_TYPES

MATTER_NUMBER_RE = re.compile(r"\bM\d{4,6}\b", re.IGNORECASE)

# Maps loose phrasing in the email body to the canonical doc type label.
DOC_TYPE_ALIASES = {
    "exhibit": "Exhibits",
    "exhibits": "Exhibits",
    "key document": "Key Documents",
    "key documents": "Key Documents",
    "other document": "Other Documents",
    "other documents": "Other Documents",
    "other docs": "Other Documents",
    "transcript": "Transcripts",
    "transcripts": "Transcripts",
    "recording": "Recordings",
    "recordings": "Recordings",
}


class UnparseableRequest(Exception):
    pass


def parse_request_text(subject: str, body: str) -> tuple[str, str]:
    """Extract (matter_number, doc_type) from an inbound email's subject+body.

    Raises UnparseableRequest if either field can't be confidently identified.
    """
    text = f"{subject}\n{body}"

    matter_match = MATTER_NUMBER_RE.search(text)
    if not matter_match:
        raise UnparseableRequest("No matter number (e.g. M12205) found in the email.")
    matter_number = matter_match.group(0).upper()

    lowered = text.lower()
    doc_type = None
    # Sort aliases longest-first so "other documents" matches before a bare "document" would.
    for alias in sorted(DOC_TYPE_ALIASES, key=len, reverse=True):
        if alias in lowered:
            doc_type = DOC_TYPE_ALIASES[alias]
            break

    if doc_type is None:
        raise UnparseableRequest(
            f"No recognizable document type found. Expected one of: {', '.join(DOC_TYPES)}"
        )

    return matter_number, doc_type

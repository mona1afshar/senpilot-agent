from dataclasses import dataclass, field


@dataclass
class MatterRequest:
    from_address: str
    message_id: str
    matter_number: str
    doc_type: str  # one of config.DOC_TYPES


@dataclass
class MatterMetadata:
    title: str | None = None  # e.g. "Halifax Regional Water Commission - Windsor Street Exchange Redevelopment Project - $69,275,000"
    type: str | None = None  # e.g. "Water"
    category: str | None = None  # e.g. "Capital Expenditure"
    status: str | None = None  # e.g. "Closed"
    outcome: str | None = None  # e.g. "Directions given"
    initial_filing_date: str | None = None
    final_filing_date: str | None = None


@dataclass
class ScrapeResult:
    metadata: MatterMetadata
    counts_by_type: dict[str, int] = field(default_factory=dict)
    downloaded_files: list[str] = field(default_factory=list)
    requested_doc_type: str = ""

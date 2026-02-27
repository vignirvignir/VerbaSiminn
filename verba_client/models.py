"""Data models for Verba API responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


def _parse_dt(value: str | None) -> datetime | None:
    """Parse a Verba datetime string into a datetime object."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


@dataclass
class CallRecord:
    """Represents a single call/CDR record from the Verba API."""

    ccdr_id: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration: str = ""
    source_caller_id: str = ""
    source_name: str = ""
    source_ip: str = ""
    destination_caller_id: str = ""
    destination_name: str = ""
    destination_ip: str = ""
    direction: str = ""
    cause: str = ""
    location: str = ""
    audio_codec: str = ""
    state: str = ""
    ondemand: bool = False
    secondary: bool = False
    meeting_id: str = ""
    url: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_xml_element(cls, elem) -> CallRecord:
        """Build a CallRecord from an XML element (verbacdr or similar)."""

        def text(tag: str) -> str:
            child = elem.find(tag)
            return child.text.strip() if child is not None and child.text else ""

        return cls(
            ccdr_id=text("ccdr_id"),
            start_time=_parse_dt(
                text("start_time") or text("starttime") or text("startdate")
            ),
            end_time=_parse_dt(text("end_time") or text("endtime") or text("enddate")),
            duration=text("duration"),
            source_caller_id=text("source_caller_id"),
            source_name=text("source_name"),
            source_ip=text("source_ip"),
            destination_caller_id=text("destination_caller_id"),
            destination_name=text("destination_name"),
            destination_ip=text("destination_ip"),
            direction=text("userdirection") or text("defdirection"),
            cause=text("usercause") or text("defcause"),
            location=text("location"),
            audio_codec=text("audio_codec"),
            state=elem.get("state", ""),
            ondemand=text("ondemand").lower() == "true",
            secondary=text("secondary").lower() == "true",
            meeting_id=text("meeting_id"),
            url=text("url"),
            raw={child.tag: (child.text or "").strip() for child in elem},
        )


@dataclass
class SearchResult:
    """Result container for SearchCalls responses.

    Attributes:
        row_count: Number of rows in this page of results (from
            the ``rowcount`` XML attribute).  This is the page
            size, **not** the total number of matching records.
        calls: Parsed CallRecord objects from this page.
    """

    row_count: int
    calls: list[CallRecord]

"""Gazette notification extraction (Docs/Backend.md §6).

Two paths, in this order:

  1. **Regex templates** — the offline default. Gazette notifications under NH Act
     1956 (3A/3D) and RFCTLARR 2013 (s.11/s.19) follow fixed phrasing: an S.O.
     number, a place-and-date dateline, "in exercise of the powers conferred by
     sub-section (1) of section <N> of the <Act>", a competent-authority line and a
     SCHEDULE table of village / tehsil / survey numbers / area.
  2. **LLM refinement** — attempted ONLY when `settings.LLM_EXTRACTION_URL` is
     non-empty. With no endpoint configured the pipeline is regex-only, which is
     what the offline demo laptop runs.

Nothing here writes to the ledger. The output is a *proposal*: fields, per-field
confidence, source spans, and a `proposed_event` an officer must confirm through
`POST /cases/{id}/events` (Docs/rules.md C4).

Confidence convention (fixed by the build contract):
    regex hit          -> 0.95
    fuzzy / derived     -> 0.70
    absent              -> None
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from app.core.config import settings

log = logging.getLogger(__name__)

CONF_REGEX = 0.95
CONF_DERIVED = 0.70

# Dash characters that show up where a gazette prints an em dash. Real e-Gazette
# PDFs (and reportlab's base-14 Times) frequently hand back U+FFFD here, so the
# text is normalised before matching rather than every pattern carrying the noise.
_DASHES = "—–‒‐�"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))


# --- statute / section templates ---------------------------------------------------

# (statute, section, event_type, pattern)
SECTION_TEMPLATES: list[tuple[str, str, str, re.Pattern]] = [
    (
        "NH_ACT_1956", "3A", "NOTIFICATION_3A",
        re.compile(
            r"section\s*3\s*[-\s]?A\b[^.;]{0,80}?National\s+Highways\s+Act",
            re.I | re.S),
    ),
    (
        "NH_ACT_1956", "3D", "DECLARATION_3D",
        re.compile(
            r"section\s*3\s*[-\s]?D\b[^.;]{0,80}?National\s+Highways\s+Act",
            re.I | re.S),
    ),
    (
        "RFCTLARR_2013", "11", "PRELIM_NOTIFICATION_S11",
        re.compile(
            r"powers\s+conferred\s+by\s+sub-?section\s*\(\s*1\s*\)\s+of\s+section\s*11\b",
            re.I | re.S),
    ),
    (
        "RFCTLARR_2013", "19", "DECLARATION_S19",
        re.compile(
            r"powers\s+conferred\s+by\s+sub-?section\s*\(\s*1\s*\)\s+of\s+section\s*19\b",
            re.I | re.S),
    ),
]

# Weaker corroboration used when the primary template misses (derived confidence).
FALLBACK_TEMPLATES: list[tuple[str, str, str, re.Pattern]] = [
    ("NH_ACT_1956", "3A", "NOTIFICATION_3A",
     re.compile(r"declares?\s+its\s+intention\s+to\s+acquire", re.I)),
    ("NH_ACT_1956", "3D", "DECLARATION_3D",
     re.compile(r"shall\s+vest\s+absolutely\s+in\s+the\s+Central\s+Government", re.I)),
    ("RFCTLARR_2013", "11", "PRELIM_NOTIFICATION_S11",
     re.compile(r"preliminary\s+notification", re.I)),
    ("RFCTLARR_2013", "19", "DECLARATION_S19",
     re.compile(r"summary\s+of\s+the\s+Rehabilitation\s+and\s+Resettlement\s+Scheme", re.I)),
]

RFCTLARR_ACT_RE = re.compile(
    r"Right\s+to\s+Fair\s+Compensation\s+and\s+Transparency\s+in\s+Land\s+Acquisition",
    re.I | re.S)
NH_ACT_RE = re.compile(r"National\s+Highways\s+Act,?\s*1956", re.I)

# --- scalar field templates --------------------------------------------------------

RE_GAZETTE_SO = re.compile(r"\bS\.?\s?O\.?\s*(\d{1,6})\s*\(\s*E\s*\)", re.I)
RE_GAZETTE_NO = re.compile(
    r"\bNotification\s+No\.?\s*([A-Z0-9][A-Z0-9/\-.]{2,40})", re.I)

# The gazette dateline: "New Delhi, the 27th September, 2025" / "Bhopal, the 20th ..."
RE_DATELINE = re.compile(
    rf"^[ \t]*([A-Z][A-Za-z .]{{2,30}}),\s*the\s+(\d{{1,2}})\s*(?:st|nd|rd|th)?\s+"
    rf"({_MONTH_ALT})\.?,?\s+(\d{{4}})",
    re.I | re.M)
# Masthead line: "No. 4211] NEW DELHI, SATURDAY, SEPTEMBER 27, 2025"
RE_HEADER_DATE = re.compile(
    rf"({_MONTH_ALT})\s+(\d{{1,2}}),\s*(\d{{4}})", re.I)
# "dated the 27th September, 2025" — used for the PRIOR notification reference only.
RE_DATED_THE = re.compile(
    rf"dated\s+the\s+(\d{{1,2}})\s*(?:st|nd|rd|th)?\s+({_MONTH_ALT})\.?,?\s+(\d{{4}})",
    re.I)
RE_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")

RE_STATE = re.compile(r"\bState\s*[:\-]\s*([A-Za-z][A-Za-z .&'()-]{2,40}?)(?=\s{2,}|\s+District\b|$)",
                      re.I | re.M)
RE_DISTRICT = re.compile(r"\bDistrict\s*[:\-]\s*([A-Za-z][A-Za-z .&'()-]{2,40}?)\s*$",
                         re.I | re.M)
RE_COMPETENT = re.compile(
    r"Competent\s+Authority\s*(?:\(\s*Land\s+Acquisition\s*\))?\s*[:\-]\s*(.+?)\s*$",
    re.I | re.M)
RE_TOTAL_AREA = re.compile(
    r"\bTotal\s+area\s*[:\-]?\s*([\d,]+(?:\.\d{1,4})?)\s*(?:hect|ha\b)", re.I)

# --- schedule table templates ------------------------------------------------------

RE_SCHEDULE_HEAD = re.compile(r"^\s*S\s?C\s?H\s?E\s?D\s?U\s?L\s?E\s*$", re.I | re.M)
# "1 Adegaon Seoni 112/1, 112/2, 118 7.2100"  (serial · names · survey nos · area)
RE_ROW = re.compile(r"^\s*(\d{1,3})[.)]?\s+(?P<rest>\S.*?)\s+(?P<area>\d{1,6}(?:\.\d{1,4})?)\s*$")
# The survey-number block sitting immediately before the area column.
RE_SURVEY_TAIL = re.compile(
    r"(?P<survey>\d+[A-Za-z]?(?:\s*/\s*\d+[A-Za-z]?)*"
    r"(?:\s*,\s*\d+[A-Za-z]?(?:\s*/\s*\d+[A-Za-z]?)*)*)\s*$")
RE_SURVEY_SPLIT = re.compile(r"\s*,\s*")

EVENT_FOR_SECTION = {
    ("NH_ACT_1956", "3A"): "NOTIFICATION_3A",
    ("NH_ACT_1956", "3D"): "DECLARATION_3D",
    ("RFCTLARR_2013", "11"): "PRELIM_NOTIFICATION_S11",
    ("RFCTLARR_2013", "19"): "DECLARATION_S19",
}


# --- result container --------------------------------------------------------------


@dataclass
class ExtractionResult:
    fields: dict = field(default_factory=dict)
    confidence: dict = field(default_factory=dict)
    source_spans: dict = field(default_factory=dict)
    proposed_event: dict | None = None
    engine: str = "regex"
    pages: int = 0
    ocr: bool = False
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "fields": self.fields,
            "confidence": self.confidence,
            "source_spans": self.source_spans,
            "proposed_event": self.proposed_event,
            "engine": self.engine,
            "pages": self.pages,
            "ocr": self.ocr,
            "warnings": self.warnings,
        }


# --- text layer --------------------------------------------------------------------


def normalise(text: str) -> str:
    """Fold the dash zoo (and NBSP) to plain ASCII-ish so one pattern set suffices."""
    for ch in _DASHES:
        text = text.replace(ch, "—")
    return text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")


def page_texts(data: bytes) -> list[str]:
    """Text layer per page via pdfplumber. Returns [] when the PDF has no text
    layer (scanned) — OCR is a worker concern and out of scope for the MVP."""
    import pdfplumber

    out: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            out.append(normalise(page.extract_text() or ""))
    return out


# --- matching helpers --------------------------------------------------------------


def _find(pages: list[str], pattern: re.Pattern) -> tuple[int, re.Match] | None:
    """First match across pages, in page order. Returns (page_number_1based, match)."""
    for i, text in enumerate(pages):
        m = pattern.search(text)
        if m:
            return i + 1, m
    return None


def _span(page_no: int, m: re.Match, group: int | str = 0) -> dict:
    return {"page": page_no, "start": m.start(group), "end": m.end(group)}


def _set(res: ExtractionResult, key: str, value, conf: float | None,
         span: dict | None = None) -> None:
    res.fields[key] = value
    res.confidence[key] = conf if value is not None else None
    if span is not None and value is not None:
        res.source_spans[key] = span


def _iso(day: int, month: int, year: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


# --- individual field extractors ---------------------------------------------------


def _extract_statute_section(pages: list[str], res: ExtractionResult) -> tuple[str | None, str | None]:
    for statute, section, _event, pattern in SECTION_TEMPLATES:
        hit = _find(pages, pattern)
        if hit:
            page_no, m = hit
            _set(res, "statute", statute, CONF_REGEX, _span(page_no, m))
            _set(res, "section", section, CONF_REGEX, _span(page_no, m))
            return statute, section

    # Nothing matched the primary phrasing — corroborate from the Act name plus a
    # weaker cue, and mark the result derived.
    act = None
    if _find(pages, RFCTLARR_ACT_RE):
        act = "RFCTLARR_2013"
    elif _find(pages, NH_ACT_RE):
        act = "NH_ACT_1956"
    for statute, section, _event, pattern in FALLBACK_TEMPLATES:
        if act and statute != act:
            continue
        hit = _find(pages, pattern)
        if hit:
            page_no, m = hit
            _set(res, "statute", statute, CONF_DERIVED, _span(page_no, m))
            _set(res, "section", section, CONF_DERIVED, _span(page_no, m))
            res.warnings.append(
                "statute/section inferred from secondary phrasing; confirm before commit")
            return statute, section

    _set(res, "statute", act, CONF_DERIVED if act else None)
    _set(res, "section", None, None)
    if act is None:
        res.warnings.append("no statute template matched this document")
    return act, None


def _extract_gazette_no(pages: list[str], res: ExtractionResult) -> None:
    hit = _find(pages, RE_GAZETTE_SO)
    if hit:
        page_no, m = hit
        _set(res, "gazette_no", f"S.O. {m.group(1)}(E)", CONF_REGEX, _span(page_no, m))
        return
    hit = _find(pages, RE_GAZETTE_NO)
    if hit:
        page_no, m = hit
        _set(res, "gazette_no", m.group(1).strip(), CONF_DERIVED, _span(page_no, m))
        return
    _set(res, "gazette_no", None, None)


def _extract_publication_date(pages: list[str], res: ExtractionResult) -> None:
    """Prefer the dateline of THIS notification ("New Delhi, the 28th August, 2026")
    over any "dated the ..." reference, which in a 3D/s.19 points at the PRIOR
    notification and would silently backdate the clock."""
    hit = _find(pages, RE_DATELINE)
    if hit:
        page_no, m = hit
        iso = _iso(int(m.group(2)), MONTHS[m.group(3).lower()], int(m.group(4)))
        if iso:
            _set(res, "publication_date", iso, CONF_REGEX, _span(page_no, m))
            _set(res, "publication_place", m.group(1).strip(), CONF_REGEX,
                 _span(page_no, m, 1))
            return

    hit = _find(pages, RE_HEADER_DATE)  # masthead "SEPTEMBER 27, 2025"
    if hit:
        page_no, m = hit
        iso = _iso(int(m.group(2)), MONTHS[m.group(1).lower()], int(m.group(3)))
        if iso:
            _set(res, "publication_date", iso, CONF_DERIVED, _span(page_no, m))
            res.warnings.append("publication_date read from masthead, not the dateline")
            return

    hit = _find(pages, RE_NUMERIC_DATE)
    if hit:
        page_no, m = hit
        iso = _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            _set(res, "publication_date", iso, CONF_DERIVED, _span(page_no, m))
            return
    _set(res, "publication_date", None, None)


def _extract_prior_reference(pages: list[str], res: ExtractionResult) -> None:
    """3D / s.19 recite the notification they follow. Useful for linking, never
    for dating this document."""
    hit = _find(pages, RE_DATED_THE)
    if not hit:
        _set(res, "prior_notification_date", None, None)
        _set(res, "prior_gazette_no", None, None)
        return
    page_no, m = hit
    iso = _iso(int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3)))
    _set(res, "prior_notification_date", iso, CONF_DERIVED, _span(page_no, m))

    # The S.O. immediately preceding "dated the ..." on the same page.
    text = pages[page_no - 1]
    prior = None
    prior_m = None
    for so in RE_GAZETTE_SO.finditer(text[: m.start()]):
        prior, prior_m = f"S.O. {so.group(1)}(E)", so
    if prior and prior != res.fields.get("gazette_no"):
        _set(res, "prior_gazette_no", prior, CONF_DERIVED, _span(page_no, prior_m))
    else:
        _set(res, "prior_gazette_no", None, None)


def _extract_jurisdiction(pages: list[str], res: ExtractionResult) -> None:
    hit = _find(pages, RE_STATE)
    if hit:
        page_no, m = hit
        _set(res, "state", m.group(1).strip(), CONF_REGEX, _span(page_no, m, 1))
    else:
        _set(res, "state", None, None)

    hit = _find(pages, RE_DISTRICT)
    if hit:
        page_no, m = hit
        _set(res, "district", m.group(1).strip(), CONF_REGEX, _span(page_no, m, 1))
    else:
        _set(res, "district", None, None)

    hit = _find(pages, RE_COMPETENT)
    if hit:
        page_no, m = hit
        _set(res, "competent_authority", m.group(1).strip(), CONF_REGEX,
             _span(page_no, m, 1))
    else:
        _set(res, "competent_authority", None, None)


def _parse_schedule_row(line: str) -> dict | None:
    """Parse one SCHEDULE row right-to-left: area, then the survey-number block,
    then the remaining words as village (+ trailing tehsil)."""
    m = RE_ROW.match(line)
    if not m:
        return None
    area = m.group("area")
    rest = m.group("rest")
    sm = RE_SURVEY_TAIL.search(rest)
    if not sm:
        return None
    survey_nos = [s for s in RE_SURVEY_SPLIT.split(sm.group("survey").strip()) if s]
    survey_nos = [re.sub(r"\s*/\s*", "/", s) for s in survey_nos]
    names = rest[: sm.start()].strip().split()
    if not names:
        return None
    if len(names) == 1:
        village, tehsil = names[0], None
    else:
        village, tehsil = " ".join(names[:-1]), names[-1]
    return {
        "name": village,
        "tehsil": tehsil,
        "survey_nos": survey_nos,
        "area_ha": f"{float(area):.4f}",
    }


def _extract_villages(pages: list[str], res: ExtractionResult) -> None:
    villages: list[dict] = []
    for page_index, text in enumerate(pages):
        head = RE_SCHEDULE_HEAD.search(text)
        start = head.end() if head else 0
        offset = start
        for line in text[start:].split("\n"):
            row = _parse_schedule_row(line)
            line_len = len(line) + 1
            if row:
                idx = len(villages)
                villages.append(row)
                lead = len(line) - len(line.lstrip())
                res.source_spans[f"villages[{idx}]"] = {
                    "page": page_index + 1,
                    "start": offset + lead,
                    "end": offset + len(line),
                }
                res.confidence[f"villages[{idx}].area_ha"] = CONF_REGEX
                if row["tehsil"] is None:
                    res.confidence[f"villages[{idx}].tehsil"] = None
            offset += line_len
        if villages:
            break  # the schedule lives on one page in every template we ship

    _set(res, "villages", villages, CONF_REGEX if villages else None)
    if not villages:
        res.warnings.append("no SCHEDULE rows matched; villages must be entered by hand")


def _extract_total_area(pages: list[str], res: ExtractionResult) -> None:
    hit = _find(pages, RE_TOTAL_AREA)
    if hit:
        page_no, m = hit
        value = f"{float(m.group(1).replace(',', '')):.4f}"
        _set(res, "total_area_ha", value, CONF_REGEX, _span(page_no, m, 1))
        return
    villages = res.fields.get("villages") or []
    if villages:
        total = sum(float(v["area_ha"]) for v in villages)
        _set(res, "total_area_ha", f"{total:.4f}", CONF_DERIVED)
        res.warnings.append("total_area_ha summed from the schedule rows")
        return
    _set(res, "total_area_ha", None, None)


# --- proposed event ----------------------------------------------------------------


def build_proposed_event(fields: dict) -> dict | None:
    """Map the extracted section onto the ledger event an officer would confirm.
    Returns None when the section is unknown — nothing is ever proposed on a guess."""
    statute, section = fields.get("statute"), fields.get("section")
    event_type = EVENT_FOR_SECTION.get((statute, section))
    if not event_type:
        return None
    payload = {
        "gazette_no": fields.get("gazette_no"),
        "total_area_ha": fields.get("total_area_ha"),
        "villages": fields.get("villages") or [],
        "state": fields.get("state"),
        "district": fields.get("district"),
        "competent_authority": fields.get("competent_authority"),
        "source": "extraction",
    }
    if fields.get("prior_gazette_no"):
        payload["prior_gazette_no"] = fields["prior_gazette_no"]
    return {
        "type": event_type,
        "occurred_at": fields.get("publication_date"),
        "payload": {k: v for k, v in payload.items() if v not in (None, [], "")},
    }


# --- LLM path (optional) -----------------------------------------------------------

LLM_SYSTEM_PROMPT = (
    "Extract fields for the schema; return null when a field is absent; never infer. "
    "Return strict JSON with keys: statute, section, gazette_no, publication_date, "
    "state, district, villages[{name,tehsil,survey_nos[],area_ha}], total_area_ha, "
    "competent_authority, confidence{field: 0..1}."
)


def _llm_refine(pages: list[str], res: ExtractionResult) -> None:
    """Fill fields the regex templates could not read. Only reached when
    LLM_EXTRACTION_URL is configured; any failure leaves the regex result intact."""
    url = settings.LLM_EXTRACTION_URL
    if not url:
        return
    try:
        import httpx

        payload = {
            "system": LLM_SYSTEM_PROMPT,
            "text": "\n\n".join(pages)[:60_000],
            "known_fields": res.fields,
        }
        resp = httpx.post(url, json=payload, timeout=45.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.exception("extraction: LLM path failed; keeping regex result")
        res.warnings.append("LLM refinement unavailable; regex result kept")
        return

    got = data.get("fields", data) or {}
    conf = data.get("confidence", got.get("confidence", {})) or {}
    filled = []
    for key, value in got.items():
        if key == "confidence" or value in (None, "", []):
            continue
        if res.fields.get(key) in (None, "", []):
            res.fields[key] = value
            res.confidence[key] = float(conf.get(key, CONF_DERIVED))
            filled.append(key)
    if filled:
        res.engine = "regex+llm"
        res.warnings.append(f"LLM filled: {', '.join(sorted(filled))}")


# --- entry points ------------------------------------------------------------------


def extract_from_pages(pages: list[str]) -> ExtractionResult:
    """Run the template set over an already-extracted text layer (unit-testable)."""
    res = ExtractionResult(pages=len(pages))
    if not any(p.strip() for p in pages):
        res.ocr = True
        res.warnings.append("no text layer; OCR required (not enabled in the MVP)")
        return res
    _extract_statute_section(pages, res)
    _extract_gazette_no(pages, res)
    _extract_publication_date(pages, res)
    _extract_prior_reference(pages, res)
    _extract_jurisdiction(pages, res)
    _extract_villages(pages, res)
    _extract_total_area(pages, res)
    _llm_refine(pages, res)
    res.proposed_event = build_proposed_event(res.fields)
    return res


def extract_from_bytes(data: bytes) -> ExtractionResult:
    """Full pipeline from raw PDF bytes."""
    try:
        pages = page_texts(data)
    except Exception:
        log.exception("extraction: failed to read the PDF text layer")
        res = ExtractionResult()
        res.warnings.append("document could not be parsed as PDF")
        return res
    return extract_from_pages(pages)


def extract_document(db, doc) -> dict:
    """Run extraction for a stored document and persist the proposal on the row.

    Synchronous by design: the regex path is milliseconds, and a demo laptop has no
    worker. Status becomes `proposed` on success, stays `pending` when nothing
    usable came out. Does not commit; the caller owns the transaction.
    """
    from app.domain.documents.storage import document_bytes

    data = document_bytes(doc)
    result = extract_from_bytes(data)
    doc.extraction = result.as_dict()
    doc.extraction_status = "proposed" if result.proposed_event else "pending"
    if result.pages and not doc.pages:
        doc.pages = result.pages
    db.add(doc)
    return doc.extraction

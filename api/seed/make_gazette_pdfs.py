"""Generate realistic gazette notification PDFs for the demo (reportlab).

These are SYNTHETIC reproductions of the real e-Gazette layout and phrasing — the
same wording the regex templates in `app.domain.documents.extraction` key on:

  * NH Act 1956 s.3A  — "declares its intention to acquire"
  * NH Act 1956 s.3D  — "declares that the land ... shall be acquired"
  * RFCTLARR 2013 s.11 — preliminary notification
  * RFCTLARR 2013 s.19 — declaration + summary of R&R scheme

Every notification carries the standard gazette dateline ("New Delhi, the 27th
September, 2025"), an S.O. number, a competent-authority line and a SCHEDULE table
of village / tehsil / survey numbers / area. The demo uploads the 3A and 3D files.

Public helpers (used by seed/seed_demo.py):
    make_3a_pdf(path) -> Path
    make_3d_pdf(path) -> Path
Extras used by the extraction smoke test:
    make_s11_pdf(path) -> Path
    make_s19_pdf(path) -> Path
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# --- shared demo geography (matches seed_demo.py case LAQ/SEO/2025/01) -------------

SEONI_SCHEDULE = [
    # (village, tehsil, survey numbers, area in hectares)
    ("Adegaon", "Seoni", "112/1, 112/2, 118", "7.2100"),
    ("Bhoma", "Seoni", "57, 58/2", "6.0300"),
    ("Chhapara", "Chhapara", "203/1", "5.4000"),
]
SEONI_TOTAL = "18.6400"

KIRNAPUR_SCHEDULE = [
    ("Kirnapur", "Kirnapur", "77/2, 81", "9.4000"),
    ("Lalbarra", "Lalbarra", "128, 129/1", "4.1500"),
]
KIRNAPUR_TOTAL = "13.5500"


# --- styles -----------------------------------------------------------------------


def _styles() -> dict:
    ss = getSampleStyleSheet()
    return {
        "masthead": ParagraphStyle(
            "masthead", parent=ss["Normal"], fontName="Times-Bold", fontSize=15,
            leading=18, alignment=TA_CENTER, spaceAfter=2,
        ),
        "sub": ParagraphStyle(
            "sub", parent=ss["Normal"], fontName="Times-Bold", fontSize=11,
            leading=14, alignment=TA_CENTER,
        ),
        "small": ParagraphStyle(
            "small", parent=ss["Normal"], fontName="Times-Roman", fontSize=9,
            leading=12, alignment=TA_CENTER,
        ),
        "dept": ParagraphStyle(
            "dept", parent=ss["Normal"], fontName="Times-Bold", fontSize=11,
            leading=14, alignment=TA_CENTER, spaceBefore=8,
        ),
        "body": ParagraphStyle(
            "body", parent=ss["Normal"], fontName="Times-Roman", fontSize=10,
            leading=14, alignment=TA_JUSTIFY, spaceAfter=6, firstLineIndent=14,
        ),
        "plain": ParagraphStyle(
            "plain", parent=ss["Normal"], fontName="Times-Roman", fontSize=10,
            leading=14, spaceAfter=4,
        ),
        "right": ParagraphStyle(
            "right", parent=ss["Normal"], fontName="Times-Roman", fontSize=10,
            leading=14, alignment=2, spaceBefore=8,
        ),
    }


def _masthead(st: dict, issue_no: str, dateline_header: str) -> list:
    return [
        Paragraph("THE GAZETTE OF INDIA", st["masthead"]),
        Paragraph("EXTRAORDINARY", st["sub"]),
        Paragraph("PART II&mdash;Section 3&mdash;Sub-section (ii)", st["small"]),
        Paragraph("PUBLISHED BY AUTHORITY", st["small"]),
        Spacer(1, 4),
        HRFlowable(width="100%", thickness=0.8, color=colors.black),
        Paragraph(f"No. {issue_no}]&nbsp;&nbsp;&nbsp;&nbsp;{dateline_header}",
                  st["small"]),
        HRFlowable(width="100%", thickness=0.8, color=colors.black),
    ]


def _schedule_table(st: dict, state: str, district: str, rows, total: str) -> list:
    data = [["Sl. No.", "Village", "Tehsil", "Survey / Khasra Nos.", "Area (Ha.)"]]
    for i, (village, tehsil, survey, area) in enumerate(rows, start=1):
        data.append([str(i), village, tehsil, survey, area])
    tbl = Table(data, colWidths=[16 * mm, 32 * mm, 28 * mm, 58 * mm, 26 * mm],
                hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (4, 0), (4, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [
        Spacer(1, 8),
        Paragraph("SCHEDULE", st["sub"]),
        Spacer(1, 4),
        Paragraph(f"State: {state}    District: {district}", st["plain"]),
        Spacer(1, 3),
        tbl,
        Spacer(1, 4),
        Paragraph(f"Total area: {total} hectares", st["plain"]),
    ]


def _build(path: Path, flow: list) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=path.stem, author="Government of India (synthetic demo copy)",
    )
    doc.build(flow)
    return path


# --- NH Act 1956 -------------------------------------------------------------------


def make_3a_pdf(
    path: str | Path,
    *,
    gazette_no: str = "S.O. 4211(E)",
    date_text: str = "27th September, 2025",
    header_date: str = "NEW DELHI, SATURDAY, SEPTEMBER 27, 2025",
    issue_no: str = "4211",
    nh_no: str = "44",
    stretch: str = "Lakhnadon to Seoni (Package II)",
    state: str = "Madhya Pradesh",
    district: str = "Seoni",
    schedule=SEONI_SCHEDULE,
    total: str = SEONI_TOTAL,
    competent_authority: str = "Shri A. Verma, Sub-Divisional Officer (Revenue), Seoni",
) -> Path:
    """NH Act 1956 s.3A — notification of intention to acquire."""
    st = _styles()
    flow = _masthead(st, issue_no, header_date)
    flow += [
        Paragraph("MINISTRY OF ROAD TRANSPORT AND HIGHWAYS", st["dept"]),
        Paragraph("NOTIFICATION", st["sub"]),
        Paragraph(f"New Delhi, the {date_text}", st["small"]),
        Spacer(1, 8),
        Paragraph(
            f"<b>{gazette_no}</b>&mdash;Whereas the Central Government is satisfied that "
            f"for a public purpose, namely, for the building, maintenance, management and "
            f"operation of National Highway No. {nh_no} in the stretch {stretch}, the land "
            f"specified in the Schedule annexed hereto is required to be acquired;",
            st["body"]),
        Paragraph(
            "Now, therefore, in exercise of the powers conferred by sub-section (1) of "
            "section 3A of the National Highways Act, 1956 (48 of 1956), the Central "
            "Government hereby declares its intention to acquire the said land.",
            st["body"]),
        Paragraph(
            "Any person interested in the land may, within twenty-one days from the date "
            "of publication of this notification in the Official Gazette, object in "
            "writing to the use of the land for the purpose mentioned above, to the "
            "Competent Authority (Land Acquisition) named below.",
            st["body"]),
        Paragraph(
            f"Competent Authority (Land Acquisition): {competent_authority}",
            st["plain"]),
    ]
    flow += _schedule_table(st, state, district, schedule, total)
    flow += [Paragraph("[F. No. RW/NH-33044/2025/MP]", st["right"])]
    return _build(path, flow)


def make_3d_pdf(
    path: str | Path,
    *,
    gazette_no: str = "S.O. 3902(E)",
    date_text: str = "28th August, 2026",
    header_date: str = "NEW DELHI, FRIDAY, AUGUST 28, 2026",
    issue_no: str = "3902",
    prior_gazette_no: str = "S.O. 4211(E)",
    prior_date_text: str = "27th September, 2025",
    nh_no: str = "44",
    state: str = "Madhya Pradesh",
    district: str = "Seoni",
    schedule=SEONI_SCHEDULE,
    total: str = SEONI_TOTAL,
    competent_authority: str = "Shri A. Verma, Sub-Divisional Officer (Revenue), Seoni",
) -> Path:
    """NH Act 1956 s.3D — declaration of acquisition (land vests in Central Govt., 3D(2))."""
    st = _styles()
    flow = _masthead(st, issue_no, header_date)
    flow += [
        Paragraph("MINISTRY OF ROAD TRANSPORT AND HIGHWAYS", st["dept"]),
        Paragraph("NOTIFICATION", st["sub"]),
        Paragraph(f"New Delhi, the {date_text}", st["small"]),
        Spacer(1, 8),
        Paragraph(
            f"<b>{gazette_no}</b>&mdash;Whereas by the notification of the Government of "
            f"India in the Ministry of Road Transport and Highways number {prior_gazette_no} "
            f"dated the {prior_date_text}, published in the Gazette of India, Extraordinary, "
            f"Part II, Section 3, Sub-section (ii), the Central Government declared its "
            f"intention to acquire the land specified therein for the building of National "
            f"Highway No. {nh_no};",
            st["body"]),
        Paragraph(
            "And whereas the Competent Authority has, after considering the objections "
            "received under section 3C of the said Act, submitted its report to the Central "
            "Government;",
            st["body"]),
        Paragraph(
            "Now, therefore, in exercise of the powers conferred by sub-section (1) of "
            "section 3D of the National Highways Act, 1956 (48 of 1956), the Central "
            "Government hereby declares that the land specified in the Schedule annexed "
            "hereto shall be acquired for the aforesaid purpose, and on publication of "
            "this declaration the said land shall vest absolutely in the Central "
            "Government free from all encumbrances.",
            st["body"]),
        Paragraph(
            f"Competent Authority (Land Acquisition): {competent_authority}",
            st["plain"]),
    ]
    flow += _schedule_table(st, state, district, schedule, total)
    flow += [Paragraph("[F. No. RW/NH-33044/2025/MP]", st["right"])]
    return _build(path, flow)


# --- RFCTLARR 2013 -----------------------------------------------------------------


def make_s11_pdf(
    path: str | Path,
    *,
    gazette_no: str = "S.O. 812(E)",
    date_text: str = "20th October, 2025",
    header_date: str = "BHOPAL, MONDAY, OCTOBER 20, 2025",
    issue_no: str = "812",
    purpose: str = "the Seoni-Balaghat 220 kV Transmission Line",
    state: str = "Madhya Pradesh",
    district: str = "Balaghat",
    schedule=KIRNAPUR_SCHEDULE,
    total: str = KIRNAPUR_TOTAL,
    competent_authority: str = "Shri K. Meshram, Land Acquisition Officer, Balaghat",
) -> Path:
    """RFCTLARR 2013 s.11 — preliminary notification."""
    st = _styles()
    flow = _masthead(st, issue_no, header_date)
    flow += [
        Paragraph("REVENUE DEPARTMENT, GOVERNMENT OF MADHYA PRADESH", st["dept"]),
        Paragraph("NOTIFICATION", st["sub"]),
        Paragraph(f"Bhopal, the {date_text}", st["small"]),
        Spacer(1, 8),
        Paragraph(
            f"<b>{gazette_no}</b>&mdash;Whereas it appears to the appropriate Government "
            f"that the land specified in the Schedule annexed hereto is required for a "
            f"public purpose, namely {purpose};",
            st["body"]),
        Paragraph(
            "And whereas the Social Impact Assessment study under section 4 has been "
            "completed, the report published under section 6 and the recommendations of "
            "the Expert Group under section 7 considered by the appropriate Government "
            "under section 8;",
            st["body"]),
        Paragraph(
            "Now, therefore, in exercise of the powers conferred by sub-section (1) of "
            "section 11 of the Right to Fair Compensation and Transparency in Land "
            "Acquisition, Rehabilitation and Resettlement Act, 2013 (30 of 2013), the "
            "appropriate Government hereby notifies its intention to acquire the said land.",
            st["body"]),
        Paragraph(
            "Any person interested in the land may, within sixty days from the date of "
            "publication of this preliminary notification, object under section 15 of the "
            "said Act before the Collector.",
            st["body"]),
        Paragraph(
            f"Competent Authority (Land Acquisition): {competent_authority}",
            st["plain"]),
    ]
    flow += _schedule_table(st, state, district, schedule, total)
    flow += [Paragraph("[No. F 4-27/2025/Seven/2-A]", st["right"])]
    return _build(path, flow)


def make_s19_pdf(
    path: str | Path,
    *,
    gazette_no: str = "S.O. 1477(E)",
    date_text: str = "14th August, 2026",
    header_date: str = "BHOPAL, FRIDAY, AUGUST 14, 2026",
    issue_no: str = "1477",
    prior_gazette_no: str = "S.O. 812(E)",
    prior_date_text: str = "20th October, 2025",
    state: str = "Madhya Pradesh",
    district: str = "Balaghat",
    schedule=KIRNAPUR_SCHEDULE,
    total: str = KIRNAPUR_TOTAL,
    competent_authority: str = "Shri K. Meshram, Land Acquisition Officer, Balaghat",
) -> Path:
    """RFCTLARR 2013 s.19 — declaration with summary of the R&R scheme."""
    st = _styles()
    flow = _masthead(st, issue_no, header_date)
    flow += [
        Paragraph("REVENUE DEPARTMENT, GOVERNMENT OF MADHYA PRADESH", st["dept"]),
        Paragraph("NOTIFICATION", st["sub"]),
        Paragraph(f"Bhopal, the {date_text}", st["small"]),
        Spacer(1, 8),
        Paragraph(
            f"<b>{gazette_no}</b>&mdash;Whereas a preliminary notification {prior_gazette_no} "
            f"dated the {prior_date_text} was published under section 11 of the Right to "
            f"Fair Compensation and Transparency in Land Acquisition, Rehabilitation and "
            f"Resettlement Act, 2013 (30 of 2013);",
            st["body"]),
        Paragraph(
            "And whereas the Rehabilitation and Resettlement Scheme has been published "
            "under section 18 of the said Act, and the Requiring Body has deposited the "
            "cost of acquisition under sub-section (2) of section 19;",
            st["body"]),
        Paragraph(
            "Now, therefore, in exercise of the powers conferred by sub-section (1) of "
            "section 19 of the said Act, the appropriate Government hereby declares that "
            "the land specified in the Schedule annexed hereto is required for the said "
            "public purpose, and the summary of the Rehabilitation and Resettlement Scheme "
            "is published along with this declaration.",
            st["body"]),
        Paragraph(
            f"Competent Authority (Land Acquisition): {competent_authority}",
            st["plain"]),
    ]
    flow += _schedule_table(st, state, district, schedule, total)
    flow += [Paragraph("[No. F 4-27/2025/Seven/2-A]", st["right"])]
    return _build(path, flow)


ALL_GENERATORS = {
    "3A": make_3a_pdf,
    "3D": make_3d_pdf,
    "S11": make_s11_pdf,
    "S19": make_s19_pdf,
}


def make_all(out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return {
        "3A": make_3a_pdf(out / "gazette_3A_LAQ-SEO-2025-01.pdf"),
        "3D": make_3d_pdf(out / "gazette_3D_LAQ-SEO-2025-01.pdf"),
        "S11": make_s11_pdf(out / "gazette_S11_LAQ-BLG-2025-03.pdf"),
        "S19": make_s19_pdf(out / "gazette_S19_LAQ-BLG-2025-03.pdf"),
    }


if __name__ == "__main__":  # pragma: no cover
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "demo_uploads")
    for k, p in make_all(target).items():
        print(f"{k}: {p}")

"""Build realistic CV PDFs in several layouts, for tests that must not depend on a private file.

Each style differs in the ways that matter to in-place editing: typeface, size, bullet glyph,
heading treatment, justified or ragged text, colours, and where employer/date lines sit. They
are produced by a different engine than Word (ReportLab), which is the point — the editor must work on a
PDF it was not tuned against.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate

#: bullet style -> (marker text, marker font). The circle is Word's sub-bullet: a Courier "o".
BULLET_STYLES = {
    "disc": ("•", "Times-Roman"),
    "square": ("·", "Helvetica"),
    "circle": ("o", "Courier"),
    "dash": ("–", "Times-Roman"),
}


@dataclass(frozen=True)
class CvStyle:
    name: str
    body_font: str  # CSS family: "serif" | "sans-serif"
    size: float
    heading_color: str
    justify: bool
    bullet: str
    heading_upper: bool = True
    margin: float = 54
    #: Draw each section's separator above its heading (as many Word templates do).
    rule_above: bool = False


@dataclass(frozen=True)
class CvContent:
    person: str
    contact: str
    summary: str
    skills: str
    jobs: tuple[tuple[str, str, str, tuple[str, ...]], ...]  # employer, title, dates, bullets
    education: tuple[str, ...]
    certifications: tuple[str, ...]
    #: Optional extra section, and the names the sections should carry.
    extracurricular: tuple[str, ...] = ()
    labels: tuple[tuple[str, str], ...] = ()
    #: Section order; any of skills, experience, education, extra, certifications.
    order: tuple[str, ...] = ("skills", "experience", "education", "certifications")
    #: Blank paragraphs inserted before the first section, to push content down a page.
    pad: int = 0


STYLES = {
    "serif_teal": CvStyle("serif_teal", "serif", 11.0, "#0F4761", True, "disc"),
    "sans_plain": CvStyle("sans_plain", "sans-serif", 10.0, "#222222", False, "square"),
    "serif_navy_small": CvStyle("serif_navy_small", "serif", 10.0, "#1F2A56", False, "circle", margin=48),
    "sans_green": CvStyle("sans_green", "sans-serif", 10.5, "#1B6B4A", True, "disc", margin=60),
}

DATA_SCIENTIST = CvContent(
    person="Asha Raman",
    contact="London, UK | asha.raman@example.com | +44 7700 900123 | linkedin.com/in/asharaman",
    summary=(
        "Data scientist with 5 years of experience building forecasting and classification models "
        "for retail and logistics clients. I work end to end, from problem framing and feature "
        "engineering through to deployment, monitoring and stakeholder reporting, and I mentor "
        "junior analysts on statistical practice and clean, reviewable code."
    ),
    skills="Python, SQL, scikit-learn, PyTorch, Airflow, Docker, dbt, Tableau, A/B testing, statistics",
    jobs=(
        (
            "Northwind Logistics",
            "Senior Data Scientist",
            "March 2022 - Present",
            (
                "Built a demand forecasting model in Python and LightGBM covering 1,200 SKUs, reducing "
                "forecast error by 18% against the previous spreadsheet process.",
                "Designed an experimentation framework with A/B testing for routing changes, which "
                "informed rollout decisions across 6 regional depots.",
                "Productionised batch scoring pipelines on Airflow and Docker, with monitoring for data "
                "drift and alerting on failed runs.",
                "Mentored 3 junior analysts through code reviews and weekly statistics sessions.",
            ),
        ),
        (
            "Brightside Retail",
            "Data Analyst",
            "June 2019 - February 2022",
            (
                "Created Tableau dashboards used by 40 store managers to track weekly sales and stock.",
                "Wrote SQL transformations in dbt to consolidate five reporting sources into one model.",
                "Analysed promotion performance and presented findings to the commercial director.",
            ),
        ),
    ),
    education=("University of Leeds, MSc Statistics, 2018 - 2019", "University of Pune, BSc Mathematics, 2015 - 2018"),
    certifications=("Google Professional Data Engineer, 2023", "dbt Analytics Engineering, 2022"),
)

PRODUCT_MANAGER = CvContent(
    person="Daniel Okafor",
    contact="Manchester, UK | daniel.okafor@example.com | +44 7700 900456 | linkedin.com/in/danielokafor",
    summary=(
        "Product manager with 6 years of experience taking B2B payments and workflow products from "
        "discovery to launch. I run roadmaps with engineering and design, write clear requirements, "
        "and use customer interviews and usage data to decide what to build next."
    ),
    skills="Roadmapping, Discovery, User research, SQL, Jira, Stakeholder management, Agile, Analytics",
    jobs=(
        (
            "Paystream Ltd",
            "Senior Product Manager",
            "January 2021 - Present",
            (
                "Owned the invoicing product roadmap for a team of 8 engineers, shipping three major "
                "releases that lifted weekly active accounts by 22%.",
                "Ran customer discovery with 30 finance teams and turned the findings into a prioritised "
                "backlog agreed with design and engineering.",
                "Defined success metrics for onboarding and used funnel analysis in SQL to cut drop-off "
                "at the verification step.",
                "Worked with compliance and legal to scope a new reconciliation feature.",
            ),
        ),
        (
            "Clearbridge Software",
            "Product Manager",
            "August 2018 - December 2020",
            (
                "Managed the integrations portfolio and the partner onboarding process.",
                "Wrote product requirement documents and acceptance criteria for 14 releases.",
                "Coordinated beta programmes with 12 customers and summarised feedback for leadership.",
            ),
        ),
    ),
    education=("University of Manchester, BA Economics, 2014 - 2017",),
    certifications=("Pragmatic Institute Product Management, 2020",),
)

BUSINESS_ANALYST = CvContent(
    person="Priya Nair",
    contact="Birmingham, UK | priya.nair@example.com | +44 7700 900789 | linkedin.com/in/priyanair",
    summary=(
        "Business analyst with 4 years of experience in financial services, translating regulatory and "
        "operational needs into clear requirements. I map processes, run workshops with stakeholders "
        "and support delivery teams through testing and release."
    ),
    skills="Requirements gathering, Process mapping, SQL, Power BI, UAT, Jira, Confluence, Agile",
    jobs=(
        (
            "Harlow Bank",
            "Business Analyst",
            "April 2021 - Present",
            (
                "Documented current and future state processes for the onboarding journey, working with "
                "operations, risk and technology teams.",
                "Wrote user stories and acceptance criteria for a case management upgrade delivered in "
                "four sprints.",
                "Built Power BI reports on onboarding turnaround that operations used in weekly reviews.",
                "Coordinated user acceptance testing with 15 testers and tracked defects to closure.",
            ),
        ),
        (
            "Meridian Insurance",
            "Junior Business Analyst",
            "September 2019 - March 2021",
            (
                "Supported claims process improvement by gathering requirements through interviews.",
                "Produced SQL extracts for management information and reconciled monthly figures.",
            ),
        ),
    ),
    education=("University of Birmingham, BSc Business Management, 2016 - 2019",),
    certifications=("BCS Foundation Certificate in Business Analysis, 2020",),
)

CONTENTS = {"data_scientist": DATA_SCIENTIST, "product_manager": PRODUCT_MANAGER, "business_analyst": BUSINESS_ANALYST}


def _fonts(style: CvStyle) -> tuple[str, str, str]:
    return ("Times-Roman", "Times-Bold", "Times-Italic") if style.body_font == "serif" else (
        "Helvetica", "Helvetica-Bold", "Helvetica-Oblique")


def _story(style: CvStyle, cv: CvContent) -> list:
    regular, bold, italic = _fonts(style)
    align = TA_JUSTIFY if style.justify else TA_LEFT
    size, lead = style.size, style.size * 1.18
    colour = HexColor(style.heading_color)
    base = ParagraphStyle("base", fontName=regular, fontSize=size, leading=lead, textColor=HexColor("#111111"))
    h1 = ParagraphStyle("h1", parent=base, fontName=bold, fontSize=size + 8, leading=(size + 8) * 1.2,
                        textColor=colour, alignment=TA_CENTER, spaceAfter=2)
    contact = ParagraphStyle("contact", parent=base, fontSize=size - 1, alignment=TA_CENTER, spaceAfter=8)
    h2 = ParagraphStyle("h2", parent=base, fontName=bold, fontSize=size + 1, leading=(size + 1) * 1.2,
                        textColor=colour, spaceBefore=12, spaceAfter=1)
    summary = ParagraphStyle("summary", parent=base, alignment=align, spaceBefore=4, spaceAfter=4)
    plain = ParagraphStyle("plain", parent=base, spaceBefore=2, spaceAfter=2)
    job = ParagraphStyle("job", parent=base, spaceBefore=8, spaceAfter=2)
    marker, marker_font = BULLET_STYLES[style.bullet]
    item = ParagraphStyle(
        "item", parent=base, alignment=align, leftIndent=16, bulletIndent=2, spaceAfter=2.5,
        bulletFontName=marker_font, bulletFontSize=size,
    )

    names = {"skills": "Skills", "experience": "Experience", "education": "Education",
             "certifications": "Certifications", "extra": "Extra-Curricular Experience", **dict(cv.labels)}

    def heading(key: str) -> list:
        text = names[key]
        label = text.upper() if style.heading_upper else text
        rule = HRFlowable(width="100%", thickness=0.6, color=colour, spaceBefore=1, spaceAfter=4)
        title = Paragraph(label, h2)
        return [rule, title] if style.rule_above else [title, rule]

    def bullets(items: tuple[str, ...]) -> list:
        return [Paragraph(text, item, bulletText=marker) for text in items]

    def section(key: str) -> list:
        if key == "skills":
            if chr(10) in cv.skills:  # one "Label: item, item" bullet per line, as a skills table has
                return heading(key) + bullets(tuple(cv.skills.split(chr(10))))
            return heading(key) + [Paragraph(cv.skills, plain)]
        if key == "experience":
            out = heading(key)
            for employer, title, dates, items in cv.jobs:
                out.append(Paragraph(f"<font name='{bold}'>{employer}</font>, {title}<br/><font name='{italic}'>{dates}</font>", job))
                out += bullets(items)
            return out
        if key == "education":
            return heading(key) + [Paragraph(e, plain) for e in cv.education]
        if key == "extra":
            return heading(key) + bullets(cv.extracurricular)
        return heading(key) + bullets(cv.certifications)

    out: list = [Paragraph(cv.person, h1), Paragraph(cv.contact, contact), Paragraph(cv.summary, summary)]
    out += [Paragraph("&nbsp;", base) for _ in range(cv.pad)]
    for key in cv.order:
        out += section(key)
    return out


def make_cv(path: Path | str, style: str = "serif_teal", content: str = "data_scientist") -> Path:
    """Write a CV PDF in ``style`` with ``content`` and return its path."""
    s, cv = STYLES[style], CONTENTS[content]
    doc = SimpleDocTemplate(
        str(path), pagesize=letter, leftMargin=s.margin, rightMargin=s.margin,
        topMargin=s.margin, bottomMargin=s.margin, title=cv.person, author=cv.person,
    )
    doc.build(_story(s, cv))
    return Path(path)

"""Explainable CV checks and a text-based, accessible PDF layout."""
from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from pydantic import BaseModel, Field


class CVSection(BaseModel):
    heading: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=12000)


class CVDocument(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    headline: str = Field(default="", max_length=200)
    contact: str = Field(default="", max_length=1000)
    sections: list[CVSection] = Field(min_length=1, max_length=15)


class CVSavePayload(BaseModel):
    source_hash: str
    document: CVDocument


def fingerprint(text: str, profile_json: str) -> str:
    return hashlib.sha256((text + "\n" + profile_json).encode()).hexdigest()


def review_text(text: str, profile: dict) -> dict:
    """A repeatable writing-readiness rubric, not a hiring/ATS probability."""
    lower = text.casefold()
    words = re.findall(r"\b[\w+#.-]+\b", text)
    criteria = []
    recommendations = []

    def criterion(label, earned, maximum, evidence, advice):
        criteria.append({"label": label, "score": earned, "maximum": maximum, "evidence": evidence})
        if earned < maximum:
            recommendations.append({"title": label, "detail": advice,
                                    "priority": "High" if earned < maximum / 2 else "Medium"})

    email = bool(re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", text))
    link = bool(re.search(r"linkedin|github|portfolio|https?://", lower))
    criterion("Contact & links", (10 if email else 0) + (5 if link else 0), 15,
              f"Email {'found' if email else 'missing'}; professional link {'found' if link else 'missing'}.",
              "Add a professional email and a working portfolio or LinkedIn URL in the header.")
    sections = [name for name, pattern in {
        "education": r"education|academic", "experience": r"experience|employment",
        "skills": r"skills|technologies", "projects": r"projects|portfolio"
    }.items() if re.search(pattern, lower)]
    criterion("Structure", len(sections) * 5, 20, "Recognized: " + (", ".join(sections) or "no standard headings") + ".",
              "Use clear Education, Experience, Skills and Projects headings, with recent work first.")
    target = profile.get("preferred_roles") or profile.get("disciplines") or []
    terms = {w.casefold() for role in target for w in re.findall(r"[\w+#]+", role)
             if (len(w) > 2 or w.casefold() in {"ai", "ml", "ux", "ui", "hr", "it"}) and w.casefold() not in {"intern", "internship", "junior", "and", "student"}}
    matched = sorted(t for t in terms if re.search(r"\b" + re.escape(t) + r"\b", lower))
    fit = round(20 * len(matched) / len(terms)) if terms else 0
    criterion("Target alignment", fit, 20,
              f"{len(matched)} of {len(terms)} target terms appear: {', '.join(matched[:8]) or 'none configured/matched'}.",
              "Set your target roles in Profile, then emphasize relevant work you can demonstrate. Avoid adding unsupported keywords.")
    action_count = len(re.findall(r"\b(built|developed|implemented|analyzed|designed|automated|led|created|improved|reduced|managed|engineered)\b", lower))
    criterion("Action-led writing", min(20, action_count * 2), 20,
              f"{action_count} specific action verbs found.",
              "Start experience bullets with an action, the work you did, and its outcome. Replace vague phrases like 'responsible for'.")
    measures = re.findall(r"\b\d[\d,.]*\+?\s*(?:(?:backend|automated|active|monthly)\s+)?(?:%|users|students|tests|hours|records|views|documents|customers|hadiths)(?!\w)", lower)
    criterion("Evidence & outcomes", min(15, len(measures) * 5), 15,
              f"{len(measures)} measurable outcomes or scope indicators found.",
              "Add truthful measures of scope or results where available, such as records processed, tests, time saved, or people served. Do not invent numbers.")
    length_score = 10 if 250 <= len(words) <= 850 else 5 if 150 <= len(words) <= 1200 else 0
    criterion("Focus & length", length_score, 10, f"{len(words)} extracted words.",
              "Aim for a focused one- or two-page early-career CV. Keep the strongest relevant projects and shorten repeated descriptions.")
    recommendations.append({"title": "Final editorial pass", "detail": "Check reverse chronology, consistent verb tense, spelling, and working links. Keep the most relevant projects first and remove duplicated descriptions.", "priority": "Review"})
    score = sum(c["score"] for c in criteria)
    return {"score": score, "criteria": criteria, "recommendations": recommendations,
            "word_count": len(words), "method": "Transparent text rubric v1",
            "explanation": "A writing-readiness score based on extracted text. It is not an ATS certification, hiring prediction, or a visual-layout assessment."}


def original_document(text: str, profile: dict) -> CVDocument:
    """Offline fallback preserves source text, clearly labelled for editing."""
    blocks = re.split(r"\n(?=(?:EDUCATION|TECHNICAL SKILLS|PROJECTS|LANGUAGES|CERTIFICATIONS|AWARDS)\b)", text)
    sections = []
    for index, block in enumerate(blocks[:15]):
        lines = block.strip().splitlines()
        if not lines:
            continue
        heading = lines.pop(0) if index else "Original CV text"
        sections.append(CVSection(heading=heading[:100], body="\n".join(lines if index else block.splitlines())[:12000] or heading))
    return CVDocument(name=profile.get("full_name") or "Your name", headline="",
                      contact=" | ".join(str(profile.get(k) or "") for k in ("email", "phone", "city") if profile.get(k)),
                      sections=sections)


def validate_ai_document(raw: dict, text: str) -> CVDocument:
    """Require every rewritten section to cite a real passage from the CV."""
    compact = lambda value: re.sub(r"\s+", " ", str(value)).strip().casefold()
    source = compact(text)
    sections = raw.get("sections") or []
    if not sections:
        raise ValueError("The model returned no CV sections.")
    for section in sections:
        evidence = compact(section.get("evidence") or "")
        if len(evidence) < 20 or evidence not in source:
            raise ValueError("A rewritten section could not be traced to the original CV. Try again or edit the original text.")
    return CVDocument.model_validate(raw)


def render_pdf(document: CVDocument) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

    # ReportLab ships these freely redistributable fonts on every supported OS.
    import reportlab
    font_dir = Path(reportlab.__file__).parent / "fonts"
    if "MasarCV" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("MasarCV", str(font_dir / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("MasarCV-Bold", str(font_dir / "VeraBd.ttf")))
    ink = colors.HexColor("#182B27")
    green = colors.HexColor("#174D3C")
    styles = {
        "name": ParagraphStyle("name", fontName="MasarCV-Bold", fontSize=21, leading=26, textColor=ink, spaceAfter=6),
        "headline": ParagraphStyle("headline", fontName="MasarCV", fontSize=11, leading=15, textColor=green, spaceAfter=6),
        "contact": ParagraphStyle("contact", fontName="MasarCV", fontSize=8, leading=12, textColor=ink, spaceAfter=12, splitLongWords=True),
        "section": ParagraphStyle("section", fontName="MasarCV-Bold", fontSize=10, leading=14, textColor=green, spaceBefore=13, spaceAfter=7, keepWithNext=True),
        "body": ParagraphStyle("body", fontName="MasarCV", fontSize=9, leading=13.2, textColor=ink, spaceAfter=5, alignment=TA_LEFT, splitLongWords=True),
        "bullet": ParagraphStyle("bullet", fontName="MasarCV", fontSize=9, leading=13.2, textColor=ink, leftIndent=10, firstLineIndent=-8, spaceAfter=4),
        "entry": ParagraphStyle("entry", fontName="MasarCV-Bold", fontSize=9, leading=13, textColor=ink, spaceBefore=5, spaceAfter=5, keepWithNext=True),
    }
    output = BytesIO()
    pdf = SimpleDocTemplate(output, pagesize=A4, rightMargin=44, leftMargin=44, topMargin=39, bottomMargin=42,
                            title=f"{document.name} - CV", author=document.name, pageCompression=1)
    def clean(value):
        return escape(value.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-"))
    story = [Paragraph(clean(document.name), styles["name"])]
    if document.headline:
        story.append(Paragraph(clean(document.headline), styles["headline"]))
    story += [Paragraph(clean(document.contact).replace("\n", "<br/>"), styles["contact"]), HRFlowable(width="100%", thickness=1, color=green)]
    for section in document.sections:
        story.append(Paragraph(clean(section.heading.upper()), styles["section"]))
        for line in section.body.splitlines():
            line = line.strip()
            if not line:
                story.append(Spacer(1, 4))
            elif line.startswith("## "):
                story.append(Paragraph(clean(line[3:]), styles["entry"]))
            elif line.startswith(("- ", "• ")):
                story.append(Paragraph("- " + clean(line[2:]), styles["bullet"]))
            else:
                story.append(Paragraph(clean(line), styles["body"]))
    def footer(canvas, doc):
        canvas.setFont("MasarCV", 7)
        canvas.setFillColor(colors.HexColor("#66736F"))
        canvas.drawString(44, 23, document.name[:90])
        canvas.drawRightString(A4[0] - 44, 23, str(doc.page))
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()

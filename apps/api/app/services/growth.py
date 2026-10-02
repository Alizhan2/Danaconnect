"""Awards are reconciled from trusted domain records, never from browser claims."""
from io import BytesIO
import hashlib
import os
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Booking, Participation, Result, Slot, utcnow
from app.models_growth import PointEvent

BUNDLED_CERTIFICATE_FONT = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "DejaVuSans.ttf"
BUNDLED_CERTIFICATE_FONT_SHA256 = "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954"


def certificate_font_path():
    # Ship an unchanged, licensed Unicode font with the API. Resolving from
    # this module works independently of the serverless process's working dir.
    try:
        if BUNDLED_CERTIFICATE_FONT.is_file():
            if hashlib.sha256(BUNDLED_CERTIFICATE_FONT.read_bytes()).hexdigest() != BUNDLED_CERTIFICATE_FONT_SHA256:
                raise HTTPException(503, "Шрифт сертификатов временно недоступен")
            return BUNDLED_CERTIFICATE_FONT
        paths = [Path(os.environ["CERTIFICATE_FONT_PATH"])] if os.environ.get("CERTIFICATE_FONT_PATH") else []
        paths += [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("C:/Windows/Fonts/arial.ttf")]
        for path in paths:
            if path.is_file():
                return path
    except OSError:
        raise HTTPException(503, "Шрифт сертификатов временно недоступен") from None
    raise HTTPException(503, "Для сертификатов не настроен шрифт с поддержкой RU/KZ/EN")

POINT_RULES = {"completed_meeting": 10, "verified_result": 100}
BADGES = (
    ("first_meeting", "completed_meeting", 1, ("Первая встреча", "Алғашқы кездесу", "First meeting")),
    ("five_meetings", "completed_meeting", 5, ("Пять встреч", "Бес кездесу", "Five meetings")),
    ("first_result", "verified_result", 1, ("Первый подтверждённый результат", "Алғашқы расталған нәтиже", "First verified outcome")),
    ("three_results", "verified_result", 3, ("Три подтверждённых результата", "Үш расталған нәтиже", "Three verified outcomes")),
)


def sync_user_progress(db, user_id):
    """Idempotent and safe under concurrent requests; the caller commits."""
    sources = []
    meetings = db.scalars(select(Booking).join(Slot, Slot.id == Booking.slot_id).where(
        ((Booking.mentee_id == user_id) | (Booking.mentor_id == user_id)),
        Booking.status == "completed", Slot.mentor_id == Booking.mentor_id, Slot.starts_at <= utcnow(),
    )).all()
    sources.extend(("completed_meeting", row.id, db.get(Slot, row.slot_id).starts_at) for row in meetings)
    results = db.scalars(select(Result).join(Participation, Participation.id == Result.participation_id).where(
        ((Participation.mentee_id == user_id) | (Participation.mentor_id == user_id)),
        Participation.status == "completed_successfully", Result.status == "completed_successfully",
        Result.verification_status == "verified",
    )).all()
    sources.extend(("verified_result", row.id, row.completed_at) for row in results)
    existing = {(event.source_type, event.source_id) for event in db.scalars(select(PointEvent).where(PointEvent.user_id == user_id)).all()}
    for source_type, source_id, earned_at in sources:
        if (source_type, source_id) in existing:
            continue
        try:
            with db.begin_nested():
                db.add(PointEvent(user_id=user_id, source_type=source_type, source_id=source_id,
                                  points=POINT_RULES[source_type], earned_at=earned_at))
                db.flush()
        except IntegrityError:
            # Another reconciler inserted this unique event; never award it twice.
            pass
    return db.scalars(select(PointEvent).where(PointEvent.user_id == user_id).order_by(PointEvent.earned_at.desc(), PointEvent.id)).all()


def progression(events, locale="ru"):
    counts = {kind: sum(event.source_type == kind for event in events) for kind in POINT_RULES}
    language = {"ru": 0, "kk": 1, "en": 2}[locale]
    return {"points": sum(event.points for event in events), "counts": counts,
            "badges": [{"code": code, "title": titles[language], "earned": counts[kind] >= threshold,
                         "progress": min(counts[kind], threshold), "threshold": threshold,
                         "source_type": kind} for code, kind, threshold, titles in BADGES],
            "rules": POINT_RULES}


def certificate_pdf(award, locale):
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
        from reportlab.platypus import Paragraph
    except ImportError:
        raise HTTPException(503, "Генератор сертификатов временно недоступен") from None
    font_path = certificate_font_path()
    if "DanaCertificate" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DanaCertificate", str(font_path)))
    labels = {
        "ru": ("Сертификат платформы", "DanaConnect подтверждает результат участника", "Выдан", "Номер записи"),
        "kk": ("Платформа сертификаты", "DanaConnect қатысушының нәтижесін растайды", "Берілген күні", "Жазба нөмірі"),
        "en": ("Platform certificate", "DanaConnect acknowledges the participant's outcome", "Issued", "Record number"),
    }[locale]
    title = getattr(award, "title_" + locale) or award.title_ru
    description = getattr(award, "description_" + locale) or award.description_ru
    used_text = " ".join([*labels, award.issued_name, title, description])
    glyphs = pdfmetrics.getFont("DanaCertificate").face.charToGlyph
    if any(ord(char) not in glyphs for char in used_text if not char.isspace()):
        raise HTTPException(503, "Шрифт сертификата не поддерживает символы этого документа")
    stream = BytesIO()
    document = canvas.Canvas(stream, pagesize=landscape(A4), pageCompression=1)
    width, height = landscape(A4)
    document.setTitle("DanaConnect platform certificate")
    document.setFillColor(HexColor("#fafae6")); document.rect(0, 0, width, height, fill=1, stroke=0)
    document.setStrokeColor(HexColor("#030ba6")); document.setLineWidth(2); document.rect(30, 30, width-60, height-60)
    document.setFillColor(HexColor("#030ba6")); document.setFont("DanaCertificate", 16); document.drawString(60, height-75, "DanaConnect")
    def paragraph(text, top, size, max_width=width-140):
        while True:
            style = ParagraphStyle("certificate", fontName="DanaCertificate", fontSize=size, leading=size*1.35,
                                   textColor=HexColor("#030039"), alignment=TA_CENTER)
            block = Paragraph(escape(text).replace("\n", "<br/>"), style)
            _, block_height = block.wrap(max_width, height)
            if top - block_height >= 112:
                break
            if size <= 8:
                raise HTTPException(422, "Текст сертификата слишком длинный. Попросите команду сократить описание")
            size -= 1
        block.drawOn(document, (width-max_width)/2, top-block_height)
        return top-block_height-15
    top = paragraph(labels[0], height-125, 26)
    top = paragraph(labels[1], top, 12)
    top = paragraph(award.issued_name, top-10, 23)
    top = paragraph(title, top, 17)
    # Long evidence remains available in the account; the PDF keeps a bounded certificate summary.
    summary = description[:280] + ("…" if len(description)>280 else "")
    paragraph(summary, top, 11)
    document.setFont("DanaCertificate", 9)
    document.drawString(60, 75, f"{labels[2]}: {award.issued_at.date().isoformat()}")
    document.drawString(60, 56, f"{labels[3]}: {award.id}")
    document.save()
    return stream.getvalue()

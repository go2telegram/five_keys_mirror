from io import BytesIO
from pathlib import Path

from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.config import settings
from app.utils.cards import prepare_cards, render_product_text

FONTS_DIR = Path(__file__).parent / "fonts"
FONT_CANDIDATES = [
    ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "NotoSans-Italic.ttf"),
    ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf"),
    (
        "_helveticaneuedeskinteface_regular.ttf",
        "_helveticaneuedeskinteface_bold.ttf",
        "_helveticaneuedeskinteface_ultralightp2.ttf",
    ),
]


def _pick_fonts() -> tuple[str, str]:
    for reg, bold, ital in FONT_CANDIDATES:
        reg_p, bold_p, ital_p = FONTS_DIR / reg, FONTS_DIR / bold, FONTS_DIR / ital
        if reg_p.exists() and bold_p.exists():
            try:
                pdfmetrics.registerFont(TTFont("Cyr-Regular", str(reg_p)))
                pdfmetrics.registerFont(TTFont("Cyr-Bold", str(bold_p)))
                if ital_p.exists():
                    pdfmetrics.registerFont(TTFont("Cyr-Italic", str(ital_p)))
                return "Cyr-Regular", "Cyr-Bold"
            except Exception as e:
                print(f"[pdf] font register error for {reg}/{bold}: {e}")
                continue
    return "Helvetica", "Helvetica-Bold"


def _hline():
    return HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#A5D6A7"))


def _on_page(canvas, doc):
    canvas.setFont("Cyr-Regular" if "Cyr-Regular" in pdfmetrics.getRegisteredFontNames() else "Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#2E7D32"))
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Стр. {doc.page}")


def _qr_drawing(url: str, size: float = 2.6 * cm) -> Drawing:
    code = qr.QrCodeWidget(url)
    b = code.getBounds()
    w, h = b[2] - b[0], b[3] - b[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(code)
    return d


# ===== ДЕФОЛТНЫЕ СХЕМЫ ПРИЁМА (если в плане intake пуст) =====
INTAKE_DEFAULTS = {
    "T8 EXTRA": {"morning": True, "day": False, "evening": True, "note": "1–2 мл в воде; не поздно вечером"},
    "T8 BLEND": {"morning": True, "day": True, "evening": False, "note": "30 мл в воде/кефире"},
    "NASH ViTEN": {"morning": True, "day": False, "evening": False, "note": "1 стик под язык, курс 5 дней"},
    "T8 TEO GREEN": {"morning": True, "day": True, "evening": False, "note": "1 порция в воде"},
    "MOBIO+": {"morning": True, "day": True, "evening": False, "note": "1 ч.л. в 30 мл воды"},
    "NASH Омега-3": {"morning": True, "day": False, "evening": False, "note": "1 капсула с завтраком"},
    "Magnesium + B6": {"morning": False, "day": False, "evening": True, "note": "по инструкции"},
    "Vitamin D3": {"morning": True, "day": False, "evening": False, "note": "по дефициту/согласованию"},
    "T8 ERA MIT UP": {"morning": True, "day": False, "evening": False, "note": "1 стик утром, 30 мин до еды"},
}


def _build_intake_rows(products_block: list[str], custom_rows: list[dict] | None) -> list[dict]:
    """
    Если custom_rows передали — используем их.
    Иначе парсим названия из блока products (строки вида '— T8 EXTRA: ...')
    и подставляем дефолтные расписания.
    """
    if custom_rows:
        return custom_rows
    rows = []
    for s in products_block:
        # название — до двоеточия, без '— '
        name = s.split(":", 1)[0].replace("—", "").strip()
        base = INTAKE_DEFAULTS.get(name)
        if base:
            row = {"name": name}
            row.update(base)
            rows.append(row)
    return rows


def _intake_table(data_rows: list[dict], body_style: ParagraphStyle) -> Table:
    header = ["Продукт", "Утро", "День", "Вечер", "Комментарий"]
    table_data = [header]

    def mark(x):
        return "✓" if x else "—"

    for r in data_rows:
        if isinstance(r, dict):
            row = r
        elif isinstance(r, (list, tuple)):
            time_label = str(r[0]).lower() if r else ""
            name = str(r[1]) if len(r) > 1 else ""
            note = str(r[2]) if len(r) > 2 else ""
            row = {
                "name": name,
                "morning": "утро" in time_label,
                "day": "день" in time_label,
                "evening": "вечер" in time_label,
                "note": note,
            }
        else:
            row = {"name": str(r)}

        table_data.append(
            [
                Paragraph(row.get("name", ""), body_style),
                mark(row.get("morning")),
                mark(row.get("day")),
                mark(row.get("evening")),
                Paragraph(row.get("note", ""), body_style),
            ]
        )
    t = Table(table_data, colWidths=[5.5 * cm, 1.5 * cm, 1.5 * cm, 1.8 * cm, 6.2 * cm])
    t.setStyle(
        TableStyle(
            [
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, -1),
                    "Cyr-Regular" if "Cyr-Regular" in pdfmetrics.getRegisteredFontNames() else "Helvetica",
                ),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F5E9")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1B5E20")),
                ("ALIGN", (1, 1), (3, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#A5D6A7")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def build_pdf(
    title: str,
    subtitle: str,
    actions: list[str] | None,
    products: list[str],
    *,
    notes: str | None = "",
    footer: str = "",
    intake_rows: list[dict] | None = None,
    order_url: str | None = None,
    channel_note: str = "telegram-канал «Пять ключей здоровья»",
    recommended_products: list[str] | None = None,
    context: str | None = None,
) -> bytes:
    reg_font, bold_font = _pick_fonts()

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=1.5 * cm
    )

    styles = getSampleStyleSheet()
    title_s = ParagraphStyle(
        "title_s",
        parent=styles["Title"],
        fontName=bold_font,
        textColor=colors.HexColor("#2E7D32"),
        fontSize=22,
        leading=26,
        alignment=1,
    )
    h_s = ParagraphStyle(
        "h_s",
        parent=styles["Heading2"],
        fontName=bold_font,
        textColor=colors.HexColor("#388E3C"),
        fontSize=14,
        leading=18,
    )
    p_s = ParagraphStyle("p_s", parent=styles["BodyText"], fontName=reg_font, fontSize=11, leading=15)
    bullet_s = ParagraphStyle("bullet_s", parent=p_s, leftIndent=0.2 * cm, bulletFontName=reg_font, bulletFontSize=10)

    story = []
    # Заголовок
    story.append(Paragraph(title, title_s))
    if subtitle:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph(subtitle, h_s))
    story.append(Spacer(1, 0.4 * cm))
    story.append(_hline())
    story.append(Spacer(1, 0.6 * cm))

    # Шаги
    if actions:
        story.append(Paragraph("Ключевые шаги на 7 дней", h_s))
        story.append(Spacer(1, 0.2 * cm))
        a_items = [ListItem(Paragraph(a, bullet_s), bulletColor=colors.HexColor("#2E7D32")) for a in actions]
        story.append(ListFlowable(a_items, bulletType="bullet", bulletColor=colors.HexColor("#2E7D32")))
        story.append(Spacer(1, 0.5 * cm))
        story.append(_hline())
        story.append(Spacer(1, 0.5 * cm))

    products_block_for_intake = list(products)
    recommended_cards = prepare_cards(recommended_products or [], context)
    if recommended_cards:
        story.append(Paragraph("Рекомендуемые продукты", h_s))
        story.append(Spacer(1, 0.2 * cm))
        for card in recommended_cards:
            header, card_bullets = render_product_text(card, context)
            story.append(Paragraph(header, p_s))
            if card_bullets:
                items = [
                    ListItem(Paragraph(line, bullet_s), bulletColor=colors.HexColor("#2E7D32")) for line in card_bullets
                ]
                story.append(ListFlowable(items, bulletType="bullet", bulletColor=colors.HexColor("#2E7D32")))
            story.append(Spacer(1, 0.3 * cm))
        story.append(_hline())
        story.append(Spacer(1, 0.5 * cm))
        products_block_for_intake = [
            render_product_text(card, context)[0].replace("<b>", "").replace("</b>", "") for card in recommended_cards
        ]
    elif products:
        story.append(Paragraph("Рекомендованные продукты", h_s))
        story.append(Spacer(1, 0.2 * cm))
        pr_items = [ListItem(Paragraph(s, bullet_s), bulletColor=colors.HexColor("#2E7D32")) for s in products]
        story.append(ListFlowable(pr_items, bulletType="bullet", bulletColor=colors.HexColor("#2E7D32")))
        story.append(Spacer(1, 0.5 * cm))

    # Таблица приёмов
    rows = _build_intake_rows(products_block_for_intake, intake_rows)
    if rows:
        story.append(_hline())
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Таблица приёмов", h_s))
        story.append(Spacer(1, 0.2 * cm))
        story.append(_intake_table(rows, p_s))
        story.append(Spacer(1, 0.5 * cm))

    # Заметки
    if notes:
        story.append(_hline())
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Заметки", h_s))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(notes, p_s))
        story.append(Spacer(1, 0.5 * cm))

    # QR + подпись канала
    q_url = order_url or settings.velavie_url
    if q_url:
        story.append(_hline())
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph("Заказать продукты:", h_s))
        story.append(Spacer(1, 0.2 * cm))
        story.append(_qr_drawing(q_url, size=3 * cm))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(q_url, p_s))
        story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph(channel_note, p_s))
    story.append(Spacer(1, 0.4 * cm))

    # Футер
    if footer:
        story.append(_hline())
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(footer, p_s))

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    buf.seek(0)
    return buf.read()

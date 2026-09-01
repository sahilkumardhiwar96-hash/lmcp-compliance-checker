#Updated
# -*- coding: utf-8 -*-
"""
PDF report generation for the Legal Metrology Compliance Checker.
Uses fpdf2 with HarfBuzz text shaping so Devanagari (Hindi) text renders
with correct conjuncts and matra placement — plain font embedding without
shaping (e.g. default ReportLab) garbles Indic scripts.
"""

import io
from datetime import datetime
from fpdf import FPDF
from translations import PDF_STRINGS, get_field_label

FONT_REGULAR = "fonts/NotoSansDevanagari-Regular.ttf"
FONT_BOLD = "fonts/NotoSansDevanagari-Bold.ttf"

GREEN = (46, 125, 50)
RED = (198, 40, 40)
GREY = (110, 110, 110)
LIGHT_GREEN_BG = (241, 248, 242)
LIGHT_RED_BG = (253, 237, 237)


class ReportPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("Noto", "", FONT_REGULAR)
        self.add_font("Noto", "B", FONT_BOLD)
        self.set_text_shaping(True)  # enables HarfBuzz shaping for Devanagari
        self.set_auto_page_break(auto=True, margin=15)


def generate_pdf_report(image_bytes, found, missing, score, filename, field_labels_en, lang="en", location_name=None, font_height_result=None):
    """Build a compliance report PDF in the requested language ('en' or 'hi').
    font_height_result, if provided, is the calibrated Rule 7 measurement dict
    from font_height.py: {"measured_mm", "required_mm", "verdict", "field"}."""
    s = PDF_STRINGS[lang]

    pdf = ReportPDF()
    pdf.add_page()

    pdf.set_font("Noto", "B", 17)
    pdf.multi_cell(0, 9, s["title"], new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Noto", "", 10)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(0, 6, s["subtitle"], new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    pdf.set_font("Noto", "", 10.5)
    pdf.multi_cell(0, 6.5, f"{s['product_file']}: {filename}", new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 6.5, f"{s['scan_time']}: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 6.5, f"{s['score']}: {score}%", new_x="LMARGIN", new_y="NEXT")
    if location_name:
        pdf.multi_cell(0, 6.5, f"{s['location']}: {location_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    if image_bytes:
        pdf.set_font("Noto", "B", 12.5)
        pdf.multi_cell(0, 7, s["photo_evidence"], new_x="LMARGIN", new_y="NEXT")
        try:
            img_buffer = io.BytesIO(image_bytes)
            pdf.image(img_buffer, w=75)
        except Exception:
            pass
        pdf.ln(4)

    pdf.set_font("Noto", "B", 12.5)
    pdf.multi_cell(0, 7, s["found_heading"], new_x="LMARGIN", new_y="NEXT")

    if found:
        _render_table(
            pdf,
            headers=[s["col_declaration"], s["col_value"], s["col_legal_ref"]],
            col_widths=[55, 65, 60],
            rows=[
                [get_field_label(_field_key(f, field_labels_en), field_labels_en, lang), str(f["value"] or "-"), f["legal_ref"]]
                for f in found
            ],
            header_bg=GREEN,
            row_bg=LIGHT_GREEN_BG,
        )
    else:
        pdf.set_font("Noto", "", 10.5)
        pdf.multi_cell(0, 6.5, s["none_found"], new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)

    pdf.set_font("Noto", "B", 12.5)
    pdf.multi_cell(0, 7, s["missing_heading"], new_x="LMARGIN", new_y="NEXT")

    if missing:
        rows = []
        for m in missing:
            ref_text = m["legal_ref"]
            if m.get("note"):
                ref_text += f" — {s['note_prefix']}: {m['note']}"
            rows.append([get_field_label(_field_key(m, field_labels_en), field_labels_en, lang), ref_text])
        _render_table(
            pdf,
            headers=[s["col_declaration"], s["col_legal_ref_notes"]],
            col_widths=[65, 115],
            rows=rows,
            header_bg=RED,
            row_bg=LIGHT_RED_BG,
        )
        pdf.ln(2)
        pdf.set_font("Noto", "", 8.5)
        pdf.set_text_color(*GREY)
        pdf.multi_cell(0, 5, s["penalty_note"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    else:
        pdf.set_font("Noto", "", 10.5)
        pdf.multi_cell(0, 6.5, s["no_violations"], new_x="LMARGIN", new_y="NEXT")

    if font_height_result and font_height_result.get("verdict") in ("PASS", "FAIL"):
        pdf.ln(3)
        v = font_height_result["verdict"]
        color = GREEN if v == "PASS" else RED
        pdf.set_font("Noto", "B", 10.5)
        pdf.set_text_color(*color)
        req_txt = f" (Rule 7 requires \u2265 {font_height_result['required_mm']} mm)" if font_height_result.get("required_mm") else ""
        verified_line = (
            f"Rule 7 numeral height \u2014 CALIBRATED MEASUREMENT: {v} \u2014 measured "
            f"{font_height_result['measured_mm']} mm{req_txt}"
        )
        pdf.multi_cell(0, 6, verified_line, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    pdf.ln(6)
    pdf.set_font("Noto", "", 8)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(0, 5, s["font_disclaimer"], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.multi_cell(0, 5, s["footer_disclaimer"], new_x="LMARGIN", new_y="NEXT")

    buffer = io.BytesIO(pdf.output())
    buffer.seek(0)
    return buffer


def _field_key(item, field_labels_en):
    """Reverse-lookup the field key from its English label, to find the Hindi translation."""
    for key, label in field_labels_en.items():
        if label == item["label"]:
            return key
    return None


def _render_table(pdf, headers, col_widths, rows, header_bg, row_bg):
    line_h = 5.2
    cell_pad = 1.5  # left/right inset used when the text is actually drawn
    x_start = pdf.l_margin

    def measure_row_height(texts, bold):
        # Measure at the SAME width the text is actually drawn at (w - 2*cell_pad).
        # Measuring at the full column width and then drawing narrower (as before)
        # under-counts wrapped lines for some values, so those rows' text spills
        # out of their background/border box — hence the inconsistent look.
        pdf.set_font("Noto", "B" if bold else "", 9)
        heights = []
        for text, w in zip(texts, col_widths):
            text_w = w - 2 * cell_pad
            n_lines = len(pdf.multi_cell(text_w, line_h, text, dry_run=True, output="LINES"))
            heights.append(max(1, n_lines) * line_h)
        return max(heights) + 2

    def draw_row(texts, bg_color, bold, text_color=(0, 0, 0)):
        pdf.set_font("Noto", "B" if bold else "", 9)
        pdf.set_text_color(*text_color)
        row_h = measure_row_height(texts, bold)

        # A row's colored background/border is drawn with rect() (which ignores
        # auto-page-break) while its text is drawn with multi_cell() (which
        # doesn't). Left alone, a row near the bottom margin can end up with its
        # box on one page and its text on the next. So start a fresh page first
        # whenever the whole row wouldn't fit, and repeat the header for context.
        if pdf.get_y() + row_h > pdf.page_break_trigger:
            pdf.add_page()
            if texts is not headers:
                draw_row(headers, header_bg, bold=True, text_color=(255, 255, 255))
                pdf.set_font("Noto", "B" if bold else "", 9)
                pdf.set_text_color(*text_color)

        y0 = pdf.get_y()
        x = x_start
        for text, w in zip(texts, col_widths):
            pdf.set_xy(x, y0)
            pdf.set_fill_color(*bg_color)
            pdf.rect(x, y0, w, row_h, style="F")
            pdf.set_xy(x + cell_pad, y0 + 1)
            pdf.multi_cell(w - 2 * cell_pad, line_h, text, new_x="LEFT", new_y="TOP")
            x += w

        pdf.set_draw_color(180, 180, 180)
        x = x_start
        for w in col_widths:
            pdf.rect(x, y0, w, row_h)
            x += w

        pdf.set_xy(x_start, y0 + row_h)

    draw_row(headers, header_bg, bold=True, text_color=(255, 255, 255))
    for row in rows:
        draw_row(row, row_bg, bold=False)

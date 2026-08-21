"""
Generates a syntax-highlighted PDF of grok_quantum_bot.py using reportlab + Pygments.
"""

from datetime import datetime
from pathlib import Path

from pygments import lex
from pygments.lexers import PythonLexer
from pygments.token import (
    Comment, Error, Generic, Keyword, Name, Number,
    Operator, Punctuation, String, Token, Whitespace,
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

# ── Layout ────────────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN_LEFT   = 18 * mm
MARGIN_RIGHT  = 12 * mm
MARGIN_TOP    = 18 * mm
MARGIN_BOTTOM = 16 * mm

CODE_X      = MARGIN_LEFT + 14 * mm   # code starts after line-number gutter
GUTTER_X    = MARGIN_LEFT             # line numbers
CODE_WIDTH  = PAGE_W - CODE_X - MARGIN_RIGHT
LINE_H      = 4.6 * mm
FONT_SIZE   = 7.8
HEADER_H    = 14 * mm

# ── Colours ───────────────────────────────────────────────────────────────────
BG_PAGE     = colors.HexColor("#1E1E2E")   # dark page background
BG_CODE     = colors.HexColor("#181825")   # code area
BG_HEADER   = colors.HexColor("#11111B")   # header bar
BG_GUTTER   = colors.HexColor("#1E1E2E")   # line-number column
ACCENT      = colors.HexColor("#CBA6F7")   # mauve accent (Catppuccin Mocha)
RULE_COLOR  = colors.HexColor("#313244")

# ── Catppuccin Mocha token colours ───────────────────────────────────────────
TOKEN_COLORS = {
    # keywords
    Keyword:                        "#CBA6F7",   # mauve
    Keyword.Constant:               "#EBA0AC",   # red
    Keyword.Declaration:            "#CBA6F7",
    Keyword.Namespace:              "#CBA6F7",
    Keyword.Type:                   "#89DCEB",   # sky

    # names
    Name:                           "#CDD6F4",   # text
    Name.Builtin:                   "#89B4FA",   # blue
    Name.Builtin.Pseudo:            "#F38BA8",   # red
    Name.Class:                     "#F9E2AF",   # yellow
    Name.Decorator:                 "#89B4FA",
    Name.Exception:                 "#F38BA8",
    Name.Function:                  "#89B4FA",
    Name.Function.Magic:            "#94E2D5",   # teal
    Name.Attribute:                 "#CDD6F4",
    Name.Tag:                       "#F38BA8",
    Name.Variable:                  "#CDD6F4",
    Name.Variable.Magic:            "#94E2D5",

    # literals
    String:                         "#A6E3A1",   # green
    String.Doc:                     "#6C7086",   # overlay0 (docstrings muted)
    String.Escape:                  "#FAB387",   # peach
    String.Interpol:                "#FAB387",
    Number:                         "#FAB387",   # peach
    Number.Integer:                 "#FAB387",
    Number.Float:                   "#FAB387",
    Number.Hex:                     "#FAB387",

    # operators / punctuation
    Operator:                       "#89DCEB",   # sky
    Operator.Word:                  "#CBA6F7",
    Punctuation:                    "#CDD6F4",

    # comments
    Comment:                        "#6C7086",   # overlay0
    Comment.Single:                 "#6C7086",
    Comment.Multiline:              "#6C7086",
    Comment.Preproc:                "#F38BA8",

    # defaults
    Token:                          "#CDD6F4",
    Whitespace:                     "#CDD6F4",
    Error:                          "#F38BA8",
    Generic:                        "#CDD6F4",
}

def token_color(ttype):
    """Walk up the token hierarchy until a colour is found."""
    while ttype:
        if ttype in TOKEN_COLORS:
            return colors.HexColor(TOKEN_COLORS[ttype])
        ttype = ttype.parent
    return colors.HexColor("#CDD6F4")


# ── Helpers ───────────────────────────────────────────────────────────────────

def draw_page_background(c: canvas.Canvas):
    c.setFillColor(BG_PAGE)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

def draw_header(c: canvas.Canvas, filename: str, page_num: int, total_pages: int):
    """Dark header bar with file name and page number."""
    top = PAGE_H - MARGIN_TOP
    c.setFillColor(BG_HEADER)
    c.rect(MARGIN_LEFT, top - HEADER_H, PAGE_W - MARGIN_LEFT - MARGIN_RIGHT,
           HEADER_H, fill=1, stroke=0)

    # accent left strip
    c.setFillColor(ACCENT)
    c.rect(MARGIN_LEFT, top - HEADER_H, 2, HEADER_H, fill=1, stroke=0)

    # file name
    c.setFillColor(colors.HexColor("#CDD6F4"))
    c.setFont("Courier-Bold", 9)
    c.drawString(MARGIN_LEFT + 6, top - HEADER_H + 4.5 * mm, filename)

    # date
    c.setFont("Courier", 7.5)
    c.setFillColor(colors.HexColor("#6C7086"))
    date_str = datetime.now().strftime("%Y-%m-%d")
    c.drawString(MARGIN_LEFT + 6, top - HEADER_H + 2 * mm, date_str)

    # page number (right)
    pg_str = f"Page {page_num} / {total_pages}"
    c.setFillColor(colors.HexColor("#6C7086"))
    c.setFont("Courier", 7.5)
    c.drawRightString(PAGE_W - MARGIN_RIGHT - 2,
                      top - HEADER_H + 3 * mm, pg_str)

def draw_code_background(c: canvas.Canvas, y_top: float, y_bottom: float):
    """Code area + gutter backgrounds."""
    h = y_top - y_bottom
    # gutter
    c.setFillColor(BG_GUTTER)
    c.rect(MARGIN_LEFT, y_bottom, CODE_X - MARGIN_LEFT, h, fill=1, stroke=0)
    # code
    c.setFillColor(BG_CODE)
    c.rect(CODE_X, y_bottom, CODE_WIDTH, h, fill=1, stroke=0)
    # thin rule between gutter and code
    c.setStrokeColor(RULE_COLOR)
    c.setLineWidth(0.5)
    c.line(CODE_X, y_bottom, CODE_X, y_top)

def draw_footer(c: canvas.Canvas):
    c.setFillColor(colors.HexColor("#6C7086"))
    c.setFont("Courier", 6.5)
    c.drawString(MARGIN_LEFT, MARGIN_BOTTOM - 4 * mm,
                 "Educational use only. Not financial advice.")


# ── Core renderer ─────────────────────────────────────────────────────────────

def render_pdf(source_path: str, output_path: str):
    source = Path(source_path).read_text(encoding="utf-8")
    tokens = list(lex(source, PythonLexer()))

    # ── Pre-process tokens into (line_number, [(text, ttype), ...]) ──────────
    raw_lines: list[list] = [[]]
    for ttype, value in tokens:
        parts = value.split("\n")
        for i, part in enumerate(parts):
            if part:
                raw_lines[-1].append((part, ttype))
            if i < len(parts) - 1:
                raw_lines.append([])

    # ── Pagination ────────────────────────────────────────────────────────────
    usable_top    = PAGE_H - MARGIN_TOP - HEADER_H - 1 * mm
    usable_bottom = MARGIN_BOTTOM + 2 * mm
    lines_per_page = int((usable_top - usable_bottom) / LINE_H)

    pages = [raw_lines[i:i + lines_per_page]
             for i in range(0, len(raw_lines), lines_per_page)]
    total_pages = len(pages)
    filename = Path(source_path).name

    c = canvas.Canvas(output_path, pagesize=A4)
    c.setTitle(filename)
    c.setAuthor("Trading Bot PDF Generator")
    c.setSubject("Syntax-highlighted Python source")

    global_line = 1
    for page_idx, page_lines in enumerate(pages):
        draw_page_background(c)
        draw_header(c, filename, page_idx + 1, total_pages)

        y_top    = usable_top
        y_bottom = y_top - len(page_lines) * LINE_H
        if y_bottom < usable_bottom:
            y_bottom = usable_bottom

        draw_code_background(c, y_top, y_bottom)

        y = y_top - LINE_H * 0.72  # first baseline

        for line_tokens in page_lines:
            # ── line-number ───────────────────────────────────────────────
            c.setFont("Courier", FONT_SIZE - 0.5)
            c.setFillColor(colors.HexColor("#45475A"))
            ln_str = str(global_line).rjust(4)
            c.drawRightString(CODE_X - 2, y, ln_str)

            # ── highlighted tokens ────────────────────────────────────────
            x = CODE_X + 2
            c.setFont("Courier", FONT_SIZE)
            for text, ttype in line_tokens:
                col = token_color(ttype)
                bold = ttype in (Keyword, Keyword.Declaration,
                                 Keyword.Namespace, Name.Class,
                                 Name.Function, Name.Decorator)
                c.setFont("Courier-Bold" if bold else "Courier", FONT_SIZE)
                c.setFillColor(col)
                c.drawString(x, y, text)
                x += c.stringWidth(text, "Courier-Bold" if bold else "Courier", FONT_SIZE)

            y -= LINE_H
            global_line += 1

        draw_footer(c)
        c.showPage()

    c.save()
    print(f"PDF saved → {output_path}")


if __name__ == "__main__":
    render_pdf(
        source_path="/Users/joelaudu/Trading bot/grok_quantum_bot.py",
        output_path="/Users/joelaudu/Trading bot/grok_quantum_bot.pdf",
    )

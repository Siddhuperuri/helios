# -*- coding: utf-8 -*-
"""
Builds the paper in IEEE Access house style.

Page geometry, column widths, leading and the signature blue (#0073AE) were
measured directly from the reference article supplied in this folder
(Rosales Huamani et al., IEEE Access vol. 13, 2025) rather than guessed.

Placeholders that MUST be replaced before any real submission are written as
<ANGLE BRACKETS> and are listed at the end of the build output.
"""
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Image,
    Table, TableStyle, KeepTogether, NextPageTemplate, FrameBreak, Flowable,
)

OUT = r"C:\Projects_AI\college_project\paper\helios_paper_ieee_access.pdf"
FD = r"C:\Windows\Fonts"

# ------------------------------------------------------------------ fonts
pdfmetrics.registerFont(TTFont("Tm", FD + r"\times.ttf"))
pdfmetrics.registerFont(TTFont("Tm-B", FD + r"\timesbd.ttf"))
pdfmetrics.registerFont(TTFont("Tm-I", FD + r"\timesi.ttf"))
pdfmetrics.registerFont(TTFont("Tm-BI", FD + r"\timesbi.ttf"))
pdfmetrics.registerFontFamily("Tm", normal="Tm", bold="Tm-B",
                              italic="Tm-I", boldItalic="Tm-BI")
pdfmetrics.registerFont(TTFont("Ar", FD + r"\arial.ttf"))
pdfmetrics.registerFont(TTFont("Ar-B", FD + r"\arialbd.ttf"))
pdfmetrics.registerFont(TTFont("Ar-I", FD + r"\ariali.ttf"))
pdfmetrics.registerFontFamily("Ar", normal="Ar", bold="Ar-B", italic="Ar-I")

# --------------------------------------------------------------- geometry
PW, PH = 576.0, 782.929           # IEEE Access trim, measured
LM = RM = 36.0
GUT = 19.2
COLW = (PW - LM - RM - GUT) / 2.0  # 242.4
BODY_TOP = 66.2                    # from page top, measured
BODY_BOT = 49.9                    # from page bottom, measured
BODY_H = PH - BODY_TOP - BODY_BOT

BLUE = colors.HexColor("#0073AE")
DARKBLUE = colors.HexColor("#005A8C")
BLACK = colors.black

RUNNING_HEAD = ("T. H. Sowmya et al.: Quantifying Three Evaluation Pitfalls "
                "in Machine-Learning Solar Forecasting")

# ----------------------------------------------------------------- styles
def ps(name, **kw):
    base = dict(fontName="Tm", fontSize=9.5, leading=11.9, alignment=TA_JUSTIFY)
    base.update(kw)
    return ParagraphStyle(name, **base)


S = {
    "title": ps("title", fontName="Ar-B", fontSize=20, leading=24.5,
                alignment=TA_LEFT, textColor=BLUE, spaceAfter=10),
    "authors": ps("authors", fontName="Ar-B", fontSize=10, leading=13,
                  alignment=TA_LEFT, textColor=BLACK, spaceAfter=2),
    "affil": ps("affil", fontSize=7.4, leading=9.0, alignment=TA_LEFT,
                spaceAfter=1),
    "corr": ps("corr", fontSize=8.0, leading=10.0, alignment=TA_LEFT,
               spaceBefore=4, spaceAfter=8),
    "dates": ps("dates", fontSize=8.0, leading=10.0, alignment=TA_LEFT),
    "doi": ps("doi", fontName="Tm-I", fontSize=7.6, leading=9.5,
              alignment=TA_LEFT, spaceBefore=2),
    "abs": ps("abs", fontName="Tm-B", fontSize=9.0, leading=11.2,
              spaceAfter=6, leftIndent=10),
    "idx": ps("idx", fontName="Tm-B", fontSize=9.0, leading=11.2,
              spaceAfter=4, leftIndent=10),
    "sec": ps("sec", fontName="Ar-B", fontSize=9.0, leading=11.5,
              alignment=TA_LEFT, textColor=BLUE,
              spaceBefore=9, spaceAfter=3),
    "sub": ps("sub", fontName="Ar-B", fontSize=8.2, leading=10.5,
              alignment=TA_LEFT, textColor=BLUE,
              spaceBefore=7, spaceAfter=2),
    "ssub": ps("ssub", fontName="Ar", fontSize=8.0, leading=10.2,
               alignment=TA_LEFT, textColor=BLUE,
               spaceBefore=6, spaceAfter=2),
    "body": ps("body", firstLineIndent=10.5, spaceAfter=0),
    "body0": ps("body0", firstLineIndent=0, spaceAfter=0),
    "bul": ps("bul", leftIndent=14, firstLineIndent=-8, spaceAfter=2.5),
    "num": ps("num", leftIndent=14, firstLineIndent=-10, spaceAfter=2.5),
    "cap": ps("cap", fontSize=7.8, leading=9.6, alignment=TA_LEFT,
              spaceBefore=3, spaceAfter=4),
    "tcell": ps("tcell", fontSize=7.6, leading=9.2, alignment=TA_CENTER),
    "tcellL": ps("tcellL", fontSize=7.6, leading=9.2, alignment=TA_LEFT),
    "thead": ps("thead", fontName="Tm-B", fontSize=7.6, leading=9.2,
                alignment=TA_CENTER),
    "theadL": ps("theadL", fontName="Tm-B", fontSize=7.6, leading=9.2,
                 alignment=TA_LEFT),
    "ref": ps("ref", fontSize=7.6, leading=9.1, leftIndent=13,
              firstLineIndent=-13, spaceAfter=1.5),
    "bio": ps("bio", fontSize=7.8, leading=9.4, spaceAfter=6),
    "note": ps("note", fontSize=7.2, leading=8.8, alignment=TA_LEFT),
}


def P(t, s="body"):
    return Paragraph(t, S[s])


def SEC(num, t):
    return Paragraph(("%s. %s" % (num, t.upper())) if num else t.upper(), S["sec"])


def SUB(l, t):
    return Paragraph("%s. %s" % (l, t.upper()), S["sub"])


def SSUB(n, t):
    return Paragraph("%d) %s" % (n, t.upper()), S["ssub"])


# ------------------------------------------------------------- decorations
class AccessBadge(Flowable):
    """The striped bar + blue 'RESEARCH ARTICLE' pill."""

    def __init__(self, width, label="RESEARCH ARTICLE"):
        Flowable.__init__(self)
        self.width = width
        self.height = 21
        self.label = label

    def draw(self):
        c = self.canv
        x = 0
        for i, w in enumerate([1.2, 1.2, 2.4, 1.2, 3.2, 1.2, 1.2, 2.4]):
            c.setFillColor(BLUE if i % 2 == 0 else colors.HexColor("#8fc4e0"))
            c.rect(x, 2, w, 17, stroke=0, fill=1)
            x += w + 1.6
        x += 4
        c.setFillColor(colors.white)
        c.setStrokeColor(BLUE)
        c.setLineWidth(1.1)
        tw = pdfmetrics.stringWidth(self.label, "Ar-B", 11) + 18
        c.roundRect(x, 0, tw, 21, 3, stroke=1, fill=1)
        c.setFillColor(BLUE)
        c.setFont("Ar-B", 11)
        c.drawString(x + 9, 6.5, self.label)


class DottedMark(Flowable):
    """Three blue dots used beside ABSTRACT / INDEX TERMS."""

    def __init__(self):
        Flowable.__init__(self)
        self.width = 0
        self.height = 0

    def draw(self):
        c = self.canv
        c.setFillColor(BLUE)
        for i in range(3):
            c.circle(1.5, -5 - i * 4.0, 1.05, stroke=0, fill=1)


def access_logo(c, x, y, scale=1.0, tagline=True):
    """Draw an 'IEEE Access' wordmark at (x, y) = baseline-left."""
    c.saveState()
    fs = 20 * scale
    c.setFont("Ar-B", fs)
    c.setFillColor(BLACK)
    c.drawString(x, y, "IEEE")
    w = pdfmetrics.stringWidth("IEEE", "Ar-B", fs)
    c.setFont("Ar-I", fs)
    c.setFillColor(BLUE)
    c.drawString(x + w + 2.5 * scale, y, "Access")
    w2 = pdfmetrics.stringWidth("Access", "Ar-I", fs)
    c.setFont("Ar", 4.6 * scale)
    c.setFillColor(BLACK)
    if tagline:
        c.drawString(x, y - 6.5 * scale,
                     "Multidisciplinary  :  Rapid Review  :  Open Access Journal")
    c.restoreState()
    return w + w2 + 3 * scale


# ------------------------------------------------------------- table maker
def tbl(num, caption, header, rows, widths, left_first=True, bold_rows=()):
    cap = Paragraph(
        '<font name="Ar-B" color="#0073AE" size="7.8">TABLE %s.</font> '
        '<font name="Tm-B" size="7.8">%s</font>' % (num, caption), S["cap"])
    data = [[Paragraph(h, S["theadL"] if (j == 0 and left_first) else S["thead"])
             for j, h in enumerate(header)]]
    for i, r in enumerate(rows):
        cells = []
        for j, cval in enumerate(r):
            st = "tcellL" if (j == 0 and left_first) else "tcell"
            if i in bold_rows:
                cval = "<b>%s</b>" % cval
            cells.append(Paragraph(str(cval), S[st]))
        data.append(cells)
    t = Table(data, colWidths=widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.9, BLACK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, BLACK),
        ("LINEBELOW", (0, -1), (-1, -1), 0.9, BLACK),
    ]))
    return KeepTogether([cap, t, Spacer(1, 7)])


def figure(num, caption, path, width):
    from PIL import Image as PILImage
    iw, ih = PILImage.open(path).size
    h = width * ih / iw
    img = Image(path, width=width, height=h)
    cap = Paragraph(
        '<font name="Ar-B" color="#0073AE" size="7.8">FIGURE %s.</font> '
        '<font name="Tm" size="7.8">%s</font>' % (num, caption), S["cap"])
    return KeepTogether([Spacer(1, 3), img, cap, Spacer(1, 4)])


class BioPhoto(Flowable):
    def __init__(self, w=52, h=64):
        Flowable.__init__(self)
        self.width = w
        self.height = h

    def draw(self):
        c = self.canv
        c.setStrokeColor(colors.HexColor("#999999"))
        c.setFillColor(colors.HexColor("#eeeeee"))
        c.setLineWidth(0.6)
        c.rect(0, 0, self.width, self.height, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#999999"))
        c.setFont("Ar", 5.4)
        c.drawCentredString(self.width / 2, self.height / 2 + 6, "AUTHOR")
        c.drawCentredString(self.width / 2, self.height / 2 - 1, "PHOTO")
        c.drawCentredString(self.width / 2, self.height / 2 - 8, "<ADD>")


def bio(name, text):
    ph = BioPhoto()
    body = Paragraph('<font name="Ar-B" size="7.8">%s</font> %s' % (name, text),
                     S["bio"])
    t = Table([[ph, body]], colWidths=[58, COLW - 58])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (0, 0), "TOP"),
        ("VALIGN", (1, 0), (1, 0), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t

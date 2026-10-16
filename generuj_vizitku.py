#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generátor vizitek Spring Walk podle schváleného vzoru
==================================
Šablonou je tisková vizitka (sablona_vizitka.pdf, CMYK, spadávka 3 mm,
ořezové značky). Generuje se pouze osobní strana:

- jméno na 1. řádku, příjmení na 2. řádku (barevný přechod oranžová -> navy)
- titul nad jménem (vlastní krátký přechod podle vzoru)
- pozice vlevo, kontakty vpravo (Nunito Sans Bold, tracking podle vzoru)
- QR kód (vCard) vpravo nahoře na místě původního QR

Použití:
    python generuj_vizitku.py --data "Mgr.<TAB>Kristýna<TAB>..."
    python generuj_vizitku.py --tsv osoby.tsv

Pořadí sloupců:
    Titul | Jméno | Příjmení | Firma | Pozice | Telefon | E-mail | URL | Adresa
"""

import argparse
import csv
import io
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import pymupdf as fitz
import segno
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont as FontToolsFont
from reportlab.lib.colors import CMYKColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# ----------------------------------------------------------------------------
# Vzdálenosti jsou měřené od TrimBoxu na straně 2 schváleného tiskového
# vzoru vizitky-SW-90x50mm.pdf. Vnější rozměr PDF není rozměrem vizitky.
# ----------------------------------------------------------------------------
TEMPLATE = Path(__file__).parent / "sablona_vizitka.pdf"
TEMPLATE_PAGE = 0                      # čistá jednostránková osobní šablona
with fitz.open(TEMPLATE) as _template:
    if len(_template) != 1:
        raise ValueError("Použijte čistou šablonu připravenou ze strany 2 vzoru.")
    PAGE_W, PAGE_H = _template[0].rect.width, _template[0].rect.height
    TRIM = _template[0].trimbox

# jméno + příjmení: sytější řez (ExtraBold ~800); drobné texty: Bold (~700);
# pozice/role: Regular (~400). Fonty mají unikátní interní názvy kvůli PDF.
NAME_FONT_PATH = Path(__file__).parent / "fonts" / "SpringWalkExtraBold.ttf"
NAME_FONT = "SpringWalkExtraBold"
FONT_PATH = Path(__file__).parent / "fonts" / "SpringWalkBold.ttf"
FONT_NAME = "SpringWalkBold"
REGULAR_FONT_PATH = Path(__file__).parent / "fonts" / "SpringWalkRegular.ttf"
REGULAR_FONT = "SpringWalkRegular"

# CMYK barvy ze vzoru
COL_TEXT = CMYKColor(0, 0, 0, 1)
COL_QR = CMYKColor(0, 0, 0, 1)
GRAD_ORANGE = CMYKColor(0.07, 0.82, 0.85, 0.01)
GRAD_NAVY = CMYKColor(0.95, 0.72, 0.38, 0.31)
GRAD_TITUL_END = CMYKColor(0.324132, 0.707759, 0.513268, 0.352789)

# velké jméno (2 řádky) – baseline zdola
NAME_X = TRIM.x0 + 15.3085
LINE1_BASELINE = PAGE_H - (TRIM.y0 + 42.1885)
LINE2_BASELINE = PAGE_H - (TRIM.y0 + 65.1885)
NAME_SIZE = 23.0
NAME_MAX_W = 160.0                     # aby jméno nezasáhlo do QR

# Titul před jménem (Mgr., Mgr. Bc.). Prázdný titul neposouvá jméno.
TITUL_X = TRIM.x0 + 16.3825
TITUL_BASELINE = PAGE_H - (TRIM.y0 + 19.245)
TITUL_SIZE = 8.0

# malé texty, 8 pt, tracking podle vzoru
SMALL_SIZE = 8.0
SMALL_TRACKING = 0.145                 # pt navíc mezi znaky
POS_X = TRIM.x0 + 16.3043
RIGHT_EDGE = TRIM.x0 + 232.4405
POS_BASELINE = PAGE_H - (TRIM.y0 + 83.3936)
PHONE_BASELINE = POS_BASELINE
EMAIL_BASELINE = PAGE_H - (TRIM.y0 + 98.0733)
WEB_BASELINE = PAGE_H - (TRIM.y0 + 112.752)
ADDR_BASELINE = PAGE_H - (TRIM.y0 + 127.4327)

# QR – stejné místo a velikost jako ve vzoru (vpravo nahoře)
QR_RECT_TOPDOWN = fitz.Rect(TRIM.x0 + 184.2515, TRIM.y0 + 17.005,
                           TRIM.x0 + 232.4405, TRIM.y0 + 65.194)


# ----------------------------------------------------------------------------
# Pomocné funkce
# ----------------------------------------------------------------------------
def norm_phone_display(phone: str) -> str:
    p = phone.strip()
    return p if p.startswith("+") else "+" + p


def norm_phone_qr(phone: str) -> str:
    return "+" + re.sub(r"[^\d]", "", phone)


def norm_web_display(url: str) -> str:
    u = re.sub(r"^https?://", "", url.strip(), flags=re.I)
    u = re.sub(r"^www\.", "", u, flags=re.I)
    return u.rstrip("/")


def norm_address(addr: str) -> str:
    parts = [p.strip().rstrip(",") for p in addr.replace("\r", "").split("\n")]
    return ", ".join(p for p in parts if p)


def safe_filename(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower() or "vizitka"


def build_vcard(titul, jmeno, prijmeni, firma, telefon, email, url) -> str:
    fn = " ".join(x for x in (titul, jmeno, prijmeni) if x)
    return "\r\n".join([
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{prijmeni};{jmeno};;{titul}",
        f"FN:{fn}",
        f"ORG:{firma}",
        f"TEL:{norm_phone_qr(telefon)}",
        f"EMAIL:{email.strip()}",
        f"URL:{url.strip()}",
        "END:VCARD",
    ])


def fit_size(text: str, base_size: float, max_w: float,
             font: str = FONT_NAME) -> float:
    w = pdfmetrics.stringWidth(text, font, base_size)
    return base_size if w <= max_w else base_size * max_w / w


def tracked_width(text: str, size: float, tracking: float) -> float:
    return (pdfmetrics.stringWidth(text, FONT_NAME, size)
            + max(len(text) - 1, 0) * tracking)


@lru_cache(maxsize=3)
def font_geometry(path: Path):
    font = FontToolsFont(path)
    return font, font.getGlyphSet(), font.getBestCmap()


def ink_bounds(text: str, path: Path, size: float) -> tuple[float, float]:
    """Visible horizontal bounds, excluding the first/last glyph bearings."""
    font, glyphs, cmap = font_geometry(path)
    cursor = 0
    left, right = float("inf"), float("-inf")
    for char in text:
        glyph_name = cmap[ord(char)]
        pen = BoundsPen(glyphs)
        glyphs[glyph_name].draw(pen)
        if pen.bounds is not None:
            left = min(left, cursor + pen.bounds[0])
            right = max(right, cursor + pen.bounds[2])
        cursor += font["hmtx"][glyph_name][0]
    if left == float("inf"):
        raise ValueError("Text pro barevný přechod nesmí být prázdný.")
    scale = size / font["head"].unitsPerEm
    return left * scale, right * scale


# ----------------------------------------------------------------------------
# Overlay vrstva (reportlab -> PDF v paměti, vše CMYK)
# ----------------------------------------------------------------------------
def make_overlay(person: dict) -> bytes:
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
    pdfmetrics.registerFont(TTFont(NAME_FONT, str(NAME_FONT_PATH)))
    pdfmetrics.registerFont(TTFont(REGULAR_FONT, str(REGULAR_FONT_PATH)))

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))

    def gradient_text(text, x, baseline, size, gx0, gw, col_from, col_to,
                      font=FONT_NAME):
        c.saveState()
        t = c.beginText(x, baseline)
        t.setFont(font, size)
        t.setTextRenderMode(7)          # text jako ořezová maska
        t.textLine(text)
        c.drawText(t)
        c.linearGradient(gx0, baseline, gx0 + gw, baseline,
                         (col_from, col_to), extend=True)
        c.restoreState()

    # jméno + příjmení (sytější řez, společná geometrie přechodu jako ve vzoru)
    name_size = min(fit_size(person[key], NAME_SIZE, NAME_MAX_W, NAME_FONT)
                    for key in ("jmeno", "prijmeni"))
    bounds = [ink_bounds(person[key], NAME_FONT_PATH, name_size)
              for key in ("jmeno", "prijmeni")]
    gx0 = NAME_X + min(left for left, right in bounds)
    gx1 = NAME_X + max(right for left, right in bounds)
    for key, baseline in (("jmeno", LINE1_BASELINE), ("prijmeni", LINE2_BASELINE)):
        gradient_text(person[key], NAME_X, baseline, name_size,
                      gx0, gx1 - gx0, GRAD_ORANGE, GRAD_NAVY, font=NAME_FONT)

    # Titul nad jménem, řez Bold a vlastní přechod podle originálu.
    if person["titul"]:
        tl, tr = ink_bounds(person["titul"], FONT_PATH, TITUL_SIZE)
        gradient_text(person["titul"], TITUL_X, TITUL_BASELINE, TITUL_SIZE,
                      TITUL_X + tl, tr - tl, GRAD_ORANGE, GRAD_TITUL_END)

    # pozice/role v Regular řezu; kontakty v Bold (tracking podle vzoru)
    c.setFillColor(COL_TEXT)

    def small_left(x, baseline, text, font=FONT_NAME, size=SMALL_SIZE):
        t = c.beginText(x, baseline)
        t.setFont(font, size)
        t.setCharSpace(SMALL_TRACKING)
        t.textLine(text)
        c.drawText(t)

    def small_right(right_x, baseline, text, font=FONT_NAME):
        w = (pdfmetrics.stringWidth(text, font, SMALL_SIZE)
             + max(len(text) - 1, 0) * SMALL_TRACKING)
        small_left(right_x - w, baseline, text, font)

    role_lines = person["pozice"].splitlines()
    role_size = SMALL_SIZE
    if len(role_lines) > 1:
        # Víceřádková role zůstává vlevo a nezasahuje do kontaktů.
        contacts = [
            norm_phone_display(person["telefon"]),
            person["email"].strip(),
            norm_web_display(person["url"]),
        ]
        role_max_w = min(
            RIGHT_EDGE - tracked_width(text, SMALL_SIZE, SMALL_TRACKING)
            for text in contacts
        ) - POS_X - 8.0

        def role_width(text, size):
            return (pdfmetrics.stringWidth(text, REGULAR_FONT, size)
                    + max(len(text) - 1, 0) * SMALL_TRACKING)

        sizes = (8.0, 7.75, 7.5, 7.25, 7.0, 6.75, 6.5, 6.25, 6.0)
        # Upřednostnit zadané konce řádků. Další zalomení použít jen tehdy,
        # pokud se řádky nevejdou ani při minimální čitelné velikosti 6 pt.
        fixed_sizes = [size for size in sizes if len(role_lines) <= 4
                       and all(role_width(line, size) <= role_max_w
                               for line in role_lines)]
        for role_size in fixed_sizes or sizes:
            if fixed_sizes:
                break
            wrapped = []
            for paragraph in person["pozice"].splitlines():
                line = ""
                for word in paragraph.split():
                    candidate = (line + " " + word).strip()
                    if line and role_width(candidate, role_size) > role_max_w:
                        wrapped.append(line)
                        line = word
                    else:
                        line = candidate
                if line:
                    wrapped.append(line)
            if (len(wrapped) <= 4
                    and all(role_width(line, role_size) <= role_max_w
                            for line in wrapped)):
                role_lines = wrapped
                break
        else:
            raise ValueError("Víceřádková pozice se nevejde do levého sloupce.")

    for index, line in enumerate(role_lines):
        small_left(POS_X, POS_BASELINE - index * 10.0, line,
                   REGULAR_FONT, size=role_size)
    small_right(RIGHT_EDGE, PHONE_BASELINE, norm_phone_display(person["telefon"]))
    small_right(RIGHT_EDGE, EMAIL_BASELINE, person["email"].strip())
    small_right(RIGHT_EDGE, WEB_BASELINE, norm_web_display(person["url"]))
    small_right(RIGHT_EDGE, ADDR_BASELINE, norm_address(person["adresa"]))

    # QR kód (vektor, CMYK) na místě původního
    vcard = build_vcard(
        person["titul"], person["jmeno"], person["prijmeni"],
        person["firma"], person["telefon"], person["email"], person["url"],
    )
    qr = segno.make(vcard, error="l", micro=False)
    n = qr.symbol_size(border=0)[0]

    q = QR_RECT_TOPDOWN
    qr_size = q.width
    module = qr_size / n
    ox = q.x0
    oy = PAGE_H - q.y0                  # horní hrana QR zdola

    c.setFillColor(COL_QR)
    for ry, row in enumerate(qr.matrix_iter(scale=1, border=0)):
        for rx, dark in enumerate(row):
            if dark:
                c.rect(ox + rx * module, oy - (ry + 1) * module,
                       module + 0.01, module + 0.01, stroke=0, fill=1)
    c.showPage()
    c.save()
    return buf.getvalue()


# ----------------------------------------------------------------------------
# Hlavní generování
# ----------------------------------------------------------------------------
def generate(person: dict, out_dir: Path) -> Path:
    doc = fitz.open(TEMPLATE)
    doc.select([TEMPLATE_PAGE])
    page = doc[0]
    # Šablona je čistá; není nutné zakrývat žádné původní osobní údaje.
    overlay = fitz.open("pdf", make_overlay(person))
    page.show_pdf_page(page.rect, overlay, 0)

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"vizitka_{safe_filename(person['prijmeni'] + '_' + person['jmeno'])}.pdf"
    doc.save(out, garbage=3, deflate=True)
    doc.close()
    return out


COLS = ["titul", "jmeno", "prijmeni", "firma", "pozice",
        "telefon", "email", "url", "adresa"]


def parse_row(fields) -> dict:
    fields = [f.strip().strip('"') for f in fields]
    if len(fields) != len(COLS):
        raise SystemExit(
            f"Očekávám {len(COLS)} sloupců ({' | '.join(COLS)}), "
            f"dostal jsem {len(fields)}: {fields}"
        )
    return dict(zip(COLS, fields))


def main():
    ap = argparse.ArgumentParser(description="Generátor vizitek Spring Walk")
    ap.add_argument("--data", help="údaje jedné osoby oddělené tabulátorem")
    ap.add_argument("--tsv", type=Path, help="TSV soubor, jedna osoba na řádek")
    ap.add_argument("--out", type=Path, default=Path("output"),
                    help="výstupní složka (výchozí: output)")
    args = ap.parse_args()

    people = []
    if args.data:
        people.append(parse_row(args.data.replace("\\t", "\t").split("\t")))
    if args.tsv:
        with open(args.tsv, encoding="utf-8") as f:
            for row in csv.reader(f, delimiter="\t"):
                if row and any(x.strip() for x in row):
                    people.append(parse_row(row))
    if not people:
        ap.error("Zadejte --data nebo --tsv.")

    for person in people:
        out = generate(person, args.out)
        print(f"OK  {person['jmeno']} {person['prijmeni']} -> {out}")


if __name__ == "__main__":
    main()

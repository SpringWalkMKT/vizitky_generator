#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generátor vizitek Spring Walk (v2)
==================================
Šablonou je tisková vizitka (sablona_vizitka.pdf, CMYK, spadávka 3 mm,
ořezové značky). Generuje se pouze osobní strana:

- jméno na 1. řádku, příjmení na 2. řádku (barevný přechod oranžová -> navy)
- titul pod příjmením (vlastní krátký přechod, jako "DiS." ve vzoru)
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
from pathlib import Path

import fitz  # PyMuPDF
import segno
from reportlab.lib.colors import CMYKColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# ----------------------------------------------------------------------------
# Konstanty šablony (změřeno z tiskového PDF; souřadnice stránky včetně
# spadávky a značek, strana 321.118 x 207.732 pt, TrimBox od 33 pt)
# ----------------------------------------------------------------------------
TEMPLATE = Path(__file__).parent / "sablona_vizitka.pdf"
TEMPLATE_PAGE = 1                      # osobní strana = 2. stránka šablony
PAGE_W, PAGE_H = 321.118, 207.732

# jméno + příjmení: sytější řez (ExtraBold ~800); drobné texty: Bold (~700);
# pozice/role: Regular (~400). Fonty mají unikátní interní názvy kvůli PDF.
NAME_FONT_PATH = Path(__file__).parent / "fonts" / "SpringWalkExtraBold.ttf"
NAME_FONT = "SpringWalkExtraBold"
FONT_PATH = Path(__file__).parent / "fonts" / "SpringWalkBold.ttf"
FONT_NAME = "SpringWalkBold"
REGULAR_FONT_PATH = Path(__file__).parent / "fonts" / "SpringWalkRegular.ttf"
REGULAR_FONT = "SpringWalkRegular"

# CMYK barvy ze vzoru
COL_TEXT = CMYKColor(0.844, 0.758, 0.582, 0.68)     # texty
COL_QR = CMYKColor(0.965, 0.699, 0.457, 0.859)      # QR
GRAD_ORANGE = CMYKColor(0.0234375, 0.832031, 0.9375, 0.00390625)
GRAD_NAVY = CMYKColor(1, 0.785156, 0.355469, 0.246094)
GRAD_TITUL_END = CMYKColor(0.351562, 0.792969, 0.5625, 0.210937)

# velké jméno (2 řádky) – baseline zdola
NAME_X = 49.44
LINE1_BASELINE = PAGE_H - 65.64        # jméno
LINE2_BASELINE = PAGE_H - 88.92        # příjmení
NAME_SIZE = 24.0
NAME_MAX_W = 160.0                     # aby jméno nezasáhlo do QR
GRAD_X0, GRAD_W = 49.545, 146.686      # geometrie přechodu ze vzoru

# titul pod příjmením ("DiS." / "Mgr." ...)
TITUL_BASELINE = PAGE_H - 103.91
TITUL_SIZE = 8.5

# oblast původního jména + titulu – překryje se bílou (shora dolů);
# nesmí zasáhnout QR (začíná x 217.7) ani pozici (začíná y 107.7)
NAME_COVER_RECT = fitz.Rect(44.0, 44.0, 212.0, 106.0)

# malé texty, 8 pt, tracking podle vzoru
SMALL_SIZE = 8.0
SMALL_TRACKING = 0.145                 # pt navíc mezi znaky
POS_X = NAME_X                         # pozice zarovnaná přesně pod jméno
RIGHT_EDGE = 265.43
POS_BASELINE = PAGE_H - 115.95
PHONE_BASELINE = PAGE_H - 116.07
EMAIL_BASELINE = PAGE_H - 130.75
WEB_BASELINE = PAGE_H - 145.43
ADDR_BASELINE = PAGE_H - 160.43

# QR – stejné místo a velikost jako ve vzoru (vpravo nahoře)
QR_RECT_TOPDOWN = fitz.Rect(217.93, 50.88, 265.43, 98.38)   # 47.5 pt


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
    s1 = fit_size(person["jmeno"], NAME_SIZE, NAME_MAX_W, NAME_FONT)
    s2 = fit_size(person["prijmeni"], NAME_SIZE, NAME_MAX_W, NAME_FONT)
    gradient_text(person["jmeno"], NAME_X, LINE1_BASELINE, s1,
                  GRAD_X0, GRAD_W, GRAD_ORANGE, GRAD_NAVY, font=NAME_FONT)
    gradient_text(person["prijmeni"], NAME_X, LINE2_BASELINE, s2,
                  GRAD_X0, GRAD_W, GRAD_ORANGE, GRAD_NAVY, font=NAME_FONT)

    # titul pod příjmením s vlastním krátkým přechodem, zarovnaný pod jméno
    if person["titul"]:
        tw = pdfmetrics.stringWidth(person["titul"], NAME_FONT, TITUL_SIZE)
        gradient_text(person["titul"], NAME_X, TITUL_BASELINE, TITUL_SIZE,
                      NAME_X, tw, GRAD_ORANGE, GRAD_TITUL_END, font=NAME_FONT)

    # pozice/role v Regular řezu; kontakty v Bold (tracking podle vzoru)
    c.setFillColor(COL_TEXT)

    def small_left(x, baseline, text, font=FONT_NAME):
        t = c.beginText(x, baseline)
        t.setFont(font, SMALL_SIZE)
        t.setCharSpace(SMALL_TRACKING)
        t.textLine(text)
        c.drawText(t)

    def small_right(right_x, baseline, text, font=FONT_NAME):
        w = (pdfmetrics.stringWidth(text, font, SMALL_SIZE)
             + max(len(text) - 1, 0) * SMALL_TRACKING)
        small_left(right_x - w, baseline, text, font)

    small_left(POS_X, POS_BASELINE, person["pozice"], REGULAR_FONT)
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
    doc.select([TEMPLATE_PAGE])         # jen osobní strana
    page = doc[0]

    # 1) odstranit původní živé texty (pozice + kontakty)
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                page.add_redact_annot(fitz.Rect(span["bbox"]))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE)

    # 2) překrýt původní jméno + titul a původní QR bílou
    page.draw_rect(NAME_COVER_RECT, color=None, fill=(1, 1, 1))
    qr_cover = QR_RECT_TOPDOWN + (-2, -2, 2, 2)
    page.draw_rect(qr_cover, color=None, fill=(1, 1, 1))

    # 3) nová vrstva (jméno, titul, texty, QR)
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

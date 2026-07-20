#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generátor vizitek Spring Walk
=============================
Vezme šablonu vizitky (.ai / .pdf z Illustratoru), na přední straně nahradí
jméno (2 řádky s barevným přechodem + spirála za příjmením), pozici
a kontakty, a na zadní stranu doplní QR kód s vizitkou (vCard).

Použití:
    # jedna osoba (údaje oddělené tabulátorem, stejně jako z Excelu):
    python generuj_vizitku.py sablona.ai --data "Mgr.<TAB>Kristýna<TAB>..."

    # dávkově ze souboru (TSV, jedna osoba na řádek):
    python generuj_vizitku.py sablona.ai --tsv osoby.tsv

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
from reportlab.lib.colors import Color, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# ----------------------------------------------------------------------------
# Konstanty šablony (změřeno z spring_walk_vizitka.ai, strana 90 x 50 mm)
# ----------------------------------------------------------------------------
PAGE_W, PAGE_H = 255.12, 141.73          # velikost strany v bodech (pt)

FONT_PATH = Path(__file__).parent / "fonts" / "NunitoSans-ExtraLight.ttf"
FONT_NAME = "NunitoSans-ExtraLight"

# barvy z originálu (DeviceRGB)
COL_TEXT = Color(0x1E / 255, 0x1E / 255, 0x1E / 255)          # #1E1E1E
COL_GRAD_START = (0.870588, 0.286275, 0.180392)               # oranžovočervená
COL_GRAD_END = (0.109804, 0.247059, 0.364706)                 # tmavě modrá
COL_QR = Color(*COL_GRAD_END)                                  # QR v navy

# velké jméno – dva řádky, souřadnice baseline zdola (PDF systém)
NAME_X = 16.59
LINE1_BASELINE = 108.40        # titul + jméno
LINE2_BASELINE = 85.91         # příjmení (+ spirála za ním)
NAME_SIZE = 24.0
NAME_MAX_W = 195.0             # při delším textu se řádek automaticky zmenší
GRAD_X0, GRAD_W = 16.54, 146.69   # geometrie barevného přechodu z originálu

# spirála za příjmením – výřez z originální šablony (souřadnice shora dolů)
SPIRAL_CLIP = fitz.Rect(148.3, 38.9, 163.3, 57.7)
SPIRAL_GAP = 3.0               # mezera mezi koncem příjmení a spirálou

# oblast původního jména (křivky) – překryje se bílou; nesmí zasáhnout
# statický nápis "SPRING WALK" (začíná ~65 pt shora)
NAME_COVER_RECT = fitz.Rect(12.0, 11.0, 176.0, 63.5)

# malé texty, 8 pt; baseline zdola
SMALL_SIZE = 8.0
POS_X, POS_BASELINE = 16.5, PAGE_H - 82.94        # pozice, zarovnáno vlevo
RIGHT_EDGE = 231.2                                 # pravý okraj kontaktů
PHONE_BASELINE = PAGE_H - 83.07
EMAIL_BASELINE = PAGE_H - 97.74
WEB_BASELINE = PAGE_H - 112.42
ADDR_BASELINE = PAGE_H - 127.43

# QR na zadní straně – bílá dlaždice se zaoblenými rohy pod logem
QR_PLATE_SIZE = 50.0            # pt (~17.6 mm)
QR_PLATE_TOP = 88.0             # shora
QR_PLATE_RADIUS = 4.0
QR_MARGIN = 4.0                 # bílý okraj = tichá zóna QR


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
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{prijmeni};{jmeno};;{titul}",
        f"FN:{fn}",
        f"ORG:{firma}",
        f"TEL:{norm_phone_qr(telefon)}",
        f"EMAIL:{email.strip()}",
        f"URL:{url.strip()}",
        "END:VCARD",
    ]
    return "\r\n".join(lines)


def fit_size(text: str, base_size: float, max_w: float) -> float:
    """Zmenší písmo, pokud by text přesáhl max_w."""
    w = pdfmetrics.stringWidth(text, FONT_NAME, base_size)
    return base_size if w <= max_w else base_size * max_w / w


# ----------------------------------------------------------------------------
# Overlay vrstva (reportlab -> PDF v paměti)
# ----------------------------------------------------------------------------
def make_overlay(person: dict) -> tuple[bytes, float]:
    """Vrátí (PDF bajty overlay vrstvy, x-pozice spirály za příjmením)."""
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))

    # ---------- STRANA 1 ----------
    line1 = " ".join(x for x in (person["titul"], person["jmeno"]) if x)
    line2 = person["prijmeni"]

    def gradient_line(text, baseline, size):
        c.saveState()
        t = c.beginText(NAME_X, baseline)
        t.setFont(FONT_NAME, size)
        t.setTextRenderMode(7)          # text jako ořezová maska
        t.textLine(text)
        c.drawText(t)
        c.linearGradient(
            GRAD_X0, baseline, GRAD_X0 + GRAD_W, baseline,
            (Color(*COL_GRAD_START), Color(*COL_GRAD_END)),
            extend=True,
        )
        c.restoreState()

    s1 = fit_size(line1, NAME_SIZE, NAME_MAX_W)
    s2 = fit_size(line2, NAME_SIZE, NAME_MAX_W - SPIRAL_CLIP.width - SPIRAL_GAP)
    gradient_line(line1, LINE1_BASELINE, s1)
    gradient_line(line2, LINE2_BASELINE, s2)
    spiral_x = NAME_X + pdfmetrics.stringWidth(line2, FONT_NAME, s2) + SPIRAL_GAP

    # pozice + kontakty
    c.setFillColor(COL_TEXT)
    c.setFont(FONT_NAME, SMALL_SIZE)
    c.drawString(POS_X, POS_BASELINE, person["pozice"])
    c.drawRightString(RIGHT_EDGE, PHONE_BASELINE, norm_phone_display(person["telefon"]))
    c.drawRightString(RIGHT_EDGE, EMAIL_BASELINE, person["email"].strip())
    c.drawRightString(RIGHT_EDGE, WEB_BASELINE, norm_web_display(person["url"]))
    c.drawRightString(RIGHT_EDGE, ADDR_BASELINE, norm_address(person["adresa"]))
    c.showPage()

    # ---------- STRANA 2: QR ----------
    vcard = build_vcard(
        person["titul"], person["jmeno"], person["prijmeni"],
        person["firma"], person["telefon"], person["email"], person["url"],
    )
    qr = segno.make(vcard, error="l", micro=False)
    n = qr.symbol_size(border=0)[0]

    plate_x = (PAGE_W - QR_PLATE_SIZE) / 2
    plate_y = PAGE_H - QR_PLATE_TOP - QR_PLATE_SIZE

    c.setFillColor(white)
    c.roundRect(plate_x, plate_y, QR_PLATE_SIZE, QR_PLATE_SIZE,
                QR_PLATE_RADIUS, stroke=0, fill=1)

    qr_size = QR_PLATE_SIZE - 2 * QR_MARGIN
    module = qr_size / n
    ox = plate_x + QR_MARGIN
    oy = plate_y + QR_MARGIN + qr_size

    c.setFillColor(COL_QR)
    for ry, row in enumerate(qr.matrix_iter(scale=1, border=0)):
        for rx, dark in enumerate(row):
            if dark:
                c.rect(ox + rx * module, oy - (ry + 1) * module,
                       module + 0.01, module + 0.01, stroke=0, fill=1)
    c.showPage()

    c.save()
    return buf.getvalue(), spiral_x


# ----------------------------------------------------------------------------
# Hlavní generování
# ----------------------------------------------------------------------------
def generate(template_path: Path, person: dict, out_dir: Path) -> Path:
    doc = fitz.open(template_path)
    src = fitz.open(template_path)      # nedotčená kopie pro výřez spirály
    p1, p2 = doc[0], doc[1]

    # 1) odstranit původní živé texty na straně 1 (pozice + kontakty)
    for block in p1.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                p1.add_redact_annot(fitz.Rect(span["bbox"]))
    p1.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                        graphics=fitz.PDF_REDACT_LINE_ART_NONE)

    # 2) překrýt původní jméno (křivky) bílým obdélníkem
    p1.draw_rect(NAME_COVER_RECT, color=None, fill=(1, 1, 1))

    # 3) nová vrstva (texty + QR)
    overlay_bytes, spiral_x = make_overlay(person)
    overlay = fitz.open("pdf", overlay_bytes)
    p1.show_pdf_page(p1.rect, overlay, 0)
    p2.show_pdf_page(p2.rect, overlay, 1)

    # 4) spirála za příjmením – vektorový výřez z originální šablony
    target = fitz.Rect(
        spiral_x, SPIRAL_CLIP.y0,
        spiral_x + SPIRAL_CLIP.width, SPIRAL_CLIP.y1,
    )
    p1.show_pdf_page(target, src, 0, clip=SPIRAL_CLIP)

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"vizitka_{safe_filename(person['prijmeni'] + '_' + person['jmeno'])}.pdf"
    doc.save(out, garbage=3, deflate=True)
    doc.close()
    src.close()
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
    ap.add_argument("template", type=Path, help="šablona .ai / .pdf")
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
        out = generate(args.template, person, args.out)
        print(f"OK  {person['jmeno']} {person['prijmeni']} -> {out}")


if __name__ == "__main__":
    main()

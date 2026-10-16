"""Extract and clear page 2 of the approved print reference."""

import argparse
from pathlib import Path

import pymupdf


def prepare(source: Path, destination: Path):
    with pymupdf.open(source) as original, pymupdf.open() as clean:
        reference = original[1]
        page = clean.new_page(width=reference.rect.width, height=reference.rect.height)
        page.set_trimbox(reference.trimbox)
        page.set_bleedbox(reference.bleedbox)
        bleed = reference.bleedbox

        def outside(a, b):
            return (max(a.x, b.x) < bleed.x0 or min(a.x, b.x) > bleed.x1
                    or max(a.y, b.y) < bleed.y0 or min(a.y, b.y) > bleed.y1)

        # Rebuild only the printer marks. A redaction cannot remove the original
        # name reliably because PDF shadings inside glyph clips survive it.
        marks = 0
        for drawing in reference.get_drawings():
            items = drawing["items"]
            if (drawing["type"] != "s" or not items
                    or not all(item[0] == "l" and outside(item[1], item[2])
                               for item in items)):
                continue
            shape = page.new_shape()
            for _, start, end in items:
                shape.draw_line(start, end)
            # The source uses a white under-stroke and registration black.
            ink = 0 if min(drawing["color"]) > 0.9 else 1
            shape.finish(color=(ink, ink, ink, ink), width=drawing["width"],
                         closePath=False)
            shape.commit()
            marks += len(items)
        if marks < 8:
            raise ValueError("Referenční strana neobsahuje očekávané ořezové značky.")
        clean.save(destination, garbage=4, deflate=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "sablona_vizitka.pdf")
    args = ap.parse_args()
    prepare(args.source, args.out)

import csv
import tempfile
import unittest
from pathlib import Path

import pymupdf

import generuj_vizitku as generator

SAMPLE = dict(titul="Mgr.", jmeno="Filip", prijmeni="Glézl", firma="Spring Walk",
              pozice="Advokát", telefon="420 737 879 262", email="glezl@springwalk.cz",
              url="https://www.springwalk.cz/", adresa="ZET.office, Lazaretní 925/9, 615 00 Brno")


def spans(page):
    return [span for block in page.get_text("dict")["blocks"]
            if block["type"] == 0 for line in block["lines"]
            for span in line["spans"]]


class PrintLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (Path(generator.__file__).parent / "osoby.tsv").open(encoding="utf-8") as stream:
            cls.people = [generator.parse_row(row) for row in csv.reader(stream, delimiter="\t")
                          if row and any(field.strip() for field in row)]

    def test_template_is_empty_inside_print_area(self):
        with pymupdf.open(generator.TEMPLATE) as doc:
            self.assertEqual(len(doc), 1)
            page = doc[0]
            self.assertAlmostEqual(page.trimbox.width * 25.4 / 72, 90, places=2)
            self.assertAlmostEqual(page.trimbox.height * 25.4 / 72, 50, places=2)
            self.assertAlmostEqual((page.trimbox.x0 - page.bleedbox.x0) * 25.4 / 72, 3, places=2)
            pix = page.get_pixmap(clip=page.bleedbox)
            self.assertEqual(set(pix.samples), {255}, "Template still contains personal artwork")

    def test_title_is_above_name_and_omitting_it_keeps_name_position(self):
        person = dict(SAMPLE)
        origins = []
        for title in ("Mgr. Bc.", ""):
            person["titul"] = title
            with pymupdf.open(stream=generator.make_overlay(person), filetype="pdf") as doc:
                items = spans(doc[0])
                name = next(item for item in items if item["text"] == person["jmeno"])
                origins.append(name["origin"])
                self.assertAlmostEqual(name["size"], 23, places=2)
                if title:
                    title_span = next(item for item in items if item["text"] == title)
                    # PDF text boxes include unused ascender/descender space;
                    # check the actual line origins rather than those boxes.
                    self.assertLess(title_span["origin"][1], name["origin"][1] - 15)
                    self.assertAlmostEqual(title_span["size"], 8, places=2)
                else:
                    self.assertFalse(any(item["origin"][1] < name["origin"][1] for item in items))
        self.assertEqual(origins[0], origins[1])

    def test_short_name_reaches_blue_at_right_edge(self):
        person = dict(SAMPLE)
        with pymupdf.open(stream=generator.make_overlay(person), filetype="pdf") as doc:
            page = doc[0]
            surname = next(item for item in spans(page) if item["text"] == "Glézl")
            box = pymupdf.Rect(surname["bbox"])
            box.x0 = box.x1 - 7
            pix = page.get_pixmap(clip=box, matrix=pymupdf.Matrix(4, 4))
            rgb = list(zip(pix.samples[0::3], pix.samples[1::3], pix.samples[2::3]))
            blue = [pixel for pixel in rgb if pixel[2] > pixel[0] + 15 and max(pixel) < 180]
            self.assertGreater(len(blue), 30, "Short surname never reaches navy blue")
            shading = "\n".join(doc.xref_object(i) for i in range(1, doc.xref_length()))
            self.assertIn("/DeviceCMYK", shading)

    def test_long_role_does_not_overlap_contacts_or_address(self):
        person = dict(SAMPLE, titul="", jmeno="Milan", prijmeni="Závora",
                      telefon="420 775 224 765", email="zavora@springwalk.cz",
                      url="https://www.vizovakancelar.cz/",
                      pozice="poradce pro pobyt cizinců na území ČR\nobchodní attaché Jihomoravského kraje v Ukrajině")
        with pymupdf.open(stream=generator.make_overlay(person), filetype="pdf") as doc:
            items = spans(doc[0])
            roles = [item for item in items if "Regular" in item["font"]]
            contacts = [item for item in items if item["text"] in
                        (generator.norm_phone_display(person["telefon"]), person["email"],
                         generator.norm_web_display(person["url"]), generator.norm_address(person["adresa"]))]
            self.assertGreater(len(roles), 1)
            self.assertLessEqual(len(roles), 4)
            self.assertEqual(" ".join(item["text"] for item in roles), " ".join(person["pozice"].split()))
            for role in roles:
                for contact in contacts:
                    self.assertFalse(pymupdf.Rect(role["bbox"]).intersects(pymupdf.Rect(contact["bbox"])))

    def test_every_tsv_person_exports_with_print_boxes_and_contact_data(self):
        with tempfile.TemporaryDirectory() as folder:
            for person in self.people:
                path = generator.generate(person, Path(folder))
                with pymupdf.open(path) as doc:
                    self.assertEqual(len(doc), 1)
                    self.assertEqual(doc[0].trimbox, generator.TRIM)
                    text = doc[0].get_text()
                    for value in (person["jmeno"], person["prijmeni"], person["email"],
                                  generator.norm_phone_display(person["telefon"]),
                                  generator.norm_web_display(person["url"]),
                                  generator.norm_address(person["adresa"])):
                        self.assertIn(value, text)


if __name__ == "__main__":
    unittest.main()

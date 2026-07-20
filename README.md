# Generátor vizitek Spring Walk

Skript vezme originální šablonu vizitky z Illustratoru (spring_walk_vizitka.ai)
a podle dodaných údajů vygeneruje tiskové PDF (90 x 50 mm, obě strany):

- přední strana: titul + jméno a příjmení s barevným přechodem a spirálou,
  pozice, telefon, e-mail, web a adresa (typografie a rozvržení podle šablony)
- zadní strana: doplněný QR kód (vCard) s titulem, jménem, příjmením, firmou,
  telefonem, e-mailem a URL. Po naskenování telefonem se kontakt rovnou
  nabídne k uložení.

## Instalace

    pip install -r requirements.txt

## Použití

Jedna osoba (údaje oddělené tabulátorem, stačí zkopírovat řádek z Excelu):

    python generuj_vizitku.py spring_walk_vizitka.ai --data "Mgr.	Kristýna	Sasínová	Spring Walk	Advokát	420 608 877 241	sasinova@springwalk.cz	https://www.springwalk.cz/	ZET.office, Lazaretní 925/9, 615 00, Brno-Židenice"

Více osob najednou ze souboru osoby.tsv (jedna osoba na řádek):

    python generuj_vizitku.py spring_walk_vizitka.ai --tsv osoby.tsv

Hotová PDF se ukládají do složky output.

## Pořadí sloupců

    Titul | Jméno | Příjmení | Firma | Pozice | Telefon | E-mail | URL | Adresa

- Titul může zůstat prázdný (prázdná buňka, tabulátory zachovat).
- Adresa může být v uvozovkách i na více řádků (formát z Excelu), skript ji
  spojí do jednoho řádku.
- Telefon se na vizitce zobrazí s +420 a mezerami, do QR jde bez mezer.
- Z URL se na vizitce zobrazí jen doména (springwalk.cz), do QR jde celá adresa.

## GitHub Actions

Ve složce .github/workflows je připravený workflow. Po nahrání repozitáře na
GitHub stačí upravit osoby.tsv a pushnout. Workflow vygeneruje vizitky a
hotová PDF najdete v záložce Actions jako artefakt vizitky-pdf. Jde spustit
i ručně tlačítkem Run workflow.

## Technické poznámky

- Dlouhá jména se automaticky zmenší, aby se vešla na řádek.
- QR kód má 14,8 mm, modul 0,30 mm, korekce chyb L. Tiskněte v kvalitě
  300 dpi a vyšší, po prvním nátisku doporučuji zkušební sken telefonem.
- Písmo Nunito Sans ExtraLight (fonts/) je pod licencí SIL OFL, viz OFL.txt.
- Barvy jsou převzaté z originálu (RGB, stejně jako zdrojový .ai soubor).
  Pokud tiskárna vyžaduje CMYK, nechte konverzi na ní, nebo mi napište.

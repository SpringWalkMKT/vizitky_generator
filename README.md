# Generátor vizitek Spring Walk

Skript generuje osobní stranu vizitky podle tiskové šablony
(sablona_vizitka.pdf, CMYK, spadávka 3 mm, ořezové značky). Zadní strana
s logem se negeneruje, používá se beze změny z originálu.

Na vizitce se podle dodaných údajů nahradí:

- jméno na prvním řádku, příjmení na druhém (řez ExtraBold, barevný přechod
  oranžová - navy)
- titul pod příjmením (ExtraBold, krátký barevný přechod jako "DiS." ve vzoru)
- pozice/role vlevo (řez Regular), telefon, e-mail, web a adresa vpravo (Bold)
- QR kód vpravo nahoře (vCard: titul, jméno, příjmení, firma, telefon,
  e-mail, URL). Po naskenování telefonem se kontakt nabídne k uložení.

Jméno, příjmení, titul i role začínají na jedné svislici (zarovnáno podle
jména). Všechny barvy jsou v CMYK podle originálu.

## Instalace

    pip install -r requirements.txt

## Použití

Jedna osoba (údaje oddělené tabulátorem, stačí zkopírovat řádek z Excelu):

    python generuj_vizitku.py --data "Mgr.	Kristýna	Sasínová	Spring Walk	Advokát	420 608 877 241	sasinova@springwalk.cz	https://www.springwalk.cz/	ZET.office, Lazaretní 925/9, 615 00, Brno-Židenice"

Více osob najednou ze souboru osoby.tsv (jedna osoba na řádek):

    python generuj_vizitku.py --tsv osoby.tsv

Hotová PDF se ukládají do složky output.

## Pořadí sloupců

    Titul | Jméno | Příjmení | Firma | Pozice | Telefon | E-mail | URL | Adresa

- Titul může zůstat prázdný (prázdná buňka, tabulátory zachovat), na vizitce
  se pak řádek s titulem vynechá.
- Adresa může být v uvozovkách i na více řádků (formát z Excelu), skript ji
  spojí do jednoho řádku.
- Telefon se na vizitce zobrazí s +420 a mezerami, do QR jde bez mezer.
- Z URL se na vizitce zobrazí jen doména (springwalk.cz), do QR jde celá adresa.

## GitHub Actions

Ve složce .github/workflows je připravený workflow. Používá akce ve verzích
běžících na Node.js 24 (checkout@v5, setup-python@v6, upload-artifact@v6).
Po nahrání repozitáře na GitHub stačí upravit osoby.tsv a pushnout, nebo
workflow spustit ručně tlačítkem Run workflow v záložce Actions. Hotová PDF
pak najdete takto: záložka Actions, kliknout na konkrétní běh workflow, a dole
na stránce v sekci Artifacts je ke stažení balíček vizitky-pdf.

## Řezy písma

Používá se Nunito Sans (SIL OFL, viz OFL.txt) ve třech vahách s unikátními
interními názvy, aby se v PDF neslévaly:

- SpringWalkExtraBold (800) - jméno, příjmení, titul
- SpringWalkBold (700) - telefon, e-mail, web, adresa
- SpringWalkRegular (400) - pozice/role

## Technické poznámky

- Dlouhá jména se automaticky zmenší, aby nezasáhla do QR kódu.
- QR má 16,8 mm, modul 0,34 mm, korekce chyb L. Po prvním nátisku doporučuji
  zkušební sken telefonem.
- Výstup je jednostránkové PDF osobní strany včetně spadávky a ořezových
  značek, připravené do tiskárny.

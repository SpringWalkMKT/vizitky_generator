# Generátor vizitek Spring Walk

Generuje osobní stranu vizitky podle strany 2 schváleného souboru
`vizitky-SW-90x50mm.pdf` (vzor Jaroslav Zeman). Výstup má ořez 90 × 50 mm,
spadávku 3 mm a vektorové ořezové značky. Druhá strana s logem se negeneruje.

## Sazba podle vzoru

- Titul je nad jménem: Nunito Sans Bold, 8 pt. Prázdný titul se vynechá;
  poloha jména se tím nemění.
- Jméno a příjmení mají společnou velikost 23 pt v řezu ExtraBold.
  Dlouhá jména se zmenší před hranicí QR kódu.
- Oba řádky jména sdílejí vodorovný přechod. Začíná na levém viditelném
  okraji bloku a končí modrou na pravém viditelném okraji delšího řádku.
  Šířka se počítá z obrysů právě sázených písmen, nikoli z původního jména.
- Barvy jména jsou CMYK 7/82/85/1 % → 95/72/38/31 %. Titul používá vlastní
  kratší přechod převzatý ze vzoru. Kontakty a QR jsou černé v CMYK.
- Pozice je vlevo v řezu Regular, kontakty vpravo v řezu Bold (8 pt).
  Víceřádková pozice přednostně zachová zadané konce řádků a podle potřeby
  zmenší písmo až na 6 pt. Pokud se ani tak nevejde, zalomí se do levého
  sloupce, nejvýše na čtyři řádky.
- QR obsahuje vCard s titulem, jménem, příjmením, firmou, telefonem,
  e-mailem a URL. Kód se vykresluje vektorově.

`sablona_vizitka.pdf` je čistá jednostránková šablona. Obsahuje pouze
tiskové značky, žádné původní jméno, kontakty ani QR. Souřadnice se počítají
od TrimBoxu, takže okolní plocha pro tiskové značky nemění polohu sazby.

## Instalace a použití

```sh
pip install -r requirements.txt
python generuj_vizitku.py --tsv osoby.tsv
```

Výstupy se ukládají do `output/`. Jinou složku lze zadat přepínačem `--out`.
Jednu osobu lze předat přes `--data` jako údaje oddělené tabulátory.

Pořadí devíti sloupců bez záhlaví:

```text
Titul | Jméno | Příjmení | Firma | Pozice | Telefon | E-mail | URL | Adresa
```

I prázdný titul musí mít vlastní sloupec. Víceřádkovou adresu nebo pozici
uzavřete v TSV do uvozovek. Na vizitce se adresa spojí do jednoho řádku.
Z URL se pro tisk odstraní protokol a `www.`, do QR jde celá zadaná URL.

## GitHub Actions a ověření

Workflow se spustí ručně, při pull requestu nebo změně dat, generátoru,
šablony, fontů, závislostí či testů. Nejprve ověří sazbu a poté vytvoří
balíček `vizitky-pdf` s jednotlivými osobními PDF.

```sh
python -m unittest discover -s tests -v
```

Testy kontrolují čistotu šablony, tiskové boxy, titul nad jménem,
neměnnou polohu jména bez titulu, modrý konec gradientu krátkého příjmení,
kolize víceřádkové pozice a export osob ze vstupního TSV.

## Obnovení čisté šablony

Ze schváleného originálu lze šablonu znovu připravit:

```sh
python scripts/prepare_template.py /cesta/k/vizitky-SW-90x50mm.pdf
```

Skript z druhé strany převezme tiskové boxy a pouze vektorové značky mimo
spadávku. Původní osobní údaje v křivkách ani jejich gradienty nepřebírá.
Po změně vzoru je nutné znovu zkontrolovat souřadnice sazby a náhledy.

Fonty Nunito Sans používají licenci SIL OFL; viz `fonts/OFL.txt`.
Release `v1.0.0` zachovává předchozí stav generátoru.

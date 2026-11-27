# Auto-shaft

Osadí obdĺžnikové otvory do stien v miestach, kde nimi prechádzajú potrubia, VZT, káblové žľaby a chráničky z linkov profesií, a udržiava ich aktuálne pri zmenách linkov. Pracuje **len v aktívnom pohľade**.

## Postup

1. Otvor 3D pohľad, **section boxom** vymedz riešenú oblasť a zapni linky profesií.
2. Spusti **Auto-shaft** a nastav okno:
  - **1. Rodina otvoru** – predvolene `DGSK_otvor_stena`.
  - **2. Výber konštrukcií** – typy stien, do ktorých sa majú robiť otvory. Typy s „RCO“ v názve sú predoznačené, výber sa dá upraviť.
  - **3. Linky profesií** – kategórie Pipes, Ducts, Cable Trays a Conduits. Po rozbalení môžeš vypnúť jednotlivé linky (napr. Pipes zo SHZ).
  - **4. Odsadenie otvoru** – jednotné alebo podľa kategórie a od akého DN sa majú robiť otvory pre potrubia.
  - **5. Dodatočné informácie** – medzera, pri ktorej sa otvory spoja, a rozmer, od ktorého sa otvor označí na posúdenie statikom.
  - **6. Typ akcie** – osadiť nové otvory, skontrolovať existujúce, upraviť ich a zmazať nepotrebné.
3. Klikni na **Štart**. Plugin všetko vypočíta a zobrazí súhrn, do modelu zatiaľ nič nezapíše.
4. Vyber **Vykonať**, **Len report** (model sa nezmení) alebo **Zrušiť**.
5. Pozri report v okne pyRevit.

Okno si pamätá posledné nastavenia. Celú operáciu vrátiš jedným **Ctrl+Z**.

## Ako sa počíta otvor

- Odsadenie sa meria od **vonkajšieho povrchu prvku vrátane izolácie**.
- Rozmer otvoru = vonkajší rozmer prvku v stene + 2 × odsadenie, **zaokrúhlené nahor na 10 mm**.
- Zarátajú sa aj kolená, odbočky a izolácia.
- Potrubia a chráničky menšie ako nastavené DN sa neosádzajú. Rozhoduje svetlosť potrubia bez izolácie.
- **Šikmý prechod** dostane väčší otvor, ktorý pokryje celý pretiahnutý prienik. Prechody s odklonom nad 5° sú v reporte označené na kontrolu.
- Prvky vedené **pozdĺž v stene** sa neosádzajú, v reporte sú na ručné riešenie.

## Spájanie a veľké otvory

- Otvory, medzi ktorými by ostalo menej steny ako nastavená medzera (predvolene 100 mm), sa spoja do jedného.
- Otvory väčšie ako nastavený rozmer (predvolene 500 mm na šírku alebo výšku) sa osadia, ale v súhrne a reporte sú označené **⚠ posúdiť** pre statika.

## Kontrola existujúcich otvorov

Pri zapnutej kontrole plugin porovná otvory na stenách v aktívnom pohľade s aktuálnym stavom linkov. Pred kontrolou **načítaj všetky linky profesií**.

- **V poriadku** – nič sa nemení.
- **Posunutý alebo zmenený rozmer** – otvor sa upraví (aj po zmene odsadenia).
- **Spojenie** – blízke otvory sa zlúčia: jeden sa zväčší, ostatné sa zmažú.
- **Rozdelenie** – ak sa potrubia spojeného otvoru od seba vzdialia, pôvodný otvor sa upraví a pre ostatné pribudne nový.
- **Bez kolízie alebo prvok zmazaný** – otvor sa zmaže, ak je zapnuté mazanie.
- **Neoverený** – link nie je načítaný. Otvor si zachová rozmer a nikdy sa nezmaže.

## Ručne osadené otvory

- Otvor z rodiny `DGSK_otvor_stena` osadený ručne plugin pri ďalšom behu **prevezme** (musí byť zapnuté osadenie nových, kontrola aj úprava).
- Ručný rozmer ostáva ako minimum: otvor sa môže len **zväčšiť**, nikdy sa nezmenší, neposunie ani nezmaže.
- Ak z ručného otvoru potrubie zmizne, otvor ostane a je v reporte na ručné riešenie.
- Ručné otvory, ktorými neprechádza žiadne potrubie (rezerva), sa nemenia.

## Zdieľaný model

Otvory a steny obsadené iným používateľom sa vynechajú, ostatné sa zapíšu. Vynechané sú v reporte.

## Rodina otvoru

- Generic Model, **wall based**.
- Otvor vycentrovaný na stred, **spodná hrana na Ref. Level**, void zamknutý na obe líca steny.
- Inštančné parametre `Sirka_otvoru` a `Vyska_otvoru` (dĺžka) a `ID_otvor` (text).
- Parameter `ID_otvor` **ručne neprepisuj** – plugin si v ňom pamätá, ku ktorým prvkom otvor patrí.

## Obmedzenia

- Len obdĺžnikové otvory a rovné steny. Oblúkové steny sa preskočia.
- Do stien v nalinkovaných modeloch sa otvory osadiť nedajú.
- Ak otvory zmažeš, plugin ich pri ďalšom behu osadí nanovo podľa pravidiel. Ručné rozmery sa tým stratia.

# DELTA_SK – pyRevit Extension 🛠️

Custom **pyRevit** extension with automation tools for Autodesk Revit. Tools appear in Revit under the **DELTA_SK** tab.

*Slovenská verzia nižšie.*

## Contents

| Panel | Tool | Purpose |
|---|---|---|
| Architecture | **AutoJoin** | Automatic Join Geometry in the active view with structural priority |
| Architecture | **Auto-shaft** | Automatic rectangular openings in selected wall types at clashes with linked MEP models, merging of nearby openings, check and update of existing ones |
| YIT | **TALO kódy** | Naming of element types and parameters per YIT EIR (TALO 2000 codes) |
| Informácie | **Návod** | User guide for all tools, one tab per tool (in Slovak) |

---

## AutoJoin

Joins geometry (Join Geometry) of elements in the **active view only**, never the whole model.

### How to use
1. *(Optional)* Select in Revit the elements that should **not** be joined.
2. Run **AutoJoin** and pick the categories to process.
3. Review the summary (new joins, fixes, skipped elements) and confirm.
4. Check the report in the pyRevit output window. Clicking an element ID zooms to it in the model.

The whole operation is undone with a single **Ctrl+Z**.

### Join priority
* **Structural elements always cut non-structural ones.** Structural = Structural Columns, Structural Framing, Structural Foundation, and Walls/Floors with the *Structural* checkbox enabled.
* **Between structural elements:** foundations > columns > framing > floors > walls.
* **Between non-structural elements** the order is left to Revit.
* **Existing joins** are changed only if a non-structural element cuts a structural one.

### Rules
* Only elements whose volumes **actually overlap** are joined. Elements that only touch by a face (e.g. a wall standing on a slab) are not joined.
* Skipped automatically: wall–wall pairs (handled by Revit wall joins), elements in groups, elements owned by another user (workshared).
* A failed pair does not stop the run. It is skipped and listed in the report with the reason.
* Revit warnings raised during the run are suppressed but listed in the report.

### Supported categories
Walls, Floors, Ceilings, Stairs, Columns, Structural Columns, Structural Foundation, Structural Framing, Roofs.

### Limitations
* **Groups:** Revit does not allow joining a group member with an element outside the group. Joins between members of the same group must be done manually in **Edit Group** (applies to all instances).
* **Stairs** usually do not support Join Geometry and will appear in the report as failed.
* Requires **Revit 2023 or newer**.

## Auto-shaft

Finds clashes between **selected wall types** in the host model and elements in **linked MEP models**, and places rectangular openings around them with a defined clearance. Works in the **active view only**. The easiest way to limit the area is a 3D view with a section box.
Status: **v3, in testing**.

### How to use
1. Open a 3D view (or plan / section), set the section box and switch on the MEP links.
2. Run **Auto-shaft**. One window opens with all settings:
   1. **Opening family** (default `DGSK_otvor_stena`).
   2. **Wall types** – types in the active view that get openings. Types matching the name filter (default `RCO`) are pre-selected. More terms are separated by `;`.
   3. **MEP links** – a tree by Revit category (Pipes, Ducts, Cable Trays, Conduits), each including its fittings (elbows, tees) and insulation. Expanding a category shows only the links that contain it in the active view. Each link can be switched on or off per category (e.g. Pipes from the sprinkler model off).
   4. **Clearance** – uniform, or per category. Pipes and conduits smaller than the set DN are skipped.
   5. **Additional settings** – openings that leave less wall between them than the set distance are merged (default 100 mm); openings larger than the set size (default 500 mm width or height) are marked for structural review. Both values can be changed.
   6. **Action** – place new openings, check existing openings, update moved/changed/merged ones, delete openings without a clash.
3. Click **Start**. Everything is computed first, nothing is written yet.
4. A summary appears (new / to update / to delete). Choose **Execute**, **Report only** (model is not changed) or **Cancel**.
5. Check the report in the pyRevit output window. Clicking an ID zooms to the element.

The window remembers the last settings for the next run.

The whole operation is undone with a single **Ctrl+Z**.

### Processed categories
* **Pipes:** Pipes, Pipe Fittings, Pipe Insulations
* **Ducts:** Ducts, Duct Fittings, Duct Insulations
* **Cable Trays:** Cable Trays, Cable Tray Fittings
* **Conduits:** Conduits, Conduit Fittings

### Rules
* Only walls of the **selected types** in the host model are processed. Curved walls are skipped and listed in the report.
* Only links **visible in the active view** are used.
* Clashes are computed from the **actual geometry intersection**, so fittings and insulation are included. Insulation merges with its pipe or duct into one opening.
* The clearance is measured from the **outer surface of the element including insulation**, not from the pipe axis. Opening size = outer size of the element in the wall + 2 × clearance, **rounded up to 10 mm**.
* Openings that overlap or leave **less wall between them than the set distance** are merged into one. New and existing openings on the same wall are merged together (existing ones only with the check enabled): one existing opening is enlarged, the others are deleted.
* Openings larger than the **set size** (width or height) are placed normally but marked *⚠ check* in the summary and report for structural review.
* Pipes and conduits **smaller than the set DN** are ignored (default DN20, set in the window, 0 = no limit). The limit uses the nominal size without insulation; the opening size includes insulation.
* **Skewed crossings** get a larger opening that covers the whole elongated pass-through. Crossings more than 5° off perpendicular are marked in the report for checking.
* Elements **running inside the wall** (more than 75° off perpendicular) are not placed. They are listed in the report for manual solution.
* **Re-running** does not create duplicates: elements that already have an opening are skipped (and handled by the check instead).

### Checking existing openings
* Checked are openings of the selected family whose host wall is visible in the active view.
* Each opening stores the UniqueIds of its linked elements in `ID_otvor`. The tool finds them in the currently loaded links and recomputes the required size and position.
* Result per opening: **OK**, **moved / resized** (difference over 5 mm), **no clash** (element no longer passes through the wall) or **element deleted** in the link.
* `ID_otvor` also stores the link file name, so an element missing from a loaded link is reported as deleted, while elements from an **unloaded link** are marked **not verified**: the opening keeps its size and is never deleted. Openings created by older versions get the link name added on the next update.
* If the MEP designer deletes and redraws an element, it gets a new UniqueId: the old opening is reported as *element deleted* and a new opening is proposed.
* Wall geometry is computed without our openings (they are temporarily removed in a rolled-back transaction), so an element passing through an existing opening is still detected.
* An opening is never deleted when it cannot be verified: unloaded link, wall geometry not available, or a failed geometry calculation.
* **Manually placed openings** (selected family, empty `ID_otvor`) are adopted automatically when new openings and the check are both enabled: the tool writes the elements passing through them into `ID_otvor` together with a `RUCNY:` mark holding the manual size and position. From then on the manual size is a minimum: the opening can only grow (an element needs more space or a neighbour is merged into it), it is never made smaller, moved or deleted. If its elements disappear, it is kept and listed in the report.
* Manual openings with no element passing through (e.g. a reserve) stay without ID and are never changed.
* In a workshared model, openings and walls **owned by another user** are skipped and listed in the report.
* Revit warnings during writing do not interrupt the run; they are listed at the end of the report.

### Opening family requirements
* Generic Model, **wall based**.
* Opening **centered on *Center (Left/Right)***, with its **bottom edge on *Ref. Level***. *Elevation from Level* is then the bottom edge of the opening.
* Void locked to **both wall faces**, so it cuts the full wall thickness.
* Instance parameters: `Sirka_otvoru` (Length), `Vyska_otvoru` (Length), `ID_otvor` (Text).
* Parameter names can be changed at the top of `script.py` (section NASTAVENIA), together with the rounding and skew tolerance.

### Limitations
* Rectangular openings only.
* If elements of one merged opening move apart by more than the set distance, the existing opening stays with the largest group and the other groups get new openings.
* Openings cannot be placed into walls in linked models.
* Requires **Revit 2024 or newer**.

## TALO kódy (YIT)

Renames element types and fills parameters according to the YIT EIR (chapter 6.4, Appendix A – TALO 2000).
Status: **v1, in testing** (block A of Viedenská cesta).

### How to use
1. *(Optional)* Select elements in the model, or use **Pick elements in model…** in the window.
2. Choose a category – the left list shows EIR codes for it, the right list shows project types.
3. Select one code on the left and one or more types on the right → **Prepare preview**.
4. Check / edit the new names → **Write to model** (one transaction, undone with a single **Ctrl+Z**).

### What it writes (per type)
Type name `{code}_{description}`, `1_Kod_prvku`, `1_Kategoria`, Assembly Code (+ `1_TALO_kod` if present),
IfcExportAs, and Type Mark (e.g. `OH.305`) for codes with a drawing abbreviation.
If only some instances of a type are selected, a duplicate type is created for them.

### Rules table
The rules are read from `data/YIT_EIR_TALO_mapovanie_AA.xlsx` (sheet *Mapovanie*). Edit the table, not the code.
Parameter and column names are in `lib/yit_talo/config.py`.

### Not in v1
Automatic code suggestions, renaming families, cross-model numbering check for blocks A/B/C (v1 only exports used codes to CSV).

## Návod (user guide)

The **Návod** button opens a window with a tab for each tool. The text of each tab is a Markdown file in `DELTA_SK.tab/Informácie.panel/Návod.pushbutton/obsah/` (one file = one tab, ordered by file name). To update the guide, edit these files; for a new tool, add a new file. Supported formatting: `#` tab title, `##` / `###` headings, `-` bullets, `1.` numbered steps, `**bold**` and `` `code` ``.

---

## Installation

1. Open the **pyRevit Extension Manager** in Revit.
2. Paste the repository URL into **Git URL**.
3. The repository is private: paste your *GitHub Personal Access Token* into **Token (optional)**.
4. Click **Add and install**, then **Reload** pyRevit (or restart Revit).

## Updating

After new changes are pushed to GitHub: **pyRevit → Update**, then **Reload**.

---
---

# DELTA_SK – rozšírenie pre pyRevit 🛠️

Vlastné rozšírenie pre **pyRevit** s automatizačnými nástrojmi pre Autodesk Revit. Nástroje sa v Revite zobrazia na karte **DELTA_SK**.

## Obsah

| Panel | Nástroj | Účel |
|---|---|---|
| Architecture | **AutoJoin** | Automatické Join Geometry v aktívnom pohľade s prioritou konštrukcií |
| Architecture | **Auto-shaft** | Automatické obdĺžnikové otvory vo vybraných typoch stien v miestach kolízií s linkami profesií, spájanie blízkych otvorov, kontrola a aktualizácia existujúcich |
| YIT | **TALO kódy** | Pomenovanie typov a vyplnenie parametrov podľa EIR YIT (kódy TALO 2000) |
| Informácie | **Návod** | Návod na používanie všetkých nástrojov, každý nástroj vo vlastnej záložke |

---

## AutoJoin

Spája geometriu (Join Geometry) prvkov **len v aktívnom pohľade**, nikdy nie v celom modeli naraz.

### Postup
1. *(Nepovinné)* Označ v Revite prvky, ktoré sa **nemajú** joinovať.
2. Spusti **AutoJoin** a vyber kategórie.
3. Skontroluj súhrn (nové joiny, opravy, vynechané prvky) a potvrď.
4. Pozri report v okne pyRevit. Kliknutím na ID prvku ťa Revit naň presunie.

Celú operáciu vrátiš jedným **Ctrl+Z**.

### Priorita joinu
* **Konštrukčné prvky vždy režú nekonštrukčné.** Konštrukčný = Structural Columns, Structural Framing, Structural Foundation a steny/stropy so zaškrtnutým *Structural*.
* **Medzi konštrukčnými prvkami:** základy > stĺpy > trámy > stropy > steny.
* **Medzi nekonštrukčnými prvkami** určí poradie Revit.
* **Existujúce joiny** sa menia len vtedy, keď nekonštrukčný prvok reže konštrukčný.

### Pravidlá
* Joinujú sa len prvky, ktorých objemy sa **reálne prekrývajú**. Prvky, ktoré sa iba dotýkajú plochou (napr. stena položená na doske), sa nejoinujú.
* Automaticky sa vynechajú: dvojice stena–stena (rieši ich Revit vlastnými spojmi stien), prvky v skupinách, prvky obsadené iným používateľom (workshared).
* Neúspešný pár nezastaví beh. Preskočí sa a v reporte sa zobrazí aj s dôvodom.
* Upozornenia Revitu počas behu sa potláčajú, ale vypíšu sa v reporte.

### Podporované kategórie
Steny, Stropy/Podlahy, Podhľady, Schodiská, Stĺpy, Nosné stĺpy, Základy, Nosná kostra, Strechy.

### Obmedzenia
* **Skupiny:** Revit nedovolí spojiť prvok v skupine s prvkom mimo skupiny. Prvky v rovnakej skupine treba spojiť ručne cez **Edit Group** (prenesie sa do všetkých inštancií).
* **Schodiská** väčšinou Join Geometry nepodporujú a v reporte sa zobrazia ako neúspešné.
* Vyžaduje **Revit 2023 alebo novší**.

## Auto-shaft

Nájde kolízie **vybraných typov stien** v našom modeli s prvkami v **nalinkovaných modeloch profesií** a osadí okolo nich obdĺžnikové otvory so zadaným odstupom. Pracuje **len v aktívnom pohľade**. Rozsah sa najjednoduchšie obmedzí 3D pohľadom so section boxom.
Stav: **v3, testovanie**.

### Postup
1. Otvor 3D pohľad (alebo pôdorys / rez), nastav section box a zapni linky profesií.
2. Spusti **Auto-shaft**. Otvorí sa jedno okno so všetkými nastaveniami:
   1. **Rodina otvoru** (predvolene `DGSK_otvor_stena`).
   2. **Výber konštrukcií** – typy z aktívneho view, do ktorých sa vytvorí otvor. Typy podľa filtra názvu (predvolene `RCO`) sú predoznačené. Viac výrazov sa oddeľuje `;`.
   3. **Linky profesií** – strom podľa kategórií Revitu (Pipes, Ducts, Cable Trays, Conduits), každá vrátane kolien, odbočiek a izolácie. Po rozbalení sa zobrazia len linky, ktoré majú danú kategóriu viditeľnú v aktívnom view. Každý link sa dá pre danú kategóriu zapnúť alebo vypnúť (napr. Pipes zo SHZ vypnúť).
   4. **Odsadenie otvoru** – jednotné, alebo podľa kategórie. Potrubia a chráničky menšie ako nastavené DN sa neosádzajú.
   5. **Dodatočné informácie** – otvory, medzi ktorými ostane menej steny ako nastavená medzera, sa spoja (predvolene 100 mm); otvory väčšie ako nastavený rozmer (predvolene 500 mm na šírku alebo výšku) sa označia na posúdenie statikom. Obe hodnoty sa dajú zmeniť.
   6. **Typ akcie** – osadiť nové otvory, skontrolovať existujúce, upraviť posunuté/zmenené/spájané, zmazať otvory bez kolízie.
3. Klikni na **Štart**. Všetko sa najprv len vypočíta, do modelu sa nič nezapíše.
4. Zobrazí sa súhrn (nové / na úpravu / na zmazanie). Vyber **Vykonať**, **Len report** (model sa nezmení) alebo **Zrušiť**.
5. Pozri report v okne pyRevit. Kliknutím na ID ťa Revit presunie na prvok.

Okno si pamätá posledné nastavenia na ďalšie spustenie.

Celú operáciu vrátiš jedným **Ctrl+Z**.

### Spracované kategórie
* **Pipes:** Pipes, Pipe Fittings, Pipe Insulations
* **Ducts:** Ducts, Duct Fittings, Duct Insulations
* **Cable Trays:** Cable Trays, Cable Tray Fittings
* **Conduits:** Conduits, Conduit Fittings

### Pravidlá
* Spracujú sa len steny **vybraných typov** v našom modeli. Oblúkové steny sa preskočia a vypíšu v reporte.
* Použijú sa len linky **viditeľné v aktívnom pohľade**.
* Kolízie sa počítajú zo **skutočného prieniku geometrie**, takže sa zarátajú aj tvarovky a izolácia. Izolácia sa zlúči s potrubím do jedného otvoru.
* Odsadenie sa meria od **vonkajšieho povrchu prvku vrátane izolácie**, nie od osi potrubia. Rozmer otvoru = vonkajší rozmer prvku v stene + 2 × odsadenie, **zaokrúhlené nahor na 10 mm**.
* Otvory, ktoré sa prekrývajú alebo medzi nimi ostane **menej steny ako nastavená medzera**, sa spoja do jedného. Spájajú sa nové aj existujúce otvory na tej istej stene (existujúce len pri zapnutej kontrole): jeden existujúci sa zväčší, ostatné sa zmažú.
* Otvory väčšie ako **nastavený rozmer** (šírka alebo výška) sa osadia normálne, ale v súhrne a reporte sú označené *⚠ posúdiť* na kontrolu statikom.
* Potrubia a chráničky **menšie ako nastavené DN** sa neosádzajú (predvolene DN20, nastavuje sa v okne, 0 = bez obmedzenia). Rozhoduje svetlosť potrubia bez izolácie, rozmer otvoru izoláciu zahŕňa.
* **Šikmé prechody** dostanú väčší otvor, ktorý pokryje celý pretiahnutý prienik. Prechody s odklonom od kolmice nad 5° sú v reporte označené na kontrolu.
* Prvky **vedené v stene** (odklon od kolmice nad 75°) sa neosádzajú. Vypíšu sa v reporte na ručné riešenie.
* **Opakované spustenie** nevytvára duplicity: prvky, ktoré už majú otvor, sa preskočia (rieši ich kontrola existujúcich).

### Kontrola existujúcich otvorov
* Kontrolujú sa otvory vybranej rodiny, ktorých hostiteľská stena je viditeľná v aktívnom pohľade.
* Každý otvor má v `ID_otvor` UniqueId prvkov z linku. Plugin ich vyhľadá v aktuálne načítaných linkoch a znova vypočíta potrebný rozmer a polohu.
* Výsledok pre každý otvor: **v poriadku**, **posunutý / zmenený rozmer** (rozdiel nad 5 mm), **bez kolízie** (prvok už stenou neprechádza) alebo **prvok zmazaný** v linku.
* `ID_otvor` obsahuje aj názov súboru linku. Prvok, ktorý chýba v načítanom linku, je *zmazaný*; prvky z **nenačítaného linku** sú **neoverené**: otvor si zachová rozmer a nikdy sa nezmaže. Otvory zo starších verzií dostanú názov linku pri najbližšej úprave.
* Ak projektant TZB prvok zmaže a nakreslí nanovo, dostane nové UniqueId: starý otvor sa vyhodnotí ako *prvok zmazaný* a navrhne sa nový otvor.
* Geometria stien sa počíta bez našich otvorov (dočasne sa odstránia v transakcii, ktorá sa vráti), takže sa správne vyhodnotí aj prvok, ktorý prechádza existujúcim otvorom.
* Otvor sa nikdy nezmaže, ak sa nedá overiť: nenačítaný link, nedostupná geometria steny alebo zlyhaný výpočet prieniku.
* **Ručne osadené otvory** (vybraná rodina, prázdne `ID_otvor`) sa automaticky prevezmú, keď je zapnuté osadenie nových aj kontrola: plugin do `ID_otvor` zapíše prvky, ktoré nimi prechádzajú, a značku `RUCNY:` s ručným rozmerom a polohou. Odvtedy je ručný rozmer minimum: otvor sa môže len zväčšiť (prvok potrebuje viac miesta alebo sa k nemu pripojí susedný), nikdy sa nezmenší, neposunie ani nezmaže. Ak z neho prvky zmiznú, ostane a vypíše sa v reporte.
* Ručné otvory, ktorými neprechádza žiadny prvok (napr. rezerva), ostanú bez ID a nikdy sa nemenia.
* V zdieľanom modeli sa otvory a steny **obsadené iným používateľom** vynechajú a vypíšu v reporte.
* Varovania Revitu počas zápisu neprerušia beh, vypíšu sa na konci reportu.

### Požiadavky na rodinu otvoru
* Generic Model, **wall based**.
* Otvor **vycentrovaný na *Center (Left/Right)***, **spodná hrana na *Ref. Level***. *Elevation from Level* je potom výška spodnej hrany otvoru.
* Void zamknutý na **obe líca steny**, aby prerezal celú hrúbku.
* Inštančné parametre: `Sirka_otvoru` (Length), `Vyska_otvoru` (Length), `ID_otvor` (Text).
* Názvy parametrov sa dajú zmeniť na začiatku `script.py` (sekcia NASTAVENIA), spolu so zaokrúhlením a toleranciou šikmých prechodov.

### Obmedzenia
* Len obdĺžnikové otvory.
* Ak sa prvky spojeného otvoru od seba vzdialia viac ako o nastavenú medzeru, existujúci otvor ostane najväčšej skupine a ostatné skupiny dostanú nové otvory.
* Do stien v nalinkovaných modeloch sa otvory osadiť nedajú.
* Vyžaduje **Revit 2024 alebo novší**.

## TALO kódy (YIT)

Premenuje typy a vyplní parametre podľa EIR YIT (kap. 6.4, Príloha A – TALO 2000).
Stav: **v1, testovanie** (blok A Viedenskej cesty).

### Postup
1. *(Nepovinné)* Označ prvky v modeli, alebo v okne použi **Vybrať prvky v modeli…**.
2. Zvoľ kategóriu – vľavo sa zobrazia kódy z EIR, vpravo typy v projekte.
3. Vľavo vyber jeden kód, vpravo jeden alebo viac typov → **Pripraviť náhľad**.
4. Skontroluj / uprav nové názvy → **Zapísať do modelu** (jedna transakcia, vrátiš ju jedným **Ctrl+Z**).

### Čo zapisuje (na typ)
Názov typu `{kód}_{popis}`, `1_Kod_prvku`, `1_Kategoria`, Assembly Code (+ `1_TALO_kod`, ak existuje),
IfcExportAs a Type Mark (napr. `OH.305`) pri kódoch so skratkou na výkres.
Ak je vybraná len časť inštancií typu, vytvorí sa pre ne duplikát typu.

### Tabuľka pravidiel
Pravidlá sa čítajú z `data/YIT_EIR_TALO_mapovanie_AA.xlsx` (hárok *Mapovanie*). Upravuje sa tabuľka, nie kód.
Mená parametrov a stĺpcov sú v `lib/yit_talo/config.py`.

### Mimo v1
Automatické návrhy kódov, premenovanie rodín, medzimodelová kontrola číslovania blokov A/B/C (v1 vie len export použitých kódov do CSV).

## Návod

Tlačidlo **Návod** otvorí okno so záložkou pre každý nástroj. Text záložiek je v Markdown súboroch v priečinku `DELTA_SK.tab/Informácie.panel/Návod.pushbutton/obsah/` (jeden súbor = jedna záložka, poradie podľa názvu súboru). Návod sa upravuje v týchto súboroch; pre nový nástroj stačí pridať nový súbor. Podporované formátovanie: `#` názov záložky, `##` / `###` nadpisy, `-` odrážky, `1.` číslované kroky, `**tučné**` a `` `kód` ``.

---

## Inštalácia

1. Otvor v Revite **pyRevit Extension Manager**.
2. Do poľa **Git URL** vlož adresu repozitára.
3. Repozitár je súkromný: do poľa **Token (optional)** vlož svoj *GitHub Personal Access Token*.
4. Klikni na **Add and install** a potom na **Reload** v pyRevite (alebo reštartuj Revit).

## Aktualizácia

Po nahratí nových zmien na GitHub: **pyRevit → Update**, potom **Reload**.

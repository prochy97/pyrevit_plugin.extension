# DELTA_SK – pyRevit Extension 🛠️

Custom **pyRevit** extension with automation tools for Autodesk Revit. Tools appear in Revit under the **DELTA_SK** tab.

*Slovenská verzia nižšie.*

## Contents

| Panel | Tool | Purpose |
|---|---|---|
| Architecture | **AutoJoin** | Automatic Join Geometry in the active view with structural priority |

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

---

## Inštalácia

1. Otvor v Revite **pyRevit Extension Manager**.
2. Do poľa **Git URL** vlož adresu repozitára.
3. Repozitár je súkromný: do poľa **Token (optional)** vlož svoj *GitHub Personal Access Token*.
4. Klikni na **Add and install** a potom na **Reload** v pyRevite (alebo reštartuj Revit).

## Aktualizácia

Po nahratí nových zmien na GitHub: **pyRevit → Update**, potom **Reload**.

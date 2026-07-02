# pyRevit Custom Extension 🛠️

This repository serves as a custom extension for **pyRevit**, containing a set of automation tools for Autodesk Revit.

## Extension Content

The extension currently includes the following tool:

### 1. AutoJoin (`.pushbutton`)
An intelligent tool for automatic geometry joining (Join Geometry) between structural and architectural elements.

#### Key Features:
* **Intelligent Selection Logic (Selection vs Active View):** If you select elements before running the tool, the script will process only your selection[cite: 1]. If nothing is selected, it automatically analyzes all visible elements in the active view[cite: 1].
* **Geometric Tolerance (Touching Faces):** The script utilizes a bounding box with a custom tolerance to detect elements that are genuinely touching each other[cite: 1].
* **Automatic Priority (Structural Priority):** After joining, the script automatically checks and switches the join order (`Switch Join Order`) if necessary, ensuring that structural elements (columns, foundations, framing) take precedence over non-structural/architectural elements (walls, floors, ceilings)[cite: 1].
* **Warning Swallower:** The script automatically suppresses Revit warnings during the transaction, preventing the operation from being interrupted or cancelled[cite: 1].

#### Supported Element Categories:
* Walls, Floors, Ceilings[cite: 1]
* Stairs, Columns, Structural Columns[cite: 1]
* Structural Foundations, Structural Framing, Roofs[cite: 1]

---

## ⚠️ IMPORTANT WARNING (Before running)

> **Before running this plugin, it is essential to check and properly set the priorities of all elements (materials and structural layers) in the model for the plugin to execute correctly!**
> Incorrect settings of layer priorities (e.g., in a compound wall or floor) can lead to unexpected results during the automatic switching of the join order (`Switch Join Order`).

---

## Installation in pyRevit

1. Copy the URL address of this repository.
2. Open the **pyRevit Extension Manager** in Revit.
3. Paste the copied address into the **Git URL** field.
4. Since this is a private repository, paste your *GitHub Personal Access Token* into the **Token (optional)** field.
5. Click **Add and install** and restart Revit (or use *Reload* in pyRevit).

---
---

# Vlastné rozšírenie pre pyRevit 🛠️

Tento repozitár slúži ako vlastné rozšírenie (Extension) pre **pyRevit**, ktoré obsahuje sadu automatizačných nástrojov pre Autodesk Revit.

## Obsah rozšírenia

Rozšírenie momentálne obsahuje nasledujúci nástroj:

### 1. AutoJoin (`.pushbutton`)
Nástroj na inteligentné a automatické spájanie geometrie (Join Geometry) medzi konštrukčnými a architektonickými prvkami.

#### Hlavné funkcie:
* **Inteligentný výber (Selection vs Active View):** Ak pred spustením označíš prvky, skript spracuje iba tvoj výber[cite: 1]. Ak neoznačíš nič, automaticky analyzuje všetky viditeľné prvky v aktívnom pohľade[cite: 1].
* **Geometrická tolerancia (Touching Faces):** Skript využíva bounding box s toleranciou na vyhľadanie reálne sa dotýkajúcich prvkov[cite: 1].
* **Automatická priorita (Structural Priority):** Po spojení skript automaticky skontroluje a prípadne otočí poradie spojenia (`Switch Join Order`) tak, aby nosné prvky (stĺpy, základové pätky, nosníky) mali prednosť pred nenosnými/architektonickými prvkami (steny, podlahy, podhľady)[cite: 1].
* **Warning Swallower:** Skript v priebehu transakcie automaticky potláča Revit varovania (Warnings), čím predchádza prerušeniu alebo zrušeniu operácie[cite: 1].

#### Podporované kategórie prvkov:
* Steny (`Walls`), Podlahy (`Floors`), Podhľady (`Ceilings`)[cite: 1]
* Schodiská (`Stairs`), Stĺpy a Nosné stĺpy (`Columns`, `Structural Columns`)[cite: 1]
* Základy (`Structural Foundation`), Nosná kostra (`Structural Framing`), Strechy (`Roofs`)[cite: 1]

---

## ⚠️ DÔLEŽITÉ UPOZORNENIE (Pred spustením)

> **Pred spustením tohto pluginu je nevyhnutné skontrolovať a správne nastaviť priority všetkých prvkov (materiálov a konštrukčných vrstiev) v modeli pre správne prebehnutie pluginu!**
> Nesprávne nastavenie priorít vrstiev (napr. v zloženej stene alebo podlahe) môže viesť k neočakávaným výsledkom pri automatickom prepínaní poradia spojenia (`Switch Join Order`).

---

## Inštalácia do pyRevitu

1. Skopíruj si URL adresu tohto repozitára.
2. Otvor **pyRevit Extension Manager** v Revite.
3. Do poľa **Git URL** vlož skopírovanú adresu.
4. Keďže je repozitár súkromný (Private), do poľa **Token (optional)** vlož svoj *GitHub Personal Access Token*.
5. Klikni na **Add and install** a reštartuj Revit (alebo použi *Reload* v pyRevite).

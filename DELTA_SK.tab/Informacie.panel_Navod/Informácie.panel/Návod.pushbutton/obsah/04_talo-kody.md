# TALO kódy (YIT)

Premenuje typy prvkov a vyplní parametre podľa EIR YIT (kap. 6.4, Príloha A – TALO 2000).

## Postup

1. (Nepovinné) Označ prvky v modeli, alebo v okne použi **Vybrať prvky v modeli…**.
2. Zvoľ kategóriu – vľavo sa zobrazia kódy z EIR, vpravo typy v projekte.
3. Vľavo vyber jeden kód, vpravo jeden alebo viac typov a klikni na **Pripraviť náhľad**.
4. Skontroluj, prípadne uprav nové názvy a klikni na **Zapísať do modelu**.

Zápis je jedna transakcia, vrátiš ho jedným **Ctrl+Z**.

## Čo sa zapíše do typu

- Názov typu v tvare `{kód}_{popis}`.
- Parametre `1_Kod_prvku`, `1_Kategoria`, Assembly Code (a `1_TALO_kod`, ak existuje) a IfcExportAs.
- Type Mark (napr. `OH.305`) pri kódoch so skratkou na výkres.
- Ak vyberieš len časť inštancií typu, vytvorí sa pre ne duplikát typu.

## Tabuľka pravidiel

Pravidlá sa čítajú z tabuľky `data/YIT_EIR_TALO_mapovanie_AA.xlsx` (hárok Mapovanie). Pri zmene pravidiel sa upravuje tabuľka, nie kód.

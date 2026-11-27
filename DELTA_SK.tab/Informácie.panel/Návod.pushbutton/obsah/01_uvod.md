# Úvod

Rozšírenie **DELTA_SK** pre pyRevit. Nástroje sú v Revite na karte **DELTA_SK**:

- **AutoJoin** (panel Architecture) – automatické Join Geometry s prioritou konštrukcií.
- **Auto-shaft** (panel Architecture) – automatické otvory v stenách v miestach prestupov profesií.
- **TALO kódy** (panel YIT) – pomenovanie typov a vyplnenie parametrov podľa EIR YIT.

## Spoločné pre všetky nástroje

- AutoJoin a Auto-shaft pracujú **len v aktívnom pohľade**. Rozsah obmedzíš pohľadom, napr. 3D pohľadom so section boxom.
- Celú operáciu vrátiš jedným **Ctrl+Z**. Po synchronizácii s centrálnym modelom už Ctrl+Z nefunguje, preto výsledok skontroluj pred synchronizáciou.
- Výsledok sa vypíše do okna pyRevit. Kliknutím na ID prvku ťa Revit naň presunie.

## Inštalácia

1. Otvor v Revite **pyRevit → Extensions**.
2. Do poľa **Git URL** vlož adresu repozitára.
3. Repozitár je súkromný: do poľa **Token (optional)** vlož svoj GitHub Personal Access Token.
4. Klikni na **Add and install** a potom na **Reload** (alebo reštartuj Revit).

## Aktualizácia

Keď sú na GitHube nové zmeny: **pyRevit → Update**, potom **Reload**.

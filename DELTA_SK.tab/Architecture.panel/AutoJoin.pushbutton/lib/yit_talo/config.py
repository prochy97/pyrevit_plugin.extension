# -*- coding: utf-8 -*-
"""Nastavenia pluginu. Mená parametrov a hárkov meň tu, nie v kóde."""
from __future__ import unicode_literals
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
EXT_DIR = os.path.dirname(os.path.dirname(_HERE))

# Predvolená cesta k mapovacej tabuľke (data/ v extension). Ak neexistuje,
# plugin sa spýta na súbor a cestu si zapamätá v pyRevit configu.
DEFAULT_MAPPING = os.path.join(EXT_DIR, "data", "YIT_EIR_TALO_mapovanie_AA.xlsx")

SHEET_MAPPING = "Mapovanie"
SHEET_CATEGORIES = "Kategórie"

# Hlavičky stĺpcov v hárku Mapovanie (čítané podľa názvu, nie poradia)
COL_TALO = "TALO kód"
COL_OD = "Rozsah od"
COL_DO = "Rozsah do"
COL_OZ = "Označenie na výkrese"
COL_POPIS = "Popis"
COL_SKUPINA = "Skupina (TALO)"
COL_IFC = "IFC trieda – export"
COL_REVIT = "Revit kategórie"
COL_KATEGORIA = "1_Kategoria"
COL_AKTIVNY = "Aktívny"
COL_UPOZ = "Upozornenie"

# Shared parametre podľa EIR
P_KOD = "1_Kod_prvku"
P_KATEGORIA = "1_Kategoria"
P_TALO_TEXT = "1_TALO_kod"   # zapíše sa iba ak parameter v projekte existuje
REQUIRED_SHARED = [P_KOD, P_KATEGORIA]

# Názvy IFC parametra pre staršie verzie / shared parameter (fallback,
# primárne sa použije BuiltInParameter.IFC_EXPORT_ELEMENT_TYPE_AS)
IFC_PARAM_NAMES = ["IfcExportAs", "Export Type to IFC As"]

# Oddeľovač medzi kódom a popisom v názve typu: 13216.101_Obklad_keramicky
NAME_SEP = "_"

# Typ Mark sa prepisuje iba pri riadkoch so skratkou (OH.305, DI.101 ...)
WRITE_TYPE_MARK = True

TRANSACTION_NAME = "YIT – TALO kódy"

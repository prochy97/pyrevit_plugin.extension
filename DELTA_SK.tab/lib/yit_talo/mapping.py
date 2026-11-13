# -*- coding: utf-8 -*-
"""Načítanie mapovacej tabuľky z .xlsx bez Excelu a bez externých knižníc.

Funguje v IronPythone 2.7 (pyRevit) aj v CPythone 3 – číta priamo XML
vo vnútri .xlsx (zipfile + ElementTree). Bez Revit API, dá sa testovať mimo Revitu.
"""
from __future__ import unicode_literals
import re
import zipfile
import xml.etree.ElementTree as ET

from yit_talo import config

_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class MappingError(Exception):
    pass


def _col_index(ref):
    letters = re.match(r"([A-Z]+)", ref).group(1)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _text(node):
    """Všetky <t> pod uzlom (zdieľaný reťazec s formátovaním má viac <r><t>)."""
    return "".join(t.text or "" for t in node.iter(_M + "t"))


def read_sheet(path, sheet_name):
    """Vráti hárok ako zoznam riadkov (zoznam hodnôt; str, int, float alebo None)."""
    try:
        zf = zipfile.ZipFile(path)
    except Exception as ex:
        raise MappingError("Súbor sa nedá otvoriť: {} ({})".format(path, ex))
    try:
        names = zf.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            shared = [_text(si) for si in sroot.findall(_M + "si")]

        wroot = ET.fromstring(zf.read("xl/workbook.xml"))
        rid = None
        for sh in wroot.iter(_M + "sheet"):
            if sh.get("name") == sheet_name:
                rid = sh.get(_R + "id")
        if rid is None:
            raise MappingError("V súbore chýba hárok '{}'".format(sheet_name))

        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in rels.iter(_PR + "Relationship"):
            if rel.get("Id") == rid:
                target = rel.get("Target")
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target

        root = ET.fromstring(zf.read(target))
        rows = []
        for row in root.iter(_M + "row"):
            vals = {}
            for c in row.findall(_M + "c"):
                idx = _col_index(c.get("r"))
                t = c.get("t")
                v = c.find(_M + "v")
                if t == "s":
                    val = shared[int(v.text)] if v is not None else None
                elif t == "inlineStr":
                    val = _text(c)
                elif t in ("str", "e"):
                    val = v.text if v is not None else None
                elif t == "b":
                    val = bool(int(v.text)) if v is not None else None
                else:
                    if v is None or v.text is None:
                        val = None
                    else:
                        f = float(v.text)
                        val = int(f) if f == int(f) else f
                vals[idx] = val
            if vals:
                width = max(vals.keys()) + 1
                rows.append([vals.get(i) for i in range(width)])
            else:
                rows.append([])
        return rows
    finally:
        zf.close()


def _s(val):
    if val is None:
        return ""
    if isinstance(val, float) and val == int(val):
        val = int(val)
    return "{}".format(val).strip()


class CodeRow(object):
    """Jeden riadok mapovacej tabuľky = jeden rozsah kódov."""

    def __init__(self, talo, od, do, oz, popis, skupina, ifc, categories,
                 kategoria, aktivny, upozornenie):
        self.talo = talo
        self.od = od
        self.do = do
        self.oz = oz
        self.popis = popis
        self.skupina = skupina
        self.ifc = ifc
        self.categories = categories
        self.kategoria = kategoria
        self.aktivny = aktivny
        self.upozornenie = upozornenie
        # vlastnosti pre WPF binding
        self.rozsah = "{}.{:03d}–{:03d}".format(talo, od, do)
        self.kat_text = "; ".join(categories)
        self.has_warning = bool(upozornenie)

    def contains(self, talo, num):
        return self.talo == talo and self.od <= num <= self.do

    def __repr__(self):
        return "<CodeRow {} {}>".format(self.rozsah, self.popis)


def load_mapping(path):
    """Vráti (zoznam CodeRow, {názov kategórie: 'OST_...'}, zoznam varovaní)."""
    warnings = []
    data = read_sheet(path, config.SHEET_MAPPING)
    if not data:
        raise MappingError("Hárok '{}' je prázdny".format(config.SHEET_MAPPING))
    header = [_s(h) for h in data[0]]

    def col(name, required=True):
        if name in header:
            return header.index(name)
        if required:
            raise MappingError("V hárku '{}' chýba stĺpec '{}'".format(config.SHEET_MAPPING, name))
        warnings.append("Chýba stĺpec '{}' – ignoruje sa".format(name))
        return None

    ci = dict(
        talo=col(config.COL_TALO), od=col(config.COL_OD), do=col(config.COL_DO),
        oz=col(config.COL_OZ), popis=col(config.COL_POPIS),
        skupina=col(config.COL_SKUPINA, False), ifc=col(config.COL_IFC),
        revit=col(config.COL_REVIT), kat=col(config.COL_KATEGORIA, False),
        akt=col(config.COL_AKTIVNY), upoz=col(config.COL_UPOZ, False),
    )

    def get(row, key):
        i = ci[key]
        if i is None or i >= len(row):
            return ""
        return _s(row[i])

    rows = []
    for n, raw in enumerate(data[1:], start=2):
        if not raw or not get(raw, "talo"):
            continue
        talo = get(raw, "talo")
        try:
            od = int(float(get(raw, "od")))
            do = int(float(get(raw, "do")))
        except ValueError:
            warnings.append("Riadok {}: neplatný rozsah – preskočené".format(n))
            continue
        if not re.match(r"^\d{5}$", talo):
            warnings.append("Riadok {}: TALO kód '{}' nemá 5 číslic – preskočené".format(n, talo))
            continue
        cats = [c.strip() for c in get(raw, "revit").split(";") if c.strip()]
        rows.append(CodeRow(
            talo=talo, od=od, do=do, oz=get(raw, "oz"), popis=get(raw, "popis"),
            skupina=get(raw, "skupina"), ifc=get(raw, "ifc"), categories=cats,
            kategoria=get(raw, "kat"),
            aktivny=get(raw, "akt").lower() in ("áno", "ano", "a", "yes", "1", "true"),
            upozornenie=get(raw, "upoz"),
        ))

    # prekrývajúce sa rozsahy v rámci jedného TALO kódu
    by_talo = {}
    for r in rows:
        by_talo.setdefault(r.talo, []).append(r)
    for talo, lst in by_talo.items():
        lst = sorted(lst, key=lambda r: r.od)
        for a, b in zip(lst, lst[1:]):
            if b.od <= a.do:
                warnings.append("Prekrytie rozsahov: {} a {}".format(a.rozsah, b.rozsah))

    cat_map = {}
    for raw in read_sheet(path, config.SHEET_CATEGORIES)[1:]:
        if len(raw) >= 2 and _s(raw[0]) and _s(raw[1]):
            cat_map[_s(raw[0])] = _s(raw[1])
    used = set(c for r in rows for c in r.categories)
    for c in sorted(used - set(cat_map)):
        warnings.append("Kategória '{}' nie je v hárku '{}'".format(c, config.SHEET_CATEGORIES))
    return rows, cat_map, warnings

# -*- coding: utf-8 -*-
"""Logika kódov a názvov – bez Revit API, testovateľné mimo Revitu."""
from __future__ import unicode_literals
import re

from yit_talo import config

ST_NONE = "Bez kódu"
ST_OK = "OK"
ST_BAD = "Nesúlad"

_PREFIX = re.compile(r"^(\d{5})\.(\d{3})(.*)$")


def split_name(name):
    """'13216.101_Obklad' -> ('13216.101', 'Obklad'); 'Obklad' -> (None, 'Obklad')."""
    m = _PREFIX.match(name or "")
    if not m:
        return None, (name or "")
    return "{}.{}".format(m.group(1), m.group(2)), m.group(3).lstrip(" _-")


def parse_code(code):
    m = re.match(r"^(\d{5})\.(\d{3})$", code or "")
    if not m:
        return None, None
    return m.group(1), int(m.group(2))


def make_code(talo, num):
    return "{}.{:03d}".format(talo, num)


def compose_name(code, rest):
    rest = (rest or "").strip(" _-")
    return code + config.NAME_SEP + rest if rest else code


def ensure_prefix(code, name):
    """Ak používateľ v náhľade zmazal kód zo začiatku názvu, vráti ho tam."""
    old, rest = split_name(name)
    if old == code:
        return name
    return compose_name(code, rest if old else name)


def find_row(rows, code):
    talo, num = parse_code(code)
    if talo is None:
        return None
    for r in rows:
        if r.contains(talo, num):
            return r
    return None


def drawing_tag(row, code):
    if not row.oz:
        return ""
    return "{}.{}".format(row.oz, code[-3:])


def allocate(row, used_codes, count, keep=None):
    """Pridelí `count` kódov v rozsahu riadku.

    keep: zoznam existujúcich kódov typov (alebo None) v rovnakom poradí –
    ak typ už má kód z tohto rozsahu, ponechá ho. Vráti zoznam kódov.
    Vyhodí ValueError, ak rozsah nemá dosť voľných čísel.
    """
    keep = keep or [None] * count
    result = [None] * count
    taken = set(used_codes)
    for i, k in enumerate(keep):
        talo, num = parse_code(k)
        if talo is not None and row.contains(talo, num) and k not in result:
            result[i] = k
    taken.update(c for c in result if c)
    free = (make_code(row.talo, n) for n in range(row.od, row.do + 1)
            if make_code(row.talo, n) not in taken)
    for i in range(count):
        if result[i] is None:
            try:
                result[i] = next(free)
            except StopIteration:
                raise ValueError("Rozsah {} je plný".format(row.rozsah))
    return result


def evaluate(info, rows):
    """Stav typu. info: objekt s atribútmi name, kod, category_key, ifc,
    assembly, kategoria, type_mark. Vráti (stav, [dôvody])."""
    prefix, _ = split_name(info.name)
    kod = info.kod or ""
    if not prefix and not kod:
        return ST_NONE, []
    reasons = []
    code = kod or prefix
    if not kod:
        reasons.append("{} je prázdny".format(config.P_KOD))
    elif not prefix:
        reasons.append("názov nezačína kódom")
    elif prefix != kod:
        reasons.append("názov {} ≠ {} {}".format(prefix, config.P_KOD, kod))
    row = find_row(rows, code)
    if row is None:
        reasons.append("kód {} nie je v žiadnom rozsahu".format(code))
        return ST_BAD, reasons
    if row.categories and info.category_key not in row.categories:
        reasons.append("kategória {} nie je pri {}".format(info.category_key, row.rozsah))
    if row.ifc and info.ifc is not None and info.ifc != row.ifc:
        reasons.append("IFC '{}' ≠ '{}'".format(info.ifc or "", row.ifc))
    if info.assembly is not None and info.assembly != row.talo:
        reasons.append("Assembly Code '{}' ≠ {}".format(info.assembly or "", row.talo))
    if row.kategoria and info.kategoria is not None and info.kategoria != row.kategoria:
        reasons.append("{} '{}' ≠ '{}'".format(config.P_KATEGORIA, info.kategoria or "", row.kategoria))
    tag = drawing_tag(row, code)
    if config.WRITE_TYPE_MARK and tag and info.type_mark is not None and info.type_mark != tag:
        reasons.append("Type Mark '{}' ≠ {}".format(info.type_mark or "", tag))
    return (ST_BAD if reasons else ST_OK), reasons


def mark_duplicates(infos):
    """Rovnaký kód na viacerých typoch = nesúlad (každý typ má mať vlastné číslo)."""
    seen = {}
    for i in infos:
        if i.kod:
            seen.setdefault(i.kod, []).append(i)
    for code, lst in seen.items():
        if len(lst) > 1:
            for i in lst:
                others = ", ".join(x.name for x in lst if x is not i)
                i.status = ST_BAD
                i.reasons = list(i.reasons) + ["kód {} má aj: {}".format(code, others)]

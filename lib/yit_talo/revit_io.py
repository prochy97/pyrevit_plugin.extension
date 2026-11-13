# -*- coding: utf-8 -*-
"""Čítanie a zápis do Revitu."""
from __future__ import unicode_literals
from collections import defaultdict

from Autodesk.Revit import DB

from yit_talo import config, naming

CURTAIN_KEY = "Walls (curtain)"


def eid_int(eid):
    try:
        return eid.Value          # Revit 2024+
    except AttributeError:
        return eid.IntegerValue


def get_name(elem):
    try:
        return elem.Name
    except Exception:
        return DB.Element.Name.GetValue(elem)


def set_name(elem, name):
    try:
        elem.Name = name
    except Exception:
        DB.Element.Name.SetValue(elem, name)


def _bip(name):
    return getattr(DB.BuiltInParameter, name, None)


def _param(elem, bip_name=None, names=()):
    if bip_name:
        bip = _bip(bip_name)
        if bip is not None:
            p = elem.get_Parameter(bip)
            if p is not None:
                return p
    for n in names:
        p = elem.LookupParameter(n)
        if p is not None:
            return p
    return None


def _read(p):
    """None = parameter neexistuje; '' = existuje, prázdny."""
    if p is None:
        return None
    return p.AsString() or ""


def p_kod(e):
    return _param(e, names=[config.P_KOD])


def p_kategoria(e):
    return _param(e, names=[config.P_KATEGORIA])


def p_talo_text(e):
    return _param(e, names=[config.P_TALO_TEXT])


def p_ifc(e):
    return _param(e, "IFC_EXPORT_ELEMENT_TYPE_AS", config.IFC_PARAM_NAMES)


def p_assembly(e):
    return _param(e, "UNIFORMAT_CODE")


def p_type_mark(e):
    return _param(e, "ALL_MODEL_TYPE_MARK")


# ---------------------------------------------------------------- kontrola

def check_bindings(doc, names):
    """{meno: 'type' | 'instance' | None} pre projektové/shared parametre."""
    found = dict((n, None) for n in names)
    it = doc.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        nm = it.Key.Name
        if nm in found:
            found[nm] = "type" if isinstance(it.Current, DB.TypeBinding) else "instance"
    return found


# ---------------------------------------------------------------- typy

class TypeInfo(object):
    """Jeden typ v modeli + údaje pre zobrazenie v plugine."""

    def __init__(self, etype, category_key, count):
        self.id = etype.Id
        self.category_key = category_key
        self.count = count
        self.picked_ids = set()       # vybrané inštancie (ElementId int)
        self.refresh(etype)

    def refresh(self, etype):
        self.name = get_name(etype)
        try:
            self.family = etype.FamilyName
        except Exception:
            self.family = ""
        self.kod = _read(p_kod(etype))
        self.kategoria = _read(p_kategoria(etype))
        self.ifc = _read(p_ifc(etype))
        self.assembly = _read(p_assembly(etype))
        self.type_mark = _read(p_type_mark(etype))
        self.status = naming.ST_NONE
        self.reasons = []

    # vlastnosti pre WPF binding
    @property
    def picked(self):
        return len(self.picked_ids) if self.picked_ids else ""

    @property
    def kod_text(self):
        return self.kod or naming.split_name(self.name)[0] or ""

    @property
    def reasons_text(self):
        return "; ".join(self.reasons)


def _bic(name):
    return getattr(DB.BuiltInCategory, name, None)


def category_key_for(etype, keys_by_bic):
    cat = etype.Category
    if cat is None:
        return None
    keys = keys_by_bic.get(eid_int(cat.Id))
    if not keys:
        return None
    if len(keys) == 1:
        return keys[0]
    # Walls / Walls (curtain)
    if isinstance(etype, DB.WallType):
        if etype.Kind == DB.WallKind.Curtain and CURTAIN_KEY in keys:
            return CURTAIN_KEY
        return [k for k in keys if k != CURTAIN_KEY][0]
    return keys[0]


def collect_types(doc, cat_map, rows):
    """Všetky typy v kategóriách z hárku Kategórie, s počtom inštancií a stavom."""
    keys_by_bic = defaultdict(list)
    bics = {}
    for key, bic_name in cat_map.items():
        bic = _bic(bic_name)
        if bic is None:
            continue                         # napr. OST_Toposolid v starej verzii
        bics[bic_name] = bic
        keys_by_bic[int(bic)].append(key)

    infos = []
    for bic_name, bic in bics.items():
        counts = defaultdict(int)
        for inst in DB.FilteredElementCollector(doc).OfCategory(bic) \
                .WhereElementIsNotElementType():
            tid = inst.GetTypeId()
            if tid != DB.ElementId.InvalidElementId:
                counts[eid_int(tid)] += 1
        for et in DB.FilteredElementCollector(doc).OfCategory(bic) \
                .WhereElementIsElementType():
            key = category_key_for(et, keys_by_bic)
            if key is None:
                continue
            infos.append(TypeInfo(et, key, counts.get(eid_int(et.Id), 0)))
    evaluate_all(infos, rows)
    return infos


def evaluate_all(infos, rows):
    for i in infos:
        i.status, i.reasons = naming.evaluate(i, rows)
    naming.mark_duplicates(infos)


def used_codes(doc):
    """Všetky kódy v projekte (parameter aj prefix názvu) naprieč všetkými typmi."""
    codes = set()
    for et in DB.FilteredElementCollector(doc).WhereElementIsElementType():
        try:
            nm = get_name(et)
        except Exception:
            continue
        prefix = naming.split_name(nm)[0]
        if prefix:
            codes.add(prefix)
        k = _read(p_kod(et))
        if k:
            codes.add(k)
    return codes


def instances_of(doc, type_id):
    res = []
    et = doc.GetElement(type_id)
    if et is None or et.Category is None:
        return res
    for inst in DB.FilteredElementCollector(doc).OfCategoryId(et.Category.Id) \
            .WhereElementIsNotElementType():
        if inst.GetTypeId() == type_id:
            res.append(inst)
    return res


# ---------------------------------------------------------------- zápis

def _set(p, value, log, label):
    if p is None:
        return
    if p.IsReadOnly:
        log.append("  ! {} je len na čítanie".format(label))
        return
    try:
        p.Set(value)
    except Exception as ex:
        log.append("  ! {}: {}".format(label, ex))


def _set_shared(doc, etype, getter, value, binding, log, label):
    """Shared parameter môže byť typový alebo inštančný – zapíše tam, kde je."""
    p = getter(etype)
    if p is not None:
        _set(p, value, log, label)
        return
    if binding == "instance":
        insts = instances_of(doc, etype.Id)
        for inst in insts:
            _set(getter(inst), value, log, label)
        log.append("  {} zapísaný na {} inštancií".format(label, len(insts)))
    elif binding is None:
        log.append("  ! {} v projekte neexistuje – nezapísané".format(label))
    else:
        log.append("  ! {} nie je priradený ku kategórii tohto typu – nezapísané".format(label))


def apply_plan(doc, items, bindings):
    """items: PreviewItem-y. Musí bežať vo vnútri transakcie. Vráti log (zoznam riadkov)."""
    log = []
    for it in items:
        src = doc.GetElement(it.type_id)
        if src is None:
            log.append("X {}: typ už neexistuje".format(it.old_name))
            continue
        name = naming.ensure_prefix(it.code, it.new_name)
        try:
            if it.dup_ids:
                target = src.Duplicate(name)
                moved = 0
                for iid in it.dup_ids:
                    inst = doc.GetElement(DB.ElementId(iid))
                    try:
                        inst.ChangeTypeId(target.Id)
                        moved += 1
                    except Exception as ex:
                        log.append("  ! inštancia {}: {}".format(iid, ex))
                log.append("+ {} → nový typ {} ({} inštancií)".format(it.old_name, name, moved))
            else:
                target = src
                if get_name(src) != name:
                    set_name(src, name)
                log.append("= {} → {}".format(it.old_name, name))
        except Exception as ex:
            log.append("X {}: {}".format(it.old_name, ex))
            continue

        row = it.row
        _set_shared(doc, target, p_kod, it.code, bindings.get(config.P_KOD), log, config.P_KOD)
        if row.kategoria:
            _set_shared(doc, target, p_kategoria, row.kategoria,
                        bindings.get(config.P_KATEGORIA), log, config.P_KATEGORIA)
        _set(p_assembly(target), row.talo, log, "Assembly Code")
        _set(p_talo_text(target), row.talo, log, config.P_TALO_TEXT)
        if row.ifc:
            p = p_ifc(target)
            if p is None:
                log.append("  ! IFC parameter nenájdený")
            else:
                _set(p, row.ifc, log, "IfcExportAs")
        if config.WRITE_TYPE_MARK and it.tag:
            _set(p_type_mark(target), it.tag, log, "Type Mark")
    return log

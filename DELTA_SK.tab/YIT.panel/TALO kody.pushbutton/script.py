# -*- coding: utf-8 -*-
"""Pomenovanie typov podľa EIR YIT (TALO 2000) – v1."""
from __future__ import unicode_literals
import io
import os

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

from yit_talo import config, mapping, naming, revit_io

doc = revit.doc
uidoc = revit.uidoc
cfg = script.get_config()
XAML = script.get_bundle_file("ui.xaml")

ALL_CATS = "(všetky kategórie)"
STATUS_ALL = "Všetky"


class PreviewItem(object):
    def __init__(self, info, row, code, dup_ids, conflict):
        self.type_id = info.id
        self.info = info
        self.row = row
        self.code = code
        self.talo = row.talo
        self.ifc = row.ifc
        self.kategoria = row.kategoria
        self.tag = naming.drawing_tag(row, code) if config.WRITE_TYPE_MARK else ""
        self.dup_ids = dup_ids
        self.old_name = info.name
        self.new_name = naming.compose_name(code, naming.split_name(info.name)[1])
        self.action = "Duplikovať typ" if dup_ids else "Premenovať"
        notes = []
        if dup_ids:
            notes.append("nový typ pre {} z {} inštancií".format(len(dup_ids), info.count))
        if info.category_key not in row.categories:
            notes.append("kategória {} nie je pri tomto kóde v tabuľke".format(info.category_key))
        if conflict:
            notes.append(conflict)
        self.note = "; ".join(notes)


# ======================================================================
def load_mapping_path():
    path = cfg.get_option("mapping_path", "")
    if path and os.path.exists(path):
        return path
    if os.path.exists(config.DEFAULT_MAPPING):
        return config.DEFAULT_MAPPING
    path = forms.pick_file(file_ext="xlsx", title="Vyber mapovaciu tabuľku TALO (xlsx)")
    if path:
        cfg.mapping_path = path
        script.save_config()
    return path


class State(object):
    """Stav, ktorý prežije zatvorenie okna kvôli výberu v modeli."""

    def __init__(self, rows, cat_map, bindings):
        self.rows = rows
        self.cat_map = cat_map
        self.bindings = bindings
        self.infos = []
        self.category = None
        self.preview = []
        self.reload()

    def reload(self):
        picked = dict((revit_io.eid_int(i.id), i.picked_ids) for i in self.infos if i.picked_ids)
        self.infos = revit_io.collect_types(doc, self.cat_map, self.rows)
        for i in self.infos:
            i.picked_ids = picked.get(revit_io.eid_int(i.id), set())

    def set_picked(self, elements):
        by_type = {}
        for e in elements:
            tid = e.GetTypeId()
            if tid is None or tid == DB.ElementId.InvalidElementId:
                continue
            by_type.setdefault(revit_io.eid_int(tid), set()).add(revit_io.eid_int(e.Id))
        for i in self.infos:
            i.picked_ids = by_type.get(revit_io.eid_int(i.id), set())
        return sum(1 for i in self.infos if i.picked_ids)


# ======================================================================
class TaloWindow(forms.WPFWindow):
    def __init__(self, state):
        forms.WPFWindow.__init__(self, XAML)
        self.state = state
        self.result = None
        self._ready = False

        cats = sorted(set(i.category_key for i in state.infos) |
                      set(c for r in state.rows for c in r.categories if c in state.cat_map))
        self.cb_category.ItemsSource = [ALL_CATS] + cats
        self.cb_status.ItemsSource = [STATUS_ALL, naming.ST_NONE, naming.ST_OK, naming.ST_BAD]
        self.cb_status.SelectedIndex = 0
        has_pick = any(i.picked_ids for i in state.infos)
        self.chk_only_picked.IsChecked = has_pick
        if state.category in cats:
            self.cb_category.SelectedItem = state.category
        else:
            self.cb_category.SelectedIndex = 0
        self.dg_preview.ItemsSource = list(state.preview)
        self._ready = True
        self.refresh()

    # ---------------------------------------------------------- filtre
    def _category(self):
        c = self.cb_category.SelectedItem
        return None if c in (None, ALL_CATS) else c

    def refresh(self):
        if not self._ready:
            return
        st = self.state
        cat = self._category()
        only_picked = bool(self.chk_only_picked.IsChecked)

        # typy
        q = (self.tb_search_types.Text or "").lower()
        status = self.cb_status.SelectedItem
        types = []
        for i in st.infos:
            if cat and i.category_key != cat:
                continue
            if only_picked and not i.picked_ids:
                continue
            if status and status != STATUS_ALL and i.status != status:
                continue
            if q and q not in i.name.lower() and q not in (i.family or "").lower():
                continue
            types.append(i)
        types.sort(key=lambda i: (i.category_key, i.family or "", i.name))
        self.dg_types.ItemsSource = types

        # kódy – podľa kategórie, alebo podľa kategórií vo výbere
        if cat:
            cats = set([cat])
        elif only_picked:
            cats = set(i.category_key for i in types)
        else:
            cats = None
        q = (self.tb_search.Text or "").lower()
        codes = []
        for r in st.rows:
            if not r.aktivny:
                continue
            if not self.chk_all_codes.IsChecked and cats is not None \
                    and not cats.intersection(r.categories):
                continue
            if q and q not in r.rozsah.lower() and q not in r.popis.lower() \
                    and q not in r.skupina.lower():
                continue
            codes.append(r)
        self.dg_codes.ItemsSource = codes

        n_ok = sum(1 for i in st.infos if i.status == naming.ST_OK)
        n_bad = sum(1 for i in st.infos if i.status == naming.ST_BAD)
        n_none = sum(1 for i in st.infos if i.status == naming.ST_NONE)
        self.tb_info.Text = "Typov: {}  |  OK: {}  |  Nesúlad: {}  |  Bez kódu: {}".format(
            len(st.infos), n_ok, n_bad, n_none)

    def on_category_changed(self, sender, args):
        self.state.category = self._category()
        self.refresh()

    def on_filter_changed(self, sender, args):
        self.refresh()

    # ---------------------------------------------------------- výber
    def on_pick(self, sender, args):
        self.result = "pick"
        self.Close()

    def on_clear_pick(self, sender, args):
        for i in self.state.infos:
            i.picked_ids = set()
        self.chk_only_picked.IsChecked = False
        self.refresh()

    # ---------------------------------------------------------- náhľad
    def on_preview(self, sender, args):
        row = self.dg_codes.SelectedItem
        infos = list(self.dg_types.SelectedItems)
        if row is None or not infos:
            forms.alert("Vyber jeden kód vľavo a aspoň jeden typ vpravo.")
            return
        st = self.state
        in_preview = set(revit_io.eid_int(p.type_id) for p in st.preview)
        infos = [i for i in infos if revit_io.eid_int(i.id) not in in_preview]
        if not infos:
            forms.alert("Vybrané typy už sú v náhľade.")
            return

        used = revit_io.used_codes(doc) | set(p.code for p in st.preview)
        dup_flags = []
        keep = []
        for i in infos:
            partial = bool(i.picked_ids) and len(i.picked_ids) < i.count
            dup = partial and bool(self.chk_duplicate.IsChecked)
            dup_flags.append(dup)
            # pri duplikovaní ostáva starý kód pôvodnému typu
            keep.append(None if dup else (i.kod or naming.split_name(i.name)[0]))
        # vlastné kódy vybraných typov sa uvoľnia (typ si ich môže ponechať)
        try:
            codes = naming.allocate(row, used - set(k for k in keep if k), len(infos), keep)
        except ValueError as ex:
            forms.alert("{}".format(ex))
            return

        for i, code, dup in zip(infos, codes, dup_flags):
            dup_ids = sorted(i.picked_ids) if dup else []
            st.preview.append(PreviewItem(i, row, code, dup_ids, None))
        clashes = self._name_clashes(st.preview)
        for p in st.preview:
            if p in clashes and "NÁZOV UŽ EXISTUJE" not in p.note:
                p.note = (p.note + "; " if p.note else "") + "NÁZOV UŽ EXISTUJE"
        self.dg_preview.ItemsSource = list(st.preview)

    def _name_clashes(self, items):
        """Položky, ktorých nový názov už v rodine existuje (v modeli alebo v náhľade)."""
        taken = {}
        for i in self.state.infos:
            taken.setdefault((i.category_key, i.family or ""), set()).add(i.name)
        clashes = []
        for p in items:
            key = (p.info.category_key, p.info.family or "")
            final = naming.ensure_prefix(p.code, p.new_name)
            names = taken.setdefault(key, set())
            if p.dup_ids or final != p.old_name:
                if final in names:
                    clashes.append(p)
                names.add(final)
        return clashes

    def on_clear_preview(self, sender, args):
        self.state.preview = []
        self.dg_preview.ItemsSource = []

    # ---------------------------------------------------------- zápis
    def on_apply(self, sender, args):
        self.dg_preview.CommitEdit()
        items = list(self.dg_preview.ItemsSource or [])
        if not items:
            forms.alert("Náhľad je prázdny.")
            return
        bad = self._name_clashes(items)
        if bad:
            forms.alert("Niektoré nové názvy už v rodine existujú – uprav ich v náhľade:\n"
                        + "\n".join(p.new_name for p in bad[:15]))
            return
        if not forms.alert("Zapísať {} zmien do modelu?".format(len(items)), yes=True, no=True):
            return
        with revit.Transaction(config.TRANSACTION_NAME):
            log = revit_io.apply_plan(doc, items, self.state.bindings)
        self.state.preview = []
        self.state.reload()
        self.dg_preview.ItemsSource = []
        self.refresh()
        out = script.get_output()
        out.print_md("### YIT – TALO kódy: zapísané")
        for line in log:
            print(line)

    # ---------------------------------------------------------- export
    def on_export(self, sender, args):
        path = forms.save_file(file_ext="csv",
                               default_name="{}_TALO_kody".format(doc.Title))
        if not path:
            return
        rows = [i for i in self.state.infos if i.kod_text]
        rows.sort(key=lambda i: i.kod_text)
        with io.open(path, "w", encoding="utf-8-sig") as f:
            f.write("Model;Kód;Názov typu;Rodina;Kategória;Inštancií;Stav;Dôvod\n")
            for i in rows:
                vals = [doc.Title, i.kod_text, i.name, i.family or "", i.category_key,
                        "{}".format(i.count), i.status, i.reasons_text]
                f.write(";".join(v.replace(";", ",") for v in vals) + "\n")
        forms.alert("Exportovaných {} typov:\n{}".format(len(rows), path))

    def on_close(self, sender, args):
        self.result = None
        self.Close()


# ======================================================================
def main():
    path = load_mapping_path()
    if not path:
        return
    try:
        rows, cat_map, warnings = mapping.load_mapping(path)
    except mapping.MappingError as ex:
        forms.alert("Mapovacia tabuľka sa nedá načítať:\n{}".format(ex), exitscript=True)

    bindings = revit_io.check_bindings(doc, config.REQUIRED_SHARED + [config.P_TALO_TEXT])
    missing = [n for n in config.REQUIRED_SHARED if bindings.get(n) is None]
    msgs = []
    if missing:
        msgs.append("V projekte chýbajú parametre: {}\nTieto parametre sa nebudú zapisovať."
                    .format(", ".join(missing)))
    inst = [n for n in config.REQUIRED_SHARED if bindings.get(n) == "instance"]
    if inst:
        msgs.append("Inštančné (nie typové) parametre: {}\nZapíšu sa na všetky inštancie typu."
                    .format(", ".join(inst)))
    if warnings:
        msgs.append("Mapovacia tabuľka:\n- " + "\n- ".join(warnings[:15]))
    if msgs and not forms.alert("\n\n".join(msgs) + "\n\nPokračovať?", yes=True, no=True):
        return

    state = State(rows, cat_map, bindings)
    pre = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    if pre:
        state.set_picked([e for e in pre if e is not None])

    while True:
        win = TaloWindow(state)
        win.show_dialog()
        if win.result != "pick":
            break
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element,
                                               "Vyber prvky a potvrď Finish / Dokončiť")
        except OperationCanceledException:
            continue
        n = state.set_picked([doc.GetElement(r.ElementId) for r in refs])
        if n == 0:
            forms.alert("Vo výbere nie sú typy z kategórií mapovacej tabuľky.")


main()

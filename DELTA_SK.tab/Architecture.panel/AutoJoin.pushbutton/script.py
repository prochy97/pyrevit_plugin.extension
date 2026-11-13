# -*- coding: utf-8 -*-
"""Spojí (Join Geometry) prvky v aktívnom pohľade.

Postup:
1. (Nepovinné) Označ v Revite prvky, ktoré sa NEMAJÚ joinovať.
2. Spusti AutoJoin a vyber kategórie.
3. Skontroluj súhrn a potvrď.

Pravidlá:
- Konštrukčné prvky majú vždy prednosť (režú nekonštrukčné).
- Medzi konštrukčnými: základy > stĺpy > trámy > stropy > steny.
- Poradie medzi nekonštrukčnými určí Revit.
- Joinujú sa len prvky, ktorých objemy sa reálne prekrývajú.
- Celú operáciu vráti jedno Ctrl+Z.
"""
__title__ = 'AutoJoin'
__author__ = 'Matej'

from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

doc = revit.doc
uidoc = revit.uidoc
view = doc.ActiveView
output = script.get_output()


# =============================================================================
# NASTAVENIA
# =============================================================================
BATCH_SIZE = 50          # koľko operácií sa robí v jednej dávke
BB_TOLERANCE = 0.01      # stopy (cca 3 mm) - len rýchly predvýber, o joine rozhoduje skutočný prienik
MAX_REPORT_ROWS = 200    # max. riadkov v zozname neúspešných

ALLOWED_CATS = [
    DB.BuiltInCategory.OST_Walls,
    DB.BuiltInCategory.OST_Floors,
    DB.BuiltInCategory.OST_Ceilings,
    DB.BuiltInCategory.OST_Stairs,
    DB.BuiltInCategory.OST_Columns,
    DB.BuiltInCategory.OST_StructuralColumns,
    DB.BuiltInCategory.OST_StructuralFoundation,
    DB.BuiltInCategory.OST_StructuralFraming,
    DB.BuiltInCategory.OST_Roofs,
]

CAT_WALLS = int(DB.BuiltInCategory.OST_Walls)
CAT_FLOORS = int(DB.BuiltInCategory.OST_Floors)

# Poradie konštrukčných prvkov (menšie číslo = vyššia priorita = reže)
STRUCT_RANK_BY_CAT = {
    int(DB.BuiltInCategory.OST_StructuralFoundation): 0,
    int(DB.BuiltInCategory.OST_StructuralColumns): 1,
    int(DB.BuiltInCategory.OST_StructuralFraming): 2,
}
RANK_STRUCT_FLOOR = 3
RANK_STRUCT_WALL = 4


# =============================================================================
# POMOCNÉ FUNKCIE
# =============================================================================
def eid_int(eid):
    """Číslo ElementId - funguje v Revite 2023 aj 2024+."""
    try:
        return eid.Value          # Revit 2024+
    except AttributeError:
        return eid.IntegerValue   # Revit 2023


def pair_key(a, b):
    return (a, b) if a < b else (b, a)


def cat_id(el):
    return eid_int(el.Category.Id)


def label(el):
    return u"{} {}".format(el.Category.Name, eid_int(el.Id))


def param_on(el, bip):
    p = el.get_Parameter(bip)
    return bool(p and p.HasValue and p.AsInteger() == 1)


_rank_cache = {}


def struct_rank(el):
    """None = nekonštrukčný prvok, inak číslo priority (0 = najvyššia)."""
    key = eid_int(el.Id)
    if key in _rank_cache:
        return _rank_cache[key]
    cid = cat_id(el)
    rank = None
    if cid in STRUCT_RANK_BY_CAT:
        rank = STRUCT_RANK_BY_CAT[cid]
    elif cid == CAT_FLOORS and param_on(el, DB.BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL):
        rank = RANK_STRUCT_FLOOR
    elif cid == CAT_WALLS and param_on(el, DB.BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT):
        rank = RANK_STRUCT_WALL
    _rank_cache[key] = rank
    return rank


def desired_cutter(a, b):
    """Ktorý prvok má rezať. None = nechať na Revite."""
    ra, rb = struct_rank(a), struct_rank(b)
    if ra is None and rb is None:
        return None
    if ra is None:
        return b
    if rb is None:
        return a
    if ra < rb:
        return a
    if rb < ra:
        return b
    return None


def existing_fix(a, b):
    """Existujúci join opravíme len ak nekonštrukčný reže konštrukčný."""
    ra, rb = struct_rank(a), struct_rank(b)
    if (ra is None) == (rb is None):
        return None
    struct_el, other = (a, b) if ra is not None else (b, a)
    try:
        if DB.JoinGeometryUtils.IsCuttingElementInJoin(doc, struct_el, other):
            return None
    except Exception:
        return None
    return (struct_el, other)


def is_editable(el):
    """Vo workshared modeli vynechá prvky obsadené iným používateľom."""
    if not doc.IsWorkshared:
        return True
    try:
        if DB.WorksharingUtils.GetCheckoutStatus(doc, el.Id) == DB.CheckoutStatus.OwnedByOtherUser:
            return False
        status = DB.WorksharingUtils.GetModelUpdatesStatus(doc, el.Id)
        if status == DB.ModelUpdatesStatus.UpdatedInCentral or \
                status == DB.ModelUpdatesStatus.DeletedInCentral:
            return False
    except Exception:
        pass
    return True


class FailureCollector(DB.IFailuresPreprocessor):
    """Warningy zapíše do reportu a zmaže. Pri chybe dávku potichu vráti späť."""

    def __init__(self):
        self.warnings = []
        self.errors = []

    def PreprocessFailures(self, fa):
        has_error = False
        for f in fa.GetFailureMessages():
            text = f.GetDescriptionText()
            ids = list(f.GetFailingElementIds())
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                self.warnings.append((text, ids))
                fa.DeleteWarning(f)
            else:
                self.errors.append((text, ids))
                has_error = True
        if has_error:
            return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue


def do_op(op):
    """Vykoná jednu operáciu. Vracia (výsledok, prvok1, prvok2, dôvod)."""
    kind, a, b = op
    if kind == "fix":
        try:
            if DB.JoinGeometryUtils.AreElementsJoined(doc, a, b) and \
                    not DB.JoinGeometryUtils.IsCuttingElementInJoin(doc, a, b):
                DB.JoinGeometryUtils.SwitchJoinOrder(doc, a, b)
                return ("fixed", a, b, None)
            return ("unchanged", a, b, None)
        except Exception as ex:
            return ("failed", a, b, u"Oprava poradia: {}".format(ex))

    # kind == "join"
    try:
        if DB.JoinGeometryUtils.AreElementsJoined(doc, a, b):
            return ("unchanged", a, b, None)
        DB.JoinGeometryUtils.JoinGeometry(doc, a, b)
    except Exception as ex:
        return ("failed", a, b, u"{}".format(ex))

    cutter = desired_cutter(a, b)
    if cutter is None:
        return ("joined", a, b, None)
    other = b if eid_int(cutter.Id) == eid_int(a.Id) else a
    try:
        if not DB.JoinGeometryUtils.IsCuttingElementInJoin(doc, cutter, other):
            DB.JoinGeometryUtils.SwitchJoinOrder(doc, cutter, other)
            return ("switched", a, b, None)
    except Exception as ex:
        return ("failed", a, b, u"Spojené, ale poradie sa nepodarilo nastaviť: {}".format(ex))
    return ("joined", a, b, None)


def run_batch(batch):
    """Jedna dávka = jedna transakcia. Vracia (úspech, výsledky, collector)."""
    fc = FailureCollector()
    t = DB.Transaction(doc, "AutoJoin")
    t.Start()
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(fc)
    opts.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(opts)
    results = []
    try:
        for op in batch:
            results.append(do_op(op))
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        fc.errors.append((u"{}".format(ex), []))
        return False, [], fc
    status = t.Commit()
    return status == DB.TransactionStatus.Committed, results, fc


# =============================================================================
# 1. KONTROLA A ZBER PRVKOV V AKTÍVNOM POHĽADE
# =============================================================================
if doc.IsFamilyDocument:
    forms.alert(u"AutoJoin funguje len v projekte, nie v rodine.", exitscript=True)

excluded_ids = set(eid_int(i) for i in uidoc.Selection.GetElementIds())

try:
    cat_filter = DB.ElementMulticategoryFilter(List[DB.BuiltInCategory](ALLOWED_CATS))
    view_elements = DB.FilteredElementCollector(doc, view.Id) \
        .WherePasses(cat_filter) \
        .WhereElementIsNotElementType() \
        .ToElements()
except Exception:
    view_elements = []

skipped_excluded = 0
skipped_group = 0
skipped_owned = []
valid = []

for el in view_elements:
    if el.Category is None:
        continue
    if eid_int(el.Id) in excluded_ids:
        skipped_excluded += 1
        continue
    if eid_int(el.GroupId) != -1:
        skipped_group += 1
        continue
    if el.get_BoundingBox(None) is None:
        continue
    if not is_editable(el):
        skipped_owned.append(el.Id)
        continue
    valid.append(el)

if not valid:
    forms.alert(u"V aktívnom pohľade nie sú žiadne prvky na spojenie.\n\n"
                u"Otvor pohľad s modelom (pôdorys, rez, 3D) a skús znova.",
                exitscript=True)


# =============================================================================
# 2. VÝBER KATEGÓRIÍ
# =============================================================================
counts = {}
cat_by_name = {}
for el in valid:
    name = el.Category.Name
    counts[name] = counts.get(name, 0) + 1
    cat_by_name[name] = cat_id(el)

display_to_name = {}
for name, cnt in counts.items():
    display_to_name[u"{} ({})".format(name, cnt)] = name

dialog_title = u"AutoJoin – {}".format(view.Name)
if skipped_excluded:
    dialog_title += u"  |  vynechaných označených: {}".format(skipped_excluded)

picked = forms.SelectFromList.show(
    sorted(display_to_name.keys()),
    title=dialog_title,
    button_name=u"Pokračovať",
    multiselect=True
)
if not picked:
    script.exit()

chosen_cat_ids = set(cat_by_name[display_to_name[p]] for p in picked)
elements = [e for e in valid if cat_id(e) in chosen_cat_ids]

if len(elements) < 2:
    forms.alert(u"Na spojenie treba aspoň 2 prvky.", exitscript=True)


# =============================================================================
# 3. ANALÝZA (nič sa ešte nemení)
# =============================================================================
by_id = dict((eid_int(e.Id), e) for e in elements)
id_list = List[DB.ElementId]([e.Id for e in elements])

seen = set()
fix_ops = []
join_ops = []
existing_ok = 0
wall_wall_skipped = 0
analysis_cancelled = False

with forms.ProgressBar(title=u"AutoJoin – analyzujem prvky...", cancellable=True) as pb:
    total = len(elements)
    for i, el in enumerate(elements):
        if pb.cancelled:
            analysis_cancelled = True
            break
        if i % 20 == 0:
            pb.update_progress(i, total)

        own = eid_int(el.Id)

        # a) existujúce joiny
        try:
            joined_ids = DB.JoinGeometryUtils.GetJoinedElements(doc, el)
        except Exception:
            joined_ids = []
        for jid in joined_ids:
            oid = eid_int(jid)
            other = by_id.get(oid)
            if other is None:
                continue
            key = pair_key(own, oid)
            if key in seen:
                continue
            seen.add(key)
            fix = existing_fix(el, other)
            if fix:
                fix_ops.append(("fix", fix[0], fix[1]))
            else:
                existing_ok += 1

        # b) nové prieniky (najprv rýchly bounding box, potom skutočná geometria)
        bb = el.get_BoundingBox(None)
        outline = DB.Outline(
            DB.XYZ(bb.Min.X - BB_TOLERANCE, bb.Min.Y - BB_TOLERANCE, bb.Min.Z - BB_TOLERANCE),
            DB.XYZ(bb.Max.X + BB_TOLERANCE, bb.Max.Y + BB_TOLERANCE, bb.Max.Z + BB_TOLERANCE)
        )
        try:
            geo_filter = DB.ElementIntersectsElementFilter(el)
            candidates = DB.FilteredElementCollector(doc, id_list) \
                .WherePasses(DB.BoundingBoxIntersectsFilter(outline)) \
                .WherePasses(geo_filter)
        except Exception:
            continue

        for other in candidates:
            oid = eid_int(other.Id)
            if oid == own:
                continue
            key = pair_key(own, oid)
            if key in seen:
                continue
            seen.add(key)
            if cat_id(el) == CAT_WALLS and cat_id(other) == CAT_WALLS:
                wall_wall_skipped += 1
                continue
            join_ops.append(("join", el, other))

if analysis_cancelled:
    script.exit()

ops = fix_ops + join_ops

if not ops:
    forms.alert(u"Nie je čo spojiť ani opraviť.\n\n"
                u"Existujúce joiny bez zmeny: {}".format(existing_ok),
                exitscript=True)


# =============================================================================
# 4. SÚHRN PRED SPUSTENÍM
# =============================================================================
summary = [
    u"Pohľad: {}".format(view.Name),
    u"Prvkov na spracovanie: {}".format(len(elements)),
    u"",
    u"Nové joiny: {}".format(len(join_ops)),
    u"Oprava existujúcich joinov (nekonštrukčný reže konštrukčný): {}".format(len(fix_ops)),
    u"Existujúce joiny bez zmeny: {}".format(existing_ok),
    u"",
    u"Vynechané:",
    u"  – označené pred spustením: {}".format(skipped_excluded),
    u"  – prvky v skupinách: {}".format(skipped_group),
    u"  – obsadené iným používateľom: {}".format(len(skipped_owned)),
    u"  – dvojice stena–stena: {}".format(wall_wall_skipped),
    u"",
    u"Pokračovať?",
]

if not forms.alert(u"\n".join(summary), title=u"AutoJoin – kontrola",
                   ok=False, yes=True, no=True):
    script.exit()


# =============================================================================
# 5. VYKONANIE (dávky v jednej skupine = jedno Ctrl+Z)
# =============================================================================
pair_stats = {}       # "Kategória ↔ Kategória" -> [joined, switched]
fixed_count = 0
failures = []         # (prvok1, prvok2, dôvod)
warnings = {}         # text -> [ElementId]
cancelled = False
done = 0


def accept(results, fc):
    global fixed_count
    for kind, a, b, reason in results:
        if kind == "failed":
            failures.append((a, b, reason))
        elif kind in ("joined", "switched"):
            names = sorted([a.Category.Name, b.Category.Name])
            key = u"{} ↔ {}".format(names[0], names[1])
            stat = pair_stats.setdefault(key, [0, 0])
            stat[0] += 1
            if kind == "switched":
                stat[1] += 1
        elif kind == "fixed":
            fixed_count += 1
    for text, ids in fc.warnings:
        warnings.setdefault(text, []).extend(ids)


tg = DB.TransactionGroup(doc, u"AutoJoin – {}".format(view.Name))
tg.Start()
try:
    with forms.ProgressBar(title=u"AutoJoin – spájam prvky...", cancellable=True) as pb:
        total_ops = len(ops)
        for start in range(0, total_ops, BATCH_SIZE):
            if pb.cancelled:
                cancelled = True
                break
            pb.update_progress(start, total_ops)
            batch = ops[start:start + BATCH_SIZE]

            ok, results, fc = run_batch(batch)
            if ok:
                accept(results, fc)
            else:
                # dávka zlyhala -> skúsime po jednom, aby sme našli chybný pár
                for op in batch:
                    ok1, results1, fc1 = run_batch([op])
                    if ok1:
                        accept(results1, fc1)
                    else:
                        reasons = sorted(set(t for t, _ in fc1.errors))
                        failures.append((op[1], op[2],
                                         u"; ".join(reasons) or u"Revit operáciu odmietol"))
            done = start + len(batch)
    tg.Assimilate()
except Exception as ex:
    if tg.HasStarted() and not tg.HasEnded():
        tg.RollBack()
    forms.alert(u"AutoJoin zlyhal, všetky zmeny boli vrátené.\n\n{}".format(ex),
                exitscript=True)


# =============================================================================
# 6. REPORT
# =============================================================================
joined_total = sum(s[0] for s in pair_stats.values())
switched_total = sum(s[1] for s in pair_stats.values())

output.print_md(u"# AutoJoin – {}".format(view.Name))

if cancelled:
    output.print_md(u"**Prerušené používateľom** – spracovaných {} z {} operácií. "
                    u"Spracovaná časť ostáva v modeli.".format(done, len(ops)))

output.print_table(
    table_data=[
        [u"Nové joiny", joined_total],
        [u"z toho otočené poradie podľa priority", switched_total],
        [u"Opravené existujúce joiny", fixed_count],
        [u"Neúspešné", len(failures)],
    ],
    columns=[u"Výsledok", u"Počet"]
)

if pair_stats:
    rows = [[k, v[0], v[1]] for k, v in sorted(pair_stats.items())]
    output.print_table(
        table_data=rows,
        title=u"Nové joiny podľa kategórií",
        columns=[u"Dvojica", u"Spojené", u"Otočené poradie"]
    )

if failures:
    rows = []
    for a, b, reason in failures[:MAX_REPORT_ROWS]:
        rows.append([
            output.linkify(a.Id, label(a)),
            output.linkify(b.Id, label(b)),
            output.linkify([a.Id, b.Id], u"oba"),
            reason,
        ])
    output.print_table(
        table_data=rows,
        title=u"Neúspešné (klik = zobrazí prvok v modeli)",
        columns=[u"Prvok 1", u"Prvok 2", u"Výber", u"Dôvod"]
    )
    if len(failures) > MAX_REPORT_ROWS:
        output.print_md(u"*… a ďalších {}*".format(len(failures) - MAX_REPORT_ROWS))

if warnings:
    rows = []
    for text, ids in sorted(warnings.items()):
        unique = dict((eid_int(i), i) for i in ids).values()
        rows.append([text, len(unique), output.linkify(list(unique), u"zobraziť")])
    output.print_table(
        table_data=rows,
        title=u"Upozornenia Revitu (potlačené počas behu)",
        columns=[u"Upozornenie", u"Prvkov", u"Výber"]
    )

if skipped_owned:
    output.print_md(u"**Obsadené iným používateľom (nespracované):** {}".format(
        output.linkify(skipped_owned, u"{} prvkov".format(len(skipped_owned)))))

output.print_md(u"---\nCelú operáciu vrátiš jedným **Ctrl+Z**.")

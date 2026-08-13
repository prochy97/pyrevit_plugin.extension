# -*- coding: utf-8 -*-
__title__ = 'Porovnaj\nzmeny'
__doc__ = ('Porovna sucasny stav worksetov voci vybranemu vydaniu.\n'
           'Zafarbi zmenene prvky, vytvori kontrolny 3D pohlad na export '
           'a CSV zoznam zmien.\n\nSHIFT + klik = nastavenia.')

import os
import io
import time

from pyrevit import revit, DB, forms, script

import delta_changes as dc

doc = revit.doc
out = script.get_output()
cfg = script.get_config('delta_koordinacia')

DEFAULTS = {
    'view_mode': 'select',   # none | active | select | plans
    'make_3d': True,
    'make_csv': True,
}


def get(k):
    return getattr(cfg, k, DEFAULTS[k])


if __shiftclick__:  # noqa
    vm = forms.CommandSwitchWindow.show(
        ['none', 'active', 'select', 'plans'],
        message='Kde zafarbit prvky? (none = len kontrolny 3D pohlad)')
    if vm:
        cfg.view_mode = vm
    cfg.make_3d = forms.alert('Vytvarat kontrolny 3D pohlad na export?',
                              yes=True, no=True)
    cfg.make_csv = forms.alert('Generovat CSV zoznam zmien?', yes=True, no=True)
    script.save_config()
    forms.alert('Nastavenia ulozene.', title='DeltaTools')
    script.exit()

# ----------------------------------------------------------------------
# 1) vyber vydania = vyber profesie/worksetov
# ----------------------------------------------------------------------
milestones = dc.list_milestones(doc)
if not milestones:
    forms.alert('Pre tento model neexistuje ziadne vydanie.\n'
                'Najprv spusti "Vydanie pre profesiu".', exitscript=True)

opts = {}
for m in milestones:
    lbl = '{0}   |   {1}   |   {2} prvkov   |   worksety: {3}'.format(
        m['name'], m['created_str'], m['count'], ', '.join(m['workset_names']))
    opts[lbl] = m

sel = forms.SelectFromList.show(list(opts.keys()),
                                title='Voci ktoremu vydaniu porovnat?',
                                button_name='Porovnaj')
if not sel:
    script.exit()

milestone = dc.load_milestone(doc, opts[sel]['name'])
ws_ids = dc.milestone_workset_ids(doc, milestone)
if not ws_ids:
    forms.alert('Worksety tohto vydania sa v modeli uz nenasli:\n{0}'.format(
        ', '.join(milestone.get('workset_names', []))), exitscript=True)

# ----------------------------------------------------------------------
# 2) porovnanie
# ----------------------------------------------------------------------
with forms.ProgressBar(title='Porovnavam...', indeterminate=True):
    changes, deleted, scope_elements = dc.compare(doc, milestone, ws_ids)

if not changes and not deleted:
    forms.alert('Ziadne geometricke zmeny voci vydaniu "{0}" ({1}).'.format(
        milestone['name'], milestone['created_str']), title='DeltaTools')
    script.exit()

by_type = {}
for elid, (ctype, rec, old) in changes.items():
    by_type.setdefault(ctype, []).append(elid)

# ----------------------------------------------------------------------
# 3) zafarbenie v pohladoch
# ----------------------------------------------------------------------
fill = dc.solid_fill_id(doc)
ogs_cache = dict((k, dc.make_override(doc, v, fill)) for k, v in dc.COLORS.items())
ogs_map = dict((elid, ogs_cache[c]) for elid, (c, r, o) in changes.items())

VIEW_MODE = get('view_mode')


def target_views():
    if VIEW_MODE == 'none':
        return []
    if VIEW_MODE == 'active':
        return [doc.ActiveView]
    if VIEW_MODE == 'select':
        return forms.select_views(title='Vyber pohlady na zafarbenie') or []
    res = []
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements():
        if v.IsTemplate:
            continue
        if isinstance(v, DB.ViewPlan) and v.ViewType in (
                DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan,
                DB.ViewType.EngineeringPlan, DB.ViewType.AreaPlan):
            res.append(v)
    return res


views = target_views()
applied_map = {}
applied_total = 0

if views:
    with revit.Transaction('DeltaTools - zafarbenie zmien'):
        with forms.ProgressBar(title='Farbim {value}/{max_value}') as pb:
            for i, v in enumerate(views, 1):
                pb.update_progress(i, len(views))
                visible = dc.visible_ids_in_view(doc, v)
                here = []
                for elid, ogs in ogs_map.items():
                    if visible is not None and elid not in visible:
                        continue
                    try:
                        v.SetElementOverrides(DB.ElementId(elid), ogs)
                        here.append(elid)
                    except Exception:
                        continue
                if here:
                    applied_map[dc.eid(v.Id)] = here
                    applied_total += len(here)
    dc.record_overrides(doc, applied_map)

# ----------------------------------------------------------------------
# 4) kontrolny 3D pohlad na export
# ----------------------------------------------------------------------
review_view = None
if get('make_3d') and changes:
    vname = 'KONTROLA - zmeny od {0}'.format(milestone['name'])
    with revit.Transaction('DeltaTools - kontrolny 3D pohlad'):
        review_view = dc.create_review_view(doc, vname, list(changes.keys()), ogs_map)

# ----------------------------------------------------------------------
# 5) CSV
# ----------------------------------------------------------------------
csv_path = None
if get('make_csv'):
    try:
        folder = os.path.dirname(doc.PathName) if doc.PathName else os.path.expanduser('~')
        folder = os.path.join(folder, '_zmeny')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        csv_path = os.path.join(folder, 'zmeny_{0}_{1}.csv'.format(
            milestone['name'], time.strftime('%Y%m%d_%H%M')))

        wsmap = dc.workset_name_map(doc)
        rows = [u'ElementId;Typ zmeny;Posun [mm];Kategoria;Typ prvku;Podlazie;'
                u'Workset;Mark;X [mm];Y [mm];Z [mm]']
        for elid in sorted(changes.keys(), key=lambda k: changes[k][0]):
            ctype, r, old = changes[elid]
            posun = str(dc.delta_mm(old, r)) if old else ''
            rows.append(u';'.join([
                str(elid), ctype, posun, r.get('c', ''), r.get('n', ''),
                r.get('v', ''), wsmap.get(r.get('w', 0), ''), r.get('m', ''),
                str(r.get('cx', '')), str(r.get('cy', '')), str(r.get('cz', ''))]))
        for elid, r in deleted:
            rows.append(u';'.join([
                str(elid), dc.DELETED, '', r.get('c', ''), r.get('n', ''),
                r.get('v', ''), wsmap.get(r.get('w', 0), ''), r.get('m', ''),
                str(r.get('cx', '')), str(r.get('cy', '')), str(r.get('cz', ''))]))

        with io.open(csv_path, 'w', encoding='utf-8-sig') as f:
            f.write(u'\r\n'.join(rows))
    except Exception as ex:
        csv_path = None
        out.print_md('*CSV sa nepodarilo zapisat: {0}*'.format(ex))

# ----------------------------------------------------------------------
# 6) report
# ----------------------------------------------------------------------
out.print_md('# Zmeny voci vydaniu `{0}`'.format(milestone['name']))
out.print_md('*Vydanie z {0} | worksety: {1} | tolerancia: {2} mm*'.format(
    milestone['created_str'], ', '.join(milestone.get('workset_names', [])),
    dc.TOL_MM))
if milestone.get('note'):
    out.print_md('*Poznamka: {0}*'.format(milestone['note']))

summary = [[c, len(by_type.get(c, []))] for c in dc.ORDER]
summary.append([dc.DELETED, len(deleted)])
out.print_table(summary, columns=['Typ zmeny', 'Pocet'])

out.print_md('- Prvkov v rozsahu: **{0}**'.format(len(scope_elements)))
out.print_md('- Prepisov v pohladoch: **{0}** v **{1}** pohladoch'.format(
    applied_total, len(applied_map)))
if review_view is not None:
    out.print_md('- Kontrolny pohlad: **{0}**  {1}'.format(
        DB.Element.Name.__get__(review_view), out.linkify(review_view.Id)))
    out.print_md('  *IFC/NWC export rob z tohto pohladu so zapnutym '
                 '"Export only elements visible in view".*')
if csv_path:
    out.print_md('- CSV: `{0}`'.format(csv_path))

for ctype in dc.ORDER:
    ids = by_type.get(ctype, [])
    if not ids:
        continue
    out.print_md('### {0} ({1})'.format(ctype, len(ids)))
    rows = []
    for elid in ids[:300]:
        c, r, old = changes[elid]
        rows.append([out.linkify(DB.ElementId(elid)), r.get('c', ''),
                     r.get('n', ''), r.get('v', ''), r.get('m', ''),
                     str(dc.delta_mm(old, r)) if old else '-'])
    out.print_table(rows, columns=['ID', 'Kategoria', 'Typ', 'Podlazie',
                                   'Mark', 'Posun [mm]'])
    if len(ids) > 300:
        out.print_md('*... a dalsich {0}, pozri CSV*'.format(len(ids) - 300))

if deleted:
    out.print_md('### {0} ({1}) - v modeli uz nie su, lokalizuj podla suradnic'
                 .format(dc.DELETED, len(deleted)))
    rows = [[str(elid), r.get('c', ''), r.get('n', ''), r.get('v', ''),
             '{0} / {1} / {2}'.format(r.get('cx'), r.get('cy'), r.get('cz'))]
            for elid, r in deleted[:300]]
    out.print_table(rows, columns=['ID (povodne)', 'Kategoria', 'Typ',
                                   'Podlazie', 'X/Y/Z [mm]'])

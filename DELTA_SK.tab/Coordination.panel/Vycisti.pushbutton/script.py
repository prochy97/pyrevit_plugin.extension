# -*- coding: utf-8 -*-
__title__ = 'Vycisti'
__doc__ = 'Zrusi graficke prepisy a/alebo zmaze kontrolne 3D pohlady.'

from pyrevit import revit, DB, forms, script

import delta_changes as dc

doc = revit.doc

what = forms.SelectFromList.show(
    ['Graficke prepisy v pohladoch', 'Kontrolne 3D pohlady'],
    title='Co vycistit?', multiselect=True, button_name='Vycisti')
if not what:
    script.exit()

msgs = []

if 'Graficke prepisy v pohladoch' in what:
    stored = dc.stored_overrides(doc)
    empty = DB.OverrideGraphicSettings()
    n = 0
    with revit.Transaction('DeltaTools - zrusenie prepisov'):
        for vid, ids in stored.items():
            v = doc.GetElement(DB.ElementId(int(vid)))
            if not isinstance(v, DB.View):
                continue
            for i in ids:
                try:
                    v.SetElementOverrides(DB.ElementId(int(i)), empty)
                    n += 1
                except Exception:
                    continue
    dc.clear_stored_overrides(doc)
    msgs.append('Zrusenych prepisov: {0}'.format(n))

if 'Kontrolne 3D pohlady' in what:
    targets = []
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D).ToElements():
        try:
            nm = DB.Element.Name.__get__(v)
        except Exception:
            continue
        if nm.startswith('KONTROLA - zmeny'):
            targets.append(v)
    if not targets:
        msgs.append('Ziadne kontrolne pohlady nenajdene.')
    else:
        labels = dict((DB.Element.Name.__get__(v), v) for v in targets)
        picked = forms.SelectFromList.show(sorted(labels.keys()),
                                           title='Zmazat kontrolne pohlady',
                                           multiselect=True, button_name='Zmazat')
        if picked:
            with revit.Transaction('DeltaTools - mazanie pohladov'):
                for p in picked:
                    try:
                        doc.Delete(labels[p].Id)
                    except Exception:
                        continue
            msgs.append('Zmazanych pohladov: {0}'.format(len(picked)))

forms.alert('\n'.join(msgs) or 'Nic sa neurobilo.', title='DeltaTools')

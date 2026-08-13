# -*- coding: utf-8 -*-
__title__ = 'Vydanie\npre profesiu'
__doc__ = ('Ulozi odtlacok VYBRANYCH WORKSETOV ako pomenovane vydanie.\n'
           'Spusti to vzdy pri odovzdani modelu profesii (statika, MEP, ...).\n'
           'Kazda profesia ma vlastne vydanie nad vlastnymi worksetmi.')

import time
from pyrevit import revit, forms, script

import delta_changes as dc

doc = revit.doc
out = script.get_output()

if not doc.IsWorkshared:
    forms.alert('Model nie je workshared - worksety neexistuju.', exitscript=True)

wsets = dc.user_worksets(doc)
if not wsets:
    forms.alert('Ziadne user worksety.', exitscript=True)

# ----------------------------------------------------------------------
# 1) profesia - urcuje nazov vydania a predvolbu worksetov
# ----------------------------------------------------------------------
existing = dc.list_milestones(doc)

# unikatne profesie z uz existujucich vydani (prefix pred datumom)
known = []
for m in existing:
    pref = m['name'].rsplit('_', 1)[0]
    if pref and pref not in known:
        known.append(pref)

choices = known + ['+ nova profesia']
profession = forms.CommandSwitchWindow.show(
    choices, message='Pre ktoru profesiu robis vydanie?') if known else '+ nova profesia'
if not profession:
    script.exit()

if profession == '+ nova profesia':
    profession = forms.ask_for_string(
        default='STATIKA',
        prompt='Nazov profesie (napr. STATIKA, MEP_ZTI, MEP_VZT, ELI):',
        title='Nova profesia')
    if not profession:
        script.exit()
    profession = profession.strip().upper().replace(' ', '_')

# worksety naposledy pouzite pre tuto profesiu
last_ws = []
for m in existing:
    if m['name'].rsplit('_', 1)[0] == profession:
        last_ws = m['workset_names']
        break

# ----------------------------------------------------------------------
# 2) vyber worksetov
# ----------------------------------------------------------------------
active_id = dc.eid(doc.GetWorksetTable().GetActiveWorksetId())
labels = {}
for w in wsets:
    tags = []
    if w.Name in last_ws:
        tags.append('naposledy')
    if dc.eid(w.Id) == active_id:
        tags.append('aktivny')
    lbl = w.Name + ('   [{0}]'.format(', '.join(tags)) if tags else '')
    labels[lbl] = w

# naposledy pouzite hore
ordered = sorted(labels.keys(),
                 key=lambda k: (0 if 'naposledy' in k else 1, k))

picked = forms.SelectFromList.show(
    ordered,
    title='Worksety pre profesiu {0}'.format(profession),
    multiselect=True,
    button_name='Dalej')
if not picked:
    script.exit()

workset_ids = [labels[p].Id for p in picked]
ws_names = [labels[p].Name for p in picked]

# ----------------------------------------------------------------------
# 3) nazov a poznamka
# ----------------------------------------------------------------------
name = forms.ask_for_string(
    default='{0}_{1}'.format(profession, time.strftime('%Y-%m-%d')),
    prompt='Nazov vydania:',
    title='Vydanie pre profesiu')
if not name:
    script.exit()

note = forms.ask_for_string(
    default='', prompt='Poznamka (nepovinne):',
    title='Vydanie pre profesiu') or ''

if name in [m['name'] for m in existing]:
    if not forms.alert('Vydanie "{0}" uz existuje. Prepisat?'.format(name),
                       yes=True, no=True):
        script.exit()

with forms.ProgressBar(title='Vytvaram odtlacok...', indeterminate=True):
    snap = dc.create_milestone(doc, name, workset_ids, note=note)

out.print_md('## Vydanie ulozene')
out.print_md('- Nazov: **{0}**'.format(snap['name']))
out.print_md('- Worksety: **{0}**'.format(', '.join(ws_names)))
out.print_md('- Prvkov: **{0}**  (za {1} s)'.format(snap['count'], snap['duration']))
out.print_md('')
out.print_md('Odovzdaj model profesii. Pri dalsej koordinacii spusti '
             '**Porovnaj zmeny** a vyber toto vydanie.')

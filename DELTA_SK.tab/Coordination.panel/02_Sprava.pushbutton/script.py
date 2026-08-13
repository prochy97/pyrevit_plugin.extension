# -*- coding: utf-8 -*-
__doc__ = 'Prehlad vydani pre tento model, zoskupene podla profesie. Mazanie starych.'

import os
from pyrevit import revit, forms, script

import delta_changes as dc

doc = revit.doc
out = script.get_output()

ms = dc.list_milestones(doc)
if not ms:
    forms.alert('Pre tento model nie su ulozene ziadne vydania.', exitscript=True)

groups = {}
for m in ms:
    groups.setdefault(m['name'].rsplit('_', 1)[0], []).append(m)

out.print_md('# Vydania - model `{0}`'.format(doc.Title))
for prof in sorted(groups.keys()):
    out.print_md('## {0}'.format(prof))
    out.print_table(
        [[m['name'], m['created_str'], str(m['count']),
          ', '.join(m['workset_names']), m.get('note', '')]
         for m in groups[prof]],
        columns=['Nazov', 'Vytvorene', 'Prvkov', 'Worksety', 'Poznamka'])

out.print_md('*Ulozisko: `{0}`*'.format(dc.model_dir(doc)))

if forms.alert('Zmazat niektore vydania?', yes=True, no=True):
    labels = dict(('{0}  ({1})'.format(m['name'], m['created_str']), m) for m in ms)
    to_del = forms.SelectFromList.show(sorted(labels.keys()),
                                       title='Zmazat vydania',
                                       multiselect=True, button_name='Zmazat')
    if to_del:
        n = 0
        for lbl in to_del:
            try:
                os.remove(labels[lbl]['file'])
                n += 1
            except Exception:
                pass
        forms.alert('Zmazanych: {0}'.format(n), title='DeltaTools')

# -*- coding: utf-8 -*-
"""
delta_changes.py  -  sledovanie geometrickych zmien pre medziprofesijnu koordinaciu.

Princip:
  Revit API neposkytuje datum poslednej zmeny prvku, preto sa pracuje
  s pomenovanymi VYDANIAMI (milestone). Vydanie = odtlacok vybranych
  worksetov v okamihu, kedy si model odovzdal profesii.

  Kazde vydanie ma vlastne worksety. Statika = jedno vydanie nad worksetom
  statiky, MEP = ine vydanie nad worksetom MEP. Nemiesaju sa.

Sleduje sa VYLUCNE geometria:
  - pribudol / zmizol prvok
  - posunul sa
  - zmenil rozmer
  - vymenil sa typ
Parametre sa nesleduju a nezapisuju.
"""

import os
import io
import json
import time
import hashlib

from System.Collections.Generic import List
from Autodesk.Revit import DB


ROOT = os.path.join(os.getenv('APPDATA'), 'DeltaTools', 'ChangeTracker')

# tolerancia v mm - zmeny mensie ako toto sa ignoruju (potlaci sum z regenu)
TOL_MM = 1.0
TOL_ROT = 0.001          # rad
FT_TO_MM = 304.8

# typy zmien
NEW = 'NOVY'
DELETED = 'ZMAZANY'
MOVED = 'POSUNUTY'
RESIZED = 'ZMENENY_ROZMER'
RETYPED = 'ZMENENY_TYP'

ORDER = [NEW, MOVED, RESIZED, RETYPED]

COLORS = {
    NEW:     (0, 170, 60),      # zelena
    MOVED:   (255, 120, 0),     # oranzova
    RESIZED: (220, 0, 180),     # magenta
    RETYPED: (0, 110, 235),     # modra
}


# =======================================================================
# pomocne
# =======================================================================

def eid(element_id):
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def _q(ft):
    """Kvantizacia dlzky: stopy -> celociselne nasobky TOL_MM."""
    return int(round((ft * FT_TO_MM) / TOL_MM))


def _ensure_dir(path):
    if path and not os.path.isdir(path):
        os.makedirs(path)


def model_key(doc):
    path = None
    try:
        if doc.IsWorkshared:
            mp = doc.GetWorksharingCentralModelPath()
            path = DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(mp)
    except Exception:
        path = None
    if not path:
        path = doc.PathName or doc.Title
    return hashlib.md5(path.lower().encode('utf-8')).hexdigest()


def model_dir(doc):
    d = os.path.join(ROOT, model_key(doc))
    _ensure_dir(d)
    return d


def read_json(path, default=None):
    if not os.path.isfile(path):
        return default
    try:
        with io.open(path, 'r', encoding='utf-8') as f:
            return json.loads(f.read())
    except Exception:
        return default


def write_json(path, data):
    _ensure_dir(os.path.dirname(path))
    txt = json.dumps(data, ensure_ascii=True)
    if not isinstance(txt, type(u'')):
        txt = txt.decode('utf-8')
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(txt)


# =======================================================================
# worksety
# =======================================================================

def user_worksets(doc):
    if not doc.IsWorkshared:
        return []
    col = DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset)
    return sorted(list(col), key=lambda w: w.Name)


def workset_name_map(doc):
    return dict((eid(w.Id), w.Name) for w in user_worksets(doc))


def collect_by_worksets(doc, workset_ids):
    """Model prvky vo vybranych worksetoch (bez typov, bez 2D anotacii)."""
    col = DB.FilteredElementCollector(doc).WhereElementIsNotElementType()

    if workset_ids:
        filters = [DB.ElementWorksetFilter(wid, False) for wid in workset_ids]
        if len(filters) == 1:
            col = col.WherePasses(filters[0])
        else:
            col = col.WherePasses(DB.LogicalOrFilter(List[DB.ElementFilter](filters)))

    out = []
    for el in col:
        cat = el.Category
        if cat is None:
            continue
        try:
            if cat.CategoryType != DB.CategoryType.Model:
                continue
        except Exception:
            continue
        if el.ViewSpecific:
            continue
        out.append(el)
    return out


# =======================================================================
# zaznam prvku - iba geometria
# =======================================================================

def _loc(el):
    try:
        loc = el.Location
        if isinstance(loc, DB.LocationPoint):
            p = loc.Point
            rot = 0
            try:
                rot = int(round(loc.Rotation / TOL_ROT))
            except Exception:
                pass
            return 'P{0},{1},{2},{3}'.format(_q(p.X), _q(p.Y), _q(p.Z), rot)
        if isinstance(loc, DB.LocationCurve):
            c = loc.Curve
            a = c.GetEndPoint(0)
            b = c.GetEndPoint(1)
            return 'C{0},{1},{2},{3},{4},{5}'.format(
                _q(a.X), _q(a.Y), _q(a.Z), _q(b.X), _q(b.Y), _q(b.Z))
    except Exception:
        pass
    return ''


def _bbox(el):
    """Vrati (podpis rozmerov, stred v mm). Rozmery su nezavisle od polohy,
    aby sa cisty posun nehlasil aj ako zmena rozmeru."""
    try:
        bb = el.get_BoundingBox(None)
        if bb:
            dx = _q(bb.Max.X - bb.Min.X)
            dy = _q(bb.Max.Y - bb.Min.Y)
            dz = _q(bb.Max.Z - bb.Min.Z)
            cx = (bb.Min.X + bb.Max.X) / 2.0 * FT_TO_MM
            cy = (bb.Min.Y + bb.Max.Y) / 2.0 * FT_TO_MM
            cz = (bb.Min.Z + bb.Max.Z) / 2.0 * FT_TO_MM
            return '{0},{1},{2}'.format(dx, dy, dz), (cx, cy, cz)
    except Exception:
        pass
    return '', (0.0, 0.0, 0.0)


def _center_ft(el):
    try:
        bb = el.get_BoundingBox(None)
        if bb:
            return ((bb.Min.X + bb.Max.X) / 2.0,
                    (bb.Min.Y + bb.Max.Y) / 2.0,
                    (bb.Min.Z + bb.Max.Z) / 2.0)
    except Exception:
        pass
    return None


def _type_name(doc, el):
    try:
        t = doc.GetElement(el.GetTypeId())
        if t is None:
            return ''
        fam = ''
        try:
            fam = t.FamilyName
        except Exception:
            pass
        nm = DB.Element.Name.__get__(t)
        return (fam + ' : ' + nm).strip(' :')
    except Exception:
        return ''


def _level_name(doc, el):
    try:
        lid = el.LevelId
        if lid and eid(lid) > 0:
            lv = doc.GetElement(lid)
            if lv is not None:
                return DB.Element.Name.__get__(lv)
    except Exception:
        pass
    for bip in ('SCHEDULE_LEVEL_PARAM', 'FAMILY_LEVEL_PARAM',
                'WALL_BASE_CONSTRAINT', 'LEVEL_PARAM'):
        b = getattr(DB.BuiltInParameter, bip, None)
        if b is None:
            continue
        try:
            p = el.get_Parameter(b)
            if p and p.StorageType == DB.StorageType.ElementId:
                lv = doc.GetElement(p.AsElementId())
                if lv is not None:
                    return DB.Element.Name.__get__(lv)
        except Exception:
            continue
    return ''


def element_record(doc, el):
    dims, center = _bbox(el)
    mark = ''
    try:
        p = el.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK)
        if p:
            mark = p.AsString() or ''
    except Exception:
        pass
    return {
        't': eid(el.GetTypeId()),          # typ prvku
        'd': dims,                          # rozmery obalky (nezavisle od polohy)
        'l': _loc(el),                      # poloha / os
        'cx': int(round(center[0])),        # stred obalky [mm]
        'cy': int(round(center[1])),
        'cz': int(round(center[2])),
        'c': el.Category.Name if el.Category else '',
        'n': _type_name(doc, el),
        'v': _level_name(doc, el),
        'w': eid(el.WorksetId) if doc.IsWorkshared else 0,
        'm': mark,
    }


def classify(old, new):
    """Typ zmeny alebo None. Poradie priorit: typ > posun > rozmer."""
    if old.get('t') != new.get('t'):
        return RETYPED
    moved = False
    if old.get('l') != new.get('l'):
        moved = True
    elif (abs(old.get('cx', 0) - new.get('cx', 0)) > TOL_MM or
          abs(old.get('cy', 0) - new.get('cy', 0)) > TOL_MM or
          abs(old.get('cz', 0) - new.get('cz', 0)) > TOL_MM):
        moved = True
    if moved:
        return MOVED
    if old.get('d') != new.get('d'):
        return RESIZED
    return None


def delta_mm(old, new):
    """Velkost posunu stredu obalky v mm."""
    dx = new.get('cx', 0) - old.get('cx', 0)
    dy = new.get('cy', 0) - old.get('cy', 0)
    dz = new.get('cz', 0) - old.get('cz', 0)
    return int(round((dx * dx + dy * dy + dz * dz) ** 0.5))


# =======================================================================
# vydania (milestones)
# =======================================================================

def milestone_path(doc, name):
    safe = ''.join(ch if ch.isalnum() or ch in '-_. ' else '_' for ch in name)
    return os.path.join(model_dir(doc), 'MS_{0}.json'.format(safe))


def list_milestones(doc):
    d = model_dir(doc)
    res = []
    for fn in os.listdir(d):
        if fn.startswith('MS_') and fn.endswith('.json'):
            data = read_json(os.path.join(d, fn), None)
            if data:
                res.append({
                    'name': data.get('name', fn[3:-5]),
                    'created_str': data.get('created_str', '?'),
                    'count': data.get('count', 0),
                    'worksets': data.get('worksets', []),
                    'workset_names': data.get('workset_names', []),
                    'note': data.get('note', ''),
                    'file': os.path.join(d, fn),
                })
    return sorted(res, key=lambda r: r.get('created_str', ''), reverse=True)


def create_milestone(doc, name, workset_ids, note=''):
    elements = collect_by_worksets(doc, workset_ids)
    t0 = time.time()
    data = {}
    for el in elements:
        try:
            data[str(eid(el.Id))] = element_record(doc, el)
        except Exception:
            continue
    wsmap = workset_name_map(doc)
    snap = {
        'name': name,
        'note': note,
        'created': time.time(),
        'created_str': time.strftime('%Y-%m-%d %H:%M:%S'),
        'count': len(data),
        'duration': round(time.time() - t0, 2),
        'worksets': [eid(w) for w in workset_ids],
        'workset_names': [wsmap.get(eid(w), str(eid(w))) for w in workset_ids],
        'model': doc.Title,
        'elements': data,
    }
    write_json(milestone_path(doc, name), snap)
    return snap


def load_milestone(doc, name):
    return read_json(milestone_path(doc, name), None)


def milestone_workset_ids(doc, milestone):
    """Worksety vydania prepocitane na aktualny dokument, podla NAZVU
    (odolne voci precislovaniu worksetov)."""
    names = set(milestone.get('workset_names', []))
    ids_raw = set(milestone.get('worksets', []))
    out = []
    for w in user_worksets(doc):
        if w.Name in names or eid(w.Id) in ids_raw:
            out.append(w.Id)
    return out


def compare(doc, milestone, workset_ids=None):
    """Vrati (changes, deleted, scope_elements).
    changes: {elementIdInt: (typ_zmeny, record, old_record)}"""
    wids = workset_ids if workset_ids else milestone_workset_ids(doc, milestone)

    elements = collect_by_worksets(doc, wids)
    base = milestone.get('elements', {})

    changes = {}
    seen = set()
    for el in elements:
        key = str(eid(el.Id))
        seen.add(key)
        try:
            rec = element_record(doc, el)
        except Exception:
            continue
        old = base.get(key)
        if old is None:
            changes[eid(el.Id)] = (NEW, rec, None)
        else:
            ch = classify(old, rec)
            if ch:
                changes[eid(el.Id)] = (ch, rec, old)

    deleted = [(int(k), v) for k, v in base.items() if k not in seen]
    return changes, deleted, elements


# =======================================================================
# graficke prepisy
# =======================================================================

def solid_fill_id(doc):
    for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
        pat = fp.GetFillPattern()
        if pat.IsSolidFill and pat.Target == DB.FillPatternTarget.Drafting:
            return fp.Id
    return DB.ElementId.InvalidElementId


def make_override(doc, rgb, fill_id=None, weight=6):
    color = DB.Color(rgb[0], rgb[1], rgb[2])
    ogs = DB.OverrideGraphicSettings()
    if fill_id is None:
        fill_id = solid_fill_id(doc)
    try:
        ogs.SetProjectionLineColor(color)
        ogs.SetCutLineColor(color)
        ogs.SetProjectionLineWeight(weight)
        ogs.SetCutLineWeight(weight)
        ogs.SetSurfaceForegroundPatternColor(color)
        ogs.SetSurfaceForegroundPatternId(fill_id)
        ogs.SetSurfaceForegroundPatternVisible(True)
        ogs.SetCutForegroundPatternColor(color)
        ogs.SetCutForegroundPatternId(fill_id)
        ogs.SetCutForegroundPatternVisible(True)
    except AttributeError:
        ogs.SetProjectionLineColor(color)
        ogs.SetCutLineColor(color)
        ogs.SetProjectionFillColor(color)
        ogs.SetProjectionFillPatternId(fill_id)
        ogs.SetCutFillColor(color)
        ogs.SetCutFillPatternId(fill_id)
    return ogs


def visible_ids_in_view(doc, view):
    try:
        col = DB.FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
        return set(eid(x) for x in col.ToElementIds())
    except Exception:
        return None


def record_overrides(doc, view_map):
    path = os.path.join(model_dir(doc), 'overrides.json')
    old = read_json(path, {}) or {}
    for k, v in view_map.items():
        key = str(k)
        old[key] = sorted(set(old.get(key, [])) | set(v))
    write_json(path, old)


def stored_overrides(doc):
    return read_json(os.path.join(model_dir(doc), 'overrides.json'), {}) or {}


def clear_stored_overrides(doc):
    write_json(os.path.join(model_dir(doc), 'overrides.json'), {})


# =======================================================================
# kontrolny 3D pohlad
# =======================================================================

def _default_3d_type(doc):
    for vft in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
        if vft.ViewFamily == DB.ViewFamily.ThreeDimensional:
            return vft
    return None


def create_review_view(doc, name, element_ids, overrides_map):
    """3D pohlad s natrvalo izolovanymi zmenenymi prvkami.
    Z neho sa exportuje IFC/NWC ('Export only elements visible in view').
    Musi bezat vnutri transakcie."""
    existing = set()
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        try:
            existing.add(DB.Element.Name.__get__(v))
        except Exception:
            pass
    base = name
    i = 1
    while name in existing:
        i += 1
        name = '{0} ({1})'.format(base, i)

    vft = _default_3d_type(doc)
    if vft is None:
        return None
    view = DB.View3D.CreateIsometric(doc, vft.Id)
    view.Name = name
    try:
        view.DetailLevel = DB.ViewDetailLevel.Fine
        view.DisplayStyle = DB.DisplayStyle.ShadingWithEdges
    except Exception:
        pass

    ids = List[DB.ElementId]([DB.ElementId(x) for x in element_ids])
    if ids.Count:
        try:
            view.IsolateElementsTemporary(ids)
            view.ConvertTemporaryHideIsolateToPermanent()
        except Exception:
            pass

    for elid, ogs in overrides_map.items():
        try:
            view.SetElementOverrides(DB.ElementId(elid), ogs)
        except Exception:
            continue
    return view

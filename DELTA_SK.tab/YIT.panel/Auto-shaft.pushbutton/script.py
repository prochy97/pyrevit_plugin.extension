# -*- coding: utf-8 -*-
"""Auto-shaft
Osadí obdĺžnikové otvory do nosných stien v mieste kolízií
s nalinkovanými profesiami. Pracuje iba v aktívnom view.
"""
__title__ = "Auto-shaft"
__doc__ = (u"Nájde kolízie nosných stien s prvkami v nalinkovaných "
           u"modeloch profesií (iba aktívny view) a osadí do nich "
           u"obdĺžnikové otvory so zadaným odstupom.")

import math

from System.Collections.Generic import List
from pyrevit import revit, DB, forms, script

doc = revit.doc
view = doc.ActiveView
output = script.get_output()

BIC = DB.BuiltInCategory
BIP = DB.BuiltInParameter

# =====================================================================
#  NASTAVENIA – názvy parametrov rodiny otvoru a pevné pravidlá
# =====================================================================
PARAM_SIRKA = u"Sirka_otvoru"   # inštančný parameter (dĺžka)
PARAM_VYSKA = u"Vyska_otvoru"   # inštančný parameter (dĺžka)
PARAM_LINKID = u"ID_otvor"      # inštančný parameter (text)

ZAOKRUHLENIE_MM = 10.0          # rozmer otvoru sa zaokrúhli nahor
MIN_DN_MM = 20.0                # potrubia/chráničky pod DN20 sa ignorujú
TOLERANCIA_UHLA_DEG = 5.0       # väčší odklon od kolmice = šikmý prechod

PROFESIE = [
    (u"Potrubia (ZTI, ÚK, chladenie)",
     [BIC.OST_PipeCurves, BIC.OST_PipeFitting, BIC.OST_PipeInsulations]),
    (u"VZT",
     [BIC.OST_DuctCurves, BIC.OST_DuctFitting, BIC.OST_DuctInsulations]),
    (u"Elektro (žľaby, chráničky)",
     [BIC.OST_CableTray, BIC.OST_CableTrayFitting,
      BIC.OST_Conduit, BIC.OST_ConduitFitting]),
]

# kategórie, na ktoré sa uplatní pravidlo DN20
DN_KATEGORIE = set(int(c) for c in [
    BIC.OST_PipeCurves, BIC.OST_PipeFitting, BIC.OST_PipeInsulations,
    BIC.OST_Conduit, BIC.OST_ConduitFitting])

IZOLACIE = set(int(c) for c in [BIC.OST_PipeInsulations,
                                BIC.OST_DuctInsulations])


# =====================================================================
#  POMOCNÉ FUNKCIE
# =====================================================================
def mm2ft(v):
    return DB.UnitUtils.ConvertToInternalUnits(v, DB.UnitTypeId.Millimeters)


def ft2mm(v):
    return DB.UnitUtils.ConvertFromInternalUnits(v, DB.UnitTypeId.Millimeters)


def zaokruhli_nahor(dlzka_ft):
    mm = ft2mm(dlzka_ft)
    return mm2ft(math.ceil(mm / ZAOKRUHLENIE_MM - 1e-6) * ZAOKRUHLENIE_MM)


def bic_of(elem):
    cat = elem.Category
    if cat is None:
        return None
    try:
        return int(cat.BuiltInCategory)
    except Exception:
        return None


def ask_mm(prompt, default):
    while True:
        val = forms.ask_for_string(default=str(default), prompt=prompt,
                                   title=u"Auto-shaft")
        if val is None:
            script.exit()
        try:
            num = float(val.replace(",", "."))
            if num >= 0:
                return num
        except ValueError:
            pass
        forms.alert(u"Zadaj kladné číslo v mm (napr. 50).")


GEO_OPT = DB.Options()
GEO_OPT.DetailLevel = DB.ViewDetailLevel.Fine
GEO_OPT.ComputeReferences = False
GEO_OPT.IncludeNonVisibleObjects = False


def _zbieraj_solidy(geo, res):
    for g in geo:
        if isinstance(g, DB.Solid):
            if g.Volume > 1e-9:
                res.append(g)
        elif isinstance(g, DB.GeometryInstance):
            _zbieraj_solidy(g.GetInstanceGeometry(), res)


def solidy(elem, transform=None):
    res = []
    geo = elem.get_Geometry(GEO_OPT)
    if geo is None:
        return res
    _zbieraj_solidy(geo, res)
    if transform is not None and not transform.IsIdentity:
        res = [DB.SolidUtils.CreateTransformed(s, transform) for s in res]
    return res


def outline_v_linku(bb, inv):
    """Bounding box z hostiteľského modelu prepočítaný do súradníc linku."""
    pts = []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                pts.append(inv.OfPoint(DB.XYZ(x, y, z)))
    tol = mm2ft(10)
    mn = DB.XYZ(min(p.X for p in pts) - tol, min(p.Y for p in pts) - tol,
                min(p.Z for p in pts) - tol)
    mx = DB.XYZ(max(p.X for p in pts) + tol, max(p.Y for p in pts) + tol,
                max(p.Z for p in pts) + tol)
    return DB.Outline(mn, mx)


def hostitel_izolacie(elem, ldoc):
    host_id = getattr(elem, "HostElementId", None)
    if host_id is None or host_id == DB.ElementId.InvalidElementId:
        return None
    return ldoc.GetElement(host_id)


def nominalne_dn_mm(elem, ldoc):
    bic = bic_of(elem)
    if bic in IZOLACIE:
        host = hostitel_izolacie(elem, ldoc)
        return nominalne_dn_mm(host, ldoc) if host is not None else None
    if bic == int(BIC.OST_PipeCurves):
        p = elem.get_Parameter(BIP.RBS_PIPE_DIAMETER_PARAM)
        return ft2mm(p.AsDouble()) if p else None
    if bic == int(BIC.OST_Conduit):
        p = elem.get_Parameter(BIP.RBS_CONDUIT_DIAMETER_PARAM)
        return ft2mm(p.AsDouble()) if p else None
    # tvarovky – najväčší kruhový konektor
    try:
        conns = elem.MEPModel.ConnectorManager.Connectors
    except Exception:
        return None
    dn = None
    for c in conns:
        if c.Shape == DB.ConnectorProfileType.Round:
            d = ft2mm(c.Radius * 2.0)
            dn = d if dn is None else max(dn, d)
    return dn


def smer_prvku(elem, ldoc):
    """Smer osi pre rovné prvky (aj izolácia podľa hostiteľa), inak None."""
    if bic_of(elem) in IZOLACIE:
        elem = hostitel_izolacie(elem, ldoc)
        if elem is None:
            return None
    loc = elem.Location
    if isinstance(loc, DB.LocationCurve) and isinstance(loc.Curve, DB.Line):
        return loc.Curve.Direction
    return None


def rozsah_solidu(solid, p0, d):
    """Rozsah solidu v rovine steny: (u_min, u_max, z_min, z_max)."""
    umin = zmin = 1e12
    umax = zmax = -1e12
    for edge in solid.Edges:
        for pt in edge.Tessellate():
            u = (pt - p0).DotProduct(d)
            umin = min(umin, u)
            umax = max(umax, u)
            zmin = min(zmin, pt.Z)
            zmax = max(zmax, pt.Z)
    return umin, umax, zmin, zmax


def zluc_prekryvy(rects):
    """Zlúči obdĺžniky, ktoré sa prekrývajú (vrátane odstupu)."""
    rects = list(rects)
    zmena = True
    while zmena:
        zmena = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                if (a[0] <= b[1] and b[0] <= a[1] and
                        a[2] <= b[3] and b[2] <= a[3]):
                    rects[i] = [min(a[0], b[0]), max(a[1], b[1]),
                                min(a[2], b[2]), max(a[3], b[3]),
                                a[4] + b[4]]
                    del rects[j]
                    zmena = True
                    break
            if zmena:
                break
    return rects


def nazov_symbolu(sym):
    p = sym.get_Parameter(BIP.SYMBOL_NAME_PARAM)
    typ = p.AsString() if p else u"?"
    return u"{} : {}".format(sym.Family.Name, typ)


# =====================================================================
#  1) KONTROLA VIEW
# =====================================================================
if not isinstance(view, (DB.ViewPlan, DB.ViewSection, DB.View3D)):
    forms.alert(u"Aktívny view musí byť pôdorys, rez, pohľad alebo 3D.",
                exitscript=True)

# =====================================================================
#  2) VSTUPY OD POUŽÍVATEĽA
# =====================================================================
symboly = {}
for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol) \
        .OfCategory(BIC.OST_GenericModel):
    if s.Family.FamilyPlacementType == DB.FamilyPlacementType.OneLevelBasedHosted:
        symboly[nazov_symbolu(s)] = s

if not symboly:
    forms.alert(u"V projekte nie je načítaná žiadna hostovaná (wall-based) "
                u"rodina kategórie Generic Model.", exitscript=True)

volba = forms.SelectFromList.show(sorted(symboly.keys()),
                                  title=u"Auto-shaft – rodina otvoru",
                                  button_name=u"Vybrať",
                                  multiselect=False)
if not volba:
    script.exit()
symbol = symboly[volba]

nazvy_profesii = [p[0] for p in PROFESIE]
vybrane = forms.SelectFromList.show(
    [forms.TemplateListItem(n, checked=True) for n in nazvy_profesii],
    title=u"Auto-shaft – profesie",
    button_name=u"Pokračovať",
    multiselect=True)
if not vybrane:
    script.exit()

rezim = forms.CommandSwitchWindow.show(
    [u"Jednotný odstup", u"Odstup podľa profesie"],
    message=u"Odstup otvoru od prvku (na každú stranu):")
if not rezim:
    script.exit()

odstup_profesie = {}
if rezim == u"Jednotný odstup":
    hodnota = ask_mm(u"Odstup pre všetky profesie [mm]:", 50)
    for n in vybrane:
        odstup_profesie[n] = mm2ft(hodnota)
else:
    for n in vybrane:
        odstup_profesie[n] = mm2ft(ask_mm(u"Odstup – {} [mm]:".format(n), 50))

odstup_kat = {}
vsetky_kat = []
for nazov, kats in PROFESIE:
    if nazov in vybrane:
        for k in kats:
            odstup_kat[int(k)] = odstup_profesie[nazov]
            vsetky_kat.append(k)

cat_filter = DB.ElementMulticategoryFilter(List[DB.BuiltInCategory](vsetky_kat))

# =====================================================================
#  3) EXISTUJÚCE OTVORY (ochrana proti duplicitám)
# =====================================================================
existujuce = set()
for inst in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance) \
        .OfCategory(BIC.OST_GenericModel):
    if inst.Symbol.Family.Id != symbol.Family.Id:
        continue
    p = inst.LookupParameter(PARAM_LINKID)
    if p and p.AsString():
        existujuce.update(p.AsString().split(u";"))

# =====================================================================
#  4) NOSNÉ STENY V AKTÍVNOM VIEW
# =====================================================================
steny = []
steny_preskocene = []
for w in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Wall):
    if w.WallType.Kind != DB.WallKind.Basic:
        continue
    p = w.get_Parameter(BIP.WALL_STRUCTURAL_SIGNIFICANT)
    if p is None or p.AsInteger() != 1:
        continue
    loc = w.Location
    if not (isinstance(loc, DB.LocationCurve) and isinstance(loc.Curve, DB.Line)):
        steny_preskocene.append(w)
        continue
    steny.append(w)

if not steny:
    forms.alert(u"V aktívnom view nie sú žiadne nosné (Structural) rovné steny.",
                exitscript=True)

# =====================================================================
#  5) LINKY VIDITEĽNÉ V AKTÍVNOM VIEW
# =====================================================================
linky = []
for li in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.RevitLinkInstance):
    if li.IsHidden(view):
        continue
    if li.GetLinkDocument() is None:
        continue
    linky.append(li)

if not linky:
    forms.alert(u"V aktívnom view nie je zapnutý žiadny načítaný link.",
                exitscript=True)

# =====================================================================
#  6) HĽADANIE KOLÍZIÍ
# =====================================================================
solid_cache = {}
otvory_na_stene = {}     # wall_id -> [u0, u1, z0, z1, [kluce]]
sikme = []               # [link, id prvku, kategória, stena, uhol]
chyby_geometrie = []     # [link, id prvku, stena]
pocet_malych = 0
pocet_duplicit = 0
min_cos = math.cos(math.radians(TOLERANCIA_UHLA_DEG))

with forms.ProgressBar(title=u"Auto-shaft – hľadám kolízie ({value} / {max_value})",
                       cancellable=True) as pb:
    for idx, wall in enumerate(steny):
        if pb.cancelled:
            script.exit()
        pb.update_progress(idx + 1, len(steny))

        wall_bb = wall.get_BoundingBox(None)
        if wall_bb is None:
            continue
        wall_solidy = solidy(wall)
        if not wall_solidy:
            continue
        line = wall.Location.Curve
        p0 = line.GetEndPoint(0)
        d = DB.XYZ(line.Direction.X, line.Direction.Y, 0).Normalize()
        n = wall.Orientation

        for li in linky:
            ldoc = li.GetLinkDocument()
            T = li.GetTotalTransform()
            outline = outline_v_linku(wall_bb, T.Inverse)
            prvky = DB.FilteredElementCollector(doc, view.Id, li.Id) \
                .WherePasses(cat_filter) \
                .WherePasses(DB.BoundingBoxIntersectsFilter(outline))

            for e in prvky:
                bic = bic_of(e)
                if bic is None or bic not in odstup_kat:
                    continue

                # DN20
                if bic in DN_KATEGORIE:
                    dn = nominalne_dn_mm(e, ldoc)
                    if dn is not None and dn < MIN_DN_MM - 0.01:
                        pocet_malych += 1
                        continue

                # šikmý prechod / prvok vedený v stene
                smer = smer_prvku(e, ldoc)
                if smer is not None:
                    hs = T.OfVector(smer).Normalize()
                    cos_uhla = abs(hs.DotProduct(n))
                    if cos_uhla < min_cos:
                        uhol = math.degrees(math.acos(min(1.0, cos_uhla)))
                        sikme.append([li.Name, e.Id.Value, e.Category.Name,
                                      output.linkify(wall.Id),
                                      u"{:.1f}°".format(uhol)])
                        continue

                # presný prienik geometrie
                kluc_cache = (li.Id.Value, e.Id.Value)
                if kluc_cache not in solid_cache:
                    try:
                        solid_cache[kluc_cache] = solidy(e, T)
                    except Exception:
                        solid_cache[kluc_cache] = []
                rozsah = None
                zlyhalo = False
                for es in solid_cache[kluc_cache]:
                    for ws in wall_solidy:
                        try:
                            prienik = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                                es, ws, DB.BooleanOperationsType.Intersect)
                        except Exception:
                            zlyhalo = True
                            continue
                        if prienik is None or prienik.Volume < 1e-9:
                            continue
                        r = rozsah_solidu(prienik, p0, d)
                        if rozsah is None:
                            rozsah = list(r)
                        else:
                            rozsah = [min(rozsah[0], r[0]), max(rozsah[1], r[1]),
                                      min(rozsah[2], r[2]), max(rozsah[3], r[3])]
                if rozsah is None:
                    if zlyhalo:
                        chyby_geometrie.append([li.Name, e.Id.Value,
                                                output.linkify(wall.Id)])
                    continue

                kluc = u"{}@{}".format(e.UniqueId, wall.Id.Value)
                if kluc in existujuce:
                    pocet_duplicit += 1
                    continue

                off = odstup_kat[bic]
                otvory_na_stene.setdefault(wall.Id.Value, []).append(
                    [rozsah[0] - off, rozsah[1] + off,
                     rozsah[2] - off, rozsah[3] + off, [kluc]])

# =====================================================================
#  7) OSADENIE OTVOROV
# =====================================================================
osadene = []
if otvory_na_stene:
    t = DB.Transaction(doc, u"Auto-shaft")
    t.Start()
    try:
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()

        na_posun = []   # (instancia, cielovy bod, normala steny)
        kontrola_parametrov = True

        for wall_id_val, rects in otvory_na_stene.items():
            wall = doc.GetElement(DB.ElementId(wall_id_val))
            level = doc.GetElement(wall.LevelId)
            line = wall.Location.Curve
            p0 = line.GetEndPoint(0)
            d = DB.XYZ(line.Direction.X, line.Direction.Y, 0).Normalize()

            for r in zluc_prekryvy(rects):
                sirka = zaokruhli_nahor(r[1] - r[0])
                vyska = zaokruhli_nahor(r[3] - r[2])
                u_stred = (r[0] + r[1]) / 2.0
                z_stred = (r[2] + r[3]) / 2.0
                bod = p0 + d.Multiply(u_stred)
                ciel = DB.XYZ(bod.X, bod.Y, z_stred)

                inst = doc.Create.NewFamilyInstance(
                    ciel, symbol, wall, level,
                    DB.Structure.StructuralType.NonStructural)

                ps = inst.LookupParameter(PARAM_SIRKA)
                pv = inst.LookupParameter(PARAM_VYSKA)
                pl = inst.LookupParameter(PARAM_LINKID)
                if kontrola_parametrov:
                    chybajuce = [nazov for nazov, par in
                                 ((PARAM_SIRKA, ps), (PARAM_VYSKA, pv),
                                  (PARAM_LINKID, pl))
                                 if par is None or par.IsReadOnly]
                    if chybajuce:
                        t.RollBack()
                        forms.alert(
                            u"Rodina '{}' nemá zapisovateľné inštančné "
                            u"parametre: {}.\nNič nebolo osadené.".format(
                                symbol.Family.Name, u", ".join(chybajuce)),
                            exitscript=True)
                    kontrola_parametrov = False

                ps.Set(sirka)
                pv.Set(vyska)
                pl.Set(u";".join(r[4]))
                na_posun.append((inst, ciel, wall.Orientation))
                osadene.append([output.linkify(inst.Id), output.linkify(wall.Id),
                                int(round(ft2mm(sirka))), int(round(ft2mm(vyska))),
                                len(r[4])])

        # vloženie bodu do stredu otvoru (Revit pri hostovaní posúva bod)
        doc.Regenerate()
        tol = mm2ft(0.5)
        for inst, ciel, nrm in na_posun:
            skut = inst.Location.Point
            delta = ciel - skut
            delta = delta - nrm.Multiply(delta.DotProduct(nrm))
            if delta.GetLength() > tol:
                DB.ElementTransformUtils.MoveElement(doc, inst.Id, delta)

        t.Commit()
    except SystemExit:
        raise
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        forms.alert(u"Chyba pri osádzaní, nič nebolo zmenené:\n{}".format(ex),
                    exitscript=True)

# =====================================================================
#  8) REPORT
# =====================================================================
output.print_md(u"## Auto-shaft – výsledok")
output.print_md(
    u"View: **{}** | Rodina: **{}** | Nosné steny: **{}** | Linky: **{}**".format(
        view.Name, volba, len(steny), u", ".join(l.Name for l in linky)))
output.print_md(u"- Osadené otvory: **{}**".format(len(osadene)))
output.print_md(u"- Preskočené – otvor už existuje: **{}**".format(pocet_duplicit))
output.print_md(u"- Preskočené – menšie ako DN{}: **{}**".format(
    int(MIN_DN_MM), pocet_malych))
output.print_md(u"- Šikmé prechody / prvky vedené v stene: **{}**".format(len(sikme)))
output.print_md(u"- Zlyhaný výpočet geometrie: **{}**".format(len(chyby_geometrie)))

if osadene:
    output.print_md(u"### Osadené otvory")
    output.print_table(osadene, columns=[u"Otvor", u"Stena", u"Šírka [mm]",
                                         u"Výška [mm]", u"Počet prvkov"])
if sikme:
    output.print_md(u"### Šikmé prechody – riešiť ručne")
    output.print_table(sikme, columns=[u"Link", u"ID prvku", u"Kategória",
                                       u"Stena", u"Odklon od kolmice"])
if chyby_geometrie:
    output.print_md(u"### Zlyhaný výpočet geometrie – skontrolovať ručne")
    output.print_table(chyby_geometrie, columns=[u"Link", u"ID prvku", u"Stena"])
if steny_preskocene:
    output.print_md(u"### Oblúkové nosné steny – preskočené")
    output.print_md(u", ".join(output.linkify(w.Id) for w in steny_preskocene))

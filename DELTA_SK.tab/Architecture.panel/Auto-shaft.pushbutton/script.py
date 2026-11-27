# -*- coding: utf-8 -*-
"""Auto-shaft
Osadí obdĺžnikové otvory do vybraných typov stien v miestach kolízií
s nalinkovanými profesiami, spojí blízke otvory a skontroluje existujúce
(posunuté, zmenené, bez kolízie). Pracuje iba v aktívnom view.
"""
__title__ = "Auto-shaft"
__doc__ = (u"Osadí obdĺžnikové otvory do vybraných typov stien v miestach "
           u"kolízií s linkami profesií, spojí blízke otvory a skontroluje "
           u"existujúce otvory (iba aktívny view).")

import math
import os

import clr
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from System.Collections.Generic import List
from pyrevit import revit, DB, forms, script
from System.Windows import Thickness, FontWeights
from System.Windows.Controls import CheckBox, TreeViewItem

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
TOLERANCIA_UHLA_DEG = 5.0       # väčší odklon od kolmice = šikmý prechod (osadí sa, vypíše sa)
MAX_UHOL_DEG = 75.0             # väčší odklon = prvok vedený v stene (neosadí sa)
TOLERANCIA_KONTROLY_MM = 5.0    # menší rozdiel polohy/rozmeru = otvor sedí
MIN_DN_MM = 20.0                # prepíše sa hodnotou z okna

# predvolené hodnoty v okne (pri prvom spustení)
PREDVOLENY_FILTER = u"RCO"
PREDVOLENA_RODINA = u"DGSK_otvor_stena"
PREDVOLENY_ODSTUP = u"50"
PREDVOLENE_MIN_DN = u"20"
PREDVOLENA_MEDZERA = u"100"
PREDVOLENY_LIMIT_STATIKA = u"500"

# kľúč (= začiatok názvu poľa odsadenia v ui.xaml), názov, popis, kategórie
SKUPINY = [
    ("pipes", u"Pipes", u"potrubia vrátane kolien, odbočiek a izolácie",
     [BIC.OST_PipeCurves, BIC.OST_PipeFitting, BIC.OST_PipeInsulations]),
    ("ducts", u"Ducts", u"VZT potrubia vrátane kolien, odbočiek a izolácie",
     [BIC.OST_DuctCurves, BIC.OST_DuctFitting, BIC.OST_DuctInsulations]),
    ("trays", u"Cable Trays", u"káblové žľaby vrátane kolien a odbočiek",
     [BIC.OST_CableTray, BIC.OST_CableTrayFitting]),
    ("conduits", u"Conduits", u"chráničky vrátane kolien",
     [BIC.OST_Conduit, BIC.OST_ConduitFitting]),
]

# kategórie, na ktoré sa uplatní limit DN
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


def parse_mm(text):
    """Vráti nezáporné číslo v mm, alebo None pri neplatnom vstupe."""
    try:
        num = float((text or u"").strip().replace(",", "."))
    except ValueError:
        return None
    return num if num >= 0 else None


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


def nazov_symbolu(sym):
    p = sym.get_Parameter(BIP.SYMBOL_NAME_PARAM)
    typ = p.AsString() if p else u"?"
    return u"{} : {}".format(sym.Family.Name, typ)


def ram_steny(wall):
    """Lokálny rám steny: počiatok, smer pozdĺž steny, normála."""
    line = wall.Location.Curve
    p0 = line.GetEndPoint(0)
    d = DB.XYZ(line.Direction.X, line.Direction.Y, 0).Normalize()
    return p0, d, wall.Orientation


def je_rovna_stena(wall):
    loc = wall.Location if wall is not None else None
    return isinstance(loc, DB.LocationCurve) and isinstance(loc.Curve, DB.Line)


SOLID_CACHE = {}


def solidy_prvku(li, e):
    kluc = (li.Id.Value, e.Id.Value)
    if kluc not in SOLID_CACHE:
        try:
            SOLID_CACHE[kluc] = solidy(e, li.GetTotalTransform())
        except Exception:
            SOLID_CACHE[kluc] = []
    return SOLID_CACHE[kluc]


def vyhodnot_prvok(e, li, wall_solidy, p0, d, n, odstup):
    """Vyhodnotí jeden prvok z linku voči jednej stene.
    Vráti (stav, data):
      ("otvor", [u0, u1, z0, z1, uhol])  potrebuje otvor (vrátane odstupu)
      ("maly", None)                      menší ako DN20
      ("v_stene", uhol)                   prvok vedený pozdĺž v stene
      ("bez", zlyhalo)                    stenou neprechádza
    """
    ldoc = li.GetLinkDocument()
    if bic_of(e) in DN_KATEGORIE:
        dn = nominalne_dn_mm(e, ldoc)
        if dn is not None and dn < MIN_DN_MM - 0.01:
            return "maly", None

    rozsah = None
    zlyhalo = False
    for es in solidy_prvku(li, e):
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
        return "bez", zlyhalo

    uhol = 0.0
    smer = smer_prvku(e, ldoc)
    if smer is not None:
        hs = li.GetTotalTransform().OfVector(smer).Normalize()
        cos_uhla = min(1.0, abs(hs.DotProduct(n)))
        uhol = math.degrees(math.acos(cos_uhla))
        if cos_uhla < math.cos(math.radians(MAX_UHOL_DEG)):
            return "v_stene", uhol

    return "otvor", [rozsah[0] - odstup, rozsah[1] + odstup,
                     rozsah[2] - odstup, rozsah[3] + odstup, uhol]


def ciel_otvoru(r):
    """(šírka, výška, stred pozdĺž steny, spodná hrana) z obdĺžnika."""
    sirka = zaokruhli_nahor(r[1] - r[0])
    vyska = zaokruhli_nahor(r[3] - r[2])
    u_stred = (r[0] + r[1]) / 2.0
    z_spodok = (r[2] + r[3]) / 2.0 - vyska / 2.0
    return sirka, vyska, u_stred, z_spodok


def kluce_otvoru(inst):
    p = inst.LookupParameter(PARAM_LINKID)
    if p is None or not p.AsString():
        return []
    return [k for k in p.AsString().split(u";") if k]


def skutocny_otvor(inst, p0, d):
    """(šírka, výška, stred pozdĺž steny, spodná hrana) existujúceho otvoru."""
    ps = inst.LookupParameter(PARAM_SIRKA)
    pv = inst.LookupParameter(PARAM_VYSKA)
    pe = inst.get_Parameter(BIP.INSTANCE_ELEVATION_PARAM)
    lvl = doc.GetElement(inst.LevelId)
    if ps is None or pv is None or pe is None or lvl is None:
        return None
    u = (inst.Location.Point - p0).DotProduct(d)
    return ps.AsDouble(), pv.AsDouble(), u, lvl.ProjectElevation + pe.AsDouble()


class ChybaRodiny(Exception):
    pass


def nastav_otvor(inst, sirka, vyska, z_spodok, level, kluce):
    ps = inst.LookupParameter(PARAM_SIRKA)
    pv = inst.LookupParameter(PARAM_VYSKA)
    pl = inst.LookupParameter(PARAM_LINKID)
    pe = inst.get_Parameter(BIP.INSTANCE_ELEVATION_PARAM)
    chybajuce = [nazov for nazov, par in
                 ((PARAM_SIRKA, ps), (PARAM_VYSKA, pv), (PARAM_LINKID, pl),
                  (u"Elevation from Level", pe))
                 if par is None or par.IsReadOnly]
    if chybajuce:
        raise ChybaRodiny(u"Rodina '{}' nemá zapisovateľné inštančné "
                          u"parametre: {}.".format(symbol.Family.Name,
                                                   u", ".join(chybajuce)))
    ps.Set(sirka)
    pv.Set(vyska)
    pl.Set(u";".join(kluce))
    pe.Set(z_spodok - level.ProjectElevation)


def mm_txt(v_ft):
    return int(round(ft2mm(v_ft)))


def uhol_txt(uhol):
    return u"{:.1f}°".format(uhol) if uhol > TOLERANCIA_UHLA_DEG else u"–"


def nazov_linku(li):
    """Názov súboru linku (typ), napr. VIEZPSP_A0_ZT.rvt."""
    typ = doc.GetElement(li.GetTypeId())
    return DB.Element.Name.GetValue(typ) if typ is not None else li.Name


def rozober_kluc(kluc):
    """'link|uid@stena' (nový) alebo 'uid@stena' (starý) -> (link, uid, stena)."""
    link = None
    if u"|" in kluc:
        link, kluc = kluc.split(u"|", 1)
    if u"@" not in kluc:
        return None
    uid, stena = kluc.rsplit(u"@", 1)
    return link, uid, stena


def plny_kluc(link, uid, wid):
    return u"{}|{}@{}".format(link, uid, wid)


def identita(uid, wid):
    return u"{}@{}".format(uid, wid)


def su_blizko(a, b, medzera):
    """Obdĺžniky [u0, u1, z0, z1] sa prekrývajú alebo je medzi nimi
    menej steny ako 'medzera'."""
    gap_u = max(b[0] - a[1], a[0] - b[1])
    gap_z = max(b[2] - a[3], a[2] - b[3])
    if gap_u <= 0 and gap_z <= 0:
        return True
    return gap_u < medzera and gap_z < medzera


def unikatne(zoznam):
    """Odstráni duplicity a zachová poradie."""
    videne = set()
    vysl = []
    for x in zoznam:
        if x not in videne:
            videne.add(x)
            vysl.append(x)
    return vysl


def spoj_polozky(polozky, medzera):
    """Spojí blízke položky jednej steny. Položka:
    {"r": [u0,u1,z0,z1], "kluce": [...], "uhol": x, "vlastnici": set()}
    K medzere sa pripočíta rezerva na zaokrúhlenie rozmerov, aby po
    zaokrúhlení nahor neostala medzi otvormi menšia medzera, než je nastavená."""
    medzera = medzera + mm2ft(ZAOKRUHLENIE_MM)
    polozky = [dict(p, r=list(p["r"]), kluce=list(p["kluce"]),
                    vlastnici=set(p["vlastnici"])) for p in polozky]
    zmena = True
    while zmena:
        zmena = False
        for i in range(len(polozky)):
            for j in range(i + 1, len(polozky)):
                a, b = polozky[i], polozky[j]
                if su_blizko(a["r"], b["r"], medzera):
                    a["r"] = [min(a["r"][0], b["r"][0]), max(a["r"][1], b["r"][1]),
                              min(a["r"][2], b["r"][2]), max(a["r"][3], b["r"][3])]
                    a["kluce"] = unikatne(a["kluce"] + b["kluce"])
                    a["uhol"] = max(a["uhol"], b["uhol"])
                    a["vlastnici"] = a["vlastnici"] | b["vlastnici"]
                    del polozky[j]
                    zmena = True
                    break
            if zmena:
                break
    return polozky


def obsadeny(eid):
    """Prvok je v zdieľanom modeli obsadený iným používateľom."""
    if not doc.IsWorkshared:
        return False
    try:
        return DB.WorksharingUtils.GetCheckoutStatus(doc, eid) == \
            DB.CheckoutStatus.OwnedByOtherUser
    except Exception:
        return False


class PotlacVarovania(DB.IFailuresPreprocessor):
    """Varovania Revitu počas zápisu nepreruší dialógom, len ich zapíše do reportu."""
    def __init__(self):
        self.spravy = []

    def PreprocessFailures(self, accessor):
        for f in accessor.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                self.spravy.append(f.GetDescriptionText())
                accessor.DeleteWarning(f)
        return DB.FailureProcessingResult.Continue


RUCNY_ZNACKA = u"RUCNY:"


def rucny_token(r):
    """Značka ručného otvoru s jeho minimálnym obdĺžnikom (mm)."""
    return RUCNY_ZNACKA + u",".join(u"{:.1f}".format(ft2mm(x)) for x in r)


def rucny_rect(kluce):
    """Minimálny obdĺžnik ručného otvoru zo značky v ID_otvor, inak None."""
    for k in kluce:
        if k.startswith(RUCNY_ZNACKA):
            try:
                hodnoty = [mm2ft(float(x)) for x in k[len(RUCNY_ZNACKA):].split(u",")]
            except ValueError:
                return None
            if len(hodnoty) == 4:
                return hodnoty
    return None


def rect_z_akt(akt):
    """[u0,u1,z0,z1] zo skutočného otvoru (šírka, výška, stred u, spodok z)."""
    return [akt[2] - akt[0] / 2.0, akt[2] + akt[0] / 2.0, akt[3], akt[3] + akt[1]]


# =====================================================================
#  1) KONTROLA VIEW A ZBER ÚDAJOV
# =====================================================================
if not isinstance(view, (DB.ViewPlan, DB.ViewSection, DB.View3D)):
    forms.alert(u"Aktívny view musí byť pôdorys, rez, pohľad alebo 3D.",
                exitscript=True)

symboly = {}
for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol) \
        .OfCategory(BIC.OST_GenericModel):
    if s.Family.FamilyPlacementType == DB.FamilyPlacementType.OneLevelBasedHosted:
        symboly[nazov_symbolu(s)] = s
if not symboly:
    forms.alert(u"V projekte nie je načítaná žiadna hostovaná (wall-based) "
                u"rodina kategórie Generic Model.", exitscript=True)

# typy stien v aktívnom view: type_id -> {"name", "walls"}
typy_stien = {}
for w in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Wall):
    if w.WallType.Kind != DB.WallKind.Basic:
        continue
    tid = w.GetTypeId().Value
    if tid not in typy_stien:
        typy_stien[tid] = {"name": DB.Element.Name.GetValue(w.WallType),
                           "walls": []}
    typy_stien[tid]["walls"].append(w)
if not typy_stien:
    forms.alert(u"V aktívnom view nie sú žiadne steny.", exitscript=True)
steny_vo_view = {}
for info in typy_stien.values():
    for w in info["walls"]:
        steny_vo_view[w.Id.Value] = w

linky_vo_view = []
for li in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.RevitLinkInstance):
    if li.IsHidden(view) or li.GetLinkDocument() is None:
        continue
    linky_vo_view.append(li)
if not linky_vo_view:
    forms.alert(u"V aktívnom view nie je zapnutý žiadny načítaný link.",
                exitscript=True)

# počty prvkov podľa kategórie a linku v aktívnom view
pocty = {}
for li in linky_vo_view:
    for gkey, _, _, kats in SKUPINY:
        try:
            pocet = DB.FilteredElementCollector(doc, view.Id, li.Id) \
                .WherePasses(DB.ElementMulticategoryFilter(
                    List[DB.BuiltInCategory](kats))) \
                .GetElementCount()
        except Exception:
            pocet = 0
        if pocet:
            pocty[(gkey, li.Id.Value)] = pocet

cfg = script.get_config()


def cfg_get(name, default):
    try:
        val = cfg.get_option(name, default)
        return default if val is None else val
    except Exception:
        return default


# =====================================================================
#  2) OKNO S NASTAVENIAMI
# =====================================================================
class AutoShaftOkno(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)
        self.result = None

        # 1. rodina
        self.nazvy_rodin = sorted(symboly.keys())
        for n in self.nazvy_rodin:
            self.family_cb.Items.Add(n)
        ulozena = cfg_get("rodina", u"")
        idx = 0
        if ulozena in self.nazvy_rodin:
            idx = self.nazvy_rodin.index(ulozena)
        else:
            for i, n in enumerate(self.nazvy_rodin):
                if PREDVOLENA_RODINA.lower() in n.lower():
                    idx = i
                    break
        self.family_cb.SelectedIndex = idx

        # 2. konštrukcie
        self.filter_tb.Text = cfg_get("filter", PREDVOLENY_FILTER)
        self.wall_cbs = []
        for tid, info in sorted(typy_stien.items(),
                                key=lambda kv: kv[1]["name"].lower()):
            cb = CheckBox()
            cb.Content = info["name"]
            cb.Tag = tid
            cb.Margin = Thickness(2)
            self.walls_sp.Children.Add(cb)
            self.wall_cbs.append((cb, info["name"]))
        self.oznac_podla_filtra()

        # 3. strom kategórie -> linky
        vypnute = set(cfg_get("vypnute_linky", u"").split(u";"))
        self.strom = []   # (gkey, rodič, [(dieťa, link_id, názov linku)])
        for gkey, nazov, popis, _ in SKUPINY:
            deti = [li for li in linky_vo_view if (gkey, li.Id.Value) in pocty]
            uzol = TreeViewItem()
            rodic = CheckBox()
            rodic.FontWeight = FontWeights.SemiBold
            if deti:
                rodic.Content = u"{}  –  {}".format(nazov, popis)
                rodic.IsChecked = cfg_get("skupina_" + gkey, u"1") == u"1"
            else:
                rodic.Content = u"{}  –  v aktívnom view nie sú".format(nazov)
                rodic.IsChecked = False
                rodic.IsEnabled = False
            uzol.Header = rodic
            deti_cb = []
            for li in deti:
                lname = nazov_linku(li)
                cb = CheckBox()
                cb.Content = lname
                cb.IsChecked = bool(rodic.IsChecked) and \
                    (gkey + u"|" + lname) not in vypnute
                polozka = TreeViewItem()
                polozka.Header = cb
                uzol.Items.Add(polozka)
                deti_cb.append((cb, li.Id.Value, lname))
                cb.Click += self._klik_dieta(rodic, deti_cb)
            rodic.Click += self._klik_rodic(rodic, deti_cb)
            self.tree.Items.Add(uzol)
            self.strom.append((gkey, rodic, deti_cb))

        # 4. odsadenie
        self.uniform_tb.Text = cfg_get("odstup", PREDVOLENY_ODSTUP)
        for gkey, _, _, _ in SKUPINY:
            getattr(self, gkey + "_tb").Text = \
                cfg_get("odstup_" + gkey, PREDVOLENY_ODSTUP)
        self.mindn_tb.Text = cfg_get("min_dn", PREDVOLENE_MIN_DN)
        if cfg_get("rezim", u"jednotny") == u"jednotny":
            self.uniform_rb.IsChecked = True
        else:
            self.per_rb.IsChecked = True
        self.prepni_rezim()

        # 5. spájanie a veľké otvory
        self.gap_tb.Text = cfg_get("medzera", PREDVOLENA_MEDZERA)
        self.limit_tb.Text = cfg_get("limit_statika", PREDVOLENY_LIMIT_STATIKA)

        # 6. typ akcie
        self.new_cb.IsChecked = cfg_get("akcia_nove", u"1") == u"1"
        self.check_cb.IsChecked = cfg_get("akcia_kontrola", u"1") == u"1"
        self.update_cb.IsChecked = cfg_get("akcia_upravit", u"1") == u"1"
        self.delete_cb.IsChecked = cfg_get("akcia_zmazat", u"1") == u"1"
        self.prepni_kontrolu()

        # udalosti
        self.uniform_rb.Checked += lambda s, e: self.prepni_rezim()
        self.per_rb.Checked += lambda s, e: self.prepni_rezim()
        self.check_cb.Checked += lambda s, e: self.prepni_kontrolu()
        self.check_cb.Unchecked += lambda s, e: self.prepni_kontrolu()
        self.filter_b.Click += lambda s, e: self.oznac_podla_filtra()
        self.all_b.Click += lambda s, e: self.oznac_vsetky(True)
        self.none_b.Click += lambda s, e: self.oznac_vsetky(False)
        self.start_b.Click += self.start
        self.cancel_b.Click += lambda s, e: self.Close()

    @staticmethod
    def _klik_rodic(rodic, deti_cb):
        def handler(sender, args):
            stav = bool(rodic.IsChecked)
            for cb, _, _ in deti_cb:
                cb.IsChecked = stav
        return handler

    @staticmethod
    def _klik_dieta(rodic, deti_cb):
        def handler(sender, args):
            rodic.IsChecked = any(bool(cb.IsChecked) for cb, _, _ in deti_cb)
        return handler

    def oznac_podla_filtra(self):
        vyrazy = [v.strip().lower()
                  for v in (self.filter_tb.Text or u"").replace(",", ";").split(";")
                  if v.strip()]
        for cb, nazov in self.wall_cbs:
            cb.IsChecked = any(v in nazov.lower() for v in vyrazy)

    def oznac_vsetky(self, stav):
        for cb, _ in self.wall_cbs:
            cb.IsChecked = stav

    def prepni_rezim(self):
        jednotny = bool(self.uniform_rb.IsChecked)
        self.uniform_tb.IsEnabled = jednotny
        for gkey, _, _, _ in SKUPINY:
            getattr(self, gkey + "_tb").IsEnabled = not jednotny

    def prepni_kontrolu(self):
        zapnuta = bool(self.check_cb.IsChecked)
        self.update_cb.IsEnabled = zapnuta
        self.delete_cb.IsEnabled = zapnuta

    def start(self, sender, args):
        nove = bool(self.new_cb.IsChecked)
        kontrola = bool(self.check_cb.IsChecked)
        if not (nove or kontrola):
            forms.alert(u"Zvoľ aspoň jednu akciu v časti 6.")
            return
        if self.family_cb.SelectedIndex < 0:
            forms.alert(u"Vyber rodinu otvoru.")
            return
        steny_ids = set(cb.Tag for cb, _ in self.wall_cbs if cb.IsChecked)
        pary = set()
        for gkey, _, deti_cb in self.strom:
            for cb, lid, _ in deti_cb:
                if cb.IsChecked:
                    pary.add((gkey, lid))
        if nove and not steny_ids:
            forms.alert(u"Pre osadenie nových otvorov označ aspoň jeden typ konštrukcie.")
            return
        if nove and not pary:
            forms.alert(u"Pre osadenie nových otvorov označ aspoň jeden link v časti 3.")
            return

        jednotny = bool(self.uniform_rb.IsChecked)
        odstupy = {}
        if jednotny:
            v = parse_mm(self.uniform_tb.Text)
            if v is None:
                forms.alert(u"Jednotné odsadenie musí byť kladné číslo v mm.")
                return
            for gkey, _, _, _ in SKUPINY:
                odstupy[gkey] = v
        else:
            for gkey, nazov, _, _ in SKUPINY:
                v = parse_mm(getattr(self, gkey + "_tb").Text)
                if v is None:
                    forms.alert(u"Odsadenie pre {} musí byť kladné číslo v mm."
                                .format(nazov))
                    return
                odstupy[gkey] = v
        min_dn = parse_mm(self.mindn_tb.Text)
        medzera = parse_mm(self.gap_tb.Text)
        limit = parse_mm(self.limit_tb.Text)
        for hodnota, popis in ((min_dn, u"Limit DN"), (medzera, u"Medzera medzi otvormi"),
                               (limit, u"Limit pre statika")):
            if hodnota is None:
                forms.alert(u"{} musí byť kladné číslo.".format(popis))
                return

        # uloženie nastavení na ďalšie spustenie
        try:
            cfg.set_option("rodina", self.family_cb.SelectedItem)
            cfg.set_option("filter", self.filter_tb.Text or u"")
            cfg.set_option("rezim", u"jednotny" if jednotny else u"kategorie")
            cfg.set_option("odstup", self.uniform_tb.Text or u"")
            for gkey, _, _, _ in SKUPINY:
                cfg.set_option("odstup_" + gkey, getattr(self, gkey + "_tb").Text or u"")
            vypnute = []
            for gkey, rodic, deti_cb in self.strom:
                if rodic.IsEnabled:
                    cfg.set_option("skupina_" + gkey,
                                   u"1" if rodic.IsChecked else u"0")
                for cb, _, lname in deti_cb:
                    if not cb.IsChecked:
                        vypnute.append(gkey + u"|" + lname)
            cfg.set_option("vypnute_linky", u";".join(vypnute))
            cfg.set_option("min_dn", self.mindn_tb.Text or u"")
            cfg.set_option("medzera", self.gap_tb.Text or u"")
            cfg.set_option("limit_statika", self.limit_tb.Text or u"")
            for nazov, cb in (("akcia_nove", self.new_cb),
                              ("akcia_kontrola", self.check_cb),
                              ("akcia_upravit", self.update_cb),
                              ("akcia_zmazat", self.delete_cb)):
                cfg.set_option(nazov, u"1" if cb.IsChecked else u"0")
            script.save_config()
        except Exception:
            pass

        self.result = {
            "rodina": self.family_cb.SelectedItem,
            "steny": steny_ids,
            "pary": pary,
            "odstupy": odstupy,
            "min_dn": min_dn,
            "medzera": medzera,
            "limit": limit,
            "nove": nove,
            "kontrola": kontrola,
            "upravit": kontrola and bool(self.update_cb.IsChecked),
            "zmazat": kontrola and bool(self.delete_cb.IsChecked),
        }
        self.Close()


okno = AutoShaftOkno(os.path.join(os.path.dirname(__file__), "ui.xaml"))
okno.ShowDialog()
vysledok = okno.result
if not vysledok:
    script.exit()

volba = vysledok["rodina"]
symbol = symboly[volba]
rob_nove = vysledok["nove"]
rob_kontrolu = vysledok["kontrola"]
MIN_DN_MM = vysledok["min_dn"]
medzera_ft = mm2ft(vysledok["medzera"])
limit_ft = mm2ft(vysledok["limit"])
tol_kontroly = mm2ft(TOLERANCIA_KONTROLY_MM)

odstup_kat = {}
kategorie_skupiny = {}
for gkey, _, _, kats in SKUPINY:
    kategorie_skupiny[gkey] = kats
    for k in kats:
        odstup_kat[int(k)] = mm2ft(vysledok["odstupy"][gkey])


def je_velky(ciel):
    return limit_ft > 0 and (ciel[0] > limit_ft + 1e-6 or ciel[1] > limit_ft + 1e-6)


# =====================================================================
#  3) EXISTUJÚCE OTVORY, STENY, LINKY
# =====================================================================
vsetky_otvory = []
vlastnik_identity = {}      # "uid@stena" -> id otvoru
for inst in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance) \
        .OfCategory(BIC.OST_GenericModel):
    if inst.Symbol.Family.Id != symbol.Family.Id:
        continue
    vsetky_otvory.append(inst)
    for k in kluce_otvoru(inst):
        rozobrany = rozober_kluc(k)
        if rozobrany:
            vlastnik_identity[identita(rozobrany[1], rozobrany[2])] = inst.Id.Value

otvory_na_kontrolu = []
if rob_kontrolu:
    for inst in vsetky_otvory:
        host = inst.Host
        if host is not None and host.Id.Value in steny_vo_view \
                and je_rovna_stena(host):
            otvory_na_kontrolu.append(inst)
kontrolovane_ids = set(inst.Id.Value for inst in otvory_na_kontrolu)

steny = []
steny_preskocene = []
nazvy_typov = []
if rob_nove:
    for tid in vysledok["steny"]:
        nazvy_typov.append(typy_stien[tid]["name"])
        for w in typy_stien[tid]["walls"]:
            if je_rovna_stena(w):
                steny.append(w)
            else:
                steny_preskocene.append(w)
    nazvy_typov.sort()

linky = [li for li in linky_vo_view
         if any((gkey, li.Id.Value) in vysledok["pary"] for gkey, _, _, _ in SKUPINY)]

# vyhľadávanie prvkov v linkoch
linky_podla_nazvu = {}
nenacitane_nazvy = set()
for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
    nm = nazov_linku(li)
    if li.GetLinkDocument() is None:
        nenacitane_nazvy.add(nm)
    else:
        linky_podla_nazvu.setdefault(nm, []).append(li)
nenacitane_nazvy -= set(linky_podla_nazvu.keys())
PRVOK_CACHE = {}


def najdi_prvok(link, uid):
    """-> ("ok", li, e) | ("zmazany", None, None) | ("neovereny", None, None)"""
    kluc = (link, uid)
    if kluc in PRVOK_CACHE:
        return PRVOK_CACHE[kluc]
    vysl = None
    if link is not None:
        lis = linky_podla_nazvu.get(link)
        if not lis:
            vysl = ("neovereny", None, None)
        else:
            e = lis[0].GetLinkDocument().GetElement(uid)
            vysl = ("ok", lis[0], e) if e is not None else ("zmazany", None, None)
    else:
        # starý zápis bez názvu linku
        for lis in linky_podla_nazvu.values():
            e = lis[0].GetLinkDocument().GetElement(uid)
            if e is not None:
                vysl = ("ok", lis[0], e)
                break
        if vysl is None:
            vysl = ("neovereny", None, None) if nenacitane_nazvy \
                else ("zmazany", None, None)
    PRVOK_CACHE[kluc] = vysl
    return vysl


# =====================================================================
#  4) GEOMETRIA STIEN BEZ NAŠICH OTVOROV
#  (otvory sa dočasne zmažú a transakcia sa vráti, nič sa nezmení)
# =====================================================================
potrebne_steny = {}
for w in steny:
    potrebne_steny[w.Id.Value] = w
for inst in otvory_na_kontrolu:
    potrebne_steny[inst.Host.Id.Value] = inst.Host

STENY_SOLIDY = {}
presna_geometria = True
if potrebne_steny:
    docasne_zmazat = [inst.Id for inst in vsetky_otvory
                      if inst.Host is not None
                      and inst.Host.Id.Value in potrebne_steny]
    tt = DB.Transaction(doc, u"Auto-shaft – dočasný výpočet")
    try:
        tt.Start()
        if docasne_zmazat:
            doc.Delete(List[DB.ElementId](docasne_zmazat))
            doc.Regenerate()
        for wid, w in potrebne_steny.items():
            STENY_SOLIDY[wid] = [DB.SolidUtils.Clone(s) for s in solidy(w)]
    except Exception:
        presna_geometria = False
        STENY_SOLIDY = {}
    finally:
        if tt.HasStarted() and not tt.HasEnded():
            tt.RollBack()
    for wid, w in potrebne_steny.items():
        if wid not in STENY_SOLIDY:
            STENY_SOLIDY[wid] = solidy(w)

# =====================================================================
#  5) POTREBNÉ OBDĹŽNIKY NA KAŽDEJ STENE
# =====================================================================
polozky_steny = {}       # wall_id -> [položka]
v_stene = []             # [link, id prvku, kategória, stena, uhol]
chyby_geometrie = []     # [link, id prvku, stena]
pocet_malych = 0
pocet_uz_ma_otvor = 0


def pridaj_polozku(wid, r, kluce, uhol, vlastnik=None):
    polozky_steny.setdefault(wid, []).append({
        "r": list(r), "kluce": list(kluce), "uhol": uhol,
        "vlastnici": set([vlastnik]) if vlastnik is not None else set()})


# 5a) nové prvky z vybraných linkov
if rob_nove and steny and linky:
    with forms.ProgressBar(
            title=u"Auto-shaft – hľadám kolízie ({value} / {max_value})",
            cancellable=True) as pb:
        for idx, wall in enumerate(steny):
            if pb.cancelled:
                script.exit()
            pb.update_progress(idx + 1, len(steny))

            wid = wall.Id.Value
            wall_bb = wall.get_BoundingBox(None)
            wall_solidy = STENY_SOLIDY.get(wid)
            if wall_bb is None or not wall_solidy:
                continue
            p0, d, n = ram_steny(wall)

            for li in linky:
                kats = []
                for gkey, _, _, gk in SKUPINY:
                    if (gkey, li.Id.Value) in vysledok["pary"]:
                        kats.extend(gk)
                if not kats:
                    continue
                lname = nazov_linku(li)
                outline = outline_v_linku(wall_bb, li.GetTotalTransform().Inverse)
                prvky = DB.FilteredElementCollector(doc, view.Id, li.Id) \
                    .WherePasses(DB.ElementMulticategoryFilter(
                        List[DB.BuiltInCategory](kats))) \
                    .WherePasses(DB.BoundingBoxIntersectsFilter(outline))
                for e in prvky:
                    bic = bic_of(e)
                    if bic is None or bic not in odstup_kat:
                        continue
                    vlastnik = vlastnik_identity.get(identita(e.UniqueId, wid))
                    if vlastnik is not None and vlastnik in kontrolovane_ids:
                        continue    # vyhodnotí sa pri kontrole existujúceho otvoru
                    stav, data = vyhodnot_prvok(e, li, wall_solidy, p0, d, n,
                                                odstup_kat[bic])
                    if stav == "maly":
                        pocet_malych += 1
                    elif stav == "v_stene":
                        v_stene.append([lname, e.Id.Value, e.Category.Name,
                                        output.linkify(wall.Id), uhol_txt(data)])
                    elif stav == "bez":
                        if data:
                            chyby_geometrie.append([lname, e.Id.Value,
                                                    output.linkify(wall.Id)])
                    elif vlastnik is not None:
                        pocet_uz_ma_otvor += 1
                    else:
                        pridaj_polozku(wid, data[:4],
                                       [plny_kluc(lname, e.UniqueId, wid)], data[4])

# 5b) prvky existujúcich otvorov
info_otvorov = {}   # id -> údaje o otvore
if otvory_na_kontrolu:
    with forms.ProgressBar(
            title=u"Auto-shaft – kontrolujem otvory ({value} / {max_value})",
            cancellable=True) as pb:
        for idx, inst in enumerate(otvory_na_kontrolu):
            if pb.cancelled:
                script.exit()
            pb.update_progress(idx + 1, len(otvory_na_kontrolu))

            wall = inst.Host
            wid = wall.Id.Value
            p0, d, n = ram_steny(wall)
            kluce = kluce_otvoru(inst)
            inf = {"inst": inst, "id": inst.Id, "wall": wall, "p0": p0, "d": d,
                   "akt": skutocny_otvor(inst, p0, d), "kluce": kluce,
                   "zmazane": 0, "neoverene": 0, "platne": 0,
                   "rucny_rect": rucny_rect(kluce), "rucny_novy": False}
            if inf["rucny_rect"] is None and inf["akt"] is not None \
                    and not any(rozober_kluc(k) for k in kluce):
                # otvor bez ID = osadený ručne: pokus o prevzatie
                inf["rucny_rect"] = rect_z_akt(inf["akt"])
                inf["rucny_novy"] = True
            if inf["rucny_rect"] is not None:
                # ručný rozmer je minimum – otvor sa nezmenší ani neposunie
                pridaj_polozku(wid, inf["rucny_rect"], [], 0.0, inst.Id.Value)
            neoverene_kluce = []
            wall_solidy = STENY_SOLIDY.get(wid)
            for k in kluce:
                rozobrany = rozober_kluc(k)
                if not rozobrany:
                    continue
                inf["platne"] += 1
                if not wall_solidy:
                    neoverene_kluce.append(k)   # geometria steny sa nenačítala
                    continue
                link, uid, _ = rozobrany
                stav_p, li, e = najdi_prvok(link, uid)
                if stav_p == "neovereny":
                    neoverene_kluce.append(k)
                    continue
                if stav_p == "zmazany":
                    inf["zmazane"] += 1
                    continue
                bic = bic_of(e)
                if bic not in odstup_kat:
                    continue
                stav, data = vyhodnot_prvok(e, li, wall_solidy, p0, d, n,
                                            odstup_kat[bic])
                if stav == "otvor":
                    pridaj_polozku(wid, data[:4],
                                   [plny_kluc(nazov_linku(li), uid, wid)],
                                   data[4], inst.Id.Value)
                elif stav == "bez" and data:
                    neoverene_kluce.append(k)   # zlyhal výpočet, radšej nemazať
            if neoverene_kluce and inf["akt"] is not None:
                # prvky z nenačítaného linku: zachová sa pôvodný rozmer otvoru
                pridaj_polozku(wid, rect_z_akt(inf["akt"]), neoverene_kluce,
                               0.0, inst.Id.Value)
            inf["neoverene"] = len(neoverene_kluce)
            info_otvorov[inst.Id.Value] = inf

# existujúce otvory na stenách pre nové otvory (pri vypnutej kontrole len upozornenie)
existujuce_na_stene = {}
if rob_nove and not rob_kontrolu:
    ids_stien = set(w.Id.Value for w in steny)
    for inst in vsetky_otvory:
        host = inst.Host
        if host is None or host.Id.Value not in ids_stien:
            continue
        p0, d, n = ram_steny(host)
        akt = skutocny_otvor(inst, p0, d)
        if akt is not None:
            existujuce_na_stene.setdefault(host.Id.Value, []).append(
                (inst.Id, rect_z_akt(akt)))

# =====================================================================
#  6) SPOJENIE A POROVNANIE S EXISTUJÚCIMI OTVORMI
# =====================================================================
nove_otvory = []        # {"wall", "ciel", "kluce", "uhol"}
upravy = []             # {"inf", "ciel", "kluce", "uhol", "zlucit": [inf], "len_id"}
neoverene_otvory = []
bez_id = []                # ručné otvory, ktorými nič neprechádza – nemenia sa
prekryte_rucne = []        # ručné otvory v jednej skupine s iným ručným
rucne_bez_potrubia = []    # prevzaté ručné otvory, z ktorých potrubie zmizlo
blizko_existujuceho = []   # [stena, id existujúceho otvoru]
pouzite = set()
pocet_ok = 0

for wid, polozky in polozky_steny.items():
    wall = doc.GetElement(DB.ElementId(wid))
    # väčšie skupiny najprv: ak sa prvky jedného otvoru rozišli do viacerých
    # skupín, otvor ostane najväčšej a ostatné dostanú nový otvor
    skupiny = sorted(spoj_polozky(polozky, medzera_ft),
                     key=lambda c: -(c["r"][1] - c["r"][0]) * (c["r"][3] - c["r"][2]))
    for c in skupiny:
        z_rozdelenia = bool(c["vlastnici"]) and not (c["vlastnici"] - pouzite)
        c["vlastnici"] = c["vlastnici"] - pouzite
        ciel = ciel_otvoru(c["r"])
        if not c["vlastnici"]:
            nove_otvory.append({"wall": wall, "ciel": ciel, "kluce": c["kluce"],
                                "uhol": c["uhol"], "z_rozdelenia": z_rozdelenia})
            ciel_r = [ciel[2] - ciel[0] / 2.0, ciel[2] + ciel[0] / 2.0,
                      ciel[3], ciel[3] + ciel[1]]
            for eid, er in existujuce_na_stene.get(wid, []):
                if su_blizko(ciel_r, er, medzera_ft):
                    blizko_existujuceho.append([output.linkify(wall.Id),
                                                output.linkify(eid)])
            continue

        pouzite.update(c["vlastnici"])
        def je_rucny(i):
            return info_otvorov[i]["rucny_rect"] is not None

        def plocha(i):
            akt_i = info_otvorov[i]["akt"]
            return akt_i[0] * akt_i[1] if akt_i else 0

        # ručné otvory majú prednosť a nikdy sa nemažú pri spájaní
        poradie = sorted(c["vlastnici"],
                         key=lambda i: (0 if je_rucny(i) else 1, -plocha(i)))
        inf = info_otvorov[poradie[0]]
        zlucit = [info_otvorov[i] for i in poradie[1:] if not je_rucny(i)]
        for i in poradie[1:]:
            if je_rucny(i):
                prekryte_rucne.append(info_otvorov[i])
        prvky = unikatne([k for k in c["kluce"] if rozober_kluc(k)])
        if inf["rucny_novy"] and not prvky and not zlucit:
            bez_id.append(inf)          # ručným otvorom nič neprechádza
            continue
        kluce_zapis = prvky + ([rucny_token(inf["rucny_rect"])]
                               if inf["rucny_rect"] is not None else [])
        if inf["rucny_rect"] is not None and not inf["rucny_novy"] and not prvky \
                and any(rozober_kluc(k) for k in inf["kluce"]):
            rucne_bez_potrubia.append(inf)
        akt = inf["akt"]
        zhoda = akt is not None and all(
            abs(a - b) <= tol_kontroly for a, b in zip(ciel, akt))
        if inf["neoverene"]:
            neoverene_otvory.append(inf)
        if not zlucit and zhoda and set(kluce_zapis) == set(inf["kluce"]):
            pocet_ok += 1
            continue
        upravy.append({"inf": inf, "ciel": ciel, "kluce": kluce_zapis,
                       "uhol": c["uhol"], "zlucit": zlucit,
                       "len_id": zhoda and not zlucit,
                       "prevzaty": inf["rucny_novy"]})

bez_kolizie = []
for oid, inf in info_otvorov.items():
    if oid in pouzite:
        continue
    if not inf["platne"]:
        bez_id.append(inf)
        continue
    if inf["neoverene"]:
        neoverene_otvory.append(inf)    # nedá sa overiť – nikdy nemazať
        continue
    inf["stav"] = "zmazany" if inf["platne"] and inf["zmazane"] == inf["platne"] \
        else "bez_kolizie"
    bez_kolizie.append(inf)

upravy_prevzate = [u for u in upravy if u["prevzaty"]]
upravy_rozmer = [u for u in upravy if not u["prevzaty"] and not u["len_id"]]
upravy_id = [u for u in upravy if not u["prevzaty"] and u["len_id"]]
pocet_zlucenych = sum(len(u["zlucit"]) for u in upravy)
velke_nove = [o for o in nove_otvory if je_velky(o["ciel"])]
velke_upravy = [u for u in upravy_rozmer + upravy_prevzate if je_velky(u["ciel"])]

akcia_nove = [o for o in nove_otvory
              if (o["z_rozdelenia"] and vysledok["upravit"])
              or (not o["z_rozdelenia"] and rob_nove)]
akcia_upravit = upravy if vysledok["upravit"] else []
akcia_zmazat = bez_kolizie if vysledok["zmazat"] else []

# prvky obsadené iným používateľom (zdieľaný model) sa vynechajú
obsadene = []    # [prvok, dôvod]
_nove = []
for o in akcia_nove:
    if obsadeny(o["wall"].Id):
        obsadene.append([output.linkify(o["wall"].Id), u"stena – nový otvor sa neosadí"])
    else:
        _nove.append(o)
akcia_nove = _nove
_upravy = []
for u in akcia_upravit:
    ids = [u["inf"]["id"]] + [z["id"] for z in u["zlucit"]]
    if any(obsadeny(i) for i in ids):
        obsadene.append([output.linkify(u["inf"]["id"]), u"otvor – úprava sa vynechá"])
    else:
        _upravy.append(u)
akcia_upravit = _upravy
_zmazat = []
for inf in akcia_zmazat:
    if obsadeny(inf["id"]):
        obsadene.append([output.linkify(inf["id"]), u"otvor – nezmaže sa"])
    else:
        _zmazat.append(inf)
akcia_zmazat = _zmazat

# =====================================================================
#  7) SÚHRN A POTVRDENIE
# =====================================================================
vykonat = False
if akcia_nove or akcia_upravit or akcia_zmazat:
    riadky = []
    if rob_nove:
        riadky.append(u"Nové otvory: {}".format(len(nove_otvory)))
    if rob_kontrolu:
        riadky.append(u"Existujúce otvory skontrolované: {} (v poriadku: {})".format(
            len(info_otvorov), pocet_ok))
        vypnute = u"" if vysledok["upravit"] else u" (úprava vypnutá)"
        riadky.append(u"   – posunuté alebo zmenený rozmer: {}{}".format(
            len(upravy_rozmer), vypnute))
        if pocet_zlucenych:
            riadky.append(u"   – spojenie: {} otvorov sa zlúči do susedných{}".format(
                pocet_zlucenych, vypnute))
        if upravy_prevzate:
            riadky.append(u"   – prevzaté ručné otvory: {}{}".format(
                len(upravy_prevzate), vypnute))
        if upravy_id:
            riadky.append(u"   – doplnenie údajov v {}: {}{}".format(
                PARAM_LINKID, len(upravy_id), vypnute))
        riadky.append(u"   – bez kolízie alebo prvok zmazaný: {}{}".format(
            len(bez_kolizie), u"" if vysledok["zmazat"] else u" (mazanie vypnuté)"))
        if neoverene_otvory:
            riadky.append(u"   – neoverené (link nie je načítaný): {}".format(
                len(neoverene_otvory)))
    if velke_nove or velke_upravy:
        riadky.append(u"Otvory väčšie ako {:g} mm (posúdi statik): {}".format(
            vysledok["limit"], len(velke_nove) + len(velke_upravy)))
    if blizko_existujuceho:
        riadky.append(u"Nové otvory blízko existujúcich (zapni kontrolu na spojenie): {}"
                      .format(len(blizko_existujuceho)))
    if v_stene:
        riadky.append(u"Prvky vedené v stene (riešiť ručne): {}".format(len(v_stene)))
    if obsadene:
        riadky.append(u"Vynechané – obsadené iným používateľom: {}".format(len(obsadene)))
    zlucene_vykonat = sum(len(u["zlucit"]) for u in akcia_upravit)
    riadky.append(u"")
    riadky.append(u"Vykonať: {} nových, {} upraviť, {} zmazať{}?".format(
        len(akcia_nove), len(akcia_upravit),
        len(akcia_zmazat) + zlucene_vykonat,
        u" (vrátane spojených)" if zlucene_vykonat else u""))
    odpoved = forms.alert(u"\n".join(riadky), title=u"Auto-shaft – súhrn",
                          options=[u"Vykonať", u"Len report", u"Zrušiť"],
                          warn_icon=False)
    if not odpoved or odpoved == u"Zrušiť":
        script.exit()
    vykonat = odpoved == u"Vykonať"

# =====================================================================
#  8) VYKONANIE
# =====================================================================
osadene_ids = {}      # id(záznam nového otvoru) -> ElementId
zmazane_ids = set()
varovania = None
if vykonat:
    varovania = PotlacVarovania()
    t = DB.Transaction(doc, u"Auto-shaft")
    moznosti = t.GetFailureHandlingOptions()
    moznosti.SetFailuresPreprocessor(varovania)
    t.SetFailureHandlingOptions(moznosti)
    t.Start()
    try:
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()

        na_posun = []   # (inst, cieľový stred pozdĺž steny, p0, d)
        na_zmazanie = []

        for o in akcia_nove:
            sirka, vyska, u_stred, z_spodok = o["ciel"]
            wall = o["wall"]
            p0, d, n = ram_steny(wall)
            level = doc.GetElement(wall.LevelId)
            bod = p0 + d.Multiply(u_stred)
            inst = doc.Create.NewFamilyInstance(
                DB.XYZ(bod.X, bod.Y, z_spodok), symbol, wall, level,
                DB.Structure.StructuralType.NonStructural)
            nastav_otvor(inst, sirka, vyska, z_spodok, level, unikatne(o["kluce"]))
            na_posun.append((inst, u_stred, p0, d))
            osadene_ids[id(o)] = inst.Id

        for u in akcia_upravit:
            inf = u["inf"]
            inst = inf["inst"]
            sirka, vyska, u_stred, z_spodok = u["ciel"]
            nastav_otvor(inst, sirka, vyska, z_spodok,
                         doc.GetElement(inst.LevelId), unikatne(u["kluce"]))
            na_posun.append((inst, u_stred, inf["p0"], inf["d"]))
            na_zmazanie.extend(z["id"] for z in u["zlucit"])

        doc.Regenerate()
        tol = mm2ft(0.5)
        for inst, u_ciel, p0, d in na_posun:
            posun = u_ciel - (inst.Location.Point - p0).DotProduct(d)
            if abs(posun) > tol:
                DB.ElementTransformUtils.MoveElement(doc, inst.Id, d.Multiply(posun))

        na_zmazanie.extend(inf["id"] for inf in akcia_zmazat)
        if na_zmazanie:
            doc.Delete(List[DB.ElementId](na_zmazanie))
            zmazane_ids = set(i.Value for i in na_zmazanie)

        t.Commit()
    except SystemExit:
        raise
    except ChybaRodiny as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        forms.alert(u"{}\nNič nebolo zmenené.".format(ex), exitscript=True)
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        forms.alert(u"Chyba pri vykonaní, nič nebolo zmenené:\n{}".format(ex),
                    exitscript=True)

# =====================================================================
#  9) REPORT
# =====================================================================
def odkaz(eid):
    return str(eid.Value) if eid.Value in zmazane_ids else output.linkify(eid)


def statika_txt(ciel):
    return u"⚠ posúdiť" if je_velky(ciel) else u"–"


def rozmer_txt(sirka, vyska):
    return u"{} × {}".format(mm_txt(sirka), mm_txt(vyska))


output.print_md(u"## Auto-shaft – výsledok")
if not vykonat:
    output.print_md(u"**Len report – model nebol zmenený.**")
output.print_md(u"View: **{}** | Rodina: **{}** | Linky: **{}**".format(
    view.Name, volba, u", ".join(nazov_linku(l) for l in linky) or u"–"))
output.print_md(u"Odsadenie: {} | Spájanie pri medzere pod {:g} mm | "
                u"Limit pre statika {:g} mm | Limit DN {:g}".format(
                    u", ".join(u"{} {:g} mm".format(nazov, vysledok["odstupy"][gkey])
                               for gkey, nazov, _, _ in SKUPINY),
                    vysledok["medzera"], vysledok["limit"], MIN_DN_MM))
if rob_nove:
    output.print_md(u"Typy konštrukcií: {}".format(u", ".join(nazvy_typov)))
if not presna_geometria:
    output.print_md(u"**Pozor:** geometriu stien sa nepodarilo načítať bez "
                    u"existujúcich otvorov (napr. otvory obsadené iným "
                    u"používateľom). Výsledok môže byť nepresný.")

if rob_nove or nove_otvory:
    output.print_md(u"### Nové otvory")
    output.print_md(u"- {}: **{}**".format(
        u"Osadené" if vykonat else u"Navrhnuté", len(nove_otvory)))
    output.print_md(u"- Z toho na posúdenie statikom: **{}**".format(len(velke_nove)))
    output.print_md(u"- Z toho šikmé prechody (skontrolovať): **{}**".format(
        len([1 for o in nove_otvory if o["uhol"] > TOLERANCIA_UHLA_DEG])))
    if pocet_uz_ma_otvor:
        output.print_md(u"- Preskočené – prvok už má otvor: **{}**".format(
            pocet_uz_ma_otvor))
    if MIN_DN_MM > 0:
        output.print_md(u"- Preskočené – menšie ako DN{:g}: **{}**".format(
            MIN_DN_MM, pocet_malych))
    output.print_md(u"- Preskočené – prvky vedené v stene: **{}**".format(len(v_stene)))
    output.print_md(u"- Zlyhaný výpočet geometrie: **{}**".format(len(chyby_geometrie)))
    if nove_otvory:
        riadky = []
        for o in nove_otvory:
            riadky.append([output.linkify(osadene_ids[id(o)]) if id(o) in osadene_ids
                           else u"–",
                           output.linkify(o["wall"].Id),
                           rozmer_txt(o["ciel"][0], o["ciel"][1]),
                           len(unikatne(o["kluce"])), uhol_txt(o["uhol"]),
                           statika_txt(o["ciel"]),
                           u"rozdelenie existujúceho" if o["z_rozdelenia"] else u"nový"])
        output.print_table(riadky, columns=[u"Otvor", u"Stena", u"Š × V [mm]",
                                            u"Počet prvkov", u"Šikmý prechod",
                                            u"Statika", u"Pôvod"])
    if blizko_existujuceho:
        output.print_md(u"#### Nové otvory blízko existujúcich – zapni kontrolu na spojenie")
        output.print_table(blizko_existujuceho, columns=[u"Stena", u"Existujúci otvor"])

if rob_kontrolu:
    output.print_md(u"### Kontrola existujúcich otvorov")
    output.print_md(u"- Skontrolované: **{}** (v poriadku: **{}**)".format(
        len(info_otvorov), pocet_ok))
    output.print_md(u"- Posunuté alebo zmenený rozmer: **{}**".format(len(upravy_rozmer)))
    output.print_md(u"- Otvory na spojenie so susedným: **{}**".format(pocet_zlucenych))
    output.print_md(u"- Bez kolízie alebo prvok zmazaný: **{}**".format(len(bez_kolizie)))
    if upravy_prevzate:
        output.print_md(u"- Prevzaté ručné otvory: **{}**".format(len(upravy_prevzate)))
    if upravy_id:
        output.print_md(u"- Doplnenie údajov v {}: **{}**".format(
            PARAM_LINKID, len(upravy_id)))
    if rucne_bez_potrubia:
        output.print_md(u"- Ručné otvory, z ktorých potrubie zmizlo: **{}**".format(
            len(rucne_bez_potrubia)))
    if neoverene_otvory:
        output.print_md(u"- Neoverené (link nie je načítaný): **{}**".format(
            len(neoverene_otvory)))

    if upravy_rozmer:
        if not vykonat:
            akcia = u"len report"
        elif vysledok["upravit"]:
            akcia = u"upravený"
        else:
            akcia = u"neupravený (vypnuté)"
        riadky = []
        for u in upravy_rozmer:
            akt = u["inf"]["akt"]
            ciel = u["ciel"]
            if akt is not None:
                povodne = rozmer_txt(akt[0], akt[1])
                posun = max(abs(mm_txt(ciel[2] - akt[2])), abs(mm_txt(ciel[3] - akt[3])))
            else:
                povodne = posun = u"?"
            spojene = u", ".join(odkaz(z["id"]) for z in u["zlucit"]) or u"–"
            riadky.append([odkaz(u["inf"]["id"]),
                           u"ručný" if u["inf"]["rucny_rect"] is not None else u"–",
                           output.linkify(u["inf"]["wall"].Id),
                           povodne, rozmer_txt(ciel[0], ciel[1]), posun, spojene,
                           uhol_txt(u["uhol"]), statika_txt(ciel), akcia])
        output.print_md(u"#### Posunuté, zmenené a spájané otvory")
        output.print_table(riadky, columns=[u"Otvor", u"Ručný", u"Stena",
                                            u"Pôvodne Š × V", u"Nové Š × V",
                                            u"Posun [mm]",
                                            u"Spojené otvory (zmažú sa)",
                                            u"Šikmý prechod", u"Statika", u"Akcia"])

    if upravy_prevzate:
        if not vykonat:
            akcia = u"len report"
        elif vysledok["upravit"]:
            akcia = u"prevzatý"
        else:
            akcia = u"neprevzatý (úprava vypnutá)"
        riadky = []
        for u in upravy_prevzate:
            akt = u["inf"]["akt"]
            ciel = u["ciel"]
            povodne = rozmer_txt(akt[0], akt[1]) if akt else u"?"
            zvacseny = akt is not None and (ciel[0] > akt[0] + tol_kontroly
                                            or ciel[1] > akt[1] + tol_kontroly)
            riadky.append([odkaz(u["inf"]["id"]), output.linkify(u["inf"]["wall"].Id),
                           povodne, rozmer_txt(ciel[0], ciel[1]),
                           u"áno" if zvacseny else u"nie",
                           len([k for k in u["kluce"] if rozober_kluc(k)]),
                           u", ".join(odkaz(z["id"]) for z in u["zlucit"]) or u"–",
                           akcia])
        output.print_md(u"#### Prevzaté ručné otvory")
        output.print_md(u"Ručný rozmer ostáva ako minimum – otvor sa môže len "
                        u"zväčšiť, nezmenší sa, neposunie ani nezmaže.")
        output.print_table(riadky, columns=[u"Otvor", u"Stena", u"Ručný Š × V",
                                            u"Nové Š × V", u"Zväčšený",
                                            u"Počet prvkov",
                                            u"Spojené otvory (zmažú sa)", u"Akcia"])

    if rucne_bez_potrubia:
        output.print_md(u"#### Ručné otvory, z ktorých potrubie zmizlo – ponechané, riešiť ručne")
        output.print_md(u", ".join(odkaz(inf["id"]) for inf in rucne_bez_potrubia))
    if prekryte_rucne:
        output.print_md(u"#### Ručné otvory prekryté iným ručným otvorom – skontrolovať")
        output.print_md(u", ".join(odkaz(inf["id"]) for inf in prekryte_rucne))

    if bez_kolizie:
        if not vykonat:
            akcia = u"len report"
        elif vysledok["zmazat"]:
            akcia = u"zmazaný"
        else:
            akcia = u"ponechaný (vypnuté)"
        riadky = []
        for inf in bez_kolizie:
            stav = u"prvok zmazaný v linku" if inf["stav"] == "zmazany" \
                else u"prvok už stenou neprechádza"
            riadky.append([odkaz(inf["id"]), output.linkify(inf["wall"].Id), stav, akcia])
        output.print_md(u"#### Bez kolízie alebo prvok zmazaný")
        output.print_table(riadky, columns=[u"Otvor", u"Stena", u"Stav", u"Akcia"])

    if neoverene_otvory:
        output.print_md(u"#### Neoverené – prvky z nenačítaného linku, rozmer sa zachoval")
        output.print_table([[odkaz(inf["id"]), output.linkify(inf["wall"].Id),
                             inf["neoverene"]] for inf in neoverene_otvory],
                           columns=[u"Otvor", u"Stena", u"Počet neoverených prvkov"])

if bez_id:
    output.print_md(u"### Ručné otvory bez potrubia – ponechané bez zmeny")
    output.print_md(u"Otvory bez {}, ktorými neprechádza žiadne potrubie z linkov "
                    u"(napr. rezerva). Plugin ich nemení ani nemaže.".format(PARAM_LINKID))
    output.print_md(u", ".join(output.linkify(inf["id"]) for inf in bez_id))
if obsadene:
    output.print_md(u"### Vynechané – obsadené iným používateľom")
    output.print_table(obsadene, columns=[u"Prvok", u"Dôsledok"])
if varovania and varovania.spravy:
    output.print_md(u"### Varovania Revitu počas zápisu")
    for sprava in unikatne(varovania.spravy):
        output.print_md(u"- {} ({}×)".format(sprava, varovania.spravy.count(sprava)))
if v_stene:
    output.print_md(u"### Prvky vedené v stene – riešiť ručne")
    output.print_table(v_stene, columns=[u"Link", u"ID prvku", u"Kategória",
                                         u"Stena", u"Odklon od kolmice"])
if chyby_geometrie:
    output.print_md(u"### Zlyhaný výpočet geometrie – skontrolovať ručne")
    output.print_table(chyby_geometrie, columns=[u"Link", u"ID prvku", u"Stena"])
if steny_preskocene:
    output.print_md(u"### Oblúkové steny – preskočené")
    output.print_md(u", ".join(output.linkify(w.Id) for w in steny_preskocene))

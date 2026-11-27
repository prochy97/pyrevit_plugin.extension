# -*- coding: utf-8 -*-
"""Auto-shaft
Osadí obdĺžnikové otvory do vybraných typov stien v mieste kolízií
s nalinkovanými profesiami a skontroluje existujúce otvory
(posunuté, zmenené, bez kolízie). Pracuje iba v aktívnom view.
"""
__title__ = "Auto-shaft"
__doc__ = (u"Osadí obdĺžnikové otvory do vybraných typov stien v miestach "
           u"kolízií s linkami profesií a skontroluje existujúce otvory "
           u"(iba aktívny view).")

import math
import os

import clr
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from System.Collections.Generic import List
from pyrevit import revit, DB, forms, script
from System.Windows import Thickness
from System.Windows.Controls import CheckBox

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
MIN_DN_MM = 20.0                # prepíše sa hodnotou z okna (pod DN sa ignorujú)
TOLERANCIA_UHLA_DEG = 5.0       # väčší odklon od kolmice = šikmý prechod (osadí sa, vypíše sa)
MAX_UHOL_DEG = 75.0             # väčší odklon = prvok vedený v stene (neosadí sa)
TOLERANCIA_KONTROLY_MM = 5.0    # menší rozdiel polohy/rozmeru = otvor sedí

PREDVOLENY_FILTER = u"RCO"      # typy stien označené pri prvom spustení
PREDVOLENA_RODINA = u"DGSK_otvor_stena"
PREDVOLENY_ODSTUP = u"50"
PREDVOLENE_MIN_DN = u"20"

# kľúč (= názov ovládacích prvkov v ui.xaml), popis, kategórie
PROFESIE = [
    ("pipes", u"Potrubia (ZTI, ÚK, chladenie)",
     [BIC.OST_PipeCurves, BIC.OST_PipeFitting, BIC.OST_PipeInsulations]),
    ("vzt", u"VZT",
     [BIC.OST_DuctCurves, BIC.OST_DuctFitting, BIC.OST_DuctInsulations]),
    ("ele", u"Elektro (žľaby, chráničky)",
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
                                a[4] + b[4], max(a[5], b[5])]
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


def unia(rects):
    """Spojí všetky obdĺžniky do jedného (pre kontrolu existujúceho otvoru)."""
    r = list(rects[0])
    for b in rects[1:]:
        r = [min(r[0], b[0]), max(r[1], b[1]), min(r[2], b[2]), max(r[3], b[3]),
             r[4] + b[4], max(r[5], b[5])]
    return r


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

        # 2. typy stien
        self.filter_tb.Text = cfg_get("filter", PREDVOLENY_FILTER)
        self.wall_cbs = []
        for tid, info in sorted(typy_stien.items(),
                                key=lambda kv: kv[1]["name"].lower()):
            cb = CheckBox()
            cb.Content = u"{}   ({} ks)".format(info["name"], len(info["walls"]))
            cb.Tag = tid
            cb.Margin = Thickness(2)
            self.walls_sp.Children.Add(cb)
            self.wall_cbs.append((cb, info["name"]))
        self.oznac_podla_filtra()

        # 3. linky
        self.link_cbs = []
        for li in linky_vo_view:
            cb = CheckBox()
            cb.Content = li.Name
            cb.Tag = li.Id.Value
            cb.IsChecked = True
            cb.Margin = Thickness(2)
            self.links_sp.Children.Add(cb)
            self.link_cbs.append(cb)

        # 4. profesie a odstup
        self.uniform_tb.Text = cfg_get("odstup", PREDVOLENY_ODSTUP)
        for key, _, _ in PROFESIE:
            getattr(self, key + "_cb").IsChecked = \
                cfg_get("prof_" + key, u"1") == u"1"
            getattr(self, key + "_tb").Text = \
                cfg_get("odstup_" + key, PREDVOLENY_ODSTUP)
        self.mindn_tb.Text = cfg_get("min_dn", PREDVOLENE_MIN_DN)
        if cfg_get("rezim", u"jednotny") == u"jednotny":
            self.uniform_rb.IsChecked = True
        else:
            self.per_rb.IsChecked = True
        self.prepni_rezim()

        # 5. akcie
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
        for key, _, _ in PROFESIE:
            getattr(self, key + "_tb").IsEnabled = not jednotny

    def prepni_kontrolu(self):
        zapnuta = bool(self.check_cb.IsChecked)
        self.update_cb.IsEnabled = zapnuta
        self.delete_cb.IsEnabled = zapnuta

    def start(self, sender, args):
        nove = bool(self.new_cb.IsChecked)
        kontrola = bool(self.check_cb.IsChecked)
        if not (nove or kontrola):
            forms.alert(u"Zvoľ aspoň jednu akciu v časti 5.")
            return
        if self.family_cb.SelectedIndex < 0:
            forms.alert(u"Vyber rodinu otvoru.")
            return
        steny_ids = set(cb.Tag for cb, _ in self.wall_cbs if cb.IsChecked)
        link_ids = set(cb.Tag for cb in self.link_cbs if cb.IsChecked)
        profesie = [key for key, _, _ in PROFESIE
                    if getattr(self, key + "_cb").IsChecked]
        if nove and not steny_ids:
            forms.alert(u"Pre osadenie nových otvorov označ aspoň jeden typ steny.")
            return
        if nove and not link_ids:
            forms.alert(u"Pre osadenie nových otvorov označ aspoň jeden link.")
            return
        if nove and not profesie:
            forms.alert(u"Pre osadenie nových otvorov označ aspoň jednu profesiu.")
            return

        # odstupy pre všetky profesie (kontrola existujúcich ich potrebuje vždy)
        jednotny = bool(self.uniform_rb.IsChecked)
        popisy = dict((k, p) for k, p, _ in PROFESIE)
        odstupy = {}
        if jednotny:
            v = parse_mm(self.uniform_tb.Text)
            if v is None:
                forms.alert(u"Jednotný odstup musí byť kladné číslo v mm.")
                return
            for key, _, _ in PROFESIE:
                odstupy[key] = v
        else:
            for key, _, _ in PROFESIE:
                v = parse_mm(getattr(self, key + "_tb").Text)
                if v is None:
                    if key in profesie or kontrola:
                        forms.alert(u"Odstup pre '{}' musí byť kladné číslo v mm."
                                    .format(popisy[key]))
                        return
                    v = float(PREDVOLENY_ODSTUP)
                odstupy[key] = v

        min_dn = parse_mm(self.mindn_tb.Text)
        if min_dn is None:
            forms.alert(u"Minimálne DN musí byť kladné číslo (0 = bez obmedzenia).")
            return

        # uloženie nastavení na ďalšie spustenie
        try:
            cfg.set_option("rodina", self.family_cb.SelectedItem)
            cfg.set_option("filter", self.filter_tb.Text or u"")
            cfg.set_option("rezim", u"jednotny" if jednotny else u"profesie")
            cfg.set_option("odstup", self.uniform_tb.Text or u"")
            cfg.set_option("min_dn", self.mindn_tb.Text or u"")
            for key, _, _ in PROFESIE:
                cfg.set_option("prof_" + key,
                               u"1" if getattr(self, key + "_cb").IsChecked else u"0")
                cfg.set_option("odstup_" + key,
                               getattr(self, key + "_tb").Text or u"")
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
            "linky": link_ids,
            "profesie": profesie,
            "odstupy": odstupy,
            "min_dn": min_dn,
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
MIN_DN_MM = vysledok["min_dn"]
rob_kontrolu = vysledok["kontrola"]

# odstup podľa kategórie – pre všetky profesie
odstup_kat = {}
for key, _, kats in PROFESIE:
    for k in kats:
        odstup_kat[int(k)] = mm2ft(vysledok["odstupy"][key])
# kategórie pre nové otvory – len vybrané profesie
nove_kat = []
for key, _, kats in PROFESIE:
    if key in vysledok["profesie"]:
        nove_kat.extend(kats)
nove_bic = set(int(k) for k in nove_kat)

# =====================================================================
#  3) EXISTUJÚCE OTVORY, STENY, LINKY
# =====================================================================
vsetky_otvory = []
existujuce_kluce = set()
for inst in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance) \
        .OfCategory(BIC.OST_GenericModel):
    if inst.Symbol.Family.Id != symbol.Family.Id:
        continue
    vsetky_otvory.append(inst)
    existujuce_kluce.update(kluce_otvoru(inst))

# otvory na kontrolu = hostiteľská stena je v aktívnom view
otvory_na_kontrolu = []
if rob_kontrolu:
    for inst in vsetky_otvory:
        host = inst.Host
        if host is not None and host.Id.Value in steny_vo_view \
                and je_rovna_stena(host):
            otvory_na_kontrolu.append(inst)

# steny pre nové otvory
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

linky = [li for li in linky_vo_view if li.Id.Value in vysledok["linky"]]

# vyhľadávanie prvkov podľa UniqueId vo všetkých načítaných linkoch
vsetky_linky = list(DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance))
nacitane_linky = [li for li in vsetky_linky if li.GetLinkDocument() is not None]
nenacitany_link = len(nacitane_linky) < len(vsetky_linky)
UID_CACHE = {}


def najdi_v_linkoch(uid):
    if uid not in UID_CACHE:
        najdene = None
        for li in nacitane_linky:
            e = li.GetLinkDocument().GetElement(uid)
            if e is not None:
                najdene = (li, e)
                break
        UID_CACHE[uid] = najdene
    return UID_CACHE[uid]


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
#  5) NOVÉ OTVORY – HĽADANIE KOLÍZIÍ
# =====================================================================
otvory_na_stene = {}     # wall_id -> [u0, u1, z0, z1, [kluce], uhol]
v_stene = []             # [link, id prvku, kategória, stena, uhol]
chyby_geometrie = []     # [link, id prvku, stena]
pocet_malych = 0
pocet_uz_ma_otvor = 0

if rob_nove and steny and linky:
    cat_filter = DB.ElementMulticategoryFilter(
        List[DB.BuiltInCategory](nove_kat))
    with forms.ProgressBar(
            title=u"Auto-shaft – hľadám kolízie ({value} / {max_value})",
            cancellable=True) as pb:
        for idx, wall in enumerate(steny):
            if pb.cancelled:
                script.exit()
            pb.update_progress(idx + 1, len(steny))

            wall_bb = wall.get_BoundingBox(None)
            wall_solidy = STENY_SOLIDY.get(wall.Id.Value)
            if wall_bb is None or not wall_solidy:
                continue
            p0, d, n = ram_steny(wall)

            for li in linky:
                outline = outline_v_linku(wall_bb, li.GetTotalTransform().Inverse)
                prvky = DB.FilteredElementCollector(doc, view.Id, li.Id) \
                    .WherePasses(cat_filter) \
                    .WherePasses(DB.BoundingBoxIntersectsFilter(outline))
                for e in prvky:
                    bic = bic_of(e)
                    if bic is None or bic not in nove_bic:
                        continue
                    stav, data = vyhodnot_prvok(e, li, wall_solidy, p0, d, n,
                                                odstup_kat[bic])
                    if stav == "maly":
                        pocet_malych += 1
                    elif stav == "v_stene":
                        v_stene.append([li.Name, e.Id.Value, e.Category.Name,
                                        output.linkify(wall.Id), uhol_txt(data)])
                    elif stav == "bez":
                        if data:
                            chyby_geometrie.append([li.Name, e.Id.Value,
                                                    output.linkify(wall.Id)])
                    else:
                        kluc = u"{}@{}".format(e.UniqueId, wall.Id.Value)
                        if kluc in existujuce_kluce:
                            pocet_uz_ma_otvor += 1
                            continue
                        otvory_na_stene.setdefault(wall.Id.Value, []).append(
                            data[:4] + [[kluc], data[4]])

nove_otvory = []   # (wall, rect)
for wid, rects in otvory_na_stene.items():
    wall = doc.GetElement(DB.ElementId(wid))
    for r in zluc_prekryvy(rects):
        nove_otvory.append((wall, r))

# =====================================================================
#  6) KONTROLA EXISTUJÚCICH OTVOROV
# =====================================================================
kontrola = []   # dict pre každý skontrolovaný otvor
tol_kontroly = mm2ft(TOLERANCIA_KONTROLY_MM)

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
            rects = []
            ponechane = []
            zmazane = 0
            neoverene = False
            for k in kluce:
                if u"@" not in k:
                    continue
                uid = k.rsplit(u"@", 1)[0]
                najdene = najdi_v_linkoch(uid)
                if najdene is None:
                    if nenacitany_link:
                        neoverene = True
                        ponechane.append(k)
                    else:
                        zmazane += 1
                    continue
                li, e = najdene
                bic = bic_of(e)
                if bic not in odstup_kat:
                    continue
                stav, data = vyhodnot_prvok(e, li, STENY_SOLIDY[wid], p0, d, n,
                                            odstup_kat[bic])
                if stav == "otvor":
                    rects.append(data[:4] + [[k], data[4]])
                    ponechane.append(k)

            zaznam = {"inst": inst, "id": inst.Id, "wall": wall, "p0": p0, "d": d,
                      "kluce": ponechane,
                      "akt": skutocny_otvor(inst, p0, d)}
            if not rects:
                if neoverene:
                    zaznam["stav"] = "neoverene"
                elif kluce and zmazane == len(kluce):
                    zaznam["stav"] = "zmazany"
                else:
                    zaznam["stav"] = "bez_kolizie"
            else:
                r = unia(rects)
                ciel = ciel_otvoru(r)
                zaznam["ciel"] = ciel
                zaznam["uhol"] = r[5]
                akt = zaznam["akt"]
                zhoda = akt is not None and all(
                    abs(a - b) <= tol_kontroly for a, b in zip(ciel, akt))
                if zhoda and set(ponechane) == set(kluce):
                    zaznam["stav"] = "ok"
                else:
                    zaznam["stav"] = "zmeneny"
            kontrola.append(zaznam)

zmenene = [z for z in kontrola if z["stav"] == "zmeneny"]
bez_kolizie = [z for z in kontrola if z["stav"] in ("bez_kolizie", "zmazany")]
neoverene_otvory = [z for z in kontrola if z["stav"] == "neoverene"]
pocet_ok = len([z for z in kontrola if z["stav"] == "ok"])

akcia_nove = nove_otvory if rob_nove else []
akcia_upravit = zmenene if vysledok["upravit"] else []
akcia_zmazat = bez_kolizie if vysledok["zmazat"] else []

# =====================================================================
#  7) SÚHRN A POTVRDENIE
# =====================================================================
vykonat = False
if akcia_nove or akcia_upravit or akcia_zmazat:
    riadky = []
    if rob_nove:
        riadky.append(u"Nové otvory: {}".format(len(nove_otvory)))
    if rob_kontrolu:
        riadky.append(u"Existujúce otvory skontrolované: {}".format(len(kontrola)))
        riadky.append(u"   – v poriadku: {}".format(pocet_ok))
        riadky.append(u"   – posunuté alebo zmenený rozmer: {}{}".format(
            len(zmenene), u"" if vysledok["upravit"] else u" (úprava vypnutá)"))
        riadky.append(u"   – bez kolízie alebo prvok zmazaný: {}{}".format(
            len(bez_kolizie), u"" if vysledok["zmazat"] else u" (mazanie vypnuté)"))
        if neoverene_otvory:
            riadky.append(u"   – neoverené (link nie je načítaný): {}".format(
                len(neoverene_otvory)))
    if v_stene:
        riadky.append(u"Prvky vedené v stene (riešiť ručne): {}".format(len(v_stene)))
    riadky.append(u"")
    riadky.append(u"Vykonať: {} nových, {} upraviť, {} zmazať?".format(
        len(akcia_nove), len(akcia_upravit), len(akcia_zmazat)))
    odpoved = forms.alert(u"\n".join(riadky), title=u"Auto-shaft – súhrn",
                          options=[u"Vykonať", u"Len report", u"Zrušiť"],
                          warn_icon=False)
    if not odpoved or odpoved == u"Zrušiť":
        script.exit()
    vykonat = odpoved == u"Vykonať"

# =====================================================================
#  8) VYKONANIE
# =====================================================================
osadene_ids = {}      # index v akcia_nove -> ElementId
zmazane_ids = set()
if vykonat:
    t = DB.Transaction(doc, u"Auto-shaft")
    t.Start()
    try:
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()

        na_posun = []   # (inst, cieľový stred pozdĺž steny, p0, d)

        for i, (wall, r) in enumerate(akcia_nove):
            sirka, vyska, u_stred, z_spodok = ciel_otvoru(r)
            p0, d, n = ram_steny(wall)
            level = doc.GetElement(wall.LevelId)
            bod = p0 + d.Multiply(u_stred)
            inst = doc.Create.NewFamilyInstance(
                DB.XYZ(bod.X, bod.Y, z_spodok), symbol, wall, level,
                DB.Structure.StructuralType.NonStructural)
            nastav_otvor(inst, sirka, vyska, z_spodok, level, r[4])
            na_posun.append((inst, u_stred, p0, d))
            osadene_ids[i] = inst.Id

        for z in akcia_upravit:
            inst = z["inst"]
            sirka, vyska, u_stred, z_spodok = z["ciel"]
            nastav_otvor(inst, sirka, vyska, z_spodok,
                         doc.GetElement(inst.LevelId), z["kluce"])
            na_posun.append((inst, u_stred, z["p0"], z["d"]))

        # poloha pozdĺž steny
        doc.Regenerate()
        tol = mm2ft(0.5)
        for inst, u_ciel, p0, d in na_posun:
            posun = u_ciel - (inst.Location.Point - p0).DotProduct(d)
            if abs(posun) > tol:
                DB.ElementTransformUtils.MoveElement(doc, inst.Id, d.Multiply(posun))

        if akcia_zmazat:
            ids = [z["id"] for z in akcia_zmazat]
            doc.Delete(List[DB.ElementId](ids))
            zmazane_ids = set(i.Value for i in ids)

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
output.print_md(u"## Auto-shaft – výsledok")
if not vykonat:
    output.print_md(u"**Len report – model nebol zmenený.**")
output.print_md(u"View: **{}** | Rodina: **{}** | Linky: **{}**".format(
    view.Name, volba, u", ".join(l.Name for l in linky) or u"–"))
if rob_nove:
    output.print_md(u"Typy stien: {}".format(u", ".join(nazvy_typov)))
if not presna_geometria:
    output.print_md(u"**Pozor:** geometriu stien sa nepodarilo načítať bez "
                    u"existujúcich otvorov (napr. otvory obsadené iným "
                    u"používateľom). Kontrola môže byť nepresná.")

if rob_nove:
    output.print_md(u"### Nové otvory")
    output.print_md(u"- {}: **{}**".format(
        u"Osadené" if vykonat else u"Navrhnuté", len(nove_otvory)))
    output.print_md(u"- Z toho šikmé prechody (skontrolovať): **{}**".format(
        len([1 for _, r in nove_otvory if r[5] > TOLERANCIA_UHLA_DEG])))
    output.print_md(u"- Preskočené – prvok už má otvor: **{}**".format(
        pocet_uz_ma_otvor))
    if MIN_DN_MM > 0:
        output.print_md(u"- Preskočené – menšie ako DN{:g}: **{}**".format(
            MIN_DN_MM, pocet_malych))
    output.print_md(u"- Preskočené – prvky vedené v stene: **{}**".format(
        len(v_stene)))
    output.print_md(u"- Zlyhaný výpočet geometrie: **{}**".format(
        len(chyby_geometrie)))
    if nove_otvory:
        riadky = []
        for i, (wall, r) in enumerate(nove_otvory):
            sirka, vyska, _, _ = ciel_otvoru(r)
            otvor = output.linkify(osadene_ids[i]) if i in osadene_ids else u"–"
            riadky.append([otvor, output.linkify(wall.Id), mm_txt(sirka),
                           mm_txt(vyska), len(r[4]), uhol_txt(r[5])])
        output.print_table(riadky, columns=[u"Otvor", u"Stena", u"Šírka [mm]",
                                            u"Výška [mm]", u"Počet prvkov",
                                            u"Šikmý prechod"])

if rob_kontrolu:
    output.print_md(u"### Kontrola existujúcich otvorov")
    output.print_md(u"- Skontrolované: **{}** (v poriadku: **{}**)".format(
        len(kontrola), pocet_ok))
    output.print_md(u"- Posunuté alebo zmenený rozmer: **{}**".format(len(zmenene)))
    output.print_md(u"- Bez kolízie alebo prvok zmazaný: **{}**".format(
        len(bez_kolizie)))
    if neoverene_otvory:
        output.print_md(u"- Neoverené (niektorý link nie je načítaný): **{}**".format(
            len(neoverene_otvory)))

    if zmenene:
        if not vykonat:
            akcia = u"len report"
        elif vysledok["upravit"]:
            akcia = u"upravený"
        else:
            akcia = u"neupravený (vypnuté)"
        riadky = []
        for z in zmenene:
            akt = z["akt"]
            ciel = z["ciel"]
            if akt is not None:
                povodne = u"{} × {}".format(mm_txt(akt[0]), mm_txt(akt[1]))
                posun = max(abs(mm_txt(ciel[2] - akt[2])),
                            abs(mm_txt(ciel[3] - akt[3])))
            else:
                povodne = u"?"
                posun = u"?"
            riadky.append([output.linkify(z["inst"].Id), output.linkify(z["wall"].Id),
                           povodne,
                           u"{} × {}".format(mm_txt(ciel[0]), mm_txt(ciel[1])),
                           posun, uhol_txt(z["uhol"]), akcia])
        output.print_md(u"#### Posunuté alebo zmenený rozmer")
        output.print_table(riadky, columns=[u"Otvor", u"Stena", u"Pôvodne Š × V",
                                            u"Nové Š × V", u"Posun [mm]",
                                            u"Šikmý prechod", u"Akcia"])

    if bez_kolizie:
        if not vykonat:
            akcia = u"len report"
        elif vysledok["zmazat"]:
            akcia = u"zmazaný"
        else:
            akcia = u"ponechaný (vypnuté)"
        riadky = []
        for z in bez_kolizie:
            iid = z["id"]
            otvor = str(iid.Value) if iid.Value in zmazane_ids \
                else output.linkify(iid)
            stav = u"prvok zmazaný v linku" if z["stav"] == "zmazany" \
                else u"prvok už stenou neprechádza"
            riadky.append([otvor, output.linkify(z["wall"].Id), stav, akcia])
        output.print_md(u"#### Bez kolízie alebo prvok zmazaný")
        output.print_table(riadky, columns=[u"Otvor", u"Stena", u"Stav", u"Akcia"])

    if neoverene_otvory:
        output.print_md(u"#### Neoverené – načítaj všetky linky a spusti znova")
        output.print_table([[output.linkify(z["inst"].Id), output.linkify(z["wall"].Id)]
                            for z in neoverene_otvory],
                           columns=[u"Otvor", u"Stena"])

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

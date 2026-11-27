# -*- coding: utf-8 -*-
"""Návod
Návod na používanie nástrojov DELTA_SK. Každý nástroj má vlastnú záložku.
Text záložiek je v priečinku 'obsah' (jeden .md súbor = jedna záložka).
"""
__title__ = u"Návod"
__doc__ = u"Návod na používanie nástrojov DELTA_SK."

import io
import os
import re

import clr
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from pyrevit import forms
from System.Windows import Thickness, FontWeights, TextWrapping
from System.Windows.Controls import (TabItem, ScrollViewer, StackPanel, TextBlock,
                                     DockPanel, Dock, ScrollBarVisibility)
from System.Windows.Documents import Run, Bold
from System.Windows.Media import FontFamily

PRIECINOK = os.path.dirname(__file__)
OBSAH = os.path.join(PRIECINOK, "obsah")


def pridaj_text(tb, text):
    """Vloží text do TextBlocku; **tučné** a `kód` sa naformátujú."""
    for cast in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not cast:
            continue
        if cast.startswith("**") and cast.endswith("**"):
            tb.Inlines.Add(Bold(Run(cast[2:-2])))
        elif cast.startswith("`") and cast.endswith("`"):
            run = Run(cast[1:-1])
            run.FontFamily = FontFamily("Consolas")
            tb.Inlines.Add(run)
        else:
            tb.Inlines.Add(Run(cast))


def blok(text, velkost=13, tucne=False, okraj=(0, 3, 0, 3)):
    tb = TextBlock()
    tb.TextWrapping = TextWrapping.Wrap
    tb.FontSize = velkost
    if tucne:
        tb.FontWeight = FontWeights.SemiBold
    tb.Margin = Thickness(*okraj)
    pridaj_text(tb, text)
    return tb


def odrazka(znak, text, odsadenie):
    riadok = DockPanel()
    riadok.Margin = Thickness(odsadenie, 1, 0, 1)
    z = TextBlock()
    z.Text = znak
    z.Width = 24
    z.FontSize = 13
    DockPanel.SetDock(z, Dock.Left)
    riadok.Children.Add(z)
    riadok.Children.Add(blok(text, okraj=(0, 0, 0, 0)))
    return riadok


def nacitaj(cesta):
    """Prevedie jednoduchý Markdown (# ## ### - 1.) na obsah záložky."""
    titul = os.path.splitext(os.path.basename(cesta))[0]
    panel = StackPanel()
    panel.Margin = Thickness(16, 10, 16, 16)
    with io.open(cesta, encoding="utf-8-sig") as f:
        riadky = f.read().splitlines()
    for riadok in riadky:
        if not riadok.strip():
            continue
        if riadok.startswith(u"# "):
            titul = riadok[2:].strip()
            continue
        if riadok.startswith(u"## "):
            panel.Children.Add(blok(riadok[3:].strip(), 17, True, (0, 16, 0, 4)))
            continue
        if riadok.startswith(u"### "):
            panel.Children.Add(blok(riadok[4:].strip(), 14, True, (0, 10, 0, 2)))
            continue
        text = riadok.lstrip()
        odsadenie = 6 + (len(riadok) - len(text)) * 10
        cislo = re.match(r"(\d+)\.\s+(.*)", text)
        if text.startswith(u"- "):
            panel.Children.Add(odrazka(u"•", text[2:], odsadenie))
        elif cislo:
            panel.Children.Add(odrazka(cislo.group(1) + u".", cislo.group(2), odsadenie))
        else:
            panel.Children.Add(blok(text, okraj=(0, 5, 0, 5)))
    return titul, panel


class NavodOkno(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)
        subory = sorted(f for f in os.listdir(OBSAH) if f.lower().endswith(".md"))
        for nazov in subory:
            try:
                titul, panel = nacitaj(os.path.join(OBSAH, nazov))
            except Exception as ex:
                titul, panel = nazov, StackPanel()
                panel.Children.Add(blok(u"Súbor sa nepodarilo načítať: {}".format(ex)))
            obal = ScrollViewer()
            obal.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
            obal.Content = panel
            zalozka = TabItem()
            zalozka.Header = titul
            zalozka.Content = obal
            self.tabs.Items.Add(zalozka)
        if self.tabs.Items.Count:
            self.tabs.SelectedIndex = 0
        self.close_b.Click += lambda s, e: self.Close()


if not os.path.isdir(OBSAH):
    forms.alert(u"Chýba priečinok s návodmi: {}".format(OBSAH), exitscript=True)

NavodOkno(os.path.join(PRIECINOK, "ui.xaml")).ShowDialog()

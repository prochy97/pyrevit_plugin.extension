# AutoJoin

Spája geometriu (Join Geometry) prvkov **len v aktívnom pohľade**, nikdy nie v celom modeli naraz.

## Postup

1. (Nepovinné) Označ v Revite prvky, ktoré sa **nemajú** joinovať.
2. Spusti **AutoJoin** a vyber kategórie.
3. Skontroluj súhrn (nové joiny, opravy, vynechané prvky) a potvrď.
4. Pozri report v okne pyRevit.

Celú operáciu vrátiš jedným **Ctrl+Z**.

## Priorita joinu

- **Konštrukčné prvky vždy režú nekonštrukčné.** Konštrukčný prvok = Structural Columns, Structural Framing, Structural Foundation a steny alebo stropy so zaškrtnutým Structural.
- Medzi konštrukčnými prvkami: **základy > stĺpy > trámy > stropy > steny**.
- Medzi nekonštrukčnými prvkami určí poradie Revit.
- Existujúce joiny sa menia len vtedy, keď nekonštrukčný prvok reže konštrukčný.

## Pravidlá

- Joinujú sa len prvky, ktorých objemy sa **reálne prekrývajú**. Prvky, ktoré sa len dotýkajú plochou (napr. stena na doske), sa nejoinujú.
- Automaticky sa vynechajú dvojice stena–stena (rieši ich Revit), prvky v skupinách a prvky obsadené iným používateľom.
- Neúspešný pár beh nezastaví, v reporte je aj s dôvodom.

## Podporované kategórie

Steny, stropy a podlahy, podhľady, schodiská, stĺpy, nosné stĺpy, základy, nosná kostra, strechy.

## Obmedzenia

- **Skupiny:** prvok v skupine sa nedá spojiť s prvkom mimo skupiny. Prvky v rovnakej skupine spoj ručne cez **Edit Group** (prenesie sa do všetkých inštancií).
- **Schodiská** Join Geometry väčšinou nepodporujú, v reporte sa zobrazia ako neúspešné.

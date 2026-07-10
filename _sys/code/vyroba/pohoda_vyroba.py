"""
pohoda_vyroba.py
================
Generátor XML pro import do agendy VÝROBA programu POHODA (schéma version_2).

Princip:
  - Sestaví dat:dataPack s jedním nebo více dat:dataPackItem.
  - Každý item = jedna výroba (vyr:vyroba) s hlavičkou a 1..N výrobky.
  - U výrobku stačí vazba na zásobu (IDS nebo ID z dbo.SKz) + množství.
    Složení (výrobní list) si POHODA dotáhne z karty výrobku a sama odepíše
    suroviny ze skladu. Komponenty se tedy do XML NEzadávají.

KRITICKÉ:
  - Kódování MUSÍ být windows-1250. Pohoda jiné odmítne nic neříkající chybou.
  - Pouze standardní knihovna (žádný pip), aby šlo spustit i na omezeném hostu.

Zdroj struktury: api.stormware.cz/pohoda/.../sklady/vyroba (schéma vyroba.xsd).

Testování PŘED nasazením formuláře:
  python pohoda_vyroba.py
  -> vytvoří 'vyroba_test.xml' -> ručně načti přes Soubor / Datová komunikace
     / XML import v Pohodě a ověř, že vznikne doklad a odepíšou se suroviny.
"""

from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# --- Jmenné prostory Pohoda XML (version_2) -------------------------------
NS_DAT = "http://www.stormware.cz/schema/version_2/data.xsd"
NS_TYP = "http://www.stormware.cz/schema/version_2/type.xsd"
NS_VYR = "http://www.stormware.cz/schema/version_2/vyroba.xsd"

ET.register_namespace("dat", NS_DAT)
ET.register_namespace("typ", NS_TYP)
ET.register_namespace("vyr", NS_VYR)


def _d(tag: str) -> str:
    return f"{{{NS_DAT}}}{tag}"


def _t(tag: str) -> str:
    return f"{{{NS_TYP}}}{tag}"


def _v(tag: str) -> str:
    return f"{{{NS_VYR}}}{tag}"


# --- Datové struktury vstupu ----------------------------------------------
@dataclass
class VyrobaItem:
    """Jeden vyráběný výrobek na dokladu."""
    mnozstvi: float                     # vyrobené množství (ks/l...)
    vyrobek_ids: str | None = None      # IDS z dbo.SKz (textový identifikátor)
    vyrobek_id: int | None = None       # ID z dbo.SKz (má vyšší prioritu)
    sklad_ids: str | None = None        # IDS skladu, kam se výrobek naskladní
    sklad_id: int | None = None         # ID skladu (vyšší priorita)

    def __post_init__(self):
        if self.vyrobek_ids is None and self.vyrobek_id is None:
            raise ValueError("VyrobaItem: nutné zadat vyrobek_ids nebo vyrobek_id")


@dataclass
class Vyroba:
    """Jeden výrobní doklad (hlavička + položky)."""
    datum: _dt.date
    polozky: list[VyrobaItem]
    text: str = "Výroba"                # SText dokladu
    stredisko_ids: str | None = None    # středisko (source i destination)
    stredisko_id: int | None = None
    cinnost_id: int | None = None       # volitelně
    zakazka_id: int | None = None       # volitelně
    note: str | None = None             # poznámka na dokladu
    int_note: str | None = "e-most"     # interní poznámka

    def __post_init__(self):
        if not self.polozky:
            raise ValueError("Vyroba: doklad musí mít aspoň jednu položku")


# --- Pomocné stavění elementů ---------------------------------------------
def _ref(parent: ET.Element, tag_qname: str, *, id_=None, ids=None) -> None:
    """Přidá pod parenta odkazový element s typ:id / typ:ids (id má prioritu)."""
    if id_ is None and ids is None:
        return
    ref = ET.SubElement(parent, tag_qname)
    if id_ is not None:
        ET.SubElement(ref, _t("id")).text = str(id_)
    if ids is not None:
        ET.SubElement(ref, _t("ids")).text = str(ids)


def _num(x: float) -> str:
    """Číslo s desetinnou tečkou (xsd:double), bez lokalizace."""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return repr(x) if isinstance(x, float) else str(x)


# --- Hlavní funkce ---------------------------------------------------------
def build_datapack(
    vyroby: list[Vyroba],
    *,
    ico: str = "26896869",
    application: str = "e-most",
    datapack_id: str = "VYR",
    note: str = "Import výroby z e-most",
) -> ET.ElementTree:
    """Sestaví celý dat:dataPack se všemi výrobními doklady."""
    dp = ET.Element(_d("dataPack"))
    dp.set("id", datapack_id)
    dp.set("ico", ico)
    dp.set("application", application)
    dp.set("version", "2.0")
    dp.set("note", note)

    for i, vyr in enumerate(vyroby, start=1):
        item = ET.SubElement(dp, _d("dataPackItem"))
        item.set("id", f"{datapack_id}{i:03d}")
        item.set("version", "2.0")

        vyroba = ET.SubElement(item, _v("vyroba"))
        vyroba.set("version", "2.0")

        # --- hlavička ---
        header = ET.SubElement(vyroba, _v("vyrobaHeader"))
        ET.SubElement(header, _v("date")).text = vyr.datum.isoformat()
        ET.SubElement(header, _v("text")).text = vyr.text
        _ref(header, _v("centreSource"),
             id_=vyr.stredisko_id, ids=vyr.stredisko_ids)
        _ref(header, _v("centreDestination"),
             id_=vyr.stredisko_id, ids=vyr.stredisko_ids)
        if vyr.cinnost_id is not None:
            _ref(header, _v("activity"), id_=vyr.cinnost_id)
        if vyr.zakazka_id is not None:
            _ref(header, _v("contract"), id_=vyr.zakazka_id)
        if vyr.note:
            ET.SubElement(header, _v("note")).text = vyr.note
        if vyr.int_note:
            ET.SubElement(header, _v("intNote")).text = vyr.int_note

        # --- detail (výrobky) ---
        detail = ET.SubElement(vyroba, _v("vyrobaDetail"))
        for p in vyr.polozky:
            vitem = ET.SubElement(detail, _v("vyrobaItem"))
            ET.SubElement(vitem, _v("quantity")).text = _num(p.mnozstvi)
            stock = ET.SubElement(vitem, _v("stockItem"))
            _ref(stock, _t("store"), id_=p.sklad_id, ids=p.sklad_ids)
            _ref(stock, _t("stockItem"), id_=p.vyrobek_id, ids=p.vyrobek_ids)

    tree = ET.ElementTree(dp)
    try:
        ET.indent(tree, space="  ")  # Python 3.9+: jen pro čitelnost
    except AttributeError:
        pass
    return tree


def write_xml(tree: ET.ElementTree, path: str) -> str:
    """Zapíše dataPack do souboru v kódování windows-1250."""
    tree.write(path, encoding="windows-1250", xml_declaration=True)
    return path


# --- Samostatný test --------------------------------------------------------
if __name__ == "__main__":
    # POZOR: stredisko_ids / sklad_ids / vyrobek_ids níže nahraď reálnými
    # hodnotami z tvé Pohody (sSTR.IDS, sSklad.IDS, SKz.IDS).
    ukazka = Vyroba(
        datum=_dt.date.today(),
        text="Výroba moštu – denní záznam",
        stredisko_ids="VYROBA",          # <- sSTR.IDS
        note="Načteno z e-most (test).",
        polozky=[
            VyrobaItem(mnozstvi=120, vyrobek_ids="M075", sklad_ids="HOTOVO"),
            VyrobaItem(mnozstvi=60,  vyrobek_ids="M025", sklad_ids="HOTOVO"),
        ],
    )
    tree = build_datapack([ukazka])
    out = write_xml(tree, "vyroba_test.xml")
    with open(out, "r", encoding="windows-1250") as f:
        print(f.read())
    print(f"\n>>> Zapsáno: {out}  (kódování windows-1250)")

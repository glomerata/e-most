"""
eshop_dostupnost.py
===================
Kontrola dostupnosti produktu v eshopu (Shoptet) proti realnym zasobam
v Pohode (view v_401 v _all). Report Pavle POUZE PRI ZMENE.

Zdroj eshop:  CSV export sablony 10 (windows-1250, oddelovac ';').
  URL s hashem -> secrets.toml [tasks.eshop_dostupnost] shoptet_products_url = "..."
Realny sklad: dbo.v_401_sklad_zasoby_dny (EAN, Stav, Zasoba_Dny_byRok).

"Nedostupny" = OR:
  - blokovano v eshopu           (productVisibility = 'blocked')
  - eshop hlasi neskladem        (availabilityOutOfStock != 'Skladem', neprazdne)
  - malo na realnem sklade       (Zasoba_Dny_byRok < zasoba_dny_min)
  - realny sklad <= 0
'hidden' NENI dostupnost (spousta produktu je skryta zamerne) -> jen informativne.

Chovani:
  - prvni beh -> jen ulozi baseline, mail NEposila,
  - dalsi behy -> mail jen kdyz nekdo nove zeskladem/zpet (nove | vyreseno),
  - always_send = true  -> ranni digest i beze zmeny.

Pozn.: Shoptet u nas nepocita kusy (stock=0), dostupnost je rizena rucne
labelem availabilityOutOfStock + viditelnosti; proto se Shoptet 'stock' ignoruje.
"""

from __future__ import annotations

import csv
import html as _html
import io

import requests

import base

VIEW_ZASOBY = "dbo.v_401_sklad_zasoby_dny"


def run(tcfg: dict) -> str:
    url = tcfg.get("shoptet_products_url")
    if not url:
        raise RuntimeError(
            "chybi shoptet_products_url (secrets.toml [tasks.eshop_dostupnost])")

    prijemci = _prijemci(tcfg)
    zasoba_min = int(tcfg.get("zasoba_dny_min", 25))
    always = bool(tcfg.get("always_send", False))
    predmet_base = tcfg.get("subject", "e-most: dostupnost eshop")
    log_id = tcfg.get("_log_id")

    # 1) realny sklad z v_401 (_all)
    sklad = _sklad_map()

    # 2) produkty z eshopu + vyhodnoceni
    produkty = _fetch_produkty(url)
    for p in produkty:
        p["nedostupny"], p["duvod"] = _vyhodnot(p, sklad, zasoba_min)

    # 3) diff proti ulozenemu stavu + zapis noveho
    prev, first_run = _nacti_prev()
    nove, vyreseno = _diff(produkty, prev)
    _uloz_stav(produkty)

    nedostupne = [p for p in produkty if p["nedostupny"]]
    nespar = sum(1 for p in produkty if p["stav_realny"] is None)
    base.log_text(
        "eshop_dostupnost",
        f"produktu={len(produkty)} nedostupnych={len(nedostupne)} "
        f"nove={len(nove)} vyreseno={len(vyreseno)} nespar_v401={nespar}",
        log_id=log_id)

    if first_run:
        return (f"prvni beh: baseline {len(produkty)} produktu ulozen, "
                f"mail neodeslan.")
    if not (nove or vyreseno or always):
        return f"beze zmeny ({len(nedostupne)} nedostupnych), mail neodeslan."

    telo = _sestav_html(produkty, nove, vyreseno, nedostupne, nespar)
    predmet = f"{predmet_base}: {len(nove)} nove, {len(vyreseno)} vyreseno"
    base.posli_mail(predmet, telo, prijemci, html=True)
    return (f"{len(nove)} nove nedostupnych, {len(vyreseno)} vyreseno, "
            f"mail na {', '.join(prijemci)}.")


# --- vstupy ---------------------------------------------------------------
def _prijemci(tcfg: dict) -> list[str]:
    # parametr 'mailto=...' prebiji config (stejne jako faktury_po_splatnosti)
    param = tcfg.get("_param", "")
    if param.startswith("mailto="):
        return [param.split("=", 1)[1].strip()]
    return tcfg.get("mail_to", [])


def _norm(s) -> str:
    if s is None:
        return ""
    return str(s).lstrip("$").lstrip("'").strip()


def _sklad_map() -> dict:
    """EAN -> (Stav, Zasoba_Dny_byRok) z v_401."""
    with base.db_all() as cn:
        cur = cn.cursor()
        cur.execute(
            f"SELECT EAN, CAST(Stav AS int) AS Stav, "
            f"CAST(Zasoba_Dny_byRok AS int) AS ZDny FROM {VIEW_ZASOBY}")
        return {_norm(r["EAN"]): (r["Stav"], r["ZDny"])
                for r in base.rows_to_dicts(cur)}


def _fetch_produkty(url: str) -> list[dict]:
    """Stahne CSV export (sablona 10, windows-1250) -> list dictu."""
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    data = r.content.decode("cp1250").lstrip("\ufeff")   # Shoptet CSV = cp1250
    out = []
    for row in csv.DictReader(io.StringIO(data), delimiter=";"):
        kod = _norm(row.get("code"))
        ean = _norm(row.get("ean"))
        if not kod and not ean:
            continue
        vidit = (row.get("productVisibility") or "").strip()
        out.append({
            "kod": kod,
            "ean": ean,
            "nazev": (row.get("name") or "").strip(),
            "viditelnost": vidit,
            "dostupnost": (row.get("availabilityOutOfStock") or "").strip(),
            "skryty": vidit == "hidden",
            "stav_realny": None,
            "zasoba_dny": None,
            "nedostupny": False,
            "duvod": None,
        })
    return out


def _vyhodnot(p: dict, sklad: dict, zasoba_min: int):
    stav, zdny = sklad.get(_norm(p["ean"]), (None, None))
    p["stav_realny"], p["zasoba_dny"] = stav, zdny
    dost = (p["dostupnost"] or "").strip().lower()
    # 1) rucne nastaveno jako nedostupne v eshopu
    if p["viditelnost"] == "blocked":
        return True, "blokovano v eshopu"
    if dost and dost != "skladem":
        return True, f"eshop: {p['dostupnost']}"     # Vyprodano / Momentalne nedostupne
    # 2) malo / nic na realnem sklade (i kdyz eshop hlasi Skladem)
    if zdny is not None and zdny < zasoba_min:
        return True, f"malo na sklade ({zdny} dni)"
    if stav is not None and stav <= 0:
        return True, "sklad Pohoda 0"
    return False, None


# --- stav / diff (core.eshop_produkt) -------------------------------------
def _nacti_prev():
    with base.db_most() as cn:
        cur = cn.cursor()
        cur.execute("SELECT kod, nedostupny FROM core.eshop_produkt")
        prev = {r[0]: bool(r[1]) for r in cur.fetchall()}
    return prev, (len(prev) == 0)


def _diff(produkty: list[dict], prev: dict):
    nove, vyreseno = [], []
    for p in produkty:
        was = prev.get(p["kod"], False)
        if p["nedostupny"] and not was:
            nove.append(p)
        elif was and not p["nedostupny"]:
            vyreseno.append(p)
    return nove, vyreseno


def _uloz_stav(produkty: list[dict]) -> None:
    """Maly katalog -> smaz + vloz v jedne transakci (last-write-wins)."""
    ted = base._now()
    with base.db_most() as cn:
        cur = cn.cursor()
        cur.execute("DELETE FROM core.eshop_produkt")
        cur.fast_executemany = True
        cur.executemany(
            "INSERT INTO core.eshop_produkt "
            "(kod, ean, nazev, viditelnost, dostupnost, stav_realny, "
            " zasoba_dny, nedostupny, duvod, ts_sync) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(p["kod"], p["ean"], p["nazev"], p["viditelnost"], p["dostupnost"],
              p["stav_realny"], p["zasoba_dny"], 1 if p["nedostupny"] else 0,
              p["duvod"], ted) for p in produkty])
        cn.commit()


# --- report (HTML, styl jako zasoby_min / faktury_po_splatnosti) ----------
def _sestav_html(produkty, nove, vyreseno, nedostupne, nespar) -> str:
    hlava = (f"<p>Kontrola dostupnosti eshop vs. sklad Pohoda — "
             f"produktů: {len(produkty)}, nedostupných: {len(nedostupne)}, "
             f"nespárováno s v_401: {nespar}</p>")
    return (
        hlava
        + _tabulka("Nově nedostupné", nove)
        + _tabulka("Znovu dostupné", vyreseno)
        + _tabulka("Aktuálně všechny nedostupné", nedostupne)
        + "<p style='color:#888;font-size:11px'>e-most / task eshop_dostupnost</p>")


def _tabulka(nadpis: str, radky: list[dict]) -> str:
    if not radky:
        return ""
    hlavicka = ["Kód", "EAN", "Název", "Viditelnost", "Eshop",
                "Sklad Pohoda", "Zásoba dní", "Důvod"]
    th = "".join(
        f"<th style='text-align:left;padding:4px 8px;"
        f"border-bottom:2px solid #ccc'>{h}</th>" for h in hlavicka)

    tr = ""
    for p in sorted(radky, key=lambda x: (x["zasoba_dny"] is None,
                                          x["zasoba_dny"] or 0)):
        duvod = p.get("duvod") or ""
        # malo/nic na sklade -> oranzova; nedostupne v eshopu -> cervena
        barva = "#e67e22" if ("sklade" in duvod or "Pohoda 0" in duvod) else "#c0392b"
        bunky = [p["kod"], p["ean"], p["nazev"], p["viditelnost"],
                 p["dostupnost"], _num(p["stav_realny"]),
                 _num(p["zasoba_dny"]), duvod]
        tds = "".join(
            f"<td style='padding:4px 8px;border-top:1px solid #eee'>{_esc(c)}</td>"
            for c in bunky)
        tr += f"<tr style='color:{barva}'>{tds}</tr>"

    return (f"<p><b>{nadpis}</b> ({len(radky)}):</p>"
            f"<table style='border-collapse:collapse;"
            f"font-family:sans-serif;font-size:13px'><tr>{th}</tr>{tr}</table>")


def _num(v) -> str:
    return "" if v is None else str(v)


def _esc(v) -> str:
    return _html.escape("" if v is None else str(v))

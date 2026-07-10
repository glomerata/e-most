"""
upominky.py
===========
Priprava upominek faktur v prodleni pro Pavlu ke kontrole a preposlani.

Postup:
  1. z ucetni DB nacte nevyrizene vydane faktury po splatnosti >= prah dni,
     seskupene po firme (ICO), vcetne e-mailu odberatele z Adresare.
  2. pro KAZDOU fakturu vytiskne sestavu 'Upominka' (report_id) do PDF
     pres mServer (prn:print umi jen jeden doklad na volani).
  3. PDF ulozi do  pdf_root / rada / cislo / upominka_datum_ico.pdf
  4. za KAZDOU firmu posle JEDEN mail Pavle:
       - prvni radek = e-maily dluznika (aby je Pavla zkopirovala a preposlala)
       - vsechna PDF firmy v priloze
     Maily NEJDOU zakaznikum automaticky - jen Pavle jako koncept.

Config [tasks.upominky]: report_id, dny_po_splatnosti, mail_to, subject, pdf_root
"""

from __future__ import annotations

import datetime as _dt
import os
from collections import OrderedDict
from decimal import Decimal

import base
import pohoda_print


def run(tcfg: dict) -> str:
    report_id = int(tcfg["report_id"])
    prah = int(tcfg.get("dny_po_splatnosti", 5))
    prijemci = _prijemci(tcfg)
    predmet = tcfg.get("subject", "Upomínka faktur v prodlení")
    pdf_root = tcfg["pdf_root"]
    series_len = int(tcfg.get("series_len", 4))

    firmy = _nacti_dluzniky(prah)
    if not firmy:
        return f"0 faktur po splatnosti >= {prah} dni, nic neodeslano."

    poslano = 0
    faktur_celkem = 0
    for ico, info in firmy.items():
        prilohy = []
        for f in info["faktury"]:
            pdf = pohoda_print.tisk_faktury_pdf(f["ID"], report_id)
            nazev = f"upominka_{_dnes()}_{ico or 'bezICO'}_{f['Cislo']}.pdf"
            _uloz_pdf(pdf_root, series_len, str(f["Cislo"]), nazev, pdf)
            prilohy.append((nazev, pdf))
            faktur_celkem += 1

        telo = _sestav_telo(info)
        base.posli_mail(f"{predmet}: {info['firma']}", telo, prijemci,
                        prilohy=prilohy)
        poslano += 1
        base.log_text("upominky",
                      f"{info['firma']} (ICO {ico}): {len(info['faktury'])} faktur, "
                      f"dluh {int(info['suma'])} Kc", log_id=tcfg.get("_log_id"))

    return (f"{poslano} firem / {faktur_celkem} upominek pripraveno, "
            f"mail(y) na {', '.join(prijemci)}")


def _prijemci(tcfg: dict) -> list:
    """Parametr 'mailto=...' prebiji config mail_to (pro test na sebe)."""
    param = tcfg.get("_param", "")
    if param.startswith("mailto="):
        return [param.split("=", 1)[1].strip()]
    return tcfg.get("mail_to", [])


def _nacti_dluzniky(prah: int) -> OrderedDict:
    """Nevyrizene vydane faktury po splatnosti >= prah, seskupene po ICO."""
    with base.db_ucetni() as cn:
        cur = cn.cursor()
        # RefAD -> vazba na Adresar kvuli e-mailu; LEFT JOIN, kdyby chybel
        cur.execute(
            "SELECT f.ID, f.Cislo, f.Firma, f.ICO, f.KcCelkem, f.KcLikv, "
            "       f.DatSplat, DATEDIFF(day, f.DatSplat, GETDATE()) AS poSplat, "
            "       a.Email AS email "
            "FROM Fa AS f "
            "LEFT JOIN AD AS a ON a.ID = f.RefAD "
            "WHERE f.KcLikv > 0 AND f.RelTpFak = 1 "
            "  AND DATEDIFF(day, f.DatSplat, GETDATE()) >= ? "
            "ORDER BY f.Firma, f.DatSplat ASC", prah)
        radky = base.rows_to_dicts(cur)

    firmy: OrderedDict = OrderedDict()
    for r in radky:
        ico = (r.get("ICO") or "").strip()
        klic = ico or (r.get("Firma") or "").strip()
        if klic not in firmy:
            firmy[klic] = {
                "firma": (r.get("Firma") or "").strip(),
                "ico": ico,
                "email": (r.get("email") or "").strip(),
                "faktury": [],
                "suma": Decimal(0),
            }
        firmy[klic]["faktury"].append(r)
        firmy[klic]["suma"] += r.get("KcLikv") or Decimal(0)
        # e-mail vezmi z prvni faktury, ktera ho ma
        if not firmy[klic]["email"] and r.get("email"):
            firmy[klic]["email"] = r["email"].strip()
    return firmy


def _sestav_telo(info: dict) -> str:
    maily = info["email"] or "(e-mail dlužníka nenalezen v Adresáři)"
    radky = [
        maily,                                   # 1. radek = maily dluznika (k preposlani)
        "",
        f"Dlužník: {info['firma']}"
        + (f" (IČ {info['ico']})" if info['ico'] else ""),
        f"Dluží celkem: {int(info['suma'])} Kč "
        f"({len(info['faktury'])} faktur po splatnosti)",
        "",
        "Faktury:",
    ]
    for f in info["faktury"]:
        radky.append(
            f"  {f['Cislo']}  splatnost {_datum(f['DatSplat'])}  "
            f"zbývá {int(f['KcLikv'] or 0)} Kč  "
            f"({abs(int(f.get('poSplat') or 0))} dní po splatnosti)")
    radky += [
        "",
        "V příloze upomínka(y) faktur v prodlení – ke kontrole a přeposlání.",
        "",
        "e-most / task upominky",
    ]
    return "\n".join(radky)


def _uloz_pdf(pdf_root: str, series_len: int, cislo: str,
              nazev: str, data: bytes) -> str:
    rada = cislo[:series_len]
    slozka = os.path.join(pdf_root, rada, cislo)
    os.makedirs(slozka, exist_ok=True)
    cesta = os.path.join(slozka, nazev)
    with open(cesta, "wb") as f:
        f.write(data)
    return cesta


def _dnes():
    return _dt.date.today().strftime("%Y%m%d")


def _datum(v):
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.strftime("%Y-%m-%d")
    return "" if v is None else str(v)

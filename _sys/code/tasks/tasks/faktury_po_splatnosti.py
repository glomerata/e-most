"""
faktury_po_splatnosti.py
========================
Prehled vydanych faktur po splatnosti (dluznici).
Prevzato z most_day; zapis do MariaDB nahrazen zapisem do core.hist (MSSQL).

  - cte z ucetni Pohoda DB (db_ucetni):  Fa, RelTpFak=1, KcLikv>0, DatSplat<dnes
  - suma po splatnosti -> core.hist (prm='sumLikv')
  - seznam dluzniku -> telo mailu
  - prijemce z configu [tasks.faktury_po_splatnosti].mail_to,
    override parametrem:  runner.py faktury_po_splatnosti "mailto=nekdo@x.cz"
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import base


def run(tcfg: dict) -> str:
    prijemci = _prijemci(tcfg)

    with base.db_ucetni() as cn:
        cur = cn.cursor()

        # 1) suma po splatnosti
        cur.execute(
            "SELECT SUM(f.KcLikv) FROM Fa AS f "
            "WHERE f.KcLikv > 0 AND f.DatSplat < GETDATE() AND f.RelTpFak = 1")
        suma = cur.fetchone()[0] or Decimal(0)

        # 2) seznam dluzniku
        cur.execute(
            "SELECT f.Cislo, LEFT(f.Firma, 24) AS Firma, f.KcCelkem, f.KcLikv, "
            "       f.DatSplat, DATEDIFF(day, GETDATE(), f.DatSplat) AS poSplatnosti "
            "FROM Fa AS f "
            "WHERE f.KcLikv > 0 AND f.DatSplat < GETDATE() AND f.RelTpFak = 1 "
            "ORDER BY f.DatSplat ASC")
        faktury = base.rows_to_dicts(cur)

    # 3) zapis sumy do core.hist (MSSQL, misto puvodni MariaDB)
    _zapis_hist("sumLikv", suma)

    # 4) mail (HTML)
    telo = _sestav_html(suma, faktury)
    predmet = tcfg.get("subject", "faktury po splatnosti")
    base.posli_mail(predmet, telo, prijemci, html=True)

    base.log_text("faktury_po_splatnosti",
                  f"suma={int(suma)} Kc, faktur={len(faktury)}, prijemci={prijemci}", log_id=tcfg.get("_log_id"))
    return f"{len(faktury)} faktur po splatnosti, suma {int(suma)} Kc, mail na {', '.join(prijemci)}"


def _prijemci(tcfg: dict) -> list[str]:
    # parametr 'mailto=...' prebiji config
    param = tcfg.get("_param", "")
    if param.startswith("mailto="):
        return [param.split("=", 1)[1].strip()]
    return tcfg.get("mail_to", [])


def _zapis_hist(prm: str, val) -> None:
    ted = base._now()
    with base.db_most() as cn:
        cur = cn.cursor()
        cur.execute(
            "INSERT INTO core.hist (dt, ts, prm, val) VALUES (?, ?, ?, ?)",
            _dt.date.today(), ted, prm, val)
        cn.commit()


def _sestav_html(suma, faktury: list[dict]) -> str:
    if not faktury:
        return "<p>Žádné faktury po splatnosti.</p>"

    hlavicka = ["Číslo", "Firma", "Kč celkem", "Kč zbývá",
                "Splatnost", "Po splatnosti"]
    zarovnani = ["left", "left", "right", "right", "left", "right"]
    th = "".join(
        f"<th style='text-align:{z};padding:4px 8px;"
        f"border-bottom:2px solid #ccc'>{h}</th>"
        for h, z in zip(hlavicka, zarovnani))

    tr = ""
    for f in faktury:
        dni = f.get("poSplatnosti")
        # cim dele po splatnosti, tim vyraznejsi: >30 cervena, jinak oranzova
        barva = "#c0392b" if (dni is not None and dni <= -30) else "#e67e22"
        bunky = [
            (str(f.get("Cislo", "")), "left"),
            (str(f.get("Firma", "")), "left"),
            (_num(f.get("KcCelkem")), "right"),
            (_num(f.get("KcLikv")), "right"),
            (_datum(f.get("DatSplat")), "left"),
            (_dni_text(dni), "right"),
        ]
        tds = "".join(
            f"<td style='padding:4px 8px;border-top:1px solid #eee;"
            f"text-align:{z}'>{c}</td>" for c, z in bunky)
        tr += f"<tr style='color:{barva}'>{tds}</tr>"

    return (
        f"<p>Suma po splatnosti: <b>{int(suma)} Kč</b> "
        f"({len(faktury)} faktur):</p>"
        f"<table style='border-collapse:collapse;"
        f"font-family:sans-serif;font-size:13px'>"
        f"<tr>{th}</tr>{tr}</table>"
        f"<p style='color:#888;font-size:11px'>e-most / task faktury_po_splatnosti</p>")


def _dni_text(dni):
    if dni is None:
        return ""
    # poSplatnosti = DATEDIFF(day, GETDATE(), DatSplat) -> zaporne = po splatnosti
    d = abs(int(dni))
    return f"{d} dní" if d else "dnes"


def _num(v):
    if isinstance(v, Decimal):
        return str(int(v))
    return "" if v is None else str(v)


def _datum(v):
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.strftime("%Y-%m-%d")
    return "" if v is None else str(v)

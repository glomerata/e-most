"""
zasoby_min.py
=============
Denni prehled: polozky pod minimem (pod_min = 1) z view v_451.
Cte VYHRADNE view - zadna logika navic v SQL ani tady.

Chovani:
  - jsou-li polozky pod minimem -> posle mail se soupisem,
  - nejsou-li -> mail NEposila (return "0 ...").
  Chces posilat i prazdny "vse OK"? Dej v configu posilat_prazdne = true.
"""

from __future__ import annotations

import base


def run(tcfg: dict) -> str:
    view = tcfg.get("view", "dbo.v_451_skz_obj_min_stav")
    prijemci = tcfg.get("mail_to", [])
    predmet = tcfg.get("subject", "e-most: zasoby pod minimem")
    posilat_prazdne = tcfg.get("posilat_prazdne", False)

    with base.db_all() as cn:
        cur = cn.cursor()
        # view je fixni nazev z configu (ne uzivatelsky vstup) -> f-string OK,
        # zadne parametry se sem nevkladaji.
        cur.execute(
            f"SELECT * FROM {view} WHERE pod_min = 1 "
            f"ORDER BY zasoba_dny ASC, disponibilni ASC")
        radky = base.rows_to_dicts(cur)

    if not radky and not posilat_prazdne:
        return "0 polozek pod minimem, mail neodeslan."

    telo = _sestav_html(radky)
    base.posli_mail(predmet, telo, prijemci, html=True)
    return f"{len(radky)} polozek pod minimem, mail odeslan na {', '.join(prijemci)}."


def _num(v):
    if v is None:
        return ""
    try:
        return f"{float(v):.0f}"
    except (TypeError, ValueError):
        return str(v)


def _sestav_html(radky: list[dict]) -> str:
    if not radky:
        return "<p>Vse v poradku, zadna polozka pod minimem.</p>"

    hlavicka = ["IDS", "Nazev", "Objem", "Stav", "Objednano",
                "Disponibilni", "Zasoba dni"]
    th = "".join(
        f"<th style='text-align:left;padding:4px 8px;"
        f"border-bottom:2px solid #ccc'>{h}</th>" for h in hlavicka)

    tr = ""
    for r in radky:
        disp = r.get("disponibilni") or 0
        barva = "#c0392b" if disp <= 0 else "#e67e22"   # zaporny cerveny, nizky oranzovy
        bunky = [
            r.get("IDS_n", "") or "",
            r.get("Nazev", "") or "",
            r.get("Objem", "") or "",
            _num(r.get("Stav")),
            _num(r.get("objednano")),
            _num(r.get("disponibilni")),
            _num(r.get("zasoba_dny")),
        ]
        tds = "".join(
            f"<td style='padding:4px 8px;border-top:1px solid #eee'>{c}</td>"
            for c in bunky)
        tr += f"<tr style='color:{barva}'>{tds}</tr>"

    return (
        f"<p>Polozky pod minimem ({len(radky)}):</p>"
        f"<table style='border-collapse:collapse;"
        f"font-family:sans-serif;font-size:13px'>"
        f"<tr>{th}</tr>{tr}</table>"
        f"<p style='color:#888;font-size:11px'>e-most / task zasoby_min</p>")

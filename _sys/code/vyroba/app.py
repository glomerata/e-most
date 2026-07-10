"""
app.py
======
Flask aplikace pro denní záznam výroby.

Tok dat:
  Formulář vyplníš -> POST /ulozit
    1) uloží kompletní deník do PostgreSQL (vč. šarží, DMT, refrakce, sanitace)
    2) vygeneruje Pohoda XML (jen výrobek + množství + sklad + středisko)
       do složky [vyroba] xml_out_dir, kterou Pohoda načte dávkově
  Seznam záznamů (/) umožní prohlížet a stáhnout XML znovu.

Běh (vývoj):    python app.py
Běh (produkce): waitress-serve --listen=0.0.0.0:8088 app:app
"""

from __future__ import annotations

import datetime as _dt
import os

from flask import (Flask, render_template, request, redirect,
                   url_for, flash, send_file, abort)

import db
from pohoda_vyroba import Vyroba, VyrobaItem, build_datapack, write_xml

app = Flask(__name__)
app.secret_key = os.environ.get("EMOST_SECRET", "vyroba-dev-key")

OBLASTI_SANITACE = [
    ("kompresor", "Kompresor"),
    ("triblok", "Triblok"),
    ("paster", "Paster"),
    ("vyrobni_prostory", "Výrobní prostory"),
]


def _f(name: str) -> str | None:
    v = request.form.get(name, "").strip()
    return v or None


def _num(name: str):
    v = _f(name)
    return float(v.replace(",", ".")) if v else None


def _int(name: str):
    v = _f(name)
    return int(v) if v else None


# --- seznam ---------------------------------------------------------------
@app.route("/")
def index():
    return render_template("seznam.html", zaznamy=db.nacti_zaznamy())


# --- nový záznam ----------------------------------------------------------
@app.route("/novy")
def novy():
    cfg = db.vyroba_cfg()
    return render_template(
        "vyroba_form.html",
        dnes=_dt.date.today().isoformat(),
        zamestnanci=db.cis_zamestnanci(),
        vyrobky=db.cis_vyrobky(),
        sklady=db.cis_sklady(),
        oblasti=OBLASTI_SANITACE,
        stredisko_ids=cfg.get("stredisko_ids", ""),
    )


# --- uložení --------------------------------------------------------------
@app.route("/ulozit", methods=["POST"])
def ulozit():
    # hlavička
    vedouci_id = _int("vedouci_id")
    zapsal_id = _int("zapsal_id")
    zam = {z["id"]: z["jmeno"] for z in db.cis_zamestnanci()}

    # položky (paralelní pole)
    ids_list = request.form.getlist("p_ids")
    polozky = []
    vyrobky_map = {v["ids"]: v for v in db.cis_vyrobky() if v["ids"]}
    for i, pid in enumerate(ids_list):
        pid = pid.strip()
        if not pid:
            continue
        mn = request.form.getlist("p_mnozstvi")[i].strip().replace(",", ".")
        if not mn:
            continue
        vinfo = vyrobky_map.get(pid, {})

        def g(field):
            vals = request.form.getlist(field)
            return vals[i].strip() if i < len(vals) and vals[i].strip() else None

        polozky.append({
            "skz_id": vinfo.get("id"),
            "ids": pid,
            "ean": vinfo.get("ean"),
            "nazev": vinfo.get("nazev"),
            "mj": vinfo.get("mj"),
            "mnozstvi": float(mn),
            "sklad_ids": g("p_sklad"),
            "dmt": g("p_dmt"),
            "vyrobni_cislo": g("p_vc"),
            "tisk_pocatek": int(g("p_tisk_od")) if g("p_tisk_od") else None,
            "tisk_konec": int(g("p_tisk_do")) if g("p_tisk_do") else None,
            "zdroj": g("p_zdroj"),
            "refrakce_bx": float(g("p_refrakce").replace(",", ".")) if g("p_refrakce") else None,
            "kyselost": float(g("p_kyselost").replace(",", ".")) if g("p_kyselost") else None,
            "poznamka": g("p_pozn"),
        })

    if not polozky:
        flash("Přidej aspoň jeden výrobek s množstvím.", "error")
        return redirect(url_for("novy"))

    # sanitace
    sanitace = []
    for klic, _label in OBLASTI_SANITACE:
        popis = _f(f"san_{klic}_popis")
        cas = _f(f"san_{klic}_cas")
        if popis or cas:
            sanitace.append({"oblast": klic, "popis": popis, "cas": cas})

    data = {
        "datum": _f("datum"),
        "vedouci_id": vedouci_id,
        "vedouci_jmeno": zam.get(vedouci_id),
        "pocatek": _f("pocatek_vyroby"),
        "konec": _f("konec_vyroby"),
        "zapsal_id": zapsal_id,
        "zapsal_jmeno": zam.get(zapsal_id),
        "poznamka": _f("poznamka"),
        "polozky": polozky,
        "sanitace": sanitace,
    }

    zid = db.uloz_zaznam(data)
    xml_path = _generuj_xml(zid, data)
    db.oznac_exportovano(zid, os.path.basename(xml_path))
    flash(f"Záznam #{zid} uložen. XML pro Pohodu: {os.path.basename(xml_path)}", "ok")
    return redirect(url_for("index"))


def _generuj_xml(zid: int, data: dict) -> str:
    cfg = db.vyroba_cfg()
    vyr = Vyroba(
        datum=_dt.date.fromisoformat(data["datum"]),
        text="Výroba – denní záznam",
        stredisko_ids=cfg.get("stredisko_ids") or None,
        note=f"e-most záznam #{zid}",
        polozky=[
            VyrobaItem(mnozstvi=p["mnozstvi"], vyrobek_ids=p["ids"],
                       sklad_ids=p.get("sklad_ids"))
            for p in data["polozky"]
        ],
    )
    tree = build_datapack([vyr], ico=cfg["ico"], datapack_id=f"VYR{zid}")
    out_dir = cfg["xml_out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    fname = f"vyroba_{zid}_{data['datum']}.xml"
    return write_xml(tree, os.path.join(out_dir, fname))


# --- stažení XML ----------------------------------------------------------
@app.route("/xml/<int:zid>")
def stahni_xml(zid: int):
    z = db.nacti_zaznam(zid)
    if not z or not z.get("pohoda_xml_soubor"):
        abort(404)
    path = os.path.join(db.vyroba_cfg()["xml_out_dir"], z["pohoda_xml_soubor"])
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True)


if __name__ == "__main__":
    c = db.vyroba_cfg()
    app.run(host="0.0.0.0", port=8088, debug=True)

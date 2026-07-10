"""
db.py
=====
Pristup k datum pro vyrobni formular. Cele na MSSQL (pyodbc):
  - cteni ciselniku z Pohody  (StwPh_..._2025)
  - zapis deniku do vlastni DB 'most', schema 'core'

Konfigurace: centralni config.toml, sekce [vyroba] (cesta relativne
..\\..\\config\\config.toml; lze prebit promennou EMOST_CONFIG).

Zasady (pouceni z most.py):
  - Zadne spojeni na urovni modulu.
  - Vzdy parametrizovane dotazy (zadne formatovani stringu do SQL).
  - Logika (tisk_rozdil, casova razitka) v Pythonu, ne v DB.
  - ts_* sloupce se plni ZONOVE (datetime.now().astimezone()), aby je
    Grafana zobrazila spravne (datetimeoffset na strane MSSQL).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import os

try:
    import tomllib                      # Python 3.11+
except ModuleNotFoundError:             # Python 3.10
    import tomli as tomllib

import struct

import pyodbc

# MSSQL datetimeoffset (ODBC typ -155) starsi pyodbc neumi cist sam.
# Zaregistrujeme prevod surovych bajtu na datetime se zonou.
_SQL_DATETIMEOFFSET = -155


def _handle_datetimeoffset(dto_value):
    # struktura: rok,mesic,den,hod,min,sec,nanosec,offset_hod,offset_min
    tup = struct.unpack("<6hI2h", dto_value)
    tz = _dt.timezone(_dt.timedelta(hours=tup[7], minutes=tup[8]))
    return _dt.datetime(tup[0], tup[1], tup[2], tup[3], tup[4], tup[5],
                        tup[6] // 1000, tz)


_DEFAULT_CFG = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.toml"))
_CFG_PATH = os.environ.get("EMOST_CONFIG", _DEFAULT_CFG)


def _now():
    """Aktualni cas SE ZONOU (offset) - pro datetimeoffset sloupce."""
    return _dt.datetime.now().astimezone()


def _cfg() -> dict:
    if not os.path.exists(_CFG_PATH):
        raise RuntimeError(f"Nenalezen config: {_CFG_PATH}")
    with open(_CFG_PATH, "rb") as f:
        data = tomllib.load(f)
    if "vyroba" not in data:
        raise RuntimeError("V config.toml chybi sekce [vyroba]")
    return data["vyroba"]


def vyroba_cfg() -> dict:
    """Skalarni nastaveni sekce [vyroba] (ico, xml_out_dir, stredisko_ids...)."""
    return {k: v for k, v in _cfg().items() if not isinstance(v, dict)}


# --- spojeni (MSSQL) -------------------------------------------------------
def _connect(database: str):
    c = _cfg()["mssql"]
    parts = [
        f"DRIVER={{{c['driver']}}}",
        f"SERVER={c['server']}",
        f"DATABASE={database}",
    ]
    if c.get("trusted", True):
        parts.append("Trusted_Connection=yes")
    else:
        parts += [f"UID={c['uid']}", f"PWD={c['pwd']}"]
    conn = pyodbc.connect(";".join(parts), timeout=10)
    conn.add_output_converter(_SQL_DATETIMEOFFSET, _handle_datetimeoffset)
    return conn


@contextlib.contextmanager
def pohoda():
    """Spojeni do Pohody (rocni DB) - jen cteni ciselniku."""
    conn = _connect(_cfg()["mssql"]["database"])
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def most():
    """Spojeni do vlastni DB 'most' - zapis deniku."""
    conn = _connect(_cfg()["mssql"].get("most_db", "most"))
    try:
        yield conn
    finally:
        conn.close()


# --- ciselniky (Pohoda, jen cteni) ----------------------------------------
def cis_zamestnanci() -> list[dict]:
    """Vedouci smeny / zapsal - jen zamestnanci strediska vyroba."""
    refstr = int(_cfg().get("zam_refstr", 1))
    with pohoda() as cn:
        cur = cn.cursor()
        cur.execute(
            "SELECT ID, Jmeno, Prijmeni FROM dbo.ZAM "
            "WHERE RefStr = ? ORDER BY Prijmeni, Jmeno", refstr)
        return [
            {"id": r.ID,
             "jmeno": f"{(r.Prijmeni or '').strip()} {(r.Jmeno or '').strip()}".strip()}
            for r in cur.fetchall()
        ]


def cis_vyrobky() -> list[dict]:
    """Vyrobky z dbo.SKz dle filtru v configu (default = maji vyrobni list)."""
    where = _cfg()["produkt_where"]
    with pohoda() as cn:
        cur = cn.cursor()
        cur.execute(
            f"SELECT z.ID, z.IDS, z.EAN, z.Nazev, z.MJ "
            f"FROM dbo.SKz z WHERE {where} ORDER BY z.Nazev")
        return [
            {"id": r.ID, "ids": (r.IDS or "").strip(), "ean": (r.EAN or "").strip(),
             "nazev": (r.Nazev or "").strip(), "mj": (r.MJ or "").strip()}
            for r in cur.fetchall()
        ]


def cis_sklady() -> list[dict]:
    with pohoda() as cn:
        cur = cn.cursor()
        cur.execute("SELECT ID, IDS, SText FROM dbo.sSklad ORDER BY IDS")
        return [{"id": r.ID, "ids": (r.IDS or "").strip(),
                 "nazev": (r.SText or "").strip()} for r in cur.fetchall()]


def cis_strediska() -> list[dict]:
    with pohoda() as cn:
        cur = cn.cursor()
        cur.execute("SELECT ID, IDS, SText FROM dbo.sSTR ORDER BY IDS")
        return [{"id": r.ID, "ids": (r.IDS or "").strip(),
                 "nazev": (r.SText or "").strip()} for r in cur.fetchall()]


# --- denik (MSSQL 'most', schema core) ------------------------------------
def uloz_zaznam(data: dict) -> int:
    """Ulozi hlavicku + polozky + operace. Vrati id zaznamu.
    Casova razitka (ts_*) a tisk_rozdil pocita Python (logika mimo DB)."""
    ted = _now()
    with most() as cn:
        cur = cn.cursor()
        cur.execute(
            """INSERT INTO core.vyroba
                 (dt_vyroba, vedouci_smeny_id, vedouci_smeny_jmeno,
                  pocatek, konec, zapsal_id, zapsal_jmeno,
                  ts_zapis, poznamka, pohoda_importovano,
                  ts_create, ts_update)
               OUTPUT INSERTED.id
               VALUES (?,?,?,?,?,?,?,?,?,0,?,?)""",
            data["datum"], data["vedouci_id"], data["vedouci_jmeno"],
            data["pocatek"], data["konec"], data["zapsal_id"],
            data["zapsal_jmeno"], ted, data["poznamka"], ted, ted)
        zid = cur.fetchone()[0]

        for i, p in enumerate(data["polozky"]):
            tisk_rozdil = None
            if p.get("tisk_pocatek") is not None and p.get("tisk_konec") is not None:
                tisk_rozdil = p["tisk_konec"] - p["tisk_pocatek"]
            cur.execute(
                """INSERT INTO core.vyroba_pol
                     (vyroba_id, skz_id, ids, ean, nazev, mj, mnozstvi,
                      sklad_ids, dt_dmt, vyrobni_cislo, tisk_pocatek, tisk_konec,
                      tisk_rozdil, zdroj, refrakce_bx, kyselost, poznamka, poradi)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                zid, p.get("skz_id"), p.get("ids"), p.get("ean"), p.get("nazev"),
                p.get("mj"), p["mnozstvi"], p.get("sklad_ids"), p.get("dmt"),
                p.get("vyrobni_cislo"), p.get("tisk_pocatek"), p.get("tisk_konec"),
                tisk_rozdil, p.get("zdroj"), p.get("refrakce_bx"),
                p.get("kyselost"), p.get("poznamka"), i)

        for s in data.get("sanitace", []):
            cur.execute(
                """INSERT INTO core.operace (vyroba_id, oblast, popis, cas)
                   VALUES (?,?,?,?)""",
                zid, s["oblast"], s.get("popis"), s.get("cas"))

        cn.commit()
        return zid


def oznac_exportovano(zid: int, xml_soubor: str) -> None:
    ted = _now()
    with most() as cn:
        cur = cn.cursor()
        cur.execute(
            "UPDATE core.vyroba SET pohoda_xml_soubor=?, ts_update=? WHERE id=?",
            xml_soubor, ted, zid)
        cn.commit()


def _rows_to_dicts(cur) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def nacti_zaznamy(limit: int = 50) -> list[dict]:
    with most() as cn:
        cur = cn.cursor()
        cur.execute(
            """SELECT TOP (?) z.*,
                      (SELECT count(*) FROM core.vyroba_pol p WHERE p.vyroba_id=z.id) AS pocet_vyrobku
               FROM core.vyroba z ORDER BY z.dt_vyroba DESC, z.id DESC""",
            limit)
        return _rows_to_dicts(cur)


def nacti_zaznam(zid: int) -> dict | None:
    with most() as cn:
        cur = cn.cursor()
        cur.execute("SELECT * FROM core.vyroba WHERE id=?", zid)
        rows = _rows_to_dicts(cur)
        if not rows:
            return None
        z = rows[0]
        cur.execute("SELECT * FROM core.vyroba_pol WHERE vyroba_id=? ORDER BY poradi", zid)
        z["polozky"] = _rows_to_dicts(cur)
        cur.execute("SELECT * FROM core.operace WHERE vyroba_id=?", zid)
        z["operace"] = _rows_to_dicts(cur)
        return z

"""
db.py
=====
Pristup k datum pro vyrobni formular.

Konfigurace: centralni config.toml (T:\\_system\\config\\config.toml),
sekce [vyroba]. Cesta se pocita relativne k tomuto souboru
(..\\..\\config\\config.toml); lze prebit promennou EMOST_CONFIG.

Zasady (pouceni z most.py):
  - Zadne spojeni na urovni modulu (neotvira se pri importu).
  - Vzdy parametrizovane dotazy (zadne formatovani stringu do SQL).
  - MSSQL slouzi jen pro CTENI ciselniku; zapis jde do PostgreSQL.
"""

from __future__ import annotations

import contextlib
import os

try:
    import tomllib                      # Python 3.11+
except ModuleNotFoundError:             # Python 3.10
    import tomli as tomllib

import pyodbc
import psycopg2
import psycopg2.extras

_DEFAULT_CFG = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.toml"))
_CFG_PATH = os.environ.get("EMOST_CONFIG", _DEFAULT_CFG)


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


# --- spojeni ---------------------------------------------------------------
@contextlib.contextmanager
def mssql():
    c = _cfg()["mssql"]
    parts = [
        f"DRIVER={{{c['driver']}}}",
        f"SERVER={c['server']}",
        f"DATABASE={c['database']}",
    ]
    if c.get("trusted", True):
        parts.append("Trusted_Connection=yes")
    else:
        parts += [f"UID={c['uid']}", f"PWD={c['pwd']}"]
    conn = pyodbc.connect(";".join(parts), timeout=10)
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def pg():
    c = _cfg()["postgres"]
    conn = psycopg2.connect(
        host=c["host"], port=int(c.get("port", 5432)), dbname=c["dbname"],
        user=c["user"], password=c.get("password", ""),
    )
    try:
        yield conn
    finally:
        conn.close()


# --- ciselniky (MSSQL, jen cteni) -----------------------------------------
def cis_zamestnanci() -> list[dict]:
    """Vedouci smeny / zapsal - jen zamestnanci strediska vyroba."""
    refstr = int(_cfg().get("zam_refstr", 1))
    with mssql() as cn:
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
    with mssql() as cn:
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
    with mssql() as cn:
        cur = cn.cursor()
        cur.execute("SELECT ID, IDS, SText FROM dbo.sSklad ORDER BY IDS")
        return [{"id": r.ID, "ids": (r.IDS or "").strip(),
                 "nazev": (r.SText or "").strip()} for r in cur.fetchall()]


def cis_strediska() -> list[dict]:
    with mssql() as cn:
        cur = cn.cursor()
        cur.execute("SELECT ID, IDS, SText FROM dbo.sSTR ORDER BY IDS")
        return [{"id": r.ID, "ids": (r.IDS or "").strip(),
                 "nazev": (r.SText or "").strip()} for r in cur.fetchall()]


# --- denik (PostgreSQL) ----------------------------------------------------
def uloz_zaznam(data: dict) -> int:
    """Ulozi hlavicku + polozky + sanitaci. Vrati id zaznamu."""
    with pg() as cn:
        cur = cn.cursor()
        cur.execute(
            """INSERT INTO core.vyroba_zaznam
                 (datum, vedouci_smeny_id, vedouci_smeny_jmeno,
                  pocatek_vyroby, konec_vyroby,
                  zapsal_id, zapsal_jmeno, poznamka)
               VALUES (%(datum)s, %(vedouci_id)s, %(vedouci_jmeno)s,
                       %(pocatek)s, %(konec)s,
                       %(zapsal_id)s, %(zapsal_jmeno)s, %(poznamka)s)
               RETURNING id""", data)
        zid = cur.fetchone()[0]

        for i, p in enumerate(data["polozky"]):
            p2 = dict(p, zaznam_id=zid, poradi=i)
            cur.execute(
                """INSERT INTO core.vyroba_polozka
                     (zaznam_id, skz_id, ids, ean, nazev, mj, mnozstvi,
                      sklad_ids, dmt, vyrobni_cislo, tisk_pocatek, tisk_konec,
                      zdroj, refrakce_bx, kyselost, poznamka, poradi)
                   VALUES (%(zaznam_id)s, %(skz_id)s, %(ids)s, %(ean)s,
                           %(nazev)s, %(mj)s, %(mnozstvi)s, %(sklad_ids)s,
                           %(dmt)s, %(vyrobni_cislo)s, %(tisk_pocatek)s,
                           %(tisk_konec)s, %(zdroj)s, %(refrakce_bx)s,
                           %(kyselost)s, %(poznamka)s, %(poradi)s)""", p2)

        for s in data.get("sanitace", []):
            cur.execute(
                """INSERT INTO core.vyroba_sanitace (zaznam_id, oblast, popis, cas)
                   VALUES (%s, %s, %s, %s)""",
                (zid, s["oblast"], s.get("popis"), s.get("cas")))

        cn.commit()
        return zid


def oznac_exportovano(zid: int, xml_soubor: str) -> None:
    with pg() as cn:
        cur = cn.cursor()
        cur.execute(
            "UPDATE core.vyroba_zaznam SET pohoda_xml_soubor=%s WHERE id=%s",
            (xml_soubor, zid))
        cn.commit()


def nacti_zaznamy(limit: int = 50) -> list[dict]:
    with pg() as cn:
        cur = cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT z.*,
                      (SELECT count(*) FROM core.vyroba_polozka p WHERE p.zaznam_id=z.id) AS pocet_vyrobku
               FROM core.vyroba_zaznam z ORDER BY z.datum DESC, z.id DESC LIMIT %s""",
            (limit,))
        return cur.fetchall()


def nacti_zaznam(zid: int) -> dict | None:
    with pg() as cn:
        cur = cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM core.vyroba_zaznam WHERE id=%s", (zid,))
        z = cur.fetchone()
        if not z:
            return None
        cur.execute("SELECT * FROM core.vyroba_polozka WHERE zaznam_id=%s ORDER BY poradi", (zid,))
        z["polozky"] = cur.fetchall()
        cur.execute("SELECT * FROM core.vyroba_sanitace WHERE zaznam_id=%s", (zid,))
        z["sanitace"] = cur.fetchall()
        return z

"""
base.py
=======
Spolecna infrastruktura pro ulohy (tasks): config, DB spojeni, mail, log.

Zasady (stejne jako vyroba/db.py):
  - Zadne spojeni na urovni modulu.
  - Vzdy parametrizovane dotazy (zadne formatovani stringu do SQL).
  - Logika v Pythonu, ne v DB.
  - ts_* sloupce se plni ZONOVE (datetime.now().astimezone()) kvuli Grafane.
  - config.toml = source of truth; secrets.toml (mimo git) doplni hesla.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import os
import smtplib
import struct
from email.mime.text import MIMEText

try:
    import tomllib                      # Python 3.11+
except ModuleNotFoundError:             # Python 3.10
    import tomli as tomllib

import pyodbc

# MSSQL datetimeoffset (ODBC typ -155) starsi pyodbc neumi cist sam.
_SQL_DATETIMEOFFSET = -155


def _handle_datetimeoffset(dto_value):
    tup = struct.unpack("<6hI2h", dto_value)
    tz = _dt.timezone(_dt.timedelta(hours=tup[7], minutes=tup[8]))
    return _dt.datetime(tup[0], tup[1], tup[2], tup[3], tup[4], tup[5],
                        tup[6] // 1000, tz)


_DEFAULT_CFG = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.toml"))
_CFG_PATH = os.environ.get("EMOST_CONFIG", _DEFAULT_CFG)
_SECRETS_PATH = os.path.join(os.path.dirname(_CFG_PATH), "secrets.toml")


def _now():
    """Aktualni cas SE ZONOU (offset) - pro datetimeoffset sloupce."""
    return _dt.datetime.now().astimezone()


def _merge(base_d: dict, extra: dict) -> None:
    """Rekurzivne vlije extra do base (secrets doplni/prebiji config)."""
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base_d.get(k), dict):
            _merge(base_d[k], v)
        else:
            base_d[k] = v


_CFG_CACHE = None


def cfg() -> dict:
    """Cely config.toml slity se secrets.toml (hesla). Cachovano."""
    global _CFG_CACHE
    if _CFG_CACHE is None:
        if not os.path.exists(_CFG_PATH):
            raise RuntimeError(f"Nenalezen config: {_CFG_PATH}")
        with open(_CFG_PATH, "rb") as f:
            data = tomllib.load(f)
        if os.path.exists(_SECRETS_PATH):
            with open(_SECRETS_PATH, "rb") as f:
                _merge(data, tomllib.load(f))
        _CFG_CACHE = data
    return _CFG_CACHE


# --- DB spojeni (MSSQL) ---------------------------------------------------
def _connect(database: str):
    c = cfg()["mssql"]
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
def db_all():
    """Spojeni do cross-year 'all' vrstvy (v_451 ...). Jen cteni."""
    conn = _connect(cfg()["mssql"]["db_all"])
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def db_most():
    """Spojeni do vlastni DB 'most' (core.config, core.task, core.task_log)."""
    conn = _connect(cfg()["mssql"].get("db_most", "most"))
    try:
        yield conn
    finally:
        conn.close()


def rows_to_dicts(cur) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# --- mail (interni relay zodiac, port 25, bez auth) -----------------------
def posli_mail(predmet: str, telo: str, prijemci, html: bool = False) -> None:
    s = cfg()["smtp"]
    if isinstance(prijemci, str):
        prijemci = [prijemci]
    prijemci = [p for p in prijemci if p]
    if not prijemci:
        raise RuntimeError("posli_mail: prazdny seznam prijemcu")

    msg = MIMEText(telo, "html" if html else "plain", "utf-8")
    msg["Subject"] = predmet
    msg["From"] = s["from"]
    msg["To"] = ", ".join(prijemci)

    srv = smtplib.SMTP(s["host"], int(s.get("port", 25)), timeout=15)
    try:
        if s.get("auth", False):          # default false = zodiac relay bez prihlaseni
            srv.starttls()
            srv.login(s["user"], s["password"])
        srv.sendmail(s["from"], prijemci, msg.as_string())
    finally:
        srv.quit()


# --- log uloh (core.task_log + core.task v DB most) -----------------------
def log_start(task_klic: str) -> int:
    ted = _now()
    with db_most() as cn:
        cur = cn.cursor()
        cur.execute(
            """INSERT INTO core.task_log (task_klic, ts_start, stav)
               OUTPUT INSERTED.id VALUES (?, ?, 'bezi')""",
            task_klic, ted)
        rid = cur.fetchone()[0]
        cn.commit()
        return rid


def log_konec(log_id: int, task_klic: str, stav: str, zprava: str = None) -> None:
    ted = _now()
    with db_most() as cn:
        cur = cn.cursor()
        cur.execute(
            "UPDATE core.task_log SET ts_konec=?, stav=?, zprava=? WHERE id=?",
            ted, stav, zprava, log_id)
        # prehled v core.task (upsert bez MERGE kvuli jednoduchosti)
        n = cur.execute(
            "UPDATE core.task SET ts_posledni=?, stav=? WHERE klic=?",
            ted, stav, task_klic).rowcount
        if n == 0:
            cur.execute(
                """INSERT INTO core.task (klic, aktivni, ts_posledni, stav, ts_sync)
                   VALUES (?, 1, ?, ?, ?)""",
                task_klic, ted, stav, ted)
        cn.commit()

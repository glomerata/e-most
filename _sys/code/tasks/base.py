"""
base.py
=======
Spolecna infrastruktura pro ulohy (tasks): config, DB spojeni, mail,
DB log (core.task_log) i textovy .log soubor.

Zasady (stejne jako vyroba/db.py):
  - Zadne spojeni na urovni modulu.
  - Vzdy parametrizovane dotazy.
  - Logika v Pythonu, ne v DB.
  - ts_* sloupce zonove (datetime.now().astimezone()) kvuli Grafane.
  - config = source of truth (emost_config: config.toml + secrets.toml).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import os
import smtplib
import struct
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pyodbc

import emost_config

_SQL_DATETIMEOFFSET = -155


def _handle_datetimeoffset(dto_value):
    tup = struct.unpack("<6hI2h", dto_value)
    tz = _dt.timezone(_dt.timedelta(hours=tup[7], minutes=tup[8]))
    return _dt.datetime(tup[0], tup[1], tup[2], tup[3], tup[4], tup[5],
                        tup[6] // 1000, tz)


def _now():
    """Aktualni cas SE ZONOU (offset) - pro datetimeoffset i .log."""
    return _dt.datetime.now().astimezone()


_CFG_CACHE = None


def cfg() -> dict:
    global _CFG_CACHE
    if _CFG_CACHE is None:
        _CFG_CACHE = emost_config.load()
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
    """Cross-year 'all' vrstva (v_451 ...). Jen cteni."""
    conn = _connect(cfg()["mssql"]["db_all"])
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def db_most():
    """Vlastni DB 'most' (core.config / task / task_log)."""
    conn = _connect(cfg()["mssql"].get("db_most", "most"))
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def db_ucetni():
    """Aktualni ucetni Pohoda DB (StwPh_..._<rok_ucto_db>). Jen cteni."""
    conn = _connect(emost_config.db_ucetni(cfg()))
    try:
        yield conn
    finally:
        conn.close()


def rows_to_dicts(cur) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# --- mail (interni relay zodiac, port 25, bez auth) -----------------------
def posli_mail(predmet: str, telo: str, prijemci, html: bool = False,
               prilohy: list = None) -> None:
    """Odesle mail. prilohy = seznam (nazev_souboru, bajty[, mime_subtype])."""
    s = cfg()["smtp"]
    if isinstance(prijemci, str):
        prijemci = [prijemci]
    prijemci = [p for p in prijemci if p]
    if not prijemci:
        raise RuntimeError("posli_mail: prazdny seznam prijemcu")

    telo_part = MIMEText(telo, "html" if html else "plain", "utf-8")

    if prilohy:
        msg = MIMEMultipart()
        msg.attach(telo_part)
        for p in prilohy:
            nazev, data = p[0], p[1]
            subtype = p[2] if len(p) > 2 else "pdf"
            att = MIMEApplication(data, _subtype=subtype)
            att.add_header("Content-Disposition", "attachment", filename=nazev)
            msg.attach(att)
    else:
        msg = telo_part

    msg["Subject"] = predmet
    msg["From"] = s["from"]
    msg["To"] = ", ".join(prijemci)

    srv = smtplib.SMTP(s["host"], int(s.get("port", 25)), timeout=15)
    try:
        if s.get("auth", False):
            srv.starttls()
            srv.login(s["user"], s["password"])
        srv.sendmail(s["from"], prijemci, msg.as_string())
    finally:
        srv.quit()


# --- textovy log (.log soubor) --------------------------------------------
def _log_path() -> str:
    base = cfg()["storage"]["base"]
    d = os.path.join(base, "_sys", "logs")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "tasks.log")


def log_text(task_klic: str, text: str, log_id=None, uroven: str = "info") -> None:
    """Zapise radek do tasks.log:  ts | task | log_id=.. | uroven | text"""
    radek = (f"{_now().isoformat(timespec='seconds')} | {task_klic} | "
             f"log_id={log_id if log_id is not None else '-'} | "
             f"{uroven} | {text}\n")
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(radek)
    except Exception:
        pass  # log nesmi shodit ulohu


# --- log behu uloh (core.task_log + core.task) ----------------------------
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
        n = cur.execute(
            "UPDATE core.task SET ts_posledni=?, stav=? WHERE klic=?",
            ted, stav, task_klic).rowcount
        if n == 0:
            cur.execute(
                """INSERT INTO core.task (klic, aktivni, ts_posledni, stav, ts_sync)
                   VALUES (?, 1, ?, ?, ?)""",
                task_klic, ted, stav, ted)
        cn.commit()


# --- core.config helpers (pro scheduler: posledni beh) --------------------
def config_get(klic: str, default=None):
    with db_most() as cn:
        cur = cn.cursor()
        cur.execute("SELECT hodnota FROM core.config WHERE klic=?", klic)
        r = cur.fetchone()
        return r[0] if r else default


def config_set(klic: str, hodnota: str, typ: str = "str", popis: str = None) -> None:
    ted = _now()
    with db_most() as cn:
        cur = cn.cursor()
        n = cur.execute(
            "UPDATE core.config SET hodnota=?, typ=?, ts_sync=? WHERE klic=?",
            hodnota, typ, ted, klic).rowcount
        if n == 0:
            cur.execute(
                """INSERT INTO core.config (klic, hodnota, typ, popis, ts_sync)
                   VALUES (?, ?, ?, ?, ?)""",
                klic, hodnota, typ, popis, ted)
        cn.commit()

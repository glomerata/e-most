"""
scheduler.py
============
Planovac uloh. Task Scheduler spousti kazdych [scheduler].beh_minut:
    python runner.py scheduler

Precte core.task (aktivni=1, ma cron), a spusti kazdou ulohu, jejiz
cronovy cas padl do OKNA <posledni beh scheduleru; ted>. Diky oknu se
nic nepromeska, i kdyz scheduler bezi treba po 10 minutach a cron je
'2 6 * * *'.

Posledni beh se drzi v core.config (klic 'scheduler.ts_posledni').

Cron: standardni 5 poli  "min hod den mesic den_v_tydnu"
  pole: *  |  cislo  |  seznam 6,18  |  krok */2  |  rozsah 1-5  (i kombinace 1-5/2)
"""

from __future__ import annotations

import datetime as _dt
import importlib
import subprocess
import sys

import base


# --- cron parser (bez zavislosti) -----------------------------------------
def _pole(vyraz: str, low: int, high: int) -> set[int]:
    """Rozbali jedno cron pole na mnozinu povolenych hodnot."""
    out: set[int] = set()
    for cast in vyraz.split(","):
        krok = 1
        if "/" in cast:
            cast, k = cast.split("/", 1)
            krok = int(k)
        if cast == "*":
            a, b = low, high
        elif "-" in cast:
            a, b = (int(x) for x in cast.split("-", 1))
        else:
            a = b = int(cast)
        out.update(range(a, b + 1, krok))
    return out


def cron_sedi(cron: str, t: _dt.datetime) -> bool:
    """Odpovida cas t danemu cron vyrazu (5 poli)?"""
    p = cron.split()
    if len(p) != 5:
        raise ValueError(f"cron musi mit 5 poli, ma {len(p)}: '{cron}'")
    mi, ho, den, mes, dow = p
    # cron: nedele = 0 i 7; Python weekday(): po=0..ne=6  -> prevod na 0=ne..6=so
    py_dow = (t.weekday() + 1) % 7
    return (
        t.minute in _pole(mi, 0, 59) and
        t.hour in _pole(ho, 0, 23) and
        t.day in _pole(den, 1, 31) and
        t.month in _pole(mes, 1, 12) and
        (py_dow in _pole(dow, 0, 6) or (7 in _pole(dow, 0, 7) and py_dow == 0))
    )


def _casy_v_okne(od: _dt.datetime, do: _dt.datetime):
    """Generuje kazdou celou minutu v intervalu (od, do]."""
    t = od.replace(second=0, microsecond=0) + _dt.timedelta(minutes=1)
    while t <= do:
        yield t
        t += _dt.timedelta(minutes=1)


# --- hlavni beh -----------------------------------------------------------
_KEY_POSLEDNI = "scheduler.ts_posledni"


def run(tcfg: dict) -> str:
    ted = base._now()

    # okno: od posledniho behu (nebo poslednich beh_minut) do ted
    posl_raw = base.config_get(_KEY_POSLEDNI)
    if posl_raw:
        od = _dt.datetime.fromisoformat(posl_raw)
    else:
        minut = int(base.cfg().get("scheduler", {}).get("beh_minut", 10))
        od = ted - _dt.timedelta(minutes=minut)

    # nacti aktivni ulohy s cronem
    with base.db_most() as cn:
        cur = cn.cursor()
        cur.execute(
            "SELECT klic, cron, parametry FROM core.task "
            "WHERE aktivni = 1 AND cron IS NOT NULL AND LEN(cron) > 0")
        ulohy = base.rows_to_dicts(cur)

    spustene = []
    for u in ulohy:
        klic, cron = u["klic"], u["cron"]
        try:
            if any(cron_sedi(cron, t) for t in _casy_v_okne(od, ted)):
                _spust_ulohu(klic, u.get("parametry"))
                spustene.append(klic)
        except ValueError as e:
            base.log_text("scheduler", f"chybny cron u '{klic}': {e}",
                          uroven="error")

    # posun okna az PO uspesnem projiti (at se nic nepromeska pri padu)
    base.config_set(_KEY_POSLEDNI, ted.isoformat(), "str",
                    "posledni beh scheduleru (okno cronu)")

    zprava = (f"okno {od.strftime('%H:%M')}-{ted.strftime('%H:%M')}, "
              f"spusteno: {', '.join(spustene) if spustene else '(nic)'}")
    base.log_text("scheduler", zprava)
    return zprava


def _spust_ulohu(klic: str, parametry: str | None) -> None:
    """Spusti ulohu ve VLASTNIM procesu (izolace: pad jedne nezhodi scheduler)."""
    cmd = [sys.executable, "runner.py", klic]
    if parametry:
        cmd.append(parametry)
    subprocess.run(cmd, cwd=_this_dir(), check=False)


def _this_dir() -> str:
    import os
    return os.path.dirname(os.path.abspath(__file__))

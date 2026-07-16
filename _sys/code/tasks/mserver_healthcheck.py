"""
mserver_healthcheck.py
======================
Hlida, ze POHODA mServer bezi. Kdyz neodpovida na /status, zkusi ho
nahodit pres  Pohoda.exe /http restart "<nazev>"  a upozorni admina.

Vhodne pustit schedulerem casteji (napr. kazdych 10 min) PRED ulohami,
ktere mServer potrebuji (upominky, tisk).

Config [tasks.mserver_healthcheck]:
    pohoda_exe   = cesta k Pohoda.exe
    mserver_name = nazev mServeru (napr. "mServer1")
    restart      = true/false  (smi se pokusit o restart?)
"""

from __future__ import annotations

import subprocess

import base
import pohoda_print


def run(tcfg: dict) -> str:
    stav = pohoda_print.zjisti_status()
    if stav in ("idle", "working"):
        return f"mServer OK (status={stav})"

    # neodpovida
    base.log_text("mserver_healthcheck", "mServer neodpovida na /status",
                  uroven="warn")

    if not tcfg.get("restart", True):
        _upozorni(f"mServer neodpovida (status={stav}), restart vypnut v configu.")
        return "mServer neodpovida, restart vypnut."

    exe = tcfg.get("pohoda_exe")
    name = tcfg.get("mserver_name")
    if not exe or not name:
        raise RuntimeError("chybi pohoda_exe nebo mserver_name v configu")

    # Pohoda.exe /http restart "mServer1"
    subprocess.run([exe, "/http", "restart", name], check=False, timeout=60)

    # over znovu
    stav2 = pohoda_print.zjisti_status(timeout=10)
    if stav2 in ("idle", "working"):
        base.log_text("mserver_healthcheck",
                      f"mServer po restartu OK (status={stav2})")
        return f"mServer byl restartovan, ted OK (status={stav2})"

    _upozorni("mServer neodpovida ani po pokusu o restart!")
    return "mServer neodpovida ani po restartu (admin upozornen)."


def _upozorni(text: str) -> None:
    try:
        admin = base.cfg()["org"]["email_org_admin"]
        base.posli_mail("e-most: mServer nedostupny", text, admin)
    except Exception:
        pass

"""
runner.py
=========
Vstupni bod pro ulohy.  Task Scheduler vola:  python runner.py <uloha> [parametr]

Jednotne: kontrola enabled, log do core.task_log/core.task, oseterni chyb
+ notifikace adminovi (org.email_org_admin) pri padu.
Kazdy modul ulohy ma  run(tcfg: dict) -> str.
Volitelny druhy argument (parametr) se predava jako tcfg['_param'].
"""

from __future__ import annotations

import importlib
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import base  # noqa: E402

_TASKS = {
    "scheduler":      "tasks.scheduler",
    "zasoby_min":     "tasks.zasoby_min",
    "banka_import":   "tasks.banka_import",
    "skeny_kontrola": "tasks.skeny_kontrola",
    "faktury_po_splatnosti": "tasks.faktury_po_splatnosti",
}


def spust(task_klic: str, param: str | None = None) -> int:
    if task_klic not in _TASKS:
        print(f"Neznama uloha: {task_klic}. Dostupne: {', '.join(_TASKS)}")
        return 2

    tcfg = dict(base.cfg().get("tasks", {}).get(task_klic, {}))
    # scheduler nema sekci [tasks.scheduler]; bere se z [scheduler] a je vzdy povoleny
    if task_klic == "scheduler":
        tcfg.setdefault("enabled", True)
    if not tcfg.get("enabled", False):
        print(f"Uloha '{task_klic}' je v configu vypnuta (enabled=false).")
        return 0
    if param is not None:
        tcfg["_param"] = param

    modul = importlib.import_module(_TASKS[task_klic])
    log_id = base.log_start(task_klic)
    try:
        zprava = modul.run(tcfg)
        base.log_konec(log_id, task_klic, "ok", zprava)
        print(f"[{task_klic}] OK: {zprava}")
        return 0
    except Exception:
        chyba = traceback.format_exc()
        base.log_konec(log_id, task_klic, "chyba", chyba[-3000:])
        base.log_text(task_klic, chyba.splitlines()[-1], log_id, "error")
        print(f"[{task_klic}] CHYBA:\n{chyba}", file=sys.stderr)
        _notifikuj_admina(task_klic, chyba)
        return 1


def _notifikuj_admina(task_klic: str, chyba: str) -> None:
    try:
        admin = base.cfg()["org"]["email_org_admin"]
        base.posli_mail(
            f"e-most CHYBA: uloha {task_klic}",
            f"Uloha '{task_klic}' spadla:\n\n{chyba}",
            admin)
    except Exception:
        print("Navic se nepodarilo poslat notifikaci adminovi.", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Pouziti: python runner.py <uloha> [parametr]")
        print(f"Dostupne: {', '.join(_TASKS)}")
        sys.exit(2)
    _param = sys.argv[2] if len(sys.argv) > 2 else None
    sys.exit(spust(sys.argv[1], _param))

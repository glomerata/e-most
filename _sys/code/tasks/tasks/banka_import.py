"""
banka_import.py
===============
Stazeni POSLEDNIHO oficialniho FIO vypisu (lastStatement) jako PDF.
Prevzato z overeneho kodu; mail vypusten (jen stazeni + ulozeni).

  - fio_token  -> secrets.toml  [tasks.banka_import] fio_token = "..."
  - cilova slozka a ucet -> config.toml [tasks.banka_import]
      banka_dir = "{doc_root}\\Účetnictví\\Banka\\{rok}\\FIO_CZK"  (rozbaleno loaderem)
      ucet      = "2500697325"
  - nazev souboru: fio_<ucet>_<rok>_<id>.pdf   (rok = kalendarni)
"""

from __future__ import annotations

import os

import requests

import base


def run(tcfg: dict) -> str:
    token = tcfg.get("fio_token")
    if not token:
        raise RuntimeError("chybi fio_token (secrets.toml [tasks.banka_import])")

    banka_dir = tcfg["banka_dir"]        # uz rozbaleny {doc_root}/{rok}
    ucet = tcfg.get("ucet", "ucet")
    rok = base.cfg()["org"]["pohoda"]["rok"]

    # 1) posledni vypis: vrati "rok,cislo"
    r = requests.get(
        f"https://fioapi.fio.cz/v1/rest/lastStatement/{token}/statement",
        timeout=30)
    r.raise_for_status()
    st_rok, st_cislo = (x.strip() for x in r.text.split(",")[:2])

    # 2) stazeni PDF
    r = requests.get(
        f"https://fioapi.fio.cz/v1/rest/by-id/{token}/{st_rok}/{st_cislo}/transactions.pdf",
        timeout=60)
    r.raise_for_status()

    os.makedirs(banka_dir, exist_ok=True)
    nazev = f"fio_{ucet}_{rok}_{st_cislo}.pdf"
    cesta = os.path.join(banka_dir, nazev)
    with open(cesta, "wb") as f:
        f.write(r.content)

    base.log_text("banka_import", f"stazen vypis {st_rok}/{st_cislo} -> {cesta}")
    return f"FIO vypis {st_rok}/{st_cislo} ulozen: {nazev}"

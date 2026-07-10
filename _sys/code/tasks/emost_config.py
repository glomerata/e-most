"""
emost_config.py
===============
Jediny loader configu pro cely e-most. Nacte config.toml, slije se
secrets.toml (hesla, mimo git) a rozbali placeholdery:

    {base}      -> [storage].base
    {doc_root}  -> [org.pohoda].doc_root
    {rok}       -> [org.pohoda].rok         (KALENDARNI rok, napr. 2026)

Pozn.: nazev ucetni DB ({rok_ucto_db}) se NEinterpoluje jako placeholder,
sklada se v kode (db_ucetni()), aby bylo jasne, ze jde o jiny rok.
"""

from __future__ import annotations

import os

try:
    import tomllib                      # Python 3.11+
except ModuleNotFoundError:             # Python 3.10
    import tomli as tomllib


def _merge(base_d: dict, extra: dict) -> None:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base_d.get(k), dict):
            _merge(base_d[k], v)
        else:
            base_d[k] = v


def _expand(value, mapa: dict):
    if isinstance(value, str):
        for ph, val in mapa.items():
            value = value.replace(ph, val)
        return value
    if isinstance(value, dict):
        return {k: _expand(v, mapa) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, mapa) for v in value]
    return value


def load(cfg_path: str | None = None) -> dict:
    """Nacte a vrati kompletni config (config.toml + secrets.toml, placeholdery)."""
    if cfg_path is None:
        cfg_path = os.environ.get(
            "EMOST_CONFIG",
            os.path.normpath(os.path.join(
                os.path.dirname(__file__), "..", "..", "config", "config.toml")))

    if not os.path.exists(cfg_path):
        raise RuntimeError(f"Nenalezen config: {cfg_path}")
    with open(cfg_path, "rb") as f:
        data = tomllib.load(f)

    secrets_path = os.path.join(os.path.dirname(cfg_path), "secrets.toml")
    if os.path.exists(secrets_path):
        with open(secrets_path, "rb") as f:
            _merge(data, tomllib.load(f))

    # placeholdery (poradi nezalezi, klice se neprekryvaji)
    mapa = {}
    if "storage" in data and "base" in data["storage"]:
        mapa["{base}"] = data["storage"]["base"]
    poh = data.get("org", {}).get("pohoda", {})
    if "doc_root" in poh:
        mapa["{doc_root}"] = poh["doc_root"]
    if "rok" in poh:
        mapa["{rok}"] = str(poh["rok"])

    return _expand(data, mapa)


def db_ucetni(cfg: dict) -> str:
    """Nazev aktualni ucetni DB: db_prefix + '_' + rok_ucto_db  (napr. StwPh_26896869_2025)."""
    poh = cfg["org"]["pohoda"]
    return f"{poh['db_prefix']}_{poh['rok_ucto_db']}"

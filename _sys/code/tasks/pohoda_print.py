"""
pohoda_print.py
===============
Tisk tiskove sestavy POHODA do PDF pres mServer (XML komunikace).

Overeno empiricky (Release 14301): prn:print/ftr:filter povoluje pro tisk
JEN JEDNO ftr:id (jeden doklad na volani). Vice dokladu = vice volani.

XML se stavi pres ElementTree (bezpecne escapovani & < > v nazvech firem),
odpoved se kontroluje na state="ok" a PDF se dekoduje z base64 (rdc:data).

Config [mserver]:  url
Secrets [mserver]: user, pwd  (STW-Authorization Basic se spocita v kode)
"""

from __future__ import annotations

import base64
import xml.etree.ElementTree as ET

import requests

import base

# jmenne prostory (jen ty potrebne pro tisk)
_NS = {
    "dat": "http://www.stormware.cz/schema/version_2/data.xsd",
    "prn": "http://www.stormware.cz/schema/version_2/print.xsd",
    "ftr": "http://www.stormware.cz/schema/version_2/filter.xsd",
    "rsp": "http://www.stormware.cz/schema/version_2/response.xsd",
    "rdc": "http://www.stormware.cz/schema/version_2/documentresponse.xsd",
}


def _q(prefix: str, tag: str) -> str:
    return f"{{{_NS[prefix]}}}{tag}"


def _auth_header() -> str:
    """Slozi 'Basic <base64(user:pwd)>' z [mserver] user/pwd (secrets)."""
    m = base.cfg()["mserver"]
    # zpetna kompatibilita: kdyby nekdo mel primo hotovy 'auth' base64
    if m.get("auth"):
        return f"Basic {m['auth']}"
    user = m["user"]
    pwd = m.get("pwd", "")
    token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def sestav_request(fa_id: int, report_id: int, ico: str,
                   file_name: str = "tisk.pdf") -> bytes:
    """Postavi XML pozadavek na tisk jednoho dokladu do PDF (base64 v odpovedi)."""
    for p, uri in _NS.items():
        ET.register_namespace(p, uri)

    dp = ET.Element(_q("dat", "dataPack"), {
        "id": "print", "ico": ico, "application": "e-most",
        "version": "2.0", "note": "e-most tisk sestavy",
    })
    item = ET.SubElement(dp, _q("dat", "dataPackItem"),
                         {"id": "item1", "version": "2.0"})
    prnt = ET.SubElement(item, _q("prn", "print"), {"version": "1.0"})

    rec = ET.SubElement(prnt, _q("prn", "record"), {"agenda": "vydane_faktury"})
    flt = ET.SubElement(rec, _q("ftr", "filter"))
    ET.SubElement(flt, _q("ftr", "id")).text = str(fa_id)   # JEN JEDNO id

    ps = ET.SubElement(prnt, _q("prn", "printerSettings"))
    rep = ET.SubElement(ps, _q("prn", "report"))
    ET.SubElement(rep, _q("prn", "id")).text = str(report_id)
    pdf = ET.SubElement(ps, _q("prn", "pdf"))
    ET.SubElement(pdf, _q("prn", "fileName")).text = file_name
    bd = ET.SubElement(pdf, _q("prn", "binaryData"))
    ET.SubElement(bd, _q("prn", "responseXml")).text = "true"

    xml = ET.tostring(dp, encoding="windows-1250", xml_declaration=True)
    return xml


def tisk_faktury_pdf(fa_id: int, report_id: int) -> bytes:
    """Vytiskne sestavu report_id pro fakturu fa_id -> vrati PDF (bytes)."""
    m = base.cfg()["mserver"]
    ico = base.cfg()["org"]["ico"]

    xml = sestav_request(fa_id, report_id, ico)
    r = requests.post(
        m["url"],
        data=xml,
        headers={
            "STW-Authorization": _auth_header(),
            "Content-Type": "application/xml",
        },
        timeout=30,
    )
    r.raise_for_status()

    root = ET.fromstring(r.content)          # odpoved je Windows-1250, ET si poradi dle deklarace
    # kontrola state na obou urovnich
    if root.get("state") != "ok":
        raise RuntimeError(f"mServer chyba (pack): {root.get('note')}")
    for item in root.iter(_q("rsp", "responsePackItem")):
        if item.get("state") != "ok":
            raise RuntimeError(f"mServer chyba (item): {item.get('note')}")

    # base64 PDF v rdc:data
    for el in root.iter():
        if el.tag.endswith("}data") and el.text and len(el.text) > 100:
            return base64.b64decode("".join(el.text.split()))
    raise RuntimeError("V odpovedi mServeru nebylo PDF (rdc:data).")


def status_url() -> str:
    """Z [mserver].url (.../xml) odvodi .../status."""
    url = base.cfg()["mserver"]["url"]
    return url.rsplit("/", 1)[0] + "/status"


def zjisti_status(timeout: int = 5) -> str | None:
    """Vrati stav mServeru ('idle'/'working') nebo None kdyz neodpovida."""
    try:
        r = requests.get(status_url(), timeout=timeout)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for el in root.iter():
            if el.tag.endswith("}status") or el.tag == "status":
                return (el.text or "").strip()
        # fallback: bez namespace
        el = root.find("status")
        return el.text.strip() if el is not None and el.text else "unknown"
    except Exception:
        return None

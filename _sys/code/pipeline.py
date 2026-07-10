#!/usr/bin/env python3
# =====================================================================
#  e-most : pipeline.py  (modul scan, level 1.7)
#
#  Co to dela:
#    1) Vezme PDF z in/scan/one a in/scan/multi.
#    2) Pocka, az je soubor kompletni (stabilni velikost).
#    3) OCR praveho horniho rohu prvni stranky -> cislo dodaciho listu.
#    4) Kontrola: cislo z rohu se shoduje s cislem u "Dodaci list c."? (kdyz lze)
#    5) Sestavi cilovou cestu  <root>\<rada>\<cislo>\  a ulozi tam PDF.
#       - kdyz rada neexistuje a allow_new_series=false -> failed.
#    6) Cokoli nejiste -> _system\failed + zaznam v logu. Nikdy nehada.
#
#  Spousteni: Windows Task Scheduler kazde 1-2 min, ucet Hostetin.
#             Skript probehne, zpracuje co je, skonci.
#
#  Zavislosti (Win11 .132):
#    pip install pytesseract pdf2image pypdf Pillow
#    + Tesseract-OCR (UB Mannheim) vcetne ceskeho jazyka 'ces'
#    + Poppler (kvuli pdf2image)
#  Cesty k Tesseractu a Poppleru se nastavuji v config.toml.
# =====================================================================

from __future__ import annotations
import sys
import re
import time
import shutil
import logging
import argparse
from pathlib import Path
from datetime import datetime

# tomllib je v Pythonu od 3.11; pro starsi fallback na tomli
try:
    import tomllib  # py >= 3.11
except ModuleNotFoundError:
    import tomli as tomllib  # pip install tomli

import fitz  # PyMuPDF: prevod PDF -> obrazek bez externiho Poppleru
from PIL import Image
import pytesseract


# ---------------------------------------------------------------------
#  Nacteni konfigurace + rozvinuti {base} v cestach
# ---------------------------------------------------------------------
def load_config(config_path: Path) -> dict:
    with open(config_path, "rb") as f:
        cfg = tomllib.load(f)

    base = cfg["storage"]["base"]

    def expand(value):
        if isinstance(value, str):
            return value.replace("{base}", base)
        if isinstance(value, dict):
            return {k: expand(v) for k, v in value.items()}
        if isinstance(value, list):
            return [expand(v) for v in value]
        return value

    return expand(cfg)


# ---------------------------------------------------------------------
#  Logging do souboru i na konzoli
# ---------------------------------------------------------------------
def setup_logging(cfg: dict) -> logging.Logger:
    log_file = Path(cfg["logging"]["file"])
    log_file.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, cfg["logging"]["level"].upper(), logging.INFO)

    logger = logging.getLogger("e-most.scan")
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


# ---------------------------------------------------------------------
#  Soubor je "stabilni" = jeho velikost se po stable_seconds nemeni.
#  Brani sebrani PDF, ktere skener jeste dopisuje pres SMB.
# ---------------------------------------------------------------------
def is_stable(path: Path, stable_seconds: int) -> bool:
    try:
        s1 = path.stat().st_size
    except FileNotFoundError:
        return False
    time.sleep(stable_seconds)
    try:
        s2 = path.stat().st_size
    except FileNotFoundError:
        return False
    return s1 == s2 and s1 > 0


# ---------------------------------------------------------------------
#  Render jedne stranky PDF na PIL obrazek pres PyMuPDF (zadny Poppler).
#  page_index je 0-based. Vraci PIL.Image nebo None.
# ---------------------------------------------------------------------
def render_page(doc, page_index: int, dpi: int):
    if page_index < 0 or page_index >= doc.page_count:
        return None
    page = doc.load_page(page_index)
    zoom = dpi / 72.0  # PDF zaklad je 72 dpi
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


# ---------------------------------------------------------------------
#  Z obrazku jedne stranky vytahni cislo dodaciho listu.
#  Vraci (cislo | None, debug_text). Nikdy nehada - pri nejistote None.
# ---------------------------------------------------------------------
def number_from_image(img, ocr: dict, logger, tag: str) -> tuple[str | None, str]:
    w, h = img.size
    rx = re.compile(ocr["doc_number_regex"])

    # 1) orez praveho horniho rohu: "DODACI LIST c. XXXXXXX"
    crop = img.crop((
        int(w * ocr["crop_left"]),
        int(h * ocr["crop_top"]),
        int(w * ocr["crop_right"]),
        int(h * ocr["crop_bottom"]),
    ))
    txt_corner = pytesseract.image_to_string(crop, lang=ocr["lang"])
    corner_nums = rx.findall(txt_corner)

    # 2) OCR cele strany pro kontrolu
    txt_full = pytesseract.image_to_string(img, lang=ocr["lang"])
    full_nums = rx.findall(txt_full)

    debug = f"corner={corner_nums} full={full_nums}"
    logger.debug(f"{tag}: {debug}")
    logger.debug(f"{tag} corner_text={txt_corner!r}")

    if not corner_nums:
        return None, debug

    candidate = corner_nums[0]

    # vic ruznych cisel v rohu -> podezrele
    if len(set(corner_nums)) > 1:
        logger.warning(f"{tag}: vice ruznych cisel v rohu {set(corner_nums)} -> nejiste")
        return None, debug

    # cislo z rohu se nevyskytuje jinde na strance -> nejiste
    if full_nums and candidate not in full_nums:
        logger.warning(f"{tag}: cislo z rohu {candidate} neodpovida {set(full_nums)} -> nejiste")
        return None, debug

    return candidate, debug


def set_tesseract(ocr: dict):
    if ocr.get("tesseract_cmd"):
        pytesseract.pytesseract.tesseract_cmd = ocr["tesseract_cmd"]


# ---------------------------------------------------------------------
#  Sestaveni cilove slozky a ulozeni PDF.
#  Vraci True pri uspechu, False kdyz se ma soubor poslat do failed.
#  src_pdf  = hotovy PDF k ulozeni (cely sken NEBO jedna vyrizla strana)
#  stem     = zaklad nazvu vystupu (napr. timestamp originalu, u stran + _p2)
# ---------------------------------------------------------------------
def file_into_target(src_pdf: Path, doc_number: str, stem: str,
                     cfg: dict, logger) -> bool:
    tgt = cfg["target"]
    root = Path(tgt["root"])
    series = doc_number[: tgt["series_len"]]          # 2621121 -> 2621
    series_dir = root / series
    doc_dir = series_dir / doc_number                  # ...\2621\2621121

    if not root.exists():
        logger.error(f"Cilovy root neexistuje: {root} (zkontroluj pripojeni H:)")
        return False

    # kdyz rada neexistuje a nesmime ji zakladat -> nejiste, do failed
    if not series_dir.exists() and not tgt["allow_new_series"]:
        logger.warning(f"rada {series} neexistuje a allow_new_series=false "
                       f"(cislo precteno: {doc_number}) -> failed")
        return False

    # zaloz radu (kdyz povoleno) i slozku dokladu
    doc_dir.mkdir(parents=True, exist_ok=True)

    # cilovy nazev: cislo + stem, at se neprepise pri opakovani
    target_file = doc_dir / f"{doc_number}_{stem}.pdf"
    if target_file.exists():
        i = 1
        while (doc_dir / f"{doc_number}_{stem}_{i}.pdf").exists():
            i += 1
        target_file = doc_dir / f"{doc_number}_{stem}_{i}.pdf"

    shutil.copy2(src_pdf, target_file)
    logger.info(f"OK -> {target_file}")
    return True


# ---------------------------------------------------------------------
#  Presun do failed (s casovym razitkem, at se nic neprepise)
# ---------------------------------------------------------------------
def move_to_failed(pdf_path: Path, cfg: dict, logger, reason: str):
    failed = Path(cfg["paths"]["failed"])
    failed.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    dest = failed / f"{pdf_path.stem}__{stamp}.pdf"
    shutil.move(str(pdf_path), str(dest))
    # poznamka proc
    (failed / f"{dest.stem}.txt").write_text(
        f"{datetime.now():%Y-%m-%d %H:%M:%S}\nzdroj: {pdf_path}\nduvod: {reason}\n",
        encoding="utf-8",
    )
    logger.warning(f"FAILED {pdf_path.name} -> {dest.name} ({reason})")


# ---------------------------------------------------------------------
#  Rezim SINGLE: cely PDF = jeden doklad. Cislo z prvni strany.
# ---------------------------------------------------------------------
def process_single(pdf: Path, cfg: dict, logger):
    ocr = cfg["ocr"]
    set_tesseract(ocr)
    doc = fitz.open(str(pdf))
    try:
        img = render_page(doc, 0, ocr["dpi"])
        if img is None:
            move_to_failed(pdf, cfg, logger, "prazdne PDF / nelze nacist 1. stranu")
            return
        number, debug = number_from_image(img, ocr, logger, pdf.name)
    finally:
        doc.close()

    if not number:
        move_to_failed(pdf, cfg, logger, f"cislo neprecteno ({debug})")
        return

    ok = file_into_target(pdf, number, pdf.stem, cfg, logger)
    if ok:
        if cfg["behavior"]["delete_source_after"]:
            try:
                pdf.unlink()
            except OSError as e:
                logger.warning(f"  nelze smazat zdroj {pdf.name}: {e}")
    else:
        move_to_failed(pdf, cfg, logger,
                       f"cislo {number} precteno, ale cilovou slozku nelze pouzit")


# ---------------------------------------------------------------------
#  Rezim SPLIT: co strana, to doklad. Kazda strana se OCR-uje zvlast,
#  vyrizne se do samostatneho 1-stranoveho PDF a zaradi dle sveho cisla.
#  Strana bez ctelneho cisla -> ta jedna strana do failed (ne cely sken).
# ---------------------------------------------------------------------
def process_split(pdf: Path, cfg: dict, logger):
    import tempfile
    from pypdf import PdfReader, PdfWriter

    ocr = cfg["ocr"]
    set_tesseract(ocr)

    doc = fitz.open(str(pdf))
    n = doc.page_count
    logger.info(f"  {pdf.name}: {n} stran k rozdeleni")

    reader = PdfReader(str(pdf))
    any_failed = False
    ok_count = 0

    tmpdir = Path(tempfile.mkdtemp(prefix="emost_split_"))
    try:
        for i in range(n):
            tag = f"{pdf.name}#str{i+1}"
            img = render_page(doc, i, ocr["dpi"])
            if img is None:
                logger.warning(f"  {tag}: nelze vykreslit -> preskoceno")
                any_failed = True
                continue

            number, debug = number_from_image(img, ocr, logger, tag)

            # vyrizni tuto stranu do samostatneho 1-stranoveho PDF
            writer = PdfWriter()
            writer.add_page(reader.pages[i])
            page_pdf = tmpdir / f"{pdf.stem}_p{i+1}.pdf"
            with open(page_pdf, "wb") as f:
                writer.write(f)

            if not number:
                # jen tato strana do failed, zbytek pokracuje
                move_to_failed(page_pdf, cfg, logger,
                               f"strana {i+1} z {pdf.name}: cislo neprecteno ({debug})")
                any_failed = True
                continue

            stem = f"{pdf.stem}_p{i+1}"
            ok = file_into_target(page_pdf, number, stem, cfg, logger)
            if ok:
                ok_count += 1
            else:
                move_to_failed(page_pdf, cfg, logger,
                               f"strana {i+1}: cislo {number} precteno, slozku nelze pouzit")
                any_failed = True
    finally:
        doc.close()

    logger.info(f"  {pdf.name}: zarazeno stran {ok_count}/{n}"
                + (" (nektere do failed)" if any_failed else ""))

    # zdrojovy vicestranovy sken smazat jen kdyz vse proslo a je to povoleno
    if cfg["behavior"]["delete_source_after"] and not any_failed:
        try:
            pdf.unlink()
        except OSError as e:
            logger.warning(f"  nelze smazat zdroj {pdf.name}: {e}")
    elif any_failed:
        logger.info(f"  {pdf.name}: ponechan ve vstupu (nektere strany selhaly) "
                    f"- po kontrole smaz rucne")

    # uklid docasnych vyriznutych stran, ktere se uspesne zaradily/presunuly
    try:
        for leftover in tmpdir.iterdir():
            leftover.unlink()
        tmpdir.rmdir()
    except OSError:
        pass


# ---------------------------------------------------------------------
#  Zpracovani jedne vstupni slozky v danem rezimu ("single" | "split")
# ---------------------------------------------------------------------
def process_inbox(inbox: Path, mode: str, cfg: dict, logger):
    if not inbox.exists():
        logger.debug(f"Vstupni slozka neexistuje (preskoceno): {inbox}")
        return

    exts = {e.lower() for e in cfg["behavior"]["extensions"]}
    files = [p for p in inbox.iterdir()
             if p.is_file() and p.suffix.lower() in exts]

    if not files:
        logger.debug(f"{inbox}: nic ke zpracovani")
        return

    for pdf in sorted(files):
        logger.info(f"Zpracovavam: {pdf.name}  (rezim {mode})")

        if not is_stable(pdf, cfg["behavior"]["stable_seconds"]):
            logger.info(f"  {pdf.name}: jeste se zapisuje, nechavam na priste")
            continue

        try:
            if mode == "split":
                process_split(pdf, cfg, logger)
            else:
                process_single(pdf, cfg, logger)
        except Exception as e:
            move_to_failed(pdf, cfg, logger, f"chyba zpracovani: {e}")


# ---------------------------------------------------------------------
#  main
# ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="e-most scan pipeline (level 1.7)")
    ap.add_argument("--config", default=None, help="cesta ke config.toml")
    ap.add_argument("--once", action="store_true",
                    help="zpracovat jednou a skoncit (vychozi chovani pro Task Scheduler)")
    args = ap.parse_args()

    # config: bud zadany, nebo vedle skriptu v ..\config\config.toml
    if args.config:
        config_path = Path(args.config)
    else:
        config_path = Path(__file__).resolve().parent.parent / "config" / "config.toml"

    if not config_path.exists():
        print(f"CHYBA: config nenalezen: {config_path}", file=sys.stderr)
        sys.exit(1)

    cfg = load_config(config_path)
    logger = setup_logging(cfg)
    logger.info("=== e-most scan pipeline start ===")

    process_inbox(Path(cfg["scan"]["inbox_single"]), "single", cfg, logger)
    process_inbox(Path(cfg["scan"]["inbox_split"]),  "split",  cfg, logger)

    logger.info("=== hotovo ===")


if __name__ == "__main__":
    main()

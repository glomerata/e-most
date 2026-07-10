-- =====================================================================
-- e-most : databáze "most", schéma "core"
-- =====================================================================
-- Jedno sdílené schéma 'core' pro celý systém. Doména je v prefixu
-- názvu tabulky (vyroba_*, později iot_*). Tento skript je idempotentní
-- a self-sufficient: lze pustit znovu i samostatně po modulech.
--
-- Spuštění:  psql -U emost -d most -f schema_vyroba.sql
--
-- Pozn. k řazení češtiny: PostgreSQL na Windows defaultně nemusí řadit
-- ř/š/č správně. V dotazech, kde záleží, použij  ORDER BY x COLLATE "cs-CZ".
-- =====================================================================

-- --- bootstrap schématu core (sdílené napříč moduly) -----------------
CREATE SCHEMA IF NOT EXISTS core;
SET search_path TO core, public;

-- generická funkce pro automatické updated_at (využije i další moduly)
CREATE OR REPLACE FUNCTION core.touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =====================================================================
-- MODUL: VÝROBA (provozní/kvalitativní deník)
-- =====================================================================
-- Ukládá VŠE, co Pohoda agenda Výroba neumí: sledovatelnost (šarže, DMT,
-- zdroj), kvalitu (refrakce, kyselost) a hygienu (sanitace, údržba).
-- Do Pohody jde přes XML jen naskladnění (výrobek + množství + středisko).
--
-- ZAM.id a SKz.ID jsou odkazy do MSSQL (Pohoda) – držíme je jako prosté
-- int hodnoty (cross-database FK nelze), spolu se snapshotem názvu/IDS.

-- --- denní záznam (hlavička) -----------------------------------------
CREATE TABLE IF NOT EXISTS core.vyroba_zaznam (
    id                  bigserial PRIMARY KEY,
    datum               date        NOT NULL,
    vedouci_smeny_id    int,                 -- ZAM.ID (Pohoda)
    vedouci_smeny_jmeno text,                -- snapshot jména
    pocatek_vyroby      time,
    konec_vyroby        time,
    zapsal_id           int,                 -- ZAM.ID
    zapsal_jmeno        text,
    cas_zapisu          timestamptz NOT NULL DEFAULT now(),
    poznamka            text,
    -- vazba na export do Pohody
    pohoda_xml_soubor   text,
    pohoda_importovano  boolean     NOT NULL DEFAULT false,
    pohoda_import_cas   timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_vyroba_zaznam_datum
    ON core.vyroba_zaznam (datum);

-- --- vyráběné výrobky (položky) --------------------------------------
CREATE TABLE IF NOT EXISTS core.vyroba_polozka (
    id              bigserial PRIMARY KEY,
    zaznam_id       bigint  NOT NULL REFERENCES core.vyroba_zaznam(id) ON DELETE CASCADE,
    -- vazba na zásobu v Pohodě
    skz_id          int,                     -- SKz.ID
    ids             text,                    -- SKz.IDS (jde do Pohoda XML)
    ean             text,
    nazev           text,
    mj              text,
    mnozstvi        numeric(14,3) NOT NULL,  -- vyrobené množství
    sklad_ids       text,                    -- kam naskladnit (sSklad.IDS)
    -- sledovatelnost (traceability)
    dmt             date,                    -- datum min. trvanlivosti
    vyrobni_cislo   text,                    -- šarže / lot
    tisk_pocatek    integer,                 -- počáteční tištěné číslo DMT
    tisk_konec      integer,                 -- koncové tištěné číslo
    tisk_rozdil     integer GENERATED ALWAYS AS
                        (tisk_konec - tisk_pocatek) STORED,
    zdroj           text,                    -- původ surovin
    -- kvalita
    refrakce_bx     numeric(6,2),            -- °Bx
    kyselost        numeric(6,2),
    poznamka        text,
    poradi          int NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_vyroba_polozka_zaznam
    ON core.vyroba_polozka (zaznam_id);
CREATE INDEX IF NOT EXISTS ix_vyroba_polozka_sarze
    ON core.vyroba_polozka (vyrobni_cislo);

-- --- sanitace a údržba (HACCP) ---------------------------------------
CREATE TABLE IF NOT EXISTS core.vyroba_sanitace (
    id          bigserial PRIMARY KEY,
    zaznam_id   bigint NOT NULL REFERENCES core.vyroba_zaznam(id) ON DELETE CASCADE,
    oblast      text   NOT NULL,             -- 'kompresor','triblok','paster','vyrobni_prostory'
    popis       text,                        -- SV/TV/pára/louh/schaum...
    cas         time
);

CREATE INDEX IF NOT EXISTS ix_vyroba_sanitace_zaznam
    ON core.vyroba_sanitace (zaznam_id);

-- --- trigger updated_at ----------------------------------------------
DROP TRIGGER IF EXISTS trg_vyroba_zaznam_touch ON core.vyroba_zaznam;
CREATE TRIGGER trg_vyroba_zaznam_touch
    BEFORE UPDATE ON core.vyroba_zaznam
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();

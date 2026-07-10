/* =====================================================================
   core.task  +  core.task_log        (DB most, schema core)
   ---------------------------------------------------------------------
   Evidence opakovanych uloh (tasks) a jejich behu - pro prehled i Grafanu.
   Konvence: cesky bez diakritiky, snake_case, ts_ prefix pro casy.
     core.task     = registr uloh + posledni stav
     core.task_log = log jednotlivych behu (start/konec/stav/zprava)
   ===================================================================== */
CREATE TABLE core.task (
    klic        nvarchar(50)   NOT NULL PRIMARY KEY,   -- 'zasoby_min'
    nazev       nvarchar(200)  NULL,
    aktivni     bit            NOT NULL CONSTRAINT DF_task_aktivni DEFAULT 1,
    ts_posledni datetimeoffset NULL,                   -- posledni beh
    stav        varchar(10)    NULL,                   -- 'ok' | 'chyba' | 'bezi'
    popis       nvarchar(400)  NULL,
    ts_sync     datetimeoffset NULL                    -- posledni sync z TOML
);

CREATE TABLE core.task_log (
    id        bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
    task_klic nvarchar(50)   NOT NULL,
    ts_start  datetimeoffset NOT NULL,
    ts_konec  datetimeoffset NULL,
    stav      varchar(10)    NULL,          -- 'bezi' | 'ok' | 'chyba'
    zprava    nvarchar(max)  NULL           -- pocet radku / chybova hlaska
);

CREATE INDEX IX_task_log_klic_start ON core.task_log (task_klic, ts_start DESC);

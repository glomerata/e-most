/* =====================================================================
   core.hist        (DB most, schema core)
   ---------------------------------------------------------------------
   Casova rada libovolnych metrik (prm/val). Puvodne v MariaDB, migrovano.
   Prvni pouziti: prm='sumLikv' = suma faktur po splatnosti (Kc).
   Konvence: cesky bez diakritiky, ts_ prefix; ts = zonove (Grafana).
   ===================================================================== */
CREATE TABLE core.hist (
    id  bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
    dt  date           NULL,          -- datum mereni (0:00 v puvodni MariaDB)
    ts  datetimeoffset NOT NULL       -- presny cas zapisu (zonove)
        CONSTRAINT DF_hist_ts DEFAULT SYSDATETIMEOFFSET(),
    prm nvarchar(50)   NULL,          -- 'sumLikv' ...
    val decimal(13,2)  NULL
);

CREATE INDEX IX_hist_prm_dt ON core.hist (prm, dt);

/* =====================================================================
   dbo.obj_pol   (StwPh_26896869_all)
   ---------------------------------------------------------------------
   Polozky objednavek za AKTUALNI rok. Konvence 'all':
     holy nazev = aktualni rok  |  u_* = union pres roky.
   Pary s dbo.obj (hlavicky, aktualni rok).
   ROK: pri prechodu roku zmenit prefix zde (jedine misto).
   ===================================================================== */
CREATE VIEW dbo.obj_pol AS
SELECT *
FROM StwPh_26896869_2025.dbo.OBJpol;

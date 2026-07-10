/* =====================================================================
   v_451_skz_obj_min_stav      (StwPh_26896869_all)
   ---------------------------------------------------------------------
   Denni prehled zasob s upozornenim na dochazejici polozky.
     Disponibilni = Stav - (nevyrizene prijate objednavky, AKTUALNI rok).
     Zasoba_Dny   = 365 * Disponibilni / Last365  (obrat za rok).

   CTE cte VYHRADNE z 'all' vrstvy (obj, obj_pol, skz, ids) -> zadny
   rocni prefix v tomto view. Rok se udrzuje jen v obj/obj_pol.

   Prah: NEzadratovan. Cte se z most.core.config (klic 'alerty.prah_dny');
         nez tabulka existuje, COALESCE/TRY_CAST spadne na 10.
   ===================================================================== */
CREATE VIEW dbo.v_451_skz_obj_min_stav
AS
WITH objednano AS (
    -- nevyrizene prijate objednavky (aktualni rok) -> dopocet na kartu (RefSKz)
    SELECT
        p.RefSKz,
        SUM(p.Mnozstvi - ISNULL(p.Dodano, 0)) AS obj_mn
    FROM dbo.obj_pol AS p
    INNER JOIN dbo.obj AS o ON o.ID = p.RefAg
    WHERE p.RefSKz IS NOT NULL
      AND o.RelTpObj = 1              -- prijate objednavky
      AND o.Vyrizeno = 0              -- doklad nevyrizeny
      AND o.DatStorn IS NULL          -- bez storna
      AND ISNULL(p.Dodano, 0) < p.Mnozstvi
    GROUP BY p.RefSKz
),
obj_ids AS (
    -- dopocet z karty (SKz.ID) prepocteny na IDS_n pres tabulku ids
    SELECT
        i.IDS_n,
        SUM(b.obj_mn) AS objednano
    FROM objednano AS b
    INNER JOIN dbo.skz AS s ON s.ID = b.RefSKz
    LEFT  JOIN ids     AS i ON s.IDS = i.IDS
    WHERE i.IDS_n IS NOT NULL
    GROUP BY i.IDS_n
),
prah AS (
    SELECT COALESCE(
        (SELECT TRY_CAST(hodnota AS float)
         FROM most.core.config WHERE klic = 'alerty.prah_dny'), 10.0
    ) AS prah_dny
)
SELECT
    GETDATE()                                 AS ts,
    z.EAN,
    z.IDS_n,
    z.pKtg,
    z.Poradi,
    p.Nazev,
    z.Objem,
    z.Podil,
    z.BIO,
    z.Stav,
    ISNULL(o.objednano, 0)                    AS objednano,
    z.Stav - ISNULL(o.objednano, 0)           AS disponibilni,
    p.Last365,
    CASE WHEN p.Last365 IS NULL OR p.Last365 = 0 THEN NULL
         ELSE ROUND(365.0 * (z.Stav - ISNULL(o.objednano, 0)) / p.Last365, 0)
    END                                       AS zasoba_dny,
    pr.prah_dny,
    -- pod_min: zaporny/vyprodany NEBO min nez prah dni
    CASE
        WHEN (z.Stav - ISNULL(o.objednano, 0)) <= 0 THEN 1
        WHEN p.Last365 > 0
             AND 365.0 * (z.Stav - ISNULL(o.objednano, 0)) / p.Last365 < pr.prah_dny
             THEN 1
        ELSE 0
    END                                       AS pod_min
FROM dbo.v_400_sklad_zasoby AS z
INNER JOIN dbo.v_250_vydej_ids_rok AS p ON p.IDS_n = z.IDS_n
LEFT  JOIN obj_ids AS o ON o.IDS_n = z.IDS_n
CROSS JOIN prah AS pr
WHERE p.Rep = 1;

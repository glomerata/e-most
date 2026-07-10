/* =====================================================================
   ALTER core.task  -  planovani pres scheduler.py
   ---------------------------------------------------------------------
   cron      = standardni 5-pole cron ('2 6,18 * * *'). Scheduler.py cte
               a spousti ulohy, jejichz cas padl do okna od minuleho behu.
               (Task Scheduler = spousteni scheduleru; cron = KDY co.)
   parametry = volitelny parametr predany do run() jako tcfg['_param'].
   ===================================================================== */
ALTER TABLE core.task ADD
    cron      varchar(50)   NULL,
    parametry nvarchar(400) NULL;

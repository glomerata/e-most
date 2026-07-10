# Migrace hist: MariaDB -> MSSQL (core.hist)

JEDNORAZOVE. Po uspesne migraci uz MariaDB pro hist nepotrebujes.

## Postup
1. V MSSQL (most) vytvor tabulku:  _docs/db/core_hist.sql
2. Doinstaluj do venv:  pip install pymysql
3. Spust migraci (heslo zada interaktivne, needava se do gitu):
   python migrace_hist.py --mysql-host HOST --mysql-db DB --mysql-user USER
   (volitelne --truncate = pred migraci vyprazdnit cilovou core.hist)
4. Over pocet radku v core.hist proti puvodni MariaDB.
5. Az sedi, uloha faktury_po_splatnosti pise rovnou do core.hist.

"""
migrace_hist.py  -  JEDNORAZOVA migrace core.hist z MariaDB do MSSQL.
Spustit RUCNE jednou. Pak smazat / archivovat.

Pripojeni:
  - MariaDB: udaje z argumentu nebo uprav primo zde (nedavej heslo do gitu!)
  - MSSQL:   Windows auth na NJABKO\\SQLEXPRESS, DB 'most'

Pouziti:
  python migrace_hist.py --mysql-host HOST --mysql-db DB --mysql-user USER
  (heslo zada interaktivne, neukazuje se)
"""
from __future__ import annotations

import argparse
import getpass

import pymysql       # pip install pymysql
import pyodbc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mysql-host", required=True)
    ap.add_argument("--mysql-db", required=True)
    ap.add_argument("--mysql-user", required=True)
    ap.add_argument("--mssql-server", default=r"NJABKO\SQLEXPRESS")
    ap.add_argument("--mssql-db", default="most")
    ap.add_argument("--truncate", action="store_true",
                    help="pred migraci vyprazdnit cilovou core.hist")
    a = ap.parse_args()

    pwd = getpass.getpass("MariaDB heslo: ")

    src = pymysql.connect(host=a.mysql_host, user=a.mysql_user,
                          password=pwd, database=a.mysql_db, charset="utf8mb4")
    sc = src.cursor()
    sc.execute("SELECT dt, ts, prm, val FROM hist ORDER BY id")
    rows = sc.fetchall()
    src.close()
    print(f"MariaDB: nacteno {len(rows)} radku")

    dst = pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={a.mssql_server};"
        f"DATABASE={a.mssql_db};Trusted_Connection=yes")
    dc = dst.cursor()
    if a.truncate:
        dc.execute("TRUNCATE TABLE core.hist")
    dc.fast_executemany = True
    dc.executemany(
        "INSERT INTO core.hist (dt, ts, prm, val) VALUES (?, ?, ?, ?)", rows)
    dst.commit()
    dst.close()
    print(f"MSSQL: vlozeno {len(rows)} radku do core.hist")


if __name__ == "__main__":
    main()

# tasks — opakovane ulohy e-most

Tenky ramec pro naplanovane ulohy (Task Scheduler na jabku).

## Spusteni
```
cd T:\e-most\_sys\code\tasks
..\..\..\venv\Scripts\python runner.py zasoby_min
```
`runner.py <uloha>` = jediny vstupni bod. Zaloguje beh do `core.task_log`,
pri padu posle mail adminovi (`org.email_org_admin`).

## Dostupne ulohy
| klic            | co dela                          | stav        |
|-----------------|----------------------------------|-------------|
| zasoby_min      | mail s polozkami pod min (v_451) | hotovo      |
| banka_import    | nacteni bankovnich vypisu        | sablona     |
| skeny_kontrola  | kontrola naskenovanych polozek   | sablona     |
| faktury_neuhr   | kontrola neuhrazenych faktur     | sablona     |

## Pridani nove ulohy
1. `tasks/<klic>.py` s funkci `run(tcfg: dict) -> str`.
2. zaregistrovat v `runner.py` (slovnik `_TASKS`).
3. sekce `[tasks.<klic>]` v `config.toml` (aspon `enabled = true`).

## Predpoklady
- DB objekty: `core.task`, `core.task_log` (viz `_docs/db/core_task.sql`),
  `dbo.v_451_skz_obj_min_stav`, `dbo.obj_pol`. `core.config` volitelne.
- config sekce: `[mssql]`, `[smtp]`, `[tasks.*]`, `[org].email_org_admin`.

## Task Scheduler (jabko)
- Program: `T:\e-most\_sys\...\venv\Scripts\python.exe`
- Argumenty: `runner.py zasoby_min`
- Spustit v: `T:\e-most\_sys\code\tasks`
- Spoustet: denne rano (napr. 6:30).

## Scheduler (planovac v DB)
Task Scheduler spousti kazdych `[scheduler].beh_minut` (10) jeden prikaz:
```
runner.py scheduler
```
Scheduler precte `core.task.cron` a spusti ulohy, jejichz cas padl do okna
od minuleho behu (nic se nepromeska). Plan tedy menis v DB (`core.task.cron`),
NE v Task Scheduleru.

Priklad zavedeni ulohy do planu:
```sql
UPDATE core.task SET cron = '2 6 * * *', aktivni = 1 WHERE klic = 'zasoby_min';
```
Cron = 5 poli: min hod den mesic den_v_tydnu  (*, cislo, 6,18, */10, 1-5).

## Textovy log
Vedle core.task_log se pise i `{base}\_sys\logs\tasks.log`:
```
2026-07-10T06:30:05+02:00 | zasoby_min | log_id=123 | info | 8 polozek pod minimem
```

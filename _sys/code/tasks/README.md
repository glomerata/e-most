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

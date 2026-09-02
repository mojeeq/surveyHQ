# Architecture

## The shape of it

```
Browser ── nginx ── FastAPI ── Postgres   (metadata)
                       │
                       ├────── DuckDB ── Parquet files   (survey data)
                       │
                       └────── Redis ─── Celery worker + beat
```

Six containers: `web` (nginx), `api` (FastAPI), `worker` and `beat` (Celery, same
image as the API), `postgres` and `redis`.

## Why survey data does not live in Postgres

A survey dataset is wide (hundreds of columns), read-only after import, and
queried with aggregates rather than row lookups. Loading it into Postgres means
either a table per dataset — schema migrations every time someone uploads a file
— or a tall key/value table, which makes every cross-tab a self-join.

Instead each dataset is written once to a Parquet file and queried in-process
with DuckDB. Parquet is columnar and compressed, so a tabulation touches only the
columns it needs. A 100,000-row survey answers a cross-tab in single-digit
milliseconds, and adding a dataset is a file write, not a migration.

Postgres keeps what is genuinely relational: users, datasets, variables and their
labels, connections, charts, dashboards, indicators, snapshots, alerts, quality
rules and results, jobs, audit entries.

## The query specification

Every chart, indicator, widget and ad-hoc analysis compiles from the same JSON
specification:

```json
{
  "dimensions": [{"variable": "region", "grain": null, "bin_width": null}],
  "measures":   [{"agg": "mean", "variable": "income", "weight": "hhweight"}],
  "filters": {
    "op": "and",
    "conditions": [{"variable": "age", "operator": "gte", "value": 18}],
    "groups": []
  },
  "sort":  [{"field": "mean_income", "direction": "desc"}],
  "limit": 100,
  "use_labels": true
}
```

Being declarative means the same object can be stored on a chart, replayed by a
scheduled job, rebuilt in the query builder, and exported — without the server
templating SQL strings from user input.

### How injection is prevented

The compiler in `backend/app/services/query_engine.py` works to two rules:

1. **Identifiers are allowlisted.** Every variable name in a specification is
   looked up in the dataset's registered variables. An unknown name raises
   `QueryError` before any SQL is built, so no caller-supplied string ever
   reaches the query as an identifier.
2. **Literals are parameters.** Filter values are bound with `?` placeholders,
   never interpolated.

`test_query_engine.py` asserts both, including that a name like
`region"; DROP TABLE users; --` is rejected rather than escaped.

## Labels

Stata and SPSS files carry variable labels ("Age of respondent") and value labels
(1 = Male). `pyreadstat` reads both; pandas is the fallback. They are stored on
the `variables` table and applied when results are returned, so the analyst sees
"Female" while the query still groups on the stored code.

Filters can work either way: `use_label` on a condition translates a label back
to its code before the comparison.

## Background work

Celery handles anything that outlives a request:

| Task | Trigger |
|---|---|
| `run_connection_sync` | On demand, or by the scheduler |
| `schedule_due_syncs` | Every `SYNC_TICK_MINUTES` |
| `refresh_all_indicators` | Every `MONITOR_TICK_MINUTES` — recomputes indicators, stores a snapshot, evaluates alert rules |
| `run_all_quality_checks` | Every six hours |
| `prune_history` | Nightly — trims snapshots, resolved alerts, old results and jobs |

Indicator snapshots are what make trends possible: each refresh writes a
timestamped value, so every indicator carries its own history without anyone
configuring a time series.

## Monitoring model

- **Indicator** — one query producing one number, plus a target, a warning and a
  critical threshold, and a direction (higher or lower is better). The direction
  decides which side of a threshold counts as bad.
- **Alert rule** — watches an indicator with a comparison and a threshold. On a
  match it raises an alert and notifies by in-app message and optionally email.
  A cooldown stops one ongoing problem generating a stream of alerts. When the
  value recovers, open alerts for that rule resolve themselves.
- **Quality rule** — one of eight check types with a tolerance. The check fails
  when the share of offending rows exceeds it.

## Layout of the code

```
backend/app/
  core/         config, logging, password hashing, JWTs, secret encryption
  db/           SQLAlchemy engine, session, bootstrap
  models/       tables: user, dataset, connection, analytics, monitoring, system
  schemas/      pydantic request/response models, including the query spec
  api/v1/       endpoints, grouped by area
  services/     the substance:
                  ingest.py           files -> Parquet + metadata
                  query_engine.py     spec -> DuckDB SQL -> result
                  survey_solutions.py the CAPI server client
                  quality.py          the eight checks
                  monitoring.py       indicators, thresholds, alerts
                  field_progress.py   the automatic monitoring views
  workers/      Celery app and tasks

frontend/src/
  lib/          API client, types, formatting, ECharts option builder
  hooks/        auth and toast context
  components/   layout, chart card, data table, filter builder, UI primitives
  pages/        one per route
```

## Chart colour

Series colour uses a categorical palette validated for colour-vision deficiency
separation against the app's white surface. Two rules follow from that:

- Hues are assigned in a **fixed order and never cycled**, so a series keeps its
  colour when a filter changes how many series are on screen. Past eight
  categories the tail folds into "Other" rather than inventing a ninth hue.
- Three of the eight slots sit below 3:1 contrast on white, so identity never
  rests on colour alone: charts carry a legend, and every chart has a **table
  toggle** exposing the same numbers.

Sequential encodings (heatmaps) use a single blue ramp, light to dark. Status
colours — ok, warning, critical — are reserved, never reused as a series colour,
and always paired with an icon and a word.

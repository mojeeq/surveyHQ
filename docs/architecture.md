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

Postgres keeps what is genuinely relational: users, projects and their members,
datasets, variables and their labels, connections, charts, dashboards,
indicators, snapshots, alerts, quality rules and results, jobs, audit entries.

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

## Replacing data in place

The platform exists to be pointed at a survey that is still in the field, so the
central operation is not "add a dataset" but "this dataset, but newer". An
export arrives every morning with the same variables and more interviews.

An archive is therefore unpacked to one dataset per file inside it - the
interview level, each roster level, the paradata - and each file is sent to the
dataset already holding that name. The default is **replace**: the Parquet file
is rewritten and the dataset keeps its id, so every relationship, merge, chart,
indicator, quality rule and dashboard widget that references it goes on
referencing it. Append is the alternative, for exports that really are
incremental.

Keeping the id is only half of it. Three things are not in the export file and
would be lost every morning if they were not put back:

1. **Labels written by hand.** The variable rows are deleted and rebuilt from
   the file on every import, so hand-written labels are kept on the dataset's
   own metadata as well and reapplied afterwards.
2. **Generated variables.** Commands are recorded on the dataset and replayed,
   in order, immediately after the new data lands - before the import checks
   which variables went missing, so a variable the replay restores is not
   reported as lost.
3. **Merged datasets.** `derived.py` walks the dependency graph outward in
   rounds, so a merge of a merge is rebuilt only once the merge underneath it
   has been.

## Where an upload is read

Small uploads are read in the request. Anything over 48 MB is written to disk,
handed to the worker as a job, and answered with that job, which the browser
polls. Two reasons, both of which a census roster export hits at once: reading
it takes longer than any proxy holds a request open, and reading it in the API
process takes memory away from every other request being served.

The size limit is checked in middleware, from the declared content length,
before the body is read. It used to be checked in the route - which runs only
after the whole multipart body has been received and written to disk - so an
over-limit file was transferred in full and then refused, and nginx, left
holding a body nobody was reading any more, reported the refusal as a bad
gateway. nginx now enforces no ceiling of its own (`client_max_body_size 0`):
one place decides, and it is the place that can say what the limit is.

## Derived variables

`stata.py` implements the idioms - `gen`, `replace`, `egen`, `label`, `rename`,
`drop`, `keep`, with `if` - as SQL against the dataset's Parquet file.
`stata_expr.py` stands between the typed expression and that SQL: it tokenises,
checks every identifier against the dataset's registered variables and every
operator and function against a fixed list, and emits SQL from what it
recognised. Nothing is passed through as text, so the command box is not a
second, softer route into the query engine.

Two details that matter more than they look:

- Stata's `.` is SQL's `NULL`, and `NULL` comparisons are neither true nor
  false. `x != .` has to become `x IS NOT NULL`, or a `replace ... if` quietly
  changes nothing.
- `egen ... by()` compiles to a window function, and window functions do not
  preserve file order. Row order is captured with `ROW_NUMBER() OVER ()` in a
  subquery and restored afterwards, so the rewritten file is still the same file
  in the same order.

A script runs a line at a time and commits what succeeded, as a do-file does. A
failing line stops the script and reports itself; the lines above it have
already run, so the log says what got through rather than pretending nothing
happened.

## Dashboards

A dashboard is a set of widgets on a grid, across named pages. Widgets carry a
`page` index into the dashboard's `pages` list, so moving one between pages is a
field change rather than a re-layout, and every dashboard from before pages
existed is a dashboard with one unnamed page.

Every widget type renders through one `POST /dashboards/{id}/data` call, each
branch returning a shape its component knows: a chart or cross-tab re-runs its
stored spec, an indicator returns its value, status and optional breakdown, a
map returns coordinates grouped by point, freshness returns a report per
dataset, and text, countdown and HTML return their configuration.

**Filters** are declared on the dashboard and belong to a page. A control names
a variable, which not every widget's dataset necessarily has, so each widget
receives only the conditions its own dataset can answer and reports the rest as
ignored - the alternative being a filter that silently does nothing to half the
page.

**Appearance** is one JSON column rather than a set of columns: background
colour, image, fit and fade, canvas width, grid columns, row height, widget
opacity, tab-strip colour. It is presentation, it changes often, and nothing
queries it.

Background images are stored on disk, one file per dashboard, and their type is
sniffed from the leading bytes rather than trusted from the filename or the
browser's content type. SVG is refused: it is a document that can carry script,
and the file is served back from the API's own origin. Embedded HTML is
rendered in a sandboxed frame, so what it contains is between its author and
that frame.

## How recent is the data

Two questions, and `freshness.py` answers both: when the platform last received
data, and how recent the newest record in it is. An import that runs faithfully
every morning and collects nothing new passes the first and fails the second,
which is the failure worth catching.

The second needs a date column, and picking the wrong one is worse than picking
none: reading a date of birth reports a survey taken this morning as thirty
years stale. Candidate columns are therefore scored - names suggesting when a
record happened (interview, submitted, sync, starttime) score up; names that are
answers or questionnaire configuration (birth, death, reference period, the
simulated dates a template ships with) are disqualified outright - and nothing
scoring above zero means the widget says so rather than guessing. The choice can
be overridden per dataset on the widget.

## Background work

Celery handles anything that outlives a request:

| Task | Trigger |
|---|---|
| `run_connection_sync` | On demand, or by the scheduler |
| `schedule_due_syncs` | Every `SYNC_TICK_MINUTES` — decides which connections are due |
| `refresh_all_indicators` | Every `MONITOR_TICK_MINUTES` — recomputes indicators, stores a snapshot, evaluates alert rules |
| `run_all_quality_checks` | Every six hours |
| `prune_history` | Nightly — trims snapshots, resolved alerts, old results and jobs |

Indicator snapshots are what make trends possible: each refresh writes a
timestamped value, so every indicator carries its own history without anyone
configuring a time series.

A connection is due either on an interval — every N minutes since its last
import — or at times of day it lists, read in its own timezone.
`services/scheduling.py` answers the second by asking when the most recent
listed time last came round in that zone, and whether the last import was
before it. That is a comparison against wall-clock history rather than a cron
expression, so the scheduler ticking at any interval finer than a day cannot
miss an occurrence, and cannot fire the same one twice.

Times are read in the connection's zone because fieldwork happens somewhere:
06:00 means six in the morning there, which in Vanuatu is five the previous
afternoon in UTC. Getting it wrong is not an hour's error, it is a day's.

Each run's export zip is kept under `sync-archives/`, the last five per
connection, so a run's history is a list of real files that can be downloaded
and re-uploaded like any other archive.

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

## Project scope

A project owns datasets and dashboards, and nothing else. Charts, indicators,
quality rules and alert rules already reference a dataset, so they take their
project from it - which means a resource's project is recorded in exactly one
place and the two cannot disagree.

`project_id` being null is the shared area, visible to every user. That is what
the whole platform was before projects existed, so an upgraded database, where
every row is null, behaves exactly as it did. `restricted_to_projects` on a user
shuts the shared area off for them, which is what makes "this person sees one
project and nothing else" expressible without first assigning everything else to
a project.

Connections are scoped by the project their imports land in, and alert rules by
what they watch - the indicator's dataset, their own, or, tied to neither, the
shared area. Both are reached by id from every route that acts on them, so both
check on the id rather than trusting a filtered listing. A connection is worth
saying out loud: it names a server, it can be made to import, and its runs hand
back the raw export, so an unscoped one is not a stale row in a list.

`services/projects.py` answers the two questions every endpoint has - which rows
may this user see, and may they change this one - so neither is re-derived,
slightly differently, per endpoint. Enforcement sits in the lookups
(`get_dataset`, `_get_dashboard`, `_get_chart`) rather than in each route,
because filtering the listings alone would leave a dataset readable to anyone who
knew its id: the query endpoints take one directly. Anything out of scope answers
404, never 403, so a response cannot confirm that a project exists.

A member's role is capped by their own role (`effective_role` takes the lower of
the two), so membership widens what someone can reach and never what they may do.

Deleting a project takes an argument, because both answers are right for
different rounds. `contents="release"` (the default) nulls its datasets' and
dashboards' `project_id` explicitly rather than relying on `ON DELETE SET
NULL`. The column reaches an existing database through `ALTER TABLE ADD
COLUMN`, which carries no foreign key, so the constraint would never fire there
and the rows would be stranded - pointing at a project that no longer exists,
and visible to nobody but an administrator.

`contents="delete"` destroys the lot: the project's datasets and their stored
files, and everything hanging off them - charts, indicators and their
snapshots, quality rules and results, alert rules and their alerts,
relationships, and any dataset merged out of them - plus its dashboards and
their widgets. Those dependants are deleted explicitly rather than left to
`ON DELETE CASCADE`, for the same reason plus one more: SQLite does not enforce
foreign keys by default, so a cascade that works in production would silently
do nothing under the test suite. Connections are released rather than deleted -
a connection is a server and a set of credentials, which outlive the project
pointed at it.

## Layout of the code

```
backend/app/
  core/         config, logging, password hashing, JWTs, secret encryption
  db/           SQLAlchemy engine, session, bootstrap
  models/       tables: user, project, dataset, connection, analytics,
                monitoring, system
  schemas/      pydantic request/response models, including the query spec
  api/v1/       endpoints, grouped by area
  services/     the substance:
                  ingest.py           files -> Parquet + metadata
                  query_engine.py     spec -> DuckDB SQL -> result
                  projects.py         who may see and change what
                  archives.py         a zip -> one dataset per file in it
                  derived.py          merges, and rebuilding what depends
                  stata.py            gen/egen/label/... over a dataset
                  stata_expr.py       Stata expressions -> checked SQL
                  freshness.py        how recent a dataset's data is
                  geo.py              GPS points, grouped, for the map
                  scheduling.py       when the next import is due
                  dashboard_assets.py background images
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

## The look of it

The interface follows Redash's own theme values - `#2196f3` primary, `#edecec`
page, `#e8e8e8` borders, `#595959` text on `#333` headings, 13px system font,
3px panels and 2px controls, and the `#191c22` navy its sidebar has always
been. They live as Tailwind tokens in `tailwind.config.js`, so the palette is
changed in one place rather than component by component.

The chart series palette is deliberately not from there. Page furniture can be
any colour; a chart's colours carry meaning, and the palette in `lib/charts.ts`
is validated for colour-vision deficiency separation. See below.

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

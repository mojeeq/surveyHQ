# REST API

Interactive documentation is served by the running instance at `/api/docs`, with
the OpenAPI specification at `/api/openapi.json`.

Base path: `/api/v1`

## Authenticating

Two ways.

**A session token**, for browser-style use:

```bash
curl -X POST https://surveyhq.example.org/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "you@example.org", "password": "your-password"}'
# {"access_token": "eyJ...", "token_type": "bearer", "expires_in": 86400}
```

```bash
curl https://surveyhq.example.org/api/v1/datasets \
  -H "Authorization: Bearer eyJ..."
```

**An API key**, for scripts. Create one in **Administration → API keys**; it is
shown once. Keys do not expire and can be revoked at any time.

```bash
curl https://surveyhq.example.org/api/v1/datasets \
  -H "X-API-Key: shq_abc12345_..."
```

An API key carries the role of the user who created it.

## Endpoints

Every listing returns only what the caller may reach. A dataset, dashboard or
chart outside their projects answers `404`, not `403`, so responses cannot be
used to enumerate other people's projects.

### Projects

```
GET    /projects                          projects you can reach
POST   /projects                          create; you become its manager [manager]
GET    /projects/{id}                     detail, with members
PATCH  /projects/{id}                     rename, describe, set dates  [project manager]
DELETE /projects/{id}?contents=release    delete; its datasets and dashboards
                                          return to the shared area   [project manager]
DELETE /projects/{id}?contents=delete     delete it and everything in it: datasets
                                          and their files, charts, indicators and
                                          snapshots, quality and alert rules and
                                          their results, relationships, merged
                                          datasets, dashboards. Connections are
                                          released, not deleted       [project manager]
GET    /projects/{id}/members             members and their roles
PUT    /projects/{id}/members             add a member, or change a role
                                          {"user_id": "...", "role": "analyst"}
                                          "admin" is rejected: administration is
                                          global, not per project     [project manager]
DELETE /projects/{id}/members/{user_id}   remove a member             [project manager]
PUT    /projects/assign/dataset/{id}      {"project_id": "..."} or null for the
                                          shared area; needs manager rights on
                                          both the source and the target
PUT    /projects/assign/dashboard/{id}    the same, for a dashboard
```

### Relationships and merges

```
GET    /relationships                     links whose datasets you can see
                                          (project_id filters; "none" = shared)
POST   /relationships/detect              propose links by reading the data;
                                          stores the new ones      [manager]
POST   /relationships                     declare one by hand      [manager]
PATCH  /relationships/{id}                correct keys, cardinality, or turn it
                                          off; marks it no longer detected
                                                                   [manager]
DELETE /relationships/{id}                                         [manager]
POST   /relationships/clear               remove a project's links
                                          (?project_id=&detected_only=true keeps
                                          the ones declared or corrected by hand)
                                                                   [manager]
POST   /relationships/merge               join two related datasets into a new
                                          one; the recipe is stored on it
                                                                   [manager]
POST   /relationships/rebuild/{id}        re-run that merge against the current
                                          sources                  [manager]
```

A merged dataset also rebuilds itself whenever a source is replaced by a newer
import or changed by a command, so `/rebuild` is for forcing the issue rather
than for keeping up.

A many-to-many link is refused by `/merge`: joining two rosters on the interview
multiplies rows rather than adding columns.

### Datasets

```
GET    /datasets                          list (search, status, project_id, limit,
                                          offset). project_id=none returns only
                                          what is in the shared area.
POST   /datasets/upload                   multipart upload; project_id puts it
                                          straight into a project. A .zip answers
                                          with a per-file report rather than one
                                          dataset - see below      [manager]
GET    /datasets/{id}                     detail with variables
PATCH  /datasets/{id}                     rename, describe, tag [manager]
DELETE /datasets/{id}                                            [manager]
POST   /datasets/delete                   delete several at once, or a whole
                                          project's worth          [manager]
POST   /datasets/{id}/replace             refresh in place      [manager]
POST   /datasets/{id}/append              add rows to it        [manager]
GET    /datasets/{id}/variables           variable list
PATCH  /datasets/{id}/variables/{v}       set the variable's label and the labels
                                          of its codes             [manager]
GET    /datasets/{id}/preview             raw rows
GET    /datasets/{id}/download?format=      the whole dataset as a file: dta
                                          (with labels), csv or xlsx [manager]
GET    /datasets/{id}/variables/{v}/values  distinct values
POST   /datasets/{id}/command             run a Stata-style script [manager]
GET    /datasets/{id}/commands            what will be replayed after a replace
DELETE /datasets/{id}/commands            stop replaying them, without undoing
                                          what they did            [manager]
GET    /datasets/{id}/tags                tags in use
```

An upload larger than 48 MB is imported by the worker rather than in the
request, and answers with a **job** instead of a dataset - poll
`GET /system/jobs/{id}` and read its `result` when it succeeds, which carries
the same report the inline path returns. Reading a census roster export takes
longer than any proxy holds a request open, and doing it in the API process
takes memory from every other request.

An upload larger than `MAX_UPLOAD_MB` answers **413** from the declared length,
before the body is read, and the message names both the size and the limit.

`POST /datasets/upload` takes `mode` alongside the file: `replace` (the default)
swaps the data of each dataset an archive's files match, keeping their ids so
everything built on them survives; `append` adds the rows instead. `combine_all`
is for the other case again - an archive that really does hold several rounds of
one table, which goes into a single dataset.

Uploading an archive returns:

```json
{
  "datasets": [ ... ],
  "created":  ["R_demographics.dta -> R_demographics (401 rows)"],
  "replaced": ["VN_LF2024.dta -> VN_LF2024 (99 -> 190 rows)"],
  "appended": [],
  "skipped":  [],
  "warnings": ["... appear in both ... so those interviews are now counted twice"],
  "rows": 519
}
```

`POST /datasets/delete` takes either a list of ids or a project:

```json
{"ids": ["0f3c…", "7ab1…"]}
{"project_id": "2d19…"}    // "" is the shared area
```

Ids the caller cannot reach are skipped rather than refused - the listing they
were chosen from is already scoped, so a stray id is a stale page.

`POST /datasets/{id}/command` takes `{"command": "gen adult = age >= 18"}`, one
command per line. The reply reports each line that ran and what it changed. A
line that fails stops the script; everything above it has already run and is
committed, as in a do-file, and the error names the line and the reason.
Commands are recorded and replayed after a later export replaces the data.

### Analysis

```
POST /analytics/query                              run a query specification
POST /analytics/query/export?format=csv|xlsx       download the result
GET  /analytics/datasets/{id}/frequency/{variable} one-way frequencies
POST /analytics/datasets/{id}/crosstab             two-way table; max_rows
                                                  (default 5,000) and max_columns
                                                  (default 1,000) bound it, and the
                                                  result reports rows_omitted and
                                                  columns_omitted
POST /analytics/datasets/{id}/crosstab/export      download it
POST /analytics/datasets/{id}/summary              descriptive statistics
POST /analytics/datasets/{id}/suggest              suggested analyses
GET  /analytics/saved-queries
POST /analytics/saved-queries                                    [analyst]
```

### Connections

```
GET    /connections
POST   /connections                       create               [manager]
POST   /connections/test                  test before saving   [manager]
POST   /connections/{id}/test             test a saved one     [manager]
GET    /connections/{id}/questionnaires   list from the server
GET    /connections/{id}/interviews       live interview summaries
POST   /connections/{id}/sync             start an import      [manager]
GET    /connections/{id}/runs             import history; has_archive says whether
                                          the export zip is still on disk
GET    /connections/{id}/runs/{run}/archive  download that export zip exactly as
                                          the server sent it
```

Connections are scoped by their project, like everything else that has one:
listings are filtered, and every route above answers 404 for a connection
outside the caller's reach - including `/questionnaires`, `/interviews`,
`/sync` and the archive download, each of which reaches the server or its data.
Aiming an import at a project the caller does not manage is refused the same
way.

A connection carries where its imports land and when they happen:

| Field | Meaning |
|---|---|
| `project_id` | The project imported datasets go into |
| `sync_enabled` | Whether the scheduler imports without being asked |
| `sync_mode` | `interval` or `times` |
| `sync_interval_minutes` | For `interval`: how long since the last import |
| `sync_times` | For `times`: `["06:00", "18:00"]`, in `sync_timezone` |
| `sync_timezone` | An IANA zone, e.g. `Pacific/Efate`. Times mean that clock |
| `export_format` | `STATA` recommended - it carries labels |
| `interview_status` | `All`, or e.g. `ApprovedBySupervisor` |

`POST /{id}/sync` accepts `questionnaires`, `interview_status`, `project_id` and
`mode` (`replace` or `append`), each falling back to the connection's own
setting. The last five export archives per connection are kept on disk; older
ones are pruned as new runs land.

### Charts and dashboards

```
GET/POST/PATCH/DELETE /dashboards/charts[/{id}]
POST   /dashboards/charts/{id}/data       run a saved chart
GET/POST/PATCH/DELETE /dashboards[/{id}]
POST   /dashboards/{id}/widgets                                 [analyst]
PATCH  /dashboards/{id}/widgets/{wid}     change anything about a widget: what it
                                          shows, its title, size, or page
                                                                [analyst]
DELETE /dashboards/{id}/widgets/{wid}                           [analyst]
PUT    /dashboards/{id}/background        upload a background image (PNG, JPEG,
                                          GIF or WebP, 8 MB)    [analyst]
GET    /dashboards/{id}/background        the image itself
DELETE /dashboards/{id}/background                              [analyst]
PUT    /dashboards/{id}/logo              upload a header logo  [analyst]
GET    /dashboards/{id}/logo              the logo itself
DELETE /dashboards/{id}/logo                                    [analyst]
POST   /dashboards/{id}/data              render every widget; the body may carry
                                          filter conditions to narrow them
POST   /dashboards/{id}/share?enable=true public link           [analyst]
GET    /public/dashboards/{token}         no authentication
POST   /public/dashboards/{token}/data    no authentication
GET    /public/dashboards/{token}/background  no authentication
GET    /public/dashboards/{token}/logo        no authentication
```

A dashboard carries `pages` (named, each widget holding the index of the one it
sits on), `filters` (the controls offered to viewers, each belonging to a page),
`theme` (which categorical ordering its charts use) and `appearance`:

```json
{
  "background_color": "#0f172a",
  "background_image": "…",
  "background_fit": "cover",
  "fade": 0.3,
  "canvas_width": 2000,
  "columns": 12,
  "row_height": 74,
  "widget_opacity": 0.6,
  "tab_background": "#ffffff",

  "logo_image": "…", "logo_version": "…", "logo_height": 44,
  "title_size": 38, "title_font": "serif", "title_color": "#0b5e3c",
  "title_align": "left", "header_rule": true, "hide_subtitle": false
}
```

`title_font` names a stack the frontend knows (`grotesque`, `serif`, `slab`,
`mono`, or empty for the interface face) rather than carrying CSS.

A widget is one of `chart`, `crosstab`, `indicator`, `quality`, `text`,
`countdown`, `map`, `html` or `freshness`, and the rest of what it needs lives in
its `config` - the countdown's target, the map's latitude, longitude, detail
columns and aggregate, the HTML to embed, or the freshness widget's datasets,
thresholds and any date variable chosen by hand.

Filter conditions sent to `/data` are applied per widget: each one receives only
the conditions its own dataset has variables for, and reports the rest in
`filters_ignored`.

### Monitoring

Indicators, alerts, alert rules, quality rules and quality results all accept
`project_id` to narrow a listing to one project (`none` for the shared area);
a resource takes its project from its dataset.

Scope is enforced on the id, not only on the listing. An alert rule is reached
through its indicator's dataset, or its own, or - tied to neither - through the
shared area; an alert through the rule that raised it. Editing, deleting,
testing, acknowledging and resolving all answer 404 outside that reach, and a
rule cannot be moved onto an indicator or dataset the caller cannot reach.
An indicator can be moved between datasets with `dataset_id`, which is checked
at both ends.

```
GET/POST/PATCH/DELETE /monitoring/indicators[/{id}]
GET  /monitoring/indicators/values?refresh=true   current values with trends
POST /monitoring/indicators/{id}/refresh
GET/POST/PATCH/DELETE /monitoring/alert-rules[/{id}]
POST /monitoring/alert-rules/{id}/test
GET  /monitoring/alerts?status=open
POST /monitoring/alerts/{id}/acknowledge | /resolve
GET/POST/PATCH/DELETE /monitoring/quality-rules[/{id}]
POST /monitoring/quality-rules/{id}/run
POST /monitoring/datasets/{id}/quality/run-all
GET  /monitoring/datasets/{id}/quality/suggestions
POST /monitoring/datasets/{id}/field-progress
GET  /monitoring/summary
```

### System

```
GET  /system/jobs            background jobs
GET  /system/notifications
GET  /system/audit                                              [admin]
GET  /system/info
GET  /health                 no authentication
```

## The query specification

The same object drives ad-hoc queries, saved charts and indicators.

```json
{
  "dataset_id": "0f3c…",
  "spec": {
    "dimensions": [
      {"variable": "region"},
      {"variable": "interview__date", "grain": "week"}
    ],
    "measures": [
      {"agg": "count", "alias": "interviews"},
      {"agg": "mean", "variable": "hh_size", "alias": "avg_size", "weight": "hhweight"}
    ],
    "filters": {
      "op": "and",
      "conditions": [
        {"variable": "interview__status", "operator": "eq", "value": 100},
        {"variable": "age", "operator": "between", "value": [18, 65]}
      ],
      "groups": []
    },
    "sort": [{"field": "interviews", "direction": "desc"}],
    "limit": 500,
    "use_labels": true
  }
}
```

**Aggregations**: `count`, `count_distinct`, `sum`, `mean`, `median`, `min`,
`max`, `stddev`, `p25`, `p75`, `p90`, `share`.

**Filter operators**: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`,
`contains`, `not_contains`, `starts_with`, `ends_with`, `between`, `is_null`,
`is_not_null`.

**Date grains**: `day`, `week`, `month`, `quarter`, `year`.

Filter groups nest, so `A AND (B OR C)` is expressible.

A response:

```json
{
  "columns": [
    {"name": "region", "label": "Region", "type": "dimension", "data_type": "categorical"},
    {"name": "interviews", "label": "Count", "type": "measure", "data_type": "number"}
  ],
  "rows": [["Nairobi", 1240], ["Kisumu", 980]],
  "row_count": 2,
  "truncated": false,
  "sql": "SELECT …",
  "duration_ms": 12
}
```

## Errors

| Status | Meaning |
|---|---|
| 400 | Invalid query — an unknown variable, or an impossible aggregation |
| 401 | Missing or expired credentials |
| 403 | Your role does not permit this |
| 404 | Not found |
| 409 | The dataset is not ready to query |
| 413 | Upload exceeds `MAX_UPLOAD_MB` |
| 422 | The file could not be parsed, or the request body is invalid |
| 502 | The Survey Solutions server could not be reached or refused the request |

Errors carry a readable `detail`:

```json
{"detail": "Unknown variable 'regionn' in this dataset"}
```

## Example: a daily extract

```python
import requests

BASE = "https://surveyhq.example.org/api/v1"
HEAD = {"X-API-Key": "shq_..."}

datasets = requests.get(f"{BASE}/datasets", headers=HEAD).json()
dataset = next(d for d in datasets["items"] if d["name"].startswith("Household"))

response = requests.post(
    f"{BASE}/analytics/query",
    headers=HEAD,
    json={
        "dataset_id": dataset["id"],
        "spec": {
            "dimensions": [{"variable": "region"}],
            "measures": [{"agg": "count", "alias": "interviews"}],
            "filters": {
                "op": "and",
                "conditions": [
                    {"variable": "interview__status", "operator": "eq", "value": 100}
                ],
                "groups": [],
            },
            "sort": [{"field": "interviews", "direction": "desc"}],
            "limit": 100,
        },
    },
)
result = response.json()
for region, count in result["rows"]:
    print(f"{region:20s} {count:>6,}")
```

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

### Datasets

```
GET    /datasets                          list (search, status, limit, offset)
POST   /datasets/upload                   multipart upload      [manager]
GET    /datasets/{id}                     detail with variables
PATCH  /datasets/{id}                     rename, describe, tag [manager]
DELETE /datasets/{id}                                            [manager]
POST   /datasets/{id}/replace             refresh in place      [manager]
GET    /datasets/{id}/variables           variable list
GET    /datasets/{id}/preview             raw rows
GET    /datasets/{id}/variables/{v}/values  distinct values
```

### Analysis

```
POST /analytics/query                              run a query specification
POST /analytics/query/export?format=csv|xlsx       download the result
GET  /analytics/datasets/{id}/frequency/{variable} one-way frequencies
POST /analytics/datasets/{id}/crosstab             two-way table
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
GET    /connections/{id}/runs             import history
```

### Charts and dashboards

```
GET/POST/PATCH/DELETE /dashboards/charts[/{id}]
POST   /dashboards/charts/{id}/data       run a saved chart
GET/POST/PATCH/DELETE /dashboards[/{id}]
POST   /dashboards/{id}/widgets                                 [analyst]
POST   /dashboards/{id}/data              render every widget
POST   /dashboards/{id}/share?enable=true public link           [analyst]
GET    /public/dashboards/{token}         no authentication
POST   /public/dashboards/{token}/data    no authentication
```

### Monitoring

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

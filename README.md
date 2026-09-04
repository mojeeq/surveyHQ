# SurveyHQ

A self-hosted platform for monitoring survey/census data collection. Connect it to a
Survey Solutions server or upload Stata files, then tabulate, chart, and watch
field work through dashboards, indicators, alerts and automated quality checks.

Built for a survey that is still in the field: a new export replaces the data
in place, so relationships, charts, indicators, quality rules and dashboards
built on it go on working without being rebuilt.

Runs on Ubuntu with Docker. One command to install.

---

## What it does

**Get data in**
- Connect to a Survey Solutions headquarters server and import interview data
  through its export API — on demand, on an interval, or at set times of day in
  the connection's own timezone.
- Upload Stata (`.dta`), SPSS (`.sav`), CSV, tab-delimited or Excel files, or a
  `.zip` export archive.
- An archive becomes **one dataset per file inside it** — the interview level,
  each roster level, and the paradata — because those are different tables, not
  different rounds.
- A later archive **replaces** what it matches by default, keeping each
  dataset's identity, so nothing built on it has to be redone. Choose *append*
  instead for genuinely incremental exports.
- A large upload is imported by the background worker, so a census-sized export
  does not depend on a browser connection staying open while it is read.
- Variable labels and value labels are preserved, so charts read "Female"
  rather than "2" — and you can write your own where the export has none.

**Analyse it**
- Tabulate: one-way frequencies with valid and cumulative percentages.
- Cross-tabulate: two-way tables with row/column/total percentages, chi-square
  and Cramér's V.
- Aggregate: group by any variables, measure with count, sum, mean, median,
  percentiles, standard deviation or distinct count — optionally survey-weighted.
- Filter with nested AND/OR conditions on any variable.
- Bin numeric variables, truncate dates to day/week/month/quarter/year.
- Chart it as a bar, horizontal bar, stacked bar, horizontal stacked bar,
  population pyramid, line, area, pie, donut, scatter, heatmap or table, with
  control over ordering, top-N, value labels, 100% stacking, axis title and
  range, and a target line.
- Derive variables with a Stata-style script — `gen`, `replace`, `egen`,
  `label`, `rename`, `drop`, `keep`, with `if` conditions — recorded and
  replayed automatically after the next export replaces the data.
- Export any result to CSV or Excel, or download a whole dataset as Stata (with
  its labels), CSV or Excel — merged datasets included.

**Monitor it**
- Indicators: a tracked number with a target and warning/critical thresholds,
  optionally a percentage of all rows or of those who answered, and optionally
  broken down by region, team or interviewer. History is kept, so every
  indicator has a trend.
- Alerts: rules watch indicators and raise in-app or email alerts when a
  threshold is crossed, with a cooldown so one problem does not spam you.
- Data quality: eight built-in checks (missing values, out-of-range, duplicates,
  outliers, short interviews, missing GPS, constant answers, cross-variable
  consistency). The platform inspects each dataset and recommends the checks
  that suit it.
- Field progress: submissions over time, interviews per interviewer and
  supervisor, status breakdown, coverage by area and a map of GPS points — built
  automatically from recognised Survey Solutions column names, with no setup.
- Monitoring, data quality and alerts can all be viewed one project at a time.

**Organise it**
- Projects group a survey round's datasets and dashboards, and decide who can
  reach them. Anything outside a project is a shared area every user can see.
- Deleting a project either releases its contents to the shared area or deletes
  the lot — datasets, dashboards, charts, indicators, rules and alerts — as you
  choose.
- Relationships between a project's datasets are detected from the data, shown
  as a model diagram, correctable, declarable by hand, and clearable in bulk.
  Two related datasets can be merged into a new one, and that merge re-runs
  itself whenever its sources change.
- Datasets are grouped by project in the listing, collapsible, and deletable in
  bulk or a whole project at a time.
- Membership gives a person one project and nothing else: an administrator can
  create a user, tick "limit to assigned projects", and add them to the one
  project they should work on.
- A member's role on a project never exceeds their own role, so adding a viewer
  to a project as manager does not make them an editor of anything.

**Share it**
- Dashboards with drag-and-drop widgets across named pages: charts, saved
  cross-tabulations, indicator tiles with their breakdown chart, data quality
  panels, notes, countdowns, GPS maps, embedded HTML and a data-freshness
  panel.
- Every widget is editable in place — what it shows, its title, its size — and
  can be moved to another page.
- Filter controls per page, so each page asks its own question.
- Dashboard appearance: background colour or image, canvas width, grid columns
  and row height, per-dashboard widget transparency, and a colour for the page
  tab strip.
- A choice of chart palettes, each an ordering of the same validated hues,
  ranked by how far apart neighbouring series stay for colour-blind readers.
- Read-only public links for people who should not have accounts.
- Roles: viewer, analyst, manager, administrator.
- API keys for scripts, plus an OpenAPI spec at `/api/docs`.

---

## Install on Ubuntu

Ubuntu 22.04 or 24.04, 4 GB RAM minimum (8 GB recommended for large surveys).
Nothing else is needed — the installer adds Docker if it is missing.

### 1. Get the code onto the server

The repository is private, so the server needs to authenticate. The simplest way
is a GitHub personal access token with `repo` scope
([create one here](https://github.com/settings/tokens)):

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/mojeeq/surveyHQ.git surveyhq
# Username: mojeeq
# Password: paste the personal access token (not your GitHub password)
cd surveyhq
```

That is everything — the platform lives on `main`.

### 2. Run the installer

```bash
./scripts/install-ubuntu.sh
```

It installs Docker if needed, generates `.env` with fresh secrets, asks for an
administrator email and a port, builds the images and starts everything.

It prints the URL, the administrator email and the generated password when it
finishes. **Write the password down** — it is stored only in `.env`.

### 3. Open it

```
http://your-server-ip:8080
```

Sign in with the administrator account the installer printed.

> First run builds several images and takes about five to ten minutes. Later
> starts take seconds.

### Manual install

If you already have Docker and prefer to do it yourself:

```bash
cp .env.example .env
nano .env                 # set every CHANGE-ME value
docker compose up -d --build
```

Generate the two secrets with:

```bash
openssl rand -hex 32                                          # SECRET_KEY
docker compose run --rm api python -m app.cli gen-encryption-key   # ENCRYPTION_KEY
```

`ENCRYPTION_KEY` encrypts stored Survey Solutions passwords. **Back it up.** If
you lose it, saved server credentials cannot be decrypted and must be re-entered.

---

## Day-to-day operation

```bash
make up                # build and start
make down              # stop (data is kept)
make logs              # follow all logs
make ps                # service status
make backup            # database + datasets into ./backups
make restore FILE=...  # restore a backup
make update            # pull and rebuild
make test              # run the backend test suite
make create-admin EMAIL=you@org PASS=secret
make reset-password EMAIL=you@org PASS=newsecret
make help              # everything else
```

---

## Connecting to Survey Solutions

1. On your Survey Solutions server, create an **API user** and give it access to
   the workspace holding your survey.
2. In SurveyHQ go to **Connections → Add connection** and enter the server URL
   (the site root, e.g. `https://demo.mysurvey.solutions`), the workspace name
   (usually `primary`), and the API user's credentials. Pick the project the
   imports should land in.
3. Press **Test connection**. It reports how many questionnaires the account can
   see, which confirms both the URL and the permissions.
4. Save, then press **Import data** and pick the questionnaires you want.

Each questionnaire's export becomes one dataset per file in it — the interview
level, every roster level and the paradata. Re-importing **replaces** those
datasets in place, so saved charts, dashboards, indicators, quality rules,
relationships, merges and derived variables keep working.

Turn on **Import automatically** to have the scheduler pull new interviews,
either on an interval or at set times of day (e.g. 06:00 and 18:00) read in the
connection's own timezone. The export zip of each run is kept and can be
downloaded from the connection's history.

Stata is the recommended export format because it carries variable and value
labels. See [docs/survey-solutions.md](docs/survey-solutions.md) for the details
and for troubleshooting.

---

## How it fits together

```
      Browser
         │
    ┌────▼─────┐   static bundle + /api proxy
    │  nginx   │   (web, port 8080)
    └────┬─────┘
         │
    ┌────▼─────┐   REST API, auth, query compilation
    │ FastAPI  │   (api, port 8000)
    └──┬───┬───┘
       │   │
       │   └──────────────┐
  ┌────▼─────┐      ┌─────▼──────┐
  │ Postgres │      │   Redis    │
  │ metadata │      │   queue    │
  └──────────┘      └─────┬──────┘
                          │
                 ┌────────▼─────────┐   imports, indicator refresh,
                 │ Celery worker    │   quality checks, pruning
                 │ + beat scheduler │
                 └──────────────────┘

  Survey data itself lives as Parquet files on a Docker volume and is
  queried in-process with DuckDB. Postgres holds only metadata: users,
  datasets, variables, charts, dashboards, indicators, alerts, jobs.
```

Storing data as Parquet and querying it with DuckDB means a survey with hundreds
of thousands of interviews tabulates in milliseconds without loading anything
into Postgres, and adding a dataset never means migrating a schema.

More in [docs/architecture.md](docs/architecture.md).

---

## Security

- Passwords are hashed with bcrypt; sessions use signed JWTs.
- Survey Solutions passwords are encrypted at rest with Fernet, because the API
  needs the real password on every call and cannot use a hash.
- Four roles gate every write: viewer < analyst < manager < administrator.
- Project access is enforced where a dataset, dashboard, chart, connection,
  alert rule or alert is looked up, not route by route, so it covers the query endpoints too - listing alone would
  leave a dataset readable to anyone who knew its id. A resource outside your
  reach answers 404 rather than 403, so responses cannot be used to enumerate
  other people's projects.
- Every query is compiled server-side. Variable names are checked against the
  dataset's registered variables and literals are always bound as parameters, so
  a query specification cannot inject SQL.
- Public dashboard links are opt-in per dashboard and carry a random token.
- Stata-style commands are parsed into a recognised set of operators and
  functions before any SQL is built, so what runs is only ever what was
  understood — never the text as typed.
- Embedded HTML renders in a sandboxed frame with no access to the page around
  it, and uploaded dashboard backgrounds are identified from their bytes rather
  than their name or content type (SVG is refused: it can carry script).
- Security-relevant actions are recorded in an audit log.

Before exposing the platform to the internet, read the TLS and hardening section
in [docs/deployment.md](docs/deployment.md).

---

## Documentation

| Document | What it covers |
|---|---|
| [docs/deployment.md](docs/deployment.md) | Production install, TLS, backups, upgrades, troubleshooting |
| [docs/survey-solutions.md](docs/survey-solutions.md) | Connecting, importing, scheduling, common errors |
| [docs/user-guide.md](docs/user-guide.md) | Projects, getting data in, deriving variables, analysing, building dashboards, setting up monitoring |
| [docs/api.md](docs/api.md) | REST API and API keys, with examples |
| [docs/architecture.md](docs/architecture.md) | How the pieces work and why |

---

## Development

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests -q

# Frontend
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to localhost:8000

# Both, with hot reload for the API
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

---

## Licence

Provided as-is for you to run and modify.

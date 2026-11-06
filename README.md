<img src="frontend/public/logo.svg" width="56" alt="">

# SurveyHQ

SurveyHQ is a self-hosted platform for monitoring survey and census fieldwork.
You connect it to a Survey Solutions server, or upload Stata, SPSS, CSV or Excel
files, and then use tables, charts, dashboards, indicators, alerts and automatic
quality checks to follow the data as it comes in.

It is a working prototype that shows how automated, close-to-real-time
monitoring can be built using data pipeline model.

SurveyHQ is designed for surveys that are still in the field. When a new export
arrives it replaces the existing data in place, so the charts, indicators,
quality rules and dashboards built on that data keep working without any
changes.

It runs on Ubuntu with Docker and installs with a single command.

---

## Features

### Getting data in

- Import interview data from a Survey Solutions headquarters server through its
  export API: on demand, at a fixed interval, or at set times of day in the
  connection's time zone.
- Upload Stata (`.dta`), SPSS (`.sav`), CSV, tab-delimited or Excel files, or a
  `.zip` export archive.
- Each file in an archive becomes its own dataset (interview level, each roster
  level and the paradata).
- By default a newer archive replaces the datasets it matches and keeps their
  IDs. Choose **append** instead if your exports are incremental.
- Several archives uploaded together are appended, one dataset per file, with
  each row tagged with the questionnaire version it came from. This is useful
  when the questionnaire changes during fieldwork. Connections add the version
  automatically.
- Large uploads are processed by a background worker, so you don't need to keep
  the browser open.
- Variable and value labels are kept, and you can add your own where the export
  has none.

### Analysis

- One-way frequency tables with valid and cumulative percentages.
- Cross-tabulations with row, column and total percentages, chi-square and
  Cramér's V, up to 5,000 rows.
- Grouped summaries: count, sum, mean, median, percentiles, standard deviation
  and distinct count, with optional survey weights.
- Filters with nested AND/OR conditions. You can build them row by row or type
  them the way you would write a Survey Solutions condition, for example
  `age.InRange(15, 49) && sex == "Female"`. Arithmetic works on both sides
  (`inc2020 - inc2019 > 100`, `total != boys + girls`), and the box suggests
  variables, functions and value labels as you type.
- Binning for numeric variables, and day, week, month, quarter or year grouping
  for dates.
- Chart types: bar, horizontal bar, stacked and horizontal stacked bar,
  population pyramid, line, area, pie, donut, scatter, box plot, heatmap and
  table. You can set the sort order, top-N, value labels, 100% stacking, axis
  titles and ranges, and add a target line.
- "Select all that apply" questions are tabulated from their 0/1 columns as a
  single table.
- A Stata-style command box for preparing data (`gen`, `replace`, `egen` with
  `by()`, `label`, `rename`, `destring`, `drop`, `keep`, with `if` conditions).
  Commands are saved with the dataset and run again after each new export, so
  derived variables are not lost.
- Export any result to CSV or Excel, or download a whole dataset as Stata (with
  labels), CSV or Excel.

### Monitoring

- **Indicators**: a tracked number with a target and warning and critical
  thresholds. An indicator can be a percentage, and can be broken down by
  region, team or interviewer. Its history is stored so you can see the trend.
- **Alerts**: rules that watch indicators and send an in-app or email alert when
  a threshold is crossed. A cooldown stops repeat alerts for the same problem.
- **Data quality checks**: missing values, out-of-range values, duplicates,
  likely duplicates (similar names, ages and dates of birth), outliers, short
  interviews, missing GPS, constant answers and custom logic conditions.
  SurveyHQ recommends checks for each dataset and runs them again after every
  import.
- **GPS quality map**: compares each record's recorded enumeration area with the
  boundary its GPS reading falls in, flags readings that are too close to
  another record, compares hand-entered locations with GPS readings, and shades
  the areas that have been visited. Each check is a separate layer with a count.
- **Field progress**: submissions over time, interviews per interviewer and
  supervisor, status breakdown, coverage by area and a map of GPS points. These
  are built automatically from standard Survey Solutions column names.
- Monitoring, data quality and alerts can be filtered to a single project.

### Projects and access

- A project holds a survey round's datasets and dashboards and controls who can
  see them. Anything not in a project is in the shared area, which all users can
  see.
- When you delete a project you can either move its contents to the shared area
  or delete everything in it.
- Relationships between a project's datasets are detected automatically and
  shown as a diagram. You can correct them, add them by hand or clear them.
- Two related datasets can be merged into a new dataset that rebuilds itself
  when its sources change. You can also bring variables from one dataset into
  another existing dataset without changing its rows, so charts built on it
  keep working.
- Users can be limited to the projects they are assigned to. A user's role in a
  project can never be higher than their overall role.

### Dashboards and sharing

- Dashboards with drag-and-drop widgets on named pages: charts, saved
  cross-tabulations, indicator tiles, data quality panels, notes, countdowns,
  GPS maps, embedded HTML and a data freshness panel.
- Branding: a logo on each side of the header, title size, font, colour and
  alignment, a title band and a page background. These settings carry over to
  shared links. There are 48 ready-made looks, including light, dark and
  coloured themes and a set based on national flag colours.
- Widgets can be grouped under a heading with its own background, and groups can
  be collapsed.
- Each widget has a text size setting that applies to everything in it.
- Widgets can be edited in place and moved to another page.
- Filters per page, plus click-to-filter on bars, slices and table rows.
- Drill-down through levels you define, such as province, district and
  enumeration area.
- Saved views, such as "This week, northern region", available to everyone who
  opens the dashboard, including through shared links. One view can be set as
  the default.
- Threaded comments on widgets.
- **Edit** on a saved chart reopens it in Analyse, and saving updates the chart
  everywhere it is used.
- Appearance settings: background colour or image, canvas width, grid columns
  and row height, widget transparency and tab colour.
- Download a dashboard as a single HTML file that works offline, with working
  filters.
- Publish that file to GitHub Pages or a web server over SFTP or FTP, and
  optionally republish it after every import. **Test** writes a file to the
  destination, so permission problems show up before the first publish.
- Each dashboard shows when it was last updated and when the next update is
  due.
- Chart palettes chosen to stay distinguishable for colour-blind readers.
- Read-only public links, and with a wildcard DNS record and certificate, a
  dashboard can have its own address such as `labour-force.dash.example.org`.
- Roles: viewer, analyst, manager and administrator.
- API keys and an OpenAPI description at `/api/docs`.

---

## Installing on Ubuntu

You need Ubuntu 22.04 or 24.04 with at least 4 GB of RAM (8 GB is better for
large surveys). The installer adds Docker if it isn't already installed.

### 1. Get the code

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/mojeeq/surveyHQ.git surveyhq
cd surveyhq
```

### 2. Run the installer

```bash
./scripts/install-ubuntu.sh
```

The installer installs Docker if needed, creates `.env` with new secrets, asks
for an administrator email address and a port, builds the images and starts the
services.

When it finishes it prints the URL, the administrator email and a generated
password. **Write the password down.** It is only stored in `.env`.

### 3. Sign in

Open `http://your-server-ip:8080` and sign in with the administrator account.

> The first start builds several images and takes 5 to 10 minutes. After that,
> starting takes a few seconds.

### Manual install

If Docker is already installed and you would rather set things up yourself:

```bash
cp .env.example .env
nano .env                 # replace every CHANGE-ME value
docker compose up -d --build
```

To generate the two secrets:

```bash
openssl rand -hex 32                                               # SECRET_KEY
docker compose run --rm api python -m app.cli gen-encryption-key   # ENCRYPTION_KEY
```

`ENCRYPTION_KEY` is used to encrypt stored Survey Solutions passwords. **Keep a
backup of it.** If it is lost, saved server passwords can't be decrypted and
have to be entered again.

For database migrations, import review, dataset versions and backup
compatibility, see the [reliability upgrade notes](docs/reliability-upgrade.md).

---

## Day-to-day commands

```bash
make up                # build and start
make down              # stop (data is kept)
make logs              # follow the logs
make ps                # show service status
make backup            # back up the database and datasets to ./backups
make restore FILE=...  # restore a backup
make update            # pull the latest code and rebuild
make test              # run the backend tests
make create-admin EMAIL=you@org PASS=secret
make reset-password EMAIL=you@org PASS=newsecret
make help              # list all commands
```

Add `STACK=prod` to any command to work on a production stack running next to
the development one on the same server. `make setup STACK=prod` creates it and
`make copy-prod-to-dev` copies production data into development. See
[Development and production on one server](docs/deployment.md#development-and-production-on-one-server).

---

## Connecting to Survey Solutions

1. On your Survey Solutions server, create an **API user** with access to the
   workspace that holds your survey.
2. In SurveyHQ, go to **Connections → Add connection**. Enter the server URL
   (the site root, for example `https://demo.mysurvey.solutions`), the workspace
   name (usually `primary`) and the API user's details, and choose the project
   the data should go into.
3. Click **Test connection**. It shows how many questionnaires the account can
   see, which confirms the URL and the permissions.
4. Save, click **Import data** and choose the questionnaires to import.

Each questionnaire export becomes one dataset per file: the interview level,
each roster level and the paradata. Importing again replaces those datasets in
place, so charts, dashboards, indicators, quality rules, relationships, merges
and derived variables keep working.

Turn on **Import automatically** to have new interviews pulled on a schedule,
either at an interval or at set times (for example 06:00 and 18:00) in the
connection's time zone. Each run's export file is kept and can be downloaded
from the connection's history.

We recommend the Stata export format because it includes variable and value
labels. See [docs/survey-solutions.md](docs/survey-solutions.md) for more detail
and troubleshooting.

---

## Architecture

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

  Survey data is stored as Parquet files on a Docker volume and queried
  in-process with DuckDB. Postgres only holds metadata: users, datasets,
  variables, charts, dashboards, indicators, alerts and jobs.
```

Because the data is stored as Parquet and queried with DuckDB, a survey with
hundreds of thousands of interviews can be tabulated in milliseconds, and adding
a dataset doesn't require a database schema change.

See [docs/architecture.md](docs/architecture.md) for more.

---

## Security

- Passwords are hashed with bcrypt. Sessions use signed JWTs.
- Survey Solutions passwords are encrypted at rest with Fernet. They can't be
  hashed because the API needs the actual password for each request.
- There are four roles: viewer, analyst, manager and administrator. Roles
  control what a user can change. Within the projects they have access to, a
  viewer can read datasets (the Data tab and Analyse) as well as dashboards. To
  restrict someone to one project, use "Limit to assigned projects". To show
  someone a dashboard without giving them an account, use a shared link.
- Project access is checked whenever a dataset, dashboard, chart, connection,
  alert rule or alert is loaded, including by the query endpoints. Requests for
  resources outside a user's access return 404 rather than 403, so the API
  doesn't reveal which projects exist.
- All queries are built on the server. Variable names are checked against the
  dataset's variables and values are always passed as bound parameters, so a
  query can't inject SQL. Arithmetic in filters is parsed into an expression
  tree (numbers, names, `+ - * /` and brackets only) and compiled from that tree.
- Public dashboard links are turned on per dashboard and use a random token.
  Filters sent through a link can only refer to variables the page already
  shows, and this is checked for every column a condition uses.
- The command box never sends the typed text to the database. Commands are
  tokenised, every name must be a variable in the dataset, only a fixed list of
  functions is allowed, and the query is built from the tokens. Only project
  managers can use it, and every run is logged.
- Embedded HTML is shown in a sandboxed frame. Uploaded background images are
  checked by their content, not their file name or declared type, and SVG files
  are rejected because they can contain scripts.
- Security-related actions are recorded in the audit log.

Before putting SurveyHQ on the internet, read the TLS and hardening section of
[docs/deployment.md](docs/deployment.md).

---

## Documentation

The documentation is also available inside the platform under **Help**.
`scripts/build-help.mjs` builds it from the `docs/` folder on every build, so
the in-app help always matches these files.

| Document | Contents |
|---|---|
| [docs/deployment.md](docs/deployment.md) | Production install, TLS, backups, upgrades and troubleshooting |
| [docs/survey-solutions.md](docs/survey-solutions.md) | Connecting, importing, scheduling and common errors |
| [docs/user-guide.md](docs/user-guide.md) | Projects, importing data, derived variables, analysis, dashboards and monitoring |
| [docs/gis-manual.md](docs/gis-manual.md) | Boundary layers, maps, location checks and the data quality map |
| [docs/api.md](docs/api.md) | REST API and API keys, with examples |
| [docs/architecture.md](docs/architecture.md) | How the system is built |

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

Provided as is. You are free to run and modify it.

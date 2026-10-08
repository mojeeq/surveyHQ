# Running a script in R

**Prototype.** Nothing in the platform submits jobs to this yet. It is here so
the isolation and the protocol can be read, reviewed and argued with before
anything depends on them.

The question it exists to answer: can a dataset go out to R and come back
without losing anything, and can the thing that runs it be made safe enough to
hand to an analyst? The first half is tested. The second half is declared in
`docker-compose.yml` and has to be checked on a real host.

## Why this shape

The script engine already works entirely through Parquet files in a temporary
workspace: `stata_frame.load()` copies a dataset's Parquet in, every command
writes a new one, and `settle()` reads the schema back. Nothing passes through
Python. So another language does not need a new data path - it needs a
directory with a file in it.

```
in/data.parquet  ->  [ R, in a container that can reach nothing ]  ->  out/data.parquet
```

## What makes it safe

Everything is in the `runner-r` service, not the image:

| | Why |
|---|---|
| `networks: [sandbox]`, `internal: true` | Docker gives such a network no route off the host. The script cannot reach the internet, the API, Postgres or Redis, whatever it asks for. |
| `environment: {}` | The worker holds `SECRET_KEY`, `ENCRYPTION_KEY` and the database password. This holds none of them, and an empty map rather than an omitted one makes adding one a visible decision. |
| Only `script-work` mounted | A script sees the job it was given, not `/data` and not every project's microdata. |
| `mem_limit`, `cpus`, `pids_limit` | The ceiling the import path did not have. A script that asks for too much fails with a message instead of letting the kernel kill the worker. |
| `cap_drop: [ALL]`, `no-new-privileges`, `read_only`, non-root | The ordinary container hardening, none of it interesting on its own. |

The channel is a directory because the runner can reach nothing else. A queue
would mean giving it Redis, and Redis is then something it can read.

## The protocol

The platform writes, then marks ready:

    <job>/script.R          what to run
    <job>/in/data.parquet   the dataset, as the platform already stores it
    <job>/in/labels.json    {"variable_labels": {...}, "value_labels": {...}}
    <job>/READY             written last

The runner claims it, runs it, writes, then marks done:

    <job>/CLAIMED
    <job>/out/data.parquet  whatever the script left in `data`
    <job>/out/labels.json   the labels read back off it
    <job>/result.json       {"ok", "error", "rows", "columns", "seconds"}
    <job>/log.txt           whatever the script printed
    <job>/DONE              written last

Each side writes its marker last and neither reads before seeing the other's,
so neither can act on a half-written job. `app/services/sandbox.py` is the
platform's half.

## The contract a script sees

There is one table in memory, called `data`, and whatever `data` holds at the
end is what gets written. The same contract as the command box.

```r
data$adult <- as.integer(data$age >= 18)
labelled::var_label(data$adult) <- "Aged 18 or over"

library(dplyr)
data <- data |>
  group_by(province) |>
  summarise(people = n(), adults = sum(adult)) |>
  as.data.frame()
```

`arrow`, `labelled`, `dplyr` and `jsonlite` are installed.

## Labels

This is the part that would have sunk it quietly. Parquet has no standard place
for variable and value labels, and this platform leans on them everywhere -
axis titles, legends, cross-tab headers, filter dropdowns. They travel in a
JSON file beside the data and are applied onto the frame with `labelled`, so a
script sees `sex` as Male and Female rather than 1 and 2.

On the way back they are read off **what the script produced**, never carried
forward from the input. A script that drops or renames a variable must not have
the old label reappear on the new data; that is how a chart ends up captioned
with the wrong question.

## Running it

```bash
docker compose --profile sandbox up -d --build runner-r
docker compose --profile sandbox logs -f runner-r
```

The profile keeps it out of an ordinary `docker compose up`, since nothing
needs it yet.

## What is tested, and what is not

`backend/tests/test_sandbox_r_roundtrip.py` covers the translation: labels out
and back, a variable the script created, a dropped variable's label not
reappearing, a rename carrying its label, dplyr, a script that fails saying
why, and a script that leaves something that is not a table. Those tests run
the harness directly and skip when R is absent, so they do not hold CI hostage
to an R toolchain.

**They do not test the isolation.** Neither this sandbox nor CI has a Docker
daemon, so nothing here has verified that the container cannot reach the
network, that `mem_limit` stops a runaway, or that the image builds. Before
trusting any of it on a real host, check at least:

```bash
# No route anywhere.
docker compose --profile sandbox exec runner-r \
  Rscript -e 'print(try(url("https://example.com", open="rb")))'

# No secrets.
docker compose --profile sandbox exec runner-r env | grep -Ei 'key|password|postgres' || echo none

# The ceiling holds, and the job fails rather than the host.
# (a script that allocates past mem_limit should come back ok:false)
```

## What is missing before this is a feature

- Nothing submits jobs: no API endpoint, no UI, no language choice on the
  Command tab.
- Reading the result back into a dataset. `settle()` already does this for the
  Stata engine and should be reused rather than reimplemented.
- One job at a time, globally. The loop is single threaded by design, so two
  people running scripts queue behind each other.
- Nothing cleans up finished jobs except `sandbox.discard`, and a job
  directory holds a copy of confidential microdata.
- Timeouts are a fixed 300 seconds rather than anything a project can set.

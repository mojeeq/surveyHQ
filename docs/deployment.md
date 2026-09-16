# Deployment

Production notes for running SurveyHQ on an Ubuntu server.

## Requirements

| | Minimum | Recommended |
|---|---|---|
| Ubuntu | 22.04 | 24.04 LTS |
| CPU | 2 cores | 4 cores |
| RAM | 4 GB | 8 GB |
| Disk | 20 GB | 50 GB+ |

Disk depends on your data. A survey with 100,000 interviews and 500 variables
stores as roughly 100-200 MB of Parquet, because Parquet is columnar and
compressed. Budget for keeping several rounds.

Four other things share that volume: the uploads as received, the last five
export archives per connection (tens of megabytes each), dashboard background
and logo images (8 MB each at most), and boundary layers, which are stored as
GeoJSON and are usually a few megabytes for a national enumeration-area frame.
The archives prune themselves as new runs land; nothing else does.

## Install

```bash
git clone <your-repository-url> surveyhq
cd surveyhq
./scripts/install-ubuntu.sh
```

The installer is idempotent: run it again and it keeps an existing `.env`.

## Configuration

Everything lives in `.env`. Values worth attention:

| Setting | Notes |
|---|---|
| `SECRET_KEY` | Signs session tokens. Changing it signs everyone out. |
| `ENCRYPTION_KEY` | Encrypts stored Survey Solutions passwords. **Losing it means re-entering every server credential.** |
| `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` | Used only on the very first boot, when no users exist. |
| `PUBLIC_URL` | The URL people use. Appears in alert emails, and is a name no dashboard may take. |
| `DASHBOARD_DOMAIN` | The domain shared dashboards are named under, e.g. `dash.example.org`. Needs the wildcard DNS record and certificate above. Empty hides the feature. |
| `CORS_ORIGINS` | Comma separated. Must include your real domain in production. |
| `WEB_PORT` | Host port for the web interface. Default 8080. |
| `MAX_UPLOAD_MB` | The upload ceiling, and the only one: nginx no longer enforces a second. An upload over it is refused with a message naming the size and the limit, before the body is transferred. It also bounds how far a zip may expand once opened - twenty times this - so an archive built to exhaust memory is refused rather than unpacked. |
| `SIGNUP_ENABLED` | Whether anyone reaching the sign-in page may create their own account. **Off by default** - see below before turning it on. |
| `R_SCRIPTS_ENABLED` | Whether R may be run over a project. Off by default. |
| `R_SANDBOX_REQUIRED` | Whether unconfined R is refused. On by default; see below. |
| `RATE_LIMIT_ENABLED` | Caps sign-in attempts and requests to shared dashboards. Leave it on. Turn it off only if every visitor reaches you from one address, as behind some corporate proxies, where they would share one budget. |
| `SYNC_TICK_MINUTES` | How often the scheduler checks for due imports. A connection set to import at a time of day cannot be honoured more precisely than this. |
| `MONITOR_TICK_MINUTES` | How often indicators, alerts and checks are evaluated. |

After editing `.env`:

```bash
docker compose up -d
```

### Letting people create their own accounts

`SIGNUP_ENABLED=true` puts a **Create account** button on the sign-in page, and
anyone who can reach that page may then make themselves an account. It is off
unless you say otherwise, and it is worth understanding why before you change
that.

A self-service account is a **manager**. A manager may create a project, and
becomes that project's manager. A project's manager may **run R in it**, which
is a program on this server. With the sandbox enforcing, that program is
confined to the stranger's own new project - it cannot read your surveys - but
it is still their code on your processor and your disk. Where the sandbox
cannot be enforced, or has been turned off with `R_SANDBOX_REQUIRED=false`, it
is worse than that: opening sign-up then hands read of every survey on the
server to anyone who can load the page. Even with R off entirely, a stranger
can create an account and take up space.

Turn it on where **at least one** of these is true:

- the sign-in page is not reachable from the public internet - a VPN, an office
  network, or an IP allow-list in front of nginx;
- `R_SCRIPTS_ENABLED` is off and you accept strangers holding empty accounts.

Never turn both this and `R_SANDBOX_REQUIRED=false` on where the sign-in page
is public. That pair is the one combination that gives a stranger your data.

Otherwise leave it off and create accounts yourself under **Administration →
Add user**, which is what a survey office usually wants anyway: the people who
should be in it are known in advance.

With sign-up off, `POST /auth/signup` answers **404**, the same as any unrouted
path, and the sign-in page does not offer the button.

### Withholding small cells

A cross-tabulation cell that rests on two households can identify them, and a
dashboard share link is public by design. Set the floor your office publishes
under and the platform applies it to every cross-tabulation, everywhere one is
shown:

```
DISCLOSURE_THRESHOLD=5
```

`0` is off, which is the default and what an existing deployment gets until
somebody changes it. `5` is the usual floor in official statistics; `3` and
`10` both occur. It is here rather than in the interface on purpose: a rule
anybody can switch off to get a prettier table is not a rule.

What it does:

- **Cells are counted unweighted.** What a cell discloses is the number of
  people behind it, not the number it estimates. A weighted cell reading 12,500
  can rest on one household, and a mean of two incomes discloses those two
  people whatever the mean is.
- **A zero is left alone.** Nobody is identified by an absence, and blanking it
  would only announce that somebody is being protected where nobody is. A
  withheld cell reads `*`; an empty one still reads `-`.
- **Cells are counted by what reaches the statistic**, not by how many rows are
  in the category. Every aggregate ignores nulls and a weighted one ignores a
  null weight, so a province of a hundred people with one reported wage has a
  mean that is that one person's wage.
- **A total is withheld on the same terms as a cell.** A margin is a line sum,
  so it is recoverable arithmetic in both directions: a one-way table's row
  total is its single cell exactly. Margins are protected in the same pass as
  the cells, which is also why a second cell sometimes goes with the first -
  one withheld cell beside a published row total is that total minus the
  others. The smallest neighbour goes, since it costs the reader least.
- **A category too small to publish is not listed at all** on a table set to
  list categories without cell values. There is no cell to blank, and naming
  the category still says those people exist and where they are.
- **No chi-square is reported** for a table with withheld cells, since it would
  be a statistic computed over numbers the reader has been refused.
- **A standalone HTML export carries the finished table** rather than the cube
  it normally carries. The cube is the cell values, so exporting it under a
  floor would write the withheld numbers into a file nobody can withdraw. The
  cost is that a cross-tabulation in an exported file no longer responds to the
  page's filters, and the file says so - on every exported table, not only the
  ones with something starred, since filtering could have cut a large cell down
  to a small one and that is why the cube cannot travel at all.

This covers cross-tabulations, which is what a statistics office publishes.
Charts and KPI tiles are not yet covered, so a bar chart of counts by
enumeration area can still show a bar of two.

### Turning R on

R itself is already in the image, so enabling it is one setting rather than a
server to build. It is **off by default**, because running an R script is
running a program on this machine, sandboxed or not - read
[the user guide](user-guide.md#what-this-is-and-is-not) for what the sandbox
does and does not cover before you turn it on.

**Check the server can confine it first.** A script runs inside a Landlock and
seccomp sandbox, and where the kernel cannot enforce that, the platform refuses
to run R rather than running it unconfined. One command says which you have:

```bash
docker compose exec api surveyhq-check-r-sandbox
```

It reports the kernel, whether the launcher is in the image, and whether the
kernel will actually apply it. Landlock needs **Linux 5.13 or newer** - Ubuntu
22.04 (5.15) and 24.04 (6.8) both qualify - and the `landlock_*` syscalls have
to reach the kernel, which Docker's default seccomp profile permits.

Then set it in `.env`:

```bash
R_SCRIPTS_ENABLED=true
docker compose up -d api worker
docker compose exec api printenv R_SCRIPTS_ENABLED   # should print: true
```

The worker needs it too, which `docker-compose.yml` handles - both services
share one environment block. `R_TIMEOUT_SECONDS` (60) and `R_MEMORY_MB` (2048)
bound one run.

**If the check says the sandbox cannot be enforced**, the interface will say so
too and R will stay unavailable. The way round it is deliberate and worth
understanding before you use it:

```bash
R_SANDBOX_REQUIRED=false
```

That runs scripts unconfined, which is what the platform did before the sandbox
existed: any project's script can then read every other project's data files on
the server, and reach anything the server can reach. Use it only where everyone
who can run R in any project is someone you would trust with a shell on that
machine.

## Putting it behind HTTPS

The stack serves plain HTTP on `WEB_PORT`, bound for a reverse proxy in front.
The API container is deliberately published only on `127.0.0.1`, so it is never
reachable from outside the host.

### Caddy (simplest - certificates handled for you)

```bash
sudo apt install -y caddy
```

`/etc/caddy/Caddyfile`:

```
surveyhq.example.org {
    reverse_proxy localhost:8080
    request_body {
        max_size 1GB
    }
}
```

```bash
sudo systemctl reload caddy
```

### nginx + certbot

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/surveyhq`:

```nginx
server {
    listen 80;
    server_name surveyhq.example.org;

    client_max_body_size 1024m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/surveyhq /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d surveyhq.example.org
```

Then set both in `.env` and restart:

```
PUBLIC_URL=https://surveyhq.example.org
CORS_ORIGINS=https://surveyhq.example.org
```

The long `proxy_read_timeout` matters: importing a large questionnaire from
Survey Solutions can keep a request open for minutes.

## Giving dashboards their own addresses

A shared dashboard can answer on its own subdomain - `labour-force.dash.example.org`
rather than a link ending in a 64-character token. The platform side is one
setting; the rest is DNS and a certificate, done once for all dashboards
present and future.

**1. One wildcard DNS record.** Point every name under your chosen domain at
this server:

```
*.dash.example.org.   A   203.0.113.10
```

**2. One wildcard certificate.** Let's Encrypt issues wildcards only through
the DNS-01 challenge, which proves control by writing a TXT record - so this
needs an API token for wherever your DNS is hosted. Caddy is the least work:

```
{
    # The DNS provider plugin has to be in the build:
    #   xcaddy build --with github.com/caddy-dns/cloudflare
    acme_dns cloudflare {env.CLOUDFLARE_API_TOKEN}
}

surveyhq.example.org, *.dash.example.org {
    reverse_proxy localhost:8080
    request_body {
        max_size 2GB
    }
}
```

Both names go to the same place. SurveyHQ decides from the `Host` header
whether a request is the platform or one of its published dashboards, so no
per-dashboard configuration is ever needed. If you use nginx instead, the same
applies: keep `server_name` covering `*.dash.example.org`, pass `Host` through
unchanged (`proxy_set_header Host $host`, which the bundled config already
does), and obtain the wildcard with `certbot --dns-<provider>`.

**3. Tell the platform the domain.** In `.env`:

```
DASHBOARD_DOMAIN=dash.example.org
```

Restart, and **Share link → Give it a name…** appears on every shared
dashboard. Leave the setting empty and the option is hidden, because a name
would resolve to nothing.

### What a name is, and is not

The share link's token is unguessable, which is what makes it safe to send to
one person. A name is the opposite by design - it is meant to be typed from
memory - so a named dashboard is reachable by anyone who guesses the name.
Naming is publishing. The interface says so at the point of naming, and:

- only a dashboard that is already shared can be given a name;
- turning sharing off removes the name with it, so a DNS record never resolves
  to something nobody may read;
- names live under the configured domain only, and the platform's own hostname
  and a list of reserved labels (`www`, `api`, `admin`, …) cannot be taken.

## Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Do not open 8080 once a reverse proxy is in front of it.

## Backups

```bash
make backup                                   # ./backups/surveyhq-<timestamp>.tar.gz
make restore FILE=backups/surveyhq-....tar.gz
```

Each archive holds the database dump, everything on the data volume - Parquet
datasets, uploads, kept export archives and dashboard images - and a copy
of `.env` (which carries `ENCRYPTION_KEY`). Treat archives as secrets.

Nightly at 02:00, keeping the 14 most recent:

```bash
crontab -e
```

```
0 2 * * * cd /home/USER/surveyhq && make backup >> /var/log/surveyhq-backup.log 2>&1
```

Copy archives off the machine. A backup on the same disk is not a backup.

## Upgrades

```bash
cd surveyhq
make backup
make update      # git pull + rebuild + restart
make logs        # watch the rollout
```

The schema is brought up to date at start-up: new tables are created, new
nullable columns are added to existing tables, indexes the models declare but
the database lacks are created, and new values are added to existing PostgreSQL
enum types. Between them these cover every change the schema has needed so far,
and the API logs each one it applies.

The index step matters on databases that have been running a while. `ALTER TABLE
ADD COLUMN` adds the column and nothing else, so every index declared on a column
the models grew later was missing on exactly the installations that had been
upgraded most often - including the unique ones, which are constraints rather
than mere speed. If a unique index cannot be created because rows already violate
it, the error names the index and the platform starts anyway; the duplicate rows
have to be settled by hand before it can be applied.

What is *not* automatic is anything destructive - dropping, renaming or retyping
a column, or adding one that is `NOT NULL` with no default. Those need a real
migration, so check the release notes before upgrading across one. A column that
cannot be added safely is logged as an error at start-up rather than crashing
the server, so look for it in `make logs` after an upgrade.

## Monitoring the platform itself

```bash
make ps                        # health of every container
curl localhost:8080/health     # API and database status
docker stats --no-stream       # resource usage
docker system df               # disk used by images and volumes
```

Each service has a Docker health check, so `docker compose ps` shows
`healthy`/`unhealthy` rather than just "running".

## Scaling

The default is sized for one field team. For a larger operation:

- **More concurrent imports** - raise `--concurrency` on the `worker` service in
  `docker-compose.yml`, or run several worker containers.
- **More concurrent users** - raise `--workers` on the `api` service. Roughly
  one worker per CPU core.
- **Large datasets** - DuckDB is capped at 2 GB per query in
  `backend/app/services/query_engine.py` (`memory_limit`). Raise it if the host
  has the RAM.

## Troubleshooting

**The web page will not load**

```bash
make ps                        # is `web` up?
docker compose logs web
sudo ss -tlnp | grep 8080      # something else on the port?
```

**"Could not reach the server" in the browser**

The API container is down or unhealthy.

```bash
docker compose logs api --tail=50
curl localhost:8080/health
```

**Every request answers 502, including signing in, but `api` is healthy**

nginx resolves the `api` name once, when its configuration is loaded, and holds
that address for the life of the process. Rebuild or recreate the API container
and it usually comes back on a different address inside the Docker network -
which nginx does not know, so it goes on sending requests to an address nothing
is listening on. `docker compose ps` shows `api` healthy and `web` unhealthy at
the same time, which is the tell.

Restarting the web container is the whole fix, and it takes a second:

```bash
docker compose restart web
curl -s localhost:8080/health          # expect {"status":"ok"}
```

Do this after any `docker compose up -d --build` that recreated `api` while
`web` stayed up.

**A large upload never finishes**

Uploads over 48 MB are imported by the worker, so the file is transferred, a
job is created, and nothing happens if the worker is not running. The job says
so under **Administration → Background jobs**.

**Imports stay queued forever**

The worker or Redis is down.

```bash
docker compose logs worker --tail=50
docker compose restart worker beat
```

**"Stored secret could not be decrypted"**

`ENCRYPTION_KEY` changed since the credentials were saved. Restore the old key
from a backup, or open each connection and re-enter its password.

**Out of disk**

```bash
docker system df
docker system prune -a          # removes unused images (not your volumes)
```

Datasets live in the `survey-data` volume; deleting a dataset in the interface
removes its files, and deleting a project with its contents removes all of
theirs. Kept export archives (`sync-archives/`) are the usual surprise on a
server with several busy connections; the five most recent per connection are
kept and the rest are deleted as new runs land.

**Reset the administrator password**

```bash
make reset-password EMAIL=admin@example.org PASS=new-password
```

**Start over completely** (deletes all data):

```bash
make clean
```

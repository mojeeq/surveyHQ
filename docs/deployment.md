# Deployment

Production notes for running susoDash on an Ubuntu server.

## Requirements

| | Minimum | Recommended |
|---|---|---|
| Ubuntu | 22.04 | 24.04 LTS |
| CPU | 2 cores | 4 cores |
| RAM | 4 GB | 8 GB |
| Disk | 20 GB | 50 GB+ |

Disk depends on your data. A survey with 100,000 interviews and 500 variables
stores as roughly 100–200 MB of Parquet, because Parquet is columnar and
compressed. Budget for keeping several rounds.

Three other things share that volume: the uploads as received, the last five
export archives per connection (tens of megabytes each), and dashboard
background and logo images (8 MB each at most). The archives prune themselves as new runs
land; nothing else does.

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
| `MAX_UPLOAD_MB` | The upload ceiling, and the only one: nginx no longer enforces a second. An upload over it is refused with a message naming the size and the limit, before the body is transferred. It also bounds how far a zip may expand once opened — twenty times this — so an archive built to exhaust memory is refused rather than unpacked. |
| `RATE_LIMIT_ENABLED` | Caps sign-in attempts and requests to shared dashboards. Leave it on. Turn it off only if every visitor reaches you from one address, as behind some corporate proxies, where they would share one budget. |
| `SYNC_TICK_MINUTES` | How often the scheduler checks for due imports. A connection set to import at a time of day cannot be honoured more precisely than this. |
| `MONITOR_TICK_MINUTES` | How often indicators, alerts and checks are evaluated. |

After editing `.env`:

```bash
docker compose up -d
```

## Putting it behind HTTPS

The stack serves plain HTTP on `WEB_PORT`, bound for a reverse proxy in front.
The API container is deliberately published only on `127.0.0.1`, so it is never
reachable from outside the host.

### Caddy (simplest — certificates handled for you)

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

A shared dashboard can answer on its own subdomain — `labour-force.dash.example.org`
rather than a link ending in a 64-character token. The platform side is one
setting; the rest is DNS and a certificate, done once for all dashboards
present and future.

**1. One wildcard DNS record.** Point every name under your chosen domain at
this server:

```
*.dash.example.org.   A   203.0.113.10
```

**2. One wildcard certificate.** Let's Encrypt issues wildcards only through
the DNS-01 challenge, which proves control by writing a TXT record — so this
needs an API token for wherever your DNS is hosted. Caddy is the least work:

```
{
    # The DNS provider plugin has to be in the build:
    #   xcaddy build --with github.com/caddy-dns/cloudflare
    acme_dns cloudflare {env.CLOUDFLARE_API_TOKEN}
}

susodash.example.org, *.dash.example.org {
    reverse_proxy localhost:8080
    request_body {
        max_size 2GB
    }
}
```

Both names go to the same place. susoDash decides from the `Host` header
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
one person. A name is the opposite by design — it is meant to be typed from
memory — so a named dashboard is reachable by anyone who guesses the name.
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

Each archive holds the database dump, everything on the data volume — Parquet
datasets, uploads, kept export archives and dashboard images — and a copy
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
upgraded most often — including the unique ones, which are constraints rather
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

- **More concurrent imports** — raise `--concurrency` on the `worker` service in
  `docker-compose.yml`, or run several worker containers.
- **More concurrent users** — raise `--workers` on the `api` service. Roughly
  one worker per CPU core.
- **Large datasets** — DuckDB is capped at 2 GB per query in
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

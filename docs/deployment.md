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
stores as roughly 100–200 MB of Parquet, because Parquet is columnar and
compressed. Budget for keeping several rounds.

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
| `PUBLIC_URL` | The URL people use. Appears in alert emails. |
| `CORS_ORIGINS` | Comma separated. Must include your real domain in production. |
| `WEB_PORT` | Host port for the web interface. Default 8080. |
| `MAX_UPLOAD_MB` | Upload ceiling. Raise `client_max_body_size` in `frontend/nginx.conf` to match if you go above 1 GB. |
| `SYNC_TICK_MINUTES` | How often the scheduler checks for due imports. |
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

Each archive holds the database dump, all Parquet datasets, and a copy of
`.env` (which carries `ENCRYPTION_KEY`). Treat archives as secrets.

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
nullable columns are added to existing tables, and new values are added to
existing PostgreSQL enum types. Between them these cover every change the schema
has needed so far, and the API logs each one it applies.

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
removes its files.

**Reset the administrator password**

```bash
make reset-password EMAIL=admin@example.org PASS=new-password
```

**Start over completely** (deletes all data):

```bash
make clean
```

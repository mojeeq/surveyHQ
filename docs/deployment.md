# Deployment

How to install and run SurveyHQ on an Ubuntu server.

## Requirements

| | Minimum | Recommended |
|---|---|---|
| Ubuntu | 22.04 | 24.04 LTS |
| CPU | 2 cores | 4 cores |
| RAM | 4 GB | 8 GB |
| Disk | 20 GB | 50 GB+ |

How much disk you need depends on your data. A survey with 100,000 interviews and
500 variables takes about 100–200 MB as Parquet. Allow space for several survey
rounds.

The same disk also holds:

- uploaded files
- the last five export archives for each connection (tens of megabytes each)
- dashboard background and logo images (up to 8 MB each)
- boundary layers (usually a few megabytes each)

Old export archives are deleted automatically. Nothing else is.

## Install

```bash
git clone <your-repository-url> surveyhq
cd surveyhq
./scripts/install-ubuntu.sh
```

You can run the installer again safely. It keeps your existing `.env`.

## Configuration

All settings are in `.env`. The main ones are:

| Setting | Notes |
|---|---|
| `SECRET_KEY` | Signs session tokens. Changing it signs everyone out. |
| `ENCRYPTION_KEY` | Encrypts stored Survey Solutions passwords. **If you lose it, you'll have to enter every server password again.** |
| `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` | Only used the first time the platform starts, when there are no users. |
| `PUBLIC_URL` | The address people use. Used in alert emails. No dashboard can use this name. |
| `DASHBOARD_DOMAIN` | The domain for dashboard addresses, for example `dash.example.org`. Needs a wildcard DNS record and certificate (see below). Leave empty to turn the feature off. |
| `CORS_ORIGINS` | Comma separated. Must include your domain in production. |
| `WEB_PORT` | Port for the web interface. Default 8080. |
| `MAX_UPLOAD_MB` | Maximum upload size. Default 20480 (20 GB). Larger uploads are refused before they are sent, with a message giving the size and the limit. It also limits how large a zip can be once unpacked: 20 times this value or `MAX_EXTRACTED_GB`, whichever is smaller. See *What a large upload costs* below before raising it. |
| `MAX_EXTRACTED_GB` | Maximum size of an unpacked zip. Default 64. The error message says which of the two limits was reached. |
| `DATASET_VERSIONS_KEEP` | Restore points kept per dataset. Default 10. 0 keeps every version. |
| `STORAGE_CLEANUP_DELETE` | Whether the nightly storage check removes unused dataset files. Default `false`, which only reports them. See *Disk space* below. |
| `STORAGE_CLEANUP_GRACE_HOURS` | How old an unused file must be before it can be removed. Default 24, minimum 6. |
| `SIGNUP_ENABLED` | Lets people create their own account from the sign-in page. **Off by default.** Read the section below before turning it on. |
| `RATE_LIMIT_ENABLED` | Limits sign-in attempts and requests to shared dashboards. Leave it on, unless all your users come from one IP address (for example behind a company proxy). |
| `SYNC_TICK_MINUTES` | How often the scheduler checks for imports that are due. Scheduled times can't be more precise than this. |
| `MONITOR_TICK_MINUTES` | How often indicators, alerts and checks are updated. |

Administrators can also change some of these in **Administration → Settings**:
the upload limit, the unpacked zip limit, the three storage settings, the two scheduler intervals, the
analytics cache, the DuckDB CSV threshold, the monitoring precompute, SMTP
settings, sign-ups, the rate limit and the disclosure threshold. Values set there
override `.env`, which keeps the defaults. The Settings page shows where each
value comes from and lets you reset it.

After editing `.env`, run:

```bash
docker compose up -d
```

### Letting people create their own accounts

With `SIGNUP_ENABLED=true`, the sign-in page shows a **Create account** button and
anyone who can reach the page can create an account.

New accounts get the **manager** role. A manager can create projects, upload and
change data in their own projects and use disk space. They can't see projects
they haven't been added to.

Only turn this on if the sign-in page isn't reachable from the public internet,
for example behind a VPN, on an office network or with an IP allow-list in front
of nginx.

Otherwise leave it off and create accounts yourself in **Administration → Add
user**.

With sign-up off, `POST /auth/signup` returns **404** and the sign-in page doesn't
show the button.

### Withholding small cells

Small cells in a cross-tabulation can identify individual households, and share
links are public. To hide small cells in every cross-tabulation, set:

```
DISCLOSURE_THRESHOLD=5
```

`0` turns it off. This is the default. `5` is common in official statistics;
some offices use `3` or `10`.

How it works:

- **Cells are counted unweighted.** What matters is the number of people in the
  cell, not the weighted estimate.
- **Zeros are shown.** An empty cell doesn't identify anyone. Hidden cells show
  `*`; empty cells still show `-`.
- **Cells are counted by the records used for the statistic.** Missing values and
  missing weights aren't counted. For example, a mean based on one reported wage
  is hidden, even if the category has a hundred people.
- **Totals are hidden in the same way as cells.** Sometimes a second cell is also
  hidden, so a hidden cell can't be worked out from the total. The smallest
  neighbouring cell is chosen.
- **Categories that are too small are left out** of tables that list categories
  without values.
- **No chi-square is shown** for tables with hidden cells.
- **Standalone HTML exports include the finished table** instead of the underlying
  data. This means cross-tabulations in exported files don't respond to filters.
  The file says this on every exported table.

This only applies to cross-tabulations. Charts and indicator tiles aren't covered
yet.

## Security headers

The included nginx sets these headers on every response:

| Header | Value |
| --- | --- |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `SAMEORIGIN` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | camera, microphone, geolocation, payment and USB denied |
| `Content-Security-Policy` | see below |
| `Strict-Transport-Security` | one year, including subdomains, **only over HTTPS** |

HSTS is only sent for HTTPS requests, which the container detects from
`X-Forwarded-Proto`. If you terminate TLS yourself, pass that header through. The
reverse proxy examples below already do.

### What the content security policy covers

The policy blocks injected `<base>` tags and plugins, and stops other sites
putting the page in a frame.

It doesn't restrict scripts, images, frames or connections. This is because:

- The Embedded HTML widget shows whatever HTML a dashboard author pastes in (for
  example a logo, a video or links). Its iframe inherits the page's policy, so a
  strict policy would break embedded videos.
- **Map tiles** accepts any tile server URL, so a fixed list of tile hosts would
  break offline installations.

A stricter policy would need embedded HTML to be served as a separate response
with its own headers.

Values from survey data are escaped before they are shown in charts and map
tooltips. That is what stops survey answers running as script. The policy is an
extra layer, not a replacement.

`Permissions-Policy` denies camera, microphone, geolocation, payment and USB. The
platform doesn't use any of them. Embedded HTML can't use them either, because
its frame is sandboxed without `allow-same-origin` and has no `allow=` attribute.

## Putting it behind HTTPS

SurveyHQ serves plain HTTP on `WEB_PORT`, so put a reverse proxy in front of it.
The API container is only published on `127.0.0.1`, so it can't be reached from
outside the server.

### Caddy (simplest, certificates are handled for you)

```bash
sudo apt install -y caddy
```

`/etc/caddy/Caddyfile`:

```
surveyhq.example.org {
    reverse_proxy localhost:8080
}
```

Don't set a `request_body` limit. SurveyHQ has its own upload limit and gives a
clear message when a file is too large. A smaller limit in Caddy refuses the file
first with a plain `413` error.

```bash
sudo systemctl reload caddy
```

### nginx and certbot

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/surveyhq`:

```nginx
server {
    listen 80;
    server_name surveyhq.example.org;

    # No size limit and no request buffering. SurveyHQ sets the upload limit
    # and explains it when a file is too large. nginx's default is 1 MB, and
    # any limit here refuses larger files with a plain 413.
    client_max_body_size 0;
    proxy_request_buffering off;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/surveyhq /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d surveyhq.example.org
```

Then set these in `.env` and restart:

```
PUBLIC_URL=https://surveyhq.example.org
CORS_ORIGINS=https://surveyhq.example.org
```

The long `proxy_read_timeout` is needed because large Survey Solutions imports
can keep a request open for several minutes.

## Giving dashboards their own addresses

A shared dashboard can have its own subdomain, such as
`labour-force.dash.example.org`, instead of a link with a 64-character token. You
only need to set this up once for all dashboards.

**1. Add a wildcard DNS record** pointing every name under your domain to this
server:

```
*.dash.example.org.   A   203.0.113.10
```

**2. Get a wildcard certificate.** Let's Encrypt only issues wildcard certificates
through the DNS-01 challenge, so you need an API token for your DNS provider.
With Caddy:

```
{
    # The DNS provider plugin has to be in the build:
    #   xcaddy build --with github.com/caddy-dns/cloudflare
    acme_dns cloudflare {env.CLOUDFLARE_API_TOKEN}
}

surveyhq.example.org, *.dash.example.org {
    reverse_proxy localhost:8080
}
```

Both names go to the same place. SurveyHQ uses the `Host` header to tell whether a
request is for the platform or a dashboard, so you don't need to configure each
dashboard. If you use nginx, make sure `server_name` includes
`*.dash.example.org`, pass the `Host` header through unchanged
(`proxy_set_header Host $host`, as in the example above) and get the wildcard
certificate with `certbot --dns-<provider>`.

**3. Set the domain** in `.env`:

```
DASHBOARD_DOMAIN=dash.example.org
```

Restart. **Share link → Give it a name…** now appears on shared dashboards. If the
setting is empty, the option is hidden.

### Things to know about dashboard names

A share link token can't be guessed, but a name is meant to be easy to remember,
so anyone who guesses it can open the dashboard. Giving a dashboard a name is the
same as publishing it. The app warns about this when you add a name.

- Only shared dashboards can have a name.
- If you stop sharing a dashboard, its name is removed.
- Names only work under the configured domain. The platform's own hostname and
  reserved names (`www`, `api`, `admin` and others) can't be used.

## Publishing dashboards to other web servers

Dashboards can be published to GitHub Pages or to a web server over SFTP or FTP
(see *Publishing to a website* in the user guide). The platform sends the pages
out, so it can run on an office network or a laptop with no incoming
connections.

It only needs **outgoing** access from the server that runs the API and worker:

| Destination | Needs access to |
|---|---|
| GitHub Pages | `api.github.com` on port 443 (or your GitHub Enterprise server) |
| SFTP | the web server's SSH port, usually 22 |
| FTP / FTPS | port 21 and the server's passive data ports |

No incoming ports are needed.

Set up destinations in **Administration → Publishing**. Tokens, passwords and keys
are encrypted with `ENCRYPTION_KEY`, so if you change the key you'll need to
enter them again. An SFTP destination saves the server's host key the first time
you test it and refuses the server if the key changes.

SFTP publishing uses `paramiko`. `make update` rebuilds the images with it. For a
manual install, run `pip install -r requirements.txt` again.

## Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Don't open port 8080 once you have a reverse proxy in front of it.

## Keeping the sign-in page off the open internet

Sign-in attempts are rate-limited and self-service sign-up is off by default, but
it is safer if the sign-in page can't be reached from the internet at all. You can
do this in front of SurveyHQ without changing SurveyHQ itself.

Whatever you choose, keep these paths open or share links will stop working:

| Path | What it is |
|---|---|
| `/shared/…` | the shared dashboard page |
| `/assets/…` | scripts and styles for that page |
| `/api/v1/public/…` | the shared dashboard's data, logos and boundaries |
| `/health`, `/health/live`, `/health/ready` | the health checks, if you monitor them from outside |

Dashboards on their own addresses (`*.DASHBOARD_DOMAIN`) are share links too.

**Cloudflare Access** (free for up to 50 users) is the easiest option if the site
is already behind Cloudflare.

1. Add a self-hosted application for the platform's address, with a policy that
   allows your staff's email addresses (one-time code by email, or Google or
   Microsoft sign-in).
2. Add a second application for the paths above with the **Bypass** action.

Users then have to pass Cloudflare's sign-in before they can reach SurveyHQ's, and
Cloudflare keeps a log.

**Office or VPN only, with nginx.** List the addresses that can sign in. Everyone
else gets "not found" for everything except the paths above:

```nginx
geo $staff {
    default        0;
    203.0.113.0/24 1;   # the office
    10.8.0.0/24    1;   # the VPN
}

server {
    # ... as before ...

    location /shared/        { try_files $uri /index.html; }   # open
    location /api/v1/public/ { proxy_pass http://surveyhq_api; } # open, with
                                                                # the headers
                                                                # /api/ sets

    location /api/ {
        if ($staff = 0) { return 404; }
        # ... as before ...
    }
    location /api/v1/datasets/upload {
        if ($staff = 0) { return 404; }
        # ... as before ...
    }
    location / {
        if ($staff = 0) { return 404; }
        # ... as before ...
    }
    # The site icon, shown in the browser tab of shared pages.
    location ~ ^/[^/]+\.(svg|png|ico|webmanifest)$ { try_files $uri =404; }
}
```

Share links still work for everyone. Staff working outside the office connect to
the VPN first.

**Behind Cloudflare's proxy, pass on the visitor's real IP address.** Otherwise
nginx sees Cloudflare's address for every request, so the allow-list doesn't work
and the rate limits treat everyone as one visitor:

```nginx
# In the http block. Cloudflare publishes the current list at
# https://www.cloudflare.com/ips/ - keep it up to date.
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
# ... the rest of Cloudflare's IPv4 and IPv6 ranges ...
real_ip_header CF-Connecting-IP;
```

**Client certificates** are the most secure option. nginx asks for a client
certificate on everything except the paths above (`ssl_verify_client optional`
and a check of `$ssl_client_verify`), and you install a certificate in each staff
member's browser.

## Backups

```bash
make backup                                   # ./backups/surveyhq-<timestamp>.tar.gz
make restore FILE=backups/surveyhq-....tar.gz
```

Each backup contains the database, everything on the data volume (Parquet
datasets and their restore points, uploads, export archives and dashboard
images) and a copy of `.env`, which includes `ENCRYPTION_KEY`. Keep backups
secure. Restore points removed by the storage clean-up are no longer in the
backups taken after that, which also makes the backups smaller.

To back up every night at 02:00 (the 14 most recent are kept):

```bash
crontab -e
```

```
0 2 * * * cd /home/USER/surveyhq && make backup >> /var/log/surveyhq-backup.log 2>&1
```

Copy backups to another machine. A backup on the same disk won't help if the disk
fails.

## Disk space

Every time a dataset's data is replaced, the previous version is kept as a
restore point. Each dataset keeps its newest 10 (`DATASET_VERSIONS_KEEP`).

Every night at 03:45 a storage check works out which dataset files are no
longer needed:

- restore points past the limit
- files left behind by imports that failed or were abandoned
- the folders of datasets that no longer exist

A file is never removed if a dataset uses it now, a listed restore point refers
to it, or an import waiting for review will publish it. Files newer than
`STORAGE_CLEANUP_GRACE_HOURS` (24 by default) are left alone, in case an import
is still writing them.

By default the check only reports. To see the report, go to **Administration →
Background jobs → Storage**. It shows free disk space, space used by datasets
and restore points, and what could be removed. Then either:

- click **Remove unused files** to remove them now, or
- turn on **Remove unused files every night** in **Administration → Settings**
  (or set `STORAGE_CLEANUP_DELETE=true`).

From the command line:

```bash
docker compose exec api python -m app.cli storage-cleanup           # report only
docker compose exec api python -m app.cli storage-cleanup --delete  # remove
```

The Platform status panel warns when less than 10% of the disk is free.

Removed files can only be recovered from a backup, so make sure nightly backups
are running before you turn on automatic removal.

## Upgrades

```bash
cd surveyhq
make backup
make update      # git pull + rebuild + restart
make logs        # watch the restart
```

The database schema is updated when the platform starts. It:

- creates new tables
- adds new nullable columns to existing tables
- creates missing indexes
- adds new values to existing PostgreSQL enum types

Each change is written to the API log.

If a unique index can't be created because existing rows break it, the error
names the index and the platform starts anyway. You'll need to fix the duplicate
rows yourself before the index can be added.

Changes that could lose data aren't automatic, such as dropping, renaming or
changing the type of a column, or adding a `NOT NULL` column with no default.
These need a migration, so check the release notes before upgrading. If a column
can't be added safely, an error is logged at start-up and the server keeps
running. Check `make logs` after upgrading.

## Development and production on one server

You can run two separate stacks on one server: a development stack for testing
changes and imports, and a production stack for real use. Each has its own
containers, database, data volumes, Redis, ports, import folder and secrets.

| | Development | Production |
|---|---|---|
| Settings file | `.env` | `.env.prod` |
| Compose project | `surveyhq` | `surveyhq-prod` |
| Web / API port | 8080 / 8000 | 8081 / 8001 |
| Import folder | `./incoming` | `./incoming-prod` |
| Backups | `./backups` | `./backups/prod` |
| Make commands | `make up`, `make logs`, ... | `make up STACK=prod`, `make logs STACK=prod`, ... |

An existing installation becomes the development stack. Nothing about it changes.

### Setting up production

```bash
make setup STACK=prod        # writes .env.prod with new secrets
nano .env.prod               # PUBLIC_URL, CORS_ORIGINS, FIRST_ADMIN_EMAIL, SMTP
make up STACK=prod
```

Point the reverse proxy for the production address to port 8081 (see *Putting it
behind HTTPS* above). Give development a separate address, or no public address.
Use the same proxy settings for both, especially `client_max_body_size 0`.
Without it, nginx's 1 MB default refuses real exports with "Request failed with
status 413".

`COMPOSE_PROJECT_NAME` in `.env.prod` keeps the two stacks apart. It overrides
`name: surveyhq` in `docker-compose.yml`, so production containers and volumes
are prefixed `surveyhq-prod`. Don't remove it: without it, `make up STACK=prod`
would rebuild the development containers.

### Moving a change to production

Both stacks are built from the same checkout. Test a change on development, commit
it, then rebuild production:

```bash
make up                      # development, with the change
# ...check it...
git commit ...
make backup STACK=prod
make up STACK=prod
```

`make up STACK=prod` won't build if there are uncommitted changes. Use `FORCE=1`
to override this. It prints the branch and commit it builds from.

### Copying production data to development

```bash
make copy-prod-to-dev                                  # take a fresh copy
make copy-prod-to-dev FILE=backups/prod/surveyhq-....tar.gz   # or use a backup
```

This replaces development's database and datasets with production's. It never
changes production. Taking a fresh copy makes a production backup, which stops
production's API and workers until it finishes (this can take several minutes
for a large survey). During working hours, use last night's backup instead. The
command refuses to run if `.env` and `.env.prod` use the same compose project
name.

After copying, development keeps its own secrets:

- Users sign in to development with their production password, but have to sign
  in again.
- Survey Solutions connections can't read production's stored passwords, so they
  won't import until a password is entered on development. This stops
  development pulling data from the live survey server.
- Alert rules are copied with their recipients. Leave `SMTP_HOST` empty in `.env`
  so development doesn't send emails. The command warns you if it is set.

To back up both every night:

```
0 2 * * * cd /home/USER/surveyhq && make backup STACK=prod >> /var/log/surveyhq-backup.log 2>&1
30 2 * * * cd /home/USER/surveyhq && make backup >> /var/log/surveyhq-backup.log 2>&1
```

Two stacks need about twice the memory. Allow 8 GB for both (more for large
surveys), or lower `DUCKDB_MEMORY_LIMIT` and the worker concurrency for
development in `.env`.

## Checking the platform is running

```bash
make ps                          # status of every container
curl localhost:8080/health/ready # can the API serve requests?
docker stats --no-stream         # resource use
docker system df                 # disk used by images and volumes
```

Each service has a Docker health check, so `docker compose ps` shows `healthy` or
`unhealthy`.

**Health endpoints.** None of these need a sign-in.

| Endpoint | Answers | Use it for |
|---|---|---|
| `/health/live` | Always 200 while the API process is running. Checks nothing else. | Deciding whether to restart the API. A database outage doesn't fail it, because restarting the API wouldn't fix that. |
| `/health/ready` | 200 when the API can serve requests, **503** when the database is unreachable. Also reports whether the job queue (Redis) answers, without failing on it. | Uptime monitors, load balancers and the Docker health check. |
| `/health` | The same as `/health/ready`. | Existing monitors. |

**Background work.** A working API doesn't mean imports and scheduled checks are
running. Administrators can see that under **Administration → Background jobs →
Platform status**, which shows:

- whether the database and job queue are reachable
- how many jobs are waiting in each queue
- which workers are answering, and any queue that has no worker taking from it
- when the scheduler last sent work (it normally sends something at least every
  ten minutes; after 20 minutes of silence it is reported as stopped)
- any job that has been waiting more than 15 minutes to start

The same information is available to administrators at `GET /api/v1/system/status`.

## Scaling

The default setup suits one field team. For larger operations:

- **More imports at once.** Increase `--concurrency` on the `worker` service in
  `docker-compose.yml`, or run more worker containers.
- **More users at once.** Increase `--workers` on the `api` service, roughly one
  per CPU core.
- **Large datasets.** DuckDB is limited to 2 GB per query in
  `backend/app/services/query_engine.py` (`memory_limit`). Increase it if the
  server has enough RAM.

### Importing from the server

For very large files, copy them to the server and import them there instead of
uploading through the browser. Browser uploads over 90 MB are sent in 50 MB
pieces (which works behind Cloudflare's 100 MB limit), but the browser tab still
has to stay open until the upload finishes.

Copy the file with a tool that can resume, then import it:

```bash
rsync -P "Household Survey 2026 - FINAL.dta" server:~/surveyHQ/incoming/
```

```bash
make import FILE="/incoming/Household Survey 2026 - FINAL.dta" PROJECT="Household Survey 2026"
```

`./incoming` (next to `docker-compose.yml`) is mounted read-only in the API and
import worker containers as `/incoming`, so use that path for `FILE`, not the
path on the host.

You can also import from this folder **without the command line**. Create a
connection with *A folder on this server* as the source and it will import on a
schedule. Connections can only use folders listed in `IMPORT_ROOTS` (`/incoming`
by default). To add more, list them comma separated and mount each one in both
containers. `IMPORT_SETTLE_SECONDS` (default 60) is how long a file must be
unchanged before it is imported, so files still being copied are skipped.

Files imported this way are handled exactly like uploads: the same parsing,
variable and value labels, Parquet, dataset record and audit log entry. Your file
is left where it is.

To import several files at once, each as its own dataset:

```bash
docker compose exec api python -m app.cli import \
  /incoming/household.dta /incoming/roster_pp.dta /incoming/interview_actions.dta \
  --project "Household Survey 2026"
```

A `.zip` file is unpacked into one dataset per file, the same as an upload. Run
with `--help` to see the other options: `--name`, `--description`, `--tags`,
`--mode` and `--user` (who the import is recorded as). Without `--user`, the
import is recorded as the first administrator, and the command tells you which
user it used.

Delete the file from the import folder afterwards. It is a copy of confidential
data outside the platform's storage, and it isn't deleted automatically.

### What a large upload costs

`MAX_UPLOAD_MB` is 20 GB by default. Large uploads use disk space, not memory.

**Memory.** Uploads are written to disk a megabyte at a time. Files over 48 MB are
passed to the worker instead of being processed during the request. nginx has no
size limit and doesn't buffer the upload (`client_max_body_size 0`,
`proxy_request_buffering off`), so the upload doesn't use disk in the web
container.

**Disk.** Allow about twice the file size during the upload. The file is first
saved to a temporary file, then copied into `/data/uploads`, so both copies exist
until the upload finishes. The Parquet version takes extra space, but is usually
much smaller than the original file.

The temporary file is saved in the API container's temp folder, not on the `/data`
volume. On a standard Docker install these are on the same disk. If you've put
`/data` on a separate, larger disk, set `TMPDIR` on the `api` service to a folder
on that disk.

**Timeouts.** The one-hour timeout is an idle timeout. nginx measures the time
between reads, not the total time, so a slow upload won't be cut off as long as
data keeps arriving.

**Unpacked zip size.** A zip can expand to 20 times the upload limit or
`MAX_EXTRACTED_GB` (64 GB by default), whichever is smaller. Increase
`MAX_EXTRACTED_GB` if a real export is refused. The error message says which limit
was reached.

## Troubleshooting

**The web page won't load**

```bash
make ps                        # is `web` up?
docker compose logs web
sudo ss -tlnp | grep 8080      # is something else using the port?
```

**An upload fails with "Request failed with status 413"**

Something in front of SurveyHQ refused the file. SurveyHQ's own limit always gives
a full message with the file size and the limit, so a plain 413 means a reverse
proxy (nginx's default is 1 MB) or a CDN has a lower limit. Find it and remove it:

```bash
sudo nginx -T 2>/dev/null | grep -n client_max_body_size   # host nginx
grep -n max_size /etc/caddy/Caddyfile                      # host Caddy
```

Set `client_max_body_size 0;` and `proxy_request_buffering off;` in the server
block, or remove the Caddy `request_body` limit, then reload the proxy. See
*Putting it behind HTTPS* for the full example. You can't change a CDN's limit
(Cloudflare's free plan allows 100 MB), but you don't need to, because the browser
sends uploads over 90 MB in 50 MB pieces. A 413 behind a CDN almost always means a
proxy with a limit below 50 MB, usually nginx's 1 MB default.

**"Could not reach the server" in the browser**

The API container is down or unhealthy.

```bash
docker compose logs api --tail=50
curl localhost:8080/health
```

**Every request returns 502, including sign-in, but `api` is healthy**

nginx looks up the `api` container's address when it starts and keeps it. If the
API container is rebuilt or recreated, it usually gets a new address, and nginx
keeps sending requests to the old one. `docker compose ps` shows `api` as healthy
and `web` as unhealthy.

Restart the web container:

```bash
docker compose restart web
curl -s localhost:8080/health          # expect {"status":"ok"}
```

Do this after any `docker compose up -d --build` that recreated `api` while `web`
kept running.

**A large upload never finishes**

Uploads over 48 MB are imported by the worker. If the worker isn't running, the
file is uploaded and a job is created, but nothing happens. Check **Administration
→ Background jobs**.

**Imports stay queued**

The worker or Redis is down.

```bash
docker compose logs worker --tail=50
docker compose restart worker beat
```

**A dashboard's scheduled copies never appear**

Scheduled copies need two containers: `beat` decides what is due and `worker` does
the work. If a dashboard is set up correctly but no copies appear, one of these
has usually stopped working.

Check each step in turn:

```bash
docker compose ps beat                                  # Up, and not Restarting
docker compose logs --tail=100 beat | grep "due task"   # a line every ten minutes
docker compose logs --tail=200 worker | grep take_due_snapshots
```

A working scheduler logs this every ten minutes:

```
Scheduler: Sending due task take-due-dashboard-snapshots
```

If `beat` shows as `Up` but logs nothing, it has stopped responding.
`docker compose ps` can't show this. `celery inspect ping` only works for workers,
not for beat.

If beat sends the task but the worker never mentions it, check the queue.
`take_due_snapshots` goes to the `default` queue, which the `worker` service
reads. A worker started with a narrower `--queues` list won't pick it up.

If the logs have been cleared, check the database. A dashboard with the schedule
turned on and no copies long after the scheduled time has never been picked up:

```bash
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
select name, snapshot_times, snapshot_timezone, last_snapshot_at
  from dashboards where snapshot_enabled;
SQL
```

(`$POSTGRES_USER` and `$POSTGRES_DB` are set inside the container, not in your
shell.)

If either container has stopped responding, restart both:

```bash
docker compose restart worker beat
```

To test the whole process, set a dashboard's scheduled time two or three minutes
ahead and check that the copy appears in its Views list.

**An import fails because the worker ran out of memory**

Files in a zip are read one at a time, but each one still has to fit in memory,
and the data takes up several times the file size once loaded. A 2 GB roster file
in a zip can need more memory than a small server has.

```bash
docker inspect $(docker compose ps -q worker) --format '{{.State.OOMKilled}}'
```

Import it from the server instead (see *Importing from the server* above). Files
imported that way are read in chunks and written straight to Parquet, so size
doesn't matter. Unzip the archive first and import the files:

```bash
unzip incoming/export.zip -d incoming/export/
docker compose exec api sh -c 'python -m app.cli import /incoming/export/*.dta --project "Household Survey 2026"'
```

Adding more RAM or swap to the server also works.

**"Stored secret could not be decrypted"**

`ENCRYPTION_KEY` has changed since the passwords were saved. Restore the old key
from a backup, or open each connection and enter its password again.

**Out of disk space**

```bash
docker system df
docker system prune -a          # removes unused images (not your volumes)
```

Datasets are stored in the `survey-data` volume. Deleting a dataset in the app
deletes its files, and deleting a project with its contents deletes all of their
files. Export archives (`sync-archives/`) can take a lot of space on a server with
several busy connections. The five most recent for each connection are kept and
older ones are deleted.

Each dataset also keeps restore points (10 by default). Go to **Administration →
Background jobs → Storage** to see how much space they and any unused files
take, and click **Remove unused files** to free it. See *Disk space* above.

**Resetting the administrator password**

```bash
make reset-password EMAIL=admin@example.org PASS=new-password
```

**Starting over** (deletes all data):

```bash
make clean
```

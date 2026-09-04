# Connecting to Survey Solutions

Survey Solutions is the World Bank's CAPI system. SurveyHQ talks to a
headquarters server through its REST API to list questionnaires, read interview
summaries and run data exports.

## What you need

- The **server URL** — the site root, e.g. `https://demo.mysurvey.solutions`.
  Not a path inside it: no `/primary`, no `/api`.
- The **workspace** name. Most servers have one, called `primary`.
- An **API user** with access to that workspace.

### Creating the API user

On the Survey Solutions server, signed in as an administrator:

1. Go to **Administration → API Users** (older versions: **Teams and Roles →
   API Users**).
2. Add a user, set a strong password.
3. Grant it access to the workspace holding your survey.

A headquarters or admin account also works, but a dedicated API user is better:
it can be revoked without disturbing anyone's login.

## Setting up the connection

**Connections → Add connection**, then fill in:

| Field | Value |
|---|---|
| Connection name | Anything meaningful, e.g. "National Household Survey 2026" |
| Server URL | `https://your-server.mysurvey.solutions` |
| Workspace | `primary` unless you know otherwise |
| API user name | The account you just created |
| Password | Its password — encrypted before it is stored |
| Export format | **Stata** (recommended — it carries variable and value labels) |
| Interview status | `All`, or restrict to e.g. `ApprovedBySupervisor` |
| Project | Which project the imported datasets belong to |

Press **Test connection** before saving. On success it reports the workspace and
how many questionnaires the account can see, which confirms the URL, the
credentials and the permissions in one step.

## Importing

Press **Import data** on a connection. It lists every questionnaire the account
can see; tick the ones you want and start the import.

What happens next:

1. SurveyHQ asks the server to prepare an export job.
2. It polls until the server reports the job complete. Large surveys take
   minutes — this runs in the background, so you can close the page.
3. It downloads the archive, keeps it, and unpacks the data files.
4. It imports **every** data file in it — the interview level, each roster
   level, and the paradata — one dataset each.

**Re-importing replaces those datasets in place**, keeping each one's identity,
so saved charts, dashboards, indicators, quality rules, relationships, merges
and derived variables keep working as long as variable names are stable. That is
the whole point: an export arrives every morning with the same variables and
more interviews, and nothing downstream should have to be rebuilt.

Choose *append* instead if your export really is incremental — each run holding
only what is new.

Progress and history appear under **Recent imports** on the connection, and
under **Administration → Background jobs**. Each run keeps the export zip
exactly as the server sent it; **Download** on the run hands it back. It is the
only record of what was actually imported, and it can be re-uploaded like any
other archive. The last five per connection are kept — an export is tens of
megabytes, and a connection syncing every six hours produces four a day.

## Scheduled imports

Turn on **Import automatically**, then choose how the schedule is expressed:

- **Every N minutes** — keeps the data no older than a known age. For daily
  monitoring, 60–360 minutes is usually right.
- **At set times** — e.g. `06:00` and `18:00`, listed as many as you like. This
  puts the import where the day has room for it: before the office opens, after
  the field teams sync their tablets. A monitoring dashboard is usually read at
  a particular hour, and the useful guarantee is that it was refreshed just
  before.

Times are read in the connection's **timezone**, which you set alongside them.
Fieldwork happens somewhere, and 06:00 means six in the morning there — in
Vanuatu that is five the previous afternoon in UTC, so getting the zone wrong is
a day's error, not an hour's.

A connection with no default questionnaires selected is skipped. Exports are
expensive for the Survey Solutions server, so avoid very short intervals on a
busy production server.

## Roster and multi-level data

A Survey Solutions export contains one file per roster level, and SurveyHQ
imports all of them. The interview level is what field monitoring needs; the
rosters are what analysis of people, plots or livestock needs.

Because they arrive together in one project, **Projects → Relationships** can
detect the links between them from the data, and two related datasets can be
merged into one for analysis. See the [user guide](user-guide.md#relating-and-merging-datasets).

## What gets recognised automatically

After an import, SurveyHQ looks for the standard Survey Solutions columns and
records what it finds:

| Role | Columns it looks for |
|---|---|
| Interview key | `interview__key` |
| Status | `interview__status`, `assignment__status` |
| Interviewer | `interviewer`, `responsible` |
| Supervisor | `supervisor`, `team` |
| Date | `interview__date`, `submitted_date`, `starttime` |
| Duration | `duration`, `interview__duration` |
| GPS | `latitude` / `longitude` and their prefixed variants |
| Area | `region`, `province`, `district`, `admin1` |

Whatever it finds drives the **Field progress** tab on the dataset — submissions
over time, interviews per interviewer and supervisor, status breakdown, coverage
by area, GPS map — with no configuration. What it recognises is listed on the
dataset page, so you can see exactly what was matched.

Uploaded files with the same column names get the same treatment.

## Common errors

**"Authentication failed"**
The user name or password is wrong, or the account lacks the API role. Confirm
by signing in to Survey Solutions directly with the same credentials.

**"Access denied to workspace 'primary'"**
The account exists but has no access to that workspace. Grant it on the server,
or correct the workspace name.

**"Endpoint not found"**
Usually the URL includes a path. Use the site root only. Also check the server
is version 20.06 or later, which is where the v2 export API arrives.

**"The server did not return JSON"**
The URL points at the web interface rather than the API root — typically a
trailing path, or a login page being returned by a proxy in front of the server.

**"Could not reach the Survey Solutions server"**
Network or DNS. From the host:
`curl -I https://your-server.mysurvey.solutions`.
If the server uses a self-signed certificate, turn off **Verify the server's TLS
certificate** on the connection — only on a network you trust.

**"The export archive contained no data files"**
The questionnaire has no interviews matching the selected status. Set interview
status to `All` and try again.

**The scheduled import is not running**
Check that **Import automatically** is on, that the connection lists at least
one questionnaire, and — for a time-of-day schedule — that the timezone is the
one you meant. `SYNC_TICK_MINUTES` decides how often the scheduler looks; a
time of day cannot be honoured more precisely than that.

**Import runs but the dataset is empty**
Interviews exist but none match the status filter. Check the filter on the
connection.

## Reading interview status codes

Stata exports store status as a number with a label attached. SurveyHQ shows the
label. The usual codes:

| Code | Meaning |
|---|---|
| 100 | Completed |
| 120 | Approved by supervisor |
| 130 | Rejected by supervisor |
| 125 | Approved by headquarters |
| 135 | Rejected by headquarters |
| 65 | Interviewer assigned |
| 85 | Supervisor assigned |

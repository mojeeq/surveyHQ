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
3. It downloads the archive and unpacks the data files.
4. It picks the interview-level file (the one named after the questionnaire
   variable, ignoring `interview__actions` and friends) and imports it.

Each questionnaire becomes one dataset. **Re-importing refreshes that dataset in
place**, so saved charts, dashboards, indicators and quality checks keep working
as long as variable names are stable.

Progress and history appear under **Recent imports** on the connection, and
under **Administration → Background jobs**.

## Scheduled imports

Turn on **Import automatically** and set an interval. The scheduler then
re-imports the questionnaires listed on the connection whenever the interval has
elapsed. A connection with no default questionnaires selected is skipped.

For daily monitoring, every 60–360 minutes is usually right. Exports are
expensive for the Survey Solutions server, so avoid very short intervals on a
busy production server.

## Roster and multi-level data

A Survey Solutions export contains one file per roster level. SurveyHQ imports
the interview level, which is what field monitoring needs.

To analyse a roster level, download the export from Survey Solutions and upload
the roster's `.dta` file as its own dataset. It behaves like any other dataset.

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

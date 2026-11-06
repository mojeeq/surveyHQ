# Connecting to Survey Solutions

Survey Solutions is the World Bank's CAPI system. SurveyHQ connects to a
Survey Solutions headquarters server through its REST API. It can list
questionnaires, read interview summaries and run data exports.

## What you need

- The **server URL**. This is the site root, for example
  `https://demo.mysurvey.solutions`. Don't include a path such as `/primary` or
  `/api`.
- The **workspace** name. Most servers have one workspace called `primary`.
- An **API user** with access to that workspace.

### Creating the API user

Sign in to the Survey Solutions server as an administrator, then:

1. Go to **Administration → API Users** (in older versions, **Teams and Roles →
   API Users**).
2. Add a user and give it a strong password.
3. Give it access to the workspace that holds your survey.

An **administrator** account also works, but a separate API user is better
because you can remove it without affecting anyone's login.

An ordinary **headquarters** account won't work. The export API only accepts API
users and administrators, so a headquarters account is refused even though it
can export through the web interface. If your server administrator can't create
an API user, see [When there is no API user](#when-there-is-no-api-user) below.

## Setting up the connection

Go to **Connections → Add connection** and fill in:

| Field | Value |
|---|---|
| Connection name | A name you'll recognise, for example "National Household Survey 2026" |
| Server URL | `https://your-server.mysurvey.solutions` |
| Workspace | `primary`, unless you know it's different |
| API user name | The API user you created |
| Password | Its password. This is encrypted before it is stored. |
| Export format | **Stata** (recommended, because it includes variable and value labels) |
| Interview status | `All`, or a single status such as `ApprovedBySupervisor` |
| Project | The project the imported datasets will belong to |

Click **Test connection** before saving. If it works, it shows the workspace and
the number of questionnaires the account can see. This confirms the URL, the
login details and the permissions.

## Importing

Click **Import data** on a connection. It lists every questionnaire the account
can see. Tick the ones you want and start the import.

**Ask the server for** sets the format for this import only. It starts with the
connection's format. Survey Solutions offers three:

| Format | File | When to use it |
|---|---|---|
| Stata | `.dta` | The default. Includes variable and value labels, so coded answers show as text (for example "Rented" instead of 3). |
| Tab-delimited text | `.tab` | Plain text. Try this if a `.dta` file imports with values you can't explain. Labels aren't included, so coded answers stay as codes. |
| SPSS | `.sav` | If you already work in SPSS. Includes labels. |

Survey Solutions doesn't export CSV or `.dat`. A `.tab` file is a text file with
tab separators, which Excel, Stata and R can all open.

The format used is shown next to each run under **Recent imports**.

**What happens during an import**

1. SurveyHQ asks the server to prepare an export.
2. It checks until the export is ready. Large surveys can take several minutes.
   This runs in the background, so you can close the page.
3. It downloads the archive, keeps a copy and unpacks the data files.
4. It imports **every** data file in the archive (the interview level, each
   roster level and the paradata) as a separate dataset.

**Re-importing replaces the datasets in place.** Each dataset keeps its
identity, so charts, dashboards, indicators, quality checks, relationships,
merges and derived variables keep working, as long as the variable names stay
the same.

Choose **append** instead if each export only contains new interviews.

After the files are imported, SurveyHQ:

1. applies the saved commands for each dataset again
2. rebuilds merges that use them
3. runs project scripts that read them
4. runs their data quality checks
5. updates indicators and dashboards
6. republishes any published copies of the dashboards

This happens on every import, scheduled or manual. See *What happens after the
data lands* in the [user guide](user-guide.md#what-happens-after-the-data-lands).

**Following progress.** While an import runs, the **activity** button in the top
bar shows the current step, including the server's progress while it prepares
the export (usually the longest wait). Past runs are listed under **Recent
imports** on the connection and under **Administration → Background jobs**.

Each run keeps the export zip exactly as the server sent it. Click **Download**
on a run to get it. You can upload it again like any other archive. The last
five exports for each connection are kept.

## Scheduled imports

Turn on **Import automatically** and choose a schedule:

- **Every N minutes.** For daily monitoring, 60 to 360 minutes is usually enough.
- **At set times**, for example `06:00` and `18:00`. Add as many times as you
  need. Use this to make sure data is fresh before people check the dashboard,
  for example before the office opens or after field teams sync.

Times use the connection's **timezone**, which you set next to them. Make sure
it is right: in UTC+11, 06:00 is 19:00 UTC the previous day.

Choose which questionnaires to import under **Edit → Questionnaires to import
automatically**. Connections with no questionnaires selected are skipped, and
the dialog warns you about this. Exports put load on the Survey Solutions
server, so don't use very short intervals on a busy server.

**Questionnaire versions.** By default, every version of a questionnaire is
imported, oldest first, into one dataset with a `questionnaire_version` column.
New versions are picked up automatically. If you only want certain versions,
choose **Only the versions ticked below**.

## Roster and multi-level data

A Survey Solutions export has one file per roster level, and SurveyHQ imports
all of them. The interview level is used for field monitoring. Roster files are
used for analysing people, plots, livestock and so on.

Because they are imported into the same project, **Projects → Relationships**
can detect how they link to each other, and you can merge two related datasets
for analysis. See the [user guide](user-guide.md#relating-and-merging-datasets).

## What gets recognised automatically

After an import, SurveyHQ looks for the standard Survey Solutions columns:

| Role | Columns it looks for |
|---|---|
| Interview key | `interview__key` |
| Status | `interview__status`, `assignment__status` |
| Interviewer | `interviewer`, `responsible` |
| Supervisor | `supervisor`, `team` |
| Date | `interview__date`, `submitted_date`, `starttime` |
| Duration | `duration`, `interview__duration` |
| GPS | `latitude` / `longitude` and versions with a prefix |
| Area | `region`, `province`, `district`, `admin1` |

These are used for the **Field progress** tab on the dataset: submissions over
time, interviews per interviewer and supervisor, status breakdown, coverage by
area and a GPS map. You don't need to set anything up. The dataset page lists
what was recognised.

Uploaded files with the same column names are treated the same way.

**Checking GPS against enumeration areas.** A dashboard map can check each
interview's recorded EA against the area its GPS point falls in, if you add your
EA boundaries as a layer. If interviewers also record a location by hand (for
example a second GPS question used when the first gets no fix), set it as the
map's **second location**. It is checked separately, a line is drawn to the GPS
point when the two are far apart, and points shared by two households are
flagged. Each result is a layer you can turn on and off. See *The data quality
layers* in the [GIS manual](gis-manual.md#7-the-data-quality-layers).

## When there is no API user

Only a server administrator can create an API user. If you can't get one, you
can still bring the data in without an account on the survey server:

- **Send the export to a cloud drive.** On the Survey Solutions Data Export page
  you can send the export to OneDrive, Dropbox or Google Drive instead of
  downloading it. Sync that folder to the SurveyHQ server and import from it.
- **Read the server's export folder.** A self-hosted Survey Solutions server
  saves export archives to a folder set by
  `Export_ExportSettings__DirectoryPath` (often `/app/AppData/Export`). On AWS
  this can be an S3 bucket. Mount it read-only on the SurveyHQ server.
- **Copy the file into `./incoming`.** Anyone who can download an export from
  the web interface can copy it to the server. `make import` loads it the same
  way as an upload. A scheduled task can do the copying.

In each case you end up with a file in a folder, which a **folder connection**
can import on a schedule.

### A folder connection

1. Go to **Connections → Add a connection**.
2. Set **Where the data comes from** to *A folder on this server*.
3. Enter the folder.

There is no URL, user name or password. The server only reads from folders the
administrator has allowed. By default this is `/incoming`, which the compose file
already mounts. Set `IMPORT_ROOTS` to allow other folders (comma separated).

**Test connection** shows how many files are in the folder, how many haven't been
imported yet and how many are still being written. Then click **Import data**, or
turn on **Import automatically**. The schedule options are the same as for a
server connection.

**What it reads**

- **`.zip` files** are treated as Survey Solutions exports. Each file inside
  becomes a dataset.
- **Single `.dta`, `.sav`, `.csv`, `.tab` or `.xlsx` files** each become one
  dataset.
- Other files, files starting with a dot and files in subfolders are ignored.

**Good to know**

- **Each file is imported once.** Files are recognised by their content, not their
  name. Tomorrow's export with the same name is imported; a copy of today's with a
  new name is not.
- **Files still being copied are skipped until next time.** A file is only read
  once it hasn't changed for `IMPORT_SETTLE_SECONDS` (one minute by default). Set
  this to 0 if the files are created on the same machine.
- **Your files are never moved or deleted.** You'll need to clear out old files
  yourself.

Re-importing replaces the datasets in place, the same as a server connection, so
charts, indicators and quality checks keep working.

## Common errors

**"Authentication failed"**
The user name or password is wrong, or the account isn't an API user. Try
signing in to Survey Solutions directly with the same details.

**"Access denied to workspace 'primary'"**
The account exists but doesn't have access to that workspace. Give it access on
the server, or correct the workspace name.

**"Endpoint not found"**
The URL probably includes a path. Use the site root only. Also check the server
is version 20.06 or later, which added the v2 export API.

**"The server did not return JSON"**
The URL points to the web interface instead of the API root. This is usually
because of an extra path, or a proxy returning a login page.

**"Could not reach the Survey Solutions server"**
A network or DNS problem. Test it from the SurveyHQ server:
`curl -I https://your-server.mysurvey.solutions`.
If the server uses a self-signed certificate, turn off **Verify the server's TLS
certificate** on the connection. Only do this on a network you trust.

**"... points at this server itself" or "... is a link-local address"**
SurveyHQ won't connect to `127.0.0.1`, `localhost` or the `169.254.x.x` range.
These are SurveyHQ's own container or other local addresses, not a survey
server. Servers on your own network are fine: `10.x`, `192.168.x` and
`172.16-31.x` are all allowed. Enter the address as it is reached from the
SurveyHQ server.

**"... is a cloud provider's metadata service"**
Cloud metadata addresses return the server's own credentials, so SurveyHQ
refuses them:

| Address | Provider |
| --- | --- |
| `169.254.169.254` | AWS, Azure, Google Cloud, DigitalOcean, Hetzner, Oracle |
| `fd00:ec2::254` | AWS over IPv6 |
| `100.100.100.200` | Alibaba Cloud |
| `192.0.0.192` | Oracle Cloud, older instances |

Only these exact addresses are blocked, not whole ranges, so a Survey Solutions
server on a private IPv6 network still works. The same addresses written in
other forms are also blocked.

**"Too many connection tests"**
Connection tests are limited to ten a minute per user. Wait a minute and try
again.

**"The export archive contained no data files"**
No interviews match the selected status. Set the interview status to `All` and
try again.

**The scheduled import isn't running**
Check that **Import automatically** is on, that at least one questionnaire is
selected and, for set times, that the timezone is correct. `SYNC_TICK_MINUTES`
sets how often the scheduler checks, so set times can't be more precise than
that.

**The import runs but the dataset is empty**
There are interviews, but none match the status filter. Check the filter on the
connection.

## Interview status codes

Stata exports store status as a number with a label. SurveyHQ shows the label.
The usual codes are:

| Code | Meaning |
|---|---|
| 100 | Completed |
| 120 | Approved by supervisor |
| 130 | Rejected by supervisor |
| 125 | Approved by headquarters |
| 135 | Rejected by headquarters |
| 65 | Interviewer assigned |
| 85 | Supervisor assigned |

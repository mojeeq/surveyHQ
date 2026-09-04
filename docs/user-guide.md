# User guide

## Roles

| Role | Can do |
|---|---|
| **Viewer** | Read dashboards and analyses |
| **Analyst** | Everything above, plus build charts, dashboards and run any analysis |
| **Manager** | Everything above, plus upload data, manage connections, indicators and quality rules |
| **Administrator** | Everything, plus manage users and see the audit log |

A role is what someone may *do*. What they may *reach* is decided separately, by
projects.

## Projects

A project groups one survey round's datasets and dashboards, and controls who
can see them. Anything not in a project sits in the **shared area**, which every
user can see - that is where everything lives until you decide otherwise, so
projects are something you opt into rather than something you must set up first.

To create one: **Projects → New project**. You are added as its manager, so it
stays visible to you.

To put data in it, either choose the project when uploading, or open a dataset
or dashboard and click the project button in its header to move it. Moving needs
manager rights on *both* projects, so nobody can take a dataset out of a project
they have no say over.

Monitoring, Data quality and Alerts each have a project filter at the top, so a
round in the field can be looked at on its own rather than alongside every other
survey the platform holds. Connections belong to a project too: someone who can
reach one project sees that project's servers and its imported archives, and
not anybody else's.

### Giving someone one project only

This is the point of projects, and it takes two steps:

1. **Administration → Add user**. Set their role, then tick **Limit to assigned
   projects**. This hides the shared area from them; without it they would still
   see everything not in a project.
2. **Projects → (the project) → Members → Add member**. Choose their role on
   this project.

They now see that project and nothing else - not in listings, and not by typing
a URL or calling the API directly. A dataset outside their reach answers "not
found" rather than "forbidden", so they cannot even tell that other projects
exist.

A member's role on a project never exceeds their own role. Adding a viewer to a
project as manager does not make them an editor of anything; membership widens
what someone can reach, never what they are allowed to do.

### Deleting a project

**Delete project** asks what should happen to its contents, because both answers
are reasonable:

- **Delete, keep the data** dissolves the project and moves its datasets and
  dashboards to the shared area, where they go on working. A project is an
  organising idea, and dissolving one need not throw away the data organised by
  it.
- **Delete everything** also destroys those datasets and their files, and
  everything built on them — charts, indicators and their history, quality
  checks, alert rules and the alerts they raised, relationships, any dataset
  merged out of them, and this project's dashboards. A round that is finished
  with is finished with.

The second cannot be undone, so it asks you to type the project's name first.
Connections are kept either way: a connection is a server and a set of
credentials, which outlive the project pointed at it.

## Relating and merging datasets

A Survey Solutions export is several tables, not one. A labour force export
holds the interview, the household members and the people living abroad, and
each becomes its own dataset when you upload the archive.

**Projects → (a project) → Relationships** has three ways to build the model:

- **Detect relationships** reads the data and proposes the links. It reads
  values, not column names: whether a key is unique on each side is what tells
  one-to-many from many-to-many. It also reports the overlap, so you can see
  that (say) only 18% of interviews have someone living abroad — a real link
  that covers little of the data.
- **Add by hand** declares one directly: pick the two datasets, the key on each
  side, and the cardinality. Use it when detection cannot see a link, for
  instance where the key is spelled differently on the two sides.
- **Clear relationships** removes the project's links and starts again, either
  all of them or **only the detected ones**, leaving what you declared or
  corrected by hand. Detection is a guess, and a wrong guess is easier to clear
  out than to correct one at a time. Datasets already merged keep their data —
  they hold their own copy — but can no longer be re-run from a relationship
  that is gone.

Click a link to correct it. Changing anything marks it as yours, and detecting
again never reverts it.

**Merge into a new dataset** joins two related datasets, letting you choose
which columns to bring across and whether to keep every row of the left dataset
or only matching ones. Watch the row count: joining 190 interviews to their 782
people gives 789 rows, because each interview is repeated once per person. The
platform says so when it happens.

Two rosters are many-to-many on the interview, so joining them would multiply
rows rather than add columns. Those links are recorded but cannot be merged.

The merge is saved with the dataset it produces. **Rebuild from sources** re-runs
it on demand, and a merged dataset rebuilds itself automatically whenever a
source is replaced by a newer export or changed by a command — including a merge
of a merge, which waits for the merge underneath it to finish first.

## Getting data in

### Uploading a file

**Datasets → Upload data**. Supported: Stata (`.dta`), SPSS (`.sav`), CSV,
tab-delimited (`.tab`, `.tsv`), Excel, and `.zip` archives of them.

**An export archive becomes one dataset per file inside it**, because a Survey
Solutions export holds one file per roster level — the interview, the household
members, the people abroad — and those are different tables, not different
rounds. The paradata file comes in with the rest of them.

Upload a later round's archive and each of its files goes to the dataset already
holding that file name. **When a dataset already holds that file** is where you
say what happens next:

- **Replace its data** (the default) swaps that dataset's data and keeps its
  identity, so every relationship, merge, chart, indicator, quality rule and
  dashboard widget built on it goes on working. Use it for a fresh export of
  everything collected so far — which is what a live monitoring tool wants: the
  variables are the same, only the interviews are newer.
- **Add its rows to what is there** appends, for an export that contains only
  what is new. A `source_file` column records which archive each row came from,
  so the rounds stay distinguishable. Appending a cumulative export counts the
  same interviews twice.

### A questionnaire that changed mid-fieldwork

A form revised during collection exports as separate versions, each a zip
holding the same member file names. They belong in one dataset per file, with
something in the rows to say which version each interview was answered on.

Choose **several archives at once** and that is what happens. They are imported
in the order listed — the first under your replace/append choice, the rest
appended onto what it produced — so every archive's interview file meets the
interview file, each roster meets its roster, and the paradata meets the
paradata.

Two things make the result usable afterwards:

- **A label per file**, written into a variable you name (`version` by default).
  Give the three archives `11`, `10` and `9` and you can tabulate by version,
  cross-tabulate against it, or filter a dashboard to one form. A variable of
  that name already in the data is left alone rather than written over, and the
  import says so.
- **Variables that differ between versions are unioned, not refused.** A
  variable added in version 11 is blank for the version 9 rows, and the import
  reports which variables that applied to.

Use ▲ beside a file to change the order. The first file is the base, as it is
in a do-file that opens one export and appends the others onto it.

Imports from a Survey Solutions connection do the same thing on their own: each
questionnaire version's rows are stamped with `questionnaire_version`, so
syncing several versions in append mode builds the same combined dataset.

### What survives a replacement

What survives a replacement, and is put back automatically:

- the dataset's id, so nothing pointing at it breaks,
- variable and value labels you wrote by hand (the file does not carry them),
- variables you generated with commands, replayed in the order you ran them,
- datasets merged out of it, rebuilt from the new data.

Two things it will tell you rather than let pass quietly:

- On an append, if an interview appears in both the existing data and the new
  rows, they are now counted twice. That usually means the export was set to
  cumulative rather than incremental.
- If a same-named file from a different survey does not share enough columns, it
  is not written over yours; it becomes its own dataset.

A file too large to hold in memory is read in chunks automatically. Nothing
changes for you except that the import reports it.

An upload over 48 MB is handed to the background worker rather than read while
you wait: the browser says *Importing…* and watches it, and a census roster
export that takes minutes no longer depends on a connection staying open for
all of them. An upload over the platform's limit is refused before it is sent,
with the size and the limit in the message — the limit is `MAX_UPLOAD_MB` on
the server, and an administrator can raise it.

Stata and SPSS are the best choice because they carry variable labels and value
labels; those are read and used everywhere in the interface.

The file is parsed immediately and you land on the dataset with its row count,
variables and detected types.

### Importing from Survey Solutions

See [survey-solutions.md](survey-solutions.md).

### Refreshing

A dataset can be refreshed in place — by re-importing from its connection, or
with **Replace data** for an uploaded file. Charts, dashboards, indicators and
quality checks that point at it keep working, provided variable names have not
changed.

### Tidying up

The dataset list groups datasets by project, and each group collapses — one
survey export is eight datasets, and four rounds of it is thirty-two.

Tick several datasets and **Delete selected** removes them in one confirmation,
or use **Delete all** on a project's group to clear a whole round. Anything the
merge or a chart depends on goes with it, so read the confirmation.

**Rename** on a dataset gives it a name and a description of your own. An
archive names each dataset after the file inside it, which is how a project
ends up holding `R_demographics` and `roster_pp`; those are the names the export
chose, and this is where they become the names your team uses. Nothing breaks:
charts, indicators and merges point at the dataset, not at its name.

### Taking a dataset out

**Stata**, **CSV** and **Excel** on a dataset download the whole table. All
three are written from the data the platform is actually querying, not from
whatever was uploaded — so a merged dataset, which never had a file of its own,
downloads like any other, and so does a dataset changed by commands.

Prefer **Stata**: it carries the variable labels and, where the codes are whole
numbers, the value labels. CSV carries neither. Excel stops at a million rows
and says so rather than writing a file Excel would refuse to open.

Downloading is a manager's action, and it is recorded in the audit log.

## Looking at a dataset

The dataset page has four tabs, and a fifth for managers:

- **Variables** — every variable with its label, type, missing count, distinct
  count and range. Variables missing on more than 20% of records are highlighted.
  **Tabulate** on any row gives an instant frequency table with a chart.
- **Data** — page through the raw rows.
- **Statistics** — mean, standard deviation, min, quartiles, median and max for
  every numeric variable.
- **Field progress** — submissions over time, interviews per interviewer and
  supervisor, status breakdown, coverage by area and a GPS map. Appears
  automatically when the relevant columns are recognised.
- **Command** — the Stata-style script box, below. Managers only.

### Naming variables and their codes

An export often arrives with neither name nor labels: a column called `DEM_SEX`
holding 1 and 2, which a table then prints as "1.0" and "2.0". On the
**Variables** tab, **Labels** on any row lets you write the variable's label and
a label for each of its codes.

Nothing about the data changes — only what the platform calls it, everywhere it
is shown: axis labels, legends, cross-tab headers, filter dropdowns. Labels you
write are kept on the dataset as well as on the variable, so a newer export
replacing the file does not wipe them.

### The command box

**Command** runs a Stata-style script against the dataset, one command per
line, in the order written. The useful subset:

| Command | Example |
|---|---|
| `gen` | `gen adult = age >= 18` |
| `replace` | `replace adult = 0 if age == .` |
| `egen` | `egen hh_total = total(income), by(interview__key)` |
| `egen` (rowwise) | `egen answered = rownonmiss(q1 q2 q3)` |
| `label variable` | `label variable adult "Adult (18+)"` |
| `label define` / `label values` | `label define yesno 0 "No" 1 "Yes"` then `label values adult yesno` |
| `rename` | `rename DEM_SEX sex` |
| `drop` / `keep` | `drop if interview__status != 100` |

`egen` supports `total`, `sum`, `mean`, `count`, `min`, `max`, `median`, `sd`,
`group` and `tag` down a column (with `by()`), and `rowtotal`, `rowmean`,
`rowmiss`, `rownonmiss`, `rowmax`, `rowmin` across a row. Comments (`*`, `//`)
and continuations (`///`) work as in a do-file. Ctrl/⌘+Enter runs the script.

A line that fails stops the script and says which line and why. Everything above
it has already run, as in a do-file, so it stays — the log tells you what got
through.

Commands are **recorded on the dataset and replayed** after a newer export
replaces it. A variable somebody generated is not in the export file, so without
that it would vanish on exactly the upload this platform is built around, taking
every chart built on it. The history is listed under the box: **Edit** puts a
command back in the box, and **Clear** stops the replay without undoing what the
commands already did.

## Explore

**Explore** is where analysis happens. Two modes.

### Tabulate & chart

1. **Group by** one or two variables. Dates offer a grain (day, week, month,
   quarter, year). Numeric variables can be binned by width. The first grouping
   can keep the top N categories and fold the rest into "Other". Any variable
   can be grouped on, `interview__key` included — a variable with a value per
   row says how many values it has beside its name, and the row limit decides
   how much comes back.
2. **Measure**: count, share of total, sum, mean, median, min, max, standard
   deviation, percentiles or distinct count. Add several measures to compare
   them side by side. Any measure can be weighted by a numeric variable — pick
   your survey weight to get weighted estimates.
3. **Filters**: as many conditions as you like, combined with all/any. Variables
   with value labels offer a dropdown of their labels.
4. **Display**: how it is drawn, below. Then **Run query**.

Results can be viewed as a chart or a table, exported to CSV or Excel, and saved
as a chart for use on a dashboard. **Show SQL** reveals the generated query if
you want to check what was computed.

If you are not sure where to start, **Suggested analyses** proposes charts built
from the dataset's own variables — one click to run.

#### Display

| Control | What it does |
|---|---|
| Chart type | Bar, horizontal bar, stacked bar, horizontal stacked bar, population pyramid, line, area, donut, pie, scatter, heatmap, table |
| Order | Leave the query's order, or sort by value or by label, ascending or descending |
| Show only the top | Keep the largest N categories and fold the rest into one "Other" |
| Value axis title | Name the value axis |
| Axis from … to | Fix its minimum and maximum, so two charts can be compared |
| Target line | A line across the plot with a label, e.g. the target this is read against |
| Print the numbers on the chart | On bars and slices, up to 24 of them. Not offered on lines, where they collide |
| Stack to 100% | Read composition rather than magnitude, on a stacked bar or area |
| Smooth the line | Curve a line or area chart |
| Row limit | How many rows the query returns |

Controls that make no sense for the chart type are not offered, so the panel
changes as you change the type.

A **population pyramid** wants an age band on the first grouping and sex on the
second; it draws the two sides back to back. Bands are ordered by the number
they start with rather than as text, so "5–9" lands between "0–4" and "10–14"
rather than after "45–49".

Every chart with more than one series carries a legend, and every chart has a
table toggle exposing the same numbers, because colour alone is never the only
thing telling two series apart.

### Cross-tabulation

Pick a row variable and a column variable, choose what the cells hold (count by
default, or any aggregate of a numeric variable), and choose percentages: none,
row, column, or percent of total. Row and column totals are always shown.

Underneath, chi-square and Cramér's V are reported so you can see whether an
apparent association is worth anything.

A cross-tabulation is not capped at a readable size: up to 5,000 rows and 1,000
columns come back, so tabulating by interview key or enumeration area gives you
the whole table. It scrolls with its headers pinned, and exports whole. If a
variable somehow has more categories than that, the table says how many it left
out rather than quietly ending.

**Save for dashboards** keeps the table itself, not a picture of it. It reruns
against current data wherever it appears, and dashboard filters narrow it like
any other widget.

## Charts and dashboards

Any Explore result can be saved as a chart. Saved charts live under
**Dashboards → Saved charts**, each showing live data.

To build a dashboard:

1. **Dashboards → New dashboard**. Choose the project it belongs to, or leave it
   in the shared area.
2. **Add widget** — see the list below.
3. **Move & resize** — turns on dragging and resizing; the layout saves itself.
4. **Edit** — hover a widget and use the ✎ to change anything about it: what it
   shows, its title, its width and height, its background colour, and which
   page it sits on. The ✕ beside it removes it. Both are there whether or not
   you are arranging. A widget's own colour still takes the dashboard's
   transparency, so the two settings do not cancel each other.
5. **Pages** — **+ Page** adds one; double-click a tab to rename it, and ◀ ▶
   move it earlier or later. A page takes its widgets with it, so reordering is
   safe. Each page lays out on its own and has its own filters.
6. **Filters** — see below.
7. **Appearance** — background, canvas and transparency; see below.
8. **Colours** — the picker in the header sets which palette this dashboard's
   charts use. The alternatives are the same hues in a different order, chosen
   for how far apart neighbouring series stay for colour-blind readers.
9. **Share link** — generates a read-only public URL, copied to your clipboard.
   Anyone with the link can view the dashboard without an account. Press again
   to revoke it.
10. **Give it a name** — where an administrator has configured a dashboard
    domain, a shared dashboard can also answer on its own address, such as
    `labour-force.dash.example.org`. See below.

### The widgets

| Widget | Shows |
|---|---|
| **Saved chart or cross-tab** | A chart or a two-way table saved from Explore, re-run against current data |
| **Indicator tile** | One tracked number with its target, status colour and trend — and optionally its breakdown drawn as a chart beneath |
| **Data quality panel** | The last result of every check on a dataset, and how old the oldest one is |
| **Text note** | A heading, an explanation, a caveat |
| **Countdown to a date** | Time remaining to a deadline, ticking, with your own label and a message for when it passes |
| **Map of interview locations** | GPS points from a dataset, grouped by coordinate — up to 50,000 places. Click a point for its count or any aggregate, plus the detail columns you chose |
| **Embedded HTML** | Whatever HTML you paste, rendered in a sandboxed frame — a logo, an embedded video, a link bar |
| **How recent the data is** | When each dataset was last imported, and how old its newest record is |

The **freshness** widget answers two questions, because a monitoring tool needs
both. *When did the platform last receive data* says whether the import is
running. *How recent is the newest record* says whether the field teams are
still sending anything — an import that runs faithfully every morning and
collects nothing new looks healthy by the first measure and is exactly what the
second one catches. It turns amber after 24 hours and red after 72 by default;
both thresholds are yours to set.

It picks the date variable that says when a record happened — an interview date,
a submission or sync timestamp — and deliberately ignores dates that are
answers rather than moments, such as a date of birth. Where a dataset has no
obvious one, or the wrong one is chosen, name the variable yourself on the
widget.

### Giving a dashboard its own address

A share link ends in a 64-character token. That is what makes it safe to send
to one person — nobody guesses it — but it is not something you can put on a
poster or read down a phone line.

Where an administrator has set a dashboard domain, **Give it a name…** beside
the share link assigns one: type `labour-force` and the dashboard answers on
`labour-force.dash.example.org`, showing exactly what the share link shows,
logo and colours and all.

**A name is not a secret.** It is meant to be typed from memory, so anyone who
guesses it reaches the dashboard. Naming is publishing, and it is worth being
deliberate about which dashboards get one. Two rules follow from that:

- only an already-shared dashboard can be given a name;
- turning sharing off removes the name too, so an address never resolves to
  something nobody may read.

Names live under the one configured domain, and reserved names — the platform's
own address, `www`, `api`, `admin` and similar — cannot be taken. If the option
is not there, no domain is configured; an administrator sets `DASHBOARD_DOMAIN`
along with the DNS record and certificate described in
[deployment.md](deployment.md).

### Filters

**Filters** on a dashboard adds controls its readers can use: pick a variable
and every viewer gets a dropdown of its labels, which narrows every widget
underneath.

Filters belong to **the page they are on**, so a "Fieldwork" page can filter by
interviewer while a "Coverage" page filters by district. A control only applies
to widgets whose dataset actually has that variable; widgets that cannot answer
it say so rather than quietly ignoring it.

### Making it yours

A dashboard is usually the thing a survey team shows other people, and it
belongs to them rather than to the platform. **Appearance → Header** is where it
says so:

- **Logo** — upload your organisation's mark (PNG, JPEG, GIF or WebP, up to
  8 MB). It sits beside the title, at whatever height you set, and it travels
  with the shared link, where it matters most.
- **Title size** — from 16 to 64 pixels, so a board left on an office wall can
  be read from across the room.
- **Title font** — the interface face, or a grotesque, serif, slab or
  monospace. All of them are already on the machine, so a screen with no
  internet still renders in the face you chose.
- **Title colour and alignment** — your colour, left or centred.
- **A rule under the header**, and the option to **hide the description**, for
  when the title alone is the whole heading.

### Appearance

The rest of **Appearance** controls how the dashboard is dressed:

- **Background** — a colour, or an uploaded image (PNG, JPEG, GIF or WebP, up to
  8 MB), set to fill the page, fit whole, or repeat, with a fade slider so text
  stays readable over it.
- **Canvas width** — fit the window, or a fixed width that scrolls, for a
  dashboard meant to go on a wall. **Columns** and **row height** set how fine
  the grid underneath the widgets is.
- **Widget transparency** — how much of the background shows through the
  widgets, from solid to barely there.
- **Behind the page tabs** — the colour of the tab band, so tabs stay visible
  when the dashboard background happens to be the same colour as their text.

## Monitoring

### Indicators

An indicator is one tracked number.

**Monitoring → New indicator**: name it, pick a dataset, choose the measure
(count of records, or an aggregate of a variable), and optionally:

- a **target**, which draws a progress bar,
- a **warning** and **critical threshold**,
- a **direction** — with "higher is better", the indicator turns amber at or
  below the warning threshold and red at or below critical; with "lower is
  better" the logic reverses,
- a **breakdown variable**, so the indicator can be expanded per region or team,
- a **percentage**, where the number is a share rather than a count.

**Percentages.** Filters pick the rows the indicator counts; *percent of* says
what they are a share of. "Of all rows" divides by every row in the dataset
before the indicator's own filters — that is how "% of interviews completed" is
expressed. "Of those who answered" divides by the rows that answered the
measured variable, which is the same question asked of a variable rather than of
the file.

**✎ on an indicator** edits all of it — the measure, the filters, the target and
thresholds, the breakdown, even which dataset it reads. A threshold set before
fieldwork started is a guess, and correcting one should not mean deleting the
indicator and losing its history.

Indicators recompute on a schedule and store a snapshot each time, which is what
gives every indicator a trend line.

To count something specific — completed interviews, say — put a filter in the
indicator's query, the same as in Explore.

### Alerts

**Alerts → New alert rule**: pick an indicator, a comparison and a threshold.
When the condition holds, an alert is raised with the severity you chose, and
delivered in-app and optionally by email. The cooldown stops one ongoing problem
generating a stream of alerts. When the value recovers, open alerts for that rule
resolve automatically.

**Test now** evaluates the rule immediately rather than waiting for the
scheduler — useful for confirming a threshold does what you meant.

Alerts can be acknowledged (someone is looking at it) or resolved (it is dealt
with).

### Data quality

**Data quality** lists the checks on a dataset and whether each is passing.

The platform inspects a dataset and recommends checks that suit it — duplicate
interview keys, unusually short interviews, missing GPS, variables with high
missingness. Accept one and it is created and run immediately.

The eight check types:

| Check | Flags |
|---|---|
| Missing values | Records where a variable is blank |
| Value out of range | Values below a minimum or above a maximum |
| Duplicate records | Repeated key combinations, e.g. the same interview key twice |
| Statistical outliers | Values far from the rest (IQR or z-score) |
| Interview duration | Interviews finished suspiciously fast |
| Missing GPS | Records with no usable coordinates |
| Constant answers | Interviewers recording the same answer for everyone |
| Cross-variable consistency | Rows where one variable should relate to another but does not |

Each check has a **tolerance**: the share of flagged rows it will accept before
reporting a failure. Zero means any occurrence fails — right for duplicate
interview keys. A few percent is more sensible for short interviews.

**Edit** changes a check and re-runs it, so the stored result never describes a
definition that no longer exists. The check type is fixed — changing that would
make it a different check.

A check can also be restricted to part of the dataset. The filter narrows the
total as well as the flagged rows, so the failure rate stays a rate of what was
actually checked: "3% of interviews in Shefa", not "3% of everything, some of
which was in Shefa".

Checks run every six hours, and on demand with **Run** or **Run all**. Add a
**data quality panel** to a dashboard to keep the results where people look;
it shows the last run rather than re-running eight full scans every time
somebody opens the page, and says how old the oldest result is.

## API keys

**Administration → API keys** creates a key for scripts and integrations. The key
is shown once — copy it then. See [api.md](api.md).

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

Overview, Monitoring, Data quality and Alerts each have a project filter at the
top, so a
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
  everything built on them - charts, indicators and their history, quality
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
  that (say) only 18% of interviews have someone living abroad - a real link
  that covers little of the data.
- **Add by hand** declares one directly: pick the two datasets, the key on each
  side, and the cardinality. Use it when detection cannot see a link, for
  instance where the key is spelled differently on the two sides.
- **Clear relationships** removes the project's links and starts again, either
  all of them or **only the detected ones**, leaving what you declared or
  corrected by hand. Detection is a guess, and a wrong guess is easier to clear
  out than to correct one at a time. Datasets already merged keep their data -
  they hold their own copy - but can no longer be re-run from a relationship
  that is gone.

Click a link to correct it. Changing anything marks it as yours, and detecting
again never reverts it.

The diagram lays itself out from the cardinalities - the interview table on top,
its rosters hanging below - which is right until a project has enough tables
that the lines cross each other. **Drag a box** to move it, and the links
follow. Where you put it is remembered for that project in the browser you are
using, since an arrangement is a way of looking at the model rather than part of
it; **Tidy up** puts everything back where the layout computed.

**Merge into a new dataset** joins two related datasets, letting you choose
which columns to bring across and whether to keep every row of the left dataset
or only matching ones. Watch the row count: joining 190 interviews to their 782
people gives 789 rows, because each interview is repeated once per person. The
platform says so when it happens.

Two rosters are many-to-many on the interview, so joining them would multiply
rows rather than add columns. Those links are recorded but cannot be merged.

The merge is saved with the dataset it produces. **Rebuild from sources** re-runs
it on demand, and a merged dataset rebuilds itself automatically whenever a
source is replaced by a newer export or changed by a command - including a merge
of a merge, which waits for the merge underneath it to finish first.

## Getting data in

### Uploading a file

**Datasets → Upload data**. Supported: Stata (`.dta`), SPSS (`.sav`), CSV,
tab-delimited (`.tab`, `.tsv`), Excel, and `.zip` archives of them.

**An export archive becomes one dataset per file inside it**, because a Survey
Solutions export holds one file per roster level - the interview, the household
members, the people abroad - and those are different tables, not different
rounds. The paradata file comes in with the rest of them.

Upload a later round's archive and each of its files goes to the dataset already
holding that file name. **When a dataset already holds that file** is where you
say what happens next:

- **Replace its data** (the default) swaps that dataset's data and keeps its
  identity, so every relationship, merge, chart, indicator, quality rule and
  dashboard widget built on it goes on working. Use it for a fresh export of
  everything collected so far - which is what a live monitoring tool wants: the
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
in the order listed - the first under your replace/append choice, the rest
appended onto what it produced - so every archive's interview file meets the
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
- **A code that changed meaning is reported.** If a revised questionnaire uses
  the same code for a different answer, the rows are still appended but they
  are shown under the labels the dataset already had - so the import says which
  variables recoded, and it is worth checking before trusting a tabulation
  across versions.

Use ▲ beside a file to change the order. The first file is the base, as it is
in a do-file that opens one export and appends the others onto it.

**From a Survey Solutions connection it is one tick.** The server lists every
version as its own entry, so a questionnaire revised twice used to appear three
times in a flat list with nothing saying they belonged together. Now **Import
data** groups them: one row per questionnaire, saying "3 versions · v1-v3", and
ticking it takes every version. Under a questionnaire with more than one there
is a choice:

- **Every version, including any published later** - the default, and the one
  to leave alone. It is stored as the questionnaire rather than as a list of
  versions, so an import that runs again after the form is revised picks up the
  new version by itself.
- **Only the versions ticked below** - for going back for one particular
  version, with a box per version.

The same picker is in **Edit → Questionnaires to import automatically**, which
is what a scheduled import runs on. It had nowhere to be set before, so a
connection could have automatic imports switched on, and a schedule set, and
still never import anything: the scheduler skips a connection with no
questionnaires chosen, and said nothing about it. The dialog now warns while
that list is empty.

They are imported oldest first into **one** dataset, with each version's rows
stamped `questionnaire_version`. Only the first version honours your
replace/append choice; the rest are appended onto it, whatever was chosen.
That is not a detail: with "Replace their data" applied to each version in
turn, v2 replaced v1 and v3 replaced v2, so a run that reported importing three
versions left a dataset holding only the last one - and nothing announced it,
the row count was simply lower than it should have been.

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
with the size and the limit in the message - the limit is `MAX_UPLOAD_MB` on
the server, and an administrator can raise it.

Stata and SPSS are the best choice because they carry variable labels and value
labels; those are read and used everywhere in the interface.

The file is parsed immediately and you land on the dataset with its row count,
variables and detected types.

### Importing from Survey Solutions

See [survey-solutions.md](survey-solutions.md).

### Refreshing

A dataset can be refreshed in place - by re-importing from its connection, or
with **Replace data** for an uploaded file. Charts, dashboards, indicators and
quality checks that point at it keep working, provided variable names have not
changed.

### Tidying up

The dataset list groups datasets by project, and each group collapses - one
survey export is eight datasets, and four rounds of it is thirty-two.

Tick several datasets and **Delete selected** removes them in one confirmation,
or use **Delete all** on a project's group to clear a whole round. Anything the
merge or a chart depends on goes with it, so read the confirmation.

**Rename** on a dataset gives it a name and a description of your own. An
archive names each dataset after the file inside it, which is how a project
ends up holding `R_demographics` and `roster_pp`; those are the names the export
chose, and this is where they become the names your team uses. Nothing breaks:
charts, indicators and merges point at the dataset, not at its name.

Downloads follow the new name too, however many times it has been renamed. The
file arrives as `the-new-name.csv`, not as whatever the dataset was called on
the day it was uploaded.

### Taking a dataset out

**Stata**, **CSV** and **Excel** on a dataset download the whole table. All
three are written from the data the platform is actually querying, not from
whatever was uploaded - so a merged dataset, which never had a file of its own,
downloads like any other, and so does a dataset changed by commands.

Prefer **Stata**: it carries the variable labels and, where the codes are whole
numbers, the value labels. CSV carries neither. Excel stops at a million rows
and says so rather than writing a file Excel would refuse to open.

Downloading is a manager's action, and it is recorded in the audit log.

## Looking at a dataset

The dataset page has four tabs, and a fifth for managers:

- **Variables** - every variable with its label, type, missing count, distinct
  count and range. Variables missing on more than 20% of records are highlighted.
  **Tabulate** on any row gives an instant frequency table with a chart.
- **Data** - page through the raw rows.
- **Statistics** - mean, standard deviation, min, quartiles, median and max for
  every numeric variable.
- **Field progress** - submissions over time, interviews per interviewer and
  supervisor, status breakdown, coverage by area and a GPS map. Appears
  automatically when the relevant columns are recognised.
- **Command** - the Stata-style script box, below. Managers only.

### Naming variables and their codes

An export often arrives with neither name nor labels: a column called `DEM_SEX`
holding 1 and 2, which a table then prints as "1.0" and "2.0". On the
**Variables** tab, **Labels** on any row lets you write the variable's label and
a label for each of its codes.

Nothing about the data changes - only what the platform calls it, everywhere it
is shown: axis labels, legends, cross-tab headers, filter dropdowns. Labels you
write are kept on the dataset as well as on the variable, so a newer export
replacing the file does not wipe them.

**What the codes mean** on the same tab shows what each variable's codes stand
for without opening anything - "1 = Male, 2 = Female", with the rest on the
cell's tooltip. A categorical column stored as numbers with no names for its
codes says so in amber, because until they are written every table of it prints
the codes. A column of 0s and 1s is left alone: that is a tick, not a code.

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
it has already run, as in a do-file, so it stays - the log tells you what got
through.

Commands are **recorded on the dataset and replayed** after a newer export
replaces it. A variable somebody generated is not in the export file, so without
that it would vanish on exactly the upload this platform is built around, taking
every chart built on it. The history is listed under the box: **Edit** puts a
command back in the box, and **Clear** stops the replay without undoing what the
commands already did.

### Running R over a dataset

The Stata box covers generating a variable and labelling it. Everything past
that - recoding a battery of questions, deriving a poverty line, reshaping a
roster - is a few lines of R and no lines of anything this platform could
reasonably invent. So the **R script** tab hands the dataset to R.

The contract is one sentence: **the dataset is a data frame called `data`, and
whatever `data` holds when the script ends is what the dataset becomes** - its
rows, its columns and their types.

```r
data$adult <- ifelse(data$age >= 18, 1, 0)
data$age_band <- cut(data$age, c(0, 15, 25, 65, Inf), right = FALSE)
data <- data[!is.na(data$age), ]
```

Base R is enough; nothing needs installing. Packages an administrator has
installed on the server are available too - base R is the floor, not a ceiling.
Anything the script prints comes back under the box, so `cat()` and `print()`
are how it is debugged.

A script that fails changes nothing: the frame is read, the script runs, and
only a script that finished writes anything back. The error R gave is shown as
R gave it.

Like a Stata command, the script is **recorded and replayed** after a newer
export replaces the dataset, and in its turn among the Stata commands beside
it - so a script reading a variable that `gen` created still runs after it. The
list on the right shows both, in the order they will be re-run, with the R ones
marked.

The round trip goes through CSV, which is what base R reads and writes with no
packages at all. Types are therefore re-read on the way back in, exactly as
they would be from an uploaded CSV, and a variable's label survives as long as
its column does.

**What this is and is not.** Running R here is running a program on the server.
It can read what the server can read and reach what the server can reach. The
timeout and the memory limit stop a script that runs away; nothing stops one
written to do harm, and there is no list of forbidden functions, because a list
like that over a language with `eval(parse(text=))` would only be a promise
nobody can keep.

So it is **off until an administrator turns it on**, with `R_SCRIPTS_ENABLED=true`,
and only a manager or an administrator can reach it. Turn it on where the
people who can open the command box are people you would trust with a shell on
that server. `R_TIMEOUT_SECONDS` (60 by default) and `R_MEMORY_MB` (2048) bound
one run; every script that runs is written to the audit log with the account
that ran it.

## Explore

**Explore** is where analysis happens. Two modes.

### Tabulate & chart

1. **Group by** one or two variables. Dates offer a grain (day, week, month,
   quarter, year). Numeric variables can be binned by width. The first grouping
   can keep the top N categories and fold the rest into "Other". Any variable
   can be grouped on, `interview__key` included - a variable with a value per
   row says how many values it has beside its name, and the row limit decides
   how much comes back.
2. **Measure**: count, share of total, sum, mean, median, min, max, standard
   deviation, percentiles or distinct count. Add several measures to compare
   them side by side. Any measure can be weighted by a numeric variable - pick
   your survey weight to get weighted estimates.
3. **Filters**: as many conditions as you like, combined with all/any. Variables
   with value labels offer a dropdown of their labels.
4. **Display**: how it is drawn, below. Then **Run query**.

Results can be viewed as a chart or a table, exported to CSV or Excel, and saved
as a chart for use on a dashboard. **Show SQL** reveals the generated query if
you want to check what was computed.

If you are not sure where to start, **Suggested analyses** proposes charts built
from the dataset's own variables - one click to run.

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
they start with rather than as text, so "5-9" lands between "0-4" and "10-14"
rather than after "45-49".

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

**One variable on its own.** Leave either Rows or Columns empty and you get
that variable's frequencies rather than a cross-tabulation - which is what
"tabulate this" usually means before anybody wants it crossed with something.
The missing side becomes a single column named after the measure ("Count",
"mean of age"), so it saves, exports and goes on a dashboard like any other
table. Percentages on a one-way table are shares of the total, since that is
the only denominator it has, and there is no chi-square: there is no
independence to test between a variable and nothing.

### Tick all that apply

A multiple-select question does not arrive as one variable. Survey Solutions
writes one column per option - `toilet__1`, `toilet__2`, `toilet__3` - each
holding 1 where that option was chosen and 0 where it was not. Tabulating any
one of them answers "how many households have a flush toilet"; none of them
answers "what do households use", which is the question that was asked.

This tab puts the set back together. It reads the column names and offers the
questions it found, so picking **Main source of drinking water** is one choice
rather than ticking twelve columns. Each option becomes one bar, counted down
its own column.

The shares add to more than 100, and that is correct: a household that ticked
three options is counted in three of them. **Percent of** decides the
denominator - the people who were asked the question, which is the usual
reading, or every row in the file, for a dataset where most rows were never
asked it.

**Show** decides which number is drawn. A count and a percentage on one axis
are two scales pretending to be one, so a chart takes one of them; a table is
the place for both.

Untick an option to leave it out - the "other" and "don't know" options usually
belong on the table and not on the chart - and the percentages stay shares of
the same respondents, so leaving a bar out does not inflate the rest.

**Choose the columns myself** is there for a file that does not follow the
`name__1` convention: search for the columns that hold the question and tick
them. Anything holding 1 and 0 works, and so does Yes/No, since a CSV round
trip turns one into the other often enough.

#### What the options are called

The bars carry the option's own words wherever the file has them, which is
usually in one of two places, both read on import:

- **The option column's label.** An export that labels `hhld_goods__8` as
  "Household goods: Bicycle" gets "Bicycle" - the question's own words are
  taken off the front, because they are already the chart's title and repeating
  them on nineteen bars makes the axis unreadable. Where every option column
  carries the same label word for word, that label is the question and not the
  answer, so it is passed over rather than printed on every bar.
- **The question's own codes.** Many exports leave those columns unlabelled and
  keep the option text in the question's value labels, where code 8 reads
  "Bicycle" - and the 8 in `hhld_goods__8` is that code. This is read on
  import and written into the columns as their labels, so the names appear
  everywhere the columns do, not only on this chart.

A file that carries neither leaves the options numbered: **Option 1** to
**Option 19**, which sends the reader to the questionnaire to find out what
option 8 was. The panel says so, and **Name them** puts every option in one
dialog with a box each. The names are the columns' labels, kept on the dataset,
so they show in every chart, filter, cross-tab and table, and they survive the
next export replacing the file.

The **Options to show** list is drawn under the same names, so ticking eight
boxes out of nineteen is choosing between options rather than between column
numbers.

Saved as a chart it goes on a dashboard like any other, drawn horizontally or
vertically, and dashboard filters reach it: filtering to one province moves the
counts and the denominator with them. Clicking a bar does not filter the
dashboard, because the bars are columns of the file rather than values of one
variable, so there is no filter a click could stand for.

## Charts and dashboards

Any Explore result can be saved as a chart. Saved charts live under
**Dashboards → Saved charts**, each showing live data.

The **project** dropdown at the top narrows both tabs at once. A dashboard
carries a project of its own; a chart takes one from its dataset, so the two
agree about where something lives without anybody keeping them in step. Leave
it on **All projects** to see everything, which is what it does until you
change it.

**Edit** on a saved chart opens it back in Explore with everything it was built
from already filled in - the grouping, the measure, the filters, the chart type
and how it is drawn - and runs it, so you are looking at the chart you are
about to change. Change the variable, add a filter, switch it to a horizontal
bar, then **Save changes**: it writes back to the same chart, so every
dashboard showing it follows. **Stop editing** leaves it as it was. Saved
cross-tabulations edit the same way, in the cross-tabulation tab.

To build a dashboard:

1. **Dashboards → New dashboard**. Choose the project it belongs to, or leave it
   in the shared area.
2. **Add widget** - see the list below. A dashboard that belongs to a project
   is offered that project's charts, indicators and datasets rather than every
   one on the platform; a dashboard in the shared area belongs to no project,
   so it goes on seeing everything you can.
3. **Move & resize** - turns on dragging and resizing; the layout saves itself.
4. **Edit** - hover a widget and use the ✎ to change anything about it: what it
   shows, its title, its width and height, its background colour, and which
   page it sits on. The ✕ beside it removes it. Both are there whether or not
   you are arranging. A widget's own colour still takes the dashboard's
   transparency, so the two settings do not cancel each other.
5. **Pages** - **+ Page** adds one; double-click a tab to rename it, and ◀ ▶
   move it earlier or later. A page takes its widgets with it, so reordering is
   safe. Each page lays out on its own and has its own filters.
6. **Filters** - see below.
7. **Appearance** - background, canvas and transparency; see below.
8. **Colours** - the picker in the header sets which palette this dashboard's
   charts use. The alternatives are the same hues in a different order, chosen
   for how far apart neighbouring series stay for colour-blind readers.
9. **Share link** - generates a read-only public URL, copied to your clipboard.
   Anyone with the link can view the dashboard without an account. Press again
   to revoke it.
10. **Give it a name** - where an administrator has configured a dashboard
    domain, a shared dashboard can also answer on its own address, such as
    `labour-force.dash.example.org`. See below.

### The widgets

| Widget | Shows |
|---|---|
| **Saved chart or cross-tab** | A chart or a two-way table saved from Explore, re-run against current data |
| **Indicator tile** | One tracked number with its target, status colour and trend - and optionally its breakdown drawn as a chart beneath |
| **Data quality panel** | The last result of every check on a dataset, and how old the oldest one is |
| **Text note** | A heading, an explanation, a caveat |
| **Countdown to a date** | Time remaining to a deadline, ticking, with your own label and a message for when it passes |
| **Map of interview locations** | GPS points from a dataset, grouped by coordinate - up to 50,000 places. Click a point for its count or any aggregate, plus the detail columns you chose |
| **Embedded HTML** | Whatever HTML you paste, rendered in a sandboxed frame - a logo, an embedded video, a link bar |
| **How recent the data is** | When each dataset was last imported, and how old its newest record is |

The **freshness** widget answers two questions, because a monitoring tool needs
both. *When did the platform last receive data* says whether the import is
running. *How recent is the newest record* says whether the field teams are
still sending anything - an import that runs faithfully every morning and
collects nothing new looks healthy by the first measure and is exactly what the
second one catches. It turns amber after 24 hours and red after 72 by default;
both thresholds are yours to set.

It picks the date variable that says when a record happened - an interview date,
a submission or sync timestamp - and deliberately ignores dates that are
answers rather than moments, such as a date of birth. Where a dataset has no
obvious one, or the wrong one is chosen, name the variable yourself on the
widget.

### Boundaries

**Datasets → Boundaries → Add boundaries** takes the frame fieldwork is
organised into - enumeration areas, districts, villages - as GeoJSON, a
GeoPackage (`.gpkg`), or a shapefile zipped together with its `.dbf` and
`.shx`. Whatever your GIS office exports is read as it is; nothing has to be
converted first.

A layer left in the shared area is available to every project, which is what a
national frame usually wants. One given a project stays with it.

Reading a boundary file needs no GIS software on the server and no internet at
the moment it is read, which is deliberate: this platform is meant to run in a
statistics office behind a ministry firewall, and a feature that quietly needs
a download the first time it is used is a feature that fails there.

What a layer is good for is the two things below.

### Drawing boundaries under a map

A map widget's **Boundaries** setting draws a layer's areas beneath its pins,
in outline rather than filled, so the ground under them is still visible on the
satellite view. **Write on each area** picks which of the layer's attributes
names it; hovering an area shows that name.

The map frames itself on the layer rather than on the pins when one is chosen.
A single coordinate recorded in the wrong hemisphere would otherwise squeeze
the whole survey into a thumbnail to keep that one mistake on screen.

**Turning the outlines off.** The layers box in the map's top right corner,
which chooses the ground, also carries a tick-box for the boundary layer by
name. Untick it and the outlines go; tick it and they come back, under the pins
where they were. Boundaries are drawn to be read against, and there are maps
where they are the thing in the way: a cluster of households inside one
enumeration area is a handful of pins under a heavy line, and "which of these
is on the wrong side of it" is asked by taking the line off and putting it
back. It is the reader's choice rather than the author's, so it lives on the
map and not in a dialog only the board's author can open.

**Point shape** draws the pins as circles, squares, triangles, diamonds or
pentagons. A circle is right when the size of the pin carries a quantity. A
shape is right when the map is answering "what happened here", because shapes
are told apart at a glance and in a photocopy, which two shades of one colour
are not.

**Fill the window**, on the widget's menu, fills the screen with the map. See
below: it works on every widget, not only maps.

### Checking that a record was collected where it says it was

This is what the boundaries are really for.

A household listing records the enumeration area the interviewer says they were
in. The device records where they actually were. Those two disagreeing is one
of three things, and each is worth knowing during fieldwork rather than after
it: an EA code typed wrong, an interviewer working the wrong area, or a
boundary the field reads differently from the office.

Set **Recorded area** to the variable holding the code the interviewer
recorded, and **Matched against** to the attribute on the boundary layer that
holds the same code. Every pin is then coloured by its verdict, and the legend
counts them:

| | |
|---|---|
| **Red** | The recorded area does not match the area the GPS falls in |
| **Amber** | The point is outside every area in the layer |
| **Purple** | No area was recorded on this record |
| **Green** | The recorded area agrees with the GPS |

Clicking a pin says which area was recorded, which one it is standing in, and
whatever detail columns the widget carries - usually enough to name the
interviewer to ask.

A point outside every area is deliberately not counted as a mismatch. It is
usually a frame that does not cover an island yet, or a coordinate in the wrong
hemisphere, and folding it in with the real mismatches would bury them.

Codes are compared by what identifies them rather than by how they were typed.
`07`, `7` and `007` are one enumeration area: a code crosses from a
questionnaire to a GIS file as text on one side and a number on the other, and
treating those as different would report every record in the country as a
mismatch.

### The ground under a map

A map widget draws its pins on one of three grounds, chosen when you add it and
changeable afterwards from **✎**:

- **Streets** - OpenStreetMap, the default.
- **Satellite** - aerial imagery, with place names and boundaries drawn over it
  so a cluster of pins can still be read as a village rather than a shape.
- **Terrain** - contours and relief, for fieldwork where the question is what
  the ground is like between two points.

A reader can also switch grounds on the map itself, from the control in its top
right corner, without editing the widget or being able to. That choice is
theirs for as long as they have the page open; the one saved on the widget is
what everybody starts on.

All three fetch their tiles from the internet. A server that cannot reach them
still draws the pins, on a plain ground, and says so under the map - and a
deployment with its own tile service can be pointed at it with **Map tiles**,
which replaces the three and hides the switcher, since a choice between hosts
this server cannot reach is no choice at all.

### How the pins are drawn

The pins on a map are set from **✎**, and the defaults are only defaults:

- **Point shape** - a circle, or a shape with corners. A shape survives a
  photocopy and a colour-blind reader; a shade of a colour does not.
- **Point colour** - any colour, from the swatches or the picker. Default blue
  when nothing is chosen.
- **Point size** - how big a pin is before the value scales it, from 6 to 40.
- **Point transparency** - how much shows through. A low value is what turns a
  crowd of overlapping pins into readable density instead of one solid blob,
  which is why the default is 60% rather than solid.
- **Bigger pins where the number is bigger** - on by default. Each pin is sized
  by what it carries, so a village with 40 interviews reads as bigger than one
  with 3. Turn it off when the question is where the work happened rather than
  how much of it, and every pin is drawn the same size.

Where a map checks records against a boundary layer, the verdicts - the
matches, the mismatches, the ones outside every area - draw their own colour
and their own size instead, because on that map the colour is the finding and a
pin sized by a second number would compete with it.

### Reusing an embed

An **Embedded HTML** widget holds a piece of markup - a map, a video, the
bureau's own banner. The same one usually belongs on several dashboards, often
across surveys, and pasting it into each widget let the copies drift: a
corrected link was fixed in one place and left wrong in four.

**Save to library** on the widget keeps it under a name; **Load from
library** on any other HTML widget brings it back. A snippet saved to the
shared area is offered in every project, which is the point; one saved to a
project stays with it.

Loading takes a *copy* of the markup rather than a live reference, deliberately.
A widget that changed under its dashboard because somebody edited a shared
snippet would be a worse surprise than one that is merely out of date - so
editing a snippet changes the library, and removing one leaves the dashboards
already built from it alone.

### Share links

**Share** lists every address this dashboard is published at, and adds more.

One board usually goes to several audiences at once - a minister, the field
supervisors, a donor - and those do not end together. Each gets its own link,
so closing the donor's access when the report is filed leaves the supervisors
working. Each link records how often it has been opened, which is how a link
nobody uses can be recognised and closed.

**Close** a link rather than deleting it. A closed link stops working and can
be switched back on at the same address, which matters once it is already
pasted into somebody's email. Deleting is permanent.

**Stops working after** gives a link an end date. It works all of that day,
where you are, and is shut the next morning - so "expires on the 3rd" means
what a date on a pass means. This is closing a link without having to remember
to: the donor's copy was for a report that has since been filed and the
workshop's was for the workshop, and both otherwise stay open until somebody
thinks of them. An expired link is marked **Expired** in this list and still
here: type a later date and the same address opens again, or use **No end
date** to take the end off. To a reader an expired link and a closed one say
the same thing, which is that the dashboard is not available - not that it
expired on the 3rd, which tells a stranger more about the work than the address
itself does.

A link can carry a **password**. The reader is asked for it once and then reads
the dashboard normally; it is remembered for that browser tab only, so a shared
computer in a field office does not leave the next person signed in. This is
not an account - everyone holding the password is the same anonymous reader -
and it exists so that a forwarded link is not a public one.

### Taking the dashboard away as a file

A link needs susoDash running and reachable. **Share -> Download as a web page**
gives you the board itself: one HTML file, which you can put on any web host,
attach to a report, or send to somebody who will open it from their own disk.

**Its filters still work.** That is the point of it. The file carries the
numbers behind each widget rather than a picture of it, grouped by what the
widget groups on *and* by every variable the page's filter controls name.
Choosing "Shefa" keeps the rows where the province is Shefa and adds the
measures back up, which is exactly the number the platform would have returned:
a sum of counts is a count. An average is carried as its total and the number
of values behind it, so it is divided again rather than averaged twice - an
average of averages is not an average unless every group happens to be the same
size, and quietly returning one would be worse than not exporting it at all.
The page tabs work too, and each page keeps its own controls.

What the copy does not do:

- **Clicking a mark does not filter it.** The dropdowns are the filters.
- **The charts and the map are drawn by libraries fetched from the internet**
  (ECharts and Leaflet, from public addresses, pinned to a version). A machine
  with no connection still opens the file and reads every number - each chart
  falls back to its table - but it will not draw the pictures, and the map will
  have no ground under its pins.
- **Some widgets are frozen** and say so on their face, with the reason. A data
  quality panel and a freshness panel report what their last run found rather
  than answering a query, so there is nothing for a filter to narrow. A chart
  resting on a median, a distinct count, a percentile or a standard deviation
  cannot be worked out again from group totals - a median of medians is not a
  median. A tick-all-that-apply chart is built from columns rather than groups.
  A widget with so many combinations of groups and filter values that the file
  would be enormous is frozen too. All of them are still drawn, as they stood
  when the file was made.
- **Boundary outlines are left out of the map.** A national frame is megabytes
  of coordinates and would dwarf the rest of the file.

The file says at its foot when it was made. Nothing in it goes back to the
platform, so the numbers are the numbers of that moment: export it again when
they should be newer.

### Giving a dashboard its own address

A share link ends in a 64-character token. That is what makes it safe to send
to one person - nobody guesses it - but it is not something you can put on a
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

Names live under the one configured domain, and reserved names - the platform's
own address, `www`, `api`, `admin` and similar - cannot be taken. If the option
is not there, no domain is configured; an administrator sets `DASHBOARD_DOMAIN`
along with the DNS record and certificate described in
[deployment.md](deployment.md).

### Filtering by clicking a chart

Click a mark and the rest of the page follows it. That means a bar, a slice, a
point on a line or scatter, a heatmap cell, a table row, an indicator's
breakdown bar, or the row and column headings of a cross-tab. Click the Shefa
bar on "Interviews by province" and every other widget on that page shows Shefa
only, with a bar across the top saying what is selected and a **Clear** beside
it.

A cross-tab is the one with two answers rather than one, so which heading you
click decides which variable is used: a row heading filters by the row
variable, a column heading by the column variable. The cells themselves are not
clickable - a cell is both at once, and filtering by two things from one click
is not what anyone expects of it.

On a pie or a doughnut, **the legend counts as the chart**. The slices carry
only a value and a percentage, so the name of a category appears once, in the
legend, and that is where the hand goes. A click there filters the page like a
click on the slice does. It used to do the one thing nobody wanted: hide the
slice.

The chart you clicked is deliberately left alone - it is the thing you are
clicking, and narrowing it to the one bar you just chose would take away the
means of choosing another. Clicking the same mark again lets go of it, and
changing page clears it, since a selection means nothing to widgets reading
another dataset.

It stacks with the filter controls below: a click narrows whatever they have
already narrowed. Widgets whose dataset has no such variable say so rather than
quietly ignoring it, exactly as with the controls.

The board does not blank while it refilters. The numbers already on screen stay
up, dimmed slightly, until the new ones arrive - so a click is acknowledged
without the page being torn down and rebuilt. A dashboard left up on a wall is
not dimmed by its own timed refresh, only by a selection somebody made.

### Filters

**Filters** on a dashboard adds controls its readers can use: pick a variable
and every viewer gets a dropdown of its labels, which narrows every widget
underneath.

**Name them.** Beside each ticked variable is a box for the label the filter
carries on the dashboard. It starts from the variable's own label, or its
column name where the data has none, and can be typed over - a board built for
a minister should say "Province", not `hh_prov_cd`.

Filters belong to **the page they are on**, so a "Fieldwork" page can filter by
interviewer while a "Coverage" page filters by district. A control only applies
to widgets whose dataset actually has that variable; widgets that cannot answer
it say so rather than quietly ignoring it.

Indicator tiles and the data quality panel follow the filter too. Both normally
show what the last scheduled run worked out, so opening a board does not set a
query going for every tile on it; under a filter there is nothing stored to
show - no run ever counted only the rows you are looking at - so they are
counted afresh and say **Counted for the filters on this page** in place of the
"Updated" time. A tile that is a percentage narrows both halves of its
fraction, so filtering to one province gives that province's rate rather than
its share of the national total.

**Removing one** is the same dialog: untick it and save. If a filter's data has
since left the page - the widget that brought its dataset was moved or deleted,
or the variable now has too many values to filter by - it appears in its own
section at the bottom with a **Remove** beside it. Such a filter used to be
impossible to get rid of: it was still drawn on the bar, but the dialog had no
tick-box to untick, and saving wrote it straight back.

The bar itself can be made to fit the dashboard: **Appearance → Filter bar
colour** sets its background, for when plain white floats oddly over a coloured
one.

### Making it yours

**Click the dashboard's title** to open these controls - or use **Appearance**,
which is the same thing.


A dashboard is usually the thing a survey team shows other people, and it
belongs to them rather than to the platform. **Appearance → Header** is where it
says so:

- **Logo** - upload your organisation's mark (PNG, JPEG, GIF or WebP, up to
  8 MB). It sits beside the title, at whatever height you set, and it travels
  with the shared link, where it matters most.
- **Title size** - from 16 to 64 pixels, so a board left on an office wall can
  be read from across the room.
- **Title font** - the interface face, or a grotesque, serif, slab or
  monospace. All of them are already on the machine, so a screen with no
  internet still renders in the face you chose.
- **Title colour and alignment** - your colour, left or centred.
- **A rule under the header**, and the option to **hide the description**, for
  when the title alone is the whole heading.

### Giving a widget its own colour

A widget's **background** is any colour, and the gloss follows it: light over
the top half, shadow over the bottom, meeting on a hard line. Black comes out
as glossy black, and so does everything else - the finish is a tint over the
colour rather than a coat of paint on top of it.

Set a dark background and the widget's text follows without being asked: the
title, the caption, and the chart's own axes and legend all turn light, because
a black widget with near-black labels is a black rectangle. Choosing a **text
colour** yourself always wins over that.

### How a widget's chart is drawn

**Edit this widget** carries two controls over the chart itself, beside its
colour:

- **Print the value on each bar, slice or point.** The same question the chart
  was built with, asked again where it is read: the same chart wants its
  numbers on when it is a quarter-tile on a wall and off on a crowded page.
  Leave it as the chart was saved, or decide either way here. Past two dozen
  marks the numbers are dropped whatever is asked, because a digit on every one
  of forty bars is a wall rather than a label.
- **Chart text size**, from 8 to 28 pixels. The axes, the legend and those
  printed values together, rather than a control for each: what makes anybody
  reach for it is a board read across a room or a widget shrunk to a corner,
  and in both cases it is all of the text that is the wrong size. **Default**
  puts it back to 12.

### A widget's menu

Everything a widget can be asked to do sits behind one button at the top right
of it, marked with three dots and shown when the pointer is anywhere over the
widget. On a board being arranged it stays visible.

It holds, depending on what the widget is and who is looking:

- **Copy the table, for Excel** or **Copy as a picture** - see below.
- **Fill the window** - see below.
- **Move to (page)**, where the dashboard has more than one, with a tick
  against the page it is on now.
- **Edit this widget** and **Remove from dashboard**, for whoever can edit.

These used to stand in a row in the title bar, which on a narrow tile left the
title a few characters wide before it was cut off. A menu costs one more click
on things nobody does twice a minute, and gives the title its bar back.

### Taking a widget with you

The widget's menu offers to copy it, for readers as well as authors.

On a table it copies the rows to the clipboard as cells: paste into Excel and
they land in columns, paste into a plain editor and they arrive tab-separated.
What is copied is what is on screen, so a table narrowed by its column filters
copies narrowed.

This works on a plain HTTP deployment as well as over HTTPS. The modern
clipboard interface exists only on a secure connection, and it is also allowed
to take its time - by which point the browser has stopped counting your click
as permission to copy, and it refuses without saying so. The button therefore
uses the older synchronous copy first, which asks for no permission and needs
no secure connection, and still carries the HTML that makes Excel fill cells.

On a chart it copies a picture, ready to paste into a report. Where a browser
refuses to put an image on the clipboard - several do, outside a secure
connection - the picture is saved as a file instead, which reaches the same
document by a longer road.

### Filling the screen with one widget

**Fill the window** on any widget's menu blows it up to the size of the window,
for reading small values on a crowded chart, a table longer than its tile, or
one red pin on a map. **Escape** or **Close** puts it back.

The dashboard behind it keeps running, and the widget is the same one, so a
filter applied before expanding is still applied inside it - and it is drawn in
its own colours, on the dashboard's own background, so a widget built to be
read on a dark board is still read on one. Blowing a widget up makes it bigger
and changes nothing else.

### Filtering a table by its columns

The **⌕** button above a table opens a box under each heading. Typing in one
narrows the rows on screen, and the button then reads how many of how many are
showing.

Text matches on what the cell reads as, so typing a label matches the label
rather than the code behind it. A number column also takes a comparison -
`> 100`, `<= 0` - because the question asked of a measure is rarely which of
its values contains a 7.

This narrows what is already on screen rather than asking the server a new
question, so it is instant, and it does not change what anybody else sees.

### Captions

Every widget takes an optional **caption**, set when you add it or from **✎**
afterwards. It appears under the widget in small print - the place a figure
caption goes in a report, and out of the way of the numbers at the top.

Use it for what the reader cannot see: which rows are counted, what was
excluded, where a target came from. A caption travels with the widget onto a
shared dashboard, so the people reading the link get it too.

### One widget at a time

**✎ on a widget** sets what belongs to that widget rather than the whole
dashboard: its own background colour, its own transparency, a font, a text
colour, a face for its title, and - for a chart - the colour it leads with.

Each falls back to the dashboard when it is left alone, so a single tile can be
lifted off a busy background without lifting all of them.

**Title font**, **title size** and **title position** dress the widget's
heading on its own, in the same typefaces the dashboard title offers. A centred
title suits a tile that is read on its own; the default left is easier to scan
down a column of widgets. A tile meant to be read across a
room can carry a heading twice the size of the ones beside it without every
other widget growing to match.

**Text colour** is the whole widget's writing, not the heading alone: the
title, the caption, and the labels on the chart - its axes and their names, its
legend, and the values printed beside its marks. A value printed *on* a mark
stays white, because it sits on a filled bar or slice rather than on the page,
and giving it the colour of the axis is how it disappears into the bar it is
labelling.

A chart's colour is a *lead* colour, not the only one. A chart with several
series keeps distinct hues behind the one chosen, because painting every series
the same colour leaves nothing but the legend telling them apart - and a
colour-blind reader cannot use that either. Colours can be picked from the
swatches, typed as a code like `#1F4E79`, or chosen with the system picker;
the swatch row for marks is in an order already checked to stay readable for
colour-blind readers.

**Shadow** lifts one widget off whatever is behind it - useful on a coloured or
photographic dashboard background, where a flat card can read as part of the
picture rather than as something on top of it.

### Appearance

The rest of **Appearance** controls how the dashboard is dressed:

- **Background** - a colour, or an uploaded image (PNG, JPEG, GIF or WebP, up to
  8 MB), set to fill the page, fit whole, or repeat, with a fade slider so text
  stays readable over it.
- **Canvas width** - fit the window, or a fixed width that scrolls, for a
  dashboard meant to go on a wall. **Columns** and **row height** set how fine
  the grid underneath the widgets is.
- **Widget transparency** - how much of the background shows through the
  widgets, from solid to barely there.
- **Behind the page tabs** - the colour of the tab band, so tabs stay visible
  when the dashboard background happens to be the same colour as their text.
- **Page tab colour** and **filter label colour** - the text itself. Left alone,
  the platform picks black or white from whatever is behind the tabs, which is
  right most of the time and occasionally not; the filter labels stay a fixed
  grey that a dark filter bar swallows. Either can be set outright.

## Monitoring

### Indicators

An indicator is one tracked number.

**Monitoring → New indicator**: name it, pick a dataset, choose the measure
(count of records, or an aggregate of a variable), and optionally:

- a **target**, which draws a progress bar,
- a **warning** and **critical threshold**,
- a **direction** - with "higher is better", the indicator turns amber at or
  below the warning threshold and red at or below critical; with "lower is
  better" the logic reverses,
- a **breakdown variable**, so the indicator can be expanded per region or team,
- a **target for each group** of that breakdown, once one is chosen,
- a **percentage**, where the number is a share rather than a count.

The datasets offered are the ones in whatever the project filter above the page
is set to, because an indicator belongs to whatever project its dataset belongs
to. Building one from a dataset in another project is how an indicator quietly
ends up somewhere its team will not find it, so under a project you are offered
that project's data, and under "All projects" you are offered everything.

**Percentages.** Filters pick the rows the indicator counts; *percent of* says
what they are a share of. "Of all rows" divides by every row in the dataset
before the indicator's own filters - that is how "% of interviews completed" is
expressed. "Of those who answered" divides by the rows that answered the
measured variable, which is the same question asked of a variable rather than of
the file.

**✎ on an indicator** edits all of it - the measure, the filters, the target and
thresholds, the breakdown, even which dataset it reads. A threshold set before
fieldwork started is a guess, and correcting one should not mean deleting the
indicator and losing its history.

**A target per group.** A survey's quota is rarely one number: "6,000
interviews" is really 3,500 in one province and 2,500 in another, or a set
number of men and of women. Once a breakdown variable is chosen, each of its
groups gets a target box, filled from the values actually in the data. A group
left blank is judged against the overall target.

The warning and critical thresholds scale with whichever target applies, so a
province carrying a tenth of the quota trips its warning at a tenth of the
count. Without that, every small province sat permanently in the red - and,
worse, a group well behind its own quota could read as on track simply because
the overall target is the sum of several unequal ones.

On a dashboard, an indicator tile shows its breakdown as a chart when **Show
the breakdown** is ticked on the widget, and clicking one of those bars filters
the page by that group, like any other chart.

Once groups have targets, that chart becomes a quota chart: **the bar is the
target**, split into what has been achieved and what is still to go, with
anything past the target as its own segment. Read across, the coloured part is
the actual and the whole bar is the quota. A province at 109 of a quota of 400
is then obviously behind one at 89 of 100, which the raw counts alone hide.

Stacking the actual *on top of* the target would not mean anything - 86
interviews plus a quota of 100 is not 186 of something - which is why it is
built as progress through the target instead.

"Lower is better" reads the other way round, and the chart follows: there the
target is a ceiling, so there is no "still to go" - the space under a limit is
not something anyone is trying to fill - and passing it is drawn as a warning
rather than as good news.

Indicators recompute on a schedule and store a snapshot each time, which is what
gives every indicator a trend line.

To count something specific - completed interviews, say - put a filter in the
indicator's query, the same as in Explore.

### Alerts

**Alerts → New alert rule**: pick an indicator, a comparison and a threshold.
When the condition holds, an alert is raised with the severity you chose, and
delivered in-app and optionally by email. The cooldown stops one ongoing problem
generating a stream of alerts. When the value recovers, open alerts for that rule
resolve automatically.

**Test now** evaluates the rule immediately rather than waiting for the
scheduler - useful for confirming a threshold does what you meant.

Alerts can be acknowledged (someone is looking at it) or resolved (it is dealt
with).

### Data quality

**Data quality** lists the checks on a dataset and whether each is passing.

The platform inspects a dataset and recommends checks that suit it - duplicate
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
reporting a failure. Zero means any occurrence fails - right for duplicate
interview keys. A few percent is more sensible for short interviews.

**Edit** changes a check and re-runs it, so the stored result never describes a
definition that no longer exists. The check type is fixed - changing that would
make it a different check.

A check can also be restricted to part of the dataset. The filter narrows the
total as well as the flagged rows, so the failure rate stays a rate of what was
actually checked: "3% of interviews in Shefa", not "3% of everything, some of
which was in Shefa".

Checks run every six hours, and on demand with **Run** or **Run all**. Add a
**data quality panel** to a dashboard to keep the results where people look;
it shows the last run rather than re-running eight full scans every time
somebody opens the page, and says how old the oldest result is.

Each failing check is a pane of coloured glass with a rail of solid colour down
its left edge and its failure rate on the right, so a column of them is read
down the rails and the numbers rather than by reading every sentence. It is the
same material as the buttons and the cards around it, which is the point: a
finding is part of the interface, not a notice pasted onto it.

**Show it as** turns the panel into a chart. A list of findings reads at a
desk; a board on a wall is read from across the room, and "is this getting
better" is a question about a line rather than about today:

- **The findings, listed** - the panes above, and the default.
- **Share of rows failing** - one bar per check, longest first. The bar is
  coloured by what the check found rather than by where it sits, so a green bar
  above a red one is not a mistake: a check allowed 5% and sitting at 3% is
  passing, while one allowed nothing and sitting at 2.5% is not, and the colour
  is the only thing that can say so.
- **How many rows flagged** - the same chart in counts, for when the question
  is how much work the fixing is rather than how bad the rate is.
- **Failure rate over time** - a line per check across the last month, drawn
  from the runs already stored. The last run of each day is the day's point,
  because the checks run every few hours and four points a day land on top of
  each other at the width a widget has. A day with no run is a gap rather than
  a straight line across it: a check added last week has nothing to say about
  the week before.

The line is drawn from stored runs, which counted the whole dataset, so the
page's filters do not reach it and the panel says so under the chart. The two
bar charts are the current state, so they narrow with the page like everything
else.

**A filtered page filters the panel.** Narrow a dashboard to one province and
the panel counts that province: no stored run ever counted only those rows, so
it counts them now, and a failing check says how many of how many rows in view
failed. It then says "Counted for the filters on this page" instead of showing
a time, because there is no last run to date it by - the numbers were worked
out for the question you are asking. A check restricted to part of the dataset
keeps its own restriction and takes the page's on top of it. Remove the filters
and it goes back to reporting the stored run, which costs nothing.

## API keys

**Administration → API keys** creates a key for scripts and integrations. The key
is shown once - copy it then. See [api.md](api.md).

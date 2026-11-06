# User guide

## Finding your way

The documentation is built into SurveyHQ. Click **Help** in the sidebar (under
System) to read and search it. It works without an internet connection and is
updated with each release, so it always matches the version you are using.

### Keyboard shortcuts

- In a dialog, **Enter** clicks the main button (Save, Add, Apply and so on) and
  **Escape** closes the dialog. In a multi-line text box Enter adds a new line,
  and in a list of suggestions it picks the highlighted one.
- In the script editor on the **Scripts** page, **Ctrl+Enter** (**Cmd+Enter** on
  a Mac) runs the script and **Ctrl+S** (**Cmd+S**) saves it. **Ctrl+Space**
  shows suggestions; **Enter** or **Tab** inserts the highlighted one and
  **Escape** closes the list.
- Some empty boxes show a suggested value in grey, such as the name for a saved
  chart or the label for a variable. A small **Tab** marker appears when you
  click into the box. Press **Tab** to fill in the suggestion; press it again to
  move to the next field. **Shift+Tab** never fills anything in.

### Deleting things

Delete options are kept behind the **⋯** button on datasets, dashboards, saved
charts, indicators, scripts and projects. Before anything is deleted, a dialog
tells you what will be removed.

### The Overview

The **Overview** page shows the main figures and a **Needs attention** list. The
list includes open alerts and anything else that is currently wrong:

- a data quality check that failed on its last run
- an import that failed
- a script that stopped on its last run
- a merged dataset or brought-in variables that couldn't be updated

Each item links to the page where you can fix it, and disappears once it is
fixed.

On a new installation, the Overview also shows a **Getting started** list with
six steps: create a project, bring in your data, check its quality, track a
number, build a dashboard and invite your team. Each step is ticked off
automatically once it is done, and **Start here** takes you to the next one. The
list is shown to managers and administrators only (inviting the team is for
administrators). It disappears when all steps are done, or you can remove it
with **Hide this list**.

### Breadcrumbs

The top bar shows where you are, for example **Datasets › Household roster** or
**Indicators › Targets**. Click the first part to go back to that list. On small
screens the breadcrumbs are hidden.

### Appearance

Click the palette button in the top bar to open **Appearance**. These settings
only change how the screen looks and are saved in your browser on this
computer.

- **Theme**: Light, Dark, or **As the computer** (the default), which follows
  your operating system setting.
- **Surfaces**: Flat (the default) or Aero, which adds gloss and shading to
  panels, buttons and input boxes. Both work in light and dark mode.
- **Side pane colour**: choose one of nine colours or pick your own. Text colour
  adjusts automatically so it stays readable.

### Pinning the side pane

Use the pin at the top of the side pane to keep it open or collapse it.

- **Pinned**: the full menu is always visible.
- **Unpinned**: the menu shrinks to a row of icons, giving the page more room.
  Hover over it (or tab into it) to open it over the page. Each icon shows its
  name as a tooltip.

The pin setting is saved to your account, so it is the same on every computer
you sign in from.

## Roles

| Role | What they can do |
|---|---|
| **Viewer** | View dashboards, and view the data in datasets they have access to (the Data tab, Analyse and exports of results) |
| **Analyst** | Everything a viewer can do, plus build charts and dashboards and run any analysis |
| **Manager** | Everything an analyst can do, plus upload data, download whole datasets, and manage connections, scripts, indicators and quality rules |
| **Administrator** | Everything, plus manage users and settings and view the audit log |

A role controls what someone can do. Which data they can see is controlled
separately, by projects. Within the projects they have access to, viewers can
see datasets as well as dashboards.

- To limit someone to one project, add them to it and tick **Limit to assigned
  projects** on their account. Otherwise they can also see everything in the
  shared area.
- To show someone a dashboard without giving them an account, send them a
  **share link**. Filters on a shared dashboard only work on data the dashboard
  already shows.

**Forgotten passwords** are reset by an administrator in **Administration →
Users**. There is no email reset. The user has to choose a new password the next
time they sign in, so the administrator never knows it. The **Forgot your
password?** link on the sign-in page explains this.

## Projects

A project holds the datasets and dashboards for one survey round and controls
who can see them. Anything not in a project is in the **shared area**, which
every user can see. You don't have to use projects; everything stays in the
shared area until you move it.

To create a project, go to **Projects → New project**. You are added as its
manager. To change its name or description later, use **Edit name and
description** in the **⋯** menu on the project page. If a project has no
description, managers see an **Add a description** link instead.

The project picker at the top of the page sets the project you are working in.
Other pages then only show that project's data. The **Projects** page always
lists all projects you have access to; the current one is marked **Working
here**, and **Work in this project** switches to another one.

A project's **Overview** is laid out in the order data moves through it:

- **Data comes in**: connections (with their last and next import) and datasets
- **Joined**: merged datasets and whether they are up to date
- **Prepared**: the project's script, whether imports run it, when it last ran
  and what it creates
- **Shown**: dashboards and when they were last updated
- **Watched**: indicators, open alerts and failing quality checks

Problems that need someone's attention, such as a failed import, a merge that
couldn't be rebuilt, or a script that failed or was never saved, are listed at
the top with links to fix them.

To add data to a project, choose the project when you upload, or open a dataset
or dashboard and use the project button in its header to move it. Moving
requires manager rights on both projects.

Connections also belong to a project. People with access to a project can see
its connections and imported files, but not those of other projects.

### Limiting someone to one project

1. Go to **Administration → Add user**. Choose their role and tick **Limit to
   assigned projects**. This hides the shared area from them.
2. Go to **Projects →** *the project* **→ Members → Add member**. Choose the
   person from the list and set their role in this project. (If people can
   create their own accounts on your server, there is no list; type their exact
   username instead.)

They will only see that project, in lists, through direct URLs and through the
API. Anything outside their access returns "not found", so they can't tell that
other projects exist.

A person's role in a project can't be higher than their overall role. Adding a
viewer to a project as a manager doesn't give them editing rights.

### Archiving a project

Once a survey round is finished, its data can take up a lot of disk space (a
census can be tens of gigabytes). **Archive** deletes the survey data and keeps
everything else.

| Deleted | Kept |
| --- | --- |
| The Parquet files that hold the rows | Each dataset's name, variables, labels and row count |
| Earlier versions kept for rollback | Dashboards, including their widgets, colours and pages |
| | Charts, indicators and their history |
| | Quality checks and results, alert rules and alerts |
| | Relationships and scripts |
| | Boundary layers, dashboard backgrounds and logos |

The dialog shows how much disk space will be freed before you confirm.

After archiving:

- The project is marked as archived with the date.
- Its datasets show "data archived" and all figures are empty.
- Open share links are closed (not deleted), so they can be reopened later.
- Importing into the project and running its scripts are blocked.

**Unarchive** makes the project usable again. The deleted rows don't come back,
so you need to import the data again. Because the datasets keep their names, a
new import goes into the same datasets and the dashboards start working again.
Share links closed by the archive are reopened; links you closed yourself stay
closed.

### Deleting a project

When you delete a project you choose what happens to its contents:

- **Delete, keep the data**: removes the project and moves its datasets and
  dashboards to the shared area, where they keep working.
- **Delete everything**: also deletes the datasets and their files, and
  everything built on them: charts, indicators and their history, quality
  checks, alert rules and alerts, relationships, merged datasets made from them,
  and the project's dashboards.

**Delete everything** can't be undone, so you have to type the project's name to
confirm. Connections are kept in both cases.

If you only want to free disk space, archive the project instead.

## Relating and merging datasets

A Survey Solutions export usually contains several tables. For example, a labour
force survey export might have one table for the interview, one for household
members and one for people living abroad. Each table becomes its own dataset when
you upload the archive.

Go to **Projects →** *a project* **→ Relationships** to define how the datasets
link together. There are three options:

- **Detect relationships**: SurveyHQ looks at the data and suggests links. It
  checks whether key values are unique on each side to decide between
  one-to-many and many-to-many, and shows how much the two sides overlap (for
  example, only 18% of interviews might have someone living abroad).
- **Add by hand**: choose the two datasets, the key on each side and the
  cardinality. Use this when detection misses a link, for example when the key
  has a different name in each dataset.
- **Clear relationships**: remove all links, or only the detected ones (links
  you added or edited are kept). Merged datasets keep their data but can't be
  rebuilt from a relationship that no longer exists.

Click a link to edit it. Once you edit a link, running detection again won't
change it back.

### Matching keys

**Match keys** controls how the two key columns are compared. The default is
**exactly, as stored**. With this setting, a merge is refused if one key is text
and the other is a number.

If the same ID is stored differently in the two datasets, for example `0041` in
one export and `41` in another, or as text in a CSV and as a number in a Stata
file, set **as text** or **as numbers**. Both keys are then converted before
comparing: `41` and `"41"` match, leading zeros and a trailing `.0` are
ignored, and values that aren't numbers simply don't match.

Conversion can't fix IDs that are actually different (`H0041` will never match
`41`). If a conversion results in no matching rows, the merge still runs (a left
join keeps every row of the left dataset with blanks for the right) and a
warning is added to the dataset. Links that use a conversion are marked in the
list.

### The relationship diagram

The diagram is laid out automatically, with the main interview table at the top
and rosters below it. In larger projects you can drag the boxes to tidy it up;
the links move with them. Your layout is saved in your browser. **Tidy up**
resets it.

### Merging two datasets

**Merge into a new dataset** joins two related datasets. You choose which
columns to include and whether to keep all rows from the left dataset or only
the ones that match.

Check the row count after merging. Joining 190 interviews to their 782 household
members gives 789 rows, because each interview is repeated once for each person.
SurveyHQ shows a message when this happens.

Two rosters linked through the interview are many-to-many, so joining them would
multiply rows. These links are recorded but can't be merged.

The merge settings are saved with the new dataset. To run the merge again, use
**Rebuild from sources** in the **⋯** menu on the dataset page. Merged datasets
are also rebuilt automatically whenever a source dataset is replaced by a new
export, has rows appended or is changed by a command. If one merged dataset is
built from another, they are rebuilt in the right order.

A merge keeps its own record of which datasets and keys it uses, so clearing and
re-detecting relationships doesn't break it. If the original relationship still
exists, its settings are used, so editing the relationship's key also changes
the merge.

If a merge can't be rebuilt (for example, because a source dataset was deleted),
its card shows **Not rebuilt from the latest data** with the reason. The dataset
keeps its existing data.

### Bringing variables into an existing dataset

Merging creates a new dataset, which means existing charts, indicators and
quality checks would need to be rebuilt on it. To avoid this, use **Bring in
variables from another dataset** in the **⋯** menu on a dataset's page. It adds
variables from another dataset to this one. The dataset keeps its ID and its
rows stay in the same order, so everything built on it keeps working.

Fill in:

- **From dataset**: the dataset the variables come from.
- **Matched on**: the variable that links rows in the two datasets, such as the
  interview key or a household ID. SurveyHQ fills this in where it can (from a
  relationship between the datasets, or a shared variable that identifies rows
  in the other dataset). Rosters are matched on two keys, the interview and the
  roster line; use **+ Another key** to add the second. **Compare the keys**
  works as described in [Matching keys](#matching-keys).
- **Variables to bring in**: tick the ones you want. Variables that already
  exist in this dataset are shown but can't be ticked; rename one of them first.

As you make your choices, a summary shows how well the keys match, for example
"Every one of the 349 rows of 'members' has a match in 'households'", or how
many rows will be blank. Nothing is saved until you click **Bring in**.

**The other dataset must have one row per key.** You can bring a household's
province into the members dataset, because each member belongs to one
household. You can't bring members' ages into the household dataset, because a
household has several members. SurveyHQ refuses this and shows an example of a
repeated key. Use a merge instead, or summarise the members in a project script
first.

**Brought-in variables are kept up to date.** Whenever either dataset gets new
data (a new export or appended rows), the variables are brought in again. They
are added as soon as the new data arrives and before the dataset's recorded
commands run, so commands can use them, for example `gen large = hh_size >= 6`.
A new export won't contain these variables, but this isn't reported as a lost
variable.

In the variable list, brought-in variables are marked with their source (for
example **from households**). The **Brought in from other datasets** box lists
each link and how many rows matched last time. **Bring in again now** refreshes
them immediately. **Stop** gives you two choices: **Remove them** (charts that
use them will show the variable as missing) or **Keep them as they are** (they
stay as a static copy and are no longer updated).

Note:

- If a command changes a brought-in variable directly, for example
  `replace province = "North" if ...`, the change is lost the next time the
  variable is brought in. Change the source dataset instead, or create a new
  variable.
- A brought-in variable can't be used as the key for another link.

## Getting data in

### Uploading a file

Go to **Datasets → Upload data**. Supported formats are Stata (`.dta`), SPSS
(`.sav`), CSV, tab-delimited (`.tab`, `.tsv`), Excel, and `.zip` archives
containing any of these.

**Each file in an archive becomes its own dataset.** A Survey Solutions export
has one file per level (the interview, household members, people living abroad
and so on), plus the paradata, and each becomes a separate dataset.

When you upload a later archive, each file goes into the dataset that already has
that file name. Under **When a dataset already holds that file**, choose:

- **Replace its data** (the default): swaps in the new data and keeps the
  dataset's identity, so relationships, merges, charts, indicators, quality rules
  and dashboard widgets keep working. Use this when the export contains
  everything collected so far.
- **Add its rows to what is there**: appends the new rows. Use this when the
  export only contains new interviews. A `source_file` column records which
  archive each row came from. If you append a cumulative export, interviews will
  be counted twice.

**GPS readings stored in one column are split automatically.** For example, ODK
stores `-12.3456 134.5678 42.0 5.0` in a single field, and CSV files often have
`-12.3456,134.5678`. For a column named `gps`, SurveyHQ adds numeric
`gps__latitude` and `gps__longitude` columns and leaves the original as it is.
The import notes list which columns were split. See [the GIS
manual](gis-manual.md#4-putting-a-map-on-a-dashboard) for details.

### A questionnaire that changed during fieldwork

If the questionnaire was revised during fieldwork, Survey Solutions exports each
version separately. To combine them, select **several archives at once** in the
upload dialog. They are imported in the order listed: the first one uses your
replace/append choice and the rest are appended to it. Interview files are
combined with interview files, each roster with the same roster, and paradata
with paradata.

- **Each file gets a label** in a variable you choose (`version` by default). For
  example, label the archives `11`, `10` and `9` and you can then tabulate, cross
  tabulate or filter by version. If the data already has a variable with that
  name, it is left alone and the import tells you.
- **Variables that only exist in some versions are kept.** A variable added in
  version 11 is blank for version 9 rows, and the import lists these variables.
- **Changed codes are reported.** If a later version uses the same code for a
  different answer, the rows are still appended but use the dataset's existing
  labels. The import lists the variables affected so you can check them.

Use ▲ next to a file to change the order. The first file is the base.

**With a Survey Solutions connection**, **Import data** groups the versions of
each questionnaire into one row (for example "3 versions · v1-v3"). Tick the row
to import all versions. For questionnaires with more than one version you can
choose:

- **Every version, including any published later** (the default): new versions
  are picked up automatically by later imports.
- **Only the versions ticked below**: import specific versions only.

The same choice is in **Edit → Questionnaires to import automatically**, which
scheduled imports use. A scheduled import with no questionnaires selected does
nothing, so the dialog warns you if the list is empty.

Versions are imported oldest first into one dataset, and each row gets a
`questionnaire_version` value. Only the first version uses your replace/append
choice; the others are always appended.

### What is kept when data is replaced

When a dataset's data is replaced, SurveyHQ keeps or restores:

- the dataset's ID, so links to it keep working
- variable and value labels you added yourself
- variables created by recorded commands (the commands run again in their
  original order)
- merged datasets built from it (they are rebuilt from the new data)

You will see a warning if:

- appended rows include interviews that were already in the dataset (this
  usually means the export was cumulative, not incremental)
- a file with the same name but different columns is uploaded (it is imported as
  a new dataset instead of overwriting yours)

Files too large to fit in memory are read in chunks automatically.

### Uploading several files

If you select several data files (not archives), each becomes its own dataset,
named after the file. This is useful for a census round, where the household
file, person file and paradata are separate tables. You can't select data files
and archives together. To name datasets yourself, upload the files one at a time.

### Large files

- Uploads over 48 MB are processed in the background. The browser shows
  *Importing…* and you don't need to keep it open.
- Uploads over 90 MB are sent in 50 MB pieces and reassembled on the server.
  This lets large files through proxies with a size limit (Cloudflare, for
  example, rejects requests over 100 MB). If a piece fails, only that piece is
  sent again.
- Uploads over the server limit (`MAX_UPLOAD_MB`) are rejected before they are
  sent, with a message showing the size and the limit. An administrator can
  raise the limit.

For a very large export, such as a full census round, ask your administrator to
import it directly on the server. See *Importing from the server* in the
deployment guide.

Stata and SPSS files are recommended because they include variable and value
labels, which are used throughout SurveyHQ. After the upload you are taken to the
new dataset, which shows its row count, variables and detected types.

### Importing from Survey Solutions

See [survey-solutions.md](survey-solutions.md).

### Importing from a folder

A connection can also read from a folder on the SurveyHQ server instead of a
Survey Solutions server. Go to **Connections → Add a connection** and set
**Where the data comes from** to *A folder on this server*. Any export placed in
that folder (downloaded by hand, synced from a cloud drive or copied by a
scheduled task) is imported on the connection's schedule and replaces the data
in place.

This is for situations where you can't get an API user on the survey server.
The folder must be inside a directory that the SurveyHQ administrator has
allowed. See
[survey-solutions.md](survey-solutions.md#when-there-is-no-api-user) for details.

### What happens after the data lands

Every import (upload, Survey Solutions, folder or reviewed import) is followed by
the same steps, in this order:

1. **Recorded commands run again** on each replaced dataset, to recreate derived
   variables.
2. **Merged datasets are rebuilt** if their sources changed.
3. **Project scripts run** if they read any of the changed data. Only saved
   scripts run; unsaved ones are listed in the report with a reminder to save
   them.
4. **Data quality checks run** on every changed dataset, including datasets
   written by scripts. Failing checks are listed in the report but don't stop
   the import.
5. **Indicators and dashboards are updated.** The report lists the dashboards
   that now show the new data. Alerts are checked at the next scheduled check.
6. **Published dashboards are republished** if they are set to update with the
   data.

The **activity** button in the top bar (the pulse icon next to the bell) shows
progress, for example *Survey Solutions is preparing the export: 40%*. The panel
lists each step and its result: records read, merges rebuilt (or why they
couldn't be), scripts run and dashboards updated. Finished imports stay in the
list for 30 minutes, and an amber dot means one of them needs checking. Upcoming
scheduled imports are listed below.

When an import finishes, open pages refresh automatically.

Everyone with access to the project can see its imports, including scheduled
ones.

### Refreshing a dataset

To refresh a dataset in place, import it again from its connection or use
**Replace data** for an uploaded file. Charts, dashboards, indicators and quality
checks keep working as long as variable names haven't changed.

### Organising datasets

The dataset list is grouped by project, and each group can be collapsed.

To delete several datasets, tick them and click **Delete selected**, or use
**Delete all** on a project's group. Anything that depends on them is deleted
too, so check the confirmation message.

To rename a dataset or add a description, use **Rename** in the **⋯** menu on its
page. Datasets from an archive are named after the file (for example
`R_demographics`), so you may want to give them clearer names. Charts, indicators
and merges are not affected by renaming. Downloads use the current name.

### Downloading a dataset

Use **Download: Stata**, **CSV** or **Excel** on a dataset's page to download the
whole table. Downloads include merged datasets and variables created by
commands.

Stata is recommended because it keeps variable labels and, for whole-number
codes, value labels. CSV keeps neither. Excel is limited to one million rows;
SurveyHQ tells you if a dataset is too large.

Only managers can download whole datasets, and downloads are recorded in the
audit log.

### Which variables can be measured

Any variable stored as a number can be used for a mean, sum or median.

SurveyHQ guesses whether a numeric variable is a set of codes or a quantity, and
uses that only to decide the order variables are listed in:

| The variable | Treated as | Why |
|---|---|---|
| Has value labels, e.g. 1 = Male, 2 = Female | Codes | The labels say what the numbers mean |
| Only two values and no labels, e.g. 0 and 1 | Codes | Usually a yes/no |
| Any other number | A quantity | |

Variables keep the type they were given when imported. To re-check an older
dataset, upload the export again.

### Password-protected archives

If an archive is password-protected, type the password in **Password, if the
archive has one** when you upload. The password is only used to open the file
and is not saved.

Archives protected with **AES** encryption can't be opened. Save the archive
again with standard zip protection (or none) and upload that.

### Duplicating a dashboard

**Duplicate** creates a copy of a dashboard with its own link, so you can change
the copy without affecting the original. This is useful for trying a new layout,
starting next quarter's dashboard, or making a regional version.

The copy includes the pages, groups, appearance, filters, drill-down and all
widgets in the same positions.

Not copied:

- The original's public link. The copy is private until you share it.
- The snapshot schedule.

Charts are shared, not copied. Moving, resizing or renaming a widget on the copy
only affects the copy, but editing the chart itself changes it on both
dashboards. To keep a frozen copy of a dashboard as it is today, use
**Snapshots** instead.

### Deleting and restoring a dataset

Deleting a dataset removes its data and frees disk space. What happens next
depends on whether anything uses it:

- **Nothing uses it**: the dataset is deleted.
- **Charts, indicators, quality rules, targets, alerts or merges use it**: the
  data is removed but the dataset is kept, empty and marked **Waiting for data**,
  so everything built on it stays linked.

**To restore it, upload the same export again.** SurveyHQ recognises the file and
fills the empty dataset, and the charts and widgets work again:

    Delete "persons"
      'persons' emptied. 3 charts and 2 dashboard widgets stay attached
      and are waiting for data: upload this export again and they will work.

    Upload persons.dta again
      persons: 4 rows replaced by 4

Deleting an empty dataset a second time removes it completely.

If you just want newer data, you don't need to delete anything: upload the
export again and it replaces the data in place.

## Looking at a dataset

A dataset's page has four tabs:

- **Variables**: every variable with its label, type, number of missing values,
  number of distinct values and range. Variables missing in more than 20% of
  records are highlighted. Click **Tabulate** on a row for a quick frequency
  table and chart.
- **Data**: browse the rows.
- **Statistics**: mean, standard deviation, minimum, quartiles, median and
  maximum for each numeric variable.
- **Field progress**: submissions over time, interviews per interviewer and
  supervisor, status breakdown, coverage by area and a GPS map. This tab appears
  when SurveyHQ recognises the relevant columns.

### Labelling variables and codes

Exports sometimes have no labels, for example a column `DEM_SEX` containing 1
and 2. On the **Variables** tab, click **Labels** on a row to add a label for the
variable and for each of its codes.

This doesn't change the data. The labels are used everywhere the variable
appears: axis labels, legends, cross-tab headings and filter lists. Values
without a label are shown as numbers, and whole numbers are shown without
decimals. Your labels are saved with the dataset, so they are kept when a new
export replaces the data.

The **What the codes mean** column shows the code labels for each variable, for
example "1 = Male, 2 = Female" (hover for the full list). Numeric categorical
variables that have no code labels are flagged in amber. Columns that only
contain 0 and 1 are not flagged.

### Preparing data with Stata commands

You can derive and recode variables using Stata-style commands.

Go to **Scripts** (under Data) and choose a script from the list, or click
**+ New** to create one. Write one command per line, as in a do-file:

    * everyone old enough to work
    gen adult = age >= 18
    replace adult = 0 if age == .
    label variable adult "Aged 18 or over"

Click **Run** or press **Ctrl+Enter** (**Cmd+Enter** on a Mac) to run the script.
Click **Save** or press **Ctrl+S** to save it without running.

Lines run from top to bottom and stop at the first error. Lines that already ran
stay applied, as in Stata. The **Output** panel shows the results. The line where
the script stopped is marked in red; click **Stopped at line…** under the editor
to jump to it. `*` and `//` start a comment, and `///` continues a line.

The editor uses colour to show commands, dataset names, functions, options,
numbers, text, macros and comments. If the first word on a line isn't a known
command, it is underlined in red.

As you type, the editor suggests:

- commands, at the start of a line
- the project's datasets (with row and variable counts), after `use` or `using`
- variables, where a variable is expected. The list follows the script: `use`
  loads a dataset's variables, `merge` and `append` add more, `gen` and `egen`
  add new ones, and `rename`, `drop`, `keep` and `collapse` change the list
- functions, inside expressions
- options, after the comma
- macros, after `` ` `` or `$`

Hover over a command, function, option, dataset or variable to see what it is.

The **Reference** panel lists all supported commands. Click an entry to insert it
at the cursor.

Managers can write, run and save scripts. Anyone with access to the project can
view them.

#### Several scripts in a project

A project can have several scripts, for example one to clean the roster, one to
build the household file and one to make tables. Each is run, saved and deleted
separately.

**+ New** asks which project the script belongs to and what to call it. If you
leave the name blank it is called **Main script**, then **Main script 2** and so
on. Names must be unique within a project (ignoring case).

Click the name above the editor to rename the script; press **Enter** to save or
**Escape** to cancel. Each script keeps its own unsaved changes, last run and
output.

A script can't overwrite a dataset created by another script, unless the line
says `save as <name>, replace`.

The project page lists its scripts under **Prepared**, with when each last ran
and what it reads.

#### Supported commands

| Command | What it does |
|---|---|
| `gen` | Creates a variable from an expression, with optional `if`. |
| `replace` | Changes an existing variable, with optional `if`. |
| `egen` | Aggregates with `by()`, or row-wise functions: `rowtotal`, `rowmean`, `rowmin`, `rowmax`, `rowmiss`, `rownonmiss`. |
| `label variable` | Sets a variable's label. |
| `label define` / `label values` | Defines a set of value labels and applies it to a variable. |
| `rename` | Renames a variable. Charts and other items that use it follow the new name. |
| `destring` | Converts text containing numbers to numbers, with `replace` or `generate()`. |
| `drop` / `keep` | Drops or keeps variables, or rows with `if`. |
| `recode` | Recodes values by rules, in place or into new variables. |
| `by` / `bysort` | Runs `gen`, `replace`, `egen`, `keep`, `drop` or `assert` within groups, with `_n` and `_N`. |
| `duplicates report` / `tag` / `drop` | Finds rows that repeat on some or all variables. |
| `reshape long` / `wide` | Converts columns such as `inc2019 inc2020` into rows of `inc` by year, and back. |
| `encode` / `decode` | Converts text to labelled codes, and labelled codes to text. |
| `tostring` | Converts numbers to text. |
| `sort` / `gsort` / `order` | Sorts rows or reorders columns. |
| `assert` | Stops the script if a condition is false for any row. |
| `count` / `summarize` / `tabulate` | Shows information without changing the data. |
| `foreach` / `forvalues` | Repeats a block of lines for each item. |
| `local` / `global` | Defines macros. |

`destring` follows Stata's rules: a variable is only converted if every value is
a number, blank or `.`. Otherwise it stays as text, the log shows some of the
values that prevented conversion, and the script continues. Options:

- `force` turns non-numeric values into missing
- `ignore(",$")` removes the listed characters first
- `percent` removes `%` and divides by 100
- `dpcomma` treats a comma as the decimal point

With no variables listed, `destring` checks every variable and skips ones that
are already numeric.

Comparisons return numbers, as in Stata: `gen adult = age >= 18` gives 1 or 0. So
`egen total = sum(adult)` and `collapse (sum) adult` count the matching rows.

#### Recoding

`recode` changes values according to rules in brackets. Each value uses the
first rule it matches:

    recode q5 (1 2 = 1 "Agree") (3 = 0 "Neutral") (4 5 = -1 "Disagree"), gen(view)
    recode age (min/14 = 1) (15/64 = 2) (65/max = 3), gen(age_band)
    recode income (-99 -98 = .)

On the left of a rule you can use numbers, ranges such as `15/64` (inclusive),
`min` and `max`, `.` or `missing`, `nonmissing`, and `else` (or `*`) for
everything else. Put `else`, `missing` and `nonmissing` last. Text in quotes
after the new value becomes its label.

Without `generate()` or `prefix()`, variables are changed in place, and the log
shows how many values changed. Values that don't match any rule are left as
they are. With `if`, rows that don't meet the condition keep their value (in
place) or are missing (in a new variable). `recode` only works on numbers; for
text, use `replace` or `encode` first.

#### Working within groups: by, bysort, _n and _N

A `by` prefix runs a command within each group:

    bysort hhid: gen members = _N
    bysort hhid (age): gen eldest = _n == _N
    bysort hhid (line): keep if _n == 1
    by hhid: gen previous = visit[_n-1]

- `_n` is the row number (within each group when using `by`), and `_N` is the
  number of rows.
- `x[_n-1]` is the previous row's value and `x[_n+1]` the next row's (missing at
  the edges of a group). `x[1]` is the first value in the group and `x[_N]` the
  last.
- `bysort` sorts by the group variables and then by any variables in brackets,
  and leaves the data sorted. `by` uses the current order (sorted within groups
  by the bracketed variables, if given). Ties keep their order.
- The prefix works with `gen`, `replace`, `egen`, `keep`, `drop` and `assert`.
- Without a prefix, `_n` and `_N` refer to the whole dataset: `gen id = _n`
  numbers the rows.

To fill gaps from the row above, use
`replace visit = visit[_n-1] if missing(visit)`. As in Stata, each blank takes
the value above it after that value has been filled, so a run of blanks under a
5 all become 5. Add `by hhid:` to fill within households only.

Other `replace` commands that read the same variable from an earlier row (for
example `replace x = x[_n-1] + 1`) are not supported and are refused, because the
result could differ from Stata's. Reading the next row (`x[_n+1]`) is allowed.

#### Duplicates, sorting and checks

- `duplicates report hhid` shows how many rows repeat a value of `hhid`.
- `duplicates tag hhid line, generate(dup)` creates `dup`, the number of other
  rows with the same values.
- `duplicates drop` keeps the first row of each set of duplicates. With no
  variables listed it compares whole rows. Dropping on some variables only
  requires `force`, as in Stata: `duplicates drop hhid, force`. Missing values
  count as equal.
- `sort hhid line` sorts rows. `gsort province -income` sorts with a minus sign
  for descending order. Missing numbers sort last.
- `order hhid line` moves variables to the front; use `, last`, `before(age)` or
  `after(age)` to put them elsewhere.
- `assert age >= 0 & age <= 120` stops the script if any row fails the
  condition, and reports how many rows failed and the first one. Use `if` to
  check only some rows, or `bysort hhid:` to count within households.

#### Viewing the data

`count`, `summarize` and `tabulate` don't change the data. Their results appear
in the **Output** panel in the same layout as Stata:

    count if age >= 18
    summarize age income
    summarize income, detail
    tabulate province
    tab province sex
    tab q1, missing

- `summarize` shows the count, mean, standard deviation, minimum and maximum for
  each numeric variable (all of them if none are listed). `detail` adds quartiles
  and the median.
- `tabulate` shows each value's count, percentage and cumulative percentage,
  using labels where available. With two variables it shows a cross-table with
  totals. Missing values are excluded unless you add `missing`.

All three accept `if`. When run from a dataset's command box they are not
recorded.

#### Text and codes

- `encode province, generate(province_code)` numbers each distinct text value
  alphabetically from 1 and labels the codes with the text. Use `label(places)`
  to use an existing label set.
- `decode q1, generate(q1_text)` converts labelled codes to their labels. Values
  without a label become missing, and the log reports how many.
- `tostring hhid, replace` converts numbers to text. Whole numbers have no
  decimal point and missing values stay missing.

#### Reshaping

    reshape long inc, i(hhid) j(year)
    reshape wide inc, i(hhid) j(year)

`reshape long` turns `inc2019 inc2020 inc2021` into an `inc` column and a `year`
column, with one row per household and year. Other variables are copied to every
row. `i()` must identify rows uniquely, and the suffixes must be numbers unless
you add `string`.

`reshape wide` reverses this, giving one row per `i()` value and one column per
`j()` value. Every other variable must have the same value on all of a
household's rows, otherwise the command is refused. Extended missing values such
as `.a` and `.b` are kept in both directions. As with `collapse`, the result is
a new dataset, so use `save as` to name it.

#### Loops

    foreach v of varlist q1-q5 {
        replace `v' = . if `v' == -99
    }
    forvalues i = 1/4 {
        gen visit`i' = visit == `i'
    }

The lines between `{` and `}` run once for each item, with the loop variable
available as a local macro (`` `v' ``).

- `foreach` loops over words (`foreach x in water power road {`), variables
  (`of varlist`, including ranges like `q1-q5` and wildcards like `inc*`), macro
  contents (`of local`, `of global`), new variable names (`of newlist`) or numbers
  (`of numlist 1/5 10(10)50`).
- `forvalues` counts: `1/10`, or `0(5)100` in steps of five.
- Loops can be nested. The `{` must end the first line and the `}` must be on a
  line of its own.

The loop's list is read when the loop starts, so a varlist can include variables
created earlier in the script. If a line in a loop fails, the script stops and
the message shows which item it was on, for example *Line 3 (replace `v' = ...):
... (where v is height)*. A loop runs at most 1,000 times. In a dataset's command
box, each line the loop ran is recorded separately.

#### The script list and run order

Scripts can depend on each other: one script might create a cleaned person file
that another script reads. If they run in the wrong order, the second script
uses old data without any error.

The list on the left of the **Scripts** page shows all scripts, grouped into the
order they need to run in. Each entry shows the project, the number of commands,
and when it last ran (or that it failed). Hover over a script to see what it
reads and writes. The dot next to it shows its status:

- filled: it ran
- amber: it ran but was never saved
- red: the last run failed
- hollow: it has never run

The order is based on what each script actually read and saved in its last run.
Scripts that have never run have no record, so they appear in step 1.

All scripts in step 1 can run in any order. A script moves to step 2 if it reads
something a step 1 script writes, and so on. Each step's heading says which
script it depends on. Scripts that read each other's output have no valid order
and are listed under **No order**.

Within a step, use **↑** and **↓** (shown when you hover over or open a script)
to set the order. Imports run scripts in this order when several use the same
data. You can't move a script to a different step, because it can't run before
the script whose output it reads.

**Delete** removes the script and its last run record. Datasets it created are
not deleted.

Unsaved changes are kept in your browser. If you leave the page, open another
script or reload, your changes are still there when you come back, with a note
saying when you made them and a **Discard them** button. Scripts with unsaved
changes have an amber • next to their name. Changes are only sent to the server
when you click **Save** or **Run**; imports always use the saved version.

#### Macros

Use macros to avoid repeating the same condition. In this example, the working
age condition and the employment condition are defined once and reused:

```
local wap       ilo_wap == 1
local working   main_activity == 1 | main_activity == 3 | inc_2nd_activity == 1
local helping   additional_work == 1 | help_family == 1
local employed  `working' | `helping'

gen ilo_lfs_emp = .
replace ilo_lfs_emp = 1 if (`employed') & `wap'
replace ilo_lfs_emp = 3 if !inlist(ilo_lfs_emp, 1, 2) & `wap'
```

Use a local as `` `name' `` and a global as `$name` or `${name}`. The macro is
replaced by its text before the command is read, so a macro can hold any part
of a command: a condition, a variable list or an operator. A macro defined using
other macros takes their values at the time it is defined.

Macros last for the whole run. You can define them before `use`, since defining
a macro doesn't touch the data.

Two differences from Stata:

- **Undefined macros cause an error.** In Stata, an undefined macro is replaced
  with nothing, so a typo like `` `poor' `` could turn `keep if `poor'` into
  `keep if` and keep every row. Here the script stops and lists the macros that
  are defined.
- **`local x = age > 15` stores the expression, not its value.** Stata would
  evaluate it for the first observation only. The run log says which was done.

#### Missing values

As in Stata, a missing number is treated as **larger than any number**:

| Expression | Result when the value is missing | |
|---|---|---|
| `age > 65` | true | missing is larger than 65 |
| `age >= 18` | true | |
| `age < 18` | false | |
| `sex != 1` | true | |
| `age == .` | true | tests for missing |
| `missing(age)` | true | the same test |
| `inlist(x, 1, 2)` | false | |
| `!inlist(x, 1, 2)` | **true** | |

So after `gen adult = age >= 18`, someone with no recorded age counts as an
adult. Exclude them explicitly:

    gen adult = age >= 18
    replace adult = 0 if age == .

This matches Stata so that results agree with the same do-file run in Stata.

Arithmetic with missing values still gives missing: `. + 1` is missing.

For text, a missing value is `""`, which sorts before all other text.

#### Classifying into categories

A sequence of `replace` commands works as it would in Stata, with a final rule
for everyone not yet classified:

    gen lfs = .
    replace lfs = 1 if (main_activity == 1 | main_activity == 3) & wap == 1
    replace lfs = 2 if inlist(reason_absent, 1, 2, 3, 4) & wap == 1
    replace lfs = 3 if !inlist(lfs, 1, 2) & wap == 1
    label define lfslbl 1 "Employed" 2 "Temporarily absent" 3 "Not employed"
    label values lfs lfslbl
    label variable lfs "Employment"

The order matters, because each `replace` can overwrite an earlier one. The last
line works because `!inlist` is true for values that are still missing. If the
data is re-imported regularly, put this in a project script so it runs again on
each new export.

#### Working with several datasets

A project script starts by loading a dataset, and nothing is saved until the
script says so. This means you can run a script again without changing anything
by accident.

    use people
    merge m:1 hhid using households, keep(match)
    gen adult = age >= 18
    collapse (sum) adult (count) age, by(province)
    save as "Adults by province"

| Command | What it does |
|---|---|
| `use` | Loads a copy of one of the project's datasets. Another `use` starts a new section. |
| `save as <name>` | Saves the data as a new dataset. The name must not already exist. |
| `save, replace` | Overwrites the dataset that was loaded. A plain `save` is refused. |
| `merge 1:1` / `m:1` / `1:m` | Joins another dataset on one or more keys. |
| `append using` | Adds another dataset's rows below. |
| `collapse` | One row per group, for example `collapse (mean) wage (sum) hours, by(province)`. With just a variable list it calculates the mean. |
| `contract` | Counts rows for each combination of values, in `_freq`. |

**merge** keeps all rows by default, as in Stata, and creates `_merge`: 1 for
rows only in the data in memory, 2 for rows only in the other dataset, and 3 for
matches. Use `keep(match)` to keep only matches, `keepusing(...)` to choose which
variables to bring across, and `nogen` to skip creating `_merge`.

The merge type is enforced: a `1:1` merge with a repeated key is refused instead
of multiplying rows. If both datasets have a variable with the same name, the
value from the data in memory is kept. Missing keys never match each other; those
rows get `_merge == 1`.

**append** matches columns by name, not position, so it works even if a question
was added between rounds. Variables that only exist in one dataset are missing in
the other's rows. Text and numeric variables with the same name can't be
appended, and the error names the variable.

**collapse** and **contract** replace the data in memory, as in Stata. Use
`save as` to save the result as a new dataset.

#### Saving and re-running scripts

- **Save** saves the script without running it.
- **Run script** runs it, and if every line succeeds, saves it as well. This is
  the version that runs on the next import. If the run stops on an error, nothing
  is saved, so a broken draft never replaces a working script.

The previous saved version is kept: **Put the previous one in the box** restores
it, and you can save it again.

Scripts run again automatically. When a new export replaces a dataset that a
script reads, the script runs from the top and rebuilds what it created. The
**Last run** panel shows which datasets the script read and wrote last time.

- Imports never run a script that has never been run manually. Run it once to
  include it.
- `save as` can overwrite a dataset the same script created last time, but not
  one it didn't create, unless the line says `save as <name>, replace`.

If an automatic re-run fails, the import still succeeds. The failure is reported
with the import and on the script, with the line where it stopped.

Scripts run after merged datasets are rebuilt, so scripts that read merged
datasets get the latest data.

Expressions support arithmetic, comparisons, `&`, `|`, `!`, `.` for missing, and
functions including `int`, `round`, `abs`, `min`, `max`, `substr`, `upper`,
`lower`, `strlen` and `real`.

#### Security

Commands are never sent to the database as text. Each command is parsed into
tokens, every name must be a variable in the dataset, only supported functions
are allowed, and the query is built from the parsed tokens. So
`gen x = 1); DROP TABLE users --` just produces an error message about the part
that couldn't be understood.

#### Commands are kept for the next export

Variables you create aren't in the export file, so they would be lost when a new
export replaces the dataset. To prevent this, commands run from a dataset's
command box are saved with the dataset and run again, in order, after each
replacement. They run before the import checks for missing variables, so
recreated variables aren't reported as lost. If a command can't be re-applied
(for example because it uses a variable the new export doesn't have), a note is
added to the import; the import itself still succeeds.

The **Kept for the next import** panel lists the commands that will run.
**Clear** stops them from running again but doesn't undo their effects.

Commands keep the original row order, including `egen` with `by()`.

## Analyse

The **Analyse** page starts with the **Dataset** you are analysing, the project
it belongs to, its number of rows and variables, and a link to open it. Choose
the dataset first, because all the variables below come from it.

### Tabulate & chart

1. **Group by** one or two variables. For dates, choose day, week, month,
   quarter or year. Numeric variables can be grouped into bins of a set width.
   The first grouping can keep only the top N categories and put the rest in
   "Other". You can group by any variable, including `interview__key`; variables
   with a different value on every row show their number of values next to the
   name, and the row limit controls how many rows are returned.
2. **Measure**: count, share of total, sum, mean, median, minimum, maximum,
   standard deviation, percentiles or distinct count. Add several measures to
   compare them. Any measure can be weighted by a numeric variable, such as your
   survey weight.
3. **Filters**: add conditions and combine them with all/any. Variables with
   value labels show a list of their labels. You can also switch to
   **Expression** and type the filter (see below).
4. **Display**: choose the chart type. Order, axes, target line and row limit are
   in a section below that opens when you click it. Then click **Run query**,
   which stays visible at the bottom of the screen.

You can view the result as a chart or a table, export it to CSV or Excel, or
save it as a chart for dashboards. **Show SQL** shows the query that was run.

**Suggested analyses** lists charts based on the dataset's variables that you
can run with one click.

#### Typing a filter as an expression

Every filter (in Analyse, on indicators and in quality checks) has a **Builder |
Expression** switch. With **Expression** you can type the filter the way you
would write a condition in Survey Solutions (C# syntax):

```
age.InRange(15, 49) && sex == "Female" && (district == "North" || district == "East")
```

Use `&&` for and, `||` for or (`&&` is evaluated first) and `!` for not, with
brackets to group conditions. You can also write `and`, `or` and `not`.

| Write | Meaning |
|---|---|
| `==` `!=` `>` `>=` `<` `<=` | comparisons (`=` is treated as `==`) |
| `district == "North"` or `district == 1` | a coded variable, by its label in quotes or by its code |
| `x.InList(1, 2, "East")` | is one of |
| `x.InRange(15, 49)` | between, inclusive |
| `x.Contains("ab")`, `x.StartsWith("A")`, `x.EndsWith("z")` | text matching |
| `IsAnswered(x)`, `!IsAnswered(x)`, `x == null` | answered or missing |
| `IsSelected(water__3)` | an option ticked in a "select all that apply" question |
| `end_date < start_date` | compare two variables |
| `inc2020 - inc2019 > 100`, `total != boys + girls` | arithmetic (`+ - * /` and brackets) on either side |
| `` `my column` == 1 `` | names with spaces or special characters, in backticks |

The box suggests variable names (press Tab or Enter to accept), methods after a
dot, and value labels inside quotes. **How to write one** under the box shows the
table above.

Both modes edit the same filter. A typed filter is applied as soon as it is
valid, and **Builder** shows it as rows. A filter built in rows is shown as an
expression, with codes written as labels. Errors are underlined with an
explanation, for example: There is no variable "agee" - did you mean age? Until
you fix it, the last valid filter stays in use. SurveyHQ remembers which mode
you prefer.

**Arithmetic** can be used on either side of a comparison, for example the
change between rounds (`inc2020 - inc2019 > 100`), a growth rate
(`(inc2020 - inc2019) / inc2019 * 100 >= 10`) or a total that should equal its
parts (`total != boys + girls`, which works well as a **Logic condition** quality
check). `*` and `/` are calculated before `+` and `-`. Calculations can be
compared with a number, a variable or another calculation, but not with text or
`null`. Rows where any value in the calculation is missing are excluded, and
division by zero gives no value. **Builder** shows calculations as written; edit
them in **Expression** mode.

This is C# syntax with the Survey Solutions helper functions, not full C#.
LINQ queries over rosters and other methods are not supported.

#### Display options

| Option | What it does |
|---|---|
| Chart type | Bar, horizontal bar, stacked bar, horizontal stacked bar, population pyramid, line, area, donut, pie, scatter, box plot, heatmap or table |
| Order | Keep the query order, or sort by value or label, ascending or descending. Not available for date or numeric axes, which follow their own scale |
| Show only the top | Keep the N largest categories and combine the rest into "Other". On a date or numeric axis, this ranks the values instead (for example, the ten busiest days) |
| Value axis title | Title for the value axis |
| Axis from … to | Fixed minimum and maximum, so charts can be compared |
| Target line | A labelled horizontal line, for example at a target value |
| Print the numbers on the chart | Shows values on up to 24 marks; with more, the labels are hidden to avoid overlap |
| Stack to 100% | Shows composition instead of totals on stacked bar and area charts |
| Smooth the line | Curves a line or area chart |
| Row limit | Maximum number of rows the query returns |

Only options that apply to the selected chart type are shown.

A **population pyramid** needs age groups as the first grouping and sex as the
second. Age groups are sorted by their starting number, so "5-9" comes between
"0-4" and "10-14".

A **box plot** shows how values are spread within each group. When you choose
it, the **Measure** card changes to **Summarise**: choose one numeric variable
and each group gets a box showing the minimum, lower quartile, median, upper
quartile and maximum. The whiskers go to the minimum and maximum values (not 1.5
times the box), so no points are shown as outliers. Note that R and Stata use
the 1.5 rule by default. Boxes are sorted by their median, and "Show only the
top" keeps the largest boxes without an "Other" box.

Charts with more than one series have a legend, and every chart can be switched
to a table showing the same numbers.

### Cross-tabulation

Choose a row variable and a column variable, what the cells show (count by
default, or a summary of a numeric variable), and the percentages: none, row,
column or total. Row and column totals are always shown. Chi-square and Cramér's
V are shown below the table.

**Survey weight.** When the cells show a count, sum or mean, you can choose a
**Survey weight**. Unweighted counts are numbers of interviews; weighted counts
estimate the population. Weighted counts are labelled "Estimated total" instead
of "Count". A count of a variable only includes rows that answered it.

Chi-square isn't shown for weighted tables, because the standard test assumes
the counts are observations. Use statistical software that accounts for the
survey design if you need a test.

Weights aren't available for medians and percentiles. Switching to one of these
removes the weight.

**Suppressed cells.** If your administrator has set a minimum cell size, cells
based on fewer records show `*` instead of a number, with a note below the
table. Empty cells show `-`. Totals can also be suppressed (for example, a row
total made up of one suppressed cell), and sometimes a second cell is suppressed
so the first can't be worked out by subtraction. See the deployment guide for
how to set the minimum.

Tables can have up to 5,000 rows and 1,000 columns, so you can tabulate by
interview key or enumeration area. Headers stay visible as you scroll, and
exports include the whole table. If a variable has more categories than this,
the table says how many were left out.

**Save for dashboards** saves the table definition, not a picture. On a
dashboard it uses current data and responds to dashboard filters.

**One variable.** Leave Rows or Columns empty to get a frequency table for one
variable. The empty side becomes a single column named after the measure (for
example "Count" or "mean of age"). Percentages are of the total, and there is no
chi-square.

**Several variables as columns.** With Columns empty and the cells set to a sum,
mean or other value, use **+ Another variable** under *Of variables* to add more
variables. Each becomes a column, with the row variable down the side. For
example, rejections by supervisor and by headquarters for each interviewer:

| Responsible | sum of rejections__sup | sum of rejections__hq | Total |
|---|---|---|---|
| T1_interv1 | 21 | 12 | 33 |
| T1_interv2 | 19 | 20 | 39 |

All columns use the same calculation and filters. Sums and counts are added
across each row in a **Total** column, and percentages work as usual. Means,
medians and similar values aren't added up: there is no row total, the bottom
row shows the value over all rows (for example the overall mean), and
percentages aren't available. There is no chi-square.

While there is more than one variable, Columns is disabled. Remove the extra
variables to use a column variable instead. These tables can be saved for
dashboards and exported to CSV, Word and the offline web page.

**Rename columns** (next to Export CSV) lets you change the column headings, for
example "sum of rejections__sup" to "Rejected by supervisor", or "Male" to "Men",
and the row heading ("responsible" to "Interviewer"). Leave a name blank to keep
the original. Only the headings change. On dashboards, clicking a renamed heading
still filters by the original category. The names are saved with the table and
used on dashboards and in CSV, Word and web page exports.

**Listing categories only.** With Columns empty, choose **None (just list the
categories)** under Cell values to get a list of the row variable's categories
with no numbers, for example to see which provinces have reported or which codes
a variable uses. Dashboard filters still apply, so categories with no rows are
dropped. Percentages aren't available with this option, and it isn't offered
once a column variable is chosen.

### Select all that apply

Survey Solutions exports a "select all that apply" question as one column per
option (for example `toilet__1`, `toilet__2`, `toilet__3`), with 1 where the
option was chosen and 0 where it wasn't.

The **Tick all that apply** tab combines these columns. It finds the questions
from the column names, so you can choose, for example, **Main source of drinking
water** once instead of selecting twelve columns. Each option becomes one bar.

The percentages add up to more than 100, because a respondent who chose three
options is counted three times. **Percent of** sets the denominator: the people
who were asked the question (usual), or every row in the dataset.

**Show** chooses whether the chart shows counts or percentages. Tables can show
both.

Untick options to hide them from the chart (for example "Other" and "Don't
know"). The percentages are still calculated from all respondents.

If your columns don't follow the `name__1` pattern, use **Choose the columns
myself** and tick the columns that belong to the question. Columns containing 1
and 0, or Yes and No, both work.

#### Other views

**What to show** offers several views of the same question:

- **How many chose each option**: the bar chart above. Choose **Bars**,
  **Lollipops** (a dot on a thin line, easier to read with many options) or
  **Bars on a 100% track** (each bar on a pale background running to 100%). Pie
  and donut charts are also available, with a warning that the options aren't
  parts of a whole; each slice is that option's share of all ticks.
- **Each option, by a group**: each option's share within groups of another
  variable such as district, sex or urban/rural (choose it under **Break down
  by**). Shares are calculated within each group. Shown as a heatmap, grouped
  bars or a table, for up to 40 groups.
- **The combinations chosen**: the sets of options respondents chose together,
  for example *Piped + Rain*, *Well only* or *None of these*. These add up to
  100%. **Name the most common** sets how many combinations are listed; the rest
  are grouped as *Other combinations*.
- **How many options each chose**: respondents by the number of options they
  chose, with the average in the title.
- **Which options go together**: a heatmap where each row shows, for people who
  chose that option, the share who also chose each other option. Read it across
  the rows; the table isn't symmetrical. Up to 30 options.

Long option names wrap onto two lines, and heatmaps show the values in the
cells. All views can be saved as charts and added to dashboards, and dashboard
filters apply to them.

#### Option names

Bars are labelled with the option text where the file has it. SurveyHQ looks in
two places when importing:

- **The option column's label.** For example, if `hhld_goods__8` is labelled
  "Household goods: Bicycle", the bar is labelled "Bicycle" (the question text is
  removed because it is already the chart title). If all option columns have the
  same label, that label is the question, so it isn't used.
- **The question's value labels.** Often the option columns have no labels but
  the question's value labels say that code 8 is "Bicycle". SurveyHQ copies these
  labels onto the matching columns when importing.

If neither is available, options are shown as **Option 1**, **Option 2** and so
on. Click **Name them** to enter names for all options in one dialog. The names
are saved as column labels on the dataset, so they appear everywhere and are kept
when a new export replaces the data.

The **Options to show** list uses the same names.

Clicking a bar on a dashboard doesn't filter the dashboard, because each bar is a
separate column rather than a value of one variable.

## Charts and dashboards

Any result in Analyse can be saved as a chart. Saved charts are listed under
**Dashboards → Saved charts** and always show current data.

Each dashboard in the list has a thumbnail showing the layout of its first page
and the type of each widget (chart, list, number, map or note), drawn in the
dashboard's colours. Below the name are its project, the number of widgets and
pages, and when it was last changed.

The **project** picker at the top filters both tabs. A dashboard belongs to a
project directly; a chart belongs to the project of its dataset. Choose **All
projects** to see everything.

**Edit** on a saved chart opens it in Analyse with all its settings filled in
(grouping, measure, filters, chart type and display options) and runs it. Make
your changes and click **Save changes** to update the chart on every dashboard
that uses it, or **Stop editing** to leave it unchanged. Saved cross-tabulations
are edited the same way, on the Cross-tabulation tab.

When you open a dashboard it is in reading mode. The toolbar has **Edit**,
**Share** (shown as **Shared** if the dashboard has an open link) and **⋯** with
**Snapshots** and **Duplicate**. Click **Edit** to add widgets and groups, set
filters, drill-down, appearance, chart colours and the project, and manage pages.
Click **Done** when you have finished. The open link's address and the setting
for the dashboard's own web address are also shown in edit mode; in reading mode
they are in the Share dialog.

**On a phone**, dashboards are shown in a single column, with each widget at full
width in reading order and groups kept together. This doesn't change the layout
on larger screens. Editing isn't available on a phone.

To build a dashboard:

1. Go to **Dashboards → New dashboard**, choose a project (or leave it in the
   shared area) and click **Edit**.
2. Click **Add widget** (see the list of widgets below). A dashboard in a project
   offers that project's charts, indicators and datasets; a dashboard in the
   shared area offers everything you have access to.
3. Drag widgets by their title bar and resize them from the corner. The layout
   is saved automatically.
4. Hover over a widget and click ✎ to change what it shows, its title, size,
   background colour and page. ✕ removes it. A widget's own background colour
   still uses the dashboard's transparency setting.
5. Click **+ Page** to add a page. Double-click a tab to rename it, and use ◀ ▶
   to move it. Each page has its own layout and filters.
6. Click **Add group** to put a box around related widgets (see below).
7. Set up **Filters** (see below).
8. Use **Appearance** for ready-made looks, the title band, page background,
   canvas and transparency (see below).
9. Use **Colours** in the header to choose the chart colour palette. All
   palettes use the same colours in different orders, arranged so neighbouring
   series stay distinguishable for colour-blind readers.
10. Use **Share** to create links (with or without a password), download the
    dashboard or publish it to a website (see Share links below). Opening the
    dialog doesn't share anything until you create a link.
11. If your administrator has set up a dashboard domain, a shared dashboard can
    have its own address, such as `labour-force.dash.example.org` (see below).

### Grouping widgets

Groups put a named box around related widgets so they can be moved and collapsed
together.

In edit mode, click **Add group** and give it a name. The box appears at the
bottom of the page. Spacing between groups and widgets is the same as between
widgets.

| To | Do this |
|---|---|
| Add a widget to a group | In edit mode, drag the widget into the group's box. Or open the widget's **⋯** menu and choose **Put in "…"**. |
| Remove a widget from a group | Drag it out of the box, or choose **Take out of its group** in the widget's **⋯** menu. |
| Move the group | Drag its title bar. The widgets inside move with it. |
| Resize the group | Drag the corner of the title bar. |
| Rename it | Click **✎** on the title bar. |
| Change its colours or heading size | Click **◐** on the title bar. **Background** sets the colour behind the widgets and title bar (on a dark background the heading turns light). **Heading and frame colour** sets the name and border colour. **Heading size** ranges from 10 to 32 pixels; **Default** is 12. These settings also apply to shared links, downloads and published copies. |
| Collapse it | Click the arrow at the left of the title bar. |
| Remove the group | Click **✕** on the title bar. The widgets stay on the page. |

When a group is collapsed, its widgets are hidden and the space below closes up.
The title bar shows how many widgets it contains. Expanding it puts them back in
the same place.

Groups are shown on shared links, public dashboards and the downloaded HTML file.
Viewers can collapse and expand groups for themselves; this doesn't affect anyone
else. Groups start collapsed or expanded as the dashboard was saved.

A group belongs to one page. Putting a widget in a group on another page moves
the widget to that page, and moving a widget to another page removes it from its
group.

### Widgets

| Widget | Shows |
|---|---|
| **Saved chart or cross-tab** | A chart or table saved from Analyse, using current data |
| **Indicator tile** | An indicator's value, distance from target, recent trend, progress bar and status, with an optional breakdown chart |
| **Data quality panel** | The latest result of each check on a dataset, and the age of the oldest result |
| **Text note** | A heading, explanation or note |
| **Countdown to a date** | Time left until a deadline, with your own label and a message for when it passes |
| **Map of interview locations** | GPS points from a dataset, grouped when there are too many to show individually. Click a point for its count or another summary, plus any detail columns you chose |
| **Embedded HTML** | HTML you paste in, shown in a sandboxed frame (for example a logo, video or links) |
| **How recent the data is** | When each dataset was last imported and how old its newest record is |

An **indicator tile** shows:

- the value
- how far it is from target, in the indicator's units and as a percentage (for
  example "283 behind target" or "+12% ahead"). For "lower is better" indicators,
  exceeding the target reads as "over the limit"
- a small trend line of recent values

The variance only appears if the indicator has a target, and the trend only if it
has more than one stored value.

The **freshness** widget shows two things: when data was last imported (is the
import running?) and how recent the newest record is (are field teams still
sending data?). By default it turns amber after 24 hours and red after 72; you can
change both thresholds.

It uses a date variable that records when the interview took place, such as an
interview date or submission timestamp, and ignores dates that are answers (such
as date of birth). If it picks the wrong variable, or none, choose one in the
widget settings.

### Boundaries

> For full details, see [the GIS manual](gis-manual.md), which covers preparing
> files, the area check, limits and troubleshooting.

Go to **Datasets → Boundaries → Add boundaries** to upload the areas fieldwork is
organised by (enumeration areas, districts, villages). Supported formats are
GeoJSON, GeoPackage (`.gpkg`) and zipped shapefiles (with `.dbf` and `.shx`).

Layers in the shared area are available to all projects; layers in a project are
only available in that project.

Reading boundary files doesn't need GIS software or an internet connection on the
server.

Boundary layers are used for drawing areas under a map and for checking where
records were collected.

### Maps with many points

Each point on a map is a location, not an interview. Several interviews at the
same place are shown as one point with a count.

When there are many locations, as in a census, nearby locations are grouped into
cells so the map loads quickly. The line under the map then says, for example,
"100,000 located interviews, drawn as 1,509 pins about 1.1 km across". With up to
a few thousand locations, every point is drawn exactly where it was recorded.
Values on a grouped point are always calculated from the underlying interviews
(for example, a mean is the mean of those interviews, not an average of
averages).

On maps that check recorded areas (see below), each location is checked before
grouping, so the legend counts locations, not points. A grouped point takes the
most serious result among its locations, and its popup says how many of them
don't match.

### Drawing boundaries under a map

In a map widget's settings, **Boundaries** draws a boundary layer's areas as
outlines under the points. **Write on each area** chooses which attribute is used
as the area's name (shown when you hover). Set **Show the names** to **Always** to
show the names permanently.

When a boundary layer is chosen, the map zooms to the layer instead of the points,
so a single wrong coordinate doesn't zoom the map out too far.

The layers box in the map's top-right corner has a tick box for the boundary
layer, so viewers can hide and show the outlines.

**Point shape** draws points as circles, squares, triangles, diamonds or
pentagons. Use circles when point size shows a quantity, and different shapes
when you want categories to be easy to tell apart, including in black and white.

**Fill the window** in the widget's menu shows the map full screen (this works
for all widgets).

### Checking where a record was collected

A household listing records the enumeration area (EA) the interviewer entered,
and the device records the GPS location. If they disagree, the EA code may be
wrong, the interviewer may be in the wrong area, or the boundary may be
interpreted differently in the field.

In the map widget, set **Recorded area** to the variable with the recorded EA
code, and **Matched against** to the boundary layer attribute with the same code.
Points are then coloured by result, and the box in the top-right corner lists each
result with a count and a tick box:

| Colour | Meaning |
|---|---|
| **Red** | The recorded area doesn't match the area the GPS point is in |
| **Amber** | The point is outside every area in the layer |
| **Purple** | No area was recorded |
| **Green** | The recorded area matches the GPS location |

Click a point to see the recorded area, the area it is actually in, and the
widget's detail columns (useful for identifying the interviewer).

Points outside every area are not counted as mismatches. They usually mean the
boundary file doesn't cover that place, or the coordinates are wrong.

Codes are compared by value, so `07`, `7` and `007` are treated as the same EA.

### Data quality map

The **Data quality layers** section of a map widget adds separate layers for GPS
checks. The box in the top-right corner lists each layer with its colour and
count and a tick box to show or hide it. Hidden layers stay hidden when you zoom
or the dashboard refreshes.

| Layer | What it shows |
|---|---|
| **Area agrees / does not match the GPS**, **Outside every area**, **No area recorded** | The recorded area check above, one layer per result |
| **Duplicated GPS (within 100 m)** | A black ring around each reading that has another record within the distance you set. The popup shows how many |
| **Manual location agrees / is in another area / …** | The **second location** (entered by hand) checked against the areas, in blue and yellow |
| **GPS and manual over 100 m apart** | A dashed line from each GPS reading to the record's second location where they are further apart than the distance you set. Click it to see the distance |
| **Areas with interviews (12 of 30)** | Areas with at least one GPS reading, shaded |

- **Flag duplicated GPS** takes a distance in metres. Where houses are close
  together, a large distance flags most of them, so start with 10 to 20 m (which
  catches a reading taken twice from the same doorway) and increase it if needed.
  Use the household dataset; on a roster, all members share their household's
  location and would all be flagged.
- **Second location** takes the latitude and longitude variables of the location
  entered by hand, and a name for it ("Manual" by default). Records with no GPS
  reading but a manual location still appear on the manual layers.
- **Draw a line where the two are more than … metres apart** sets the distance
  for the lines.
- **Shade the areas with interviews** requires a boundary layer.

On a map with these layers, every location is drawn exactly as recorded (not
grouped).

### Map backgrounds

A map can use one of three backgrounds, chosen when you add it and changeable
later with **✎**:

- **Streets**: OpenStreetMap (the default)
- **Satellite**: aerial imagery with place names and boundaries
- **Terrain**: contours and relief

Viewers can switch backgrounds with the control in the top-right corner. Their
choice only lasts while the page is open.

All three backgrounds are loaded from the internet. If the server can't reach
them, points are drawn on a plain background and a note appears under the map.
If your organisation has its own tile server, an administrator can set it under
**Map tiles**; this replaces the three options.

### Point settings

In the map widget's settings (**✎**):

- **Point shape**: circle or a shape with corners.
- **Point colour**: any colour (blue by default).
- **Point size**: base size from 6 to 40.
- **Point transparency**: 60% by default, so overlapping points show density.
- **Bigger pins where the number is bigger**: on by default, so points with more
  interviews are larger. Turn it off to draw all points the same size.

On maps that check records against boundaries, points use the colour and size of
their result instead.

### Reusing embedded HTML

To use the same HTML on several dashboards, click **Save to library** on an
Embedded HTML widget and give it a name. On another HTML widget, click **Load
from library** to use it. Snippets saved in the shared area are available in all
projects; snippets saved in a project are only available there.

Loading a snippet copies it into the widget. Editing or deleting the snippet in
the library doesn't change widgets that already use it.

### Share links

**Share** lists every link to the dashboard and lets you add more. The same
dialog is used to download the dashboard and publish it to a website (see
below).

Opening the dialog doesn't share anything. An unshared dashboard shows **Not
shared** until you create a link:

- **Create an open link** makes a link without a password that anyone can open
  without signing in. You can turn it off from the same row; it then stops
  working for everyone, and turning it on again creates a new address.
- **Add a link** makes a named link that can have a password and an end date.

Turning the open link on or off doesn't affect named links.

Create a separate link for each audience (for example field supervisors and a
partner organisation), so you can close one without affecting the others. Each
link shows how many times it has been opened.

**Close** a link instead of deleting it if you might need it again: a closed link
stops working but can be reopened at the same address. Deleting is permanent.

**Stops working after** sets an end date. The link works until the end of that
day (in your time zone). Expired links are marked **Expired** and stay in the
list; set a later date to reopen the same address, or choose **No end date**.
Readers see the same message for expired and closed links: the dashboard is not
available.

A link can have a **password**. Readers enter it once and it is remembered for
that browser tab only, so people on a shared computer aren't left signed in.
Everyone with the password is treated as the same anonymous reader; it isn't an
account.

### Downloading a dashboard

A link only works while SurveyHQ is running and reachable. To take a copy of
the dashboard instead, use **Share → Download this board** and choose a format.

**Web page** creates a single HTML file that you can put on any web server,
attach to a report or send to someone to open on their computer.

**Filters still work in the file.** The file contains the numbers behind each
widget, broken down by the variables used in the page's filters, so choosing a
filter value recalculates the figures. Averages are stored as totals and counts,
so they are recalculated correctly rather than averaged again. Page tabs work,
and each page has its own filters.

These filters are included:

- **Dropdowns**, including numeric and coded variables shown by their labels.
- **Date ranges**, with the same options as the dashboard: all dates, Today,
  Yesterday, the last 7 or 30 days, this week, this month, last month, or
  **Choose dates…**. Relative ranges are calculated from the day the file is
  opened, so use fixed dates if you need a specific period. Date filtering makes
  the file larger for long fieldwork periods.
- **Select all that apply charts**, in all their views, recalculated for the
  filtered respondents.

**The file looks like the dashboard**: background, header, logos, title style,
tabs, filter bar and transparency are all included, along with any built-in font
the dashboard uses. The layout matches the shared link.

**Word** creates a report with the dashboard title and filters, then each page
and widget, with each widget as a heading and a table of its numbers. Charts are
shown as tables of figures, and text widgets as text.

Cross-tabulations appear as tables with the same rows, columns, percentages and
totals as on the dashboard. Suppressed cells stay suppressed (marked `*`), with a
note under the table. Widgets that can't be recalculated (for example a chart
based on a median, or one whose dataset has been deleted) show a message with the
reason.

For **PDF**, open the web page and print it. The print layout has margins, hides
the tabs, keeps each widget on one page, opens collapsed groups and prints the
filter values.

Limitations of the web page:

- **Clicking a chart doesn't filter the page.** Use the filter controls.
- **Maps need an internet connection** for their background. Charts work offline.
- **Some widgets are static** and say so, with the reason: data quality and
  freshness panels, charts based on a median, distinct count, percentile or
  standard deviation, and widgets that would make the file too large. They show
  their values as they were when the file was created.
- **Boundary outlines and data quality layers are not included** in maps, only
  the interview locations.
- **Background images over 3 MB are left out**, and the background colour is used
  instead.

The bottom of the file shows when it was created. The figures don't update;
download it again to get newer numbers.

#### Reports for one area

Use **Of** in the download panel to create a report for a saved view. Leave it on
"everything" for the full dashboard with its filters. Choose a view (for example
"Northern") to get a file for that view only, titled with the view's name.

The file only contains data for that view. Other areas' figures aren't calculated
or included, and the filter isn't shown. Use this when the recipient should only
see their own area.

**One report for each** creates a separate file for every value of a filter (for
example one per province) and downloads them as a zip. Each file is limited to
its own value.

This runs in the background and can take several minutes, because each file is a
full calculation. A progress indicator shows how far it has got. If a file can't
be created, it is skipped and listed, and the rest are still produced. Filters
with more than 60 values are refused.

The server keeps the zip files from the last five runs for each dashboard. Older
runs are still listed in the job history, but their files are gone. Download the
zip when it finishes and keep it with your files.

Files are named after the view.

### Publishing to a website

If SurveyHQ runs on an office network or a laptop that isn't always on, you can
**publish** a dashboard to GitHub Pages or your own web server so it stays
available.

The published page is the same as the **Web page** download: one file with
working filters, containing only the numbers shown on the dashboard, never raw
data. Minimum cell sizes apply in the same way.

Go to **Share → Publish to a website**:

- **To**: a GitHub Pages site or web server set up by an administrator (see
  below).
- **At the address**: the folder on the site, for example `fieldwork-week` for
  `https://.../fieldwork-week/`. The full address is shown before you publish.
  Use letters, numbers, dashes, dots and underscores, with `/` between folders.
- **Of**: publish one saved view instead of the whole dashboard.
- **Publish again after each import**: update the published copy automatically
  whenever an import changes the dashboard's data. The import report lists what
  was republished. If the destination can't be reached, this is noted in the
  report but the import still succeeds.

Published copies are listed with their address and when they were last
published, with buttons to **Publish again**, **Copy link** and **Unpublish**
(which deletes the page from the server). A dashboard can be published to several
sites, or to the same site at different addresses.

SurveyHQ never overwrites or deletes pages it didn't create. If the address
already has another page, publishing stops and asks before replacing it, and
unpublishing leaves it in place.

If publishing fails, the previous copy stays online. The list shows **Last
publish failed** and the reason.

Deleting a dashboard also removes its published copies. If a server can't be
reached at the time, the message names it so you can remove the copy manually.

Dashboards in archived projects can't be published.

#### Setting up a destination

Administrators add destinations in **Administration → Publishing → Add
destination**. Credentials are stored encrypted and aren't shown again; when you
edit a destination, existing credentials are kept unless you enter new ones.
SurveyHQ tests a new destination straight away by connecting and writing and
removing a small file. Click **Test** to test it again later.

**GitHub Pages** needs a repository and a token:

1. Create a GitHub repository for the dashboards, for example `dashboards`. A
   public repository is simplest. (GitHub Pages sites are public even if the
   repository is private, and Pages on private repositories requires a paid
   plan.)
2. Create a **fine-grained personal access token** (GitHub → Settings → Developer
   settings → Personal access tokens → Fine-grained tokens) for that repository
   only, with **Contents: Read and write** and **Pages: Read and write**. New
   permissions default to **Read-only**, so change both.
3. Add the destination with the account, repository and token. The branch is
   `gh-pages` unless you change it, and is created on the first publish. The test
   writes to the repository (in an empty repository, it creates an empty
   `.nojekyll` file as the first commit).

If the test says the token can't write, edit the token on GitHub: check that
**Repository access** includes the repository and that Contents is **Read and
write**. The token itself doesn't change, so just test the destination again.

Each publish is one commit to the branch. The first publish turns on GitHub
Pages if the token allows it; otherwise turn it on in the repository's
**Settings → Pages → Deploy from a branch → gh-pages / (root)**. The site will be
at `https://account.github.io/repository/`. New pages take about a minute to
appear. If the site has its own domain, enter it as the **web address**. For
GitHub Enterprise Server, also enter the **API address**.

**SFTP** is for a Linux web server (nginx or Apache) that you can reach over SSH.
Enter the server, user name, password or private key, the **folder** for the
pages (for example `/var/www/html/dashboards`) and the **web address** for that
folder (for example `https://stats.example.org/dashboards/`). The first test
saves the server's key and shows its fingerprint so you can check it. Later
connections are refused if the key changes. If the server has been rebuilt,
click **Forget it** and test again.

**FTP** is for shared web hosting. The fields are the same as for SFTP. The
connection uses FTPS and checks the host's certificate unless you turn these off.
On shared hosting the certificate is often issued for the hosting company's
server name, so use that name.

**Keep a list of the published dashboards at the front of the folder** creates an
`index.html` with links to all dashboards published there, updated as dashboards
are published and removed. It isn't created if the folder already has an index
page.

A destination can't be deleted while it has published dashboards.

### Custom dashboard addresses

Share links end with a long random token, which makes them hard to guess but
also hard to type. If an administrator has set up a dashboard domain, click
**Give it a name…** next to the share link to give the dashboard a short address.
For example, `labour-force` makes the dashboard available at
`labour-force.dash.example.org`, looking exactly like the share link.

Anyone who knows or guesses the name can open the dashboard, so only name
dashboards that are meant to be public:

- only shared dashboards can be given a name
- turning sharing off also removes the name

Reserved names (such as `www`, `api` and `admin`) can't be used. If the option
isn't shown, no domain has been set up; an administrator needs to set
`DASHBOARD_DOMAIN` and the DNS record and certificate described in
[deployment.md](deployment.md).

### Filtering by clicking a chart

Click a bar, slice, point, heatmap cell, table row, indicator breakdown bar or
cross-tab heading to filter the rest of the page by that value. For example,
click the "Northern" bar on "Interviews by province" and the other widgets show
Northern only. A bar at the top shows the selection, with a **Clear** button.

On a cross-tab, click a row heading to filter by the row variable or a column
heading to filter by the column variable. Cells can't be clicked.

On pie and donut charts you can also click the legend to filter.

**Missing values can be clicked too.** They are shown as "-" (or as "(blank)",
".a", ".b" and so on for Stata files with extended missing values). Clicking "-"
shows records where the variable is missing; clicking ".a" shows only that kind
of missing value. A "-" typed as a text answer is treated as a normal value.

The chart you clicked isn't filtered, so you can choose another value. Click the
same value again to clear the selection. Changing page also clears it.

Click filters combine with the filter controls. Widgets whose dataset doesn't have
the variable show a message.

While the page updates, the current figures stay visible (slightly dimmed) until
the new ones load. Automatic refreshes don't dim the page.

### Drill-down

Drill-down lets you click through levels, for example from province to district
to enumeration area.

Click **Drill-down** in the header and list the levels from broadest to most
detailed. Clicking a province then filters the page to that province and regroups
every chart by district; clicking a district regroups by enumeration area. The
bar above the dashboard shows the current level and lets you go back up.

The levels come from the datasets the dashboard uses, so add a widget first.
Charts grouped by something else (such as interviewer or date) keep their
grouping and are just filtered.


### Filters

Click **Filters** in the dashboard header to add filter controls for readers.
Tick a variable and readers get a dropdown of its labels. Choosing a value
filters every widget on the page.

**Names.** Each ticked variable has a box for the name shown on the dashboard.
It starts as the variable label (or the column name if there is no label). You
can type over it, for example "Province" instead of `hh_prov_cd`.

**Date ranges.** Date variables are listed separately under **As a date range**.
Tick one and readers can choose:

- **Today**
- **Yesterday**
- **Last 7 days**
- **Last 30 days**
- **This week** (from Monday)
- **This month**
- **Last month**
- **Choose dates…** to pick a start and end date. Either end can be left open.

A range includes the whole of its last day. Dates stored as text are read as
dates. If you save a view with a named range such as "Last 7 days", it always
means the last seven days from when the view is opened. A file downloaded from
that view uses the range on the day it was made and lists the dates under its
title.

Filters belong to the page they are on, so one page can filter by interviewer and
another by district. A filter only applies to widgets whose dataset has that
variable. Widgets that can't use it show a message.

Indicator tiles and the data quality panel also follow filters. Normally they show
the figures from the last scheduled run. When a filter is set they are
recalculated for the filtered rows and show **Counted for the filters on this
page** instead of the "Updated" time. For percentages, both the top and bottom of
the fraction are filtered, so filtering to one province gives that province's
rate.

**Removing a filter.** Open **Filters**, untick it and save. If a filter's
variable is no longer available (for example, the widget that used its dataset
was deleted, or the variable now has too many values), it is listed at the
bottom with a **Remove** button.

To change the background of the filter bar, use **Appearance → Filter bar
colour**.

### Saved views

Saved views let readers switch between common filter settings with one click.

1. Set the page, filters and drill-down level you want.
2. Click **Save this view** and enter a name.

The view appears as a button above the filters. Click it to apply those settings
again.

Views are stored with the dashboard, not in your browser.

- Views saved by an analyst, manager or admin are **shared**. Everyone who opens
  the dashboard sees them, including people using a share link.
- One shared view can be set as the **default**, which the dashboard opens in.
  This is useful for a screen on a wall.
- Views saved by a viewer, or by someone using a share link, are private to them.

### Making it yours

Click the dashboard title, or click **Appearance**, to change how the header
looks. The options are under **Appearance → Header**:

| Setting | What it does |
|---|---|
| **Logo** | Upload a logo (PNG, JPEG, GIF or WebP, up to 8 MB). It appears beside the title, or above it if the title is centred. It is included on share links, downloads and published copies. |
| **Second logo** | Add a second logo, for example for a dashboard published by two organisations. The two logos sit at each end of the header with the title between them. |
| **Logo height** | 20 to 200 pixels. Applies to both logos. |
| **Make a plain background transparent** | Tick this before uploading a logo that has a solid black or white background. The background colour is removed from the edges inward, so the same colour inside the logo is kept. PNGs that are already transparent are not changed. |
| **Title size** | 16 to 64 pixels. |
| **Title font** | Choose from the interface font, sans serif, serif, slab or monospace. These fonts are built in, so they work without an internet connection. |
| **Title colour and alignment** | Pick a colour and choose left or centred. |
| **Rule under the header** | Adds a line below the header. |
| **Hide the description** | Shows the title only. |

### Giving a widget its own colour

You can set any colour as a widget's **background**. The glossy finish is applied
on top of whatever colour you choose.

If you choose a dark background, the widget's text (title, caption, chart axes
and legend) changes to a light colour automatically. If you set a **text colour**
yourself, that is used instead.

### How a widget's chart is drawn

**Edit this widget** has two settings for the chart:

**Show values.** Choose whether to print the value on each bar, slice or point,
or leave it as it was when the chart was saved. If a chart has more than 24
bars or points, values are not shown.

**Text size.** Set from 8 to 36 pixels. This works for charts, indicator tiles,
data quality panels, text notes and countdowns, and changes all of the widget's
text. **Default** sets it back to 12.

- On a chart it sets the axes, legend, values and table cells.
- On an indicator it sets the text under the number. The number scales with it
  (30 pixels at the default size of 14, about 47 at 22), and so does any
  breakdown chart. Countdowns work the same way.
- An indicator keeps the text size you chose. If the tile is too short to show
  everything, items are hidden in this order: the trend line, the "Updated" time,
  the progress bar, the projection (for example, "At 191 a day, reaches 4,570 on
  26 Nov") and the change since yesterday. The number, the distance from target
  and "Counted for the filters on this page" are always shown. Make the tile
  taller to see everything.
- If a tile is too short even for the number, the text gets smaller, down to a
  minimum of 10 pixels. Countdowns do the same.
- An indicator's breakdown chart is only drawn if there is room for it.
  Otherwise the tile asks you to make it taller.
- Downloaded and published files use the same sizes.

### A widget's menu

Each widget has a menu button (three dots) at its top right. It appears when you
hover over the widget, and is always shown while you are arranging the
dashboard.

Depending on the widget and your role, the menu has:

- **Copy the table, for Excel** or **Copy as a picture**
- **Fill the window**
- **Move to (page)**, if the dashboard has more than one page. The current page
  is ticked.
- **Comment**
- **Edit this widget** and **Remove from dashboard**, if you can edit the
  dashboard.

### Taking a widget with you

Anyone viewing the dashboard can copy a widget from its menu.

**Tables.** **Copy the table, for Excel** copies the rows to the clipboard.
Paste into Excel and they fill the cells; paste into a text editor and they are
tab-separated. Only the rows on screen are copied, so if you have filtered the
columns, the copy is filtered too.

Copying works on both HTTP and HTTPS sites.

**Charts.** **Copy as a picture** copies an image of the chart that you can paste
into a report. Some browsers don't allow images to be copied on HTTP sites; in
that case the picture is downloaded as a file instead.

### Filling the screen with one widget

Choose **Fill the window** from a widget's menu to show it at full size. This
helps with crowded charts, long tables and detailed maps. Press **Escape** or
click **Close** to go back.

Any filters you have set still apply, and the widget keeps its colours and the
dashboard background.

### Filtering a table by its columns

Click **⌕** above a table to show a filter box under each column heading. Type
in a box to filter the rows. The button then shows how many rows are showing out
of the total.

- Text columns match on the label shown, not the code behind it.
- Number columns also accept comparisons, such as `> 100` or `<= 0`.

This only filters what is on your screen. It doesn't change what other people
see.

### Captions

Every widget can have a **caption**. Add it when you create the widget, or later
with **✎**. It appears in small text under the widget.

Use it to explain things the reader can't see, such as which records are
counted, what was left out, or where a target came from. Captions are shown on
share links too.

### Comments on a widget

Each widget has its own comments. Hover over the widget to see the comment count
beside the title, or choose **Comment** from its menu.

You can reply to, edit and **resolve** comments. Resolved comments are hidden but
can be shown again.

Comments are linked to the view they were made in. A comment made while a saved
view was open is shown when that view is open. Comments made on the dashboard
without a view are shown on the dashboard. If you delete a view, its comments
stay on the widget.

### One widget at a time

Use **✎** on a widget to change settings for that widget only:

- background colour
- transparency
- font
- text colour
- title font, size and position
- the main colour of a chart
- shadow

Any setting you leave empty uses the dashboard's setting.

**Title.** Choose the font, size and position (left or centred) for the widget
title. Left is easier to scan down a column; centred suits a tile that stands on
its own.

**Text colour** applies to the title, caption and chart labels (axes, axis
titles, legend and values printed beside bars or points). Values printed inside
a bar or slice stay white so they can be read.

**Chart colour** sets the first colour of the chart. Charts with several series
still use different colours for the others so you can tell them apart. Pick a
colour from the swatches, type a code such as `#1F4E79`, or use the colour
picker. The swatches are ordered so that they work for people with colour
blindness.

**Shadow** helps a widget stand out on a coloured or photo background.

### Appearance

**Appearance** has the following settings for the whole dashboard.

**Ready-made looks.** There are 48 looks at the top of the dialog. Each one sets
the page background, title band, board, page tabs and filter bar together. You
can change any of these afterwards. Hover over a look to see what it is for.

| Group | Looks | Good for |
|---|---|---|
| Light | Plain, Paper, Bureau, Linen, Arctic, Sandstone, Mint, Rose, Slate, Citrus | Reading on a desk and printing |
| Dark | Harbour, Forest, Ochre, Midnight, Blueprint, Lagoon, Moss, Carbon, Plum, Volcano | Wall screens and dim rooms |
| Colour | Cobalt, Coral, Savannah, Monsoon, Copper, Orchid | Programme or project branding |
| Flag colours | 22 looks based on national flag colours | Matching a national colour scheme |

Each flag colour look also sets the chart colours, starting with the flag's
colours and filled out to eight so every series is different. The colour strip
under each swatch shows the palette, which is applied when you save. These
palettes are also in the chart colours list next to **Filters**, so you can use
them with a different look.

**Other settings:**

| Setting | What it does |
|---|---|
| **Title band** | One colour, or two for a gradient, behind the dashboard title. The title gets larger, the description goes under it, and the buttons move to their own row. Text changes to light or dark to suit the band. |
| **Page ground** | The colour behind the whole page, around the board. It only applies to this dashboard and is included on share links. |
| **Background** | The board itself. Choose a colour, a ready-made ground or an uploaded image (PNG, JPEG, GIF or WebP, up to 8 MB). Images can fill, fit or repeat, and the fade slider keeps text readable. |
| **Canvas width** | Fit the window, or a fixed width that scrolls (useful for wall screens). |
| **Columns** and **row height** | How fine the grid is. |
| **Widget transparency** | How much of the background shows through widgets. |
| **Behind the page tabs** | The colour of the tab band. |
| **Page tab colour** and **filter label colour** | The text colour of the tabs and filter labels. If left empty, tabs use black or white depending on the background, and filter labels are grey. |
| **Filter bar colour** | The background of the filter bar. |

There are twelve ready-made grounds: Mist, Paper, Graph paper, Dots, Sand, Dawn,
Arctic, Blueprint, Sea, Moss, Carbon and Plum. They are drawn by the app, so they
work in downloaded dashboards, print without a connection and stay sharp at any
zoom. Mist, Paper, Graph paper, Dots and Carbon are textures that take on the
board's colour. The other seven have their own colour. An uploaded image replaces
the ground.

## Monitoring

### Indicators

An indicator tracks one number, such as completed interviews or the refusal
rate.

To create one, go to **Indicators → New indicator**. Enter a name, pick a
dataset and choose the measure (a count of records, or a sum, mean or other
aggregate of a variable). The rest is optional:

- **Target.** Shows a progress bar.
- **Warning** and **critical** thresholds.
- **Direction.** With "higher is better", the indicator turns amber at or below
  the warning threshold and red at or below the critical threshold. With "lower
  is better" it works the other way round.
- **Breakdown variable.** Lets you see the indicator by region, team or another
  group.
- **Target for each group** in the breakdown.
- **Percentage.** Shows the number as a share instead of a count.

The direction and thresholds are under **On track or not**.

**Status badge.** The badge shows **On track**, **Watch** or **Critical**
depending on the thresholds. If an indicator has no thresholds it shows **No
target** (if it has no target either) or **No thresholds** (if it has a target).
These indicators aren't counted as on track on the Overview.

**Which datasets you can choose.** You can only pick datasets in the project
selected at the top of the page. Under "All projects" you can pick any dataset.
An indicator belongs to the same project as its dataset.

**Percentages.** The indicator's filters choose which rows are counted. **Percent
of** sets what they are divided by:

- **Of all rows** divides by every row in the dataset, before the indicator's
  filters. Use this for something like "% of interviews completed".
- **Of those who answered** divides by the rows that have a value for the
  variable being measured.

**A formula over several counts.** Use this for ratios between two different
counts, such as refusals per completed interview. Under **Count**, choose **A
formula over several counts**.

1. Add the **parts**. Each part has its own count and filters and a short name,
   for example `done`, `issued`, `refused` or `visits`.
2. Write the **formula** using the part names, numbers, `+ - * /` and brackets.
   For a percentage: `done / issued * 100`. For a ratio: `visits / interviews`.

While you work, each part shows its current count (for example, "issued counts
300 right now") and the line under the formula shows the result. This makes it
easy to spot a part that counts nothing.

**Report it as** only changes how the number is displayed (as a percentage or
not).

When you use a formula, the single measure and **Percent of** settings are
ignored. The formula is also used for:

- **Breakdowns.** Each group uses its own parts, so a province shows 50% of its
  own issued work.
- **Page filters.** Every part is filtered the same way.
- **Groups with nothing to divide by.** These show no value instead of 0.
- **Exports.** The exported web page and Word report give the same result.

The formula box only accepts part names, numbers, the four operators and
brackets. Anything else is rejected.

**A survey weight.** Choose a weight variable under **Survey weight** to weight
the count, share, sum or mean:

- A weighted count adds up the weights of the rows counted.
- A weighted share divides that by the total weight of the rows it is a share
  of.
- A weighted mean is the weighted sum divided by the weighted count.
- A weighted count of a variable only includes rows where the variable has a
  value.

Medians and distinct counts can't be weighted, so a formula that includes one
can't be weighted either. The form tells you which part is the problem. In a
formula, all parts use the same weight. A weighted indicator shows **Weighted
by …** under the number, and exports use the weighted figure.

**Target date.** If the indicator has a target, enter a date in **Reach it by**,
for example the last day of fieldwork. The tile then uses the indicator's
history to show:

- *At 190 a day, reaches 15,040 on 18 Nov, in time*, or *after 30 Nov* in red if
  the current pace is too slow.
- *Needs 240 a day to make 30 Nov*, if the current pace won't reach the target.
- *Not moving towards the target this week*, if there has been no progress.
- *The target date, 30 Nov, has passed*, once the date has gone.

The pace is the average daily change over the last week, so it needs at least a
day of history. "Lower is better" indicators are projected downwards. Indicators
with no direction aren't projected. Without a date you still get the
projection, but not "in time". An indicator with no target only shows its
average per day. If the target is more than ten years away at the current pace,
the tile says so instead of giving a date.

**Recent change.** Each tile shows how the number has changed, for example
*+212 since yesterday · +1,340 in a week*. The colour shows whether the change is
good or bad for the indicator's direction. A new indicator needs at least a day
of history before this appears. Percentages change in points, so going from 40%
to 42% is two points. This line is shown on dashboard tiles, the Indicators page
and the Overview. It isn't shown when page filters are applied.

**Editing.** Click **✎** on an indicator to change anything about it, including
the dataset. Its history is kept.

**A target for each group.** Once you choose a breakdown variable, **Where the
quotas come from** gives two options:

- a **target set**, a shared list of quotas (see [Targets](#targets) below). Use
  this for long lists such as enumeration areas in a census.
- type a quota into a box for each group. The boxes are filled from the values
  in the data. This is fine for a short list such as four provinces.

Quotas are matched to groups by the label shown on screen. For example, if an
enumeration area is stored as 405 and labelled `0405`, the quota is matched to
`0405`. Quotas entered against the code still work.

Each box is that group's own quota, not a share of the overall target. Under the
list, the form shows what the quotas add up to and how this compares with the
overall target, for example "38 groups with a quota, adding up to 14,820, 220
short of the overall 15,040". The totals don't have to match, but a difference is
often a typing mistake.

Groups left blank have no quota and aren't judged against one.

The warning and critical thresholds are scaled to each group's quota. A province
with a tenth of the total quota reaches its warning at a tenth of the count.

**Breakdowns on a dashboard.** Tick **Show the breakdown** on an indicator widget
to show the breakdown under the number. Clicking a bar filters the page by that
group.

**Draw the breakdown as** a chart or a table. A table is easier to read when
there are many groups. It shows each group, its value, its quota and its share
of the quota, and scrolls inside the tile. Group names in the table can be
clicked to filter the page. Quota columns are left out if no group has a quota.
Groups without a quota show a hyphen. Exported dashboards use the same setting.

**Order the groups by:**

- **Furthest behind first** (default). Groups with no quota go last.
- **Most complete first**
- **Largest first**, useful when there are no quotas.
- **By name**, for looking up a group.

The Indicators page always shows the breakdown furthest behind first. Exported
dashboards use the widget's setting.

**Quota charts.** When groups have quotas, each bar is the group's quota. The
coloured part is what has been achieved, the rest is still to go, and anything
over the quota is shown as a separate segment. Groups without a quota just show
their value.

Quota charts are also used on the **Indicators** page (under **Show by …**) and
in exported web pages. The Word report adds an "Its own target" column, with the
overall target on the Total line.

For "lower is better" indicators the quota is a ceiling. There is no "still to
go" part, and going over the quota is shown as a warning.

### Targets

The **Targets** tab on the **Indicators** page holds target sets. A target set is
a named list of groups and the quota for each one. Several indicators can use
the same set, for example households enumerated, questionnaires received and
interviews verified. Old links to the separate Targets page still work and open
this tab.

**Creating a target set**

1. Click **New target set**.
2. Enter a name, pick the dataset and the variable the groups come from (for
   example `EA_Id`, `province` or `team`).
3. Paste the list.

**Pasting.** You can paste in two formats:

- **A group and a number on each line**, for example `EA0508,346`. Tabs (as
  copied from a spreadsheet) and semicolons also work. A header line such as
  `EA_Id,target` is ignored. Commas inside numbers are handled, so
  `EA0508,15,040` is read as a quota of 15,040.
- **A single column of numbers.** These are matched to the groups in sorted
  order, so sort your spreadsheet the same way. The list below shows which
  number went to which group.

Pasting replaces the whole list.

Before you save, the form shows how many quotas were read, how many matched a
value in the data, and which didn't match. Check this carefully: spreadsheets
often drop leading zeros, so `0508` becomes `508` and won't match. Groups with no
matching value are marked in the list.

**Linking to indicators.** An indicator uses a target set by linking to it. A
linked target set replaces any quotas typed into the indicator. The typed quotas
are kept, so if you unlink the set they are used again. If you delete a target
set, the indicators that used it go back to their own quotas.

A breakdown shows up to 5,000 groups. If there are more, it tells you.

Indicators are recalculated on a schedule. Each run is saved, which gives every
indicator a trend line.

To count something specific, such as completed interviews, add a filter to the
indicator, the same way as in Explore.

### Alerts

To create an alert, go to **Alerts → New alert rule**. Pick an indicator, a
comparison and a threshold. When the condition is met, an alert is raised with
the severity you chose. Alerts are shown in the app and can also be sent by
email.

The **cooldown** stops the same problem from raising repeated alerts. When the
value goes back to normal, open alerts for that rule are resolved automatically.

| Button | What it does |
|---|---|
| **Test now** | Checks the rule straight away instead of waiting for the next scheduled run. |
| **Edit** | Changes the rule, including the indicator it watches. The rule's history is kept. |
| **Pause** | Stops the rule raising alerts without deleting it. Paused rules are marked in the list. |
| **Resume** | Starts a paused rule again. |

You can **acknowledge** an alert to show someone is looking at it, or
**resolve** it once it has been dealt with.

If there are no rules, the page shows **Nothing is being watched yet**.

### Data quality

The **Data quality** page lists your checks and whether each one is passing.

It opens on **All datasets**, which shows every check grouped by dataset.
Datasets with failing checks come first. Within each dataset, failing checks come
first, then checks that haven't run yet, then passing checks. Datasets with no
checks are listed at the end.

To see one dataset, choose it in the **Dataset** box (each dataset shows how many
checks are failing) or click **Only this dataset** next to its group. With one
dataset selected you also get:

- recommended checks
- **Run all**
- **Export quality workbook**

**Add check** works in both views. From All datasets it asks which dataset first.

**Recommended checks.** The app looks at a dataset and suggests checks that suit
it, such as duplicate interview keys, very short interviews, missing GPS,
variables with a lot of missing values, and people entered twice with a
different spelling. Click to accept one and it is created and run straight away.

**Check types**

| Check | Flags |
|---|---|
| Missing values | Records where a variable is blank |
| Value out of range | Values below a minimum or above a maximum |
| Duplicate records | Repeated key combinations, for example the same interview key twice |
| Likely duplicates (similar records) | Records similar enough to be the same person entered twice |
| Statistical outliers | Values far from the rest (IQR or z-score) |
| Interview duration | Interviews that were too quick |
| Missing GPS | Records with no usable coordinates |
| Constant answers | Interviewers recording the same answer for everyone |
| Logic condition | Rows that meet a condition you write |

#### Logic conditions

Use a **Logic condition** for rules specific to your questionnaire, for example:

- a respondent under 18 recorded as married
- an interview that ends before it starts
- a household total that doesn't equal the sum of its parts

You build the condition the same way as a filter, with two extras:

- **Add group** puts brackets around part of the condition so you can mix "and"
  and "or". For example, `(age under 18 and married) or (age over 90 and in
  work)` is two groups joined by "any".
- Each row can compare against **a variable** instead of a value, for example
  `end_date` earlier than `start_date`. Only the six comparisons that work
  between two columns are offered.

**Which rows are the problem** sets the direction:

- **The rows that match the condition.** Describe what is wrong.
- **The rows that do NOT match it.** Describe what must be true. The check finds
  rows that break it, like Stata's `assert`.

If a value needed by the condition is missing, the row is skipped, not flagged.
For example, a check that `end_date` is on or after `start_date` won't flag
interviews with no end date. Use a Missing values check for those. Because of
this, the matching and non-matching counts don't always add up to the total
number of rows. The difference is the rows that couldn't be checked.

**Start from** fills in a condition for you. **Cross-variable consistency**
compares one variable with another in the "must be true" direction. You can then
add rows, groups or change the direction.

Cross-variable consistency used to be a separate check type. Older checks of
that type still run and open in their own form, but new ones are created from
the preset.

#### Likely duplicates

**Duplicate records** only finds keys that repeat exactly. A person entered twice
often has small differences, for example "Mary Smith, 34, born 05/03/1990" and
"Marie Smith, 35, born 05/03/1990". **Likely duplicates** compares pairs of
records field by field, gives each pair a similarity score and flags pairs that
are similar enough to be the same person.

**Compare these fields.** Choose at least two fields and how to compare each:

| Compared by | Counts as alike when | Use for |
|---|---|---|
| Similar spelling | The spellings are close (Jaro-Winkler similarity). Case, accents, punctuation and word order are ignored, so "Smith John" matches "John Smith" | Names |
| Number within ± | The difference is within the tolerance | Age (±1 by default), household size |
| Date within ± days | Within the tolerance, or the same date with day and month swapped | Date of birth |
| Exactly the same | Equal, ignoring case and spaces around the value | Codes such as sex or relationship to head |

When you choose a variable, a comparison is suggested based on its type. You can
change it.

If a name is split into first name and surname, choose the first name and click
**+ name part** to add the surname. The parts are joined before comparing, so a
name typed in the wrong boxes still matches.

**How the score is calculated**

- Each field scores between 0 (different) and 1 (the same). Spelling gives a
  score in between; numbers, dates and codes score 0 or 1.
- The overall score is the **weighted average** of the field scores. **Weight**
  sets how much each field counts. Names start at 2 and other fields at 1.
- Blank values are left out, not counted as a difference. A pair is only scored
  if the fields both records have make up at least half of the total weight.

**How alike counts as a likely duplicate** starts at 90%. At 90%, a name with one
or two letters different and an age one year apart is found, but two relatives
with the same surname are not. Lower values find more pairs, including more
false matches. 95% and above finds little more than typing errors.

**Only compare records with the same** makes the check faster on large datasets.
Comparing every record with every other means n×(n-1)/2 pairs, so 10,000 people
is 50 million pairs. Grouping by enumeration area, household or the first letter
of the surname reduces this a lot. Duplicates split across groups won't be
found, for example a person listed in two different areas. A check that would
compare more than 25 million pairs is refused, with a suggestion of what to
group by.

**Show to tell the records apart** adds identifiers, such as the interview key or
line number, to each pair.

**Results.** Flagged rows are shown in pairs, most similar first. Each record
shows its pair number and similarity, then the identifiers and compared fields,
then the other variables. A record similar to two others appears in both pairs.
The message gives both counts, for example "8 record(s) look like duplicates of
another: 4 pair(s) at least 90% alike on ...". The failure rate is the share of
records in at least one pair.

If a dataset has a person's name and an age or date of birth, the recommended
checks include **Same person entered twice**, with name parts, age within one
year, date of birth, sex and an identifier already filled in. Interviewer and
supervisor names are not used.

**Limits.** The check compares spelling, not sound, so "Kathryn" and "Catherine"
score lower than a single missed letter. A flagged pair needs checking by a
person. For example, twins can share a surname, date of birth and sex.

#### Settings shared by all checks

**Tolerance** is the share of flagged rows allowed before the check fails. Zero
means any flagged row fails the check, which suits duplicate interview keys. A
few percent is more realistic for short interviews.

**Edit** changes a check and runs it again. You can't change the check type.

**Only check part of the dataset** adds a filter to the check. The filter applies
to both the flagged rows and the total, so the failure rate is a rate of what
was checked, for example "3% of interviews in Northern".

**When checks run.** Checks run:

- whenever their dataset is updated (by upload, Survey Solutions import, folder
  import or reviewed import)
- every six hours
- when you click **Run** or **Run all**

#### Data quality panels on a dashboard

Add a **data quality panel** to a dashboard to show check results there. It shows
the last run and how old the oldest result is.

Each failing check is shown with a coloured bar down its left edge and its
failure rate on the right.

**Show it as** changes what the panel shows:

| Option | Shows |
|---|---|
| **The findings, listed** | The list of checks (default) |
| **Share of rows failing** | One bar per check, longest first, coloured by the check's result. A check allowed 5% at 3% is green (passing); a check allowed 0% at 2.5% is red. |
| **How many rows flagged** | The same chart with counts |
| **Failure rate over time** | A line per check over the last month, using the last run of each day. Days with no run are left as gaps. |
| **Rows flagged over time** | The same, with counts. While data is still coming in, the rate can fall while the count rises. |
| **Passing, failing and never run** | The three counts as one chart, in green, red and grey |

**Drawn as** sets the chart type:

- Share of rows failing: horizontal bars, columns or a table
- How many rows flagged: horizontal bars, columns, table, pie or donut
- Trends: line, area or table
- Passing, failing and never run: donut, pie, bars or table

You can also change **Show it as** from the panel's **...** menu. The current
option is ticked. Your choice is saved with the dashboard. This is available to
anyone who can edit the dashboard. **Drawn as** is only in the edit dialog.

**Draw at most** limits the chart to the worst few checks. The panel says how
many it shows, for example "the 5 worst of 14 checks", and the counts above the
chart still include every check. Leave it blank to show all checks. This applies
to the per-check charts only.

The worst check is always where you start reading: at the top of horizontal
bars, and first on other charts. Bars are coloured by result. Pies use separate
colours for each check.

The two trend charts use stored runs of the whole dataset, so page filters don't
apply to them. The panel shows a note saying so. The other views follow the page
filters.

**Text size** sets the size of the panel's text, from 15 pixels (default) up to
28. It also sets the chart labels.

Charts make room for larger text:

- Names beside horizontal bars can use up to a third of the width before they are
  shortened with "…".
- Names under columns are shortened to the column width when they are long.
- Space for values at the end of bars grows with the text.
- Axis values that would overlap are dropped.

This applies to all dashboard charts.

**Filters.** When the page is filtered, for example to one province, the panel
recalculates the checks for those rows. A failing check shows how many of the
filtered rows failed, and the panel shows "Counted for the filters on this page"
instead of a time. A check that only covers part of the dataset keeps its own
filter and adds the page filter. When you remove the filters, the panel goes
back to the stored results.

## API keys

Go to **Administration → API keys** to create a key for scripts and
integrations. The key is only shown once, so copy it straight away. See
[api.md](api.md).

## Settings

Administrators can change some settings in **Administration → Settings** without
restarting the server. There are five groups:

| Group | Settings |
|---|---|
| **Files and uploads** | Maximum upload size, and how large a zip file can be once unpacked |
| **How often things run** | How often to look for due imports, recalculate indicators and check alert rules |
| **Analytics and caching** | Whether to cache results in Redis and for how long, the file size above which delimited files are read by DuckDB, and whether to summarise fieldwork after each import |
| **Email** | The mail server used for alerts and invitations. The password is stored encrypted and is never shown. Leave the box empty to keep the current password. |
| **Access and disclosure** | Self-service accounts, the sign-in rate limit, and the minimum count below which a table cell is hidden |

Each setting shows what it does, its current value and where the value comes
from. "From .env" means it hasn't been changed. "Set here" means it has been
changed here; it shows the original value and a **put it back** link.

Changes take effect within about 30 seconds and are recorded in the audit log
straight away with your name.

Some settings can only be changed in the `.env` file on the server. These include
the secret key, the encryption key, the database and Redis connections, and the
addresses the platform runs on. The `.env` file also holds the defaults for the
settings above.

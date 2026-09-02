# User guide

## Roles

| Role | Can do |
|---|---|
| **Viewer** | Read dashboards and analyses |
| **Analyst** | Everything above, plus build charts, dashboards and run any analysis |
| **Manager** | Everything above, plus upload data, manage connections, indicators and quality rules |
| **Administrator** | Everything, plus manage users and see the audit log |

## Getting data in

### Uploading a file

**Datasets → Upload data**. Supported: Stata (`.dta`), SPSS (`.sav`), CSV,
tab-delimited (`.tab`, `.tsv`) and Excel.

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

## Looking at a dataset

The dataset page has four tabs:

- **Variables** — every variable with its label, type, missing count, distinct
  count and range. Variables missing on more than 20% of records are highlighted.
  **Tabulate** on any row gives an instant frequency table with a chart.
- **Data** — page through the raw rows.
- **Statistics** — mean, standard deviation, min, quartiles, median and max for
  every numeric variable.
- **Field progress** — submissions over time, interviews per interviewer and
  supervisor, status breakdown, coverage by area and a GPS map. Appears
  automatically when the relevant columns are recognised.

## Explore

**Explore** is where analysis happens. Two modes.

### Tabulate & chart

1. **Group by** one or two variables. Dates offer a grain (day, week, month,
   quarter, year). Numeric variables can be binned by width. The first grouping
   can keep the top N categories and fold the rest into "Other".
2. **Measure**: count, share of total, sum, mean, median, min, max, standard
   deviation, percentiles or distinct count. Add several measures to compare
   them side by side. Any measure can be weighted by a numeric variable — pick
   your survey weight to get weighted estimates.
3. **Filters**: as many conditions as you like, combined with all/any. Variables
   with value labels offer a dropdown of their labels.
4. **Display**: chart type and row limit, then **Run query**.

Results can be viewed as a chart or a table, exported to CSV or Excel, and saved
as a chart for use on a dashboard. **Show SQL** reveals the generated query if
you want to check what was computed.

If you are not sure where to start, **Suggested analyses** proposes charts built
from the dataset's own variables — one click to run.

### Cross-tabulation

Pick a row variable and a column variable, choose what the cells hold (count by
default, or any aggregate of a numeric variable), and choose percentages: none,
row, column, or percent of total. Row and column totals are always shown.

Underneath, chi-square and Cramér's V are reported so you can see whether an
apparent association is worth anything.

## Charts and dashboards

Any Explore result can be saved as a chart. Saved charts live under
**Dashboards → Saved charts**, each showing live data.

To build a dashboard:

1. **Dashboards → New dashboard**.
2. **Add widget** — a saved chart, an indicator tile, or a text note.
3. **Arrange** — drag widgets around and resize them; the layout saves itself.
4. **Share link** — generates a read-only public URL, copied to your clipboard.
   Anyone with the link can view the dashboard without an account. Press again
   to revoke it.

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
- a **breakdown variable**, so the indicator can be expanded per region or team.

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

Checks run every six hours, and on demand with **Run** or **Run all**.

## API keys

**Administration → API keys** creates a key for scripts and integrations. The key
is shown once — copy it then. See [api.md](api.md).

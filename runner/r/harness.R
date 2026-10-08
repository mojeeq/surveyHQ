# What runs around somebody's script.
#
# Reads the job the platform wrote, applies the labels, runs the script, reads
# the labels back off whatever it produced, and writes the answer. The label
# translation lives in labels.R so it can be tested without Parquet; this file
# is the I/O and the running.
#
# Called as: Rscript harness.R <job directory>

suppressPackageStartupMessages({
  library(arrow)
  library(jsonlite)
})
source(file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])), "labels.R"))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) stop("usage: harness.R <job directory>")
job <- args[[1]]

started <- Sys.time()
finish <- function(ok, error = "", rows = NA_integer_, columns = NA_integer_) {
  write_json(
    list(
      ok = ok,
      error = error,
      rows = rows,
      columns = columns,
      seconds = as.numeric(difftime(Sys.time(), started, units = "secs"))
    ),
    file.path(job, "result.json"),
    auto_unbox = TRUE
  )
  # Written last and on its own, so the platform never reads a half-written
  # result: the marker existing is the promise that everything else is there.
  file.create(file.path(job, "DONE"))
  quit(status = if (isTRUE(ok)) 0L else 1L, save = "no")
}
fail <- function(message) finish(FALSE, as.character(message))

# --- in ---------------------------------------------------------------------

data <- tryCatch(
  as.data.frame(arrow::read_parquet(file.path(job, "in", "data.parquet"))),
  error = function(e) fail(paste("could not read the data:", conditionMessage(e)))
)

labels_path <- file.path(job, "in", "labels.json")
if (file.exists(labels_path)) {
  data <- apply_labels(data, fromJSON(labels_path, simplifyVector = FALSE))
}

# --- the script --------------------------------------------------------------

# Run in this environment so the script sees `data`, and whatever it leaves in
# `data` is what gets written. The same contract as the command box: there is
# one table in memory, and saving writes that one.
log_path <- file.path(job, "log.txt")
connection <- file(log_path, open = "wt")
sink(connection, type = "output")
sink(connection, type = "message")
ran <- tryCatch(
  {
    source(file.path(job, "script.R"), local = environment(), echo = FALSE)
    TRUE
  },
  error = function(e) conditionMessage(e)
)
sink(type = "message")
sink(type = "output")
close(connection)

if (!isTRUE(ran)) fail(ran)
if (!is.data.frame(data)) fail("the script left something that is not a table in `data`")
if (ncol(data) == 0L) fail("the script left a table with no columns")

# --- out ---------------------------------------------------------------------

dir.create(file.path(job, "out"), showWarnings = FALSE, recursive = TRUE)
found <- read_labels(data)

written <- tryCatch(
  {
    # Labels beside the file rather than in it: Parquet has no standard place
    # for them, and a sidecar is readable by the platform without R.
    arrow::write_parquet(remove_labels(data), file.path(job, "out", "data.parquet"))
    write_json(found, file.path(job, "out", "labels.json"), auto_unbox = TRUE)
    TRUE
  },
  error = function(e) conditionMessage(e)
)
if (!isTRUE(written)) fail(written)

finish(TRUE, "", nrow(data), ncol(data))

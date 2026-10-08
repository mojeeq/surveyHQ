# The label translation, checked without Parquet or a container.
#
# This is the half of the round trip that can be subtly wrong, and the half
# that fails silently: a chart keeps rendering, it just loses the question
# wording. Run it with:  Rscript runner/r/test-labels.R

source(file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])), "labels.R"))

failures <- 0L
check <- function(what, ok) {
  if (isTRUE(ok)) {
    cat("  ok   ", what, "\n", sep = "")
  } else {
    failures <<- failures + 1L
    cat("  FAIL ", what, "\n", sep = "")
  }
}

frame <- function() {
  data.frame(
    interview__key = c("k1", "k2", "k3"),
    age = c(4, 33, 70),
    sex = c(1, 2, 2),
    province = c("Central", "Western", "Central"),
    stringsAsFactors = FALSE
  )
}

meta <- list(
  variable_labels = list(
    age = "Age of respondent in completed years",
    sex = "Sex of respondent",
    province = "Division"
  ),
  value_labels = list(sex = list(`1` = "Male", `2` = "Female"))
)

# Every call to the code under test goes through this. An error in it is a
# failure of that check, not the end of the run: a translation that throws on
# the first Stata file would otherwise take this whole file down with it and
# report nothing at all.
attempt <- function(expr) tryCatch(expr, error = function(e) conditionMessage(e))

cat("variable labels\n")
applied <- attempt(apply_labels(frame(), meta))
check("the labels go on without erroring", is.data.frame(applied))
if (!is.data.frame(applied)) {
  cat("  (", applied, ")\n", sep = "")
  applied <- frame()  # carry on, so the rest reports rather than crashes
}
check("the wording is on the column", labelled::var_label(applied$age) ==
  "Age of respondent in completed years")
back <- read_labels(applied)
check("it comes back under the same name", identical(
  back$variable_labels$province, "Division"
))
check("a column with no label is not invented", is.null(back$variable_labels$interview__key))

cat("value labels\n")
check("the codes are on the column", identical(
  unname(labelled::val_labels(applied$sex)), c(1, 2)
))
check("a script sees the words", identical(
  as.character(labelled::to_factor(applied$sex)), c("Male", "Female", "Female")
))
check("they come back as code to text", identical(
  back$value_labels$sex, list(`1` = "Male", `2` = "Female")
))

cat("numeric codes against a numeric column\n")
# JSON keys are always text. labelled() refuses them against a numeric column,
# so without the conversion the harness does not lose labels - it dies, on the
# first Stata file it is handed. Wrapped, because an error here would otherwise
# end this run rather than report a failure in it.
converted <- attempt(apply_labels(frame(), meta))
check("text codes are converted, not handed straight to labelled()", is.data.frame(converted))
check("and all of them arrive", length(labelled::val_labels(applied$sex)) == 2L)

cat("text codes against a text column\n")
text_meta <- list(
  variable_labels = list(),
  value_labels = list(province = list(Central = "Central Division", Western = "Western Division"))
)
text_applied <- attempt(apply_labels(frame(), text_meta))
check("text codes survive too", is.data.frame(text_applied) && identical(
  read_labels(text_applied)$value_labels$province,
  list(Central = "Central Division", Western = "Western Division")
))

cat("what the script did is what comes back\n")
dropped <- applied
dropped$sex <- NULL
after_drop <- read_labels(dropped)
check("a dropped variable takes its label with it", is.null(after_drop$variable_labels$sex))
check("and its value labels", is.null(after_drop$value_labels$sex))

renamed <- applied
names(renamed)[names(renamed) == "province"] <- "division"
after_rename <- read_labels(renamed)
check("a rename carries the label to the new name", identical(
  after_rename$variable_labels$division, "Division"
))
check("and leaves nothing under the old one", is.null(after_rename$variable_labels$province))

made <- applied
made$adult <- as.integer(made$age >= 18)
labelled::var_label(made$adult) <- "Aged 18 or over"
check("a label the script wrote is kept", identical(
  read_labels(made)$variable_labels$adult, "Aged 18 or over"
))

cat("nothing to do\n")
bare <- read_labels(frame())
check("an unlabelled frame reports no labels", length(bare$variable_labels) == 0L &&
  length(bare$value_labels) == 0L)
check("empty metadata changes nothing", identical(
  apply_labels(frame(), list()), frame()
))

cat("\n")
if (failures > 0L) {
  cat(failures, "failed\n")
  quit(status = 1L, save = "no")
}
cat("all passed\n")

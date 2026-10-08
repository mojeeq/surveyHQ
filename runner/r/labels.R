# Variable and value labels, between the platform's JSON and R's `labelled`.
#
# Kept apart from the harness because this is the part that can be subtly
# wrong. Parquet has no standard place for labels, and this platform leans on
# them everywhere - axis titles, legends, cross-tab headers, filter dropdowns -
# so a translation that loses one looks like it worked and strips the question
# wording off every chart built on the result.
#
# Pure functions over a data frame, so they can be tested without Parquet, a
# container, or a running platform: see test-labels.R.

suppressPackageStartupMessages(library(labelled))

`%or%` <- function(a, b) if (is.null(a)) b else a

#' Put the platform's labels onto a frame.
#'
#' meta is the parsed labels.json: variable_labels maps name to wording, and
#' value_labels maps name to a code-to-text list.
apply_labels <- function(data, meta) {
  for (name in names(meta$variable_labels %or% list())) {
    if (name %in% names(data)) {
      var_label(data[[name]]) <- as.character(meta$variable_labels[[name]])
    }
  }

  for (name in names(meta$value_labels %or% list())) {
    if (!name %in% names(data)) next
    pairs <- meta$value_labels[[name]]
    if (!length(pairs)) next

    # JSON keys are always text; the column they describe is usually numeric.
    # labelled() refuses a character code against a numeric column - "Can't
    # convert `labels` <character> to match type of `x` <double>" - so without
    # this the harness dies on the first Stata file it is given, since a
    # value-labelled numeric column is what a Stata file mostly is.
    codes <- names(pairs)
    as_numbers <- suppressWarnings(as.numeric(codes))
    values <- if (!anyNA(as_numbers) && is.numeric(data[[name]])) as_numbers else codes

    data[[name]] <- labelled(
      data[[name]],
      stats::setNames(values, vapply(pairs, as.character, character(1))),
      label = var_label(data[[name]])
    )
  }
  data
}

#' Read the labels back off whatever the script produced.
#'
#' Off the result, never carried forward from the input: a script that dropped
#' or renamed a variable must not have the old label reappear on the new data,
#' which is how a chart ends up captioned with the wrong question.
read_labels <- function(data) {
  variable_labels <- list()
  value_labels <- list()
  for (name in names(data)) {
    one <- var_label(data[[name]])
    if (!is.null(one) && nzchar(one)) variable_labels[[name]] <- one

    pairs <- val_labels(data[[name]])
    if (length(pairs)) {
      # labelled stores them the other way round - text as the name, code as
      # the value - and the platform wants code to text.
      value_labels[[name]] <- stats::setNames(
        as.list(as.character(names(pairs))),
        as.character(unname(pairs))
      )
    }
  }
  list(variable_labels = variable_labels, value_labels = value_labels)
}

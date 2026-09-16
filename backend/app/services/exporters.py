"""Turns query results into downloadable CSV and Excel files."""

from __future__ import annotations

import csv
import io
from typing import Any

from app.schemas.query import CrosstabResult, QueryResult


def query_result_to_csv(result: QueryResult) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([column.label or column.name for column in result.columns])
    for row in result.rows:
        writer.writerow(["" if value is None else value for value in row])
    return buffer.getvalue().encode("utf-8-sig")


# What a withheld cell reads as. A CSV has nowhere to put a footnote, so the
# mark has to carry the meaning on its own and match what the table on screen
# and the exported page both show.
SUPPRESSED_MARK = "*"


def crosstab_to_csv(result: CrosstabResult) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if not result.column_labels:
        # A table with no value columns: the categories and nothing else. The
        # totals would be a column of zeroes and a row saying zero, which is
        # not a smaller file so much as a wrong one.
        writer.writerow([result.row_variable])
        for label in result.row_labels:
            writer.writerow([label])
        return buffer.getvalue().encode("utf-8-sig")
    writer.writerow([result.row_variable] + result.column_labels + ["Total"])
    for index, label in enumerate(result.row_labels):
        hidden = result.suppressed[index] if index < len(result.suppressed) else []
        values = [
            # An empty cell and a withheld one are both blank in the result and
            # must not both be blank in the file: one says nobody was here, the
            # other says we are not telling you.
            SUPPRESSED_MARK
            if j < len(hidden) and hidden[j]
            else ("" if v is None else v)
            for j, v in enumerate(result.values[index])
        ]
        writer.writerow([label] + values + [result.row_totals[index]])
    writer.writerow(["Total"] + result.column_totals + [result.grand_total])
    return buffer.getvalue().encode("utf-8-sig")


def query_result_to_xlsx(result: QueryResult, sheet_name: str = "Results") -> bytes:
    import xlsxwriter

    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {"in_memory": True, "constant_memory": True})
    worksheet = workbook.add_worksheet(sheet_name[:31] or "Results")

    header_format = workbook.add_format(
        {"bold": True, "bg_color": "#1e293b", "font_color": "#ffffff", "border": 1}
    )
    number_format = workbook.add_format({"num_format": "#,##0.####"})

    for column_index, column in enumerate(result.columns):
        worksheet.write(0, column_index, column.label or column.name, header_format)
        worksheet.set_column(column_index, column_index, max(len(column.name) + 4, 14))

    for row_index, row in enumerate(result.rows, start=1):
        for column_index, value in enumerate(row):
            _write_cell(worksheet, row_index, column_index, value, number_format)

    worksheet.freeze_panes(1, 0)
    if result.rows:
        worksheet.autofilter(0, 0, len(result.rows), len(result.columns) - 1)
    workbook.close()
    return buffer.getvalue()


def _write_cell(worksheet: Any, row: int, column: int, value: Any, number_format: Any) -> None:
    if value is None:
        worksheet.write_blank(row, column, None)
    elif isinstance(value, bool):
        worksheet.write_boolean(row, column, value)
    elif isinstance(value, (int, float)):
        worksheet.write_number(row, column, value, number_format)
    else:
        worksheet.write_string(row, column, str(value))


def tables_to_xlsx(tables: dict[str, QueryResult]) -> bytes:
    """Write several result sets into one workbook, one sheet per entry."""
    import xlsxwriter

    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
    header_format = workbook.add_format(
        {"bold": True, "bg_color": "#1e293b", "font_color": "#ffffff", "border": 1}
    )
    number_format = workbook.add_format({"num_format": "#,##0.####"})
    used_names: set[str] = set()

    for raw_name, result in tables.items():
        name = _safe_sheet_name(raw_name, used_names)
        worksheet = workbook.add_worksheet(name)
        for column_index, column in enumerate(result.columns):
            worksheet.write(0, column_index, column.label or column.name, header_format)
            worksheet.set_column(column_index, column_index, 18)
        for row_index, row in enumerate(result.rows, start=1):
            for column_index, value in enumerate(row):
                _write_cell(worksheet, row_index, column_index, value, number_format)
        worksheet.freeze_panes(1, 0)
    workbook.close()
    return buffer.getvalue()


def _safe_sheet_name(name: str, used: set[str]) -> str:
    cleaned = "".join(c for c in name if c not in "[]:*?/\\")[:31] or "Sheet"
    candidate = cleaned
    counter = 2
    while candidate in used:
        suffix = f"_{counter}"
        candidate = cleaned[: 31 - len(suffix)] + suffix
        counter += 1
    used.add(candidate)
    return candidate

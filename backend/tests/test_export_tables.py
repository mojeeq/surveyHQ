"""Turning a widget's numbers into a table, which is what the exports write.

The exported web page holds each widget's numbers at a finer grain than the
widget draws - its own groupings crossed with every filter variable on the
page - so that the page can answer a filter with no database behind it.
Anything writing those numbers into a document has to add that grain back up,
and has to do it the way the page does, or two readings of one board would
disagree.

These were written against the workbook export. The workbook has been taken
out and the arithmetic has not, because the Word report is still built from
it - which is the whole reason the arithmetic lives in a module of its own
now rather than inside something that produces a file.
"""

from __future__ import annotations

from app.services import export_tables


def _cube(dimensions, columns, rows, measures, sort=None):
    return {
        "dimensions": dimensions,
        "filters": [],
        "measures": measures,
        "columns": [{"name": name, "label": label, "type": kind, "data_type": "text"}
                    for name, label, kind in columns],
        "rows": rows,
        "top": None,
        "sort": sort or [],
    }

def test_the_finer_grain_a_filter_needs_is_added_back_up():
    """A cube is held at the widget's grouping crossed with the page's filters.

    The page adds that up again to answer a filter; a workbook answers none,
    so it has to be added up here or every row would appear several times.
    """
    cube = _cube(
        ["province"],
        [("province", "Province", "dimension"), ("interviewer", "Interviewer", "dimension"),
         ("value", "Interviews", "measure")],
        [["Northern", "int1", 4], ["Northern", "int2", 6], ["Highland", "int1", 3]],
        [{"name": "value", "label": "Interviews", "how": "sum", "parts": ["value"]}],
    )
    columns, rows = export_tables.combine(cube)

    assert [column["label"] for column in columns] == ["Province", "Interviews"]
    assert rows == [["Northern", 10], ["Highland", 3]]

def test_a_mean_is_rebuilt_from_its_total_and_its_count():
    """Averaging group averages is not the average, which is why the export
    asks for the parts. A workbook that divided twice would disagree with the
    board it came from."""
    cube = _cube(
        ["province"],
        [("province", "Province", "dimension"), ("interviewer", "Interviewer", "dimension"),
         ("__x0_total", "", "measure"), ("__x0_count", "", "measure")],
        [["Northern", "int1", 100.0, 1], ["Northern", "int2", 20.0, 3]],
        [{"name": "mean_age", "label": "Mean age", "how": "mean",
          "parts": ["__x0_total", "__x0_count"]}],
    )
    _, rows = export_tables.combine(cube)

    # 120 over 4 people, not the average of 100 and 6.67.
    assert rows == [["Northern", 30.0]]

def test_the_youngest_in_a_province_is_the_youngest_of_its_parts():
    """A minimum combines as a minimum, not as a total and not as a maximum."""
    def over(how: str, label: str):
        return _cube(
            ["province"],
            [("province", "Province", "dimension"), ("interviewer", "Interviewer", "dimension"),
             ("value", label, "measure")],
            [["Northern", "int1", 31], ["Northern", "int2", 18], ["Northern", "int3", 44]],
            [{"name": "value", "label": label, "how": how, "parts": ["value"]}],
        )

    assert export_tables.combine(over("min", "Youngest"))[1] == [["Northern", 18]]
    assert export_tables.combine(over("max", "Oldest"))[1] == [["Northern", 44]]

def test_a_share_is_a_share_of_the_table_it_is_on():
    cube = _cube(
        ["status"],
        [("status", "Status", "dimension"), ("value", "Share", "measure")],
        [["Done", 30], ["Open", 10]],
        [{"name": "value", "label": "Share", "how": "share", "parts": ["value"]}],
    )
    _, rows = export_tables.combine(cube)

    assert rows == [["Done", 75.0], ["Open", 25.0]]

def test_a_table_is_in_the_order_the_widget_is():
    cube = _cube(
        ["province"],
        [("province", "Province", "dimension"), ("value", "Interviews", "measure")],
        [["Highland", 3], ["Northern", 10], ["Southern", 7]],
        [{"name": "value", "label": "Interviews", "how": "sum", "parts": ["value"]}],
        sort=[{"field": "value", "direction": "desc"}],
    )
    table = export_tables.widget_table({"kind": "chart", "cube": cube})

    assert table is not None
    assert [row[0] for row in table[1]] == ["Northern", "Southern", "Highland"]

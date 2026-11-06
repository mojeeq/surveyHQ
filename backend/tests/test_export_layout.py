"""An exported board has to be laid out the way the board is.

The platform packs a board upwards: a widget dragged halfway down the page
settles against whatever is above it, and what gets stored is where it was
dropped rather than where it came to rest. The exported page used neither -
it flowed the widgets in the order they were created, each pinned to its own
columns - and that is a different layout whenever a widget is not simply
after the one before it.

Reported from a census board: a counter on the left, a second counter under
it, and a donut beside the first. Exported, the donut came out beside the
*second* counter and the first sat alone with a third of a page of white
beside it.
"""

from __future__ import annotations

from app.services.static_export import _box, pack, place_widgets


def _boxes(*rectangles: tuple[int, int, int, int], columns: int = 12) -> list[dict[str, int]]:
    """(x, y, w, h) as the board stores them."""
    return [
        _box({"x": x, "y": y, "w": w, "h": h}, columns)
        for x, y, w, h in rectangles
    ]


def test_the_donut_comes_back_beside_the_counter_it_sits_beside():
    counter = (0, 0, 3, 4)
    under_it = (0, 4, 3, 3)
    donut = (3, 0, 7, 7)

    assert pack(_boxes(counter, under_it, donut)) == [0, 4, 0]


def test_a_widget_with_nothing_above_it_rises_to_the_top():
    """Stored y is where it was dropped. A board full of those exported as
    bands of empty paper, which is why the page stopped reading y at all."""
    assert pack(_boxes((0, 20, 4, 4))) == [0]
    assert pack(_boxes((0, 0, 4, 4), (0, 30, 4, 4))) == [0, 4]


def test_widgets_in_the_same_columns_keep_their_order_and_do_not_overlap():
    rows = pack(_boxes((0, 0, 6, 3), (0, 9, 6, 3), (0, 4, 6, 3)))
    assert rows == [0, 6, 3]
    # Which is to say: three stacked, in the order they were stored, touching.
    assert sorted(rows) == [0, 3, 6]


def test_a_widget_wider_than_the_board_is_brought_back_inside_it():
    """A board narrowed after its widgets were placed still holds some at the
    old width, and one running off the end adds a column, which narrows every
    other widget on the page to make room for half a widget."""
    assert _box({"x": 10, "y": 0, "w": 6, "h": 4}, 12) == {"x": 6, "y": 0, "w": 6, "h": 4}
    assert _box({"x": 0, "y": 0, "w": 30, "h": 4}, 12)["w"] == 12
    # And a widget that says nothing about itself is the board's own default.
    assert _box({}, 12) == {"x": 0, "y": 0, "w": 4, "h": 6}


def test_each_container_is_packed_on_its_own():
    """A group is a band of its own on the page, so what is loose above it
    cannot decide where its first widget sits."""
    widgets = [
        {"id": "loose", "page": 0, "group_id": "", "layout": {"x": 0, "y": 0, "w": 6, "h": 8}},
        {"id": "inside", "page": 0, "group_id": "g1", "layout": {"x": 0, "y": 9, "w": 6, "h": 4}},
        {"id": "next page", "page": 1, "group_id": "", "layout": {"x": 0, "y": 7, "w": 6, "h": 4}},
    ]
    placed = {widget["id"]: widget["place"] for widget in place_widgets(widgets, 12)}

    assert placed["loose"]["row"] == 0
    assert placed["inside"]["row"] == 0
    assert placed["next page"]["row"] == 0


def test_the_file_is_written_in_the_order_it_is_read():
    """Down the page and then across, so printing and a screen reader follow
    the layout rather than the order somebody happened to add the widgets in."""
    widgets = [
        {"id": "bottom", "page": 0, "group_id": "", "layout": {"x": 0, "y": 8, "w": 4, "h": 4}},
        {"id": "top right", "page": 0, "group_id": "", "layout": {"x": 6, "y": 0, "w": 6, "h": 4}},
        {"id": "top left", "page": 0, "group_id": "", "layout": {"x": 0, "y": 0, "w": 6, "h": 4}},
        {"id": "page two", "page": 1, "group_id": "", "layout": {"x": 0, "y": 0, "w": 4, "h": 4}},
    ]
    assert [widget["id"] for widget in place_widgets(widgets, 12)] == [
        "top left",
        "top right",
        "bottom",
        "page two",
    ]

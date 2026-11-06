"""Records that are probably the same person or household, entered twice.

An exact duplicate check asks whether a key repeats. The duplicates a field
office actually has to find do not share a key: the same woman listed in two
households, as "Mary Smith, 34" in one and "Marie Smith, 35" in the other; a
household interviewed twice by two interviewers, each typing the head's name
their own way. Nothing about them is identical, and everything about them is
close.

So this compares records field by field and scores how alike they are:

- **text** - names, spelled differently: Jaro-Winkler similarity, which is
  forgiving of a transposed or dropped letter and weights the start of a word,
  where names are least often misspelled. Case, accents and punctuation are
  ignored, and the words are put in order first, so "Smith Mary" is "Mary
  Smith". A text field can join several variables - a first name and a surname
  - into one before comparing, which is what catches the names typed into each
  other's boxes.
- **number** - an age, a household size: alike within a tolerance, so 34 and
  35 count as the same age when the tolerance is 1.
- **date** - a date of birth: alike within a number of days, and alike when the
  day and the month have been swapped, which is how a date of birth is most
  often typed wrong.
- **exact** - a code: sex, a village.

Each field has a weight, and a pair's similarity is the weighted mean over the
fields both records have. A blank is not evidence either way, so a field missing
from either record is left out of that pair's mean rather than counted as a
disagreement - and a pair is judged only when at least half the weight could be
compared, so two records alike on nothing but their sex are not called a match.

Comparing every record with every other is n squared: a census of a hundred
thousand people is five billion pairs. So the comparison can be held to records
that share something - the same enumeration area, the same household, the same
first letter of the surname - which is how record linkage is always done, and
the check refuses to start a comparison larger than `MAX_PAIRS`, saying how many
pairs it would have been and what to compare within instead.

All of it is one DuckDB query: the names are normalised once per record, the
pairs are a self-join on the grouping, and the scoring is SQL. Every column
named is looked up in the dataset and quoted; every number is checked as a
finite number before it is written into the query.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.services.query_engine import (
    DatasetContext,
    QueryError,
    _quote_path,
    quote_ident,
    run_sql,
)

#: The ways a field can be compared.
METHODS = ("text", "number", "date", "exact")

#: The ways a comparison can be held to records that share something.
BLOCKS = ("same", "first_letter")

#: The most record pairs one run may compare - several seconds of work.
MAX_PAIRS = 25_000_000

#: How alike a pair has to be, when the rule does not say.
DEFAULT_SIMILARITY = 0.9

#: The share of the fields' weight a pair has to be comparable on to be judged.
MIN_COVERAGE = 0.5

#: Pairs kept in a result's details, most alike first.
EXAMPLE_PAIRS = 20


@dataclass
class Field:
    #: How the field is named to a reader: "first_name + surname".
    variable: str
    #: The quoted columns it reads - several only for a text field joining them.
    columns: list[str]
    method: str
    weight: float
    tolerance: float

    def value(self, alias: str = "") -> str:
        """The field's value as SQL: one column, or text joined from several."""
        qualified = [f"{alias}.{column}" if alias else column for column in self.columns]
        if len(qualified) == 1:
            return qualified[0]
        parts = ", ".join(f"CAST({column} AS VARCHAR)" for column in qualified)
        return f"nullif(concat_ws(' ', {parts}), '')"


@dataclass
class Plan:
    fields: list[Field]
    blocks: list[tuple[str, str]]  # (quoted column, how)
    similarity: float
    ids: list[str] = field(default_factory=list)  # quoted columns shown in pairs
    id_names: list[str] = field(default_factory=list)


def _number(value: Any, default: float, *, low: float, high: float, what: str) -> float:
    try:
        number = float(default if value in (None, "") else value)
    except (TypeError, ValueError):
        raise QueryError(f"{what} has to be a number") from None
    if not math.isfinite(number) or number < low or number > high:
        raise QueryError(f"{what} has to be between {low:g} and {high:g}")
    return number


def plan(ctx: DatasetContext, config: dict[str, Any]) -> Plan:
    """The rule's settings, checked: every variable real, every number finite."""
    fields: list[Field] = []
    for raw in config.get("fields") or []:
        if not isinstance(raw, dict) or not raw.get("variable"):
            continue
        method = str(raw.get("compare") or "text")
        if method not in METHODS:
            raise QueryError(
                f"'{method}' is not a way to compare a field. Use one of: {', '.join(METHODS)}."
            )
        names = [ctx.require(str(raw["variable"])).name]
        # Further variables joined to the first, for a name kept in parts.
        if method == "text":
            names += [ctx.require(str(extra)).name for extra in raw.get("also") or [] if extra]
        fields.append(
            Field(
                variable=" + ".join(names),
                columns=[quote_ident(name) for name in names],
                method=method,
                weight=_number(raw.get("weight"), 1, low=0.1, high=10, what="A field's weight"),
                tolerance=_number(
                    raw.get("tolerance"), 0, low=0, high=100_000, what="A field's tolerance"
                ),
            )
        )
    if len(fields) < 2:
        raise QueryError(
            "A likely-duplicates check compares at least two fields - a name and an "
            "age, say. One field alone is the exact duplicate check."
        )

    blocks: list[tuple[str, str]] = []
    for raw in config.get("block") or []:
        if isinstance(raw, str):
            raw = {"variable": raw}
        if not isinstance(raw, dict) or not raw.get("variable"):
            continue
        how = str(raw.get("how") or "same")
        if how not in BLOCKS:
            raise QueryError(
                f"'{how}' is not a way to group records. Use 'same' or 'first_letter'."
            )
        blocks.append((quote_ident(ctx.require(str(raw["variable"])).name), how))

    ids = [str(name) for name in config.get("id_variables") or [] if name]
    for name in ids:
        ctx.require(name)
    return Plan(
        fields=fields,
        blocks=blocks,
        similarity=_number(
            config.get("min_similarity"),
            DEFAULT_SIMILARITY,
            low=0.5,
            high=1,
            what="The similarity a pair needs",
        ),
        ids=[quote_ident(name) for name in ids],
        id_names=ids,
    )


def _text_key(column: str) -> str:
    """A name as it is compared: no case, accents or punctuation, words in order.

    Letters of any script survive (`\\p{L}`), so a name written with accents or in a
    non-Latin script such as Devanagari is compared on its own letters rather
    than reduced to nothing.
    """
    cleaned = (
        f"trim(regexp_replace(lower(strip_accents(CAST({column} AS VARCHAR))), "
        f"'[^\\p{{L}}\\p{{N}}]+', ' ', 'g'))"
    )
    return f"nullif(array_to_string(list_sort(string_split({cleaned}, ' ')), ' '), '')"


def _key(item: Field) -> str:
    """The value of a field as each record carries it into the comparison."""
    if item.method == "text":
        return _text_key(item.value())
    if item.method == "number":
        return f"TRY_CAST({item.value()} AS DOUBLE)"
    if item.method == "date":
        return f"TRY_CAST({item.value()} AS DATE)"
    return f"nullif(lower(trim(CAST({item.value()} AS VARCHAR))), '')"


def _alike(item: Field, left: str, right: str) -> str:
    """How alike two records are on one field, 0 to 1, or NULL when either lacks it."""
    missing = f"{left} IS NULL OR {right} IS NULL"
    if item.method == "text":
        return f"CASE WHEN {missing} THEN NULL ELSE jaro_winkler_similarity({left}, {right}) END"
    if item.method == "number":
        return (
            f"CASE WHEN {missing} THEN NULL "
            f"WHEN abs({left} - {right}) <= {item.tolerance!r} THEN 1.0 ELSE 0.0 END"
        )
    if item.method == "date":
        return (
            f"CASE WHEN {missing} THEN NULL "
            f"WHEN abs(date_diff('day', {left}, {right})) <= {item.tolerance!r} THEN 1.0 "
            # The day and the month typed the wrong way round.
            f"WHEN year({left}) = year({right}) AND month({left}) = day({right}) "
            f"AND day({left}) = month({right}) THEN 1.0 ELSE 0.0 END"
        )
    return f"CASE WHEN {missing} THEN NULL WHEN {left} = {right} THEN 1.0 ELSE 0.0 END"


def _block_key(column: str, how: str) -> str:
    if how == "first_letter":
        return f"nullif(left({_text_key(column)}, 1), '')"
    return column


def _source(ctx: DatasetContext, the_plan: Plan, where: str) -> str:
    """Each record numbered, with its fields ready to compare and its grouping."""
    keys = "".join(f", {_key(item)} AS __f{index}" for index, item in enumerate(the_plan.fields))
    blocks = "".join(
        f", {_block_key(column, how)} AS __b{index}"
        for index, (column, how) in enumerate(the_plan.blocks)
    )
    sql = (
        f"SELECT *, file_row_number AS __row{keys}{blocks} "
        f"FROM read_parquet({_quote_path(ctx.parquet_path)}, file_row_number = true)"
    )
    return f"{sql} WHERE {where}" if where else sql


def candidate_pairs(ctx: DatasetContext, the_plan: Plan, where: str, params: list[Any]) -> int:
    """How many pairs a run would compare, before comparing any."""
    source = _source(ctx, the_plan, where)
    if not the_plan.blocks:
        _, rows = run_sql(f"SELECT COUNT(*) FROM ({source}) s", params)
        count = int(rows[0][0]) if rows else 0
        return count * (count - 1) // 2
    keys = ", ".join(f"__b{index}" for index in range(len(the_plan.blocks)))
    present = " AND ".join(f"__b{index} IS NOT NULL" for index in range(len(the_plan.blocks)))
    _, rows = run_sql(
        f"SELECT COALESCE(SUM(n * (n - 1) // 2), 0) FROM ("
        f"SELECT COUNT(*) AS n FROM ({source}) s WHERE {present} GROUP BY {keys}) g",
        params,
    )
    return int(rows[0][0]) if rows else 0


def pair_ctes(ctx: DatasetContext, the_plan: Plan, where: str) -> str:
    """The pairs at least as alike as the rule asks, as CTEs to put after a WITH.

    `src` is every record, numbered, and `pairs` is (__left, __right,
    __similarity) - both named so a caller can join each side of a pair back
    to its record.
    """
    on = ["a.__row < b.__row"] + [
        f"a.__b{index} = b.__b{index}" for index in range(len(the_plan.blocks))
    ]
    scores = ", ".join(
        f"{_alike(item, f'a.__f{index}', f'b.__f{index}')} AS __s{index}"
        for index, item in enumerate(the_plan.fields)
    )
    weighted = " + ".join(
        f"{item.weight!r} * COALESCE(__s{index}, 0)" for index, item in enumerate(the_plan.fields)
    )
    seen = " + ".join(
        f"{item.weight!r} * CAST(__s{index} IS NOT NULL AS INTEGER)"
        for index, item in enumerate(the_plan.fields)
    )
    total = sum(item.weight for item in the_plan.fields)
    return (
        f"src AS ({_source(ctx, the_plan, where)}), "
        f"scored AS (SELECT a.__row AS __left, b.__row AS __right, {scores} "
        f"FROM src a JOIN src b ON {' AND '.join(on)}), "
        f"judged AS (SELECT __left, __right, ({weighted}) / NULLIF({seen}, 0) AS __similarity, "
        f"({seen}) AS __seen FROM scored), "
        f"pairs AS (SELECT __left, __right, __similarity FROM judged "
        f"WHERE __seen >= {total * MIN_COVERAGE!r} AND __similarity >= {the_plan.similarity!r})"
    )


def refuse_if_too_many(pairs: int, the_plan: Plan) -> None:
    if pairs <= MAX_PAIRS:
        return
    advice = (
        "Compare within a smaller group as well"
        if the_plan.blocks
        else "Compare only records that share something"
    )
    raise QueryError(
        f"This would compare {pairs:,} pairs of records, more than the "
        f"{MAX_PAIRS:,} a check may. {advice} - the same enumeration area or "
        "household, or the same first letter of the surname."
    )


@dataclass
class Found:
    pairs: int
    records: int
    examples: dict[str, Any]


def find(
    ctx: DatasetContext, config: dict[str, Any], where: str, params: list[Any]
) -> tuple[Plan, Found]:
    """Run the comparison: how many pairs, how many records, and the closest pairs."""
    the_plan = plan(ctx, config)
    refuse_if_too_many(candidate_pairs(ctx, the_plan, where, params), the_plan)
    ctes = pair_ctes(ctx, the_plan, where)
    _, rows = run_sql(
        f"WITH {ctes} SELECT "
        f"(SELECT COUNT(*) FROM pairs), "
        f"(SELECT COUNT(*) FROM (SELECT __left FROM pairs UNION SELECT __right FROM pairs) r)",
        params,
    )
    count, records = (int(rows[0][0]), int(rows[0][1])) if rows else (0, 0)

    # The closest pairs, side by side, for the result to show without a second
    # trip: what each record says on every field compared, and who they are.
    names = the_plan.id_names + [item.variable for item in the_plan.fields]
    width = len(names)

    def side(alias: str) -> str:
        values = [f"{alias}.{column}" for column in the_plan.ids]
        values += [item.value(alias) for item in the_plan.fields]
        return ", ".join(f"CAST({value} AS VARCHAR)" for value in values)

    _, examples = run_sql(
        f"WITH {ctes} SELECT p.__similarity, {side('l')}, {side('r')} "
        f"FROM pairs p JOIN src l ON l.__row = p.__left JOIN src r ON r.__row = p.__right "
        f"ORDER BY p.__similarity DESC, p.__left, p.__right LIMIT {EXAMPLE_PAIRS}",
        params,
    )
    rows_out = [
        [round(float(row[0]) * 100, 1)]
        + [f"{_show(row[1 + i])} ↔ {_show(row[1 + width + i])}" for i in range(width)]
        for row in examples
    ]
    return the_plan, Found(
        pairs=count,
        records=records,
        examples={"columns": ["similarity_percent", *names], "rows": rows_out},
    )


def _show(value: Any) -> str:
    return "-" if value is None or value == "" else str(value)


def failure_sql(ctx: DatasetContext, config: dict[str, Any], where: str) -> str:
    """Both records of every pair, one row each, numbered by pair, most alike first.

    A record alike to several others appears once in each of its pairs, which is
    what lets each pair be read on its own.
    """
    the_plan = plan(ctx, config)
    helpers = ["file_row_number", "__row"] + [f"__f{i}" for i in range(len(the_plan.fields))]
    helpers += [f"__b{i}" for i in range(len(the_plan.blocks))]
    # What tells the records apart and what they were compared on, first, so a
    # pair is read across two rows without looking for it; then the rest.
    compared = [column for item in the_plan.fields for column in item.columns]
    first = list(dict.fromkeys(the_plan.ids + compared))
    return (
        f"WITH {pair_ctes(ctx, the_plan, where)}, "
        f"ranked AS (SELECT row_number() OVER (ORDER BY __similarity DESC, __left, __right) "
        f"AS __pair, * FROM pairs), "
        f"sides AS (SELECT __pair, __similarity, __left AS __member FROM ranked "
        f"UNION ALL SELECT __pair, __similarity, __right FROM ranked) "
        f"SELECT sides.__pair AS likely_duplicate_pair, "
        f"round(sides.__similarity * 100, 1) AS similarity_percent, "
        f"{''.join(f'src.{column}, ' for column in first)}"
        f"src.* EXCLUDE ({', '.join(helpers + first)}) "
        f"FROM sides JOIN src ON src.__row = sides.__member"
    )


"""Stata expressions, translated to SQL that can only say what it is allowed to.

An expression typed into the command box reaches the database, so none of it is
passed through: it is tokenised, every name in it has to be a variable of the
dataset being worked on, every function has to be one of a listed few, and the
SQL is built from the tokens rather than from the text. What cannot be
recognised is refused with a message naming the piece that was not understood,
which is also what makes a typo readable rather than a database error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Stata writes what SQL writes differently. Order matters: the two-character
# operators have to be matched before their first character is.
OPERATORS: list[tuple[str, str]] = [
    ("==", "="),
    ("~=", "<>"),
    ("!=", "<>"),
    (">=", ">="),
    ("<=", "<="),
    ("&", " AND "),
    ("|", " OR "),
    ("!", " NOT "),
    ("~", " NOT "),
    ("^", "^"),
    ("+", "+"),
    ("-", "-"),
    ("*", "*"),
    ("/", "/"),
    (">", ">"),
    ("<", "<"),
    ("=", "="),
]

# Stata name -> SQL name. Everything else is refused; a function that reaches
# the database unlisted is a function nobody checked the arguments of.
FUNCTIONS: dict[str, str] = {
    "abs": "abs",
    "ceil": "ceiling",
    "exp": "exp",
    "floor": "floor",
    "int": "trunc",
    "ln": "ln",
    "log": "ln",
    "log10": "log10",
    "round": "round",
    "sqrt": "sqrt",
    "max": "greatest",
    "min": "least",
    "length": "length",
    "strlen": "length",
    "lower": "lower",
    "upper": "upper",
    "strlower": "lower",
    "strupper": "upper",
    "trim": "trim",
    "strtrim": "trim",
    "substr": "substring",
    "year": "year",
    "month": "month",
    "day": "day",
    "mod": "mod",
}

# These read as functions in Stata but are not function calls in SQL.
SPECIAL = {"missing", "mi", "inlist", "inrange", "cond", "string", "real"}

TOKEN = re.compile(
    r"""
    (?P<string>"[^"]*")
  | (?P<number>\d+\.\d*|\.\d+|\d+)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>==|~=|!=|>=|<=|[-+*/^&|!~<>=(),])
  | (?P<dot>\.)
  | (?P<space>\s+)
    """,
    re.VERBOSE,
)


class ExpressionError(ValueError):
    """The expression says something this cannot translate."""


@dataclass
class Token:
    kind: str
    text: str


def tokenize(expression: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    while position < len(expression):
        match = TOKEN.match(expression, position)
        if match is None:
            raise ExpressionError(
                f"Cannot read '{expression[position:position + 12]}' in the expression"
            )
        position = match.end()
        kind = match.lastgroup or ""
        if kind == "space":
            continue
        tokens.append(Token(kind, match.group()))
    return tokens


def translate(expression: str, columns: set[str], quote: object) -> str:
    """Turn a Stata expression into SQL over the given columns.

    `quote` is the identifier quoter, passed in so this module stays free of
    the query engine and can be tested on its own.
    """
    tokens = tokenize(expression)
    if not tokens:
        raise ExpressionError("The expression is empty")

    lower = {name.lower(): name for name in columns}
    out: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]

        if token.kind == "string":
            # Re-emitted rather than pasted: a quote inside it is doubled, so
            # the literal cannot end early and become SQL of its own.
            out.append("'" + token.text[1:-1].replace("'", "''") + "'")
        elif token.kind == "number":
            out.append(token.text)
        elif token.kind == "dot":
            # Stata's missing value. Comparisons against it are rewritten below.
            out.append("NULL")
        elif token.kind == "op":
            out.append(_operator(token.text))
        elif token.kind == "name":
            index, sql = _name(tokens, index, lower, quote)
            out.append(sql)
        index += 1

    sql = "".join(out)
    return _fix_null_comparisons(sql)


def _operator(text: str) -> str:
    for stata, replacement in OPERATORS:
        if text == stata:
            return replacement
    if text in "(),":
        return text
    raise ExpressionError(f"'{text}' is not an operator this understands")


def _name(
    tokens: list[Token], index: int, columns: dict[str, str], quote: object
) -> tuple[int, str]:
    """Resolve a bare name: a function call, a variable, or a keyword."""
    name = tokens[index].text
    key = name.lower()
    is_call = index + 1 < len(tokens) and tokens[index + 1].text == "("

    if is_call and key in SPECIAL:
        return _special(tokens, index, columns, quote)
    if is_call:
        if key not in FUNCTIONS:
            raise ExpressionError(
                f"'{name}' is not a function this understands. "
                f"Allowed: {', '.join(sorted(set(FUNCTIONS) | SPECIAL))}"
            )
        return index, FUNCTIONS[key]
    if key in ("_n", "_N"):
        raise ExpressionError(
            "_n and _N are not available here; use egen with by() for row numbers"
        )
    if key in columns:
        return index, str(quote(columns[key]))  # type: ignore[operator]
    raise ExpressionError(f"'{name}' is not a variable in this dataset")


def _special(
    tokens: list[Token], index: int, columns: dict[str, str], quote: object
) -> tuple[int, str]:
    """The few that look like calls but compile to something else."""
    name = tokens[index].text.lower()
    args, end = _arguments(tokens, index + 1)
    rendered = [translate(arg, set(columns.values()), quote) for arg in args]

    if name in ("missing", "mi"):
        if len(rendered) != 1:
            raise ExpressionError("missing() takes one variable")
        return end, f"({rendered[0]} IS NULL)"
    if name == "inlist":
        if len(rendered) < 2:
            raise ExpressionError("inlist() takes a variable and at least one value")
        return end, f"({rendered[0]} IN ({', '.join(rendered[1:])}))"
    if name == "inrange":
        if len(rendered) != 3:
            raise ExpressionError("inrange() takes a variable, a low and a high value")
        return end, f"({rendered[0]} BETWEEN {rendered[1]} AND {rendered[2]})"
    if name == "string":
        if len(rendered) != 1:
            raise ExpressionError("string() takes one value")
        return end, f"CAST({rendered[0]} AS VARCHAR)"
    if name == "real":
        if len(rendered) != 1:
            raise ExpressionError("real() takes one value")
        # try_cast rather than cast: a value that is not a number becomes
        # missing, which is what Stata's real() does, instead of an error that
        # stops the whole command.
        return end, f"TRY_CAST({rendered[0]} AS DOUBLE)"
    if name == "cond":
        if len(rendered) not in (2, 3):
            raise ExpressionError("cond() takes a condition, a value, and optionally another")
        otherwise = rendered[2] if len(rendered) == 3 else "NULL"
        return end, f"(CASE WHEN {rendered[0]} THEN {rendered[1]} ELSE {otherwise} END)"
    raise ExpressionError(f"'{name}' is not supported")


def _arguments(tokens: list[Token], open_index: int) -> tuple[list[str], int]:
    """Split a bracketed argument list, respecting nested brackets."""
    if open_index >= len(tokens) or tokens[open_index].text != "(":
        raise ExpressionError("Expected '(' after the function name")
    depth = 0
    args: list[str] = []
    current: list[str] = []
    index = open_index
    while index < len(tokens):
        text = tokens[index].text
        if text == "(":
            depth += 1
            if depth == 1:
                index += 1
                continue
        elif text == ")":
            depth -= 1
            if depth == 0:
                args.append(" ".join(current).strip())
                return [a for a in args if a], index
        elif text == "," and depth == 1:
            args.append(" ".join(current).strip())
            current = []
            index += 1
            continue
        current.append(text if tokens[index].kind != "string" else tokens[index].text)
        index += 1
    raise ExpressionError("A bracket is not closed")


def _fix_null_comparisons(sql: str) -> str:
    """`x = NULL` is never true in SQL; in Stata it is how missing is tested."""
    sql = re.sub(r"(?i)\s*<>\s*NULL", " IS NOT NULL", sql)
    sql = re.sub(r"(?i)\s*=\s*NULL", " IS NULL", sql)
    return sql

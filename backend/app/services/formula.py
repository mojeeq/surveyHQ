"""Arithmetic over an indicator's named parts.

An indicator used to be one aggregate with one filter, plus a switch saying
"and divide that by the row count". That answers "how many" and "what share of
everything", and stops there. The questions a survey office actually asks are
ratios between two different things: refusals per completed interview, the
share of households with electricity among those answering, the gap between
visits and interviews. Each of those is two or three counted things combined
by arithmetic, and none of them is a share of all the rows.

So an indicator can instead be a handful of named parts - each one an
aggregate over its own filter - and an expression combining them:

    done   = count where status = done
    issued = count
    expression: done / issued * 100

Which is a tiny language, and this is all of it: numbers, part names,
``+ - * /``, parentheses and a leading minus. No names but the parts, no
function calls, no attribute access, nothing that reaches out of the
expression. It is parsed into a tree of tuples and walked, rather than handed
to eval, because the expression is typed by a user and stored - eval would
make every indicator a way to run code on the server.

Division by zero is not an error here. A province where nothing was issued has
no completion rate; the honest answer is that there is no value, which is what
a blank tile says, rather than a crash or an infinity drawn as a bar.
"""

from __future__ import annotations

import re
from typing import Any

#: A part name: what somebody would call a variable, and nothing else.
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NUMBER = re.compile(r"\d+(?:\.\d+)?|\.\d+")


class FormulaError(ValueError):
    """A formula that cannot be read, with where it stopped making sense."""


#: As long as a formula is allowed to be, and as deeply as it may nest.
#:
#: Neither is a design limit - no rate anybody writes comes near either - they
#: are there because the text is typed by a user and parsed by a function that
#: calls itself: five hundred opening brackets would otherwise be a stack
#: overflow rather than a message saying the formula is too deep.
MAX_LENGTH = 500
MAX_DEPTH = 40


Node = tuple[str, Any, Any]


def _tokenize(text: str) -> list[tuple[str, str, int]]:
    tokens: list[tuple[str, str, int]] = []
    at = 0
    while at < len(text):
        char = text[at]
        if char.isspace():
            at += 1
            continue
        if char in "+-*/()":
            tokens.append((char, char, at))
            at += 1
            continue
        found = NUMBER.match(text, at)
        if found:
            tokens.append(("number", found.group(0), at))
            at = found.end()
            continue
        found = NAME.match(text, at)
        if found:
            tokens.append(("name", found.group(0), at))
            at = found.end()
            continue
        raise FormulaError(f"{char!r} does not mean anything here (position {at + 1})")
    return tokens


class _Reader:
    """Plain recursive descent: the grammar is four lines, so is this."""

    def __init__(self, tokens: list[tuple[str, str, int]], text: str) -> None:
        self.tokens = tokens
        self.text = text
        self.at = 0
        self.depth = 0

    def peek(self) -> tuple[str, str, int] | None:
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self) -> tuple[str, str, int]:
        token = self.peek()
        if token is None:
            raise FormulaError("the formula stops in the middle of a sum")
        self.at += 1
        return token

    def expression(self) -> Node:
        left = self.term()
        while (token := self.peek()) and token[0] in "+-":
            self.take()
            left = (token[0], left, self.term())
        return left

    def term(self) -> Node:
        left = self.factor()
        while (token := self.peek()) and token[0] in "*/":
            self.take()
            left = (token[0], left, self.factor())
        return left

    def factor(self) -> Node:
        token = self.peek()
        if token and token[0] in "+-":
            self.take()
            inner = self.factor()
            return ("-", ("number", 0.0, None), inner) if token[0] == "-" else inner
        return self.primary()

    def primary(self) -> Node:
        kind, value, where = self.take()
        if kind == "number":
            return ("number", float(value), None)
        if kind == "name":
            return ("name", value, None)
        if kind == "(":
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise FormulaError("the formula nests more deeply than it is allowed to")
            inside = self.expression()
            self.depth -= 1
            closing = self.peek()
            if closing is None or closing[0] != ")":
                raise FormulaError("a bracket was opened and never closed")
            self.take()
            return inside
        raise FormulaError(f"{value!r} cannot start a sum (position {where + 1})")


def parse(expression: str) -> Node:
    """The expression as a tree, or a readable complaint about why not."""
    text = (expression or "").strip()
    if not text:
        raise FormulaError("the formula is empty")
    if len(text) > MAX_LENGTH:
        raise FormulaError(f"the formula is longer than {MAX_LENGTH} characters")
    reader = _Reader(_tokenize(text), text)
    tree = reader.expression()
    left = reader.peek()
    if left is not None:
        raise FormulaError(
            f"{left[1]!r} is left over at the end (position {left[2] + 1})"
        )
    return tree


def names_in(expression: str) -> set[str]:
    """Every part the expression asks for, so a missing one is caught on save."""
    return {value for kind, value, _ in _tokenize(expression or "") if kind == "name"}


def evaluate(tree: Node, parts: dict[str, float | None]) -> float | None:
    """The tree against one set of part values.

    Nothing here raises: a part with no value, and a division by zero, both
    give no value rather than an error, and that travels up through the rest
    of the sum. A tile with a blank number says "nothing to report here",
    which is true, where a failed indicator says the definition is broken,
    which would not be.
    """
    kind, left, right = tree
    if kind == "number":
        return float(left)
    if kind == "name":
        value = parts.get(left)
        return None if value is None else float(value)
    one = evaluate(left, parts)
    other = evaluate(right, parts)
    if one is None or other is None:
        return None
    if kind == "+":
        return one + other
    if kind == "-":
        return one - other
    if kind == "*":
        return one * other
    if kind == "/":
        return None if other == 0 else one / other
    raise FormulaError(f"unknown operator {kind!r}")  # pragma: no cover - unreachable


def compute(expression: str, parts: dict[str, float | None]) -> float | None:
    """Parse and evaluate in one go, for a caller holding both."""
    return evaluate(parse(expression), parts)

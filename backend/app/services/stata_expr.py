"""Stata expressions, translated to SQL that can only say what it is allowed to.

An expression typed into the command box reaches the database, so none of it is
passed through: it is tokenised, parsed, every name in it has to be a variable
of the dataset being worked on, every function has to be one of a listed few,
and the SQL is built from the parse rather than from the text. What cannot be
recognised is refused with a message naming the piece that was not understood,
which is also what makes a typo readable rather than a database error.

Missing values are the whole reason this parses rather than rewrites. Stata and
SQL disagree about them, and the disagreement is silent:

    replace ilo_lfs_emp = 3 if !inlist(ilo_lfs_emp, 1, 2)

is how every recode cascade ends - "everything not yet classified" - and the
variable is still missing for exactly the rows it is meant to catch. SQL answers
`NULL IN (1, 2)` with NULL, `NOT NULL` with NULL, and a WHERE clause reads NULL
as no. The command reports success, changes nothing, and leaves a labour force
statistic with a hole in it.

Stata instead treats numeric missing as **larger than any number**. That one
rule gives all of its behaviour:

    . > 65   is true        . == .   is true        inlist(., 1, 2)  is false
    . < 65   is false       . != .   is false       inrange(., 1, 5) is false
    . != 1   is true        . >= .   is true        !inlist(., 1, 2) is true

So every comparison here is emitted NULL-aware, in the one helper `_compare`,
and `inlist`, `inrange` and `!` are defined in terms of it rather than given
rules of their own. Being faithful means inheriting Stata's traps too: after
`gen adult = age >= 18`, somebody whose age was never recorded is an adult, in
Stata and here alike. That is the point - a figure this platform reports should
be the figure the do-file produced.

Two places the rule deliberately does not reach:

- arithmetic, where missing propagates as missing, because `. + 1` is missing in
  Stata and NULL + 1 is NULL in SQL, and they already agree; and
- `missing(x)`, which asks the question directly and must see the NULL.

Text is ordered the other way. Stata's string missing is the empty string, and
"" sorts below every other string, so a text comparison coalesces to '' instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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

#: Of the listed functions, the ones that hand back text. Everything else is a
#: quantity, which is what decides whether a comparison orders missing high
#: (numbers) or low (strings).
TEXT_FUNCTIONS = {
    "lower",
    "upper",
    "strlower",
    "strupper",
    "trim",
    "strtrim",
    "substr",
    "string",
}

NUMBER, TEXT, BOOL = "number", "text", "bool"

COMPARISONS = {"==", "=", "!=", "~=", ">", ">=", "<", "<="}

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


@dataclass(frozen=True)
class Value:
    """A translated piece of an expression, and what sort of thing it holds.

    The kind travels with the SQL because the missing rule depends on it: a
    comparison of numbers orders missing above everything, a comparison of text
    orders it below, and a value that is already a condition needs no coercion
    to be used as one.
    """

    sql: str
    kind: str

    #: A comparison against this value can meet a NULL. A literal cannot, which
    #: is what keeps `1 == 1` from being wrapped in NULL tests nobody needs.
    nullable: bool = True


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


def translate(expression: str, columns: object, quote: object) -> str:
    """Turn a Stata expression into SQL over the given columns.

    `columns` is the variables the expression may name. Pass a mapping of name
    to kind - "number" or "text" - and comparisons order missing the way Stata
    orders it for that kind. A bare set of names is accepted for callers that
    have no types to hand, and reads every column as a number.

    `quote` is the identifier quoter, passed in so this module stays free of
    the query engine and can be tested on its own.
    """
    tokens = tokenize(expression)
    if not tokens:
        raise ExpressionError("The expression is empty")

    parser = _Parser(tokens, _kinds(columns), _spellings(columns), quote)
    value = parser.expression()
    if not parser.done:
        raise ExpressionError(
            f"'{parser.peek_text()}' is unexpected here in the expression"
        )
    return value.sql


def _kinds(columns: object) -> dict[str, str]:
    """Column name, lowercased, to the kind of thing it holds."""
    if isinstance(columns, dict):
        return {
            str(name).lower(): (TEXT if str(kind) == TEXT else NUMBER)
            for name, kind in columns.items()
        }
    return {str(name).lower(): NUMBER for name in columns}  # type: ignore[union-attr]


def _spellings(columns: object) -> dict[str, str]:
    """Lowercased name back to the name as the dataset spells it.

    Stata is case-insensitive about variable names and the stored column is
    not, so `AGE` has to be quoted as whatever the file calls it.
    """
    names = columns.keys() if isinstance(columns, dict) else columns
    return {str(name).lower(): str(name) for name in names}  # type: ignore[union-attr]


# --- The missing rule --------------------------------------------------------


def _missing_test(value: Value) -> str:
    """How to ask whether this value is Stata-missing.

    A number is missing when the column is NULL. Text is missing when it is the
    empty string, which Stata writes as "" and a file may store either way, so
    both count.
    """
    if value.kind == TEXT:
        return f"({value.sql} IS NULL OR {value.sql} = '')"
    return f"{value.sql} IS NULL"


def _compare(operator: str, left: Value, right: Value) -> Value:
    """One comparison, ordering missing the way Stata orders it.

    Written out per operator rather than by coalescing to an infinity, so that
    a wide integer keeps its exact value: casting a BIGINT id to DOUBLE to make
    room for a sentinel would quietly round the comparison it was there to make.

    Each operator becomes the boolean form of "missing is the largest value":

        a >  b   is   b is present and (a is missing or a > b)
        a >= b   is   a is missing or (b is present and a >= b)
        a <  b   is   a is present and (b is missing or a < b)
        a <= b   is   b is missing or (a is present and a <= b)

    and equality is `IS NOT DISTINCT FROM`, which is already the rule Stata
    wants: two missings are equal, a missing and a number are not. A side that
    cannot be missing - a literal, another comparison - has its test dropped,
    so `age > 65` stays legible rather than growing branches that never run.
    """
    if left.kind == TEXT or right.kind == TEXT:
        return _compare_text(operator, left, right)

    a, b = left.sql, right.sql
    equality = operator in ("==", "=", "!=", "~=")
    negated = operator in ("!=", "~=")

    # `x == .` and `x != .` are how Stata asks whether something is missing,
    # and saying so plainly beats comparing against a NULL literal.
    if equality and right.sql == "NULL" and right.kind == NUMBER:
        return Value(f"({_missing_test(left)})" if not negated else
                     f"(NOT ({_missing_test(left)}))", BOOL, nullable=False)
    if equality and left.sql == "NULL" and left.kind == NUMBER:
        return Value(f"({_missing_test(right)})" if not negated else
                     f"(NOT ({_missing_test(right)}))", BOOL, nullable=False)

    if not left.nullable and not right.nullable:
        # Neither side can be missing, so the plain comparison is the whole of
        # it. This is `1 == 1`, and `age > 65` once the column is known to have
        # no missing to order.
        return Value(f"({a}{_plain(operator)}{b})", BOOL, nullable=False)

    if equality:
        how = "IS DISTINCT FROM" if negated else "IS NOT DISTINCT FROM"
        return Value(f"({a} {how} {b})", BOOL, nullable=False)

    present, absent = "IS NOT NULL", "IS NULL"
    if operator == ">":
        parts = [f"{b} {present}", f"({a} {absent} OR {a}>{b})"]
        if not right.nullable:
            parts = [f"({a} {absent} OR {a}>{b})"]
        elif not left.nullable:
            parts = [f"{b} {present}", f"{a}>{b}"]
    elif operator == ">=":
        if not left.nullable:
            parts = [f"{b} {present}", f"{a}>={b}"]
        elif not right.nullable:
            parts = [f"({a} {absent} OR {a}>={b})"]
        else:
            return Value(
                f"({a} {absent} OR ({b} {present} AND {a}>={b}))", BOOL, nullable=False
            )
    elif operator == "<":
        parts = [f"{a} {present}", f"({b} {absent} OR {a}<{b})"]
        if not left.nullable:
            parts = [f"({b} {absent} OR {a}<{b})"]
        elif not right.nullable:
            parts = [f"{a} {present}", f"{a}<{b}"]
    elif operator == "<=":
        if not right.nullable:
            parts = [f"{a} {present}", f"{a}<={b}"]
        elif not left.nullable:
            parts = [f"({b} {absent} OR {a}<={b})"]
        else:
            return Value(
                f"({b} {absent} OR ({a} {present} AND {a}<={b}))", BOOL, nullable=False
            )
    else:  # pragma: no cover - the caller only passes comparisons
        raise ExpressionError(f"'{operator}' is not a comparison")
    return Value(f"({' AND '.join(parts)})", BOOL, nullable=False)


def _compare_text(operator: str, left: Value, right: Value) -> Value:
    """A comparison where either side is text.

    Stata's string missing is "", and "" sorts below every other string, so
    coalescing to it gives Stata's order directly. No sentinel and no rounding
    to worry about, because strings have no width to lose.
    """
    a = f"COALESCE({left.sql}, '')" if left.nullable else left.sql
    b = f"COALESCE({right.sql}, '')" if right.nullable else right.sql
    return Value(f"({a}{_plain(operator)}{b})", BOOL, nullable=False)


def _plain(operator: str) -> str:
    return {"==": "=", "=": "=", "!=": "<>", "~=": "<>"}.get(operator, operator)


def _truthy(value: Value) -> str:
    """This value used as a condition, as Stata would read it.

    Stata has no true or false: a condition is a number, zero is no and
    anything else is yes. Missing is not zero, so missing is yes - which is why
    `if x` and `if x != 0` agree in Stata and would not if NULL were simply
    dropped.
    """
    if value.kind == BOOL:
        return value.sql
    if value.kind == TEXT:
        return f"(COALESCE({value.sql}, '') <> '')"
    if not value.nullable:
        return f"({value.sql} <> 0)"
    return f"({value.sql} IS NULL OR {value.sql} <> 0)"


# --- The parser --------------------------------------------------------------


class _Parser:
    """Stata's expression grammar, by precedence.

    Lowest to highest: `|`, `&`, the comparisons, `+ -`, `* /`, `^`, then the
    unary operators and the primaries. `!` sits with unary minus and binds to
    what follows it, which is Stata's own precedence: `!inlist(x, 1, 2)` negates
    the inlist, and `!x == 1` compares `!x` against 1.
    """

    def __init__(
        self,
        tokens: list[Token],
        kinds: dict[str, str],
        spellings: dict[str, str],
        quote: object,
    ):
        self.tokens = tokens
        self.kinds = kinds
        self.spellings = spellings
        self.quote = quote
        self.at = 0

    # --- the token stream ---

    @property
    def done(self) -> bool:
        return self.at >= len(self.tokens)

    def peek(self) -> str:
        return "" if self.done else self.tokens[self.at].text

    def peek_text(self) -> str:
        return self.peek() or "the end of the expression"

    def kind(self) -> str:
        return "" if self.done else self.tokens[self.at].kind

    def take(self) -> Token:
        token = self.tokens[self.at]
        self.at += 1
        return token

    def eat(self, text: str) -> bool:
        if self.peek() == text:
            self.at += 1
            return True
        return False

    # --- the grammar ---

    def expression(self) -> Value:
        return self._or()

    def _or(self) -> Value:
        left = self._and()
        while self.peek() == "|":
            self.take()
            right = self._and()
            left = Value(f"({_truthy(left)} OR {_truthy(right)})", BOOL, nullable=False)
        return left

    def _and(self) -> Value:
        left = self._comparison()
        while self.peek() == "&":
            self.take()
            right = self._comparison()
            left = Value(f"({_truthy(left)} AND {_truthy(right)})", BOOL, nullable=False)
        return left

    def _comparison(self) -> Value:
        left = self._additive()
        while self.peek() in COMPARISONS:
            operator = self.take().text
            right = self._additive()
            left = _compare(operator, left, right)
        return left

    def _additive(self) -> Value:
        left = self._multiplicative()
        while self.peek() in ("+", "-"):
            operator = self.take().text
            right = self._multiplicative()
            left = self._arithmetic(operator, left, right)
        return left

    def _multiplicative(self) -> Value:
        left = self._unary()
        while self.peek() in ("*", "/"):
            operator = self.take().text
            right = self._unary()
            left = self._arithmetic(operator, left, right)
        return left

    def _power(self) -> Value:
        """Exponentiation, which binds tighter than the sign in front of it.

        `-age^2` is `-(age^2)` in Stata and not `(-age)^2`, so the sign is
        applied by `_unary` after this has run rather than being swept into the
        base. Left to right among themselves, as Stata evaluates operators of
        equal precedence, so `2^3^2` is 64 and not 512 - which is why the
        exponent is parsed as a signed primary that cannot itself take a `^`.
        """
        left = self._primary()
        while self.peek() == "^":
            self.take()
            right = self._signed_primary()
            left = Value(f"({_as_number(left)}^{_as_number(right)})", NUMBER)
        return left

    def _signed_primary(self) -> Value:
        """An exponent: a primary, possibly signed, as in `2^-1`."""
        if self.peek() == "-":
            self.take()
            return Value(f"(-{_as_number(self._signed_primary())})", NUMBER)
        if self.peek() == "+":
            self.take()
            return self._signed_primary()
        return self._primary()

    def _arithmetic(self, operator: str, left: Value, right: Value) -> Value:
        """Arithmetic, where missing is left to propagate.

        `. + 1` is missing in Stata and NULL + 1 is NULL in SQL, so this is the
        one place the two already agree and the missing rule stays out of it.
        A text operand would be a silent cast, so it is refused instead.
        """
        if operator == "+" and left.kind == TEXT and right.kind == TEXT:
            # Stata joins two strings with +, and only two strings.
            return Value(f"({_as_text(left)}||{_as_text(right)})", TEXT)
        for side in (left, right):
            if side.kind == TEXT:
                # Stata calls this a type mismatch rather than guessing, and so
                # does this: quietly turning `name + age` into "Alice30" is the
                # sort of silent coercion the rest of this module exists to
                # avoid. Say which way to resolve it instead.
                raise ExpressionError(
                    f"'{operator}' needs numbers, and one side of it is text. "
                    "Convert it first, with string(...) to join as text or "
                    "real(...) to use it as a number."
                )
        return Value(f"({_as_number(left)}{operator}{_as_number(right)})", NUMBER)

    def _unary(self) -> Value:
        if self.peek() in ("!", "~"):
            self.take()
            inner = self._unary()
            return Value(f"(NOT {_truthy(inner)})", BOOL, nullable=False)
        if self.peek() == "-":
            self.take()
            inner = self._unary()
            return Value(f"(-{_as_number(inner)})", NUMBER)
        if self.peek() == "+":
            self.take()
            return self._unary()
        return self._power()

    def _primary(self) -> Value:
        if self.done:
            raise ExpressionError("The expression stops in the middle")

        if self.eat("("):
            inner = self.expression()
            if not self.eat(")"):
                raise ExpressionError("A bracket is not closed")
            return Value(f"({inner.sql})", inner.kind, inner.nullable)

        token = self.take()

        if token.kind == "string":
            # Re-emitted rather than pasted: a quote inside it is doubled, so
            # the literal cannot end early and become SQL of its own.
            body = token.text[1:-1].replace("'", "''")
            return Value(f"'{body}'", TEXT, nullable=False)
        if token.kind == "number":
            return Value(token.text, NUMBER, nullable=False)
        if token.kind == "dot":
            # Stata's missing. It is a value, and a comparison against it is a
            # comparison against a value that is always missing.
            return Value("NULL", NUMBER)
        if token.kind == "name":
            return self._named(token)
        raise ExpressionError(f"'{token.text}' is unexpected here in the expression")

    def _named(self, token: Token) -> Value:
        """A bare name: a function call, a variable, or a refusal."""
        name = token.text
        key = name.lower()
        calling = self.peek() == "("

        if calling and key in SPECIAL:
            return self._special(key)
        if calling:
            if key not in FUNCTIONS:
                raise ExpressionError(
                    f"'{name}' is not a function this understands. "
                    f"Allowed: {', '.join(sorted(set(FUNCTIONS) | SPECIAL))}"
                )
            args = self._arguments()
            if not args:
                raise ExpressionError(f"{name}() needs at least one value")
            kind = TEXT if key in TEXT_FUNCTIONS else NUMBER
            inside = ", ".join(one.sql for one in args)
            return Value(f"{FUNCTIONS[key]}({inside})", kind)
        if key in ("_n", "_N"):
            raise ExpressionError(
                "_n and _N are not available here; use egen with by() for row numbers"
            )
        if key in self.kinds:
            stored = self.spellings[key]
            return Value(str(self.quote(stored)), self.kinds[key])  # type: ignore[operator]
        raise ExpressionError(f"'{name}' is not a variable in this dataset")

    def _arguments(self) -> list[Value]:
        """A bracketed, comma-separated argument list."""
        if not self.eat("("):
            raise ExpressionError("Expected '(' after the function name")
        args: list[Value] = []
        if self.eat(")"):
            return args
        while True:
            args.append(self.expression())
            if self.eat(","):
                continue
            if self.eat(")"):
                return args
            raise ExpressionError("A bracket is not closed")

    def _special(self, name: str) -> Value:
        """The few that look like calls but are built out of the rules above."""
        args = self._arguments()

        if name in ("missing", "mi"):
            if len(args) != 1:
                raise ExpressionError("missing() takes one variable")
            # Asks the question directly, so it is the one place that has to see
            # the NULL rather than have it ordered.
            return Value(f"({_missing_test(args[0])})", BOOL, nullable=False)

        if name == "inlist":
            if len(args) < 2:
                raise ExpressionError("inlist() takes a variable and at least one value")
            subject, rest = args[0], args[1:]
            # Stata's own definition: equal to any of them. Built out of the
            # equality rule rather than given one, so a missing subject is not
            # in a list of numbers, and is in a list that holds a missing.
            each = [_compare("==", subject, one).sql for one in rest]
            return Value(f"({' OR '.join(each)})", BOOL, nullable=False)

        if name == "inrange":
            if len(args) != 3:
                raise ExpressionError("inrange() takes a variable, a low and a high value")
            subject, low, high = args
            # Also its definition: at least the low and at most the high. A
            # missing subject fails the upper test, so it is in no range.
            lower = _compare(">=", subject, low).sql
            upper = _compare("<=", subject, high).sql
            return Value(f"({lower} AND {upper})", BOOL, nullable=False)

        if name == "string":
            if len(args) != 1:
                raise ExpressionError("string() takes one value")
            return Value(f"CAST({args[0].sql} AS VARCHAR)", TEXT)

        if name == "real":
            if len(args) != 1:
                raise ExpressionError("real() takes one value")
            # try_cast rather than cast: a value that is not a number becomes
            # missing, which is what Stata's real() does, instead of an error
            # that stops the whole command.
            return Value(f"TRY_CAST({args[0].sql} AS DOUBLE)", NUMBER)

        if name == "cond":
            if len(args) not in (2, 3):
                raise ExpressionError(
                    "cond() takes a condition, a value, and optionally another"
                )
            otherwise = args[2].sql if len(args) == 3 else "NULL"
            kind = args[1].kind if len(args) < 3 or args[1].kind == args[2].kind else NUMBER
            return Value(
                f"(CASE WHEN {_truthy(args[0])} THEN {args[1].sql} ELSE {otherwise} END)",
                kind,
            )

        raise ExpressionError(f"'{name}' is not supported")  # pragma: no cover


def _as_number(value: Value) -> str:
    """A value where arithmetic is about to be done on it."""
    if value.kind == BOOL:
        # Stata has no boolean: a comparison is 1 or 0, and arithmetic on it is
        # arithmetic on 1 or 0.
        return f"CAST({value.sql} AS INTEGER)"
    return value.sql


def _as_text(value: Value) -> str:
    if value.kind == TEXT:
        return f"COALESCE({value.sql}, '')" if value.nullable else value.sql
    return f"COALESCE(CAST({value.sql} AS VARCHAR), '')"

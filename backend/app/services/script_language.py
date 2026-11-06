"""The script language, described for the editor that writes it.

The editor colours a script and offers what can come next - a command at the
start of a line, a dataset after `use`, an option after the comma, a function
inside an expression. Every one of those lists is a fact about the engine, and
a copy of it kept in the browser would drift the way the engine's own error
message once did, when it listed nine commands and left out four that worked.
An editor that offers an option the command then refuses is worse than one
that offers nothing.

So the lists are read off the engine's tables here: the verbs and their
spellings from `stata.verbs()`, the options from `stata.OPTIONS`, the functions
from `stata_expr`, the egen and collapse names from theirs. What the tables do
not carry - a line saying what each thing is for and how it is written - is
written out beside them, and a test holds the two to the same names, so a
command or function added to the engine without a line here fails the build
rather than going unoffered.
"""

from __future__ import annotations

from typing import Any

from app.services import stata, stata_expr

# How each command is written and what it is for. Keyed by the name
# `stata.verb_names()` gives it; its other spellings come from the engine.
COMMANDS: dict[str, tuple[str, str]] = {
    "use": ("use <dataset>", "Load a copy of one of the project's datasets."),
    "save": (
        'save as "<name>" | save, replace',
        "Write what is in memory out as a new dataset, or back over the one it came from.",
    ),
    "merge": (
        "merge 1:1|m:1|1:m <keys> using <dataset> [, keep() keepusing() nogen]",
        "Add another dataset's variables, matched on keys.",
    ),
    "append": ("append using <dataset>", "Put another dataset's rows under these."),
    "collapse": (
        "collapse (stat) <variables> [(stat) <variables>...] [, by(<variables>)]",
        "One row per group, with a statistic of each variable.",
    ),
    "contract": ("contract <variables>", "How many rows each combination has, in _freq."),
    "gen": (
        "gen <name> = <expression> [if <condition>]",
        "Make a new variable.",
    ),
    "replace": (
        "replace <name> = <expression> [if <condition>]",
        "Change the values of a variable that exists.",
    ),
    "egen": (
        "egen <name> = <function>(<arguments>) [, by(<variables>)]",
        "Make a variable from a whole column or a whole row: totals, means, counts, groups.",
    ),
    "label": (
        'label variable <name> "<text>" | label define <set> 1 "Yes" 2 "No" '
        "| label values <name> <set>",
        "Name a variable, or give its values words.",
    ),
    "rename": ("rename <old> <new>", "Give a variable another name."),
    "drop": ("drop <variables> | drop if <condition>", "Remove variables, or rows."),
    "keep": ("keep <variables> | keep if <condition>", "Keep only these variables, or rows."),
    "destring": (
        "destring [<variables>], replace | generate(<names>) "
        '[force ignore("<chars>") percent dpcomma]',
        "Turn text that holds numbers into numbers.",
    ),
    "recode": (
        "recode <variables> (<old> = <new>) [(...)...] [if <condition>] "
        "[, generate(<names>) prefix(<text>)]",
        "Turn old values into new ones by rules: (1 2 = 0) (3/5 = 1) (else = .).",
    ),
    "duplicates": (
        "duplicates report|tag|drop [<variables>] [, generate(<name>) force]",
        "Find rows that repeat, mark them, or keep only the first of each.",
    ),
    "reshape": (
        "reshape long|wide <stubs>, i(<ids>) j(<name>) [string]",
        "Turn inc2019 inc2020 into rows of inc by year, or back into columns.",
    ),
    "tostring": (
        "tostring <variables>, replace | generate(<names>)",
        "Write numbers as text.",
    ),
    "encode": (
        "encode <variable>, generate(<name>) [label(<set>)]",
        "Number the values of a text variable, labelled with their text.",
    ),
    "decode": (
        "decode <variable>, generate(<name>)",
        "Write a labelled code as its label's text.",
    ),
    "sort": ("sort <variables>", "Put the rows in order of these, smallest first."),
    "gsort": ("gsort [-]<variable> ...", "Sort, with - in front of a variable for largest first."),
    "order": (
        "order <variables> [, first | last | before(<variable>) | after(<variable>)]",
        "Move variables to the front, the end, or beside another.",
    ),
    "assert": (
        "assert <expression> [if <condition>]",
        "Stop the script unless this holds on every row.",
    ),
    "count": ("count [if <condition>]", "How many rows, or how many meet a condition."),
    "summarize": (
        "summarize [<variables>] [if <condition>] [, detail]",
        "Count, mean, spread, smallest and largest of numeric variables.",
    ),
    "tabulate": (
        "tabulate <variable> [<variable>] [if <condition>] [, missing]",
        "How often each value appears, or a cross-table of two.",
    ),
    "by": (
        "by <variables>: <command>",
        "Run gen, replace, egen, keep, drop or assert within each group; _n and _N count in it.",
    ),
    "bysort": (
        "bysort <variables> [(<order>)]: <command>",
        "Sort by the groups first, then run the command within each.",
    ),
    "foreach": (
        "foreach <name> in <words> | of varlist|local|global|numlist <list> {",
        "Run the lines up to } once for each item, as `name'.",
    ),
    "forvalues": (
        "forvalues <name> = <start>/<end> | <start>(<step>)<end> {",
        "Run the lines up to } once for each number, as `name'.",
    ),
    "local": ("local <name> <text>", "Name a piece of script text, used as `name'."),
    "global": ("global <name> <text>", "Name a piece of script text, used as $name."),
}

# What each option is for, keyed by command and then by option, for the
# options in `stata.OPTIONS`. Spellings of one option share a line.
OPTION_NOTES: dict[str, dict[str, str]] = {
    "merge": {
        "keep": "Which rows survive: master, using, match.",
        "keepusing": "Only these variables from the other dataset.",
        "nogen": "Do not make _merge.",
        "nogenerate": "Do not make _merge.",
    },
    "collapse": {"by": "The variables to group by: one row per combination."},
    "destring": {
        "replace": "Convert the variables in place.",
        "generate": "Put the numbers in new variables, named here.",
        "gen": "Put the numbers in new variables, named here.",
        "g": "Put the numbers in new variables, named here.",
        "force": "Make anything that is not a number missing.",
        "percent": "Read 45% as 0.45.",
        "dpcomma": "Read a comma as the decimal point.",
        "ignore": "Characters to take out first, in quotes.",
    },
    "egen": {"by": "Work within each group of these variables."},
    "save": {"replace": "Write over a dataset that exists."},
    "recode": {
        "generate": "Put the new values in new variables, named here.",
        "gen": "Put the new values in new variables, named here.",
        "g": "Put the new values in new variables, named here.",
        "prefix": "Put the new values in new variables, named with this in front.",
    },
    "duplicates": {
        "generate": "With tag: the new variable counting each row's duplicates.",
        "gen": "With tag: the new variable counting each row's duplicates.",
        "g": "With tag: the new variable counting each row's duplicates.",
        "force": "With drop on some variables: lose what the dropped rows held.",
    },
    "reshape": {
        "i": "The variables that identify a row of the wide data.",
        "j": "The variable that holds the suffix: year in inc2019.",
        "string": "The suffixes are text, not numbers.",
    },
    "tostring": {
        "replace": "Write the text over the numbers.",
        "generate": "Put the text in new variables, named here.",
        "gen": "Put the text in new variables, named here.",
        "g": "Put the text in new variables, named here.",
        "force": "Accepted for Stata's sake; nothing is lost here without it.",
    },
    "encode": {
        "generate": "The new variable holding the codes.",
        "gen": "The new variable holding the codes.",
        "g": "The new variable holding the codes.",
        "label": "The label set to use, or make; codes already in it are kept.",
    },
    "decode": {
        "generate": "The new variable holding the text.",
        "gen": "The new variable holding the text.",
        "g": "The new variable holding the text.",
    },
    "sort": {"stable": "Always so here: rows that tie keep their order."},
    "order": {
        "first": "To the front (the default).",
        "last": "To the end.",
        "before": "Just before this variable.",
        "after": "Just after this variable.",
    },
    "summarize": {"detail": "Add the quartiles and median."},
    "tabulate": {"missing": "Count missing as a value of its own."},
}

# Options written with brackets after them, so the editor can put the cursor
# between them. The rest are words on their own.
TAKES_ARGUMENT = {
    "keep", "keepusing", "by", "generate", "gen", "g", "ignore", "prefix", "i", "j",
    "label", "before", "after",
}

# Functions, by the name the expression language takes.
FUNCTIONS: dict[str, tuple[str, str]] = {
    "abs": ("abs(x)", "The value without its sign."),
    "ceil": ("ceil(x)", "Round up to a whole number."),
    "exp": ("exp(x)", "e to the power of x."),
    "floor": ("floor(x)", "Round down to a whole number."),
    "int": ("int(x)", "The whole-number part, towards zero."),
    "ln": ("ln(x)", "Natural logarithm."),
    "log": ("log(x)", "Natural logarithm, as ln()."),
    "log10": ("log10(x)", "Logarithm to base 10."),
    "round": ("round(x[, places])", "Round to the nearest whole number, or to places."),
    "sqrt": ("sqrt(x)", "Square root."),
    "max": ("max(a, b, ...)", "The largest of the values in a row."),
    "min": ("min(a, b, ...)", "The smallest of the values in a row."),
    "length": ("length(s)", "How many characters the text has."),
    "strlen": ("strlen(s)", "How many characters the text has."),
    "lower": ("lower(s)", "The text in lower case."),
    "upper": ("upper(s)", "The text in upper case."),
    "strlower": ("strlower(s)", "The text in lower case."),
    "strupper": ("strupper(s)", "The text in upper case."),
    "trim": ("trim(s)", "The text without spaces at either end."),
    "strtrim": ("strtrim(s)", "The text without spaces at either end."),
    "substr": ("substr(s, start, length)", "Part of the text, counted from 1."),
    "year": ("year(d)", "The year of a date."),
    "month": ("month(d)", "The month of a date, 1 to 12."),
    "day": ("day(d)", "The day of the month of a date."),
    "mod": ("mod(x, y)", "The remainder of x divided by y."),
    "missing": ("missing(x)", "True where the value is missing."),
    "mi": ("mi(x)", "True where the value is missing, as missing()."),
    "inlist": ("inlist(x, a, b, ...)", "True where x is one of the values listed."),
    "inrange": ("inrange(x, low, high)", "True where x is between low and high, inclusive."),
    "cond": ("cond(test, a, b)", "a where the test holds, b where it does not."),
    "string": ("string(x)", "The number written as text."),
    "real": ("real(s)", "The text read as a number; missing where it is not one."),
}

EGEN: dict[str, str] = {
    "total": "The column's total, within by() groups.",
    "sum": "The column's total, as total().",
    "mean": "The column's mean, within by() groups.",
    "count": "How many values are not missing, within by() groups.",
    "min": "The smallest value, within by() groups.",
    "max": "The largest value, within by() groups.",
    "median": "The median, within by() groups.",
    "sd": "The standard deviation, within by() groups.",
    "rowtotal": "The total across these variables, row by row.",
    "rowmean": "The mean across these variables, row by row.",
    "rowmiss": "How many of these variables are missing, row by row.",
    "rownonmiss": "How many of these variables are not missing, row by row.",
    "rowmax": "The largest of these variables, row by row.",
    "rowmin": "The smallest of these variables, row by row.",
    "group": "A number for each combination of these variables.",
    "tag": "1 on the first row of each combination of these variables, else 0.",
}

COLLAPSE: dict[str, str] = {
    "mean": "The mean.",
    "sum": "The total.",
    "count": "How many are not missing.",
    "max": "The largest.",
    "min": "The smallest.",
    "median": "The median.",
    "p50": "The median, as median.",
    "sd": "The standard deviation.",
    "first": "The first value in the group.",
    "last": "The last value in the group.",
}

LABEL_KINDS: dict[str, str] = {
    "variable": "Give a variable a label.",
    "define": "Make a set of value labels.",
    "values": "Put a set of value labels on a variable.",
}

MERGE_KEEP: dict[str, str] = {
    "master": "Rows only in the data in memory.",
    "using": "Rows only in the other dataset.",
    "match": "Rows in both.",
}

# The word that comes straight after a command and says which of its forms
# this is. label's are LABEL_KINDS, above, kept under their own name for the
# editor that already reads them.
SUBCOMMANDS: dict[str, dict[str, str]] = {
    "duplicates": {
        "report": "How many rows repeat, and how often.",
        "tag": "A new variable counting each row's duplicates.",
        "drop": "Keep only the first row of each set of duplicates.",
    },
    "reshape": {
        "long": "Columns like inc2019 inc2020 into rows, one per year.",
        "wide": "Rows, one per year, into columns like inc2019 inc2020.",
    },
}

# The words a loop's first line is written with: `foreach v of varlist`.
LOOP_WORDS: dict[str, str] = {
    "in": "The words that follow, one at a time.",
    "of": "Items of the kind that follows.",
    "varlist": "Variables in the data: names, q1-q5, inc*.",
    "newlist": "Names for variables not made yet.",
    "local": "The words of a local macro.",
    "global": "The words of a global macro.",
    "numlist": "Numbers: 1/5, 0(10)50, 2 4 8.",
}

# What an expression can count rows with, under a by or not.
ROW_NAMES: dict[str, str] = {
    "_n": "This row's number, counted within the by group.",
    "_N": "How many rows there are, or in the by group.",
}


def _aliases() -> dict[str, list[str]]:
    """Every other spelling of each command, read off the engine's table."""
    canonical: dict[Any, str] = {}
    for name, handler in stata.verbs().items():
        canonical.setdefault(handler, name)
    out: dict[str, list[str]] = {name: [] for name in canonical.values()}
    for name, handler in stata.verbs().items():
        if name != canonical[handler]:
            out[canonical[handler]].append(name)
    return out


def language() -> dict[str, Any]:
    """The whole vocabulary, in the shape the editor reads."""
    aliases = _aliases()
    return {
        "commands": [
            {
                "name": name,
                "aliases": aliases.get(name, []),
                "syntax": COMMANDS[name][0],
                "summary": COMMANDS[name][1],
                "options": [
                    {
                        "name": option,
                        "summary": OPTION_NOTES.get(name, {}).get(option, ""),
                        "takes_argument": option in TAKES_ARGUMENT,
                    }
                    for option in stata.OPTIONS.get(name, ())
                ],
            }
            for name in stata.verb_names()
        ],
        "functions": [
            {"name": name, "syntax": FUNCTIONS[name][0], "summary": FUNCTIONS[name][1]}
            for name in sorted(set(stata_expr.FUNCTIONS) | stata_expr.SPECIAL)
        ],
        "egen": [
            {"name": name, "summary": EGEN[name], "rowwise": name in stata.EGEN_ROWWISE}
            for name in sorted(_egen_names())
        ],
        "collapse": [
            {"name": name, "summary": COLLAPSE[name]} for name in stata.COLLAPSE_STATS
        ],
        "label_kinds": [{"name": name, "summary": text} for name, text in LABEL_KINDS.items()],
        "subcommands": {
            command: [{"name": name, "summary": text} for name, text in forms.items()]
            for command, forms in SUBCOMMANDS.items()
        },
        "loop_words": [{"name": name, "summary": text} for name, text in LOOP_WORDS.items()],
        "row_names": [{"name": name, "summary": text} for name, text in ROW_NAMES.items()],
        "by_able": sorted(stata.BY_ABLE),
        "merge_shapes": list(stata.MERGE_SHAPES),
        "merge_keep": [{"name": name, "summary": text} for name, text in MERGE_KEEP.items()],
    }


def _egen_names() -> set[str]:
    # group() and tag() are handled by name inside egen rather than listed in
    # a table, so they are added here by name as well.
    return set(stata.EGEN_AGGREGATES) | stata.EGEN_ROWWISE | {"group", "tag"}

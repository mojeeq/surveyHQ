"""The ready-made grounds a board can be given, for the exported file.

A ground is CSS rather than a picture - gradients and repeating gradients -
which is what lets an exported dashboard carry it. A picture would have to be
base64'd into the file and would still be a photograph behind somebody's
numbers; this is a surface, and it costs a few hundred bytes.

The table is the same one the application draws from, in
`frontend/src/lib/backgrounds.ts`. Two copies rather than one generated from
the other, because the application needs it in the browser with no server and
the export needs it in Python with no build step - and a test reads the
TypeScript and fails if a ground here says anything different.
"""

from __future__ import annotations

#: id -> the flat colour under the pattern, the CSS background-image over it,
#: and the background-size the pattern repeats in where it needs one.
GROUNDS: dict[str, dict[str, str]] = {
    "mist": {
        "tint": "#f4f6f9",
        "layers": (
            "linear-gradient(180deg, rgba(255,255,255,0.55) 0%, rgba(0,0,0,0.03) "
            "100%)"
        ),
    },
    "paper-grain": {
        "tint": "#f7f5f0",
        "layers": (
            "repeating-linear-gradient(45deg, rgba(120,110,90,0.04) 0 2px, "
            "rgba(0,0,0,0) 2px 6px), repeating-linear-gradient(-45deg, "
            "rgba(120,110,90,0.03) 0 2px, rgba(0,0,0,0) 2px 6px), "
            "linear-gradient(180deg, rgba(255,255,255,0.45) 0%, rgba(90,70,40,0.05) "
            "100%)"
        ),
    },
    "graph": {
        "tint": "#fbfcfd",
        "layers": (
            "linear-gradient(rgba(70,100,140,0.10) 1px, rgba(0,0,0,0) 1px), "
            "linear-gradient(90deg, rgba(70,100,140,0.10) 1px, rgba(0,0,0,0) 1px), "
            "linear-gradient(180deg, rgba(255,255,255,0.5) 0%, rgba(0,0,0,0.02) 100%)"
        ),
        "size": "24px 24px, 24px 24px, auto",
    },
    "dots": {
        "tint": "#f6f7f9",
        "layers": (
            "radial-gradient(rgba(60,80,110,0.16) 1px, rgba(0,0,0,0) 1.5px), "
            "linear-gradient(180deg, rgba(255,255,255,0.5) 0%, rgba(0,0,0,0.03) 100%)"
        ),
        "size": "16px 16px, auto",
    },
    "sand": {
        "tint": "#f6efe3",
        "layers": (
            "linear-gradient(160deg, #fbf6ec 0%, #efe3cf 100%)"
        ),
    },
    "dawn": {
        "tint": "#fdf1e7",
        "layers": (
            "linear-gradient(160deg, #fff6ee 0%, #fbe3d2 55%, #f3dcd6 100%)"
        ),
    },
    "arctic": {
        "tint": "#eef4fb",
        "layers": (
            "linear-gradient(160deg, #f8fbff 0%, #e4eef9 100%)"
        ),
    },
    "blueprint": {
        "tint": "#0f2b4a",
        "layers": (
            "linear-gradient(rgba(255,255,255,0.08) 1px, rgba(0,0,0,0) 1px), "
            "linear-gradient(90deg, rgba(255,255,255,0.08) 1px, rgba(0,0,0,0) 1px), "
            "linear-gradient(160deg, #123355 0%, #0b2138 100%)"
        ),
        "size": "26px 26px, 26px 26px, auto",
    },
    "sea": {
        "tint": "#0b2f36",
        "layers": (
            "linear-gradient(160deg, #11404a 0%, #082227 100%)"
        ),
    },
    "moss": {
        "tint": "#0f241b",
        "layers": (
            "linear-gradient(160deg, #163528 0%, #0a1a13 100%)"
        ),
    },
    "carbon": {
        "tint": "#111418",
        "layers": (
            "repeating-linear-gradient(45deg, rgba(255,255,255,0.025) 0 2px, "
            "rgba(0,0,0,0) 2px 7px), linear-gradient(160deg, rgba(255,255,255,0.05) "
            "0%, rgba(0,0,0,0.28) 100%)"
        ),
    },
    "plum": {
        "tint": "#241427",
        "layers": (
            "linear-gradient(160deg, #33203a 0%, #190e1c 100%)"
        ),
    },
}


def ground(name: str) -> dict[str, str] | None:
    """One ground by id, or None where the board names one this version dropped."""
    return GROUNDS.get(str(name or ""))

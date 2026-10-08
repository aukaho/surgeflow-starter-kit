"""Build the Colab notebooks in notebooks/ from readable sources in notebooks/src/.

Source format (percent format, like Jupytext):

    # %% [markdown]
    # # A heading
    # Some text.

    # %%
    print("a code cell")

    # %% [helpers]

The ``# %% [helpers]`` marker is replaced by a code cell holding
kit/surgeflow_helpers.py, so every notebook carries the same client and
chart theme. An "Open in Colab" badge is added above the first cell.

Usage:
    python tools/build_notebooks.py            # build every notebook
    python tools/build_notebooks.py 01-market-boards
    python tools/build_notebooks.py --check    # fail if a notebook is stale
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "notebooks" / "src"
OUT = ROOT / "notebooks"
HELPERS = ROOT / "kit" / "surgeflow_helpers.py"
COLAB = "https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/{name}.ipynb"
BADGE = "[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)]({url})"
MARKER = re.compile(r"^# %%(?: \[(markdown|helpers)\])?\s*$")


def _lines(text: str) -> list[str]:
    lines = text.strip("\n").split("\n")
    return [line + "\n" for line in lines[:-1]] + [lines[-1]] if lines != [""] else []


def _cell(kind: str, text: str) -> dict:
    cell = {"cell_type": kind, "metadata": {}, "source": _lines(text)}
    if kind == "code":
        cell.update(execution_count=None, outputs=[])
    return cell


def parse(source: str) -> list[dict]:
    cells, kind, buf = [], None, []

    def flush():
        if kind is None:
            return
        body = "\n".join(buf).strip("\n")
        if kind == "markdown":
            body = "\n".join(re.sub(r"^# ?", "", line) for line in body.split("\n"))
        if kind == "helpers":
            cells.append(_cell("code", HELPERS.read_text().strip("\n")))
        elif body.strip():
            cells.append(_cell(kind, body))

    for line in source.split("\n"):
        match = MARKER.match(line)
        if match:
            flush()
            kind, buf = (match.group(1) or "code"), []
        else:
            buf.append(line)
    flush()
    return cells


def build(src: Path) -> str:
    name = src.stem
    cells = parse(src.read_text())
    cells.insert(0, _cell("markdown", BADGE.format(url=COLAB.format(name=name))))
    notebook = {
        "cells": cells,
        "metadata": {
            "colab": {"name": f"{name}.ipynb", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    for i, cell in enumerate(notebook["cells"]):
        cell["id"] = f"{name[:2]}-{i:02d}"
    return json.dumps(notebook, indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="source stems to build (default: all)")
    parser.add_argument("--check", action="store_true", help="exit 1 if any notebook is out of date")
    args = parser.parse_args()

    sources = sorted(SRC.glob("*.py"))
    if args.names:
        sources = [s for s in sources if s.stem in args.names or s.name in args.names]
    stale = []
    for src in sources:
        target = OUT / f"{src.stem}.ipynb"
        text = build(src)
        if args.check:
            if not target.exists() or target.read_text() != text:
                stale.append(target.name)
        else:
            target.write_text(text)
            print(f"built {target.relative_to(ROOT)}")
    if stale:
        print("Out of date (run python tools/build_notebooks.py):", ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

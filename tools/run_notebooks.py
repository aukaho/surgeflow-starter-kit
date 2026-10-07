"""Execute the starter-kit notebooks headlessly and report pass/fail.

    python tools/run_notebooks.py --mock            # offline, tests/fixtures/*.json
    python tools/run_notebooks.py --live            # real API; needs SURGEFLOW_API_KEY
    python tools/run_notebooks.py --mock 06-ml-lab  # one notebook

Executed copies (with outputs) go to build/executed/ (git-ignored); the
committed notebooks stay output-free. A run fails if any cell raises, or if
an output contains something that looks like an API key.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = ROOT / "notebooks"
OUT = ROOT / "build" / "executed"
KEY_PATTERN = re.compile(r"sf_(live|test)_[A-Za-z0-9]{8,}")

MOCK_PRELUDE = f"""
import os, sys, time
os.environ["SURGEFLOW_API_KEY"] = "sf_live_mock"
sys.path.insert(0, {str(ROOT / "tools")!r})
import mock_api; mock_api.install()
time.sleep = lambda seconds: None   # skip refresh waits offline
import plotly.io as pio; pio.renderers.default = "json"
"""
LIVE_PRELUDE = """
import plotly.io as pio; pio.renderers.default = "json"
"""


def run(path: Path, mode: str, timeout: int) -> tuple[bool, str]:
    nb = nbformat.read(path, as_version=4)
    prelude = nbformat.v4.new_code_cell(MOCK_PRELUDE if mode == "mock" else LIVE_PRELUDE)
    prelude.metadata["tags"] = ["injected-by-run-notebooks"]
    nb.cells.insert(0, prelude)
    client = NotebookClient(nb, timeout=timeout, kernel_name="python3", resources={"metadata": {"path": str(NOTEBOOKS)}})
    started = time.monotonic()
    try:
        client.execute()
        ok, detail = True, ""
    except CellExecutionError as exc:
        ok, detail = False, str(exc)[-2500:]
    OUT.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, OUT / f"{path.stem}.{mode}.ipynb")
    dumped = json.dumps([c.get("outputs", []) for c in nb.cells if c.cell_type == "code"])
    if mode == "live" and KEY_PATTERN.search(dumped):
        ok, detail = False, "An output contains something that looks like an API key."
    return ok, f"{time.monotonic() - started:.0f}s {detail}".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_const", dest="mode", const="mock")
    mode.add_argument("--live", action="store_const", dest="mode", const="live")
    parser.add_argument("names", nargs="*", help="notebook stems (default: all)")
    parser.add_argument("--timeout", type=int, default=900, help="per-cell timeout in seconds")
    args = parser.parse_args()

    if args.mode == "live" and not os.getenv("SURGEFLOW_API_KEY"):
        print("Set SURGEFLOW_API_KEY to run against the live API.")
        return 2
    paths = sorted(NOTEBOOKS.glob("*.ipynb"))
    if args.names:
        paths = [p for p in paths if p.stem in args.names]
    failures = 0
    for path in paths:
        ok, detail = run(path, args.mode, args.timeout)
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {path.name}  {detail}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

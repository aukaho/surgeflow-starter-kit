import json
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOKS = ROOT / "notebooks"


def notebook_paths():
    return sorted(NOTEBOOKS.glob("*.ipynb"))


def test_all_eleven_notebooks_execute_in_fixture_mode(monkeypatch):
    monkeypatch.setenv("SURGEFLOW_FIXTURES", "1")
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "python" / "src"))
    monkeypatch.delenv("SURGEFLOW_API_KEY", raising=False)
    paths = notebook_paths()
    assert len(paths) == 11

    for path in paths:
        notebook = nbformat.read(path, as_version=4)
        client = NotebookClient(
            notebook,
            timeout=120,
            kernel_name="python3",
            resources={"metadata": {"path": str(NOTEBOOKS)}},
        )
        client.execute()


def test_committed_notebook_template_has_no_outputs():
    for path in notebook_paths():
        notebook = json.loads(path.read_text(encoding="utf-8"))
        assert notebook["nbformat"] == 4
        nbformat.validate(nbformat.reads(path.read_text(encoding="utf-8"), as_version=4))
        for cell in notebook["cells"]:
            assert cell.get("id")
            if cell["cell_type"] == "code":
                assert cell["outputs"] == []
                assert cell["execution_count"] is None


def test_new_fixtures_have_top_level_synthetic_label():
    recorded = {
        "data-freshness.json",
        "momentum-hotlist-us.json",
        "momentum-hotlist-us.csv",
    }
    for path in (ROOT / "python" / "tests" / "fixtures").glob("*.json"):
        if path.name in recorded:
            continue
        assert json.loads(path.read_text(encoding="utf-8"))["synthetic"] is True

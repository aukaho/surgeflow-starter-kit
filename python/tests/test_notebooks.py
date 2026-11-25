import json
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOKS = ROOT / "notebooks"


def notebook_paths():
    return sorted(NOTEBOOKS.glob("*.ipynb"))


def failure_lines(text):
    # Notebook cells print "Error ..."; monitor panels print "HTTP <code>; ...".
    return [line for line in text.splitlines() if line.startswith(("Error ", "HTTP 4", "HTTP 5"))]


def test_all_eleven_notebooks_execute_in_fixture_mode(monkeypatch):
    monkeypatch.setenv("SURGEFLOW_FIXTURES", "1")
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "python" / "src"))
    monkeypatch.delenv("SURGEFLOW_API_KEY", raising=False)
    monkeypatch.setenv("SURGEFLOW_MONITOR_MAX_CYCLES", "1")
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
        # fetch_panel swallows exceptions into printed text, so check the printed text.
        text = "".join(
            output.get("text", "")
            for cell in notebook.cells if cell.cell_type == "code"
            for output in cell.outputs if output.get("output_type") == "stream"
        )
        assert not failure_lines(text), path.name
        assert not any(o.get("output_type") == "error" for c in notebook.cells
                       if c.cell_type == "code" for o in c.outputs), path.name
        if path.name.startswith("10_"):
            # The refresh task's output must show every panel, not stop after one.
            from surgeflow.monitor import default_panels

            for panel in default_panels(None, "key"):
                assert f"{panel.offering} — {panel.name}\n" in text, panel.name
            assert "monitor task stopped" not in text
            assert "Projected scheduled requests per full active day: 1234" in text
            assert "Projected total including one startup account check: 1235" in text
            # me.json reports 1,400 remaining, so the 1,500 budget is seeded to 100 used.
            assert "Key daily requests remaining across all processes: 1400" in text
            assert "local budget used: 100 / 1500" in text
        assert "Unavailable by member key" not in text, path.name
        if path.name[:2] in ("03", "09"):
            assert "Data status: available" in text, path.name
            assert "source date: 2026-11-20" in text, path.name
            assert "Column guide:" in text, path.name


def test_real_feed_notebooks_fetch_once_and_cite_both_routes():
    cases = (
        ("03_technical_cohorts.ipynb", ".member_technical_cohorts(", "COHORT_COLUMNS"),
        ("09_layoffs.ipynb", ".member_layoffs(", "WATCH_COLUMNS"),
    )
    for name, method_call, column_guide in cases:
        notebook = json.loads((NOTEBOOKS / name).read_text(encoding="utf-8"))
        code = "\n".join(
            "".join(cell["source"])
            for cell in notebook["cells"] if cell["cell_type"] == "code"
        )
        markdown = "\n".join(
            "".join(cell["source"])
            for cell in notebook["cells"] if cell["cell_type"] == "markdown"
        )
        assert code.count(method_call) == 1
        assert column_guide in code
        assert "member research routes (beta)" in markdown
        assert "GET /api/{market}/technical-strategies/cohorts" in markdown
        assert "GET /api/us/layoffs/latest" in markdown
        assert "Do not republish" in markdown


def test_notebook_feed_unavailable_is_not_an_error(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(NOTEBOOKS))
    from _shared import fetch_payload
    from surgeflow import SurgeFlowFeedUnavailable

    def unavailable():
        raise SurgeFlowFeedUnavailable(503, "Feed unavailable")

    assert fetch_payload("Feed test", unavailable) is None
    text = capsys.readouterr().out
    assert "Data status: Feed unavailable" in text
    assert "source date: not supplied" in text
    assert "Error " not in text


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


def run_notebook_in_process(name, monkeypatch, patches=()):
    """Run a notebook's code cells in this process; return its namespace."""
    import _shared
    from surgeflow import SurgeFlow

    monkeypatch.setenv("SURGEFLOW_FIXTURES", "1")
    monkeypatch.delenv("SURGEFLOW_API_KEY", raising=False)
    monkeypatch.chdir(NOTEBOOKS)
    monkeypatch.setattr(_shared, "display", lambda frame: None)
    for method, replacement in patches:
        monkeypatch.setattr(SurgeFlow, method, replacement)
    namespace = {}
    notebook = json.loads((NOTEBOOKS / name).read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            exec("".join(cell["source"]), namespace)
    return namespace


def test_cycle_columns_match_producer_schema(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(NOTEBOOKS))
    namespace = run_notebook_in_process("01_macro_model_votes.ipynb", monkeypatch)
    row = namespace["cycle_frame"].iloc[0]

    assert row["leading_method"] == "pc1" and row["lagging_method"] == "equal_weight"
    assert (row["leading_n_used"], row["leading_n_max"]) == (5, 6)
    assert row["cycle_phase"] == "expansion"
    assert not namespace["cycle_frame"].isna().any().any()


def test_notebook_summaries_keep_freshness_and_fallback(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(NOTEBOOKS))
    fixtures = ROOT / "python" / "tests" / "fixtures"

    def stale_votes(self, api_key, *args, **kwargs):
        payload = json.loads((fixtures / "macro-index-votes.json").read_text(encoding="utf-8"))
        payload["data"]["freshness"]["state"] = "stale"
        return payload

    def past_week_books(self, api_key):
        payload = json.loads((fixtures / "weekly-pure-books.json").read_text(encoding="utf-8"))
        payload["data"]["freshness"] = "past_week"
        payload["data"]["publication"] = {"fallback": True, "fallback_reason": "accepted_publication_unavailable"}
        return payload

    run_notebook_in_process("01_macro_model_votes.ipynb", monkeypatch,
                            [("member_macro_index_votes", stale_votes)])
    assert "Data status: available; freshness: stale;" in capsys.readouterr().out

    run_notebook_in_process("04_pure_factor_portfolios.ipynb", monkeypatch,
                            [("member_weekly_pure_books", past_week_books)])
    out = capsys.readouterr().out
    assert "Current weekly research books" not in out
    assert ("Data status: available; freshness: past_week; "
            "fallback reason: accepted_publication_unavailable;") in out


def test_cohort_notebook_reports_expired_feed(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(NOTEBOOKS))
    fixtures = ROOT / "python" / "tests" / "fixtures"

    def expired(self, market, api_key):
        payload = json.loads((fixtures / "technical-cohorts-us.json").read_text(encoding="utf-8"))
        payload["valid_until"] = "2000-01-01T00:00:00+00:00"
        return payload

    run_notebook_in_process("03_technical_cohorts.ipynb", monkeypatch,
                            [("member_technical_cohorts", expired)])
    out = capsys.readouterr().out
    assert "Data status: past valid_until;" in out
    assert "Data status: available" not in out


def test_cohort_analytics_notebook_executes_in_fixture_mode(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(NOTEBOOKS))

    namespace = run_notebook_in_process("03_technical_cohorts.ipynb", monkeypatch)
    out = capsys.readouterr().out
    frame = namespace["analytics_frame"]

    assert len(frame) == 4
    assert not frame.isna().any().any()
    assert "Cohort analytics (research measurement, not a forecast)" in out
    assert "A 30-session window is short and these estimates are noisy. Measured returns describe the past window only; they are not a forecast." in out
    assert "The risk-free rate is a proxy where analytics.risk_free.proxy is true." in out
    assert "risk-free rate carried from the previous date" in out
    assert frame.iloc[3]["window_return"] == "analytics not published for this cohort"


def test_live_monitor_runs_requests_off_the_event_loop():
    notebook = json.loads((NOTEBOOKS / "10_live_monitor.ipynb").read_text(encoding="utf-8"))
    code = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")

    assert "await asyncio.to_thread(monitor.run_due, lambda: STOP)" in code
    assert "            monitor.run_due()" not in code


def test_failure_scan_catches_failed_monitor_panels():
    text = ("07 Hotlist — us-hotlist\nHTTP 401; message: bad key; requested at 2026-11-23\n"
            "07 Hotlist — us-realtime\nHTTP 429; Retry-After 17 seconds; message: slow\n"
            "09 Layoffs — us-layoffs\nFeed unavailable; requested at 2026-11-23\n")
    assert [line[:8] for line in failure_lines(text)] == ["HTTP 401", "HTTP 429"]


def test_shared_fetches_are_sent_once_even_when_they_fail(monkeypatch, capsys):
    from surgeflow import SurgeFlowApiError

    monkeypatch.syspath_prepend(str(NOTEBOOKS))
    for name, method in (("05_fundamental_rankings.ipynb", "member_fundamental_peers"),
                         ("08_daily_insights.ipynb", "member_daily_insights")):
        calls = []

        def unavailable(self, *args, **kwargs):
            calls.append(args)
            raise SurgeFlowApiError(503, "Service unavailable")

        run_notebook_in_process(name, monkeypatch, [(method, unavailable)])
        assert len(calls) == 1, name
        assert capsys.readouterr().out.count("Error SurgeFlowApiError") == 2, name

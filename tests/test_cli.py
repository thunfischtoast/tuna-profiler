import json

import pytest

from tuna import cli


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "root"
    sales = root / "data" / "2024"
    sales.mkdir(parents=True)
    for d in range(1, 6):
        (sales / f"sales_2024-01-0{d}.csv").write_text(f"id,amount,day\n{d},{d}.5,2024-01-0{d}\n", encoding="utf-8")
    (root / "data" / "other").mkdir()
    (root / "data" / "other" / "a.csv").write_text("id,amount,day\n9,1.0,2024-02-01\n", encoding="utf-8")
    (root / "cfg").mkdir()
    (root / "cfg" / "app.yaml").write_text("name: app\nport: 8080\n", encoding="utf-8")
    (root / "notes.txt").write_text("hi", encoding="utf-8")
    (root / "broken.json").write_text("{", encoding="utf-8")
    return root


def _run(args, tmp_path):
    md, js = tmp_path / "r.md", tmp_path / "r.json"
    assert cli.main([*map(str, args), "-o", str(md), "-o", str(js), "-q"]) == 0
    return md.read_text(encoding="utf-8"), json.loads(js.read_text(encoding="utf-8"))


def test_tree(tree, tmp_path):
    md, rep = _run([tree], tmp_path)
    assert len(rep["groups"]) == 2
    assert rep["ignored"] == {".txt": 1}
    assert [e["path"] for e in rep["errors"]] == ["broken.json"]
    assert rep["files_found"] == 8 and rep["files_profiled"] == 7
    sales = rep["groups"][0]
    assert sales["tables"] == 6
    loc = {loc["folder"]: loc for loc in sales["locations"]}
    (pattern,) = loc["data/2024"]["patterns"]
    assert pattern["pattern"] == "sales_{date:YYYY-MM-DD}.csv"
    assert pattern["files"] == 5
    assert loc["data/other"]["unmatched"] == ["a.csv"]
    amount = next(f for f in sales["fields"] if f["name"] == "amount")
    assert amount["type"] == "float" and amount["min"] == 1.0 and amount["max"] == 5.5
    assert "sales_{date:YYYY-MM-DD}.csv" in md
    assert len(sales["members"]) == 6


def test_single_file(tree, tmp_path):
    _, rep = _run([tree / "cfg" / "app.yaml"], tmp_path)
    assert rep["files_profiled"] == 1
    assert [f["folder"] for f in rep["folders"]] == ["."]
    assert [f["name"] for f in rep["groups"][0]["fields"]] == ["name", "port"]


def test_no_stats(tree, tmp_path):
    _, rep = _run([tree, "--no-stats"], tmp_path)
    for g in rep["groups"]:
        for f in g["fields"]:
            assert f["nulls_pct"] is None and f["min"] is None and f["distinct"] is None


def test_parallel_matches_inline(tree, tmp_path):
    for i in range(8):
        (tree / f"extra_{i}.csv").write_text("x\n1\n", encoding="utf-8")
    _, inline = _run([tree, "-j", "1"], tmp_path)
    _, parallel = _run([tree, "-j", "2"], tmp_path)
    assert inline["groups"] == parallel["groups"]


def test_bad_args(tree, tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.main([str(tree / "missing")])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        cli.main([str(tree), "-o", str(tmp_path / "r.txt")])
    assert e.value.code == 2


def test_table_warnings_reach_reports(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("a,b\n1,2\n3,4\nx,5\n", encoding="utf-8")
    md, rep = _run([p, "--sample-rows", "2"], tmp_path)
    assert len(rep["warnings"]) == 1 and "did not match" in rep["warnings"][0]["message"]
    assert "## Warnings" in md


@pytest.mark.parametrize(
    "opt", [["--sample-rows", "0"], ["--min-pattern-files", "1"], ["--jobs", "0"], ["--max-depth", "-1"]]
)
def test_invalid_numbers(tree, opt):
    with pytest.raises(SystemExit) as e:
        cli.main([str(tree), *opt])
    assert e.value.code == 2


def test_output_dir_missing(tree, tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.main([str(tree), "-q", "-o", str(tmp_path / "nope" / "r.md")])
    assert e.value.code == 2


def test_outputs_and_lock_files_not_profiled(tree, tmp_path):
    (tree / "~$budget.xlsx").write_bytes(b"lock")
    out = tree / "r.json"
    for _ in range(2):
        assert cli.main([str(tree), "-q", "-o", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    paths = {m["path"] for g in rep["groups"] for m in g["members"]}
    assert "r.json" not in paths
    assert rep["files_found"] == 8


def test_windows_worker_clamp(tree, monkeypatch):
    seen = []

    class FakePool:
        def __init__(self, workers):
            seen.append(workers)
            raise RuntimeError("stop")

    monkeypatch.setattr(cli, "ProcessPoolExecutor", FakePool)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    jobs = [(str(tree / "notes.txt"), "notes.txt", "csv", None)] * 8
    with pytest.raises(RuntimeError):
        list(cli._run(jobs, 100))
    assert seen == [61]


def test_terminal_output(tree, capsys):
    assert cli.main([str(tree)]) == 0
    out = capsys.readouterr().out
    assert "S1" in out and "sales_{date:YYYY-MM-DD}.csv" in out
    assert "broken.json" in out

import datetime as dt
import json

import polars as pl
import pytest
import xlsxwriter

from tuna.readers import ReadOptions, read_file

OPTS = ReadOptions()


def _one(path, fmt, opts=OPTS):
    (t,) = read_file(path, path.name, fmt, opts)
    return t


def test_semicolon_csv(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("id;name;day\n1;x;2024-01-02\n2;y;2024-01-03\n", encoding="utf-8")
    t = _one(p, "csv")
    assert t.fields == {"id": {"int"}, "name": {"str"}, "day": {"date"}}
    assert t.rows == 2
    assert t.stats["id"].max == 2


def test_tsv(tmp_path):
    p = tmp_path / "a.tsv"
    p.write_text("a\tb\n1\t2.5\n", encoding="utf-8")
    assert _one(p, "tsv").fields == {"a": {"int"}, "b": {"float"}}


def test_bom_header(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes("﻿id,v\n1,2\n".encode())
    assert list(_one(p, "csv").fields) == ["id", "v"]


def test_ragged_csv_reads(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("a,b\n1,2\n3,4,5\n6\n", encoding="utf-8")
    t = _one(p, "csv")
    assert list(t.fields) == ["a", "b"]
    assert t.rows == 3


def test_schema_from_schema_rows(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("a,b\n1,2\n3,4\nx,5\n", encoding="utf-8")
    t = _one(p, "csv", ReadOptions(sample_rows=2, schema_rows=2))
    assert t.fields["a"] == {"int"}
    assert t.rows == 3


def test_sample_rows_limits_stats_not_rows(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("n\n" + "\n".join(str(i) for i in range(50)) + "\n", encoding="utf-8")
    t = _one(p, "csv", ReadOptions(sample_rows=10))
    assert t.rows == 50
    assert t.stats["n"].count == 10
    full = _one(p, "csv", ReadOptions(sample_rows=None))
    assert full.rows == 50 and full.stats["n"].count == 50


def test_xlsx_two_sheets(tmp_path):
    p = tmp_path / "book.xlsx"
    wb = xlsxwriter.Workbook(p)
    s1 = wb.add_worksheet("first")
    s1.write_row(0, 0, ["a", "b"])
    for i in range(5):
        s1.write_row(i + 1, 0, [i, f"t{i}"])
    s2 = wb.add_worksheet("second")
    s2.write_row(0, 0, ["x"])
    s2.write_row(1, 0, [1.5])
    wb.add_worksheet("empty")
    wb.close()
    tables = read_file(p, "book.xlsx", "xlsx", ReadOptions(sample_rows=2))
    assert [t.sheet for t in tables] == ["first", "second"]
    assert tables[0].rows == 5
    assert tables[0].fields == {"a": {"float"}, "b": {"str"}}  # Excel stores numbers as floats
    assert tables[0].stats["b"].count == 2
    assert "empty" in tables[0].warnings[0]


def test_nested_json_object(tmp_path):
    p = tmp_path / "a.json"
    doc = {"name": "x", "meta": {"v": 1}, "items": [{"id": 1}, {"id": 2, "tag": "t"}], "tags": ["a", "b"]}
    p.write_text(json.dumps(doc), encoding="utf-8")
    t = _one(p, "json")
    assert t.rows == 1
    assert t.fields == {
        "name": {"str"},
        "meta.v": {"int"},
        "items[]": {"array"},
        "items[].id": {"int"},
        "items[].tag": {"str"},
        "tags[]": {"str"},
    }
    assert t.stats["items[].id"].count == 2


def test_json_root_list_and_iso_dates(tmp_path):
    p = tmp_path / "a.json"
    recs = [{"d": "2024-01-01", "ts": "2024-01-01T10:00:00", "s": "2024-01-01x"}, {"d": None}, 5]
    p.write_text(json.dumps(recs), encoding="utf-8")
    t = _one(p, "json")
    assert t.rows == 3
    assert t.fields["d"] == {"date", "null"}
    assert t.fields["ts"] == {"datetime"}
    assert t.fields["s"] == {"str"}
    assert t.fields["value"] == {"int"}
    assert t.stats["d"].min == "2024-01-01"


def test_json_sample_rows_limits_stats(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps([{"n": i} for i in range(20)] + [{"n": "late"}]), encoding="utf-8")
    t = _one(p, "json", ReadOptions(sample_rows=5))
    assert t.fields["n"] == {"int", "str"}
    assert t.stats["n"].count == 5


def test_yaml_multi_doc(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("a: 1\nwhen: 2024-01-01\n---\na: 2\n", encoding="utf-8")
    t = _one(p, "yaml")
    assert t.rows == 2
    assert t.fields == {"a": {"int"}, "when": {"date"}}
    assert t.stats["when"].min == "2024-01-01"


def test_bad_json_raises(tmp_path):
    p = tmp_path / "a.json"
    p.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError):
        _one(p, "json")


def test_column_named_count(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("count,name\n1,a\n1,b\n", encoding="utf-8")
    t = _one(p, "csv")
    assert t.stats["count"].top[1] == 2


def test_json_with_bom(tmp_path):
    p = tmp_path / "a.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"a": 1}).encode())
    assert _one(p, "json").fields == {"a": {"int"}}


def test_yaml_trailing_separator(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("a: 1\n---\na: 2\n---\n", encoding="utf-8")
    t = _one(p, "yaml")
    assert t.rows == 2
    assert t.fields == {"a": {"int"}}


def test_full_read_keeps_sampled_schema(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("n,s\n" + "".join(f"{i},x\n" for i in range(30)) + "N/A,y\n", encoding="utf-8")
    t = _one(p, "csv", ReadOptions(sample_rows=None, schema_rows=10))
    assert t.fields == {"n": {"int"}, "s": {"str"}}
    assert t.rows == 31
    assert t.stats["n"].nulls == 1
    assert any("did not match" in w for w in t.warnings)


def test_duration_and_binary_series():
    from tuna.readers import stats_from_series
    from tuna.types import polars_type_name

    dur = pl.Series("d", [dt.timedelta(hours=1), dt.timedelta(hours=30), None])
    assert polars_type_name(dur.dtype) == "duration"
    st = stats_from_series(dur, "duration")
    assert (st.count, st.nulls, st.min_len) == (2, 1, None)
    assert st.max == dt.timedelta(hours=30)
    binary = pl.Series("b", [b"x", b"yz"])
    assert polars_type_name(binary.dtype) == "binary"
    assert stats_from_series(binary, "binary").count == 2
    # A non-String series labelled "str" must not crash.
    assert stats_from_series(pl.Series("c", [b"x"]), "str").min_len is None


def test_temporal_minmax_normalized():
    from tuna.readers import stats_from_series, stats_from_values

    a = stats_from_values([dt.date(2024, 1, 5)])
    a.merge(stats_from_values(["2023-12-01"]))
    a.merge(stats_from_series(pl.Series("t", [dt.datetime(2024, 3, 1, 8)]), "datetime"))  # noqa: DTZ001
    assert a.min == "2023-12-01"
    assert a.max == "2024-03-01T08:00:00"


def test_xlsx_full_keeps_sampled_schema(tmp_path):
    p = tmp_path / "late.xlsx"
    wb = xlsxwriter.Workbook(p)
    ws = wb.add_worksheet("s")
    ws.write_row(0, 0, ["a"])
    for i in range(1, 6):
        ws.write(i, 0, i)
    ws.write(6, 0, "x")
    wb.close()
    sampled = read_file(p, "late.xlsx", "xlsx", ReadOptions(sample_rows=3, schema_rows=3))[0]
    full = read_file(p, "late.xlsx", "xlsx", ReadOptions(sample_rows=None, schema_rows=3))[0]
    assert full.fields == sampled.fields
    assert full.rows == sampled.rows == 6


def test_blank_strings_in_json_are_null_and_empty(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps([{"n": 1}, {"n": ""}, {"n": "  "}, {"n": 4}]), encoding="utf-8")
    t = _one(p, "json")
    assert t.fields["n"] == {"int", "null"}
    st = t.stats["n"]
    assert (st.count, st.nulls, st.empty) == (2, 2, 2)


def test_whitespace_cells_in_csv(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("n,f,s\n1,1.5,a\n   ,  ,\n3,2.5, \n", encoding="utf-8")
    t = _one(p, "csv")
    assert t.fields == {"n": {"int"}, "f": {"float"}, "s": {"str"}}
    assert (t.stats["n"].nulls, t.stats["n"].empty) == (1, 1)
    assert t.stats["n"].max == 3
    assert t.stats["s"].empty == 1


def test_whitespace_cells_in_excel(tmp_path):
    p = tmp_path / "b.xlsx"
    wb = xlsxwriter.Workbook(p)
    s = wb.add_worksheet("s")
    s.write_row(0, 0, ["a"])
    s.write_string(1, 0, "  ")
    s.write_number(2, 0, 2)
    wb.close()
    (t,) = read_file(p, "b.xlsx", "xlsx", OPTS)
    assert t.fields["a"] == {"float"}
    assert t.stats["a"].nulls == 1


def test_blank_cells_do_not_turn_nan_text_into_float(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("v,w\nnan,1.5\n  ,\n-INF,2.5\n", encoding="utf-8")
    t = _one(p, "csv")
    assert t.fields == {"v": {"str"}, "w": {"float"}}

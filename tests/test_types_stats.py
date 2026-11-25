import polars as pl

from tuna.model import DISTINCT_CAP, TOP_CAP, FieldStats
from tuna.readers import stats_from_series, stats_from_values
from tuna.types import compatible, display_type


def test_display_type():
    assert display_type({"int"}) == "int"
    assert display_type({"int", "float", "null"}) == "float"
    assert display_type({"date", "datetime"}) == "datetime"
    assert display_type({"null"}) == "null"
    assert display_type({"str", "int"}) == "int|str"


def test_compatible():
    assert compatible({"int"}, {"float"})
    assert compatible({"null"}, {"str"})
    assert compatible({"date"}, {"datetime", "null"})
    assert not compatible({"int"}, {"str"})


def test_merge_min_max_mean():
    a = stats_from_values([1, 5, None])
    b = stats_from_values([-2, 3])
    a.merge(b)
    assert (a.count, a.nulls, a.min, a.max, a.sum) == (4, 1, -2, 5, 7.0)
    assert a.sum / a.count == 1.75


def test_merge_incomparable_minmax_keeps_value():
    a = stats_from_values([1])
    a.merge(stats_from_values(["x"]))
    assert a.min == 1 and a.max == 1


def test_merge_distinct_cap():
    a = FieldStats(distinct=set(range(DISTINCT_CAP)))
    a.merge(FieldStats(distinct={-1}))
    assert a.distinct is None
    b = FieldStats(distinct={1})
    b.merge(FieldStats(distinct=None))
    assert b.distinct is None


def test_merge_top_prune():
    a = stats_from_values([f"a{i}" for i in range(TOP_CAP)] + ["hot"] * 5)
    a.merge(stats_from_values([f"b{i}" for i in range(10)] + ["hot"]))
    assert len(a.top) == TOP_CAP
    assert a.top.most_common(1) == [("hot", 6)]


def test_series_and_values_agree():
    data = [3, 1, None, 3, 7]
    s1 = stats_from_series(pl.Series("x", data), "int")
    s2 = stats_from_values(data)
    for attr in ("count", "nulls", "min", "max", "sum", "distinct", "top"):
        assert getattr(s1, attr) == getattr(s2, attr), attr
    words = ["ab", "c", None, "ab"]
    w1 = stats_from_series(pl.Series("w", words), "str")
    w2 = stats_from_values(words)
    for attr in ("count", "nulls", "min", "max", "min_len", "max_len", "distinct", "top"):
        assert getattr(w1, attr) == getattr(w2, attr), attr


def test_empty_merges():
    a = FieldStats(nulls=2, empty=1)
    a.merge(FieldStats(nulls=1, empty=1))
    assert (a.nulls, a.empty) == (3, 2)

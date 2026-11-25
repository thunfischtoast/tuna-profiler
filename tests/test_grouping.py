from tuna.grouping import group_tables
from tuna.model import TableProfile


def _t(path, **fields):
    return TableProfile(path, None, "csv", 1, {k: set(v.split("|")) for k, v in fields.items()}, {})


COLS = {"a": "int", "b": "str", "c": "date", "d": "float", "e": "str"}


def test_missing_column_joins_as_optional():
    full = [_t(f"f{i}.csv", **COLS) for i in range(3)]
    partial = _t("p.csv", **{k: v for k, v in COLS.items() if k != "e"})
    groups = group_tables([partial, *full])
    assert len(groups) == 1
    assert len(groups[0]) == 4


def test_int_float_merge():
    a = _t("a.csv", x="int", y="str")
    b = _t("b.csv", x="float", y="str")
    assert len(group_tables([a, b])) == 1


def test_null_column_merges():
    a = _t("a.csv", x="int", y="str")
    b = _t("b.csv", x="null", y="str")
    assert len(group_tables([a, b])) == 1


def test_str_vs_int_splits():
    a = _t("a.csv", x="int", y="str")
    b = _t("b.csv", x="str", y="str")
    assert len(group_tables([a, b])) == 2


def test_low_similarity_splits():
    a = _t("a.csv", x="int", y="str")
    b = _t("b.csv", x="int", z="str")
    assert len(group_tables([a, b])) == 2


def test_empty_tables_group_together():
    e1, e2 = _t("e1.csv"), _t("e2.csv")
    groups = group_tables([e1, _t("a.csv", x="int"), e2])
    assert sorted(len(g) for g in groups) == [1, 2]
    assert next(g for g in groups if len(g) == 2) == [e1, e2]


def test_largest_group_first():
    small = [_t("s.csv", q="str")]
    big = [_t(f"b{i}.csv", x="int") for i in range(3)]
    assert group_tables(small + big)[0] == big

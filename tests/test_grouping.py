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


def test_str_vs_int_splits_with_strict_types():
    a = _t("a.csv", x="int", y="str")
    b = _t("b.csv", x="str", y="str")
    assert len(group_tables([a, b], strict_types=True)) == 2


def test_type_conflict_joins_by_default():
    a = _t("a.csv", x="int", y="str")
    b = _t("b.csv", x="str", y="str")
    assert len(group_tables([a, b])) == 1


def test_empty_string_file_joins():
    a = _t("a.json", x="int", y="str")
    b = _t("b.json", x="int|null", y="null")
    assert len(group_tables([a, b], strict_types=True)) == 1


S2 = {"id": "int", "structures[]": "array", **{f"structures[].f{i}": "str" for i in range(16)}}


def test_empty_array_rule():
    full = [_t(f"f{i}.json", **S2) for i in range(3)]
    empty = _t("e.json", id="int", **{"structures[]": "array"})
    groups = group_tables([*full, empty])
    assert len(groups) == 1
    reverse = group_tables([empty, empty, empty, full[0]])
    assert len(reverse) == 1


def test_tiny_table_does_not_join_large_one():
    big = [_t(f"b{i}.csv", **{c: "int" for c in "abcdefghij"}) for i in range(3)]
    tiny = _t("t.csv", a="int")
    assert len(group_tables([*big, tiny])) == 2


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


def test_empty_array_children_are_optional_in_report():
    from tuna.report import build_report

    full = [_t(f"f{i}.json", **S2) for i in range(3)]
    empty = _t("e.json", id="int", **{"structures[]": "array"})
    rep = build_report(".", [*full, empty], [], [], {}, 0.0)
    (group,) = rep.groups
    present = {f.name: f.present_in for f in group.fields}
    assert present["structures[]"] == 4
    assert present["structures[].f0"] == 3


def test_type_variants_denominator_and_ties():
    from tuna.report import build_report, fmt_type

    ys = {f"y{i}": "str" for i in range(5)}
    tables = [_t("a.csv", x="str", **ys), _t("b.csv", x="int", **ys), _t("c.csv", **ys)]
    tables.append(_t("d.csv", x="null", **ys))
    rep = build_report(".", tables, [], [], {}, 0.0)
    (g,) = rep.groups
    x = g.fields[0]
    assert x.type_variants == {"int": 1, "str": 1}
    assert fmt_type(x) == "int|str (str in 1/2)"


def test_sheets_only_for_all_excel_groups():
    from tuna.report import build_report

    xl = _t("b.xlsx", x="int")
    xl.sheet, xl.format = "S", "xlsx"
    rep = build_report(".", [_t("a.csv", x="int"), xl], [], [], {}, 0.0)
    assert rep.groups[0].sheets == []
    rep = build_report(".", [xl], [], [], {}, 0.0)
    assert rep.groups[0].sheets == ["S"]

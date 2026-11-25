import uuid

from tuna.patterns import infer_patterns


def test_daily_dates():
    names = [f"sales_2024-01-{d:02d}.csv" for d in range(1, 32)]
    (p,), unmatched = infer_patterns(names, 3)
    assert p.pattern == "sales_{date:YYYY-MM-DD}.csv"
    assert p.files == 31
    assert p.ranges == {"date:YYYY-MM-DD": "2024-01-01 .. 2024-01-31"}
    assert unmatched == []


def test_compact_dates_and_datetimes():
    names = [f"dump_202401{d:02d}_120000.json" for d in (3, 1, 2)]
    (p,), _ = infer_patterns(names, 3)
    assert p.pattern == "dump_{datetime:YYYYMMDD_HHMMSS}.json"
    assert p.ranges["datetime:YYYYMMDD_HHMMSS"] == "20240101_120000 .. 20240103_120000"


def test_zero_padded_ints():
    names = [f"part_{i:03d}.csv" for i in (1, 2, 10, 120)]
    (p,), _ = infer_patterns(names, 3)
    assert p.pattern == "part_{int}.csv"
    assert p.ranges == {"int": "001 .. 120"}


def test_two_shapes_in_one_folder():
    names = [f"a_{i}.csv" for i in range(3)] + [f"b-2024-0{m}.csv" for m in range(1, 5)] + ["x.csv"]
    patterns, unmatched = infer_patterns(names, 3)
    assert [(p.pattern, p.files) for p in patterns] == [
        ("b-{date:YYYY-MM}.csv", 4),
        ("a_{int}.csv", 3),
    ]
    assert unmatched == ["x.csv"]


def test_uuids():
    names = [f"{uuid.uuid4()}.json" for _ in range(4)]
    (p,), _ = infer_patterns(names, 3)
    assert p.pattern == "{uuid}.json"
    assert p.ranges == {"uuid": "4 distinct"}


def test_fewer_than_min_files():
    names = ["a_1.csv", "a_2.csv"]
    assert infer_patterns(names, 3) == ([], ["a_1.csv", "a_2.csv"])


def test_fallback_common_prefix():
    names = ["report final.csv", "report-draft.csv", "report_v2b.csv"]
    (p,), unmatched = infer_patterns(names, 3)
    assert p.pattern == "report{*}.csv"
    assert unmatched == []

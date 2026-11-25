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


def test_hex_tokens():
    names = ["ANON01d63767.json", "ANON0b00d147.json", "ANONffe12a90.json"]
    (p,), _ = infer_patterns(names, 3)
    assert p.pattern == "ANON{hex}.json"
    assert p.ranges == {"hex": "3 distinct"}


def test_hex_needs_digit_and_letter():
    from tuna.patterns import tokenize

    assert tokenize("facade") == [("alpha", "facade")]
    assert tokenize("added") == [("alpha", "added")]
    assert tokenize("123456") == [("digits", "123456")]


def test_uid_tokens_and_dates():
    from tuna.patterns import tokenize

    names = ["1.2.840.113619.6.95.31.json", "1.2.3.4.json", "1.2.840.10008.5.1.4.json"]
    (p,), _ = infer_patterns(names, 3)
    assert p.pattern == "{uid}.json"
    assert tokenize("01.02.2024") == [("date:DD.MM.YYYY", "01.02.2024")]


def test_paths_over_several_depths():
    paths = [f"ANON{h}/annotations.json" for h in ("01d63767", "0b00d147", "aa12bb34")]
    paths += [f"ANON{h}/1.2.840.{i}.1/properties.json" for i, h in enumerate(("01d63767", "0b00d147", "aa12bb34"))]
    paths += [f"ANON{h}/1.2.3.{i}/1.2.3.4.{i}/{i}.dcm" for i, h in enumerate(("01d63767", "0b00d147", "aa12bb34"))]
    patterns, unmatched = infer_patterns(paths, 3)
    assert sorted(p.pattern for p in patterns) == [
        "ANON{hex}/annotations.json",
        "ANON{hex}/{uid}/properties.json",
        "ANON{hex}/{uid}/{uid}/{int}.dcm",
    ]
    assert unmatched == []


def test_dotted_folder_is_no_extension():
    from tuna.patterns import split_ext

    assert split_ext("ANON1/1.2.3.4/file") == ("ANON1/1.2.3.4/file", "")
    assert split_ext("a.b/c.json") == ("a.b/c", ".json")
    assert split_ext("x/.hidden") == ("x/.hidden", "")


def test_performance_600k_paths():
    import random
    import time

    rnd = random.Random(0)
    hexes = [h for h in (f"{rnd.getrandbits(32):08x}" for _ in range(600)) if not h.isdigit()][:500]
    paths = []
    for i in range(600_000):
        h = hexes[i % 500]
        study = f"1.2.840.{i % 500}.{i % 7}"
        series = f"{study}.{i % 3}"
        paths.append(f"ANON{h}/{study}/{series}/{i}.dcm")
    start = time.perf_counter()
    patterns, _ = infer_patterns(paths, 3)
    elapsed = time.perf_counter() - start
    print(f"infer_patterns on 600k paths: {elapsed:.1f} s")
    assert patterns[0].files == 600_000
    assert elapsed < 20


def test_hex_after_word_of_other_case():
    from tuna.patterns import tokenize

    for word in ("IMAGE", "CASE", "CODE"):
        assert tokenize(f"{word}0b00d147") == [("alpha", word), ("hex", "0b00d147")]
        assert tokenize(f"{word}ffe12a90") == [("alpha", word), ("hex", "ffe12a90")]
    for word in ("image", "case", "code"):
        assert tokenize(f"{word}0B00D147") == [("alpha", word), ("hex", "0B00D147")]
        assert tokenize(f"{word}FFE12A90") == [("alpha", word), ("hex", "FFE12A90")]
    assert tokenize("deadbeef12") == [("hex", "deadbeef12")]
    assert tokenize("CASEFILE") == [("alpha", "CASEFILE")]

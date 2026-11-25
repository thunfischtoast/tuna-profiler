# Path patterns, type tolerance, file sets

Follow-up to `2026-11-25-tuna-v1.md`. Branch `feat/path-patterns` (based on `feat/rename-command`).

## Problem (from a real scan: 505 `ANON<hex>/annotations.json`, 511 `ANON<hex>/<DICOM UID>/properties.json`, 573,066 `.dcm`)

- `properties.json` split into 7 structures:
  - `""` in otherwise-int fields made them str, and str vs int splits groups.
  - Empty arrays (`structures[]` with no elements) made 16 child fields count as missing (Jaccard 0.53).
- Every folder held one file, so per-folder name patterns never fired. The report listed more than 1000 folders. `ANON01d63767` (hex) and `1.2.840.113619.6.95…` (DICOM UID) have no token.
- `.dcm` only appears as an ignored count. Its folders are invisible.

## Decisions (approved)

- A: name patterns over the whole relative path, replacing per-folder patterns. New tokens `{hex}` and `{uid}`. The Folders section is collapsed into folder-path patterns.
- B1: `""` and whitespace-only strings count as null. They are counted separately as `empty`.
- B2: type conflicts no longer split groups. They are reported as type variants per field. `--strict-types` restores the v1 behavior.
- C: if a table has `x[]` but no `x[].*` fields, the `x[].*` fields of the other side are ignored in the similarity check (both directions).
- D1: unsupported files are listed as file sets per extension, with path patterns. They are not read.
- E: renderers cap pattern rows per structure / file set (20) with "… N more".

## Steps

1. **patterns.py tokens.** Order: uuid, datetime, date, then:
   - `uid`: `\d+(?:\.\d+){3,}(?![\d.])`. It needs 3 or more dots, so `DD.MM.YYYY` stays a date.
   - `hex`: a run matching `[0-9a-f]{6,}` or `[0-9A-F]{6,}`, bounded by non-hex characters on both sides (lookarounds over `[0-9a-fA-F]`), containing at least one digit and at least one letter. Pure digits stay `digits`.

   Then the generic runs. The ranges of `{hex}`/`{uid}` are "N distinct". Tests:
   - `ANON01d63767`, `ANON0b00d147` → `ANON{hex}`
   - mixed-length UIDs → `{uid}`
   - `01.02.2024` stays a date
   - `facade`/`added` stay alpha
2. **Path patterns.**
   - `infer_patterns` takes relative posix paths. The extension is split off the last segment only: `ANON1/1.2.3.4/file` has no extension, and a dotted folder must never become an extension. Bucketing and per-position logic stay as they are. `/` is an `other` run, so it must be constant within a bucket.
   - Check that a test case with 3 depths in one call gives 3 patterns.
   - Rename the parameter and docstring from names to paths. `min_files` now applies to the whole group, not per folder.
   - **Performance gate:** time `infer_patterns` on 600k synthetic paths shaped like `ANON{hex8}/{uid}/{uid}/{int}.dcm` with 500 hex values. It must finish in under 20 s. If slower, profile and optimize the tokenizer (for example a fast path for repeated segments by caching per-segment tokens with `functools.lru_cache` on segment strings) before going on. Report the timing.
3. **B1, empty strings.**
   - `FieldStats.empty: int` is merged like `nulls`.
   - JSON/YAML collector: a str value with `.strip() == ""` → counts as null and empty, contributes type "null".
   - CSV: polars already reads empty fields as null. For whitespace-only fields, after the read, cast str columns with `pl.when(col.str.strip_chars() == "").then(None)` and count them as empty. A whitespace-only column must then be typed by its remaining values: re-infer int/float/bool/date with `str.to_integer(strict=False)` etc. only if that is simple. Otherwise leave the column as str and document it.
   - Excel: `load_sheet(..., whitespace_as_null=True)` (check what it does to `""`). Empty counts for Excel may be 0.
   - `FieldSummary.empty` (count) goes into JSON. Markdown/terminal show null% including empties, with no extra column.
4. **B2, grouping.**
   - `group_tables(tables, strict_types=False)`. Non-strict: the bucket key is the name set only, and joining checks Jaccard only. Strict: v1 behavior (families in the key plus the `compatible` check).
   - `FieldSummary.type_variants: dict[str, int]` (display type → number of tables), filled only when the members disagree on the non-null type family. Markdown/terminal show `int|str` plus `(str in 3/511)` for the minority variants.
   - CLI `--strict-types`. README.
5. **C, empty arrays.** In the similarity check, `_effective(names, other)` removes from `other` every name starting with `p + "."`, for each `p` in `names` that ends in `[]` and has no name starting with `p + "."` (and the same in the other direction). Jaccard runs on the reduced sets. Test: S2-shaped tables, one with an empty `structures[]` → one group, and its `structures[].*` fields have `present_in` < all.
6. **Report model.**
   - `Group.locations: list[Location]` is replaced by `Group.paths: list[NamePattern]` and `Group.unmatched: list[str]` (whole relative paths; xlsx members deduped per file).
   - `Group.sheets: list[str]` is set when all xlsx members share a sheet set, else `[]`. Remove `Location`.
   - `FolderSummary` is replaced by `FolderPattern(pattern: str, folders: int, contents: list[tuple[str, int]])`. Bucket folders by their content signature, which is the sorted tuple of the structure ids and file-set exts present in the folder. File counts are not part of the signature. Run `infer_patterns` on the folder paths of each bucket with `min_files`. Folders without a pattern become their own rows. `contents` sums the file counts per id over the bucket.
   - Root-level files: folder ".".
7. **D1, file sets.**
   - `discover` returns the ignored paths: `(supported: list[Path], ignored: list[Path])`. Derive the ext counter in the CLI/report.
   - `FileSet(ext: str, files: int, paths: list[NamePattern], unmatched: list[str])`. Ext is lowercased, `"(none)"` when there is no extension.
   - `Report.file_sets` is sorted by file count, descending. Their folders take part in the folder patterns of step 6, keyed by ext.
   - Excel lock files stay excluded entirely.
   - `Report.ignored` stays as is (ext → count).
8. **Renderers (terminal, Markdown).**
   - Structure blocks show `paths` (pattern, files, ranges), then unmatched (cap 10). Patterns are capped at 20 with "… N more".
   - New "File sets" section after Structures.
   - The Folders section uses `FolderPattern` rows: pattern | folders | contents.
   - JSON: dataclasses as before.
9. **README.** Update the sample output, the location/pattern explanation, `--strict-types`, empty strings as null, the empty-array rule and file sets.
10. **Manual check.** Build a synthetic tree shaped like the real one:
    - 30 `ANON<hex8>/annotations.json`
    - 30 `ANON<hex8>/<uid>/properties.json` (some with `""` in int fields, some with empty `structures[]`)
    - 3 levels of `.dcm` dummies, 2000 files

    Run the CLI. Expected: 2 structures, one `.dcm` file set with one pattern, and folder patterns collapsed into a handful of rows. Look at the terminal and Markdown output.

## Tests

- `test_patterns.py`: hex, uid, path patterns over several depths, a dotted folder without an extension, the 20-row cap does not belong here (renderer).
- `test_grouping.py`: empty-string files join, a type conflict joins with `type_variants`, `strict_types=True` splits, the empty-array rule, a tiny table does not join a large one.
- `test_readers.py`: `""` and `"  "` in JSON → null + empty; CSV whitespace-only cells.
- `test_cli.py`: update the expectations for the tree fixture (patterns over paths, `file_sets` contains `.txt`, folder patterns), `--strict-types`, the terminal renderer with file sets.
- Existing tests whose asserted behavior changes (v1 grouping on type conflicts, Location-based asserts) get adapted. List them in the report.

## Commands

- Targeted: `uv run pytest tests/<file> -q`, `uvx ruff check <files>`
- Full (main agent only): `uv run pytest -q && uvx ruff check . && uv build`

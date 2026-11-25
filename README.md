# tuna

tuna profiles the structure of a folder of data files. It reads CSV, TSV, Excel, JSON and YAML files, finds the files that share a structure and describes each structure once: its fields, their types and basic statistics, the folders it occurs in and the naming pattern of its files.

Use it to get an overview of an unfamiliar data dump, an export directory or a config tree before you write code against it.

## Install

```
uv tool install git+https://github.com/thunfischtoast/tuna-profiler
```

With pipx:

```
pipx install git+https://github.com/thunfischtoast/tuna-profiler
```

tuna needs Python 3.10 or newer.

## Usage

```
tuna-profiler PATH [options]
```

PATH is a folder or a single file. Examples:

```
tuna-profiler data/                              # summary in the terminal
tuna-profiler data/ -o report.md -o report.json  # also write Markdown and JSON
tuna-profiler data/ --full                       # statistics over all rows
tuna-profiler data/ --no-stats --max-depth 1     # schema only, top two levels
tuna-profiler data/ --exclude "archive" --include "*.csv"
```

Sample terminal output for a folder of medical image exports:

```
┌─ S2  30 files · json · 30 rows · 7 fields ────────────────────────────────────────────────┐
│ paths                                                                                     │
│ └── ANON{hex}/{uid}/properties.json  30 files  hex: 30 distinct  uid: 30 distinct         │
│ field                 type    present   null%   distinct   min   max / top                │
│ ──────────────────────────────────────────────────────────────────────────────            │
│ rows                  int         all      20          1   512   512                      │
│ modality              str         all       0          1         CT (30)                  │
│ structures[]          array       all                  0                                  │
│ structures[].name     str       22/30       0          3         s0 (22), s1 (22), ...    │
│ structures[].volume   float     22/30       0          3   0     3                        │
└───────────────────────────────────────────────────────────────────────────────────────────┘
┌─ .dcm  2000 files · not read ─────────────────────────────────────────────────────────────┐
│ paths                                                                                     │
│ └── ANON{hex}/{uid}/{uid}/{int}.dcm  2000 files  hex: 30 distinct  uid: 30 distinct  ...  │
└───────────────────────────────────────────────────────────────────────────────────────────┘
folders
├── ANON{hex}/{uid}/{uid}  60 folders  .dcm (2000)
├── ANON{hex}  30 folders  S1 (30)
└── ANON{hex}/{uid}  30 folders  S2 (30)
```

The same structure in the Markdown report:

```markdown
### S2: rows, cols, modality

30 tables in 30 files · json · 30 rows · 7 fields

| path | files | ranges |
| --- | --- | --- |
| `ANON{hex}/{uid}/properties.json` | 30 | hex: 30 distinct; uid: 30 distinct |
```

The JSON report contains the same data and also lists every member file of each structure.

## Options

| option | default | meaning |
| --- | --- | --- |
| `-o, --output FILE` | | write a report; `.md` or `.json` by extension; repeatable |
| `--full` | off | read all rows for statistics |
| `--sample-rows N` | 1000 | rows per file used for statistics |
| `--no-stats` | off | schema and row counts only |
| `--strict-types` | off | split structures when a field has conflicting types |
| `--include GLOB` | | only profile files that match; repeatable |
| `--exclude GLOB` | | skip matching files and folders; repeatable |
| `--max-depth N` | unlimited | 0 means only files directly in PATH |
| `--hidden` | off | include files and folders whose name starts with a dot |
| `--min-pattern-files N` | 3 | paths needed before tuna infers a path pattern |
| `-j, --jobs N` | CPU count | worker processes |
| `-q, --quiet` | off | no terminal output |
| `--version` | | print the version |

Globs use `fnmatch` syntax and are matched against the path relative to PATH and against the file name. Files with other extensions are not read; they are listed as file sets. tuna exits with 0 even when some files cannot be read; those files are listed as errors. Bad arguments or a missing PATH exit with 2.

## How it works

Each CSV or TSV file, each Excel sheet and each JSON or YAML file becomes one table. Nested JSON and YAML is flattened: object keys are joined with `.`, and list elements appear under `key[]`. A root list counts as one row per element. JSON strings in ISO format (`2024-01-31`, `2024-01-31T10:00`) are typed as dates.

Empty and whitespace-only strings count as null, and the null percentage includes them. The JSON report also counts them per field as `empty`, but what is counted depends on the format. For CSV, `empty` counts whitespace-only cells, because empty cells are read as plain nulls. For Excel, `empty` is always 0, because blank cells are read as nulls. For JSON and YAML, `empty` counts empty and whitespace-only strings.

Tables share a structure when they have similar field names in any order. A field whose type differs between tables (for example int in most files and str in a few) does not split the structure; the report shows the variants, as in `int|str (str in 3/511)`. With `--strict-types`, conflicting types split structures as in v1: int and float are compatible, as are date and datetime, and an all-null column is compatible with anything. A table may miss some fields of its structure, as long as the shared field names make up at least 80 % of all field names of the two (Jaccard similarity). In practice, tables with 4 fields or fewer must have exactly the same field names. With 5 to 9 fields, one missing or extra field is tolerated, and with 10 fields, two. Fields that only some tables have are shown as "present in 3/40". An empty list gives only the field `key[]` and no `key[].*` fields, so when one table has an empty `key[]`, the `key[].*` fields of the other table are left out of the comparison.

tuna looks for common patterns among the relative paths of each structure. Dates (`YYYY-MM-DD`, `YYYY_MM_DD`, `YYYYMMDD`, `DD.MM.YYYY`, `YYYY-MM`), timestamps (`YYYYMMDD_HHMMSS`), UUIDs, hex ids (`ANON01d63767` gives `ANON{hex}`), dotted ids such as DICOM UIDs (`{uid}`), numbers and words become placeholders, and the report shows the range of each placeholder. Paths that fit no pattern are listed by name. Each structure shows at most 20 patterns.

Files with unsupported extensions are grouped by extension into file sets, which get path patterns the same way. Their contents are not read.

The Folders section groups folders that hold the same structures and file sets, and shows one folder-path pattern for each such group, for example `ANON{hex}/{uid}  30 folders  S2 (30)`.

## Limits

- JSON and YAML files are parsed fully into memory. Only a root list is sampled by rows; a root object that holds a big list counts as one row, and all of its list elements are read.
- The schema of CSV files is inferred from the first `--sample-rows` rows, also with `--full`. A later value that does not fit the inferred type is read as null, and the file gets a warning. Row counts are always exact.
- An empty (0-byte) CSV file is reported as an error. A CSV file with only a header row gives fields of type null.
- Statistics come from the first N rows of each file unless `--full` is given.
- Excel stores all numbers as floats, so integer columns in Excel files appear as float.

## License

MIT, see [LICENSE](LICENSE).

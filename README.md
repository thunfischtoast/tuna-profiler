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
tuna PATH [options]
```

PATH is a folder or a single file. Examples:

```
tuna data/                              # summary in the terminal
tuna data/ -o report.md -o report.json  # also write Markdown and JSON
tuna data/ --full                       # statistics over all rows
tuna data/ --no-stats --max-depth 1     # schema only, top two levels
tuna data/ --exclude "archive" --include "*.csv"
```

Sample terminal output:

```
┌─ S1  40 files · csv · 2.0k rows · 4 fields ──────────────────────────────────────┐
│ locations                                                                        │
│ └── data/sales  40 files                                                         │
│     └── sales_{date:YYYY-MM-DD}_{int}.csv  40 files                              │
│         date:YYYY-MM-DD: 2024-02-01 .. 2024-02-28  int: 001 .. 040               │
│ field      type    present   null%   distinct   min          max / top           │
│ ──────────────────────────────────────────────────────────────────────────       │
│ order_id   int         all       0       2000   100          4049                │
│ customer   str         all       0          3                initech (694), ...  │
│ amount     float       all       0       1802   0.06         99.95               │
│ day        date        all       0         28   2024-02-01   2024-02-28          │
└──────────────────────────────────────────────────────────────────────────────────┘
```

The same structure in the Markdown report:

```markdown
### S1: order_id, customer, amount

40 tables in 40 files · csv · 2.0k rows · 4 fields

| folder | files | pattern | ranges |
| --- | --- | --- | --- |
| data/sales | 40 | `sales_{date:YYYY-MM-DD}_{int}.csv` | date:YYYY-MM-DD: 2024-02-01 .. 2024-02-28; int: 001 .. 040 |
```

The JSON report contains the same data and also lists every member file of each structure.

## Options

| option | default | meaning |
| --- | --- | --- |
| `-o, --output FILE` | | write a report; `.md` or `.json` by extension; repeatable |
| `--full` | off | read all rows for statistics |
| `--sample-rows N` | 1000 | rows per file used for statistics |
| `--no-stats` | off | schema and row counts only |
| `--include GLOB` | | only profile files that match; repeatable |
| `--exclude GLOB` | | skip matching files and folders; repeatable |
| `--max-depth N` | unlimited | 0 means only files directly in PATH |
| `--hidden` | off | include files and folders whose name starts with a dot |
| `--min-pattern-files N` | 3 | files needed in a folder before tuna infers a name pattern |
| `-j, --jobs N` | CPU count | worker processes |
| `-q, --quiet` | off | no terminal output |
| `--version` | | print the version |

Globs use `fnmatch` syntax and are matched against the path relative to PATH and against the file name. Files with other extensions are counted as ignored. tuna exits with 0 even when some files cannot be read; those files are listed as errors. Bad arguments or a missing PATH exit with 2.

## How it works

Each CSV or TSV file, each Excel sheet and each JSON or YAML file becomes one table. Nested JSON and YAML is flattened: object keys are joined with `.`, and list elements appear under `key[]`. A root list counts as one row per element. JSON strings in ISO format (`2024-01-31`, `2024-01-31T10:00`) are typed as dates.

Tables share a structure when they have similar field names in any order and compatible types. int and float are compatible, as are date and datetime, and an all-null column is compatible with anything. A table may miss some fields of its structure, as long as the shared field names make up at least 80 % of all field names of the two (Jaccard similarity). In practice, tables with 4 fields or fewer must have exactly the same field names. With 5 to 9 fields, one missing or extra field is tolerated, and with 10 fields, two. Fields that only some tables have are shown as "present in 3/40".

Within a folder, tuna looks for a common name pattern among the files of one structure. Dates (`YYYY-MM-DD`, `YYYY_MM_DD`, `YYYYMMDD`, `DD.MM.YYYY`, `YYYY-MM`), timestamps (`YYYYMMDD_HHMMSS`), UUIDs, numbers and words become placeholders, and the report shows the range of each placeholder. Files that fit no pattern are listed by name.

## Limits

- JSON and YAML files are parsed fully into memory. Only a root list is sampled by rows; a root object that holds a big list counts as one row, and all of its list elements are read.
- The schema of CSV files is inferred from the first `--sample-rows` rows, also with `--full`. A later value that does not fit the inferred type is read as null, and the file gets a warning. Row counts are always exact.
- An empty (0-byte) CSV file is reported as an error. A CSV file with only a header row gives fields of type null.
- Statistics come from the first N rows of each file unless `--full` is given.
- Excel stores all numbers as floats, so integer columns in Excel files appear as float.

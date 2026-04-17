# Get Modem IPv4 Address

Queries the Cradlepoint NetCloud Manager (NCM) APIv2 to retrieve modem IDs and current IPv4
addresses for all devices in one or more groups.  Results are written to a CSV file.  A matching
log file is produced for every run.

---

## Requirements

| Dependency | Install |
|---|---|
| `requests` | `python3 -m pip install requests` |

The `ncm` library is included with this release.

---

## API Keys

API keys must be available before the script runs.  They are loaded in the following priority order:

1. **OS environment variables** — set the variables below in your shell profile or session:

    ```
    X_CP_API_ID
    X_CP_API_KEY
    X_ECM_API_ID
    X_ECM_API_KEY
    ```

2. **`settings.py`** — create a `settings.py` file in the same directory as the script with a
   dictionary named `api_keys`:

    ```python
    api_keys = {
        'X-CP-API-ID':  'your-id',
        'X-CP-API-KEY': 'your-key',
        'X-ECM-API-ID': 'your-id',
        'X-ECM-API-KEY': 'your-key',
    }
    ```

---

## Usage

```
python3 get_modem_ipv4_address.py [options]
```

At least one of `--group-names` or `--group-ids` is required.

### Arguments

| Argument | Short | Description |
|---|---|---|
| `--group-names` | `-g` | Comma-separated list of NCM group names. Group names are case-sensitive. Enclose in double quotes if a name contains spaces. |
| `--group-ids` | `-i` | Comma-separated list of NCM group IDs. |
| `--return-all-modems` | `-r` | Include modems with no IPv4 address in the CSV output. Default behavior excludes them. |
| `--verbose` | `-v` | Enable DEBUG logging to the log file. |
| `--log-level` | `-l` | Explicit log level: `debug`, `info`, `warning`, `error`, or `critical`. Overrides `--verbose`. |
| `--version` | `-V` | Print the script version and exit. |

### Examples

```
python3 get_modem_ipv4_address.py --group-names="API Testing"

python3 get_modem_ipv4_address.py --group-ids=568379,568380 --verbose

python3 get_modem_ipv4_address.py \
  --group-names="API Testing,Field Devices" \
  --group-ids=568379 \
  --return-all-modems \
  --log-level=debug
```

---

## Output

### Directory Structure

Output files are written to subdirectories under `output/`:

```
output/
├── csv/    ← CSV reports
└── logs/   ← Log files
```

Both output files share an identical timestamp (`YYYY-MM-DD_HH-MM-SS`) captured at startup so
every CSV can always be matched to its corresponding log file.

| File | Location | Pattern | Description |
|---|---|---|---|
| CSV | `output/csv/` | `<script_name>_<timestamp>.csv` | Row 1: script version. Row 2: column headers. Row 3+: data. |
| Log | `output/logs/` | `<script_name>_<timestamp>.log` | Full log of the run at the configured log level. First entry is the script version. |

Example output pair:

```
output/csv/get_modem_ipv4_address_2026-04-17_14-30-00.csv
output/logs/get_modem_ipv4_address_2026-04-17_14-30-00.log
```

### CSV Columns

| Column | Description |
|---|---|
| Device Id | NCM device ID |
| Device Name | Device name in NCM |
| Serial Number | Device serial number |
| Product | Full product name (e.g. W1855-8ec, IBR1700-1200M) |
| Group | NCM group name the device belongs to |
| Modem Id | NCM net device ID for the modem |
| Modem Name | Modem interface name (e.g. mdm-xxxxxxxx) |
| Ipv4 Address | Current IPv4 address assigned to the modem |
| Mode | Interface mode (e.g. wan) |
| Connection State | Current connection state (e.g. connected) |

By default, modems with no IPv4 address are excluded from the CSV.  Use `--return-all-modems`
to include them.

---

## Classes

---

### `GetModemIPv4Address`

Main class.  Orchestrates API queries, data assembly, and output.

#### Class Attributes

| Attribute | Description |
|---|---|
| `apiv2` | Base URL for the Cradlepoint NCM APIv2. |
| `all_routers` | Dictionary keyed by device ID that accumulates device and modem data. |
| `red`, `green`, … `reset` | ANSI terminal color codes used for console output. |

#### `__init__(group_names, group_ids, return_all_modems, verbose, log_level)`

Initializes the object.  Captures `self.timestamp` at startup (used by both the log file and CSV
filename), loads and validates API keys, configures logging, authenticates against the API, and
stores all user-supplied filters.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `group_names` | `list[str]` | `None` | NCM group names. |
| `group_ids` | `list[str]` | `None` | NCM group IDs. |
| `return_all_modems` | `bool` | `False` | When `True`, include modems with no IPv4 address in the CSV. |
| `verbose` | `bool` | `False` | Enables DEBUG logging when `log_level` is not set. |
| `log_level` | `str` | `None` | Explicit log level string; overrides `verbose`. |

#### `_load_api_keys()` *(static)*

Loads the four required Cradlepoint API keys.  Checks OS environment variables first, then falls
back to `settings.py`.  Raises `LogThenSystemExit` if any key is missing.

#### `can_write_to_log_file()`

Tests whether the log file path is writable by attempting to open it in append mode.  Creates
parent directories if they do not exist.  Returns `True` on success; logs a warning and returns
`False` on `PermissionError` or `OSError`.

#### `_make_request(method, url, **kwargs)`

Central wrapper for all outbound HTTP requests.  Passes the call through to the `requests.Session`
object and catches `requests.exceptions.ConnectionError`, exiting with a user-friendly message if
the host cannot be reached.

#### `get_group_id_from_group_name(group_name)`

Looks up a group by name and returns its integer ID.  Returns `None` and logs a failure message
if the group is not found.

#### `get_group_name_from_group_id(group_id)`

Looks up a group by ID and returns its name string.  Returns `None` if the API returns a non-`2xx`
response; returns `'UNKNOWN'` if the response is `2xx` but does not contain a `name` key.

#### `get_routers_in_group_ids()`

For each group ID in `self.group_ids`, validates that the group exists via
`get_group_name_from_group_id()` before querying the NCM library.  Raises `LogThenSystemExit`
if the group ID is not found or if the group contains no devices.

#### `get_routers_in_group_names()`

For each group name in `self.group_names`, resolves the group ID via
`get_group_id_from_group_name()`.  Raises `LogThenSystemExit` if the group name is not found
(including a case-sensitivity reminder).

#### `compile_modem_data()`

Iterates over `self.all_routers` and, for each device, fetches its modem interfaces via the NCM
library's `get_net_devices_for_router()` with `is_asset=True`.  Extracts the modem ID, name,
IPv4 address, mode, and connection state for each modem.  By default, modems with no IPv4 address
are skipped (logged at DEBUG level).  Set `return_all_modems=True` to include them.

#### `parse_log_level()`

Converts `self.log_level` (a string) to the corresponding `logging` integer constant.  Falls back
to `WARNING` for invalid values.  If no explicit level is given, uses `DEBUG` when `--verbose` is
set, otherwise defaults to `INFO`.

#### `run()`

Main entry point called after construction.  Dispatches to the appropriate group fetch methods,
calls `compile_modem_data()`, and finally calls `write_to_csv()`.

#### `setup_logging()`

Configures the root logger with up to two handlers:

- **File handler** — writes at the selected log level with timestamps; ANSI color codes are stripped
  via `StripAnsiFilter`.
- **Console handler** — always present; limited to `INFO` and above when a file handler exists;
  filtered by `ConsoleFilter`.

#### `verify_api_authentication()`

Makes a test `GET` request to `/api/v2/products/` to confirm the supplied API keys are valid.
Raises `LogThenSystemExit` on failure.

#### `write_to_csv()`

Flattens `self.all_routers` into a list of rows (one per device/modem combination) and writes
them to a CSV file in `output/csv/` using Python's native `csv` module.  The first row contains
the script version.

---

### `StripAnsiFilter`

A `logging.Filter` subclass attached to the file handler.  Strips ANSI terminal color codes and
leading whitespace from log record messages.

---

### `ConsoleFilter`

A `logging.Filter` subclass attached to the console handler.  Blocks `urllib3` messages and
records logged with `extra={'file_only': True}` from reaching the console.

---

### `LogThenSystemExit`

A `SystemExit` subclass that writes the exit message to the log before terminating.  Accepts
an optional `exc_info` keyword argument to log a full traceback.

---

### `CustomArgParse`

An `argparse.ArgumentParser` subclass with `allow_abbrev=False` that detects unquoted spaces in
argument values and provides corrected command examples to the user.  Prefix matching is disabled
so typos like `--group-name` (missing the 's') are properly rejected instead of silently matching
`--group-names`.

---

## Changelog

### v1.0.0

- Initial release.
- Accepts group names (`--group-names`) and/or group IDs (`--group-ids`) as input.
- Queries the NCM APIv2 groups endpoint to find all devices in the specified group(s).
- For each device, queries the net devices endpoint (`is_asset=True`) to retrieve modem IDs and current IPv4 addresses.
- By default, modems with no IPv4 address are excluded from the CSV.  Use `--return-all-modems` / `-r` to include them.
- Outputs CSV reports to `output/csv/` and log files to `output/logs/`.
- Uses native Python `csv` module (no pandas dependency).
- API key loading from environment variables with fallback to `settings.py`.
- Dual logging (file + console) with ANSI stripping for log files.
- `CustomArgParse` subclass with `allow_abbrev=False` and unquoted-space detection.

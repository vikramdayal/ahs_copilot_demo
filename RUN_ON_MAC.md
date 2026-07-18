# Running AHS Copilot on macOS

This guide runs the AHS 2023 governed DuckDB research engine on macOS using a project-local Python virtual environment. It applies to both Apple Silicon (`arm64`) and Intel (`x86_64`) Macs.

The repository requires Python 3.11 or newer. Python 3.12 is recommended for a predictable local setup.

## 1. Open Terminal and enter the repository

If you downloaded `ahs_copilot_day3.zip`, extract it and enter the repository directory:

```bash
cd "$HOME/Downloads"
unzip ahs_copilot_day3.zip
cd ahs_copilot_day3
```

If the repository is elsewhere, replace the path accordingly. All remaining commands must be run from the repository root—the directory containing `pyproject.toml`, `config/`, `src/`, and `tests/`.

Confirm the location:

```bash
pwd
ls pyproject.toml config src tests
```

## 2. Confirm Mac and toolchain architecture

Determine whether the Mac is Apple Silicon or Intel:

```bash
uname -m
```

Expected output:

- `arm64` — Apple Silicon
- `x86_64` — Intel Mac, or a Terminal process running under Rosetta

Check the current shell architecture, Homebrew location, and Python architecture:

```bash
printf 'Machine: '; uname -m
printf 'Shell: '; echo "$SHELL"
command -v brew || true
command -v python3 || true
python3 -c 'import platform, sys; print("Python:", sys.executable); print("Python architecture:", platform.machine()); print("Python version:", platform.python_version())' 2>/dev/null || true
```

For a native Apple Silicon setup, Homebrew normally resolves under `/opt/homebrew`. For a native Intel setup, it normally resolves under `/usr/local`. Do not combine an Intel Homebrew Python with native ARM packages, or an ARM Python with Intel packages. A virtual environment inherits the architecture of the Python used to create it.

## 3. Install Python

### Option A: Homebrew

Confirm Homebrew is usable:

```bash
brew --version
brew --prefix
```

Install Python 3.12:

```bash
brew install python@3.12
```

Resolve the exact interpreter without hard-coding the Homebrew prefix:

```bash
PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
"$PYTHON_BIN" --version
"$PYTHON_BIN" -c 'import platform, sys; print(sys.executable); print(platform.machine())'
```

The Python architecture should match `uname -m` unless you intentionally run the entire toolchain under Rosetta.

### Option B: Existing Python 3.11 or newer

Check the version:

```bash
python3 --version
```

Use it only when the version is at least 3.11 and its architecture matches the Terminal architecture:

```bash
python3 -c 'import platform, sys; print(sys.executable); print(platform.machine())'
PYTHON_BIN="$(command -v python3)"
```

### Optional compiler tools

DuckDB and Pydantic normally install from prebuilt wheels. If `pip` reports that compiler tools are missing, install Apple's Command Line Tools:

```bash
xcode-select --install
```

After the installer completes, reopen Terminal and continue.

## 4. Create and activate a virtual environment

From the repository root:

```bash
rm -rf .venv
"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate
```

Verify that the active Python is inside the repository and has the expected architecture:

```bash
which python
python --version
python -c 'import platform, sys; print(sys.executable); print(platform.machine())'
```

The executable path should end in `ahs_copilot_day3/.venv/bin/python`.

Every new Terminal session must reactivate the environment:

```bash
cd /path/to/ahs_copilot_day3
source .venv/bin/activate
```

Exit the environment with:

```bash
deactivate
```

## 5. Install the project

Upgrade packaging tools, then install the repository in editable mode with test dependencies:

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[dev]'
python -m pip check
```

Keep the quotes around `'.[dev]'`. The default macOS shell, Zsh, otherwise may interpret the brackets as a filename pattern.

Expected dependency-check result:

```text
No broken requirements found.
```

Confirm that both command-line programs were installed:

```bash
ahs-query --help
ahs-plan --help
```

## 6. Run the automated verification checkpoint

Compile the Python modules:

```bash
python -m compileall -q src tests
```

Run the critical AnalysisPlan tests:

```bash
python -m pytest tests/test_analysis_plan.py -ra
```

Run the full regression suite:

```bash
python -m pytest -ra
```

The repository checkpoint recorded:

```text
11 passed  # critical AnalysisPlan tests
32 passed  # full regression suite
```

Minor timing differences on a Mac are expected. A different number of collected tests means the repository contents differ from this checkpoint.

## 7. Run with the deterministic synthetic fixture

No real AHS CSV files are required for the first run. The example configuration uses `fixture.mode = "auto"`, which creates deterministic household, mortgage, and projects CSVs when configured real files are absent.

Inspect the resolved datasets and inferred schemas:

```bash
ahs-query inspect \
  --config config/ahs_engine.example.toml \
  --output sample_outputs/mac_schema_inspection.json
```

Validate an AnalysisPlan without generating SQL:

```bash
ahs-plan \
  --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_high_burden_by_tenure.json \
  --action validate \
  > sample_outputs/mac_validated_plan.json
```

Compile the validated plan to deterministic parameterized SQL:

```bash
ahs-plan \
  --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_high_burden_by_tenure.json \
  --action compile \
  > sample_outputs/mac_compiled_plan.json
```

Execute the plan:

```bash
ahs-plan \
  --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_high_burden_by_tenure.json \
  --action execute \
  > sample_outputs/mac_executed_plan.json
```

Run the lower-level descriptive survey example:

```bash
ahs-query survey-run \
  examples/survey_tenure_comparison.json \
  --config config/ahs_engine.example.toml \
  --output sample_outputs/mac_survey_tenure_comparison.json
```

Review any JSON output with the built-in macOS tools:

```bash
python -m json.tool sample_outputs/mac_executed_plan.json | less
```

The outputs are descriptive estimates only. The code does not implement replicate-weight variance estimation and must not be used to claim valid standard errors, confidence intervals, p-values, or statistical significance.

## 8. Configure real AHS CSV files

Create a working configuration:

```bash
cp config/ahs_engine.example.toml config/ahs_engine.toml
```

Set absolute paths to the three CSV files. Quoting is important when a path contains spaces:

```bash
export AHS_HOUSEHOLD_CSV="$HOME/Data/AHS-2023/household.csv"
export AHS_MORTGAGE_CSV="$HOME/Data/AHS-2023/mortgage.csv"
export AHS_PROJECTS_CSV="$HOME/Data/AHS-2023/projects.csv"
```

Confirm that the files exist:

```bash
ls -lh "$AHS_HOUSEHOLD_CSV" "$AHS_MORTGAGE_CSV" "$AHS_PROJECTS_CSV"
```

For a production-style fail-closed run, edit `config/ahs_engine.toml` and change:

```toml
[fixture]
mode = "disabled"
```

Then inspect the real schemas before executing a plan:

```bash
ahs-query inspect \
  --config config/ahs_engine.toml \
  --output sample_outputs/real_schema_inspection.json
```

If a required file is absent, the engine should stop instead of silently using synthetic data when fixture mode is `disabled`.

Environment variables apply only to the current Terminal session. To preserve them, add the `export` commands to a private shell configuration file or a local startup script that is not committed to source control. Do not commit protected or restricted data paths, credentials, or AHS data.

## 9. Large-CSV settings on a Mac

DuckDB scans the CSV files directly and does not load the entire dataset into a pandas DataFrame. The example configuration is intentionally conservative:

```toml
[engine]
memory_limit = "512MB"
temp_directory = "../.duckdb_tmp"
threads = 4
preserve_insertion_order = false
```

For large files:

1. Keep the repository and DuckDB temporary directory on a local SSD when possible.
2. Ensure the temporary directory has enough free disk space for spill files.
3. Avoid an iCloud-synchronized directory for DuckDB temporary files.
4. Increase `memory_limit` only when the Mac has sufficient free memory.
5. Set `threads` to a reasonable value for the machine; more threads can increase memory and I/O pressure.
6. Keep `preserve_insertion_order = false` unless row-order preservation is explicitly required.

Check free disk space:

```bash
df -h .
du -sh .duckdb_tmp 2>/dev/null || true
```

To place DuckDB spill files in a dedicated local directory, create it:

```bash
mkdir -p "$HOME/Library/Caches/ahs-copilot/duckdb"
```

Then set an absolute path in `config/ahs_engine.toml`:

```toml
[engine]
temp_directory = "/Users/YOUR_USERNAME/Library/Caches/ahs-copilot/duckdb"
```

Replace `YOUR_USERNAME` with the output of `whoami`.

## 10. Common macOS problems

### `zsh: no matches found: .[dev]`

Quote the editable-install target:

```bash
python -m pip install -e '.[dev]'
```

### `command not found: ahs-query` or `ahs-plan`

Activate the project virtual environment and reinstall:

```bash
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

You can also invoke the installed scripts explicitly:

```bash
.venv/bin/ahs-query --help
.venv/bin/ahs-plan --help
```

### `ModuleNotFoundError: No module named 'ahs_copilot'`

Run the editable installation from the repository root:

```bash
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

### Architecture or dynamic-library errors

Symptoms may include an incompatible architecture message, a failed native-module import, or a reference to `arm64` versus `x86_64`.

Inspect the complete chain:

```bash
uname -m
command -v brew && brew --prefix
which python
python -c 'import platform, sys; print(sys.executable); print(platform.machine())'
file "$(which python)"
```

On Apple Silicon, a native Homebrew installation normally uses `/opt/homebrew`; `/usr/local` commonly indicates an Intel/Rosetta installation. Choose one architecture, delete the old virtual environment, and recreate it with a matching Python:

```bash
rm -rf .venv
PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[dev]'
```

### CSV files are not found

Print the configured environment variables:

```bash
printf '%s\n' "$AHS_HOUSEHOLD_CSV" "$AHS_MORTGAGE_CSV" "$AHS_PROJECTS_CSV"
```

Verify each path with `ls -lh`. Use `config/ahs_engine.example.toml` and fixture mode `auto` for a synthetic smoke test, or use `config/ahs_engine.toml` with fixture mode `disabled` for a fail-closed real-data run.

### DuckDB cannot write its temporary directory

Create the directory and confirm ownership:

```bash
mkdir -p .duckdb_tmp
chmod u+rwx .duckdb_tmp
ls -ld .duckdb_tmp
```

Alternatively, configure an absolute writable path under `$HOME/Library/Caches` as described above.

### Rebuild the environment from scratch

```bash
deactivate 2>/dev/null || true
rm -rf .venv
PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[dev]'
python -m pip check
python -m pytest -ra
```

## 11. Recommended repeatable run sequence

Use this sequence after the first installation:

```bash
cd /path/to/ahs_copilot_day3
source .venv/bin/activate
python -m pip check
python -m pytest tests/test_analysis_plan.py -ra
ahs-plan \
  --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_high_burden_by_tenure.json \
  --action execute \
  > sample_outputs/mac_executed_plan.json
python -m json.tool sample_outputs/mac_executed_plan.json | less
```

For real AHS data, replace `config/ahs_engine.example.toml` with `config/ahs_engine.toml` after setting the three CSV environment variables and disabling fixture fallback.

## 12. Security and statistical boundaries

- Do not add a raw SQL field to `AnalysisPlan`, `SurveyEstimateRequest`, or `QuerySpec`.
- Do not bypass `AnalysisPlanService` for natural-language-generated plans.
- Do not directly join mortgage and projects data.
- Mortgage and projects rows must be preaggregated to `CONTROL` before joining to household records.
- Keep real AHS files outside the repository and source-control history.
- Treat all current survey outputs as deterministic descriptive weighted estimates.
- Do not claim valid variance estimates until approved replicate weights and a certified variance method are implemented and tested.

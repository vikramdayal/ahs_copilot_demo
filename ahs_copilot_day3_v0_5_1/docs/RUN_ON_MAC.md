# Running v0.5.1 on macOS

```bash
cd ahs_copilot_day3_v0_5_1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[dev]'
python -m pytest -ra
```

Configure real files:

```bash
export AHS_HOUSEHOLD_CSV="$HOME/Data/AHS-2023/household.csv"
export AHS_MORTGAGE_CSV="$HOME/Data/AHS-2023/mortgage.csv"
export AHS_PROJECTS_CSV="$HOME/Data/AHS-2023/projects.csv"

ahs-query inspect \
  --config config/ahs_engine.toml \
  --output sample_outputs/real_schema_inspection.json
```

The project file needs `CONTROL`; it does not need `PROJECTNO`.

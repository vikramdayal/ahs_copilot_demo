from __future__ import annotations

import csv
from pathlib import Path


HOUSEHOLD_ROWS = [
    {"CONTROL": "1001", "INTSTATUS": "1", "TENURE": "1", "WEIGHT": "10.0", "SP1WEIGHT": "8.0", "OMB13CBSA": "35620", "TOTHCAMT": "2200", "HINCP": "96000", "TOTHCPCT": "28", "ADEQUACY": "1", "BLD": "2", "HIMOVFRC": "5", "HIWORRY": "1"},
    {"CONTROL": "1002", "INTSTATUS": "1", "TENURE": "2", "WEIGHT": "20.0", "SP1WEIGHT": "18.0", "OMB13CBSA": "35620", "TOTHCAMT": "1800", "HINCP": "42000", "TOTHCPCT": "51", "ADEQUACY": "2", "BLD": "5", "HIMOVFRC": "2", "HIWORRY": "4"},
    {"CONTROL": "1003", "INTSTATUS": "1", "TENURE": "3", "WEIGHT": "7.0", "SP1WEIGHT": "6.0", "OMB13CBSA": "35620", "TOTHCAMT": "0", "HINCP": "18000", "TOTHCPCT": "0", "ADEQUACY": "3", "BLD": "5", "HIMOVFRC": "1", "HIWORRY": "5"},
    {"CONTROL": "1004", "INTSTATUS": "2", "TENURE": "", "WEIGHT": "5.0", "SP1WEIGHT": "0", "OMB13CBSA": "33100", "TOTHCAMT": "", "HINCP": "-6", "TOTHCPCT": "-6", "ADEQUACY": "", "BLD": "2", "HIMOVFRC": "", "HIWORRY": ""},
    {"CONTROL": "1005", "INTSTATUS": "1", "TENURE": "2", "WEIGHT": "15.0", "SP1WEIGHT": "14.0", "OMB13CBSA": "33100", "TOTHCAMT": "1500", "HINCP": "54000", "TOTHCPCT": "33", "ADEQUACY": "1", "BLD": "3", "HIMOVFRC": "4", "HIWORRY": "2"},
    {"CONTROL": "1006", "INTSTATUS": "1", "TENURE": "2", "WEIGHT": "12.0", "SP1WEIGHT": "11.0", "OMB13CBSA": "33100", "TOTHCAMT": "2100", "HINCP": "36000", "TOTHCPCT": "70", "ADEQUACY": "2", "BLD": "7", "HIMOVFRC": "2", "HIWORRY": "5"},
    {"CONTROL": "1007", "INTSTATUS": "1", "TENURE": "1", "WEIGHT": "11.0", "SP1WEIGHT": "10.0", "OMB13CBSA": "33100", "TOTHCAMT": "1700", "HINCP": "84000", "TOTHCPCT": "24", "ADEQUACY": "1", "BLD": "2", "HIMOVFRC": "5", "HIWORRY": "1"},
    {"CONTROL": "1008", "INTSTATUS": "3", "TENURE": "", "WEIGHT": "4.0", "SP1WEIGHT": "0", "OMB13CBSA": "", "TOTHCAMT": "", "HINCP": "", "TOTHCPCT": "", "ADEQUACY": "", "BLD": "1", "HIMOVFRC": "", "HIWORRY": ""},
]

MORTGAGE_ROWS = [
    {"CONTROL": "1001", "MORTLINE": "1", "MORTAMT": "180000", "MORTTYPE": "1"},
    {"CONTROL": "1001", "MORTLINE": "2", "MORTAMT": "25000", "MORTTYPE": "2"},
    {"CONTROL": "1007", "MORTLINE": "1", "MORTAMT": "120000", "MORTTYPE": "1"},
]

# CONTROL is the only certified PUF projects relationship key. No synthetic
# project-row identifier is invented; duplicate CONTROL values intentionally
# model a one-to-many child relation that must be preaggregated before joining.
PROJECT_ROWS = [
    {"CONTROL": "1001", "PROJECTCOST": "12000", "PROJECTTYPE": "ROOF"},
    {"CONTROL": "1001", "PROJECTCOST": "4500", "PROJECTTYPE": "HVAC"},
    {"CONTROL": "1002", "PROJECTCOST": "900", "PROJECTTYPE": "PAINT"},
    {"CONTROL": "1007", "PROJECTCOST": "8000", "PROJECTTYPE": "KITCHEN"},
]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _header_matches(path: Path, rows: list[dict[str, str]]) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = next(reader)
    except (OSError, StopIteration, UnicodeError):
        return False
    return header == list(rows[0])


def create_synthetic_fixture(directory: str | Path, *, overwrite: bool = False) -> dict[str, Path]:
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    targets = {
        "household": output / "household.csv",
        "mortgage": output / "mortgage.csv",
        "projects": output / "projects.csv",
    }
    payloads = {
        "household": HOUSEHOLD_ROWS,
        "mortgage": MORTGAGE_ROWS,
        "projects": PROJECT_ROWS,
    }
    for name, path in targets.items():
        rows = payloads[name]
        if overwrite or not _header_matches(path, rows):
            _write_csv(path, rows)
    return targets

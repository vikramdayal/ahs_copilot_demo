from pathlib import Path
import pytest
from ahs_copilot.query_engine import AHSQueryEngine

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def config_path():
    return ROOT / "config" / "ahs_engine.example.toml"

@pytest.fixture
def engine(config_path):
    with AHSQueryEngine(config_path) as value:
        yield value

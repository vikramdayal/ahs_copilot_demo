import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from ahs_copilot.query_engine import QuerySpec
from ahs_copilot.query_engine.errors import QueryValidationError

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    return QuerySpec.model_validate_json((ROOT / "examples" / name).read_text())

def test_raw_sql_property_rejected():
    with pytest.raises(ValidationError):
        QuerySpec.model_validate({"base_dataset":"household","columns":[{"column":"CONTROL"}],"sql":"select 1"})

def test_typed_filter_execution(engine):
    result = engine.execute(load("household_filter.json"))
    assert result.row_count == 5
    assert all(row["CONTROL"].startswith("H") for row in result.rows)
    assert result.compiled.parameters == [1]

def test_project_join_preaggregates_to_control(engine):
    result = engine.execute(load("household_with_project_aggregation.json"))
    sql = result.compiled.sql.upper()
    assert "GROUP BY" in sql
    assert "CONTROL" in sql
    assert "PROJECTNO" not in sql
    h1 = next(x for x in result.rows if x["CONTROL"] == "H001")
    assert h1["project_count"] == 2
    assert float(h1["total_project_cost"]) == 3400.0
    assert result.compiled.relationship_ids == ["rel_household_projects_control"]

def test_mortgage_to_projects_is_not_approved(engine):
    spec = QuerySpec.model_validate({
      "base_dataset":"mortgage",
      "columns":[{"column":"CONTROL"}],
      "joins":[{"relationship_id":"rel_household_projects_control","aggregates":[{"function":"count","alias":"n"}]}]
    })
    with pytest.raises(QueryValidationError, match="cannot be used from base dataset"):
        engine.compile(spec)

def test_unknown_column_rejected(engine):
    spec = QuerySpec.model_validate({"base_dataset":"household","columns":[{"column":"DOES_NOT_EXIST"}]})
    with pytest.raises(QueryValidationError, match="Unknown column"):
        engine.compile(spec)

def test_result_limit_is_capped(engine):
    spec = QuerySpec.model_validate({"base_dataset":"household","columns":[{"column":"CONTROL"}],"limit":10001})
    with pytest.raises(QueryValidationError, match="exceeds"):
        engine.compile(spec)

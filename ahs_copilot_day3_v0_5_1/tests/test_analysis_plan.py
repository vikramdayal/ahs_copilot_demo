import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from ahs_copilot.analysis_plan import AnalysisPlan, AnalysisPlanService, AnalysisPlanValidationError

ROOT = Path(__file__).resolve().parents[1]

def valid_plan():
    return AnalysisPlan.model_validate_json((ROOT / "examples/analysis_plan_high_burden_by_tenure.json").read_text())

def test_valid_plan_compiles_and_executes(engine):
    service = AnalysisPlanService(engine)
    validated = service.validate(valid_plan())
    assert set(validated.required_variable_closure) == {"INTSTATUS","TENURE","TOTHCPCT","WEIGHT"}
    output = service.execute(valid_plan())
    assert output["result"]["variance"]["status"] == "NOT_ESTIMATED"

def test_required_variable_closure_enforced(engine):
    plan = valid_plan().model_copy(update={"required_variables":["INTSTATUS"]})
    with pytest.raises(AnalysisPlanValidationError) as exc:
        AnalysisPlanService(engine).validate(plan)
    assert any(x.code == "REQUIRED_VARIABLE_CLOSURE_INCOMPLETE" for x in exc.value.issues)

def test_unknown_variable_rejected(engine):
    plan = valid_plan().model_copy(update={"grouping_dimensions":["FAKE"],"required_variables":["INTSTATUS","TOTHCPCT","WEIGHT","FAKE"]})
    with pytest.raises(AnalysisPlanValidationError) as exc:
        AnalysisPlanService(engine).validate(plan)
    assert any(x.code == "UNKNOWN_VARIABLE" for x in exc.value.issues)

def test_iuf_variable_rejected(engine):
    plan = valid_plan().model_copy(update={"grouping_dimensions":["IUF_ONLY_STATE_CODE"],"required_variables":["INTSTATUS","TOTHCPCT","WEIGHT","IUF_ONLY_STATE_CODE"]})
    with pytest.raises(AnalysisPlanValidationError) as exc:
        AnalysisPlanService(engine).validate(plan)
    assert any(x.code == "IUF_VARIABLE_REJECTED" for x in exc.value.issues)

def test_iuf_recode_rejected(engine):
    plan = valid_plan().model_copy(update={"derived_recodes":["iuf_state_group_v1"],"required_variables":["INTSTATUS","TENURE","TOTHCPCT","WEIGHT","IUF_ONLY_STATE_CODE"]})
    with pytest.raises(AnalysisPlanValidationError) as exc:
        AnalysisPlanService(engine).validate(plan)
    assert any(x.code == "IUF_RECODE_REJECTED" for x in exc.value.issues)

def test_raw_sql_rejected():
    payload = json.loads((ROOT / "examples/analysis_plan_high_burden_by_tenure.json").read_text())
    payload["sql"] = "select * from household"
    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(payload)

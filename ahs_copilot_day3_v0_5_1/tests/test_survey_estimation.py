from ahs_copilot.survey_estimation import Condition, SurveyEstimateRequest, SurveyEstimator

def test_weighted_percentage_by_tenure(engine):
    request = SurveyEstimateRequest(
        dataset="household",
        measure="percentage",
        universe_id="occupied_housing_units",
        numerator_conditions=[Condition(variable="TOTHCPCT", operator="gt", value=50)],
        denominator_conditions=[Condition(variable="TOTHCPCT", operator="gt", value=0)],
        grouping_dimensions=["TENURE"],
        weight_id="final_household_weight",
    )
    result = SurveyEstimator(engine).execute(request)
    by_tenure = {int(x["groups"]["TENURE"]): x for x in result.estimates}
    assert round(by_tenure[2]["estimate"], 6) == round((1200+1300)/(1200+900+1300)*100, 6)
    assert by_tenure[1]["estimate"] == 0.0
    assert result.variance["status"] == "NOT_ESTIMATED"
    assert result.variance["standard_errors_valid"] is False

def test_unweighted_count(engine):
    request = SurveyEstimateRequest(
        measure="count",
        universe_id="renter_occupied_housing_units",
        weight_id="unit_weight",
    )
    result = SurveyEstimator(engine).execute(request)
    assert result.estimates[0]["estimate"] == 3.0

def test_empty_denominator_flagged(engine):
    request = SurveyEstimateRequest(
        measure="percentage",
        universe_id="occupied_housing_units",
        numerator_conditions=[Condition(variable="TENURE", operator="eq", value=99)],
        denominator_conditions=[Condition(variable="TENURE", operator="eq", value=99)],
        weight_id="final_household_weight",
    )
    estimate = SurveyEstimator(engine).execute(request).estimates[0]
    assert estimate["estimate"] is None
    assert "EMPTY_DENOMINATOR" in estimate["flags"]

def test_mean_excludes_declared_missing_codes(engine):
    request = SurveyEstimateRequest(
        measure="mean",
        universe_id="all_housing_units",
        value_variable="HINCP",
        weight_id="unit_weight",
    )
    result = SurveyEstimator(engine).execute(request)
    expected = (36000+60000+120000+48000+80000)/5
    assert result.estimates[0]["estimate"] == expected

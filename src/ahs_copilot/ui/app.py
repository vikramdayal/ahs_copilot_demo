from __future__ import annotations

import html
import json
import os
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import altair as alt
import pandas as pd
import streamlit as st

from .support import (
    COMPARISON_DIMENSIONS,
    SUGGESTED_QUESTIONS,
    TENURE_LABELS,
    YEAR_BUILT_PRESETS,
    BlockedRequest,
    approved_catalog_columns,
    build_comparison_plan,
    comparison_cache_key,
    comparison_capabilities,
    comparison_selections_from_plan,
    format_estimate,
    group_label,
    object_to_json_bytes,
    plan_summary,
    records_to_csv,
    resolve_demo_question,
    result_records,
    to_plain,
)

APP_VERSION = "0.9.0"
PROVIDER_DEMO = "No-network certified demo"
PROVIDER_OPENAI = "OpenAI / OpenAI-compatible"
PROVIDER_ANTHROPIC = "Anthropic"
PROVIDER_BEDROCK = "AWS Bedrock"


@dataclass
class RuntimeBundle:
    engine: Any
    workflow: Any
    provider: str
    config_path: str

    def close(self) -> None:
        close = getattr(self.engine, "close", None)
        if callable(close):
            close()


def _set_page() -> None:
    st.set_page_config(
        page_title="AHS 2023 Research Copilot",
        page_icon="🏛️",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            "About": (
                "A governed Streamlit interface for descriptive, survey-weighted analysis "
                "of the 2023 American Housing Survey Public Use File."
            )
        },
    )


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ahs-navy: #0b1f33;
          --ahs-navy-2: #102a43;
          --ahs-teal: #00a6a6;
          --ahs-cyan: #52d3d8;
          --ahs-gold: #f0b429;
          --ahs-ink: #102a43;
          --ahs-muted: #627d98;
          --ahs-line: rgba(82, 211, 216, 0.22);
        }
        .stApp {
          background:
            linear-gradient(rgba(255,255,255,.97), rgba(255,255,255,.97)),
            repeating-linear-gradient(0deg, transparent, transparent 31px, rgba(11,31,51,.045) 32px),
            repeating-linear-gradient(90deg, transparent, transparent 31px, rgba(11,31,51,.045) 32px);
        }
        .block-container { padding-top: 1.4rem; padding-bottom: 4rem; max-width: 1500px; }
        [data-testid="stSidebar"] {
          background: linear-gradient(180deg, #071827 0%, #0b263d 100%);
          color: #e6f6f7;
          border-right: 1px solid rgba(82,211,216,.28);
        }
        [data-testid="stSidebar"] * { color: #e6f6f7; }
        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] textarea,
        [data-testid="stSidebar"] select { color: #102a43 !important; }
        .ahs-hero {
          position: relative;
          overflow: hidden;
          border-radius: 18px;
          padding: 28px 30px;
          margin-bottom: 18px;
          color: white;
          background:
            radial-gradient(circle at 85% 10%, rgba(82,211,216,.24), transparent 28%),
            linear-gradient(135deg, #071827 0%, #103b55 68%, #0b5960 100%);
          border: 1px solid rgba(82,211,216,.32);
          box-shadow: 0 15px 45px rgba(7,24,39,.16);
        }
        .ahs-hero:after {
          content: "";
          position: absolute;
          inset: 0;
          pointer-events: none;
          background-image:
            linear-gradient(rgba(82,211,216,.09) 1px, transparent 1px),
            linear-gradient(90deg, rgba(82,211,216,.09) 1px, transparent 1px);
          background-size: 28px 28px;
          mask-image: linear-gradient(to left, rgba(0,0,0,.8), transparent 72%);
        }
        .ahs-kicker { color: #8be4e6; letter-spacing: .16em; font-size: .76rem; font-weight: 700; }
        .ahs-title { font-size: clamp(2rem, 4vw, 3.4rem); line-height: 1.04; margin: .35rem 0 .6rem; font-weight: 760; }
        .ahs-subtitle { max-width: 900px; color: #d9eef0; font-size: 1.02rem; }
        .ahs-status-row { display: flex; gap: .55rem; flex-wrap: wrap; margin-top: 1rem; }
        .ahs-pill {
          display: inline-flex; align-items: center; gap: .35rem;
          border: 1px solid rgba(139,228,230,.42);
          background: rgba(5,20,32,.48);
          padding: .32rem .62rem; border-radius: 999px;
          color: #dffafb; font-size: .78rem; font-weight: 600;
        }
        .ahs-section-title { font-size: 1.12rem; font-weight: 720; color: var(--ahs-navy); margin: 1.15rem 0 .55rem; }
        .ahs-question-card {
          min-height: 168px;
          border: 1px solid #d9e2ec;
          border-top: 3px solid var(--ahs-teal);
          border-radius: 14px;
          background: rgba(255,255,255,.86);
          padding: 15px 16px 12px;
          box-shadow: 0 8px 24px rgba(16,42,67,.06);
        }
        .ahs-eyebrow { color: #007c83; font-size: .7rem; font-weight: 750; letter-spacing: .12em; }
        .ahs-question-title { color: var(--ahs-navy); font-size: 1rem; font-weight: 720; margin: .35rem 0; }
        .ahs-note { color: var(--ahs-muted); font-size: .82rem; }
        .ahs-stage {
          border: 1px solid #cbdbe7; border-radius: 14px; padding: 16px 18px;
          background: rgba(248,252,253,.93); margin: 10px 0 16px;
        }
        .ahs-stage-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
        .ahs-stage-item { border-radius: 10px; padding: 9px 10px; background: #eaf2f6; color: #486581; font-size: .78rem; font-weight: 650; }
        .ahs-stage-item.active { background: #dff8f7; color: #006d72; outline: 1px solid rgba(0,166,166,.3); }
        .ahs-stage-item.done { background: #e8f5ed; color: #176b3a; }
        .ahs-plan-card {
          border: 1px solid rgba(0,166,166,.35);
          border-left: 5px solid var(--ahs-teal);
          background: linear-gradient(90deg, rgba(223,248,247,.7), rgba(255,255,255,.95));
          border-radius: 14px; padding: 18px 20px; margin: 10px 0;
        }
        .ahs-plan-label { color: #006d72; font-weight: 750; font-size: .76rem; letter-spacing: .11em; }
        .ahs-plan-title { color: var(--ahs-navy); font-size: 1.15rem; font-weight: 740; margin-top: .25rem; }
        .ahs-blocked {
          border: 1px solid rgba(240,180,41,.55); border-left: 5px solid var(--ahs-gold);
          background: #fff9e8; border-radius: 14px; padding: 18px 20px; margin: 12px 0;
        }
        .ahs-comparison {
          border: 1px solid rgba(0,166,166,.42); border-radius: 16px; padding: 18px 20px;
          background: linear-gradient(135deg, rgba(235,251,250,.92), rgba(255,255,255,.96));
          margin: 18px 0; box-shadow: 0 10px 30px rgba(16,42,67,.06);
        }
        .ahs-comparison-grid { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 10px; margin-top: 10px; }
        .ahs-contract-chip { border: 1px solid #cbdbe7; border-radius: 10px; padding: 8px 10px; background: #fff; font-size: .78rem; }
        .ahs-contract-chip strong { color: #006d72; display: block; margin-bottom: 2px; }
        [data-testid="stMetric"] {
          border: 1px solid #d9e2ec; border-radius: 13px; padding: 13px 14px;
          background: rgba(255,255,255,.9); box-shadow: 0 8px 20px rgba(16,42,67,.05);
        }
        [data-testid="stMetricValue"] { color: var(--ahs-navy); }
        .stButton > button, .stDownloadButton > button {
          border-radius: 9px; font-weight: 680; border-color: #9fb3c8;
        }
        .stButton > button[kind="primary"] { background: #007f86; border-color: #007f86; }
        div[data-testid="stExpander"] { border: 1px solid #d9e2ec; border-radius: 12px; background: rgba(255,255,255,.85); }
        code { font-size: .82rem !important; }
        @media (max-width: 760px) { .ahs-stage-grid { grid-template-columns: 1fr 1fr; } .ahs-comparison-grid { grid-template-columns: 1fr; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _hero() -> None:
    st.markdown(
        f"""
        <div class="ahs-hero">
          <div class="ahs-kicker">U.S. HOUSING DATA · GOVERNED ANALYTICS</div>
          <div class="ahs-title">AHS 2023 Research Copilot</div>
          <div class="ahs-subtitle">
            Ask a housing research question, inspect the proposed analysis plan, approve it,
            and receive deterministic survey-weighted results with SQL and a complete audit trace.
          </div>
          <div class="ahs-status-row">
            <span class="ahs-pill">● Typed plans only</span>
            <span class="ahs-pill">● DuckDB execution</span>
            <span class="ahs-pill">● Human approval</span>
            <span class="ahs-pill">● Descriptive estimates</span>
            <span class="ahs-pill">v{APP_VERSION}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
        return str(value) if value is not None else default
    except Exception:
        return default


def _env_or_secret(env_name: str, secret_name: str, default: str = "") -> str:
    return os.getenv(env_name) or _secret(secret_name, default)


def _default_config_path() -> str:
    preferred = Path("config/ahs_engine.toml")
    fallback = Path("config/ahs_engine.example.toml")
    if preferred.exists():
        return str(preferred)
    return str(fallback)


def _sidebar() -> dict[str, Any]:
    with st.sidebar:
        st.markdown("### Runtime control")
        st.caption("Local files, model provider, and governance settings")

        config_path = st.text_input(
            "Engine configuration",
            value=st.session_state.get("config_path", _default_config_path()),
            help="TOML file containing local household, mortgage, and projects CSV paths.",
        )
        st.session_state["config_path"] = config_path

        provider = st.selectbox(
            "Planning provider",
            (PROVIDER_DEMO, PROVIDER_OPENAI, PROVIDER_ANTHROPIC, PROVIDER_BEDROCK),
            index=0,
            help="Every provider is constrained to the typed AnalysisPlan schema.",
        )

        settings: dict[str, Any] = {"provider": provider, "config_path": config_path}
        if provider == PROVIDER_OPENAI:
            settings["model"] = st.text_input(
                "Model",
                value=_env_or_secret("AHS_MODEL_NAME", "AHS_MODEL_NAME"),
                placeholder="Enter a structured-output capable model name",
            )
            settings["api_key"] = st.text_input(
                "API key",
                value="",
                type="password",
                placeholder="Uses OPENAI_API_KEY when blank",
            ) or _env_or_secret("OPENAI_API_KEY", "OPENAI_API_KEY")
            settings["base_url"] = st.text_input(
                "Base URL (optional)",
                value=_env_or_secret("OPENAI_BASE_URL", "OPENAI_BASE_URL"),
                help="Supports OpenAI-compatible gateways. Leave blank for the default endpoint.",
            )
        elif provider == PROVIDER_ANTHROPIC:
            settings["model"] = st.text_input(
                "Model",
                value=_env_or_secret("AHS_MODEL_NAME", "AHS_MODEL_NAME"),
                placeholder="Enter an Anthropic model name",
            )
            settings["api_key"] = st.text_input(
                "API key",
                value="",
                type="password",
                placeholder="Uses ANTHROPIC_API_KEY when blank",
            ) or _env_or_secret("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
        elif provider == PROVIDER_BEDROCK:
            settings["model"] = st.text_input(
                "Bedrock model ID",
                value=_env_or_secret("AHS_MODEL_NAME", "AHS_MODEL_NAME"),
                placeholder="Enter a Bedrock model ID",
            )
            settings["region"] = st.text_input(
                "AWS region",
                value=_env_or_secret("AWS_REGION", "AWS_REGION", "us-east-1"),
            )
            st.caption("Bedrock uses the standard AWS credential chain; credentials are not persisted by this app.")
        else:
            st.info("No network calls. Questions map to conservative, deterministic plan templates.")

        with st.expander("Governance settings", expanded=False):
            settings["max_plan_attempts"] = st.slider("Maximum plan attempts", 1, 5, 3)
            settings["max_reexecutions"] = st.slider("Maximum deterministic re-executions", 0, 2, 1)
            settings["show_raw_codes"] = st.toggle("Show raw category codes", value=True)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Test data", use_container_width=True):
                _test_data_connection(config_path)
        with col2:
            if st.button("Reset", use_container_width=True):
                _reset_state()
                st.rerun()

        st.divider()
        st.markdown("**Statistical boundary**")
        st.caption(
            "Descriptive weighted estimates only. Standard errors, confidence intervals, "
            "p-values, significance, prediction, and causal claims are not implemented."
        )
        st.markdown(f"<small>Interface build {APP_VERSION}</small>", unsafe_allow_html=True)

    return settings


def _import_domain() -> dict[str, Any]:
    from ahs_copilot.agent_workflow import (
        AHSAgentWorkflow,
        AgentWorkflowRequest,
        LangChainStructuredPlanModel,
        MockAnalysisPlanModel,
        ResultCriticConfig,
    )
    from ahs_copilot.analysis_plan import AnalysisPlan, AnalysisPlanService
    from ahs_copilot.query_engine import AHSQueryEngine

    return {
        "AHSAgentWorkflow": AHSAgentWorkflow,
        "AgentWorkflowRequest": AgentWorkflowRequest,
        "LangChainStructuredPlanModel": LangChainStructuredPlanModel,
        "MockAnalysisPlanModel": MockAnalysisPlanModel,
        "ResultCriticConfig": ResultCriticConfig,
        "AnalysisPlan": AnalysisPlan,
        "AnalysisPlanService": AnalysisPlanService,
        "AHSQueryEngine": AHSQueryEngine,
    }


def _test_data_connection(config_path: str) -> None:
    try:
        domain = _import_domain()
        engine = domain["AHSQueryEngine"](config_path)
        try:
            schemas = engine.inspect_schemas()
            items = list(schemas.values()) if isinstance(schemas, dict) else list(schemas)
            synthetic = sum(bool(getattr(item, "synthetic_fixture", False)) for item in items)
            st.success(f"Connected to {len(items)} datasets; {synthetic} use synthetic fixtures.")
        finally:
            close = getattr(engine, "close", None)
            if callable(close):
                close()
    except Exception as exc:
        st.error(f"Data connection failed: {exc}")


def _build_external_planner(domain: dict[str, Any], settings: dict[str, Any]) -> Any:
    provider = settings["provider"]
    model_name = (settings.get("model") or "").strip()
    if not model_name:
        raise RuntimeError("Enter a model name or set AHS_MODEL_NAME before starting the analysis.")
    if provider == PROVIDER_OPENAI:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("Install the 'model-openai' extra to use OpenAI planning.") from exc
        kwargs: dict[str, Any] = {"model": model_name, "temperature": 0}
        if settings.get("api_key"):
            kwargs["api_key"] = settings["api_key"]
        if settings.get("base_url"):
            kwargs["base_url"] = settings["base_url"]
        chat_model = ChatOpenAI(**kwargs)
    elif provider == PROVIDER_ANTHROPIC:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise RuntimeError("Install the 'model-anthropic' extra to use Anthropic planning.") from exc
        kwargs = {"model": model_name, "temperature": 0}
        if settings.get("api_key"):
            kwargs["api_key"] = settings["api_key"]
        chat_model = ChatAnthropic(**kwargs)
    elif provider == PROVIDER_BEDROCK:
        try:
            from langchain_aws import ChatBedrockConverse
        except ImportError as exc:
            raise RuntimeError("Install the 'model-bedrock' extra to use Bedrock planning.") from exc
        chat_model = ChatBedrockConverse(
            model_id=model_name,
            region_name=settings.get("region") or None,
            temperature=0,
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    return domain["LangChainStructuredPlanModel"](chat_model)


def _dispose_runtime() -> None:
    runtime = st.session_state.pop("ahs_runtime", None)
    if runtime is not None:
        try:
            runtime.close()
        except Exception:
            pass


def _reset_state() -> None:
    _dispose_runtime()
    for key in (
        "ahs_pause",
        "ahs_result",
        "ahs_blocked",
        "ahs_error",
        "ahs_question",
        "ahs_stage",
        "revision_feedback",
        "ahs_comparison_runs",
        "ahs_active_comparison_key",
        "ahs_comparison_error",
    ):
        st.session_state.pop(key, None)


def _start_analysis(question: str, settings: dict[str, Any]) -> None:
    _reset_state()
    st.session_state["ahs_question"] = question
    st.session_state["ahs_stage"] = "planning"

    try:
        resolved: dict[str, Any] | BlockedRequest | None = None
        if settings["provider"] == PROVIDER_DEMO:
            resolved = resolve_demo_question(question)
            if isinstance(resolved, BlockedRequest):
                st.session_state["ahs_blocked"] = resolved
                st.session_state["ahs_stage"] = "blocked"
                return

        domain = _import_domain()
        if settings["provider"] == PROVIDER_DEMO:
            plan = domain["AnalysisPlan"].model_validate(resolved)
            planner = domain["MockAnalysisPlanModel"]([plan], repeat_last=True)
        else:
            planner = _build_external_planner(domain, settings)

        engine = domain["AHSQueryEngine"](settings["config_path"])
        service = domain["AnalysisPlanService"](engine)
        workflow = domain["AHSAgentWorkflow"](planner, service)
        runtime = RuntimeBundle(
            engine=engine,
            workflow=workflow,
            provider=settings["provider"],
            config_path=settings["config_path"],
        )
        st.session_state["ahs_runtime"] = runtime

        request = domain["AgentWorkflowRequest"](
            question=question,
            context={
                "channel": "streamlit",
                "interface_version": APP_VERSION,
                "descriptive_only": True,
                "geography_mappings_confirmed": False,
            },
            approval_mode="interrupt",
            max_plan_attempts=settings.get("max_plan_attempts", 3),
            result_critic=domain["ResultCriticConfig"](
                max_reexecutions=settings.get("max_reexecutions", 1)
            ),
        )
        output = workflow.invoke(request, thread_id=f"streamlit-{uuid4()}")
        _store_workflow_output(output)
    except Exception as exc:
        _dispose_runtime()
        st.session_state["ahs_stage"] = "failed"
        st.session_state["ahs_error"] = {
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }


def _store_workflow_output(output: Any) -> None:
    if hasattr(output, "approval_request") and hasattr(output, "thread_id"):
        st.session_state["ahs_pause"] = output
        st.session_state.pop("ahs_result", None)
        st.session_state["ahs_stage"] = "approval"
    else:
        st.session_state["ahs_result"] = output
        st.session_state.pop("ahs_pause", None)
        status = getattr(output, "status", "failed")
        st.session_state["ahs_stage"] = "results" if status == "completed" else status
        if status in {"failed", "rejected"}:
            _dispose_runtime()


def _resume(decision: str, feedback: str | None = None) -> None:
    runtime: RuntimeBundle | None = st.session_state.get("ahs_runtime")
    pause = st.session_state.get("ahs_pause")
    if runtime is None or pause is None:
        st.error("The approval session is no longer available. Start the analysis again.")
        return
    try:
        output = runtime.workflow.resume(
            pause.thread_id,
            {"decision": decision, "feedback": feedback},
        )
        _store_workflow_output(output)
    except Exception as exc:
        st.session_state["ahs_stage"] = "failed"
        st.session_state["ahs_error"] = {
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        _dispose_runtime()


def _render_suggested_questions() -> None:
    st.markdown('<div class="ahs-section-title">Suggested research questions</div>', unsafe_allow_html=True)
    columns = st.columns(3)
    for column, item in zip(columns, SUGGESTED_QUESTIONS):
        with column:
            st.markdown(
                f"""
                <div class="ahs-question-card">
                  <div class="ahs-eyebrow">{item.eyebrow}</div>
                  <div class="ahs-question-title">{item.title}</div>
                  <div>{item.question}</div>
                  <div class="ahs-note" style="margin-top:.55rem">{item.governance_note}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Use this question", key=f"suggest-{item.question_id}", use_container_width=True):
                st.session_state["question_input"] = item.question
                st.rerun()


def _render_question_form(settings: dict[str, Any]) -> None:
    st.markdown('<div class="ahs-section-title">Research request</div>', unsafe_allow_html=True)
    with st.form("research-question-form", clear_on_submit=False):
        question = st.text_area(
            "Ask about the 2023 AHS National PUF",
            key="question_input",
            height=105,
            placeholder=(
                "Example: What percentage of occupied housing units have high housing-cost "
                "burden, grouped by tenure?"
            ),
        )
        col1, col2 = st.columns([1, 3])
        with col1:
            submitted = st.form_submit_button("Build analysis plan", type="primary", use_container_width=True)
        with col2:
            st.caption(
                "The planner cannot execute SQL. A deterministic validator must accept the typed plan, "
                "and you must approve it before execution."
            )
    if submitted:
        if len(question.strip()) < 3:
            st.warning("Enter a research question before building a plan.")
        else:
            with st.spinner("Resolving metadata and validating a typed analysis plan…"):
                _start_analysis(question.strip(), settings)
            st.rerun()


def _render_stage() -> None:
    stage = st.session_state.get("ahs_stage")
    if not stage:
        return
    order = ("planning", "approval", "execution", "results")
    labels = {
        "planning": "1 · Resolve & plan",
        "approval": "2 · Human approval",
        "execution": "3 · Deterministic run",
        "results": "4 · Certified result",
    }
    effective = "execution" if stage in {"failed", "rejected"} else stage
    active_index = order.index(effective) if effective in order else 0
    items = []
    for index, key in enumerate(order):
        css = "done" if index < active_index else "active" if index == active_index else ""
        items.append(f'<div class="ahs-stage-item {css}">{labels[key]}</div>')
    st.markdown(
        '<div class="ahs-stage"><div class="ahs-stage-grid">' + "".join(items) + "</div></div>",
        unsafe_allow_html=True,
    )


def _render_blocked(blocked: BlockedRequest) -> None:
    detail_items = "".join(f"<li>{item}</li>" for item in blocked.details)
    st.markdown(
        f"""
        <div class="ahs-blocked">
          <div class="ahs-plan-label">BLOCKED · {blocked.code}</div>
          <div class="ahs-plan-title">{blocked.title}</div>
          <p>{blocked.message}</p>
          <ul>{detail_items}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.warning("No SQL was generated and no data was queried.")


def _render_plan_approval() -> None:
    pause = st.session_state.get("ahs_pause")
    if pause is None:
        return
    request = pause.approval_request
    plan = request.plan
    summary = plan_summary(plan)
    group_names = [item.get("column") for item in summary["grouping_dimensions"]]
    weight = (summary.get("weight") or {}).get("column") or {}

    st.markdown(
        f"""
        <div class="ahs-plan-card">
          <div class="ahs-plan-label">ANALYSIS PLAN · AWAITING APPROVAL</div>
          <div class="ahs-plan-title">{html.escape(request.question)}</div>
          <p><strong>Dataset:</strong> {summary.get('dataset')} &nbsp;·&nbsp;
             <strong>Universe:</strong> {(summary.get('universe') or {}).get('universe_id')} &nbsp;·&nbsp;
             <strong>Weight:</strong> {weight.get('dataset', '')}.{weight.get('column', 'unweighted')}</p>
          <p><strong>Measure:</strong> {json.dumps(summary.get('measure'), sort_keys=True)}<br>
             <strong>Groupings:</strong> {', '.join(group_names) if group_names else 'None'}</p>
          <small>Fingerprint: {request.plan_fingerprint}</small>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if request.validation_messages:
        st.success("Deterministic validation passed: " + " · ".join(request.validation_messages))

    with st.expander("Inspect complete typed plan", expanded=False):
        st.json(to_plain(plan), expanded=2)

    st.markdown("#### Approval decision")
    feedback = st.text_area(
        "Revision feedback",
        key="revision_feedback",
        placeholder="Required only when requesting a revised plan.",
    )
    approve_col, revise_col, reject_col = st.columns(3)
    with approve_col:
        if st.button("Approve and execute", type="primary", use_container_width=True):
            with st.spinner("Compiling and executing the approved plan…"):
                _resume("approved")
            st.rerun()
    with revise_col:
        if st.button("Request revision", use_container_width=True):
            if not feedback.strip():
                st.warning("Enter revision feedback before requesting a revised plan.")
            else:
                with st.spinner("Requesting a revised typed plan…"):
                    _resume("revise", feedback.strip())
                st.rerun()
    with reject_col:
        if st.button("Reject plan", use_container_width=True):
            _resume("rejected", "Rejected by the researcher in the Streamlit approval gate.")
            st.rerun()


def _result_payload(result: Any) -> Any | None:
    execution = getattr(result, "execution", None)
    return getattr(execution, "result", None) if execution is not None else None


def _render_result_banners(result: Any, payload: Any, records: list[dict[str, Any]]) -> None:
    st.warning(
        "Descriptive survey-weighted estimates only. Replicate-weight variance estimation is not "
        "implemented; do not interpret differences as statistically significant or causal."
    )
    metadata = to_plain(getattr(payload, "metadata", {}))
    synthetic = [item for item in metadata.get("datasets", []) if item.get("synthetic_fixture")]
    if synthetic:
        names = ", ".join(item.get("logical_name", "dataset") for item in synthetic)
        st.info(f"Demo data mode: synthetic fixture rows were used for {names}.")
    suppressed = sum(bool(item.get("suppressed")) for item in records)
    if suppressed:
        st.warning(f"{suppressed} result cells were suppressed or flagged by the configured release policy.")
    critique = getattr(result, "result_critique", None)
    if critique is not None and getattr(critique, "decision", None) == "approve":
        st.success("Deterministic result checks and the non-mutating result critic approved this output.")


def _render_run_metrics(result: Any, payload: Any, records: list[dict[str, Any]]) -> None:
    metadata = to_plain(getattr(payload, "metadata", {}))
    critique = getattr(result, "result_critique", None)
    cols = st.columns(4)
    cols[0].metric("Workflow", str(getattr(result, "status", "unknown")).upper())
    cols[1].metric("Estimate cells", f"{len(records):,}")
    cols[2].metric("Execution", f"{float(metadata.get('elapsed_ms') or 0):,.1f} ms")
    cols[3].metric("Result critic", str(getattr(critique, "decision", "not run")).upper())


def _render_estimate_metrics(payload: Any) -> None:
    estimates = list(getattr(payload, "estimates", []) or [])
    if not estimates:
        return
    st.markdown("#### Key estimates")
    for offset in range(0, min(len(estimates), 8), 4):
        columns = st.columns(min(4, len(estimates) - offset))
        for column, estimate in zip(columns, estimates[offset : offset + 4]):
            with column:
                st.metric(
                    group_label(getattr(estimate, "group", {})),
                    format_estimate(
                        getattr(estimate, "estimate", None),
                        getattr(estimate, "statistic", None),
                    ),
                    help=(
                        f"Unweighted denominator: {getattr(estimate, 'unweighted_denominator', 0):,}; "
                        f"weighted denominator: {getattr(estimate, 'weighted_denominator', 0)}"
                    ),
                )


def _chart_dataframe(records: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[str]]:
    frame = pd.DataFrame(records)
    metric_columns = {
        "estimate_alias",
        "statistic",
        "estimate",
        "weighted_numerator",
        "weighted_denominator",
        "unweighted_numerator",
        "unweighted_denominator",
        "missing_value_rows_excluded",
        "suppressed",
        "suppression_reasons",
    }
    groups = [column for column in frame.columns if column not in metric_columns]
    frame["estimate_numeric"] = pd.to_numeric(frame.get("estimate"), errors="coerce")
    frame["group_label"] = frame.apply(
        lambda row: " · ".join(f"{column}={row[column]}" for column in groups) or "All eligible units",
        axis=1,
    )
    return frame, groups


def _render_chart_and_table(records: list[dict[str, Any]]) -> None:
    if not records:
        st.info("No estimate rows were returned.")
        return
    frame, groups = _chart_dataframe(records)
    chart_frame = frame.dropna(subset=["estimate_numeric"]).copy()
    if not chart_frame.empty:
        if len(chart_frame) > 30:
            chart_frame = chart_frame.sort_values("estimate_numeric", ascending=False).head(30)
            st.caption("Chart shows the 30 largest displayed estimates; the table and downloads contain all rows.")
        statistic = str(chart_frame["statistic"].iloc[0])
        x_title = "Weighted percentage" if statistic == "weighted_percentage" else "Weighted estimate"
        chart = (
            alt.Chart(chart_frame)
            .mark_bar(cornerRadiusEnd=4, color="#008b93")
            .encode(
                x=alt.X("estimate_numeric:Q", title=x_title),
                y=alt.Y("group_label:N", sort="-x", title=None),
                tooltip=[
                    alt.Tooltip("group_label:N", title="Group"),
                    alt.Tooltip("estimate_numeric:Q", title="Estimate", format=",.2f"),
                    alt.Tooltip("unweighted_denominator:Q", title="Unweighted denominator", format=","),
                    alt.Tooltip("weighted_denominator:Q", title="Weighted denominator", format=",.2f"),
                ],
            )
            .properties(height=max(260, min(760, 28 * len(chart_frame))))
        )
        st.altair_chart(chart, use_container_width=True)

    st.dataframe(frame.drop(columns=["estimate_numeric", "group_label"]), use_container_width=True, hide_index=True)
    if groups:
        st.caption("Group fields are shown as raw approved variable codes unless certified labels exist in metadata.")


def _render_trust_panel(result: Any, payload: Any) -> None:
    plan = getattr(result, "validated_plan", None)
    plan_obj = getattr(plan, "plan", None) or getattr(result, "plan", None)
    summary = plan_summary(plan_obj) if plan_obj is not None else {}
    metadata = to_plain(getattr(payload, "metadata", {}))
    checks = to_plain(getattr(result, "result_checks", {}))
    critique = to_plain(getattr(result, "result_critique", {}))

    with st.expander("Why should I trust this?", expanded=True):
        trust_cols = st.columns(4)
        trust_cols[0].metric("Universe", (summary.get("universe") or {}).get("universe_id", "unknown"))
        trust_cols[1].metric("Weight mode", (summary.get("weight") or {}).get("mode", "unknown"))
        trust_cols[2].metric("SQL fingerprint", str(metadata.get("sql_fingerprint", ""))[:12] or "n/a")
        trust_cols[3].metric("Variance", (metadata.get("variance") or {}).get("status", "NOT_ESTIMATED"))
        st.markdown(
            "The model selected a typed plan only. Deterministic services validated metadata, compiled "
            "parameterized SQL, executed DuckDB, calculated survey estimates, and checked result integrity."
        )
        left, right = st.columns(2)
        with left:
            st.markdown("**Deterministic checks**")
            st.json(checks, expanded=1)
        with right:
            st.markdown("**Result critic**")
            st.json(critique, expanded=1)


def _render_methodology(result: Any, payload: Any) -> None:
    validated = getattr(result, "validated_plan", None)
    plan_obj = getattr(validated, "plan", None) or getattr(result, "plan", None)
    compiled = getattr(result, "compiled", None)
    metadata = getattr(payload, "metadata", None)
    with st.expander("Methodology", expanded=False):
        st.markdown("**Analysis contract**")
        st.json(plan_summary(plan_obj), expanded=2)
        st.markdown("**Deterministic formulas**")
        st.json(to_plain(getattr(compiled, "formulas", getattr(payload, "formulas", []))), expanded=2)
        st.markdown("**Suppression and variance boundary**")
        meta = to_plain(metadata)
        st.json(
            {
                "suppression_policy": meta.get("suppression_policy"),
                "weight_eligibility_rule": meta.get("weight_eligibility_rule"),
                "arithmetic_rule": meta.get("arithmetic_rule"),
                "variance": meta.get("variance"),
            },
            expanded=2,
        )


def _render_sources_and_filters(result: Any, payload: Any) -> None:
    validated = getattr(result, "validated_plan", None)
    plan_obj = getattr(validated, "plan", None) or getattr(result, "plan", None)
    summary = plan_summary(plan_obj)
    metadata = to_plain(getattr(payload, "metadata", {}))
    with st.expander("Source variables and filters", expanded=False):
        left, right = st.columns(2)
        with left:
            st.markdown("**Required variables**")
            st.dataframe(pd.DataFrame(summary.get("required_variables", [])), hide_index=True, use_container_width=True)
            st.markdown("**Grouping dimensions**")
            st.dataframe(pd.DataFrame(summary.get("grouping_dimensions", [])), hide_index=True, use_container_width=True)
        with right:
            st.markdown("**Analysis and numerator filters**")
            filters = list(summary.get("filters", [])) + list(summary.get("numerator_filters", []))
            st.json(filters, expanded=2)
            st.markdown("**Physical sources**")
            source_rows = [
                {
                    "dataset": item.get("logical_name"),
                    "source_file_id": item.get("source_file_id"),
                    "physical_path": item.get("physical_path"),
                    "synthetic_fixture": item.get("synthetic_fixture"),
                }
                for item in metadata.get("datasets", [])
            ]
            st.dataframe(pd.DataFrame(source_rows), hide_index=True, use_container_width=True)


def _render_sql(result: Any, payload: Any) -> None:
    with st.expander("Generated SQL", expanded=False):
        st.caption("Display SQL is generated by the deterministic compiler. Bound values are executed as parameters.")
        st.code(getattr(payload, "generated_sql", ""), language="sql", line_numbers=True)
        st.markdown("**Bound parameters**")
        st.json(to_plain(getattr(payload, "parameters", [])))
        compiled = getattr(result, "compiled", None)
        if compiled is not None:
            st.caption(f"Request fingerprint: {getattr(compiled, 'request_fingerprint', 'n/a')}")


def _render_trace(result: Any) -> None:
    events = [to_plain(item) for item in (getattr(result, "audit_log", []) or [])]
    with st.expander("Agent trace", expanded=False):
        if events:
            rows = []
            for event in events:
                rows.append(
                    {
                        "timestamp": event.get("timestamp"),
                        "level": event.get("level"),
                        "node": event.get("node"),
                        "event": event.get("event"),
                        "attempt": event.get("attempt"),
                        "message": event.get("message"),
                    }
                )
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            st.json(events, expanded=1)
        else:
            st.info("No audit events were returned.")


def _render_downloads(
    result: Any,
    records: list[dict[str, Any]],
    *,
    file_prefix: str = "ahs_research_copilot",
) -> None:
    csv_bytes = records_to_csv(records)
    json_bytes = object_to_json_bytes(result)
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        st.download_button(
            "Download CSV",
            data=csv_bytes,
            file_name=f"{file_prefix}_results.csv",
            mime="text/csv",
            use_container_width=True,
            disabled=not bool(csv_bytes),
        )
    with col2:
        st.download_button(
            "Download JSON",
            data=json_bytes,
            file_name=f"{file_prefix}_result.json",
            mime="application/json",
            use_container_width=True,
        )
    with col3:
        st.caption("JSON includes the plan, SQL, execution metadata, critic report, and audit events.")



def _validated_plan_parts(result: Any) -> tuple[Any | None, str]:
    validated = getattr(result, "validated_plan", None)
    if validated is not None:
        return getattr(validated, "plan", None), str(getattr(validated, "plan_fingerprint", ""))
    return getattr(result, "plan", None), ""


def _comparison_catalog_path() -> str:
    return str(Path("metadata/semantic_catalog.json"))


def _run_comparison_plan(base_result: Any, mutation: Any) -> None:
    runtime: RuntimeBundle | None = st.session_state.get("ahs_runtime")
    if runtime is None:
        raise RuntimeError(
            "The deterministic runtime is no longer available. Re-run the approved analysis "
            "before starting a comparison."
        )
    domain = _import_domain()
    plan = domain["AnalysisPlan"].model_validate(mutation.plan)
    planner = domain["MockAnalysisPlanModel"]([plan], repeat_last=True)
    workflow = domain["AHSAgentWorkflow"](planner, runtime.workflow.service)
    _, base_fingerprint = _validated_plan_parts(base_result)
    request = domain["AgentWorkflowRequest"](
        question=plan.user_question,
        context={
            "channel": "streamlit_comparison_workspace",
            "interface_version": APP_VERSION,
            "descriptive_only": True,
            "reused_validated_plan": True,
            "base_plan_fingerprint": base_fingerprint,
            "changed_filter_columns": list(mutation.changed_columns),
            "model_planning_skipped": True,
        },
        approval_mode="auto_approve",
        max_plan_attempts=1,
        result_critic=domain["ResultCriticConfig"](max_reexecutions=1),
    )
    key = comparison_cache_key(base_fingerprint, mutation.selections)
    cache = st.session_state.setdefault("ahs_comparison_runs", {})
    if key not in cache:
        output = workflow.invoke(request, thread_id=f"streamlit-comparison-{uuid4()}")
        cache[key] = {"result": output, "mutation": mutation}
    st.session_state["ahs_active_comparison_key"] = key
    st.session_state.pop("ahs_comparison_error", None)


def _comparison_delta_frame(base_result: Any, comparison_result: Any) -> pd.DataFrame:
    base_payload = _result_payload(base_result)
    comparison_payload = _result_payload(comparison_result)
    base_records = result_records(base_payload) if base_payload is not None else []
    comparison_records = result_records(comparison_payload) if comparison_payload is not None else []
    if not base_records and not comparison_records:
        return pd.DataFrame()
    metric_columns = {
        "estimate",
        "weighted_numerator",
        "weighted_denominator",
        "unweighted_numerator",
        "unweighted_denominator",
        "missing_value_rows_excluded",
        "suppressed",
        "suppression_reasons",
    }
    all_columns = set().union(*(record.keys() for record in base_records + comparison_records))
    keys = [column for column in all_columns if column not in metric_columns]
    base_frame = pd.DataFrame(base_records)
    comparison_frame = pd.DataFrame(comparison_records)
    for frame in (base_frame, comparison_frame):
        for key in keys:
            if key not in frame:
                frame[key] = None
    base_keep = keys + ["estimate", "unweighted_denominator", "weighted_denominator"]
    comparison_keep = keys + ["estimate", "unweighted_denominator", "weighted_denominator"]
    merged = base_frame[base_keep].merge(
        comparison_frame[comparison_keep],
        on=keys,
        how="outer",
        suffixes=("_baseline", "_comparison"),
    )
    merged["estimate_baseline"] = pd.to_numeric(merged["estimate_baseline"], errors="coerce")
    merged["estimate_comparison"] = pd.to_numeric(merged["estimate_comparison"], errors="coerce")
    merged["estimate_change"] = merged["estimate_comparison"] - merged["estimate_baseline"]
    return merged


def _render_result_view(
    result: Any,
    *,
    heading: str,
    file_prefix: str,
    include_workspace: bool = False,
) -> None:
    status = getattr(result, "status", "failed")
    if status != "completed":
        error = getattr(result, "error", None)
        message = getattr(error, "message", None) or f"Workflow ended with status {status}."
        if status == "rejected":
            st.warning(message)
        else:
            st.error(message)
        _render_trace(result)
        return

    payload = _result_payload(result)
    if payload is None:
        st.error("The workflow completed without an execution result.")
        return
    records = result_records(payload)
    st.markdown(f'<div class="ahs-section-title">{html.escape(heading)}</div>', unsafe_allow_html=True)
    _render_result_banners(result, payload, records)
    _render_run_metrics(result, payload, records)
    _render_estimate_metrics(payload)
    _render_chart_and_table(records)
    _render_trust_panel(result, payload)
    _render_methodology(result, payload)
    _render_sources_and_filters(result, payload)
    _render_sql(result, payload)
    _render_trace(result)
    _render_downloads(result, records, file_prefix=file_prefix)


def _render_comparison_workspace(base_result: Any) -> None:
    base_plan, base_fingerprint = _validated_plan_parts(base_result)
    if base_plan is None or not base_fingerprint:
        return
    catalog_path = _comparison_catalog_path()
    if not Path(catalog_path).exists():
        st.warning("Comparison workspace unavailable: executable semantic catalog was not found.")
        return
    capabilities = comparison_capabilities(base_plan, catalog_path)
    approved = approved_catalog_columns(catalog_path, dataset=str(getattr(base_plan, "dataset", "household")))
    current = comparison_selections_from_plan(base_plan)

    st.markdown(
        """
        <div class="ahs-comparison">
          <div class="ahs-plan-label">COMPARISON WORKSPACE · FILTER-ONLY REPLAY</div>
          <div class="ahs-plan-title">Change comparison dimensions without rewriting the research question</div>
          <p>The approved measure, universe, denominator, weight, joins, recodes, grouping dimensions,
          and output contract remain fixed. Only approved top-level filters and their required-variable
          closure may change.</p>
          <div class="ahs-comparison-grid">
            <div class="ahs-contract-chip"><strong>Question</strong>Preserved verbatim</div>
            <div class="ahs-contract-chip"><strong>Planner</strong>Not called again</div>
            <div class="ahs-contract-chip"><strong>Execution</strong>Revalidated, recompiled, rechecked</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    geography_default = ", ".join(str(item) for item in current["geography"])
    structure_default = ", ".join(str(item) for item in current["structure_type"])
    year_enabled = bool(capabilities["year_built"]["enabled"])
    with st.form(f"comparison-workspace-{base_fingerprint[:12]}", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            geography = st.text_input(
                "Geography codes",
                value=geography_default,
                placeholder="Example: 35620, 33100",
                disabled=not capabilities["geography"]["enabled"],
                help=(
                    "Enter raw approved OMB13CBSA integer codes. The interface does not invent city or metro labels."
                ),
            )
            tenure = st.multiselect(
                "Tenure",
                options=list(TENURE_LABELS),
                default=current["tenure"],
                format_func=lambda value: f"{value} · {TENURE_LABELS[value]}",
                disabled=not capabilities["tenure"]["enabled"],
            )
        with col2:
            structure = st.text_input(
                "Structure-type codes",
                value=structure_default,
                placeholder="Comma-separated raw BLD codes",
                disabled=not capabilities["structure_type"]["enabled"],
                help="Raw BLD codes are used unless certified labels are present in metadata.",
            )
            year_options = list(YEAR_BUILT_PRESETS) + ["Custom range"]
            year_choice = st.selectbox(
                "Year-built group",
                year_options,
                disabled=not year_enabled,
                help="This control is enabled only when YRBUILT is approved in the executable catalog.",
            )
        year_min: int | None = None
        year_max: int | None = None
        if year_enabled:
            if year_choice == "Custom range":
                year_col1, year_col2 = st.columns(2)
                with year_col1:
                    year_min_value = st.number_input("Minimum year", min_value=1600, max_value=2023, value=1980)
                with year_col2:
                    year_max_value = st.number_input("Maximum year", min_value=1600, max_value=2023, value=2023)
                year_min, year_max = int(year_min_value), int(year_max_value)
            else:
                year_min, year_max = YEAR_BUILT_PRESETS[year_choice]
        else:
            st.info(capabilities["year_built"]["reason"] + " The control is disabled rather than inferred.")

        run_comparison = st.form_submit_button(
            "Apply filters and rerun",
            type="primary",
            use_container_width=True,
        )

    if run_comparison:
        try:
            mutation = build_comparison_plan(
                base_plan,
                {
                    "geography": geography,
                    "tenure": tenure,
                    "structure_type": structure,
                    "year_built": {"min": year_min, "max": year_max},
                },
                approved_columns=approved,
            )
            if not mutation.changed_columns:
                st.info("The selected filters match the approved baseline plan; no rerun was needed.")
            else:
                with st.spinner("Revalidating the filter-only plan and regenerating deterministic results…"):
                    _run_comparison_plan(base_result, mutation)
                st.rerun()
        except Exception as exc:
            st.session_state["ahs_comparison_error"] = {
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            st.rerun()

    comparison_error = st.session_state.get("ahs_comparison_error")
    if comparison_error:
        st.error(comparison_error["message"])
        with st.expander("Comparison technical details", expanded=False):
            st.code(comparison_error.get("traceback", ""), language="text")

    cache = st.session_state.get("ahs_comparison_runs", {})
    active_key = st.session_state.get("ahs_active_comparison_key")
    active = cache.get(active_key) if active_key else None
    if active is None:
        return
    comparison_result = active["result"]
    mutation = active["mutation"]
    st.success(
        "Comparison executed from the approved plan. Changed filters: "
        + ", ".join(mutation.changed_columns)
        + ". The original question and statistical contract were preserved."
    )
    summary_cols = st.columns(3)
    summary_cols[0].metric("Base plan", base_fingerprint[:12])
    comparison_plan, comparison_fingerprint = _validated_plan_parts(comparison_result)
    summary_cols[1].metric("Comparison plan", comparison_fingerprint[:12] or "failed")
    summary_cols[2].metric("Contract preserved", "YES" if mutation.contract_preserved else "NO")
    with st.expander("Filter mutation audit", expanded=True):
        st.json(
            {
                "question_unchanged": to_plain(comparison_plan).get("user_question")
                == to_plain(base_plan).get("user_question") if comparison_plan is not None else False,
                "changed_filter_columns": list(mutation.changed_columns),
                "selections": mutation.selections,
                "base_contract_fingerprint": mutation.base_contract_fingerprint,
                "modified_contract_fingerprint": mutation.modified_contract_fingerprint,
            },
            expanded=2,
        )
    delta = _comparison_delta_frame(base_result, comparison_result)
    if not delta.empty:
        st.markdown("#### Baseline-to-comparison change")
        st.dataframe(delta, use_container_width=True, hide_index=True)
    with st.expander("Modified comparison result", expanded=True):
        _render_result_view(
            comparison_result,
            heading="Filtered survey-weighted result",
            file_prefix="ahs_research_copilot_comparison",
        )


def _render_result() -> None:
    result = st.session_state.get("ahs_result")
    if result is None:
        return
    if getattr(result, "status", "failed") == "completed":
        _render_comparison_workspace(result)
        st.divider()
    _render_result_view(
        result,
        heading="Baseline survey-weighted results",
        file_prefix="ahs_research_copilot",
    )

def _render_error() -> None:
    error = st.session_state.get("ahs_error")
    if not error:
        return
    st.error(error.get("message", "Unknown application error"))
    with st.expander("Technical details", expanded=False):
        st.code(error.get("traceback", ""), language="text")


def main() -> None:
    _set_page()
    _inject_css()
    settings = _sidebar()
    _hero()

    st.warning(
        "Research-use demonstration. Results are descriptive and must retain their universe, weight, "
        "denominators, source files, suppression flags, and limitations."
    )

    _render_suggested_questions()
    _render_question_form(settings)
    _render_stage()

    blocked = st.session_state.get("ahs_blocked")
    if blocked is not None:
        _render_blocked(blocked)
    _render_plan_approval()
    _render_result()
    _render_error()


if __name__ == "__main__":
    main()

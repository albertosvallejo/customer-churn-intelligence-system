import logging
import math
import os
import secrets
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from api import churn_service
from api.phase7_reporting_page import build_phase7_reporting_view_model
from api.phase7_review_page import build_phase7_review_page_view_model
from evidence.phase6_integration import (
    build_action_proposals,
    build_kpi_status_view,
    build_n8n_action_payload,
    launch_ab_test,
    load_action_history,
    load_action_proposals,
    load_latest_kpi_status,
    load_latest_n8n_action_payload,
    record_action_decision,
)
from evidence.phase7_integration import (
    build_integrated_actions,
    build_phase7_kpi_status_view,
    build_phase7_n8n_payload,
    build_phase7_post_test_decision_queue,
    build_phase7_stat_summary,
    create_phase7_stat_launch_request,
    execute_phase7_stat_launch_request,
    load_integrated_actions,
    load_latest_phase7_kpi_status,
    load_latest_phase7_n8n_payload,
    load_phase7_action_history,
    load_phase7_launch_requests,
    record_phase7_action_decision,
    record_phase7_post_test_decision,
)

logger = logging.getLogger(__name__)
PROJECT_ROOT = churn_service.PROJECT_ROOT
WEB_ROOT = PROJECT_ROOT / "web"
WEB_STATIC_ROOT = WEB_ROOT / "static"
WEB_TEMPLATES_ROOT = WEB_ROOT / "templates"

app = FastAPI(title="Daily Customer Churn API", version="cp3")
app.mount("/static", StaticFiles(directory=str(WEB_STATIC_ROOT)), name="static")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        if getattr(value, "tzinfo", None) is None:
            return value.isoformat()
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
        return value.tolist()
    try:
        is_missing = bool(pd.isna(value))
    except (TypeError, ValueError):
        is_missing = False
    if is_missing:
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _sanitize_json_payload(value: Any) -> Any:
    value = _json_default(value)
    if isinstance(value, dict):
        return {str(key): _sanitize_json_payload(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_payload(inner) for inner in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _json_response(status: int, payload: Any) -> Response:
    encoded = _sanitize_json_payload(payload)
    body = churn_service.json.dumps(encoded, ensure_ascii=False).encode("utf-8")
    return Response(status_code=status, content=body, media_type="application/json; charset=utf-8")


def _html_error(status: int, message: str) -> HTMLResponse:
    return HTMLResponse(
        status_code=status,
        content=f'<!DOCTYPE html><html lang="en"><body><h1>{status}</h1><p>{message}</p></body></html>',
    )


def _template_response(template_name: str) -> HTMLResponse:
    path = WEB_TEMPLATES_ROOT / template_name
    return HTMLResponse(status_code=HTTPStatus.OK, content=path.read_text(encoding="utf-8"))


def _allow_query_string_review_token() -> bool:
    app_env = str(os.getenv("APP_ENV") or "").strip().lower()
    return app_env in {"test", "ci"}


def _extract_phase7_review_token(request: Request) -> tuple[str, str]:
    header_token = str(request.headers.get("X-Phase7-Token") or "").strip()
    if header_token:
        return header_token, "header"
    query_token = str(request.query_params.get("token") or "").strip()
    if query_token:
        return query_token, "query"
    return "", "missing"


def _validate_phase7_review_token(request: Request) -> tuple[bool, str | None]:
    expected_token = str(os.getenv("PHASE7_REVIEW_TOKEN") or "").strip()
    if not expected_token:
        return False, "Phase 7 review token is not configured"
    provided_token, source = _extract_phase7_review_token(request)
    if not provided_token:
        return False, "Phase 7 review token is required"
    if source == "query" and not _allow_query_string_review_token():
        return False, "Invalid or expired Phase 7 review token"
    if not secrets.compare_digest(provided_token, expected_token):
        return False, "Invalid or expired Phase 7 review token"
    return True, None


def _require_phase7_review_token(request: Request, *, html_response: bool = False):
    is_valid, error_message = _validate_phase7_review_token(request)
    if is_valid:
        return None
    status = HTTPStatus.SERVICE_UNAVAILABLE if error_message == "Phase 7 review token is not configured" else HTTPStatus.UNAUTHORIZED
    if html_response:
        return _html_error(status.value, str(error_message))
    return _json_response(status.value, {"error": error_message})


def _bad_request(exc: Exception) -> JSONResponse:
    return _json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


def _not_found(exc: Exception) -> JSONResponse:
    return _json_response(HTTPStatus.NOT_FOUND, {"error": str(exc)})


def _internal_error(log_message: str, exc: Exception) -> JSONResponse:
    logger.exception(log_message)
    return _json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


@app.get("/health")
def health() -> JSONResponse:
    scoring_metadata = churn_service._latest_scoring_metadata()
    return _json_response(
        HTTPStatus.OK,
        {
            "status": "ok",
            "service": "daily-customer-churn-api",
            "timestamp": _utc_now_iso(),
            "run_id": scoring_metadata["run_id"],
            "run_date_tag": scoring_metadata["run_date_tag"],
            "model_version": scoring_metadata["model_version"],
            "pipeline_tag": scoring_metadata["pipeline_tag"],
            "source_file": scoring_metadata["source_file"],
            "risk_thresholds": scoring_metadata["risk_thresholds"],
        },
    )


@app.get("/thresholds/latest")
def thresholds_latest() -> JSONResponse:
    scoring_metadata = churn_service._latest_scoring_metadata()
    return _json_response(
        HTTPStatus.OK,
        {
            "status": "ok",
            "run_id": scoring_metadata["run_id"],
            "run_date_tag": scoring_metadata["run_date_tag"],
            "model_version": scoring_metadata["model_version"],
            "pipeline_tag": scoring_metadata["pipeline_tag"],
            "source_file": scoring_metadata["source_file"],
            "risk_thresholds": scoring_metadata["risk_thresholds"],
            "timestamp": _utc_now_iso(),
        },
    )


@app.get("/explainability/latest")
def explainability_latest(customer_id: str | None = None, risk_level: str | None = None, limit: int | None = None):
    try:
        payload = churn_service._load_latest_explainability(customer_id=customer_id, risk_level=risk_level, limit=limit)
    except FileNotFoundError as exc:
        return _not_found(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected explainability error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/health/events")
def health_events() -> JSONResponse:
    try:
        churn_service._ensure_retention_events_table()
        with churn_service._ops_engine().connect() as conn:
            event_count = conn.execute(churn_service.text("SELECT COUNT(*) FROM retention_events")).scalar_one()
        return _json_response(
            HTTPStatus.OK,
            {
                "status": "ok",
                "service": "daily-customer-churn-api-events",
                "event_table": "retention_events",
                "event_count": int(event_count),
                "timestamp": _utc_now_iso(),
            },
        )
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected event health error", exc)


@app.get("/agent/status")
def agent_status() -> JSONResponse:
    try:
        payload = churn_service._load_agent_status()
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected agent status error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/agent/status/daily")
def agent_status_daily(refresh: bool = False) -> JSONResponse:
    try:
        payload = churn_service._load_phase5_daily_status(refresh=refresh)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected phase5 daily status error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/agent/status/shadow-monitor")
def agent_status_shadow_monitor(refresh: bool = False) -> JSONResponse:
    try:
        payload = churn_service._load_phase5_shadow_monitor_status(refresh=refresh)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected phase5 shadow monitor error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/agent/status/phase5")
def agent_status_phase5(refresh: bool = False) -> JSONResponse:
    try:
        payload = churn_service._load_phase5_operational_snapshot(refresh=refresh)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected phase5 operational snapshot error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/phase6/proposals/latest")
def phase6_proposals_latest(run_date: str | None = None, refresh: bool = False) -> JSONResponse:
    try:
        if refresh:
            payload = build_action_proposals(project_root=PROJECT_ROOT, run_date=run_date)
            proposals = load_action_proposals(PROJECT_ROOT, payload["run_date"])
            response_payload = {**payload, "proposals": proposals, "refreshed": True}
        else:
            proposals = load_action_proposals(PROJECT_ROOT, run_date)
            effective_run_date = run_date or proposals[0]["proposal_run_date"] if proposals else run_date
            response_payload = {
                "run_date": effective_run_date,
                "proposal_count": len(proposals),
                "proposals": proposals,
                "refreshed": False,
            }
    except FileNotFoundError as exc:
        return _not_found(exc)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 6 proposal error", exc)
    return _json_response(HTTPStatus.OK, response_payload)


@app.get("/phase6/action-history/latest")
def phase6_action_history_latest() -> JSONResponse:
    try:
        history = load_action_history(PROJECT_ROOT)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 6 action-history error", exc)
    return _json_response(HTTPStatus.OK, {"status": "ok", "record_count": len(history), "records": history, "timestamp": _utc_now_iso()})


@app.get("/phase6/kpis/latest")
def phase6_kpis_latest(refresh: bool = False) -> JSONResponse:
    try:
        payload = build_kpi_status_view(PROJECT_ROOT) if refresh else load_latest_kpi_status(PROJECT_ROOT)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 6 KPI status error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/phase6/n8n-payload/latest")
def phase6_n8n_payload_latest(run_date: str | None = None, refresh: bool = False) -> JSONResponse:
    try:
        payload = build_n8n_action_payload(PROJECT_ROOT, run_date=run_date) if refresh else load_latest_n8n_action_payload(PROJECT_ROOT)
    except FileNotFoundError as exc:
        return _not_found(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 6 n8n payload error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/customer-churn/dashboard", response_class=HTMLResponse)
def customer_churn_dashboard(run_date: str | None = None):
    try:
        return _template_response("dashboard.html")
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected customer-churn dashboard error", exc)


@app.get("/customer-churn/dashboard/data")
def customer_churn_dashboard_data(run_date: str | None = None):
    try:
        payload = build_phase7_reporting_view_model(PROJECT_ROOT, run_date=run_date)
    except FileNotFoundError as exc:
        return _not_found(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected customer-churn dashboard data error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/customer-churn/tested-actions-approval", response_class=HTMLResponse)
def tested_actions_approval(request: Request, run_date: str | None = None):
    try:
        return _template_response("tested-actions-approval.html")
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected tested-actions approval page error", exc)


@app.get("/customer-churn/tested-actions-approval/data")
def tested_actions_approval_data(request: Request, run_date: str | None = None):
    try:
        payload = build_phase7_review_page_view_model(PROJECT_ROOT, run_date=run_date)
    except FileNotFoundError as exc:
        return _not_found(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected tested-actions approval data error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/customer-churn/new-actions-testing", response_class=HTMLResponse)
def new_actions_testing(request: Request, run_date: str | None = None):
    try:
        return _template_response("new-actions-testing.html")
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected new-actions testing page error", exc)


@app.get("/customer-churn/new-actions-testing/data")
def new_actions_testing_data(request: Request, run_date: str | None = None):
    try:
        payload = build_phase7_review_page_view_model(PROJECT_ROOT, run_date=run_date)
    except FileNotFoundError as exc:
        return _not_found(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected new-actions testing data error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/phase7/integrated-actions/latest")
def phase7_integrated_actions_latest(run_date: str | None = None, refresh: bool = False):
    try:
        if refresh:
            payload = build_integrated_actions(PROJECT_ROOT, run_date=run_date)
            response_payload = {**payload, "integrated": load_integrated_actions(PROJECT_ROOT, payload["run_date"]), "refreshed": True}
        else:
            integrated = load_integrated_actions(PROJECT_ROOT, run_date)
            response_payload = {**integrated, "refreshed": False}
    except FileNotFoundError as exc:
        return _not_found(exc)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 7 integrated actions error", exc)
    return _json_response(HTTPStatus.OK, response_payload)


@app.get("/phase7/stat-tests/latest")
def phase7_stat_tests_latest(run_date: str | None = None):
    try:
        payload = build_phase7_stat_summary(PROJECT_ROOT, run_date=run_date)
    except FileNotFoundError as exc:
        return _not_found(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 7 stat summary error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/phase7/action-history/latest")
def phase7_action_history_latest(run_date: str | None = None):
    try:
        payload = {"status": "ok", "run_date": run_date, "history": load_phase7_action_history(PROJECT_ROOT, run_date=run_date)}
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 7 action history error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/phase7/stat-launch-requests/latest")
def phase7_stat_launch_requests_latest(run_date: str | None = None):
    try:
        payload = {"status": "ok", "run_date": run_date, "requests": load_phase7_launch_requests(PROJECT_ROOT, run_date=run_date)}
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 7 launch request listing error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/phase7/post-test-decisions/pending")
def phase7_post_test_decisions_pending(run_date: str | None = None):
    try:
        payload = build_phase7_post_test_decision_queue(PROJECT_ROOT, run_date=run_date)
    except FileNotFoundError as exc:
        return _not_found(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 7 post-test-decision queue error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/phase7/kpis/latest")
def phase7_kpis_latest(run_date: str | None = None, refresh: bool = False):
    try:
        payload = build_phase7_kpi_status_view(PROJECT_ROOT, run_date=run_date) if refresh else load_latest_phase7_kpi_status(PROJECT_ROOT)
    except FileNotFoundError as exc:
        return _not_found(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 7 KPI status error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.get("/phase7/n8n-payload/latest")
def phase7_n8n_payload_latest(run_date: str | None = None, refresh: bool = False):
    try:
        payload = build_phase7_n8n_payload(PROJECT_ROOT, run_date=run_date) if refresh else load_latest_phase7_n8n_payload(PROJECT_ROOT)
    except FileNotFoundError as exc:
        return _not_found(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 7 n8n payload error", exc)
    return _json_response(HTTPStatus.OK, payload)


@app.post("/events/onesignal")
async def events_onesignal(request: Request):
    try:
        payload = await request.json()
        response_payload = churn_service._ingest_onesignal_events(payload)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected OneSignal ingestion error", exc)
    return _json_response(HTTPStatus.CREATED, response_payload)


@app.post("/phase6/proposals/decision")
async def phase6_proposals_decision(request: Request):
    try:
        payload = await request.json()
        response_payload = record_action_decision(payload, project_root=PROJECT_ROOT)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 6 proposal decision error", exc)
    return _json_response(HTTPStatus.CREATED, response_payload)


@app.post("/phase6/ab-tests/launch")
async def phase6_ab_tests_launch(request: Request):
    try:
        payload = await request.json()
        if "scenario_key" in payload:
            raise ValueError("scenario_key is not accepted by the public API")
        response_payload = launch_ab_test(payload, project_root=PROJECT_ROOT)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 6 A/B launch error", exc)
    return _json_response(HTTPStatus.CREATED, response_payload)


@app.post("/phase7/stat-tests/launch")
def phase7_stat_tests_launch_deprecated():
    return _json_response(
        HTTPStatus.GONE,
        {
            "error": "POST /phase7/stat-tests/launch is no longer a public route; use /phase7/stat-launch-requests and /phase7/stat-launch-requests/execute",
            "deprecated": True,
        },
    )


@app.post("/phase7/actions/decision")
async def phase7_actions_decision(request: Request):
    auth = _require_phase7_review_token(request)
    if auth is not None:
        return auth
    try:
        payload = await request.json()
        response_payload = record_phase7_action_decision(payload, project_root=PROJECT_ROOT)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 7 action decision error", exc)
    return _json_response(HTTPStatus.CREATED, response_payload)


@app.post("/phase7/actions/post-test-decision")
async def phase7_actions_post_test_decision(request: Request):
    auth = _require_phase7_review_token(request)
    if auth is not None:
        return auth
    try:
        payload = await request.json()
        response_payload = record_phase7_post_test_decision(payload, project_root=PROJECT_ROOT)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 7 post-test decision error", exc)
    return _json_response(HTTPStatus.CREATED, response_payload)


@app.post("/phase7/stat-launch-requests")
async def phase7_stat_launch_requests_create(request: Request):
    auth = _require_phase7_review_token(request)
    if auth is not None:
        return auth
    try:
        payload = await request.json()
        response_payload = create_phase7_stat_launch_request(payload, project_root=PROJECT_ROOT)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 7 launch request create error", exc)
    return _json_response(HTTPStatus.CREATED, response_payload)


@app.post("/phase7/stat-launch-requests/execute")
async def phase7_stat_launch_requests_execute(request: Request):
    auth = _require_phase7_review_token(request)
    if auth is not None:
        return auth
    try:
        payload = await request.json()
        response_payload = execute_phase7_stat_launch_request(payload, project_root=PROJECT_ROOT)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected Phase 7 launch request execute error", exc)
    return _json_response(HTTPStatus.CREATED, response_payload)


@app.post("/agent/decisions/shadow")
async def agent_decisions_shadow(request: Request):
    try:
        payload = await request.json()
        response_payload = churn_service._create_shadow_decision(payload, refresh_artifacts=True, refresh_trigger="shadow_create")
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected shadow decision create error", exc)
    return _json_response(HTTPStatus.CREATED, response_payload)


@app.post("/agent/decisions/shadow/run")
async def agent_decisions_shadow_run(request: Request):
    try:
        payload = await request.json()
        response_payload = churn_service._run_shadow_decision_cycle(payload)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected shadow decision run error", exc)
    return _json_response(HTTPStatus.CREATED, response_payload)


@app.post("/agent/decisions/shadow/reconcile")
async def agent_decisions_shadow_reconcile(request: Request):
    try:
        payload = await request.json()
        response_payload = churn_service._reconcile_shadow_decision(payload)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected shadow decision reconcile error", exc)
    return _json_response(HTTPStatus.OK, response_payload)


@app.post("/coupons/generate")
async def coupons_generate(request: Request):
    try:
        payload = await request.json()
        response_payload = churn_service._generate_coupon(payload)
    except ValueError as exc:
        return _bad_request(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        return _internal_error("Unexpected coupon generation error", exc)
    return _json_response(HTTPStatus.CREATED, response_payload)

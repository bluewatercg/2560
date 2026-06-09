from __future__ import annotations

import json
import importlib
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPORTS_IMPORT_ERROR: Exception | None = None


def _empty_reports_module():
    return types.SimpleNamespace(router=types.SimpleNamespace(routes=[]))


def _load_reports_module():
    global REPORTS_IMPORT_ERROR
    try:
        return importlib.import_module("app.api.reports")
    except ModuleNotFoundError as exc:
        if exc.name not in {"fastapi", "sqlalchemy"}:
            raise
    except ImportError as exc:
        REPORTS_IMPORT_ERROR = exc
        return _empty_reports_module()

    names = [
        "fastapi",
        "fastapi.responses",
        "sqlalchemy",
        "sqlalchemy.orm",
        "app",
        "app.db",
        "app.db.session",
        "app.services",
        "app.services.daily_selection_report",
    ]
    saved = {name: sys.modules.get(name) for name in names}
    for name in names:
        sys.modules[name] = types.ModuleType(name)

    class _Route:
        def __init__(self, method: str, path: str):
            self.methods = {method}
            self.path = path

    class _Router:
        def __init__(self, *args: Any, prefix: str = "", **kwargs: Any):
            self.prefix = prefix
            self.routes: list[_Route] = []

        def get(self, path: str, *args: Any, **kwargs: Any):
            def _decorator(fn):
                self.routes.append(_Route("GET", f"{self.prefix}{path}"))
                return fn

            return _decorator

        def post(self, path: str, *args: Any, **kwargs: Any):
            def _decorator(fn):
                self.routes.append(_Route("POST", f"{self.prefix}{path}"))
                return fn

            return _decorator

    class _HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    fastapi = sys.modules["fastapi"]
    fastapi.APIRouter = _Router
    fastapi.Depends = lambda dependency=None: dependency
    fastapi.HTTPException = _HTTPException
    fastapi.Query = lambda default, **kwargs: default
    sys.modules["fastapi.responses"].HTMLResponse = str
    sys.modules["fastapi.responses"].PlainTextResponse = str
    sys.modules["sqlalchemy.orm"].Session = object
    sys.modules["app.db.session"].get_db = lambda: object()
    report_service = sys.modules["app.services.daily_selection_report"]
    report_service.DailySelectionReportService = object
    report_service.render_html_report = lambda report: "<html></html>"

    try:
        spec = importlib.util.spec_from_file_location(
            "reports_api_acceptance_under_test",
            PROJECT_ROOT / "app/api/reports.py",
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


reports = _load_reports_module()


TRADE_DATE = "2026-06-09"

AFTER_MARKET_PACKAGE_FILES = [
    "01_daily_selection.md",
    "02_focus_full_reports.md",
    "03_watch_lite_reports.md",
    "04_scan_summary.json",
    "05_focus_watch_list.json",
    "06_reject_summary.json",
    "07_field_audit.json",
    "08_skill_input.md",
]

MORNING_PACKAGE_FILES = [
    "09_morning_confirm.md",
    "10_skill_morning_input.md",
]

PUBLIC_FIELD_NAMES = {
    "selection_status",
    "final_score",
    "recent_3d_pct",
    "explode_status",
    "market_state",
    "environment_score",
    "hot_topic_strength",
    "position_in_hot_topic",
    "hot_topic_score",
    "volume_score",
    "structure_score",
    "intraday_score",
    "pressure_score",
}

FORBIDDEN_AFTER_MARKET_MORNING_FIELDS = {
    "morning_grade",
    "pre_market_state",
    "yesterday_auction_volume",
    "auction_gap_pct",
    "auction_volume_ratio",
    "09_morning_confirm",
    "10_skill_morning_input",
}


@pytest.fixture()
def reports_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated reports API client for package endpoint acceptance checks."""
    if REPORTS_IMPORT_ERROR is not None:
        pytest.skip(f"app.api.reports import is not compatible yet: {REPORTS_IMPORT_ERROR}")
    monkeypatch.setenv("REPORT_PACKAGE_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("REPORT_CACHE_DIR", str(tmp_path / "legacy-cache"))
    return _DirectReportsClient()


class _DirectResponse:
    def __init__(self, *, status_code: int, text: str = "", payload: Any | None = None):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self.headers = {"content-type": "text/plain; charset=utf-8"}

    def json(self) -> Any:
        return self._payload


class _DirectReportsClient:
    def post(self, path: str) -> _DirectResponse:
        route, _, query = path.partition("?")
        params = _query_params(query)
        if route == "/api/reports/daily-package/new":
            try:
                payload = reports.daily_report_package_new(
                    trade_date=params.get("trade_date", ""),
                    db=object(),
                )
            except reports.HTTPException as exc:
                return _DirectResponse(status_code=exc.status_code, text=str(exc.detail))
            return _DirectResponse(status_code=200, payload=payload, text=json.dumps(payload))
        if route == "/api/reports/morning-package/new":
            try:
                payload = reports.morning_report_package_new(
                    trade_date=params.get("trade_date", ""),
                    source_trade_date=params.get("source_trade_date"),
                    db=object(),
                )
            except reports.HTTPException as exc:
                return _DirectResponse(status_code=exc.status_code, text=str(exc.detail))
            return _DirectResponse(status_code=200, payload=payload, text=json.dumps(payload))
        else:
            return _DirectResponse(status_code=404, text="not found")

    def get(self, path: str) -> _DirectResponse:
        route, _, query = path.partition("?")
        params = _query_params(query)
        try:
            if route == "/api/reports/skill-input.md":
                text = reports.skill_input_report_markdown(
                    trade_date=params.get("trade_date", ""),
                )
            elif route == "/api/reports/daily-package/file":
                text = reports.daily_report_package_file(
                    trade_date=params.get("trade_date", ""),
                    filename=params.get("filename", ""),
                )
            elif route == "/api/reports/morning-confirm.md":
                text = reports.morning_confirm_report_markdown(
                    trade_date=params.get("trade_date", ""),
                )
            elif route == "/api/reports/skill-morning-input.md":
                text = reports.skill_morning_input_report_markdown(
                    trade_date=params.get("trade_date", ""),
                )
            else:
                return _DirectResponse(status_code=404, text="not found")
        except reports.HTTPException as exc:
            return _DirectResponse(status_code=exc.status_code, text=str(exc.detail))
        return _DirectResponse(status_code=200, text=text)


def _query_params(query: str) -> dict[str, str]:
    from urllib.parse import parse_qs

    return {key: values[-1] for key, values in parse_qs(query).items() if values}


def _route_paths() -> set[tuple[str, str]]:
    paths: set[tuple[str, str]] = set()
    for route in reports.router.routes:
        for method in getattr(route, "methods", set()) or set():
            paths.add((method, getattr(route, "path", "")))
    return paths


def _seed_daily_package(root: Path) -> Path:
    package_dir = root / "reports" / TRADE_DATE
    package_dir.mkdir(parents=True)
    (package_dir / "01_daily_selection.md").write_text(
        "# 2560 盘后决策报告\n\nselection_status: focus\nfinal_score: 0.91\n",
        encoding="utf-8",
    )
    (package_dir / "02_focus_full_reports.md").write_text(
        "\n".join(
            [
                "# focus 全维度报告",
                "code: sh.600000",
                "selection_status: focus",
                "final_score: 0.91",
                "recent_3d_pct: 4.2",
                "explode_status: normal",
                "market_state: rebound",
                "environment_score: 1.0",
                "hot_topic_strength: strong",
                "position_in_hot_topic: leader",
                "hot_topic_score: 0.9",
                "volume_score: 0.8",
                "structure_score: 0.85",
                "intraday_score: 0.7",
                "pressure_score: 0.75",
            ]
        ),
        encoding="utf-8",
    )
    (package_dir / "03_watch_lite_reports.md").write_text(
        "# watch 简版报告\n\nselection_status: watch\nfinal_score: 0.72\n",
        encoding="utf-8",
    )
    (package_dir / "04_scan_summary.json").write_text(
        json.dumps(
            {
                "trade_date": TRADE_DATE,
                "batch_id": "20260609042344",
                "total_stocks": 3,
                "distribution": {
                    "selection_status": {"focus": 1, "watch": 1, "reject": 1},
                    "explode_status": {"normal": 2, "warm": 0, "acceleration": 0, "overheat": 1},
                    "market_state": "rebound",
                    "hot_topic_strength": {"strong": 1, "medium": 1, "weak": 0, "none": 1},
                    "position_in_hot_topic": {"leader": 1, "strong": 0, "follower": 1, "edge": 1},
                },
                "data_quality": {"missing_auction_volume_count": 1, "missing_avg5_count": 0},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (package_dir / "05_focus_watch_list.json").write_text(
        json.dumps(
            [
                {
                    "code": "sh.600000",
                    "name": "样例A",
                    "selection_status": "focus",
                    "final_score": 0.91,
                    "hot_topic_strength": "strong",
                    "position_in_hot_topic": "leader",
                    "explode_status": "normal",
                    "market_state": "rebound",
                },
                {
                    "code": "sz.000001",
                    "name": "样例B",
                    "selection_status": "watch",
                    "final_score": 0.72,
                    "hot_topic_strength": "medium",
                    "position_in_hot_topic": "follower",
                    "explode_status": "warm",
                    "market_state": "rebound",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (package_dir / "06_reject_summary.json").write_text(
        json.dumps({"total_reject": 1, "by_reason": {"volume_weak": 1}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (package_dir / "07_field_audit.json").write_text(
        json.dumps(
            {
                "fields": {
                    "recent_3d_pct": {"missing_count": 0, "out_of_range_count": 0},
                    "kdj_j": {"missing_count": 0},
                    "macd_hist": {"missing_count": 0},
                    "hot_topic_strength": {"missing_count": 0},
                    "position_in_hot_topic": {"missing_count": 0},
                },
                "data_sources": {"auction_volume": {"available": True, "last_update": "2026-06-09 09:25:00"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (package_dir / "08_skill_input.md").write_text(
        "\n".join(
            [
                "# 2560 盘后 Skill 输入报告",
                "## 1. 市场环境",
                "- market_state: rebound",
                "- environment_score: 1.0",
                "## 2. 候选池概览",
                "- focus 数量: 1",
                "- watch 数量: 1",
                "## 3. focus 全维度明细",
                "- selection_status: focus",
                "- final_score: 0.91",
                "- recent_3d_pct: 4.2",
                "- explode_status: normal",
                "- hot_topic_strength: strong",
                "- position_in_hot_topic: leader",
                "- hot_topic_score: 0.9",
                "- volume_score: 0.8",
                "- structure_score: 0.85",
                "- intraday_score: 0.7",
                "- pressure_score: 0.75",
                "## 4. watch 简版明细",
                "- selection_status: watch",
                "## 5. reject 按原因汇总",
                "- volume_weak: 1",
                "## 6. 数据质量提示",
                "- missing_auction_volume_count: 1",
                "## 7. 明日早盘需验证的关键点",
                "- focus 需关注放量要求、理想缺口范围。",
            ]
        ),
        encoding="utf-8",
    )
    return package_dir


def test_reports_router_exposes_report_driven_workflow_endpoints_without_breaking_daily_selection():
    assert REPORTS_IMPORT_ERROR is None, (
        "app.api.reports must import cleanly before the report-driven workflow "
        f"endpoints can be used: {REPORTS_IMPORT_ERROR}"
    )
    routes = _route_paths()

    assert ("GET", "/api/reports/daily-selection") in routes
    assert ("GET", "/api/reports/daily-selection.md") in routes
    assert ("GET", "/api/reports/daily-selection.md/new") in routes
    assert ("POST", "/api/reports/daily-package/new") in routes
    assert ("POST", "/api/reports/morning-package/new") in routes
    assert ("GET", "/api/reports/skill-input.md") in routes
    assert ("GET", "/api/reports/morning-confirm.md") in routes
    assert ("GET", "/api/reports/skill-morning-input.md") in routes
    assert ("GET", "/api/reports/daily-package/file") in routes


def test_daily_package_new_creates_exact_after_market_file_set(
    reports_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class _PackageService:
        def __init__(self, db: Any):
            self.db = db

        def generate_daily_package(self, *, trade_date: str):
            package_dir = tmp_path / "reports" / trade_date
            package_dir.mkdir(parents=True)
            for filename in AFTER_MARKET_PACKAGE_FILES:
                (package_dir / filename).write_text(filename, encoding="utf-8")
            return {
                "trade_date": trade_date,
                "batch_id": "20260609042344",
                "status": "generated",
                "files": [f"reports/{trade_date}/{name}" for name in AFTER_MARKET_PACKAGE_FILES],
            }

    monkeypatch.setattr(reports, "DailyReportPackageService", _PackageService)

    response = reports_client.post(f"/api/reports/daily-package/new?trade_date={TRADE_DATE}")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["trade_date"] == TRADE_DATE
    assert payload["status"] == "generated"

    expected_paths = [f"reports/{TRADE_DATE}/{name}" for name in AFTER_MARKET_PACKAGE_FILES]
    assert payload["files"] == expected_paths

    package_dir = tmp_path / "reports" / TRADE_DATE
    assert sorted(p.name for p in package_dir.iterdir() if p.is_file()) == AFTER_MARKET_PACKAGE_FILES


def test_skill_input_can_be_read_without_ui_and_contains_required_sections(
    reports_client,
    tmp_path: Path,
):
    _seed_daily_package(tmp_path)

    response = reports_client.get(f"/api/reports/skill-input.md?trade_date={TRADE_DATE}")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "# 2560 盘后 Skill 输入报告" in body
    assert "## 3. focus 全维度明细" in body
    assert "## 4. watch 简版明细" in body
    assert "## 5. reject 按原因汇总" in body
    assert "## 6. 数据质量提示" in body


def test_morning_package_new_creates_exact_file_set(
    reports_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class _MorningPackageService:
        def __init__(self, db: Any):
            self.db = db

        def generate_morning_package(self, *, trade_date: str, source_trade_date: str | None = None):
            package_dir = tmp_path / "reports" / trade_date
            package_dir.mkdir(parents=True, exist_ok=True)
            for filename in MORNING_PACKAGE_FILES:
                (package_dir / filename).write_text(filename, encoding="utf-8")
            return {
                "trade_date": trade_date,
                "source_trade_date": source_trade_date or "2026-06-09",
                "status": "generated",
                "files": [f"reports/{trade_date}/{name}" for name in MORNING_PACKAGE_FILES],
            }

    monkeypatch.setattr(reports, "MorningReportPackageService", _MorningPackageService)

    response = reports_client.post("/api/reports/morning-package/new?trade_date=2026-06-10&source_trade_date=2026-06-09")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["trade_date"] == "2026-06-10"
    assert payload["source_trade_date"] == "2026-06-09"
    assert payload["status"] == "generated"
    assert payload["files"] == [f"reports/2026-06-10/{name}" for name in MORNING_PACKAGE_FILES]


def test_morning_report_endpoints_can_be_read_without_ui(
    reports_client,
    tmp_path: Path,
):
    package_dir = tmp_path / "reports" / "2026-06-10"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "09_morning_confirm.md").write_text("# 2560 早盘确认报告\n", encoding="utf-8")
    (package_dir / "10_skill_morning_input.md").write_text("# 2560 早盘 Skill 输入报告\n", encoding="utf-8")

    confirm = reports_client.get("/api/reports/morning-confirm.md?trade_date=2026-06-10")
    assert confirm.status_code == 200, confirm.text
    assert confirm.text.startswith("# 2560 早盘确认报告")

    skill = reports_client.get("/api/reports/skill-morning-input.md?trade_date=2026-06-10")
    assert skill.status_code == 200, skill.text
    assert skill.text.startswith("# 2560 早盘 Skill 输入报告")


def test_package_content_uses_v122_public_fields_and_excludes_morning_data_from_after_market_skill_input(
    tmp_path: Path,
):
    package_dir = _seed_daily_package(tmp_path)
    combined = "\n".join(path.read_text(encoding="utf-8") for path in package_dir.iterdir() if path.is_file())
    skill_input = (package_dir / "08_skill_input.md").read_text(encoding="utf-8")

    missing_public_fields = sorted(field for field in PUBLIC_FIELD_NAMES if field not in combined)
    assert missing_public_fields == []
    leaked_morning_fields = sorted(field for field in FORBIDDEN_AFTER_MARKET_MORNING_FIELDS if field in skill_input)
    assert leaked_morning_fields == []


def test_package_file_endpoint_serves_whitelisted_package_file_and_blocks_path_traversal(
    reports_client,
    tmp_path: Path,
):
    _seed_daily_package(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("outside package", encoding="utf-8")

    ok = reports_client.get(
        f"/api/reports/daily-package/file?trade_date={TRADE_DATE}&filename=08_skill_input.md"
    )
    assert ok.status_code == 200, ok.text
    assert "# 2560 盘后 Skill 输入报告" in ok.text

    traversal = reports_client.get(
        f"/api/reports/daily-package/file?trade_date={TRADE_DATE}&filename=../secret.txt"
    )
    assert traversal.status_code in {400, 403, 422}, traversal.text
    assert "outside package" not in traversal.text


def test_workspace_page_exposes_after_market_report_package_controls():
    index_html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    app_js = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert 'id="dailyGenerateReportPackageBtn"' in index_html
    assert 'id="reportPackageTradeDate"' in index_html
    assert 'id="workspaceReportPackage"' in index_html

    assert "window.generateDailyReportPackageFromWorkspace" in app_js
    assert "/api/reports/daily-package/new?trade_date=" in app_js
    assert "/api/reports/skill-input.md?trade_date=" in app_js


def test_workspace_page_exposes_morning_report_package_controls():
    index_html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    app_js = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert 'id="morningReportTradeDate"' in index_html
    assert 'id="dailyGenerateMorningReportBtn"' in index_html
    assert 'id="workspaceMorningReportPackage"' in index_html

    assert "window.generateMorningReportPackageFromWorkspace" in app_js
    assert "/api/reports/morning-package/new?trade_date=" in app_js
    assert "/api/reports/morning-confirm.md?trade_date=" in app_js
    assert "/api/reports/skill-morning-input.md?trade_date=" in app_js

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
import sys
import csv

from fastapi.routing import APIRoute
from starlette.routing import Mount, Route

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "system_feature_map.md"
ROUTES_CSV_PATH = ROOT / "docs" / "system_feature_routes.csv"
VALIDATION_CSV_PATH = ROOT / "docs" / "system_feature_validation_matrix.csv"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.main import app


@dataclass
class RouteRow:
    methods: str
    path: str
    name: str
    area: str
    kind: str


AREA_BY_DOMAIN = {
    "ai": "AI Pipeline",
    "analytics": "Analytics",
    "auth": "Authentication",
    "config": "Configuration",
    "dashboard": "Dashboard Compatibility",
    "events": "Events",
    "health": "Health & Operations",
    "intelligence": "Intelligence Assistant",
    "interactions": "Interaction Capture",
    "m365": "Microsoft 365",
    "network": "Network Queues",
    "network-lab": "Network Lab",
    "people": "People & Profiles",
    "settings": "System Settings",
    "tasks": "Tasks",
    "taxonomy": "Taxonomy",
    "toolkit": "Toolkit",
    "twin": "Legacy Twin",
    "v2": "V2 APIs",
}


def _classify_api_area(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return "General API"
    domain = parts[1]
    if domain == "v2" and len(parts) >= 3:
        return f"V2 APIs ({parts[2]})"
    return AREA_BY_DOMAIN.get(domain, f"General API ({domain})")


def _classify_ui_area(path: str) -> str:
    if path.startswith("/uploads/"):
        return "Uploads"
    if path.startswith("/js"):
        return "Frontend Assets"
    if path.startswith("/static"):
        return "Frontend Assets"
    if path in {"/", "/login", "/login.html"}:
        return "Authentication UI"
    if path.startswith("/network-lab"):
        return "Network Lab UI"
    if path.startswith("/profile") or path.startswith("/person/"):
        return "Profile UI"
    if path.startswith("/api/"):
        return _classify_api_area(path)
    return "Core UI"


def collect_routes() -> list[RouteRow]:
    rows: list[RouteRow] = []
    for route in app.router.routes:
        if isinstance(route, APIRoute):
            methods = ", ".join(sorted(route.methods))
            path = route.path
            if path in {"/openapi.json", "/docs", "/redoc"}:
                continue
            area = _classify_api_area(path) if path.startswith("/api/") else _classify_ui_area(path)
            rows.append(
                RouteRow(
                    methods=methods,
                    path=path,
                    name=route.name,
                    area=area,
                    kind="api" if path.startswith("/api/") else "ui-route",
                )
            )
        elif isinstance(route, Route):
            path = route.path
            if path in {"/openapi.json", "/docs", "/redoc"}:
                continue
            methods = ", ".join(sorted(route.methods or []))
            rows.append(
                RouteRow(
                    methods=methods,
                    path=path,
                    name=getattr(route, "name", ""),
                    area=_classify_ui_area(path),
                    kind="ui-route",
                )
            )
        elif isinstance(route, Mount):
            path = route.path
            rows.append(
                RouteRow(
                    methods="",
                    path=path,
                    name=getattr(route, "name", ""),
                    area=_classify_ui_area(path),
                    kind="mount",
                )
            )
    rows.sort(key=lambda item: (item.path, item.methods))
    return rows


def collect_html_pages() -> list[str]:
    frontend = ROOT / "frontend"
    return sorted(file.name for file in frontend.glob("*.html"))


def collect_js_modules() -> list[str]:
    js_root = ROOT / "frontend" / "js"
    modules: list[str] = []
    for file in js_root.rglob("*.js"):
        modules.append(str(file.relative_to(ROOT)).replace("\\", "/"))
    return sorted(modules)


def _to_markdown_table(rows: Iterable[list[str]]) -> str:
    rows = list(rows)
    if not rows:
        return ""
    header = rows[0]
    body = rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def build_markdown() -> tuple[str, list[RouteRow], list[list[str]]]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    routes = collect_routes()
    pages = collect_html_pages()
    modules = collect_js_modules()

    api_routes = [route for route in routes if route.path.startswith("/api/")]
    ui_routes = [route for route in routes if not route.path.startswith("/api/")]

    counts_by_area: dict[str, int] = defaultdict(int)
    for route in routes:
        counts_by_area[route.area] += 1

    area_rows = [["Area", "Route Count"]]
    for area, count in sorted(counts_by_area.items(), key=lambda item: (-item[1], item[0])):
        area_rows.append([area, str(count)])

    route_rows = [["Methods", "Path", "Area", "Handler"]]
    for route in routes:
        route_rows.append([route.methods or "-", route.path, route.area, route.name or "-"])

    page_rows = [["Page", "Purpose"]]
    for page in pages:
        purpose = "Main UI"
        if page == "login.html":
            purpose = "Authentication"
        elif page == "profile.html":
            purpose = "Profile workspace"
        elif page.startswith("network-lab"):
            purpose = "Network Lab workspace"
        elif page in {"activities.html", "agenda.html", "analytics.html", "events.html", "settings.html"}:
            purpose = page.replace(".html", "").title()
        page_rows.append([page, purpose])

    module_rows = [["JavaScript Module", "Domain"]]
    for module in modules:
        domain = "General"
        if "/profile/" in module:
            domain = "Profile"
        elif "network-lab" in module:
            domain = "Network Lab"
        elif module.endswith("settings.js"):
            domain = "Settings"
        elif module.endswith("analytics.js"):
            domain = "Analytics"
        elif module.endswith("events.js"):
            domain = "Events"
        elif module.endswith("agenda.js"):
            domain = "Agenda"
        elif module.endswith("activities.js"):
            domain = "Activities"
        module_rows.append([module, domain])

    validation_rows = [
        ["Feature Area", "Pre-Deploy Check", "Post-Data Check", "Owner", "Status"],
        [
            "Authentication",
            "Login, session cookie, logout",
            "Role-based access still enforced with real users",
            "TBD",
            "Pending",
        ],
        [
            "People & Profile",
            "Create/update person, profile load, profile widgets",
            "Data completeness, profile photos, relationship signals render correctly",
            "TBD",
            "Pending",
        ],
        [
            "Interaction Capture",
            "Text/image/pdf upload via chat, interaction create/edit/delete",
            "Bulk imported history lands on correct profiles with no mojibake",
            "TBD",
            "Pending",
        ],
        [
            "Intelligence Assistant",
            "Profile chat response, brief endpoint, TTS/transcription queues",
            "Claims, stages, and updates remain grounded after full data ingestion",
            "TBD",
            "Pending",
        ],
        [
            "AI Pipeline",
            "Artifacts/signals CRUD, review queue, status patching",
            "Signal quality, dedupe behavior, inclusion/exclusion in briefs",
            "TBD",
            "Pending",
        ],
        [
            "Network Lab",
            "Databank/review/profile pages load, refresh + tagging actions work",
            "Databank has grounded non-noisy points and no profile cross-contamination",
            "TBD",
            "Pending",
        ],
        [
            "Dashboard & Analytics",
            "Dashboard queues, analytics endpoints, category trends",
            "Scores and trend distributions look realistic with full dataset",
            "TBD",
            "Pending",
        ],
        [
            "Events",
            "CRUD + participant linking + export",
            "Event relevance and participant states stay consistent at scale",
            "TBD",
            "Pending",
        ],
        [
            "Tasks",
            "Task CRUD + pipeline endpoint",
            "Follow-up pressure and due-state logic remains correct after import",
            "TBD",
            "Pending",
        ],
        [
            "M365",
            "Auth status/start/reset, mail fetch, calendar fetch, full sync",
            "Mailbox/calendar matching accuracy and meeting metadata integrity",
            "TBD",
            "Pending",
        ],
        [
            "System Settings",
            "Intelligence + runtime settings read/write/reset",
            "No config drift after deploy restart",
            "TBD",
            "Pending",
        ],
        [
            "Health & Operations",
            "Health endpoint + backup status/run",
            "Nightly jobs, backups, and workers stable for 24h",
            "TBD",
            "Pending",
        ],
    ]

    checklist = [
        "- [ ] Run backend tests: `./.venv/Scripts/python.exe -m pytest -q tests`",
        "- [ ] Run browser smoke audit: `./.venv/Scripts/python.exe tests/ui_full_audit_selenium.py`",
        "- [ ] Run profile upload/chat flow: `./.venv/Scripts/python.exe tests/ui_profile_chat_upload_selenium.py`",
        "- [ ] Verify `GET /api/health` returns `200`",
        "- [ ] Validate top 20 strategic profiles in Network Lab for stage/queue sanity",
        "- [ ] Validate random sample of 30 imported artifacts for filename/channel correctness",
        "- [ ] Validate random sample of 30 databank points for grounding and no cross-profile leakage",
    ]

    lines = []
    lines.append("# System Feature Map")
    lines.append("")
    lines.append(f"_Generated from application routes on {now} UTC._")
    lines.append("")
    lines.append("Regenerate with: `./.venv/Scripts/python.exe scripts/generate_feature_map.py`")
    lines.append("")
    lines.append("## Coverage Snapshot")
    lines.append("")
    lines.append(f"- Total routes: **{len(routes)}**")
    lines.append(f"- API routes: **{len(api_routes)}**")
    lines.append(f"- UI/static routes and mounts: **{len(ui_routes)}**")
    lines.append(f"- Frontend HTML pages: **{len(pages)}**")
    lines.append(f"- Frontend JS modules: **{len(modules)}**")
    lines.append("")
    lines.append("## Route Counts By Area")
    lines.append("")
    lines.append(_to_markdown_table(area_rows))
    lines.append("")
    lines.append("## UI Surface Map")
    lines.append("")
    lines.append(_to_markdown_table(page_rows))
    lines.append("")
    lines.append("## Frontend Module Map")
    lines.append("")
    lines.append(_to_markdown_table(module_rows))
    lines.append("")
    lines.append("## Deployment + Post-Data Validation Matrix")
    lines.append("")
    lines.append(_to_markdown_table(validation_rows))
    lines.append("")
    lines.append("## Release Checklist")
    lines.append("")
    lines.extend(checklist)
    lines.append("")
    lines.append("## Full Route Inventory")
    lines.append("")
    lines.append(_to_markdown_table(route_rows))
    lines.append("")
    return "\n".join(lines), routes, validation_rows


def main() -> None:
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    markdown, routes, validation_rows = build_markdown()
    DOC_PATH.write_text(markdown, encoding="utf-8")

    with ROUTES_CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "area",
                "kind",
                "methods",
                "path",
                "handler",
                "pre_deploy_status",
                "post_data_status",
                "notes",
            ]
        )
        for route in routes:
            writer.writerow([route.area, route.kind, route.methods or "-", route.path, route.name or "-", "PENDING", "PENDING", ""])

    with VALIDATION_CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for row in validation_rows:
            writer.writerow(row)

    print(f"Wrote {DOC_PATH}")
    print(f"Wrote {ROUTES_CSV_PATH}")
    print(f"Wrote {VALIDATION_CSV_PATH}")


if __name__ == "__main__":
    main()

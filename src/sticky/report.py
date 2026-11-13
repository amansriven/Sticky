"""One JSON document with everything a UI needs: recorder health and findings.

The menu bar app runs ``sticky report --json`` instead of re-implementing the
diagnosis rules, so the Python engine stays the single source of truth.
"""

from __future__ import annotations

import os
import plistlib
from pathlib import Path
from typing import Callable

from . import __version__
from .diagnose import diagnose, ignored_by, service_name
from .identity import code_path_for
from .store import Store, now_ts, parse_duration, ts_ago

STALE_AFTER = "3m"  # no heartbeat for this long = not healthy


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def recorder_health(store: Store, agent_installed: bool, agent_loaded: bool) -> dict:
    """``state`` is running | stale | stopped | never."""
    run = store.latest_run()
    health = {
        "agent_installed": agent_installed,
        "agent_loaded": agent_loaded,
        "decisions_total": store.count_events(),
        "state": "never",
    }
    if run is None:
        return health
    running = run["ended_at"] is None and pid_alive(run["pid"])
    stale = run["heartbeat"] is not None and run["heartbeat"] < ts_ago(parse_duration(STALE_AFTER))
    note = run["note"] or "process ended without saying why"
    health.update(
        state="running" if running and not stale else "stale" if running else "stopped",
        stopped_reason=None if running else note,
        pid=run["pid"],
        run_id=run["id"],
        started_at=run["started_at"],
        heartbeat=run["heartbeat"],
        last_record=run["last_record"],
        records=run["records"],
        requests=run["requests"],
        decisions=run["decisions"],
        restarts=run["restarts"],
    )
    return health


def app_name(client_id: str, path: str | None, fallback: str | None = None) -> str:
    """A display name from the app's Info.plist (cheap: no codesign)."""
    if path:
        info = code_path_for(path) / "Contents" / "Info.plist"
        try:
            with open(info, "rb") as f:
                plist = plistlib.load(f)
            name = plist.get("CFBundleDisplayName") or plist.get("CFBundleName")
            if name:
                return str(name)
        except Exception:
            pass
        if Path(path).suffix == ".app":
            return Path(path).stem
    if "/" in client_id:  # identified by path, e.g. /usr/libexec/foo
        return Path(client_id).name
    return fallback or client_id.rsplit(".", 1)[-1] or client_id


APPLE_PATHS = ("/System/", "/usr/", "/Library/Apple/", "/sbin/", "/bin/")


def app_kind(client_id: str, path: str | None, platform: bool | None) -> str:
    """"system" for Apple's own processes and daemons, else "app"."""
    if platform:
        return "system"
    p = path or (client_id if client_id.startswith("/") else "")
    if p.startswith(APPLE_PATHS):
        return "system"
    if client_id.startswith("com.apple.") and not p.startswith("/Applications/"):
        return "system"
    return "app"


def activity(store: Store, hours: int = 24, include_system: bool = False) -> dict:
    """Decisions per hour for the last ``hours`` hours, oldest first.

    Counts your apps only by default: system services are refused default-off
    permissions constantly (about 250 times a day on the test Mac), which
    would make the chart look alarming while meaning nothing.
    """
    from datetime import datetime, timedelta

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=hours - 1)
    buckets = {(start + timedelta(hours=i)).strftime("%Y-%m-%d %H"): {"allowed": 0, "denied": 0, "asked": 0}
               for i in range(hours)}
    rows = store.db.execute(
        "SELECT ts_start, client_id, client_path, client_platform, prompted, final_auth FROM events "
        "WHERE ts_start >= ? AND entitled = 0 AND client_id IS NOT NULL "
        "AND service <> 'kTCCServiceDeveloperTool' AND NOT (preflight = 1 AND final_auth = 1)",
        (start.strftime("%Y-%m-%d %H:00:00.000"),)).fetchall()
    apps = set()
    for r in rows:
        if not include_system and app_kind(r["client_id"], r["client_path"], r["client_platform"]) == "system":
            continue
        b = buckets.get(r["ts_start"][:13])
        if b is None:
            continue
        apps.add(r["client_id"])
        if r["prompted"]:
            b["asked"] += 1
        elif r["final_auth"] == 2:
            b["allowed"] += 1
        elif r["final_auth"] == 0:
            b["denied"] += 1
    series = [{"hour": h + ":00", **v} for h, v in buckets.items()]
    totals = {k: sum(b[k] for b in series) for k in ("allowed", "denied", "asked")}
    totals["apps"] = len(apps)
    return {"hours": series, "totals": totals}


def build_report(
    store: Store,
    since: str | None = "30d",
    agent_state: Callable[[], tuple[bool, bool]] | None = None,
) -> dict:
    """``agent_state`` returns (installed, loaded); injectable for tests."""
    if agent_state is None:
        from . import agent

        def agent_state():
            installed = agent.is_installed()
            return installed, agent.is_loaded() if installed else False

    installed, loaded = agent_state()
    cutoff = None if since in (None, "all") else ts_ago(parse_duration(since))
    rows = store.query_events(since=cutoff)
    clients = {r["client_id"] for r in rows if r["client_id"]}
    results = diagnose(rows, {c: store.identities_for(c) for c in clients})
    ignores = [dict(r) for r in store.list_ignores()]
    hidden: dict[int, int] = {}  # ignore id -> findings it currently hides

    apps: dict[str, dict] = {}
    problems: list[dict] = []
    for g, findings in results:
        path = next((e.get("client_path") for e in reversed(g.events) if e.get("client_path")),
                    None) or store.latest_path_for(g.client_id)
        name_hint = next((e.get("client_name") for e in g.events if e.get("client_name")), None)
        platform = next((e.get("client_platform") for e in reversed(g.events)
                         if e.get("client_platform") is not None), None)
        app = apps.setdefault(g.client_id, {
            "client_id": g.client_id,
            "app_name": app_name(g.client_id, path, name_hint),
            "app_path": path,
            "kind": app_kind(g.client_id, path, platform),
            "last_seen": "",
            "permissions": [],
        })
        finding_dicts = []
        for f in findings:
            d = f.to_dict()
            d["ignored_by"] = ignored_by(f, ignores) if f.severity != "ok" else None
            if d["ignored_by"] is not None:
                hidden[d["ignored_by"]] = hidden.get(d["ignored_by"], 0) + 1
            finding_dicts.append(d)
        severities = [d["severity"] for d in finding_dicts if d["ignored_by"] is None]
        status = next((s for s in ("problem", "info", "ok") if s in severities), "none")
        permission = {
            "service": g.service,
            "service_name": service_name(g.service),
            "target": g.target,
            "label": g.label,
            "requests": len(g.events),
            "last_seen": g.latest["ts_start"],
            "last_outcome": g.latest.get("outcome"),
            "status": status,
            "findings": finding_dicts,
        }
        app["permissions"].append(permission)
        app["last_seen"] = max(app["last_seen"], permission["last_seen"])
        for d in finding_dicts:
            if d["severity"] == "problem" and d["ignored_by"] is None:
                problems.append({**d, "app_name": app["app_name"], "app_path": path,
                                 "app_kind": app["kind"],
                                 "service_name": permission["service_name"],
                                 "label": g.label})

    order = {"problem": 0, "info": 1, "ok": 2, "none": 3}
    for app in apps.values():
        app["permissions"].sort(key=lambda p: (order[p["status"]], p["label"]))
        app["status"] = min((p["status"] for p in app["permissions"]), key=order.__getitem__,
                            default="none")
    problems.sort(key=lambda p: p["when"] or "", reverse=True)
    return {
        "sticky_version": __version__,
        "generated_at": now_ts(),
        "since": cutoff,
        "recorder": recorder_health(store, installed, loaded),
        "problems": problems,
        "activity": activity(store),
        "ignored": [
            {**ig, "app_name": apps[ig["client_id"]]["app_name"] if ig["client_id"] in apps
             else app_name(ig["client_id"], store.latest_path_for(ig["client_id"])),
             "service_name": service_name(ig["service"]) if ig["service"] else None,
             "hiding": hidden.get(ig["id"], 0)}
            for ig in ignores
        ],
        "apps": sorted(apps.values(), key=lambda a: a["last_seen"], reverse=True),
    }

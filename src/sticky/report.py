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
from .diagnose import diagnose, service_name
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

    apps: dict[str, dict] = {}
    problems: list[dict] = []
    for g, findings in results:
        path = next((e.get("client_path") for e in reversed(g.events) if e.get("client_path")),
                    None) or store.latest_path_for(g.client_id)
        name_hint = next((e.get("client_name") for e in g.events if e.get("client_name")), None)
        app = apps.setdefault(g.client_id, {
            "client_id": g.client_id,
            "app_name": app_name(g.client_id, path, name_hint),
            "app_path": path,
            "last_seen": "",
            "permissions": [],
        })
        severities = [f.severity for f in findings]
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
            "findings": [f.to_dict() for f in findings],
        }
        app["permissions"].append(permission)
        app["last_seen"] = max(app["last_seen"], permission["last_seen"])
        for f in findings:
            if f.severity == "problem":
                problems.append({**f.to_dict(), "app_name": app["app_name"], "app_path": path,
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
        "apps": sorted(apps.values(), key=lambda a: a["last_seen"], reverse=True),
    }

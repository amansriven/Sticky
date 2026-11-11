"""Turn recorded permission decisions into plain-English findings.

Rules (see sticky-design.md §2.6):

R1  Grant didn't stick: macOS prompted again for an app + service + target
    that already had a saved answer. The cause is one of:
    R1a  path moved     the app is identified by its location, and it moved
    R1b  identity changed  its signing requirement differs from the one in
                        force when the earlier answer was saved
    R1c  blamed on a different app  the same tool was granted under one
                        app, but macOS now holds a different app responsible
    R1d  reset externally  same identity, same place: the saved answer was
                        removed (tccutil, System Settings, or MDM)
R2  Silent denial: the saved answer is "deny", so requests are refused
    without asking.
R4  Prompt storm: three or more prompts for one app + service + target in
    24 hours.
R5  Kept its grant after a rebuild (info): the app was rebuilt with a
    different signing identity since you approved it, macOS still allowed
    it without asking, and the log didn't show the usual "Requirements
    match" check. Observed on macOS 27.2.1 for Automation with an ad-hoc
    signed app (week 3 test): the rebuild did NOT cause a new prompt.
R6  Switched on, but not for this build: tccd checked the current build
    against the requirement saved with the grant and it failed (status
    -67050), so access is denied without asking, while System Settings
    still shows the app switched on. Observed on macOS 27.2.1 for
    Accessibility after rebuilding an ad-hoc signed app (BrokenTool ax1 ->
    ax2). Replaces R2 when it applies.

Ignored: entitlement shortcuts, "would this prompt?" preflight checks that
decided nothing, and services that never prompt (Developer Tools, which
syspolicyd checks on every app launch).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Mapping

SERVICE_NAMES = {
    "kTCCServiceAppleEvents": "Automation",
    "kTCCServiceAccessibility": "Accessibility",
    "kTCCServicePostEvent": "Accessibility (send events)",
    "kTCCServiceListenEvent": "Input Monitoring",
    "kTCCServiceScreenCapture": "Screen Recording",
    "kTCCServiceSystemPolicyAllFiles": "Full Disk Access",
    "kTCCServiceSystemPolicyDesktopFolder": "Desktop folder",
    "kTCCServiceSystemPolicyDocumentsFolder": "Documents folder",
    "kTCCServiceSystemPolicyDownloadsFolder": "Downloads folder",
    "kTCCServiceSystemPolicyNetworkVolumes": "Network volumes",
    "kTCCServiceSystemPolicyRemovableVolumes": "Removable volumes",
    "kTCCServiceCamera": "Camera",
    "kTCCServiceMicrophone": "Microphone",
    "kTCCServiceAddressBook": "Contacts",
    "kTCCServiceCalendar": "Calendars",
    "kTCCServiceReminders": "Reminders",
    "kTCCServicePhotos": "Photos",
    "kTCCServiceMediaLibrary": "Media & Apple Music",
    "kTCCServiceDeveloperTool": "Developer Tools",
    "kTCCServiceBluetoothAlways": "Bluetooth",
    "kTCCServiceSpeechRecognition": "Speech Recognition",
    "kTCCServiceUbiquity": "iCloud",
}

# Anchors for x-apple.systempreferences:com.apple.preference.security?<anchor>
SETTINGS_ANCHORS = {
    "kTCCServiceAppleEvents": "Privacy_Automation",
    "kTCCServiceAccessibility": "Privacy_Accessibility",
    "kTCCServicePostEvent": "Privacy_Accessibility",
    "kTCCServiceListenEvent": "Privacy_ListenEvent",
    "kTCCServiceScreenCapture": "Privacy_ScreenCapture",
    "kTCCServiceSystemPolicyAllFiles": "Privacy_AllFiles",
    "kTCCServiceCamera": "Privacy_Camera",
    "kTCCServiceMicrophone": "Privacy_Microphone",
    "kTCCServiceAddressBook": "Privacy_Contacts",
    "kTCCServiceCalendar": "Privacy_Calendars",
    "kTCCServiceReminders": "Privacy_Reminders",
    "kTCCServicePhotos": "Privacy_Photos",
    "kTCCServiceDeveloperTool": "Privacy_DevTools",
}

# Services macOS checks without ever prompting; a "deny" there is the default,
# not something the user chose.
NON_PROMPTING_SERVICES = {"kTCCServiceDeveloperTool"}

PROMPT_STORM_COUNT = 3
PROMPT_STORM_WINDOW = timedelta(hours=24)


def service_name(service: str | None) -> str:
    if not service:
        return "unknown permission"
    return SERVICE_NAMES.get(service, service.removeprefix("kTCCService"))


def settings_url(service: str | None) -> str:
    anchor = SETTINGS_ANCHORS.get(service or "", "Privacy")
    return f"x-apple.systempreferences:com.apple.preference.security?{anchor}"


def tccutil_command(service: str | None, client_id: str | None) -> str | None:
    if not service or not client_id or "/" in client_id:
        return None  # tccutil only resets by bundle id
    return f"tccutil reset {service.removeprefix('kTCCService')} {client_id}"


@dataclass
class Finding:
    rule: str  # R1a | R1b | R1c | R1d | R2 | R4 | OK
    severity: str  # problem | info | ok
    client_id: str
    service: str
    target: str | None
    title: str
    detail: list[str] = field(default_factory=list)
    fix: list[str] = field(default_factory=list)
    when: str | None = None  # timestamp of the event the finding is about

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Group:
    """Every prompt-capable decision for one app + permission + target."""

    client_id: str
    service: str
    target: str | None
    events: list[dict]

    @property
    def label(self) -> str:
        name = service_name(self.service)
        return f"{name} → {self.target}" if self.target else name

    @property
    def latest(self) -> dict:
        return self.events[-1]


def _counts_as_decision(e: Mapping) -> bool:
    return (
        e.get("service") is not None
        and e.get("service") not in NON_PROMPTING_SERVICES
        and e.get("final_auth") is not None
        and not e.get("entitled")
        # Preflight checks that decided something count: Accessibility and
        # similar services are only ever checked this way.
        and not (e.get("preflight") and e.get("final_auth") == 1)
    )


def _target(e: Mapping) -> str | None:
    return e.get("target_id") or e.get("target_name")


def group_events(events: Iterable[Mapping]) -> list[Group]:
    groups: dict[tuple, Group] = {}
    for e in sorted((dict(e) for e in events), key=lambda e: e["ts_start"]):
        if not _counts_as_decision(e) or not e.get("client_id"):
            continue
        key = (e["client_id"], e["service"], _target(e))
        groups.setdefault(key, Group(*key, events=[])).events.append(e)
    return list(groups.values())


def _short_dr(dr: str | None) -> str:
    if not dr:
        return "unknown"
    return dr if len(dr) <= 90 else dr[:87] + "…"


def _when(ts: str | None) -> str:
    return ts[5:16] if ts else "?"


def diagnose_group(g: Group, all_groups: list[Group] | None = None,
                   builds: list[Mapping] | None = None) -> list[Finding]:
    """``builds``: identity snapshots for this app, oldest first (store.identities_for)."""
    findings: list[Finding] = []
    base = dict(client_id=g.client_id, service=g.service, target=g.target)

    # R1: prompted again after a saved answer existed.
    for i, ev in enumerate(g.events):
        if not ev.get("prompted") or i == 0:
            continue
        earlier = g.events[:i]
        settled = [e for e in earlier if e.get("final_auth") in (0, 2, 3)]
        if not settled:
            continue
        findings.append(_why_reprompted(g, ev, earlier, settled[-1], all_groups or [], base))

    # R1c can also explain a *first* prompt for this app: the same tool was
    # already allowed while a different app was held responsible.
    first = g.events[0]
    if first.get("prompted") and all_groups:
        other = _granted_under_other_app(first, g, all_groups)
        if other is not None:
            findings.append(_blamed_finding(first, other, base))

    # R6: denied because this build doesn't match the saved requirement.
    last = g.latest
    r6 = _not_for_this_build(g, base)
    if r6 is not None:
        findings.append(r6)

    # R2: the saved answer is "deny".
    if last.get("final_auth") == 0 and r6 is None:
        denied_at = next(
            (e for e in reversed(g.events) if e.get("prompted") and e.get("final_auth") == 0), None
        )
        refused = [e for e in g.events if e["ts_start"] > (denied_at or last)["ts_start"]
                   and e.get("final_auth") == 0 and not e.get("prompted")]
        detail = []
        if denied_at:
            detail.append(f"You chose \"Don't Allow\" on {_when(denied_at['ts_start'])}.")
        else:
            detail.append("It was denied before Sticky started recording.")
        if refused or not last.get("prompted"):
            n = len(refused) or 1
            detail.append(f"macOS won't ask again: {n} request{'s' if n != 1 else ''} since "
                          f"{'were' if n != 1 else 'was'} refused without a prompt.")
        fix = [f"Turn it on in System Settings → Privacy & Security → {service_name(g.service)}: "
               f"open \"{settings_url(g.service)}\""]
        if cmd := tccutil_command(g.service, g.client_id):
            fix.append(f"Or make macOS ask again: {cmd}"
                       + (" (resets this app's Automation for every target)"
                          if g.service == "kTCCServiceAppleEvents" else ""))
        findings.append(Finding("R2", "problem", **base, when=last["ts_start"],
                                title="Denied: requests are refused silently", detail=detail, fix=fix))

    # R4: prompt storm.
    prompts = [e for e in g.events if e.get("prompted")]
    for i in range(len(prompts) - PROMPT_STORM_COUNT + 1):
        window = prompts[i : i + PROMPT_STORM_COUNT]
        if _parse(window[-1]["ts_start"]) - _parse(window[0]["ts_start"]) <= PROMPT_STORM_WINDOW:
            findings.append(Finding(
                "R4", "info", **base, when=window[-1]["ts_start"],
                title=f"Asked {len(prompts)} times",
                detail=[f"{PROMPT_STORM_COUNT} prompts within 24 hours, the latest on "
                        f"{_when(window[-1]['ts_start'])}."],
            ))
            break

    # R5: allowed after a rebuild without the usual signature match.
    if (r5 := _kept_after_rebuild(g, builds or [], base)) is not None:
        findings.append(r5)

    if not any(f.severity == "problem" for f in findings) and last.get("final_auth") == 2 \
            and not any(f.rule == "R4" for f in findings):
        n = len(g.events)
        allowed = sum(1 for e in g.events if e.get("final_auth") == 2)
        # Automation logs "Requirements match"; direct requests log a stored-requirement check.
        matched = sum(1 for e in g.events
                      if e.get("requirements_match") or e.get("stored_dr_status") == 0)
        detail = [f"{allowed} of {n} recorded request{'s' if n != 1 else ''} allowed"
                  + (f"; the saved approval matched the app on {matched}." if matched else ".")]
        denied = [e for e in g.events if e.get("final_auth") == 0]
        if denied:
            since = next(e for e in g.events
                         if e["ts_start"] > denied[-1]["ts_start"] and e.get("final_auth") == 2)
            detail.append(f"Denied {len(denied)} time{'s' if len(denied) != 1 else ''} before, "
                          f"last on {_when(denied[-1]['ts_start'])}; allowed again since "
                          f"{_when(since['ts_start'])}.")
        findings.append(Finding("OK", "ok", **base, when=last["ts_start"], title="Allowed",
                                detail=detail))
    return findings


def _why_reprompted(g: Group, ev: dict, earlier: list[dict], settled: dict,
                    all_groups: list[Group], base: dict) -> Finding:
    when = ev["ts_start"]
    prior_drs = [e for e in earlier if e.get("client_dr")]
    old_dr = prior_drs[-1]["client_dr"] if prior_drs else None
    new_dr = ev.get("client_dr")
    answer = {0: "denied", 2: "allowed", 3: "limited"}.get(settled.get("final_auth"), "answered")
    lead = (f"Prompted again on {_when(when)}, although it was {answer} on "
            f"{_when(settled['ts_start'])}.")

    if old_dr and new_dr and old_dr != new_dr:
        adhoc = new_dr.startswith("cdhash")
        detail = [lead, "The app's signing identity changed, so macOS treated it as a new app:",
                  f"  before: {_short_dr(old_dr)}", f"  now:    {_short_dr(new_dr)}"]
        if adhoc:
            detail.append("It's ad-hoc signed: its identity is a hash of the exact build, so a "
                          "rebuild or update can lose its permissions.")
        fix = ["Sign it with a stable identity (a Developer ID or Apple Development certificate). "
               "macOS then ties permissions to the bundle id and team, which survive rebuilds."]
        if adhoc:
            fix.append("For your own builds: sign every build with the same certificate, "
                       "e.g. codesign -s \"Apple Development: …\" <app>")
        return Finding("R1b", "problem", **base, when=when,
                       title="Asked again: the app's signing identity changed",
                       detail=detail, fix=fix)

    old_path, new_path = settled.get("client_path"), ev.get("client_path")
    path_identity = ev.get("client_type") == 1 or not new_dr
    if old_path and new_path and old_path != new_path and path_identity:
        return Finding("R1a", "problem", **base, when=when,
                       title="Asked again: the app moved",
                       detail=[lead, "macOS identifies this app by its location, and it moved:",
                               f"  before: {old_path}", f"  now:    {new_path}"],
                       fix=["Keep it at one fixed path (e.g. a symlink that updates point to), "
                            "or sign it so macOS identifies it by bundle id and team instead."])

    return Finding("R1d", "problem", **base, when=when,
                   title="Asked again: the saved answer was removed",
                   detail=[lead, "The app's identity and location didn't change, so the saved "
                                 "answer was removed: by tccutil reset, by switching it off and "
                                 "back on in System Settings, or by a management profile."],
                   fix=["If this keeps happening on a managed Mac, ask your IT team whether a "
                        "profile resets privacy permissions."])


def _not_for_this_build(g: Group, base: dict) -> Finding | None:
    from .rules import REQUIREMENT_FAILED

    last = g.latest
    if last.get("final_auth") != 0 or last.get("stored_dr_status") != REQUIREMENT_FAILED:
        return None
    first_fail = next(e for e in g.events
                      if e.get("final_auth") == 0 and e.get("stored_dr_status") == REQUIREMENT_FAILED
                      and e["ts_start"] >= _last_allowed_ts(g))
    allowed_before = [e for e in g.events
                      if e["ts_start"] < first_fail["ts_start"] and e.get("final_auth") == 2]
    n = sum(1 for e in g.events if e["ts_start"] >= first_fail["ts_start"]
            and e.get("final_auth") == 0)
    name = service_name(g.service)
    detail = [f"Your approval is saved for the build signed as {_short_dr(last.get('stored_dr'))}."]
    if last.get("client_dr"):
        detail.append(f"The current build is signed as {_short_dr(last['client_dr'])}, which "
                      f"doesn't match it, so macOS denies access without asking.")
    else:
        detail.append("The current build doesn't match it, so macOS denies access without asking.")
    if allowed_before:
        detail.append(f"It worked until {_when(allowed_before[-1]['ts_start'])}; "
                      f"{n} request{'s' if n != 1 else ''} since {'were' if n != 1 else 'was'} "
                      f"denied.")
    detail.append(f"System Settings → Privacy & Security → {name} may still show it switched on.")
    # Verified on macOS 27.2.1 (BrokenTool ax2): switching it off and on keeps
    # the old build's requirement; removing and re-adding saves the new one.
    fix = [f"Re-approve this build: in System Settings → {name}, remove the app with − and add "
           f"it again with + (open \"{settings_url(g.service)}\"). Switching it off and on "
           f"isn't enough: the approval keeps naming the old build."]
    if cmd := tccutil_command(g.service, g.client_id):
        fix.append(f"Or clear the stale approval from Terminal ({cmd}), then add it again.")
    if (last.get("client_dr") or last.get("stored_dr") or "").startswith("cdhash"):
        fix.append("To stop this after every rebuild, sign with a stable identity (Developer ID "
                   "or Apple Development certificate) instead of ad-hoc.")
    return Finding("R6", "problem", **base, when=last["ts_start"],
                   title="Switched on, but not for this build", detail=detail, fix=fix)


def _last_allowed_ts(g: Group) -> str:
    allowed = [e["ts_start"] for e in g.events if e.get("final_auth") == 2]
    return allowed[-1] if allowed else ""


def _kept_after_rebuild(g: Group, builds: list[Mapping], base: dict) -> Finding | None:
    last = g.latest
    if last.get("final_auth") != 2 or last.get("prompted") or last.get("requirements_match"):
        return None
    approved = next((e for e in reversed(g.events)
                     if e.get("prompted") and e.get("final_auth") == 2 and e.get("client_dr")), None)
    if approved is None or not builds:
        return None
    current = builds[-1]
    if not current["dr"] or current["dr"] == approved["client_dr"]:
        return None
    return Finding(
        "R5", "info", **base, when=last["ts_start"],
        title="Kept its permission after a rebuild",
        detail=[f"You approved the build signed as {_short_dr(approved['client_dr'])} "
                f"on {_when(approved['ts_start'])}.",
                f"The current build is signed as {_short_dr(current['dr'])} "
                f"(first seen {_when(current['first_seen'])}), which doesn't match,",
                f"yet macOS allowed it on {_when(last['ts_start'])} without asking, and the log "
                f"didn't show its usual signature-match check.",
                "macOS 27 carried the earlier answer over to the new build. Other permissions "
                "(or other macOS versions) may not, so a rebuild can still cause a new prompt."],
    )


def _granted_under_other_app(ev: dict, g: Group, all_groups: list[Group]) -> dict | None:
    tool = ev.get("requesting_id") or ev.get("accessing_id")
    if not tool or tool == g.client_id:
        return None
    for other in all_groups:
        if other is g or other.service != g.service or other.target != g.target:
            continue
        for e in other.events:
            if (e["ts_start"] < ev["ts_start"] and e.get("final_auth") == 2
                    and tool in (e.get("requesting_id"), e.get("accessing_id"))):
                return e
    return None


def _blamed_finding(ev: dict, granted: dict, base: dict) -> Finding:
    tool = ev.get("requesting_id") or ev.get("accessing_id")
    return Finding(
        "R1c", "problem", **base, when=ev["ts_start"],
        title=f"Asked again: macOS blamed {base['client_id']} this time",
        detail=[f"{tool} was allowed on {_when(granted['ts_start'])} while macOS held "
                f"{granted['client_id']} responsible.",
                f"On {_when(ev['ts_start'])} it ran under {base['client_id']}, which has no "
                f"saved answer, so macOS asked again.",
                "Permissions belong to the app macOS holds responsible (usually the app that "
                "launched the tool, such as your terminal), not to the tool itself."],
        fix=[f"Allow it for {base['client_id']} as well, or run the tool from "
             f"{granted['client_id']}."],
    )


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")


def diagnose(events: Iterable[Mapping],
             builds: Mapping[str, list[Mapping]] | None = None) -> list[tuple[Group, list[Finding]]]:
    """``builds`` maps client_id -> identity snapshots, oldest first."""
    groups = group_events(events)
    builds = builds or {}
    return [(g, diagnose_group(g, groups, builds.get(g.client_id))) for g in groups]

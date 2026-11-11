"""Group permissions-service log lines into one ``Event`` per request.

How it works (verified on macOS 27.2.1, 194 of 194 requests in the spike
logs): tccd handles each request on a single thread, from its
``REQUEST: … msgID=X`` line to its ``REPLY: … msgID=X`` line, including while
a prompt waits for the user. So every tccd line between the two on the same
``(pid, thread)`` belongs to that request.

Two kinds of request end without a REPLY. In both, the next REQUEST on the
same thread ends the previous one (``ended_by == "next_request"``):

* **Forwarded:** the system-wide tccd (uid 0) passes a per-user request to
  the user's tccd, which logs its own REQUEST with the *same msgID* (its
  sender is the system tccd) and makes the decision there. The system-side
  stub has no decision; the user-side event has ``forwarded == True``.
* **Entitled shortcut:** for processes with a built-in permission, tccd logs
  ``Auth:Allowed (Entitled) to <service> …`` and moves on.

One fact is logged by a different process. For Automation requests the
*target* app (Finder, Safari…) logs
``TCCAccessRequestIndirect_block_invoke: access request result was N``. Its
pid equals the request's ``sender_pid``, so results are linked in order per
sender. That line may arrive after the event was emitted; it updates the
same ``Event`` object in place.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

from . import rules
from .logsource import LogRecord
from .rules import public

AUTH_NAMES = {0: "denied", 1: "undetermined", 2: "allowed", 3: "limited"}


@dataclass
class Event:
    # Where and when
    tccd_pid: int
    tid: int
    ts_start: str
    ts_end: str | None = None
    msg_id: str | None = None
    tccd_uid: int | None = None
    function: str | None = None
    sender_pid: int | None = None
    complete: bool = False  # saw the matching REPLY
    ended_by: str | None = None  # "reply" | "next_request" | "end_of_log"
    forwarded: bool = False  # sent here by the system-wide tccd

    # What was asked
    service: str | None = None
    preflight: bool | None = None  # a check that can't show a prompt

    # Who asked (the app macOS holds responsible)
    client_id: str | None = None
    client_type: int | None = None  # 0 = bundle id, 1 = path
    client_path: str | None = None
    client_version: str | None = None
    client_dr: str | None = None  # designated (code-signing) requirement
    responsible_id: str | None = None
    responsible_path: str | None = None
    requesting_id: str | None = None  # the process that actually asked
    accessing_id: str | None = None

    # Automation target
    target_id: str | None = None
    target_name: str | None = None
    client_name: str | None = None  # short name used in the prompt line

    # The decision
    auth_before: int | None = None  # saved decision when the request arrived
    auth_result: int | None = None  # AUTHREQ_RESULT (direct requests)
    prompted: bool = False
    auth_after: int | None = None  # the user's answer to a prompt
    publish_event_type: int | None = None
    client_result: int | None = None  # 1 granted / 0 refused, from the target app
    requirements_match: bool = False
    usage_string: bool = False
    policy_allowed: bool | None = None
    entitled: bool = False  # decided by a built-in entitlement, never prompts

    # Bookkeeping
    lines: int = 0
    unrecognised_lines: int = 0
    _subject: str | None = field(default=None, repr=False)
    _handling_client: str | None = field(default=None, repr=False)
    _bundle_id: str | None = field(default=None, repr=False)
    _drs: dict = field(default_factory=dict, repr=False)
    _identity_types: dict = field(default_factory=dict, repr=False)
    _row_id: int | None = field(default=None, repr=False)  # set by a store

    # -- Derived ------------------------------------------------------------
    @property
    def tccd_scope(self) -> str | None:
        if self.tccd_uid is None:
            return None
        return "system" if self.tccd_uid == 0 else "user"

    @property
    def final_auth(self) -> int | None:
        for value in (self.auth_after, self.auth_result, self.auth_before):
            if value is not None:
                return value
        return None

    @property
    def is_decision(self) -> bool:
        """True for requests that decided access to a service."""
        return self.service is not None and self.final_auth is not None

    @property
    def outcome(self) -> str:
        final = self.final_auth
        if self.prompted:
            if final == 2:
                return "prompted-allowed"
            if final == 0:
                return "prompted-denied"
            return "prompted"
        if final is None:
            return "unknown"
        return AUTH_NAMES.get(final, f"auth-{final}")

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        d.update(tccd_scope=self.tccd_scope, final_auth=self.final_auth, outcome=self.outcome)
        return d

    # -- Finalisation -------------------------------------------------------
    def resolve(self) -> None:
        """Fill client/target fields from whichever lines had them unredacted."""
        candidates = (
            self._bundle_id, self._handling_client, self._subject, self.responsible_id,
            self.accessing_id if self.entitled else None,
        )
        self.client_id = next((c for c in map(public, candidates) if c), None)
        if self.client_path is None:
            self.client_path = self.responsible_path
        if self.client_id is not None:
            self.client_dr = self._drs.get(self.client_id)
            self.client_type = self._identity_types.get(self.client_id)
        if self.target_id is None and self.function and "Indirect" in self.function:
            # For Automation, tccd's "accessing" process is the target app.
            self.target_id = public(self.accessing_id)


class Assembler:
    """Feed ``LogRecord``s in log order; collect completed ``Event``s.

    ``on_client_result`` is called with an already-returned ``Event`` when the
    target app's result line arrives afterwards, so a recorder can update the
    stored row.
    """

    # Requests per sender that may still be waiting for a client result line.
    MAX_AWAITING_PER_SENDER = 32

    def __init__(self, on_client_result: Callable[[Event], None] | None = None) -> None:
        self._open: dict[tuple[int, int], Event] = {}
        self._awaiting_result: dict[int, deque[Event]] = {}
        self._tccd_pids: set[int] = set()
        self._on_client_result = on_client_result
        self.stats: Counter[str] = Counter()
        self.unrecognised: Counter[str] = Counter()

    # Public API -------------------------------------------------------------
    def feed(self, rec: LogRecord) -> list[Event]:
        if rec.process != "tccd":
            self._feed_client(rec)
            return []

        key = (rec.pid, rec.tid)
        msg = rec.message
        self._tccd_pids.add(rec.pid)

        m = rules.REQUEST.match(msg)
        if m:
            done = []
            if key in self._open:  # previous request ended without a REPLY
                self.stats["ended_without_reply"] += 1
                prev = self._open.pop(key)
                prev.ended_by = "next_request"
                done.append(self._finish(prev))
            ev = Event(
                tccd_pid=rec.pid,
                tid=rec.tid,
                ts_start=rec.ts,
                msg_id=public(m["msg_id"]),
                tccd_uid=int(m["tccd_uid"]),
                function=m["function"],
                sender_pid=int(m["sender_pid"]),
                lines=1,
            )
            if ev.sender_pid in self._tccd_pids and ev.sender_pid != rec.pid:
                ev.forwarded = True
                self.stats["forwarded"] += 1
            self._open[key] = ev
            self.stats["requests"] += 1
            if ev.function.startswith("TCCAccessRequestIndirect"):
                self._awaiting_result.setdefault(
                    ev.sender_pid, deque(maxlen=self.MAX_AWAITING_PER_SENDER)
                ).append(ev)
            return done

        ev = self._open.get(key)
        if ev is None:
            self.stats["lines_outside_requests"] += 1
            return []
        ev.lines += 1

        m = rules.REPLY.match(msg)
        if m:
            reply_id = public(m["msg_id"])
            if ev.msg_id and reply_id and reply_id != ev.msg_id:
                self.stats["msg_id_mismatch"] += 1
            ev.ts_end = rec.ts
            ev.complete = True
            ev.ended_by = "reply"
            self.stats["complete"] += 1
            return [self._finish(self._open.pop(key))]

        if not self._apply(ev, msg):
            ev.unrecognised_lines += 1
            self.unrecognised[_template_key(rec)] += 1
        return []

    def flush(self) -> list[Event]:
        """End of input: return requests that never saw their REPLY."""
        done = []
        for key in list(self._open):
            self.stats["incomplete_at_end"] += 1
            ev = self._open.pop(key)
            ev.ended_by = "end_of_log"
            done.append(self._finish(ev))
        self._awaiting_result.clear()
        return done

    def expire(self, older_than: str) -> list[Event]:
        """Close requests that started before ``older_than`` and are still open.

        A long-running recorder calls this now and then, so a request whose
        REPLY was never logged (and whose thread is never reused) can't stay
        in memory forever. Pick a cutoff longer than a user might leave a
        permission prompt unanswered.
        """
        done = []
        for key, ev in list(self._open.items()):
            if ev.ts_start < older_than:
                self.stats["expired"] += 1
                ev.ended_by = "timeout"
                done.append(self._finish(self._open.pop(key)))
        for pid, queue in list(self._awaiting_result.items()):
            while queue and queue[0].ts_start < older_than:
                queue.popleft()
            if not queue:
                del self._awaiting_result[pid]
        return done

    # Internals --------------------------------------------------------------
    def _finish(self, ev: Event) -> Event:
        ev.resolve()
        return ev

    def _feed_client(self, rec: LogRecord) -> None:
        m = rules.CLIENT_RESULT.match(rec.message)
        if not m:
            return
        queue = self._awaiting_result.get(rec.pid)
        while queue:
            ev = queue.popleft()
            if ev.client_result is None:
                ev.client_result = int(m["result"])
                self.stats["client_results_linked"] += 1
                # ended_by is set once the event has been returned to the caller.
                if ev.ended_by is not None and self._on_client_result is not None:
                    self._on_client_result(ev)
                return
        self.stats["client_results_unlinked"] += 1

    def _apply(self, ev: Event, msg: str) -> bool:
        """Read any facts from one line. Returns False if nothing matched."""
        matched = False

        if m := rules.HANDLING_INDIRECT.search(msg):
            matched = True
            ev.service = ev.service or m["service"]
            ev._handling_client = m["client"]
            ev.target_id = public(m["target"]) or ev.target_id
            ev.auth_before = int(m["auth"])
        elif m := rules.HANDLING_DIRECT.search(msg):
            matched = True
            ev.service = ev.service or m["service"]
            ev.responsible_id = ev.responsible_id or public(m["responsible"])

        if m := rules.AUTHREQ_CTX.search(msg):
            matched = True
            ev.service = m["service"]
            ev.preflight = m["preflight"] == "yes"
        if m := rules.AUTHREQ_SUBJECT.search(msg):
            matched = True
            ev._subject = m["subject"]
        if m := rules.AUTHREQ_RESULT.search(msg):
            matched = True
            ev.auth_result = int(m["auth"])

        if m := rules.POLICY.search(msg):
            matched = True
            ev.policy_allowed = m["value"] == "True"
        if m := rules.ENTITLED.search(msg):
            matched = True
            ev.entitled = True
            ev.service = ev.service or m["service"]
            ev.accessing_id = ev.accessing_id or public(m["identifier"])
            if m["verdict"] == "Allowed":
                ev.auth_result = 2
            elif m["verdict"] == "Denied":
                ev.auth_result = 0
        if rules.PROMPTING.search(msg):
            matched = True
            ev.prompted = True
            if m := rules.PROMPTING_INDIRECT.search(msg):
                ev.target_name = m["target_name"]
                ev.client_name = m["client_name"]
        if m := rules.PUBLISH_CHANGE.search(msg):
            matched = True
            ev.auth_after = int(m["auth"])
            ev.publish_event_type = int(m["event_type"])
        if m := rules.REQUIREMENTS_MATCH.search(msg):
            matched = True
            ev.requirements_match = True
            ev.target_id = ev.target_id or public(m["target"])
        if rules.USAGE_STRING.search(msg):
            matched = True
            ev.usage_string = True

        if m := rules.BUNDLE.search(msg):
            matched = True
            ev._bundle_id = m["bundle_id"]
            ev.client_version = public(m["version"])
            ev.client_path = public(m["path"])
        if m := rules.DESIGNATED_REQUIREMENT.search(msg):
            matched = True
            ev._drs.setdefault(m["identifier"], m["dr"].strip())
        if m := rules.IDENTITY.search(msg):
            matched = True
            ev._identity_types.setdefault(m["identifier"].strip(), int(m["type"]))

        if rules.ATTRIBUTION_LINE.search(msg):
            matched = True
            for role in rules.ATTRIBUTION_ROLE.finditer(msg):
                ident = public(role["identifier"])
                if role["role"] == "responsible":
                    ev.responsible_id = ev.responsible_id or ident
                    if p := rules.RESPONSIBLE_PATH.search(role["rest"]):
                        ev.responsible_path = ev.responsible_path or public(p["path"])
                elif role["role"] == "requesting":
                    ev.requesting_id = ev.requesting_id or ident
                elif role["role"] == "accessing":
                    ev.accessing_id = ev.accessing_id or ident

        return matched


def _template_key(rec: LogRecord) -> str:
    if rec.fmt:
        return rec.fmt
    head = rec.message.split("\n", 1)[0]
    return head.split(":", 1)[0][:80] if ":" in head else head[:80]


def assemble(records: Iterable[LogRecord]) -> tuple[list[Event], Assembler]:
    """Batch helper: run every record through a fresh ``Assembler``."""
    asm = Assembler()
    events: list[Event] = []
    for rec in records:
        events.extend(asm.feed(rec))
    events.extend(asm.flush())
    events.sort(key=lambda e: e.ts_start)
    return events, asm


def decisions(events: Iterable[Event]) -> Iterator[Event]:
    return (e for e in events if e.is_decision)

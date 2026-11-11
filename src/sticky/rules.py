"""Patterns for the permissions-service (tccd) log lines Sticky understands.

Verified against macOS 27.2.1 (build 26B7131). Each pattern matches the
*message text*. For ndjson input, ``KNOWN_FORMATS`` also lists the developer
format strings these lines come from, so ``sticky doctor`` can notice when a
macOS update renames one.

The log format is undocumented. Keep every pattern tolerant: optional
trailing commas, and fields that may be ``<private>``.
"""

from __future__ import annotations

import re

PRIVATE = "<private>"

# -- Request boundaries (on the tccd thread that handles the request) --------
REQUEST = re.compile(
    r"^REQUEST: tccd_uid=(?P<tccd_uid>-?\d+), sender_pid=(?P<sender_pid>-?\d+), "
    r"sender_uid=(?P<sender_uid>-?\d+), sender_auid=(?P<sender_auid>-?\d+), "
    r"function=(?P<function>[^,]+), msgID=(?P<msg_id>[^,\s]+)"
)
REPLY = re.compile(
    r"^REPLY: \((?P<uid>-?\d+)\) function=(?P<function>[^,]+), msgID=(?P<msg_id>[^,\s]+)"
)

# -- Direct requests (AUTHREQ_* family) --------------------------------------
AUTHREQ_CTX = re.compile(
    r"AUTHREQ_CTX: msgID=[^,]+, function=[^,]+, service=(?P<service>\w+), "
    r"preflight=(?P<preflight>\w+)"
)
AUTHREQ_SUBJECT = re.compile(r"AUTHREQ_SUBJECT: msgID=[^,]+, subject=(?P<subject>[^,]+)")
AUTHREQ_RESULT = re.compile(
    r"AUTHREQ_RESULT: msgID=[^,]+, authValue=(?P<auth>\d+), authReason=(?P<reason>\d+)"
)

# -- Decision lines -----------------------------------------------------------
# Indirect (Automation) form: "<service>:<client>:<target>"
HANDLING_INDIRECT = re.compile(
    r"Handling access request: (?P<service>kTCCService\w+):(?P<client>[^:]*):"
    r"(?P<target>[^,]*), default_allow: (?P<default_allow>\d+), authValue: (?P<auth>\d+)"
)
# Direct form: "to <service>, from Sub:{…}Resp:{TCCDProcess: identifier=…"
HANDLING_DIRECT = re.compile(
    r"Handling access request to (?P<service>kTCCService\w+), from "
    r"Sub:\{(?P<subject>[^}]*)\}Resp:\{TCCDProcess: identifier=(?P<responsible>[^,]+)"
)
POLICY = re.compile(r"allowed_by_policy for (?P<service>\w+) is (?P<value>True|False)")
# Shortcut for processes with a built-in (entitlement) permission. tccd logs
# this and does not log a REPLY for the request.
#   "Auth:Allowed (Entitled) to kTCCServiceListenEvent for TCCDProcess: identifier=com.apple.finder, …"
ENTITLED = re.compile(
    r"Auth:(?P<verdict>\w+) \((?P<why>[^)]*)\) to (?P<service>kTCCService\w+)"
    r"(?: for TCCDProcess: identifier=(?P<identifier>[^,]+))?"
)
PROMPTING = re.compile(r"Prompting for access")
PROMPTING_INDIRECT = re.compile(
    r"Prompting for access to indirect object (?P<target_name>.+?) by (?P<client_name>\S+)\s*$"
)
# The user's answer to a prompt (Debug level).
PUBLISH_CHANGE = re.compile(
    r"publishAccessChangedEvent:.*?event_type=(?P<event_type>\d+),.*?auth_value=(?P<auth>\d+)"
)
REQUIREMENTS_MATCH = re.compile(
    r"target Requirements match for (?P<client>.*?) : (?P<target>\S+)"
)
USAGE_STRING = re.compile(r"found usage string")
# The current build checked against a requirement. "anchor apple" is only the
# is-it-an-Apple-binary check; any other requirement is the one *saved with
# the grant*. status 0 = matches; -67050 (errSecCSReqFailed) = this build is
# not the one that was approved, so the grant doesn't apply.
#   "-[TCCDAccessIdentity matchesCodeRequirement:]: SecStaticCodeCheckValidity()
#    static code (0x…) from dev.x : cdhash H"970b…"; status: -67050"
STORED_REQUIREMENT_CHECK = re.compile(
    r"matchesCodeRequirement:\]: SecStaticCodeCheckValidity\(\) static code \(\S+\) "
    r"from (?P<identifier>.+?) : (?P<requirement>.+); status: (?P<status>-?\d+)"
)
PLATFORM_REQUIREMENT = "anchor apple"
REQUIREMENT_FAILED = -67050

# -- Identity of the app asking ---------------------------------------------
BUNDLE = re.compile(
    r"bundle:<TCCDBundle: bundleID=(?P<bundle_id>[^,]+), version=(?P<version>[^,]+), "
    r"path=(?P<path>[^>]+)>"
)
DESIGNATED_REQUIREMENT = re.compile(
    r"DR for identifier (?P<identifier>\S+) with static code \S+: (?P<dr>.+)$"
)
# "IDENTITY_ATTRIBUTION: identifier = com.x.y, type 0"
# "IDENTITY_ATTRIBUTION: /path/App[123]: from cache: = com.x.y, type 0 (764/1299)"
# type 0 = identified by bundle id, type 1 = identified by path.
IDENTITY = re.compile(
    r"IDENTITY_ATTRIBUTION: (?:identifier = |.*?from cache: = )"
    r"(?P<identifier>[^,]+), type (?P<type>\d+)"
)
# AttributionChain: / AUTHREQ_ATTRIBUTION: role={TCCDProcess: identifier=…, …}
ATTRIBUTION_LINE = re.compile(r"(?:AttributionChain|AUTHREQ_ATTRIBUTION):")
ATTRIBUTION_ROLE = re.compile(
    r"(?P<role>responsible|accessing|requesting)=\{TCCDProcess: identifier=(?P<identifier>[^,]+), "
    r"pid=(?P<pid>\d+)(?P<rest>[^}]*)\}"
)
RESPONSIBLE_PATH = re.compile(r"responsible_path=(?P<path>[^,}]+)")
BINARY_PATH = re.compile(r"binary_path=(?P<path>[^,}]+)")

# -- Client side (logged by the target app, not by tccd) ---------------------
CLIENT_RESULT = re.compile(
    r"^(?P<function>TCCAccessRequestIndirect\w*?)_block_invoke: access request result was "
    r"(?P<result>-?\d+)"
)

# Lines the assembler reads facts from. Anything else on a tccd request thread
# is counted as "unrecognised" (most are harmless noise like REQUEST_MSG).
FACT_PATTERNS = (
    REQUEST, REPLY, AUTHREQ_CTX, AUTHREQ_SUBJECT, AUTHREQ_RESULT,
    HANDLING_INDIRECT, HANDLING_DIRECT, POLICY, ENTITLED, PROMPTING, PUBLISH_CHANGE,
    REQUIREMENTS_MATCH, USAGE_STRING, STORED_REQUIREMENT_CHECK, BUNDLE,
    DESIGNATED_REQUIREMENT, IDENTITY,
    ATTRIBUTION_LINE,
)

# Format strings observed on macOS 27.2.1 for the lines Sticky depends on.
# Used for health checks with ndjson input; not needed for parsing.
KNOWN_FORMATS = {
    "REQUEST": "REQUEST: tccd_uid=%d, sender_pid=%d, sender_uid=%d, sender_auid=%d, function=%{public}s, msgID=%{public}s",
    "REPLY": "REPLY: (%d) function=%{public}s, msgID=%{public}s",
    "HANDLING_DIRECT": "Handling access request to %{public}@, from %{public}@, %{public}@",
    "DESIGNATED_REQUIREMENT": "%{public}s: DR for identifier %{public}@ with static code %p: %{public}@",
    "BUNDLE": "%{public}s: self.bundle=%p, bundle:%{public}@; for: %{public}@, URL: %{public}@, %{public}s",
    "REQUIREMENTS_MATCH": "%s: target Requirements match for %s : %@\n",
    "CLIENT_RESULT": "%s: access request result was %d, timeout was %d",
    "ATTRIBUTION": "AttributionChain: %{public}@",
}


def public(value: str | None) -> str | None:
    """Return ``value`` unless it is missing or redacted."""
    if value is None:
        return None
    value = value.strip()
    if not value or value == PRIVATE or value == "(null)":
        return None
    return value

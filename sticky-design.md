# Sticky: design and MVP plan

**Sticky explains why your Mac keeps asking for permissions, and makes them stick.**

Target users are developers and power users on macOS 27 (Golden Gate). It ships open source through GitHub and Homebrew. It can't go on the Mac App Store, because it needs to run outside the sandbox and launch `log`.

Each design decision below is tagged:

- **[verified]**: tested on macOS 27.2.1 (build 26B7131) on 2026-11-11.
- **[to verify]**: an assumption that still needs a test.

---

## 1. What the spike established

| Question | Answer | Status |
|---|---|---|
| Can we read the per-user permissions database (`~/Library/.../TCC.db`)? | **No.** It's blocked even with Full Disk Access. | [verified] |
| Can we read the system permissions database? | Yes, read-only, with Full Disk Access. It only holds system-wide services: Accessibility, Full Disk Access, Input Monitoring, Developer Tools. | [verified] |
| Does the permissions log show per-user decisions? | **Yes.** It shows the requester, the target, the decision, whether there was a prompt, and the user's answer. | [verified] |
| Does reading the log need Full Disk Access or root? | **No.** `/usr/bin/log stream` works as a normal user. | [verified] |
| Can we rely on log history (`log show`)? | **No.** Detailed lines expire within minutes. We have to record live. | [verified] |
| Is the log redacted? | Partly. Some fields are `<private>`, but the same facts appear unredacted on other lines of the same request. | [verified] |

**What this means:** Sticky's main data source is a **live recording of the permissions log**. Reading the database is an optional extra, and inspecting the requesting app's code signature fills in the diagnosis.

### What each permission outcome looks like in the log [verified]

| Situation | Log lines |
|---|---|
| Already allowed | `Handling access request ... authValue: 2` plus `target Requirements match` |
| First request (prompt) | `allowed_by_policy ... False because: Default not allowed` → `authValue: 1` → `Prompting for access to indirect object <Target> by <app>` |
| User's answer | `publishAccessChangedEvent ... auth_value=<0 denied, 2 allowed>` (debug level) |
| Remembered denial | `authValue: 0`, no prompt, `access request result was 0` (osascript gets error -1743) |

`authValue` follows the standard TCC values: 0 = denied, 1 = not decided yet, 2 = allowed, 3 = limited.

### Testing gotchas found in the spike

- In zsh, `log` is a **built-in command**. Always call `/usr/bin/log`.
- `tell application "X" to get version` (also `name`) is answered locally and **never asks for permission**. Use a command that sends a real event, such as `count windows`.
- Apps that quit as soon as they launch, like Preview with no open documents, fail with -600 before any permission check happens.

---

## 2. Architecture

```
┌───────────────────────── sticky-agent (LaunchAgent, always on) ─────────────────────────┐
│                                                                                          │
│  /usr/bin/log stream --style ndjson ──▶ Line parser ──▶ Event assembler ──▶ SQLite (WAL)  │
│     --info --debug                      (match on        (group by tccd                   │
│     predicate: subsystem=com.apple.TCC   formatString)    pid+thread,                     │
│               AND category=access                         REQUEST…REPLY)                  │
│                                                                                          │
│  Identity snapshotter: for each new client path → code signature + Info.plist → SQLite   │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                               │
                         ┌─────────────────────┴─────────────────────┐
                         ▼                                           ▼
               sticky CLI (MVP)                          Menu bar app (v1, SwiftUI)
   `sticky why <app>` · `sticky log` · `sticky doctor`    notifications, timeline, one-click fixes
                         │
                         ▼
               Diagnosis engine (rules over events + identity history)
```

### 2.1 Collector

- Launch `/usr/bin/log stream --info --debug --style ndjson --predicate 'subsystem == "com.apple.TCC" AND category == "access"'`. This is the only way to record live; the public `OSLogStore` API only reads history.
- **Why ndjson** [verified]: each line carries `threadID`, `processID`, `messageType`, `timestamp` and `formatString` as separate fields.
- **Why `--debug`** [verified]: two facts are only logged at debug level: the user's answer (`publishAccessChangedEvent ... auth_value=`) and the signing identity (`DR for identifier ...`).
- Run it as a **per-user LaunchAgent** with `KeepAlive`, and restart `log stream` if it exits. Sticky can only explain prompts that happened while it was recording, so it has to start at login.

### 2.2 Line parser: match on `formatString`, not message text [verified]

Each log line includes the developer's template, for example:

```
REQUEST: tccd_uid=%d, sender_pid=%d, sender_uid=%d, sender_auid=%d, function=%{public}s, msgID=%{public}s
REPLY: (%d) function=%{public}s, msgID=%{public}s
Handling access request to %{public}@, from %{public}@, %{public}@
%{public}s: DR for identifier %{public}@ with static code %p: %{public}@
%s: access request result was %d, timeout was %d
```

- Keep a **rule table** keyed by `formatString`. Each rule has a regex built from the template and a list of fields to extract.
- Templates change less often than message text, and they tell you which placeholders are `%{public}`, meaning never redacted.
- **Unknown templates are counted, not dropped.** If a known template stops appearing after a macOS update, `sticky doctor` reports "parser out of date for build X."
- Keep the rule tables per macOS build (`rules/27.2.yaml`) so a new release means adding a file, not editing code.

### 2.3 Event assembler: group lines into requests [verified]

The permissions service (`tccd`) handles each request on **one thread from `REQUEST` to `REPLY`**, including while a prompt waits for the user. In the spike logs, 194 of 194 requests started and ended on the same thread.

- Grouping key: `(tccd processID, threadID)`. Open a group on `REQUEST: ... msgID=X` and close it on `REPLY: ... msgID=X`. Every line in between belongs to that request.
- There are two `tccd` processes. `tccd_uid=0` is the system-wide one; `tccd_uid=501` is your per-user one. Record which handled each request.
- There are **two log formats** to support:
  - The `AUTHREQ_CTX / ATTRIBUTION / SUBJECT / RESULT` lines, used by direct requests (mostly the system-wide service).
  - `do_TCCAccessRequestIndirect` plus `Handling access request: <svc>:<client>:<target>`, used by Automation (AppleEvents) requests in the per-user service.
- Fill fields from whichever line has them unredacted. In the spike, the decision line said `<private>:<private>`, but `TCCDBundle: bundleID=...` and `Prompting for access ... TextEdit by claude` named both apps on the same thread.

### 2.4 Event schema (SQLite)

```sql
CREATE TABLE events (
  id            INTEGER PRIMARY KEY,
  ts_start      TEXT, ts_end TEXT,              -- REQUEST / REPLY timestamps
  tccd_scope    TEXT,                           -- 'system' | 'user'
  function      TEXT,                           -- TCCAccessRequest, TCCAccessRequestIndirect, …
  service       TEXT,                           -- kTCCServiceAppleEvents, …
  client_id     TEXT,                           -- responsible bundle id or path
  client_type   INTEGER,                        -- 0 = bundle id, 1 = path
  client_path   TEXT, client_version TEXT,
  accessing_id  TEXT,                           -- process that actually asked (osascript, ls, …)
  target_id     TEXT,                           -- Automation target (com.apple.Safari)
  auth_before   INTEGER,                        -- authValue on "Handling access request"
  prompted      INTEGER,                        -- saw "Prompting for access"
  auth_after    INTEGER,                        -- publishAccessChangedEvent auth_value
  result        INTEGER,                        -- access request result was N
  req_match     INTEGER,                        -- saw "Requirements match"
  usage_string  INTEGER,                        -- saw "found usage string"
  dr_hash       TEXT,                           -- hash of code requirement string
  raw_count     INTEGER, unknown_lines INTEGER
);

CREATE TABLE identities (                        -- one row per (client_id, dr_hash, path)
  client_id TEXT, path TEXT, version TEXT, team_id TEXT,
  dr TEXT, dr_hash TEXT, sign_kind TEXT,         -- 'developer-id' | 'apple' | 'adhoc' | 'unsigned'
  usage_keys TEXT,                               -- JSON list of NS*UsageDescription keys present
  first_seen TEXT, last_seen TEXT
);
```

Keep 30 days of events. Everything stays on the Mac; there is no telemetry.

### 2.5 Identity snapshotter

The first time a `client_path` appears, record its signing identity:

- **MVP (Python):** run `codesign -dv --verbose=4 <path>` for the identifier, team ID and signature type. Run `codesign -d -r- <path>` for the signing requirement. Run `plutil -extract` for the `NS*UsageDescription` keys.
- **v1 (Swift):** use the Security framework directly: `SecStaticCodeCreateWithPath`, `SecCodeCopySigningInformation`, `SecCodeCopyDesignatedRequirement`.

Example from the spike [verified]: `com.anthropic.claude-code`, Developer ID, team `Q6L2SF6YDW`, path `…/claude-code/2.1.321/ddbdf2b334e1/claude.app`. The signing requirement names the identifier and team, not the path, so its grants survive updates even though the path changes. That's a healthy app to compare broken ones against.

### 2.6 Diagnosis engine

Rules run over the event history plus identity history. Each finding comes with a plain-English explanation and a targeted fix.

| # | Rule | Trigger | Explanation and fix |
|---|---|---|---|
| R1 | **Grant didn't stick** | Same (client, service, target) got an answer (`auth_after` 0 or 2), then later `auth_before = 1` and a prompt again | The headline diagnosis. Sub-rules R1a–R1d below find the cause. |
| R1a | Path moved | `client_type = 1` (identity is a path) and `client_path` changed between the two events | "This tool is identified by its location, and it moved on update." Fix: install it at a stable path, or ask the developer to sign it. |
| R1b | Signing identity changed | `dr_hash` differs between the two events. This is common for ad-hoc builds, whose requirement is a hash of the exact binary. | "Every rebuild looks like a new app to macOS." Fix: sign with a stable certificate. |
| R1c | Blamed on a different app | The `responsible` app differs from the one that was granted (Terminal vs iTerm vs VS Code vs tmux) | "macOS gives the permission to the app it blames, not the tool you ran." |
| R1d | Reset externally | The grant disappeared with no prompt in between | Reset by `tccutil`, MDM or System Settings. |
| R2 | **Silent denial** | `auth_before = 0`, no prompt, `result = 0` | "You denied this on <date>. macOS won't ask again." Fix: deep link to Settings → Automation. |
| R3 | No usage description | Prompt-eligible request without `found usage string` | "The app never says why it needs this." [to verify: what the log shows when the string is missing] |
| R4 | Prompt storm | ≥ N prompts for one client within a time window | Summary notification. |

**Fixes are always targeted:** `tccutil reset <Service> <bundle-id>` (one app, one service), or a deep link into System Settings. Never use a bare `tccutil reset <Service>`, which wipes the permission for every app.

---

## 3. Languages and why

| Part | MVP | v1 |
|---|---|---|
| Collector, parser, assembler | **Python 3** (stdlib only: `subprocess`, `json`, `sqlite3`) | Port to Swift or a C++ core if CPU budget requires it |
| Signing inspector | Python, running `codesign` and `plutil` | Swift Security framework |
| UI | CLI | **SwiftUI** menu bar app reading the same SQLite file |

Reasons for this split:

- **Python first:** fastest to iterate against the log fixtures, and developers already install Python tools with Homebrew. It gets you in front of real users in about 3 weeks.
- **SwiftUI later:** that's what Mac teams look for on a resume, and it's where notifications and one-click fixes live.
- **Shared SQLite file as the boundary:** the two halves stay independent, and that's a clean cross-language story for interviews.

---

## 4. MVP: the `sticky` CLI

```text
$ sticky why claude
Claude Code  (com.anthropic.claude-code 2.1.321, Developer ID Q6L2SF6YDW)

  Automation → Safari     DENIED   Nov 11 04:16 — you clicked "Don't Allow"
                                   1 request since, refused silently (no prompt)
                                   Fix: sticky fix claude --service AppleEvents --open-settings

  Automation → TextEdit   ALLOWED  Nov 11 04:14 — after prompt, grant matched since ✓
  Automation → Finder     ALLOWED  grant matched on every request ✓

  Identity: stable (signed by team, not by path) — updates won't reset these grants.

$ sticky log --since 1h          # timeline of every permission decision
$ sticky doctor                  # agent running? parser healthy? unknown templates?
$ sticky inspect /path/to/tool   # signing + usage-string report, no history needed
```

**Commands:** `install-agent`, `uninstall-agent`, `why`, `log`, `inspect`, `fix`, `doctor`.

**Out of scope for the MVP:** a GUI, editing permissions beyond `tccutil reset`, the system database, and non-Automation services beyond what the parser picks up for free.

---

## 5. Milestones

| Week | Deliverable | Done when |
|---|---|---|
| **0** | Spike | ✅ Done 2026-11-11 |
| **1** | Parser and assembler with tests | The four spike logs (anonymized) are test fixtures. All 194 requests are grouped correctly. Allowed, prompted, denied and remembered-denial events come out with the right fields. |
| **2** | Collector agent plus SQLite plus `sticky log` | It runs for 24 h with CPU and memory measured [to verify: budget < 1 % CPU, < 30 MB]. It survives sleep and a `log stream` restart. |
| **3** | Identity snapshotter, rules R1/R2, `sticky why`, `sticky inspect` | A **deliberately broken test tool** (below) produces an R1b diagnosis end to end. |
| **4** | Release | A Homebrew tap, a README with a demo GIF, and posts to r/macapps and Show HN. Collect real user reports for the R1c/R3 cases. |
| **5–7** | SwiftUI menu bar app | A notification reads "Claude Code was asked again about Safari — here's why." The app shows a timeline and one-click fixes, and is signed and notarized. |

### The deliberately broken test tool (week 3)

Write a tiny C or Swift command-line program that runs `osascript -e 'tell application "Finder" to count windows'`, with no stable signature (ad-hoc signed).

1. Build it, run it, and click **Allow**.
2. Change one line, rebuild, and run it again. Expect a new prompt and a different `dr_hash`. **That's R1b.**
3. Copy it to another folder unsigned and run it again. Expect R1a.

This verifies the core diagnosis on your own Mac, and it makes a good demo GIF.

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| The log format is undocumented and Apple can change it in any update | Match on `formatString`; keep rule tables per build; count unknown templates; have `sticky doctor` warn; test against fixtures on every macOS beta. |
| Apple redacts more fields | Get each fact from whichever line has it as `%{public}`; the identity snapshot fills in the rest. |
| It only sees what happened while it was running | Install the LaunchAgent at first run, and say so clearly in the README. |
| Log volume and CPU use | Narrow the predicate (`category == "access"`); parse cheaply; measure in week 2. The spike saw about 7k lines in 25 s while prompts were happening, and much less when idle. |
| `authReason` codes are undocumented | Don't show them to users until each one's meaning is confirmed. |
| The audience is small | It's developer-focused on purpose; launch on HN and r/macapps where those users are. |

---

## 7. Open questions (to test next)

1. **Ad-hoc rebuild re-prompt (R1b):** confirm with the broken test tool.
2. **Missing usage description (R3):** what does the log show when an app has no `NSAppleEventsUsageDescription`?
3. **Other services:** camera, microphone, Screen Recording, Accessibility. Which `tccd` handles each, and which log format does it use?
4. **Recording for 24 h:** CPU and memory use, and whether recording survives sleep and wake.
5. **The `reminder_count` and `one_time_reprompt_eligible` columns** in the system database: what do they track?
6. **Is `--debug` needed for everything?** The answer and the signing requirement are only logged at debug level. Measure how much extra volume that costs.
7. **Composed authorization (found in week 2).** tccd logs `Evaluated composed authorization from kTCCServiceListenEvent to parent service kTCCServicePostEvent: Auth:Unknown (None)`, and PostEvent in turn checks Accessibility. A permission can be granted through its parent, so `sticky why` could say "allowed because Accessibility is on." Parse this in week 3.

### Week 2 results (2026-11-11, macOS 27.2.1)

- `log stream` doesn't hold output back when writing into a pipe. Lines reach the recorder about 0.16 s after the event.
- A 3-minute live run captured a Finder request (allowed) and a Safari request (remembered denial). It recorded 553 log lines, 19 requests and 14 decisions.
- CPU averaged over the run: recorder 0.01 %, `log stream` 0.02 % of one core. Memory: recorder 18 MB steady (32 MB at startup), `log stream` 2.6 MB. Both are within budget.
- SIGTERM stops the recorder cleanly, and `log stream` stops with it.
- **Still to do:** run it for 24 h as a LaunchAgent, including sleep and wake.

### Week 3 results (2026-11-11, macOS 27.2.1)

Built `sticky inspect`, `sticky why`, identity snapshots and rules R1a–R1d, R2, R4 and the new R5. The end-to-end test used `tools/brokentool`, an ad-hoc signed app launched with `open` so macOS holds it responsible:

| Step | Signing identity | Result |
|---|---|---|
| v1, first run | `cdhash H"90e03ff5…"` | Prompted; allowed. tccd logged v1's requirement. |
| v1, second run | same | Allowed silently, with `target Requirements match`. |
| v2 (rebuilt, same bundle id) | `cdhash H"7289ee52…"` | **Allowed silently, no prompt.** The request carried v2's requirement, and there was **no** `target Requirements match` line. |

- **The planned R1b scenario didn't happen.** For Automation, macOS 27.2.1 carried an ad-hoc app's grant over to a rebuild with a different requirement. The R1b rule stays (it's unit-tested), but it's unconfirmed live. The new R5 (info) rule reports what actually happened.
- tccd logs an app's signing requirement only when it prompts. So R1b compares the requirement from the original prompt with the one from the new prompt, and R5 compares the original prompt with identity snapshots.
- syspolicyd checks **Developer Tools** on every app launch, and the answer defaults to deny without a prompt. Diagnoses now ignore it so it doesn't show up as a false "silently denied".
### Accessibility after a rebuild (2026-11-11, macOS 27.2.1): **it breaks**

`tools/brokentool/run.sh ax` calls `AXIsProcessTrustedWithOptions` (a preflight check, logged as `TCCAccessRequest` with `preflight=yes` by the system tccd), then tries to read the focused app.

| Step | Identity | Result |
|---|---|---|
| ax1, before you switched it on | `cdhash H"970b1915…"` | `AXIsProcessTrusted: no`; recorded as not decided |
| ax1, after you switched it on | same | **trusted**; `matchesCodeRequirement … cdhash H"970b1915…"; status: 0` |
| ax2 (rebuilt, identical code) | `cdhash H"c1296205…"` | **not trusted, no prompt**, switch still on; `matchesCodeRequirement … cdhash H"970b1915…"; status: -67050` |

- tccd checks the running build against the requirement **saved with the grant**, and logs both that requirement and the result. -67050 is `errSecCSReqFailed`. This is direct evidence, so new rule **R6, "switched on, but not for this build"**, uses it instead of inferring from snapshots. R6 replaces R2 when it applies.
- The denied ax2 requests also logged ax2's own requirement, so R6 can show both hashes.
- **Automation (R5) and Accessibility (R6) behave differently** after the same kind of rebuild: Automation carried the grant over, Accessibility didn't.
- Accessibility checks are always preflight. Diagnoses now count preflight checks that decided something (allowed/denied) and still ignore those that decided nothing.
- In Accessibility requests the app is the *requesting* process, with no *responsible* one. The app's path now comes from that process's `binary_path`, stored as the enclosing `.app`.
- BrokenTool's attempt to read the focused app failed with `AXError -25204` even while trusted. It's probably a limit of a windowless test app, not a permission problem, so the test relies on `AXIsProcessTrusted` and tccd's decision.
- **Which re-approval fixes it (verified):**
  - **Switching it off and on: no effect.** ax2 was still denied, and the saved requirement still named ax1 (`status -67050`).
  - **Removing it with − and adding it with +: fixed.** ax2 became trusted, and the saved requirement became ax2's own `cdhash H"c1296205…"` (`status 0`).

  R6's fix text now says this. The `tccutil reset` alternative is still unverified.
- **Still untested:** Screen Recording.

---

## 8. Resume numbers to measure

- Events parsed per second and CPU % of the always-on agent.
- Requests correctly grouped against the fixture set (spike baseline: 194/194).
- Number of diagnosis rules with end-to-end tests.
- Homebrew installs, GitHub stars, and real-user reports resolved.

---

## 9. Module 2: background items ("why does this keep coming back?")

This module answers the "Background Items Added" notifications. It asks which app installed an item, why it reappears after you turn it off, and how to remove it for good. It reuses the collector, the SQLite store and the identity snapshotter. Its only new input is a different log source.

### What's reachable without `sudo` [verified 2026-11-11, macOS 27.2.1]

| Source | Without sudo | Notes |
|---|---|---|
| `sfltool dumpbtm` | **No.** It only prints a placeholder record (`UID -2`). | The full inventory (developer, team ID, status) needs `sudo`. Make it an optional one-time `sticky btm snapshot --sudo`. |
| `/var/db/com.apple.backgroundtaskmanagement/` | **No.** Permission denied. | — |
| Log subsystem `com.apple.backgroundtaskmanagement` | **Yes.** About 1,000 lines in 24 h, at Default and Info level, so they stay in log history much longer than the permissions debug lines. | Main source for this module. |

### Useful log lines (all readable without sudo)

```
registerLaunchItem: found existing item: uuid=…, name=Zoom, type=legacy agent, disposition=[enabled, allowed, notified]
registerItem: uid=501, type=spotlight, parentURL=<private>, url=<private>, config=(null)
getEffectiveDisposition: disposition=[enabled, allowed, not notified], have LWCR=true
effectiveItemDisposition: record not found: appURL=/Applications/Zen.app, …
handleDistributedNotification: bundleIdentifier:com.microsoft.Excel
noteUseOfItemWithIdentifier: identifier=2.com.anthropic.claudefordesktop, uid=501
```

- **`disposition` is the key field.** It combines enabled/disabled, allowed/disallowed and notified/not notified. A change from `notified` to a new notification, or from `disabled` back to `enabled`, is the "it came back" event.
- Item URLs are often `<private>`, but `name`, `uuid`, `type` and the parent app's URL usually aren't.
- Item types seen: `legacy agent`, `spotlight`, `app`, `background tasks`.

### Diagnoses

| # | Rule | Explanation |
|---|---|---|
| B1 | **Came back after you disabled it** | Same `uuid` or name: `disabled` → `enabled`, or a new `notified`. Usually the parent app re-registers it at launch, so name the app and when it happened. |
| B2 | **Orphaned item** | The registration points at an app that's no longer installed (`record not found` for the app URL). Fix: remove the leftover plist. |
| B3 | **Unknown helper** | Map the helper to its parent app using its code signature and team ID (identity snapshotter) and Apple's helper-to-app map. |

### Open questions

1. Does turning an item off in System Settings produce a log line with the new disposition?
2. What exactly triggers `notified` in the disposition (the "Background Items Added" notification)?
3. How much does the 24 h log history cover for B1 if the collector wasn't running?

Plan: start this after the permissions MVP ships (week 8+), so Sticky grows one module at a time.

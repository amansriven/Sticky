"""Inspect an app's code-signing identity, the way macOS permissions see it.

macOS stores a permission grant against the app's *designated requirement*
(DR), a rule the app's signature must satisfy. Whether a grant survives an
update depends on what that rule names:

* ``identifier "com.x" and anchor apple generic and … subject.OU = TEAMID``
  (Developer ID, App Store): bundle id plus developer team. Survives updates
  and moves.
* ``identifier "com.apple.x" and anchor apple``: Apple's own apps. Stable.
* ``cdhash H"…"``: ad-hoc or linker-signed. The rule is a hash of this exact
  build, so **every rebuild looks like a new app** and grants are lost.
* Unsigned: no rule at all. macOS falls back to the file path, so moving or
  replacing the file loses grants.

Uses ``codesign`` and Info.plist; no special permissions needed.
"""

from __future__ import annotations

import hashlib
import plistlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Info.plist keys an app must declare before macOS will ask for a permission.
USAGE_KEYS = {
    "kTCCServiceAppleEvents": "NSAppleEventsUsageDescription",
    "kTCCServiceCamera": "NSCameraUsageDescription",
    "kTCCServiceMicrophone": "NSMicrophoneUsageDescription",
    "kTCCServiceAddressBook": "NSContactsUsageDescription",
    "kTCCServiceCalendar": "NSCalendarsFullAccessUsageDescription",
    "kTCCServiceReminders": "NSRemindersFullAccessUsageDescription",
    "kTCCServicePhotos": "NSPhotoLibraryUsageDescription",
    "kTCCServiceBluetoothAlways": "NSBluetoothAlwaysUsageDescription",
    "kTCCServiceSystemPolicyDesktopFolder": "NSDesktopFolderUsageDescription",
    "kTCCServiceSystemPolicyDocumentsFolder": "NSDocumentsFolderUsageDescription",
    "kTCCServiceSystemPolicyDownloadsFolder": "NSDownloadsFolderUsageDescription",
    "kTCCServiceSpeechRecognition": "NSSpeechRecognitionUsageDescription",
}


@dataclass
class Identity:
    path: str  # what was asked about
    code_path: str  # what was inspected: the enclosing .app, or the file
    exists: bool = True
    identifier: str | None = None  # codesign Identifier (bundle id for apps)
    name: str | None = None
    version: str | None = None
    sign_kind: str = "unknown"  # apple | app-store | developer-id | development | adhoc | unsigned | other
    linker_signed: bool = False
    team_id: str | None = None
    authority: str | None = None  # leaf certificate
    cdhash: str | None = None
    hardened_runtime: bool = False
    notarization: str | None = None  # "stapled" if a ticket is stapled
    designated_requirement: str | None = None
    usage_keys: dict[str, str] = field(default_factory=dict)  # key -> text
    error: str | None = None

    @property
    def dr_kind(self) -> str:
        dr = self.designated_requirement or ""
        if self.sign_kind == "unsigned":
            return "path"
        if dr.startswith("cdhash"):
            return "cdhash"
        if "subject.OU" in dr:
            return "team"
        if "anchor apple" in dr and "generic" not in dr:
            return "apple"
        return "other" if dr else "unknown"

    @property
    def stable(self) -> bool:
        """Will permission grants survive an update to this app?"""
        return self.dr_kind in ("team", "apple")

    @property
    def dr_hash(self) -> str | None:
        if not self.designated_requirement:
            return None
        return hashlib.sha256(self.designated_requirement.encode()).hexdigest()[:16]

    def explain(self) -> str:
        kind = self.dr_kind
        if kind == "team":
            return (f"Signed by developer team {self.team_id}. macOS ties permissions to the "
                    f"bundle id and team, so grants survive updates and moves.")
        if kind == "apple":
            return "An Apple app. Permissions are tied to its bundle id; grants are stable."
        if kind == "cdhash":
            how = "linker-signed" if self.linker_signed else "ad-hoc signed"
            return (f"{how.capitalize()}: no developer identity. Its signature is a hash of this "
                    f"exact build, so after a rebuild or update macOS may treat it as a new app "
                    f"and ask again.")
        if kind == "path":
            return ("Not signed. macOS falls back to the file's location, so moving or replacing "
                    "it loses its permissions.")
        return "Unusual signing requirement; check whether it names a team or a hash."

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d.update(dr_kind=self.dr_kind, stable=self.stable, dr_hash=self.dr_hash)
        return d


def code_path_for(path: str | Path) -> Path:
    """The enclosing .app bundle if ``path`` is inside one, else the path."""
    p = Path(path)
    for parent in (p, *p.parents):
        if parent.suffix == ".app":
            return parent
    return p


def signature_mtime(path: str | Path) -> float:
    """When the code at ``path`` was last signed (or modified), for change detection.

    Signing a bundle rewrites ``Contents/_CodeSignature/CodeResources``; for a
    bare executable the signature is inside the file. Returns 0.0 if missing.
    """
    code = code_path_for(path)
    for candidate in (code / "Contents" / "_CodeSignature" / "CodeResources", code):
        try:
            return candidate.stat().st_mtime
        except OSError:
            continue
    return 0.0


def _codesign(args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(["/usr/bin/codesign", *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _kv(text: str, key: str) -> str | None:
    m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def parse_codesign_details(text: str, ident: Identity) -> None:
    """Fill ``ident`` from ``codesign -dv --verbose=4`` output."""
    if "code object is not signed at all" in text:
        ident.sign_kind = "unsigned"
        return
    ident.identifier = _kv(text, "Identifier") or ident.identifier
    ident.cdhash = _kv(text, "CDHash")
    flags = _kv(text, "CodeDirectory v") or ""
    ident.hardened_runtime = "runtime" in flags
    ident.linker_signed = "linker-signed" in flags
    team = _kv(text, "TeamIdentifier")
    ident.team_id = None if team in (None, "not set") else team
    ident.notarization = "stapled" if _kv(text, "Notarization Ticket") == "stapled" else None
    authorities = re.findall(r"^Authority=(.*)$", text, re.MULTILINE)
    ident.authority = authorities[0].strip() if authorities else None
    leaf = ident.authority or ""
    if _kv(text, "Signature") == "adhoc" or "adhoc" in flags:
        ident.sign_kind = "adhoc"
    elif leaf.startswith("Developer ID Application"):
        ident.sign_kind = "developer-id"
    elif leaf.startswith(("Apple Mac OS Application Signing", "Apple iPhone OS Application Signing")):
        ident.sign_kind = "app-store"
    elif leaf.startswith(("Apple Development", "Mac Developer", "Apple Distribution")):
        ident.sign_kind = "development"
    elif leaf in ("Software Signing", "macOS Software Signing") or "Platform identifier" in text:
        ident.sign_kind = "apple"
    else:
        ident.sign_kind = "other"


def parse_requirement(text: str) -> str | None:
    """The DR from ``codesign -d -r-`` output (``# designated =>`` if implicit)."""
    m = re.search(r"^#?\s*designated => (.*)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def _read_info_plist(code_path: Path, ident: Identity) -> None:
    info = code_path / "Contents" / "Info.plist"
    if not info.is_file():
        return
    try:
        with open(info, "rb") as f:
            plist = plistlib.load(f)
    except Exception:
        return
    ident.identifier = ident.identifier or plist.get("CFBundleIdentifier")
    ident.name = plist.get("CFBundleDisplayName") or plist.get("CFBundleName")
    ident.version = plist.get("CFBundleShortVersionString") or plist.get("CFBundleVersion")
    ident.usage_keys = {
        k: str(v) for k, v in plist.items() if k.startswith("NS") and k.endswith("UsageDescription")
    }


def inspect(path: str | Path) -> Identity:
    code_path = code_path_for(path)
    ident = Identity(path=str(path), code_path=str(code_path))
    if not code_path.exists():
        ident.exists = False
        ident.error = "file not found (deleted, moved, or replaced by an update)"
        return ident
    _read_info_plist(code_path, ident)
    ident.name = ident.name or code_path.stem
    _, details = _codesign(["-dv", "--verbose=4", str(code_path)])
    parse_codesign_details(details, ident)
    if ident.sign_kind != "unsigned":
        _, req = _codesign(["-d", "-r-", str(code_path)])
        ident.designated_requirement = parse_requirement(req)
    return ident


def find_app_by_bundle_id(bundle_id: str) -> str | None:
    """Locate an installed app by bundle id with Spotlight."""
    try:
        r = subprocess.run(
            ["/usr/bin/mdfind", f"kMDItemCFBundleIdentifier == '{bundle_id}'"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    paths = [p for p in r.stdout.splitlines() if p.endswith(".app")]
    return paths[0] if paths else None

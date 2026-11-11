"""Install the recorder as a per-user LaunchAgent.

The agent runs ``python -m sticky record`` at login and launchd restarts it
if it exits. It runs as you, not root, at background priority. Its output
goes to ``~/Library/Logs/Sticky/recorder.log``.

macOS will show a "Background Items Added" notification the first time it is
installed. That's expected.
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

LABEL = "dev.sticky.recorder"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True)


def plist_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "Logs" / "Sticky" / "recorder.log"


_CELLAR = re.compile(r"^(?P<prefix>.*)/Cellar/(?P<name>[^/]+)/[^/]+/(?P<rest>.*)$")


def stable_python_path(python: str) -> str:
    """Use Homebrew's version-independent ``opt`` path when installed by Homebrew.

    ``/opt/homebrew/Cellar/sticky/0.1.0/libexec/bin/python`` becomes
    ``/opt/homebrew/opt/sticky/libexec/bin/python``, so the agent keeps
    working after ``brew upgrade`` (which removes the old Cellar folder).
    """
    m = _CELLAR.match(python)
    if not m:
        return python
    return f"{m['prefix']}/opt/{m['name']}/{m['rest']}"


def source_checkout_root(package_dir: Path | None = None) -> Path | None:
    """The ``src`` folder if Sticky runs from a source checkout, else None."""
    src = (package_dir or Path(__file__).resolve().parent).parent
    if src.name == "src" and (src.parent / "pyproject.toml").is_file():
        return src
    return None


def build_plist(
    python: str = sys.executable,
    db_path: str | None = None,
    home: Path | None = None,
    package_dir: Path | None = None,
) -> dict:
    env = {"PYTHONUNBUFFERED": "1"}
    if db_path:
        env["STICKY_DB"] = str(db_path)
    # Running from a source checkout (not installed): point Python at it.
    # Never set this for installed copies: it would pin a version's folder.
    if (src := source_checkout_root(package_dir)) is not None:
        env["PYTHONPATH"] = str(src)
    log = str(log_path(home))
    return {
        "Label": LABEL,
        "ProgramArguments": [stable_python_path(python), "-m", "sticky", "record"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,  # if it crashes, wait 30 s before relaunching
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 10,
        "EnvironmentVariables": env,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _stop(run: Runner, sleep: Callable[[float], None], timeout: float = 10.0) -> None:
    """Boot the agent out and wait until launchd has really unloaded it.

    ``bootout`` returns before the old service is gone. Bootstrapping again
    straight away fails with "Bootstrap failed: 5: Input/output error"
    (seen on macOS 27.2.1 when reinstalling), which left no recorder running.
    """
    run(["/bin/launchctl", "bootout", f"{_domain()}/{LABEL}"])
    waited = 0.0
    while is_loaded(run) and waited < timeout:
        sleep(0.2)
        waited += 0.2


def install(
    python: str = sys.executable,
    db_path: str | None = None,
    home: Path | None = None,
    run: Runner = _run,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 5,
) -> Path:
    path = plist_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    log_path(home).parent.mkdir(parents=True, exist_ok=True)
    if is_loaded(run):
        _stop(run, sleep)
    with open(path, "wb") as f:
        plistlib.dump(build_plist(python, db_path, home), f)
    for attempt in range(attempts):
        result = run(["/bin/launchctl", "bootstrap", _domain(), str(path)])
        if result.returncode == 0:
            return path
        if attempt < attempts - 1:
            sleep(1.0)  # launchd may still be tearing down the old service
    raise RuntimeError(
        f"launchctl bootstrap failed: {result.stderr.strip() or result.returncode}. "
        f"Try again in a few seconds, or run: launchctl bootstrap {_domain()} {path}"
    )


def uninstall(home: Path | None = None, run: Runner = _run,
              sleep: Callable[[float], None] = time.sleep) -> bool:
    """Stop and remove the agent. Returns False if it wasn't installed."""
    path = plist_path(home)
    was_there = path.exists() or is_loaded(run)
    if is_loaded(run):
        _stop(run, sleep)
    if path.exists():
        path.unlink()
    return was_there


def is_loaded(run: Runner = _run) -> bool:
    return run(["/bin/launchctl", "print", f"{_domain()}/{LABEL}"]).returncode == 0


def is_installed(home: Path | None = None) -> bool:
    return plist_path(home).exists()

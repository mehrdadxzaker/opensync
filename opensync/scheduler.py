"""User-level OS timers. No daemon, cron edits, or shell interpolation."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
import sys


def label(home: Path) -> str:
    return "local.opensync." + hashlib.sha256(str(home).encode()).hexdigest()[:12]


def command(home: Path) -> list[str]:
    # Absolute entry point works from a checkout and from an installed package.
    return [sys.executable, str(Path(__file__).with_name("worker.py").resolve()), "--home", str(home), "refresh"]


def plan(home: Path, platform: str | None = None) -> dict:
    platform = platform or sys.platform
    ident = label(home)
    args = command(home)
    if platform == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / (ident + ".plist")
        payload = {"Label": ident, "ProgramArguments": args, "StartInterval": 60, "RunAtLoad": True, "StandardOutPath": str(home / "worker.log"), "StandardErrorPath": str(home / "worker-error.log")}
        return {"backend": "launchd", "path": str(path), "label": ident, "arguments": args, "payload": payload}
    if platform.startswith("linux"):
        # systemd ExecStart is not a shell: quote arguments and escape specifiers.
        quoted = " ".join('"' + a.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"' for a in args)
        folder = Path.home() / ".config" / "systemd" / "user"
        service = "[Unit]\nDescription=OpenSync knowledge base refresh\n[Service]\nType=oneshot\nExecStart=" + quoted + "\n"
        timer = "[Unit]\nDescription=Refresh due OpenSync sources\n[Timer]\nOnBootSec=60\nOnUnitActiveSec=60\n[Install]\nWantedBy=timers.target\n"
        return {"backend": "systemd", "path": str(folder / (ident + ".timer")), "label": ident, "arguments": args, "service": service, "timer": timer}
    return {"backend": "worker", "label": ident, "arguments": args, "instructions": "Run kb worker in a persistent terminal, or configure your OS task scheduler to run kb refresh every minute."}


def _run(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Timer command failed.")


def install(home: Path) -> dict:
    spec = plan(home)
    ident = spec["label"]
    if spec["backend"] == "launchd":
        path = Path(spec["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = plistlib.dumps(spec["payload"])
        domain = f"gui/{os.getuid()}"
        loaded = subprocess.run(["/bin/launchctl", "print", f"{domain}/{ident}"], capture_output=True, timeout=10).returncode == 0
        changed = not path.exists() or path.read_bytes() != payload
        if changed:
            temp = path.with_suffix(".tmp")
            temp.write_bytes(payload)
            temp.replace(path)
            if loaded:
                _run(["/bin/launchctl", "bootout", f"{domain}/{ident}"])
        if changed or not loaded:
            _run(["/bin/launchctl", "bootstrap", domain, str(path)])
    elif spec["backend"] == "systemd":
        path = Path(spec["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".service").write_text(spec["service"])
        path.write_text(spec["timer"])
        _run(["systemctl", "--user", "daemon-reload"])
        _run(["systemctl", "--user", "enable", "--now", ident + ".timer"])
    else:
        raise RuntimeError(spec["instructions"])
    (home / "scheduler.json").write_text(__import__("json").dumps({"backend": spec["backend"], "label": ident, "path": spec["path"]}))
    return {"installed": True, "backend": spec["backend"], "path": spec["path"]}


def uninstall(home: Path) -> dict:
    spec = plan(home)
    ident = spec["label"]
    if spec["backend"] == "launchd":
        domain = f"gui/{os.getuid()}"
        loaded = subprocess.run(["/bin/launchctl", "print", f"{domain}/{ident}"], capture_output=True, timeout=10).returncode == 0
        if loaded:
            _run(["/bin/launchctl", "bootout", f"{domain}/{ident}"])
        Path(spec["path"]).unlink(missing_ok=True)
    elif spec["backend"] == "systemd":
        _run(["systemctl", "--user", "disable", "--now", ident + ".timer"])
        Path(spec["path"]).unlink(missing_ok=True)
        Path(spec["path"]).with_suffix(".service").unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"])
    (home / "scheduler.json").unlink(missing_ok=True)
    return {"installed": False}


def status(home: Path) -> dict:
    spec = plan(home)
    if spec["backend"] == "launchd":
        domain = f"gui/{os.getuid()}"
        active = subprocess.run(["/bin/launchctl", "print", f'{domain}/{spec["label"]}'], capture_output=True, timeout=10).returncode == 0
    elif spec["backend"] == "systemd":
        active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", spec["label"] + ".timer"], capture_output=True, timeout=10).returncode == 0
    else:
        active = False
    return {"installed": active, "backend": spec["backend"], "label": spec["label"], "path": spec.get("path")}

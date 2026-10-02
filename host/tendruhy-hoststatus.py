#!/usr/bin/env python3
"""Read-only host status collector for Ten druhý's watchdog.

Runs as root from a systemd timer every 5 minutes and writes one JSON file the app reads
(/opt/tendruhy/data/state/host.json). The app itself gets no access to the host.
"""

import json
import os
import re
import shutil
import ssl
import socket
import subprocess
import time
import urllib.request
from datetime import datetime, timezone

OUT = os.environ.get("TD_HOST_JSON", "/opt/tendruhy/data/state/host.json")
RESTIC_LOG = "/var/log/restic-backup.log"
PUBLIC_URL = os.environ.get("TD_PUBLIC_URL", "https://druhy.ppolivka.com/v1/models")  # expect 401 = tunnel + app up
CERT_HOSTS = os.environ.get("TD_CERT_HOSTS", "druhy.ppolivka.com,auth.ppolivka.com").split(",")


def run(cmd: list[str], timeout: int = 30) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def restic() -> dict:
    try:
        lines = open(RESTIC_LOG, errors="replace").read().splitlines()[-4000:]
    except OSError as e:
        return {"error": str(e)}
    started = [l for l in lines if l.startswith("=== Backup started")]
    complete = [l for l in lines if l.startswith("=== Backup complete")]
    last_start = started[-1].removeprefix("=== Backup started ").removesuffix(" ===") if started else None
    last_done = complete[-1].removeprefix("=== Backup complete ").removesuffix(" ===") if complete else None
    # The run in progress / last run = everything after the last "started" line.
    tail = lines[len(lines) - 1 - lines[::-1].index(started[-1]):] if started else []
    errors = [l for l in tail if re.search(r"\b(error|fatal|failed)\b", l, re.I)][:5]
    finished = any(l.startswith("=== Backup complete") for l in tail)
    snap = next((l.split()[1] for l in reversed(tail) if re.match(r"snapshot \S+ saved", l)), None)
    mtime = os.path.getmtime(RESTIC_LOG)
    return {"last_started": last_start, "last_complete": last_done, "last_run_finished": finished,
            "last_snapshot": snap, "errors": errors, "log_mtime": int(mtime)}


def disks() -> list[dict]:
    out, seen = [], set()
    for line in open("/proc/mounts"):
        dev, mnt, fs = line.split()[:3]
        if fs not in ("ext4", "xfs", "btrfs", "vfat", "exfat", "zfs") or dev in seen:
            continue
        seen.add(dev)
        u = shutil.disk_usage(mnt)
        out.append({"mount": mnt, "used_pct": round(u.used / u.total * 100, 1), "free_gb": round(u.free / 1e9, 1)})
    return out


def memory_load() -> dict:
    info = {}
    for line in open("/proc/meminfo"):
        k, v = line.split(":")
        info[k] = int(v.split()[0])
    l1, l5, l15 = open("/proc/loadavg").read().split()[:3]
    return {"mem_total_mb": info["MemTotal"] // 1024, "mem_available_mb": info["MemAvailable"] // 1024,
            "swap_used_mb": (info.get("SwapTotal", 0) - info.get("SwapFree", 0)) // 1024,
            "load1": float(l1), "load5": float(l5), "load15": float(l15), "cpus": os.cpu_count()}


def containers() -> list[dict]:
    names = run(["docker", "ps", "-a", "--format", "{{.Names}}"]).split()
    if not names:
        return []
    data = json.loads(run(["docker", "inspect", *names]) or "[]")
    out = []
    for c in data:
        st = c.get("State", {})
        out.append({"name": c["Name"].lstrip("/"), "status": st.get("Status"), "running": st.get("Running"),
                    "restarting": st.get("Restarting"), "exit_code": st.get("ExitCode"),
                    "restart_count": c.get("RestartCount", 0), "health": (st.get("Health") or {}).get("Status"),
                    "started_at": st.get("StartedAt"), "finished_at": st.get("FinishedAt")})
    return out


def updates() -> dict:
    lines = [l for l in run(["apt", "list", "--upgradable"], timeout=60).splitlines() if "/" in l]
    sec = [l.split("/")[0] for l in lines if "-security" in l]
    return {"upgradable": len(lines), "security": len(sec), "security_pkgs": sec[:15],
            "reboot_required": os.path.exists("/var/run/reboot-required")}


def public() -> dict:
    t = time.time()
    try:
        urllib.request.urlopen(urllib.request.Request(PUBLIC_URL, headers={"User-Agent": "td-hoststatus"}), timeout=15)
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": code in (200, 401), "code": code, "ms": int((time.time() - t) * 1000)}


def certs() -> list[dict]:
    out = []
    for host in [h.strip() for h in CERT_HOSTS if h.strip()]:
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, 443), timeout=10) as s, ctx.wrap_socket(s, server_hostname=host) as t:
                exp = datetime.strptime(t.getpeercert()["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            out.append({"host": host, "days_left": (exp - datetime.now(timezone.utc)).days})
        except Exception as e:
            out.append({"host": host, "error": str(e)[:200]})
    return out


def main():
    status = {"ts": int(time.time()), "hostname": socket.gethostname()}
    for key, fn in (("restic", restic), ("disks", disks), ("system", memory_load), ("containers", containers),
                    ("updates", updates), ("public", public), ("certs", certs)):
        try:
            status[key] = fn()
        except Exception as e:
            status[key] = {"error": str(e)[:200]}
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o644)
    os.replace(tmp, OUT)  # atomic: the app never reads half a file


if __name__ == "__main__":
    main()

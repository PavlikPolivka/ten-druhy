"""Homelab watchdog: reads host.json (written by the root-run collector in host/), alerts admins in his voice.

The app has no host access of its own; it only reads that file. Alerts are de-duplicated: sent when a problem
appears, repeated after REPEAT_H if it persists, and an "all good again" note when it clears.
Containers are judged by changes (was running → stopped / restart loop / unhealthy), since some are stopped on purpose.
"""

import json
import re
import threading
import time
from datetime import datetime, timedelta

from app import config, llm, push, sessions, tools
from app.prompt import TZ

TICK_S = 300
REPEAT_H = 24
DISK_PCT, DISK_CRIT = 85, 95
CERT_DAYS = 14
STALE_MIN = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchdog_alerts (key TEXT PRIMARY KEY, text TEXT, first_seen INTEGER, last_sent INTEGER);
CREATE TABLE IF NOT EXISTS watchdog_kv (k TEXT PRIMARY KEY, v TEXT);
"""
_ready = False


def _q(sql: str, args: tuple = ()) -> list[tuple]:
    global _ready
    if not _ready:
        sessions.db().executescript(SCHEMA)
        _ready = True
    return sessions._q(sql, args)


def is_admin(user: str) -> bool:
    return user in config.ADMIN_USERS


def read() -> dict | None:
    try:
        return json.loads(config.HOST_JSON.read_text())
    except (OSError, ValueError):
        return None


def _restic_time(s: str | None) -> datetime | None:
    """'Fri Oct  2 03:03:41 CEST 2026' (local time)."""
    if not s:
        return None
    s = re.sub(r"\s+[A-Z]{3,4}\s+(\d{4})$", r" \1", s.strip())
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %Y").replace(tzinfo=TZ)
    except ValueError:
        return None


def problems(h: dict, prev_containers: dict, open_keys: set[str] = frozenset()) -> dict[str, str]:
    """key -> human description (Czech facts, no style)."""
    p = {}
    if time.time() - h.get("ts", 0) > STALE_MIN * 60:
        p["stale"] = f"sběr stavu serveru neběží (poslední data {int((time.time() - h.get('ts', 0)) / 60)} min stará)"
    r = h.get("restic", {})
    done = _restic_time(r.get("last_complete"))
    if r.get("errors"):
        p["backup_errors"] = "poslední záloha (restic) hlásila chyby: " + "; ".join(r["errors"])[:300]
    if not r.get("last_run_finished") and time.time() - r.get("log_mtime", time.time()) > 2 * 3600:
        p["backup_hung"] = f"záloha spuštěná {r.get('last_started')} nedoběhla"
    if done and datetime.now(TZ) - done > timedelta(hours=26):
        p["backup_old"] = f"poslední dokončená záloha je z {r.get('last_complete')} (víc než 26 h)"
    for d in h.get("disks", []) if isinstance(h.get("disks"), list) else []:
        if d["used_pct"] >= DISK_PCT:
            p[f"disk:{d['mount']}"] = f"disk {d['mount']} je plný na {d['used_pct']} % (volno {d['free_gb']} GB)"
    s = h.get("system", {})
    if s.get("mem_total_mb") and s["mem_available_mb"] < 0.08 * s["mem_total_mb"]:
        p["memory"] = f"dochází RAM: volno {s['mem_available_mb']} MB z {s['mem_total_mb']} MB"
    if s.get("cpus") and s.get("load15", 0) > 2 * s["cpus"]:
        p["load"] = f"server je dlouhodobě přetížený (load15 {s['load15']} na {s['cpus']} CPU)"
    for c in h.get("containers", []) if isinstance(h.get("containers"), list) else []:
        name, was = c["name"], prev_containers.get(c["name"], {})
        if c.get("restarting") or (was and c.get("restart_count", 0) > was.get("restart_count", 0)):
            p[f"ct:{name}"] = f"kontejner {name} se pořád restartuje (restartů: {c.get('restart_count')})"
        elif not c.get("running") and (was.get("running") or f"ct:{name}" in open_keys):
            # Stays an open problem until it runs again (the snapshot alone would forget it next tick).
            p[f"ct:{name}"] = f"kontejner {name} spadl / zastavil se (stav {c.get('status')}, exit {c.get('exit_code')})"
        elif c.get("running") and c.get("health") == "unhealthy":
            p[f"ct:{name}"] = f"kontejner {name} je unhealthy"
    pub = h.get("public", {})
    if pub and not pub.get("ok"):
        p["public"] = f"druhy.ppolivka.com není zvenku dostupný ({pub.get('code') or pub.get('error')}) – tunel/Caddy?"
    for c in h.get("certs", []) if isinstance(h.get("certs"), list) else []:
        if "days_left" in c and c["days_left"] < CERT_DAYS:
            p[f"cert:{c['host']}"] = f"certifikát {c['host']} vyprší za {c['days_left']} dní"
    u = h.get("updates", {})
    if u.get("security"):
        p["updates"] = f"čeká {u['security']} bezpečnostních aktualizací systému ({', '.join(u.get('security_pkgs', [])[:5])})"
    if u.get("reboot_required"):
        p["reboot"] = "server potřebuje restart po aktualizacích"
    return p


QUIP = ("Jsi „Ten druhý“, cynický vnitřní hlas, a hlídáš mu homelab. Napiš JEDNU krátkou úvodní větu k hlášení ze "
        "serveru (česky, hovorově, suše). NEZMIŇUJ žádná konkrétní fakta, názvy, služby ani čísla – ty přijdou pod tebou "
        "doslova. Jen nálada: {mood}. Vrať jen tu větu.")


def _resolved_text(key: str, h: dict | None) -> str:
    """What's true NOW for a cleared problem (current values, nothing to guess)."""
    h = h or {}
    if key.startswith("disk:"):
        d = next((d for d in h.get("disks", []) if d["mount"] == key[5:]), None)
        return f"disk {key[5:]} je zase v pořádku" + (f" ({d['used_pct']} %, volno {d['free_gb']} GB)" if d else "")
    if key.startswith("ct:"):
        return f"kontejner {key[3:]} zase normálně běží"
    if key.startswith("cert:"):
        return f"certifikát {key[5:]} je obnovený"
    return {"backup_errors": "záloha zase proběhla bez chyb", "backup_hung": "záloha zase doběhla",
            "backup_old": "je tu zase čerstvá záloha", "memory": "RAM je zase v pohodě", "load": "zátěž serveru opadla",
            "public": "druhy.ppolivka.com je zase zvenku dostupný", "updates": "bezpečnostní aktualizace jsou nainstalované",
            "reboot": "server je po restartu", "stale": "sběr stavu serveru zase běží"}.get(key, f"{key} je v pořádku")


def _message(new: list[str], repeat: list[str], resolved: list[str]) -> str:
    """His one-line opener (no facts, so nothing to hallucinate) + the exact facts as the watchdog found them."""
    mood = ("špatné zprávy" if new else "pořád to samé, nikdo to nespravil" if repeat else "dobré zprávy, je to spravené")
    try:
        quip = llm.generate(QUIP.format(mood=mood), "Úvodní věta:", temperature=0.9, patient=False).strip().splitlines()[0]
    except Exception:
        quip = ""
    quip = quip or {"špatné zprávy": "Server hlásí problém.", "dobré zprávy, je to spravené": "Dobrý zprávy, pro změnu."}.get(
        mood, "Pořád to visí.")
    lines = [*(f"• {x}" for x in new), *(f"• pořád: {x}" for x in repeat), *(f"• ✓ {x}" for x in resolved)]
    return quip + "\n" + "\n".join(lines)


def check():
    h = read()
    prev = json.loads((_q("SELECT v FROM watchdog_kv WHERE k = 'containers'") or [("{}",)])[0][0])
    if h is None:
        found = {"stale": "soubor se stavem serveru (host.json) chybí – běží sběr stavu na hostu?"}
    else:
        open_keys = {k for (k,) in _q("SELECT key FROM watchdog_alerts")}
        found = problems(h, prev, open_keys)
        conts = {c["name"]: c for c in h.get("containers", []) if isinstance(c, dict)}
        _q("INSERT INTO watchdog_kv(k, v) VALUES ('containers', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
           (json.dumps(conts),))
    now = int(time.time())
    known = {k: (t, f, s) for k, t, f, s in _q("SELECT key, text, first_seen, last_sent FROM watchdog_alerts")}
    new, repeat, resolved = [], [], []
    for k, text in found.items():
        if k not in known:
            new.append(text)
            _q("INSERT INTO watchdog_alerts(key, text, first_seen, last_sent) VALUES (?, ?, ?, ?)", (k, text, now, now))
        elif now - known[k][2] > REPEAT_H * 3600:
            repeat.append(text)
            _q("UPDATE watchdog_alerts SET text = ?, last_sent = ? WHERE key = ?", (text, now, k))
    for k, (text, _, _) in known.items():
        if k not in found:
            resolved.append(_resolved_text(k, h))
            _q("DELETE FROM watchdog_alerts WHERE key = ?", (k,))
    if not (new or repeat or resolved):
        return None
    msg = _message(new, repeat, resolved)
    title = "Homelab: " + ("vyřešeno" if not (new or repeat) else (new or repeat)[0][:40])
    for user in config.ADMIN_USERS:
        cid = sessions.create(user)
        sessions.add(cid, "assistant", msg)
        sessions.set_title(cid, title)
        push.send(user, "Ten druhý – homelab", msg, f"/?c={cid}")
    print(f"  [watchdog] new={len(new)} repeat={len(repeat)} resolved={len(resolved)}", flush=True)
    return msg


def summary() -> str:
    """Compact status for the chat tool."""
    h = read()
    if not h:
        return "stav serveru není k dispozici (host.json chybí)"
    s, r, u = h.get("system", {}), h.get("restic", {}), h.get("updates", {})
    cs = [c for c in h.get("containers", []) if isinstance(c, dict)]
    down = [c["name"] for c in cs if not c.get("running")]
    bad = [c["name"] for c in cs if (c.get("running") and c.get("health") == "unhealthy") or c.get("restarting")]
    lines = [
        f"data z {datetime.fromtimestamp(h['ts'], TZ):%H:%M}",
        "disky: " + ", ".join(f"{d['mount']} {d['used_pct']} % (volno {d['free_gb']} GB)" for d in h.get("disks", [])),
        f"RAM volno {s.get('mem_available_mb')} / {s.get('mem_total_mb')} MB, swap {s.get('swap_used_mb')} MB, "
        f"load {s.get('load1')}/{s.get('load5')}/{s.get('load15')} na {s.get('cpus')} CPU",
        f"záloha: poslední hotová {r.get('last_complete')}, snapshot {r.get('last_snapshot')}"
        + (f", CHYBY: {r['errors']}" if r.get("errors") else ""),
        f"kontejnery: {sum(1 for c in cs if c.get('running'))} běží z {len(cs)}; zastavené: {', '.join(down) or '-'}"
        + (f"; problém: {', '.join(bad)}" if bad else ""),
        f"aktualizace: {u.get('upgradable')} čeká, z toho bezpečnostních {u.get('security')}"
        + (", potřebuje restart" if u.get("reboot_required") else ""),
        f"veřejně: {'OK' if h.get('public', {}).get('ok') else 'NEDOSTUPNÉ'} ({h.get('public', {}).get('ms')} ms)",
        "certifikáty: " + ", ".join(f"{c['host']} {c.get('days_left', '?')} dní" for c in h.get("certs", [])),
    ]
    return "\n".join(lines)


tools.register(tools.Tool("homelab_status", "stav jeho domácího serveru (disky, RAM, zálohy, kontejnery, aktualizace, "
                                            "dostupnost). Args: {}", lambda user, args: summary(), allowed=is_admin))


def _loop():
    time.sleep(90)
    while True:
        try:
            check()
        except Exception as e:
            print(f"  [watchdog] {str(e)[:120]}", flush=True)
        time.sleep(TICK_S)


def start():
    if config.ADMIN_USERS:
        threading.Thread(target=_loop, daemon=True, name="watchdog").start()

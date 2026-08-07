# -*- coding: utf-8 -*-
"""
SmartY Login Security for PySpigot 0.9.1 / Jython 2.7.

Records every pre-login attempt and confirmed session, maintains account/IP
relations, optionally enriches public IPs with approximate geolocation, and
supports opt-in strict IP locking per account.

IMPORTANT: IP geolocation is approximate.  With geo enabled, public IPs are
sent over HTTPS to ipwho.is.  Disable it with /loginsec geo off if undesired.
"""

import os
import io
import json
import time
import math
import shutil
import threading

import pyspigot as ps

from java.lang import Runnable, System, String as JavaString
from java.net import URL
from java.io import BufferedReader, InputStreamReader
from java.util.concurrent import Executors, TimeUnit
from org.bukkit import Bukkit
from org.bukkit.entity import Player
from org.bukkit.event.player import (
    AsyncPlayerPreLoginEvent, PlayerJoinEvent, PlayerQuitEvent
)


try:
    unicode
except NameError:
    unicode = str


cmd_mgr = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler = ps.scheduler

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
DB_FILE = os.path.join(DATA_DIR, "login_security.json")
BACKUP_FILE = DB_FILE + ".bak"
AUDIT_FILE = os.path.join(DATA_DIR, "login_security_audit.log")

MAX_RECENT = 5000
MAX_ALERTS = 1500
GEO_CACHE_SECONDS = 30 * 24 * 3600
BASELINE_RADIUS_KM = 250.0
IMPOSSIBLE_SPEED_KMH = 900.0
GEO_ENDPOINT = "https://ipwho.is/"

db_lock = threading.RLock()
pending_logins = {}       # uuid -> prelogin record
session_starts = {}       # uuid -> epoch
admin_notices = []
geo_pending = set()
running = [True]
geo_executor = Executors.newFixedThreadPool(2)


def _text(value):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    try:
        return unicode(value)
    except Exception:
        try:
            return unicode(str(value), "utf-8", "replace")
        except Exception:
            return u""


def _timestamp(epoch=None):
    value = time.time() if epoch is None else float(epoch)
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


def _default_db():
    return {
        "version": 1,
        "settings": {"geo_enabled": True},
        "players": {},
        "ips": {},
        "geo_cache": {},
        "recent": [],
        "alerts": []
    }


def _ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        try:
            os.makedirs(DATA_DIR)
        except Exception:
            pass


def _load_json(path):
    f = io.open(path, "r", encoding="utf-8")
    try:
        return json.load(f)
    finally:
        f.close()


def _load_db():
    data = None
    for path in (DB_FILE, BACKUP_FILE):
        if not os.path.exists(path):
            continue
        try:
            candidate = _load_json(path)
            if isinstance(candidate, dict):
                data = candidate
                break
        except Exception as exc:
            Bukkit.getLogger().warning("[login-security] Could not read " + path + ": " + str(exc))
    base = _default_db()
    if isinstance(data, dict):
        for key in base.keys():
            if key in data:
                base[key] = data[key]
    if not isinstance(base.get("settings"), dict): base["settings"] = {"geo_enabled": True}
    if not isinstance(base.get("players"), dict): base["players"] = {}
    if not isinstance(base.get("ips"), dict): base["ips"] = {}
    if not isinstance(base.get("geo_cache"), dict): base["geo_cache"] = {}
    if not isinstance(base.get("recent"), list): base["recent"] = []
    if not isinstance(base.get("alerts"), list): base["alerts"] = []
    return base


database = _load_db()


def _save_db_locked():
    _ensure_data_dir()
    temp_file = DB_FILE + ".tmp"
    try:
        payload = json.dumps(database, ensure_ascii=True, indent=2, sort_keys=True)
        if not isinstance(payload, unicode):
            payload = payload.decode("utf-8", "replace")
        f = io.open(temp_file, "w", encoding="utf-8")
        try:
            f.write(payload)
            f.flush()
            try: os.fsync(f.fileno())
            except Exception: pass
        finally:
            f.close()
        if os.path.exists(DB_FILE):
            try: shutil.copy2(DB_FILE, BACKUP_FILE)
            except Exception: pass
        try:
            from java.nio.file import Files, Paths, StandardCopyOption
            Files.move(Paths.get(temp_file), Paths.get(DB_FILE),
                       StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        except Exception:
            if os.path.exists(DB_FILE): os.remove(DB_FILE)
            os.rename(temp_file, DB_FILE)
        return True
    except Exception as exc:
        Bukkit.getLogger().warning("[login-security] Database save failed: " + str(exc))
        return False


def save_db():
    db_lock.acquire()
    try:
        return _save_db_locked()
    finally:
        db_lock.release()


def _append_audit(record):
    try:
        _ensure_data_dir()
        line = json.dumps(record, ensure_ascii=True, sort_keys=True)
        if not isinstance(line, unicode): line = line.decode("utf-8", "replace")
        f = io.open(AUDIT_FILE, "a", encoding="utf-8")
        try: f.write(line + u"\n")
        finally: f.close()
    except Exception as exc:
        Bukkit.getLogger().warning("[login-security] Audit write failed: " + str(exc))


def _bounded_append(target, item, maximum):
    target.append(item)
    if len(target) > maximum:
        del target[:-maximum]


def _new_player(uuid_str, name):
    return {
        "uuid": uuid_str,
        "current_name": name,
        "names": [name],
        "first_seen": time.time(),
        "last_attempt": 0.0,
        "last_success": 0.0,
        "last_success_ip": None,
        "ips": {},
        "trusted_ips": [],
        "locked": False,
        "baseline_geo": None,
        "sessions": 0
    }


def _player_record(uuid_str, name):
    record = database["players"].get(uuid_str)
    if not isinstance(record, dict):
        record = _new_player(uuid_str, name)
        database["players"][uuid_str] = record
    record["current_name"] = name
    names = record.setdefault("names", [])
    if name not in names: names.append(name)
    record.setdefault("ips", {})
    record.setdefault("trusted_ips", [])
    record.setdefault("locked", False)
    record.setdefault("baseline_geo", None)
    return record


def _ip_record(ip):
    record = database["ips"].get(ip)
    if not isinstance(record, dict):
        record = {"first_seen": time.time(), "last_seen": time.time(),
                  "successful_accounts": {}, "attempted_names": [], "attempts": 0,
                  "successful_logins": 0}
        database["ips"][ip] = record
    record.setdefault("successful_accounts", {})
    record.setdefault("attempted_names", [])
    return record


def _mask_ip(ip):
    raw = _text(ip)
    if u":" in raw:
        parts = raw.split(u":")
        return u":".join(parts[:3]) + u":…"
    parts = raw.split(u".")
    if len(parts) == 4:
        return u".".join(parts[:3]) + u".*"
    return u"***"


def _is_public_address(address):
    try:
        return not (address.isAnyLocalAddress() or address.isLoopbackAddress() or
                    address.isLinkLocalAddress() or address.isSiteLocalAddress() or
                    address.isMulticastAddress())
    except Exception:
        return False


def _queue_notice(message):
    db_lock.acquire()
    try:
        admin_notices.append(_text(message))
    finally:
        db_lock.release()


def _create_alert(kind, severity, uuid_str, name, ip, details):
    alert = {
        "time": time.time(), "timestamp": _timestamp(), "kind": kind,
        "severity": severity, "uuid": uuid_str, "player": name,
        "ip": ip, "details": _text(details)
    }
    _bounded_append(database["alerts"], alert, MAX_ALERTS)
    _append_audit(dict(alert, event="SECURITY_ALERT"))
    _queue_notice(u"§c[LoginSecurity] §f{0} §7— {1} §8({2})".format(
        name, _text(details), _mask_ip(ip)))
    return alert


def _allowed_result_name(event):
    try: return str(event.getLoginResult().name())
    except Exception:
        try: return str(event.getResult().name())
        except Exception: return "UNKNOWN"


def _event_raw_ip(event):
    try:
        address = event.getRawAddress()
        return address.getHostAddress() if address is not None else u""
    except Exception:
        return u""


def _event_hostname(event):
    try: return _text(event.getHostname())
    except Exception: return u""


def _event_transferred(event):
    try: return bool(event.isTransferred())
    except Exception: return False


def _find_player(query):
    needle = _text(query).strip().lower()
    direct = database["players"].get(_text(query).strip())
    if isinstance(direct, dict): return direct
    matches = []
    for record in database["players"].values():
        names = [_text(n).lower() for n in record.get("names", [])]
        if _text(record.get("current_name")).lower() == needle or needle in names:
            matches.append(record)
    return matches[0] if len(matches) == 1 else None


def _geo_summary(geo):
    if not isinstance(geo, dict) or not geo.get("success"):
        return u"геолокация неизвестна"
    parts = [geo.get("country"), geo.get("region"), geo.get("city")]
    return u", ".join([_text(part) for part in parts if part])


def _distance_km(a, b):
    try:
        lat1 = math.radians(float(a.get("latitude")))
        lon1 = math.radians(float(a.get("longitude")))
        lat2 = math.radians(float(b.get("latitude")))
        lon2 = math.radians(float(b.get("longitude")))
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        value = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
        return 6371.0 * 2.0 * math.asin(min(1.0, math.sqrt(value)))
    except Exception:
        return 0.0


def _read_connection(conn):
    reader = BufferedReader(InputStreamReader(conn.getInputStream(), "UTF-8"))
    parts = []
    try:
        while True:
            line = reader.readLine()
            if line is None: break
            parts.append(_text(line))
            if sum([len(part) for part in parts]) > 262144:
                raise ValueError("geolocation response is too large")
    finally:
        reader.close()
    return u"".join(parts)


def _lookup_geo(ip):
    conn = None
    try:
        conn = URL(GEO_ENDPOINT + ip + "?lang=ru").openConnection()
        conn.setConnectTimeout(3000)
        conn.setReadTimeout(4000)
        conn.setRequestProperty("User-Agent", "SmartY-LoginSecurity/1.0")
        payload = _read_connection(conn)
        raw = json.loads(payload)
        if not isinstance(raw, dict) or not raw.get("success"):
            return {"success": False, "message": _text(raw.get("message", "lookup failed")) if isinstance(raw, dict) else u"lookup failed"}
        timezone = raw.get("timezone") if isinstance(raw.get("timezone"), dict) else {}
        connection = raw.get("connection") if isinstance(raw.get("connection"), dict) else {}
        return {
            "success": True, "fetched_at": time.time(),
            "country": raw.get("country"), "country_code": raw.get("country_code"),
            "region": raw.get("region"), "city": raw.get("city"),
            "latitude": raw.get("latitude"), "longitude": raw.get("longitude"),
            "timezone": timezone.get("id"), "isp": connection.get("isp"),
            "org": connection.get("org"), "asn": connection.get("asn")
        }
    except Exception as exc:
        return {"success": False, "message": _text(exc), "fetched_at": time.time()}
    finally:
        try:
            if conn is not None and hasattr(conn, "disconnect"): conn.disconnect()
        except Exception:
            pass


def _evaluate_geo_alerts(ip, geo):
    for player_record in database["players"].values():
        ip_info = player_record.get("ips", {}).get(ip)
        if not isinstance(ip_info, dict):
            continue
        uuid_str = player_record.get("uuid")
        name = player_record.get("current_name")
        baseline = player_record.get("baseline_geo")
        if isinstance(baseline, dict):
            distance = _distance_km(baseline, geo)
            if distance > BASELINE_RADIUS_KM and not ip_info.get("baseline_alerted"):
                ip_info["baseline_alerted"] = True
                _create_alert("LOCATION_DEVIATION", "HIGH", uuid_str, name, ip,
                              u"вход примерно в {0:.0f} км от сохранённой локации: {1}".format(
                                  distance, _geo_summary(geo)))

        previous_ip = ip_info.get("previous_ip")
        previous = player_record.get("ips", {}).get(previous_ip) if previous_ip else None
        previous_geo = previous.get("geo") if isinstance(previous, dict) else None
        if isinstance(previous_geo, dict) and previous_geo.get("success"):
            old_country = _text(previous_geo.get("country_code"))
            new_country = _text(geo.get("country_code"))
            if old_country and new_country and old_country != new_country and not ip_info.get("country_alerted"):
                ip_info["country_alerted"] = True
                _create_alert("COUNTRY_CHANGE", "HIGH", uuid_str, name, ip,
                              u"смена страны: {0} → {1}".format(
                                  _geo_summary(previous_geo), _geo_summary(geo)))
            elapsed = float(ip_info.get("first_seen", 0.0)) - float(previous.get("last_seen", 0.0))
            distance = _distance_km(previous_geo, geo)
            if elapsed > 0 and elapsed < 48 * 3600 and distance > 300:
                speed = distance / max(elapsed / 3600.0, 0.01)
                if speed > IMPOSSIBLE_SPEED_KMH and not ip_info.get("travel_alerted"):
                    ip_info["travel_alerted"] = True
                    _create_alert("IMPOSSIBLE_TRAVEL", "HIGH", uuid_str, name, ip,
                                  u"подозрительная смена локации: {0:.0f} км, расчётная скорость {1:.0f} км/ч".format(
                                      distance, speed))


class GeoLookupTask(Runnable):
    def __init__(self, ip):
        self.ip = ip

    def run(self):
        try:
            geo = _lookup_geo(self.ip)
            db_lock.acquire()
            try:
                database["geo_cache"][self.ip] = geo
                ip_record = database["ips"].get(self.ip)
                if isinstance(ip_record, dict): ip_record["geo"] = geo
                for player_record in database["players"].values():
                    info = player_record.get("ips", {}).get(self.ip)
                    if isinstance(info, dict): info["geo"] = geo
                if geo.get("success"):
                    _evaluate_geo_alerts(self.ip, geo)
                    _append_audit({"event": "GEO_RESOLVED", "timestamp": _timestamp(),
                                   "time": time.time(), "ip": self.ip, "geo": geo})
                _save_db_locked()
            finally:
                geo_pending.discard(self.ip)
                db_lock.release()
        except Exception as exc:
            db_lock.acquire()
            try: geo_pending.discard(self.ip)
            finally: db_lock.release()
            Bukkit.getLogger().warning("[login-security] Geo worker failed: " + str(exc))


def _schedule_geo(ip, address):
    db_lock.acquire()
    try:
        if not database.get("settings", {}).get("geo_enabled", True): return
        if not _is_public_address(address): return
        cached = database.get("geo_cache", {}).get(ip)
        if isinstance(cached, dict) and time.time() - float(cached.get("fetched_at", 0.0)) < GEO_CACHE_SECONDS:
            return
        if ip in geo_pending: return
        if len(geo_pending) >= 50: return
        geo_pending.add(ip)
        geo_executor.submit(GeoLookupTask(ip))
    finally:
        db_lock.release()


def on_prelogin(event):
    now = time.time()
    name = _text(event.getName())
    uuid_str = _text(event.getUniqueId().toString())
    address = event.getAddress()
    ip = _text(address.getHostAddress())
    raw_ip = _text(_event_raw_ip(event))
    initial_result = _allowed_result_name(event)

    db_lock.acquire()
    try:
        player_record = _player_record(uuid_str, name)
        previous_ip = player_record.get("last_success_ip")
        known_success_ip = ip in player_record.get("ips", {})
        player_record["last_attempt"] = now
        ip_record = _ip_record(ip)
        ip_record["last_seen"] = now
        ip_record["attempts"] = int(ip_record.get("attempts", 0)) + 1
        attempted_names = ip_record.setdefault("attempted_names", [])
        if name not in attempted_names:
            attempted_names.append(name)
            if len(attempted_names) > 100: del attempted_names[:-100]

        name_collision = None
        lower_name = name.lower()
        for other_uuid, other in database["players"].items():
            if other_uuid != uuid_str and lower_name in [_text(n).lower() for n in other.get("names", [])]:
                name_collision = other_uuid
                break

        blocked_by_lock = False
        if initial_result == "ALLOWED" and bool(player_record.get("locked")):
            if ip not in player_record.get("trusted_ips", []):
                try:
                    event.disallow(AsyncPlayerPreLoginEvent.Result.KICK_WHITELIST,
                                   u"§cВход с нового IP заблокирован защитой аккаунта.\n§7Обратитесь к администрации сервера.")
                    blocked_by_lock = _allowed_result_name(event) != "ALLOWED"
                except Exception as exc:
                    Bukkit.getLogger().warning("[login-security] Could not block unknown IP: " + str(exc))

        final_result = "BLOCKED_UNKNOWN_IP" if blocked_by_lock else _allowed_result_name(event)
        record = {
            "event": "PRELOGIN", "time": now, "timestamp": _timestamp(now),
            "uuid": uuid_str, "player": name, "ip": ip, "raw_ip": raw_ip,
            "hostname": _event_hostname(event), "transferred": _event_transferred(event),
            "initial_result": initial_result, "result": final_result,
            "online_mode": bool(Bukkit.getOnlineMode()), "previous_ip": previous_ip
        }
        _bounded_append(database["recent"], record, MAX_RECENT)
        _append_audit(record)

        if initial_result == "ALLOWED" and not known_success_ip and previous_ip:
            _create_alert("NEW_IP", "HIGH", uuid_str, name, ip,
                          u"новый IP; предыдущий: " + _mask_ip(previous_ip))
        if name_collision:
            _create_alert("NAME_UUID_COLLISION", "HIGH", uuid_str, name, ip,
                          u"тот же ник замечен с другим UUID")
        if blocked_by_lock:
            _create_alert("IP_LOCK_BLOCK", "CRITICAL", uuid_str, name, ip,
                          u"IP-lock заблокировал вход с недоверенного адреса")

        if initial_result == "ALLOWED" and not blocked_by_lock:
            pending_logins[uuid_str] = record
            player_record["last_success"] = now
            player_record["last_success_ip"] = ip
            player_record["sessions"] = int(player_record.get("sessions", 0)) + 1
            ip_info = player_record.setdefault("ips", {}).get(ip)
            if not isinstance(ip_info, dict):
                ip_info = {"first_seen": now, "last_seen": now, "count": 0,
                           "previous_ip": previous_ip}
                player_record["ips"][ip] = ip_info
            ip_info["last_seen"] = now
            ip_info["count"] = int(ip_info.get("count", 0)) + 1
            successful_accounts = ip_record.setdefault("successful_accounts", {})
            account_was_linked = uuid_str in successful_accounts
            successful_accounts[uuid_str] = name
            ip_record["successful_logins"] = int(ip_record.get("successful_logins", 0)) + 1
            if not account_was_linked and len(successful_accounts) >= 3:
                _create_alert("SHARED_IP", "MEDIUM", uuid_str, name, ip,
                              u"с этого IP успешно входили {0} аккаунта(ов)".format(len(successful_accounts)))
        _save_db_locked()
    finally:
        db_lock.release()

    if initial_result == "ALLOWED" or blocked_by_lock:
        _schedule_geo(ip, address)


def _safe_player_detail(player, method, default=u"unknown"):
    try:
        value = getattr(player, method)()
        return _text(value) if value is not None else default
    except Exception:
        return default


def _record_client_details(player, uuid_str, join_time):
    if not player.isOnline(): return
    record = {
        "event": "CLIENT_DETAILS", "time": time.time(), "timestamp": _timestamp(),
        "uuid": uuid_str, "player": player.getName(),
        "protocol": _safe_player_detail(player, "getProtocolVersion"),
        "client_brand": _safe_player_detail(player, "getClientBrandName"),
        "locale": _safe_player_detail(player, "getLocale"),
        "ping": _safe_player_detail(player, "getPing")
    }
    db_lock.acquire()
    try:
        player_record = database.get("players", {}).get(uuid_str)
        if isinstance(player_record, dict):
            player_record["last_client"] = {
                "time": record["time"], "protocol": record["protocol"],
                "client_brand": record["client_brand"], "locale": record["locale"],
                "ping": record["ping"]
            }
        _bounded_append(database["recent"], record, MAX_RECENT)
        _append_audit(record)
        _save_db_locked()
    finally:
        db_lock.release()


def on_join(event):
    player = event.getPlayer()
    uuid_str = _text(player.getUniqueId().toString())
    now = time.time()
    session_starts[uuid_str] = now
    prelogin = pending_logins.pop(uuid_str, {})
    record = {
        "event": "JOIN_CONFIRMED", "time": now, "timestamp": _timestamp(now),
        "uuid": uuid_str, "player": player.getName(), "ip": prelogin.get("ip"),
        "world": player.getWorld().getName()
    }
    db_lock.acquire()
    try:
        _bounded_append(database["recent"], record, MAX_RECENT)
        _append_audit(record)
        _save_db_locked()
    finally:
        db_lock.release()
    scheduler.runTaskLater(lambda: _record_client_details(player, uuid_str, now), 40)


def on_quit(event):
    player = event.getPlayer()
    uuid_str = _text(player.getUniqueId().toString())
    now = time.time()
    started = session_starts.pop(uuid_str, now)
    record = {
        "event": "QUIT", "time": now, "timestamp": _timestamp(now),
        "uuid": uuid_str, "player": player.getName(),
        "session_seconds": max(0, int(now - started))
    }
    db_lock.acquire()
    try:
        _bounded_append(database["recent"], record, MAX_RECENT)
        _append_audit(record)
        _save_db_locked()
    finally:
        db_lock.release()


def _admin_notice_tick():
    if not running[0]: return
    db_lock.acquire()
    try:
        notices = list(admin_notices)
        admin_notices[:] = []
    finally:
        db_lock.release()
    if notices:
        for player in Bukkit.getOnlinePlayers():
            try:
                if player.isOp() or player.hasPermission("loginsecurity.admin"):
                    for notice in notices: player.sendMessage(notice)
            except Exception:
                pass
        for notice in notices:
            Bukkit.getLogger().warning(u"[login-security] " + notice.replace(u"§", u"&"))
    scheduler.runTaskLater(_admin_notice_tick, 20)


def _has_admin(sender):
    try: return bool(sender.isOp() or sender.hasPermission("loginsecurity.admin"))
    except Exception: return not isinstance(sender, Player)


def _send(sender, message):
    sender.sendMessage(u"§8[§cLoginSecurity§8] §r" + _text(message))


def _format_login(record):
    result = record.get("result", record.get("event", "?"))
    return u"§7{0} §f{1} §8— §e{2} §8— §f{3}".format(
        record.get("timestamp", _timestamp(record.get("time", 0))),
        record.get("player", u"?"), record.get("ip", u"—"), result)


def _is_command_string(value):
    return isinstance(value, (str, unicode, JavaString))


def _normalize_command_args(label, args):
    values = []
    # Normal PySpigot callback: (sender, label, Java String[] args).
    if args is not None and not _is_command_string(args):
        try: values = [_text(value) for value in list(args)]
        except Exception: values = []
    # Compatibility with builds/wrappers that swap label and args.
    if not values and label is not None and not _is_command_string(label):
        try: values = [_text(value) for value in list(label)]
        except Exception: values = []
    # Last-resort handling when arguments arrive as one raw string.
    if not values and args is not None and _is_command_string(args):
        raw_args = _text(args).strip()
        if raw_args.lower().lstrip(u"/") not in [u"loginsec", u"loginsecurity"]:
            values = raw_args.split()
    if not values and label is not None and _is_command_string(label):
        raw_label = _text(label).strip()
        if raw_label.lower().lstrip(u"/") not in [u"loginsec", u"loginsecurity"]:
            values = raw_label.split()

    flattened = []
    for value in values:
        flattened.extend(_text(value).strip().split())
    while flattened and flattened[0].lower().lstrip(u"/") in [u"loginsec", u"loginsecurity"]:
        del flattened[0]
    return flattened


def cmd_loginsecurity(sender, label, args):
    command_args = _normalize_command_args(label, args)
    if not _has_admin(sender):
        _send(sender, u"§cНет права loginsecurity.admin.")
        return True
    sub = command_args[0].lower() if command_args else u"help"

    db_lock.acquire()
    try:
        if sub in [u"help", u"?"]:
            _send(sender, u"§f/loginsec player <ник> §7— IP и история аккаунта")
            _send(sender, u"§f/loginsec accounts <IP> §7— аккаунты, успешно входившие с IP")
            _send(sender, u"§f/loginsec recent [число] §7— последние попытки")
            _send(sender, u"§f/loginsec alerts [число] §7— предупреждения")
            _send(sender, u"§f/loginsec lock <ник> <on|off> §7— строгая привязка IP")
            _send(sender, u"§f/loginsec trust|untrust <ник> <IP> §7— доверенные адреса")
            _send(sender, u"§f/loginsec baseline <ник> §7— сохранить текущую геолокацию")
            _send(sender, u"§f/loginsec geo <on|off> §7— внешняя геолокация IP")
            return True

        if sub in [u"player", u"user"] and len(command_args) >= 2:
            record = _find_player(command_args[1])
            if not record:
                _send(sender, u"§cИгрок не найден в журнале.")
                return True
            _send(sender, u"§f{0} §7| UUID: §f{1}".format(record.get("current_name"), record.get("uuid")))
            _send(sender, u"§7IP-lock: {0} §7| входов: §f{1}".format(
                u"§aвключён" if record.get("locked") else u"§cвыключен", record.get("sessions", 0)))
            client = record.get("last_client")
            if isinstance(client, dict):
                _send(sender, u"§7Клиент: §f{0} §7| протокол: §f{1} §7| язык: §f{2}".format(
                    client.get("client_brand", u"unknown"), client.get("protocol", u"unknown"),
                    client.get("locale", u"unknown")))
            ordered = sorted(record.get("ips", {}).items(), key=lambda item: item[1].get("last_seen", 0), reverse=True)
            for ip, info in ordered[:15]:
                _send(sender, u"§e{0} §7— {1} §8| §7входов: §f{2} §8| §7последний: §f{3}".format(
                    ip, _geo_summary(info.get("geo")), info.get("count", 0), _timestamp(info.get("last_seen", 0))))
            return True

        if sub in [u"accounts", u"ip"] and len(command_args) >= 2:
            ip = command_args[1].strip()
            record = database["ips"].get(ip)
            if not record:
                _send(sender, u"§cIP не найден.")
                return True
            accounts = record.get("successful_accounts", {})
            _send(sender, u"§e{0} §7— {1}".format(ip, _geo_summary(record.get("geo"))))
            _send(sender, u"§7Успешные аккаунты ({0}): §f{1}".format(
                len(accounts), u", ".join([_text(name) for name in accounts.values()]) or u"нет"))
            _send(sender, u"§7Всего попыток: §f{0} §7| успешных: §f{1}".format(
                record.get("attempts", 0), record.get("successful_logins", 0)))
            return True

        if sub == u"recent":
            limit = 10
            if len(command_args) > 1:
                try: limit = max(1, min(50, int(command_args[1])))
                except Exception: pass
            for record in list(reversed(database["recent"]))[:limit]:
                _send(sender, _format_login(record))
            return True

        if sub == u"alerts":
            limit = 10
            if len(command_args) > 1:
                try: limit = max(1, min(50, int(command_args[1])))
                except Exception: pass
            for alert in list(reversed(database["alerts"]))[:limit]:
                _send(sender, u"§7{0} §c{1} §f{2} §e{3} §7— {4}".format(
                    alert.get("timestamp"), alert.get("severity"), alert.get("player"),
                    alert.get("ip"), alert.get("details")))
            return True

        if sub == u"lock" and len(command_args) >= 3:
            record = _find_player(command_args[1])
            if not record:
                _send(sender, u"§cИгрок не найден.")
                return True
            enabled = command_args[2].lower() in [u"on", u"true", u"1", u"да"]
            if enabled:
                current_ip = record.get("last_success_ip")
                if not current_ip:
                    _send(sender, u"§cУ игрока ещё нет успешного входа.")
                    return True
                trusted = record.setdefault("trusted_ips", [])
                if current_ip not in trusted: trusted.append(current_ip)
            record["locked"] = enabled
            _save_db_locked()
            _send(sender, u"§aIP-lock {0}.".format(u"включён" if enabled else u"выключен"))
            return True

        if sub in [u"trust", u"untrust"] and len(command_args) >= 3:
            record = _find_player(command_args[1])
            if not record:
                _send(sender, u"§cИгрок не найден.")
                return True
            ip = command_args[2].strip()
            trusted = record.setdefault("trusted_ips", [])
            if sub == u"trust" and ip not in trusted: trusted.append(ip)
            if sub == u"untrust" and ip in trusted: trusted.remove(ip)
            _save_db_locked()
            _send(sender, u"§aСписок доверенных IP обновлён: §f" + (u", ".join(trusted) or u"пусто"))
            return True

        if sub == u"baseline" and len(command_args) >= 2:
            record = _find_player(command_args[1])
            if not record or not record.get("last_success_ip"):
                _send(sender, u"§cНет успешного входа игрока.")
                return True
            ip = record.get("last_success_ip")
            geo = record.get("ips", {}).get(ip, {}).get("geo")
            if not isinstance(geo, dict) or not geo.get("success"):
                _send(sender, u"§cГеолокация ещё не получена. Повторите через несколько секунд.")
                return True
            record["baseline_geo"] = dict(geo)
            _save_db_locked()
            _send(sender, u"§aБазовая локация сохранена: §f" + _geo_summary(geo))
            return True

        if sub == u"geo" and len(command_args) >= 2:
            enabled = command_args[1].lower() in [u"on", u"true", u"1", u"да"]
            database.setdefault("settings", {})["geo_enabled"] = enabled
            _save_db_locked()
            _send(sender, u"§aГеолокация {0}.".format(u"включена" if enabled else u"выключена"))
            return True

        if sub == u"status":
            _send(sender, u"§7Игроков: §f{0} §7| IP: §f{1} §7| предупреждений: §f{2} §7| geo: {3}".format(
                len(database["players"]), len(database["ips"]), len(database["alerts"]),
                u"§aвкл" if database.get("settings", {}).get("geo_enabled", True) else u"§cвыкл"))
            return True
    finally:
        db_lock.release()

    _send(sender, u"§cНеизвестная команда. Используйте /loginsec help")
    _send(sender, u"§8Диагностика: label={0}, args={1}, parsed={2}".format(
        _text(label), _text(args), u" ".join(command_args)))
    return True


listener_mgr.registerListener(on_prelogin, AsyncPlayerPreLoginEvent)
listener_mgr.registerListener(on_join, PlayerJoinEvent)
listener_mgr.registerListener(on_quit, PlayerQuitEvent)
cmd_mgr.registerCommand(cmd_loginsecurity, "loginsecurity")
cmd_mgr.registerCommand(cmd_loginsecurity, "loginsec")
_admin_notice_tick()
save_db()
Bukkit.getLogger().info("[login-security] Loaded. Commands: /loginsec help")


def stop(script=None):
    running[0] = False
    save_db()
    try:
        geo_executor.shutdown()
        geo_executor.awaitTermination(2, TimeUnit.SECONDS)
    except Exception:
        try: geo_executor.shutdownNow()
        except Exception: pass

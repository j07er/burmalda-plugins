# -*- coding: utf-8 -*-
"""
Отдельная блокировка Ада/Энда и аудит фактических обходов.

Флаги открытия читаются из data/world_achievements.json, поэтому команды
/wa nether|end on|off остаются единственным источником состояния.

ВАЖНО: скрипт намеренно повторяет старую блокировку только PlayerPortalEvent.
Он не возвращает игрока из закрытого мира и не блокирует перенос на лодке —
такие обходы нужны для аудита и записываются в отдельный журнал.
"""

import os
import io
import json
import time

import pyspigot as ps

from java.lang import System
from org.bukkit import Bukkit
from org.bukkit.entity import Player
from org.bukkit.event.player import (
    PlayerPortalEvent, PlayerTeleportEvent, PlayerChangedWorldEvent,
    PlayerJoinEvent, PlayerQuitEvent
)
from org.bukkit.event.vehicle import VehicleEnterEvent, VehicleExitEvent


listener_mgr = ps.listener_manager()
scheduler = ps.scheduler

def _resolve_script_dir():
    """Find plugins/PySpigot/scripts even when PySpigot omits __file__."""
    cwd = os.path.abspath(os.getcwd())

    # Depending on how the server was launched, cwd may be the scripts folder,
    # the PySpigot plugin folder, or the server root.
    candidates = []
    if os.path.basename(cwd).lower() == "scripts":
        candidates.append(cwd)
    if os.path.basename(cwd).lower() == "pyspigot":
        candidates.append(os.path.join(cwd, "scripts"))
    candidates.append(os.path.join(cwd, "plugins", "PySpigot", "scripts"))

    for candidate in candidates:
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)

    try:
        if "__file__" in globals() and __file__:
            return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        pass
    return cwd


SCRIPT_DIR = _resolve_script_dir()
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
STATE_FILE = os.path.join(DATA_DIR, "world_achievements.json")
AUDIT_FILE = os.path.join(DATA_DIR, "dimension_access_audit.log")


def _state_candidates():
    cwd = os.path.abspath(os.getcwd())
    raw = [
        STATE_FILE,
        os.path.join(cwd, "data", "world_achievements.json"),
        os.path.join(cwd, "plugins", "PySpigot", "scripts", "data",
                     "world_achievements.json"),
        os.path.join(cwd, "plugins", "PySpigot", "data",
                     "world_achievements.json"),
        os.path.join(os.path.dirname(SCRIPT_DIR), "data",
                     "world_achievements.json"),
    ]
    result = []
    seen = set()
    for path in raw:
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized not in seen:
            seen.add(normalized)
            result.append(os.path.abspath(path))
    return result


STATE_CANDIDATES = _state_candidates()

DEFAULT_STATE = {"nether_enabled": False, "end_enabled": False}

state_cache = dict(DEFAULT_STATE)
state_stamp = [None]
active_state_file = [STATE_FILE]
recent_teleports = {}     # uuid -> context
vehicle_context = {}      # uuid -> context, сохраняется недолго после выхода
audit_seen = {}           # uuid -> world name, чтобы ticker не спамил
running = [True]


def now_tick():
    return long(System.currentTimeMillis() / 50)


def uid(entity):
    return entity.getUniqueId().toString()


def _ensure_data_dir():
    try:
        if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)
    except Exception: pass


def _reload_state(force=False):
    global state_cache
    try:
        existing = [path for path in STATE_CANDIDATES if os.path.isfile(path)]
        state_file = max(existing, key=os.path.getmtime) if existing else STATE_FILE
        mtime = os.path.getmtime(state_file) if os.path.exists(state_file) else -1.0
        stamp = (os.path.normcase(state_file), mtime)
        if not force and stamp == state_stamp[0]: return
        state_stamp[0] = stamp
        active_state_file[0] = state_file
        data = {}
        if mtime >= 0:
            f = io.open(state_file, "r", encoding="utf-8")
            try: data = json.load(f)
            finally: f.close()
        merged = dict(DEFAULT_STATE)
        if isinstance(data, dict): merged.update(data)
        state_cache = merged
    except Exception as ex:
        Bukkit.getLogger().warning("[dimension-audit] state read: " + str(ex))


def _environment(world):
    try: return str(world.getEnvironment().name())
    except Exception: return "UNKNOWN"


def _is_closed_environment(environment):
    _reload_state(False)
    if environment == "NETHER": return not bool(state_cache.get("nether_enabled", False))
    if environment == "THE_END": return not bool(state_cache.get("end_enabled", False))
    return False


def _location_data(location):
    if location is None: return {}
    try:
        return {
            "world": location.getWorld().getName() if location.getWorld() else "UNKNOWN",
            "x": round(location.getX(), 2), "y": round(location.getY(), 2),
            "z": round(location.getZ(), 2),
        }
    except Exception: return {}


def _vehicle_data(player):
    try:
        vehicle = player.getVehicle()
    except Exception:
        vehicle = None
    if vehicle is not None:
        passengers = []
        try: passengers = [p.getName() if isinstance(p, Player) else str(p.getType().name())
                           for p in vehicle.getPassengers()]
        except Exception: pass
        return {"type": str(vehicle.getType().name()), "passengers": passengers,
                "live": True, "tick": now_tick()}
    old = vehicle_context.get(uid(player))
    if old and now_tick() - int(old.get("tick", 0)) <= 200:
        return dict(old)
    return {"type": "NONE", "passengers": [], "live": False, "tick": now_tick()}


def _append_audit(record):
    try:
        _ensure_data_dir()
        record["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        environment_names = {
            "NORMAL": u"обычный мир",
            "NETHER": u"Ад",
            "THE_END": u"Энд",
            "UNKNOWN": u"неизвестный мир",
        }
        method_names = {
            "PERIODIC_DETECTION": u"периодическая проверка",
            "WORLD_CHANGE": u"смена мира",
            "LOGIN_IN_CLOSED_DIMENSION": u"вход на сервер в закрытом измерении",
        }
        method = record.get("method", "UNKNOWN")
        if method.startswith("VEHICLE:"):
            vehicle_type = method.split(":", 1)[1]
            method_text = u"на транспорте ({0})".format(vehicle_type)
        elif method.startswith("TELEPORT:"):
            method_text = u"телепортация ({0})".format(method.split(":", 1)[1])
        else:
            method_text = method_names.get(method, unicode(method))

        from_env = environment_names.get(record.get("from_environment"),
                                         unicode(record.get("from_environment", "UNKNOWN")))
        to_env = environment_names.get(record.get("to_environment"),
                                       unicode(record.get("to_environment", "UNKNOWN")))
        location = record.get("location", {})
        line = (u"[{timestamp}] Игрок: {player} | Откуда: {from_env} ({from_world}) | "
                u"Куда: {to_env} ({to_world}) | Способ: {method} | "
                u"Координаты: {x}, {y}, {z}").format(
                    timestamp=record["timestamp"],
                    player=record.get("player", "UNKNOWN"),
                    from_env=from_env,
                    from_world=record.get("from_world", "UNKNOWN"),
                    to_env=to_env,
                    to_world=record.get("to_world", "UNKNOWN"),
                    method=method_text,
                    x=location.get("x", "?"), y=location.get("y", "?"),
                    z=location.get("z", "?"))
        f = io.open(AUDIT_FILE, "a", encoding="utf-8")
        try: f.write(line + u"\n")
        finally: f.close()
        Bukkit.getLogger().warning(
            u"[dimension-audit] {0} попал в {1}; способ: {2}".format(
                record.get("player", "UNKNOWN"), to_env, method_text))
    except Exception as ex:
        Bukkit.getLogger().warning("[dimension-audit] log write: " + str(ex))


def _audit_entry(player, from_world=None, detection="WORLD_CHANGE"):
    if player is None or not player.isOnline(): return False
    world = player.getWorld()
    env = _environment(world)
    if not _is_closed_environment(env):
        audit_seen.pop(uid(player), None)
        return False
    puid = uid(player)
    world_name = world.getName()
    if audit_seen.get(puid) == world_name: return False

    vehicle = _vehicle_data(player)
    teleport = recent_teleports.get(puid, {})
    age = now_tick() - int(teleport.get("tick", 0)) if teleport else 999999
    cause = teleport.get("cause", "UNKNOWN") if age <= 100 else "UNKNOWN"
    if vehicle.get("type") != "NONE":
        method = "VEHICLE:" + str(vehicle.get("type"))
    elif cause != "UNKNOWN":
        method = "TELEPORT:" + str(cause)
    else:
        method = detection

    record = {
        "event": "CLOSED_DIMENSION_ENTRY",
        "player": player.getName(), "uuid": puid,
        "from_world": from_world.getName() if from_world is not None else teleport.get("from_world", "UNKNOWN"),
        "from_environment": _environment(from_world) if from_world is not None else teleport.get("from_environment", "UNKNOWN"),
        "to_world": world_name, "to_environment": env,
        "location": _location_data(player.getLocation()),
        "method": method, "teleport_cause": cause,
        "vehicle": vehicle, "detection": detection,
        "portal_event_cancelled": bool(teleport.get("portal_cancelled", False)),
    }
    audit_seen[puid] = world_name
    _append_audit(record)
    return True


def on_player_portal(event):
    player = event.getPlayer()
    target = event.getTo()
    target_env = _environment(target.getWorld()) if target is not None else "UNKNOWN"
    try: cause = str(event.getCause().name())
    except Exception: cause = "UNKNOWN"
    # Some portal implementations do not expose the destination until after the
    # event. Keep the original WA behaviour by deriving it from the portal cause.
    if target_env == "UNKNOWN":
        if cause == "NETHER_PORTAL":
            target_env = "NETHER"
        elif cause == "END_PORTAL":
            target_env = "THE_END"
    closed = _is_closed_environment(target_env)
    recent_teleports[uid(player)] = {
        "tick": now_tick(), "cause": cause,
        "from_world": event.getFrom().getWorld().getName() if event.getFrom() else "UNKNOWN",
        "from_environment": _environment(event.getFrom().getWorld()) if event.getFrom() else "UNKNOWN",
        "to_environment": target_env, "portal_cancelled": closed,
    }
    if closed:
        event.setCancelled(True)
        if target_env == "NETHER": player.sendMessage(u"§cАд пока закрыт администрацией.")
        elif target_env == "THE_END": player.sendMessage(u"§cЭнд пока закрыт администрацией.")


def on_player_teleport(event):
    player = event.getPlayer()
    try: cause = str(event.getCause().name())
    except Exception: cause = "UNKNOWN"
    old = dict(recent_teleports.get(uid(player), {}))
    old.update({
        "tick": now_tick(), "cause": cause,
        "from_world": event.getFrom().getWorld().getName() if event.getFrom() else "UNKNOWN",
        "from_environment": _environment(event.getFrom().getWorld()) if event.getFrom() else "UNKNOWN",
        "to_environment": _environment(event.getTo().getWorld()) if event.getTo() else "UNKNOWN",
    })
    recent_teleports[uid(player)] = old


def on_world_change(event):
    _audit_entry(event.getPlayer(), event.getFrom(), "WORLD_CHANGE")


def on_join(event):
    _audit_entry(event.getPlayer(), None, "LOGIN_IN_CLOSED_DIMENSION")


def on_quit(event):
    puid = uid(event.getPlayer())
    audit_seen.pop(puid, None)
    recent_teleports.pop(puid, None)


def on_vehicle_enter(event):
    entered = event.getEntered()
    if not isinstance(entered, Player): return
    vehicle = event.getVehicle()
    vehicle_context[uid(entered)] = {
        "type": str(vehicle.getType().name()), "passengers": [entered.getName()],
        "live": True, "tick": now_tick(),
    }


def on_vehicle_exit(event):
    exited = event.getExited()
    if not isinstance(exited, Player): return
    ctx = dict(vehicle_context.get(uid(exited), {}))
    ctx.update({"type": str(event.getVehicle().getType().name()),
                "live": False, "tick": now_tick()})
    vehicle_context[uid(exited)] = ctx


def audit_tick():
    if not running[0]: return
    try:
        _reload_state(False)
        for player in Bukkit.getOnlinePlayers():
            _audit_entry(player, None, "PERIODIC_DETECTION")
        cutoff = now_tick() - 600
        for mapping in (recent_teleports, vehicle_context):
            for key, value in list(mapping.items()):
                if int(value.get("tick", 0)) < cutoff: mapping.pop(key, None)
    except Exception as ex:
        Bukkit.getLogger().warning("[dimension-audit] tick: " + str(ex))
    scheduler.runTaskLater(audit_tick, 20)


_reload_state(True)
listener_mgr.registerListener(on_player_portal, PlayerPortalEvent)
listener_mgr.registerListener(on_player_teleport, PlayerTeleportEvent)
listener_mgr.registerListener(on_world_change, PlayerChangedWorldEvent)
listener_mgr.registerListener(on_join, PlayerJoinEvent)
listener_mgr.registerListener(on_quit, PlayerQuitEvent)
listener_mgr.registerListener(on_vehicle_enter, VehicleEnterEvent)
listener_mgr.registerListener(on_vehicle_exit, VehicleExitEvent)
scheduler.runTaskLater(audit_tick, 20)
Bukkit.getLogger().info("[dimension-audit] Loaded. Log: " + AUDIT_FILE)
Bukkit.getLogger().info("[dimension-audit] State: " + active_state_file[0])


def stop(script=None):
    running[0] = False

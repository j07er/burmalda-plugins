# -*- coding: utf-8 -*-
"""
SmartY World Achievements — PySpigot 0.9.1 / Paper 1.21.11
Глобальный учёт достижений + прогрессивное расширение границы (×1.5, ceil)
"""

import json
import os
import sys

try:
    unicode
except NameError:
    unicode = str

try:
    if hasattr(sys, "setdefaultencoding"):
        reload(sys)
        sys.setdefaultencoding("utf-8")
except Exception:
    pass

from org.bukkit import Bukkit, ChatColor
from org.bukkit.entity import Player
from org.bukkit.event.player import PlayerAdvancementDoneEvent, PlayerPortalEvent
from org.bukkit.event import EventPriority, Listener
from org.bukkit.plugin import EventExecutor
from org.bukkit.event import HandlerList
from java.util import ArrayList
from java.lang import String as JavaString, StringBuilder

# ============================================================================
#  CONFIG
# ============================================================================

class PluginConfig(object):
    PLUGIN_NAME = u"SmartY-WorldAchievements"
    VERSION = u"1.1.0"
    PREFIX = u"&2&l[Граница]&r "
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    DATA_DIR = os.path.join(SCRIPT_DIR, "data")
    DATA_FILE = os.path.join(DATA_DIR, "world_achievements.json")
    DISABLED_BORDER_SIZE = 59999968.0

    DEFAULT_STATE = {
        "enabled": True,
        "base_size": 32.0,
        "nether_enabled": False,
        "end_enabled": False,
        "manual_adjustment": 0,
        "processed_advancements": []
    }

# ============================================================================
#  UTILS
# ============================================================================

def to_unicode(value):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    if isinstance(value, JavaString):
        try:
            return unicode(value.getBytes("UTF-8"), "utf-8")
        except Exception:
            pass
    if isinstance(value, str):
        try:
            return value.decode("utf-8")
        except Exception:
            try:
                return value.decode("cp1251")
            except Exception:
                return unicode(value, "utf-8", "ignore")
    return unicode(str(value))

def colorize(text):
    text = to_unicode(text)
    if not text:
        return u""
    try:
        return to_unicode(ChatColor.translateAlternateColorCodes('&', JavaString(text)))
    except Exception:
        return text

def send_message(target, text):
    msg = colorize(text)
    try:
        if target is not None:
            target.sendMessage(JavaString(msg))
        else:
            Bukkit.getConsoleSender().sendMessage(JavaString(msg))
    except Exception:
        print("[WorldAchievements] " + msg)

def log_info(text):
    Bukkit.getLogger().info("[WorldAchievements] " + to_unicode(text))

def java_list(values):
    lst = ArrayList()
    for v in values:
        lst.add(JavaString(to_unicode(v)))
    return lst

# ============================================================================
#  STORAGE
# ============================================================================

class JsonStorage(object):
    def __init__(self, path, defaults):
        self.path = path
        self.defaults = defaults

    def load(self):
        self.ensure_dir()
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                return self.merge_defaults(data)
            except Exception as e:
                log_info(u"Ошибка чтения данных: " + unicode(e))
        return self.merge_defaults({})

    def save(self, data):
        self.ensure_dir()
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except Exception:
                pass
        os.rename(tmp, self.path)

    def ensure_dir(self):
        d = os.path.dirname(self.path)
        if not os.path.exists(d):
            os.makedirs(d)

    def merge_defaults(self, data):
        merged = dict(self.defaults)
        if isinstance(data, dict):
            merged.update(data)
        return merged

# ============================================================================
#  STATE
# ============================================================================

class AdvancementState(object):
    def __init__(self, storage):
        self.storage = storage
        self.data = self.storage.load()
        self.processed = set(self.data.get("processed_advancements", []))

    def reload(self):
        self.data = self.storage.load()
        self.processed = set(self.data.get("processed_advancements", []))

    def save(self):
        self.data["processed_advancements"] = sorted(list(self.processed))
        self.storage.save(self.data)

    def is_enabled(self):
        return bool(self.data.get("enabled", True))

    def set_enabled(self, value):
        self.data["enabled"] = bool(value)
        self.save()

    def is_nether_enabled(self):
        return bool(self.data.get("nether_enabled", False))

    def set_nether_enabled(self, value):
        self.data["nether_enabled"] = bool(value)
        self.save()

    def is_end_enabled(self):
        return bool(self.data.get("end_enabled", False))

    def set_end_enabled(self, value):
        self.data["end_enabled"] = bool(value)
        self.save()

    def get_base_size(self):
        return float(self.data.get("base_size", 32.0))

    def get_manual_adjustment(self):
        try:
            return int(self.data.get("manual_adjustment", 0))
        except Exception:
            return 0

    def set_manual_adjustment(self, value):
        self.data["manual_adjustment"] = int(value)
        self.save()

    # ==================== НОВАЯ ПРОГРЕССИВНАЯ ФОРМУЛА ====================
    def get_step_for_index(self, index):
        """Прирост радиуса для n-го достижения (начиная с 0)"""
        if index <= 0:
            return 1
        prev = self.get_step_for_index(index - 1)
        return int((prev * 1.5) + 0.999)   # ceil

    def get_total_steps(self):
        return max(0, len(self.processed) + self.get_manual_adjustment())

    def get_border_size(self):
        if not self.is_enabled():
            return PluginConfig.DISABLED_BORDER_SIZE

        steps = self.get_total_steps()
        total = self.get_base_size()
        manual = self.get_manual_adjustment()

        for i in range(steps):
            total += self.get_step_for_index(i)

        total += manual
        return max(1.0, total)

    def mark_advancement(self, advancement_key):
        """Глобальный учёт (одно достижение = один шаг)"""
        key = to_unicode(advancement_key)
        if key in self.processed:
            return False
        self.processed.add(key)
        self.save()
        return True

# ============================================================================
#  BORDER SERVICE
# ============================================================================

class WorldBorderService(object):
    def __init__(self, state):
        self.state = state

    def apply(self):
        worlds = self.get_target_worlds()
        if not worlds:
            return
        size = self.state.get_border_size() if self.state.is_enabled() else PluginConfig.DISABLED_BORDER_SIZE
        for world in worlds:
            border = world.getWorldBorder()
            spawn = world.getSpawnLocation()
            border.setCenter(spawn.getX(), spawn.getZ())
            border.setSize(float(size))

    def get_target_worlds(self):
        names = self.state.data.get("target_worlds", [])
        if names:
            result = []
            for name in names:
                w = Bukkit.getWorld(JavaString(name))
                if w is not None:
                    result.append(w)
            return result

        for world in Bukkit.getWorlds():
            try:
                if str(world.getEnvironment().name()) == "NORMAL":
                    return [world]
            except Exception:
                pass
        return list(Bukkit.getWorlds())[:1]

# ============================================================================
#  SERVICES
# ============================================================================

class AdvancementService(object):
    def __init__(self, state, border_service):
        self.state = state
        self.border_service = border_service

    def handle_done(self, event):
        if not self.state.is_enabled():
            return

        try:
            adv = event.getAdvancement()
            key = to_unicode(adv.getKey().toString())
        except Exception:
            return

        if key.startswith(u"minecraft:recipes/"):
            return

        if not self.state.mark_advancement(key):
            return

        self.border_service.apply()

        new_size = self.state.get_border_size()
        player = event.getPlayer()
        send_message(player, PluginConfig.PREFIX + u"&aМир расширился! &7Новый радиус: &e{0:.0f}".format(new_size))
        log_info(u"Advancement: {0} → border = {1:.0f}".format(key, new_size))

class PortalAccessService(object):
    def __init__(self, state):
        self.state = state

    def handle_portal(self, event):
        env = self._get_environment(event)
        if env == "NETHER" and not self.state.is_nether_enabled():
            self._cancel(event, u"&cАд пока закрыт администрацией.")
        elif env == "THE_END" and not self.state.is_end_enabled():
            self._cancel(event, u"&cЭнд пока закрыт администрацией.")

    def _get_environment(self, event):
        try:
            to = event.getTo()
            if to is not None and to.getWorld() is not None:
                return str(to.getWorld().getEnvironment().name())
        except Exception:
            pass
        try:
            cause = str(event.getCause().name())
            if cause == "NETHER_PORTAL":
                return "NETHER"
            if cause == "END_PORTAL":
                return "THE_END"
        except Exception:
            pass
        return ""

    def _cancel(self, event, message):
        try:
            event.setCancelled(True)
        except Exception:
            pass
        try:
            send_message(event.getPlayer(), PluginConfig.PREFIX + message)
        except Exception:
            pass

# ============================================================================
#  COMMAND HANDLER
# ============================================================================

class WorldAchievementsCommand(object):
    def __init__(self, state, border_service):
        self.state = state
        self.border_service = border_service

    def execute(self, sender, label, args):
        if not self._is_admin(sender):
            send_message(sender, PluginConfig.PREFIX + u"&cКоманда доступна только операторам.")
            return True

        args = list(args)
        sub = args[0].lower() if args else "status"

        if sub == "status":
            self._send_status(sender)
        elif sub == "add":
            self._adjust(sender, args, 1)
        elif sub in ("remove", "take"):
            self._adjust(sender, args, -1)
        elif sub == "on":
            self.state.set_enabled(True)
            self.border_service.apply()
            send_message(sender, PluginConfig.PREFIX + u"&aГраницы включены.")
        elif sub == "off":
            self.state.set_enabled(False)
            self.border_service.apply()
            send_message(sender, PluginConfig.PREFIX + u"&eГраницы отключены.")
        elif sub == "nether":
            self._toggle_dimension(sender, args, "nether")
        elif sub == "end":
            self._toggle_dimension(sender, args, "end")
        elif sub == "reload":
            self.state.reload()
            self.border_service.apply()
            send_message(sender, PluginConfig.PREFIX + u"&aДанные перезагружены.")
        elif sub == "apply":
            self.border_service.apply()
            send_message(sender, PluginConfig.PREFIX + u"&aГраница применена.")
        else:
            self._send_help(sender, label)
        return True

    def tab_complete(self, sender, alias, args):
        args = list(args)
        if len(args) == 1:
            cmds = ["status", "add", "remove", "on", "off", "nether", "end", "reload", "apply"]
            prefix = args[0].lower()
            return java_list([c for c in cmds if c.startswith(prefix)])
        if len(args) == 2 and args[0].lower() in ("add", "remove", "take"):
            return java_list(["1", "2", "5", "10"])
        if len(args) == 2 and args[0].lower() in ("nether", "end"):
            return java_list(["on", "off", "status"])
        return java_list([])

    def _adjust(self, sender, args, direction):
        amount = 1
        if len(args) > 1:
            try:
                amount = max(1, int(args[1]))
            except Exception:
                amount = 1

        current = self.state.get_manual_adjustment()
        self.state.set_manual_adjustment(current + (amount * direction))
        self.border_service.apply()

        action = u"расширена" if direction > 0 else u"уменьшена"
        send_message(sender, PluginConfig.PREFIX +
                     u"&aГраница {0}. &7Размер: &e{1:.0f}".format(action, self.state.get_border_size()))

    def _toggle_dimension(self, sender, args, dimension):
        action = args[1].lower() if len(args) > 1 else "status"
        if action in ("on", "open"):
            if dimension == "nether":
                self.state.set_nether_enabled(True)
            else:
                self.state.set_end_enabled(True)
        elif action in ("off", "close"):
            if dimension == "nether":
                self.state.set_nether_enabled(False)
            else:
                self.state.set_end_enabled(False)
        elif action != "status":
            send_message(sender, PluginConfig.PREFIX + u"&7/wa {0} <on|off|status>".format(dimension))
            return

        name = u"Ад" if dimension == "nether" else u"Энд"
        enabled = self.state.is_nether_enabled() if dimension == "nether" else self.state.is_end_enabled()
        status = u"&aоткрыт" if enabled else u"&cзакрыт"
        send_message(sender, PluginConfig.PREFIX + u"&7{0}: {1}&7.".format(name, status))

    def _send_status(self, sender):
        size = self.state.get_border_size()
        send_message(sender, PluginConfig.PREFIX + u"&7Статус: {0}".format(
            u"&aвключено" if self.state.is_enabled() else u"&cвыключено"))
        send_message(sender, u"&7Достижений учтено: &e{0}".format(len(self.state.processed)))
        send_message(sender, u"&7Ручная поправка: &e{0}".format(self.state.get_manual_adjustment()))
        send_message(sender, u"&7Размер границы: &e{0:.0f}".format(size))
        send_message(sender, u"&7Ад: {0} &8| &7Энд: {1}".format(
            u"&aоткрыт" if self.state.is_nether_enabled() else u"&cзакрыт",
            u"&aоткрыт" if self.state.is_end_enabled() else u"&cзакрыт"))

    def _send_help(self, sender, label):
        send_message(sender, PluginConfig.PREFIX + u"&7/{0} status".format(label))
        send_message(sender, u"&7/{0} add/remove [кол-во]".format(label))
        send_message(sender, u"&7/{0} on|off".format(label))
        send_message(sender, u"&7/{0} nether/end <on|off>".format(label))
        send_message(sender, u"&7/{0} reload|apply".format(label))

    def _is_admin(self, sender):
        if sender is None:
            return True
        try:
            return sender.isOp() or sender.hasPermission("smarty.worldachievements.admin")
        except Exception:
            return False

# ============================================================================
#  REGISTRATION
# ============================================================================

registered_listeners = []
state = None
border_service = None
advancement_service = None
portal_service = None
command_handler = None
initialized = False

def register_event(event_class, handler):
    if event_class is None:
        return False
    plugin = Bukkit.getPluginManager().getPlugin("PySpigot")
    if plugin is None:
        return False

    class DirectListener(Listener):
        pass

    class DirectExecutor(EventExecutor):
        def execute(self, listener, event):
            try:
                handler(event)
            except Exception as e:
                log_info(u"Event error: " + unicode(e))

    listener = DirectListener()
    Bukkit.getPluginManager().registerEvent(
        event_class, listener, EventPriority.HIGHEST, DirectExecutor(), plugin, True
    )
    registered_listeners.append(listener)
    return True

def unregister_events():
    for listener in list(registered_listeners):
        try:
            HandlerList.unregisterAll(listener)
        except Exception:
            pass
    del registered_listeners[:]

def force_register_command():
    from org.bukkit.command import Command, TabCompleter

    class PyCommand(Command, TabCompleter):
        def __init__(self):
            Command.__init__(self, "worldachievements", "", "", ["wa", "achborder", "worldborderachievements"])

        def execute(self, sender, label, args):
            return command_handler.execute(sender, label, list(args))

        def tabComplete(self, sender, alias, args):
            return command_handler.tab_complete(sender, alias, list(args))

        def onTabComplete(self, sender, alias, args):
            return self.tabComplete(sender, alias, args)

    cmd = PyCommand()
    server = Bukkit.getServer()
    cmd_map = server.getCommandMap()
    known = cmd_map.getKnownCommands()

    for name in ["worldachievements", "wa", "achborder", "worldborderachievements"]:
        try:
            old = known.get(name)
            if old and hasattr(old, "unregister"):
                old.unregister(cmd_map)
            known.remove(name)
        except Exception:
            pass

    known.put("worldachievements", cmd)
    known.put("wa", cmd)
    known.put("achborder", cmd)
    known.put("worldborderachievements", cmd)

def force_unregister_command():
    """Снимает /worldachievements и все алиасы из Bukkit CommandMap. Без этого
    команда остаётся рабочей даже после /pyspigot unload, т.к. она была внедрена
    напрямую рефлексией, в обход command_manager PySpigot."""
    try:
        server = Bukkit.getServer()
        cmd_map = server.getCommandMap()
        known = cmd_map.getKnownCommands()
        for name in ["worldachievements", "wa", "achborder", "worldborderachievements"]:
            try:
                old = known.get(name)
                if old and hasattr(old, "unregister"):
                    old.unregister(cmd_map)
                known.remove(name)
            except Exception:
                pass
        if hasattr(server, "syncCommands"):
            server.syncCommands()
    except Exception as e:
        log_info(u"Command unregistration error: " + unicode(e))

def on_enable():
    global state, border_service, advancement_service, portal_service, command_handler, initialized

    if initialized:
        return

    log_info(u"Starting SmartY-WorldAchievements v1.1.0 (прогрессивное расширение ×1.5)")

    storage = JsonStorage(PluginConfig.DATA_FILE, PluginConfig.DEFAULT_STATE)
    state = AdvancementState(storage)
    state.save()

    border_service = WorldBorderService(state)
    advancement_service = AdvancementService(state, border_service)
    portal_service = PortalAccessService(state)
    command_handler = WorldAchievementsCommand(state, border_service)

    unregister_events()
    register_event(PlayerAdvancementDoneEvent, advancement_service.handle_done)
    register_event(PlayerPortalEvent, portal_service.handle_portal)

    force_register_command()
    border_service.apply()

    initialized = True
    log_info(u"Loaded. Current border size: {0:.0f}".format(state.get_border_size()))

def on_disable():
    global initialized
    unregister_events()
    force_unregister_command()
    if state is not None:
        state.save()
    initialized = False
    log_info(u"Disabled.")

def start(script=None):
    on_enable()

def stop(script=None):
    on_disable()

if __name__ == "__main__" or "ps" in globals():
    on_enable()

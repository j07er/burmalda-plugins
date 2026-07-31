# -*- coding: utf-8 -*-
"""
===============================================================================
SmartY-HiddenMode — Персональный скрытый режим для избранных игроков
Для PySpigot 0.9.1 (Jython 2.7) + Paper 1.21.11
===============================================================================
Команда:
  /hidden         — Переключить скрытый режим (см. логику ниже)
  /hidden status  — Посмотреть текущее состояние (только для себя)

Доступно ТОЛЬКО никам из ALLOWED_NAMES (см. ниже), регистр ника не важен.

Логика (по ТЗ):
  1. Игрок пишет /hidden, пока он НЕ скрыт в этой сессии (зашёл как обычно).
     -> Скрытый режим "взводится" на будущее: ничего не меняется в текущей
        сессии (он уже зашёл и все это видели), но на СЛЕДУЮЩИЙ вход он
        зайдёт незаметно (никто не увидит присоединение, будет невидим в Tab
        и в мире, чат не будет отправляться).
  2. Игрок заходит на сервер, когда флаг взведён -> вход абсолютно тихий:
     нет сообщения "X присоединился к игре", игрок невидим в Tab-листе и в
     мире для всех, кроме операторов (/op), его сообщения в чате никуда не
     уходят (даже ему самому не показываются - выглядит как будто чат не
     работает, чтобы не спалиться).
  3. Игрок пишет /hidden, ПОКА он скрыт в текущей сессии.
     -> Это "разоблачение": он становится видимым прямо сейчас (Tab + мир),
        всем в чат отправляется сообщение "X присоединился к игре" (как будто
        он только что зашёл), чат для него снова работает, и флаг на будущее
        сбрасывается (следующий вход будет обычным).
===============================================================================
"""

import os
import json
import time

# Совместимость unicode в Python 2 (Jython) и Python 3
try:
    unicode
except NameError:
    unicode = str

# Выставляем кодировку UTF-8 в Jython
import sys
try:
    if hasattr(sys, "setdefaultencoding"):
        reload(sys)
        sys.setdefaultencoding("utf-8")
except Exception:
    pass

# -----------------------------------------------------------------------------
# ИМПОРТ BUKKIT / PYSPIGOT / JAVA
# -----------------------------------------------------------------------------
try:
    import pyspigot as ps
    cmd_mgr = ps.command_manager()
    listener_mgr = ps.listener_manager()
    PYSPIGOT_AVAILABLE = True
except Exception:
    PYSPIGOT_AVAILABLE = False
    cmd_mgr = None
    listener_mgr = None

try:
    from org.bukkit import Bukkit, ChatColor
    from org.bukkit.entity import Player
    from org.bukkit.event.player import PlayerJoinEvent, PlayerQuitEvent
    try:
        from org.bukkit.event.player import AsyncPlayerChatEvent
    except ImportError:
        AsyncPlayerChatEvent = None
    BUKKIT_AVAILABLE = True
except ImportError:
    BUKKIT_AVAILABLE = False
    ChatColor = None
    Player = object
    PlayerJoinEvent = None
    PlayerQuitEvent = None
    AsyncPlayerChatEvent = None

try:
    from java.lang import String as JavaString, StringBuilder
    JAVA_STRING_AVAILABLE = True
except ImportError:
    JAVA_STRING_AVAILABLE = False
    JavaString = str
    StringBuilder = None


# -----------------------------------------------------------------------------
# КОНФИГУРАЦИЯ: КОМУ ДОСТУПЕН СКРЫТЫЙ РЕЖИМ
# -----------------------------------------------------------------------------
# ФИКС по ТЗ: "dramo_smarty" может быть введён с любым регистром в игре -
# сравнение всегда идёт по .lower(), поэтому храним список тоже в нижнем регистре.
ALLOWED_NAMES = set([u"blueredtronce", u"dramo_smarty"])

PLUGIN_NAME = u"SmartY-HiddenMode"
VERSION = u"1.0.0"
PREFIX = u"&8[&7Hidden&8]&r "


# -----------------------------------------------------------------------------
# ПУТИ К ФАЙЛУ ДАННЫХ
# -----------------------------------------------------------------------------
def get_script_dir():
    if "__file__" in globals() and __file__:
        try:
            return os.path.dirname(os.path.abspath(__file__))
        except Exception:
            pass
    cwd = os.getcwd()
    pyspigot_path = os.path.join(cwd, "plugins", "PySpigot", "scripts")
    if os.path.exists(pyspigot_path):
        return pyspigot_path
    return cwd


SCRIPT_DIR = get_script_dir()
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "hidden_mode.json")


# -----------------------------------------------------------------------------
# ХЕЛПЕРЫ UNICODE / ЦВЕТА / СООБЩЕНИЙ
# -----------------------------------------------------------------------------
def to_unicode(text):
    if text is None:
        return u""
    if isinstance(text, unicode):
        return text
    if JAVA_STRING_AVAILABLE and hasattr(text, "getBytes"):
        try:
            utf8_bytes = text.getBytes("UTF-8")
            return unicode(utf8_bytes, "utf-8")
        except Exception:
            pass
    if isinstance(text, str):
        try:
            return text.decode("utf-8")
        except Exception:
            return unicode(text)
    return unicode(text)


def to_java_string(text):
    if text is None:
        return JavaString("") if JAVA_STRING_AVAILABLE else u""
    if JAVA_STRING_AVAILABLE:
        if isinstance(text, JavaString):
            return text
        u_text = to_unicode(text)
        if StringBuilder is not None:
            try:
                sb = StringBuilder()
                for ch in u_text:
                    sb.appendCodePoint(ord(ch))
                return sb.toString()
            except Exception:
                pass
        try:
            return JavaString(u_text.encode("utf-8"), "UTF-8")
        except Exception:
            return JavaString(u_text)
    return to_unicode(text)


def colorize(text):
    if not text:
        return u""
    u_text = to_unicode(text)
    if BUKKIT_AVAILABLE and ChatColor is not None:
        j_str = to_java_string(u_text)
        res = ChatColor.translateAlternateColorCodes('&', j_str)
        return to_unicode(res)
    return u_text


def send_message(target, text):
    if target is None:
        return
    try:
        target.sendMessage(to_java_string(colorize(text)))
    except Exception:
        try:
            target.sendMessage(colorize(text))
        except Exception:
            pass


def broadcast_message(text):
    if not BUKKIT_AVAILABLE:
        return
    colored = colorize(text)
    for p in Bukkit.getOnlinePlayers():
        send_message(p, colored)


def log_info(text):
    # ФИКС: Windows-консоль (cp866) - только ASCII в Bukkit.getLogger().
    if BUKKIT_AVAILABLE:
        try:
            Bukkit.getLogger().info("[SmartY-HiddenMode] " + str(text))
        except Exception:
            pass


def log_error(text):
    if BUKKIT_AVAILABLE:
        try:
            Bukkit.getLogger().warning("[SmartY-HiddenMode] [ERROR] " + str(text))
        except Exception:
            pass


def get_pyspigot_plugin():
    if not BUKKIT_AVAILABLE:
        return None
    try:
        pm = Bukkit.getPluginManager()
        plugin = pm.getPlugin("PySpigot")
        if plugin:
            return plugin
        for p in pm.getPlugins():
            if "pyspigot" in str(p.getName()).lower():
                return p
        plugins = pm.getPlugins()
        if len(plugins) > 0:
            return plugins[0]
    except Exception:
        pass
    return None


def uid(player):
    try:
        return str(player.getUniqueId())
    except Exception:
        return None


def is_allowed_name(name):
    if not name:
        return False
    return to_unicode(name).lower() in ALLOWED_NAMES


def is_admin_viewer(player):
    """Операторы (/op) видят скрытого игрока в Tab и в мире, как и было запрошено."""
    try:
        return bool(player.isOp())
    except Exception:
        return False


# -----------------------------------------------------------------------------
# ПЕРСИСТЕНТНОЕ ХРАНИЛИЩЕ ФЛАГА "СКРЫВАТЬСЯ ПРИ СЛЕДУЮЩЕМ ВХОДЕ"
# -----------------------------------------------------------------------------
class HiddenModeStorage(object):
    """
    Хранит per-UUID персистентный флаг enabled (bool) + последний известный
    ник (для удобства чтения файла человеком). Переживает рестарт сервера
    и перезагрузку скрипта - в отличие от active_hidden_sessions (см. ниже),
    которое живёт только в памяти текущего запуска JVM.
    """
    def __init__(self):
        self.data = {}
        self.load()

    def load(self):
        self.data = {}
        if not os.path.exists(DATA_FILE):
            return
        try:
            with open(DATA_FILE, "r") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    self.data = raw
        except Exception as e:
            log_error(u"Failed to read hidden_mode.json: {0}".format(e))

    def save(self):
        try:
            if not os.path.exists(DATA_DIR):
                os.makedirs(DATA_DIR)
            temp_file = DATA_FILE + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            if hasattr(os, "replace"):
                os.replace(temp_file, DATA_FILE)
            else:
                if os.path.exists(DATA_FILE):
                    try:
                        os.remove(DATA_FILE)
                    except Exception:
                        pass
                os.rename(temp_file, DATA_FILE)
        except Exception as e:
            log_error(u"Failed to save hidden_mode.json: {0}".format(e))

    def is_armed(self, uuid_str):
        entry = self.data.get(uuid_str)
        if not entry:
            return False
        return bool(entry.get("enabled", False))

    def set_armed(self, uuid_str, name, enabled):
        self.data[uuid_str] = {
            "enabled": bool(enabled),
            "name": to_unicode(name),
            "updated_at": int(time.time())
        }
        self.save()


storage = HiddenModeStorage()

# Набор UUID тех, кто СЕЙЧАС (в текущей сессии, только в памяти) реально
# невидим - заполняется на PlayerJoinEvent, если на момент входа флаг был
# взведён. Сбрасывается на выход/при перезагрузке скрипта (что нормально -
# персистентный флаг storage переживёт рестарт и снова спрячет при заходе).
active_hidden_sessions = set()


# -----------------------------------------------------------------------------
# ВИЗУАЛЬНОЕ СКРЫТИЕ / ПОКАЗ ИГРОКА (Tab + мир одним вызовом hidePlayer)
# -----------------------------------------------------------------------------
def _hide_from_viewer(viewer, target, plugin):
    try:
        viewer.hidePlayer(plugin, target)
    except TypeError:
        try:
            viewer.hidePlayer(target)
        except Exception:
            pass
    except Exception:
        pass


def _show_to_viewer(viewer, target, plugin):
    try:
        viewer.showPlayer(plugin, target)
    except TypeError:
        try:
            viewer.showPlayer(target)
        except Exception:
            pass
    except Exception:
        pass


def hide_player_from_everyone(hidden_player):
    """Скрывает hidden_player от всех текущих онлайн-игроков, кроме операторов."""
    if not BUKKIT_AVAILABLE:
        return
    plugin = get_pyspigot_plugin()
    for viewer in Bukkit.getOnlinePlayers():
        if viewer == hidden_player:
            continue
        if is_admin_viewer(viewer):
            continue
        _hide_from_viewer(viewer, hidden_player, plugin)


def show_player_to_everyone(revealed_player):
    """Показывает revealed_player всем игрокам (используется при /hidden-разоблачении)."""
    if not BUKKIT_AVAILABLE:
        return
    plugin = get_pyspigot_plugin()
    for viewer in Bukkit.getOnlinePlayers():
        if viewer == revealed_player:
            continue
        _show_to_viewer(viewer, revealed_player, plugin)


def hide_all_active_sessions_from(new_viewer):
    """
    Вызывается при входе ЛЮБОГО игрока (кроме самих скрытых): все, кто сейчас
    активно скрыт (active_hidden_sessions), должны остаться невидимыми и для
    только что зашедшего нового игрока, если только он не оператор.
    """
    if not BUKKIT_AVAILABLE or is_admin_viewer(new_viewer):
        return
    plugin = get_pyspigot_plugin()
    for hidden_uuid in list(active_hidden_sessions):
        # Ищем игрока перебором онлайн-списка (проще и надёжнее, чем
        # конвертировать строковый UUID обратно в java.util.UUID вручную).
        hidden_player = None
        for p in Bukkit.getOnlinePlayers():
            if uid(p) == hidden_uuid:
                hidden_player = p
                break
        if hidden_player is not None and hidden_player != new_viewer:
            _hide_from_viewer(new_viewer, hidden_player, plugin)


# -----------------------------------------------------------------------------
# ОБРАБОТЧИКИ СОБЫТИЙ (диспетчер - один листенер на тип события в скрипте)
# -----------------------------------------------------------------------------
def on_player_join(event):
    try:
        player = event.getPlayer()
        if player is None:
            return
        name = player.getName()
        u_id = uid(player)

        if is_allowed_name(name) and u_id:
            if storage.is_armed(u_id):
                # ФИКС по ТЗ: тихий вход - никто не видит "X присоединился к игре",
                # игрок невидим в Tab/мире для всех, кроме операторов.
                active_hidden_sessions.add(u_id)
                event.setJoinMessage(None)
                hide_player_from_everyone(player)
                send_message(player, PREFIX + u"&7Вы вошли в &8скрытом &7режиме. Никто не увидит ваш вход.")
                log_info("Player joined in hidden mode (silent, UUID hidden from log for privacy).")
                return
            # Флаг не взведён - обычный вход, ничего не делаем.

        # Обычный игрок (или разрешённый игрок с выключенным флагом) - прячем
        # от него всех, кто СЕЙЧАС активно скрыт, если он сам не оператор.
        hide_all_active_sessions_from(player)

    except Exception as e:
        log_error("Error in on_player_join: {0}".format(e))


def on_player_quit(event):
    try:
        player = event.getPlayer()
        if player is None:
            return
        u_id = uid(player)
        if u_id and u_id in active_hidden_sessions:
            # ФИКС по ТЗ: выход скрытого игрока тоже никто не видит.
            event.setQuitMessage(None)
            active_hidden_sessions.discard(u_id)
    except Exception as e:
        log_error("Error in on_player_quit: {0}".format(e))


def on_player_chat(event):
    try:
        player = event.getPlayer()
        if player is None:
            return
        u_id = uid(player)
        if u_id and u_id in active_hidden_sessions:
            # ФИКС по ТЗ: сообщение полностью пропадает, даже для самого
            # отправителя - выглядит как будто чат сломан, чтобы не спалиться.
            event.setCancelled(True)
    except Exception as e:
        log_error("Error in on_player_chat: {0}".format(e))


# -----------------------------------------------------------------------------
# КОМАНДА /hidden
# -----------------------------------------------------------------------------
def cmd_hidden(sender, label, args):
    if not isinstance(sender, Player):
        send_message(sender, u"Команда доступна только игрокам.")
        return True

    name = sender.getName()
    if not is_allowed_name(name):
        send_message(sender, PREFIX + u"&cУ вас нет доступа к этой команде.")
        return True

    u_id = uid(sender)
    if not u_id:
        return True

    args_list = list(args) if args else []
    sub = to_unicode(args_list[0]).lower() if args_list else u""

    if sub == u"status":
        armed = storage.is_armed(u_id)
        active_now = u_id in active_hidden_sessions
        send_message(sender, PREFIX + u"&7Скрытый режим на будущие входы: " +
                     (u"&aВКЛ" if armed else u"&cВЫКЛ"))
        send_message(sender, PREFIX + u"&7Сейчас вы: " +
                     (u"&8невидимы" if active_now else u"&aвидимы всем"))
        return True

    # --- Переключение (без аргументов) ---
    if u_id in active_hidden_sessions:
        # ФИКС по ТЗ: разоблачение прямо сейчас - показать всем, разослать
        # фейковое сообщение о входе, снова разрешить чат, снять флаг на будущее.
        active_hidden_sessions.discard(u_id)
        storage.set_armed(u_id, name, False)
        show_player_to_everyone(sender)
        broadcast_message(u"&e{0} присоединился к игре".format(to_unicode(sender.getName())))
        send_message(sender, PREFIX + u"&7Скрытый режим &cотключён&7. Вы снова видны всем.")
    else:
        # Текущая сессия визуально не менялась - просто взводим/снимаем флаг
        # на СЛЕДУЮЩИЙ вход, ничего не показываем остальным игрокам.
        currently_armed = storage.is_armed(u_id)
        new_state = not currently_armed
        storage.set_armed(u_id, name, new_state)
        if new_state:
            send_message(sender, PREFIX + u"&7Скрытый режим &aвключён&7 для следующего входа. " +
                         u"Текущая сессия не изменится.")
        else:
            send_message(sender, PREFIX + u"&7Скрытый режим &cвыключен&7 для следующего входа.")

    return True


def tab_hidden(sender, alias, args):
    args_list = list(args) if args else []
    if len(args_list) <= 1:
        prefix = to_unicode(args_list[0]).lower() if args_list else u""
        return [item for item in ["status"] if item.startswith(prefix)]
    return []


# -----------------------------------------------------------------------------
# РЕГИСТРАЦИЯ / ЗАПУСК / ОСТАНОВКА
# -----------------------------------------------------------------------------
def register_listeners():
    if not PYSPIGOT_AVAILABLE or not BUKKIT_AVAILABLE:
        return
    if PlayerJoinEvent is not None:
        listener_mgr.registerListener(on_player_join, PlayerJoinEvent)
    if PlayerQuitEvent is not None:
        listener_mgr.registerListener(on_player_quit, PlayerQuitEvent)
    if AsyncPlayerChatEvent is not None:
        listener_mgr.registerListener(on_player_chat, AsyncPlayerChatEvent)


def register_commands():
    if not PYSPIGOT_AVAILABLE:
        return
    cmd_mgr.registerCommand(cmd_hidden, tab_hidden, "hidden", "Toggle personal hidden mode", "/hidden [status]", [])


def on_enable():
    log_info("Starting SmartY-HiddenMode v{0}".format(VERSION))
    storage.load()
    register_listeners()
    register_commands()
    log_info("Enabled. Allowed players count: {0}".format(len(ALLOWED_NAMES)))


def on_disable():
    log_info("Disabling SmartY-HiddenMode")
    # На выгрузку скрипта - на всякий случай возвращаем видимость всем, кто
    # был активно скрыт в этой сессии, чтобы никто не остался невидимым
    # навечно из-за выгрузки/удаления этого скрипта.
    if BUKKIT_AVAILABLE:
        for u_id in list(active_hidden_sessions):
            for p in Bukkit.getOnlinePlayers():
                if uid(p) == u_id:
                    show_player_to_everyone(p)
                    break
    active_hidden_sessions.clear()
    # Команды и listeners этого скрипта зарегистрированы ТОЛЬКО через штатные
    # cmd_mgr/listener_mgr PySpigot, поэтому их снятие PySpigot делает сам -
    # здесь ничего дополнительно снимать не нужно.


def start(script=None):
    on_enable()


def stop(script=None):
    # ВАЖНО: PySpigot вызывает автоматически именно stop() (не on_disable())
    # при /pyspigot unload <script>. Без этой функции on_disable() никогда бы
    # не выполнился при ручной выгрузке, и скрытые игроки рисковали остаться
    # невидимыми даже после удаления скрипта.
    on_disable()



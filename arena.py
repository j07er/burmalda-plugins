# -*- coding: utf-8 -*-
"""
===============================================================================
PySpigot Arena PvP Rating System — ВЕРСИЯ 3.7.0 (UNICODE STRINGS & STRINGBUILDER FIX)
===============================================================================
Команды арены:
  /arena                        — Открыть графическое Chest GUI меню арены
  /arena request <ник> <ставка> — Вызвать игрока на PvP дуэль
  /arena accept [ник]           — Принять вызов на дуэль
  /arena deny [ник]             — Отклонить вызов на дуэль
  /arena stats                  — Просмотреть свою статистику и ELO
  /arena profile <ник>          — Просмотреть профиль любого игрока
  /arena top                    — Просмотреть Топ-10 игроков сервера по ELO
  /arena resetelo <ник>         — Сбросить ELO игрока до 1000 (Только /op)
  /arena setspawn <p1|p2|spec>  — Установить точки спавна арены (Только /op)
  /arena reload                 — Перезагрузить конфиг и данные (Только /op)
===============================================================================
"""

import os
import sys
import json
import time
import re

# Совместимость unicode в Python 2 (Jython) и Python 3
try:
    unicode
except NameError:
    unicode = str

# Выставляем кодировку UTF-8 в Jython
try:
    if hasattr(sys, "setdefaultencoding"):
        reload(sys)
        sys.setdefaultencoding("utf-8")
except Exception:
    pass

# -----------------------------------------------------------------------------
# ИМПОРТ BUKKIT / PYSPIGOT / JAVA ARRAYLIST / STRINGBUILDER
# -----------------------------------------------------------------------------
try:
    from org.bukkit import Bukkit, ChatColor, Sound, Location, Material, GameMode
    from org.bukkit.entity import Player
    from org.bukkit.util import Vector
    from org.bukkit.command import Command, TabCompleter
    from org.bukkit.inventory import Inventory, ItemStack
    from org.bukkit.inventory.meta import ItemMeta, SkullMeta
    from org.bukkit.event import Listener, EventPriority
    from org.bukkit.plugin import EventExecutor
    from org.bukkit.event.player import PlayerJoinEvent, PlayerQuitEvent, PlayerRespawnEvent, PlayerMoveEvent
    from org.bukkit.event.entity import PlayerDeathEvent, EntityDamageEvent
    from org.bukkit.event.inventory import InventoryClickEvent
    BUKKIT_AVAILABLE = True
except ImportError:
    BUKKIT_AVAILABLE = False
    Command = object
    TabCompleter = object
    Location = None
    GameMode = None
    Player = object
    Vector = object
    Material = None
    Inventory = None
    ItemStack = None
    Listener = object
    EventPriority = None
    EventExecutor = object
    PlayerMoveEvent = None
    EntityDamageEvent = None
    PlayerDeathEvent = None
    PlayerRespawnEvent = None
    PlayerQuitEvent = None
    InventoryClickEvent = None

try:
    from java.lang import String as JavaString, StringBuilder, Runnable, System, Throwable
    from java.util import UUID as JavaUUID
    JAVA_STRING_AVAILABLE = True
except ImportError:
    JAVA_STRING_AVAILABLE = False
    JavaString = str
    StringBuilder = None
    Runnable = object
    System = None
    JavaUUID = None
    Throwable = Exception

try:
    from java.util import ArrayList
except ImportError:
    ArrayList = list

try:
    from net.kyori.adventure.text.serializer.legacy import LegacyComponentSerializer
    ADVENTURE_AVAILABLE = True
except ImportError:
    ADVENTURE_AVAILABLE = False


# -----------------------------------------------------------------------------
# 100% БЕЗОПАСНАЯ КОНВЕРТАЦИЯ СТРОК ЧЕРЕЗ JAVA STRINGBUILDER.APPENDCODEPOINT
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


def to_unicode(text):
    if text is None:
        return u""
    if isinstance(text, unicode):
        return text

    if JAVA_STRING_AVAILABLE and hasattr(text, "getBytes"):
        try:
            utf8_bytes = text.getBytes("UTF-8")
            return unicode(utf8_bytes, "utf-8")
        except:
            pass

    if isinstance(text, str):
        try:
            return text.decode("utf-8")
        except:
            try:
                return text.decode("cp1251")
            except:
                return unicode(text, "utf-8", "ignore")

    return unicode(str(text))


def to_java_string(text):
    """Посимвольная сборка нативной Java строки через StringBuilder.appendCodePoint."""
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
            except:
                pass
        try:
            return JavaString(u_text)
        except:
            pass
    return text


def create_component(text):
    if text is None:
        text = u""
    u_text = to_unicode(text)
    colored = colorize(u_text)
    j_str = to_java_string(colored)

    if ADVENTURE_AVAILABLE:
        try:
            return LegacyComponentSerializer.legacySection().deserialize(j_str)
        except:
            try:
                return LegacyComponentSerializer.legacyAmpersand().deserialize(to_java_string(u_text))
            except:
                pass

    return j_str


def build_java_list(items):
    j_list = ArrayList()
    if items:
        for item in items:
            j_list.add(to_java_string(item))
    return j_list


def colorize(text):
    if not text:
        return u""
    u_text = to_unicode(text)
    if BUKKIT_AVAILABLE:
        j_str = to_java_string(u_text)
        res = ChatColor.translateAlternateColorCodes('&', j_str)
        return to_unicode(res)
    else:
        return re.sub(r'&([0-9a-fk-or])', u'', u_text, flags=re.IGNORECASE)


def safe_console_send(text):
    colored_text = colorize(text)
    if BUKKIT_AVAILABLE:
        try:
            java_msg = to_java_string(colored_text)
            Bukkit.getConsoleSender().sendMessage(java_msg)
            return
        except:
            pass
    print("[SmartY-Arena] " + str(text))


def log_info(text):
    safe_console_send(u"&c[SmartY-Arena] &a[INFO] " + to_unicode(text))


def log_error(text):
    safe_console_send(u"&c[SmartY-Arena] &c[ERROR] " + to_unicode(text))


def format_currency(amount):
    try:
        val = float(amount)
        # ФИКС "nan$/inf$": round(nan) в CPython выбрасывает ValueError, НО в Jython 2.7
        # это молча проходило (не бросало исключение), и "{:,.2f}".format(nan)
        # возвращает строку "nan" вместо ошибки — отсюда и брался "nan$" в чате.
        # Явная проверка ниже отсекает NaN/Infinity ДО любого форматирования.
        if val != val or val == float("inf") or val == float("-inf"):
            return u"0$"
        if val.is_integer() or abs(val - round(val)) < 0.001:
            formatted_int = str(int(round(val)))
            res = []
            for i, ch in enumerate(reversed(formatted_int)):
                if i > 0 and i % 3 == 0:
                    res.append(" ")
                res.append(ch)
            formatted = "".join(reversed(res))
        else:
            formatted = "{:,.2f}".format(val).replace(",", " ")

        cleaned = to_unicode(formatted).replace(u"\u00a0", u" ").replace(u"\u00c2", u"").strip()
        return cleaned + u"$"
    except:
        return u"0$"


def safe_send_title(player, title_text, subtitle_text, fade_in=10, stay=70, fade_out=20):
    if not BUKKIT_AVAILABLE or player is None or not player.isOnline():
        return
    c_title = colorize(title_text) if title_text else u""
    c_sub = colorize(subtitle_text) if subtitle_text else u""

    try:
        player.sendTitle(to_java_string(c_title), to_java_string(c_sub), fade_in, stay, fade_out)
        return
    except:
        pass


def get_online_player_by_uuid_or_name(uuid_str, name=None):
    if not BUKKIT_AVAILABLE:
        return None

    str_uuid = str(uuid_str)
    try:
        for p in Bukkit.getOnlinePlayers():
            if str(p.getUniqueId()) == str_uuid:
                return p
    except:
        pass

    if JavaUUID:
        try:
            p = Bukkit.getPlayer(JavaUUID.fromString(str_uuid))
            if p and p.isOnline():
                return p
        except:
            pass

    if name:
        try:
            p = Bukkit.getPlayer(to_unicode(name))
            if p and p.isOnline():
                return p
        except:
            pass

    return None


# -----------------------------------------------------------------------------
# ГЛОБАЛЬНЫЕ НАСТРОЙКИ И СООБЩЕНИЯ АРЕНЫ
# -----------------------------------------------------------------------------
class ArenaConfig:
    PLUGIN_NAME = u"SmartY-Arena"
    VERSION = u"3.8.1"
    PREFIX = u"&c&l[\u0410\u0440\u0435\u043d\u0430]&r "

    SCRIPT_DIR = get_script_dir()
    DATA_DIR = os.path.join(SCRIPT_DIR, "data")
    ARENA_FILE = os.path.join(DATA_DIR, "arena.json")
    PLAYERS_FILE = os.path.join(DATA_DIR, "players.json")
    REQUEST_TIMEOUT = 30

    MESSAGES = {
        "request_sent": u"{prefix}&7Вы вызвали игрока &e{target} &7на дуэль со ставкой &a{bet}&7!",
        "request_received": u"{prefix}&e{sender} &7вызывает вас на PvP дуэль!\n{prefix}&7Ставка: &a{bet}\n{prefix}&7Введите &a/arena accept {sender} &7или &c/arena deny {sender}",
        "request_expired": u"{prefix}&cВремя ожидания вызова на дуэль от {player} истекло.",
        "request_denied_sender": u"{prefix}&cИгрок {target} отклонил ваш вызов на дуэль.",
        "request_denied_target": u"{prefix}&7Вы отклонили вызов на дуэль от &e{sender}&7.",
        "request_disabled": u"{prefix}&cИгрок &e{target} &cотключил прием вызовов на дуэль!",
        "no_pending_request": u"{prefix}&cУ вас нет активных вызовов на дуэль.",
        "cannot_duel_self": u"{prefix}&cВы не можете вызвать самого себя на дуэль!",
        "already_in_fight": u"{prefix}&cВы или ваш соперник уже находитесь в бою!",
        "insufficient_funds_sender": u"{prefix}&cУ вас недостаточно средств для этой ставки (&e{bet}&c)!",
        "insufficient_funds_target": u"{prefix}&cУ игрока &e{target} &cнедостаточно средств для этой ставки!",
        "player_offline": u"{prefix}&cИгрок &e{player} &cне найден или находится оффлайн.",
        "usage": u"{prefix}&cИспользование: &f/arena <request|accept|deny|stats|profile|top|setspawn|reload>",
        "spawn_set": u"{prefix}&aТочка спавна &e{point} &aуспешно установлена на ваши координаты!",
        "fight_start_broadcast": u"&c&l⚔ [\u0410\u0420\u0415\u041d\u0410] &e{p1} &7против &e{p2} &7на ставку &a{bet}&7!",
        "victory_title": u"&a&lПОБЕДА! &7(+{elo_change} ELO)",
        "victory_subtitle": u"&7Вы победили &e{opponent} &7и забрали &a{reward}&7!",
        "defeat_title": u"&c&lПОРАЖЕНИЕ! &7(-{elo_change} ELO)",
        "defeat_subtitle": u"&7Вы проиграли дуэль игроку &e{opponent}&7.",
        "leaver_loss": u"{prefix}&cИгрок &e{player} &cвышел из игры во время боя и получил поражение!",
        "elo_reset": u"{prefix}&aРейтинг ELO игрока &e{target} &aуспешно сброшен до &e1000 ELO&a!",
        "toggle_requests_on": u"{prefix}&aПрием вызовов на дуэль &lВКЛЮЧЕН&a!",
        "toggle_requests_off": u"{prefix}&cПрием вызовов на дуэль &lВЫКЛЮЧЕН&c!"
    }


def send_arena_msg(recipient, key, *args, **kwargs):
    if key in ArenaConfig.MESSAGES:
        raw = ArenaConfig.MESSAGES[key]
    else:
        raw = to_unicode(key)

    fmt_args = {"prefix": ArenaConfig.PREFIX}
    for k, v in kwargs.items():
        fmt_args[k] = to_unicode(v)

    try:
        if args:
            formatted_raw = raw.format(*args)
        else:
            formatted_raw = raw
        text = formatted_raw.format(**fmt_args)
    except:
        text = raw

    colored = colorize(text)
    if recipient is not None:
        if hasattr(recipient, "sendMessage"):
            recipient.sendMessage(to_java_string(colored))
        else:
            safe_console_send(colored)


def send_clickable_duel_request(target_player, sender_name, bet_str):
    if not BUKKIT_AVAILABLE or target_player is None or not target_player.isOnline():
        return

    try:
        from net.md_5.bungee.api.chat import TextComponent, ClickEvent, HoverEvent, ComponentBuilder

        header_text = colorize(
            ArenaConfig.PREFIX + u"&e{0} &7вызывает вас на PvP дуэль!\n".format(sender_name) +
            ArenaConfig.PREFIX + u"&7Ставка: &a{0}\n".format(bet_str) +
            ArenaConfig.PREFIX + u"&7Выберите действие: "
        )
        msg_comp = TextComponent(header_text)

        btn_accept = TextComponent(colorize(u"&a&l[ПРИНЯТЬ]"))
        btn_accept.setClickEvent(ClickEvent(ClickEvent.Action.RUN_COMMAND, u"/arena accept {0}".format(sender_name)))
        try:
            btn_accept.setHoverEvent(HoverEvent(HoverEvent.Action.SHOW_TEXT, ComponentBuilder(colorize(u"&aНажмите, чтобы &lПРИНЯТЬ &aдуэль!")).create()))
        except:
            pass

        spacer = TextComponent(colorize(u"   "))

        btn_deny = TextComponent(colorize(u"&c&l[ОТКЛОНИТЬ]"))
        btn_deny.setClickEvent(ClickEvent(ClickEvent.Action.RUN_COMMAND, u"/arena deny {0}".format(sender_name)))
        try:
            btn_deny.setHoverEvent(HoverEvent(HoverEvent.Action.SHOW_TEXT, ComponentBuilder(colorize(u"&cНажмите, чтобы &lОТКЛОНИТЬ &cвызов!")).create()))
        except:
            pass

        msg_comp.addExtra(btn_accept)
        msg_comp.addExtra(spacer)
        msg_comp.addExtra(btn_deny)

        if hasattr(target_player, "spigot"):
            target_player.spigot().sendMessage(msg_comp)
            return

    except Exception as e:
        log_error(u"Could not send clickable duel chat component: {0}".format(e))

    send_arena_msg(target_player, "request_received", sender=sender_name, bet=bet_str)


# -----------------------------------------------------------------------------
# МЕНЕДЖЕР ДАННЫХ ИГРОКОВ И СТАТИСТИКИ
# -----------------------------------------------------------------------------
pending_requests = {}
active_duels = {}
player_states = {}
frozen_players = set()
active_spectators = {}


def get_economy_manager():
    if JAVA_STRING_AVAILABLE and System is not None:
        try:
            inst = System.getProperties().get("PySpigot_EconomyManager")
            if inst:
                return inst
        except:
            pass
    if "economy" in sys.modules:
        mod = sys.modules["economy"]
        if hasattr(mod, "EconomyManager"):
            return mod.EconomyManager()
    return None


def get_sender_uuid_and_name(sender):
    if sender is None:
        return None, u"Console"
    name = u"Unknown"
    if hasattr(sender, "getName"):
        try:
            name = to_unicode(sender.getName())
        except:
            pass
    uuid_str = None
    if hasattr(sender, "getUniqueId"):
        try:
            u_obj = sender.getUniqueId()
            if u_obj:
                uuid_str = str(u_obj)
        except:
            pass
    return uuid_str, name


class PlayerProfile(object):
    def __init__(self, uuid_str, name, elo=1000, kills=0, deaths=0, wins=0, losses=0, win_streak=0, best_win_streak=0, history=None, accept_requests=True):
        self.uuid = str(uuid_str)
        self.name = to_unicode(name)
        self.elo = int(elo)
        self.kills = int(kills)
        self.deaths = int(deaths)
        self.wins = int(wins)
        self.losses = int(losses)
        self.win_streak = int(win_streak)
        self.best_win_streak = int(best_win_streak)
        self.history = history if isinstance(history, list) else []
        self.accept_requests = bool(accept_requests)

    def to_dict(self):
        return {
            "uuid": self.uuid,
            "name": self.name,
            "elo": self.elo,
            "kills": self.kills,
            "deaths": self.deaths,
            "wins": self.wins,
            "losses": self.losses,
            "win_streak": self.win_streak,
            "best_win_streak": self.best_win_streak,
            "history": self.history[-10:],
            "accept_requests": self.accept_requests
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            uuid_str=data.get("uuid"),
            name=data.get("name", u"Unknown"),
            elo=data.get("elo", 1000),
            kills=data.get("kills", 0),
            deaths=data.get("deaths", 0),
            wins=data.get("wins", 0),
            losses=data.get("losses", 0),
            win_streak=data.get("win_streak", 0),
            best_win_streak=data.get("best_win_streak", 0),
            history=data.get("history", []),
            accept_requests=data.get("accept_requests", True)
        )

    def record_win(self, elo_delta):
        self.elo += int(elo_delta)
        self.kills += 1
        self.wins += 1
        self.win_streak += 1
        if self.win_streak > self.best_win_streak:
            self.best_win_streak = self.win_streak
        self.history.append("WIN")
        if len(self.history) > 10:
            self.history.pop(0)

    def record_loss(self, elo_delta):
        self.elo = max(0, self.elo - int(elo_delta))
        self.deaths += 1
        self.losses += 1
        self.win_streak = 0
        self.history.append("LOSS")
        if len(self.history) > 10:
            self.history.pop(0)


class PlayerStatsManager(object):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PlayerStatsManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.profiles = {}
        self.name_to_uuid = {}
        self.load_data()

    def load_data(self):
        self.profiles.clear()
        self.name_to_uuid.clear()

        if not os.path.exists(ArenaConfig.DATA_DIR):
            try:
                os.makedirs(ArenaConfig.DATA_DIR)
            except:
                pass

        if not os.path.exists(ArenaConfig.PLAYERS_FILE):
            self.save_data()
            return

        try:
            with open(ArenaConfig.PLAYERS_FILE, "r") as f:
                data = json.load(f)
                for uuid_str, p_dict in data.items():
                    prof = PlayerProfile.from_dict(p_dict)
                    self.profiles[uuid_str] = prof
                    if prof.name:
                        self.name_to_uuid[prof.name.lower()] = uuid_str
        except Exception as e:
            log_error(u"Error reading players.json: {0}".format(e))

    def save_data(self):
        try:
            if not os.path.exists(ArenaConfig.DATA_DIR):
                os.makedirs(ArenaConfig.DATA_DIR)
            data_to_write = {uuid_str: prof.to_dict() for uuid_str, prof in self.profiles.items()}

            temp_file = ArenaConfig.PLAYERS_FILE + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(data_to_write, f, indent=2, ensure_ascii=False)

            if os.path.exists(ArenaConfig.PLAYERS_FILE):
                os.remove(ArenaConfig.PLAYERS_FILE)
            os.rename(temp_file, ArenaConfig.PLAYERS_FILE)
        except Exception as e:
            log_error(u"Error saving players.json: {0}".format(e))

    def get_or_create_profile(self, uuid_str, name):
        uuid_key = str(uuid_str)
        unicode_name = to_unicode(name)
        if uuid_key in self.profiles:
            prof = self.profiles[uuid_key]
            if unicode_name and unicode_name != u"Unknown":
                prof.name = unicode_name
                self.name_to_uuid[unicode_name.lower()] = uuid_key
            self.save_data()
            return prof
        else:
            prof = PlayerProfile(uuid_key, unicode_name)
            self.profiles[uuid_key] = prof
            if unicode_name and unicode_name != u"Unknown":
                self.name_to_uuid[unicode_name.lower()] = uuid_key
            self.save_data()
            return prof

    def get_profile_by_name(self, name):
        if not name:
            return None
        lower_name = to_unicode(name).lower()
        uuid_key = self.name_to_uuid.get(lower_name)
        if uuid_key and uuid_key in self.profiles:
            return self.profiles[uuid_key]

        for prof in self.profiles.values():
            if prof.name and prof.name.lower() == lower_name:
                self.name_to_uuid[lower_name] = prof.uuid
                return prof

        if BUKKIT_AVAILABLE:
            try:
                for p in Bukkit.getOnlinePlayers():
                    if p.getName().lower() == lower_name:
                        return self.get_or_create_profile(str(p.getUniqueId()), p.getName())
            except:
                pass
        return None

    def get_top_profiles(self, limit=10):
        return sorted(self.profiles.values(), key=lambda p: p.elo, reverse=True)[:limit]


class ArenaDataManager(object):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ArenaDataManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.spawns = {"p1": None, "p2": None, "spectator": None}
        self.load_data()

    def load_data(self):
        if not os.path.exists(ArenaConfig.DATA_DIR):
            try:
                os.makedirs(ArenaConfig.DATA_DIR)
            except:
                pass
        if not os.path.exists(ArenaConfig.ARENA_FILE):
            self.save_data()
            return
        try:
            with open(ArenaConfig.ARENA_FILE, "r") as f:
                data = json.load(f)
                self.spawns = data.get("spawns", self.spawns)
        except Exception as e:
            log_error(u"Error reading arena.json: {0}".format(e))

    def save_data(self):
        try:
            if not os.path.exists(ArenaConfig.DATA_DIR):
                os.makedirs(ArenaConfig.DATA_DIR)
            with open(ArenaConfig.ARENA_FILE, "w") as f:
                json.dump({"spawns": self.spawns}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log_error(u"Error saving arena.json: {0}".format(e))

    def set_spawn(self, point, location):
        if not BUKKIT_AVAILABLE or not location:
            return False
        self.spawns[point] = {
            "world": str(location.getWorld().getName()),
            "x": round(location.getX(), 2),
            "y": round(location.getY(), 2),
            "z": round(location.getZ(), 2),
            "yaw": round(location.getYaw(), 2),
            "pitch": round(location.getPitch(), 2)
        }
        self.save_data()
        return True

    def get_spawn_location(self, point):
        if not BUKKIT_AVAILABLE or point not in self.spawns or not self.spawns[point]:
            return None
        s = self.spawns[point]
        world = Bukkit.getWorld(s["world"])
        if not world:
            return None
        return Location(world, s["x"], s["y"], s["z"], s["yaw"], s["pitch"])


# -----------------------------------------------------------------------------
# СОХРАНЕНИЕ И ВОССТАНОВЛЕНИЕ СОСТОЯНИЯ ИГРОКА
# -----------------------------------------------------------------------------
def save_player_state(player):
    if not BUKKIT_AVAILABLE or player is None:
        return
    uuid_str = str(player.getUniqueId())

    inv = player.getInventory()
    contents = [item.clone() if item else None for item in inv.getContents()]
    armor = [item.clone() if item else None for item in inv.getArmorContents()]
    extra = [item.clone() if item else None for item in getattr(inv, "getExtraContents", lambda: [])()]

    loc = player.getLocation().clone()
    potion_effects = list(player.getActivePotionEffects())

    player_states[uuid_str] = {
        "location": loc,
        "contents": contents,
        "armor": armor,
        "extra": extra,
        "health": player.getHealth(),
        "food": player.getFoodLevel(),
        "saturation": player.getSaturation(),
        "exp": player.getTotalExperience(),
        "level": player.getLevel(),
        "potions": potion_effects
    }
    log_info(u"Saved pre-duel state for player {0} at location {1},{2},{3}".format(
        player.getName(), int(loc.getX()), int(loc.getY()), int(loc.getZ())
    ))


def restore_player_state(player):
    if not BUKKIT_AVAILABLE or player is None or not player.isOnline():
        return False
    uuid_str = str(player.getUniqueId())
    if uuid_str not in player_states:
        return True

    if hasattr(player, "isDead") and player.isDead():
        if hasattr(player, "spigot"):
            try:
                player.spigot().respawn()
            except:
                pass
        return False

    st = player_states[uuid_str]
    try:
        loc = st.get("location")
        if loc and loc.getWorld():
            try:
                if Vector:
                    player.setVelocity(Vector(0, 0, 0))
            except:
                pass
            res = player.teleport(loc)
            log_info(u"Teleported player {0} back to original location {1},{2},{3} (success: {4})".format(
                player.getName(), int(loc.getX()), int(loc.getY()), int(loc.getZ()), res
            ))
            if not res:
                return False

        player_states.pop(uuid_str, None)

        player.setHealth(max(1.0, player.getMaxHealth()))
        player.setFoodLevel(st.get("food", 20))
        player.setSaturation(st.get("saturation", 5.0))

        inv = player.getInventory()
        inv.clear()
        if st.get("contents"):
            inv.setContents(st["contents"])
        if st.get("armor"):
            inv.setArmorContents(st["armor"])
        if st.get("extra") and hasattr(inv, "setExtraContents"):
            try:
                inv.setExtraContents(st["extra"])
            except:
                pass

        for p_effect in list(player.getActivePotionEffects()):
            player.removePotionEffect(p_effect.getType())
        for p_effect in st.get("potions", []):
            player.addPotionEffect(p_effect)

        player.setLevel(st.get("level", 0))

        try:
            if "economy" in sys.modules:
                mod = sys.modules["economy"]
                if hasattr(mod, "update_player_hud"):
                    mod.update_player_hud(player)
        except:
            pass

        return True

    except Exception as e:
        log_error(u"Error restoring player state for {0}: {1}".format(player.getName(), e))
        return False


def schedule_restore_player(player, delay=2, retries=20):
    if not BUKKIT_AVAILABLE or player is None or not player.isOnline():
        return

    plugin = get_pyspigot_plugin()
    if not plugin:
        restore_player_state(player)
        return

    class RestoreRunnable(Runnable):
        def __init__(self, current_retries):
            self.retries = current_retries

        def run(self):
            try:
                if player and player.isOnline():
                    success = restore_player_state(player)
                    if not success and self.retries > 0:
                        Bukkit.getScheduler().runTaskLater(plugin, RestoreRunnable(self.retries - 1), 3)
            except Exception as e:
                log_error(u"Error in delayed restore retry: {0}".format(e))

    try:
        Bukkit.getScheduler().runTaskLater(plugin, RestoreRunnable(retries), delay)
    except:
        restore_player_state(player)


# -----------------------------------------------------------------------------
# ЛОГИКА ДУЭЛЕЙ И БОЯ
# -----------------------------------------------------------------------------
def get_pyspigot_plugin():
    if BUKKIT_AVAILABLE:
        try:
            return Bukkit.getPluginManager().getPlugin("PySpigot")
        except:
            pass
    return None


def is_player_in_duel(uuid_str):
    for duel in active_duels.values():
        if duel["p1_uuid"] == str(uuid_str) or duel["p2_uuid"] == str(uuid_str):
            return True
    return False


def get_player_duel(uuid_str):
    for duel_id, duel in active_duels.items():
        if duel["p1_uuid"] == str(uuid_str) or duel["p2_uuid"] == str(uuid_str):
            return duel_id, duel
    return None, None


def calculate_elo_delta(winner_player, leaver=False):
    if leaver or not winner_player or not BUKKIT_AVAILABLE:
        return 30
    try:
        max_hp = winner_player.getMaxHealth()
        cur_hp = winner_player.getHealth()
        hp_pct = (cur_hp / max_hp) * 100.0 if max_hp > 0 else 100.0

        if hp_pct >= 90.0:
            return 30
        elif hp_pct >= 50.0:
            return 25
        else:
            return 20
    except:
        return 25


def start_arena_duel(p1, p2, bet):
    p1_uuid, p1_name = get_sender_uuid_and_name(p1)
    p2_uuid, p2_name = get_sender_uuid_and_name(p2)

    p1_player = get_online_player_by_uuid_or_name(p1_uuid, p1_name)
    p2_player = get_online_player_by_uuid_or_name(p2_uuid, p2_name)

    if not p1_player or not p2_player:
        log_error(u"Could not find Bukkit Player objects for duel start.")
        return

    duel_id = "{0}_vs_{1}_{2}".format(p1_uuid, p2_uuid, int(time.time()))
    active_duels[duel_id] = {
        "p1_uuid": p1_uuid,
        "p2_uuid": p2_uuid,
        "p1_name": p1_name,
        "p2_name": p2_name,
        "bet": float(bet),
        "state": "COUNTDOWN"
    }

    save_player_state(p1_player)
    save_player_state(p2_player)

    frozen_players.add(p1_uuid)
    frozen_players.add(p2_uuid)

    mgr = ArenaDataManager()
    loc1 = mgr.get_spawn_location("p1")
    loc2 = mgr.get_spawn_location("p2")

    if not loc1 or not loc2:
        send_arena_msg(p1_player, u"{prefix}&cВнимание: Точки спавна арены (p1/p2) не установлены! Установите их: &f/arena setspawn p1 &cи &f/arena setspawn p2")
        send_arena_msg(p2_player, u"{prefix}&cВнимание: Точки спавна арены (p1/p2) не установлены! Установите их: &f/arena setspawn p1 &cи &f/arena setspawn p2")
    else:
        p1_player.teleport(loc1)
        p2_player.teleport(loc2)

    p1_player.setHealth(p1_player.getMaxHealth())
    p1_player.setFoodLevel(20)
    p2_player.setHealth(p2_player.getMaxHealth())
    p2_player.setFoodLevel(20)

    plugin = get_pyspigot_plugin()
    if not plugin or not BUKKIT_AVAILABLE:
        frozen_players.discard(p1_uuid)
        frozen_players.discard(p2_uuid)
        active_duels[duel_id]["state"] = "FIGHT"
        return

    class CountdownRunnable(Runnable):
        def __init__(self):
            self.counter = 3
            self.task_id = -1

        def run(self):
            try:
                if not p1_player.isOnline() or not p2_player.isOnline():
                    if self.task_id != -1:
                        Bukkit.getScheduler().cancelTask(self.task_id)
                    finish_arena_duel(duel_id, leaver_uuid=p1_uuid if not p1_player.isOnline() else p2_uuid)
                    return

                if self.counter > 0:
                    safe_send_title(p1_player, u"&e&l{0}".format(self.counter), u"&7Приготовьтесь к бою!", 0, 20, 5)
                    safe_send_title(p2_player, u"&e&l{0}".format(self.counter), u"&7Приготовьтесь к бою!", 0, 20, 5)

                    try:
                        s_enum = Sound.valueOf("BLOCK_NOTE_BLOCK_PLING")
                        p1_player.playSound(p1_player.getLocation(), s_enum, 1.0, 1.0)
                        p2_player.playSound(p2_player.getLocation(), s_enum, 1.0, 1.0)
                    except:
                        pass
                    self.counter -= 1

                else:
                    if self.task_id != -1:
                        Bukkit.getScheduler().cancelTask(self.task_id)

                    safe_send_title(p1_player, u"&c&lБОЙ!", u"&7Уничтожьте соперника!", 0, 30, 10)
                    safe_send_title(p2_player, u"&c&lБОЙ!", u"&7Уничтожьте соперника!", 0, 30, 10)

                    try:
                        s_enum = Sound.valueOf("ENTITY_ENDER_DRAGON_GROWL")
                        p1_player.playSound(p1_player.getLocation(), s_enum, 0.6, 1.2)
                        p2_player.playSound(p2_player.getLocation(), s_enum, 0.6, 1.2)
                    except:
                        pass

                    frozen_players.discard(p1_uuid)
                    frozen_players.discard(p2_uuid)
                    if duel_id in active_duels:
                        active_duels[duel_id]["state"] = "FIGHT"

            except Exception as e:
                log_error(u"Error in CountdownRunnable: {0}".format(e))
                if self.task_id != -1:
                    Bukkit.getScheduler().cancelTask(self.task_id)

    runner = CountdownRunnable()
    try:
        task_obj = Bukkit.getScheduler().runTaskTimer(plugin, runner, 0, 20)
        runner.task_id = task_obj.getTaskId()
    except Exception as e:
        log_error(u"Could not start countdown timer: {0}".format(e))
        frozen_players.discard(p1_uuid)
        frozen_players.discard(p2_uuid)
        active_duels[duel_id]["state"] = "FIGHT"


def finish_arena_duel(duel_id, winner_uuid=None, loser_uuid=None, leaver_uuid=None):
    if duel_id not in active_duels:
        return

    duel = active_duels.pop(duel_id)
    p1_uuid = duel["p1_uuid"]
    p2_uuid = duel["p2_uuid"]
    bet = duel["bet"]

    frozen_players.discard(p1_uuid)
    frozen_players.discard(p2_uuid)

    if leaver_uuid:
        loser_uuid = leaver_uuid
        winner_uuid = p2_uuid if leaver_uuid == p1_uuid else p1_uuid

    if not winner_uuid or not loser_uuid:
        return

    winner_name = duel["p1_name"] if winner_uuid == p1_uuid else duel["p2_name"]
    loser_name = duel["p2_name"] if winner_uuid == p1_uuid else duel["p1_name"]

    w_player = get_online_player_by_uuid_or_name(winner_uuid, winner_name)
    l_player = get_online_player_by_uuid_or_name(loser_uuid, loser_name)

    elo_delta = calculate_elo_delta(w_player, leaver=(leaver_uuid is not None))

    stats_mgr = PlayerStatsManager()
    w_prof = stats_mgr.get_or_create_profile(winner_uuid, winner_name)
    l_prof = stats_mgr.get_or_create_profile(loser_uuid, loser_name)

    w_prof.record_win(elo_delta)
    l_prof.record_loss(elo_delta)
    stats_mgr.save_data()

    eco = get_economy_manager()
    if eco and bet > 0:
        # ФИКС дублирования денег: раньше deposit() победителю выполнялся
        # БЕЗУСЛОВНО, даже если withdraw() у проигравшего вернул False
        # (например баланс проигравшего уже < ставки на момент завершения
        # дуэли — деньги успели потратить/забрать за время боя). Теперь
        # деньги переводятся победителю ТОЛЬКО если списание реально прошло.
        withdrawn_ok = eco.withdraw(loser_uuid, bet)
        if withdrawn_ok:
            eco.deposit(winner_uuid, bet, winner_name)
        else:
            log_error(u"Arena duel {0}: withdraw failed for loser {1}, bet {2} NOT paid out to winner (anti-duplication guard)".format(duel_id, loser_uuid, bet))

    if BUKKIT_AVAILABLE:
        if w_player and w_player.isOnline():
            w_title = ArenaConfig.MESSAGES["victory_title"].format(elo_change=elo_delta)
            w_sub = ArenaConfig.MESSAGES["victory_subtitle"].format(opponent=loser_name, reward=format_currency(bet))
            safe_send_title(w_player, w_title, w_sub, 10, 80, 20)
            try:
                w_player.playSound(w_player.getLocation(), Sound.valueOf("UI_TOAST_CHALLENGE_COMPLETE"), 1.0, 1.0)
            except:
                pass
            send_arena_msg(w_player, u"{prefix}&a+ {elo_change} ELO &7| Ваш новый рейтинг: &e{new_elo} ELO", elo_change=elo_delta, new_elo=w_prof.elo)
            schedule_restore_player(w_player, delay=2, retries=20)

        if l_player and l_player.isOnline():
            l_title = ArenaConfig.MESSAGES["defeat_title"].format(elo_change=elo_delta)
            l_sub = ArenaConfig.MESSAGES["defeat_subtitle"].format(opponent=winner_name)
            safe_send_title(l_player, l_title, l_sub, 10, 80, 20)
            send_arena_msg(l_player, u"{prefix}&c- {elo_change} ELO &7| Ваш новый рейтинг: &e{new_elo} ELO", elo_change=elo_delta, new_elo=l_prof.elo)
            schedule_restore_player(l_player, delay=2, retries=20)

    log_info(u"Duel finished: Winner {0} (+{1} ELO), Loser {2} (-{3} ELO)".format(winner_name, elo_delta, loser_name, elo_delta))


# -----------------------------------------------------------------------------
# ГРАФИЧЕСКОЕ CHEST GUI МЕНЮ С 100% БЕЗОПАСНЫМИ СТРОКАМИ И COMPONENT
# -----------------------------------------------------------------------------
GUI_MAIN_TITLE = u"&c&l⚔ МЕНЮ АРЕНЫ PVP"
GUI_TOP_TITLE = u"&6&l🏆 ТОП-10 ИГРОКОВ ELO"


def create_gui_item(material_name, name_text, lore_lines=None, skull_owner=None, amount=1):
    if not BUKKIT_AVAILABLE:
        return None
    try:
        mat = None
        try:
            mat = Material.valueOf(material_name)
        except:
            pass

        if not mat:
            if "GLASS_PANE" in material_name:
                try:
                    mat = Material.valueOf("STAINED_GLASS_PANE")
                except:
                    mat = Material.STONE
            else:
                mat = Material.STONE

        item = ItemStack(mat, amount)
        meta = item.getItemMeta()

        if meta:
            if name_text:
                c_name = create_component(name_text)
                if hasattr(meta, "displayName"):
                    try:
                        meta.displayName(c_name)
                    except:
                        meta.setDisplayName(to_java_string(colorize(name_text)))
                else:
                    meta.setDisplayName(to_java_string(colorize(name_text)))

            if lore_lines:
                j_lore = ArrayList()
                for line in lore_lines:
                    j_lore.add(create_component(line))
                if hasattr(meta, "lore"):
                    try:
                        meta.lore(j_lore)
                    except:
                        meta.setLore(j_lore)
                else:
                    meta.setLore(j_lore)

            if skull_owner and hasattr(meta, "setOwner"):
                try:
                    meta.setOwner(to_java_string(to_unicode(skull_owner)))
                except:
                    pass

            item.setItemMeta(meta)
        return item
    except Exception as e:
        log_error(u"Error creating GUI item: {0}".format(e))
        return None


def open_arena_main_gui(player):
    if not BUKKIT_AVAILABLE or player is None or not player.isOnline():
        return

    try:
        uuid_str, name = get_sender_uuid_and_name(player)
        stats_mgr = PlayerStatsManager()
        prof = stats_mgr.get_or_create_profile(uuid_str, name)

        inv = None
        comp_title = create_component(GUI_MAIN_TITLE)

        try:
            inv = Bukkit.createInventory(None, 27, comp_title)
        except:
            pass

        if not inv:
            try:
                inv = Bukkit.createInventory(None, 27, to_java_string(colorize(GUI_MAIN_TITLE)))
            except:
                pass

        if not inv:
            inv = Bukkit.createInventory(None, 27)

        filler = create_gui_item("BLACK_STAINED_GLASS_PANE", u" ")
        if not filler:
            filler = create_gui_item("GRAY_STAINED_GLASS_PANE", u" ")

        for slot in range(27):
            if filler:
                inv.setItem(slot, filler)

        # 1. Слот 10: Вызов на дуэль
        item_request = create_gui_item(
            "DIAMOND_SWORD",
            u"&c&l⚔ Вызвать на дуэль",
            [
                u"&7Отправить случайный или прямой",
                u"&7вызов игроку сервера!",
                u"",
                u"&eКоманда: &f/arena request <ник> [ставка]",
                u"&aНажмите, чтобы получить подсказку!"
            ]
        )
        if item_request:
            inv.setItem(10, item_request)

        # 2. Слот 12: Мой Профиль ELO
        total_games = prof.wins + prof.losses
        winrate = round((float(prof.wins) / float(total_games)) * 100.0, 1) if total_games > 0 else 0.0
        item_profile = create_gui_item(
            "PLAYER_HEAD",
            u"&e&l📊 Мой Профиль PvP",
            [
                u"&fИгрок: &e{0}".format(prof.name),
                u"&fРейтинг: &e&l{0} ELO".format(prof.elo),
                u"&fПобед / Поражений: &a{0} &7/ &c{1}".format(prof.wins, prof.losses),
                u"&fВинрейт: &e{0}%".format(winrate),
                u"&fСерия побед: &6{0}🔥 &7(Рекорд: &e{1}🔥&7)".format(prof.win_streak, prof.best_win_streak),
                u"&fИстория: {0}".format(render_history_tags(prof.history)),
                u"",
                u"&aНажмите, чтобы вывести статистику в чат!"
            ],
            skull_owner=prof.name
        )
        if item_profile:
            inv.setItem(12, item_profile)

        # 3. Слот 14: Топ-10 Лидеров
        item_top = create_gui_item(
            "NETHER_STAR",
            u"&6&l🏆 Таблица Лидеров (Top 10)",
            [
                u"&7Список 10 лучших PvP бойцов",
                u"&7нашего сервера по рейтингу ELO!",
                u"",
                u"&aНажмите, чтобы открыть таблицу лидеров!"
            ]
        )
        if item_top:
            inv.setItem(14, item_top)

        # 4. Слот 16: Настройки дуэлей (Переключатель)
        status_text = u"&a&lВКЛЮЧЕНЫ" if prof.accept_requests else u"&c&lВЫКЛЮЧЕНЫ"
        item_toggle = create_gui_item(
            "REDSTONE_TORCH" if prof.accept_requests else "LEVER",
            u"&a&l⚙ Прием вызовов",
            [
                u"&7Текущий статус: {0}".format(status_text),
                u"",
                u"&eНажмите, чтобы изменить статус!"
            ]
        )
        if item_toggle:
            inv.setItem(16, item_toggle)

        player.openInventory(inv)

    except Exception as e:
        log_error(u"Error opening main arena GUI: {0}".format(e))
        import traceback
        traceback.print_exc()


def open_arena_top_gui(player):
    if not BUKKIT_AVAILABLE or player is None or not player.isOnline():
        return

    try:
        stats_mgr = PlayerStatsManager()
        top_profiles = stats_mgr.get_top_profiles(10)

        comp_title = create_component(GUI_TOP_TITLE)
        inv = None
        try:
            inv = Bukkit.createInventory(None, 36, comp_title)
        except:
            pass

        if not inv:
            try:
                inv = Bukkit.createInventory(None, 36, to_java_string(colorize(GUI_TOP_TITLE)))
            except:
                pass

        if not inv:
            inv = Bukkit.createInventory(None, 36)

        filler = create_gui_item("BLACK_STAINED_GLASS_PANE", u" ")
        if not filler:
            filler = create_gui_item("GRAY_STAINED_GLASS_PANE", u" ")

        for slot in range(36):
            if filler:
                inv.setItem(slot, filler)

        slots_layout = [10, 11, 12, 13, 14, 15, 16, 19, 20, 21]

        for idx, prof in enumerate(top_profiles):
            if idx >= len(slots_layout):
                break

            rank = idx + 1
            total_games = prof.wins + prof.losses
            winrate = round((float(prof.wins) / float(total_games)) * 100.0, 1) if total_games > 0 else 0.0

            rank_color = u"&6" if rank == 1 else (u"&e" if rank == 2 else (u"&f" if rank == 3 else u"&7"))
            item_head = create_gui_item(
                "PLAYER_HEAD",
                u"{0}#{1} &l{2}".format(rank_color, rank, prof.name),
                [
                    u"&fРейтинг: &e&l{0} ELO".format(prof.elo),
                    u"&fУбийств / Смертей: &a{0} &7/ &c{1}".format(prof.kills, prof.deaths),
                    u"&fПобед / Поражений: &a{0} &7/ &c{1}".format(prof.wins, prof.losses),
                    u"&fВинрейт: &e{0}%".format(winrate),
                    u"&fРекорд серии: &6{0}🔥".format(prof.best_win_streak)
                ],
                skull_owner=prof.name
            )
            if item_head:
                inv.setItem(slots_layout[idx], item_head)

        item_back = create_gui_item(
            "BARRIER",
            u"&c← Назад в главное меню",
            [u"&7Вернуться в меню арены"]
        )
        if item_back:
            inv.setItem(31, item_back)

        player.openInventory(inv)

    except Exception as e:
        log_error(u"Error opening top arena GUI: {0}".format(e))
        import traceback
        traceback.print_exc()


def on_inventory_click(event):
    if not BUKKIT_AVAILABLE or event is None:
        return

    try:
        view = event.getView()
        if not view:
            return

        raw_title = to_unicode(view.getTitle())

        # Если инвентарь наш — всегда отменяем забирание предметов!
        top_inv = view.getTopInventory()
        if top_inv and (top_inv.getSize() == 27 or top_inv.getSize() == 36):
            is_arena_gui = False
            if u"МЕНЮ АРЕНЫ PVP" in raw_title or u"ТОП-10 ИГРОКОВ ELO" in raw_title or u"МЕНЮ" in raw_title or u"ТОП" in raw_title:
                is_arena_gui = True
            else:
                slot10 = top_inv.getItem(10)
                slot14 = top_inv.getItem(14)
                if (slot10 and "SWORD" in str(slot10.getType())) or (slot14 and "STAR" in str(slot14.getType())):
                    is_arena_gui = True

            if is_arena_gui:
                event.setCancelled(True)

                clicker = event.getWhoClicked()
                if not isinstance(clicker, Player):
                    return

                slot = event.getRawSlot()
                if slot < 0 or slot >= top_inv.getSize():
                    return

                if top_inv.getSize() == 27:
                    if slot == 10:
                        clicker.closeInventory()
                        send_arena_msg(clicker, u"{prefix}&eДля вызова игрока используйте команду: &a/arena request <ник> [ставка]")
                    elif slot == 12:
                        clicker.closeInventory()
                        uuid_str, name = get_sender_uuid_and_name(clicker)
                        stats_mgr = PlayerStatsManager()
                        prof = stats_mgr.get_or_create_profile(uuid_str, name)
                        display_player_profile(clicker, prof)
                    elif slot == 14:
                        open_arena_top_gui(clicker)
                    elif slot == 16:
                        uuid_str, name = get_sender_uuid_and_name(clicker)
                        stats_mgr = PlayerStatsManager()
                        prof = stats_mgr.get_or_create_profile(uuid_str, name)
                        prof.accept_requests = not prof.accept_requests
                        stats_mgr.save_data()

                        msg_key = "toggle_requests_on" if prof.accept_requests else "toggle_requests_off"
                        send_arena_msg(clicker, msg_key)
                        open_arena_main_gui(clicker)

                elif top_inv.getSize() == 36:
                    if slot == 31:
                        open_arena_main_gui(clicker)

    except Exception as e:
        log_error(u"Error handling inventory click: {0}".format(e))


# -----------------------------------------------------------------------------
# ОБРАБОТЧИКИ СОБЫТИЙ BUKKIT (EVENTS)
# -----------------------------------------------------------------------------
def on_player_move(event):
    try:
        player = event.getPlayer()
        uuid_str = str(player.getUniqueId())
        if uuid_str in frozen_players:
            from_loc = event.getFrom()
            to_loc = event.getTo()
            if from_loc.getX() != to_loc.getX() or from_loc.getY() != to_loc.getY() or from_loc.getZ() != to_loc.getZ():
                event.setCancelled(True)
    except:
        pass


def on_entity_damage(event):
    try:
        entity = event.getEntity()
        if not BUKKIT_AVAILABLE or not isinstance(entity, Player):
            return

        victim_uuid = str(entity.getUniqueId())
        duel_id, duel = get_player_duel(victim_uuid)
        if not duel_id:
            return

        if duel.get("state") == "COUNTDOWN":
            event.setCancelled(True)
            if hasattr(event, "setDamage"):
                event.setDamage(0.0)
            return

        damage = event.getFinalDamage() if hasattr(event, "getFinalDamage") else event.getDamage()

        if entity.getHealth() - damage <= 0.001:
            event.setCancelled(True)
            if hasattr(event, "setDamage"):
                event.setDamage(0.0)
            try:
                if hasattr(event, "setFinalDamage"):
                    event.setFinalDamage(0.0)
            except:
                pass

            entity.setHealth(max(2.0, entity.getHealth()))

            loser_uuid = victim_uuid
            winner_uuid = duel["p2_uuid"] if victim_uuid == duel["p1_uuid"] else duel["p1_uuid"]

            finish_arena_duel(duel_id, winner_uuid=winner_uuid, loser_uuid=loser_uuid)

    except Exception as e:
        log_error(u"Error in EntityDamageEvent: {0}".format(e))


def on_player_death(event):
    try:
        dead_player = event.getEntity()
        uuid_str = str(dead_player.getUniqueId())

        duel_id, duel = get_player_duel(uuid_str)
        if duel_id:
            event.getDrops().clear()
            if hasattr(event, "setDroppedExp"):
                event.setDroppedExp(0)

            loser_uuid = uuid_str
            winner_uuid = duel["p2_uuid"] if uuid_str == duel["p1_uuid"] else duel["p1_uuid"]

            finish_arena_duel(duel_id, winner_uuid=winner_uuid, loser_uuid=loser_uuid)
    except Exception as e:
        log_error(u"Error in PlayerDeathEvent: {0}".format(e))


def on_player_respawn(event):
    try:
        player = event.getPlayer()
        uuid_str = str(player.getUniqueId())
        if uuid_str in player_states:
            st = player_states.get(uuid_str)
            if st and st.get("location") and st["location"].getWorld():
                event.setRespawnLocation(st["location"])
                log_info(u"Set respawn location for {0} to {1},{2},{3}".format(
                    player.getName(), int(st["location"].getX()), int(st["location"].getY()), int(st["location"].getZ())
                ))
            schedule_restore_player(player, delay=1, retries=10)
    except:
        pass


def on_player_quit(event):
    try:
        player = event.getPlayer()
        uuid_str = str(player.getUniqueId())

        frozen_players.discard(uuid_str)

        if uuid_str in active_spectators:
            spec_data = active_spectators.pop(uuid_str)
            if spec_data.get("saved_loc") is not None and hasattr(player, "teleport"):
                try:
                    player.teleport(spec_data["saved_loc"])
                except Exception:
                    pass

        duel_id, duel = get_player_duel(uuid_str)
        if duel_id:
            finish_arena_duel(duel_id, leaver_uuid=uuid_str)

        if uuid_str in player_states:
            restore_player_state(player)
    except Exception as e:
        log_error(u"Error in PlayerQuitEvent: {0}".format(e))


# -----------------------------------------------------------------------------
# ПРЯМАЯ РЕГИСТРАЦИЯ И СНЯТИЕ BUKKIT EVENT EXECUTOR
# -----------------------------------------------------------------------------
registered_listeners = []

if BUKKIT_AVAILABLE:
    class DirectPyBukkitListener(Listener):
        pass

    class DirectPyBukkitEventExecutor(EventExecutor):
        def __init__(self, handler_func):
            self.handler_func = handler_func

        def execute(self, listener, event):
            try:
                self.handler_func(event)
            except Exception as e:
                log_error(u"Error executing event handler: {0}".format(e))
else:
    class DirectPyBukkitListener(object):
        pass
    class DirectPyBukkitEventExecutor(object):
        pass


def unregister_script_listeners():
    if not BUKKIT_AVAILABLE:
        return
    try:
        from org.bukkit.event import HandlerList
        for listener in registered_listeners:
            try:
                HandlerList.unregisterAll(listener)
            except:
                pass
        del registered_listeners[:]
    except:
        pass


def register_event_directly(event_class, handler_func):
    if not BUKKIT_AVAILABLE or event_class is None:
        return False
    try:
        plugin = Bukkit.getPluginManager().getPlugin("PySpigot")
        if not plugin:
            return False

        dummy_listener = DirectPyBukkitListener()
        executor = DirectPyBukkitEventExecutor(handler_func)
        priority = EventPriority.HIGHEST

        Bukkit.getPluginManager().registerEvent(
            event_class,
            dummy_listener,
            priority,
            executor,
            plugin
        )
        registered_listeners.append(dummy_listener)
        return True
    except Exception as e:
        log_error(u"Failed direct event registration for {0}: {1}".format(event_class, e))
        return False


# -----------------------------------------------------------------------------
# ОБРАБОТЧИКИ КОМАНД АРЕНЫ (/arena request|accept|deny|stats|profile|top|resetelo)
# -----------------------------------------------------------------------------
def parse_cmd_args(*args):
    if len(args) == 0:
        return None, []
    sender = args[0]
    if len(args) == 1:
        return sender, []

    last_arg = args[-1]
    if isinstance(last_arg, (list, tuple)):
        return sender, [to_unicode(a) for a in last_arg]

    return sender, [to_unicode(a) for a in args[1:]]


def render_history_tags(history_list):
    if not history_list:
        return colorize(u"&7[Нет боев]")
    tags = []
    for res in history_list[-5:]:
        if res == "WIN":
            tags.append(u"&aW")
        else:
            tags.append(u"&cL")
    joined = u" ".join(tags)
    return colorize(u"&7[{0}&7]".format(joined))


def display_player_profile(sender, target_prof):
    if not target_prof:
        send_arena_msg(sender, u"{prefix}&cПрофиль игрока не найден.")
        return

    total_games = target_prof.wins + target_prof.losses
    winrate = round((float(target_prof.wins) / float(total_games)) * 100.0, 1) if total_games > 0 else 0.0
    history_str = render_history_tags(target_prof.history)

    lines = [
        colorize(u"&c&m-------&r &e&lПРОФИЛЬ PVP &7({0}) &c&m-------".format(target_prof.name)),
        colorize(u"&fРейтинг ELO: &e&l{0} ELO".format(target_prof.elo)),
        colorize(u"&fУбийств / Смертей: &a{0} &7/ &c{1}".format(target_prof.kills, target_prof.deaths)),
        colorize(u"&fПобед / Поражений: &a{0} &7/ &c{1} &7(Винрейт: &e{2}%&7)".format(target_prof.wins, target_prof.losses, winrate)),
        colorize(u"&fТекущий стрик: &6{0}🔥 &7(Рекорд: &e{1}🔥&7)".format(target_prof.win_streak, target_prof.best_win_streak)),
        colorize(u"&fИстория боев: {0}".format(history_str)),
        colorize(u"&c&m---------------------------------------")
    ]

    for line in lines:
        if sender is not None and hasattr(sender, "sendMessage"):
            sender.sendMessage(to_java_string(line))
        else:
            safe_console_send(line)


def cmd_arena(*args):
    sender, cmd_args = parse_cmd_args(*args)
    sender_uuid, sender_name = get_sender_uuid_and_name(sender)

    if len(cmd_args) == 0:
        if sender is not None and hasattr(sender, "openInventory"):
            open_arena_main_gui(sender)
        else:
            send_arena_msg(sender, "usage")
        return True

    sub = cmd_args[0].lower()

    if sub in ["menu", "gui"]:
        if sender is not None and hasattr(sender, "openInventory"):
            open_arena_main_gui(sender)
        else:
            send_arena_msg(sender, "usage")
        return True

    elif sub in ["request", "req", "duel"]:
        if len(cmd_args) < 2:
            send_arena_msg(sender, u"{prefix}&cИспользование: &f/arena request <ник> [ставка]")
            return True

        target_name = cmd_args[1]
        bet = 0.0
        if len(cmd_args) >= 3:
            try:
                raw_bet = float(cmd_args[2])
                # ФИКС: max(0.0, nan) полагается на порядок сравнения аргументов
                # (деталь реализации, не гарантирована в Jython) — здесь NaN/Infinity
                # отсекаются явной проверкой ДО арифметики.
                if raw_bet != raw_bet or raw_bet == float("inf") or raw_bet == float("-inf"):
                    bet = 0.0
                else:
                    bet = max(0.0, raw_bet)
            except ValueError:
                bet = 0.0

        if target_name.lower() == sender_name.lower():
            send_arena_msg(sender, "cannot_duel_self")
            return True

        target_player = Bukkit.getPlayer(target_name) if BUKKIT_AVAILABLE else None
        if not target_player or not target_player.isOnline():
            send_arena_msg(sender, "player_offline", player=target_name)
            return True

        target_uuid = str(target_player.getUniqueId())

        stats_mgr = PlayerStatsManager()
        target_prof = stats_mgr.get_or_create_profile(target_uuid, target_player.getName())
        if not target_prof.accept_requests:
            send_arena_msg(sender, "request_disabled", target=target_player.getName())
            return True

        if is_player_in_duel(sender_uuid) or is_player_in_duel(target_uuid):
            send_arena_msg(sender, "already_in_fight")
            return True

        eco = get_economy_manager()
        if eco and bet > 0:
            if not eco.has_enough(sender_uuid, bet):
                send_arena_msg(sender, "insufficient_funds_sender", bet=format_currency(bet))
                return True
            if not eco.has_enough(target_uuid, bet):
                send_arena_msg(sender, "insufficient_funds_target", target=target_name)
                return True

        pending_requests[target_uuid] = {
            "sender_uuid": sender_uuid,
            "sender_name": sender_name,
            "bet": bet,
            "expire_time": time.time() + ArenaConfig.REQUEST_TIMEOUT
        }

        send_arena_msg(sender, "request_sent", target=target_player.getName(), bet=format_currency(bet))
        send_clickable_duel_request(target_player, sender_name, format_currency(bet))
        return True

    elif sub in ["accept", "yes"]:
        if sender_uuid not in pending_requests:
            send_arena_msg(sender, "no_pending_request")
            return True

        req = pending_requests.pop(sender_uuid)
        if time.time() > req["expire_time"]:
            send_arena_msg(sender, "request_expired", player=req["sender_name"])
            return True

        sender_player = get_online_player_by_uuid_or_name(req["sender_uuid"], req["sender_name"])
        target_player = get_online_player_by_uuid_or_name(sender_uuid, sender_name)

        if not sender_player or not sender_player.isOnline():
            send_arena_msg(sender, "player_offline", player=req["sender_name"])
            return True

        if is_player_in_duel(sender_uuid) or is_player_in_duel(req["sender_uuid"]):
            send_arena_msg(sender, "already_in_fight")
            return True

        eco = get_economy_manager()
        bet = req["bet"]
        if eco and bet > 0:
            if not eco.has_enough(req["sender_uuid"], bet) or not eco.has_enough(sender_uuid, bet):
                send_arena_msg(sender, u"{prefix}&cУ одного из игроков недостаточно средств для начала боя!")
                return True

        start_arena_duel(sender_player, target_player if target_player else sender, bet)
        return True

    elif sub in ["deny", "no", "decline"]:
        if sender_uuid not in pending_requests:
            send_arena_msg(sender, "no_pending_request")
            return True

        req = pending_requests.pop(sender_uuid)
        sender_player = get_online_player_by_uuid_or_name(req["sender_uuid"], req["sender_name"])

        send_arena_msg(sender, "request_denied_target", sender=req["sender_name"])
        if sender_player and sender_player.isOnline():
            send_arena_msg(sender_player, "request_denied_sender", target=sender_name)
        return True

    elif sub in ["stats", "me", "mystats"]:
        stats_mgr = PlayerStatsManager()
        prof = stats_mgr.get_or_create_profile(sender_uuid, sender_name)
        display_player_profile(sender, prof)
        return True

    elif sub in ["profile", "player"]:
        target_name = cmd_args[1] if len(cmd_args) >= 2 else sender_name
        stats_mgr = PlayerStatsManager()
        prof = stats_mgr.get_profile_by_name(target_name)
        if not prof:
            send_arena_msg(sender, "player_offline", player=target_name)
            return True
        display_player_profile(sender, prof)
        return True

    elif sub in ["top", "leaderboard", "top10"]:
        if sender is not None and hasattr(sender, "openInventory"):
            open_arena_top_gui(sender)
        else:
            stats_mgr = PlayerStatsManager()
            top_profiles = stats_mgr.get_top_profiles(10)
            lines = [colorize(u"&6&m-------&r &e&lТОП-10 ИГРОКОВ ELO &6&m-------")]
            for idx, prof in enumerate(top_profiles, 1):
                lines.append(colorize(u"&e{0}. &f{1} &7— &e&l{2} ELO".format(idx, prof.name, prof.elo)))
            lines.append(colorize(u"&6&m-------------------------------------"))
            for line in lines:
                safe_console_send(line)
        return True

    elif sub in ["resetelo", "clearelo"]:
        if hasattr(sender, "isOp") and not sender.isOp():
            send_arena_msg(sender, u"{prefix}&cУ вас недостаточно прав!")
            return True

        if len(cmd_args) < 2:
            send_arena_msg(sender, u"{prefix}&cИспользование: &f/arena resetelo <ник>")
            return True

        target_name = cmd_args[1]
        stats_mgr = PlayerStatsManager()
        prof = stats_mgr.get_profile_by_name(target_name)

        if not prof:
            send_arena_msg(sender, "player_offline", player=target_name)
            return True

        prof.elo = 1000
        stats_mgr.save_data()
        send_arena_msg(sender, "elo_reset", target=prof.name)
        return True

    elif sub in ["setspawn", "setpoint"]:
        if hasattr(sender, "isOp") and not sender.isOp():
            send_arena_msg(sender, u"{prefix}&cУ вас недостаточно прав!")
            return True

        if len(cmd_args) < 2:
            send_arena_msg(sender, u"{prefix}&cИспользование: &f/arena setspawn <p1|p2|spectator>")
            return True

        point = cmd_args[1].lower()
        if point not in ["p1", "p2", "spectator", "spec"]:
            send_arena_msg(sender, u"{prefix}&cУкажите корректную точку: &fp1, p2, spectator")
            return True

        mgr = ArenaDataManager()
        loc = sender.getLocation() if hasattr(sender, "getLocation") else None
        if loc and mgr.set_spawn(point, loc):
            send_arena_msg(sender, "spawn_set", point=point)
        else:
            send_arena_msg(sender, u"{prefix}&cНе удалось установить точку спавна.")
        return True

    elif sub in ["spec", "spectate", "spectator"]:
        if not sender_uuid or not hasattr(sender, "teleport"):
            safe_console_send(u"Console cannot enter spectator mode.")
            return True

        if is_player_in_duel(sender_uuid):
            send_arena_msg(sender, "already_in_fight")
            return True

        mgr = ArenaDataManager()
        spec_loc = mgr.get_spawn_location("spectator")

        if not spec_loc:
            send_arena_msg(sender, u"{prefix}&cТочка спавна наблюдателя не установлена! Установите через &f/arena setspawn spectator")
            return True

        if sender_uuid in active_spectators:
            sender.teleport(spec_loc)
            send_arena_msg(sender, u"{prefix}&aВы перемещены в трибуну наблюдателей арены.")
            return True

        saved_loc = sender.getLocation() if hasattr(sender, "getLocation") else None

        active_spectators[sender_uuid] = {
            "saved_loc": saved_loc
        }

        sender.teleport(spec_loc)
        send_arena_msg(sender, u"{prefix}&aВы перемещены в трибуну наблюдателей. Напишите &f/arena leave&a, чтобы вернуться на прежнее место.")
        return True

    elif sub in ["leave", "quit", "exit"]:
        if not sender_uuid:
            return True

        if sender_uuid in active_spectators:
            spec_data = active_spectators.pop(sender_uuid)

            if spec_data.get("saved_loc") is not None and hasattr(sender, "teleport"):
                try:
                    sender.teleport(spec_data["saved_loc"])
                except Exception as e:
                    log_error(u"Error teleporting back from spectator mode: {0}".format(e))

            send_arena_msg(sender, u"{prefix}&aВы вышли из зоны наблюдения и вернулись на прежнее место.")
            return True

        send_arena_msg(sender, u"{prefix}&cВы не находитесь в зоне наблюдения!")
        return True

    elif sub in ["reload"]:
        if hasattr(sender, "isOp") and not sender.isOp():
            send_arena_msg(sender, u"{prefix}&cУ вас недостаточно прав!")
            return True
        mgr = ArenaDataManager()
        mgr.load_data()
        stats_mgr = PlayerStatsManager()
        stats_mgr.load_data()
        send_arena_msg(sender, u"{prefix}&aКонфиг и статистика арены успешно перезагружены!")
        return True

    else:
        send_arena_msg(sender, "usage")
        return True


# -----------------------------------------------------------------------------
# ТАБ-ОБРАБОТЧИК ДЛЯ PAPER 1.21 (*args UNPACKING)
# -----------------------------------------------------------------------------
def get_cmd_args_from_args(args):
    cmd_args = []
    for a in reversed(args):
        if isinstance(a, (list, tuple)):
            cmd_args = [to_unicode(x) for x in a]
            break
        elif hasattr(a, "__iter__") and not isinstance(a, (str, unicode, type(to_java_string("")))):
            try:
                cmd_args = [to_unicode(x) for x in a]
                break
            except:
                pass
    return cmd_args


def tab_arena(*args):
    cmd_args = get_cmd_args_from_args(args)

    if len(cmd_args) <= 1:
        subcmds = ["request", "accept", "deny", "stats", "profile", "top", "menu", "resetelo", "setspawn", "reload"]
        prefix = cmd_args[0].lower() if len(cmd_args) == 1 else ""
        return build_java_list([s for s in subcmds if s.startswith(prefix)])

    elif len(cmd_args) == 2 and cmd_args[0].lower() in ["request", "req", "duel", "profile", "player", "resetelo"]:
        prefix = cmd_args[1].lower()
        names = []
        if BUKKIT_AVAILABLE:
            for p in Bukkit.getOnlinePlayers():
                p_name = to_unicode(p.getName())
                if p_name.lower().startswith(prefix):
                    names.append(p_name)
        return build_java_list(names)

    elif len(cmd_args) == 3 and cmd_args[0].lower() in ["request", "req", "duel"]:
        prefix = cmd_args[2].lower()
        bets = ["0", "100", "500", "1000", "5000"]
        return build_java_list([b for b in bets if b.startswith(prefix)])

    elif len(cmd_args) == 2 and cmd_args[0].lower() in ["setspawn", "setpoint"]:
        prefix = cmd_args[1].lower()
        points = ["p1", "p2", "spectator"]
        return build_java_list([p for p in points if p.startswith(prefix)])

    return build_java_list([])


# -----------------------------------------------------------------------------
# РЕГИСТРАЦИЯ КОМАНД И СОБЫТИЙ В BUKKIT
# -----------------------------------------------------------------------------
if BUKKIT_AVAILABLE:
    class PyBukkitArenaCommand(Command, TabCompleter):
        def __init__(self, name, description="", usage="", aliases=[], executor=None, completer=None):
            Command.__init__(self, name, description, usage, aliases)
            self.cmd_name = name
            self.executor = executor
            self.completer = completer

        def execute(self, sender, commandLabel, args):
            try:
                if self.executor:
                    return self.executor(sender, commandLabel, list(args))
            except Exception as e:
                log_error(u"Error executing /{0}: {1}".format(self.cmd_name, e))
                import traceback
                traceback.print_exc()
            return True

        def tabComplete(self, *args):
            if self.completer:
                try:
                    res = self.completer(*args)
                    if res is not None:
                        if isinstance(res, (list, tuple)):
                            return build_java_list(res)
                        return res
                except Exception as e:
                    log_error(u"Error in tabComplete: {0}".format(e))
            return build_java_list([])

        def onTabComplete(self, *args):
            return self.tabComplete(*args)
else:
    class PyBukkitArenaCommand(object):
        def __init__(self, name, description="", usage="", aliases=[], executor=None, completer=None):
            self.cmd_name = name
            self.executor = executor
            self.completer = completer


def force_register_bukkit_command(fallback_prefix, cmd_obj, aliases=[]):
    if not BUKKIT_AVAILABLE:
        return
    try:
        server = Bukkit.getServer()
        cmap = None
        if hasattr(server, "getCommandMap"):
            cmap = server.getCommandMap()
        else:
            field = server.getClass().getDeclaredField("commandMap")
            field.setAccessible(True)
            cmap = field.get(server)

        if cmap:
            known_commands = None
            if hasattr(cmap, "getKnownCommands"):
                try:
                    known_commands = cmap.getKnownCommands()
                except Exception:
                    pass

            if known_commands is None:
                curr_cls = cmap.getClass()
                while curr_cls is not None and curr_cls != object:
                    try:
                        f = curr_cls.getDeclaredField("knownCommands")
                        f.setAccessible(True)
                        known_commands = f.get(cmap)
                        break
                    except Exception:
                        curr_cls = curr_cls.getSuperclass()

            if known_commands:
                name = cmd_obj.getName().lower()

                keys_to_remove = []
                iterator = known_commands.keySet().iterator()
                while iterator.hasNext():
                    k = iterator.next()
                    k_str = str(k).lower()
                    if k_str == name or k_str.endswith(":" + name):
                        keys_to_remove.append(k)
                    for alias in aliases:
                        a_str = str(alias).lower()
                        if k_str == a_str or k_str.endswith(":" + a_str):
                            keys_to_remove.append(k)

                for k in keys_to_remove:
                    try:
                        old_cmd = known_commands.get(k)
                        if hasattr(old_cmd, "unregister"):
                            old_cmd.unregister(cmap)
                        known_commands.remove(k)
                    except:
                        pass

                known_commands.put(name, cmd_obj)
                known_commands.put(fallback_prefix + ":" + name, cmd_obj)

                for alias in aliases:
                    a_str = str(alias).lower()
                    alias_cmd = PyBukkitArenaCommand(a_str, cmd_obj.getDescription(), cmd_obj.getUsage(), [], cmd_obj.executor, cmd_obj.completer)
                    known_commands.put(a_str, alias_cmd)
                    known_commands.put(fallback_prefix + ":" + a_str, alias_cmd)

    except Exception as e:
        log_error(u"Error force-registering Bukkit command: {0}".format(e))


registered_arena_commands = []   # (name, aliases) - для полного снятия при выгрузке,
                                  # т.к. эти команды внедрены напрямую в CommandMap в
                                  # обход command_manager PySpigot и PySpigot не может
                                  # их снять сам при /pyspigot unload.


def force_unregister_bukkit_command(fallback_prefix, name, aliases):
    """Симметрична force_register_bukkit_command - снимает команду и её алиасы
    из Bukkit CommandMap."""
    if not BUKKIT_AVAILABLE:
        return
    try:
        server = Bukkit.getServer()
        cmap = None
        if hasattr(server, "getCommandMap"):
            cmap = server.getCommandMap()
        else:
            field = server.getClass().getDeclaredField("commandMap")
            field.setAccessible(True)
            cmap = field.get(server)

        if cmap:
            known_commands = None
            if hasattr(cmap, "getKnownCommands"):
                try:
                    known_commands = cmap.getKnownCommands()
                except Exception:
                    pass

            if known_commands is None:
                curr_cls = cmap.getClass()
                while curr_cls is not None and curr_cls != object:
                    try:
                        f = curr_cls.getDeclaredField("knownCommands")
                        f.setAccessible(True)
                        known_commands = f.get(cmap)
                        break
                    except Exception:
                        curr_cls = curr_cls.getSuperclass()

            if known_commands:
                names = [name] + list(aliases)
                for item_name in names:
                    lowered = str(item_name).lower()
                    for key in [lowered, fallback_prefix + ":" + lowered]:
                        try:
                            old_command = known_commands.get(key)
                            if old_command is not None and hasattr(old_command, "unregister"):
                                old_command.unregister(cmap)
                            known_commands.remove(key)
                        except Exception:
                            pass
    except Exception as e:
        log_error(u"Error force-unregistering Bukkit command: {0}".format(e))


def unregister_arena_commands():
    for name, aliases in list(registered_arena_commands):
        force_unregister_bukkit_command("pyspigot-arena", name, aliases)
    del registered_arena_commands[:]
    try:
        if BUKKIT_AVAILABLE and hasattr(Bukkit.getServer(), "syncCommands"):
            Bukkit.getServer().syncCommands()
    except Exception:
        pass


def register_arena_commands():
    commands_def = [
        ("arena", "Arena PvP System", "/arena <request|accept|deny|stats|profile|top|menu|resetelo|setspawn|reload>", ["pvp", "duel"], cmd_arena, tab_arena)
    ]

    for item in commands_def:
        name, desc, usage, aliases, handler, tab_handler = item[0], item[1], item[2], item[3], item[4], item[5]
        cmd_obj = PyBukkitArenaCommand(name, desc, usage, aliases, handler, tab_handler)
        force_register_bukkit_command("pyspigot-arena", cmd_obj, aliases)
        registered_arena_commands.append((name, aliases))

    log_info(u"Arena commands force-registered in Bukkit CommandMap (/arena, /duel) with TabCompletion.")


# -----------------------------------------------------------------------------
# ЖИЗНЕННЫЙ ЦИКЛ СКРИПТА PYSPIGOT (LIFECYCLE HOOKS)
# -----------------------------------------------------------------------------
def on_enable():
    log_info(u"=== Starting {0} v{1} ===".format(ArenaConfig.PLUGIN_NAME, ArenaConfig.VERSION))
    try:
        unregister_script_listeners()
        mgr = ArenaDataManager()
        stats_mgr = PlayerStatsManager()
        log_info(u"Arena config and players stats loaded ({0} profiles).".format(len(stats_mgr.profiles)))

        if BUKKIT_AVAILABLE:
            register_event_directly(PlayerMoveEvent, on_player_move)
            register_event_directly(EntityDamageEvent, on_entity_damage)
            register_event_directly(PlayerDeathEvent, on_player_death)
            register_event_directly(PlayerRespawnEvent, on_player_respawn)
            register_event_directly(PlayerQuitEvent, on_player_quit)
            register_event_directly(InventoryClickEvent, on_inventory_click)
            log_info(u"Arena events (including InventoryClickEvent) registered directly into Bukkit EventMap.")

        register_arena_commands()
        log_info(u"{0} successfully enabled!".format(ArenaConfig.PLUGIN_NAME))
    except Exception as e:
        log_error(u"Critical error in arena on_enable: {0}".format(e))
        import traceback
        traceback.print_exc()


def on_disable():
    log_info(u"=== Disabling {0} ===".format(ArenaConfig.PLUGIN_NAME))
    unregister_script_listeners()
    unregister_arena_commands()
    if BUKKIT_AVAILABLE:
        for uuid_str in list(player_states.keys()):
            try:
                p = get_online_player_by_uuid_or_name(uuid_str)
                if p and p.isOnline():
                    restore_player_state(p)
            except:
                pass


def start(script=None):
    on_enable()


def stop(script=None):
    # ВАЖНО: PySpigot вызывает автоматически именно stop() (не on_disable()) при
    # /pyspigot unload <script>. Без этой функции on_disable() никогда не выполнялся бы
    # при ручной выгрузке скрипта - команда /arena (внедрённая напрямую в CommandMap в
    # обход command_manager) и все listeners (PlayerMove/EntityDamage/PlayerDeath/
    # PlayerRespawn/PlayerQuit/InventoryClick, зарегистрированные напрямую в обход
    # listener_manager) продолжали бы работать даже после выгрузки скрипта.
    on_disable()


if __name__ == "__main__" or "ps" in globals() or "command_manager" in globals():
    on_enable()

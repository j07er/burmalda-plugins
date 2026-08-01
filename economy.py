# -*- coding: utf-8 -*-
"""
===============================================================================
SmartY-Economy System — ВЕРСИЯ 3.0.0 (PAYDAY & MOB MONEY DROP SYSTEM)
===============================================================================
Команды экономики:
  /bal [ник]                 — Просмотреть баланс (свой или чужой)
  /pay <ник> <сумма>          — Перевести деньги другому игроку
  /eco <give|take|set> ...   — Админ-команды управления балансом (Только /op)
  /showbal [on|off]           — Включить/выключить виджет баланса на экране
  /afk [on|off]               — Включить/выключить AFK-режим
  /baltop                    — Посмотреть топ богатейших игроков
===============================================================================
"""

import os
import sys
import json
import time
import re
import random

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
# ИМПОРТ BUKKIT / PYSPIGOT / JAVA ARRAYLIST
# -----------------------------------------------------------------------------
try:
    from org.bukkit import Bukkit, ChatColor, GameRule, Sound
    from org.bukkit.entity import Player
    from org.bukkit.command import Command, TabCompleter
    from org.bukkit.scoreboard import DisplaySlot
    from org.bukkit.event import Listener, EventPriority
    from org.bukkit.plugin import EventExecutor
    from org.bukkit.event.player import PlayerCommandPreprocessEvent, PlayerInteractEvent, PlayerJoinEvent, PlayerMoveEvent, PlayerQuitEvent
    try:
        from org.bukkit.event.player import AsyncPlayerChatEvent
    except ImportError:
        AsyncPlayerChatEvent = None
    from org.bukkit.event.entity import EntityDeathEvent
    from org.bukkit.event.inventory import InventoryClickEvent
    BUKKIT_AVAILABLE = True
except ImportError:
    BUKKIT_AVAILABLE = False
    GameRule = None
    Command = object
    TabCompleter = object
    DisplaySlot = None
    Listener = object
    EventPriority = None
    EventExecutor = object
    AsyncPlayerChatEvent = None
    PlayerCommandPreprocessEvent = None
    PlayerInteractEvent = None
    Player = object
    PlayerJoinEvent = None
    PlayerMoveEvent = None
    PlayerQuitEvent = None
    EntityDeathEvent = None
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
        except Exception:
            pass

    if isinstance(text, str):
        try:
            return text.decode("utf-8")
        except Exception:
            try:
                return text.decode("cp1251")
            except Exception:
                return unicode(text, "utf-8", "ignore")

    return unicode(str(text))


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
            return JavaString(u_text)
        except Exception:
            pass
    return text


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
        except Exception:
            pass
    print("[SmartY-Economy] " + str(text))


def log_info(text):
    safe_console_send(u"&a[SmartY-Economy] &a[INFO] " + to_unicode(text))


def log_error(text):
    safe_console_send(u"&a[SmartY-Economy] &c[ERROR] " + to_unicode(text))


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
    except (ValueError, TypeError):
        return u"0$"


def safe_amount(amount, default=0.0):
    u"""
    ЗАЩИТА ОТ NaN/Infinity (фикс дыры дублирования баланса).
    Раньше float("nan") и float("inf") проходили ЛЮБЫЕ проверки вида
    "balance < amount" или "amount <= 0" (сравнения с NaN всегда False),
    а min()/max() с NaN на некоторых порядках аргументов не отсекают NaN
    (например min(MAX_BALANCE, x + nan) == MAX_BALANCE).
    Эта функция — единая точка входа: любое некорректное число превращается
    в безопасный default ДО того, как попадёт в баланс/банк джекпота.
    """
    try:
        val = float(amount)
    except (ValueError, TypeError):
        return default
    # val != val истинно ТОЛЬКО для NaN (стандартный питон-трюк без math.isnan)
    if val != val:
        return default
    if val == float("inf") or val == float("-inf"):
        return default
    return val


# -----------------------------------------------------------------------------
# ГЛОБАЛЬНЫЕ НАСТРОЙКИ И СООБЩЕНИЯ ЭКОНОМИКИ
# -----------------------------------------------------------------------------
class EconomyConfig:
    PLUGIN_NAME = u"SmartY-Economy"
    VERSION = u"3.5.0"
    PREFIX = u"&a&l[\u042d\u043a\u043e\u043d\u043e\u043c\u0438\u043a\u0430]&r "

    DEFAULT_BALANCE = 100.0
    MIN_BALANCE = 0.0
    MAX_BALANCE = 10000000000000000.0
    DEFAULT_PAYDAY_AMOUNT = 1000.0
    PAYDAY_INTERVAL_SECONDS = 3600.0
    AFK_TIMEOUT_SECONDS = 600.0
    AFK_CHECK_PERIOD_TICKS = 100

    SCRIPT_DIR = get_script_dir()
    DATA_DIR = os.path.join(SCRIPT_DIR, "data")
    DB_FILE = os.path.join(DATA_DIR, "economy.json")
    TOWNS_FILE = os.path.join(DATA_DIR, "cities.json")
    COMPANIES_FILE = os.path.join(DATA_DIR, "companies.json")
    TRANSACTIONS_LOG = os.path.join(DATA_DIR, "economy_transactions.log")

    # Порог "неактивности" для payday (сек). Игрок должен был сдвинуться
    # в течение этого окна, иначе прогресс payday замирает. Настраивается
    # через /eco afk-threshold <секунды>.
    DEFAULT_PAYDAY_INACTIVITY = 60.0

    # Baltop cache TTL (сек) — топ-10 пересчитывается раз в X сек.
    BALTOP_CACHE_TTL = 300.0

    MESSAGES = {
        "balance_self": u"{prefix}&7Ваш текущий баланс: &a{formatted_balance}",
        "balance_other": u"{prefix}&7Баланс игрока &e{player}&7: &a{formatted_balance}",
        "pay_success_sender": u"{prefix}&7Вы успешно перевели &a{formatted_amount} &7игроку &e{target}&7. Ваш новый баланс: &a{formatted_balance}",
        "pay_success_receiver": u"{prefix}&7Вам поступил перевод &a{formatted_amount} &7от игрока &e{sender}&7!",
        "pay_self": u"{prefix}&cВы не можете перевести деньги самому себе!",
        "invalid_amount": u"{prefix}&cУкажите корректную положительную сумму!",
        "insufficient_funds": u"{prefix}&cУ вас недостаточно средств! Ваш баланс: &a{formatted_balance}",
        "player_not_found": u"{prefix}&cИгрок &e{player} &cне найден в базе данных экономики.",
        "eco_give": u"{prefix}&7Вы выдали &a{formatted_amount} &7игроку &e{target}&7. Новый баланс: &a{formatted_balance}",
        "eco_take": u"{prefix}&7Вы забрали &c{formatted_amount} &7у игрока &e{target}&7. Новый баланс: &a{formatted_balance}",
        "eco_set": u"{prefix}&7Вы установили баланс игрока &e{target} &7на &a{formatted_balance}",
        "hud_toggled": u"{prefix}&7HUD справа: {status}",
        "afk_enabled": u"&8{player} отошел.",
        "afk_disabled": u"&8{player} вернулся.",
        "usage_afk": u"{prefix}&cИспользование: &f/afk [on|off]",
        "payday_status": u"{prefix}&7Payday: &e{amount} &7каждые &e60 минут &7онлайн-времени.",
        "payday_fixed_notice": u"{prefix}&7Сумма Payday зафиксирована и не настраивается: &e{amount}&7 каждые 60 минут онлайн-времени.",
        "payday_all": u"{prefix}&7Payday &e{amount} &7выдан всем аккаунтам: &a{count}&7.",
        "payday_received": u"{prefix}&aВы получили payday &e{amount}&a за &e60 минут&a онлайн-времени! &7Баланс: &e{balance}",
        "baltop_header": u"&6&m-------&r &e&lТОП БОГАТЕЙШИХ ИГРОКОВ &6&m-------",
        "baltop_entry": u"&e{rank}. &f{player} &7— &a{formatted_balance}",
        "baltop_footer": u"&6&m---------------------------------------",
        "usage_pay": u"{prefix}&cИспользование: &f/pay <ник> <сумма>",
        "usage_eco": u"{prefix}&cИспользование: &f/eco <give|take|set|reset|afk-threshold|sleep-default> ...",
        "usage_showbal": u"{prefix}&cИспользование: &f/hud [on|off] &7или &f/showbal [on|off]",
        "usage_payday": u"{prefix}&cИспользование: &f/payday <status|set|all>",
        "no_permission": u"{prefix}&cУ вас нет прав на использование этой команды!"
    }


# -----------------------------------------------------------------------------
# TRANSACTION LOG — журнал всех финансовых операций
# -----------------------------------------------------------------------------
# Пишет строку TSV в economy_transactions.log:
#   TIMESTAMP  TYPE  FROM  TO  AMOUNT  NEW_BAL_FROM  NEW_BAL_TO  REASON
#
#   TYPE ∈ {PAY, DEPOSIT, WITHDRAW, SET, PAYDAY, MOB_KILL, SYSTEM}
#
# Легко парсится awk/grep, читается глазами.

def log_transaction(tx_type, from_name, to_name, amount, reason=u"",
                    new_bal_from=None, new_bal_to=None):
    try:
        import io as _io
        if not os.path.exists(EconomyConfig.DATA_DIR):
            try: os.makedirs(EconomyConfig.DATA_DIR)
            except Exception: pass
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        parts = [
            ts,
            unicode(tx_type),
            unicode(from_name if from_name else u"-"),
            unicode(to_name if to_name else u"-"),
            u"%.2f" % float(amount),
            (u"%.2f" % float(new_bal_from)) if new_bal_from is not None else u"-",
            (u"%.2f" % float(new_bal_to))   if new_bal_to   is not None else u"-",
            unicode(reason if reason else u"-").replace(u"\t", u" ").replace(u"\n", u" "),
        ]
        line = u"\t".join(parts) + u"\n"
        f = _io.open(EconomyConfig.TRANSACTIONS_LOG, "a", encoding="utf-8")
        try:
            if isinstance(line, str):
                line = line.decode("utf-8", "replace")
            f.write(line)
        finally:
            f.close()
    except Exception as e:
        try:
            log_error(u"Failed to write transaction log: {0}".format(e))
        except Exception:
            pass


# -----------------------------------------------------------------------------
# BALTOP CACHE — сортировка TOP-10 может быть тяжёлой на большой базе.
# Кэшируем результат на BALTOP_CACHE_TTL секунд, обновляем лениво.
# -----------------------------------------------------------------------------
_baltop_cache = {"data": [], "ts": 0.0}


def get_baltop_cached(limit=10):
    now = time.time()
    if now - _baltop_cache["ts"] < EconomyConfig.BALTOP_CACHE_TTL and _baltop_cache["data"]:
        return _baltop_cache["data"][:limit]
    try:
        eco = EconomyManager()
        sorted_accs = sorted(eco.accounts.values(), key=lambda a: a.balance, reverse=True)[:limit]
        # Сохраняем tuple(name, balance) — чтобы не держать ссылки на аккаунты.
        _baltop_cache["data"] = [(acc.name, acc.balance) for acc in sorted_accs]
        _baltop_cache["ts"] = now
        return _baltop_cache["data"][:limit]
    except Exception as e:
        log_error(u"baltop cache rebuild failed: {0}".format(e))
        return []


def invalidate_baltop_cache():
    _baltop_cache["ts"] = 0.0


# СБАЛАНСИРОВАННАЯ ТАБЛИЦА НАГРАД ЗА УБИЙСТВО МОБОВ (мин, макс, босс?)
MOB_REWARDS = {
    # Боссы
    "ENDER_DRAGON": (1000.0, 2000.0, True),
    "WITHER": (500.0, 1000.0, True),
    "ELDER_GUARDIAN": (100.0, 200.0, False),
    "RAVAGER": (50.0, 100.0, False),

    # Адские монстры
    "WITHER_SKELETON": (10.0, 20.0, False),
    "BLAZE": (5.0, 10.0, False),
    "GHAST": (8.0, 15.0, False),
    "ZOMBIFIED_PIGLIN": (2.0, 4.0, False),
    "PIGLIN": (3.0, 6.0, False),
    "PIGLIN_BRUTE": (8.0, 15.0, False),
    "MAGMA_CUBE": (2.0, 5.0, False),

    # Враждебные мобы
    "CREEPER": (6.0, 12.0, False),
    "ENDERMAN": (8.0, 15.0, False),
    "WITCH": (8.0, 15.0, False),
    "GUARDIAN": (6.0, 12.0, False),
    "PHANTOM": (5.0, 10.0, False),

    # Обычные монстры
    "ZOMBIE": (3.0, 6.0, False),
    "ZOMBIE_VILLAGER": (3.0, 6.0, False),
    "DROWNED": (3.0, 6.0, False),
    "HUSK": (3.0, 6.0, False),
    "SKELETON": (3.0, 6.0, False),
    "STRAY": (3.0, 6.0, False),
    "SPIDER": (3.0, 5.0, False),
    "CAVE_SPIDER": (3.0, 5.0, False),
    "SLIME": (2.0, 4.0, False),

    # Мирные мобы
    "COW": (2.0, 5.0, False),
    "PIG": (2.0, 4.0, False),
    "SHEEP": (2.0, 4.0, False),
    "CHICKEN": (1.0, 3.0, False),
    "RABBIT": (1.0, 3.0, False),
}

MOB_DISPLAY_NAMES = {
    "ZOMBIE": u"Зомби",
    "SKELETON": u"Скелета",
    "CREEPER": u"Крипера",
    "ENDERMAN": u"Эндермена",
    "SPIDER": u"Паука",
    "WITCH": u"Ведьму",
    "COW": u"Корову",
    "PIG": u"Свинью",
    "SHEEP": u"Овцу",
    "CHICKEN": u"Курицу",
    "ZOMBIFIED_PIGLIN": u"Свинозомби",
    "WITHER_SKELETON": u"Иссушителя-скелета",
    "WITHER": u"Иссушителя",
    "ENDER_DRAGON": u"Эндер-Дракона"
}


def send_message(recipient, key, **kwargs):
    if key in EconomyConfig.MESSAGES:
        raw = EconomyConfig.MESSAGES[key]
    else:
        raw = to_unicode(key)

    fmt_args = {"prefix": EconomyConfig.PREFIX}
    for k, v in kwargs.items():
        fmt_args[k] = to_unicode(v)

    try:
        text = raw.format(**fmt_args)
    except Exception:
        text = raw

    colored = colorize(text)
    if recipient is not None:
        if hasattr(recipient, "sendMessage"):
            recipient.sendMessage(to_java_string(colored))
        else:
            safe_console_send(colored)


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


# -----------------------------------------------------------------------------
# МЕНЕДЖЕР ДАННЫХ И МОДЕЛИ ИГРОКОВ
# -----------------------------------------------------------------------------
class Account(object):
    def __init__(self, uuid_str, name, balance=None, show_hud=False, last_seen=None, playtime_minutes=0,
                 last_payday_timestamp=0.0, payday_progress_seconds=None, last_payday_check_timestamp=0.0):
        self.uuid = str(uuid_str)
        self.name = to_unicode(name)
        # ФИКС: если баланс в JSON битый (NaN/Infinity — например от старой версии
        # плагина до патча), откатываемся на DEFAULT_BALANCE вместо застревания в NaN.
        self.balance = safe_amount(balance, default=float(EconomyConfig.DEFAULT_BALANCE)) if balance is not None else float(EconomyConfig.DEFAULT_BALANCE)
        self.show_hud = bool(show_hud)
        self.last_seen = int(last_seen) if last_seen else int(time.time())
        if payday_progress_seconds is None:
            payday_progress_seconds = float(int(playtime_minutes) * 60) if playtime_minutes else 0.0
        self.payday_progress_seconds = max(0.0, float(payday_progress_seconds))
        self.playtime_minutes = int(self.payday_progress_seconds // 60)
        self.last_payday_timestamp = float(last_payday_timestamp) if last_payday_timestamp else 0.0
        self.last_payday_check_timestamp = float(last_payday_check_timestamp) if last_payday_check_timestamp else 0.0

    def to_dict(self):
        self.playtime_minutes = int(self.payday_progress_seconds // 60)
        return {
            "uuid": self.uuid,
            "name": self.name,
            "balance": round(self.balance, 2),
            "show_hud": self.show_hud,
            "last_seen": self.last_seen,
            "playtime_minutes": self.playtime_minutes,
            "payday_progress_seconds": round(self.payday_progress_seconds, 2),
            "last_payday_timestamp": self.last_payday_timestamp,
            "last_payday_check_timestamp": self.last_payday_check_timestamp
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            uuid_str=data.get("uuid"),
            name=data.get("name", u"Unknown"),
            balance=data.get("balance", EconomyConfig.DEFAULT_BALANCE),
            show_hud=data.get("show_hud", False),
            last_seen=data.get("last_seen", int(time.time())),
            playtime_minutes=data.get("playtime_minutes", 0),
            last_payday_timestamp=data.get("last_payday_timestamp", 0.0),
            payday_progress_seconds=data.get("payday_progress_seconds"),
            last_payday_check_timestamp=data.get("last_payday_check_timestamp", 0.0)
        )

    def update_last_seen(self, name=None):
        if name:
            self.name = to_unicode(name)
        self.last_seen = int(time.time())


class EconomyManager(object):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EconomyManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.accounts = {}
        self.name_to_uuid = {}
        self.jackpot_bank = 0.0
        self.payday_amount = float(EconomyConfig.DEFAULT_PAYDAY_AMOUNT)
        # Порог неактивности для payday — модифицируется командой /eco afk-threshold.
        self.payday_afk_threshold = float(EconomyConfig.DEFAULT_PAYDAY_INACTIVITY)
        # Истинный дефолт PLAYERS_SLEEPING_PERCENTAGE per-world. Настраивается
        # через /eco sleep-default. Хранится в JSON, чтобы переживать релоад.
        # world_name -> percent (1..100)
        self.sleep_defaults = {}
        self.load_database()

    def load_database(self):
        self.accounts.clear()
        self.name_to_uuid.clear()

        if not os.path.exists(EconomyConfig.DATA_DIR):
            try:
                os.makedirs(EconomyConfig.DATA_DIR)
            except Exception:
                pass

        if not os.path.exists(EconomyConfig.DB_FILE):
            self.save_database()
            return

        try:
            with open(EconomyConfig.DB_FILE, "r") as f:
                data = json.load(f)
                # ФИКС: если в старом JSON уже успел сохраниться NaN (баг до патча),
                # при загрузке банк сбрасывается на 0.0 вместо застревания в NaN навсегда.
                self.jackpot_bank = safe_amount(data.get("jackpot_bank", 0.0), default=0.0)
                self.payday_amount = float(data.get("payday_amount", EconomyConfig.DEFAULT_PAYDAY_AMOUNT))
                self.payday_afk_threshold = float(data.get("payday_afk_threshold", EconomyConfig.DEFAULT_PAYDAY_INACTIVITY))
                sd_raw = data.get("sleep_defaults", {}) or {}
                if isinstance(sd_raw, dict):
                    for wn, pct in sd_raw.items():
                        try:
                            self.sleep_defaults[to_unicode(wn)] = max(1, min(100, int(pct)))
                        except Exception:
                            pass
                accs = data.get("accounts", {})
                for uuid_str, acc_dict in accs.items():
                    acc = Account.from_dict(acc_dict)
                    self.accounts[uuid_str] = acc
                    if acc.name:
                        self.name_to_uuid[acc.name.lower()] = uuid_str
        except Exception as e:
            log_error(u"Error reading economy.json: {0}".format(e))

    def save_database(self):
        try:
            if not os.path.exists(EconomyConfig.DATA_DIR):
                os.makedirs(EconomyConfig.DATA_DIR)

            data_to_write = {
                "jackpot_bank": self.jackpot_bank,
                "payday_amount": round(float(self.payday_amount), 2),
                "payday_afk_threshold": round(float(self.payday_afk_threshold), 1),
                "sleep_defaults": {str(wn): int(pct) for wn, pct in self.sleep_defaults.items()},
                "accounts": {uuid_str: acc.to_dict() for uuid_str, acc in self.accounts.items()}
            }

            temp_file = EconomyConfig.DB_FILE + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(data_to_write, f, indent=2, ensure_ascii=False)

            if hasattr(os, "replace"):
                os.replace(temp_file, EconomyConfig.DB_FILE)
            else:
                if os.path.exists(EconomyConfig.DB_FILE):
                    try:
                        os.remove(EconomyConfig.DB_FILE)
                    except Exception:
                        pass
                os.rename(temp_file, EconomyConfig.DB_FILE)
        except Exception as e:
            log_error(u"Error saving economy.json: {0}".format(e))

    def get_or_create_account(self, uuid_str, name):
        uuid_key = str(uuid_str)
        unicode_name = to_unicode(name)

        if uuid_key in self.accounts:
            acc = self.accounts[uuid_key]
            acc.update_last_seen(unicode_name)
            if unicode_name and unicode_name != u"Unknown":
                self.name_to_uuid[unicode_name.lower()] = uuid_key
            return acc
        else:
            acc = Account(uuid_key, unicode_name)
            self.accounts[uuid_key] = acc
            if unicode_name and unicode_name != u"Unknown":
                self.name_to_uuid[unicode_name.lower()] = uuid_key
            self.save_database()
            return acc

    def get_account_by_name(self, name):
        if not name:
            return None
        lower_name = to_unicode(name).lower()
        uuid_key = self.name_to_uuid.get(lower_name)
        if uuid_key and uuid_key in self.accounts:
            return self.accounts[uuid_key]

        for acc in self.accounts.values():
            if acc.name and acc.name.lower() == lower_name:
                self.name_to_uuid[lower_name] = acc.uuid
                return acc

        if BUKKIT_AVAILABLE:
            try:
                for p in Bukkit.getOnlinePlayers():
                    if p.getName().lower() == lower_name:
                        return self.get_or_create_account(str(p.getUniqueId()), p.getName())
            except Exception:
                pass

        return None

    def get_balance(self, uuid_str):
        acc = self.accounts.get(str(uuid_str))
        return acc.balance if acc else 0.0

    def has_enough(self, uuid_str, amount):
        # ФИКС: safe_amount() отсекает NaN/Infinity ДО сравнения. Без этого
        # "balance >= float('nan')" всегда False, но некоторые вызовы этот
        # False молча игнорировали выше по стеку (см. casino.py) — теперь
        # такая "ставка" считается некорректной (0.0) на самом раннем этапе.
        safe = safe_amount(amount, default=None)
        if safe is None:
            return False
        return self.get_balance(uuid_str) >= safe

    def deposit(self, uuid_str, amount, name=None):
        # ФИКС дыры дублирования денег (NaN -> MAX_BALANCE): раньше
        # min(MAX_BALANCE, balance + float('nan')) возвращал MAX_BALANCE
        # из-за особенностей сравнения Python с NaN внутри min(). Теперь
        # некорректная сумма превращается в 0.0 ДО арифметики.
        safe = safe_amount(amount, default=0.0)
        acc = self.get_or_create_account(uuid_str, name if name else u"Unknown")
        acc.balance = min(EconomyConfig.MAX_BALANCE, acc.balance + safe)
        self.save_database()
        update_online_player_hud(uuid_str)
        invalidate_baltop_cache()
        return acc.balance

    def withdraw(self, uuid_str, amount):
        uuid_key = str(uuid_str)
        # ФИКС: has_enough() теперь сам отсекает NaN/Infinity, поэтому
        # withdraw(nan) корректно вернет False и баланс не пострадает.
        if not self.has_enough(uuid_key, amount):
            return False
        safe = safe_amount(amount, default=0.0)
        acc = self.accounts[uuid_key]
        acc.balance = max(EconomyConfig.MIN_BALANCE, acc.balance - safe)
        self.save_database()
        update_online_player_hud(uuid_key)
        invalidate_baltop_cache()
        return True

    def set_balance(self, uuid_str, amount, name=None):
        safe = safe_amount(amount, default=EconomyConfig.MIN_BALANCE)
        acc = self.get_or_create_account(uuid_str, name if name else u"Unknown")
        acc.balance = max(EconomyConfig.MIN_BALANCE, min(EconomyConfig.MAX_BALANCE, safe))
        self.save_database()
        update_online_player_hud(uuid_str)
        invalidate_baltop_cache()
        return acc.balance

    def get_payday_amount(self):
        # ФИКС "большой Payday": сумма зафиксирована жёстко и не читается из
        # self.payday_amount / JSON — раньше её можно было раздуть командой
        # /payday set <сумма> (или испортить старым NaN-багом до патча).
        # Теперь Payday гарантированно = EconomyConfig.DEFAULT_PAYDAY_AMOUNT
        # (1000$), что бы ни было записано в economy.json.
        return float(EconomyConfig.DEFAULT_PAYDAY_AMOUNT)

    def set_payday_amount(self, amount):
        # ФИКС: изменение суммы Payday отключено — она зафиксирована на 1000$
        # (см. get_payday_amount()). Функция оставлена как no-op ради обратной
        # совместимости с существующими вызовами /payday set, чтобы не падать
        # с ошибкой, но реального эффекта на выплату она больше не имеет.
        return float(EconomyConfig.DEFAULT_PAYDAY_AMOUNT)

    def add_to_jackpot(self, amount):
        # ФИКС: раньше "self.jackpot_bank += float('nan')" НАВСЕГДА портил
        # банк джекпота в NaN — банк уже никогда не восстанавливался, а
        # следующий выигрыш джекпота выплачивал бы NaN (->MAX_BALANCE игроку).
        safe = safe_amount(amount, default=0.0)
        self.jackpot_bank = safe_amount(self.jackpot_bank + safe, default=self.jackpot_bank)
        self.save_database()
        return self.jackpot_bank

    def claim_jackpot(self, bet):
        safe_bet = safe_amount(bet, default=0.0)
        safe_bank = safe_amount(self.jackpot_bank, default=0.0)
        payout = safe_bet + safe_bank
        self.jackpot_bank = 0.0
        self.save_database()
        return payout


def get_sender_uuid_and_name(sender):
    if sender is None:
        return None, u"Console"
    name = u"Unknown"
    if hasattr(sender, "getName"):
        try:
            name = to_unicode(sender.getName())
        except Exception:
            pass
    uuid_str = None
    if hasattr(sender, "getUniqueId"):
        try:
            u_obj = sender.getUniqueId()
            if u_obj:
                uuid_str = str(u_obj)
        except Exception:
            pass
    return uuid_str, name


def get_online_player_by_uuid(uuid_str):
    if not BUKKIT_AVAILABLE or not uuid_str:
        return None
    try:
        for player in Bukkit.getOnlinePlayers():
            if str(player.getUniqueId()) == str(uuid_str):
                return player
    except Exception:
        pass
    return None


def update_online_player_hud(uuid_str):
    player = get_online_player_by_uuid(uuid_str)
    if player is not None:
        update_balance_hud(player)


try:
    from net.kyori.adventure.text.serializer.legacy import LegacyComponentSerializer
    ADVENTURE_AVAILABLE = True
except ImportError:
    ADVENTURE_AVAILABLE = False


def create_component(text):
    if text is None:
        text = u""
    u_text = to_unicode(text)
    colored = colorize(u_text)
    j_str = to_java_string(colored)

    if ADVENTURE_AVAILABLE:
        try:
            return LegacyComponentSerializer.legacySection().deserialize(j_str)
        except Exception:
            try:
                return LegacyComponentSerializer.legacyAmpersand().deserialize(to_java_string(u_text))
            except Exception:
                pass

    return j_str





# -----------------------------------------------------------------------------
# ПЕРСОНАЛЬНЫЙ ЕЖЕЧАСОВОЙ БОНУС (60 МИНУТ НАИГРАННОГО ВРЕМЕНИ ИГРОКА)
# -----------------------------------------------------------------------------
payday_task_id = -1
afk_task_id = -1
hud_task_id = -1


# ФИКС "большой payday": до исправления бага с /pyspigot unload у этого скрипта не было
# stop(), поэтому каждая перезагрузка скрипта (релоад, повторная загрузка и т.п.)
# ОСТАВЛЯЛа старый PaydayRunnable живым и запускала второй поверх него.
# Два независимых таймера независимо начисляли payday каждый час игроку —
# эффективно удваивая (или умножая) сумму payday. Сейчас это исправлено через
# сам факт добавления stop() (см. конец файла), но дополнительно добавлена
# страховка на JVM-уровне: ID активных таймеров хранятся в System.getProperties()
# (переживает перезагрузку Python-модуля, в отличие от обычных глобальных
# переменных, которые обнуляются при каждой перезагрузке скрипта). Перед запуском
# нового таймера всегда отменяется любой старый, если он ещё "жив" в этой JVM.
_SYS_PROP_PAYDAY_TASK = u"SmartY_Economy_PaydayTaskId"
_SYS_PROP_AFK_TASK = u"SmartY_Economy_AfkTaskId"
_SYS_PROP_HUD_TASK = u"SmartY_Economy_HudTaskId"


def _cancel_stale_task_by_system_property(prop_key):
    u"""Отменяет старый таймер по ID, сохранённому в System-свойствах
    от ПРЕДЫДУЩЕГО запуска этого же скрипта (возможно из старой версии
    модуля до релоада). Безопасно вызвать даже если таймер уже отменён.
    """
    if not BUKKIT_AVAILABLE or not JAVA_STRING_AVAILABLE or System is None:
        return
    try:
        props = System.getProperties()
        raw = props.get(prop_key)
        if raw is not None:
            try:
                stale_id = int(str(raw))
                if stale_id != -1:
                    Bukkit.getScheduler().cancelTask(stale_id)
                    log_info(u"Cancelled stale task from previous script load (property={0}, id={1}).".format(prop_key, stale_id))
            except Exception:
                pass
    except Exception:
        pass


def _store_task_id_in_system_property(prop_key, task_id):
    if not JAVA_STRING_AVAILABLE or System is None:
        return
    try:
        System.getProperties().put(prop_key, str(task_id))
    except Exception:
        pass
afk_players = {}
last_activity = {}
last_location_keys = {}
default_sleep_percentages = {}


def get_location_key(location):
    if location is None:
        return None
    try:
        world_name = to_unicode(location.getWorld().getName())
        return (world_name, int(location.getBlockX()), int(location.getBlockY()), int(location.getBlockZ()))
    except Exception:
        return None


def broadcast_plain(message):
    line = colorize(message)
    if BUKKIT_AVAILABLE:
        try:
            Bukkit.broadcastMessage(to_java_string(line))
            return
        except Exception:
            pass
    safe_console_send(line)


def is_player_afk(player):
    if player is None:
        return False
    try:
        return bool(afk_players.get(str(player.getUniqueId()), False))
    except Exception:
        return False


def _get_sleep_default(world_name):
    """Priority: EconomyManager.sleep_defaults > runtime cache > 100."""
    try:
        eco = EconomyManager()
        val = eco.sleep_defaults.get(to_unicode(world_name))
        if val is not None:
            return max(1, min(100, int(val)))
    except Exception:
        pass
    val = default_sleep_percentages.get(to_unicode(world_name))
    if val is not None:
        try:
            return max(1, min(100, int(val)))
        except Exception:
            pass
    return 100


def refresh_sleep_rules():
    if not BUKKIT_AVAILABLE or GameRule is None:
        return
    try:
        worlds = Bukkit.getWorlds()
        for world in worlds:
            players = list(world.getPlayers())
            total = len(players)
            if total <= 0:
                restore_sleep_rule(world)
                continue
            active = 0
            for player in players:
                if not is_player_afk(player):
                    active += 1
            if active <= 0:
                percent = 1
            else:
                default_percent = _get_sleep_default(world.getName())
                active_sleepers = int((active * default_percent + 99) / 100)
                active_sleepers = max(1, active_sleepers)
                percent = int((active_sleepers * 100 + total - 1) / total)
                percent = max(1, min(100, percent))
            try:
                cur = int(world.getGameRuleValue(GameRule.PLAYERS_SLEEPING_PERCENTAGE))
            except Exception:
                cur = -1
            if cur != percent:
                world.setGameRule(GameRule.PLAYERS_SLEEPING_PERCENTAGE, percent)
    except Exception as e:
        log_error(u"Error refreshing sleep rules: {0}".format(e))


def capture_default_sleep_rules():
    """
    Reads gamerule for each world and stores as 'true default' ONLY if the
    admin has not set an explicit value via /eco sleep-default. So on first
    load we capture vanilla defaults, later we use whatever admin configured.
    """
    if not BUKKIT_AVAILABLE or GameRule is None:
        return
    try:
        eco = EconomyManager()
    except Exception:
        eco = None
    try:
        for world in Bukkit.getWorlds():
            name = to_unicode(world.getName())
            if eco is not None and name in eco.sleep_defaults:
                default_sleep_percentages[name] = int(eco.sleep_defaults[name])
                continue
            if name in default_sleep_percentages:
                continue
            value = world.getGameRuleValue(GameRule.PLAYERS_SLEEPING_PERCENTAGE)
            default_sleep_percentages[name] = int(value)
    except Exception:
        pass


def restore_sleep_rule(world):
    if not BUKKIT_AVAILABLE or GameRule is None or world is None:
        return
    try:
        name = to_unicode(world.getName())
        value = _get_sleep_default(name)
        try:
            cur = int(world.getGameRuleValue(GameRule.PLAYERS_SLEEPING_PERCENTAGE))
        except Exception:
            cur = -1
        if cur != value:
            world.setGameRule(GameRule.PLAYERS_SLEEPING_PERCENTAGE, value)
    except Exception:
        pass


def restore_all_sleep_rules():
    if not BUKKIT_AVAILABLE:
        return
    try:
        for world in Bukkit.getWorlds():
            restore_sleep_rule(world)
    except Exception:
        pass


def set_sleep_default_for_world(world_name, percent):
    """Explicit admin setting. Writes to EconomyManager + applies immediately."""
    try:
        percent = max(1, min(100, int(percent)))
        eco = EconomyManager()
        eco.sleep_defaults[to_unicode(world_name)] = percent
        default_sleep_percentages[to_unicode(world_name)] = percent
        eco.save_database()
        if BUKKIT_AVAILABLE and GameRule is not None:
            w = Bukkit.getWorld(to_java_string(world_name))
            if w is not None:
                restore_sleep_rule(w)
                refresh_sleep_rules()
        return True
    except Exception as e:
        log_error(u"set_sleep_default_for_world failed: {0}".format(e))
        return False



def set_player_afk(player, value, automatic=False):
    if not BUKKIT_AVAILABLE or player is None:
        return False
    try:
        uuid_str, name = get_sender_uuid_and_name(player)
        if not uuid_str:
            return False
        current = bool(afk_players.get(uuid_str, False))
        value = bool(value)
        if current == value:
            return False

        now = time.time()
        economy = EconomyManager()
        if value:
            process_player_payday(economy, player, now, False)
            acc = economy.get_or_create_account(uuid_str, name)
            acc.last_payday_check_timestamp = now
            economy.save_database()
            afk_players[uuid_str] = True
            broadcast_plain(EconomyConfig.MESSAGES["afk_enabled"].format(player=name))
        else:
            afk_players.pop(uuid_str, None)
            last_activity[uuid_str] = now
            last_location_keys[uuid_str] = get_location_key(player.getLocation())
            acc = economy.get_or_create_account(uuid_str, name)
            acc.last_payday_check_timestamp = now
            economy.save_database()
            broadcast_plain(EconomyConfig.MESSAGES["afk_disabled"].format(player=name))
        refresh_sleep_rules()
        return True
    except Exception as e:
        log_error(u"Error changing AFK state: {0}".format(e))
        return False


def mark_player_active(player, force=False):
    if not BUKKIT_AVAILABLE or player is None:
        return
    try:
        uuid_str, name = get_sender_uuid_and_name(player)
        if not uuid_str:
            return
        last_activity[uuid_str] = time.time()
        last_location_keys[uuid_str] = get_location_key(player.getLocation())
        if force and is_player_afk(player):
            set_player_afk(player, False, False)
    except Exception:
        pass


class AfkRunnable(Runnable):
    def run(self):
        try:
            now = time.time()
            for player in Bukkit.getOnlinePlayers():
                if not player or not player.isOnline():
                    continue
                uuid_str, name = get_sender_uuid_and_name(player)
                if not uuid_str:
                    continue
                if uuid_str not in last_activity:
                    last_activity[uuid_str] = now
                    last_location_keys[uuid_str] = get_location_key(player.getLocation())
                    continue
                if is_player_afk(player):
                    continue
                if now - float(last_activity.get(uuid_str, now)) >= EconomyConfig.AFK_TIMEOUT_SECONDS:
                    set_player_afk(player, True, True)
            refresh_sleep_rules()
        except Exception as e:
            log_error(u"Error in AfkRunnable: {0}".format(e))


def create_scoreboard_objective(board, name, criteria, display_name):
    try:
        return board.registerNewObjective(to_java_string(name), to_java_string(criteria), to_java_string(display_name))
    except Exception:
        objective = board.registerNewObjective(to_java_string(name), to_java_string(criteria))
        objective.setDisplayName(to_java_string(display_name))
        return objective


def clear_balance_hud(player):
    if not BUKKIT_AVAILABLE or player is None:
        return
    try:
        main_board = Bukkit.getScoreboardManager().getMainScoreboard()
        player.setScoreboard(main_board)
    except Exception as e:
        log_error(u"Error clearing balance HUD: {0}".format(e))


def read_json_file(path, default_value):
    if not os.path.exists(path):
        return default_value
    try:
        with open(path, "r") as handle:
            return json.load(handle)
    except Exception:
        return default_value


def get_player_town_name(uuid_str):
    data = read_json_file(EconomyConfig.TOWNS_FILE, {"cities": {}})
    for city in data.get("cities", {}).values():
        if str(uuid_str) in city.get("members", {}):
            return to_unicode(city.get("name", u"-"))
    return u"-"


def get_player_town_profile(uuid_str):
    data = read_json_file(EconomyConfig.TOWNS_FILE, {"cities": {}})
    for city in data.get("cities", {}).values():
        if str(uuid_str) not in city.get("members", {}):
            continue
        roles = city.get("member_roles", {}).get(str(uuid_str), [])
        if str(city.get("mayor_uuid")) == str(uuid_str):
            role_key = "mayor"
        elif roles:
            role_key = roles[0]
        else:
            role_key = "citizen"
        role_data = city.get("roles", {}).get(role_key, {})
        if isinstance(role_data, dict):
            role_name = to_unicode(role_data.get("display", role_key))
        else:
            role_name = to_unicode(role_key).capitalize()
        return to_unicode(city.get("name", u"-")), role_name
    return u"-", u"-"


def get_company_share_price(company):
    try:
        available = int(company.get("available_shares", 10000))
        start_price = float(company.get("start_price", 10.0))
        backing = float(company.get("balance", 0.0)) + float(available) * start_price
        return max(1.0, round(backing / 10000.0, 2))
    except Exception:
        return 0.0


def get_portfolio_value(uuid_str):
    total = 0.0
    data = read_json_file(EconomyConfig.COMPANIES_FILE, {"companies": {}})
    for company in data.get("companies", {}).values():
        shares = int(company.get("shares", {}).get(str(uuid_str), 0))
        if shares > 0:
            total += get_company_share_price(company) * shares
    return round(total, 2)


def set_hud_score(objective, text, score):
    objective.getScore(to_java_string(colorize(text))).setScore(int(score))


def update_balance_hud(player):
    if not BUKKIT_AVAILABLE or player is None:
        return
    try:
        uuid_str, name = get_sender_uuid_and_name(player)
        if not uuid_str:
            return

        economy = EconomyManager()
        economy.load_database()
        acc = economy.get_or_create_account(uuid_str, name)
        if not acc.show_hud:
            return

        board = None
        try:
            current_board = player.getScoreboard()
            if current_board is not None and (current_board.getObjective(to_java_string("smartyhud")) is not None or current_board.getObjective(to_java_string("smartybal")) is not None):
                board = current_board
        except Exception:
            board = None
        if board is None:
            board = Bukkit.getScoreboardManager().getNewScoreboard()
        for old_name in ["smartyhud", "smartybal"]:
            try:
                old_objective = board.getObjective(to_java_string(old_name))
                if old_objective is not None:
                    old_objective.unregister()
            except Exception:
                pass
        objective = create_scoreboard_objective(
            board,
            "smartyhud",
            "dummy",
            colorize(u"&a&lМой профиль")
        )
        objective.setDisplaySlot(DisplaySlot.SIDEBAR)
        town_name, role_name = get_player_town_profile(uuid_str)
        shares_value = get_portfolio_value(uuid_str)
        jackpot = max(0.0, float(getattr(economy, "jackpot_bank", 0.0)))
        set_hud_score(objective, u"&7Город: &b{0}".format(town_name), 6)
        set_hud_score(objective, u"&7Роль: &f{0}".format(role_name), 5)
        set_hud_score(objective, u"&7Баланс: &a{0}".format(format_currency(acc.balance)), 4)
        set_hud_score(objective, u"&7Акции: &6{0}".format(format_currency(shares_value)), 3)
        set_hud_score(objective, u"&7Джекпот: &e{0}".format(format_currency(jackpot)), 2)
        player.setScoreboard(board)
    except Exception as e:
        log_error(u"Error updating balance HUD: {0}".format(e))


class PaydayRunnable(Runnable):
    def run(self):
        now = time.time()
        try:
            eco = EconomyManager()

            for p in Bukkit.getOnlinePlayers():
                if p and p.isOnline():
                    process_player_payday(eco, p, now, True)
            eco.save_database()

        except Exception as e:
            log_error(u"Error in PaydayRunnable: {0}".format(e))

        # Heartbeat ограничивает ошибку last-seen примерно одной минутой даже
        # после аварийного завершения, когда PlayerQuitEvent/on_disable не успели.
        try:
            checkpoint_online_last_seen(now)
        except Exception as e:
            log_error(u"Error in last-seen heartbeat: {0}".format(e))


class HudRunnable(Runnable):
    def run(self):
        try:
            if not BUKKIT_AVAILABLE:
                return
            for player in Bukkit.getOnlinePlayers():
                update_balance_hud(player)
        except Exception as e:
            log_error(u"Error in HudRunnable: {0}".format(e))


# Сколько секунд бездействия УЖЕ означает "не начисляем payday" (даже
# если игрок формально не в AFK-статусе). Это защита от коротких пауз,
# когда игрок отвернулся от ПК — AFK-статус срабатывает только через
# 10 минут, но payday-прогресс должен замирать сразу.
# Порог неактивности для payday. Хранится в EconomyManager.payday_afk_threshold
# и настраивается командой /eco afk-threshold <секунды>.
# Начальное значение — EconomyConfig.DEFAULT_PAYDAY_INACTIVITY.


def _is_recently_active(uuid_str, now, threshold=None):
    """True если игрок активно двигался в последние `threshold` секунд.
    По умолчанию берётся текущий payday_afk_threshold из EconomyManager."""
    if threshold is None:
        try:
            threshold = float(EconomyManager().payday_afk_threshold)
        except Exception:
            threshold = float(EconomyConfig.DEFAULT_PAYDAY_INACTIVITY)
    la = last_activity.get(uuid_str)
    if la is None:
        return False
    try:
        return (now - float(la)) < threshold
    except Exception:
        return False


def process_player_payday(economy, player, now=None, notify=True):
    if not BUKKIT_AVAILABLE or player is None:
        return 0
    if now is None:
        now = time.time()

    uuid_str, name = get_sender_uuid_and_name(player)
    if not uuid_str:
        return 0

    acc = economy.get_or_create_account(uuid_str, name)
    last_check = float(getattr(acc, "last_payday_check_timestamp", 0.0))
    if last_check <= 0.0 or last_check > now:
        acc.last_payday_check_timestamp = now
        economy.save_database()
        return 0
    if is_player_afk(player):
        acc.last_payday_check_timestamp = now
        economy.save_database()
        return 0

    # Защита от стоящих на месте: если игрок не двигался последние N сек
    # (payday_afk_threshold, настраивается через /eco afk-threshold) —
    # не начисляем payday за этот интервал. AFK-статус срабатывает только
    # через 10 мин, а прогресс payday должен замирать сразу.
    if not _is_recently_active(uuid_str, now):
        acc.last_payday_check_timestamp = now
        economy.save_database()
        return 0

    elapsed = max(0.0, now - last_check)
    acc.last_payday_check_timestamp = now
    acc.payday_progress_seconds = max(0.0, float(getattr(acc, "payday_progress_seconds", 0.0)) + elapsed)

    payouts = 0
    interval = float(EconomyConfig.PAYDAY_INTERVAL_SECONDS)
    while acc.payday_progress_seconds >= interval:
        acc.payday_progress_seconds -= interval
        acc.last_payday_timestamp = now
        payouts += 1

    acc.playtime_minutes = int(acc.payday_progress_seconds // 60)

    if payouts > 0:
        amount = economy.get_payday_amount() * payouts
        new_balance = economy.deposit(uuid_str, amount, name)
        if notify:
            send_message(player, "payday_received", amount=format_currency(amount), balance=format_currency(new_balance))
            safe_play_sound(player, ["ENTITY_PLAYER_LEVELUP", "LEVEL_UP"], 1.0, 1.0)
    else:
        economy.save_database()

    return payouts


def reset_online_payday_checks():
    if not BUKKIT_AVAILABLE:
        return
    economy = EconomyManager()
    now = time.time()
    changed = False
    for player in Bukkit.getOnlinePlayers():
        uuid_str, name = get_sender_uuid_and_name(player)
        if uuid_str:
            acc = economy.get_or_create_account(uuid_str, name)
            acc.last_payday_check_timestamp = now
            changed = True
    if changed:
        economy.save_database()


def start_payday_timer():
    global payday_task_id
    stop_payday_timer()
    # ФИКС "большого payday": дополнительно отменяем любой таймер от
    # ПРЕДЫДУЩЕЙ загрузки этого скрипта в этой же JVM (см. _SYS_PROP_PAYDAY_TASK) —
    # обычная переменная payday_task_id обнуляется при каждой перезагрузке
    # модуля, поэтому stop_payday_timer() выше не видит старый таймер из ПРОШЛОЙ загрузки.
    _cancel_stale_task_by_system_property(_SYS_PROP_PAYDAY_TASK)
    plugin = get_pyspigot_plugin()
    if plugin:
        try:
            # 1200 тиков = 60 секунд (раз в минуту проверяем и прибавляем +1 мин наигранного времени)
            task_obj = Bukkit.getScheduler().runTaskTimer(plugin, PaydayRunnable(), 1200, 1200)
            payday_task_id = task_obj.getTaskId()
            _store_task_id_in_system_property(_SYS_PROP_PAYDAY_TASK, payday_task_id)
            log_info(u"Started Personal Playtime Payday timer task (ID: {0}, period: 60s).".format(payday_task_id))
        except Exception as e:
            log_error(u"Failed to start payday timer: {0}".format(e))


def stop_payday_timer():
    global payday_task_id
    if BUKKIT_AVAILABLE:
        if payday_task_id != -1:
            try:
                Bukkit.getScheduler().cancelTask(payday_task_id)
                log_info(u"Cancelled Payday timer task (ID: {0}).".format(payday_task_id))
            except Exception:
                pass
            payday_task_id = -1
        _store_task_id_in_system_property(_SYS_PROP_PAYDAY_TASK, -1)


def start_afk_timer():
    global afk_task_id
    stop_afk_timer()
    _cancel_stale_task_by_system_property(_SYS_PROP_AFK_TASK)
    plugin = get_pyspigot_plugin()
    if plugin:
        try:
            task_obj = Bukkit.getScheduler().runTaskTimer(
                plugin,
                AfkRunnable(),
                EconomyConfig.AFK_CHECK_PERIOD_TICKS,
                EconomyConfig.AFK_CHECK_PERIOD_TICKS
            )
            afk_task_id = task_obj.getTaskId()
            _store_task_id_in_system_property(_SYS_PROP_AFK_TASK, afk_task_id)
            log_info(u"Started AFK timer task (ID: {0}).".format(afk_task_id))
        except Exception as e:
            log_error(u"Failed to start AFK timer: {0}".format(e))


def stop_afk_timer():
    global afk_task_id
    if BUKKIT_AVAILABLE:
        if afk_task_id != -1:
            try:
                Bukkit.getScheduler().cancelTask(afk_task_id)
                log_info(u"Cancelled AFK timer task (ID: {0}).".format(afk_task_id))
            except Exception:
                pass
            afk_task_id = -1
        _store_task_id_in_system_property(_SYS_PROP_AFK_TASK, -1)


def start_hud_timer():
    global hud_task_id
    stop_hud_timer()
    _cancel_stale_task_by_system_property(_SYS_PROP_HUD_TASK)
    plugin = get_pyspigot_plugin()
    if plugin:
        try:
            task_obj = Bukkit.getScheduler().runTaskTimer(plugin, HudRunnable(), 100, 100)
            hud_task_id = task_obj.getTaskId()
            _store_task_id_in_system_property(_SYS_PROP_HUD_TASK, hud_task_id)
            log_info(u"Started HUD timer task (ID: {0}).".format(hud_task_id))
        except Exception as e:
            log_error(u"Failed to start HUD timer: {0}".format(e))


def stop_hud_timer():
    global hud_task_id
    if BUKKIT_AVAILABLE:
        if hud_task_id != -1:
            try:
                Bukkit.getScheduler().cancelTask(hud_task_id)
                log_info(u"Cancelled HUD timer task (ID: {0}).".format(hud_task_id))
            except Exception:
                pass
            hud_task_id = -1
        _store_task_id_in_system_property(_SYS_PROP_HUD_TASK, -1)

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
            except Exception:
                pass
        del registered_listeners[:]
    except Exception:
        pass


def register_event_directly(event_class, handler_func):
    if not BUKKIT_AVAILABLE or event_class is None:
        return False
    try:
        plugin = get_pyspigot_plugin()
        if not plugin:
            log_error(u"Could not find PySpigot plugin for event registration!")
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
        log_info(u"Successfully registered event listener for {0}".format(
            event_class.getSimpleName() if hasattr(event_class, "getSimpleName") else str(event_class)
        ))
        return True
    except Exception as e:
        log_error(u"Failed direct event registration for {0}: {1}".format(event_class, e))
        return False


# -----------------------------------------------------------------------------
# МЕНЕДЖЕР ВРЕМЕНИ ПОСЛЕДНЕГО ВХОДА (LAST SEEN & GREETING)
# -----------------------------------------------------------------------------
def format_offline_time(seconds):
    seconds = int(seconds)
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if days > 0:
        parts.append(u"{0} дн.".format(days))
    if hours > 0:
        parts.append(u"{0} ч.".format(hours))
    if mins > 0 or (days == 0 and hours == 0):
        parts.append(u"{0} мин.".format(mins))
    if days == 0 and hours == 0 and mins < 5:
        parts.append(u"{0} сек.".format(secs))

    return u" ".join(parts)


class LastSeenManager(object):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LastSeenManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.file_path = os.path.join(get_script_dir(), "data", "last_seen.json")
        self.data = {}
        self.load_data()

    def load_data(self):
        if not os.path.exists(self.file_path):
            self.data = {}
            return
        try:
            with open(self.file_path, "r") as f:
                self.data = json.load(f)
        except Exception as e:
            log_error(u"Error loading last_seen.json: {0}".format(e))
            self.data = {}

    def save_data(self):
        try:
            data_dir = os.path.dirname(self.file_path)
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            temp_file = self.file_path + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(self.data, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            if hasattr(os, "replace"):
                os.replace(temp_file, self.file_path)
            else:
                try:
                    os.rename(temp_file, self.file_path)
                except OSError:
                    if os.path.exists(self.file_path):
                        os.remove(self.file_path)
                    os.rename(temp_file, self.file_path)
        except Exception as e:
            log_error(u"Error saving last_seen.json: {0}".format(e))

    def get_last_seen(self, uuid_str):
        return self.data.get(str(uuid_str))

    def update_last_seen(self, uuid_str):
        return self.update_many([uuid_str])

    def update_many(self, uuid_values, timestamp=None):
        """Обновляет несколько игроков одной атомарной записью файла."""
        if timestamp is None:
            timestamp = time.time()
        try:
            timestamp = float(timestamp)
        except (ValueError, TypeError, OverflowError):
            timestamp = time.time()
        if timestamp != timestamp or timestamp in (float("inf"), float("-inf")):
            timestamp = time.time()

        updated = 0
        for uuid_value in uuid_values:
            if uuid_value is None:
                continue
            uuid_key = str(uuid_value).strip()
            if not uuid_key:
                continue
            self.data[uuid_key] = timestamp
            updated += 1

        if updated > 0:
            self.save_data()
        return updated


def checkpoint_online_last_seen(timestamp=None):
    """Пакетно фиксирует, что текущие онлайн-игроки были на сервере в этот момент."""
    if not BUKKIT_AVAILABLE:
        return 0
    if timestamp is None:
        timestamp = time.time()

    online_uuids = []
    try:
        for player in Bukkit.getOnlinePlayers():
            if player is None:
                continue
            uuid_str, _ = get_sender_uuid_and_name(player)
            if uuid_str:
                online_uuids.append(uuid_str)
    except Exception as e:
        log_error(u"Error collecting online players for last-seen checkpoint: {0}".format(e))
        return 0

    return LastSeenManager().update_many(online_uuids, timestamp)


def safe_play_sound(player, sound_candidates, volume=1.0, pitch=1.0):
    if not BUKKIT_AVAILABLE or player is None:
        return
    if isinstance(sound_candidates, (str, unicode)):
        sound_candidates = [sound_candidates]
    for s_name in sound_candidates:
        try:
            sound_enum = Sound.valueOf(str(s_name))
            player.playSound(player.getLocation(), sound_enum, float(volume), float(pitch))
            return
        except Exception:
            pass


def send_join_greeting(player, name, diff_seconds):
    if not hasattr(player, "sendMessage"):
        return

    if diff_seconds is not None and diff_seconds >= 300:
        time_str = format_offline_time(diff_seconds)
        greeting = colorize(u"&aС возвращением, &f{0}&a! &8• &7Вы отсутствовали: &e{1}".format(name, time_str))
    else:
        greeting = colorize(u"&aС возвращением, &f{0}&a!".format(name))

    player.sendMessage(to_java_string(greeting))


def on_player_join(event):
    try:
        player = event.getPlayer()
        if not player:
            return
        uuid_str, name = get_sender_uuid_and_name(player)
        log_info(u"Player {0} ({1}) joined the server.".format(name, uuid_str))

        now = time.time()
        economy = EconomyManager()
        acc = economy.get_or_create_account(uuid_str, name)
        acc.last_payday_check_timestamp = now
        economy.save_database()
        last_activity[uuid_str] = now
        last_location_keys[uuid_str] = get_location_key(player.getLocation())
        afk_players.pop(uuid_str, None)

        ls_mgr = LastSeenManager()
        last_seen_time = ls_mgr.get_last_seen(uuid_str)

        diff_seconds = None
        if last_seen_time is not None:
            diff_seconds = max(0, now - float(last_seen_time))

        safe_play_sound(player, ["ENTITY_PLAYER_LEVELUP", "LEVEL_UP"], 0.7, 1.2)
        send_join_greeting(player, name, diff_seconds)
        update_balance_hud(player)
        refresh_sleep_rules()

        ls_mgr.update_last_seen(uuid_str)

    except Exception as e:
        log_error(u"Error in PlayerJoinEvent: {0}".format(e))
        import traceback
        traceback.print_exc()


def on_player_quit(event):
    try:
        player = event.getPlayer()
        if player:
            uuid_str, name = get_sender_uuid_and_name(player)
            log_info(u"Player {0} ({1}) quit the server.".format(name, uuid_str))
            process_player_payday(EconomyManager(), player, time.time(), False)
            afk_players.pop(uuid_str, None)
            last_activity.pop(uuid_str, None)
            last_location_keys.pop(uuid_str, None)
            ls_mgr = LastSeenManager()
            ls_mgr.update_last_seen(uuid_str)
            refresh_sleep_rules()
    except Exception as e:
        log_error(u"Error in PlayerQuitEvent: {0}".format(e))


def on_player_move(event):
    try:
        player = event.getPlayer()
        if not player:
            return
        uuid_str, name = get_sender_uuid_and_name(player)
        if not uuid_str:
            return
        new_key = get_location_key(event.getTo())
        old_key = last_location_keys.get(uuid_str)
        if old_key is None:
            last_location_keys[uuid_str] = new_key
            last_activity[uuid_str] = time.time()
            return
        if new_key != old_key:
            mark_player_active(player, True)
    except Exception as e:
        log_error(u"Error in PlayerMoveEvent: {0}".format(e))


def on_player_activity(event):
    try:
        player = event.getPlayer()
        if not player:
            return
        if hasattr(event, "isAsynchronous") and event.isAsynchronous():
            plugin = get_pyspigot_plugin()
            if plugin:
                class ActivityRunnable(Runnable):
                    def __init__(self, target):
                        self.target = target

                    def run(self):
                        mark_player_active(self.target, True)
                Bukkit.getScheduler().runTask(plugin, ActivityRunnable(player))
                return
        mark_player_active(player, True)
    except Exception:
        pass


def on_player_command(event):
    try:
        player = event.getPlayer()
        message = to_unicode(event.getMessage()).lower().strip()
        if message.startswith("/afk"):
            return
        if player:
            mark_player_active(player, True)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# ОБРАБОТЧИКИ КОМАНД ЭКОНОМИКИ (/bal, /pay, /eco, /showbal, /baltop)
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


def cmd_balance(*args):
    sender, cmd_args = parse_cmd_args(*args)
    sender_uuid, sender_name = get_sender_uuid_and_name(sender)
    economy = EconomyManager()

    if len(cmd_args) == 0:
        if not sender_uuid:
            safe_console_send(u"Console does not have a balance. Use /bal <player>")
            return True
        acc = economy.get_or_create_account(sender_uuid, sender_name)
        send_message(sender, "balance_self", formatted_balance=format_currency(acc.balance))
    else:
        target_name = cmd_args[0]
        acc = economy.get_account_by_name(target_name)
        if not acc:
            send_message(sender, "player_not_found", player=target_name)
        else:
            send_message(sender, "balance_other", player=acc.name, formatted_balance=format_currency(acc.balance))
    return True


def cmd_pay(*args):
    sender, cmd_args = parse_cmd_args(*args)
    sender_uuid, sender_name = get_sender_uuid_and_name(sender)

    if not sender_uuid:
        safe_console_send(u"Console cannot pay players.")
        return True

    if len(cmd_args) < 2:
        send_message(sender, "usage_pay")
        return True

    target_name = cmd_args[0]
    try:
        amount = float(cmd_args[1])
        if amount <= 0:
            raise ValueError()
    except ValueError:
        send_message(sender, "invalid_amount")
        return True

    if target_name.lower() == sender_name.lower():
        send_message(sender, "pay_self")
        return True

    economy = EconomyManager()
    sender_acc = economy.get_or_create_account(sender_uuid, sender_name)

    if not economy.has_enough(sender_uuid, amount):
        send_message(sender, "insufficient_funds", formatted_balance=format_currency(sender_acc.balance))
        return True

    target_acc = economy.get_account_by_name(target_name)
    if not target_acc:
        send_message(sender, "player_not_found", player=target_name)
        return True

    economy.withdraw(sender_uuid, amount)
    economy.deposit(target_acc.uuid, amount, target_acc.name)

    new_sender_bal = sender_acc.balance
    # Лог транзакции.
    log_transaction(
        u"PAY", sender_name, target_acc.name, amount,
        reason=u"/pay",
        new_bal_from=new_sender_bal,
        new_bal_to=economy.get_balance(target_acc.uuid),
    )

    send_message(sender, "pay_success_sender", formatted_amount=format_currency(amount), target=target_acc.name, formatted_balance=format_currency(new_sender_bal))

    target_player = Bukkit.getPlayer(target_acc.name) if BUKKIT_AVAILABLE else None
    if target_player and target_player.isOnline():
        send_message(target_player, "pay_success_receiver", formatted_amount=format_currency(amount), sender=sender_name)

    return True


def cmd_eco(*args):
    sender, cmd_args = parse_cmd_args(*args)
    # Для лога транзакций нужно имя отправителя (или "CONSOLE").
    try:
        _, sender_name = get_sender_uuid_and_name(sender)
        if not sender_name:
            sender_name = u"CONSOLE"
    except Exception:
        sender_name = u"CONSOLE"

    is_console = not hasattr(sender, "getUniqueId")
    is_op = hasattr(sender, "isOp") and sender.isOp()
    has_perm = hasattr(sender, "hasPermission") and (sender.hasPermission("pyspigot.economy.admin") or sender.hasPermission("economy.admin"))

    if not (is_console or is_op or has_perm):
        send_message(sender, "no_permission")
        return True

    if len(cmd_args) < 1:
        send_message(sender, "usage_eco")
        return True

    sub = cmd_args[0].lower()
    economy = EconomyManager()

    # --- Спец. подкоманды без target-игрока ---
    if sub == "afk-threshold":
        if len(cmd_args) < 2:
            sender.sendMessage(to_java_string(colorize(u"&cИспользование: &f/eco afk-threshold <сек>")))
            return True
        try:
            secs = float(cmd_args[1])
        except ValueError:
            secs = -1.0
        if secs < 0.0 or secs > 3600.0:
            sender.sendMessage(to_java_string(colorize(u"&cУкажите число секунд от 0 до 3600.")))
            return True
        economy.payday_afk_threshold = secs
        economy.save_database()
        sender.sendMessage(to_java_string(colorize(
            u"&a✓ Порог неактивности для payday: &f%.0f сек." % secs)))
        return True

    if sub == "sleep-default":
        # /eco sleep-default <percent> [world]
        if len(cmd_args) < 2:
            sender.sendMessage(to_java_string(colorize(u"&cИспользование: &f/eco sleep-default <percent> [world]")))
            for wn, pct in economy.sleep_defaults.items():
                sender.sendMessage(to_java_string(colorize(u"&7" + wn + u": &f" + str(pct))))
            return True
        try:
            pct = int(cmd_args[1])
        except ValueError:
            sender.sendMessage(to_java_string(colorize(u"&cПроцент должен быть целым числом 1..100.")))
            return True
        if pct < 1 or pct > 100:
            sender.sendMessage(to_java_string(colorize(u"&cПроцент должен быть 1..100.")))
            return True
        world_name = None
        if len(cmd_args) >= 3:
            world_name = to_unicode(cmd_args[2])
        else:
            if hasattr(sender, "getWorld"):
                try: world_name = to_unicode(sender.getWorld().getName())
                except Exception: pass
        if not world_name:
            sender.sendMessage(to_java_string(colorize(u"&cУкажите мир: &f/eco sleep-default <percent> <world>")))
            return True
        ok = set_sleep_default_for_world(world_name, pct)
        if ok:
            sender.sendMessage(to_java_string(colorize(
                u"&a✓ Дефолт sleep-percent для &f" + world_name + u"&a: &f" + str(pct))))
        else:
            sender.sendMessage(to_java_string(colorize(u"&cНе удалось установить.")))
        return True

    # --- Ниже — команды, требующие target-игрока ---
    if len(cmd_args) < 2:
        send_message(sender, "usage_eco")
        return True
    target_name = cmd_args[1]

    acc = economy.get_account_by_name(target_name)

    if not acc and BUKKIT_AVAILABLE:
        try:
            target_p = Bukkit.getPlayer(target_name)
            if target_p and target_p.isOnline():
                acc = economy.get_or_create_account(str(target_p.getUniqueId()), target_p.getName())
        except Exception:
            pass

    if not acc:
        send_message(sender, "player_not_found", player=target_name)
        return True

    if sub == "reset":
        new_bal = economy.set_balance(acc.uuid, EconomyConfig.DEFAULT_BALANCE, acc.name)
        send_message(sender, "eco_set", target=acc.name, formatted_balance=format_currency(new_bal))
        return True

    if len(cmd_args) < 3:
        send_message(sender, "usage_eco")
        return True

    try:
        amount = float(cmd_args[2])
        if amount < 0:
            raise ValueError()
    except ValueError:
        send_message(sender, "invalid_amount")
        return True

    if sub in ["give", "add"]:
        new_bal = economy.deposit(acc.uuid, amount, acc.name)
        log_transaction(u"DEPOSIT", sender_name if hasattr(sender, "getUniqueId") else u"CONSOLE",
                        acc.name, amount, reason=u"/eco give",
                        new_bal_to=new_bal)
        send_message(sender, "eco_give", formatted_amount=format_currency(amount), target=acc.name, formatted_balance=format_currency(new_bal))
    elif sub in ["take", "remove"]:
        if not economy.withdraw(acc.uuid, amount):
            send_message(sender, "insufficient_funds", formatted_balance=format_currency(economy.get_balance(acc.uuid)))
            return True
        new_bal = economy.get_balance(acc.uuid)
        log_transaction(u"WITHDRAW", acc.name,
                        sender_name if hasattr(sender, "getUniqueId") else u"CONSOLE",
                        amount, reason=u"/eco take",
                        new_bal_from=new_bal)
        send_message(sender, "eco_take", formatted_amount=format_currency(amount), target=acc.name, formatted_balance=format_currency(new_bal))
    elif sub == "set":
        old_bal = economy.get_balance(acc.uuid)
        new_bal = economy.set_balance(acc.uuid, amount, acc.name)
        log_transaction(u"SET", sender_name if hasattr(sender, "getUniqueId") else u"CONSOLE",
                        acc.name, amount, reason=u"/eco set (was %.2f)" % old_bal,
                        new_bal_to=new_bal)
        send_message(sender, "eco_set", target=acc.name, formatted_balance=format_currency(new_bal))
    else:
        send_message(sender, "usage_eco")

    return True


def cmd_showbal(*args):
    sender, cmd_args = parse_cmd_args(*args)
    sender_uuid, sender_name = get_sender_uuid_and_name(sender)

    if not sender_uuid:
        safe_console_send(u"Console cannot use balance HUD.")
        return True

    economy = EconomyManager()
    acc = economy.get_or_create_account(sender_uuid, sender_name)

    if len(cmd_args) == 0:
        acc.show_hud = not acc.show_hud
    else:
        mode = cmd_args[0].lower()
        if mode in ["on", "enable", "enabled", "true", "1"]:
            acc.show_hud = True
        elif mode in ["off", "disable", "disabled", "false", "0"]:
            acc.show_hud = False
        else:
            send_message(sender, "usage_showbal")
            return True

    economy.save_database()
    if acc.show_hud:
        update_balance_hud(sender)
        status = u"&aвключено"
    else:
        clear_balance_hud(sender)
        status = u"&cвыключено"

    send_message(sender, "hud_toggled", status=status)
    return True


def cmd_afk(*args):
    sender, cmd_args = parse_cmd_args(*args)
    sender_uuid, sender_name = get_sender_uuid_and_name(sender)

    if not sender_uuid:
        safe_console_send(u"Console cannot use AFK mode.")
        return True

    if len(cmd_args) == 0:
        set_player_afk(sender, not is_player_afk(sender), False)
        return True

    mode = cmd_args[0].lower()
    if mode in ["on", "enable", "enabled", "true", "1"]:
        set_player_afk(sender, True, False)
    elif mode in ["off", "disable", "disabled", "false", "0"]:
        set_player_afk(sender, False, False)
    else:
        send_message(sender, "usage_afk")
    return True


def cmd_payday(*args):
    sender, cmd_args = parse_cmd_args(*args)
    is_console = not hasattr(sender, "getUniqueId")
    is_op = hasattr(sender, "isOp") and sender.isOp()
    has_perm = hasattr(sender, "hasPermission") and sender.hasPermission("pyspigot.economy.admin")

    if not (is_console or is_op or has_perm):
        send_message(sender, "no_permission")
        return True

    economy = EconomyManager()
    sub = cmd_args[0].lower() if cmd_args else "status"

    if sub == "status":
        send_message(sender, "payday_status", amount=format_currency(economy.get_payday_amount()))
        return True

    if sub == "set":
        # ФИКС: Payday теперь зафиксирован на 1000$ и не настраивается —
        # команда честно сообщает об этом вместо тихого "принятия" суммы,
        # которая всё равно ни на что не влияет (см. get_payday_amount()).
        send_message(sender, "payday_fixed_notice", amount=format_currency(economy.get_payday_amount()))
        return True

    if sub in ["all", "giveall"]:
        amount = economy.get_payday_amount()
        count = 0
        for acc in list(economy.accounts.values()):
            economy.deposit(acc.uuid, amount, acc.name)
            count += 1
            player = get_online_player_by_uuid(acc.uuid)
            if player is not None:
                send_message(player, "payday_received", amount=format_currency(amount), balance=format_currency(economy.get_balance(acc.uuid)))
        send_message(sender, "payday_all", amount=format_currency(amount), count=count)
        return True

    send_message(sender, "usage_payday")
    return True


def cmd_baltop(*args):
    sender, cmd_args = parse_cmd_args(*args)
    top = get_baltop_cached(10)

    lines = [colorize(EconomyConfig.MESSAGES["baltop_header"])]
    for rank, (acc_name, acc_bal) in enumerate(top, 1):
        lines.append(colorize(EconomyConfig.MESSAGES["baltop_entry"].format(
            rank=rank,
            player=acc_name,
            formatted_balance=format_currency(acc_bal)
        )))
    lines.append(colorize(EconomyConfig.MESSAGES["baltop_footer"]))

    for line in lines:
        if sender is not None and hasattr(sender, "sendMessage"):
            sender.sendMessage(to_java_string(line))
        else:
            safe_console_send(line)

    return True


# -----------------------------------------------------------------------------
# ТАБ-ОБРАБОТЧИКИ
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
            except Exception:
                pass
    return cmd_args


def tab_balance(*args):
    cmd_args = get_cmd_args_from_args(args)
    if len(cmd_args) == 1:
        prefix = cmd_args[0].lower()
        names = []
        if BUKKIT_AVAILABLE:
            for p in Bukkit.getOnlinePlayers():
                p_name = to_unicode(p.getName())
                if p_name.lower().startswith(prefix):
                    names.append(p_name)
        return build_java_list(names)
    return build_java_list([])


def tab_pay(*args):
    cmd_args = get_cmd_args_from_args(args)
    if len(cmd_args) == 1:
        prefix = cmd_args[0].lower()
        names = []
        if BUKKIT_AVAILABLE:
            for p in Bukkit.getOnlinePlayers():
                p_name = to_unicode(p.getName())
                if p_name.lower().startswith(prefix):
                    names.append(p_name)
        return build_java_list(names)
    elif len(cmd_args) == 2:
        prefix = cmd_args[1].lower()
        amounts = ["10", "50", "100", "500", "1000"]
        return build_java_list([a for a in amounts if a.startswith(prefix)])
    return build_java_list([])


def tab_eco(*args):
    cmd_args = get_cmd_args_from_args(args)
    if len(cmd_args) <= 1:
        subcmds = ["give", "take", "set"]
        prefix = cmd_args[0].lower() if len(cmd_args) == 1 else ""
        return build_java_list([s for s in subcmds if s.startswith(prefix)])
    elif len(cmd_args) == 2:
        prefix = cmd_args[1].lower()
        names = []
        if BUKKIT_AVAILABLE:
            for p in Bukkit.getOnlinePlayers():
                p_name = to_unicode(p.getName())
                if p_name.lower().startswith(prefix):
                    names.append(p_name)
        return build_java_list(names)
    elif len(cmd_args) == 3:
        prefix = cmd_args[2].lower()
        amounts = ["100", "1000", "10000", "100000"]
        return build_java_list([a for a in amounts if a.startswith(prefix)])
    return build_java_list([])


def tab_showbal(*args):
    cmd_args = get_cmd_args_from_args(args)
    if len(cmd_args) == 1:
        prefix = cmd_args[0].lower()
        modes = ["on", "off"]
        return build_java_list([mode for mode in modes if mode.startswith(prefix)])
    return build_java_list([])


def tab_afk(*args):
    cmd_args = get_cmd_args_from_args(args)
    if len(cmd_args) == 1:
        prefix = cmd_args[0].lower()
        modes = ["on", "off"]
        return build_java_list([mode for mode in modes if mode.startswith(prefix)])
    return build_java_list([])


def tab_payday(*args):
    cmd_args = get_cmd_args_from_args(args)
    if len(cmd_args) <= 1:
        prefix = cmd_args[0].lower() if len(cmd_args) == 1 else ""
        subcmds = ["status", "set", "all"]
        return build_java_list([sub for sub in subcmds if sub.startswith(prefix)])
    if len(cmd_args) == 2 and cmd_args[0].lower() == "set":
        prefix = cmd_args[1].lower()
        amounts = ["500", "1000", "1500", "2000", "5000"]
        return build_java_list([amount for amount in amounts if amount.startswith(prefix)])
    return build_java_list([])


# -----------------------------------------------------------------------------
# РЕГИСТРАЦИЯ КОМАНД В BUKKIT
# -----------------------------------------------------------------------------
if BUKKIT_AVAILABLE:
    class PyBukkitCommand(Command, TabCompleter):
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
    class PyBukkitCommand(object):
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
                    except Exception:
                        pass

                known_commands.put(name, cmd_obj)
                known_commands.put(fallback_prefix + ":" + name, cmd_obj)

                for alias in aliases:
                    a_str = str(alias).lower()
                    alias_cmd = PyBukkitCommand(a_str, cmd_obj.getDescription(), cmd_obj.getUsage(), [], cmd_obj.executor, cmd_obj.completer)
                    known_commands.put(a_str, alias_cmd)
                    known_commands.put(fallback_prefix + ":" + a_str, alias_cmd)

    except Exception as e:
        log_error(u"Error force-registering Bukkit command: {0}".format(e))


registered_economy_commands = []   # (name, aliases) - для полного снятия при выгрузке,
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


def unregister_economy_commands():
    for name, aliases in list(registered_economy_commands):
        force_unregister_bukkit_command("smarty-economy", name, aliases)
    del registered_economy_commands[:]
    try:
        if BUKKIT_AVAILABLE and hasattr(Bukkit.getServer(), "syncCommands"):
            Bukkit.getServer().syncCommands()
    except Exception:
        pass


def register_economy_commands():
    commands_def = [
        ("bal", "Check balance", "/bal [player]", ["money", "balance"], cmd_balance, tab_balance),
        ("pay", "Pay money to a player", "/pay <player> <amount>", [], cmd_pay, tab_pay),
        ("eco", "Admin economy control", "/eco <give|take|set> <player> <amount>", ["economy"], cmd_eco, tab_eco),
        ("showbal", "Toggle right HUD", "/showbal [on|off]", ["showbalance"], cmd_showbal, tab_showbal),
        ("hud", "Toggle right HUD", "/hud [on|off]", [], cmd_showbal, tab_showbal),
        ("afk", "Toggle AFK mode", "/afk [on|off]", [], cmd_afk, tab_afk),
        ("payday", "Admin payday tools", "/payday <status|set|all>", [], cmd_payday, tab_payday),
        ("baltop", "View richest players", "/baltop", ["moneytop", "topbal"], cmd_baltop, None)
    ]

    for item in commands_def:
        name, desc, usage, aliases, handler, tab_handler = item[0], item[1], item[2], item[3], item[4], item[5]
        cmd_obj = PyBukkitCommand(name, desc, usage, aliases, handler, tab_handler)
        force_register_bukkit_command("smarty-economy", cmd_obj, aliases)
        registered_economy_commands.append((name, aliases))

    log_info(u"Commands force-registered in Bukkit CommandMap (/bal, /pay, /eco, /showbal, /hud, /afk, /payday, /baltop) with TabCompletion.")


# -----------------------------------------------------------------------------
# ЖИЗНЕННЫЙ ЦИКЛ СКРИПТА PYSPIGOT (LIFECYCLE HOOKS)
# -----------------------------------------------------------------------------
def on_enable():
    log_info(u"=== Starting {0} v{1} ===".format(EconomyConfig.PLUGIN_NAME, EconomyConfig.VERSION))
    try:
        unregister_script_listeners()
        economy = EconomyManager()
        log_info(u"Database loaded successfully ({0} accounts).".format(len(economy.accounts)))

        if JAVA_STRING_AVAILABLE and System is not None:
            try:
                System.getProperties().put("PySpigot_EconomyManager", economy)
                System.getProperties().put("SmartY_EconomyManager", economy)
            except Exception:
                pass

        if BUKKIT_AVAILABLE:
            capture_default_sleep_rules()
            register_event_directly(PlayerJoinEvent, on_player_join)
            register_event_directly(PlayerQuitEvent, on_player_quit)
            register_event_directly(PlayerMoveEvent, on_player_move)
            register_event_directly(PlayerInteractEvent, on_player_activity)
            register_event_directly(PlayerCommandPreprocessEvent, on_player_command)
            register_event_directly(AsyncPlayerChatEvent, on_player_activity)
            if InventoryClickEvent is not None:
                register_event_directly(InventoryClickEvent, on_player_activity)
            log_info(u"Economy events registered directly into Bukkit EventMap.")
            # При /ps reload игроки не получают новый PlayerJoinEvent. Фиксируем,
            # что они уже онлайн, чтобы будущий рестарт не считал время от старого входа.
            checkpoint_online_last_seen(time.time())

        register_economy_commands()
        reset_online_payday_checks()
        start_payday_timer()
        start_afk_timer()
        start_hud_timer()
        log_info(u"{0} successfully enabled and ready!".format(EconomyConfig.PLUGIN_NAME))
    except Exception as e:
        log_error(u"Critical error in economy on_enable: {0}".format(e))
        import traceback
        traceback.print_exc()


def on_disable():
    log_info(u"=== Disabling {0} ===".format(EconomyConfig.PLUGIN_NAME))
    shutdown_timestamp = time.time()
    stop_hud_timer()
    stop_afk_timer()
    stop_payday_timer()
    # На остановке сервера PlayerQuitEvent может не дойти до PySpigot-скрипта.
    # Сохраняем всех, кого Bukkit ещё считает подключёнными, одним JSON-write.
    try:
        checkpoint_online_last_seen(shutdown_timestamp)
    except Exception as e:
        log_error(u"Error saving online last-seen values during shutdown: {0}".format(e))
    unregister_script_listeners()
    unregister_economy_commands()
    try:
        economy = EconomyManager()
        if BUKKIT_AVAILABLE:
            for player in Bukkit.getOnlinePlayers():
                process_player_payday(economy, player, shutdown_timestamp, False)
        economy.save_database()
    except Exception:
        pass
    restore_all_sleep_rules()


def start(script=None):
    on_enable()


def stop(script=None):
    # ВАЖНО: PySpigot вызывает автоматически именно stop() (не on_disable()) при
    # /pyspigot unload <script>. Без этой функции on_disable() никогда не выполнялся бы
    # при ручной выгрузке скрипта - таймеры (payday/afk/hud), напрямую (в обход
    # command_manager) зарегистрированные команды /bal /pay /eco /showbal /hud /afk
    # /payday /baltop и listeners, добавленные через registerEvent в обход
    # listener_manager, продолжали бы работать даже после выгрузки скрипта.
    on_disable()


if __name__ == "__main__" or "ps" in globals() or "command_manager" in globals():
    on_enable()

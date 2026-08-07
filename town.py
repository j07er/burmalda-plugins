# -*- coding: utf-8 -*-
"""
SmartY Politic for PySpigot / Paper 1.21.
Версия 1.5.3 — Полное исправление:
 - Восстановлен класс CityCommand (исправлена ошибка NameError: global name 'CityCommand' is not defined).
 - Исправлена ошибка 'global name uid is not defined' (добавлена функция uid для всех обработчиков GUI).
 - Полностью удалены теги ролей ([М], [ЗМ], [СТ], [Ж]) из общего Таба (Tab) и общедоступного чата:
   теперь игрокам в табе и чате отображается только ник в цвете города без каких-либо внутренних званий.
   Внутренние роли (Мэр, Заместитель, Строитель, Житель) видны только в меню города (/townmenu) и GUI!
 - Оповещение всего города при запуске строительства проекта.
 - Сдача материалов и денег в проект больше НЕ меняет время готовности (его ставит Мэр/Строитель).
 - Мэр или Строитель могут ЗАБИРАТЬ сданные в проект материалы в свой инвентарь (Shift+ЛКМ/ПКМ в меню).
 - Удобное добавление ресурсов в проект: просто кликайте по предметам в своём нижнем инвентаре,
   когда открыто меню настройки проекта (ЛКМ = +64, ПКМ = +16, Shift+ЛКМ = +512 шт.)!
 - Телепорт к союзному жителю города доступен всем гражданам с КД 15 минут (900 секунд).
 - Система кастомных квестов через Админ-панель (/ta menu -> Управление квестами).

Commands:
 /town help
 /town create <name>
 /town list [page]
 /town info [town]
 /town members [town]
 /town project <create|desc|reqmoney|addreq|addhand|duration|start|delete> [args...]
 /town add <player>
 /town remove <player>
 /town mayor <player>
 /town deposit <amount>
 /town withdraw <amount>
 /town leave
 /town disband
 /townadmin <reload|delete|setmayor|treasury|menu|gui>
 /townmenu
"""

import json
import os
import re
import sys
import time
import copy

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

try:
    from org.bukkit import Bukkit, ChatColor, Material, Sound, Location
    from org.bukkit.command import Command, TabCompleter
    from org.bukkit.entity import Player
    from org.bukkit.inventory import InventoryHolder, ItemStack
    from org.bukkit.event import EventPriority, HandlerList, Listener
    from org.bukkit.event.inventory import InventoryClickEvent, InventoryDragEvent
    from org.bukkit.event.player import PlayerJoinEvent, PlayerQuitEvent
    from org.bukkit.plugin import EventExecutor
    try:
        from org.bukkit.event.player import AsyncPlayerChatEvent
    except ImportError:
        AsyncPlayerChatEvent = None
    try:
        from org.bukkit.event.entity import EntityDeathEvent
    except ImportError:
        EntityDeathEvent = None
    BUKKIT_AVAILABLE = True
except ImportError:
    Bukkit = None
    ChatColor = None
    Material = None
    Location = None
    Player = None
    Command = object
    TabCompleter = object
    InventoryHolder = object
    ItemStack = None
    EventPriority = None
    HandlerList = None
    Listener = object
    InventoryClickEvent = None
    InventoryDragEvent = None
    AsyncPlayerChatEvent = None
    EntityDeathEvent = None
    PlayerJoinEvent = None
    PlayerQuitEvent = None
    EventExecutor = object
    BUKKIT_AVAILABLE = False

try:
    from java.lang import String as JavaString, StringBuilder, Runnable, System
    JAVA_STRING_AVAILABLE = True
except ImportError:
    JavaString = str
    StringBuilder = None
    Runnable = object
    System = None
    JAVA_STRING_AVAILABLE = False

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


def to_unicode(value):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    if JAVA_STRING_AVAILABLE and hasattr(value, "getBytes"):
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


def to_java_string(value):
    text = to_unicode(value)
    if JAVA_STRING_AVAILABLE:
        if isinstance(text, JavaString):
            return text
        if StringBuilder is not None:
            try:
                builder = StringBuilder()
                for ch in text:
                    builder.appendCodePoint(ord(ch))
                return builder.toString()
            except Exception:
                pass
        try:
            return JavaString(text)
        except Exception:
            pass
    return text


def colorize(value):
    text = to_unicode(value)
    if not text:
        return u""
    if BUKKIT_AVAILABLE and ChatColor is not None:
        try:
            return to_unicode(ChatColor.translateAlternateColorCodes('&', to_java_string(text)))
        except Exception:
            pass
    return re.sub(r'&([0-9a-fk-or])', u'', text, flags=re.IGNORECASE)


def send_message(target, value):
    message = colorize(value)
    if BUKKIT_AVAILABLE and target is not None:
        try:
            target.sendMessage(to_java_string(message))
            return
        except Exception:
            pass
    print("[SmartY-Politic] " + to_unicode(message))


def send_clickable_invite(target_player, town_name, mayor_name):
    if not BUKKIT_AVAILABLE or target_player is None:
        return
    try:
        from net.md_5.bungee.api.chat import TextComponent, ClickEvent, HoverEvent, ComponentBuilder
        message = TextComponent(colorize(
            CitiesConfig.PREFIX + u"&e{0} &7приглашает вас в город &b{1}&7.\n".format(mayor_name, town_name) +
            CitiesConfig.PREFIX + u"&7Выберите действие: "
        ))
        accept = TextComponent(colorize(u"&a&l[ПРИНЯТЬ]"))
        accept.setClickEvent(ClickEvent(ClickEvent.Action.RUN_COMMAND, u"/town accept {0}".format(town_name)))
        accept.setHoverEvent(HoverEvent(HoverEvent.Action.SHOW_TEXT, ComponentBuilder(colorize(u"&aВступить в город")).create()))
        deny = TextComponent(colorize(u"&c&l[ОТКЛОНИТЬ]"))
        deny.setClickEvent(ClickEvent(ClickEvent.Action.RUN_COMMAND, u"/town deny {0}".format(town_name)))
        deny.setHoverEvent(HoverEvent(HoverEvent.Action.SHOW_TEXT, ComponentBuilder(colorize(u"&cОтклонить приглашение")).create()))
        message.addExtra(accept)
        message.addExtra(TextComponent(colorize(u" ")))
        message.addExtra(deny)
        target_player.spigot().sendMessage(message)
    except Exception:
        send_message(target_player, CitiesConfig.PREFIX + u"&7Приглашение в &b{0}&7. Принять: &e/town accept {0}&7, отклонить: &e/town deny {0}".format(town_name))


def log_info(value):
    if BUKKIT_AVAILABLE:
        send_message(Bukkit.getConsoleSender(), u"&9[SmartY-Politic] &7" + to_unicode(value))
    else:
        print("[SmartY-Politic] " + str(value))


def build_java_list(values):
    if not BUKKIT_AVAILABLE:
        return values
    result = ArrayList()
    for value in values:
        result.add(to_java_string(value))
    return result


def format_currency(amount):
    try:
        val = float(amount)
        # ФИКС "nan$": round/format в Jython 2.7 молча пропускают NaN/Infinity,
        # возвращая строку "nan$"/"inf$" вместо ошибки. Явный гард ниже.
        if val != val or val == float("inf") or val == float("-inf"):
            return u"0$"
        return to_unicode("{:,.0f}".format(val).replace(",", " ")) + u"$"
    except Exception:
        return u"0$"


def safe_float(value, default=0.0, minimum=None, maximum=None):
    try:
        result = float(value)
        if result != result or result in (float("inf"), float("-inf")):
            return default
        if minimum is not None and result < minimum:
            return default
        if maximum is not None and result > maximum:
            return default
        return result
    except Exception:
        return default


def parse_amount(raw):
    text = to_unicode(raw).replace(",", ".").replace(" ", "")
    amount = float(text)
    if amount != amount or amount in (float("inf"), float("-inf")) or amount <= 0 or amount > 10000000000000000.0:
        raise ValueError()
    return round(amount, 2)


def reject_json_constant(value):
    raise ValueError("non-finite JSON number: {0}".format(value))


def load_companies_data():
    if not os.path.exists(CitiesConfig.COMPANIES_FILE):
        return {"companies": {}}
    try:
        with open(CitiesConfig.COMPANIES_FILE, "r") as handle:
            return json.load(handle)
    except Exception as exc:
        log_info(u"Cannot read companies data: {0}".format(exc))
        return {"companies": {}}


def get_company_share_price(company):
    try:
        total = 10000
        available = max(0, min(total, int(company.get("available_shares", total))))
        issued = total - available
        start_price = float(company.get("start_price", 10.0))
        balance = float(company.get("balance", 0.0))
        if "price_offset" not in company:
            if company.get("share_price") is not None:
                migrated_price = float(company.get("share_price"))
                if migrated_price == migrated_price and migrated_price not in (float("inf"), float("-inf")):
                    return max(1.0, round(migrated_price, 6))
            return max(1.0, round((balance + available * start_price) / float(total), 6))
        offset = float(company.get("price_offset", 0.0))
        values = (start_price, balance, offset)
        if any(value != value or value == float("inf") or value == float("-inf") for value in values):
            return 0.0
        price = start_price + balance / float(total) + issued * start_price / float(total) + offset
        return max(1.0, round(price, 6))
    except Exception:
        return 0.0


def get_company_capitalization(company):
    return round(get_company_share_price(company) * 10000.0, 2)


def get_city_companies(city_name):
    city_keys = {to_unicode(city_name).strip().lower()}
    try:
        if state is not None:
            target_city = state.get_city_by_name(city_name)
            if target_city is not None:
                city_keys.add(to_unicode(target_city.get("name")).strip().lower())
                for alias in target_city.get("aliases", []):
                    city_keys.add(to_unicode(alias).strip().lower())
    except Exception:
        pass
    data = load_companies_data()
    companies = []
    for company in data.get("companies", {}).values():
        if to_unicode(company.get("town")).strip().lower() in city_keys:
            companies.append(company)
    return sorted(companies, key=lambda item: to_unicode(item.get("name")).lower())


def player_owns_city_company(city, uuid_str):
    for company in get_city_companies(city.get("name")):
        if str(company.get("owner_uuid")) == str(uuid_str):
            return True
    return False


def get_sender_uuid_and_name(sender):
    if sender is None:
        return None, u"Console"
    uuid_str = None
    name = u"Unknown"
    try:
        uuid_str = str(sender.getUniqueId())
    except Exception:
        pass
    try:
        name = to_unicode(sender.getName())
    except Exception:
        pass
    return uuid_str, name


# Функция получения UUID для совместимости со всеми вызовами
def uid(e):
    if e is None:
        return ""
    try:
        return str(e.getUniqueId())
    except Exception:
        return ""


def is_admin(sender):
    if sender is None:
        return True
    try:
        if sender.isOp():
            return True
    except Exception:
        pass
    try:
        return sender.hasPermission("smarty.cities.admin")
    except Exception:
        return False


NUCLEAR_TELEPORT_LOCK_PROPERTY = "SmartY_NuclearTeleportLockUntil"


def is_nuclear_teleport_locked():
    """Читает опубликованный nuclear_bomb.py дедлайн без прямого импорта скрипта."""
    if not JAVA_STRING_AVAILABLE or System is None:
        return False
    try:
        raw_deadline = System.getProperties().get(NUCLEAR_TELEPORT_LOCK_PROPERTY)
        if raw_deadline is None:
            return False
        deadline_ms = int(to_unicode(raw_deadline).strip())
        return int(System.currentTimeMillis()) < deadline_ms
    except Exception:
        return False


def deny_city_teleport_during_nuclear_drop(player):
    if not is_nuclear_teleport_locked():
        return False
    send_message(
        player,
        CitiesConfig.PREFIX
        + u"&4☢ &cТелепортация города заблокирована: зафиксирован ядерный сброс! &7Спасайтесь без телепорта.",
    )
    return True


def get_pyspigot_plugin():
    if not BUKKIT_AVAILABLE:
        return None
    try:
        plugin = Bukkit.getPluginManager().getPlugin("PySpigot")
        if plugin:
            return plugin
        for item in Bukkit.getPluginManager().getPlugins():
            if "pyspigot" in str(item.getName()).lower():
                return item
    except Exception:
        pass
    return None


class MainThreadRunnable(Runnable):
    def __init__(self, callback):
        self.callback = callback

    def run(self):
        self.callback()


def run_on_main_thread(callback):
    """Run a Bukkit mutation now or schedule it with an unambiguous Runnable."""
    if not BUKKIT_AVAILABLE or Bukkit is None:
        callback()
        return True
    try:
        if Bukkit.isPrimaryThread():
            callback()
            return True
        plugin = get_pyspigot_plugin()
        if plugin is None:
            log_info(u"Cannot schedule main-thread town action: PySpigot plugin not found.")
            return False
        Bukkit.getScheduler().runTask(plugin, MainThreadRunnable(callback))
        return True
    except Exception as exc:
        log_info(u"Cannot schedule main-thread town action: {0}".format(exc))
        return False


def get_player_hero(nick):
    try:
        owners = System.getProperties().get("pyspigot.character_owners")
        if owners is not None:
            for hero_id in owners.keySet():
                nicks = owners.get(hero_id)
                if nicks and any(to_unicode(n).lower() == to_unicode(nick).lower() for n in nicks):
                    return to_unicode(hero_id).upper()
    except Exception:
        pass
    return u"Не выбран"


def format_duration_human(seconds_left):
    if seconds_left <= 0:
        return u"Готово к завершению!"
    hours = int(seconds_left / 3600)
    mins = int((seconds_left % 3600) / 60)
    if hours > 0:
        return u"%d ч. %d мин." % (hours, mins)
    return u"%d мин." % max(1, mins)


# Перезарядки телепортации к жителям города: uuid_str -> timestamp готовности (15 минут = 900 сек)
tp_cooldowns = {}


class CitiesConfig(object):
    PLUGIN_NAME = u"SmartY-Politic"
    VERSION = u"1.5.8"
    PREFIX = u"&9&l[Политика]&r "
    SCRIPT_DIR = get_script_dir()
    DATA_DIR = os.path.join(SCRIPT_DIR, "data")
    DATA_FILE = os.path.join(DATA_DIR, "cities.json")
    COMPANIES_FILE = os.path.join(DATA_DIR, "companies.json")
    LIST_PAGE_SIZE = 8
    NAME_MIN_LENGTH = 3
    NAME_MAX_LENGTH = 24
    INVITE_TIMEOUT_SECONDS = 300
    DEFAULT_COMPANY_TAX_PERCENT = 2.0
    TAX_TYPES = {
        "companies": u"Общий",
        "primary": u"Первичные акции",
        "resale": u"Перепродажа акций",
        "dividends": u"Дивиденды",
        "tradehall": u"Трейдхолл"
    }
    DEFAULT_STATE = {
        "cities": {},
        "invites": {},
        "server_audit": [],
        "custom_quests": {}
    }
    COLORS = {
        "white": ("WHITE", u"&f"),
        "gray": ("GRAY", u"&7"),
        "dark_gray": ("DARK_GRAY", u"&8"),
        "black": ("BLACK", u"&0"),
        "red": ("RED", u"&c"),
        "dark_red": ("DARK_RED", u"&4"),
        "gold": ("GOLD", u"&6"),
        "yellow": ("YELLOW", u"&e"),
        "green": ("GREEN", u"&a"),
        "dark_green": ("DARK_GREEN", u"&2"),
        "aqua": ("AQUA", u"&b"),
        "dark_aqua": ("DARK_AQUA", u"&3"),
        "blue": ("BLUE", u"&9"),
        "dark_blue": ("DARK_BLUE", u"&1"),
        "light_purple": ("LIGHT_PURPLE", u"&d"),
        "purple": ("DARK_PURPLE", u"&5")
    }


class JsonStorage(object):
    def __init__(self, path, defaults):
        self.path = path
        self.backup_path = path + ".bak"
        self.defaults = defaults
        self.loaded_ok = False
        self.primary_valid = False

    def read_file(self, path):
        with open(path, "r") as handle:
            return self.merge_defaults(json.load(handle, parse_constant=reject_json_constant))

    def load(self):
        self.ensure_dir()
        if not os.path.exists(self.path):
            if os.path.exists(self.backup_path):
                try:
                    data = self.read_file(self.backup_path)
                    self.loaded_ok = True
                    log_info(u"Loaded cities data from backup because the primary file is missing.")
                    return data
                except Exception as exc:
                    log_info(u"Cannot read cities backup: {0}".format(exc))
                    return self.merge_defaults({})
            self.loaded_ok = True
            return self.merge_defaults({})
        try:
            data = self.read_file(self.path)
            self.loaded_ok = True
            self.primary_valid = True
            return data
        except UnicodeDecodeError:
            try:
                with open(self.path, "rb") as handle:
                    raw = handle.read()
                    data = self.merge_defaults(json.loads(raw.decode("utf-8"), parse_constant=reject_json_constant))
                    self.loaded_ok = True
                    self.primary_valid = True
                    return data
            except Exception as exc:
                log_info(u"Cannot read cities data as UTF-8: {0}".format(exc))
        except Exception as exc:
            log_info(u"Cannot read cities data: {0}".format(exc))

        if os.path.exists(self.backup_path):
            try:
                data = self.read_file(self.backup_path)
                self.loaded_ok = True
                log_info(u"Loaded cities data from backup; primary file is damaged.")
                return data
            except Exception as exc:
                log_info(u"Cannot read cities backup: {0}".format(exc))
        return self.merge_defaults({})

    def save(self, data):
        temp_path = self.path + ".tmp"
        if not self.loaded_ok:
            log_info(u"Refusing to overwrite cities data that failed to load.")
            return False
        try:
            self.ensure_dir()
            with open(temp_path, "w") as handle:
                handle.write(json.dumps(data, indent=2, ensure_ascii=True, sort_keys=True, allow_nan=False))
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except Exception:
                    pass
            if self.primary_valid and os.path.exists(self.path):
                backup_tmp = self.backup_path + ".tmp"
                try:
                    with open(self.path, "rb") as source:
                        with open(backup_tmp, "wb") as target:
                            target.write(source.read())
                            target.flush()
                            try:
                                os.fsync(target.fileno())
                            except Exception:
                                pass
                    if hasattr(os, "replace"):
                        os.replace(backup_tmp, self.backup_path)
                    else:
                        os.rename(backup_tmp, self.backup_path)
                except Exception as backup_exc:
                    log_info(u"Cannot update cities backup: {0}".format(backup_exc))
            if hasattr(os, "replace"):
                os.replace(temp_path, self.path)
            else:
                os.rename(temp_path, self.path)
            self.primary_valid = True
            return True
        except Exception as exc:
            log_info(u"Cannot save cities data: {0}".format(exc))
            return False

    def ensure_dir(self):
        folder = os.path.dirname(self.path)
        if not os.path.exists(folder):
            os.makedirs(folder)

    def merge_defaults(self, data):
        result = {"cities": {}, "invites": {}, "server_audit": [], "custom_quests": {}}
        if isinstance(data, dict):
            for key, value in data.items():
                result[key] = value
        return result


class EconomyGateway(object):
    def __init__(self):
        self.manager = self.find_manager()

    def refresh(self):
        self.manager = self.find_manager()

    def find_manager(self):
        if JAVA_STRING_AVAILABLE and System is not None:
            try:
                manager = System.getProperties().get("PySpigot_EconomyManager")
                if not manager:
                    manager = System.getProperties().get("SmartY_EconomyManager")
                if manager:
                    try:
                        if hasattr(manager, "is_active") and not manager.is_active():
                            return None
                    except Exception:
                        return None
                    return manager
            except Exception:
                pass
        # Importing economy.py here would silently resurrect an unloaded script.
        return None

    def is_ready(self):
        self.refresh()
        return self.manager is not None

    def get_or_create(self, uuid_str, name):
        if not self.is_ready():
            return None
        return self.manager.get_or_create_account(uuid_str, name)

    def get_account_by_name(self, name):
        if not self.is_ready():
            return None
        return self.manager.get_account_by_name(name)

    def withdraw(self, uuid_str, amount):
        if not self.is_ready():
            return False
        return bool(self.manager.withdraw(uuid_str, amount))

    def deposit(self, uuid_str, amount, name):
        if not self.is_ready():
            return 0.0
        return self.manager.deposit(uuid_str, amount, name)

    def deposit_checked(self, uuid_str, amount, name):
        if not self.is_ready():
            return False, 0.0
        if hasattr(self.manager, "deposit_checked"):
            return self.manager.deposit_checked(uuid_str, amount, name)
        return True, self.manager.deposit(uuid_str, amount, name)

    def transfer(self, from_uuid, to_uuid, amount, to_name):
        if not self.is_ready():
            return False, 0.0, 0.0
        if hasattr(self.manager, "transfer"):
            return self.manager.transfer(from_uuid, to_uuid, amount, to_name)
        return False, self.manager.get_balance(from_uuid), self.manager.get_balance(to_uuid)

    def get_balance(self, uuid_str):
        if not self.is_ready():
            return 0.0
        return self.manager.get_balance(uuid_str)

    def get_online_names(self):
        names = []
        if BUKKIT_AVAILABLE:
            try:
                for player in Bukkit.getOnlinePlayers():
                    names.append(to_unicode(player.getName()))
            except Exception:
                pass
        if self.is_ready():
            try:
                for account in self.manager.accounts.values():
                    if account.name:
                        names.append(to_unicode(account.name))
            except Exception:
                pass
        return sorted(list(set(names)), key=lambda item: item.lower())


class CityState(object):
    def __init__(self, storage):
        self.storage = storage
        self.data = self.storage.load()

    def reload(self):
        self.data = self.storage.load()
        self.normalize_existing_data()

    def save(self):
        self.normalize_existing_data()
        return self.storage.save(self.data)

    def normalize_existing_data(self):
        self.data.setdefault("cities", {})
        self.data.setdefault("invites", {})
        self.data.setdefault("server_audit", [])
        self.data.setdefault("custom_quests", {})
        # ФИКС: хранилище для настройки "отключить телепорты к себе" (/town tp on|off).
        # uuid_str -> True, если игрок выключил телепорты к себе через &e/town tp offа.
        # Когда это True, игрок также НЕ МОЖЕТ телепортироваться к другим жителям
        # (взаимная блокировка: входящие и исходящие телепорты отключаются вместе).
        self.data.setdefault("tp_disabled", {})
        for city in self.data.get("cities", {}).values():
            city.setdefault("roles", {})
            if "mayor" not in city["roles"]:
                city["roles"]["mayor"] = {"name": "mayor", "display": u"Мэр", "color": "gold"}
            if "citizen" not in city["roles"]:
                city["roles"]["citizen"] = {"name": "citizen", "display": u"Житель", "color": "gray"}
            if "builder" not in city["roles"]:
                city["roles"]["builder"] = {"name": "builder", "display": u"Строитель", "color": "yellow"}
            for role_key, role_data in city["roles"].items():
                if isinstance(role_data, dict):
                    role_data.setdefault("name", role_key)
                    role_data.setdefault("display", role_key)
                    role_data.setdefault("color", "white")
            city.setdefault("member_roles", {})
            city.setdefault("aliases", [])
            city.setdefault("color", "white")
            city["treasury"] = round(safe_float(city.get("treasury", 0.0), 0.0, 0.0, 10000000000000000.0), 2)
            taxes = city.setdefault("taxes", {})
            taxes.setdefault("companies", CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT)
            taxes.setdefault("primary", taxes.get("companies", CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT))
            taxes.setdefault("resale", taxes.get("companies", CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT))
            taxes.setdefault("dividends", taxes.get("companies", CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT))
            taxes.setdefault("tradehall", taxes.get("companies", CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT))
            for tax_key in ("companies", "primary", "resale", "dividends", "tradehall"):
                taxes[tax_key] = round(safe_float(
                    taxes.get(tax_key), CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT, 0.0, 100.0
                ), 2)
            city.setdefault("members", {})
            city.setdefault("log", [])
            city.setdefault("quest_progress", {"iron": 0, "mobs": 0})
            city.setdefault("contributions", {})
            city.setdefault("rank_perms", {
                "mayor": ["INVITE", "KICK", "SPEND_TREASURY", "SET_TAX", "MANAGE_QUESTS", "MANAGE_PROJECTS"],
                "deputy": ["INVITE", "KICK", "MANAGE_QUESTS", "MANAGE_PROJECTS"],
                "builder": ["MANAGE_PROJECTS", "MANAGE_QUESTS", "INVITE"],
                "citizen": []
            })
            cproj = city.setdefault("custom_projects", {})
            for pid, pdata in cproj.items():
                pdata.setdefault("id", pid)
                pdata.setdefault("name", pid)
                pdata.setdefault("desc", u"Кастомный проект города")
                pdata.setdefault("icon", "STONE_BRICKS")
                pdata.setdefault("status", "DRAFT")
                pdata.setdefault("req_money", 10000.0)
                pdata.setdefault("req_items", {})
                pdata.setdefault("duration_sec", 24 * 3600)
                pdata.setdefault("start_time", 0)
                pdata.setdefault("end_time", 0)
                pdata.setdefault("contributed_money", 0.0)
                pdata.setdefault("contributed_items", {})

    def normalize_name(self, name):
        return to_unicode(name).strip().lower()

    def validate_name(self, name):
        value = to_unicode(name).strip()
        if len(value) < CitiesConfig.NAME_MIN_LENGTH or len(value) > CitiesConfig.NAME_MAX_LENGTH:
            return False
        return re.match(r'^[\w\-]+$', value, re.UNICODE) is not None

    def get_city(self, name):
        return self.data.get("cities", {}).get(self.normalize_name(name))

    def get_city_by_player(self, uuid_str):
        uuid_key = str(uuid_str)
        for city in self.data.get("cities", {}).values():
            if uuid_key in city.get("members", {}):
                return city
        return None

    def get_city_by_name(self, city_name):
        normalized = self.normalize_name(city_name)
        city = self.data.get("cities", {}).get(normalized)
        if city is not None:
            return city
        for item in self.data.get("cities", {}).values():
            if self.normalize_name(item.get("name")) == normalized:
                return item
            for alias in item.get("aliases", []):
                if self.normalize_name(alias) == normalized:
                    return item
        return None

    def is_active(self):
        return initialized and state is self

    def add_company_tax(self, city_name, amount):
        try:
            value = float(amount)
        except Exception:
            return False, 0.0
        if value != value or value in (float("inf"), float("-inf")) or value <= 0.0:
            return False, 0.0
        city = self.get_city_by_name(city_name)
        if city is None:
            return False, 0.0
        treasury = self.change_treasury(city, value, actor_name=u"Налог предприятий")
        return (treasury is not None), (treasury if treasury is not None else float(city.get("treasury", 0.0)))

    def get_company_tax_percent(self, city_name, operation, default_percent):
        city = self.get_city_by_name(city_name)
        if city is None:
            return float(default_percent)
        taxes = city.get("taxes", {})
        try:
            percent = float(taxes.get(operation, taxes.get("companies", default_percent)))
            if percent != percent or percent in (float("inf"), float("-inf")):
                return float(default_percent)
            return max(0.0, min(100.0, percent))
        except Exception:
            return float(default_percent)

    # ФИКС: отключение телепортов к себе через &f/town tp off&r.
    # Если игрок выключил свои входящие телепорты, он АВТОМАТИЧЕСКИ
    # теряет возможность телепортироваться и К ДРУГИМ жителям из GUI жителя
    # (взаимная блокировка — так и было запрошено пользователем).
    def is_tp_disabled(self, uuid_str):
        return bool(self.data.get("tp_disabled", {}).get(str(uuid_str), False))

    def set_tp_disabled(self, uuid_str, disabled):
        tp_map = self.data.setdefault("tp_disabled", {})
        uuid_key = str(uuid_str)
        if disabled:
            tp_map[uuid_key] = True
        else:
            tp_map.pop(uuid_key, None)
        self.save()

    def create_city(self, name, mayor_uuid, mayor_name):
        city_id = self.normalize_name(name)
        now = int(time.time())
        starter_proj = {
            "monument": {
                "id": "monument",
                "name": u"Памятник Основателям",
                "desc": u"Статуя в центре города в честь первого Мэра",
                "icon": "STONE_BRICKS",
                "status": "DRAFT",
                "req_money": 5000.0,
                "req_items": {"STONE_BRICKS": 128, "OAK_LOG": 32},
                "duration_sec": 12 * 3600,
                "start_time": 0,
                "end_time": 0,
                "contributed_money": 0.0,
                "contributed_items": {}
            }
        }
        city = {
            "id": city_id,
            "name": to_unicode(name).strip(),
            "mayor_uuid": str(mayor_uuid),
            "mayor_name": to_unicode(mayor_name),
            "treasury": 0.0,
            "taxes": {
                "companies": CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT,
                "primary": CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT,
                "resale": CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT,
                "dividends": CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT,
                "tradehall": CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT
            },
            "color": "white",
            "roles": {
                "mayor": {"name": "mayor", "display": u"Мэр", "color": "gold"},
                "citizen": {"name": "citizen", "display": u"Житель", "color": "gray"},
                "deputy": {"name": "deputy", "display": u"Заместитель", "color": "aqua"},
                "builder": {"name": "builder", "display": u"Строитель", "color": "yellow"}
            },
            "member_roles": {str(mayor_uuid): ["mayor"]},
            "members": {str(mayor_uuid): to_unicode(mayor_name)},
            "log": [u"§aГород был основан!"],
            "custom_projects": starter_proj,
            "quest_progress": {"iron": 0, "mobs": 0},
            "contributions": {str(mayor_uuid): 0.0},
            "rank_perms": {
                "mayor": ["INVITE", "KICK", "SPEND_TREASURY", "SET_TAX", "MANAGE_QUESTS", "MANAGE_PROJECTS"],
                "deputy": ["INVITE", "KICK", "MANAGE_QUESTS", "MANAGE_PROJECTS"],
                "builder": ["MANAGE_PROJECTS", "MANAGE_QUESTS", "INVITE"],
                "citizen": []
            },
            "created_at": now,
            "updated_at": now
        }
        self.data.setdefault("cities", {})[city_id] = city
        self.add_server_audit(u"§aОснован город §e%s §7(Мэр: %s)" % (to_unicode(name), to_unicode(mayor_name)))
        self.save()
        return city

    def delete_city(self, city):
        city_id = city.get("id")
        audit_snapshot = list(self.data.get("server_audit", []))
        if city_id in self.data.get("cities", {}):
            del self.data["cities"][city_id]
        self.add_server_audit(u"§cРаспущен город §e%s" % to_unicode(city.get("name")))
        if not self.save():
            self.data.setdefault("cities", {})[city_id] = city
            self.data["server_audit"] = audit_snapshot
            return False
        return True

    def add_server_audit(self, msg):
        audit_list = self.data.setdefault("server_audit", [])
        t_str = time.strftime("%d.%m %H:%M")
        audit_list.insert(0, u"[%s] %s" % (to_unicode(t_str), to_unicode(msg)))
        if len(audit_list) > 20:
            self.data["server_audit"] = audit_list[:20]

    def add_member(self, city, uuid_str, name):
        city.setdefault("members", {})[str(uuid_str)] = to_unicode(name)
        city.setdefault("member_roles", {}).setdefault(str(uuid_str), ["citizen"])
        city.setdefault("contributions", {}).setdefault(str(uuid_str), 0.0)
        self.add_treasury_log(city, u"§a+ §f" + to_unicode(name) + u" §7вступил в город")
        city["updated_at"] = int(time.time())
        self.save()

    def remove_member(self, city, uuid_str):
        members = city.setdefault("members", {})
        m_name = members.get(str(uuid_str), u"Житель")
        if str(uuid_str) in members:
            del members[str(uuid_str)]
        roles = city.setdefault("member_roles", {})
        if str(uuid_str) in roles:
            del roles[str(uuid_str)]
        self.add_treasury_log(city, u"§c- §f" + to_unicode(m_name) + u" §7покинул город")
        city["updated_at"] = int(time.time())
        self.save()

    def set_mayor(self, city, uuid_str, name):
        old_mayor_uuid = str(city.get("mayor_uuid"))
        self.add_member(city, uuid_str, name)
        old_roles = city.setdefault("member_roles", {}).setdefault(old_mayor_uuid, [])
        if "mayor" in old_roles:
            old_roles.remove("mayor")
        if "citizen" not in old_roles:
            old_roles.append("citizen")
        city["mayor_uuid"] = str(uuid_str)
        city["mayor_name"] = to_unicode(name)
        new_roles = city.setdefault("member_roles", {}).setdefault(str(uuid_str), [])
        if "mayor" not in new_roles:
            new_roles.insert(0, "mayor")
        self.add_treasury_log(city, u"§6Новый Мэр: §f" + to_unicode(name))
        self.add_server_audit(u"§6Новый Мэр города §e%s§7: §f%s" % (to_unicode(city.get("name")), to_unicode(name)))
        city["updated_at"] = int(time.time())
        self.save()

    def change_treasury(self, city, delta, actor_name=None, actor_uuid=None):
        snapshot = copy.deepcopy(city)
        current = float(city.get("treasury", 0.0))
        change = float(delta)
        if current != current or change != change or current in (float("inf"), float("-inf")) or change in (float("inf"), float("-inf")):
            return None
        new_total = current + change
        if new_total < 0.0 or new_total > 10000000000000000.0:
            return None
        city["treasury"] = round(new_total, 2)
        if delta > 0:
            if actor_name:
                self.add_treasury_log(city, u"§f" + to_unicode(actor_name) + u" §aвнёс +" + format_currency(delta))
            if actor_uuid:
                contribs = city.setdefault("contributions", {})
                contribs[str(actor_uuid)] = round(float(contribs.get(str(actor_uuid), 0.0)) + change, 2)
        elif delta < 0 and actor_name:
            self.add_treasury_log(city, u"§f" + to_unicode(actor_name) + u" §cснял " + format_currency(abs(delta)))
        city["updated_at"] = int(time.time())
        if not self.save():
            city.clear()
            city.update(snapshot)
            return None
        return city["treasury"]

    def set_treasury(self, city, amount, actor_name=None):
        snapshot = copy.deepcopy(city)
        try:
            value = float(amount)
        except Exception:
            return None
        if value != value or value in (float("inf"), float("-inf")) or value < 0.0 or value > 10000000000000000.0:
            return None
        city["treasury"] = round(value, 2)
        if actor_name:
            self.add_treasury_log(city, u"§f" + to_unicode(actor_name) + u" §eустановил казну: " + format_currency(value))
        city["updated_at"] = int(time.time())
        if not self.save():
            city.clear()
            city.update(snapshot)
            return None
        return city["treasury"]

    def add_treasury_log(self, city, msg):
        log_list = city.setdefault("log", [])
        t_str = time.strftime("%d.%m %H:%M")
        log_list.insert(0, u"[%s] %s" % (to_unicode(t_str), to_unicode(msg)))
        if len(log_list) > 10:
            city["log"] = log_list[:10]

    def list_cities(self):
        cities = list(self.data.get("cities", {}).values())
        return sorted(cities, key=lambda city: to_unicode(city.get("name", "")).lower())

    def set_color(self, city, color_name):
        city["color"] = color_name
        city["updated_at"] = int(time.time())
        self.save()

    def set_tax(self, city, tax_type, percent):
        snapshot = copy.deepcopy(city)
        try:
            value = float(percent)
        except Exception:
            return False
        if value != value or value in (float("inf"), float("-inf")) or value < 0.0 or value > 100.0:
            return False
        taxes = city.setdefault("taxes", {})
        taxes[tax_type] = round(value, 2)
        # Общая ставка предприятий является мастер-ставкой. Раньше GUI менял
        # только ``companies``, тогда как биржа читала ``primary``, ``resale``
        # и ``dividends``. В результате отображаемый налог и реальное списание
        # расходились. Явная настройка отдельного типа по-прежнему меняет
        # только выбранную операцию.
        if tax_type == "companies":
            for operation in ("primary", "resale", "dividends", "tradehall"):
                taxes[operation] = round(value, 2)
        self.add_treasury_log(city, u"§eНалог %s установлен: %s%%" % (to_unicode(tax_type), str(value)))
        city["updated_at"] = int(time.time())
        if not self.save():
            city.clear()
            city.update(snapshot)
            return False
        return True

    def rename_city(self, city, new_name):
        snapshot = copy.deepcopy(city)
        old_id = city.get("id")
        old_name = city.get("name")
        new_id = self.normalize_name(new_name)
        aliases = city.setdefault("aliases", [])
        if old_name and self.normalize_name(old_name) != new_id and old_name not in aliases:
            aliases.append(to_unicode(old_name))
            if len(aliases) > 10:
                del aliases[:-10]
        city["id"] = new_id
        city["name"] = to_unicode(new_name).strip()
        city["updated_at"] = int(time.time())
        if old_id in self.data.get("cities", {}):
            del self.data["cities"][old_id]
        self.data.setdefault("cities", {})[new_id] = city
        if not self.save():
            self.data["cities"].pop(new_id, None)
            city.clear()
            city.update(snapshot)
            self.data["cities"][old_id] = city
            return None
        return city

    def create_role(self, city, role_name):
        key = self.normalize_name(role_name)
        city.setdefault("roles", {})[key] = {"name": key, "display": to_unicode(role_name), "color": "white"}
        city["updated_at"] = int(time.time())
        self.save()
        return key

    def set_role_color(self, city, role_name, color_name):
        key = self.normalize_name(role_name)
        roles = city.setdefault("roles", {})
        if key not in roles:
            return None
        role_data = roles[key]
        if not isinstance(role_data, dict):
            role_data = {"name": key, "display": to_unicode(role_name)}
            roles[key] = role_data
        role_data["color"] = color_name
        city["updated_at"] = int(time.time())
        self.save()
        return key

    def delete_role(self, city, role_name):
        key = self.normalize_name(role_name)
        if key in ("citizen", "mayor"):
            return False
        roles = city.setdefault("roles", {})
        if key in roles:
            del roles[key]
        for player_roles in city.setdefault("member_roles", {}).values():
            if key in player_roles:
                player_roles.remove(key)
        city["updated_at"] = int(time.time())
        self.save()
        return True

    def give_role(self, city, uuid_str, role_name):
        key = self.normalize_name(role_name)
        roles = city.setdefault("member_roles", {}).setdefault(str(uuid_str), [])
        if key not in roles:
            roles.append(key)
        city["updated_at"] = int(time.time())
        self.save()

    def take_role(self, city, uuid_str, role_name):
        key = self.normalize_name(role_name)
        roles = city.setdefault("member_roles", {}).setdefault(str(uuid_str), [])
        if key in roles and key != "mayor":
            roles.remove(key)
        city["updated_at"] = int(time.time())
        self.save()

    def create_invite(self, city, uuid_str, name, inviter_name):
        self.data.setdefault("invites", {})[str(uuid_str)] = {
            "city_id": city.get("id"),
            "city_name": city.get("name"),
            "player_name": to_unicode(name),
            "inviter_name": to_unicode(inviter_name),
            "expires_at": int(time.time() + CitiesConfig.INVITE_TIMEOUT_SECONDS)
        }
        self.save()

    def get_invite(self, uuid_str, city_name=None):
        invite = self.data.setdefault("invites", {}).get(str(uuid_str))
        if not invite:
            return None
        if int(invite.get("expires_at", 0)) < int(time.time()):
            self.remove_invite(uuid_str)
            return None
        if city_name and self.normalize_name(city_name) != self.normalize_name(invite.get("city_name")):
            return None
        return invite

    def remove_invite(self, uuid_str):
        invites = self.data.setdefault("invites", {})
        if str(uuid_str) in invites:
            del invites[str(uuid_str)]
        self.save()

    def create_custom_project(self, city, proj_id, name, desc, icon):
        pid = self.normalize_name(proj_id)
        cproj = city.setdefault("custom_projects", {})
        cproj[pid] = {
            "id": pid,
            "name": to_unicode(name),
            "desc": to_unicode(desc),
            "icon": str(icon),
            "status": "DRAFT",
            "req_money": 10000.0,
            "req_items": {},
            "duration_sec": 24 * 3600,
            "start_time": 0,
            "end_time": 0,
            "contributed_money": 0.0,
            "contributed_items": {}
        }
        city["updated_at"] = int(time.time())
        self.save()
        return pid

    def delete_custom_project(self, city, proj_id):
        pid = self.normalize_name(proj_id)
        cproj = city.setdefault("custom_projects", {})
        if pid in cproj:
            del cproj[pid]
            city["updated_at"] = int(time.time())
            self.save()
            return True
        return False

    def create_custom_quest(self, qid, title, mat_name, count, reward_money):
        cquests = self.data.setdefault("custom_quests", {})
        cquests[qid] = {
            "id": qid,
            "title": to_unicode(title),
            "material": str(mat_name),
            "required_count": max(1, int(count)),
            "reward_money": float(reward_money),
            "created_at": int(time.time())
        }
        self.save()
        return qid

    def delete_custom_quest(self, qid):
        cquests = self.data.setdefault("custom_quests", {})
        if qid in cquests:
            del cquests[qid]
            self.save()
            return True
        return False


class CityService(object):
    def __init__(self, state, economy):
        self.state = state
        self.economy = economy

    def resolve_player(self, name):
        if BUKKIT_AVAILABLE:
            try:
                player = Bukkit.getPlayer(to_java_string(name))
                if player and player.isOnline():
                    uuid_str, player_name = get_sender_uuid_and_name(player)
                    return self.economy.get_or_create(uuid_str, player_name)
            except Exception:
                pass
        return self.economy.get_account_by_name(name)

    def get_role_display(self, city, role_key):
        key = self.state.normalize_name(role_key)
        role = city.get("roles", {}).get(key)
        if isinstance(role, dict) and role.get("display"):
            return to_unicode(role.get("display"))
        return to_unicode(role_key).strip().capitalize()

    def get_role_color_key(self, city, role_key):
        key = self.state.normalize_name(role_key)
        role = city.get("roles", {}).get(key)
        if isinstance(role, dict):
            color_key = to_unicode(role.get("color", "white")).lower()
            if color_key in CitiesConfig.COLORS:
                return color_key
        return "white"

    def get_role_color_prefix(self, city, role_key):
        color_key = self.get_role_color_key(city, role_key)
        return CitiesConfig.COLORS.get(color_key, CitiesConfig.COLORS["white"])[1]

    def format_player_label(self, city, uuid_str, name):
        town_color_key = city.get("color", "white")
        town_color = CitiesConfig.COLORS.get(town_color_key, CitiesConfig.COLORS["white"])[1]
        role_key = self.get_primary_role(city, uuid_str)
        role_display = self.get_role_display(city, role_key)
        role_color = self.get_role_color_prefix(city, role_key)

        abbr_map = {
            "mayor": u"[М]",
            "deputy": u"[ЗМ]",
            "builder": u"[СТ]",
            "citizen": u"[Ж]"
        }
        short_abbr = abbr_map.get(role_key, u"[%s]" % role_display[:2].upper())

        full_label = colorize(role_color + u"[" + role_display + u"] " + town_color + name)
        return role_key, short_abbr, full_label

    def get_primary_role(self, city, uuid_str):
        roles = city.get("member_roles", {}).get(str(uuid_str), [])
        if str(city.get("mayor_uuid")) == str(uuid_str):
            return "mayor"
        if roles:
            return roles[0]
        return "citizen"

    def group_members_by_role(self, city):
        result = {}
        members = city.get("members", {})
        for uuid_str, name in members.items():
            roles = city.get("member_roles", {}).get(uuid_str, ["citizen"])
            if str(city.get("mayor_uuid")) == str(uuid_str) and "mayor" not in roles:
                roles = ["mayor"] + list(roles)
            for role in roles:
                result.setdefault(role, []).append(to_unicode(name))
        return result

    def get_members_balance_total(self, city):
        total = 0.0
        if not self.economy.is_ready():
            return total
        for uuid_str in city.get("members", {}).keys():
            try:
                total += float(self.economy.get_balance(uuid_str))
            except Exception:
                pass
        return total

    def get_companies_summary(self, city):
        companies = get_city_companies(city.get("name"))
        total_capital = 0.0
        for company in companies:
            total_capital += get_company_capitalization(company)
        return len(companies), total_capital

    def set_tax(self, sender, tax_type, percent):
        city = self.require_own_city(sender)
        if not city or not self.can_manage(sender, city):
            return
        tax_key = to_unicode(tax_type).lower()
        if tax_key == "all":
            tax_key = "companies"
        if tax_key not in CitiesConfig.TAX_TYPES:
            send_message(sender, CitiesConfig.PREFIX + u"&cТип налога: &ecompanies, primary, resale, dividends, tradehall")
            return
        if not self.state.set_tax(city, tax_key, percent):
            send_message(sender, CitiesConfig.PREFIX + u"&cНалог не изменен: значение некорректно или данные не удалось сохранить.")
            return
        send_message(sender, CitiesConfig.PREFIX + u"&aНалог &e{0}&a города &b{1}&a установлен: &e{2}%&a.".format(
            CitiesConfig.TAX_TYPES.get(tax_key, tax_key),
            city.get("name"),
            round(float(percent), 2)
        ))

    def create_city(self, sender, name):
        uuid_str, player_name = get_sender_uuid_and_name(sender)
        if not uuid_str:
            send_message(sender, CitiesConfig.PREFIX + u"&cТолько игрок может создать город.")
            return
        if not self.state.validate_name(name):
            send_message(sender, CitiesConfig.PREFIX + u"&cНазвание: 3-24 символа, буквы/цифры/_/-.")
            return
        if self.state.get_city(name):
            send_message(sender, CitiesConfig.PREFIX + u"&cГород с таким названием уже существует.")
            return
        if self.state.get_city_by_player(uuid_str):
            send_message(sender, CitiesConfig.PREFIX + u"&cВы уже состоите в городе.")
            return
        self.economy.get_or_create(uuid_str, player_name)
        city = self.state.create_city(name, uuid_str, player_name)
        # Устанавливаем "дом города" — точка, где стоял Мэр при создании.
        try:
            if isinstance(sender, Player):
                loc = sender.getLocation()
                city["home"] = {
                    "world": loc.getWorld().getName(),
                    "x": float(loc.getX()),
                    "y": float(loc.getY()),
                    "z": float(loc.getZ()),
                    "yaw": float(loc.getYaw()),
                    "pitch": float(loc.getPitch()),
                }
                self.state.save()
        except Exception:
            pass
        send_message(sender, CitiesConfig.PREFIX + u"&aГород &e{0}&a создан. Вы стали мэром.".format(city["name"]))
        if city.get("home"):
            send_message(sender, CitiesConfig.PREFIX + u"&7Дом города установлен здесь. Использовать: &f/town home&7.")

    def add_member(self, sender, player_name):
        city = self.require_own_city(sender)
        if not city:
            return
        if not self.can_manage(sender, city):
            return
        account = self.resolve_player(player_name)
        if not account:
            send_message(sender, CitiesConfig.PREFIX + u"&cИгрок &e{0}&c не найден в экономике.".format(player_name))
            return
        if self.state.get_city_by_player(account.uuid):
            send_message(sender, CitiesConfig.PREFIX + u"&cЭтот игрок уже состоит в городе.")
            return
        sender_uuid, sender_name = get_sender_uuid_and_name(sender)
        self.state.create_invite(city, account.uuid, account.name, sender_name)
        send_message(sender, CitiesConfig.PREFIX + u"&aПриглашение отправлено игроку &e{0}&a.".format(account.name))
        self.send_invite(account.name, city, sender_name)

    def accept_invite(self, sender, city_name=None):
        uuid_str, player_name = get_sender_uuid_and_name(sender)
        invite = self.state.get_invite(uuid_str, city_name)
        if not invite:
            send_message(sender, CitiesConfig.PREFIX + u"&cАктивное приглашение не найдено.")
            return
        if self.state.get_city_by_player(uuid_str):
            self.state.remove_invite(uuid_str)
            send_message(sender, CitiesConfig.PREFIX + u"&cВы уже состоите в городе.")
            return
        city = self.state.get_city(invite.get("city_name"))
        if not city:
            self.state.remove_invite(uuid_str)
            send_message(sender, CitiesConfig.PREFIX + u"&cГород больше не существует.")
            return
        self.state.add_member(city, uuid_str, player_name)
        self.state.remove_invite(uuid_str)
        self.apply_player_color(sender)
        send_message(sender, CitiesConfig.PREFIX + u"&aВы вступили в город &e{0}&a.".format(city.get("name")))

    def deny_invite(self, sender, city_name=None):
        uuid_str, player_name = get_sender_uuid_and_name(sender)
        invite = self.state.get_invite(uuid_str, city_name)
        if not invite:
            send_message(sender, CitiesConfig.PREFIX + u"&cАктивное приглашение не найдено.")
            return
        self.state.remove_invite(uuid_str)
        send_message(sender, CitiesConfig.PREFIX + u"&7Вы отклонили приглашение в город &e{0}&7.".format(invite.get("city_name")))

    def remove_member(self, sender, player_name):
        city = self.require_own_city(sender)
        if not city:
            return
        if not self.can_manage(sender, city):
            return
        account = self.resolve_player(player_name)
        if not account or str(account.uuid) not in city.get("members", {}):
            send_message(sender, CitiesConfig.PREFIX + u"&cИгрок не является жителем вашего города.")
            return
        if str(account.uuid) == str(city.get("mayor_uuid")):
            send_message(sender, CitiesConfig.PREFIX + u"&cНельзя удалить мэра. Сначала назначьте другого мэра.")
            return
        if player_owns_city_company(city, account.uuid):
            send_message(sender, CitiesConfig.PREFIX + u"&cНельзя удалить владельца предприятия. Сначала предприятие должно быть закрыто.")
            return
        self.state.remove_member(city, account.uuid)
        self.reset_player_color_by_name(account.name)
        send_message(sender, CitiesConfig.PREFIX + u"&aИгрок &e{0}&a удален из города.".format(account.name))
        self.notify_player(account.name, u"&cВас удалили из города &e{0}&c.".format(city["name"]))

    def set_mayor(self, sender, player_name):
        city = self.require_own_city(sender)
        if not city:
            return
        if not self.can_manage(sender, city):
            return
        account = self.resolve_player(player_name)
        if not account or str(account.uuid) not in city.get("members", {}):
            send_message(sender, CitiesConfig.PREFIX + u"&cНовый мэр должен быть жителем города.")
            return
        old_mayor_uuid = city.get("mayor_uuid")
        self.state.set_mayor(city, account.uuid, account.name)
        self.apply_player_color_by_uuid(old_mayor_uuid)
        self.apply_player_color_by_uuid(account.uuid)
        send_message(sender, CitiesConfig.PREFIX + u"&aНовым мэром города &e{0}&a стал &e{1}&a.".format(city["name"], account.name))
        self.notify_player(account.name, u"&aВы стали мэром города &e{0}&a.".format(city["name"]))

    def rename(self, sender, new_name):
        city = self.require_own_city(sender)
        if not city or not self.can_manage(sender, city):
            return
        if not self.state.validate_name(new_name):
            send_message(sender, CitiesConfig.PREFIX + u"&cНазвание: 3-24 символа, буквы/цифры/_/-.")
            return
        if self.state.get_city(new_name):
            send_message(sender, CitiesConfig.PREFIX + u"&cГород с таким названием уже существует.")
            return
        old_name = city.get("name")
        city = self.state.rename_city(city, new_name)
        if city is None:
            send_message(sender, CitiesConfig.PREFIX + u"&cПереименование отменено: данные города не удалось сохранить.")
            return
        send_message(sender, CitiesConfig.PREFIX + u"&aГород &e{0}&a переименован в &e{1}&a.".format(old_name, city.get("name")))

    def set_color(self, sender, color_name):
        city = self.require_own_city(sender)
        if not city or not self.can_manage(sender, city):
            return
        color_key = to_unicode(color_name).lower()
        if color_key not in CitiesConfig.COLORS:
            send_message(sender, CitiesConfig.PREFIX + u"&cЦвет не найден. Доступно: &e{0}".format(u", ".join(sorted(CitiesConfig.COLORS.keys()))))
            return
        self.state.set_color(city, color_key)
        self.apply_city_color(city)
        send_message(sender, CitiesConfig.PREFIX + u"&aЦвет ников города &e{0}&a изменен на &e{1}&a.".format(city.get("name"), color_key))

    def create_role(self, sender, role_name):
        city = self.require_own_city(sender)
        if not city or not self.can_manage(sender, city):
            return
        if not self.state.validate_name(role_name):
            send_message(sender, CitiesConfig.PREFIX + u"&cНазвание роли: 3-24 символа, буквы/цифры/_/-.")
            return
        key = self.state.create_role(city, role_name)
        send_message(sender, CitiesConfig.PREFIX + u"&aРоль &e{0}&a создана.".format(self.get_role_display(city, key)))

    def delete_role(self, sender, role_name):
        city = self.require_own_city(sender)
        if not city or not self.can_manage(sender, city):
            return
        if self.state.delete_role(city, role_name):
            self.apply_city_color(city)
            send_message(sender, CitiesConfig.PREFIX + u"&aРоль удалена.")
        else:
            send_message(sender, CitiesConfig.PREFIX + u"&cЭту роль нельзя удалить.")

    def set_role_color(self, sender, role_name, color_name):
        city = self.require_own_city(sender)
        if not city or not self.can_manage(sender, city):
            return
        color_key = to_unicode(color_name).lower()
        if color_key not in CitiesConfig.COLORS:
            send_message(sender, CitiesConfig.PREFIX + u"&cЦвет не найден. Доступно: &e{0}".format(u", ".join(sorted(CitiesConfig.COLORS.keys()))))
            return
        role_key = self.state.set_role_color(city, role_name, color_key)
        if not role_key:
            send_message(sender, CitiesConfig.PREFIX + u"&cРоль не найдена.")
            return
        self.apply_city_color(city)
        send_message(sender, CitiesConfig.PREFIX + u"&aЦвет роли &e{0}&a изменен на &e{1}&a.".format(self.get_role_display(city, role_key), color_key))

    def give_role(self, sender, player_name, role_name):
        city = self.require_own_city(sender)
        if not city or not self.can_manage(sender, city):
            return
        account = self.resolve_player(player_name)
        role_key = self.state.normalize_name(role_name)
        if not account or str(account.uuid) not in city.get("members", {}):
            send_message(sender, CitiesConfig.PREFIX + u"&cИгрок не является жителем города.")
            return
        if role_key not in city.get("roles", {}) and role_key != "mayor":
            send_message(sender, CitiesConfig.PREFIX + u"&cРоль не найдена.")
            return
        self.state.give_role(city, account.uuid, role_key)
        self.apply_player_color_by_uuid(account.uuid)
        send_message(sender, CitiesConfig.PREFIX + u"&aИгроку &e{0}&a выдана роль &e{1}&a.".format(account.name, self.get_role_display(city, role_key)))

    def take_role(self, sender, player_name, role_name):
        city = self.require_own_city(sender)
        if not city or not self.can_manage(sender, city):
            return
        account = self.resolve_player(player_name)
        if not account or str(account.uuid) not in city.get("members", {}):
            send_message(sender, CitiesConfig.PREFIX + u"&cИгрок не является жителем города.")
            return
        self.state.take_role(city, account.uuid, role_name)
        self.apply_player_color_by_uuid(account.uuid)
        send_message(sender, CitiesConfig.PREFIX + u"&aРоль снята с игрока &e{0}&a.".format(account.name))

    def deposit(self, sender, amount):
        uuid_str, player_name = get_sender_uuid_and_name(sender)
        city = self.require_own_city(sender)
        if not city:
            return
        if not self.economy.is_ready():
            send_message(sender, CitiesConfig.PREFIX + u"&cЭкономика сейчас отключена. Операция отменена.")
            return
        if self.economy.get_balance(uuid_str) < amount:
            send_message(sender, CitiesConfig.PREFIX + u"&cНедостаточно денег.")
            return
        if not self.economy.withdraw(uuid_str, amount):
            send_message(sender, CitiesConfig.PREFIX + u"&cНе удалось сохранить списание. Баланс не изменён.")
            return
        total = self.state.change_treasury(city, amount, actor_name=player_name, actor_uuid=uuid_str)
        if total is None:
            refunded, balance = self.economy.deposit_checked(uuid_str, amount, player_name)
            if not refunded:
                log_info(u"CRITICAL: failed to refund town deposit for {0}, amount={1}".format(player_name, amount))
                send_message(sender, CitiesConfig.PREFIX + u"&4Ошибка возврата денег. Немедленно сообщите администратору.")
            else:
                send_message(sender, CitiesConfig.PREFIX + u"&cНе удалось сохранить казну. Операция отменена, деньги возвращены.")
            return
        send_message(sender, CitiesConfig.PREFIX + u"&aВы пополнили казну &e{0}&a на &6{1}&a. Казна: &6{2}&a.".format(
            city["name"], format_currency(amount), format_currency(total)
        ))

    def withdraw(self, sender, amount):
        uuid_str, player_name = get_sender_uuid_and_name(sender)
        city = self.require_own_city(sender)
        if not city:
            return
        if not self.can_manage(sender, city):
            return
        treasury = float(city.get("treasury", 0.0))
        if amount > treasury:
            send_message(sender, CitiesConfig.PREFIX + u"&cВ казне недостаточно денег. Сейчас: &e{0}&c.".format(format_currency(treasury)))
            return
        if not self.economy.is_ready():
            send_message(sender, CitiesConfig.PREFIX + u"&cЭкономика сейчас отключена. Операция отменена.")
            return
        city_snapshot = copy.deepcopy(city)
        total = self.state.change_treasury(city, -amount, actor_name=player_name)
        if total is None:
            send_message(sender, CitiesConfig.PREFIX + u"&cНе удалось сохранить казну. Операция отменена.")
            return
        deposited, balance = self.economy.deposit_checked(uuid_str, amount, player_name)
        if not deposited:
            city.clear()
            city.update(city_snapshot)
            restored = self.state.save()
            if not restored:
                log_info(u"CRITICAL: failed to roll back town withdrawal for {0}, amount={1}".format(player_name, amount))
            send_message(sender, CitiesConfig.PREFIX + u"&cНе удалось начислить деньги. Операция отменена.")
            return
        send_message(sender, CitiesConfig.PREFIX + u"&aВы вывели из казны &6{0}&a. Ваш баланс: &e{1}&a.".format(
            format_currency(amount), format_currency(balance)
        ))

    def leave(self, sender):
        uuid_str, player_name = get_sender_uuid_and_name(sender)
        city = self.state.get_city_by_player(uuid_str)
        if not city:
            send_message(sender, CitiesConfig.PREFIX + u"&cВы не состоите в городе.")
            return
        if str(city.get("mayor_uuid")) == str(uuid_str):
            send_message(sender, CitiesConfig.PREFIX + u"&cМэр не может выйти. Передайте пост или распустите город.")
            return
        if player_owns_city_company(city, uuid_str):
            send_message(sender, CitiesConfig.PREFIX + u"&cСначала закройте принадлежащие вам предприятия этого города.")
            return
        self.state.remove_member(city, uuid_str)
        self.reset_player_color(sender)
        send_message(sender, CitiesConfig.PREFIX + u"&aВы покинули город &e{0}&a.".format(city["name"]))

    def disband(self, sender):
        city = self.require_own_city(sender)
        if not city:
            return
        if not self.can_manage(sender, city):
            return
        if get_city_companies(city.get("name")):
            send_message(sender, CitiesConfig.PREFIX + u"&cНельзя распустить город, пока в нем зарегистрированы предприятия.")
            return
        name = city.get("name")
        member_uuids = list(city.get("members", {}).keys())
        if not self.state.delete_city(city):
            send_message(sender, CitiesConfig.PREFIX + u"&cГород не удален: данные не удалось сохранить.")
            return
        for player_uuid in member_uuids:
            player = self.get_online_player_by_uuid(player_uuid)
            if player:
                self.reset_player_color(player)
        send_message(sender, CitiesConfig.PREFIX + u"&cГород &e{0}&c удален. Казна удаленного города сгорает.".format(name))

    # ----- ДОМ ГОРОДА (/town home / /town sethome) -----
    # CD на телепорт 45 минут для всех жителей. Мэр может сбросить home
    # командой /town sethome (в текущей позиции).
    HOME_TP_COOLDOWN_SECONDS = 45 * 60

    def town_home(self, sender):
        if not isinstance(sender, Player):
            send_message(sender, CitiesConfig.PREFIX + u"&cТолько для игроков.")
            return
        if deny_city_teleport_during_nuclear_drop(sender):
            return
        city = self.require_own_city(sender)
        if not city:
            return
        home = city.get("home")
        if not home:
            send_message(sender, CitiesConfig.PREFIX + u"&cДом города не установлен. Мэр может задать его через &f/town sethome&c.")
            return

        uuid_str, name = get_sender_uuid_and_name(sender)
        # Проверка CD (per-player).
        cd_map = city.setdefault("home_cd", {})
        last_use = float(cd_map.get(uuid_str, 0.0))
        now = time.time()
        remaining = self.HOME_TP_COOLDOWN_SECONDS - (now - last_use)
        # Мэр и админ — без КД.
        is_mayor = (str(city.get("mayor_uuid")) == str(uuid_str))
        if not (is_admin(sender) or is_mayor) and remaining > 0:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            send_message(sender, CitiesConfig.PREFIX +
                u"&cПерезарядка: &f{0} мин {1} сек&c.".format(mins, secs))
            return

        # Проверяем что мир существует.
        try:
            w = Bukkit.getWorld(to_java_string(home.get("world", "world")))
            if w is None:
                send_message(sender, CitiesConfig.PREFIX + u"&cМир дома города не найден.")
                return
            target_loc = Location(w,
                float(home.get("x", 0.0)),
                float(home.get("y", 64.0)),
                float(home.get("z", 0.0)),
                float(home.get("yaw", 0.0)),
                float(home.get("pitch", 0.0)))
            sender.teleport(target_loc)
            try: sender.setFallDistance(0.0)
            except Exception: pass
            send_message(sender, CitiesConfig.PREFIX + u"&aВы дома. &7Следующий телепорт: через 45 минут.")
            try:
                sender.playSound(sender.getLocation(),
                    Sound.ENTITY_ENDERMAN_TELEPORT, 1.0, 1.0)
            except Exception: pass
        except Exception as exc:
            send_message(sender, CitiesConfig.PREFIX + u"&cОшибка телепорта: {0}".format(exc))
            return

        # Кладём CD.
        cd_map[uuid_str] = now
        self.state.save()

    def town_sethome(self, sender):
        if not isinstance(sender, Player):
            send_message(sender, CitiesConfig.PREFIX + u"&cТолько для игроков.")
            return
        city = self.require_own_city(sender)
        if not city:
            return
        if not self.can_manage(sender, city):
            return
        loc = sender.getLocation()
        city["home"] = {
            "world": loc.getWorld().getName(),
            "x":     float(loc.getX()),
            "y":     float(loc.getY()),
            "z":     float(loc.getZ()),
            "yaw":   float(loc.getYaw()),
            "pitch": float(loc.getPitch()),
        }
        # Сброс CD для всех — новый дом, отсчёт заново.
        city["home_cd"] = {}
        self.state.save()
        send_message(sender, CitiesConfig.PREFIX +
            u"&a✓ Дом города установлен здесь. &7Все КД сброшены.")

    def require_own_city(self, sender):
        uuid_str, player_name = get_sender_uuid_and_name(sender)
        if not uuid_str:
            send_message(sender, CitiesConfig.PREFIX + u"&cЭта команда доступна только игрокам.")
            return None
        city = self.state.get_city_by_player(uuid_str)
        if not city:
            send_message(sender, CitiesConfig.PREFIX + u"&cВы не состоите в городе.")
            return None
        return city

    def town_tp_toggle(self, sender, enable):
        u"""
        ФИКС (по запросу пользователя): /town tp <on|off>.
        Когда игрок выключает входящие телепорты к себе (чтобы никто
        из его города не мог телепортироваться к нему через GUI жителя),
        автоматически отключаются и его телепорты К другим жителям (взаимная
        блокировка, как было запрошено). Доступно любому игроку, не только мэру.
        """
        if not isinstance(sender, Player):
            send_message(sender, CitiesConfig.PREFIX + u"&cТолько для игроков.")
            return
        uuid_str, player_name = get_sender_uuid_and_name(sender)
        if not uuid_str:
            return
        self.state.set_tp_disabled(uuid_str, not enable)
        if enable:
            send_message(sender, CitiesConfig.PREFIX + u"&a\u2713 Телепорты к вам и ваши телепорты к другим жителям включены.")
        else:
            send_message(sender, CitiesConfig.PREFIX + u"&c\u2718 Телепорты к вам ОТКЛЮЧЕНЫ. Ваши телепорты к другим жителям также отключены (взаимная блокировка).")


    def can_manage(self, sender, city):
        uuid_str, player_name = get_sender_uuid_and_name(sender)
        if is_admin(sender) or str(city.get("mayor_uuid")) == str(uuid_str):
            return True
        send_message(sender, CitiesConfig.PREFIX + u"&cЭта команда доступна только мэру города.")
        return False

    def can_manage_projects(self, sender, city):
        uuid_str, player_name = get_sender_uuid_and_name(sender)
        if is_admin(sender) or str(city.get("mayor_uuid")) == str(uuid_str):
            return True
        roles = city.get("member_roles", {}).get(str(uuid_str), [])
        if "deputy" in roles or "builder" in roles:
            return True
        for role in roles:
            perms = city.get("rank_perms", {}).get(role, [])
            if "MANAGE_PROJECTS" in perms:
                return True
        return False

    def notify_player(self, name, message):
        if not BUKKIT_AVAILABLE:
            return
        try:
            player = Bukkit.getPlayer(to_java_string(name))
            if player and player.isOnline():
                send_message(player, CitiesConfig.PREFIX + message)
        except Exception:
            pass

    def send_invite(self, name, city, mayor_name):
        if not BUKKIT_AVAILABLE:
            return
        try:
            player = Bukkit.getPlayer(to_java_string(name))
            if player and player.isOnline():
                send_clickable_invite(player, city.get("name"), mayor_name)
        except Exception:
            pass

    def get_online_player_by_uuid(self, uuid_str):
        if not BUKKIT_AVAILABLE:
            return None
        try:
            for player in Bukkit.getOnlinePlayers():
                if str(player.getUniqueId()) == str(uuid_str):
                    return player
        except Exception:
            pass
        return None

    def reset_player_color_by_name(self, name):
        if not BUKKIT_AVAILABLE:
            return
        try:
            player = Bukkit.getPlayer(to_java_string(name))
            if player and player.isOnline():
                self.reset_player_color(player)
        except Exception:
            pass

    def apply_player_color_by_uuid(self, uuid_str):
        player = self.get_online_player_by_uuid(uuid_str)
        if player:
            self.apply_player_color(player)

    def reset_player_color(self, player):
        try:
            name = get_sender_uuid_and_name(player)[1]
            self.remove_politic_team(player)
            player.setDisplayName(to_java_string(name))
            player.setPlayerListName(to_java_string(name))
            if hasattr(player, "setCustomName"):
                player.setCustomName(None)
            if hasattr(player, "setCustomNameVisible"):
                player.setCustomNameVisible(False)
        except Exception:
            pass

    def apply_city_color(self, city):
        for uuid_str in city.get("members", {}).keys():
            player = self.get_online_player_by_uuid(uuid_str)
            if player:
                self.apply_player_color(player)

    def apply_player_color(self, player):
        uuid_str, name = get_sender_uuid_and_name(player)
        city = self.state.get_city_by_player(uuid_str)
        if not city:
            self.reset_player_color(player)
            return
        color_key = city.get("color", "white")
        color_data = CitiesConfig.COLORS.get(color_key, CitiesConfig.COLORS["white"])
        town_color = color_data[1]
        role_key, short_abbr, full_label = self.format_player_label(city, uuid_str, name)
        role_color = self.get_role_color_prefix(city, role_key)

        # В ОБЩЕМ ТАБЕ (Tab) отображаем только ник в цвете города БЕЗ кастомных тегов!
        # displayName тоже без тегов ролей — vanilla-чат и многие плагины
        # подставляют displayName как имя, из-за чего теги ролей просачивались.
        tab_name = colorize(town_color + name)
        try:
            player.setDisplayName(to_java_string(tab_name))
            player.setPlayerListName(to_java_string(tab_name))
            if hasattr(player, "setCustomName"):
                player.setCustomName(to_java_string(tab_name))
            if hasattr(player, "setCustomNameVisible"):
                player.setCustomNameVisible(True)
            self.apply_scoreboard_team(player, color_key, town_color, role_color, short_abbr, city=city)
        except Exception:
            pass

    # -----------------------------------------------------------------
    # ТРАНСЛИТЕРАЦИЯ КИРИЛЛИЦЫ + ХЭШ ДЛЯ УНИКАЛЬНОСТИ TEAM-NAME
    # -----------------------------------------------------------------
    #
    # Bukkit ограничивает имя scoreboard-team 16 символами ASCII (A-Z, 0-9, _).
    # Кириллица не поддерживается: если просто заменить все не-латинские
    # символы на "_", разные города с одинаковой длиной названия получат
    # одинаковый team_name → баг "все города в одной /team".
    #
    # Схема:
    #   1. Транслитерируем кириллицу → латиница (простая карта).
    #   2. Убираем всё, что не [A-Za-z0-9_].
    #   3. К префиксу добавляем короткий хэш от полного city_id.
    #   4. Итог: "t_<8-transl>_<3-hash>" ≤ 16 симв., уникально даже для
    #      города-омонима.
    _CYR_MAP = {
        u"а": "a",  u"б": "b",  u"в": "v",  u"г": "g",  u"д": "d",
        u"е": "e",  u"ё": "e",  u"ж": "zh", u"з": "z",  u"и": "i",
        u"й": "y",  u"к": "k",  u"л": "l",  u"м": "m",  u"н": "n",
        u"о": "o",  u"п": "p",  u"р": "r",  u"с": "s",  u"т": "t",
        u"у": "u",  u"ф": "f",  u"х": "h",  u"ц": "c",  u"ч": "ch",
        u"ш": "sh", u"щ": "sh", u"ъ": "",   u"ы": "y",  u"ь": "",
        u"э": "e",  u"ю": "yu", u"я": "ya",
    }

    def _transliterate(self, text):
        out = []
        for ch in to_unicode(text or u""):
            lo = ch.lower()
            if lo in self._CYR_MAP:
                # Сохраняем регистр: первый символ = верхний если исходник был верхним.
                latin = self._CYR_MAP[lo]
                if ch.isupper() and latin:
                    latin = latin[0].upper() + latin[1:]
                out.append(latin)
            else:
                out.append(ch)
        return u"".join(out)

    def _short_hash(self, text, length=3):
        """3-символьный alphanumeric хэш (base36 от md5). Гарантирует
        различие даже для двух одинаковых транслитов."""
        try:
            import hashlib
            h = hashlib.md5(to_unicode(text or u"").encode("utf-8")).hexdigest()
            # Берём первые 6 hex-символов и переводим в base36 (0-9a-z).
            n = int(h[:6], 16)
            digits = "0123456789abcdefghijklmnopqrstuvwxyz"
            out = ""
            while n > 0 and len(out) < length:
                out = digits[n % 36] + out
                n //= 36
            return (out.rjust(length, "0"))[:length]
        except Exception:
            # Fallback — простая сумма по кодам.
            n = sum(ord(c) for c in to_unicode(text or u""))
            digits = "0123456789abcdefghijklmnopqrstuvwxyz"
            out = ""
            while n > 0 and len(out) < length:
                out = digits[n % 36] + out
                n //= 36
            return (out.rjust(length, "0"))[:length]

    def get_politic_team_name(self, player, city=None):
        """
        Возвращает уникальное имя scoreboard-team.
        - Если у игрока есть город → одна общая команда `t_<трансл>_<хэш>`
          (все жители одного города в одной /team). ≤16 символов, кириллица
          транслитерируется, хэш от полного city_id — гарантия уникальности
          между городами-омонимами по транслиту.
        - Если города нет → per-player fallback `pol_<uuid>`.
        """
        if city is not None:
            city_id = to_unicode(city.get("id", u""))
            # Транслитерация → чистка → обрезка до 8 символов.
            transl = self._transliterate(city_id)
            transl = re.sub(r'[^A-Za-z0-9_]', '', transl)
            transl = transl[:8].lower() if transl else u"x"
            # Хэш от исходного (не транслита!) city_id — 3 символа.
            h = self._short_hash(city_id, length=3)
            # Итог: "t_<8>_<3>" = максимум 2 + 8 + 1 + 3 = 14 символов.
            team_name = ("t_" + transl + "_" + h)[:16]
            return team_name
        uuid_str = get_sender_uuid_and_name(player)[0] or to_unicode(player.getName())
        clean = re.sub(r'[^A-Za-z0-9_]', '', to_unicode(uuid_str).replace("-", ""))[:10]
        return "pol_" + clean

    def get_player_scoreboard(self, player):
        try:
            board = player.getScoreboard()
            if board is not None:
                return board
        except Exception:
            pass
        try:
            return Bukkit.getScoreboardManager().getMainScoreboard()
        except Exception:
            return None

    def get_active_scoreboards(self):
        boards = []
        seen = set()
        if BUKKIT_AVAILABLE:
            try:
                main_board = Bukkit.getScoreboardManager().getMainScoreboard()
                if main_board is not None:
                    boards.append(main_board)
                    seen.add(str(main_board))
            except Exception:
                pass
            try:
                for online_player in Bukkit.getOnlinePlayers():
                    board = online_player.getScoreboard()
                    board_key = str(board)
                    if board is not None and board_key not in seen:
                        boards.append(board)
                        seen.add(board_key)
            except Exception:
                pass
        return boards

    def remove_politic_team(self, player):
        """
        Убирает игрока из ЛЮБЫХ наших scoreboard-команд (и per-player pol_*,
        и city-team town_*). Пустые per-player team удаляем (мусор), а
        town_-команды сохраняем — там могут быть другие жители.
        """
        if not BUKKIT_AVAILABLE:
            return
        try:
            entry = to_java_string(player.getName())
            for board in self.get_active_scoreboards():
                for team in board.getTeams():
                    try:
                        tname = str(team.getName())
                        # Наши команды: pol_* (fallback per-player), t_* (city-teams),
                        # town_* (legacy from prev version, чистим тоже).
                        if not (tname.startswith("pol_") or tname.startswith("t_") or tname.startswith("town_")):
                            continue
                        if team.hasEntry(entry):
                            team.removeEntry(entry)
                            # Удаляем пустой per-player team (мусор).
                            if tname.startswith("pol_"):
                                try:
                                    if team.getSize() == 0:
                                        team.unregister()
                                except Exception:
                                    pass
                            # Удаляем legacy town_* если он пустой — миграция.
                            if tname.startswith("town_"):
                                try:
                                    if team.getSize() == 0:
                                        team.unregister()
                                except Exception:
                                    pass
                    except Exception:
                        pass
        except Exception:
            pass

    def apply_scoreboard_team(self, player, color_key, town_color, role_color, short_abbr, city=None):
        if not BUKKIT_AVAILABLE:
            return
        try:
            team_name = self.get_politic_team_name(player, city=city)
            entry = to_java_string(player.getName())
            # Убираем игрока из всех прежних команд.
            self.remove_politic_team(player)
            for board in self.get_active_scoreboards():
                team = board.getTeam(to_java_string(team_name))
                if team is None:
                    team = board.registerNewTeam(to_java_string(team_name))
                team.addEntry(entry)
                # В ТАБЕ БЕЗ КАСТОМНЫХ ТЕГОВ РОЛЕЙ: только цвет города!
                team.setPrefix(to_java_string(colorize(town_color)))
                try:
                    color_enum = ChatColor.valueOf(CitiesConfig.COLORS.get(color_key, CitiesConfig.COLORS["white"])[0])
                    team.setColor(color_enum)
                except Exception:
                    pass
                # Дополнительные настройки только для city-team (не для fallback pol_).
                if city is not None:
                    try:
                        # displayName команды — название города (видно в /team).
                        team.setDisplayName(to_java_string(colorize(town_color + to_unicode(city.get("name", team_name)))))
                    except Exception:
                        pass
                    try:
                        # FRIENDLY-FIRE между жителями одного города — off.
                        team.setAllowFriendlyFire(False)
                    except Exception:
                        pass
                    try:
                        # Видеть невидимых соратников (Paper API).
                        team.setCanSeeFriendlyInvisibles(True)
                    except Exception:
                        pass
        except Exception:
            pass


class TownInventoryHolder(InventoryHolder):
    def __init__(self, gui):
        self.gui = gui

    def getInventory(self):
        return getattr(self.gui, "inventory", None)


def material_value(name, fallback):
    if Material is None:
        return None
    try:
        return Material.valueOf(name)
    except Exception:
        try:
            return Material.valueOf(fallback)
        except Exception:
            return None


def remove_inventory_material(inventory, material, amount):
    remaining = int(amount)
    if remaining <= 0:
        return True
    if not inventory.contains(material, remaining):
        return False
    contents = inventory.getContents()
    for slot in range(len(contents)):
        item = contents[slot]
        if item is None or item.getType() != material:
            continue
        take = min(remaining, int(item.getAmount()))
        new_amount = int(item.getAmount()) - take
        if new_amount <= 0:
            inventory.setItem(slot, None)
        else:
            item.setAmount(new_amount)
            inventory.setItem(slot, item)
        remaining -= take
        if remaining <= 0:
            return True
    return False


def refund_inventory_material(player, material, amount):
    remaining = int(amount)
    max_stack = max(1, int(material.getMaxStackSize()))
    while remaining > 0:
        stack_size = min(max_stack, remaining)
        leftovers = player.getInventory().addItem(ItemStack(material, stack_size))
        if leftovers:
            try:
                for item in leftovers.values():
                    player.getWorld().dropItemNaturally(player.getLocation(), item)
            except Exception:
                pass
        remaining -= stack_size


def create_gui_item(material_name, title, lore=None, fallback="PAPER"):
    material = material_value(material_name, fallback)
    if material is None or ItemStack is None:
        return None
    item = ItemStack(material, 1)
    meta = item.getItemMeta()
    if meta:
        meta.setDisplayName(to_java_string(colorize(title)))
        if lore:
            meta.setLore([to_java_string(colorize(line)) for line in lore])
        item.setItemMeta(meta)
    return item


class BaseTownGUI(object):
    def __init__(self, player, title, rows=6):
        self.player = player
        self.title = colorize(title)
        self.rows = max(1, min(6, int(rows)))
        self.size = self.rows * 9
        self.holder = TownInventoryHolder(self)
        self.inventory = Bukkit.createInventory(self.holder, self.size, to_java_string(self.title)) if BUKKIT_AVAILABLE else None

    def open(self):
        if self.inventory:
            self.build()
            self.player.openInventory(self.inventory)

    def build(self):
        pass

    def set_item(self, slot, material, title, lore=None, fallback="PAPER"):
        item = create_gui_item(material, title, lore, fallback)
        if item is not None:
            self.inventory.setItem(int(slot), item)

    def handle_click(self, player, raw_slot, click_type, is_shift):
        pass


class TownMainGUI(BaseTownGUI):
    def __init__(self, player):
        BaseTownGUI.__init__(self, player, u"&b&lМеню городов", 6)

    def build(self):
        self.inventory.clear()
        uuid_str, name = get_sender_uuid_and_name(self.player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None

        if city:
            total_members = len(city.get("members", {}))
            treasury = city.get("treasury", 0.0)
            lore_city = [
                u"&8---------------------------",
                u"&7Мэр города: &6" + to_unicode(city.get("mayor_name", u"Неизвестно")),
                u"&7Население: &a" + str(total_members) + u" &7жителей",
                u"&7Баланс казны: &6" + format_currency(treasury),
                u"&8---------------------------",
                u"&eЛКМ &7— открыть детали города"
            ]
            self.set_item(4, "BEACON", u"&6&lГОРОД: &e&l" + to_unicode(city.get("name")), lore_city, "EMERALD")
        else:
            self.set_item(4, "BARRIER", u"&c&lВы не состоите в городе", [
                u"&7Используйте: &f/town create <название>",
                u"&7чтобы основать свой собственный город!"
            ], "PAPER")

        self.set_item(19, "PLAYER_HEAD", u"&a&lСписок жителей", [
            u"&7Интерактивный список граждан города",
            u"&7Клик по жителю открывает его профиль:",
            u"  &f• Карточка и статистика",
            u"  &f• Перевод монет и ТП",
            u"  &f• Управление званием и кик",
            u"",
            u"&eНажмите для просмотра"
        ], "PLAYER_HEAD")

        self.set_item(20, "GOLD_INGOT", u"&e&lКазна и Налоги", [
            u"&7Управление финансами города",
            u"&7Взносы, снятия и настройка налогов",
            u"&7Просмотр истории последних операций",
            u"",
            u"&eНажмите для открытия казны"
        ], "GOLD_INGOT")

        self.set_item(22, "ENCHANTING_TABLE", u"&b&lПроекты и Стройки", [
            u"&7Собственные проекты вашего города!",
            u"&7Создавайте постройки с любыми требованиями",
            u"&7(Мэр / Заместитель / Строитель).",
            u"&7Сдавайте ресурсы в активный проект!",
            u"",
            u"&eНажмите для открытия каталога проектов"
        ], "BOOK")

        self.set_item(24, "WRITABLE_BOOK", u"&d&lДоска квестов", [
            u"&7Общегородские задачи для граждан",
            u"&7Сдавайте ресурсы или убивайте мобов,",
            u"&7чтобы получать награду в казну!",
            u"",
            u"&eНажмите для просмотра квестов"
        ], "BOOK")

        self.set_item(25, "NAME_TAG", u"&6&lЗвания и Права", [
            u"&7Настройка разрешений для ролей:",
            u"&eМэр, Заместитель, Строитель, Житель",
            u"&7Включение/отключение прав в GUI",
            u"",
            u"&eНажмите для настройки прав"
        ], "PAPER")

        self.set_item(38, "BELL", u"&b&lВсе города сервера", [
            u"&7Посмотреть список всех городов",
            u"&eНажмите, чтобы открыть"
        ], "PAPER")

        self.set_item(42, "PAPER", u"&e&lПредприятия и Акции", [
            u"&7Список компаний вашего города",
            u"&eНажмите, чтобы посмотреть"
        ], "PAPER")

        if is_admin(self.player):
            self.set_item(40, "COMMAND_BLOCK", u"&c&lАдминистративное меню", [
                u"&7Панель управления для модераторов/админов",
                u"&7Управление всеми городами в 1 клик",
                u"&cНажмите для открытия"
            ], "PAPER")

        self.set_item(49, "BARRIER", u"&c&lЗакрыть меню", [u"&7Закрыть окно городов"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 49:
            player.closeInventory()
        elif raw_slot == 4:
            TownInfoGUI(player).open()
        elif raw_slot == 19:
            TownMembersGUI(player).open()
        elif raw_slot == 20:
            TownTreasuryGUI(player).open()
        elif raw_slot == 22:
            TownUpgradesGUI(player).open()
        elif raw_slot == 24:
            TownQuestsGUI(player).open()
        elif raw_slot == 25:
            TownRanksGUI(player).open()
        elif raw_slot == 38:
            TownListGUI(player, 1).open()
        elif raw_slot == 42:
            TownCompaniesGUI(player).open()
        elif raw_slot == 40 and is_admin(player):
            AdminMainGUI(player).open()


class TownInfoGUI(BaseTownGUI):
    def __init__(self, player, city_name=None):
        self.city_name = city_name
        BaseTownGUI.__init__(self, player, u"&a&lИнформация о городе", 4)

    def get_city(self):
        if self.city_name:
            return state.get_city(self.city_name)
        uuid_str, name = get_sender_uuid_and_name(self.player)
        return state.get_city_by_player(uuid_str) if uuid_str else None

    def build(self):
        self.inventory.clear()
        city = self.get_city()
        if not city:
            self.set_item(13, "BARRIER", u"&cГород не найден", [u"&7Создать: /town create <название>"], "PAPER")
        else:
            color = city.get("color", "white")
            self.set_item(11, "BEACON", u"&e" + to_unicode(city.get("name")), [
                u"&7Мэр: &f" + to_unicode(city.get("mayor_name")),
                u"&7Цвет: &f" + color,
                u"&7Жителей: &a" + str(len(city.get("members", {}))),
                u"&7Казна: &6" + format_currency(city.get("treasury", 0.0))
            ], "EMERALD")
            self.set_item(13, "PLAYER_HEAD", u"&aЖители", [u"&eНажмите, чтобы открыть"], "PLAYER_HEAD")
            self.set_item(15, "CHEST", u"&6Казна и Налоги", [
                u"&7Пополнить: /town deposit <сумма>",
                u"&7Снять мэру: /town withdraw <сумма>",
                u"&eНажмите для открытия меню казны"
            ], "CHEST")
            self.set_item(31, "ARROW", u"&7Назад", [u"&eГлавное меню"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 31:
            TownMainGUI(player).open()
        elif raw_slot == 13:
            city = self.get_city()
            if city:
                TownMembersGUI(player, city.get("name")).open()
        elif raw_slot == 15:
            TownTreasuryGUI(player).open()


class TownMembersGUI(BaseTownGUI):
    def __init__(self, player, city_name=None, sort_mode="ONLINE", page=0):
        self.city_name = city_name
        self.sort_mode = sort_mode
        self.page = page
        self.members_list = []
        BaseTownGUI.__init__(self, player, u"&e&lЖители (Стр. " + str(page + 1) + u")", 6)

    def get_city(self):
        if self.city_name:
            return state.get_city(self.city_name)
        uuid_str, name = get_sender_uuid_and_name(self.player)
        return state.get_city_by_player(uuid_str) if uuid_str else None

    def build(self):
        self.inventory.clear()
        city = self.get_city()
        if not city:
            self.set_item(22, "BARRIER", u"&cВы не состоите в городе", [u"&7Откройте список городов"], "PAPER")
            return

        sort_labels = {
            "ONLINE": u"&aСначала онлайн",
            "ROLE": u"&6По званию",
            "CONTRIB": u"&eПо вкладу в казну"
        }
        next_sort = "ROLE" if self.sort_mode == "ONLINE" else ("CONTRIB" if self.sort_mode == "ROLE" else "ONLINE")
        self.set_item(4, "COMPARATOR", u"&e&lСортировка списка", [
            u"&7Текущий режим: " + sort_labels.get(self.sort_mode, u"&aСначала онлайн"),
            u"",
            u"&eЛКМ &7— переключить на: " + sort_labels.get(next_sort, u"&aСначала онлайн")
        ], "PAPER")

        self.members_list = []
        for uuid_str, name in city.get("members", {}).items():
            is_on = (service.get_online_player_by_uuid(uuid_str) is not None)
            roles = city.get("member_roles", {}).get(uuid_str, ["citizen"])
            primary = "mayor" if str(city.get("mayor_uuid")) == str(uuid_str) else (roles[0] if roles else "citizen")
            r_weight = 4 if primary == "mayor" else (3 if primary == "deputy" else (2 if primary == "builder" else 1))
            contrib = city.get("contributions", {}).get(uuid_str, 0.0)
            self.members_list.append({
                "uuid": uuid_str,
                "name": to_unicode(name),
                "online": is_on,
                "primary": primary,
                "r_weight": r_weight,
                "contrib": contrib
            })

        if self.sort_mode == "ONLINE":
            self.members_list.sort(key=lambda x: (not x["online"], -x["r_weight"], x["name"].lower()))
        elif self.sort_mode == "ROLE":
            self.members_list.sort(key=lambda x: (-x["r_weight"], -x["contrib"], x["name"].lower()))
        elif self.sort_mode == "CONTRIB":
            self.members_list.sort(key=lambda x: (-x["contrib"], -x["r_weight"], x["name"].lower()))

        start_idx = self.page * 36
        end_idx = min(start_idx + 36, len(self.members_list))

        for i in range(start_idx, end_idx):
            slot = 9 + (i - start_idx)
            item_data = self.members_list[i]
            status_str = u"&a● Онлайн" if item_data["online"] else u"&c○ Оффлайн"
            role_disp = service.get_role_display(city, item_data["primary"])
            hero_str = get_player_hero(item_data["name"])

            lore = [
                u"&7Статус: " + status_str,
                u"&7Звание: &f" + role_disp,
                u"&7Вклад в казну: &6" + format_currency(item_data["contrib"]),
                u"&7Герой (Кит): &d" + hero_str,
                u"&8---------------------------",
                u"&eЛКМ &7— открыть профиль и управление"
            ]
            self.set_item(slot, "PLAYER_HEAD", u"&f&l" + item_data["name"], lore, "PLAYER_HEAD")

        if start_idx > 0:
            self.set_item(45, "ARROW", u"&a&l<- Предыдущая", [u"&7На страницу назад"], "PAPER")
        if end_idx < len(self.members_list):
            self.set_item(53, "ARROW", u"&a&lСледующая ->", [u"&7На страницу вперед"], "PAPER")

        self.set_item(49, "DARK_OAK_DOOR", u"&c&lНазад", [u"&eГлавное меню"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 49:
            TownMainGUI(player).open()
        elif raw_slot == 4:
            next_sort = "ROLE" if self.sort_mode == "ONLINE" else ("CONTRIB" if self.sort_mode == "ROLE" else "ONLINE")
            TownMembersGUI(player, self.city_name, next_sort, 0).open()
        elif raw_slot == 45 and self.page > 0:
            TownMembersGUI(player, self.city_name, self.sort_mode, self.page - 1).open()
        elif raw_slot == 53 and (self.page + 1) * 36 < len(self.members_list):
            TownMembersGUI(player, self.city_name, self.sort_mode, self.page + 1).open()
        elif 9 <= raw_slot < 45:
            idx = self.page * 36 + (raw_slot - 9)
            if idx < len(self.members_list):
                target = self.members_list[idx]
                city = self.get_city()
                TownResidentSubmenuGUI(player, target["uuid"], target["name"], city.get("name") if city else None).open()


class TownResidentSubmenuGUI(BaseTownGUI):
    def __init__(self, player, target_uuid, target_name, city_name=None):
        self.target_uuid = str(target_uuid)
        self.target_name = to_unicode(target_name)
        self.city_name = city_name
        BaseTownGUI.__init__(self, player, u"&e&lЖитель: " + self.target_name, 3)

    def get_city(self):
        if self.city_name:
            return state.get_city(self.city_name)
        uuid_str, name = get_sender_uuid_and_name(self.player)
        return state.get_city_by_player(uuid_str) if uuid_str else None

    def build(self):
        self.inventory.clear()
        city = self.get_city()
        if not city or self.target_uuid not in city.get("members", {}):
            self.set_item(13, "BARRIER", u"&cЖитель не найден", [u"&7Игрок больше не в городе"], "PAPER")
            self.set_item(22, "DARK_OAK_DOOR", u"&c&lНазад", [u"&7К списку жителей"], "PAPER")
            return

        is_on = (service.get_online_player_by_uuid(self.target_uuid) is not None)
        status_str = u"&a● Онлайн" if is_on else u"&c○ Оффлайн"
        roles = city.get("member_roles", {}).get(self.target_uuid, ["citizen"])
        primary = "mayor" if str(city.get("mayor_uuid")) == self.target_uuid else (roles[0] if roles else "citizen")
        role_disp = service.get_role_display(city, primary)
        contrib = city.get("contributions", {}).get(self.target_uuid, 0.0)
        hero_str = get_player_hero(self.target_name)

        lore_profile = [
            u"&7Ник: &f" + self.target_name,
            u"&7Статус: " + status_str,
            u"&7Звание: &f" + role_disp,
            u"&7Суммарный вклад: &6" + format_currency(contrib),
            u"&7Выбранный герой: &d" + hero_str
        ]
        self.set_item(4, "PLAYER_HEAD", u"&6&lПрофиль: &f&l" + self.target_name, lore_profile, "PLAYER_HEAD")

        lore_pay = [
            u"&7Быстрый перевод денег со своего счёта",
            u"&7на личный баланс этого жителя.",
            u"",
            u"&eЛКМ &7— перевести &a+100$",
            u"&eПКМ &7— перевести &a+500$"
        ]
        self.set_item(10, "EMERALD", u"&a&lПеревести монеты", lore_pay, "EMERALD")

        rem_tp = max(0, int(tp_cooldowns.get(uid(self.player), 0)) - int(time.time()))
        target_tp_disabled = state.is_tp_disabled(self.target_uuid)
        lore_tp = [
            u"&7Телепорт к союзному жителю (if online).",
            u"&7Доступно всем гражданам с КД 15 минут.",
            u"&7В чужие города телепортироваться нельзя!",
            u"",
            (u"&cЖитель отключил телепорты к себе!" if target_tp_disabled else
             u"&7Статус КД: " + (u"&aГотово" if rem_tp <= 0 else (u"&c" + format_duration_human(rem_tp)))),
            u"",
            u"&eЛКМ &7— телепорт к союзнику"
        ]
        self.set_item(12, "ENDER_PEARL" if not target_tp_disabled else "BARRIER", u"&b&lТелепортироваться", lore_tp, "ENDER_PEARL")

        lore_rank = [
            u"&7Изменить звание жителя в городе.",
            u"&7Текущее звание: &f" + role_disp,
            u"",
            u"&eЛКМ &7— &aПовысить &7(Житель -> Строитель -> Зам)",
            u"&eПКМ &7— &cПонизить",
            u"",
            u"&8(Доступно Мэру города)"
        ]
        self.set_item(14, "GOLDEN_HELMET", u"&6&lИзменить звание", lore_rank, "PAPER")

        lore_kick = [
            u"&7Исключить жителя из вашего города.",
            u"&c&lВнимание: &7действие вступает в силу сразу!",
            u"",
            u"&eЛКМ &7— &cИсключить из города",
            u"&8(Доступно Мэру города)"
        ]
        self.set_item(16, "REDSTONE_BLOCK", u"&c&lИсключить из города (Кик)", lore_kick, "PAPER")

        self.set_item(22, "DARK_OAK_DOOR", u"&c&lНазад к списку жителей", [u"&7Вернуться к списку"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 22:
            TownMembersGUI(player, self.city_name).open()
            return

        city = self.get_city()
        if not city or self.target_uuid not in city.get("members", {}):
            return

        uuid_str, my_name = get_sender_uuid_and_name(player)

        if raw_slot == 10:
            amount = 500.0 if click_type in ("RIGHT", "RIGHT_CLICK") else 100.0
            success, sender_balance, target_balance = economy.transfer(
                uuid_str, self.target_uuid, amount, self.target_name
            )
            if not success:
                send_message(player, CitiesConfig.PREFIX + u"&cПеревод не выполнен. Проверьте баланс и доступность экономики.")
                return
            send_message(player, CitiesConfig.PREFIX + u"&aВы перевели &e{0} &aжителю &f{1}&a.".format(format_currency(amount), self.target_name))
            service.notify_player(self.target_name, u"&aИгрок &f{0} &aперевёл вам &e{1}&a!".format(my_name, format_currency(amount)))
            self.open()

        elif raw_slot == 12:
            if deny_city_teleport_during_nuclear_drop(player):
                return
            target_player = service.get_online_player_by_uuid(self.target_uuid)
            if not target_player:
                send_message(player, CitiesConfig.PREFIX + u"&cИгрок &f{0} &cсейчас оффлайн!".format(self.target_name))
                return
            if self.target_uuid == uuid_str:
                send_message(player, CitiesConfig.PREFIX + u"&cВы не можете телепортироваться к самому себе!")
                return
            # ФИКС: если ЛЮБАЯ из двух сторон отключила входящие телепорты через &f/town tp off&r,
            # телепортироваться к ней тоже нельзя (взаимная блокировка: выключая свой входящие,
            # игрок автоматически отключает и свои исходящие).
            if state.is_tp_disabled(self.target_uuid) and not is_admin(player):
                send_message(player, CitiesConfig.PREFIX + u"&cИгрок &f{0} &cотключил телепорты к себе!".format(self.target_name))
                return
            if state.is_tp_disabled(uuid_str) and not is_admin(player):
                send_message(player, CitiesConfig.PREFIX + u"&cВы отключили телепорты к себе (&f/town tp on&c чтобы снова телепортироваться).")
                return
            now = int(time.time())
            end_cd = int(tp_cooldowns.get(uuid_str, 0))
            if end_cd > now and not is_admin(player):
                send_message(player, CitiesConfig.PREFIX + u"&cТелепорт на перезарядке! Осталось: &e%s" % format_duration_human(end_cd - now))
                return
            try:
                player.teleport(target_player.getLocation())
                tp_cooldowns[uuid_str] = now + 900
                send_message(player, CitiesConfig.PREFIX + u"&aВы телепортировались к союзному жителю &f%s&a! (КД 15 мин.)" % self.target_name)
                player.closeInventory()
            except Exception:
                send_message(player, CitiesConfig.PREFIX + u"&cОшибка телепортации.")

        elif raw_slot == 14:
            if not service.can_manage(player, city):
                return
            if self.target_uuid == str(city.get("mayor_uuid")):
                send_message(player, CitiesConfig.PREFIX + u"&cНельзя изменить звание Мэра!")
                return
            roles = city.setdefault("member_roles", {}).setdefault(self.target_uuid, ["citizen"])
            cur_role = roles[0] if roles else "citizen"
            if click_type in ("RIGHT", "RIGHT_CLICK"):
                new_role = "citizen" if cur_role in ("deputy", "builder") else "citizen"
            else:
                new_role = "builder" if cur_role == "citizen" else ("deputy" if cur_role == "builder" else "deputy")

            city["member_roles"][self.target_uuid] = [new_role]
            state.add_treasury_log(city, u"§f{0} §7получил роль {1}".format(self.target_name, service.get_role_display(city, new_role)))
            state.save()
            service.apply_player_color_by_uuid(self.target_uuid)
            send_message(player, CitiesConfig.PREFIX + u"&aРоль игрока &f{0} &aизменена на &e{1}&a.".format(
                self.target_name, service.get_role_display(city, new_role)
            ))
            self.open()

        elif raw_slot == 16:
            if not service.can_manage(player, city):
                return
            if self.target_uuid == str(city.get("mayor_uuid")):
                send_message(player, CitiesConfig.PREFIX + u"&cНельзя исключить Мэра!")
                return
            service.remove_member(player, self.target_name)
            TownMembersGUI(player, self.city_name).open()


class TownTreasuryGUI(BaseTownGUI):
    def __init__(self, player):
        BaseTownGUI.__init__(self, player, u"&6&lКазна и Налоги", 4)

    def build(self):
        self.inventory.clear()
        uuid_str, name = get_sender_uuid_and_name(self.player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city:
            self.set_item(13, "BARRIER", u"&cВы не состоите в городе", [u"&7Казна недоступна"], "PAPER")
            self.set_item(31, "DARK_OAK_DOOR", u"&cНазад", [u"&7Вернуться в главное меню"], "PAPER")
            return

        treasury = city.get("treasury", 0.0)
        tax_comp = city.get("taxes", {}).get("companies", CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT)

        lore_bal = [
            u"&7В городской казне: &6" + format_currency(treasury),
            u"&7Ваш баланс: &e" + format_currency(economy.get_balance(uuid_str)),
            u"&7Налог предприятий: &a" + str(tax_comp) + u"%"
        ]
        self.set_item(4, "GOLD_BLOCK", u"&6&lКАЗНА ГОРОДА: &f&l" + format_currency(treasury), lore_bal, "GOLD_BLOCK")

        self.set_item(10, "GOLD_NUGGET", u"&a&lВнести +100$", [u"&7Списать 100$ в казну", u"&eЛКМ — внести"], "GOLD_NUGGET")
        self.set_item(11, "GOLD_INGOT", u"&a&lВнести +500$", [u"&7Списать 500$ в казну", u"&eЛКМ — внести"], "GOLD_INGOT")
        self.set_item(12, "GOLD_BLOCK", u"&a&lВнести +2500$", [u"&7Списать 2500$ в казну", u"&eЛКМ — внести"], "GOLD_BLOCK")

        self.set_item(14, "IRON_NUGGET", u"&c&lСнять -100$", [u"&7Снять 100$ себе", u"&8(Только для Мэра)", u"&eЛКМ — снять"], "PAPER")
        self.set_item(15, "IRON_INGOT", u"&c&lСнять -500$", [u"&7Снять 500$ себе", u"&8(Только для Мэра)", u"&eЛКМ — снять"], "PAPER")
        self.set_item(16, "IRON_BLOCK", u"&c&lСнять -2500$", [u"&7Снять 2500$ себе", u"&8(Только для Мэра)", u"&eЛКМ — снять"], "PAPER")

        lore_tax = [
            u"&7Текущий налог предприятий: &e" + str(tax_comp) + u"%",
            u"&7Взимается со сделок компаний города.",
            u"",
            u"&eЛКМ &7— переключить: 0% -> 2% -> 5% -> 10%",
            u"&8(Только для Мэра города)"
        ]
        self.set_item(22, "PAPER", u"&e&lНастройка налога", lore_tax, "PAPER")

        log_list = city.get("log", [])
        for i in range(9):
            slot = 27 + i
            if i < len(log_list):
                msg = log_list[i]
                self.set_item(slot, "BOOK", u"&e&lЗапись #" + str(i + 1), [u"&7" + msg], "PAPER")
            else:
                self.set_item(slot, "GRAY_STAINED_GLASS_PANE", u"&8[Пустая запись]", [u"&7История операций чиста"], "PAPER")

        self.set_item(31, "DARK_OAK_DOOR", u"&c&lНазад", [u"&7Вернуться в главное меню"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 31:
            TownMainGUI(player).open()
            return

        uuid_str, name = get_sender_uuid_and_name(player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city:
            return

        if raw_slot == 10:
            service.deposit(player, 100.0)
            self.open()
        elif raw_slot == 11:
            service.deposit(player, 500.0)
            self.open()
        elif raw_slot == 12:
            service.deposit(player, 2500.0)
            self.open()
        elif raw_slot == 14:
            service.withdraw(player, 100.0)
            self.open()
        elif raw_slot == 15:
            service.withdraw(player, 500.0)
            self.open()
        elif raw_slot == 16:
            service.withdraw(player, 2500.0)
            self.open()
        elif raw_slot == 22:
            if not service.can_manage(player, city):
                return
            cur = city.get("taxes", {}).get("companies", CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT)
            taxes = [0.0, 2.0, 5.0, 10.0]
            next_t = taxes[0]
            for i, val in enumerate(taxes):
                if cur == val and i + 1 < len(taxes):
                    next_t = taxes[i + 1]
                    break
            service.set_tax(player, "companies", next_t)
            self.open()


class TownQuestsGUI(BaseTownGUI):
    def __init__(self, player):
        BaseTownGUI.__init__(self, player, u"&d&lДоска квестов города", 4)

    def build(self):
        self.inventory.clear()
        uuid_str, name = get_sender_uuid_and_name(self.player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city:
            self.set_item(13, "BARRIER", u"&cВы не состоите в городе", [u"&7Квесты недоступны"], "PAPER")
            self.set_item(31, "DARK_OAK_DOOR", u"&cНазад", [u"&7Вернуться в главное меню"], "PAPER")
            return

        q_iron = city.get("quest_progress", {}).get("iron", 0)
        q_mobs = city.get("quest_progress", {}).get("mobs", 0)

        iron_done = (q_iron >= 64)
        lore_iron = [
            u"&7Собрать 64 железных слитка в казну города.",
            u"&7Прогресс: &f" + str(q_iron) + u" &8/ &764",
            u"",
            u"&7Награда: &6+1 000$ &7в казну города",
            u"",
            u"&eЛКМ &7— сдать 1 Железный слиток из инвентаря",
            u"&eПКМ &7— сдать 64 Железных слитка"
        ]
        mat_iron = "IRON_BLOCK" if iron_done else "IRON_INGOT"
        name_iron = u"&a&l[ВЫПОЛНЕНО] &fЖелезный запас" if iron_done else u"&e&lКвест: Железный запас"
        self.set_item(10, mat_iron, name_iron, lore_iron, "PAPER")

        mobs_done = (q_mobs >= 25)
        lore_mobs = [
            u"&7Убить 25 враждебных мобов (автозачёт).",
            u"&7Прогресс: &f" + str(q_mobs) + u" &8/ &725",
            u"",
            u"&7Награда: &6+2 500$ &7в казну города"
        ]
        mat_mobs = "ZOMBIE_HEAD" if mobs_done else "WOODEN_SWORD"
        name_mobs = u"&a&l[ВЫПОЛНЕНО] &fОхота на чудовищ" if mobs_done else u"&c&lКвест: Охота на чудовищ"
        self.set_item(12, mat_mobs, name_mobs, lore_mobs, "PAPER")

        cquests = state.data.get("custom_quests", {})
        slot_idx = 14
        for qid, qdata in sorted(cquests.items(), key=lambda x: x[1].get("title", "").lower()):
            if slot_idx >= 27:
                break
            q_prog = city.setdefault("quest_progress", {}).get(qid, 0)
            req_cnt = qdata.get("required_count", 64)
            mat_name = qdata.get("material", "STONE")
            done = (q_prog >= req_cnt)

            lore_cq = [
                u"&7Серверное задание для вашего города.",
                u"&7Требуется сдать: &f%s x%d" % (mat_name, req_cnt),
                u"&7Прогресс города: &a%d &8/ &7%d" % (q_prog, req_cnt),
                u"",
                u"&7Награда городу: &6" + format_currency(qdata.get("reward_money", 1000.0)),
                u"",
                u"&eЛКМ &7— сдать 1 шт. из инвентаря",
                u"&eПКМ &7— сдать всё требуемое (стак)"
            ]
            icon_mat = "EMERALD_BLOCK" if done else mat_name
            title_cq = (u"&a&l[ВЫПОЛНЕНО] &f" if done else u"&b&lКвест: &f") + qdata.get("title", qid)
            self.set_item(slot_idx, icon_mat, title_cq, lore_cq, "PAPER")
            slot_idx += 1

        self.set_item(31, "DARK_OAK_DOOR", u"&c&lНазад", [u"&7Вернуться в главное меню"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 31:
            TownMainGUI(player).open()
            return

        uuid_str, name = get_sender_uuid_and_name(player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city:
            return

        if raw_slot == 10:
            q_iron = city.setdefault("quest_progress", {}).get("iron", 0)
            if q_iron >= 64:
                send_message(player, CitiesConfig.PREFIX + u"&aКвест «Железный запас» уже выполнен!")
                return
            inv = player.getInventory()
            count = 64 - q_iron if click_type in ("RIGHT", "RIGHT_CLICK") else 1
            if not inv.contains(Material.IRON_INGOT, count):
                send_message(player, CitiesConfig.PREFIX + u"&cУ вас в инвентаре нет {0} железных слитков!".format(count))
                return
            city_snapshot = copy.deepcopy(city)
            if not remove_inventory_material(inv, Material.IRON_INGOT, count):
                send_message(player, CitiesConfig.PREFIX + u"&cНе удалось списать железные слитки. Попробуйте снова.")
                return
            city["quest_progress"]["iron"] = min(64, q_iron + count)
            completed = city["quest_progress"]["iron"] >= 64
            if completed:
                state.add_treasury_log(city, u"§a§lКвест «Железный запас» выполнен!")
                city["treasury"] = city.get("treasury", 0.0) + 1000.0
            if not state.save():
                city.clear()
                city.update(city_snapshot)
                refund_inventory_material(player, Material.IRON_INGOT, count)
                send_message(player, CitiesConfig.PREFIX + u"&cПрогресс квеста не сохранен. Предметы возвращены.")
                return
            send_message(player, CitiesConfig.PREFIX + u"&aВы сдали &e{0} &aжелезных слитков в городской квест!".format(count))
            if completed:
                send_message(player, CitiesConfig.PREFIX + u"&a&lКвест выполнен! В казну начислено +1000$.")
            self.open()

        elif 14 <= raw_slot < 27:
            cquests = state.data.get("custom_quests", {})
            sorted_q = sorted(cquests.items(), key=lambda x: x[1].get("title", "").lower())
            idx = raw_slot - 14
            if idx >= len(sorted_q):
                return
            qid, qdata = sorted_q[idx]
            req_cnt = qdata.get("required_count", 64)
            q_prog = city.setdefault("quest_progress", {}).get(qid, 0)
            if q_prog >= req_cnt:
                send_message(player, CitiesConfig.PREFIX + u"&aЭтот квест уже выполнен вашим городом!")
                return
            mat_name = qdata.get("material", "STONE")
            mat_enum = material_value(mat_name, "STONE")
            inv = player.getInventory()
            count = req_cnt - q_prog if click_type in ("RIGHT", "RIGHT_CLICK") else 1
            if not inv.contains(mat_enum, count):
                send_message(player, CitiesConfig.PREFIX + u"&cУ вас в инвентаре нет %d шт. %s!" % (count, mat_name))
                return
            city_snapshot = copy.deepcopy(city)
            if not remove_inventory_material(inv, mat_enum, count):
                send_message(player, CitiesConfig.PREFIX + u"&cНе удалось списать предметы. Попробуйте снова.")
                return
            city["quest_progress"][qid] = min(req_cnt, q_prog + count)
            completed = city["quest_progress"][qid] >= req_cnt
            reward = 0.0
            if completed:
                reward = safe_float(qdata.get("reward_money", 1000.0), 0.0, 0.0, 10000000000000000.0)
                city["treasury"] = city.get("treasury", 0.0) + reward
                state.add_treasury_log(city, u"§a§lКвест «%s» выполнен! +%s" % (qdata.get("title", qid), format_currency(reward)))
            if not state.save():
                city.clear()
                city.update(city_snapshot)
                refund_inventory_material(player, mat_enum, count)
                send_message(player, CitiesConfig.PREFIX + u"&cПрогресс квеста не сохранен. Предметы возвращены.")
                return
            send_message(player, CitiesConfig.PREFIX + u"&aВы сдали &e%d шт. %s &aв квест!" % (count, mat_name))
            if completed:
                send_message(player, CitiesConfig.PREFIX + u"&a&l✓ КВЕСТ ВЫПОЛНЕН! В казну начислено %s." % format_currency(reward))
            self.open()


class TownRanksGUI(BaseTownGUI):
    def __init__(self, player):
        BaseTownGUI.__init__(self, player, u"&6&lЗвания и Права", 3)

    def build(self):
        self.inventory.clear()
        uuid_str, name = get_sender_uuid_and_name(self.player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city:
            self.set_item(13, "BARRIER", u"&cВы не состоите в городе", [u"&7Права недоступны"], "PAPER")
            self.set_item(22, "DARK_OAK_DOOR", u"&cНазад", [u"&7Вернуться в главное меню"], "PAPER")
            return

        rank_perms = city.setdefault("rank_perms", {
            "mayor": ["INVITE", "KICK", "SPEND_TREASURY", "SET_TAX", "MANAGE_QUESTS", "MANAGE_PROJECTS"],
            "deputy": ["INVITE", "KICK", "MANAGE_QUESTS", "MANAGE_PROJECTS"],
            "builder": ["MANAGE_PROJECTS", "MANAGE_QUESTS", "INVITE"],
            "citizen": []
        })

        def build_lore(r_key, title):
            perms = rank_perms.get(r_key, [])
            lore = [
                u"&7Настройка полномочий для: &f" + title,
                u"&8---------------------------",
                (u"&a✓" if "INVITE" in perms else u"&c✗") + u" &fПриглашение &8(INVITE)",
                (u"&a✓" if "KICK" in perms else u"&c✗") + u" &fИсключение &8(KICK)",
                (u"&a✓" if "SPEND_TREASURY" in perms else u"&c✗") + u" &fКазна &8(SPEND_TREASURY)",
                (u"&a✓" if "MANAGE_PROJECTS" in perms else u"&c✗") + u" &fПроекты &8(MANAGE_PROJECTS)",
                u"&8---------------------------",
                u"&eЛКМ &7— переключить &fINVITE",
                u"&eПКМ &7— переключить &fMANAGE_PROJECTS"
            ]
            return lore

        self.set_item(10, "GOLDEN_CHESTPLATE", u"&6&l[М] Мэр", build_lore("mayor", u"Мэр"), "PAPER")
        self.set_item(12, "IRON_CHESTPLATE", u"&b&l[ЗМ] Заместитель", build_lore("deputy", u"Заместитель"), "PAPER")
        self.set_item(14, "GOLDEN_PICKAXE", u"&e&l[СТ] Строитель", build_lore("builder", u"Строитель"), "PAPER")
        self.set_item(16, "LEATHER_CHESTPLATE", u"&7&l[Ж] Житель", build_lore("citizen", u"Житель"), "PAPER")

        self.set_item(22, "DARK_OAK_DOOR", u"&c&lНазад", [u"&7Вернуться в главное меню"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 22:
            TownMainGUI(player).open()
            return

        uuid_str, name = get_sender_uuid_and_name(player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city or not service.can_manage(player, city):
            return

        rank_perms = city.setdefault("rank_perms", {
            "mayor": ["INVITE", "KICK", "SPEND_TREASURY", "SET_TAX", "MANAGE_QUESTS", "MANAGE_PROJECTS"],
            "deputy": ["INVITE", "KICK", "MANAGE_QUESTS", "MANAGE_PROJECTS"],
            "builder": ["MANAGE_PROJECTS", "MANAGE_QUESTS", "INVITE"],
            "citizen": []
        })

        target_rank = None
        if raw_slot == 10:
            target_rank = "mayor"
        elif raw_slot == 12:
            target_rank = "deputy"
        elif raw_slot == 14:
            target_rank = "builder"
        elif raw_slot == 16:
            target_rank = "citizen"

        if target_rank:
            perms = rank_perms.setdefault(target_rank, [])
            target_perm = "MANAGE_PROJECTS" if click_type in ("RIGHT", "RIGHT_CLICK") else "INVITE"
            if target_perm in perms:
                perms.remove(target_perm)
                send_message(player, CitiesConfig.PREFIX + u"&eПраво {0} отключено для {1}.".format(target_perm, target_rank))
            else:
                perms.append(target_perm)
                send_message(player, CitiesConfig.PREFIX + u"&aПраво {0} включено для {1}.".format(target_perm, target_rank))
            state.save()
            self.open()


class TownCompaniesGUI(BaseTownGUI):
    def __init__(self, player, city_name=None):
        self.city_name = city_name
        BaseTownGUI.__init__(self, player, u"&b&lПредприятия города", 6)

    def get_city(self):
        if self.city_name:
            return state.get_city(self.city_name)
        uuid_str, name = get_sender_uuid_and_name(self.player)
        return state.get_city_by_player(uuid_str) if uuid_str else None

    def build(self):
        self.inventory.clear()
        city = self.get_city()
        if not city:
            self.set_item(22, "BARRIER", u"&cГород не найден", [u"&7Вы не состоите в городе"], "PAPER")
            self.set_item(49, "DARK_OAK_DOOR", u"&cНазад", [u"&7Вернуться в главное меню"], "PAPER")
            return
        companies = get_city_companies(city.get("name"))
        for index, company in enumerate(companies[:45]):
            self.set_item(index, "GOLD_BLOCK", u"&e&l" + to_unicode(company.get("name", u"Компания")), [
                u"&7Владелец: &f" + to_unicode(company.get("owner_name", u"Неизвестно")),
                u"&7Цена акции: &a" + format_currency(get_company_share_price(company)),
                u"&7Капитализация: &6" + format_currency(get_company_capitalization(company))
            ], "GOLD_BLOCK")
        self.set_item(49, "DARK_OAK_DOOR", u"&cНазад", [u"&7Вернуться в главное меню"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 49:
            TownMainGUI(player).open()


class TownListGUI(BaseTownGUI):
    def __init__(self, player, page=1):
        self.page = max(1, int(page))
        BaseTownGUI.__init__(self, player, u"&b&lВсе города", 6)

    def build(self):
        self.inventory.clear()
        cities = state.list_cities()
        page_size = 45
        total_pages = max(1, int((len(cities) + page_size - 1) / page_size))
        self.page = min(self.page, total_pages)
        chunk = cities[(self.page - 1) * page_size:self.page * page_size]
        for index, city in enumerate(chunk):
            self.set_item(index, "BELL", u"&e" + to_unicode(city.get("name")), [
                u"&7Мэр: &f" + to_unicode(city.get("mayor_name")),
                u"&7Жителей: &a{0}".format(len(city.get("members", {}))),
                u"&7Казна: &6" + format_currency(city.get("treasury", 0.0)),
                u"&eНажмите для информации"
            ], "PAPER")
        self.set_item(45, "ARROW", u"&7Назад", [u"&eГлавное меню"], "PAPER")
        if self.page > 1:
            self.set_item(48, "ARROW", u"&aПредыдущая", [u"&7Страница {0}".format(self.page - 1)], "PAPER")
        self.set_item(49, "MAP", u"&eСтраница {0}/{1}".format(self.page, total_pages), None, "PAPER")
        if self.page < total_pages:
            self.set_item(50, "ARROW", u"&aСледующая", [u"&7Страница {0}".format(self.page + 1)], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 45:
            TownMainGUI(player).open()
        elif raw_slot == 48 and self.page > 1:
            TownListGUI(player, self.page - 1).open()
        elif raw_slot == 50:
            TownListGUI(player, self.page + 1).open()
        elif 0 <= raw_slot < 45:
            cities = state.list_cities()
            idx = (self.page - 1) * 45 + raw_slot
            if idx < len(cities):
                TownInfoGUI(player, cities[idx].get("name")).open()


class TownUpgradesGUI(BaseTownGUI):
    """
    Каталог собственных проектов города.
    Строители/Заместители/Мэр создают свои собственные проекты и выбирают какой начать.
    Жители кликают по активному проекту, чтобы сдавать ресурсы.
    """
    def __init__(self, player):
        BaseTownGUI.__init__(self, player, u"&b&lСобственные проекты города", 6)

    def build(self):
        self.inventory.clear()
        uuid_str, name = get_sender_uuid_and_name(self.player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city:
            self.set_item(22, "BARRIER", u"&cВы не состоите в городе", [u"&7Проекты недоступны"], "PAPER")
            self.set_item(49, "DARK_OAK_DOOR", u"&cНазад", [u"&7Вернуться в главное меню"], "PAPER")
            return

        cproj = city.setdefault("custom_projects", {})
        built_count = sum(1 for p in cproj.values() if p.get("status") == "BUILT")
        active_id = None
        for pid, pdata in cproj.items():
            if pdata.get("status") == "ACTIVE":
                active_id = pid
                break

        lore_overview = [
            u"&7Всего создано проектов в городе: &a%d" % len(cproj),
            u"&7Построено и завершено: &a%d" % built_count,
            u"&7Текущая стройка: " + (u"&e" + cproj[active_id]["name"] if active_id else u"&7Нет"),
            u"&8---------------------------",
            u"&eСтроители, Заместители и Мэр",
            u"&7создают свои проекты с любыми требованиями",
            u"&7и выбирают какой из них строить сейчас.",
            u"&aВсе жители &7сдают ресурсы в стройку!"
        ]
        self.set_item(4, "BEACON", u"&b&lАрхитектурный фонд города", lore_overview, "EMERALD")

        if service.can_manage_projects(self.player, city):
            self.set_item(8, "EMERALD_BLOCK", u"&a&l+ Создать проект в руке", [
                u"&7Создаёт новый черновик проекта",
                u"&7с иконкой предмета в вашей руке!",
                u"",
                u"&eЛКМ &7— Создать проект",
                u"&8(Далее настраивайте требования кликом)"
            ], "PAPER")

        for idx, (pid, pdata) in enumerate(sorted(cproj.items(), key=lambda x: x[1].get("name", "").lower())[:36]):
            slot = 9 + idx
            status = pdata.get("status", "DRAFT")
            req_items_str = u", ".join([u"%s x%d" % (k, v) for k, v in pdata.get("req_items", {}).items()]) or u"нет"
            icon = pdata.get("icon", "STONE_BRICKS")

            if status == "BUILT":
                lore = [
                    u"&7" + pdata.get("desc", u""),
                    u"&8---------------------------",
                    u"&a§l● ПОСТРОЕНО И ЗАВЕРШЕНО",
                    u"&7Этот объект украшает ваш город!"
                ]
                self.set_item(slot, icon, u"&a&l[ПОСТРОЕНО] &f" + pdata.get("name", pid), lore, "EMERALD")

            elif status == "ACTIVE":
                rem_sec = int(pdata.get("end_time", 0)) - int(time.time())
                lore = [
                    u"&7" + pdata.get("desc", u""),
                    u"&8---------------------------",
                    u"&e§l● СТРОИТЕЛЬСТВО В ПРОЦЕССЕ",
                    u"&7Примерная готовность: &f" + format_duration_human(rem_sec),
                    u"&7Собрано финансов: &6%s / %s" % (format_currency(pdata.get("contributed_money", 0.0)), format_currency(pdata.get("req_money", 10000.0))),
                    u"&8---------------------------",
                    u"&eЛКМ &7— Открыть окно помощи проекту",
                    u"&7(Сдавать ресурсы и ускорять стройку)"
                ]
                self.set_item(slot, "BEACON", u"&e&l[СТРОИТСЯ] &f" + pdata.get("name", pid), lore, "EMERALD")

            else:  # DRAFT
                lore = [
                    u"&7" + pdata.get("desc", u""),
                    u"&8---------------------------",
                    u"&7Требования для строительства:",
                    u"  &6• Бюджет: &f" + format_currency(pdata.get("req_money", 10000.0)),
                    u"  &b• Ресурсы: &f" + req_items_str,
                    u"  &e• Срок: &f%d ч." % int(pdata.get("duration_sec", 24 * 3600) / 3600),
                    u"&8---------------------------",
                    u"&eЛКМ &7— Начать строительство",
                    u"&eПКМ &7— Настроить проект (для Строителей)"
                ]
                self.set_item(slot, icon, u"&7[Черновик] &f" + pdata.get("name", pid), lore, "PAPER")

        self.set_item(49, "DARK_OAK_DOOR", u"&c&lНазад", [u"&7Вернуться в главное меню"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 49:
            TownMainGUI(player).open()
            return

        uuid_str, name = get_sender_uuid_and_name(player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city:
            return

        cproj = city.setdefault("custom_projects", {})

        if raw_slot == 8 and service.can_manage_projects(player, city):
            pid = u"proj_" + str(int(time.time()) % 10000)
            icon = "STONE_BRICKS"
            in_hand = player.getInventory().getItemInMainHand()
            if in_hand and in_hand.getType() != Material.AIR:
                icon = str(in_hand.getType().name())
            state.create_custom_project(city, pid, u"Новый объект #%d" % len(cproj), u"Кастомное здание города", icon)
            send_message(player, CitiesConfig.PREFIX + u"&aСоздан черновик проекта! Нажмите ПКМ по нему для настройки.")
            self.open()
            return

        if 9 <= raw_slot < 45:
            idx = raw_slot - 9
            sorted_keys = [k for k, v in sorted(cproj.items(), key=lambda x: x[1].get("name", "").lower())]
            if idx >= len(sorted_keys):
                return
            pid = sorted_keys[idx]
            pdata = cproj[pid]
            status = pdata.get("status", "DRAFT")

            if status == "BUILT":
                send_message(player, CitiesConfig.PREFIX + u"&aЭтот проект уже построен и украшает город!")
                return
            elif status == "ACTIVE":
                TownProjectDetailsGUI(player, pid).open()
                return
            else:  # DRAFT
                if click_type in ("RIGHT", "RIGHT_CLICK"):
                    if not service.can_manage_projects(player, city):
                        send_message(player, CitiesConfig.PREFIX + u"&cНастраивать проекты могут только Мэр, Заместитель или Строитель!")
                        return
                    TownProjectManageGUI(player, pid).open()
                else:
                    if not service.can_manage_projects(player, city):
                        send_message(player, CitiesConfig.PREFIX + u"&cНачинать строительство могут только Мэр, Заместитель или Строитель!")
                        return
                    for opid, opdata in cproj.items():
                        if opdata.get("status") == "ACTIVE":
                            send_message(player, CitiesConfig.PREFIX + u"&cУже ведётся строительство «%s»! Сначала завершите его." % opdata.get("name"))
                            return
                    now = int(time.time())
                    pdata["status"] = "ACTIVE"
                    pdata["start_time"] = now
                    pdata["end_time"] = now + int(pdata.get("duration_sec", 24 * 3600))
                    pdata["contributed_money"] = 0.0
                    pdata["contributed_items"] = {}
                    state.add_treasury_log(city, u"§eНачата стройка: " + pdata["name"])
                    state.save()

                    # ОПОВЕЩЕНИЕ ВСЕХ ОНЛАЙН-ЖИТЕЛЕЙ ГОРОДА О НАЧАЛЕ СТРОЙКИ
                    msg_proj = u"§e§l[Город] §a§lНАЧАТО СТРОИТЕЛЬСТВО ПРОЕКТА: §f§l«%s»§a§l!\n§7Зайдите в §e/townmenu §7-> §bПроекты§7, чтобы вносить ресурсы и средства!" % pdata["name"]
                    for m_uuid, m_name in city.get("members", {}).items():
                        m_player = service.get_online_player_by_uuid(m_uuid)
                        if m_player:
                            m_player.sendMessage(msg_proj)
                            try:
                                m_player.playSound(m_player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)
                            except Exception:
                                pass

                    send_message(player, CitiesConfig.PREFIX + u"&a&lНачато строительство проекта &e&l«%s»&a&l!" % pdata["name"])
                    self.open()


class TownProjectManageGUI(BaseTownGUI):
    def __init__(self, player, project_id):
        self.project_id = project_id
        BaseTownGUI.__init__(self, player, u"&e&lНастройка проекта", 3)

    def build(self):
        self.inventory.clear()
        uuid_str, name = get_sender_uuid_and_name(self.player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city or self.project_id not in city.get("custom_projects", {}):
            self.set_item(13, "BARRIER", u"&cПроект не найден", [u"&7Вернитесь в каталог"], "PAPER")
            self.set_item(22, "DARK_OAK_DOOR", u"&cНазад", [u"&7К каталогу проектов"], "PAPER")
            return

        pdata = city["custom_projects"][self.project_id]
        req_items_str = u", ".join([u"%s x%d" % (k, v) for k, v in pdata.get("req_items", {}).items()]) or u"нет требований"

        lore_info = [
            u"&7" + pdata.get("desc", u""),
            u"&8---------------------------",
            u"&7Бюджет (деньги жителей): &6" + format_currency(pdata.get("req_money", 10000.0)),
            u"&7Требуемые ресурсы: &b" + req_items_str,
            u"&7Время на стройку: &e%d ч." % int(pdata.get("duration_sec", 24 * 3600) / 3600),
            u"&8---------------------------",
            u"&aУдобное добавление ресурсов:",
            u"&7Кликайте ЛКМ/ПКМ по предметам",
            u"&7в своём нижнем инвентаре для добавления!"
        ]
        self.set_item(4, pdata.get("icon", "STONE_BRICKS"), u"&6&lНастройка: &f&l" + pdata.get("name"), lore_info, "EMERALD")

        self.set_item(10, "GOLD_BLOCK", u"&6&lИзменить бюджет", [
            u"&7Сколько денег нужно собрать в фонд:",
            u"&eЛКМ &7— &a+5 000$",
            u"&eПКМ &7— &c-5 000$"
        ], "GOLD_BLOCK")

        self.set_item(12, "EMERALD", u"&a&l+ Добавить предмет в руке", [
            u"&7Возьмите строительный блок/предмет",
            u"&7в руку и нажмите сюда:",
            u"&eЛКМ &7— добавить &a64 шт. &7предмета в руке",
            u"&eПКМ &7— добавить &a16 шт. &7предмета в руке"
        ], "EMERALD")

        self.set_item(14, "REDSTONE_BLOCK", u"&c&lОчистить ресурсы", [
            u"&7Сбросить все требования предметов",
            u"&cЛКМ — очистить список ресурсов"
        ], "PAPER")

        self.set_item(16, "CLOCK", u"&e&lСрок строительства", [
            u"&7Сколько часов займёт стройка:",
            u"&eЛКМ &7— &a+6 часов",
            u"&eПКМ &7— &c-6 часов"
        ], "PAPER")

        self.set_item(22, "NETHER_STAR", u"&a&l▶ ЗАПУСТИТЬ СТРОИТЕЛЬСТВО", [
            u"&7Переводит проект из черновика в",
            u"&eАКТИВНОЕ СТРОИТЕЛЬСТВО &7для всего города!"
        ], "PAPER")

        self.set_item(26, "TNT", u"&c&lУдалить проект", [u"&cНавсегда удалить этот проект"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        uuid_str, name = get_sender_uuid_and_name(player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city or self.project_id not in city.get("custom_projects", {}):
            TownUpgradesGUI(player).open()
            return

        pdata = city["custom_projects"][self.project_id]

        if raw_slot == 10:
            delta = -5000.0 if click_type in ("RIGHT", "RIGHT_CLICK") else 5000.0
            pdata["req_money"] = max(0.0, float(pdata.get("req_money", 10000.0)) + delta)
            state.save()
            self.open()

        elif raw_slot == 12:
            in_hand = player.getInventory().getItemInMainHand()
            if not in_hand or in_hand.getType() == Material.AIR:
                send_message(player, CitiesConfig.PREFIX + u"&cВозьмите предмет/блок в руку!")
                return
            mat_name = str(in_hand.getType().name())
            count = 16 if click_type in ("RIGHT", "RIGHT_CLICK") else 64
            pdata.setdefault("req_items", {})[mat_name] = pdata.get("req_items", {}).get(mat_name, 0) + count
            pdata["icon"] = mat_name
            state.save()
            send_message(player, CitiesConfig.PREFIX + u"&aДобавлено требование: &f%s x%d" % (mat_name, pdata["req_items"][mat_name]))
            self.open()

        elif raw_slot == 14:
            pdata["req_items"] = {}
            state.save()
            send_message(player, CitiesConfig.PREFIX + u"&eСписок требуемых ресурсов очищен.")
            self.open()

        elif raw_slot == 16:
            delta = -6 * 3600 if click_type in ("RIGHT", "RIGHT_CLICK") else 6 * 3600
            pdata["duration_sec"] = max(3600, int(pdata.get("duration_sec", 24 * 3600)) + delta)
            state.save()
            self.open()

        elif raw_slot == 22:
            for opid, opdata in city["custom_projects"].items():
                if opdata.get("status") == "ACTIVE":
                    send_message(player, CitiesConfig.PREFIX + u"&cУже ведётся строительство «%s»!" % opdata.get("name"))
                    return
            now = int(time.time())
            pdata["status"] = "ACTIVE"
            pdata["start_time"] = now
            pdata["end_time"] = now + int(pdata.get("duration_sec", 24 * 3600))
            pdata["contributed_money"] = 0.0
            pdata["contributed_items"] = {}
            state.add_treasury_log(city, u"§eНачата стройка: " + pdata["name"])
            state.save()

            msg_proj = u"§e§l[Город] §a§lНАЧАТО СТРОИТЕЛЬСТВО ПРОЕКТА: §f§l«%s»§a§l!\n§7Зайдите в §e/townmenu §7-> §bПроекты§7, чтобы вносить ресурсы и средства!" % pdata["name"]
            for m_uuid, m_name in city.get("members", {}).items():
                m_player = service.get_online_player_by_uuid(m_uuid)
                if m_player:
                    m_player.sendMessage(msg_proj)
                    try:
                        m_player.playSound(m_player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)
                    except Exception:
                        pass

            send_message(player, CitiesConfig.PREFIX + u"&a&lНачато строительство проекта &e&l«%s»&a&l!" % pdata["name"])
            TownUpgradesGUI(player).open()

        elif raw_slot == 26:
            state.delete_custom_project(city, self.project_id)
            send_message(player, CitiesConfig.PREFIX + u"&cПроект удалён.")
            TownUpgradesGUI(player).open()


class TownProjectDetailsGUI(BaseTownGUI):
    def __init__(self, player, project_id):
        self.project_id = project_id
        BaseTownGUI.__init__(self, player, u"&e&lСтройка города", 6)

    def build(self):
        self.inventory.clear()
        uuid_str, name = get_sender_uuid_and_name(self.player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city or self.project_id not in city.get("custom_projects", {}):
            self.set_item(13, "BARRIER", u"&cПроект не найден", [u"&7Вернитесь в каталог"], "PAPER")
            self.set_item(49, "DARK_OAK_DOOR", u"&c&lНазад", [u"&7К каталогу проектов"], "PAPER")
            return

        pdata = city["custom_projects"][self.project_id]
        rem_sec = max(0, int(pdata.get("end_time", 0)) - int(time.time()))
        cont_money = float(pdata.get("contributed_money", 0.0))
        cont_items = pdata.get("contributed_items", {})
        req_items = pdata.get("req_items", {})
        is_builder = service.can_manage_projects(self.player, city)

        item_lines = []
        for mat_name, req_cnt in req_items.items():
            got_cnt = cont_items.get(mat_name, 0)
            status_mark = u"&a✓" if got_cnt >= req_cnt else u"&c○"
            item_lines.append(u"  %s &f%s: &e%d &8/ &7%d" % (status_mark, mat_name, got_cnt, req_cnt))

        lore_card = [
            u"&7" + pdata.get("desc", u""),
            u"&8---------------------------",
            u"&7Целевое время готовности: &f" + format_duration_human(rem_sec),
            u"&7(Срок устанавливается Мэром/Строителем)",
            u"&8---------------------------",
            u"&7Собрано финансов: &6%s / %s" % (format_currency(cont_money), format_currency(pdata.get("req_money", 10000.0))),
            u"&7Собрано ресурсов:"
        ] + item_lines
        self.set_item(4, pdata.get("icon", "STONE_BRICKS"), u"&e&lСтроительство: &f&l" + pdata.get("name", self.project_id), lore_card, "EMERALD")

        # ---- Внести средства (slot 10) ----
        lore_pay = [
            u"&7Внести личные монеты в фонд",
            u"&7этого проекта.",
            u"",
            u"&eЛКМ &7— внести &a+500$",
            u"&eПКМ &7— внести &a+2500$",
            u"&eShift+ЛКМ &7— &fввести точную сумму",
        ]
        self.set_item(10, "EMERALD", u"&a&lВнести средства в проект", lore_pay, "EMERALD")

        # ---- Кнопка "Забрать средства" (только для builder/mayor/deputy) ----
        if is_builder:
            lore_wmoney = [
                u"&7Забрать деньги из фонда проекта",
                u"&7на свой личный баланс.",
                u"",
                u"&eЛКМ &7— забрать &c500$",
                u"&eПКМ &7— забрать &c2500$",
                u"&eShift+ЛКМ &7— &fввести точную сумму",
            ]
            self.set_item(16, "GOLD_INGOT", u"&6&lЗабрать средства", lore_wmoney, "GOLD_INGOT")

        # ---- ВСЕ требуемые ресурсы — каждый в отдельной ячейке (слоты 19-34) ----
        # Первый ряд 19..25 (7 слотов), второй ряд 28..34 (7 слотов). Итого до 14 ресурсов.
        RESOURCE_SLOTS = [19, 20, 21, 22, 23, 24, 25, 28, 29, 30, 31, 32, 33, 34]
        mat_keys = list(req_items.keys())
        # Сохраняем маппинг slot -> mat_name чтобы обработчик клика знал, какой ресурс.
        self._slot_to_mat = {}
        for idx, mat_name in enumerate(mat_keys[:len(RESOURCE_SLOTS)]):
            slot = RESOURCE_SLOTS[idx]
            self._slot_to_mat[slot] = mat_name
            req_cnt = req_items[mat_name]
            got_cnt = cont_items.get(mat_name, 0)
            done = u"&a✓ ГОТОВО" if got_cnt >= req_cnt else u"&e▸ В процессе"
            lore_mat = [
                u"&7Материал для строительства.",
                u"&7Собрано: &f%d &8/ &7%d  %s" % (got_cnt, req_cnt, done),
                u"",
                u"&eЛКМ &7— открыть подменю сдачи/забора",
            ]
            self.set_item(slot, mat_name, u"&b&lМатериал: &f" + mat_name, lore_mat, "PAPER")

        # ---- Кнопка завершения (slot 40) ----
        lore_finish = [
            u"&7Принудительно завершить строительство,",
            u"&7если выполнены требования или для тестов.",
            u"",
            u"&eЛКМ &7— &aЗавершить проект сейчас",
            u"&8(Только для Мэра или Администратора)"
        ]
        self.set_item(40, "NETHER_STAR", u"&6&lЗавершить проект", lore_finish, "PAPER")

        # ---- Кнопка "Назад" (slot 49) ----
        self.set_item(49, "DARK_OAK_DOOR", u"&c&lНазад к каталогу", [u"&7Вернуться к списку проектов"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        # Кнопка "Назад".
        if raw_slot == 49:
            TownUpgradesGUI(player).open()
            return

        uuid_str, name = get_sender_uuid_and_name(player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city:
            return

        pdata = city.setdefault("custom_projects", {}).get(self.project_id, {})
        if pdata.get("status") != "ACTIVE":
            TownUpgradesGUI(player).open()
            return

        is_builder = service.can_manage_projects(player, city)

        # Вклад/забор денег.
        if raw_slot == 10:
            if is_shift:
                # Точная сумма — через чат.
                pending_project_inputs[uid(player)] = {
                    "kind": "deposit_money",
                    "project_id": self.project_id,
                    "return_gui": "details",
                }
                send_message(player, CitiesConfig.PREFIX + u"&eВведите в чат сумму для вклада (или §fотмена§e):")
                player.closeInventory()
                return
            amount = 2500.0 if click_type in ("RIGHT", "RIGHT_CLICK") else 500.0
            self._deposit_money(player, city, pdata, amount)
            return

        if raw_slot == 16 and is_builder:
            if is_shift:
                pending_project_inputs[uid(player)] = {
                    "kind": "withdraw_money",
                    "project_id": self.project_id,
                    "return_gui": "details",
                }
                send_message(player, CitiesConfig.PREFIX + u"&eВведите в чат сумму для забора (или §fотмена§e):")
                player.closeInventory()
                return
            amount = 2500.0 if click_type in ("RIGHT", "RIGHT_CLICK") else 500.0
            self._withdraw_money(player, city, pdata, amount)
            return

        # Клик по ресурсу → подменю.
        slot_to_mat = getattr(self, "_slot_to_mat", {}) or {}
        if raw_slot in slot_to_mat:
            mat_name = slot_to_mat[raw_slot]
            TownProjectResourceGUI(player, self.project_id, mat_name).open()
            return

        # Завершить проект (slot 40).
        if raw_slot == 40:
            if not service.can_manage(player, city) and not is_admin(player):
                send_message(player, CitiesConfig.PREFIX + u"&cЗавершать проект досрочно может только Мэр или Администратор!")
                return
            self.finish_project(city, player)

    def _deposit_money(self, player, city, pdata, amount):
        uuid_str, name = get_sender_uuid_and_name(player)
        if amount <= 0:
            send_message(player, CitiesConfig.PREFIX + u"&cСумма должна быть больше нуля.")
            return
        city_snapshot = copy.deepcopy(city)
        if not economy.withdraw(uuid_str, amount):
            send_message(player, CitiesConfig.PREFIX + u"&cНедостаточно денег (нужно %s)." % format_currency(amount))
            return
        pdata["contributed_money"] = float(pdata.get("contributed_money", 0.0)) + amount
        state.add_treasury_log(city, u"§a+ %s в проект %s (от %s)" % (format_currency(amount), pdata["name"], name))
        if not state.save():
            city.clear()
            city.update(city_snapshot)
            refunded, balance = economy.deposit_checked(uuid_str, amount, name)
            if not refunded:
                log_info(u"CRITICAL: failed to refund project deposit for {0}, amount={1}".format(name, amount))
            send_message(player, CitiesConfig.PREFIX + u"&cНе удалось сохранить фонд проекта. Операция отменена.")
            return
        send_message(player, CitiesConfig.PREFIX + u"&aВы внесли &e%s &aв фонд проекта «%s»!" % (format_currency(amount), pdata["name"]))
        self.open()

    def _withdraw_money(self, player, city, pdata, amount):
        uuid_str, name = get_sender_uuid_and_name(player)
        cont = float(pdata.get("contributed_money", 0.0))
        if amount <= 0:
            send_message(player, CitiesConfig.PREFIX + u"&cСумма должна быть больше нуля.")
            return
        if amount > cont:
            send_message(player, CitiesConfig.PREFIX + u"&cВ фонде проекта только %s." % format_currency(cont))
            return
        city_snapshot = copy.deepcopy(city)
        pdata["contributed_money"] = cont - amount
        state.add_treasury_log(city, u"§c- %s из проекта %s (забрал %s)" % (format_currency(amount), pdata["name"], name))
        if not state.save():
            city.clear()
            city.update(city_snapshot)
            send_message(player, CitiesConfig.PREFIX + u"&cНе удалось сохранить фонд проекта. Операция отменена.")
            return
        deposited, balance = economy.deposit_checked(uuid_str, amount, name)
        if not deposited:
            city.clear()
            city.update(city_snapshot)
            if not state.save():
                log_info(u"CRITICAL: failed to roll back project withdrawal for {0}, amount={1}".format(name, amount))
            send_message(player, CitiesConfig.PREFIX + u"&cНе удалось начислить деньги. Операция отменена.")
            return
        send_message(player, CitiesConfig.PREFIX + u"&6Вы забрали &e%s &6из фонда проекта «%s»." % (format_currency(amount), pdata["name"]))
        self.open()

    def check_completion_and_reopen(self, city, player):
        pdata = city.setdefault("custom_projects", {}).get(self.project_id, {})
        rem_sec = int(pdata.get("end_time", 0)) - int(time.time())
        money_ok = (float(pdata.get("contributed_money", 0.0)) >= float(pdata.get("req_money", 10000.0)))
        items_ok = all(
            pdata.get("contributed_items", {}).get(k, 0) >= v
            for k, v in pdata.get("req_items", {}).items()
        )
        if rem_sec <= 0 or (money_ok and items_ok):
            self.finish_project(city, player)
        else:
            self.open()

    def finish_project(self, city, player):
        pdata = city.setdefault("custom_projects", {}).get(self.project_id, {})
        snapshot = copy.deepcopy(city)
        pdata["status"] = "BUILT"
        state.add_treasury_log(city, u"§a§lПОСТРОЕН ПРОЕКТ: %s!" % pdata["name"])
        state.add_server_audit(u"§aГород §e%s §aпостроил проект §f%s!" % (to_unicode(city.get("name")), pdata["name"]))
        if not state.save():
            city.clear()
            city.update(snapshot)
            send_message(player, CitiesConfig.PREFIX + u"&cПроект не завершён: данные города не удалось сохранить.")
            return
        send_message(player, CitiesConfig.PREFIX + u"&a&l✓ ПРОЕКТ «%s» УСПЕШНО ЗАВЕРШЁН!" % pdata["name"])
        TownUpgradesGUI(player).open()


# ---------------------------------------------------------------------------
# Подменю для сдачи/забора конкретного ресурса
# ---------------------------------------------------------------------------
class TownProjectResourceGUI(BaseTownGUI):
    """
    Подменю сдачи/забора одного конкретного ресурса.
    Кнопки: +1, +16, +64, +256, +512, +всё, Точное число (чат-ввод).
    Забор — только для Мэра/Заместителя/Строителя.
    """
    def __init__(self, player, project_id, mat_name):
        self.project_id = project_id
        self.mat_name = mat_name
        BaseTownGUI.__init__(self, player, u"&b&lРесурс: &f" + mat_name, 3)

    def build(self):
        self.inventory.clear()
        uuid_str, name = get_sender_uuid_and_name(self.player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city or self.project_id not in city.get("custom_projects", {}):
            self.set_item(13, "BARRIER", u"&cПроект не найден", [u"&7Вернитесь в каталог"], "PAPER")
            self.set_item(22, "DARK_OAK_DOOR", u"&cНазад", [u"&7К проекту"], "PAPER")
            return

        pdata = city["custom_projects"][self.project_id]
        req_items = pdata.get("req_items", {})
        cont_items = pdata.get("contributed_items", {})
        req_cnt = req_items.get(self.mat_name, 0)
        got_cnt = cont_items.get(self.mat_name, 0)
        is_builder = service.can_manage_projects(self.player, city)

        # Информационная плитка сверху.
        lore_info = [
            u"&7Проект: &f" + pdata.get("name", self.project_id),
            u"&7Материал: &f" + self.mat_name,
            u"&8---------------------------",
            u"&7Собрано: &e%d &8/ &7%d" % (got_cnt, req_cnt),
            u"&7Осталось: &f%d шт." % max(0, req_cnt - got_cnt),
        ]
        self.set_item(4, self.mat_name, u"&b&l" + self.mat_name, lore_info, "PAPER")

        # ---- Кнопки СДАЧИ (слоты 10-14) ----
        deposit_amounts = [(10, 1), (11, 16), (12, 64), (13, 256), (14, 512)]
        for slot, amt in deposit_amounts:
            self.set_item(slot, "EMERALD_BLOCK",
                u"&a&lСдать +%d" % amt,
                [u"&7Из вашего инвентаря",
                 u"&eЛКМ &7— сдать &a%d шт." % amt],
                "EMERALD")

        # Кнопка "точное число" (slot 15).
        self.set_item(15, "PAPER",
            u"&e&l✎ Ввести точное число",
            [u"&7Написать в чат сколько сдать.",
             u"&eЛКМ &7— открыть ввод в чат"],
            "PAPER")

        # Кнопка "сдать всё, что есть" (slot 16).
        self.set_item(16, "CHEST",
            u"&a&lСдать всё из инвентаря",
            [u"&7Сдать все имеющиеся у вас",
             u"&7предметы этого типа сразу.",
             u"&eЛКМ &7— сдать всё"],
            "CHEST")

        # ---- Кнопки ЗАБОРА (только для builder/mayor/deputy) ----
        if is_builder:
            withdraw_amounts = [(19, 1), (20, 16), (21, 64)]
            for slot, amt in withdraw_amounts:
                self.set_item(slot, "REDSTONE_BLOCK",
                    u"&c&lЗабрать -%d" % amt,
                    [u"&7В свой инвентарь",
                     u"&eЛКМ &7— забрать &c%d шт." % amt,
                     u"&8(только для Строителей+)"],
                    "REDSTONE_BLOCK")
            self.set_item(23, "PAPER",
                u"&e&l✎ Забрать точное число",
                [u"&7Написать в чат сколько забрать.",
                 u"&eЛКМ &7— открыть ввод в чат",
                 u"&8(только для Строителей+)"],
                "PAPER")
            self.set_item(24, "HOPPER",
                u"&c&lЗабрать всё сданное",
                [u"&7Забрать все сданные материалы",
                 u"&7этого типа из фонда.",
                 u"&eЛКМ &7— забрать всё"],
                "HOPPER")

        # Кнопка "Назад" (slot 22).
        self.set_item(22, "DARK_OAK_DOOR", u"&c&lНазад к проекту",
                      [u"&7Вернуться к обзору стройки"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 22:
            TownProjectDetailsGUI(player, self.project_id).open()
            return

        uuid_str, name = get_sender_uuid_and_name(player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city or self.project_id not in city.get("custom_projects", {}):
            TownUpgradesGUI(player).open()
            return
        pdata = city["custom_projects"][self.project_id]
        is_builder = service.can_manage_projects(player, city)

        # Сдача фиксированных количеств.
        deposit_map = {10: 1, 11: 16, 12: 64, 13: 256, 14: 512}
        if raw_slot in deposit_map:
            self._do_deposit_items(player, city, pdata, deposit_map[raw_slot])
            return

        # Точное число сдачи — чат.
        if raw_slot == 15:
            pending_project_inputs[uid(player)] = {
                "kind": "deposit_items",
                "project_id": self.project_id,
                "mat_name": self.mat_name,
                "return_gui": "resource",
            }
            send_message(player, CitiesConfig.PREFIX + u"&eВведите в чат количество для сдачи (или §fотмена§e):")
            player.closeInventory()
            return

        # Сдать всё.
        if raw_slot == 16:
            self._do_deposit_all(player, city, pdata)
            return

        # Забор фиксированных.
        if is_builder:
            withdraw_map = {19: 1, 20: 16, 21: 64}
            if raw_slot in withdraw_map:
                self._do_withdraw_items(player, city, pdata, withdraw_map[raw_slot])
                return
            if raw_slot == 23:
                pending_project_inputs[uid(player)] = {
                    "kind": "withdraw_items",
                    "project_id": self.project_id,
                    "mat_name": self.mat_name,
                    "return_gui": "resource",
                }
                send_message(player, CitiesConfig.PREFIX + u"&eВведите в чат количество для забора (или §fотмена§e):")
                player.closeInventory()
                return
            if raw_slot == 24:
                cont_items = pdata.setdefault("contributed_items", {})
                got = cont_items.get(self.mat_name, 0)
                if got > 0:
                    self._do_withdraw_items(player, city, pdata, got)
                else:
                    send_message(player, CitiesConfig.PREFIX + u"&cВ фонде нет %s." % self.mat_name)
                return

    def _do_deposit_items(self, player, city, pdata, count):
        if count <= 0:
            return
        inv = player.getInventory()
        mat_enum = material_value(self.mat_name, "STONE")
        if not mat_enum or not inv.contains(mat_enum, count):
            send_message(player, CitiesConfig.PREFIX + u"&cУ вас нет в инвентаре %d шт. %s." % (count, self.mat_name))
            return
        city_snapshot = copy.deepcopy(city)
        to_remove = count
        for item in inv.getContents():
            if item and item.getType() == mat_enum:
                if item.getAmount() <= to_remove:
                    to_remove -= item.getAmount()
                    inv.remove(item)
                else:
                    item.setAmount(item.getAmount() - to_remove)
                    to_remove = 0
                if to_remove <= 0:
                    break
        cont_items = pdata.setdefault("contributed_items", {})
        cont_items[self.mat_name] = cont_items.get(self.mat_name, 0) + count
        if not state.save():
            city.clear()
            city.update(city_snapshot)
            # Возвращаем изъятый ресурс. Если инвентарь заполнен между
            # операциями, остаток безопасно выпадает рядом с игроком.
            left = count
            while left > 0:
                stack = ItemStack(mat_enum, min(64, left))
                leftovers = inv.addItem(stack)
                if leftovers:
                    for extra in leftovers.values():
                        player.getWorld().dropItemNaturally(player.getLocation(), extra)
                left -= min(64, left)
            send_message(player, CitiesConfig.PREFIX + u"&cРесурс возвращён: фонд проекта не удалось сохранить.")
            return
        send_message(player, CitiesConfig.PREFIX + u"&aВы сдали &e%d шт. %s &aв проект!" % (count, self.mat_name))
        # Проверяем завершение и переоткрываем это же меню.
        req_items = pdata.get("req_items", {})
        rem_sec = int(pdata.get("end_time", 0)) - int(time.time())
        money_ok = (float(pdata.get("contributed_money", 0.0)) >= float(pdata.get("req_money", 10000.0)))
        items_ok = all(cont_items.get(k, 0) >= v for k, v in req_items.items())
        if rem_sec <= 0 or (money_ok and items_ok):
            pdata["status"] = "BUILT"
            state.add_treasury_log(city, u"§a§lПОСТРОЕН ПРОЕКТ: %s!" % pdata["name"])
            state.save()
            send_message(player, CitiesConfig.PREFIX + u"&a&l✓ ПРОЕКТ «%s» УСПЕШНО ЗАВЕРШЁН!" % pdata["name"])
            TownUpgradesGUI(player).open()
        else:
            self.open()

    def _do_deposit_all(self, player, city, pdata):
        inv = player.getInventory()
        mat_enum = material_value(self.mat_name, "STONE")
        if not mat_enum:
            return
        total = 0
        for item in inv.getContents():
            if item and item.getType() == mat_enum:
                total += item.getAmount()
        if total <= 0:
            send_message(player, CitiesConfig.PREFIX + u"&cУ вас нет %s в инвентаре." % self.mat_name)
            return
        self._do_deposit_items(player, city, pdata, total)

    def _do_withdraw_items(self, player, city, pdata, count):
        if count <= 0:
            return
        cont_items = pdata.setdefault("contributed_items", {})
        got = cont_items.get(self.mat_name, 0)
        if got <= 0:
            send_message(player, CitiesConfig.PREFIX + u"&cВ фонде проекта нет %s." % self.mat_name)
            return
        take = min(count, got)
        mat_enum = material_value(self.mat_name, "STONE")
        if not mat_enum:
            return
        # Сначала фиксируем уменьшение виртуального фонда. Это исключает дюп
        # при падении сервера между выдачей предметов и записью cities.json.
        city_snapshot = copy.deepcopy(city)
        cont_items[self.mat_name] = got - take
        if not state.save():
            city.clear()
            city.update(city_snapshot)
            send_message(player, CitiesConfig.PREFIX + u"&cПредметы не выданы: фонд проекта не удалось сохранить.")
            return

        # Раздаём стаками по 64.
        left = take
        try:
            while left > 0:
                chunk = min(64, left)
                copy = ItemStack(mat_enum, chunk)
                leftover = player.getInventory().addItem(copy)
                if leftover and len(leftover) > 0:
                    # Инвентарь полон — то, что не поместилось, кидаем под ноги.
                    for stack in leftover.values():
                        player.getWorld().dropItemNaturally(player.getLocation(), stack)
                left -= chunk
        except Exception as exc:
            # Редкий сбой Bukkit-выдачи: возвращаем ещё не выданную часть в
            # фонд. Уже выданные предметы остаются корректно списанными.
            if left > 0:
                refreshed = city.setdefault("custom_projects", {}).get(self.project_id, pdata)
                refreshed.setdefault("contributed_items", {})[self.mat_name] = \
                    refreshed.setdefault("contributed_items", {}).get(self.mat_name, 0) + left
                if not state.save():
                    log_info(u"CRITICAL: failed to restore unissued project items {0} x{1}: {2}".format(
                        self.mat_name, left, exc))
            send_message(player, CitiesConfig.PREFIX + u"&cЧасть предметов не удалось выдать; остаток возвращён в фонд.")
            return
        send_message(player, CitiesConfig.PREFIX + u"&6Вы забрали &e%d шт. %s &6из фонда проекта." % (take, self.mat_name))
        self.open()


# ---------------------------------------------------------------------------
# Ожидающие чат-вводы для проектов (кол-во / точная сумма).
# player_uuid -> {"kind": "...", "project_id": "...", "mat_name": "...", "return_gui": "..."}
# ---------------------------------------------------------------------------
pending_project_inputs = {}


class TownProjectManageGUI(BaseTownGUI):
    def __init__(self, player, project_id):
        self.project_id = project_id
        BaseTownGUI.__init__(self, player, u"&e&lНастройка проекта", 3)

    def build(self):
        self.inventory.clear()
        uuid_str, name = get_sender_uuid_and_name(self.player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city or self.project_id not in city.get("custom_projects", {}):
            self.set_item(13, "BARRIER", u"&cПроект не найден", [u"&7Вернитесь в каталог"], "PAPER")
            self.set_item(22, "DARK_OAK_DOOR", u"&cНазад", [u"&7К каталогу проектов"], "PAPER")
            return

        pdata = city["custom_projects"][self.project_id]
        req_items_str = u", ".join([u"%s x%d" % (k, v) for k, v in pdata.get("req_items", {}).items()]) or u"нет требований"

        lore_info = [
            u"&7" + pdata.get("desc", u""),
            u"&8---------------------------",
            u"&7Бюджет (деньги жителей): &6" + format_currency(pdata.get("req_money", 10000.0)),
            u"&7Требуемые ресурсы: &b" + req_items_str,
            u"&7Время на стройку: &e%d ч." % int(pdata.get("duration_sec", 24 * 3600) / 3600),
            u"&8---------------------------",
            u"&aУдобное добавление ресурсов:",
            u"&7Кликайте ЛКМ/ПКМ по предметам",
            u"&7в своём нижнем инвентаре для добавления!"
        ]
        self.set_item(4, pdata.get("icon", "STONE_BRICKS"), u"&6&lНастройка: &f&l" + pdata.get("name"), lore_info, "EMERALD")

        self.set_item(10, "GOLD_BLOCK", u"&6&lИзменить бюджет", [
            u"&7Сколько денег нужно собрать в фонд:",
            u"&eЛКМ &7— &a+5 000$",
            u"&eПКМ &7— &c-5 000$",
            u"&eShift+ЛКМ &7— &fввести точную сумму"
        ], "GOLD_BLOCK")

        self.set_item(12, "EMERALD", u"&a&l+ Добавить предмет в руке", [
            u"&7Возьмите строительный блок/предмет",
            u"&7в руку и нажмите сюда:",
            u"&eЛКМ &7— добавить &a64 шт. &7предмета в руке",
            u"&eПКМ &7— добавить &a16 шт. &7предмета в руке",
            u"&eShift+ЛКМ &7— &fввести точное число"
        ], "EMERALD")

        self.set_item(14, "REDSTONE_BLOCK", u"&c&lОчистить ресурсы", [
            u"&7Сбросить все требования предметов",
            u"&cЛКМ — очистить список ресурсов"
        ], "PAPER")

        self.set_item(16, "CLOCK", u"&e&lСрок строительства", [
            u"&7Сколько часов займёт стройка:",
            u"&eЛКМ &7— &a+6 часов",
            u"&eПКМ &7— &c-6 часов",
            u"&eShift+ЛКМ &7— &fввести точное число часов"
        ], "PAPER")

        self.set_item(22, "NETHER_STAR", u"&a&l▶ ЗАПУСТИТЬ СТРОИТЕЛЬСТВО", [
            u"&7Переводит проект из черновика в",
            u"&eАКТИВНОЕ СТРОИТЕЛЬСТВО &7для всего города!"
        ], "PAPER")

        self.set_item(18, "ARROW", u"&7Назад к каталогу", [u"&7Вернуться к списку проектов"], "PAPER")

        self.set_item(26, "TNT", u"&c&lУдалить проект", [u"&cНавсегда удалить этот проект"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 18:
            TownUpgradesGUI(player).open()
            return

        uuid_str, name = get_sender_uuid_and_name(player)
        city = state.get_city_by_player(uuid_str) if uuid_str else None
        if not city or self.project_id not in city.get("custom_projects", {}):
            TownUpgradesGUI(player).open()
            return

        pdata = city["custom_projects"][self.project_id]

        if raw_slot == 10:
            if is_shift:
                pending_project_inputs[uid(player)] = {
                    "kind": "set_budget",
                    "project_id": self.project_id,
                    "return_gui": "manage",
                }
                send_message(player, CitiesConfig.PREFIX + u"&eВведите в чат новый бюджет проекта (или §fотмена§e):")
                player.closeInventory()
                return
            delta = -5000.0 if click_type in ("RIGHT", "RIGHT_CLICK") else 5000.0
            pdata["req_money"] = max(0.0, float(pdata.get("req_money", 10000.0)) + delta)
            state.save()
            self.open()

        elif raw_slot == 12:
            in_hand = player.getInventory().getItemInMainHand()
            if not in_hand or in_hand.getType() == Material.AIR:
                send_message(player, CitiesConfig.PREFIX + u"&cВозьмите предмет/блок в руку!")
                return
            mat_name = str(in_hand.getType().name())
            if is_shift:
                pending_project_inputs[uid(player)] = {
                    "kind": "add_req_item",
                    "project_id": self.project_id,
                    "mat_name": mat_name,
                    "return_gui": "manage",
                }
                send_message(player, CitiesConfig.PREFIX + u"&eВведите в чат количество &f%s &eдля добавления (или §fотмена§e):" % mat_name)
                player.closeInventory()
                return
            count = 16 if click_type in ("RIGHT", "RIGHT_CLICK") else 64
            pdata.setdefault("req_items", {})[mat_name] = pdata.get("req_items", {}).get(mat_name, 0) + count
            pdata["icon"] = mat_name
            state.save()
            send_message(player, CitiesConfig.PREFIX + u"&aДобавлено требование: &f%s x%d" % (mat_name, pdata["req_items"][mat_name]))
            self.open()

        elif raw_slot == 14:
            pdata["req_items"] = {}
            state.save()
            send_message(player, CitiesConfig.PREFIX + u"&eСписок требуемых ресурсов очищен.")
            self.open()

        elif raw_slot == 16:
            if is_shift:
                pending_project_inputs[uid(player)] = {
                    "kind": "set_duration_h",
                    "project_id": self.project_id,
                    "return_gui": "manage",
                }
                send_message(player, CitiesConfig.PREFIX + u"&eВведите в чат новую длительность в часах (или §fотмена§e):")
                player.closeInventory()
                return
            delta = -6 * 3600 if click_type in ("RIGHT", "RIGHT_CLICK") else 6 * 3600
            pdata["duration_sec"] = max(3600, int(pdata.get("duration_sec", 24 * 3600)) + delta)
            state.save()
            self.open()

        elif raw_slot == 22:
            for opid, opdata in city["custom_projects"].items():
                if opdata.get("status") == "ACTIVE":
                    send_message(player, CitiesConfig.PREFIX + u"&cУже ведётся строительство «%s»!" % opdata.get("name"))
                    return
            now = int(time.time())
            pdata["status"] = "ACTIVE"
            pdata["start_time"] = now
            pdata["end_time"] = now + int(pdata.get("duration_sec", 24 * 3600))
            pdata["contributed_money"] = 0.0
            pdata["contributed_items"] = {}
            state.add_treasury_log(city, u"§eНачата стройка: " + pdata["name"])
            state.save()

            msg_proj = u"§e§l[Город] §a§lНАЧАТО СТРОИТЕЛЬСТВО ПРОЕКТА: §f§l«%s»§a§l!\n§7Зайдите в §e/townmenu §7-> §bПроекты§7, чтобы вносить ресурсы и средства!" % pdata["name"]
            for m_uuid, m_name in city.get("members", {}).items():
                m_player = service.get_online_player_by_uuid(m_uuid)
                if m_player:
                    m_player.sendMessage(msg_proj)
                    try:
                        m_player.playSound(m_player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)
                    except Exception:
                        pass

            send_message(player, CitiesConfig.PREFIX + u"&a&lНачато строительство проекта &e&l«%s»&a&l!" % pdata["name"])
            TownUpgradesGUI(player).open()

        elif raw_slot == 26:
            state.delete_custom_project(city, self.project_id)
            send_message(player, CitiesConfig.PREFIX + u"&cПроект удалён.")
            TownUpgradesGUI(player).open()


# -------------------------------------------------------------------------
# АДМИНСКИЕ GUI (/townadmin menu / /ta gui) И КАСТОМНЫЕ КВЕСТЫ
# -------------------------------------------------------------------------
class AdminMainGUI(BaseTownGUI):
    def __init__(self, player):
        BaseTownGUI.__init__(self, player, u"&c&lПанель Администратора", 3)

    def build(self):
        self.inventory.clear()
        total_cities = len(state.list_cities())

        self.set_item(4, "COMMAND_BLOCK", u"&c&lADMIN PANEL: &e&lSmartY-Politic", [
            u"&7Управление политикой сервера",
            u"&7Городов на сервере: &a%d" % total_cities,
            u"&8---------------------------",
            u"&7Панель модерации и аудита"
        ], "PAPER")

        self.set_item(10, "BEACON", u"&a&lСписок всех городов", [
            u"&7Управление любым городом на сервере:",
            u"  &f• Смена Мэра",
            u"  &f• Изменение казны (+/- 10 000$)",
            u"  &f• Завершение активного проекта",
            u"  &f• Удаление (роспуск) города",
            u"",
            u"&eНажмите для открытия каталога городов"
        ], "EMERALD")

        self.set_item(12, "GOLD_BLOCK", u"&6&lБыстрая выдача средств", [
            u"&7Тестовый режим экономики:",
            u"&eЛКМ &7— Выдать себе &a+50 000$",
            u"&eПКМ &7— Выдать себе &a+250 000$",
            u"",
            u"&cКлик для мгновенной выдачи"
        ], "GOLD_BLOCK")

        self.set_item(14, "BOOK", u"&e&lСерверный Аудит (Логи)", [
            u"&7История последних 20 событий:",
            u"&7Создание городов, смена мэров, постройки.",
            u"",
            u"&eНажмите для просмотра журнала"
        ], "PAPER")

        self.set_item(16, "EXPERIENCE_BOTTLE", u"&b&lЗавершить все стройки", [
            u"&7Мгновенно построить все активные",
            u"&7проекты во всех городах сервера",
            u"&7(Удобно для тестирования баффов).",
            u"",
            u"&cНажмите для завершения строек"
        ], "PAPER")

        self.set_item(18, "WRITABLE_BOOK", u"&d&lУправление Квестами", [
            u"&7Создание и удаление кастомных",
            u"&7серверных квестов для городов.",
            u"",
            u"&eНажмите для открытия менеджера квестов"
        ], "PAPER")

        self.set_item(22, "DARK_OAK_DOOR", u"&c&lВыход в меню города", [u"&7Вернуться к игровому меню"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 22:
            TownMainGUI(player).open()
        elif raw_slot == 10:
            AdminCitiesListGUI(player, 1).open()
        elif raw_slot == 12:
            uuid_str, name = get_sender_uuid_and_name(player)
            amount = 250000.0 if click_type in ("RIGHT", "RIGHT_CLICK") else 50000.0
            deposited, balance = economy.deposit_checked(uuid_str, amount, name)
            if deposited:
                send_message(player, CitiesConfig.PREFIX + u"&a&l[ADMIN] &aВам выдано +%s!" % format_currency(amount))
            else:
                send_message(player, CitiesConfig.PREFIX + u"&cВыдача не выполнена: экономика недоступна или баланс достиг лимита.")
            self.open()
        elif raw_slot == 14:
            AdminAuditGUI(player).open()
        elif raw_slot == 16:
            count = 0
            for city in state.list_cities():
                cproj = city.setdefault("custom_projects", {})
                for pid, pdata in cproj.items():
                    if pdata.get("status") == "ACTIVE":
                        pdata["status"] = "BUILT"
                        count += 1
            state.save()
            send_message(player, CitiesConfig.PREFIX + u"&a&l[ADMIN] &aЗавершено %d активных строек на сервере!" % count)
            self.open()
        elif raw_slot == 18:
            AdminQuestsGUI(player).open()


class AdminQuestsGUI(BaseTownGUI):
    """
    Управление кастомными серверными квестами.
    ЛКМ по слоту "+" — создать новый квест (открывает редактор).
    ЛКМ по существующему квесту — редактировать его.
    Shift+ЛКМ по существующему — удалить.
    """
    def __init__(self, player):
        BaseTownGUI.__init__(self, player, u"&c&l[ADMIN] Кастомные квесты", 4)

    def build(self):
        self.inventory.clear()
        cquests = state.data.setdefault("custom_quests", {})

        self.set_item(4, "WRITABLE_BOOK", u"&d&lРеестр кастомных квестов", [
            u"&7Всего квестов: &f%d" % len(cquests),
            u"&8---------------------------",
            u"&7Клик по квесту — редактировать.",
            u"&7Shift+ЛКМ — удалить квест.",
        ], "PAPER")

        self.set_item(8, "EMERALD_BLOCK", u"&a&l+ Создать новый квест", [
            u"&7Откроется редактор нового квеста.",
            u"&7Вы сможете:",
            u"&7• выбрать предмет кликом по инвентарю",
            u"&7• задать любое количество (чат)",
            u"&7• задать любую награду (чат)",
            u"&7• задать любое название (чат)",
            u"",
            u"&eЛКМ &7— создать квест",
        ], "PAPER")

        slot_idx = 9
        for qid, qdata in sorted(cquests.items(), key=lambda x: x[1].get("title", "").lower()):
            if slot_idx >= 36:
                break
            req_cnt = qdata.get("required_count", 64)
            mat_name = qdata.get("material", "STONE")
            lore = [
                u"&7Требуется сдать: &f%s x%d" % (mat_name, req_cnt),
                u"&7Награда городу: &6%s" % format_currency(qdata.get("reward_money", 1000.0)),
                u"&8---------------------------",
                u"&eЛКМ &7— редактировать",
                u"&cShift+ЛКМ &7— &cУДАЛИТЬ КВЕСТ",
            ]
            self.set_item(slot_idx, mat_name, u"&b" + qdata.get("title", qid), lore, "PAPER")
            slot_idx += 1

        self.set_item(31, "DARK_OAK_DOOR", u"&c&lНазад", [u"&cПанель Администратора"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 31:
            AdminMainGUI(player).open()
            return

        cquests = state.data.setdefault("custom_quests", {})

        if raw_slot == 8:
            # Создание нового квеста → сразу редактор.
            AdminQuestEditGUI(player, qid=None).open()
            return

        if 9 <= raw_slot < 36:
            sorted_q = sorted(cquests.items(), key=lambda x: x[1].get("title", "").lower())
            idx = raw_slot - 9
            if idx >= len(sorted_q):
                return
            qid, qdata = sorted_q[idx]
            if is_shift:
                state.delete_custom_quest(qid)
                send_message(player, CitiesConfig.PREFIX + u"&cКвест удалён.")
                self.open()
                return
            # Редактирование существующего квеста.
            AdminQuestEditGUI(player, qid=qid).open()


# ---------------------------------------------------------------------------
# Редактор одного кастомного квеста
# ---------------------------------------------------------------------------
class AdminQuestEditGUI(BaseTownGUI):
    """
    Редактор одного кастомного квеста.
    Работает и для нового (qid=None → черновик в памяти), и для существующего.

    Слоты:
       4  — превью квеста (материал + название)
      10  — изменить название (чат-ввод)
      12  — изменить количество: +1/+16/+64/+256 через click_type; Shift+ЛКМ — точное число
      14  — изменить награду:    +100/+1000/+10000/-100 через click_type; Shift+ЛКМ — точное число
      16  — сменить предмет квеста (включает режим 'кликните любой предмет в своём инвентаре')
      20  — сохранить (для нового квеста)
      24  — удалить (для существующего квеста)
      22  — Назад в каталог
    """
    # Черновики для новых квестов: uid_admin -> {title, material, required_count, reward_money}
    _drafts = {}

    def __init__(self, player, qid=None):
        self.qid = qid
        # Флаг: ждём клика по предмету в инвентаре (для смены материала).
        self.picking_material = False
        title_str = u"&c&l[ADMIN] Редактор квеста" if qid else u"&a&l[ADMIN] Новый квест"
        BaseTownGUI.__init__(self, player, title_str, 3)

    def _get_qdata(self):
        """Возвращает dict текущего квеста: либо из state, либо черновик."""
        if self.qid is not None:
            return state.data.setdefault("custom_quests", {}).get(self.qid)
        # Черновик — создаём если нет.
        u_str = uid(self.player)
        draft = AdminQuestEditGUI._drafts.get(u_str)
        if draft is None:
            draft = {
                "title": u"Новый квест",
                "material": "STONE",
                "required_count": 64,
                "reward_money": 5000.0,
            }
            AdminQuestEditGUI._drafts[u_str] = draft
        return draft

    def build(self):
        self.inventory.clear()
        qdata = self._get_qdata()
        if qdata is None:
            self.set_item(13, "BARRIER", u"&cКвест не найден", [u"&7Он был удалён."], "PAPER")
            self.set_item(22, "DARK_OAK_DOOR", u"&cНазад", [u"&7К списку квестов"], "PAPER")
            return

        is_new = (self.qid is None)
        mat_name = qdata.get("material", "STONE")
        title = qdata.get("title", u"Без названия")
        count = int(qdata.get("required_count", 64))
        reward = float(qdata.get("reward_money", 5000.0))

        # Превью (slot 4).
        preview_lore = [
            u"&7Название: &f" + title,
            u"&7Предмет: &f" + mat_name,
            u"&7Количество: &e%d шт." % count,
            u"&7Награда: &6" + format_currency(reward),
            u"",
        ]
        if self.picking_material:
            preview_lore.append(u"&e▸ Режим смены предмета активен")
            preview_lore.append(u"&7Кликните ЛКМ по нужному предмету")
            preview_lore.append(u"&7в своём инвентаре ниже.")
        else:
            preview_lore.append(u"&8Настройте параметры кнопками ниже.")
        self.set_item(4, mat_name, u"&d&l" + title, preview_lore, "PAPER")

        # Название (slot 10).
        self.set_item(10, "NAME_TAG", u"&e&l✎ Название квеста", [
            u"&7Текущее: &f" + title,
            u"",
            u"&eЛКМ &7— ввести новое в чате",
        ], "PAPER")

        # Количество (slot 12).
        self.set_item(12, "PAPER", u"&e&l⛏ Количество: &f%d" % count, [
            u"&7Сколько предмета нужно сдать.",
            u"",
            u"&eЛКМ &7— +1  &8|  &eПКМ &7— +16",
            u"&eShift+ЛКМ &7— +64  &8|  &eShift+ПКМ &7— +256",
            u"&eDROP (Q) &7— точное число (чат)",
            u"",
            u"&cЧтобы УМЕНЬШИТЬ — кнопка ниже (slot 21).",
        ], "PAPER")
        # Быстрая кнопка "-16" (slot 21).
        self.set_item(21, "REDSTONE", u"&c-16 к количеству", [
            u"&7Уменьшить на 16.",
            u"&eЛКМ &7— -16  &8|  &eПКМ &7— -64",
            u"&eShift+ЛКМ &7— сбросить в 1",
        ], "REDSTONE")

        # Награда (slot 14).
        self.set_item(14, "GOLD_INGOT", u"&6&l$ Награда: &f" + format_currency(reward), [
            u"&7Сколько денег получит город.",
            u"",
            u"&eЛКМ &7— +100  &8|  &eПКМ &7— +1 000",
            u"&eShift+ЛКМ &7— +10 000  &8|  &eShift+ПКМ &7— -1 000",
            u"&eDROP (Q) &7— точное число (чат)",
        ], "GOLD_INGOT")
        # Быстрая кнопка "-100" (slot 23).
        self.set_item(23, "GUNPOWDER", u"&c-100 к награде", [
            u"&7Уменьшить награду.",
            u"&eЛКМ &7— -100  &8|  &eПКМ &7— -1 000",
            u"&eShift+ЛКМ &7— сбросить в 0",
        ], "GUNPOWDER")

        # Сменить предмет (slot 16).
        if self.picking_material:
            slot16_mat = "COMPASS"
            slot16_title = u"&e&l▶ Ждём клик по предмету..."
            slot16_lore = [
                u"&7Кликните любой предмет в своём инвентаре.",
                u"&7Или &eЛКМ &7здесь — отменить режим.",
            ]
        else:
            slot16_mat = "COMPASS"
            slot16_title = u"&b&l🔄 Сменить предмет квеста"
            slot16_lore = [
                u"&7Текущий: &f" + mat_name,
                u"",
                u"&eЛКМ &7— включить режим:",
                u"&7  «Кликните любой предмет в своём",
                u"&7  инвентаре, чтобы взять его как цель квеста».",
            ]
        self.set_item(16, slot16_mat, slot16_title, slot16_lore, "PAPER")

        # Сохранить (только для нового) / Удалить (только для существующего).
        if is_new:
            self.set_item(20, "EMERALD_BLOCK", u"&a&l✓ СОЗДАТЬ КВЕСТ", [
                u"&7Сохранить черновик как активный квест.",
                u"&7Все города смогут его выполнять.",
                u"",
                u"&eЛКМ &7— создать",
            ], "EMERALD")
        else:
            self.set_item(24, "TNT", u"&c&lУдалить квест", [
                u"&7Квест будет удалён навсегда.",
                u"",
                u"&eЛКМ &7— удалить",
            ], "PAPER")

        # Назад (slot 22).
        self.set_item(22, "DARK_OAK_DOOR", u"&c&lНазад к списку", [
            u"&7Вернуться к каталогу квестов",
        ], "PAPER")

    def _apply_and_save(self):
        """Сохраняет qdata обратно в state."""
        state.save()

    def _get_draft_or_qdata(self):
        return self._get_qdata()

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 22:
            AdminQuestsGUI(player).open()
            return

        qdata = self._get_qdata()
        if qdata is None:
            AdminQuestsGUI(player).open()
            return

        is_new = (self.qid is None)

        # --- Название (чат-ввод) ---
        if raw_slot == 10:
            pending_project_inputs[uid(player)] = {
                "kind": "quest_title",
                "qid": self.qid,
                "return_gui": "quest_edit",
            }
            send_message(player, CitiesConfig.PREFIX + u"&eВведите в чат новое название квеста (или §fотмена§e):")
            player.closeInventory()
            return

        # --- Количество ---
        if raw_slot == 12:
            if click_type in ("DROP", "CONTROL_DROP"):
                pending_project_inputs[uid(player)] = {
                    "kind": "quest_count",
                    "qid": self.qid,
                    "return_gui": "quest_edit",
                }
                send_message(player, CitiesConfig.PREFIX + u"&eВведите в чат нужное количество (или §fотмена§e):")
                player.closeInventory()
                return
            if is_shift:
                delta = 256 if click_type in ("RIGHT", "RIGHT_CLICK") else 64
            else:
                delta = 16 if click_type in ("RIGHT", "RIGHT_CLICK") else 1
            qdata["required_count"] = max(1, int(qdata.get("required_count", 64)) + delta)
            self._apply_and_save()
            self.open()
            return

        if raw_slot == 21:
            if is_shift:
                qdata["required_count"] = 1
            else:
                delta = -64 if click_type in ("RIGHT", "RIGHT_CLICK") else -16
                qdata["required_count"] = max(1, int(qdata.get("required_count", 64)) + delta)
            self._apply_and_save()
            self.open()
            return

        # --- Награда ---
        if raw_slot == 14:
            if click_type in ("DROP", "CONTROL_DROP"):
                pending_project_inputs[uid(player)] = {
                    "kind": "quest_reward",
                    "qid": self.qid,
                    "return_gui": "quest_edit",
                }
                send_message(player, CitiesConfig.PREFIX + u"&eВведите в чат размер награды (или §fотмена§e):")
                player.closeInventory()
                return
            if is_shift:
                delta = -1000.0 if click_type in ("RIGHT", "RIGHT_CLICK") else 10000.0
            else:
                delta = 1000.0 if click_type in ("RIGHT", "RIGHT_CLICK") else 100.0
            qdata["reward_money"] = max(0.0, float(qdata.get("reward_money", 0.0)) + delta)
            self._apply_and_save()
            self.open()
            return

        if raw_slot == 23:
            if is_shift:
                qdata["reward_money"] = 0.0
            else:
                delta = -1000.0 if click_type in ("RIGHT", "RIGHT_CLICK") else -100.0
                qdata["reward_money"] = max(0.0, float(qdata.get("reward_money", 0.0)) + delta)
            self._apply_and_save()
            self.open()
            return

        # --- Сменить предмет ---
        if raw_slot == 16:
            self.picking_material = not self.picking_material
            self.open()
            return

        # --- Сохранить (только для нового) ---
        if raw_slot == 20 and is_new:
            u_str = uid(player)
            draft = AdminQuestEditGUI._drafts.get(u_str) or qdata
            new_qid = u"quest_" + str(int(time.time()) % 100000)
            state.create_custom_quest(
                new_qid,
                draft.get("title", u"Новый квест"),
                draft.get("material", "STONE"),
                int(draft.get("required_count", 64)),
                float(draft.get("reward_money", 5000.0))
            )
            AdminQuestEditGUI._drafts.pop(u_str, None)
            send_message(player, CitiesConfig.PREFIX +
                u"&a&l✓ Создан кастомный квест: &f%s &aна &e%d шт. &a(Награда: %s)" % (
                    draft.get("title", u"?"),
                    int(draft.get("required_count", 64)),
                    format_currency(draft.get("reward_money", 0.0))
                ))
            AdminQuestsGUI(player).open()
            return

        # --- Удалить (только для существующего) ---
        if raw_slot == 24 and not is_new:
            state.delete_custom_quest(self.qid)
            send_message(player, CitiesConfig.PREFIX + u"&cКвест удалён.")
            AdminQuestsGUI(player).open()
            return

    def handle_bottom_click(self, player, item):
        """Обрабатывает клик по предмету в НИЖНЕМ инвентаре игрока.
        Работает только когда включён режим picking_material."""
        if not self.picking_material:
            send_message(player, CitiesConfig.PREFIX + u"&8Чтобы взять предмет, сначала включите режим смены (slot 16).")
            return
        if not item or item.getType() == Material.AIR:
            return
        mat_name = str(item.getType().name())
        qdata = self._get_qdata()
        if qdata is None:
            return
        qdata["material"] = mat_name
        self.picking_material = False
        self._apply_and_save()
        send_message(player, CitiesConfig.PREFIX + u"&aПредмет квеста установлен: &f" + mat_name)
        self.open()


class AdminCitiesListGUI(BaseTownGUI):
    def __init__(self, player, page=1):
        self.page = max(1, int(page))
        BaseTownGUI.__init__(self, player, u"&c&l[ADMIN] Выберите город", 6)

    def build(self):
        self.inventory.clear()
        cities = state.list_cities()
        page_size = 45
        total_pages = max(1, int((len(cities) + page_size - 1) / page_size))
        self.page = min(self.page, total_pages)
        chunk = cities[(self.page - 1) * page_size:self.page * page_size]

        for index, city in enumerate(chunk):
            lore = [
                u"&7Мэр: &f" + to_unicode(city.get("mayor_name", u"?")),
                u"&7Жителей: &a%d" % len(city.get("members", {})),
                u"&7Казна: &6%s" % format_currency(city.get("treasury", 0.0)),
                u"&8---------------------------",
                u"&cЛКМ &7— Открыть управление городом"
            ]
            self.set_item(index, "BEACON", u"&e" + to_unicode(city.get("name")), lore, "EMERALD")

        self.set_item(45, "ARROW", u"&7Назад", [u"&cПанель Администратора"], "PAPER")
        if self.page > 1:
            self.set_item(48, "ARROW", u"&aПредыдущая", [u"&7Страница %d" % (self.page - 1)], "PAPER")
        self.set_item(49, "MAP", u"&eСтраница %d/%d" % (self.page, total_pages), None, "PAPER")
        if self.page < total_pages:
            self.set_item(50, "ARROW", u"&aСледующая", [u"&7Страница %d" % (self.page + 1)], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 45:
            AdminMainGUI(player).open()
        elif raw_slot == 48 and self.page > 1:
            AdminCitiesListGUI(player, self.page - 1).open()
        elif raw_slot == 50:
            AdminCitiesListGUI(player, self.page + 1).open()
        elif 0 <= raw_slot < 45:
            cities = state.list_cities()
            idx = (self.page - 1) * 45 + raw_slot
            if idx < len(cities):
                AdminCityManageGUI(player, cities[idx].get("name")).open()


class AdminCityManageGUI(BaseTownGUI):
    def __init__(self, player, city_name):
        self.city_name = city_name
        BaseTownGUI.__init__(self, player, u"&c&l[ADMIN] Город: " + to_unicode(city_name), 3)

    def build(self):
        self.inventory.clear()
        city = state.get_city(self.city_name)
        if not city:
            self.set_item(13, "BARRIER", u"&cГород не найден", [u"&7Он был удалён"], "PAPER")
            self.set_item(22, "DARK_OAK_DOOR", u"&cНазад", [u"&7К списку городов"], "PAPER")
            return

        treasury = city.get("treasury", 0.0)
        cproj = city.setdefault("custom_projects", {})
        active_id = None
        for pid, pdata in cproj.items():
            if pdata.get("status") == "ACTIVE":
                active_id = pid
                break

        lore_info = [
            u"&7Мэр: &6" + to_unicode(city.get("mayor_name")),
            u"&7Население: &a%d" % len(city.get("members", {})),
            u"&7Казна: &6%s" % format_currency(treasury),
            u"&7Активная стройка: " + (u"&e" + cproj[active_id]["name"] if active_id else u"&7Нет")
        ]
        self.set_item(4, "BEACON", u"&6&lУправление: &f&l" + to_unicode(city.get("name")), lore_info, "EMERALD")

        self.set_item(10, "GOLD_BLOCK", u"&6&lКазна Города", [
            u"&7Быстрое изменение казны города:",
            u"&eЛКМ &7— добавить &a+10 000$",
            u"&eПКМ &7— снять &c-10 000$",
            u"&eShift+ЛКМ &7— установить ровно &650 000$"
        ], "GOLD_BLOCK")

        self.set_item(12, "GOLDEN_HELMET", u"&e&lСменить Мэра", [
            u"&7Передать пост Мэра другому жителю",
            u"&7города в один клик.",
            u"",
            u"&eЛКМ &7— назначить следующего жителя Мэром"
        ], "PAPER")

        self.set_item(14, "EXPERIENCE_BOTTLE", u"&b&lЗавершить стройку", [
            u"&7Мгновенно достроить текущий",
            u"&7активный проект этого города.",
            u"",
            u"&eЛКМ &7— &aЗавершить стройку сейчас"
        ], "PAPER")

        self.set_item(16, "TNT", u"&c&lУдалить (распустить) город", [
            u"&c&lВНИМАНИЕ: Безвозвратный роспуск!",
            u"&7Удаляет город и сбрасывает цвета.",
            u"",
            u"&cShift+ЛКМ &7— &cРАСПУСТИТЬ ГОРОД"
        ], "PAPER")

        self.set_item(22, "DARK_OAK_DOOR", u"&c&lНазад к городам", [u"&7Вернуться к списку городов"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 22:
            AdminCitiesListGUI(player, 1).open()
            return

        city = state.get_city(self.city_name)
        if not city:
            return

        if raw_slot == 10:
            result = None
            if is_shift:
                result = state.set_treasury(city, 50000.0, actor_name=player.getName())
            elif click_type in ("RIGHT", "RIGHT_CLICK"):
                result = state.change_treasury(city, -10000.0, actor_name=player.getName())
            else:
                result = state.change_treasury(city, 10000.0, actor_name=player.getName())
            if result is None:
                send_message(player, CitiesConfig.PREFIX + u"&cКазну не удалось изменить. Проверьте сумму и хранилище.")
                return
            send_message(player, CitiesConfig.PREFIX + u"&a&l[ADMIN] &aКазна города изменена: %s" % format_currency(city.get("treasury", 0.0)))
            self.open()

        elif raw_slot == 12:
            members = list(city.get("members", {}).keys())
            if len(members) <= 1:
                send_message(player, CitiesConfig.PREFIX + u"&cВ городе нет других жителей для назначения Мэром.")
                return
            cur_uuid = str(city.get("mayor_uuid"))
            next_uuid = members[0]
            for i, u in enumerate(members):
                if u == cur_uuid and i + 1 < len(members):
                    next_uuid = members[i + 1]
                    break
            next_name = city["members"][next_uuid]
            state.set_mayor(city, next_uuid, next_name)
            service.apply_player_color_by_uuid(cur_uuid)
            service.apply_player_color_by_uuid(next_uuid)
            send_message(player, CitiesConfig.PREFIX + u"&a&l[ADMIN] &aНовый Мэр города %s: &e%s" % (city.get("name"), next_name))
            self.open()

        elif raw_slot == 14:
            cproj = city.setdefault("custom_projects", {})
            active_id = None
            for pid, pdata in cproj.items():
                if pdata.get("status") == "ACTIVE":
                    active_id = pid
                    break
            if not active_id:
                send_message(player, CitiesConfig.PREFIX + u"&cВ городе сейчас нет активных строек.")
                return
            cproj[active_id]["status"] = "BUILT"
            state.add_treasury_log(city, u"§a§lПОСТРОЕН ПРОЕКТ: %s!" % cproj[active_id]["name"])
            state.save()
            send_message(player, CitiesConfig.PREFIX + u"&a&l[ADMIN] &aПроект «%s» завершён!" % cproj[active_id]["name"])
            self.open()

        elif raw_slot == 16:
            if not is_shift:
                send_message(player, CitiesConfig.PREFIX + u"&cДля удаления города нажмите &eShift+ЛКМ&c!")
                return
            if get_city_companies(city.get("name")):
                send_message(player, CitiesConfig.PREFIX + u"&cСначала закройте все предприятия этого города.")
                return
            name = city.get("name")
            member_uuids = list(city.get("members", {}).keys())
            if not state.delete_city(city):
                send_message(player, CitiesConfig.PREFIX + u"&cГород не удален: данные не удалось сохранить.")
                return
            for player_uuid in member_uuids:
                p = service.get_online_player_by_uuid(player_uuid)
                if p:
                    service.reset_player_color(p)
            send_message(player, CitiesConfig.PREFIX + u"&c&l[ADMIN] &cГород %s распущен." % name)
            AdminCitiesListGUI(player, 1).open()


class AdminAuditGUI(BaseTownGUI):
    def __init__(self, player):
        BaseTownGUI.__init__(self, player, u"&e&lАудит событий сервера", 4)

    def build(self):
        self.inventory.clear()
        audit_list = state.data.get("server_audit", [])

        for idx in range(27):
            if idx < len(audit_list):
                msg = audit_list[idx]
                self.set_item(idx, "BOOK", u"&e&lСобытие #%d" % (idx + 1), [u"&7" + msg], "PAPER")
            else:
                self.set_item(idx, "GRAY_STAINED_GLASS_PANE", u"&8[Пустая запись]", [u"&7Запись отсутствует"], "PAPER")

        self.set_item(31, "DARK_OAK_DOOR", u"&c&lНазад", [u"&cПанель Администратора"], "PAPER")

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 31:
            AdminMainGUI(player).open()


class CityCommand(object):
    SUBCOMMANDS = ["help", "create", "list", "info", "members", "companies", "add", "remove", "mayor", "deposit", "withdraw", "leave", "disband", "accept", "deny", "color", "rename", "role", "tax", "project", "proj", "home", "sethome", "tp"]
    ADMIN_SUBCOMMANDS = ["reload", "delete", "setmayor", "treasury", "menu", "gui"]

    def __init__(self, service, state, economy):
        self.service = service
        self.state = state
        self.economy = economy

    def execute_city(self, sender, label, args):
        args = list(args)
        sub = args[0].lower() if args else "info"
        if sub == "help":
            self.send_help(sender, label)
        elif sub == "create" and len(args) >= 2:
            self.service.create_city(sender, args[1])
        elif sub == "list":
            self.send_city_list(sender, self.parse_page(args[1] if len(args) > 1 else "1"))
        elif sub == "info":
            self.send_city_info(sender, args[1] if len(args) > 1 else None)
        elif sub == "members":
            self.send_members(sender, args[1] if len(args) > 1 else None)
        elif sub == "companies":
            self.send_companies(sender, args[1] if len(args) > 1 else None)
        elif sub == "add" and len(args) >= 2:
            self.service.add_member(sender, args[1])
        elif sub == "remove" and len(args) >= 2:
            self.service.remove_member(sender, args[1])
        elif sub == "mayor" and len(args) >= 2:
            self.service.set_mayor(sender, args[1])
        elif sub == "accept":
            self.service.accept_invite(sender, args[1] if len(args) > 1 else None)
        elif sub == "deny":
            self.service.deny_invite(sender, args[1] if len(args) > 1 else None)
        elif sub == "rename" and len(args) >= 2:
            self.service.rename(sender, args[1])
        elif sub == "color" and len(args) >= 3 and args[1].lower() == "set":
            self.service.set_color(sender, args[2])
        elif sub == "role":
            self.handle_role(sender, args)
        elif sub == "tax":
            self.handle_tax(sender, args)
        elif sub in ("project", "proj"):
            self.handle_project(sender, args)
        elif sub == "deposit" and len(args) >= 2:
            amount = self.safe_amount(sender, args[1])
            if amount > 0:
                self.service.deposit(sender, amount)
        elif sub == "withdraw" and len(args) >= 2:
            amount = self.safe_amount(sender, args[1])
            if amount > 0:
                self.service.withdraw(sender, amount)
        elif sub == "leave":
            self.service.leave(sender)
        elif sub == "disband":
            self.service.disband(sender)
        elif sub == "home":
            self.service.town_home(sender)
        elif sub == "sethome":
            self.service.town_sethome(sender)
        elif sub == "tp" and len(args) >= 2:
            mode = args[1].lower()
            if mode in (u"on", u"вкл", u"enable"):
                self.service.town_tp_toggle(sender, True)
            elif mode in (u"off", u"выкл", u"disable"):
                self.service.town_tp_toggle(sender, False)
            else:
                send_message(sender, CitiesConfig.PREFIX + u"&cИспользование: &f/town tp <on|off>")
        else:
            self.send_help(sender, label)
        return True

    def handle_project(self, sender, args):
        city = self.service.require_own_city(sender)
        if not city:
            return
        if not self.service.can_manage_projects(sender, city):
            send_message(sender, CitiesConfig.PREFIX + u"&cУправлять проектами могут только Мэр, Заместитель или Строитель.")
            return

        if len(args) < 2:
            self.send_project_help(sender)
            return

        action = args[1].lower()
        cproj = city.setdefault("custom_projects", {})

        if action == "list":
            send_message(sender, CitiesConfig.PREFIX + u"&bПроекты города &e%s&b:" % to_unicode(city.get("name")))
            for pid, pdata in cproj.items():
                st_str = u"&a[ПОСТРОЕНО]" if pdata["status"] == "BUILT" else (u"&e[СТРОИТСЯ]" if pdata["status"] == "ACTIVE" else u"&7[Черновик]")
                send_message(sender, u"&8- %s &f%s &7(%s)" % (st_str, pdata["name"], pid))
            return

        if action == "create" and len(args) >= 3:
            pname = to_unicode(" ".join(args[2:]))
            pid = self.state.normalize_name(args[2])
            if pid in cproj:
                send_message(sender, CitiesConfig.PREFIX + u"&cПроект с таким ID уже существует!")
                return
            icon = "STONE_BRICKS"
            if hasattr(sender, "getInventory"):
                in_hand = sender.getInventory().getItemInMainHand()
                if in_hand and in_hand.getType() != Material.AIR:
                    icon = str(in_hand.getType().name())
            self.state.create_custom_project(city, pid, pname, u"Кастомная постройка города", icon)
            send_message(sender, CitiesConfig.PREFIX + u"&aСоздан черновик проекта &e%s &a(ID: &f%s&a)." % (pname, pid))
            return

        if len(args) < 3:
            self.send_project_help(sender)
            return

        pid = self.state.normalize_name(args[2])
        if pid not in cproj:
            send_message(sender, CitiesConfig.PREFIX + u"&cПроект &f%s &cне найден!" % pid)
            return

        pdata = cproj[pid]

        if action == "desc" and len(args) >= 4:
            pdata["desc"] = to_unicode(" ".join(args[3:]))
            self.state.save()
            send_message(sender, CitiesConfig.PREFIX + u"&aОписание проекта &e%s &aизменено." % pdata["name"])
            return

        if action == "reqmoney" and len(args) >= 4:
            val = self.safe_amount(sender, args[3])
            if val <= 0:
                return
            pdata["req_money"] = val
            self.state.save()
            send_message(sender, CitiesConfig.PREFIX + u"&aБюджет проекта &e%s &aустановлен: %s" % (pdata["name"], format_currency(val)))
            return

        if action == "addreq" and len(args) >= 5:
            mat_name = to_unicode(args[3]).upper()
            count = self.safe_positive_int(sender, args[4], u"Количество")
            if count is None:
                return
            mat_enum = material_value(mat_name, None)
            if not mat_enum:
                send_message(sender, CitiesConfig.PREFIX + u"&cМатериал &f%s &cне найден в Minecraft!" % mat_name)
                return
            pdata.setdefault("req_items", {})[mat_name] = count
            self.state.save()
            send_message(sender, CitiesConfig.PREFIX + u"&aК проекту &e%s &aдобавлено требование: &f%s x%d" % (pdata["name"], mat_name, count))
            return

        if action == "addhand" and len(args) >= 4:
            count = self.safe_positive_int(sender, args[3], u"Количество")
            if count is None:
                return
            if not hasattr(sender, "getInventory"):
                return
            in_hand = sender.getInventory().getItemInMainHand()
            if not in_hand or in_hand.getType() == Material.AIR:
                send_message(sender, CitiesConfig.PREFIX + u"&cВозьмите предмет в руку!")
                return
            mat_name = str(in_hand.getType().name())
            pdata.setdefault("req_items", {})[mat_name] = count
            pdata["icon"] = mat_name
            self.state.save()
            send_message(sender, CitiesConfig.PREFIX + u"&aК проекту &e%s &aдобавлено требование из руки: &f%s x%d" % (pdata["name"], mat_name, count))
            return

        if action == "duration" and len(args) >= 4:
            hours = self.safe_positive_int(sender, args[3], u"Часы", 100000)
            if hours is None:
                return
            old_duration = pdata.get("duration_sec")
            pdata["duration_sec"] = hours * 3600
            if not self.state.save():
                if old_duration is None:
                    pdata.pop("duration_sec", None)
                else:
                    pdata["duration_sec"] = old_duration
                send_message(sender, CitiesConfig.PREFIX + u"&cНе удалось сохранить срок проекта. Значение не изменено.")
                return
            send_message(sender, CitiesConfig.PREFIX + u"&aВремя строительства проекта &e%s &aустановлено: %d ч." % (pdata["name"], hours))
            return

        if action == "start":
            for opid, opdata in cproj.items():
                if opdata.get("status") == "ACTIVE":
                    send_message(sender, CitiesConfig.PREFIX + u"&cСначала завершите текущий активный проект («%s»)!" % opdata["name"])
                    return
            now = int(time.time())
            pdata["status"] = "ACTIVE"
            pdata["start_time"] = now
            pdata["end_time"] = now + int(pdata.get("duration_sec", 24 * 3600))
            pdata["contributed_money"] = 0.0
            pdata["contributed_items"] = {}
            self.state.add_treasury_log(city, u"§eНачата стройка: " + pdata["name"])
            self.state.save()
            send_message(sender, CitiesConfig.PREFIX + u"&a&lНачато строительство проекта &e&l«%s»&a&l!" % pdata["name"])
            return

        if action == "delete":
            self.state.delete_custom_project(city, pid)
            send_message(sender, CitiesConfig.PREFIX + u"&cПроект &f%s &cудалён." % pid)
            return

        self.send_project_help(sender)

    def send_project_help(self, sender):
        send_message(sender, CitiesConfig.PREFIX + u"&e/town project list &7- список проектов города")
        send_message(sender, u"&e/town project create <название> &7- создать проект")
        send_message(sender, u"&e/town project desc <id> <текст...> &7- описание")
        send_message(sender, u"&e/town project reqmoney <id> <сумма> &7- требуемые монеты")
        send_message(sender, u"&e/town project addreq <id> <материал> <кол-во> &7- добавить ресурс")
        send_message(sender, u"&e/town project addhand <id> <кол-во> &7- добавить ресурс из руки")
        send_message(sender, u"&e/town project duration <id> <часы> &7- длительность постройки")
        send_message(sender, u"&e/town project start <id> &7- начать строительство")
        send_message(sender, u"&e/town project delete <id> &7- удалить проект")

    def handle_tax(self, sender, args):
        if len(args) < 2 or args[1].lower() in ("info", "list"):
            self.send_tax_info(sender)
            return
        if args[1].lower() == "set":
            if len(args) == 3:
                amount = self.safe_percent(sender, args[2])
                if amount is not None:
                    self.service.set_tax(sender, "companies", amount)
                return
            if len(args) >= 4:
                amount = self.safe_percent(sender, args[3])
                if amount is not None:
                    self.service.set_tax(sender, args[2], amount)
                return
        self.send_tax_help(sender)

    def handle_role(self, sender, args):
        if len(args) < 2:
            self.send_role_help(sender)
            return
        action = args[1].lower()
        if action == "list":
            self.send_role_list(sender)
        elif action == "create" and len(args) >= 3:
            self.service.create_role(sender, args[2])
        elif action in ("delete", "remove") and len(args) >= 3:
            self.service.delete_role(sender, args[2])
        elif action == "setcolor" and len(args) >= 3:
            if len(args) >= 4:
                self.service.set_role_color(sender, args[2], args[3])
            else:
                uuid_str, player_name = get_sender_uuid_and_name(sender)
                city = self.state.get_city_by_player(uuid_str) if uuid_str else None
                if city:
                    self.service.set_role_color(sender, self.service.get_primary_role(city, uuid_str), args[2])
                else:
                    self.send_role_help(sender)
        elif action == "give" and len(args) >= 4:
            self.service.give_role(sender, args[2], args[3])
        elif action == "take" and len(args) >= 4:
            self.service.take_role(sender, args[2], args[3])
        else:
            self.send_role_help(sender)

    def execute_admin(self, sender, label, args):
        if not is_admin(sender):
            send_message(sender, CitiesConfig.PREFIX + u"&cКоманда доступна только администраторам.")
            return True
        args = list(args)
        sub = args[0].lower() if args else "menu"
        if sub in ("menu", "gui"):
            if not hasattr(sender, "openInventory"):
                send_message(sender, CitiesConfig.PREFIX + u"&cТолько игрок может открыть GUI.")
                return True
            AdminMainGUI(sender).open()
        elif sub == "reload":
            self.state.reload()
            send_message(sender, CitiesConfig.PREFIX + u"&aДанные городов перезагружены.")
        elif sub == "delete" and len(args) >= 2:
            city = self.state.get_city(args[1])
            if not city:
                send_message(sender, CitiesConfig.PREFIX + u"&cГород не найден.")
            else:
                name = city.get("name")
                if get_city_companies(name):
                    send_message(sender, CitiesConfig.PREFIX + u"&cСначала закройте все предприятия этого города.")
                elif self.state.delete_city(city):
                    send_message(sender, CitiesConfig.PREFIX + u"&cГород &e{0}&c удален.".format(name))
                else:
                    send_message(sender, CitiesConfig.PREFIX + u"&cГород не удален: данные не удалось сохранить.")
        elif sub == "setmayor" and len(args) >= 3:
            self.admin_set_mayor(sender, args[1], args[2])
        elif sub == "treasury" and len(args) >= 4:
            self.admin_treasury(sender, args[1], args[2], args[3])
        else:
            self.send_admin_help(sender, label)
        return True

    def execute_menu(self, sender, label, args):
        if not hasattr(sender, "openInventory"):
            send_message(sender, CitiesConfig.PREFIX + u"&cТолько игрок может открыть меню.")
            return True
        TownMainGUI(sender).open()
        return True

    def safe_amount(self, sender, raw):
        try:
            return parse_amount(raw)
        except Exception:
            send_message(sender, CitiesConfig.PREFIX + u"&cНекорректная сумма.")
            return 0.0

    def safe_positive_int(self, sender, raw, label=u"Число", maximum=2147483647):
        try:
            text = to_unicode(raw).strip()
            value = float(text.replace(",", "."))
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError()
            integer = int(value)
            if value != float(integer) or integer <= 0 or integer > int(maximum):
                raise ValueError()
            return integer
        except Exception:
            send_message(sender, CitiesConfig.PREFIX + u"&c%s должно быть целым положительным числом." % label)
            return None

    def safe_percent(self, sender, raw):
        try:
            value = float(to_unicode(raw).replace(",", "."))
            if value != value or value in (float("inf"), float("-inf")) or value < 0 or value > 100:
                raise ValueError()
            return round(value, 2)
        except Exception:
            send_message(sender, CitiesConfig.PREFIX + u"&cНалог должен быть от 0 до 100%.")
            return None

    def parse_page(self, raw):
        try:
            return max(1, int(raw))
        except Exception:
            return 1

    def send_city_list(self, sender, page):
        cities = self.state.list_cities()
        if not cities:
            send_message(sender, CitiesConfig.PREFIX + u"&7Городов пока нет. Создать: &e/town create <название>&7.")
            return
        page_size = CitiesConfig.LIST_PAGE_SIZE
        total_pages = max(1, int((len(cities) + page_size - 1) / page_size))
        page = min(max(1, page), total_pages)
        chunk = cities[(page - 1) * page_size:page * page_size]
        send_message(sender, CitiesConfig.PREFIX + u"&bСписок городов &7(страница &e{0}&7/&e{1}&7)".format(page, total_pages))
        for city in chunk:
            send_message(sender, u"&8- &e{0} &7| мэр: &f{1} &7| жителей: &a{2} &7| казна: &6{3}".format(
                city.get("name"),
                city.get("mayor_name"),
                len(city.get("members", {})),
                format_currency(city.get("treasury", 0.0))
            ))

    def send_city_info(self, sender, city_name):
        city = self.resolve_city_for_view(sender, city_name)
        if not city:
            return
        role_groups = self.service.group_members_by_role(city)
        member_count = len(city.get("members", {}))
        total_balance = self.service.get_members_balance_total(city)
        companies_count, companies_capital = self.service.get_companies_summary(city)
        color_name = city.get("color", "white")
        send_message(sender, u"&9&m----------&r &b&l{0} &9&m----------".format(city.get("name")))
        send_message(sender, u"&7Мэр: &6{0}".format(city.get("mayor_name")))
        send_message(sender, u"&7Жителей: &a{0} &8| &7Цвет города: &f{1}".format(member_count, color_name))
        send_message(sender, u"&7Казна города: &6{0}".format(format_currency(city.get("treasury", 0.0))))
        send_message(sender, u"&7Сумма балансов жителей: &e{0}".format(format_currency(total_balance)))
        send_message(sender, u"&7Предприятия: &b{0} &8| &7Общий капитал предприятий: &6{1}".format(companies_count, format_currency(companies_capital)))
        self.send_tax_lines(sender, city)
        send_message(sender, u"&7Дополнительные роли:")
        role_order = sorted([role for role in role_groups.keys() if role not in ("mayor", "citizen")])
        printed_roles = 0
        for role_key in role_order:
            names = sorted(role_groups.get(role_key, []), key=lambda item: to_unicode(item).lower())
            if not names:
                continue
            role_display = self.service.get_role_display(city, role_key)
            role_color = self.service.get_role_color_prefix(city, role_key)
            send_message(sender, u"&8- {0}{1}&7: &f{2}".format(role_color, role_display, u", ".join([to_unicode(name) for name in names])))
            printed_roles += 1
        if printed_roles == 0:
            send_message(sender, u"&8- &7Нет назначенных дополнительных ролей.")
        send_message(sender, u"&9&m--------------------------------")

    def send_members(self, sender, city_name):
        city = self.resolve_city_for_view(sender, city_name)
        if not city:
            return
        members = sorted(city.get("members", {}).values(), key=lambda item: to_unicode(item).lower())
        send_message(sender, CitiesConfig.PREFIX + u"&7Жители города &e{0}&7: &f{1}".format(
            city.get("name"),
            u", ".join([to_unicode(name) for name in members]) or u"нет"
        ))

    def send_companies(self, sender, city_name):
        city = self.resolve_city_for_view(sender, city_name)
        if not city:
            return
        companies = get_city_companies(city.get("name"))
        send_message(sender, CitiesConfig.PREFIX + u"&bПредприятия города &e{0}&7: &a{1}".format(city.get("name"), len(companies)))
        if not companies:
            send_message(sender, u"&8- &7Предприятий пока нет.")
            return
        for company in companies:
            send_message(sender, u"&8- &b{0} &7| владелец: &f{1} &7| акции: &a{2} &7| капитал: &6{3}".format(
                company.get("name"),
                company.get("owner_name"),
                format_currency(get_company_share_price(company)),
                format_currency(get_company_capitalization(company))
            ))

    def send_tax_info(self, sender):
        city = self.service.require_own_city(sender)
        if not city:
            return
        send_message(sender, CitiesConfig.PREFIX + u"&bНалоги города &e{0}&7:".format(city.get("name")))
        self.send_tax_lines(sender, city)
        send_message(sender, u"&7Изменить: &e/town tax set <тип> <процент>")

    def send_tax_lines(self, sender, city):
        taxes = city.get("taxes", {})
        parts = []
        for key in ["companies", "primary", "resale", "dividends"]:
            parts.append(u"&7{0}: &e{1}%".format(CitiesConfig.TAX_TYPES.get(key, key), taxes.get(key, CitiesConfig.DEFAULT_COMPANY_TAX_PERCENT)))
        send_message(sender, u"&7Налоги предприятий: " + u" &8| ".join(parts))

    def send_role_list(self, sender):
        city = self.service.require_own_city(sender)
        if not city:
            return
        roles = []
        for role in sorted(city.get("roles", {}).keys()):
            role_color = self.service.get_role_color_prefix(city, role)
            roles.append(role_color + self.service.get_role_display(city, role))
        send_message(sender, CitiesConfig.PREFIX + u"&7Роли города &e{0}&7: &f{1}".format(
            city.get("name"),
            u", ".join([to_unicode(role) for role in roles]) or u"нет"
        ))

    def resolve_city_for_view(self, sender, city_name):
        if city_name:
            city = self.state.get_city(city_name)
            if not city:
                send_message(sender, CitiesConfig.PREFIX + u"&cГород &e{0}&c не найден.".format(city_name))
            return city
        uuid_str, name = get_sender_uuid_and_name(sender)
        city = self.state.get_city_by_player(uuid_str) if uuid_str else None
        if not city:
            send_message(sender, CitiesConfig.PREFIX + u"&cУкажите город: &e/town info <город>&c.")
        return city

    def admin_set_mayor(self, sender, city_name, player_name):
        city = self.state.get_city(city_name)
        account = self.service.resolve_player(player_name)
        if not city or not account:
            send_message(sender, CitiesConfig.PREFIX + u"&cГород или игрок не найден.")
            return
        self.state.set_mayor(city, account.uuid, account.name)
        send_message(sender, CitiesConfig.PREFIX + u"&aМэр города &e{0}&a: &e{1}&a.".format(city.get("name"), account.name))

    def admin_treasury(self, sender, city_name, action, raw_amount):
        city = self.state.get_city(city_name)
        if not city:
            send_message(sender, CitiesConfig.PREFIX + u"&cГород не найден.")
            return
        amount = self.safe_amount(sender, raw_amount)
        if amount <= 0:
            return
        action = action.lower()
        total = None
        if action == "set":
            total = self.state.set_treasury(city, amount, actor_name=u"ADMIN")
        elif action == "add":
            total = self.state.change_treasury(city, amount, actor_name=u"ADMIN")
        elif action in ("take", "remove"):
            total = self.state.change_treasury(city, -amount, actor_name=u"ADMIN")
        else:
            self.send_admin_help(sender, "townadmin")
            return
        if total is None:
            send_message(sender, CitiesConfig.PREFIX + u"&cКазну не удалось изменить. Недостаточно средств или ошибка сохранения.")
            return
        send_message(sender, CitiesConfig.PREFIX + u"&aКазна города &e{0}&a: &6{1}&a.".format(
            city.get("name"),
            format_currency(city.get("treasury", 0.0))
        ))

    def send_help(self, sender, label):
        send_message(sender, CitiesConfig.PREFIX + u"&e/town create <название> &7- создать город")
        send_message(sender, u"&e/town list &7- список городов")
        send_message(sender, u"&e/town info [город] &7- информация")
        send_message(sender, u"&e/town members [город] &7- жители")
        send_message(sender, u"&e/town companies [город] &7- предприятия города")
        send_message(sender, u"&e/town project list/create/addreq... &7- свои проекты")
        send_message(sender, u"&e/town add/remove <игрок> &7- жители, только мэр")
        send_message(sender, u"&e/town mayor <игрок> &7- передать пост мэра")
        send_message(sender, u"&e/town role <list|create|delete|give|take|setcolor> &7- роли")
        send_message(sender, u"&e/town color set <цвет> &7- цвет ников города")
        send_message(sender, u"&e/town tax <info|set> &7- налоги предприятий")
        send_message(sender, u"&e/town rename <название> &7- переименовать город")
        send_message(sender, u"&e/town deposit <сумма> &7- пополнить казну")
        send_message(sender, u"&e/town withdraw <сумма> &7- снять из казны, только мэр")
        send_message(sender, u"&e/town home &7- телепорт в дом города (КД 45 мин)")
        send_message(sender, u"&e/town sethome &7- задать дом города здесь (только мэр)")
        send_message(sender, u"&e/town tp <on|off> &7- вкл/выкл телепорты к вам (ваши телепорты к другим тоже отключатся)")

    def send_role_help(self, sender):
        send_message(sender, CitiesConfig.PREFIX + u"&e/town role list")
        send_message(sender, u"&e/town role create <роль>")
        send_message(sender, u"&e/town role delete <роль>")
        send_message(sender, u"&e/town role setcolor <роль> <цвет>")
        send_message(sender, u"&e/town role give <игрок> <роль>")
        send_message(sender, u"&e/town role take <игрок> <роль>")

    def send_tax_help(self, sender):
        send_message(sender, CitiesConfig.PREFIX + u"&e/town tax info")
        send_message(sender, u"&e/town tax set <процент> &7- общий налог предприятий")
        send_message(sender, u"&e/town tax set <primary|resale|dividends|tradehall|companies> <процент>")

    def send_admin_help(self, sender, label):
        send_message(sender, CitiesConfig.PREFIX + u"&e/townadmin menu &7- открыть Административное GUI")
        send_message(sender, u"&e/townadmin reload")
        send_message(sender, u"&e/townadmin delete <город>")
        send_message(sender, u"&e/townadmin setmayor <город> <игрок>")
        send_message(sender, u"&e/townadmin treasury <город> <set|add|take> <сумма>")

    def tab_city(self, sender, alias, args):
        args = list(args)
        if len(args) <= 1:
            prefix = args[0].lower() if args else ""
            return build_java_list([sub for sub in self.SUBCOMMANDS if sub.startswith(prefix)])
        sub = args[0].lower()
        if len(args) == 2 and sub in ("info", "members", "companies"):
            return self.tab_city_names(args[1])
        if len(args) == 2 and sub in ("add", "remove", "mayor"):
            return self.tab_player_names(args[1])
        if len(args) == 2 and sub in ("deposit", "withdraw"):
            return build_java_list(["100", "500", "1000", "5000", "10000"])
        if len(args) == 2 and sub == "tp":
            prefix = args[1].lower()
            return build_java_list([item for item in ["on", "off"] if item.startswith(prefix)])
        if len(args) == 2 and sub == "color":
            prefix = args[1].lower()
            return build_java_list([item for item in ["set"] if item.startswith(prefix)])
        if len(args) == 3 and sub == "color" and args[1].lower() == "set":
            prefix = args[2].lower()
            return build_java_list([color for color in sorted(CitiesConfig.COLORS.keys()) if color.startswith(prefix)])
        if len(args) == 2 and sub == "tax":
            prefix = args[1].lower()
            return build_java_list([item for item in ["info", "set"] if item.startswith(prefix)])
        if len(args) == 3 and sub == "tax" and args[1].lower() == "set":
            prefix = args[2].lower()
            values = ["companies", "primary", "resale", "dividends", "tradehall", "0", "1", "2", "5", "10"]
            return build_java_list([item for item in values if item.startswith(prefix)])
        if len(args) == 4 and sub == "tax" and args[1].lower() == "set":
            return build_java_list(["0", "1", "2", "5", "10"])
        if len(args) == 2 and sub == "role":
            prefix = args[1].lower()
            return build_java_list([item for item in ["list", "create", "delete", "give", "take", "setcolor"] if item.startswith(prefix)])
        if len(args) == 3 and sub == "role" and args[1].lower() in ("give", "take"):
            return self.tab_player_names(args[2])
        if len(args) == 4 and sub == "role" and args[1].lower() in ("give", "take"):
            return self.tab_own_city_roles(sender, args[3])
        if len(args) == 3 and sub == "role" and args[1].lower() == "delete":
            return self.tab_own_city_roles(sender, args[2])
        if len(args) == 3 and sub == "role" and args[1].lower() == "setcolor":
            role_matches = self.tab_own_city_roles(sender, args[2])
            color_matches = [color for color in sorted(CitiesConfig.COLORS.keys()) if color.startswith(args[2].lower())]
            if color_matches:
                return build_java_list(color_matches)
            return role_matches
        if len(args) == 4 and sub == "role" and args[1].lower() == "setcolor":
            prefix = args[3].lower()
            return build_java_list([color for color in sorted(CitiesConfig.COLORS.keys()) if color.startswith(prefix)])
        if len(args) == 2 and sub in ("project", "proj"):
            prefix = args[1].lower()
            return build_java_list([item for item in ["list", "create", "desc", "reqmoney", "addreq", "addhand", "duration", "start", "delete"] if item.startswith(prefix)])
        return build_java_list([])

    def tab_admin(self, sender, alias, args):
        args = list(args)
        if len(args) <= 1:
            prefix = args[0].lower() if args else ""
            return build_java_list([sub for sub in self.ADMIN_SUBCOMMANDS if sub.startswith(prefix)])
        sub = args[0].lower()
        if len(args) == 2 and sub in ("delete", "setmayor", "treasury"):
            return self.tab_city_names(args[1])
        if len(args) == 3 and sub == "setmayor":
            return self.tab_player_names(args[2])
        if len(args) == 3 and sub == "treasury":
            prefix = args[2].lower()
            return build_java_list([item for item in ["set", "add", "take"] if item.startswith(prefix)])
        if len(args) == 4 and sub == "treasury":
            return build_java_list(["1000", "5000", "10000"])
        return build_java_list([])

    def tab_city_names(self, prefix):
        prefix = to_unicode(prefix).lower()
        return build_java_list([city.get("name") for city in self.state.list_cities() if to_unicode(city.get("name")).lower().startswith(prefix)])

    def tab_player_names(self, prefix):
        prefix = to_unicode(prefix).lower()
        return build_java_list([name for name in self.economy.get_online_names() if to_unicode(name).lower().startswith(prefix)][:20])

    def tab_own_city_roles(self, sender, prefix):
        uuid_str, name = get_sender_uuid_and_name(sender)
        city = self.state.get_city_by_player(uuid_str) if uuid_str else None
        if not city:
            return build_java_list([])
        prefix = to_unicode(prefix).lower()
        return build_java_list([role for role in sorted(city.get("roles", {}).keys()) if role.startswith(prefix)])


if BUKKIT_AVAILABLE:
    class PyBukkitCommand(Command, TabCompleter):
        def __init__(self, name, description, usage, aliases, executor, completer):
            Command.__init__(self, name, description, usage, aliases)
            self.executor = executor
            self.completer = completer

        def execute(self, sender, command_label, args):
            try:
                return self.executor(sender, command_label, list(args))
            except Exception as exc:
                log_info(u"Command error: {0}".format(exc))
                return True

        def tabComplete(self, *args):
            try:
                if self.completer and len(args) >= 3:
                    result = self.completer(args[0], args[1], args[2])
                    if result is not None:
                        return result
            except Exception:
                pass
            return build_java_list([])

        def onTabComplete(self, *args):
            return self.tabComplete(*args)
else:
    class PyBukkitCommand(object):
        def __init__(self, name, description, usage, aliases, executor, completer):
            self.name = name


registered_listeners = []
TOWN_STATE_PROPERTY = "SmartY_TownState"
state = None
economy = None
service = None
command_handler = None
initialized = False


def publish_town_state(manager):
    if JAVA_STRING_AVAILABLE and System is not None:
        try:
            if manager is None:
                current = System.getProperties().get(TOWN_STATE_PROPERTY)
                if current is state:
                    System.getProperties().remove(TOWN_STATE_PROPERTY)
            else:
                System.getProperties().put(TOWN_STATE_PROPERTY, manager)
        except Exception:
            pass


def force_register_bukkit_command(fallback_prefix, cmd_obj, aliases):
    if not BUKKIT_AVAILABLE:
        return
    try:
        server = Bukkit.getServer()
        command_map = server.getCommandMap() if hasattr(server, "getCommandMap") else None
        if command_map is None:
            field = server.getClass().getDeclaredField("commandMap")
            field.setAccessible(True)
            command_map = field.get(server)
        known_commands = None
        if hasattr(command_map, "getKnownCommands"):
            try:
                known_commands = command_map.getKnownCommands()
            except Exception:
                pass
        if known_commands is None:
            current_class = command_map.getClass()
            while current_class is not None and known_commands is None:
                try:
                    field = current_class.getDeclaredField("knownCommands")
                    field.setAccessible(True)
                    known_commands = field.get(command_map)
                except Exception:
                    current_class = current_class.getSuperclass()
        if known_commands is None:
            log_info(u"Cannot access Bukkit knownCommands map.")
            return
        names = [cmd_obj.getName()] + list(aliases)
        for name in names:
            lowered = str(name).lower()
            for key in [lowered, fallback_prefix + ":" + lowered]:
                try:
                    old_command = known_commands.get(key)
                    if old_command is not None and hasattr(old_command, "unregister"):
                        old_command.unregister(command_map)
                    known_commands.remove(key)
                except Exception:
                    pass
        known_commands.put(cmd_obj.getName().lower(), cmd_obj)
        known_commands.put(fallback_prefix + ":" + cmd_obj.getName().lower(), cmd_obj)
        for alias in aliases:
            alias_command = PyBukkitCommand(
                alias, cmd_obj.getDescription(), cmd_obj.getUsage(), [], cmd_obj.executor, cmd_obj.completer
            )
            known_commands.put(str(alias).lower(), alias_command)
            known_commands.put(fallback_prefix + ":" + str(alias).lower(), alias_command)
    except Exception as exc:
        log_info(u"Command registration error: {0}".format(exc))


def register_event(event_class, handler):
    if not BUKKIT_AVAILABLE or event_class is None:
        return False
    plugin = get_pyspigot_plugin()
    if not plugin:
        return False

    class DirectListener(Listener):
        pass

    class DirectExecutor(EventExecutor):
        def execute(self, listener, event):
            try:
                handler(event)
            except Exception as exc:
                log_info(u"Event error: {0}".format(exc))

    listener = DirectListener()
    Bukkit.getPluginManager().registerEvent(
        event_class, listener, EventPriority.HIGHEST, DirectExecutor(), plugin
    )
    registered_listeners.append(listener)
    return True


def unregister_events():
    if HandlerList is None:
        return
    for listener in list(registered_listeners):
        try:
            HandlerList.unregisterAll(listener)
        except Exception:
            pass
    del registered_listeners[:]


def on_inventory_click(event):
    try:
        view = event.getView()
        top_inv = view.getTopInventory() if view else None
        if top_inv is None:
            return
        holder = top_inv.getHolder()
        if holder is None or not isinstance(holder, TownInventoryHolder):
            return
        event.setCancelled(True)
        raw_slot = event.getRawSlot()
        if raw_slot < 0 or raw_slot >= top_inv.getSize():
            player = event.getWhoClicked()
            clicked_inv = event.getClickedInventory()
            # --- Клик в НИЖНИЙ инвентарь (Player.getInventory()). ---
            if clicked_inv == player.getInventory():
                item = event.getCurrentItem()
                # AdminQuestEditGUI: режим смены предмета — берём кликнутый предмет как цель квеста.
                if isinstance(holder.gui, AdminQuestEditGUI):
                    holder.gui.handle_bottom_click(player, item)
                    return
                # TownProjectManageGUI: быстрое добавление требования (существующая логика).
                if isinstance(holder.gui, TownProjectManageGUI):
                    if item and item.getType() != Material.AIR:
                        mat_name = str(item.getType().name())
                        click_type = str(event.getClick()) if hasattr(event, "getClick") else "LEFT"
                        count = 512 if event.isShiftClick() else (16 if click_type in ("RIGHT", "RIGHT_CLICK") else 64)
                        city = state.get_city_by_player(uid(player))
                        if city and holder.gui.project_id in city.get("custom_projects", {}):
                            pdata = city["custom_projects"][holder.gui.project_id]
                            pdata.setdefault("req_items", {})[mat_name] = pdata.get("req_items", {}).get(mat_name, 0) + count
                            pdata["icon"] = mat_name
                            state.save()
                            send_message(player, CitiesConfig.PREFIX + u"&aДобавлено требование из инвентаря: &f%s x%d" % (mat_name, pdata["req_items"][mat_name]))
                            holder.gui.open()
            return

        player = event.getWhoClicked()
        click_type = str(event.getClick()) if hasattr(event, "getClick") else "LEFT"
        holder.gui.handle_click(player, raw_slot, click_type, event.isShiftClick())
    except Exception as exc:
        log_info(u"Inventory click error: {0}".format(exc))


def on_inventory_drag(event):
    try:
        top_inv = event.getView().getTopInventory()
        holder = top_inv.getHolder() if top_inv else None
        if holder is not None and isinstance(holder, TownInventoryHolder):
            event.setCancelled(True)
    except Exception:
        pass


def on_player_join(event):
    try:
        if service is not None:
            for player in Bukkit.getOnlinePlayers():
                service.apply_player_color(player)
    except Exception:
        pass


def on_player_quit(event):
    try:
        if service is not None:
            service.remove_politic_team(event.getPlayer())
    except Exception:
        pass


def on_player_chat(event):
    try:
        if service is None:
            return
        player = event.getPlayer()
        uuid_str, name = get_sender_uuid_and_name(player)
        u_str = uid(player)

        # ---- Перехват ввода для проектов города (кол-во/сумма/срок) ----
        if u_str in pending_project_inputs:
            raw = to_unicode(event.getMessage() or u"").strip()
            event.setCancelled(True)
            req = pending_project_inputs.pop(u_str, None)
            if req is None:
                return
            if raw.lower() in (u"отмена", u"cancel", u"exit", u"-"):
                send_message(player, CitiesConfig.PREFIX + u"&7Ввод отменён.")
                _reopen_project_gui(player, req)
                return

            kind = req.get("kind")
            # --- Строковый ввод (название квеста). ---
            if kind == "quest_title":
                _apply_project_input_scheduled(player, req, raw)
                return

            # --- Числовой ввод. ---
            try:
                value = float(raw.replace(",", "."))
            except Exception:
                send_message(player, CitiesConfig.PREFIX + u"&cНеверное число: §f" + raw)
                _reopen_project_gui(player, req)
                return
            if value != value or value in (float("inf"), float("-inf")):
                send_message(player, CitiesConfig.PREFIX + u"&cНужно ввести обычное конечное число.")
                _reopen_project_gui(player, req)
                return
            if value <= 0 and kind not in ("quest_reward",):
                # Для награды разрешаем 0 (бесплатный квест).
                send_message(player, CitiesConfig.PREFIX + u"&cЧисло должно быть больше нуля.")
                _reopen_project_gui(player, req)
                return
            if value < 0:
                send_message(player, CitiesConfig.PREFIX + u"&cЧисло не может быть отрицательным.")
                _reopen_project_gui(player, req)
                return
            integer_kinds = (
                "quest_count", "deposit_items", "withdraw_items",
                "set_duration_h", "add_req_item",
            )
            if kind in integer_kinds and value != float(int(value)):
                send_message(player, CitiesConfig.PREFIX + u"&cДля этого поля требуется целое число.")
                _reopen_project_gui(player, req)
                return
            if kind == "set_duration_h" and value > 100000:
                send_message(player, CitiesConfig.PREFIX + u"&cСрок не может превышать 100000 часов.")
                _reopen_project_gui(player, req)
                return
            if kind in ("quest_count", "deposit_items", "withdraw_items", "add_req_item") \
                    and value > 2147483647:
                send_message(player, CitiesConfig.PREFIX + u"&cВведённое количество слишком велико.")
                _reopen_project_gui(player, req)
                return
            _apply_project_input_scheduled(player, req, value)
            return

        city = service.state.get_city_by_player(uuid_str)
        if not city:
            return
        # Роли в общем чате НЕ отображаем — только цветной ник в цвете города.
        town_color = CitiesConfig.COLORS.get(city.get("color", "white"), CitiesConfig.COLORS["white"])[1]
        chat_prefix = colorize(town_color + name + u"&f")
        event.setFormat(to_java_string(chat_prefix + u": %2$s"))
    except Exception as exc:
        log_info(u"Chat format error: {0}".format(exc))


def _reopen_project_gui(player, req):
    """Возвращает игрока в исходное меню (details / resource / manage / quest_edit)."""
    def _run():
        try:
            rgui = req.get("return_gui", "details")
            pid = req.get("project_id")
            if rgui == "resource":
                TownProjectResourceGUI(player, pid, req.get("mat_name")).open()
            elif rgui == "manage":
                TownProjectManageGUI(player, pid).open()
            elif rgui == "quest_edit":
                AdminQuestEditGUI(player, qid=req.get("qid")).open()
            else:
                TownProjectDetailsGUI(player, pid).open()
        except Exception as exc:
            log_info(u"Cannot reopen project GUI: {0}".format(exc))
    run_on_main_thread(_run)


def _apply_project_input_scheduled(player, req, value):
    """Применяет распарсенное значение к проекту/квесту в основном потоке."""
    def _run():
        try:
            uuid_str, name = get_sender_uuid_and_name(player)
            kind = req.get("kind")

            # ================= КВЕСТЫ =================
            if kind in ("quest_title", "quest_count", "quest_reward"):
                qid = req.get("qid")
                # Определяем, куда пишем: черновик (qid=None) или в state.
                if qid is None:
                    u_str = uid(player)
                    qdata = AdminQuestEditGUI._drafts.setdefault(u_str, {
                        "title": u"Новый квест",
                        "material": "STONE",
                        "required_count": 64,
                        "reward_money": 5000.0,
                    })
                else:
                    qdata = state.data.setdefault("custom_quests", {}).get(qid)
                    if qdata is None:
                        send_message(player, CitiesConfig.PREFIX + u"&cКвест не найден.")
                        return

                if kind == "quest_title":
                    new_title = to_unicode(value).strip()
                    if not new_title:
                        send_message(player, CitiesConfig.PREFIX + u"&cПустое название.")
                    else:
                        qdata["title"] = new_title
                        state.save()
                        send_message(player, CitiesConfig.PREFIX + u"&aНазвание установлено: &f" + new_title)
                elif kind == "quest_count":
                    n = max(1, int(value))
                    qdata["required_count"] = n
                    state.save()
                    send_message(player, CitiesConfig.PREFIX + u"&aКоличество: &e%d шт." % n)
                elif kind == "quest_reward":
                    n = max(0.0, float(value))
                    qdata["reward_money"] = n
                    state.save()
                    send_message(player, CitiesConfig.PREFIX + u"&aНаграда: &6" + format_currency(n))
                AdminQuestEditGUI(player, qid=qid).open()
                return

            # ================= ПРОЕКТЫ =================
            city = state.get_city_by_player(uuid_str)
            if not city:
                return
            pid = req.get("project_id")
            pdata = city.get("custom_projects", {}).get(pid)
            if not pdata:
                send_message(player, CitiesConfig.PREFIX + u"&cПроект не найден.")
                return
            n_int = int(value)

            if kind == "deposit_money":
                gui = TownProjectDetailsGUI(player, pid)
                gui._deposit_money(player, city, pdata, value)
                return
            if kind == "withdraw_money":
                gui = TownProjectDetailsGUI(player, pid)
                gui._withdraw_money(player, city, pdata, value)
                return
            if kind == "deposit_items":
                gui = TownProjectResourceGUI(player, pid, req.get("mat_name"))
                gui._do_deposit_items(player, city, pdata, n_int)
                return
            if kind == "withdraw_items":
                gui = TownProjectResourceGUI(player, pid, req.get("mat_name"))
                gui._do_withdraw_items(player, city, pdata, n_int)
                return
            if kind == "set_budget":
                pdata["req_money"] = max(0.0, value)
                state.save()
                send_message(player, CitiesConfig.PREFIX + u"&aБюджет проекта установлен: &f" + format_currency(value))
                TownProjectManageGUI(player, pid).open()
                return
            if kind == "set_duration_h":
                old_duration = pdata.get("duration_sec")
                pdata["duration_sec"] = max(3600, n_int * 3600)
                if not state.save():
                    if old_duration is None:
                        pdata.pop("duration_sec", None)
                    else:
                        pdata["duration_sec"] = old_duration
                    send_message(player, CitiesConfig.PREFIX + u"&cНе удалось сохранить срок проекта. Значение не изменено.")
                    TownProjectManageGUI(player, pid).open()
                    return
                send_message(player, CitiesConfig.PREFIX + u"&aДлительность установлена: &f%d ч." % n_int)
                TownProjectManageGUI(player, pid).open()
                return
            if kind == "add_req_item":
                mat_name = req.get("mat_name")
                pdata.setdefault("req_items", {})[mat_name] = pdata.get("req_items", {}).get(mat_name, 0) + n_int
                pdata["icon"] = mat_name
                state.save()
                send_message(player, CitiesConfig.PREFIX + u"&aДобавлено требование: &f%s x%d" % (mat_name, pdata["req_items"][mat_name]))
                TownProjectManageGUI(player, pid).open()
                return
        except Exception as exc:
            log_info(u"apply_project_input: {0}".format(exc))

    if not run_on_main_thread(_run):
        send_message(player, CitiesConfig.PREFIX + u"&cНе удалось применить значение: планировщик сервера недоступен.")


def on_entity_death(event):
    try:
        if service is None:
            return
        entity = event.getEntity()
        killer = entity.getKiller()
        if killer is None:
            return
        uuid_str, name = get_sender_uuid_and_name(killer)
        city = service.state.get_city_by_player(uuid_str)
        if not city:
            return
        q_mobs = city.setdefault("quest_progress", {}).get("mobs", 0)
        if q_mobs < 25:
            city_snapshot = copy.deepcopy(city)
            city["quest_progress"]["mobs"] = q_mobs + 1
            completed = city["quest_progress"]["mobs"] == 25
            if completed:
                service.state.add_treasury_log(city, u"§a§lКвест «Охота на чудовищ» выполнен!")
                city["treasury"] = city.get("treasury", 0.0) + 2500.0
            if not service.state.save():
                city.clear()
                city.update(city_snapshot)
                log_info(u"Mob quest progress was rolled back for {0}: cities data is not writable".format(name))
                return
            if completed:
                send_message(killer, CitiesConfig.PREFIX + u"&a&lКвест «Охота на чудовищ» выполнен! +2500$ в казну.")
    except Exception as exc:
        log_info(u"Entity death error: {0}".format(exc))


# ФИКС бага с /pyspigot unload: команды выше инжектируются напрямую в CommandMap через
# рефлексию (force_register_bukkit_command) — это невидимо для собственного
# трекера PySpigot, поэтому без явного снятия команды /town /townadmin /townmenu
# и их алиасы продолжали бы работать даже после /pyspigot unload cities.
registered_city_command_names = []


def force_unregister_bukkit_command(fallback_prefix, name):
    u"""Снимает одну команду/алиас из Bukkit CommandMap вместе с префикс-версией (plugin:name)."""
    if not BUKKIT_AVAILABLE:
        return
    try:
        server = Bukkit.getServer()
        command_map = server.getCommandMap() if hasattr(server, "getCommandMap") else None
        if command_map is None:
            field = server.getClass().getDeclaredField("commandMap")
            field.setAccessible(True)
            command_map = field.get(server)
        known_commands = None
        if hasattr(command_map, "getKnownCommands"):
            try:
                known_commands = command_map.getKnownCommands()
            except Exception:
                pass
        if known_commands is None:
            current_class = command_map.getClass()
            while current_class is not None and known_commands is None:
                try:
                    field = current_class.getDeclaredField("knownCommands")
                    field.setAccessible(True)
                    known_commands = field.get(command_map)
                except Exception:
                    current_class = current_class.getSuperclass()
        if known_commands is None:
            return
        lowered = str(name).lower()
        for key in [lowered, fallback_prefix + ":" + lowered]:
            try:
                old_command = known_commands.get(key)
                if old_command is not None and hasattr(old_command, "unregister"):
                    old_command.unregister(command_map)
                known_commands.remove(key)
            except Exception:
                pass
    except Exception as exc:
        log_info(u"Command unregistration error: {0}".format(exc))


def unregister_city_commands():
    for name in list(registered_city_command_names):
        force_unregister_bukkit_command("smarty-cities", name)
    del registered_city_command_names[:]


def register_commands():
    unregister_city_commands()
    commands = [
        ("town", "Town politics system", "/town <help|create|list|info|members|add|remove|mayor|deposit|withdraw>", ["city", "cities"], command_handler.execute_city, command_handler.tab_city),
        ("townadmin", "Admin town tools", "/townadmin <menu|gui|reload|delete|setmayor|treasury>", ["cityadmin", "ta"], command_handler.execute_admin, command_handler.tab_admin),
        ("townmenu", "Open town menu", "/townmenu", ["tm"], command_handler.execute_menu, None)
    ]
    for item in commands:
        command = PyBukkitCommand(item[0], item[1], item[2], item[3], item[4], item[5])
        force_register_bukkit_command("smarty-cities", command, item[3])
        registered_city_command_names.append(item[0])
        for alias in item[3]:
            registered_city_command_names.append(alias)
    try:
        if BUKKIT_AVAILABLE and hasattr(Bukkit.getServer(), "syncCommands"):
            Bukkit.getServer().syncCommands()
    except Exception as exc:
        log_info(u"Command synchronization error: {0}".format(exc))


def on_enable():
    global state, economy, service, command_handler, initialized
    if initialized:
        return
    log_info(u"Starting {0} v{1}".format(CitiesConfig.PLUGIN_NAME, CitiesConfig.VERSION))
    storage = JsonStorage(CitiesConfig.DATA_FILE, CitiesConfig.DEFAULT_STATE)
    state = CityState(storage)
    if not storage.loaded_ok:
        raise RuntimeError("cities.json is damaged and no valid backup is available")
    if not state.save():
        raise RuntimeError("cities.json is not writable")
    economy = EconomyGateway()
    service = CityService(state, economy)
    command_handler = CityCommand(service, state, economy)
    unregister_events()
    register_event(InventoryClickEvent, on_inventory_click)
    register_event(InventoryDragEvent, on_inventory_drag)
    register_event(PlayerJoinEvent, on_player_join)
    register_event(PlayerQuitEvent, on_player_quit)
    register_event(AsyncPlayerChatEvent, on_player_chat)
    if EntityDeathEvent is not None:
        register_event(EntityDeathEvent, on_entity_death)
    register_commands()
    if BUKKIT_AVAILABLE:
        for player in Bukkit.getOnlinePlayers():
            service.apply_player_color(player)
    initialized = True
    publish_town_state(state)
    log_info(u"Enabled.")


def on_disable():
    global initialized
    publish_town_state(None)
    unregister_events()
    unregister_city_commands()  # ФИКС: без этого /town /townadmin /townmenu переживали /pyspigot unload
    if state is not None:
        state.save()
    initialized = False
    log_info(u"Disabled.")


def start(script=None):
    on_enable()


def stop(script=None):
    on_disable()


if __name__ == "__main__" or "ps" in globals() or "command_manager" in globals():
    on_enable()

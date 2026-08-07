# -*- coding: utf-8 -*-
"""
SmartY Companies for PySpigot / Paper 1.21.

Commands:
  /companies
  /company [help|create|open|buy|deposit|withdraw|dividends|rename|description|delete]
  /shares [list|give|sell|accept|deny]
"""

import copy
import json
import os
import re
import shutil
import sys
import threading
import time

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
    from org.bukkit import Bukkit, ChatColor, Material
    from org.bukkit.command import Command, TabCompleter
    from org.bukkit.event import EventPriority, HandlerList, Listener
    from org.bukkit.event.inventory import InventoryClickEvent, InventoryDragEvent
    from org.bukkit.event.player import PlayerQuitEvent
    from org.bukkit.inventory import InventoryHolder, ItemStack
    from org.bukkit.plugin import EventExecutor
    BUKKIT_AVAILABLE = True
    try:
        from org.bukkit.event.player import AsyncPlayerChatEvent
    except ImportError:
        AsyncPlayerChatEvent = None
except ImportError:
    Bukkit = None
    ChatColor = None
    Material = None
    Command = object
    TabCompleter = object
    EventPriority = None
    HandlerList = None
    InventoryClickEvent = None
    InventoryDragEvent = None
    PlayerQuitEvent = None
    InventoryHolder = object
    ItemStack = None
    Listener = object
    EventExecutor = object
    AsyncPlayerChatEvent = None
    BUKKIT_AVAILABLE = False

try:
    from java.lang import String as JavaString, StringBuilder, Runnable, System
    from java.util import ArrayList, UUID as JavaUUID
    JAVA_AVAILABLE = True
except ImportError:
    JavaString = str
    StringBuilder = None
    Runnable = object
    System = None
    ArrayList = list
    JavaUUID = None
    JAVA_AVAILABLE = False


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
    if JAVA_AVAILABLE and hasattr(value, "getBytes"):
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
    if JAVA_AVAILABLE:
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
    if BUKKIT_AVAILABLE and ChatColor is not None:
        try:
            return to_unicode(ChatColor.translateAlternateColorCodes('&', to_java_string(text)))
        except Exception:
            pass
    return re.sub(r'&([0-9a-fk-or])', u'', text, flags=re.IGNORECASE)


def send_message(target, value):
    message = colorize(value)
    if BUKKIT_AVAILABLE and target is not None and hasattr(target, "sendMessage"):
        try:
            target.sendMessage(to_java_string(message))
            return
        except Exception:
            pass
    print("[SmartY-Companies] " + to_unicode(message))


def log_info(value):
    if BUKKIT_AVAILABLE:
        send_message(Bukkit.getConsoleSender(), u"&3[SmartY-Companies] &7" + to_unicode(value))
    else:
        print("[SmartY-Companies] " + to_unicode(value))


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


def format_share_price(amount):
    try:
        val = float(amount)
        if val != val or val == float("inf") or val == float("-inf"):
            return u"0$"
        return to_unicode("{:,.2f}".format(val).replace(",", " ")) + u"$"
    except Exception:
        return u"0$"


def safe_float(value, default=0.0, minimum=None, maximum=None):
    try:
        result = float(value)
        if result != result or result == float("inf") or result == float("-inf"):
            return default
        if minimum is not None and result < minimum:
            return default
        if maximum is not None and result > maximum:
            return default
        return result
    except Exception:
        return default


def wrap_lore_text(text, color=u"&7", width=36):
    normalized = to_unicode(text).replace("\\n", "\n")
    lines = []
    for paragraph in normalized.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append(color)
            continue
        current = u""
        for word in words:
            candidate = word if not current else current + u" " + word
            if len(candidate) > width and current:
                lines.append(color + current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(color + current)
    return lines or [color + u"Описание не задано"]


def parse_amount(raw):
    value = float(to_unicode(raw).replace(",", ".").replace(" ", ""))
    # ФИКС: NaN и Infinity раньше проходили проверку "value <= 0" молча
    # (сравнения с NaN всегда False), что открывало путь к порче балансов
    # компаний/игроков через /company deposit|withdraw <company> nan.
    # value != value истинно только для NaN.
    if value != value or value == float("inf") or value == float("-inf"):
        raise ValueError()
    if value <= 0:
        raise ValueError()
    return round(value, 2)


def parse_int(raw):
    value = int(to_unicode(raw).replace(" ", ""))
    if value <= 0:
        raise ValueError()
    return value


def get_sender_uuid_and_name(sender):
    if sender is None or not hasattr(sender, "getUniqueId"):
        return None, u"Console"
    try:
        return str(sender.getUniqueId()), to_unicode(sender.getName())
    except Exception:
        return None, u"Unknown"


def is_admin(sender):
    if sender is None or not hasattr(sender, "getUniqueId"):
        return True
    try:
        return sender.isOp() or sender.hasPermission("smarty.companies.admin")
    except Exception:
        return False


def normalize_key(value):
    text = to_unicode(value).strip().lower()
    text = re.sub(r'\s+', "_", text, flags=re.UNICODE)
    text = re.sub(r'[^\w\-]', "", text, flags=re.UNICODE)
    return text[:48]


def new_id():
    if JavaUUID is not None:
        return str(JavaUUID.randomUUID())
    return str(int(time.time() * 1000))


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


class CompaniesConfig(object):
    PLUGIN_NAME = u"SmartY-Companies"
    VERSION = u"1.2.0"
    PREFIX = u"&3&l[Предприятия]&r "
    SHARES_TOTAL = 10000
    MAX_OWNER_COMPANIES = 10
    MIN_SHARE_PRICE = 10.0
    MAX_START_SHARE_PRICE = 100000.0
    DEFAULT_TAX_PERCENT = 2.0
    DIVIDEND_INTERVAL_SECONDS = 24 * 60 * 60
    DIVIDEND_TASK_PERIOD_TICKS = 1200
    LIST_PAGE_SIZE = 45
    OFFER_TIMEOUT_SECONDS = 300
    OPERATION_HISTORY_LIMIT = 300
    PRICE_HISTORY_DAYS = 30
    LARGE_WITHDRAW_PERCENT = 20.0
    WITHDRAW_VOTE_SECONDS = 24 * 60 * 60

    SCRIPT_DIR = get_script_dir()
    DATA_DIR = os.path.join(SCRIPT_DIR, "data")
    DATA_FILE = os.path.join(DATA_DIR, "companies.json")
    TOWNS_FILE = os.path.join(DATA_DIR, "cities.json")

    COMPANY_TYPES = [
        ("farm", u"Ферма", "WHEAT"),
        ("bar", u"Бар", "BREWING_STAND"),
        ("mine", u"Шахта", "DIAMOND_PICKAXE"),
        ("bank", u"Банк", "GOLD_INGOT"),
        ("factory", u"Завод", "FURNACE"),
        ("shop", u"Магазин", "CHEST"),
        ("fishing", u"Рыбалка", "FISHING_ROD"),
        ("blacksmith", u"Кузница", "ANVIL")
    ]


def calculate_company_share_price(company):
    total = CompaniesConfig.SHARES_TOTAL
    start_price = safe_float(company.get("start_price"), CompaniesConfig.MIN_SHARE_PRICE, CompaniesConfig.MIN_SHARE_PRICE)
    balance = safe_float(company.get("balance"), 0.0, 0.0)
    try:
        available = max(0, min(total, int(company.get("available_shares", total))))
    except Exception:
        available = total
    issued = total - available
    offset = safe_float(company.get("price_offset"), 0.0)
    # Capital and issued shares move the quote in the requested directions.
    # price_offset preserves an existing company's pre-1.1.0 quote during migration.
    price = start_price + (balance / float(total)) + (float(issued) * start_price / float(total)) + offset
    return max(1.0, round(price, 6))


def legacy_company_share_price(company):
    total = CompaniesConfig.SHARES_TOTAL
    start_price = safe_float(company.get("start_price"), CompaniesConfig.MIN_SHARE_PRICE, CompaniesConfig.MIN_SHARE_PRICE)
    balance = safe_float(company.get("balance"), 0.0, 0.0)
    try:
        available = max(0, min(total, int(company.get("available_shares", total))))
    except Exception:
        available = total
    return max(1.0, round((balance + float(available) * start_price) / float(total), 6))


class JsonStorage(object):
    def __init__(self, path, defaults):
        self.path = path
        self.backup_path = path + ".bak"
        self.defaults = defaults
        self.primary_valid = not os.path.exists(path)

    def ensure_dir(self):
        folder = os.path.dirname(self.path)
        if not os.path.exists(folder):
            os.makedirs(folder)

    def read_path(self, path):
        with open(path, "rb") as handle:
            payload = handle.read()
        if not payload:
            raise ValueError("empty JSON file")
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON root must be an object")
        return self.merge_defaults(data)

    def load(self):
        self.ensure_dir()
        if not os.path.exists(self.path):
            self.primary_valid = True
            return self.merge_defaults({})
        try:
            data = self.read_path(self.path)
            self.primary_valid = True
            return data
        except Exception as exc:
            log_info(u"Cannot read companies data: {0}".format(exc))
        if os.path.exists(self.backup_path):
            try:
                data = self.read_path(self.backup_path)
                self.primary_valid = False
                log_info(u"Loaded companies data from backup; primary file will be repaired on save.")
                return data
            except Exception as exc:
                log_info(u"Cannot read companies backup: {0}".format(exc))
        self.primary_valid = False
        raise RuntimeError("companies.json and its backup are unreadable")

    def save(self, data):
        temp_path = self.path + ".tmp"
        try:
            self.ensure_dir()
            payload = json.dumps(data, indent=2, ensure_ascii=True, sort_keys=True)
            with open(temp_path, "wb") as handle:
                handle.write(payload.encode("utf-8"))
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except Exception:
                    pass
            if os.path.exists(self.path) and self.primary_valid:
                shutil.copy2(self.path, self.backup_path)
            if hasattr(os, "replace"):
                os.replace(temp_path, self.path)
            else:
                if os.path.exists(self.path):
                    os.remove(self.path)
                os.rename(temp_path, self.path)
            self.primary_valid = True
            return True
        except Exception as exc:
            log_info(u"Cannot save companies data: {0}".format(exc))
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            return False

    def merge_defaults(self, data):
        result = {}
        for key, value in self.defaults.items():
            result[key] = copy.deepcopy(value)
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
        if JAVA_AVAILABLE and System is not None:
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
        return None

    def is_ready(self):
        self.refresh()
        return self.manager is not None

    def get_or_create(self, uuid_str, name):
        if not self.is_ready():
            return None
        if hasattr(self.manager, "get_or_create_account"):
            return self.manager.get_or_create_account(uuid_str, name)
        return None

    def get_by_name(self, name):
        if not self.is_ready():
            return None
        if hasattr(self.manager, "get_account_by_name"):
            return self.manager.get_account_by_name(name)
        return None

    def has_enough(self, uuid_str, amount):
        if not self.is_ready():
            return False
        return bool(self.manager.has_enough(uuid_str, amount))

    def withdraw(self, uuid_str, amount):
        if not self.is_ready():
            return False
        return bool(self.manager.withdraw(uuid_str, amount))

    def deposit(self, uuid_str, amount, name):
        success, balance = self.deposit_checked(uuid_str, amount, name)
        return balance

    def deposit_checked(self, uuid_str, amount, name):
        if not self.is_ready():
            return False, 0.0
        if hasattr(self.manager, "deposit_checked"):
            return self.manager.deposit_checked(uuid_str, amount, name)
        return True, self.manager.deposit(uuid_str, amount, name)

    def transfer(self, from_uuid, to_uuid, amount, to_name):
        if not self.is_ready() or not hasattr(self.manager, "transfer"):
            return False, 0.0, 0.0
        return self.manager.transfer(from_uuid, to_uuid, amount, to_name)

    def online_names(self):
        names = []
        if BUKKIT_AVAILABLE:
            try:
                for player in Bukkit.getOnlinePlayers():
                    names.append(to_unicode(player.getName()))
            except Exception:
                pass
        return names


class TownGateway(object):
    def __init__(self):
        self.path = CompaniesConfig.TOWNS_FILE

    def find_manager(self):
        if JAVA_AVAILABLE and System is not None:
            try:
                manager = System.getProperties().get("SmartY_TownState")
                if manager is not None:
                    if hasattr(manager, "is_active") and not manager.is_active():
                        return None
                    return manager
            except Exception:
                pass
        return None

    def load(self):
        if not os.path.exists(self.path):
            return {"cities": {}}
        try:
            with open(self.path, "r") as handle:
                return json.load(handle)
        except Exception as exc:
            log_info(u"Cannot read towns data: {0}".format(exc))
            return {"cities": {}}

    def save(self, data):
        temp_path = self.path + ".tmp"
        try:
            folder = os.path.dirname(self.path)
            if not os.path.exists(folder):
                os.makedirs(folder)
            with open(temp_path, "wb") as handle:
                handle.write(json.dumps(data, indent=2, ensure_ascii=True, sort_keys=True).encode("utf-8"))
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except Exception:
                    pass
            if hasattr(os, "replace"):
                os.replace(temp_path, self.path)
            else:
                if os.path.exists(self.path):
                    os.remove(self.path)
                os.rename(temp_path, self.path)
            return True
        except Exception as exc:
            log_info(u"Cannot save towns data: {0}".format(exc))
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            return False

    def get_player_town(self, uuid_str):
        manager = self.find_manager()
        if manager is not None and hasattr(manager, "get_city_by_player"):
            try:
                return manager.get_city_by_player(str(uuid_str))
            except Exception:
                pass
        data = self.load()
        for city in data.get("cities", {}).values():
            if str(uuid_str) in city.get("members", {}):
                return city
        return None

    def add_tax(self, city_name, amount):
        success, treasury = self.add_tax_checked(city_name, amount)
        return treasury if success else 0.0

    def add_tax_checked(self, city_name, amount):
        if amount <= 0:
            return True, 0.0
        manager = self.find_manager()
        if manager is not None and hasattr(manager, "add_company_tax"):
            try:
                result = manager.add_company_tax(city_name, amount)
                return bool(result[0]), float(result[1])
            except Exception as exc:
                log_info(u"Town manager rejected company tax: {0}".format(exc))
                return False, 0.0
        data = self.load()
        city_id = normalize_key(city_name)
        city = data.get("cities", {}).get(city_id)
        if not city:
            for item in data.get("cities", {}).values():
                if normalize_key(item.get("name")) == city_id:
                    city = item
                    break
        if not city:
            return False, 0.0
        old_treasury = safe_float(city.get("treasury", 0.0), 0.0, 0.0)
        city["treasury"] = round(float(city.get("treasury", 0.0)) + float(amount), 2)
        city["updated_at"] = int(time.time())
        if not self.save(data):
            city["treasury"] = old_treasury
            return False, old_treasury
        return True, city["treasury"]

    def get_tax_percent(self, city_name, operation):
        manager = self.find_manager()
        if manager is not None and hasattr(manager, "get_company_tax_percent"):
            try:
                return float(manager.get_company_tax_percent(city_name, operation, CompaniesConfig.DEFAULT_TAX_PERCENT))
            except Exception:
                return CompaniesConfig.DEFAULT_TAX_PERCENT
        data = self.load()
        city_id = normalize_key(city_name)
        city = data.get("cities", {}).get(city_id)
        if not city:
            return CompaniesConfig.DEFAULT_TAX_PERCENT
        taxes = city.get("taxes", {})
        if isinstance(taxes, dict):
            try:
                return max(0.0, float(taxes.get(operation, taxes.get("companies", CompaniesConfig.DEFAULT_TAX_PERCENT))))
            except Exception:
                pass
        return CompaniesConfig.DEFAULT_TAX_PERCENT


class CompanyState(object):
    DEFAULTS = {
        "companies": {}, "offers": {}, "next_offer_id": 1,
        "operation_journal": {}, "operation_history": [],
        "next_operation_id": 1, "withdraw_votes": {}, "next_vote_id": 1,
        "limit_orders": {}, "next_limit_order_id": 1
    }

    def __init__(self, storage):
        self.storage = storage
        self.lock = threading.RLock()
        self.data = self.storage.load()
        self.normalize()

    def normalize(self):
        changed = False
        self.data.setdefault("companies", {})
        self.data.setdefault("offers", {})
        self.data.setdefault("next_offer_id", 1)
        self.data.setdefault("operation_journal", {})
        self.data.setdefault("operation_history", [])
        self.data.setdefault("next_operation_id", 1)
        self.data.setdefault("withdraw_votes", {})
        self.data.setdefault("next_vote_id", 1)
        self.data.setdefault("limit_orders", {})
        self.data.setdefault("next_limit_order_id", 1)
        now = int(time.time())
        for company in self.data.get("companies", {}).values():
            defaults = {
                "id": new_id(),
                "name": u"Company",
                "description": u"Описание не задано",
                "type": "shop",
                "owner_uuid": "",
                "owner_name": u"Unknown",
                "town": u"",
                "next_dividend_at": int(time.time() + CompaniesConfig.DIVIDEND_INTERVAL_SECONDS),
                "created_at": int(time.time()),
                "updated_at": int(time.time())
            }
            for key, value in defaults.items():
                if key not in company:
                    company[key] = value
                    changed = True
            # Старые записи могли ждать ещё трое суток. После миграции первая
            # выплата наступает не позже чем через 24 часа.
            if int(company.get("next_dividend_at", 0)) > now + CompaniesConfig.DIVIDEND_INTERVAL_SECONDS:
                company["next_dividend_at"] = now + CompaniesConfig.DIVIDEND_INTERVAL_SECONDS
                changed = True
            for key, value in (
                ("transaction_history", []), ("daily_ohlc", {}),
                ("bankrupt", False), ("bankrupt_at", 0)
            ):
                if key not in company:
                    company[key] = copy.deepcopy(value)
                    changed = True
            normalized_key = normalize_key(company.get("key") or company.get("name"))
            if company.get("key") != normalized_key:
                company["key"] = normalized_key
                changed = True
            start_price = round(safe_float(
                company.get("start_price"),
                CompaniesConfig.MIN_SHARE_PRICE,
                CompaniesConfig.MIN_SHARE_PRICE,
                CompaniesConfig.MAX_START_SHARE_PRICE
            ), 2)
            balance = round(safe_float(company.get("balance"), 0.0, 0.0), 2)
            dividends = round(safe_float(company.get("dividends"), 0.0, 0.0), 2)
            if company.get("start_price") != start_price:
                company["start_price"] = start_price
                changed = True
            if company.get("balance") != balance:
                company["balance"] = balance
                changed = True
            if company.get("dividends") != dividends:
                company["dividends"] = dividends
                changed = True
            if company.get("total_shares") != CompaniesConfig.SHARES_TOTAL:
                company["total_shares"] = CompaniesConfig.SHARES_TOTAL
                changed = True
            raw_shares = company.get("shares", {})
            clean_shares = {}
            if isinstance(raw_shares, dict):
                for uuid_str, amount in raw_shares.items():
                    try:
                        amount_int = int(amount)
                    except Exception:
                        amount_int = 0
                    if amount_int > 0:
                        clean_shares[str(uuid_str)] = amount_int
            total_owned = sum(clean_shares.values())
            if total_owned > CompaniesConfig.SHARES_TOTAL:
                raise RuntimeError("company {0} has more shares than allowed".format(company.get("name")))
            available = CompaniesConfig.SHARES_TOTAL - total_owned
            if raw_shares != clean_shares:
                company["shares"] = clean_shares
                changed = True
            if company.get("available_shares") != available:
                company["available_shares"] = available
                changed = True
            if "price_offset" not in company:
                migrated_price = safe_float(company.get("share_price"), None, 1.0)
                old_price = migrated_price if migrated_price is not None else legacy_company_share_price(company)
                base_price = start_price + balance / float(CompaniesConfig.SHARES_TOTAL) + total_owned * start_price / float(CompaniesConfig.SHARES_TOTAL)
                company["price_offset"] = round(old_price - base_price, 6)
                changed = True
            else:
                offset = round(safe_float(company.get("price_offset"), 0.0), 6)
                if company.get("price_offset") != offset:
                    company["price_offset"] = offset
                    changed = True
            normalized_price = calculate_company_share_price(company)
            if company.get("share_price") != normalized_price:
                company["share_price"] = normalized_price
                changed = True
        if changed and not self.save():
            raise RuntimeError("cannot save normalized companies data")

    def save(self):
        self.lock.acquire()
        try:
            for company in self.data.get("companies", {}).values():
                company["share_price"] = calculate_company_share_price(company)
                self.record_quote(company, company["share_price"])
            return bool(self.storage.save(self.data))
        finally:
            self.lock.release()

    def list_companies(self):
        items = list(self.data.get("companies", {}).values())
        return sorted(items, key=lambda company: to_unicode(company.get("name")).lower())

    def find_company(self, name_or_id):
        key = normalize_key(name_or_id)
        if key in self.data.get("companies", {}):
            return self.data["companies"][key]
        for company in self.data.get("companies", {}).values():
            if str(company.get("id")) == str(name_or_id) or normalize_key(company.get("name")) == key:
                return company
        return None

    def owner_count(self, uuid_str):
        count = 0
        for company in self.data.get("companies", {}).values():
            if str(company.get("owner_uuid")) == str(uuid_str):
                count += 1
        return count

    def create_company(self, name, description, company_type, start_price, owner_uuid, owner_name, town_name):
        key = normalize_key(name)
        now = int(time.time())
        company = {
            "id": new_id(),
            "key": key,
            "name": to_unicode(name).strip(),
            "description": to_unicode(description).strip(),
            "type": company_type,
            "owner_uuid": str(owner_uuid),
            "owner_name": to_unicode(owner_name),
            "town": to_unicode(town_name),
            "start_price": round(float(start_price), 2),
            "price_offset": 0.0,
            "balance": 0.0,
            "total_shares": CompaniesConfig.SHARES_TOTAL,
            "available_shares": CompaniesConfig.SHARES_TOTAL,
            "shares": {},
            "dividends": 0.0,
            "next_dividend_at": now + CompaniesConfig.DIVIDEND_INTERVAL_SECONDS,
            "created_at": now,
            "updated_at": now
        }
        self.data.setdefault("companies", {})[key] = company
        if not self.save():
            del self.data["companies"][key]
            return None
        return company

    def delete_company(self, company):
        key = company.get("key", normalize_key(company.get("name")))
        if key in self.data.get("companies", {}):
            del self.data["companies"][key]
            if not self.save():
                self.data["companies"][key] = company
                return False
            return True
        return False

    def rename_company(self, company, new_name):
        old_key = company.get("key")
        new_key = normalize_key(new_name)
        old_name = company.get("name")
        old_updated_at = company.get("updated_at")
        company["name"] = to_unicode(new_name).strip()
        company["key"] = new_key
        company["updated_at"] = int(time.time())
        if old_key in self.data.get("companies", {}):
            del self.data["companies"][old_key]
        self.data.setdefault("companies", {})[new_key] = company
        if not self.save():
            del self.data["companies"][new_key]
            company["name"] = old_name
            company["key"] = old_key
            company["updated_at"] = old_updated_at
            self.data["companies"][old_key] = company
            return None
        return company

    def next_offer_id(self):
        offer_id = int(self.data.get("next_offer_id", 1))
        self.data["next_offer_id"] = offer_id + 1
        return str(offer_id)

    def record_quote(self, company, price):
        day = time.strftime("%Y-%m-%d", time.localtime())
        history = company.setdefault("daily_ohlc", {})
        candle = history.get(day)
        price = round(float(price), 6)
        if candle is None:
            history[day] = {"open": price, "high": price, "low": price, "close": price}
        else:
            candle["high"] = max(float(candle.get("high", price)), price)
            candle["low"] = min(float(candle.get("low", price)), price)
            candle["close"] = price
        if len(history) > CompaniesConfig.PRICE_HISTORY_DAYS:
            for old_day in sorted(history.keys())[:-CompaniesConfig.PRICE_HISTORY_DAYS]:
                history.pop(old_day, None)

    def begin_operation(self, operation, payload):
        op_id = str(self.data.get("next_operation_id", 1))
        self.data["next_operation_id"] = int(op_id) + 1
        entry = {
            "id": op_id, "operation": str(operation), "status": "prepared",
            "created_at": int(time.time()), "payload": copy.deepcopy(payload)
        }
        self.data.setdefault("operation_journal", {})[op_id] = entry
        if not self.save():
            self.data["operation_journal"].pop(op_id, None)
            return None
        return op_id

    def complete_operation(self, op_id, result=None):
        entry = self.data.setdefault("operation_journal", {}).pop(str(op_id), None)
        if entry is None:
            return False
        entry["status"] = "completed"
        entry["completed_at"] = int(time.time())
        if result is not None:
            entry["result"] = copy.deepcopy(result)
        history = self.data.setdefault("operation_history", [])
        history.append(entry)
        if len(history) > CompaniesConfig.OPERATION_HISTORY_LIMIT:
            del history[:-CompaniesConfig.OPERATION_HISTORY_LIMIT]
        return self.save()

    def fail_operation(self, op_id, reason):
        entry = self.data.setdefault("operation_journal", {}).pop(str(op_id), None)
        if entry is None:
            return False
        entry["status"] = "failed"
        entry["completed_at"] = int(time.time())
        entry["reason"] = to_unicode(reason)
        history = self.data.setdefault("operation_history", [])
        history.append(entry)
        if len(history) > CompaniesConfig.OPERATION_HISTORY_LIMIT:
            del history[:-CompaniesConfig.OPERATION_HISTORY_LIMIT]
        return self.save()

    def add_company_history(self, company, operation, actor, amount=0.0, details=None):
        history = company.setdefault("transaction_history", [])
        history.append({
            "time": int(time.time()), "operation": str(operation),
            "actor": to_unicode(actor), "amount": round(float(amount), 2),
            "details": to_unicode(details or u"")
        })
        if len(history) > CompaniesConfig.OPERATION_HISTORY_LIMIT:
            del history[:-CompaniesConfig.OPERATION_HISTORY_LIMIT]


class CompanyService(object):
    def __init__(self, state, economy, towns):
        self.state = state
        self.economy = economy
        self.towns = towns

    def type_label(self, type_key):
        for item in CompaniesConfig.COMPANY_TYPES:
            if item[0] == type_key:
                return item[1]
        return type_key

    def current_price(self, company):
        return calculate_company_share_price(company)

    def is_tradable(self, player, company):
        if company.get("bankrupt"):
            send_message(player, CompaniesConfig.PREFIX + u"&cПредприятие находится в банкротстве; торговля акциями остановлена.")
            return False
        return True

    def reserved_shares(self, company, uuid_str, exclude_offer_id=None):
        reserved = 0
        for offer_id, offer in self.state.data.setdefault("offers", {}).items():
            if exclude_offer_id is not None and str(offer_id) == str(exclude_offer_id):
                continue
            if str(offer.get("company_key")) == str(company.get("key")) and \
                    str(offer.get("seller_uuid")) == str(uuid_str) and \
                    int(offer.get("expires_at", 0)) >= int(time.time()):
                reserved += max(0, int(offer.get("amount", 0)))
        for order in self.state.data.setdefault("limit_orders", {}).values():
            if order.get("side") == "sell" and str(order.get("company_key")) == str(company.get("key")) and \
                    str(order.get("player_uuid")) == str(uuid_str):
                reserved += max(0, int(order.get("amount", 0)))
        return reserved

    def available_owned_shares(self, company, uuid_str, exclude_offer_id=None):
        return max(0, self.owned_shares(company, uuid_str) - self.reserved_shares(company, uuid_str, exclude_offer_id))

    def marginal_buy_cost(self, company, amount):
        amount = int(amount)
        if amount <= 0:
            return 0.0
        total_shares = float(CompaniesConfig.SHARES_TOTAL)
        start_price = safe_float(company.get("start_price"), CompaniesConfig.MIN_SHARE_PRICE, CompaniesConfig.MIN_SHARE_PRICE)
        price = self.current_price(company)
        total = 0.0
        for unused in range(amount):
            unit_price = max(0.01, round(price, 2))
            total = round(total + unit_price, 2)
            price += (unit_price + start_price) / total_shares
        return total

    def marginal_sell_value(self, company, amount):
        amount = int(amount)
        if amount <= 0:
            return 0.0
        total_shares = float(CompaniesConfig.SHARES_TOTAL)
        start_price = safe_float(company.get("start_price"), CompaniesConfig.MIN_SHARE_PRICE, CompaniesConfig.MIN_SHARE_PRICE)
        price = self.current_price(company)
        total = 0.0
        for unused in range(amount):
            unit_price = max(0.01, round((price * total_shares - start_price) / (total_shares + 1.0), 2))
            total = round(total + unit_price, 2)
            price -= (unit_price + start_price) / total_shares
        return total

    def market_cap(self, company):
        return round(self.current_price(company) * float(CompaniesConfig.SHARES_TOTAL), 2)

    def owned_shares(self, company, uuid_str):
        return int(company.get("shares", {}).get(str(uuid_str), 0))

    def add_shares(self, company, uuid_str, amount):
        shares = company.setdefault("shares", {})
        shares[str(uuid_str)] = int(shares.get(str(uuid_str), 0)) + int(amount)
        if shares[str(uuid_str)] <= 0:
            del shares[str(uuid_str)]
        company["updated_at"] = int(time.time())

    def snapshot_company(self, company):
        return json.loads(json.dumps(company, ensure_ascii=True))

    def restore_company(self, company, snapshot):
        company.clear()
        company.update(snapshot)

    def save_company_change(self, player, company, snapshot, operation):
        actor = get_sender_uuid_and_name(player)[1] if player is not None else u"System"
        self.state.add_company_history(company, operation, actor)
        if self.state.save():
            return True
        self.restore_company(company, snapshot)
        send_message(player, CompaniesConfig.PREFIX + u"&cОперация отменена: данные компании не удалось сохранить.")
        log_info(u"Company operation {0} rolled back for {1}".format(operation, company.get("name")))
        return False

    def refund_player(self, uuid_str, amount, name, context):
        if amount <= 0:
            return True
        success, balance = self.economy.deposit_checked(uuid_str, amount, name)
        if not success:
            log_info(u"CRITICAL: failed to refund {0} to {1} after {2}".format(amount, name, context))
        return bool(success)

    def collect_town_tax(self, company, tax, payer_uuid=None, payer_name=None):
        if tax <= 0:
            return 0.0
        success, treasury = self.towns.add_tax_checked(company.get("town"), tax)
        if success:
            self.state.add_company_history(
                company, "town_tax", payer_name or u"System", tax,
                u"Казна города {0}".format(company.get("town")))
            if not self.state.save():
                log_info(u"Town tax was credited, but company audit could not be saved: {0}".format(company.get("name")))
            return tax
        log_info(u"Town tax storage failed for {0}, tax={1}".format(company.get("name"), tax))
        if payer_uuid is not None:
            self.refund_player(payer_uuid, tax, payer_name, u"town tax failure")
        return 0.0

    def remove_offer_checked(self, offer_id):
        key = str(offer_id)
        offer = self.state.data.setdefault("offers", {}).pop(key, None)
        if offer is None:
            return False, None
        if self.state.save():
            return True, offer
        self.state.data["offers"][key] = offer
        return False, offer

    def validate_company_name(self, name):
        text = to_unicode(name).strip()
        return len(text) >= 3 and len(text) <= 32 and normalize_key(text)

    def create_company(self, player, name, description, company_type, start_price):
        uuid_str, player_name = get_sender_uuid_and_name(player)
        if not uuid_str:
            send_message(player, CompaniesConfig.PREFIX + u"&cТолько игрок может создать предприятие.")
            return
        if self.state.owner_count(uuid_str) >= CompaniesConfig.MAX_OWNER_COMPANIES:
            send_message(player, CompaniesConfig.PREFIX + u"&cУ вас уже максимум предприятий: &e10&c.")
            return
        if not self.validate_company_name(name):
            send_message(player, CompaniesConfig.PREFIX + u"&cНазвание: 3-32 символа.")
            return
        if self.state.find_company(name):
            send_message(player, CompaniesConfig.PREFIX + u"&cПредприятие с таким названием уже существует.")
            return
        if company_type not in [item[0] for item in CompaniesConfig.COMPANY_TYPES]:
            send_message(player, CompaniesConfig.PREFIX + u"&cНеизвестный тип предприятия.")
            return
        if float(start_price) < CompaniesConfig.MIN_SHARE_PRICE:
            send_message(player, CompaniesConfig.PREFIX + u"&cМинимальная стартовая цена акции: &e{0}&c.".format(format_currency(CompaniesConfig.MIN_SHARE_PRICE)))
            return
        if float(start_price) > CompaniesConfig.MAX_START_SHARE_PRICE:
            send_message(player, CompaniesConfig.PREFIX + u"&cМаксимальная стартовая цена акции: &e{0}&c.".format(format_currency(CompaniesConfig.MAX_START_SHARE_PRICE)))
            return
        town = self.towns.get_player_town(uuid_str)
        if not town:
            send_message(player, CompaniesConfig.PREFIX + u"&cПредприятие можно создать только жителю города.")
            return
        self.economy.get_or_create(uuid_str, player_name)
        company = self.state.create_company(name, description, company_type, start_price, uuid_str, player_name, town.get("name"))
        if company is None:
            send_message(player, CompaniesConfig.PREFIX + u"&cПредприятие не создано: данные не удалось сохранить.")
            return
        send_message(player, CompaniesConfig.PREFIX + u"&aПредприятие &e{0}&a зарегистрировано в городе &b{1}&a.".format(company.get("name"), company.get("town")))

    def buy_primary(self, player, company_name, amount):
        uuid_str, player_name = get_sender_uuid_and_name(player)
        company = self.state.find_company(company_name)
        if not company:
            send_message(player, CompaniesConfig.PREFIX + u"&cПредприятие не найдено.")
            return
        if not self.is_tradable(player, company):
            return
        if str(company.get("owner_uuid")) == str(uuid_str):
            send_message(player, CompaniesConfig.PREFIX + u"&cВладелец не может покупать акции своей компании.")
            return
        amount = int(amount)
        available = int(company.get("available_shares", 0))
        if amount <= 0 or amount > available:
            send_message(player, CompaniesConfig.PREFIX + u"&cДоступно акций: &e{0}&c.".format(available))
            return
        price = self.current_price(company)
        subtotal = self.marginal_buy_cost(company, amount)
        tax = self.calculate_tax(company, subtotal, "primary")
        total = round(subtotal + tax, 2)
        old_price = price
        op_id = self.state.begin_operation("primary_buy", {
            "company": company.get("key"), "buyer_uuid": uuid_str,
            "buyer_name": player_name, "shares": amount, "subtotal": subtotal,
            "tax": tax, "total": total
        })
        if op_id is None:
            send_message(player, CompaniesConfig.PREFIX + u"&cСделка не начата: журнал операций недоступен.")
            return
        if not self.economy.withdraw(uuid_str, total):
            self.state.fail_operation(op_id, "withdraw failed")
            send_message(player, CompaniesConfig.PREFIX + u"&cНе удалось списать &e{0}&c. Проверьте баланс и работу экономики.".format(format_currency(total)))
            return
        snapshot = self.snapshot_company(company)
        company["balance"] = round(float(company.get("balance", 0.0)) + subtotal, 2)
        company["available_shares"] = available - amount
        self.add_shares(company, uuid_str, amount)
        if not self.save_company_change(player, company, snapshot, "primary buy"):
            self.refund_player(uuid_str, total, player_name, u"primary buy rollback")
            self.state.fail_operation(op_id, "company save failed")
            return
        applied_tax = self.collect_town_tax(company, tax, uuid_str, player_name)
        self.state.complete_operation(op_id, {"applied_tax": applied_tax, "new_price": self.current_price(company)})
        new_price = self.current_price(company)
        send_message(player, CompaniesConfig.PREFIX + u"&aКуплено &e{0}&a акций &b{1}&a за &e{2}&a. Налог: &6{3}&a. Цена: &f{4} &7→ &a{5}&a.".format(
            amount, company.get("name"), format_currency(subtotal), format_currency(applied_tax), format_share_price(old_price), format_share_price(new_price)
        ))

    def sell_to_market(self, player, company_name, amount):
        uuid_str, player_name = get_sender_uuid_and_name(player)
        company = self.state.find_company(company_name)
        if not company:
            send_message(player, CompaniesConfig.PREFIX + u"&cПредприятие не найдено.")
            return
        if not self.is_tradable(player, company):
            return
        amount = int(amount)
        owned = self.available_owned_shares(company, uuid_str)
        if amount <= 0 or amount > owned:
            send_message(player, CompaniesConfig.PREFIX + u"&cУ вас акций этого предприятия: &e{0}&c.".format(owned))
            return
        price = self.current_price(company)
        company_balance = round(float(company.get("balance", 0.0)), 2)
        subtotal = self.marginal_sell_value(company, amount)
        if subtotal <= 0:
            send_message(player, CompaniesConfig.PREFIX + u"&cУ компании нет денег для выкупа акций.")
            return
        if subtotal > company_balance:
            send_message(player, CompaniesConfig.PREFIX + u"&cУ компании недостаточно денег для выкупа. Нужно &e{0}&c, на счете &e{1}&c.".format(
                format_currency(subtotal), format_currency(company_balance)
            ))
            return
        tax = self.calculate_tax(company, subtotal, "resale")
        payout = round(subtotal - tax, 2)
        old_price = price
        op_id = self.state.begin_operation("market_sell", {
            "company": company.get("key"), "seller_uuid": uuid_str,
            "seller_name": player_name, "shares": amount, "subtotal": subtotal,
            "tax": tax, "payout": payout
        })
        if op_id is None:
            send_message(player, CompaniesConfig.PREFIX + u"&cПродажа не начата: журнал операций недоступен.")
            return
        snapshot = self.snapshot_company(company)
        company["balance"] = round(company_balance - subtotal, 2)
        company["available_shares"] = min(CompaniesConfig.SHARES_TOTAL, int(company.get("available_shares", 0)) + amount)
        self.add_shares(company, uuid_str, -amount)
        if not self.save_company_change(player, company, snapshot, "market sell"):
            self.state.fail_operation(op_id, "company save failed")
            return
        deposited, balance = self.economy.deposit_checked(uuid_str, payout, player_name)
        if not deposited:
            self.restore_company(company, snapshot)
            if not self.state.save():
                log_info(u"CRITICAL: failed to persist market sell rollback for {0}".format(company.get("name")))
            send_message(player, CompaniesConfig.PREFIX + u"&cПродажа отменена: деньги не удалось зачислить.")
            self.state.fail_operation(op_id, "payout failed and company restored")
            return
        applied_tax = self.collect_town_tax(company, tax, uuid_str, player_name)
        self.state.complete_operation(op_id, {"applied_tax": applied_tax, "new_price": self.current_price(company)})
        new_price = self.current_price(company)
        send_message(player, CompaniesConfig.PREFIX + u"&aПродано на бирже &e{0}&a акций &b{1}&a за &e{2}&a. Налог: &6{3}&a. Цена: &f{4} &7→ &c{5}&a.".format(
            amount, company.get("name"), format_currency(subtotal - applied_tax), format_currency(applied_tax), format_share_price(old_price), format_share_price(new_price)
        ))

    def deposit(self, player, company_name, amount):
        company = self.require_owner(player, company_name)
        if not company:
            return
        uuid_str, player_name = get_sender_uuid_and_name(player)
        if not uuid_str:
            send_message(player, CompaniesConfig.PREFIX + u"&cФинансовые операции доступны только игроку.")
            return
        old_price = self.current_price(company)
        op_id = self.state.begin_operation("owner_deposit", {
            "company": company.get("key"), "owner_uuid": uuid_str, "amount": amount
        })
        if op_id is None:
            send_message(player, CompaniesConfig.PREFIX + u"&cПополнение не начато: журнал операций недоступен.")
            return
        if not self.economy.withdraw(uuid_str, amount):
            self.state.fail_operation(op_id, "withdraw failed")
            send_message(player, CompaniesConfig.PREFIX + u"&cНе удалось списать деньги. Проверьте баланс и работу экономики.")
            return
        snapshot = self.snapshot_company(company)
        company["balance"] = round(float(company.get("balance", 0.0)) + float(amount), 2)
        company["updated_at"] = int(time.time())
        if not self.save_company_change(player, company, snapshot, "owner deposit"):
            self.refund_player(uuid_str, amount, player_name, u"company deposit rollback")
            self.state.fail_operation(op_id, "company save failed")
            return
        if company.get("bankrupt") and float(company.get("balance", 0.0)) > 0:
            company["bankrupt"] = False
            company["bankrupt_at"] = 0
            self.state.add_company_history(company, "bankruptcy_exit", player_name, amount)
            self.state.save()
        self.state.complete_operation(op_id, {"new_balance": company.get("balance")})
        broadcast_company(u"&7Компания &b{0}&7 пополнила счет на &e{1}&7. Акция: &f{2} &7→ &a{3}&7.".format(
            company.get("name"), format_currency(amount), format_share_price(old_price), format_share_price(self.current_price(company))
        ))

    def withdraw(self, player, company_name, amount):
        company = self.require_owner(player, company_name)
        if not company:
            return
        if amount > float(company.get("balance", 0.0)):
            send_message(player, CompaniesConfig.PREFIX + u"&cНа счете предприятия недостаточно денег.")
            return
        uuid_str, player_name = get_sender_uuid_and_name(player)
        if not uuid_str:
            send_message(player, CompaniesConfig.PREFIX + u"&cФинансовые операции доступны только игроку.")
            return
        issued = sum([int(value) for value in company.get("shares", {}).values()])
        threshold = float(company.get("balance", 0.0)) * CompaniesConfig.LARGE_WITHDRAW_PERCENT / 100.0
        approval = company.get("approved_withdraw") or {}
        approved = (
            float(approval.get("amount", -1.0)) == round(float(amount), 2)
            and int(approval.get("expires_at", 0)) >= int(time.time())
        )
        if approved:
            company.pop("approved_withdraw", None)
            if not self.state.save():
                send_message(player, CompaniesConfig.PREFIX + u"&cНе удалось использовать одобрение акционеров.")
                return
        elif issued > 0 and amount >= threshold and not is_admin(player):
            self.create_withdraw_vote(player, company, amount)
            return
        self.execute_withdraw(player, company, amount, uuid_str, player_name)

    def create_withdraw_vote(self, player, company, amount):
        now = int(time.time())
        for vote in self.state.data.setdefault("withdraw_votes", {}).values():
            if str(vote.get("company_key")) == str(company.get("key")) and int(vote.get("expires_at", 0)) >= now:
                send_message(player, CompaniesConfig.PREFIX + u"&eПо этой компании уже идёт голосование №{0}.".format(vote.get("id")))
                return
        vote_id = str(self.state.data.get("next_vote_id", 1))
        self.state.data["next_vote_id"] = int(vote_id) + 1
        issued = sum([int(value) for value in company.get("shares", {}).values()])
        vote = {
            "id": vote_id, "company_key": company.get("key"),
            "company_name": company.get("name"), "owner_uuid": company.get("owner_uuid"),
            "owner_name": company.get("owner_name"), "amount": round(float(amount), 2),
            "issued_shares": issued, "yes": {}, "no": {},
            "expires_at": now + CompaniesConfig.WITHDRAW_VOTE_SECONDS
        }
        self.state.data["withdraw_votes"][vote_id] = vote
        if not self.state.save():
            self.state.data["withdraw_votes"].pop(vote_id, None)
            send_message(player, CompaniesConfig.PREFIX + u"&cГолосование не удалось сохранить.")
            return
        broadcast_company(u"&eАкционеры &b{0}&e голосуют за вывод &6{1}&e. Команда: &f/shares vote {2} yes|no".format(
            company.get("name"), format_currency(amount), vote_id))

    def vote_withdraw(self, player, vote_id, decision):
        vote = self.state.data.setdefault("withdraw_votes", {}).get(str(vote_id))
        if not vote or int(vote.get("expires_at", 0)) < int(time.time()):
            send_message(player, CompaniesConfig.PREFIX + u"&cГолосование не найдено или истекло.")
            return
        company = self.state.find_company(vote.get("company_key"))
        if not company:
            send_message(player, CompaniesConfig.PREFIX + u"&cПредприятие не найдено.")
            return
        uuid_str, player_name = get_sender_uuid_and_name(player)
        weight = self.owned_shares(company, uuid_str)
        if weight <= 0:
            send_message(player, CompaniesConfig.PREFIX + u"&cГолосовать могут только акционеры.")
            return
        vote.setdefault("yes", {}).pop(str(uuid_str), None)
        vote.setdefault("no", {}).pop(str(uuid_str), None)
        vote["yes" if decision in ("yes", "да", "за") else "no"][str(uuid_str)] = weight
        yes_weight = sum([int(v) for v in vote.get("yes", {}).values()])
        no_weight = sum([int(v) for v in vote.get("no", {}).values()])
        required = int(vote.get("issued_shares", 0)) / 2.0
        if yes_weight > required:
            company["approved_withdraw"] = {
                "amount": float(vote.get("amount", 0.0)),
                "expires_at": int(time.time()) + 600,
                "vote_id": str(vote_id)
            }
            self.state.data["withdraw_votes"].pop(str(vote_id), None)
            self.state.add_company_history(company, "withdraw_approved", player_name, vote.get("amount", 0.0), u"vote " + str(vote_id))
            self.state.save()
            self.notify(vote.get("owner_name"), u"&aАкционеры одобрили вывод &6{0}&a. Повторите команду вывода в течение 10 минут.".format(
                format_currency(vote.get("amount", 0.0))))
            return
        if no_weight >= required:
            self.state.data["withdraw_votes"].pop(str(vote_id), None)
            self.state.save()
            self.notify(vote.get("owner_name"), u"&cАкционеры отклонили крупный вывод средств.")
            return
        self.state.save()
        send_message(player, CompaniesConfig.PREFIX + u"&aГолос учтён. За: &e{0}&a, против: &c{1}&a, всего акций: &f{2}&a.".format(
            yes_weight, no_weight, vote.get("issued_shares", 0)))

    def set_bankrupt(self, player, company_name):
        company = self.require_owner(player, company_name)
        if not company:
            return
        if company.get("bankrupt"):
            send_message(player, CompaniesConfig.PREFIX + u"&7Предприятие уже находится в банкротстве.")
            return
        snapshot = self.snapshot_company(company)
        company["bankrupt"] = True
        company["bankrupt_at"] = int(time.time())
        for offer_id, offer in list(self.state.data.setdefault("offers", {}).items()):
            if str(offer.get("company_key")) == str(company.get("key")):
                self.state.data["offers"].pop(offer_id, None)
        self.state.add_company_history(company, "bankruptcy", get_sender_uuid_and_name(player)[1])
        if not self.state.save():
            self.restore_company(company, snapshot)
            send_message(player, CompaniesConfig.PREFIX + u"&cБанкротство не удалось сохранить.")
            return
        broadcast_company(u"&cПредприятие &b{0}&c объявило банкротство. Торговля остановлена до пополнения счёта владельцем.".format(company.get("name")))

    def show_history(self, sender, company_name):
        company = self.state.find_company(company_name)
        if not company:
            send_message(sender, CompaniesConfig.PREFIX + u"&cПредприятие не найдено.")
            return
        send_message(sender, CompaniesConfig.PREFIX + u"&7Последние операции &b{0}&7:".format(company.get("name")))
        for entry in company.get("transaction_history", [])[-10:]:
            stamp = time.strftime("%d.%m %H:%M", time.localtime(int(entry.get("time", 0))))
            send_message(sender, u"&8- &7{0} &f{1} &8| &e{2} &8| &6{3}".format(
                stamp, entry.get("operation", "?"), entry.get("actor", "?"), format_currency(entry.get("amount", 0.0))))

    def show_chart(self, sender, company_name):
        company = self.state.find_company(company_name)
        if not company:
            send_message(sender, CompaniesConfig.PREFIX + u"&cПредприятие не найдено.")
            return
        send_message(sender, CompaniesConfig.PREFIX + u"&7Дневные котировки &b{0}&7:".format(company.get("name")))
        for day in sorted(company.get("daily_ohlc", {}).keys())[-7:]:
            c = company["daily_ohlc"][day]
            send_message(sender, u"&8- &f{0} &7O:&a{1} &7H:&a{2} &7L:&c{3} &7C:&e{4}".format(
                day, format_share_price(c.get("open")), format_share_price(c.get("high")),
                format_share_price(c.get("low")), format_share_price(c.get("close"))))

    def create_limit_order(self, player, side, company_name, amount, limit_price):
        side = str(side).lower()
        company = self.state.find_company(company_name)
        if not company:
            send_message(player, CompaniesConfig.PREFIX + u"&cПредприятие не найдено.")
            return
        if not self.is_tradable(player, company):
            return
        uuid_str, player_name = get_sender_uuid_and_name(player)
        amount = int(amount)
        limit_price = round(float(limit_price), 2)
        if amount <= 0 or limit_price <= 0:
            send_message(player, CompaniesConfig.PREFIX + u"&cКоличество и лимитная цена должны быть больше нуля.")
            return
        escrow = 0.0
        if side == "buy":
            max_subtotal = round(amount * limit_price, 2)
            escrow = round(max_subtotal + self.calculate_tax(company, max_subtotal, "primary"), 2)
            if not self.economy.withdraw(uuid_str, escrow):
                send_message(player, CompaniesConfig.PREFIX + u"&cНедостаточно денег для резерва &e{0}&c.".format(format_currency(escrow)))
                return
        elif side == "sell":
            if self.available_owned_shares(company, uuid_str) < amount:
                send_message(player, CompaniesConfig.PREFIX + u"&cНедостаточно свободных акций; часть уже зарезервирована.")
                return
        else:
            send_message(player, CompaniesConfig.PREFIX + u"&cСторона заявки: buy или sell.")
            return
        order_id = str(self.state.data.get("next_limit_order_id", 1))
        self.state.data["next_limit_order_id"] = int(order_id) + 1
        order = {
            "id": order_id, "side": side, "company_key": company.get("key"),
            "company_name": company.get("name"), "player_uuid": uuid_str,
            "player_name": player_name, "amount": amount,
            "limit_price": limit_price, "escrow": escrow,
            "created_at": int(time.time()), "status": "open"
        }
        self.state.data.setdefault("limit_orders", {})[order_id] = order
        if not self.state.save():
            self.state.data["limit_orders"].pop(order_id, None)
            if escrow > 0:
                self.refund_player(uuid_str, escrow, player_name, u"limit order save rollback")
            send_message(player, CompaniesConfig.PREFIX + u"&cЛимитная заявка не сохранена.")
            return
        send_message(player, CompaniesConfig.PREFIX + u"&aЗаявка №{0}: &e{1} {2} &aакций &b{3}&a по цене &6{4}&a.".format(
            order_id, side.upper(), amount, company.get("name"), format_share_price(limit_price)))

    def cancel_limit_order(self, player, order_id):
        order = self.state.data.setdefault("limit_orders", {}).get(str(order_id))
        uuid_str, player_name = get_sender_uuid_and_name(player)
        if not order or (str(order.get("player_uuid")) != str(uuid_str) and not is_admin(player)):
            send_message(player, CompaniesConfig.PREFIX + u"&cЗаявка не найдена.")
            return
        if str(order.get("status", "open")) in ("refund_in_progress", "payout_in_progress"):
            send_message(player, CompaniesConfig.PREFIX + u"&cРасчёт заявки имеет неопределённый результат. Администратор должен сверить журнал и выполнить /shares resolve.")
            return
        escrow = float(order.get("escrow", 0.0)) + float(order.get("refund_due", 0.0))
        if escrow > 0:
            order["status"] = "refund_in_progress"
            if not self.state.save():
                order["status"] = "open"
                send_message(player, CompaniesConfig.PREFIX + u"&cНе удалось зафиксировать начало возврата.")
                return
            ok, balance = self.economy.deposit_checked(order.get("player_uuid"), escrow, order.get("player_name"))
            if not ok:
                order["status"] = "filled_refund_due" if float(order.get("refund_due", 0.0)) > 0 else "open"
                self.state.save()
                send_message(player, CompaniesConfig.PREFIX + u"&cНе удалось вернуть резерв; заявка оставлена открытой.")
                return
            order["escrow"] = 0.0
            order["refund_due"] = 0.0
            order["status"] = "refund_paid"
            if not self.state.save():
                send_message(player, CompaniesConfig.PREFIX + u"&cВозврат выполнен, но закрытие заявки требует проверки администратором.")
                return
        self.state.data["limit_orders"].pop(str(order_id), None)
        if not self.state.save():
            order["status"] = "closed"
            self.state.data["limit_orders"][str(order_id)] = order
        send_message(player, CompaniesConfig.PREFIX + u"&aЗаявка отменена, резерв возвращён.")

    def resolve_limit_order(self, sender, order_id, action):
        if not is_admin(sender):
            send_message(sender, CompaniesConfig.PREFIX + u"&cТребуются права администратора.")
            return
        order = self.state.data.setdefault("limit_orders", {}).get(str(order_id))
        action = str(action).lower()
        if not order or action not in ("paid", "retry", "rollback", "reset"):
            send_message(sender, CompaniesConfig.PREFIX + u"&cИспользование: /shares resolve <id> <paid|retry|rollback|reset>")
            return
        status = str(order.get("status", "open"))
        company = self.state.find_company(order.get("company_key"))
        order_snapshot = copy.deepcopy(order)
        company_snapshot = self.snapshot_company(company) if company else None
        if action == "reset":
            if status not in ("processing_buy", "processing_sell"):
                send_message(sender, CompaniesConfig.PREFIX + u"&cСброс допустим только для операции, оборванной до расчёта.")
                return
            order["status"] = "open"
            if not self.state.save():
                order.clear()
                order.update(order_snapshot)
                send_message(sender, CompaniesConfig.PREFIX + u"&cСброс не удалось сохранить.")
                return
            send_message(sender, CompaniesConfig.PREFIX + u"&aЗаявка возвращена в очередь исполнения.")
            return
        if action == "paid" and status not in ("refund_in_progress", "payout_in_progress", "refund_paid", "payout_paid", "closed"):
            send_message(sender, CompaniesConfig.PREFIX + u"&cСтатус заявки нельзя закрыть как оплаченный.")
            return
        if action == "retry" and status == "refund_in_progress":
            amount = float(order.get("refund_due", 0.0)) + float(order.get("escrow", 0.0))
            ok, balance = self.economy.deposit_checked(order.get("player_uuid"), amount, order.get("player_name"))
            if not ok:
                send_message(sender, CompaniesConfig.PREFIX + u"&cПовторный возврат не подтверждён.")
                return
        elif action == "rollback" and status == "payout_in_progress" and company:
            amount = int(order.get("filled_amount", 0))
            subtotal = float(order.get("filled_subtotal", 0.0))
            if amount <= 0 or subtotal <= 0:
                send_message(sender, CompaniesConfig.PREFIX + u"&cВ записи недостаточно данных для отката.")
                return
            if int(company.get("available_shares", 0)) < amount:
                send_message(sender, CompaniesConfig.PREFIX + u"&cОткат невозможен: свободные акции уже изменились. Нужна ручная сверка.")
                return
            company["balance"] = round(float(company.get("balance", 0.0)) + subtotal, 2)
            company["available_shares"] = max(0, int(company.get("available_shares", 0)) - amount)
            self.add_shares(company, order.get("player_uuid"), amount)
        elif action == "retry" and status not in ("refund_in_progress",):
            send_message(sender, CompaniesConfig.PREFIX + u"&cПовтор допустим только для неопределённого возврата.")
            return
        elif action == "rollback" and status != "payout_in_progress":
            send_message(sender, CompaniesConfig.PREFIX + u"&cОткат допустим только для неопределённой выплаты продажи.")
            return
        self.state.data["limit_orders"].pop(str(order_id), None)
        if not self.state.save():
            if company is not None and company_snapshot is not None:
                self.restore_company(company, company_snapshot)
            self.state.data["limit_orders"][str(order_id)] = order_snapshot
            send_message(sender, CompaniesConfig.PREFIX + u"&cРешение не сохранено; проверьте журнал до повторной операции.")
            return
        send_message(sender, CompaniesConfig.PREFIX + u"&aЗаявка №{0} закрыта решением {1}.".format(order_id, action))

    def list_limit_orders(self, sender):
        uuid_str, player_name = get_sender_uuid_and_name(sender)
        orders = [item for item in self.state.data.setdefault("limit_orders", {}).values()
                  if str(item.get("player_uuid")) == str(uuid_str) or is_admin(sender)]
        if not orders:
            send_message(sender, CompaniesConfig.PREFIX + u"&7Лимитных заявок нет.")
            return
        for order in orders[:30]:
            send_message(sender, u"&8- &e#{0} &f{1} &b{2} &7x{3} @ &6{4} &8({5})".format(
                order.get("id"), str(order.get("side", "?")).upper(), order.get("company_name"),
                order.get("amount", 0), format_share_price(order.get("limit_price", 0)), order.get("status", "open")))

    def execute_withdraw(self, player, company, amount, uuid_str, player_name):
        old_price = self.current_price(company)
        op_id = self.state.begin_operation("owner_withdraw", {
            "company": company.get("key"), "owner_uuid": uuid_str, "amount": amount
        })
        if op_id is None:
            send_message(player, CompaniesConfig.PREFIX + u"&cВывод не начат: журнал операций недоступен.")
            return
        snapshot = self.snapshot_company(company)
        company["balance"] = round(float(company.get("balance", 0.0)) - float(amount), 2)
        company["updated_at"] = int(time.time())
        if not self.save_company_change(player, company, snapshot, "owner withdraw"):
            self.state.fail_operation(op_id, "company save failed")
            return
        deposited, balance = self.economy.deposit_checked(uuid_str, amount, player_name)
        if not deposited:
            self.restore_company(company, snapshot)
            if not self.state.save():
                log_info(u"CRITICAL: failed to persist company withdrawal rollback for {0}".format(company.get("name")))
            send_message(player, CompaniesConfig.PREFIX + u"&cВывод отменен: деньги не удалось зачислить.")
            self.state.fail_operation(op_id, "payout failed and company restored")
            return
        self.state.complete_operation(op_id, {"new_balance": company.get("balance")})
        send_message(player, CompaniesConfig.PREFIX + u"&aВы вывели &e{0}&a со счета &b{1}&a. Цена: &f{2} &7→ &c{3}&a.".format(
            format_currency(amount), company.get("name"), format_share_price(old_price), format_share_price(self.current_price(company))
        ))

    def set_dividends(self, player, company_name, raw_value):
        company = self.require_owner(player, company_name)
        if not company:
            return
        snapshot = self.snapshot_company(company)
        if to_unicode(raw_value).lower() in ("off", "0", "disable"):
            company["dividends"] = 0.0
            company["updated_at"] = int(time.time())
            if not self.save_company_change(player, company, snapshot, "disable dividends"):
                return
            send_message(player, CompaniesConfig.PREFIX + u"&7Дивиденды &b{0}&7 выключены.".format(company.get("name")))
            return
        amount = parse_amount(raw_value)
        company["dividends"] = amount
        company["updated_at"] = int(time.time())
        if not self.save_company_change(player, company, snapshot, "set dividends"):
            return
        send_message(player, CompaniesConfig.PREFIX + u"&aДивиденды &b{0}&a: &e{1}&a раз в 24 часа.".format(company.get("name"), format_currency(amount)))

    def rename(self, player, company_name, new_name):
        company = self.require_owner(player, company_name)
        if not company:
            return
        if not self.validate_company_name(new_name) or self.state.find_company(new_name):
            send_message(player, CompaniesConfig.PREFIX + u"&cНазвание занято или некорректно.")
            return
        if self.state.rename_company(company, new_name) is None:
            send_message(player, CompaniesConfig.PREFIX + u"&cПереименование отменено: данные не удалось сохранить.")
            return
        send_message(player, CompaniesConfig.PREFIX + u"&aПредприятие переименовано в &e{0}&a.".format(new_name))

    def description(self, player, company_name, description):
        company = self.require_owner(player, company_name)
        if not company:
            return
        snapshot = self.snapshot_company(company)
        company["description"] = to_unicode(description).strip()[:180]
        company["updated_at"] = int(time.time())
        if not self.save_company_change(player, company, snapshot, "change description"):
            return
        send_message(player, CompaniesConfig.PREFIX + u"&aОписание обновлено.")

    def delete(self, player, company_name):
        company = self.require_owner(player, company_name)
        if not company:
            return
        if sum([int(value) for value in company.get("shares", {}).values()]) > 0:
            send_message(player, CompaniesConfig.PREFIX + u"&cНельзя закрыть предприятие, пока у игроков есть его акции.")
            return
        if float(company.get("balance", 0.0)) > 0.0:
            send_message(player, CompaniesConfig.PREFIX + u"&cПеред закрытием выведите деньги со счета предприятия.")
            return
        if not self.state.delete_company(company):
            send_message(player, CompaniesConfig.PREFIX + u"&cЗакрытие отменено: данные не удалось сохранить.")
            return
        send_message(player, CompaniesConfig.PREFIX + u"&cПредприятие &e{0}&c закрыто. Акции стали недействительными.".format(company.get("name")))

    def transfer(self, sender, company_name, target_name, amount):
        company = self.state.find_company(company_name)
        if not company:
            send_message(sender, CompaniesConfig.PREFIX + u"&cПредприятие не найдено.")
            return
        sender_uuid, sender_name = get_sender_uuid_and_name(sender)
        target = self.resolve_player(target_name)
        if not target:
            send_message(sender, CompaniesConfig.PREFIX + u"&cИгрок не найден в экономике.")
            return
        if str(target.uuid) == str(sender_uuid):
            send_message(sender, CompaniesConfig.PREFIX + u"&cНельзя передать акции самому себе.")
            return
        if str(target.uuid) == str(company.get("owner_uuid")):
            send_message(sender, CompaniesConfig.PREFIX + u"&cВладелец не может получать акции своей компании.")
            return
        if not self.is_tradable(sender, company):
            return
        if self.available_owned_shares(company, sender_uuid) < amount:
            send_message(sender, CompaniesConfig.PREFIX + u"&cНедостаточно акций.")
            return
        snapshot = self.snapshot_company(company)
        self.add_shares(company, sender_uuid, -amount)
        self.add_shares(company, target.uuid, amount)
        if not self.save_company_change(sender, company, snapshot, "share transfer"):
            return
        send_message(sender, CompaniesConfig.PREFIX + u"&aПередано &e{0}&a акций &b{1}&a игроку &e{2}&a.".format(amount, company.get("name"), target.name))
        self.notify(target.name, u"&aВам передали &e{0}&a акций &b{1}&a.".format(amount, company.get("name")))

    def create_offer(self, sender, company_name, target_name, amount, price):
        company = self.state.find_company(company_name)
        if not company:
            send_message(sender, CompaniesConfig.PREFIX + u"&cПредприятие не найдено.")
            return
        sender_uuid, sender_name = get_sender_uuid_and_name(sender)
        target = self.resolve_player(target_name)
        if not target:
            send_message(sender, CompaniesConfig.PREFIX + u"&cИгрок не найден в экономике.")
            return
        if str(target.uuid) == str(sender_uuid):
            send_message(sender, CompaniesConfig.PREFIX + u"&cНельзя продать акции самому себе.")
            return
        if str(target.uuid) == str(company.get("owner_uuid")):
            send_message(sender, CompaniesConfig.PREFIX + u"&cВладелец не может покупать акции своей компании.")
            return
        if not self.is_tradable(sender, company):
            return
        if self.available_owned_shares(company, sender_uuid) < amount:
            send_message(sender, CompaniesConfig.PREFIX + u"&cНедостаточно акций.")
            return
        old_next_offer_id = self.state.data.get("next_offer_id", 1)
        offer_id = self.state.next_offer_id()
        self.state.data.setdefault("offers", {})[offer_id] = {
            "id": offer_id,
            "company_key": company.get("key"),
            "seller_uuid": sender_uuid,
            "seller_name": sender_name,
            "buyer_uuid": str(target.uuid),
            "buyer_name": target.name,
            "amount": int(amount),
            "price": round(float(price), 2),
            "expires_at": int(time.time() + CompaniesConfig.OFFER_TIMEOUT_SECONDS)
        }
        if not self.state.save():
            self.state.data["offers"].pop(offer_id, None)
            self.state.data["next_offer_id"] = old_next_offer_id
            send_message(sender, CompaniesConfig.PREFIX + u"&cПредложение не создано: данные не удалось сохранить.")
            return
        send_message(sender, CompaniesConfig.PREFIX + u"&aПредложение отправлено игроку &e{0}&a.".format(target.name))
        self.send_offer(target.name, offer_id, sender_name, company.get("name"), amount, price)

    def accept_offer(self, player, offer_id):
        uuid_str, player_name = get_sender_uuid_and_name(player)
        offer = self.state.data.setdefault("offers", {}).get(str(offer_id))
        if not offer or str(offer.get("buyer_uuid")) != str(uuid_str):
            send_message(player, CompaniesConfig.PREFIX + u"&cПредложение не найдено.")
            return
        if int(offer.get("expires_at", 0)) < int(time.time()):
            removed, old_offer = self.remove_offer_checked(offer_id)
            if removed:
                send_message(player, CompaniesConfig.PREFIX + u"&cПредложение истекло.")
            else:
                send_message(player, CompaniesConfig.PREFIX + u"&cПредложение истекло, но данные не удалось обновить.")
            return
        company = self.state.find_company(offer.get("company_key"))
        if not company:
            self.remove_offer_checked(offer_id)
            send_message(player, CompaniesConfig.PREFIX + u"&cПредприятие больше не существует.")
            return
        if not self.is_tradable(player, company):
            return
        if str(uuid_str) == str(company.get("owner_uuid")):
            removed, old_offer = self.remove_offer_checked(offer_id)
            if removed:
                send_message(player, CompaniesConfig.PREFIX + u"&cВладелец не может покупать акции своей компании. Предложение отменено.")
            else:
                send_message(player, CompaniesConfig.PREFIX + u"&cПредложение нельзя выполнить или сохранить его отмену.")
            return
        try:
            amount = int(offer.get("amount", 0))
        except Exception:
            amount = 0
        price = safe_float(offer.get("price", 0.0), 0.0, 0.01)
        if amount <= 0 or price <= 0:
            removed, old_offer = self.remove_offer_checked(offer_id)
            if removed:
                send_message(player, CompaniesConfig.PREFIX + u"&cПредложение повреждено и было отменено.")
            else:
                send_message(player, CompaniesConfig.PREFIX + u"&cПредложение повреждено; отмену не удалось сохранить.")
            return
        tax = self.calculate_tax(company, price, "resale")
        total = round(price + tax, 2)
        if self.available_owned_shares(company, offer.get("seller_uuid"), offer_id) < amount:
            send_message(player, CompaniesConfig.PREFIX + u"&cУ продавца уже нет этих акций.")
            return
        if not self.economy.has_enough(uuid_str, total):
            send_message(player, CompaniesConfig.PREFIX + u"&cНужно &e{0}&c с учетом налога.".format(format_currency(total)))
            return
        op_id = self.state.begin_operation("private_offer", {
            "offer_id": str(offer_id), "company": company.get("key"),
            "buyer_uuid": uuid_str, "seller_uuid": offer.get("seller_uuid"),
            "shares": amount, "price": price, "tax": tax
        })
        if op_id is None:
            send_message(player, CompaniesConfig.PREFIX + u"&cСделка не начата: журнал операций недоступен.")
            return
        transferred, buyer_balance, seller_balance = self.economy.transfer(
            uuid_str, offer.get("seller_uuid"), price, offer.get("seller_name")
        )
        if not transferred:
            self.state.fail_operation(op_id, "buyer to seller transfer failed")
            send_message(player, CompaniesConfig.PREFIX + u"&cСделка отменена: перевод продавцу не выполнен.")
            return
        if tax > 0 and not self.economy.withdraw(uuid_str, tax):
            reversed_ok, source_balance, target_balance = self.economy.transfer(
                offer.get("seller_uuid"), uuid_str, price, player_name
            )
            if not reversed_ok:
                log_info(u"CRITICAL: failed to reverse offer transfer {0}".format(offer_id))
            self.state.fail_operation(op_id, "tax withdraw failed")
            send_message(player, CompaniesConfig.PREFIX + u"&cСделка отменена: налог не удалось списать.")
            return
        snapshot = self.snapshot_company(company)
        self.add_shares(company, offer.get("seller_uuid"), -amount)
        self.add_shares(company, uuid_str, amount)
        del self.state.data["offers"][str(offer_id)]
        if not self.state.save():
            self.restore_company(company, snapshot)
            self.state.data["offers"][str(offer_id)] = offer
            reversed_ok, source_balance, target_balance = self.economy.transfer(
                offer.get("seller_uuid"), uuid_str, price, player_name
            )
            if tax > 0:
                self.refund_player(uuid_str, tax, player_name, u"offer persistence rollback")
            if not reversed_ok:
                log_info(u"CRITICAL: failed to reverse offer {0} after company save failure".format(offer_id))
            self.state.fail_operation(op_id, "share state save failed")
            send_message(player, CompaniesConfig.PREFIX + u"&cСделка отменена: данные акций не удалось сохранить.")
            return
        applied_tax = self.collect_town_tax(company, tax, uuid_str, player_name)
        self.state.add_company_history(company, "private_offer", player_name, price, u"shares={0}".format(amount))
        self.state.complete_operation(op_id, {"applied_tax": applied_tax})
        send_message(player, CompaniesConfig.PREFIX + u"&aВы купили &e{0}&a акций &b{1}&a за &e{2}&a. Налог: &6{3}&a.".format(amount, company.get("name"), format_currency(price), format_currency(applied_tax)))
        self.notify(offer.get("seller_name"), u"&aВаши акции &b{0}&a купил &e{1}&a за &e{2}&a.".format(company.get("name"), player_name, format_currency(price)))

    def deny_offer(self, player, offer_id):
        uuid_str, player_name = get_sender_uuid_and_name(player)
        offer = self.state.data.setdefault("offers", {}).get(str(offer_id))
        if offer and str(offer.get("buyer_uuid")) == str(uuid_str):
            removed, old_offer = self.remove_offer_checked(offer_id)
            if not removed:
                send_message(player, CompaniesConfig.PREFIX + u"&cОтказ не удалось сохранить. Попробуйте еще раз.")
                return
            send_message(player, CompaniesConfig.PREFIX + u"&7Предложение отклонено.")
            self.notify(offer.get("seller_name"), u"&7Игрок &e{0}&7 отклонил покупку акций.".format(player_name))
        else:
            send_message(player, CompaniesConfig.PREFIX + u"&cПредложение не найдено.")

    def process_limit_orders(self):
        for order_id, order in list(self.state.data.setdefault("limit_orders", {}).items()):
            company = self.state.find_company(order.get("company_key"))
            if (not company or company.get("bankrupt") or int(order.get("amount", 0)) <= 0 or
                    str(order.get("status", "open")) != "open"):
                continue
            amount = int(order.get("amount", 0))
            limit_price = float(order.get("limit_price", 0.0))
            price = self.current_price(company)
            if order.get("side") == "buy":
                if price > limit_price or amount > int(company.get("available_shares", 0)):
                    continue
                subtotal = self.marginal_buy_cost(company, amount)
                tax = self.calculate_tax(company, subtotal, "primary")
                total = round(subtotal + tax, 2)
                escrow = float(order.get("escrow", 0.0))
                if subtotal > round(amount * limit_price, 2) or total > escrow:
                    continue
                order["status"] = "processing_buy"
                if not self.state.save():
                    order["status"] = "open"
                    continue
                snapshot = self.snapshot_company(company)
                company["balance"] = round(float(company.get("balance", 0.0)) + subtotal, 2)
                company["available_shares"] = int(company.get("available_shares", 0)) - amount
                self.add_shares(company, order.get("player_uuid"), amount)
                self.state.add_company_history(company, "limit_buy", order.get("player_name"), total, u"shares={0}".format(amount))
                order["amount"] = 0
                order["filled_amount"] = amount
                order["escrow"] = 0.0
                order["refund_due"] = round(escrow - total, 2)
                order["status"] = "filled_tax_pending"
                if not self.state.save():
                    self.restore_company(company, snapshot)
                    order["amount"] = amount
                    order["filled_amount"] = 0
                    order["escrow"] = escrow
                    order["refund_due"] = 0.0
                    order["status"] = "open"
                    self.state.save()
                    continue
                applied_tax = self.collect_town_tax(company, tax)
                refund = round(escrow - subtotal - applied_tax, 2)
                order["refund_due"] = refund
                if refund > 0:
                    order["status"] = "refund_in_progress"
                    if not self.state.save():
                        continue
                    ok, balance = self.economy.deposit_checked(order.get("player_uuid"), refund, order.get("player_name"))
                    if not ok:
                        order["status"] = "filled_refund_due"
                        self.state.save()
                        continue
                    order["refund_due"] = 0.0
                    order["status"] = "refund_paid"
                    if not self.state.save():
                        continue
                self.state.data["limit_orders"].pop(order_id, None)
                self.state.save()
                self.notify(order.get("player_name"), u"&aИсполнена лимитная покупка №{0}: &e{1}&a акций &b{2}&a.".format(
                    order_id, amount, company.get("name")))
            elif order.get("side") == "sell":
                if price < limit_price or self.owned_shares(company, order.get("player_uuid")) < amount:
                    continue
                subtotal = self.marginal_sell_value(company, amount)
                if subtotal > float(company.get("balance", 0.0)):
                    continue
                tax = self.calculate_tax(company, subtotal, "resale")
                payout = round(subtotal - tax, 2)
                order["status"] = "processing_sell"
                if not self.state.save():
                    order["status"] = "open"
                    continue
                snapshot = self.snapshot_company(company)
                company["balance"] = round(float(company.get("balance", 0.0)) - subtotal, 2)
                company["available_shares"] = min(CompaniesConfig.SHARES_TOTAL, int(company.get("available_shares", 0)) + amount)
                self.add_shares(company, order.get("player_uuid"), -amount)
                self.state.add_company_history(company, "limit_sell", order.get("player_name"), payout, u"shares={0}".format(amount))
                order["amount"] = 0
                order["filled_amount"] = amount
                order["filled_subtotal"] = subtotal
                order["payout"] = payout
                order["tax"] = tax
                order["status"] = "payout_in_progress"
                if not self.state.save():
                    self.restore_company(company, snapshot)
                    order["amount"] = amount
                    order["filled_amount"] = 0
                    order["status"] = "open"
                    self.state.save()
                    continue
                ok, balance = self.economy.deposit_checked(order.get("player_uuid"), payout, order.get("player_name"))
                if not ok:
                    self.restore_company(company, snapshot)
                    order["amount"] = amount
                    order["filled_amount"] = 0
                    order["status"] = "open"
                    self.state.save()
                    continue
                self.collect_town_tax(company, tax, order.get("player_uuid"), order.get("player_name"))
                order["status"] = "payout_paid"
                if not self.state.save():
                    continue
                self.state.data["limit_orders"].pop(order_id, None)
                self.state.save()
                self.notify(order.get("player_name"), u"&aИсполнена лимитная продажа №{0}: &e{1}&a акций &b{2}&a.".format(
                    order_id, amount, company.get("name")))

    def process_dividends(self):
        now = int(time.time())
        self.process_limit_orders()
        # Истёкшие офферы освобождают зарезервированные акции.
        expired_offers = [oid for oid, offer in self.state.data.setdefault("offers", {}).items()
                          if int(offer.get("expires_at", 0)) < now]
        for offer_id in expired_offers:
            self.state.data["offers"].pop(offer_id, None)
        expired_votes = [vid for vid, vote in self.state.data.setdefault("withdraw_votes", {}).items()
                         if int(vote.get("expires_at", 0)) < now]
        for vote_id in expired_votes:
            self.state.data["withdraw_votes"].pop(vote_id, None)
        if expired_offers or expired_votes:
            self.state.save()
        for company in self.state.list_companies():
            dividends = safe_float(company.get("dividends", 0.0), 0.0, 0.0)
            if company.get("bankrupt") or dividends <= 0 or int(company.get("next_dividend_at", 0)) > now:
                continue
            op_id = self.state.begin_operation("dividends", {
                "company": company.get("key"), "pool": dividends,
                "shareholders": copy.deepcopy(company.get("shares", {}))
            })
            if op_id is None:
                continue
            snapshot = self.snapshot_company(company)
            company["next_dividend_at"] = now + CompaniesConfig.DIVIDEND_INTERVAL_SECONDS
            if float(company.get("balance", 0.0)) < dividends:
                if not self.state.save():
                    self.restore_company(company, snapshot)
                self.state.fail_operation(op_id, "insufficient company balance")
                continue
            total_owned = sum([int(v) for v in company.get("shares", {}).values()])
            if total_owned <= 0:
                if not self.state.save():
                    self.restore_company(company, snapshot)
                self.state.fail_operation(op_id, "no shareholders")
                continue
            tax = self.calculate_tax(company, dividends, "dividends")
            pool = round(dividends - tax, 2)
            company["balance"] = round(float(company.get("balance", 0.0)) - dividends, 2)
            company["updated_at"] = now
            if not self.state.save():
                self.restore_company(company, snapshot)
                log_info(u"Dividend skipped for {0}: company state could not be saved".format(company.get("name")))
                self.state.fail_operation(op_id, "company save failed")
                continue
            payouts = []
            for uuid_str, shares in company.get("shares", {}).items():
                payout = round(pool * float(shares) / float(total_owned), 2)
                if payout > 0:
                    payouts.append([uuid_str, payout])
            if payouts:
                rounding_delta = round(pool - sum([item[1] for item in payouts]), 2)
                payouts[0][1] = round(payouts[0][1] + rounding_delta, 2)
            unpaid = round(pool - sum([item[1] for item in payouts]), 2)
            paid = 0.0
            for uuid_str, payout in payouts:
                deposited, balance = self.economy.deposit_checked(uuid_str, payout, u"Investor")
                if deposited:
                    paid = round(paid + payout, 2)
                else:
                    unpaid = round(unpaid + payout, 2)
                    log_info(u"Dividend credit failed for {0} in {1}".format(uuid_str, company.get("name")))
            applied_tax = self.collect_town_tax(company, tax)
            unpaid = round(unpaid + (tax - applied_tax), 2)
            if unpaid > 0:
                company["balance"] = round(float(company.get("balance", 0.0)) + unpaid, 2)
                if not self.state.save():
                    log_info(u"CRITICAL: failed to return unpaid dividends to {0}, amount={1}".format(company.get("name"), unpaid))
            self.state.add_company_history(
                company, "dividends", u"System", paid,
                u"Налог городу: {0}; невыплачено: {1}".format(applied_tax, unpaid))
            self.state.complete_operation(op_id, {
                "paid": paid, "town_tax": applied_tax, "unpaid_returned": unpaid
            })
            broadcast_company(u"&7Компания &b{0}&7 выплатила дивиденды &e{1}&7. Налог города: &6{2}&7.".format(company.get("name"), format_currency(paid), format_currency(applied_tax)))

    def calculate_tax(self, company, amount, operation):
        percent = self.towns.get_tax_percent(company.get("town"), operation)
        return min(round(float(amount), 2), max(0.0, round(float(amount) * float(percent) / 100.0, 2)))

    def require_owner(self, player, company_name):
        uuid_str, player_name = get_sender_uuid_and_name(player)
        company = self.state.find_company(company_name)
        if not company:
            send_message(player, CompaniesConfig.PREFIX + u"&cПредприятие не найдено.")
            return None
        if str(company.get("owner_uuid")) != str(uuid_str) and not is_admin(player):
            send_message(player, CompaniesConfig.PREFIX + u"&cЭто доступно только владельцу предприятия.")
            return None
        return company

    def resolve_player(self, name):
        if BUKKIT_AVAILABLE:
            try:
                player = Bukkit.getPlayer(to_java_string(name))
                if player and player.isOnline():
                    uuid_str, player_name = get_sender_uuid_and_name(player)
                    return self.economy.get_or_create(uuid_str, player_name)
            except Exception:
                pass
        return self.economy.get_by_name(name)

    def notify(self, name, message):
        if not BUKKIT_AVAILABLE:
            return
        try:
            player = Bukkit.getPlayer(to_java_string(name))
            if player and player.isOnline():
                send_message(player, CompaniesConfig.PREFIX + message)
        except Exception:
            pass

    def send_offer(self, target_name, offer_id, seller_name, company_name, amount, price):
        if not BUKKIT_AVAILABLE:
            return
        try:
            player = Bukkit.getPlayer(to_java_string(target_name))
            if not player or not player.isOnline():
                return
            from net.md_5.bungee.api.chat import TextComponent, ClickEvent, HoverEvent, ComponentBuilder
            message = TextComponent(colorize(
                CompaniesConfig.PREFIX + u"&e{0} &7предлагает купить &e{1}&7 акций &b{2}&7 за &e{3}&7.\n".format(
                    seller_name, amount, company_name, format_currency(price)
                ) + CompaniesConfig.PREFIX + u"&7Выберите действие: "
            ))
            accept = TextComponent(colorize(u"&a&l[ПРИНЯТЬ]"))
            accept.setClickEvent(ClickEvent(ClickEvent.Action.RUN_COMMAND, u"/shares accept {0}".format(offer_id)))
            accept.setHoverEvent(HoverEvent(HoverEvent.Action.SHOW_TEXT, ComponentBuilder(colorize(u"&aКупить акции")).create()))
            deny = TextComponent(colorize(u"&c&l[ОТКЛОНИТЬ]"))
            deny.setClickEvent(ClickEvent(ClickEvent.Action.RUN_COMMAND, u"/shares deny {0}".format(offer_id)))
            deny.setHoverEvent(HoverEvent(HoverEvent.Action.SHOW_TEXT, ComponentBuilder(colorize(u"&cОтклонить сделку")).create()))
            message.addExtra(accept)
            message.addExtra(TextComponent(colorize(u"   ")))
            message.addExtra(deny)
            player.spigot().sendMessage(message)
        except Exception:
            self.notify(target_name, u"&7Предложение акций. Принять: &e/shares accept {0}&7, отказ: &e/shares deny {0}".format(offer_id))


def broadcast_company(message):
    line = colorize(CompaniesConfig.PREFIX + message)
    if BUKKIT_AVAILABLE:
        try:
            Bukkit.broadcastMessage(to_java_string(line))
            return
        except Exception:
            pass
    print("[SmartY-Companies] " + to_unicode(line))


class CreateSession(object):
    def __init__(self, company_type):
        self.company_type = company_type
        self.step = "name"
        self.name = None
        self.description = None


class ActionSession(object):
    def __init__(self, action, company_key):
        self.action = action
        self.company_key = company_key
        self.step = "value"
        self.target = None
        self.amount = 0


create_sessions = {}


def start_action_session(player, action, company_key):
    uuid_str, name = get_sender_uuid_and_name(player)
    if not uuid_str:
        return
    session = ActionSession(action, company_key)
    create_sessions[uuid_str] = session
    player.closeInventory()
    prompts = {
        "buy": u"&7Сколько акций купить? Напишите число в чат. Отмена: &eотмена&7.",
        "deposit": u"&7Сколько пополнить на счет компании? Отмена: &eотмена&7.",
        "withdraw": u"&7Сколько вывести со счета компании? Отмена: &eотмена&7.",
        "dividends": u"&7Введите сумму дивидендов или &eoff&7. Отмена: &eотмена&7.",
        "rename": u"&7Введите новое название предприятия. Отмена: &eотмена&7.",
        "description": u"&7Введите новое описание предприятия. Отмена: &eотмена&7.",
        "delete": u"&cЗакрытие удалит счет и акции. Напишите &eподтвердить&c или &eотмена&c.",
        "transfer": u"&7Кому передать акции? Напишите ник игрока. Отмена: &eотмена&7.",
        "sell": u"&7Кому продать акции? Напишите ник игрока. Отмена: &eотмена&7.",
        "market_sell": u"&7Сколько акций продать на бирже? Отмена: &eотмена&7."
    }
    send_message(player, CompaniesConfig.PREFIX + prompts.get(action, u"&7Введите значение. Отмена: &eотмена&7."))


def handle_action_session(player, session, text):
    action = session.action
    company_key = session.company_key
    try:
        if action == "buy":
            service.buy_primary(player, company_key, parse_int(text))
            return True
        if action == "market_sell":
            service.sell_to_market(player, company_key, parse_int(text))
            return True
        if action == "deposit":
            service.deposit(player, company_key, parse_amount(text))
            return True
        if action == "withdraw":
            service.withdraw(player, company_key, parse_amount(text))
            return True
        if action == "dividends":
            service.set_dividends(player, company_key, text)
            return True
        if action == "rename":
            service.rename(player, company_key, text)
            return True
        if action == "description":
            service.description(player, company_key, text)
            return True
        if action == "delete":
            if text.lower() in (u"подтвердить", u"confirm", u"yes", u"да"):
                service.delete(player, company_key)
            else:
                send_message(player, CompaniesConfig.PREFIX + u"&7Закрытие предприятия отменено.")
            return True
        if action in ("transfer", "sell"):
            if session.step == "value":
                session.target = text
                session.step = "amount"
                send_message(player, CompaniesConfig.PREFIX + u"&7Сколько акций? Напишите число. Отмена: &eотмена&7.")
                return False
            if session.step == "amount":
                session.amount = parse_int(text)
                if action == "transfer":
                    service.transfer(player, company_key, session.target, session.amount)
                    return True
                session.step = "price"
                send_message(player, CompaniesConfig.PREFIX + u"&7За какую общую цену продать пакет акций? Отмена: &eотмена&7.")
                return False
            if session.step == "price":
                service.create_offer(player, company_key, session.target, session.amount, parse_amount(text))
                return True
    except ValueError:
        send_message(player, CompaniesConfig.PREFIX + u"&cНекорректное число. Попробуйте еще раз или напишите &eотмена&c.")
        return False
    return True


def create_gui_item(material_name, title, lore=None, fallback="PAPER"):
    if not BUKKIT_AVAILABLE or ItemStack is None:
        return None
    try:
        material = Material.valueOf(material_name)
    except Exception:
        material = Material.valueOf(fallback)
    item = ItemStack(material, 1)
    meta = item.getItemMeta()
    if meta:
        meta.setDisplayName(to_java_string(colorize(title)))
        if lore:
            meta.setLore(build_java_list([colorize(line) for line in lore]))
        item.setItemMeta(meta)
    return item


class CompanyInventoryHolder(InventoryHolder):
    def __init__(self, gui):
        self.gui = gui

    def getInventory(self):
        return self.gui.inventory


class BaseCompanyGUI(object):
    def __init__(self, player, title, rows=6):
        self.player = player
        self.title = colorize(title)
        self.size = max(1, min(6, int(rows))) * 9
        self.holder = CompanyInventoryHolder(self)
        self.inventory = Bukkit.createInventory(self.holder, self.size, to_java_string(self.title)) if BUKKIT_AVAILABLE else None

    def open(self):
        if self.inventory:
            self.build()
            self.player.openInventory(self.inventory)

    def build(self):
        pass

    def set_item(self, slot, material, title, lore=None, fallback="PAPER"):
        item = create_gui_item(material, title, lore, fallback)
        if item:
            self.inventory.setItem(int(slot), item)

    def handle_click(self, player, raw_slot, click_type):
        pass


class CompanyListGUI(BaseCompanyGUI):
    def __init__(self, player, page=1, mode="all"):
        self.page = max(1, int(page))
        self.mode = mode
        BaseCompanyGUI.__init__(self, player, u"&3&lКаталог предприятий", 6)

    def filtered(self):
        uuid_str, name = get_sender_uuid_and_name(self.player)
        companies = state.list_companies()
        if self.mode == "mine":
            return [c for c in companies if str(c.get("owner_uuid")) == str(uuid_str)]
        if self.mode == "invest":
            return [c for c in companies if int(c.get("shares", {}).get(str(uuid_str), 0)) > 0]
        return companies

    def build(self):
        self.inventory.clear()
        companies = self.filtered()
        total_pages = max(1, int((len(companies) + CompaniesConfig.LIST_PAGE_SIZE - 1) / CompaniesConfig.LIST_PAGE_SIZE))
        self.page = min(self.page, total_pages)
        chunk = companies[(self.page - 1) * CompaniesConfig.LIST_PAGE_SIZE:self.page * CompaniesConfig.LIST_PAGE_SIZE]
        for index, company in enumerate(chunk):
            price = service.current_price(company)
            lore = wrap_lore_text(company.get("description"), u"&7", 36) + [
                u"&7Владелец: &f{0}".format(company.get("owner_name")),
                u"&7Город: &e{0}".format(company.get("town")),
                u"&7Тип: &f{0}".format(service.type_label(company.get("type"))),
                u"&7Цена акции: &a{0}".format(format_share_price(price)),
                u"&7Капитализация акций: &6{0}".format(format_currency(service.market_cap(company))),
                u"&7Свободно: &e{0}".format(company.get("available_shares")),
                u"&7Счет: &6{0}".format(format_currency(company.get("balance", 0.0))),
                u"&eНажмите, чтобы открыть"
            ]
            self.set_item(index, "EMERALD", u"&b{0}".format(company.get("name")), lore, "PAPER")
        self.set_item(45, "BOOK", u"&fВсе", [u"&7Показать все предприятия"], "PAPER")
        self.set_item(46, "PLAYER_HEAD", u"&aМои компании", [u"&7Где вы владелец"], "PLAYER_HEAD")
        self.set_item(47, "CHEST", u"&eМои инвестиции", [u"&7Где у вас есть акции"], "CHEST")
        if self.page > 1:
            self.set_item(48, "ARROW", u"&aПредыдущая", [u"&7Страница {0}".format(self.page - 1)], "PAPER")
        self.set_item(49, "MAP", u"&eСтраница {0}/{1}".format(self.page, total_pages), None, "PAPER")
        if self.page < total_pages:
            self.set_item(50, "ARROW", u"&aСледующая", [u"&7Страница {0}".format(self.page + 1)], "PAPER")
        self.set_item(53, "WRITABLE_BOOK", u"&aСоздать", [u"&7/company create"], "BOOK")

    def handle_click(self, player, raw_slot, click_type):
        if raw_slot == 45:
            CompanyListGUI(player, 1, "all").open()
        elif raw_slot == 46:
            CompanyListGUI(player, 1, "mine").open()
        elif raw_slot == 47:
            CompanyListGUI(player, 1, "invest").open()
        elif raw_slot == 48 and self.page > 1:
            CompanyListGUI(player, self.page - 1, self.mode).open()
        elif raw_slot == 50:
            CompanyListGUI(player, self.page + 1, self.mode).open()
        elif raw_slot == 53:
            CompanyTypeGUI(player).open()
        elif 0 <= raw_slot < 45:
            companies = self.filtered()
            idx = (self.page - 1) * CompaniesConfig.LIST_PAGE_SIZE + raw_slot
            if idx < len(companies):
                CompanyInfoGUI(player, companies[idx].get("key")).open()


class CompanyTypeGUI(BaseCompanyGUI):
    def __init__(self, player):
        BaseCompanyGUI.__init__(self, player, u"&3&lТип предприятия", 3)

    def build(self):
        self.inventory.clear()
        slots = [10, 11, 12, 13, 14, 15, 16, 21]
        for index, item in enumerate(CompaniesConfig.COMPANY_TYPES):
            type_key, label, material = item
            self.set_item(slots[index], material, u"&b{0}".format(label), [u"&7Выбрать тип", u"&eНажмите"], "PAPER")

    def handle_click(self, player, raw_slot, click_type):
        slots = [10, 11, 12, 13, 14, 15, 16, 21]
        if raw_slot in slots:
            item = CompaniesConfig.COMPANY_TYPES[slots.index(raw_slot)]
            uuid_str, name = get_sender_uuid_and_name(player)
            create_sessions[uuid_str] = CreateSession(item[0])
            player.closeInventory()
            send_message(player, CompaniesConfig.PREFIX + u"&7Введите название предприятия в чат. Для отмены: &eотмена&7.")


class CompanyInfoGUI(BaseCompanyGUI):
    def __init__(self, player, company_key):
        self.company_key = company_key
        BaseCompanyGUI.__init__(self, player, u"&3&lПредприятие", 6)

    def get_company(self):
        return state.find_company(self.company_key)

    def buy_lore(self, company, amount):
        price = service.current_price(company)
        subtotal = service.marginal_buy_cost(company, int(amount))
        tax = service.calculate_tax(company, subtotal, "primary")
        total = round(subtotal + tax, 2)
        return [
            u"&7Первичные акции",
            u"&7Цена акции: &a{0}".format(format_share_price(price)),
            u"&7Акций: &e{0}".format(amount),
            u"&7Стоимость: &6{0}".format(format_currency(subtotal)),
            u"&7Налог города: &6{0}".format(format_currency(tax)),
            u"&7К оплате: &a{0}".format(format_currency(total))
        ]

    def sell_lore(self, company, amount):
        price = service.current_price(company)
        subtotal = service.marginal_sell_value(company, int(amount))
        tax = service.calculate_tax(company, subtotal, "resale")
        payout = round(subtotal - tax, 2)
        lore = [
            u"&7Выкуп по текущей цене акции",
            u"&7Цена акции: &a{0}".format(format_share_price(price)),
            u"&7Акций: &e{0}".format(amount),
            u"&7Сумма продажи: &6{0}".format(format_currency(subtotal)),
            u"&7Налог города: &6{0}".format(format_currency(tax)),
            u"&7Вы получите: &a{0}".format(format_currency(payout))
        ]
        if subtotal > float(company.get("balance", 0.0)):
            lore.append(u"&cНа счете компании недостаточно денег для выкупа")
        return lore

    def build(self):
        self.inventory.clear()
        company = self.get_company()
        if not company:
            self.set_item(22, "BARRIER", u"&cПредприятие не найдено", None, "PAPER")
            return
        uuid_str, name = get_sender_uuid_and_name(self.player)
        owned = service.owned_shares(company, uuid_str)
        price = service.current_price(company)
        info_lore = [
            u"&7Владелец: &f{0}".format(company.get("owner_name")),
            u"&7Город: &e{0}".format(company.get("town")),
            u"&7Тип: &f{0}".format(service.type_label(company.get("type"))),
            u"&7Цена акции: &a{0}".format(format_share_price(price)),
            u"&7Капитализация акций: &6{0}".format(format_currency(service.market_cap(company))),
            u"&7Свободно: &e{0}".format(company.get("available_shares")),
            u"&7Ваши акции: &b{0}".format(owned),
            u"&7Дивиденды: &6{0}".format(format_currency(company.get("dividends", 0.0))),
            u"&7Счет: &6{0}".format(format_currency(company.get("balance", 0.0)))
        ]
        self.set_item(4, "PAPER", u"&b&l{0}".format(company.get("name")), info_lore, "BOOK")
        self.set_item(13, "WRITABLE_BOOK", u"&bОписание", wrap_lore_text(company.get("description"), u"&7", 36), "BOOK")
        self.set_item(20, "EMERALD", u"&aКупить 1", self.buy_lore(company, 1), "PAPER")
        self.set_item(21, "EMERALD_BLOCK", u"&aКупить 10", self.buy_lore(company, 10), "EMERALD")
        self.set_item(22, "DIAMOND", u"&aКупить 100", self.buy_lore(company, 100), "EMERALD")
        self.set_item(23, "WRITABLE_BOOK", u"&aКупить другое количество", [u"&7Введите количество в чат"], "BOOK")
        self.set_item(29, "GOLD_NUGGET", u"&6Продать 1", self.sell_lore(company, 1), "GOLD_INGOT")
        self.set_item(30, "GOLD_INGOT", u"&6Продать 10", self.sell_lore(company, 10), "EMERALD")
        self.set_item(31, "GOLD_BLOCK", u"&6Продать 100", self.sell_lore(company, 100), "GOLD_INGOT")
        self.set_item(32, "WRITABLE_BOOK", u"&6Продать другое количество", [u"&7Выкуп по текущей цене акции", u"&7Введите количество в чат"], "BOOK")
        self.set_item(33, "CHEST", u"&eПередать акции", [u"&7Выбор игрока и количества через чат"], "PAPER")
        self.set_item(34, "PAPER", u"&eПродать игроку", [u"&7Игрок, количество и цена через чат"], "PAPER")
        if str(company.get("owner_uuid")) == str(uuid_str) or is_admin(self.player):
            self.set_item(38, "GOLD_INGOT", u"&6Пополнить счет", [u"&7Введите сумму в чат"], "PAPER")
            self.set_item(39, "HOPPER", u"&cВывести деньги", [u"&7Введите сумму в чат"], "PAPER")
            self.set_item(40, "SUNFLOWER", u"&eДивиденды", [u"&7Введите сумму или off в чат"], "PAPER")
            self.set_item(41, "NAME_TAG", u"&bПереименовать", [u"&7Введите новое название в чат"], "PAPER")
            self.set_item(42, "WRITABLE_BOOK", u"&bОписание", [u"&7Введите новый текст в чат"], "BOOK")
            self.set_item(43, "BARRIER", u"&cЗакрыть", [u"&7Подтверждение через чат"], "PAPER")
        self.set_item(49, "ARROW", u"&7Назад", [u"&eКаталог"], "PAPER")

    def handle_click(self, player, raw_slot, click_type):
        company = self.get_company()
        if not company:
            return
        if raw_slot == 20:
            service.buy_primary(player, company.get("key"), 1)
            CompanyInfoGUI(player, company.get("key")).open()
        elif raw_slot == 21:
            service.buy_primary(player, company.get("key"), 10)
            CompanyInfoGUI(player, company.get("key")).open()
        elif raw_slot == 22:
            service.buy_primary(player, company.get("key"), 100)
            CompanyInfoGUI(player, company.get("key")).open()
        elif raw_slot == 23:
            start_action_session(player, "buy", company.get("key"))
        elif raw_slot == 29:
            service.sell_to_market(player, company.get("key"), 1)
            CompanyInfoGUI(player, company.get("key")).open()
        elif raw_slot == 30:
            service.sell_to_market(player, company.get("key"), 10)
            CompanyInfoGUI(player, company.get("key")).open()
        elif raw_slot == 31:
            service.sell_to_market(player, company.get("key"), 100)
            CompanyInfoGUI(player, company.get("key")).open()
        elif raw_slot == 32:
            uuid_str, name = get_sender_uuid_and_name(player)
            if service.owned_shares(company, uuid_str) <= 0:
                send_message(player, CompaniesConfig.PREFIX + u"&cУ вас нет акций этого предприятия.")
                return
            start_action_session(player, "market_sell", company.get("key"))
        elif raw_slot == 33:
            uuid_str, name = get_sender_uuid_and_name(player)
            if service.owned_shares(company, uuid_str) <= 0:
                send_message(player, CompaniesConfig.PREFIX + u"&cУ вас нет акций этого предприятия.")
                return
            start_action_session(player, "transfer", company.get("key"))
        elif raw_slot == 34:
            uuid_str, name = get_sender_uuid_and_name(player)
            if service.owned_shares(company, uuid_str) <= 0:
                send_message(player, CompaniesConfig.PREFIX + u"&cУ вас нет акций этого предприятия.")
                return
            start_action_session(player, "sell", company.get("key"))
        elif raw_slot in (38, 39, 40, 41, 42, 43):
            uuid_str, name = get_sender_uuid_and_name(player)
            if str(company.get("owner_uuid")) != str(uuid_str) and not is_admin(player):
                return
            actions = {38: "deposit", 39: "withdraw", 40: "dividends", 41: "rename", 42: "description", 43: "delete"}
            start_action_session(player, actions[raw_slot], company.get("key"))
        elif raw_slot == 49:
            CompanyListGUI(player).open()


class SharesPortfolioGUI(BaseCompanyGUI):
    def __init__(self, player, page=1):
        self.page = max(1, int(page))
        BaseCompanyGUI.__init__(self, player, u"&3&lПортфель акций", 6)

    def holdings(self):
        uuid_str, name = get_sender_uuid_and_name(self.player)
        result = []
        for company in state.list_companies():
            amount = service.owned_shares(company, uuid_str)
            if amount > 0:
                result.append((company, amount))
        return result

    def build(self):
        self.inventory.clear()
        holdings = self.holdings()
        total_pages = max(1, int((len(holdings) + CompaniesConfig.LIST_PAGE_SIZE - 1) / CompaniesConfig.LIST_PAGE_SIZE))
        self.page = min(self.page, total_pages)
        total_value = 0.0
        for company, amount in holdings:
            total_value += service.current_price(company) * amount
        self.set_item(49, "MAP", u"&bСводка", [u"&7Позиций: &e{0}".format(len(holdings)), u"&7Стоимость портфеля: &6{0}".format(format_currency(total_value))], "PAPER")
        chunk = holdings[(self.page - 1) * CompaniesConfig.LIST_PAGE_SIZE:self.page * CompaniesConfig.LIST_PAGE_SIZE]
        for index, item in enumerate(chunk):
            company, amount = item
            price = service.current_price(company)
            total = round(price * amount, 2)
            self.set_item(index, "EMERALD", u"&b{0}".format(company.get("name")), [
                u"&7Акций: &e{0}".format(amount),
                u"&7Цена одной: &a{0}".format(format_share_price(price)),
                u"&7Стоимость пакета: &6{0}".format(format_currency(total)),
                u"&7Город: &f{0}".format(company.get("town")),
                u"&eНажмите, чтобы открыть"
            ], "PAPER")
        if not holdings:
            self.set_item(22, "BARRIER", u"&7Акций пока нет", [u"&7Откройте /companies"], "PAPER")
        if self.page > 1:
            self.set_item(48, "ARROW", u"&aПредыдущая", [u"&7Страница {0}".format(self.page - 1)], "PAPER")
        if self.page < total_pages:
            self.set_item(50, "ARROW", u"&aСледующая", [u"&7Страница {0}".format(self.page + 1)], "PAPER")

    def handle_click(self, player, raw_slot, click_type):
        if raw_slot == 48 and self.page > 1:
            SharesPortfolioGUI(player, self.page - 1).open()
        elif raw_slot == 50:
            SharesPortfolioGUI(player, self.page + 1).open()
        elif 0 <= raw_slot < 45:
            holdings = self.holdings()
            idx = (self.page - 1) * CompaniesConfig.LIST_PAGE_SIZE + raw_slot
            if idx < len(holdings):
                CompanyInfoGUI(player, holdings[idx][0].get("key")).open()


class CompaniesCommand(object):
    def execute_companies(self, sender, label, args):
        if not hasattr(sender, "openInventory"):
            self.send_list(sender)
            return True
        CompanyListGUI(sender, 1, "all").open()
        return True

    def execute_company(self, sender, label, args):
        args = list(args)
        if not args and hasattr(sender, "openInventory"):
            CompanyListGUI(sender, 1, "mine").open()
            return True
        sub = args[0].lower() if args else "help"
        try:
            if sub == "help":
                self.send_help(sender)
            elif sub == "create":
                if len(args) >= 5:
                    service.create_company(sender, args[1], u" ".join(args[4:]), args[2].lower(), parse_amount(args[3]))
                elif hasattr(sender, "openInventory"):
                    CompanyTypeGUI(sender).open()
                else:
                    self.send_help(sender)
            elif sub in ("open", "info") and len(args) >= 2:
                if hasattr(sender, "openInventory"):
                    CompanyInfoGUI(sender, args[1]).open()
                else:
                    self.send_company_info(sender, args[1])
            elif sub == "buy" and len(args) >= 3:
                service.buy_primary(sender, args[1], parse_int(args[2]))
            elif sub == "deposit" and len(args) >= 3:
                service.deposit(sender, args[1], parse_amount(args[2]))
            elif sub == "withdraw" and len(args) >= 3:
                service.withdraw(sender, args[1], parse_amount(args[2]))
            elif sub == "dividends" and len(args) >= 3:
                service.set_dividends(sender, args[1], args[2])
            elif sub == "rename" and len(args) >= 3:
                service.rename(sender, args[1], u" ".join(args[2:]))
            elif sub == "description" and len(args) >= 3:
                service.description(sender, args[1], u" ".join(args[2:]))
            elif sub == "delete" and len(args) >= 2:
                if len(args) >= 3 and args[2].lower() == "confirm":
                    service.delete(sender, args[1])
                else:
                    send_message(sender, CompaniesConfig.PREFIX + u"&cЗакрытие удалит счет и все акции. Подтвердите: &e/company delete {0} confirm".format(args[1]))
            elif sub == "bankrupt" and len(args) >= 3 and args[2].lower() == "confirm":
                service.set_bankrupt(sender, args[1])
            elif sub == "history" and len(args) >= 2:
                service.show_history(sender, args[1])
            elif sub == "chart" and len(args) >= 2:
                service.show_chart(sender, args[1])
            elif sub == "journal" and is_admin(sender):
                self.send_journal(sender)
            else:
                self.send_help(sender)
        except ValueError:
            send_message(sender, CompaniesConfig.PREFIX + u"&cНекорректное число.")
        return True

    def execute_shares(self, sender, label, args):
        args = list(args)
        if not args and hasattr(sender, "openInventory"):
            SharesPortfolioGUI(sender).open()
            return True
        sub = args[0].lower() if args else "list"
        try:
            if sub == "list":
                self.send_shares(sender)
            elif sub == "give" and len(args) >= 4:
                service.transfer(sender, args[1], args[2], parse_int(args[3]))
            elif sub == "sell" and len(args) >= 5:
                service.create_offer(sender, args[1], args[2], parse_int(args[3]), parse_amount(args[4]))
            elif sub in ("market", "sellmarket") and len(args) >= 3:
                service.sell_to_market(sender, args[1], parse_int(args[2]))
            elif sub == "accept" and len(args) >= 2:
                service.accept_offer(sender, args[1])
            elif sub == "deny" and len(args) >= 2:
                service.deny_offer(sender, args[1])
            elif sub == "vote" and len(args) >= 3:
                service.vote_withdraw(sender, args[1], args[2].lower())
            elif sub == "limit" and len(args) >= 5:
                service.create_limit_order(sender, args[1], args[2], parse_int(args[3]), parse_amount(args[4]))
            elif sub == "orders":
                service.list_limit_orders(sender)
            elif sub == "cancel" and len(args) >= 2:
                service.cancel_limit_order(sender, args[1])
            elif sub == "resolve" and len(args) >= 3:
                service.resolve_limit_order(sender, args[1], args[2])
            else:
                self.send_shares_help(sender)
        except ValueError:
            send_message(sender, CompaniesConfig.PREFIX + u"&cНекорректное число.")
        return True

    def send_help(self, sender):
        send_message(sender, CompaniesConfig.PREFIX + u"&e/company create &7- создать предприятие через GUI")
        send_message(sender, u"&e/company open <компания> &7- открыть предприятие")
        send_message(sender, u"&e/company buy <компания> <акции> &7- купить первичные акции")
        send_message(sender, u"&e/company deposit/withdraw <компания> <сумма> &7- счет владельца")
        send_message(sender, u"&e/company dividends <компания> <сумма|off> &7- дивиденды")
        send_message(sender, u"&e/company rename/description/delete <компания> ... &7- управление")
        send_message(sender, u"&e/company history/chart <компания> &7- аудит и дневные OHLC")
        send_message(sender, u"&e/company bankrupt <компания> confirm &7- заморозить предприятие")
        send_message(sender, u"&e/companies &7- каталог предприятий")
        send_message(sender, u"&e/shares &7- ваши акции")

    def send_shares_help(self, sender):
        send_message(sender, CompaniesConfig.PREFIX + u"&e/shares list")
        send_message(sender, u"&e/shares market <компания> <акции>")
        send_message(sender, u"&e/shares give <компания> <игрок> <акции>")
        send_message(sender, u"&e/shares sell <компания> <игрок> <акции> <цена>")
        send_message(sender, u"&e/shares accept/deny <id>")
        send_message(sender, u"&e/shares vote <id> <yes|no> &7- голосование акционеров")
        send_message(sender, u"&e/shares limit <buy|sell> <компания> <акции> <цена>")
        send_message(sender, u"&e/shares orders | cancel <id> &7- ваши лимитные заявки")
        if is_admin(sender):
            send_message(sender, u"&e/shares resolve <id> <paid|retry|rollback|reset> &7- сверка оборванной операции")

    def send_journal(self, sender):
        pending = state.data.get("operation_journal", {})
        if not pending:
            send_message(sender, CompaniesConfig.PREFIX + u"&7Незавершённых операций нет.")
            return
        for op_id, entry in list(pending.items())[:20]:
            send_message(sender, u"&8- &e#{0} &f{1} &8| &7{2}".format(
                op_id, entry.get("operation", "?"), entry.get("payload", {})))

    def send_list(self, sender):
        companies = state.list_companies()
        if not companies:
            send_message(sender, CompaniesConfig.PREFIX + u"&7Предприятий пока нет.")
            return
        send_message(sender, CompaniesConfig.PREFIX + u"&bПредприятия:")
        for company in companies[:20]:
            send_message(sender, u"&8- &e{0} &7| город: &f{1} &7| цена: &a{2} &7| свободно: &e{3}".format(
                company.get("name"), company.get("town"), format_share_price(service.current_price(company)), company.get("available_shares")
            ))

    def send_company_info(self, sender, company_name):
        company = state.find_company(company_name)
        if not company:
            send_message(sender, CompaniesConfig.PREFIX + u"&cПредприятие не найдено.")
            return
        send_message(sender, u"&3&m----------&r &b&l{0} &3&m----------".format(company.get("name")))
        send_message(sender, u"&7Описание: &f{0}".format(company.get("description")))
        send_message(sender, u"&7Владелец: &e{0} &8| &7Город: &b{1}".format(company.get("owner_name"), company.get("town")))
        send_message(sender, u"&7Тип: &f{0} &8| &7Цена акции: &a{1}".format(service.type_label(company.get("type")), format_share_price(service.current_price(company))))
        send_message(sender, u"&7Свободно: &e{0} &8| &7В обращении: &e{1}".format(company.get("available_shares"), CompaniesConfig.SHARES_TOTAL - int(company.get("available_shares", 0))))
        send_message(sender, u"&7Счет: &6{0} &8| &7Дивиденды: &6{1}".format(format_currency(company.get("balance", 0.0)), format_currency(company.get("dividends", 0.0))))
        send_message(sender, u"&3&m--------------------------------")

    def send_shares(self, sender):
        uuid_str, name = get_sender_uuid_and_name(sender)
        if not uuid_str:
            send_message(sender, CompaniesConfig.PREFIX + u"&cТолько игрок может иметь акции.")
            return
        lines = []
        portfolio_value = 0.0
        for company in state.list_companies():
            amount = service.owned_shares(company, uuid_str)
            if amount > 0:
                price = service.current_price(company)
                total = round(price * amount, 2)
                portfolio_value += total
                lines.append(u"&8- &b{0}&7: &e{1}&7 акций &8(&a{2}&7/шт.&8) &7= &6{3}".format(
                    company.get("name"), amount, format_share_price(price), format_currency(total)
                ))
        send_message(sender, CompaniesConfig.PREFIX + u"&bВаши акции:")
        if not lines:
            send_message(sender, u"&8- &7Нет акций.")
        else:
            for line in lines:
                send_message(sender, line)
            send_message(sender, u"&7Общая стоимость акций: &6{0}".format(format_currency(portfolio_value)))

    def tab_company(self, sender, alias, args):
        args = list(args)
        subs = ["help", "create", "open", "info", "buy", "deposit", "withdraw", "dividends", "rename", "description", "delete", "bankrupt", "history", "chart", "journal"]
        if len(args) <= 1:
            prefix = args[0].lower() if args else ""
            return build_java_list([sub for sub in subs if sub.startswith(prefix)])
        sub = args[0].lower()
        if len(args) == 2 and sub in ("open", "info", "buy", "deposit", "withdraw", "dividends", "rename", "description", "delete", "bankrupt", "history", "chart"):
            return self.tab_companies(args[1])
        if len(args) == 3 and sub in ("buy", "deposit", "withdraw"):
            return build_java_list(["1", "10", "100", "1000", "10000"])
        if len(args) == 3 and sub == "dividends":
            return build_java_list(["off", "1000", "5000", "10000", "50000"])
        if len(args) == 3 and sub == "create":
            return build_java_list([item[0] for item in CompaniesConfig.COMPANY_TYPES if item[0].startswith(args[2].lower())])
        return build_java_list([])

    def tab_shares(self, sender, alias, args):
        args = list(args)
        subs = ["list", "market", "give", "sell", "accept", "deny", "vote", "limit", "orders", "cancel"]
        if is_admin(sender):
            subs.append("resolve")
        if len(args) <= 1:
            prefix = args[0].lower() if args else ""
            return build_java_list([sub for sub in subs if sub.startswith(prefix)])
        sub = args[0].lower()
        if len(args) == 2 and sub in ("give", "sell", "market", "sellmarket"):
            return self.tab_owned_companies(sender, args[1])
        if len(args) == 3 and sub in ("market", "sellmarket"):
            return build_java_list(["1", "10", "100", "1000"])
        if len(args) == 3 and sub in ("give", "sell"):
            return build_java_list([name for name in economy.online_names() if name.lower().startswith(args[2].lower())])
        if len(args) == 4 and sub in ("give", "sell"):
            return build_java_list(["1", "10", "100", "1000"])
        if len(args) == 5 and sub == "sell":
            return build_java_list(["1000", "10000", "50000", "100000"])
        if len(args) == 3 and sub == "vote":
            return build_java_list(["yes", "no"])
        if len(args) == 2 and sub == "limit":
            return build_java_list(["buy", "sell"])
        if len(args) == 3 and sub == "limit":
            return self.tab_companies(args[2])
        if len(args) == 4 and sub == "limit":
            return build_java_list(["1", "10", "100", "1000"])
        if len(args) == 5 and sub == "limit":
            return build_java_list(["10", "100", "1000", "10000"])
        if len(args) == 3 and sub == "resolve":
            return build_java_list(["paid", "retry", "rollback", "reset"])
        return build_java_list([])

    def tab_companies(self, prefix):
        prefix = to_unicode(prefix).lower()
        return build_java_list([company.get("key") for company in state.list_companies() if company.get("key", "").startswith(prefix)][:20])

    def tab_owned_companies(self, sender, prefix):
        uuid_str, name = get_sender_uuid_and_name(sender)
        prefix = to_unicode(prefix).lower()
        result = []
        for company in state.list_companies():
            if service.owned_shares(company, uuid_str) > 0 and company.get("key", "").startswith(prefix):
                result.append(company.get("key"))
        return build_java_list(result[:20])


class DividendRunnable(Runnable):
    def run(self):
        try:
            if service is not None:
                service.process_dividends()
        except Exception as exc:
            log_info(u"Dividend task error: {0}".format(exc))


registered_listeners = []
dividend_task_id = -1
DIVIDEND_TASK_PROPERTY = "SmartY_Companies_DividendTaskId"
state = None
economy = None
towns = None
service = None
command_handler = None
initialized = False


def store_dividend_task_id(task_id):
    if JAVA_AVAILABLE and System is not None:
        try:
            System.getProperties().put(DIVIDEND_TASK_PROPERTY, str(int(task_id)))
        except Exception:
            pass


def cancel_stale_dividend_task():
    if not BUKKIT_AVAILABLE or not JAVA_AVAILABLE or System is None:
        return
    try:
        raw_task_id = System.getProperties().get(DIVIDEND_TASK_PROPERTY)
        stale_task_id = int(str(raw_task_id)) if raw_task_id is not None else -1
        if stale_task_id >= 0:
            Bukkit.getScheduler().cancelTask(stale_task_id)
    except Exception:
        pass
    store_dividend_task_id(-1)


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
    Bukkit.getPluginManager().registerEvent(event_class, listener, EventPriority.HIGHEST, DirectExecutor(), plugin)
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
        if not top_inv:
            return
        holder = top_inv.getHolder()
        if holder is None or not isinstance(holder, CompanyInventoryHolder):
            return
        event.setCancelled(True)
        raw_slot = event.getRawSlot()
        if raw_slot < 0 or raw_slot >= top_inv.getSize():
            return
        player = event.getWhoClicked()
        holder.gui.handle_click(player, raw_slot, str(event.getClick()) if hasattr(event, "getClick") else "LEFT")
    except Exception as exc:
        log_info(u"Inventory click error: {0}".format(exc))


def on_inventory_drag(event):
    try:
        top_inv = event.getView().getTopInventory()
        holder = top_inv.getHolder() if top_inv else None
        if holder is not None and isinstance(holder, CompanyInventoryHolder):
            event.setCancelled(True)
    except Exception:
        pass


def on_player_chat(event):
    try:
        player = event.getPlayer()
        uuid_str, name = get_sender_uuid_and_name(player)
        session = create_sessions.get(uuid_str)
        if not session:
            return
        event.setCancelled(True)
        text = to_unicode(event.getMessage()).strip()
        if hasattr(event, "isAsynchronous") and event.isAsynchronous():
            plugin = get_pyspigot_plugin()
            if plugin:
                class ChatSessionRunnable(Runnable):
                    def __init__(self, target, message):
                        self.target = target
                        self.message = message

                    def run(self):
                        process_chat_session(self.target, self.message)
                Bukkit.getScheduler().runTask(plugin, ChatSessionRunnable(player, text))
                return
        process_chat_session(player, text)
    except Exception as exc:
        log_info(u"Chat wizard error: {0}".format(exc))


def process_chat_session(player, text):
    try:
        uuid_str, name = get_sender_uuid_and_name(player)
        session = create_sessions.get(uuid_str)
        if not session:
            return
        if text.lower() in ("cancel", u"отмена"):
            del create_sessions[uuid_str]
            send_message(player, CompaniesConfig.PREFIX + u"&7Действие отменено.")
            return
        if isinstance(session, ActionSession):
            finished = handle_action_session(player, session, text)
            if finished and uuid_str in create_sessions:
                del create_sessions[uuid_str]
            return
        if session.step == "name":
            session.name = text
            session.step = "description"
            send_message(player, CompaniesConfig.PREFIX + u"&7Введите описание предприятия.")
        elif session.step == "description":
            session.description = text[:180]
            session.step = "price"
            send_message(player, CompaniesConfig.PREFIX + u"&7Введите стартовую цену акции. Минимум: &e10$&7.")
        elif session.step == "price":
            try:
                price = parse_amount(text)
            except Exception:
                send_message(player, CompaniesConfig.PREFIX + u"&cНекорректная цена.")
                return
            service.create_company(player, session.name, session.description, session.company_type, price)
            del create_sessions[uuid_str]
    except Exception as exc:
        log_info(u"Chat wizard error: {0}".format(exc))


def on_player_quit(event):
    try:
        uuid_str, name = get_sender_uuid_and_name(event.getPlayer())
        if uuid_str in create_sessions:
            del create_sessions[uuid_str]
    except Exception:
        pass


if BUKKIT_AVAILABLE:
    class PyBukkitCommand(Command, TabCompleter):
        def __init__(self, name, description, usage, aliases, executor, completer):
            Command.__init__(self, name, description, usage, aliases)
            self.cmd_name = name
            self.executor = executor
            self.completer = completer

        def execute(self, sender, commandLabel, args):
            try:
                if self.executor:
                    return self.executor(sender, commandLabel, list(args))
            except Exception as exc:
                log_info(u"Command /{0} error: {1}".format(self.cmd_name, exc))
            return True

        def tabComplete(self, *args):
            if self.completer:
                try:
                    result = self.completer(*args)
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
            self.cmd_name = name
            self.executor = executor
            self.completer = completer


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
        known_commands = command_map.getKnownCommands() if hasattr(command_map, "getKnownCommands") else None
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
            alias_command = PyBukkitCommand(alias, cmd_obj.getDescription(), cmd_obj.getUsage(), [], cmd_obj.executor, cmd_obj.completer)
            known_commands.put(str(alias).lower(), alias_command)
            known_commands.put(fallback_prefix + ":" + str(alias).lower(), alias_command)
    except Exception as exc:
        log_info(u"Command registration error: {0}".format(exc))


registered_company_commands = []   # (name, aliases) - для полного снятия при выгрузке,
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
        command_map = server.getCommandMap() if hasattr(server, "getCommandMap") else None
        if command_map is None:
            field = server.getClass().getDeclaredField("commandMap")
            field.setAccessible(True)
            command_map = field.get(server)
        known_commands = command_map.getKnownCommands() if hasattr(command_map, "getKnownCommands") else None
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
        names = [name] + list(aliases)
        for item_name in names:
            lowered = str(item_name).lower()
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


def unregister_commands():
    for name, aliases in list(registered_company_commands):
        force_unregister_bukkit_command("smarty-companies", name, aliases)
    del registered_company_commands[:]
    try:
        if BUKKIT_AVAILABLE and hasattr(Bukkit.getServer(), "syncCommands"):
            Bukkit.getServer().syncCommands()
    except Exception:
        pass


def register_commands():
    commands = [
        ("companies", "Open companies catalog", "/companies", ["companylist"], command_handler.execute_companies, None),
        ("company", "Company management", "/company <help|create|open|buy|deposit|withdraw|dividends>", ["comp"], command_handler.execute_company, command_handler.tab_company),
        ("shares", "Share transfers and offers", "/shares <list|give|sell|accept|deny>", ["stocks"], command_handler.execute_shares, command_handler.tab_shares)
    ]
    for item in commands:
        command = PyBukkitCommand(item[0], item[1], item[2], item[3], item[4], item[5])
        force_register_bukkit_command("smarty-companies", command, item[3])
        registered_company_commands.append((item[0], item[3]))


def start_dividend_timer():
    global dividend_task_id
    cancel_stale_dividend_task()
    stop_dividend_timer()
    if not BUKKIT_AVAILABLE:
        return
    plugin = get_pyspigot_plugin()
    if plugin:
        task = Bukkit.getScheduler().runTaskTimer(plugin, DividendRunnable(), 1200, CompaniesConfig.DIVIDEND_TASK_PERIOD_TICKS)
        dividend_task_id = task.getTaskId()
        store_dividend_task_id(dividend_task_id)


def stop_dividend_timer():
    global dividend_task_id
    if BUKKIT_AVAILABLE and dividend_task_id != -1:
        try:
            Bukkit.getScheduler().cancelTask(dividend_task_id)
        except Exception:
            pass
    dividend_task_id = -1
    store_dividend_task_id(-1)


def on_enable():
    global state, economy, towns, service, command_handler, initialized
    if initialized:
        return
    log_info(u"Starting {0} v{1}".format(CompaniesConfig.PLUGIN_NAME, CompaniesConfig.VERSION))
    state = CompanyState(JsonStorage(CompaniesConfig.DATA_FILE, CompanyState.DEFAULTS))
    economy = EconomyGateway()
    towns = TownGateway()
    service = CompanyService(state, economy, towns)
    command_handler = CompaniesCommand()
    unregister_events()
    register_event(InventoryClickEvent, on_inventory_click)
    register_event(InventoryDragEvent, on_inventory_drag)
    register_event(AsyncPlayerChatEvent, on_player_chat)
    register_event(PlayerQuitEvent, on_player_quit)
    register_commands()
    start_dividend_timer()
    initialized = True
    log_info(u"Enabled. Companies: {0}".format(len(state.list_companies())))


def on_disable():
    global initialized
    stop_dividend_timer()
    unregister_events()
    unregister_commands()
    if state is not None:
        if not state.save():
            log_info(u"Cannot save companies during shutdown; the last successful transaction remains on disk.")
    initialized = False
    log_info(u"Disabled.")


def start(script=None):
    on_enable()


def stop(script=None):
    # ВАЖНО: PySpigot вызывает автоматически именно stop() (не on_disable()) при
    # /pyspigot unload <script>. Раньше эта функция отсутствовала, поэтому on_disable()
    # никогда не выполнялся при ручной выгрузке - команды /companies /company /shares
    # (внедрённые напрямую в CommandMap в обход command_manager), таймер дивидендов и
    # все listeners (InventoryClick/Drag, AsyncPlayerChat, PlayerQuit, зарегистрированные
    # напрямую в обход listener_manager) продолжали бы работать даже после выгрузки.
    on_disable()


if __name__ == "__main__" or "ps" in globals() or "command_manager" in globals():
    on_enable()

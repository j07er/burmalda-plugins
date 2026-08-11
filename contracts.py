# -*- coding: utf-8 -*-
"""
===============================================================================
SmartY-Contracts — Автономный плагин контрактов/объявлений для Paper 1.21 / PySpigot
===============================================================================
Архитектура & SOLID:
  - Models: Contract, ContractStatus, CandidateEntry, ExecutorEntry
  - Storage: StorageManager + AtomicFileWriter (data/contracts.json)
  - Managers: ContractManager (Бизнес-логика, FSM статусов, Уведомления)
  - GUI Engine: BaseGUI, Chest-GUI меню с In-Place обновлением и 100% защитой
  - Commands: PyBukkitCommand (/contracts, /contract add, my, active, done)
  - Events: InventoryClick, InventoryClose, InventoryDrag
===============================================================================
"""

import os
import sys
import json
import io
import time
import re
import uuid
import shutil
import copy

# Очистка Jython-кэша модулей
if "contracts" in sys.modules:
    try:
        del sys.modules["contracts"]
    except Exception:
        pass

# Совместимость unicode в Jython / Python 2/3
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

# -----------------------------------------------------------------------------
# ИМПОРТ BUKKIT / PYSPIGOT
# -----------------------------------------------------------------------------
try:
    from org.bukkit import Bukkit, ChatColor, Sound, Location, Material
    from org.bukkit.entity import Player
    from org.bukkit.command import Command, TabCompleter
    from org.bukkit.inventory import Inventory, ItemStack, InventoryHolder
    from org.bukkit.inventory.meta import ItemMeta, SkullMeta
    from org.bukkit.event import Listener, EventPriority
    from org.bukkit.plugin import EventExecutor
    from org.bukkit.event.inventory import InventoryClickEvent, InventoryCloseEvent, InventoryDragEvent
    from org.bukkit.event.player import PlayerJoinEvent, PlayerQuitEvent
    try:
        from org.bukkit.event.player import AsyncPlayerChatEvent
    except ImportError:
        AsyncPlayerChatEvent = None
    try:
        from org.bukkit.event.player import PlayerChatEvent
    except ImportError:
        PlayerChatEvent = None
    BUKKIT_AVAILABLE = True
except ImportError:
    BUKKIT_AVAILABLE = False
    Command = object
    TabCompleter = object
    InventoryHolder = object
    Location = None
    InventoryDragEvent = None
    Player = object
    Material = None
    ItemStack = None

try:
    from java.lang import String as JavaString, System, Runnable
    from java.util import Base64
    JAVA_STRING_AVAILABLE = True
except ImportError:
    JAVA_STRING_AVAILABLE = False
    JavaString = str
    System = None
    Runnable = object
    Base64 = None


# -----------------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ УТИЛИТЫ КОДИРОВКИ, ЦВЕТОВ И ЗВУКОВ
# -----------------------------------------------------------------------------
def to_unicode(text):
    if text is None:
        return u""
    if isinstance(text, unicode):
        u_text = text
    elif JAVA_STRING_AVAILABLE and isinstance(text, JavaString):
        # Bukkit command arguments are native java.lang.String values.
        u_text = unicode(text)
    elif isinstance(text, str):
        try:
            u_text = text.decode("utf-8")
        except Exception:
            try:
                u_text = text.decode("cp1251")
            except Exception:
                u_text = unicode(text, "utf-8", "ignore")
    else:
        # Command arguments arrive from Bukkit as java.lang.String objects in
        # Jython.  Converting those through str() first asks Jython to encode
        # them as ASCII and crashes on Cyrillic before the command handler is
        # reached.  unicode(java_string) preserves the original characters.
        try:
            u_text = unicode(text)
        except Exception:
            try:
                u_text = unicode(str(text), "utf-8", "replace")
            except Exception:
                u_text = u""

    if u"\u00d0" in u_text or u"\u00d1" in u_text or u"\u00c3" in u_text:
        try:
            raw_bytes = u_text.encode("iso-8859-1")
            return raw_bytes.decode("utf-8")
        except Exception:
            try:
                raw_bytes = u_text.encode("cp1251")
                return raw_bytes.decode("utf-8")
            except Exception:
                pass
    return u_text


def to_java_string(text):
    u_text = to_unicode(text)
    if JAVA_STRING_AVAILABLE:
        try:
            utf8_bytes = u_text.encode("utf-8")
            return JavaString(utf8_bytes, "UTF-8")
        except Exception:
            pass
    return u_text


def colorize(text):
    u_text = to_unicode(text)
    if not u_text:
        return u""
    if BUKKIT_AVAILABLE and ChatColor is not None:
        return ChatColor.translateAlternateColorCodes('&', u_text)
    else:
        return re.sub(r'&([0-9a-fk-or])', u'', u_text, flags=re.IGNORECASE)


def strip_color(text):
    u_text = to_unicode(text)
    if BUKKIT_AVAILABLE and ChatColor is not None:
        return ChatColor.stripColor(u_text)
    return re.sub(r'[\xa7&][0-9a-fk-or]', u'', u_text, flags=re.IGNORECASE)


def safe_console_send(text):
    colored_text = colorize(text)
    if BUKKIT_AVAILABLE and Bukkit is not None:
        try:
            java_msg = to_java_string(colored_text)
            Bukkit.getConsoleSender().sendMessage(java_msg)
            return
        except Exception:
            pass

    clean = strip_color(text)
    print("[SmartY-Contracts] " + clean)


def log_info(text):
    safe_console_send(u"&b[SmartY-Contracts] &a[INFO] " + to_unicode(text))


def log_error(text):
    safe_console_send(u"&b[SmartY-Contracts] &c[ERROR] " + to_unicode(text))


def safe_play_sound(player, sound_candidates, volume=1.0, pitch=1.0):
    if not BUKKIT_AVAILABLE or player is None or Sound is None:
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


def send_contract_msg(sender, text):
    msg = colorize(ContractConfig.PREFIX + to_unicode(text))
    if sender is not None:
        if hasattr(sender, "sendMessage"):
            try:
                sender.sendMessage(to_java_string(msg))
            except Exception:
                try:
                    sender.sendMessage(str(msg))
                except Exception:
                    pass
        else:
            safe_console_send(msg)


def send_to_player_by_name(player_name, text):
    if not BUKKIT_AVAILABLE or not player_name:
        return
    p = Bukkit.getPlayer(str(player_name))
    if p and p.isOnline():
        send_contract_msg(p, text)


# -----------------------------------------------------------------------------
# РАБОЧИЕ ДИРЕКТОРИИ И ГЛОБАЛЬНЫЙ КОНФИГ
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


def wrap_text(text, max_len=35, color_prefix=u"  &f"):
    u_text = to_unicode(text)
    if not u_text:
        return []
    words = u_text.split(u" ")
    lines = []
    curr_line = []
    curr_len = 0

    for w in words:
        if curr_len + len(w) + 1 > max_len and curr_line:
            lines.append(color_prefix + u" ".join(curr_line))
            curr_line = [w]
            curr_len = len(w)
        else:
            curr_line.append(w)
            curr_len += len(w) + 1

    if curr_line:
        lines.append(color_prefix + u" ".join(curr_line))

    return lines


class ContractConfig:
    PLUGIN_NAME = u"SmartY-Contracts"
    VERSION = u"1.1.0"
    PREFIX = u"&b&l[Контракты]&r "

    SCRIPT_DIR = get_script_dir()
    DATA_DIR = os.path.join(SCRIPT_DIR, "data")
    CONTRACTS_FILE = os.path.join(DATA_DIR, "contracts.json")
    DEFAULT_DEADLINE_HOURS = 72
    HISTORY_LIMIT = 1000
    NOTIFICATION_LIMIT = 100


class EconomyGateway(object):
    """Small adapter for the shared economy.py manager."""
    def __init__(self):
        self.manager = None

    def refresh(self):
        self.manager = None
        if System is not None:
            try:
                props = System.getProperties()
                self.manager = props.get("PySpigot_EconomyManager") or props.get("SmartY_EconomyManager")
                if self.manager and hasattr(self.manager, "is_active") and not self.manager.is_active():
                    self.manager = None
            except Exception:
                self.manager = None
        return self.manager

    def withdraw(self, uuid_str, amount):
        manager = self.refresh()
        return bool(manager and manager.withdraw(str(uuid_str), float(amount)))

    def deposit(self, uuid_str, amount, name):
        manager = self.refresh()
        if not manager:
            return False
        if hasattr(manager, "deposit_checked"):
            result = manager.deposit_checked(str(uuid_str), float(amount), to_unicode(name))
            return bool(result[0] if isinstance(result, (tuple, list)) else result)
        manager.deposit(str(uuid_str), float(amount), to_unicode(name))
        return True


def serialize_item(item):
    if item is None or Base64 is None:
        return None
    try:
        return str(Base64.getEncoder().encodeToString(item.serializeAsBytes()))
    except Exception as e:
        log_error(u"Unable to serialize escrow item: {0}".format(e))
        return None


def deserialize_item(encoded):
    if not encoded or ItemStack is None or Base64 is None:
        return None
    try:
        return ItemStack.deserializeBytes(Base64.getDecoder().decode(str(encoded)))
    except Exception as e:
        log_error(u"Unable to deserialize escrow item: {0}".format(e))
        return None


def remove_similar_items(player, sample, amount):
    """Remove exactly amount matching items, rolling back on a short inventory."""
    if not player or not sample or amount <= 0:
        return False
    inv = player.getInventory()
    slots = []
    left = int(amount)
    for slot in range(inv.getSize()):
        stack = inv.getItem(slot)
        if stack and stack.isSimilar(sample):
            take = min(left, int(stack.getAmount()))
            slots.append((slot, stack.clone(), take))
            left -= take
            if left <= 0:
                break
    if left > 0:
        return False
    for slot, old_stack, take in slots:
        new_amount = int(old_stack.getAmount()) - take
        if new_amount <= 0:
            inv.setItem(slot, None)
        else:
            old_stack.setAmount(new_amount)
            inv.setItem(slot, old_stack)
    return True


def give_items(player, sample, amount):
    if not player or not sample or amount <= 0:
        return False
    left = int(amount)
    max_stack = max(1, int(sample.getMaxStackSize()))
    while left > 0:
        stack = sample.clone()
        stack.setAmount(min(max_stack, left))
        leftovers = player.getInventory().addItem(stack)
        if leftovers and not leftovers.isEmpty():
            for dropped in leftovers.values():
                player.getWorld().dropItemNaturally(player.getLocation(), dropped)
        left -= int(stack.getAmount())
    return True


def parse_reward_spec(text, player=None):
    """money <sum>, item <count>, mixed <sum> <count>; item is taken from main hand."""
    raw = to_unicode(text).strip()
    parts = raw.replace(u"$", u"").split()
    money = 0.0
    item_count = 0
    kind = parts[0].lower() if parts else u""
    try:
        if kind in [u"money", u"деньги"] and len(parts) >= 2:
            money = float(parts[1].replace(",", "."))
        elif kind in [u"item", u"предмет"] and len(parts) >= 2:
            item_count = int(parts[1])
        elif kind in [u"mixed", u"смешанная"] and len(parts) >= 3:
            money = float(parts[1].replace(",", "."))
            item_count = int(parts[2])
        elif len(parts) == 1:
            money = float(parts[0].replace(",", "."))
        else:
            return {"display": raw, "money": 0.0, "item_count": 0, "item": None}
    except Exception:
        return {"display": raw, "money": 0.0, "item_count": 0, "item": None}
    if money < 0 or item_count < 0 or (money <= 0 and item_count <= 0):
        raise ValueError("reward must be positive")
    sample = None
    if item_count > 0:
        if player is None:
            raise ValueError("item escrow requires a player")
        sample = player.getInventory().getItemInMainHand()
        if sample is None or (Material is not None and sample.getType() == Material.AIR):
            raise ValueError("hold the escrow item in main hand")
        sample = sample.clone()
        sample.setAmount(1)
    display = u"{0:.2f}$".format(money) if money > 0 else u""
    if item_count > 0:
        item_name = to_unicode(str(sample.getType()))
        display += (u" + " if display else u"") + u"{0}x {1}".format(item_count, item_name)
    return {"display": display, "money": money, "item_count": item_count, "item": sample}


# -----------------------------------------------------------------------------
# СТА ТУСЫ И МОДЕЛИ ДАННЫХ (MODELS)
# -----------------------------------------------------------------------------
class ContractStatus:
    DISPUTED = "DISPUTED"
    OVERDUE = "OVERDUE"
    OPEN = "OPEN"                         # Идет набор кандидатов/исполнителей
    ACTIVE = "ACTIVE"                     # Есть хотя бы один подтвержденный исполнитель
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"  # Исполнитель отметил работу выполненной
    COMPLETED = "COMPLETED"               # Завершено и подтверждено заказчиком
    CANCELLED = "CANCELLED"               # Отменено заказчиком

    @staticmethod
    def get_display_name(status):
        if status == ContractStatus.DISPUTED:
            return colorize(u"&c&lСПОР")
        if status == ContractStatus.OVERDUE:
            return colorize(u"&4&lПРОСРОЧЕН")
        mapping = {
            ContractStatus.OPEN: u"&a&lОТКРЫТ &7(Набор исполнителей)",
            ContractStatus.ACTIVE: u"&e&lВ РАБОТЕ &7(Выполняется)",
            ContractStatus.WAITING_CONFIRMATION: u"&6&lОЖИДАЕТ ПОДТВЕРЖДЕНИЯ &7(Работа сдана)",
            ContractStatus.COMPLETED: u"&2&lЗАВЕРШЕН",
            ContractStatus.CANCELLED: u"&c&lОТМЕНЕН"
        }
        return colorize(mapping.get(status, status))


class Contract(object):
    def __init__(self, contract_id, title, description, reward, customer_uuid, customer_name,
                 max_executors=1, status=ContractStatus.OPEN, candidates=None, executors=None, created_at=None,
                 reward_money=0.0, reward_item=None, reward_item_count=0, escrow_status="NONE",
                 deadline_at=None, milestones=None, executor_status=None, dispute=None, ratings=None):
        self.id = str(contract_id)
        self.title = to_unicode(title)
        self.description = to_unicode(description)
        self.reward = to_unicode(reward)
        self.customer_uuid = str(customer_uuid)
        self.customer_name = to_unicode(customer_name)
        self.max_executors = int(max_executors)  # 1, 2, 5, 10, или -1 (без ограничений)
        self.status = str(status)
        self.candidates = candidates if candidates is not None else []  # [{"uuid": ..., "name": ..., "time": ...}]
        self.executors = executors if executors is not None else []    # [{"uuid": ..., "name": ..., "time": ...}]
        self.created_at = float(created_at) if created_at else time.time()
        self.reward_money = max(0.0, float(reward_money or 0.0))
        self.reward_item = reward_item
        self.reward_item_count = max(0, int(reward_item_count or 0))
        self.escrow_status = str(escrow_status or "NONE")
        self.deadline_at = float(deadline_at or (self.created_at + ContractConfig.DEFAULT_DEADLINE_HOURS * 3600))
        self.milestones = milestones if isinstance(milestones, list) and milestones else [
            {"id": "1", "title": u"Основная работа", "done_by": []}
        ]
        self.executor_status = executor_status if isinstance(executor_status, dict) else {}
        self.dispute = dispute if isinstance(dispute, dict) else None
        self.ratings = ratings if isinstance(ratings, list) else []

    def is_customer(self, player_uuid):
        return str(player_uuid) == self.customer_uuid

    def is_candidate(self, player_uuid):
        puuid = str(player_uuid)
        return any(c.get("uuid") == puuid for c in self.candidates)

    def is_executor(self, player_uuid):
        puuid = str(player_uuid)
        return any(e.get("uuid") == puuid for e in self.executors)

    def can_accept_more(self):
        if self.max_executors == -1:
            return True
        return len(self.executors) < self.max_executors

    def all_executors_done(self):
        return bool(self.executors) and all(
            self.executor_status.get(e.get("uuid")) == "DONE" for e in self.executors
        )

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "reward": self.reward,
            "customer_uuid": self.customer_uuid,
            "customer_name": self.customer_name,
            "max_executors": self.max_executors,
            "status": self.status,
            "candidates": self.candidates,
            "executors": self.executors,
            "created_at": self.created_at,
            "reward_money": self.reward_money,
            "reward_item": self.reward_item,
            "reward_item_count": self.reward_item_count,
            "escrow_status": self.escrow_status,
            "deadline_at": self.deadline_at,
            "milestones": self.milestones,
            "executor_status": self.executor_status,
            "dispute": self.dispute,
            "ratings": self.ratings
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            contract_id=data.get("id"),
            title=data.get("title", u"Без названия"),
            description=data.get("description", u"Без описания"),
            reward=data.get("reward", u"Не указана"),
            customer_uuid=data.get("customer_uuid"),
            customer_name=data.get("customer_name", u"Unknown"),
            max_executors=data.get("max_executors", 1),
            status=data.get("status", ContractStatus.OPEN),
            candidates=data.get("candidates", []),
            executors=data.get("executors", []),
            created_at=data.get("created_at"),
            reward_money=data.get("reward_money", 0.0),
            reward_item=data.get("reward_item"),
            reward_item_count=data.get("reward_item_count", 0),
            escrow_status=data.get("escrow_status", "NONE"),
            deadline_at=data.get("deadline_at"),
            milestones=data.get("milestones"),
            executor_status=data.get("executor_status", {}),
            dispute=data.get("dispute"),
            ratings=data.get("ratings", [])
        )


# -----------------------------------------------------------------------------
# ХРАНИЛИЩЕ ДАННЫХ И АТОМАРНАЯ ЗАПИСЬ (STORAGE)
# -----------------------------------------------------------------------------
class AtomicFileWriter(object):
    @staticmethod
    def write_json(file_path, data):
        data_dir = os.path.dirname(file_path)
        if not os.path.exists(data_dir):
            try:
                os.makedirs(data_dir)
            except Exception:
                pass

        temp_file = file_path + ".tmp"
        backup_file = file_path + ".bak"
        try:
            # Jython 2.7's json encoder can attempt an implicit ASCII encode
            # when unicode values and byte-string keys are mixed.  Escaped
            # JSON is semantically identical and avoids that failure entirely.
            json_str = json.dumps(data, indent=2, ensure_ascii=True)
            if not isinstance(json_str, unicode):
                json_str = to_unicode(json_str)

            with io.open(temp_file, "w", encoding="utf-8") as f:
                f.write(json_str)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass

            if os.path.exists(file_path):
                try:
                    shutil.copy2(file_path, backup_file)
                except Exception:
                    pass
            try:
                from java.nio.file import Files, Paths, StandardCopyOption
                Files.move(Paths.get(temp_file), Paths.get(file_path), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
            except Exception:
                if os.path.exists(file_path):
                    os.remove(file_path)
                os.rename(temp_file, file_path)
            return True
        except Exception as e:
            log_error(u"Atomic write error for {0}: {1}".format(file_path, e))
            return False


class StorageManager(object):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StorageManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.file_path = ContractConfig.CONTRACTS_FILE
        self.history = []
        self.notifications = {}
        self.ratings = {}
        self.last_error = u""

    def load_contracts(self):
        if not os.path.exists(self.file_path) and not os.path.exists(self.file_path + ".bak"):
            return {}
        last_error = None
        for candidate_path in [self.file_path, self.file_path + ".bak"]:
            if not os.path.exists(candidate_path):
                continue
            try:
                with io.open(candidate_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                contracts_dict = {}
                for cid, cdata in raw_data.get("contracts", {}).items():
                    if isinstance(cdata, dict):
                        contract = Contract.from_dict(cdata)
                        contracts_dict[cid] = contract
                self.history = raw_data.get("history", []) if isinstance(raw_data.get("history", []), list) else []
                self.notifications = raw_data.get("notifications", {}) if isinstance(raw_data.get("notifications", {}), dict) else {}
                self.ratings = raw_data.get("ratings", {}) if isinstance(raw_data.get("ratings", {}), dict) else {}
                return contracts_dict
            except Exception as e:
                last_error = e
                log_error(u"Error reading {0}: {1}".format(candidate_path, e))
        raise IOError("contracts storage and backup are unreadable: {0}".format(last_error))

    def save_contracts(self, contracts_dict, history=None, notifications=None, ratings=None):
        data = {
            "contracts": {cid: c.to_dict() for cid, c in contracts_dict.items()},
            "history": history if isinstance(history, list) else self.history,
            "notifications": notifications if isinstance(notifications, dict) else self.notifications,
            "ratings": ratings if isinstance(ratings, dict) else self.ratings
        }
        return AtomicFileWriter.write_json(self.file_path, data)


# -----------------------------------------------------------------------------
# МЕНЕДЖЕР БИЗНЕС-ЛОГИКИ КОНТРАКТОВ (MANAGERS)
# -----------------------------------------------------------------------------
class ContractManager(object):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ContractManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.storage = StorageManager()
        self.economy = EconomyGateway()
        self.contracts = {}  # contract_id -> Contract
        self.history = []
        self.notifications = {}
        self.ratings = {}
        self.load_all()

    def load_all(self):
        self.contracts = self.storage.load_contracts()
        self.history = self.storage.history
        self.notifications = self.storage.notifications
        self.ratings = self.storage.ratings
        self.mark_overdue()
        log_info(u"Loaded {0} active contracts from storage.".format(len(self.contracts)))

    def save_all(self):
        return self.storage.save_contracts(self.contracts, self.history, self.notifications, self.ratings)

    def create_contract(self, customer_uuid, customer_name, title, description, reward, max_executors=1,
                        customer_player=None, deadline_hours=None):
        self.last_error = u""
        try:
            reward_info = parse_reward_spec(reward, customer_player)
        except Exception as e:
            self.last_error = to_unicode(e)
            return None
        money = float(reward_info.get("money", 0.0))
        item_count = int(reward_info.get("item_count", 0))
        sample = reward_info.get("item")
        if money > 0 and not self.economy.withdraw(customer_uuid, money):
            self.last_error = u"Недостаточно денег или экономика недоступна"
            return None
        if item_count > 0 and not remove_similar_items(customer_player, sample, item_count):
            if money > 0:
                self.economy.deposit(customer_uuid, money, customer_name)
            self.last_error = u"Недостаточно предметов, совпадающих с предметом в руке"
            return None
        cid = "contract_" + str(int(time.time())) + "_" + str(uuid.uuid4())[:8]
        deadline_hours = float(deadline_hours or ContractConfig.DEFAULT_DEADLINE_HOURS)
        deadline_hours = max(1.0, min(deadline_hours, 24.0 * 365.0))
        contract = Contract(
            contract_id=cid,
            title=title,
            description=description,
            reward=reward_info.get("display") or reward,
            customer_uuid=customer_uuid,
            customer_name=customer_name,
            max_executors=max_executors,
            status=ContractStatus.OPEN,
            reward_money=money,
            reward_item=serialize_item(sample),
            reward_item_count=item_count,
            escrow_status="HELD" if money > 0 or item_count > 0 else "NONE",
            deadline_at=time.time() + deadline_hours * 3600.0
        )
        self.contracts[cid] = contract
        if not self.save_all():
            self.contracts.pop(cid, None)
            if money > 0:
                self.economy.deposit(customer_uuid, money, customer_name)
            if item_count > 0:
                give_items(customer_player, sample, item_count)
            self.last_error = u"Не удалось сохранить контракт; эскроу возвращён"
            return None
        log_info(u"Contract created: {0} by {1}".format(title, customer_name))
        return contract

    def notify(self, uuid_str, player_name, text):
        player = Bukkit.getPlayer(str(player_name)) if BUKKIT_AVAILABLE and player_name else None
        if player and player.isOnline():
            send_contract_msg(player, text)
            return
        key = str(uuid_str)
        queue = self.notifications.setdefault(key, [])
        queue.append({"time": time.time(), "text": to_unicode(text)})
        if len(queue) > ContractConfig.NOTIFICATION_LIMIT:
            del queue[:-ContractConfig.NOTIFICATION_LIMIT]
        self.save_all()

    def deliver_notifications(self, player):
        key = str(player.getUniqueId())
        queued = list(self.notifications.get(key, []))
        if queued:
            self.notifications.pop(key, None)
            if not self.save_all():
                self.notifications[key] = queued
                send_contract_msg(player, u"&cУведомления пока не выданы: хранилище недоступно.")
                return
            send_contract_msg(player, u"&eОфлайн-уведомления по контрактам:")
            for entry in queued:
                send_contract_msg(player, entry.get("text", u""))

    def queue_if_offline(self, uuid_str, player_name, text):
        player = Bukkit.getPlayer(str(player_name)) if BUKKIT_AVAILABLE and player_name else None
        if player and player.isOnline():
            return
        key = str(uuid_str)
        queue = self.notifications.setdefault(key, [])
        queue.append({"time": time.time(), "text": to_unicode(text)})
        if len(queue) > ContractConfig.NOTIFICATION_LIMIT:
            del queue[:-ContractConfig.NOTIFICATION_LIMIT]
        self.save_all()

    def mark_overdue(self):
        changed = False
        now = time.time()
        for contract in self.contracts.values():
            if contract.status in [ContractStatus.OPEN, ContractStatus.ACTIVE] and contract.deadline_at <= now:
                contract.status = ContractStatus.OVERDUE
                changed = True
        if changed:
            self.save_all()

    def archive(self, contract, final_status):
        snapshot = contract.to_dict()
        snapshot["status"] = final_status
        snapshot["closed_at"] = time.time()
        self.history.append(snapshot)
        if len(self.history) > ContractConfig.HISTORY_LIMIT:
            del self.history[:-ContractConfig.HISTORY_LIMIT]

    def refund_escrow(self, contract, customer_player=None):
        if contract.escrow_status not in ["HELD", "PAYOUT_FAILED"]:
            return True
        if contract.dispute and contract.dispute.get("paid_money"):
            return False
        progress = dict(contract.dispute or {})
        if progress.get("transfer_in_progress"):
            return False
        player = customer_player
        if contract.reward_item_count > 0:
            if player is None and BUKKIT_AVAILABLE:
                player = Bukkit.getPlayer(contract.customer_name)
            if not player or not player.isOnline():
                return False
        if contract.reward_money > 0 and not progress.get("refunded_money"):
            progress["transfer_in_progress"] = {"kind": "refund_money", "uuid": contract.customer_uuid}
            contract.dispute = progress
            if not self.save_all():
                progress.pop("transfer_in_progress", None)
                return False
            if not self.economy.deposit(contract.customer_uuid, contract.reward_money, contract.customer_name):
                progress.pop("transfer_in_progress", None)
                contract.dispute = progress
                self.save_all()
                return False
            progress["refunded_money"] = True
            progress.pop("transfer_in_progress", None)
            contract.dispute = progress
            if not self.save_all():
                return False
        if contract.reward_item_count > 0:
            if not progress.get("refunded_items"):
                progress["transfer_in_progress"] = {"kind": "refund_items", "uuid": contract.customer_uuid}
                contract.dispute = progress
                if not self.save_all():
                    progress.pop("transfer_in_progress", None)
                    return False
                if not give_items(player, deserialize_item(contract.reward_item), contract.reward_item_count):
                    progress.pop("transfer_in_progress", None)
                    contract.dispute = progress
                    self.save_all()
                    return False
                progress["refunded_items"] = True
                progress.pop("transfer_in_progress", None)
                contract.dispute = progress
                if not self.save_all():
                    return False
        contract.escrow_status = "REFUNDED"
        return bool(self.save_all())

    def add_milestone(self, customer, contract_id, title):
        contract = self.get_contract(contract_id)
        if not contract or not contract.is_customer(str(customer.getUniqueId())):
            return False, u"&cКонтракт не найден или вы не заказчик."
        if contract.status not in [ContractStatus.OPEN, ContractStatus.ACTIVE]:
            return False, u"&cЭтапы этого контракта уже нельзя менять."
        next_id = str(max([int(m.get("id", 0)) for m in contract.milestones] + [0]) + 1)
        contract.milestones.append({"id": next_id, "title": to_unicode(title)[:80], "done_by": []})
        if not self.save_all():
            contract.milestones.pop()
            return False, u"&cОшибка сохранения."
        return True, u"&aЭтап #{0} добавлен.".format(next_id)

    def mark_milestone_done(self, executor, contract_id, milestone_id):
        contract = self.get_contract(contract_id)
        euuid = str(executor.getUniqueId())
        if not contract or not contract.is_executor(euuid):
            return False, u"&cВы не исполнитель этого контракта."
        target = next((m for m in contract.milestones if str(m.get("id")) == str(milestone_id)), None)
        if not target:
            return False, u"&cЭтап не найден."
        if euuid not in target.setdefault("done_by", []):
            target["done_by"].append(euuid)
        self.save_all()
        return True, u"&aЭтап отмечен выполненным."

    def open_dispute(self, player, contract_id, reason):
        contract = self.get_contract(contract_id)
        puuid = str(player.getUniqueId())
        if not contract or (not contract.is_customer(puuid) and not contract.is_executor(puuid)):
            return False, u"&cВы не участник контракта."
        contract.status = ContractStatus.DISPUTED
        contract.dispute = {"opened_by": puuid, "name": to_unicode(player.getName()),
                            "reason": to_unicode(reason)[:300], "time": time.time()}
        self.save_all()
        return True, u"&eСпор открыт. Администратор должен решить судьбу эскроу."

    def rate_player(self, rater, contract_id, target_name, value):
        record = next((h for h in self.history if h.get("id") == str(contract_id)), None)
        if not record:
            return False, u"&cЗавершённый контракт не найден в истории."
        ruuid = str(rater.getUniqueId())
        participants = [record.get("customer_uuid")] + [e.get("uuid") for e in record.get("executors", [])]
        if ruuid not in participants:
            return False, u"&cОценивать могут только участники сделки."
        target = next((u for u in participants if u != ruuid and any(
            to_unicode(x.get("name", u"")).lower() == to_unicode(target_name).lower()
            for x in ([{"uuid": record.get("customer_uuid"), "name": record.get("customer_name")}]
                      + record.get("executors", [])) if x.get("uuid") == u)), None)
        if not target:
            return False, u"&cУчастник не найден."
        key = ruuid + ":" + str(contract_id) + ":" + target
        if key in self.ratings:
            return False, u"&cВы уже поставили эту оценку."
        self.ratings[key] = {"contract": str(contract_id), "from": ruuid, "to": target,
                             "value": max(1, min(5, int(value))), "time": time.time()}
        self.save_all()
        return True, u"&aОценка сохранена."

    def get_contract(self, contract_id):
        lookup = to_unicode(contract_id).strip()
        direct = self.contracts.get(lookup)
        if direct is not None:
            return direct
        # Player-facing commands may use an exact contract title instead of
        # the long generated id.  Only accept a unique match so duplicate
        # titles can never target the wrong escrow.
        title_matches = [c for c in self.contracts.values()
                         if to_unicode(c.title).strip().lower() == lookup.lower()]
        return title_matches[0] if len(title_matches) == 1 else None

    def get_all_open_or_active_contracts(self):
        return [c for c in self.contracts.values() if c.status in [ContractStatus.OPEN, ContractStatus.ACTIVE, ContractStatus.WAITING_CONFIRMATION]]

    def get_contracts_by_customer(self, customer_uuid):
        cuuid = str(customer_uuid)
        return [c for c in self.contracts.values() if c.customer_uuid == cuuid]

    def get_contracts_by_executor(self, executor_uuid):
        euuid = str(executor_uuid)
        return [c for c in self.contracts.values() if c.is_executor(euuid)]

    # --- 1. Подача заявки кандидатом ---
    def apply_for_contract(self, player, contract_id):
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден!"

        player_uuid = str(player.getUniqueId())
        player_name = to_unicode(player.getName())

        if contract.is_customer(player_uuid):
            return False, u"&cВы не можете подавать заявку на собственный контракт!"

        if contract.is_candidate(player_uuid):
            return False, u"&cВы уже подали заявку на этот контракт!"

        if contract.is_executor(player_uuid):
            return False, u"&cВы уже являетесь исполнителем этого контракта!"

        if contract.status not in [ContractStatus.OPEN, ContractStatus.ACTIVE]:
            return False, u"&cНабор исполнителей на этот контракт закрыт!"

        contract.candidates.append({
            "uuid": player_uuid,
            "name": player_name,
            "applied_at": time.time()
        })
        self.save_all()

        # Уведомление заказчику
        send_to_player_by_name(contract.customer_name, u"&eИгрок &f{0} &eхочет выполнять ваш контракт &f\"{1}\"&e!".format(
            player_name, contract.title
        ))
        cust_player = Bukkit.getPlayer(contract.customer_name) if BUKKIT_AVAILABLE else None
        if cust_player:
            safe_play_sound(cust_player, ["ENTITY_EXPERIENCE_ORB_PICKUP", "ENTITY_PLAYER_LEVELUP"], 0.8, 1.1)

        return True, u"&aВы успешно подали заявку на контракт &f\"{0}\"&a!".format(contract.title)

    # --- 2. Принятие кандидата заказчиком ---
    def accept_candidate(self, customer, contract_id, candidate_uuid):
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден!"

        cust_uuid = str(customer.getUniqueId())
        if not contract.is_customer(cust_uuid):
            return False, u"&cТолько заказчик может принимать кандидатов!"

        if not contract.can_accept_more():
            return False, u"&cДостигнуто максимальное количество исполнителей ({0})!".format(contract.max_executors)

        # Ищем кандидата
        cand_entry = None
        for c in contract.candidates:
            if c.get("uuid") == str(candidate_uuid):
                cand_entry = c
                break

        if not cand_entry:
            return False, u"&cКандидат не найден в списке!"

        contract.candidates.remove(cand_entry)
        contract.executors.append({
            "uuid": cand_entry["uuid"],
            "name": cand_entry["name"],
            "accepted_at": time.time()
        })
        contract.executor_status[cand_entry["uuid"]] = "ACTIVE"

        if contract.status == ContractStatus.OPEN and len(contract.executors) > 0:
            contract.status = ContractStatus.ACTIVE

        self.save_all()

        cand_name = cand_entry["name"]
        send_to_player_by_name(cand_name, u"&aВаша заявка на контракт &f\"{0}\" &aбыла ПРИНЯТА заказчиком &e{1}&a!".format(
            contract.title, contract.customer_name
        ))
        cand_player = Bukkit.getPlayer(cand_name) if BUKKIT_AVAILABLE else None
        if cand_player:
            safe_play_sound(cand_player, ["ENTITY_PLAYER_LEVELUP", "LEVEL_UP"], 1.0, 1.2)

        return True, u"&aИгрок &f{0} &aуспешно принят в исполнители контракта!".format(cand_name)

    # --- 3. Отклонение кандидата заказчиком ---
    def decline_candidate(self, customer, contract_id, candidate_uuid):
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден!"

        cust_uuid = str(customer.getUniqueId())
        if not contract.is_customer(cust_uuid):
            return False, u"&cТолько заказчик может отклонять кандидатов!"

        cand_entry = None
        for c in contract.candidates:
            if c.get("uuid") == str(candidate_uuid):
                cand_entry = c
                break

        if not cand_entry:
            return False, u"&cКандидат не найден в списке!"

        contract.candidates.remove(cand_entry)
        self.save_all()

        cand_name = cand_entry["name"]
        send_to_player_by_name(cand_name, u"&cВаша заявка на контракт &f\"{0}\" &cбыла отклонена заказчиком.".format(
            contract.title
        ))
        return True, u"&cВы отклонили заявку игрока &f{0}&c.".format(cand_name)

    # --- 4. Отказ исполнителя от выполнения ---
    def quit_contract(self, executor, contract_id):
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден!"

        exec_uuid = str(executor.getUniqueId())
        exec_name = to_unicode(executor.getName())

        if not contract.is_executor(exec_uuid):
            return False, u"&cВы не являетесь исполнителем этого контракта!"

        exec_entry = None
        for e in contract.executors:
            if e.get("uuid") == exec_uuid:
                exec_entry = e
                break

        if exec_entry:
            contract.executors.remove(exec_entry)
        contract.executor_status.pop(exec_uuid, None)
        for milestone in contract.milestones:
            if exec_uuid in milestone.get("done_by", []):
                milestone["done_by"].remove(exec_uuid)

        if len(contract.executors) == 0:
            contract.status = ContractStatus.OPEN

        self.save_all()

        send_to_player_by_name(contract.customer_name, u"&cИгрок &f{0} &cотказался от выполнения контракта &f\"{1}\"&c.".format(
            exec_name, contract.title
        ))
        return True, u"&cВы отказались от выполнения контракта &f\"{0}\"&c.".format(contract.title)

    # --- 5. Отметка выполения исполнителем (Сдача работы) ---
    def mark_done(self, executor, contract_id):
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден!"

        exec_uuid = str(executor.getUniqueId())
        exec_name = to_unicode(executor.getName())

        if not contract.is_executor(exec_uuid):
            return False, u"&cВы не являетесь исполнителем этого контракта!"

        contract.executor_status[exec_uuid] = "DONE"
        for milestone in contract.milestones:
            if exec_uuid not in milestone.setdefault("done_by", []):
                milestone["done_by"].append(exec_uuid)
        contract.status = ContractStatus.WAITING_CONFIRMATION if contract.all_executors_done() else ContractStatus.ACTIVE
        self.save_all()

        send_to_player_by_name(contract.customer_name, u"&e&lИгрок &f{0} &e&lотметил контракт &f\"{1}\" &e&lкак выполненный! Проверьте и подтвердите через /contract my.".format(
            exec_name, contract.title
        ))
        cust_player = Bukkit.getPlayer(contract.customer_name) if BUKKIT_AVAILABLE else None
        if cust_player:
            safe_play_sound(cust_player, ["ENTITY_EXPERIENCE_ORB_PICKUP", "ENTITY_VILLAGER_YES"], 1.0, 1.0)

        return True, u"&aВы отметите работу как выполненную! Заказчик получил уведомление."

# -----------------------------------------------------------------------------
# GUI LAYER (СУНДУЧНЫЕ ИНВЕНТАРИ, BASE_GUI И МЕНЮ)
# -----------------------------------------------------------------------------
    # Escrow settlement and durable immutable archive.
    def confirm_completion(self, customer, contract_id):
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден."
        if not contract.is_customer(str(customer.getUniqueId())):
            return False, u"&cТолько заказчик может подтвердить выполнение."
        if not contract.all_executors_done():
            return False, u"&cНе все исполнители отметили работу выполненной."
        executors = list(contract.executors)
        if not executors:
            return False, u"&cУ контракта нет исполнителей."

        progress = dict(contract.dispute or {})
        if progress.get("transfer_in_progress"):
            return False, u"&cПредыдущая выплата имеет неопределённый результат. Администратор должен использовать /contract resolve <id> paid или retry."
        if contract.reward_item_count > 0:
            for ex in executors:
                target = Bukkit.getPlayer(ex.get("name")) if BUKKIT_AVAILABLE else None
                if not target or not target.isOnline():
                    return False, u"&cВсе исполнители должны быть онлайн для выдачи предметного эскроу."

        contract.escrow_status = "PAYOUT_IN_PROGRESS"
        if not self.save_all():
            contract.escrow_status = "HELD"
            return False, u"&cНе удалось подготовить выплату."

        paid_money = list(progress.get("paid_money", []))
        money_parts = []
        if contract.reward_money > 0:
            base_money = round(contract.reward_money / float(len(executors)), 2)
            money_parts = [base_money for unused in executors]
            money_parts[-1] = round(money_parts[-1] + contract.reward_money - sum(money_parts), 2)
        else:
            money_parts = [0.0 for unused in executors]
        for index, ex in enumerate(executors):
            if ex.get("uuid") in paid_money:
                continue
            share_money = money_parts[index]
            if share_money <= 0:
                continue
            progress["paid_money"] = list(paid_money)
            progress["transfer_in_progress"] = {"kind": "money", "uuid": ex.get("uuid"),
                                                "name": ex.get("name"), "amount": share_money}
            contract.dispute = progress
            if not self.save_all():
                progress.pop("transfer_in_progress", None)
                return False, u"&cНе удалось зафиксировать начало выплаты."
            if not self.economy.deposit(ex.get("uuid"), share_money, ex.get("name")):
                progress.pop("transfer_in_progress", None)
                contract.escrow_status = "PAYOUT_FAILED"
                contract.status = ContractStatus.DISPUTED
                progress["reason"] = u"Ошибка выплаты экономики"
                progress["time"] = time.time()
                progress["paid_money"] = paid_money
                contract.dispute = progress
                self.save_all()
                return False, u"&cВыплата остановлена и переведена в спор. Не повторяйте её вручную."
            paid_money.append(ex.get("uuid"))
            progress["paid_money"] = list(paid_money)
            progress.pop("transfer_in_progress", None)
            contract.dispute = progress
            if not self.save_all():
                contract.status = ContractStatus.DISPUTED
                return False, u"&cВыплата прошла, но её подтверждение не сохранилось. Нужна админ-сверка."

        sample = deserialize_item(contract.reward_item)
        if contract.reward_item_count > 0 and sample is not None:
            # Preflight prevents a predictable half-issued item payout.
            online_targets = []
            for ex in executors:
                target = Bukkit.getPlayer(ex.get("name")) if BUKKIT_AVAILABLE else None
                if not target or not target.isOnline():
                    contract.escrow_status = "PAYOUT_FAILED"
                    contract.status = ContractStatus.DISPUTED
                    contract.dispute = {"reason": u"Исполнитель офлайн во время выдачи предметов",
                                        "time": time.time(), "paid_money": paid_money}
                    self.save_all()
                    return False, u"&cВсе исполнители должны быть онлайн для выдачи предметного эскроу."
                online_targets.append(target)
            base = contract.reward_item_count // len(executors)
            extra = contract.reward_item_count % len(executors)
            for index, target in enumerate(online_targets):
                target_uuid = str(target.getUniqueId())
                paid_items = list(progress.get("paid_items", []))
                if target_uuid in paid_items:
                    continue
                item_amount = base + (1 if index < extra else 0)
                if item_amount <= 0:
                    continue
                progress["transfer_in_progress"] = {"kind": "items", "uuid": target_uuid,
                                                    "name": target.getName(), "amount": item_amount}
                contract.dispute = progress
                if not self.save_all():
                    progress.pop("transfer_in_progress", None)
                    return False, u"&cНе удалось зафиксировать начало выдачи предметов."
                if not give_items(target, sample, item_amount):
                    progress.pop("transfer_in_progress", None)
                    contract.status = ContractStatus.DISPUTED
                    progress["reason"] = u"Ошибка предметной выплаты"
                    contract.dispute = progress
                    self.save_all()
                    return False, u"&cПредметная выплата остановлена и переведена в спор."
                paid_items.append(target_uuid)
                progress["paid_items"] = paid_items
                progress.pop("transfer_in_progress", None)
                contract.dispute = progress
                if not self.save_all():
                    contract.status = ContractStatus.DISPUTED
                    return False, u"&cПредметы выданы, но подтверждение не сохранилось. Нужна админ-сверка."

        contract.status = ContractStatus.COMPLETED
        contract.escrow_status = "PAID"
        self.archive(contract, ContractStatus.COMPLETED)
        self.contracts.pop(contract.id, None)
        if not self.save_all():
            self.contracts[contract.id] = contract
            return False, u"&cВыплата прошла, но архив не сохранился. Не запускайте выплату повторно."
        for ex in executors:
            self.notify(ex.get("uuid"), ex.get("name"),
                        u"&aКонтракт &f\"{0}\" &aзавершён; награда выплачена из эскроу.".format(contract.title))
        return True, u"&aКонтракт завершён, награда выплачена, запись добавлена в историю."

    def cancel_contract(self, customer, contract_id):
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден."
        if not contract.is_customer(str(customer.getUniqueId())):
            return False, u"&cТолько заказчик может отменить контракт."
        if contract.executors:
            return False, u"&cАктивный контракт нельзя отменить односторонне. Используйте /contract dispute."
        if not self.refund_escrow(contract, customer):
            contract.status = ContractStatus.DISPUTED
            progress = dict(contract.dispute or {})
            progress["reason"] = u"Не удалось вернуть эскроу"
            progress["time"] = time.time()
            contract.dispute = progress
            self.save_all()
            return False, u"&cНе удалось вернуть эскроу; контракт переведён в спор."
        contract.status = ContractStatus.CANCELLED
        self.archive(contract, ContractStatus.CANCELLED)
        self.contracts.pop(contract.id, None)
        self.save_all()
        return True, u"&eКонтракт отменён, эскроу возвращён."

    def resolve_dispute(self, admin, contract_id, outcome):
        if not is_contract_admin(admin):
            return False, u"&cНет права contracts.admin."
        contract = self.get_contract(contract_id)
        if not contract or contract.status != ContractStatus.DISPUTED:
            return False, u"&cАктивный спор не найден."
        outcome = str(outcome).lower()
        if outcome in ["paid", "retry"]:
            progress = dict(contract.dispute or {})
            original_progress = copy.deepcopy(progress)
            transfer = progress.get("transfer_in_progress")
            if not isinstance(transfer, dict):
                return False, u"&cУ спора нет неоднозначного перевода для сверки."
            kind = str(transfer.get("kind", ""))
            if outcome == "paid":
                target_uuid = str(transfer.get("uuid"))
                if kind == "money":
                    paid = list(progress.get("paid_money", []))
                    if target_uuid not in paid:
                        paid.append(target_uuid)
                    progress["paid_money"] = paid
                elif kind == "items":
                    paid = list(progress.get("paid_items", []))
                    if target_uuid not in paid:
                        paid.append(target_uuid)
                    progress["paid_items"] = paid
                elif kind == "refund_money":
                    progress["refunded_money"] = True
                elif kind == "refund_items":
                    progress["refunded_items"] = True
            progress.pop("transfer_in_progress", None)
            contract.dispute = progress
            if not self.save_all():
                contract.dispute = original_progress
                return False, u"&cРешение сверки не удалось сохранить."
            outcome = "customer" if kind.startswith("refund_") else "executors"
        if outcome == "customer":
            if not self.refund_escrow(contract, Bukkit.getPlayer(contract.customer_name) if BUKKIT_AVAILABLE else None):
                return False, u"&cВозврат невозможен: заказчик с предметным эскроу должен быть онлайн."
            final_status = ContractStatus.CANCELLED
        elif outcome == "executors":
            for ex in contract.executors:
                contract.executor_status[ex.get("uuid")] = "DONE"
            contract.status = ContractStatus.WAITING_CONFIRMATION
            return self.confirm_completion(admin if contract.is_customer(str(admin.getUniqueId())) else _CustomerProxy(contract), contract_id)
        else:
            return False, u"&cИспользуйте customer, executors, paid или retry."
        self.archive(contract, final_status)
        self.contracts.pop(contract.id, None)
        self.save_all()
        return True, u"&aСпор решён в пользу заказчика."

    def admin_mark_all_done(self, admin, contract_id):
        if not is_contract_admin(admin):
            return False, u"&cНет права contracts.admin."
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден."
        if not contract.executors:
            return False, u"&cУ контракта нет исполнителей."
        progress = contract.dispute if isinstance(contract.dispute, dict) else {}
        if progress.get("transfer_in_progress"):
            return False, u"&cСначала выполните ручную сверку незавершённого перевода."
        for executor in contract.executors:
            executor_uuid = executor.get("uuid")
            contract.executor_status[executor_uuid] = "DONE"
            for milestone in contract.milestones:
                done_by = milestone.setdefault("done_by", [])
                if executor_uuid not in done_by:
                    done_by.append(executor_uuid)
        contract.status = ContractStatus.WAITING_CONFIRMATION
        if not self.save_all():
            return False, u"&cНе удалось сохранить административное подтверждение."
        log_info(u"Admin {0} marked contract {1} done.".format(admin.getName(), contract.id))
        return True, u"&aВсе исполнители и этапы отмечены выполненными. Выплата ещё не произведена."

    def admin_confirm_and_pay(self, admin, contract_id):
        if not is_contract_admin(admin):
            return False, u"&cНет права contracts.admin."
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден."
        if not contract.all_executors_done():
            return False, u"&cСначала отметьте выполнение всех исполнителей."
        result = self.confirm_completion(_CustomerProxy(contract), contract.id)
        if result[0]:
            log_info(u"Admin {0} confirmed payout for contract {1}.".format(admin.getName(), contract.id))
        return result

    def admin_refund_and_close(self, admin, contract_id):
        if not is_contract_admin(admin):
            return False, u"&cНет права contracts.admin."
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден."
        progress = contract.dispute if isinstance(contract.dispute, dict) else {}
        if progress.get("transfer_in_progress") or contract.escrow_status in ["PAYOUT_IN_PROGRESS", "PAID"]:
            return False, u"&cВозврат заблокирован: сначала выполните ручную сверку незавершённой выплаты."
        customer = Bukkit.getPlayer(contract.customer_name) if BUKKIT_AVAILABLE else None
        if not self.refund_escrow(contract, customer):
            return False, u"&cВозврат не выполнен. Для предметной награды заказчик должен быть в сети; проверьте также незавершённый перевод."
        contract.status = ContractStatus.CANCELLED
        self.archive(contract, ContractStatus.CANCELLED)
        self.contracts.pop(contract.id, None)
        if not self.save_all():
            self.contracts[contract.id] = contract
            return False, u"&cВозврат прошёл, но архив не сохранился. Не повторяйте операцию."
        log_info(u"Admin {0} refunded and closed contract {1}.".format(admin.getName(), contract.id))
        return True, u"&aЭскроу возвращено заказчику, контракт закрыт."

    def set_deadline(self, customer, contract_id, hours):
        contract = self.get_contract(contract_id)
        if not contract or not contract.is_customer(str(customer.getUniqueId())):
            return False, u"&cКонтракт не найден или вы не заказчик."
        if contract.status != ContractStatus.OPEN:
            return False, u"&cСрок можно менять только до принятия исполнителя."
        hours = max(1.0, min(float(hours), 24.0 * 365.0))
        contract.deadline_at = time.time() + hours * 3600.0
        self.save_all()
        return True, u"&aСрок контракта установлен: {0:.1f} ч.".format(hours)

    def show_history(self, sender, limit=10):
        records = list(reversed(self.history[-max(1, min(50, int(limit))):]))
        if not records:
            send_contract_msg(sender, u"&7История пока пуста.")
            return
        send_contract_msg(sender, u"&eПоследние завершённые контракты:")
        for record in records:
            send_contract_msg(sender, u"&7{0} &f{1} &8— &b{2}".format(
                record.get("id"), record.get("title"), record.get("status")))


class _CustomerProxy(object):
    def __init__(self, contract):
        self.contract = contract
    def getUniqueId(self):
        return self.contract.customer_uuid


def is_contract_admin(player):
    try:
        return bool(player.isOp() or player.hasPermission("contracts.admin"))
    except Exception:
        return False


class SmartYInventoryHolder(InventoryHolder):
    def __init__(self, gui_instance):
        self.gui_instance = gui_instance

    def getInventory(self):
        return getattr(self.gui_instance, "inventory", None)


class BaseGUI(object):
    def __init__(self, title, rows=6):
        self.title = colorize(title)
        self.rows = max(1, min(6, rows))
        self.slots_count = self.rows * 9
        self.holder = SmartYInventoryHolder(self)
        if BUKKIT_AVAILABLE:
            self.inventory = Bukkit.createInventory(self.holder, self.slots_count, to_java_string(self.title))
        else:
            self.inventory = None

    def open(self, player):
        if self.inventory and hasattr(player, "openInventory"):
            player.openInventory(self.inventory)
            safe_play_sound(player, ["BLOCK_CHEST_OPEN", "CHEST_OPEN"], 0.8, 1.0)

    def handle_click(self, player, raw_slot, click_type, is_shift):
        pass


# --- 0. Главное меню всех контрактов (/contracts) ---
class ContractsMainMenuGUI(BaseGUI):
    def __init__(self, player):
        super(ContractsMainMenuGUI, self).__init__(u"&6&lМеню контрактов", rows=3)
        self.player = player
        self.build()

    def build(self):
        if not self.inventory:
            return
        self.inventory.clear()

        # Слот 10: Все заказы
        item_all = ItemStack(Material.BOOK, 1)
        m_all = item_all.getItemMeta()
        if m_all:
            m_all.setDisplayName(to_java_string(colorize(u"&a&l▶ Все заказы")))
            m_all.setLore([
                to_java_string(colorize(u"&8&m------------------------")),
                to_java_string(colorize(u"&7Просмотр всех открытых")),
                to_java_string(colorize(u"&7и активных заказов сервера.")),
                to_java_string(colorize(u"&8&m------------------------")),
                to_java_string(colorize(u"&e▶ Нажмите для просмотра"))
            ])
            item_all.setItemMeta(m_all)
        self.inventory.setItem(10, item_all)

        # Слот 12: Мои заказы (созданные мной)
        item_my = ItemStack(Material.WRITABLE_BOOK, 1)
        m_my = item_my.getItemMeta()
        if m_my:
            m_my.setDisplayName(to_java_string(colorize(u"&6&l▶ Мои заказы")))
            m_my.setLore([
                to_java_string(colorize(u"&8&m------------------------")),
                to_java_string(colorize(u"&7Заказы, созданные вами.")),
                to_java_string(colorize(u"&7Управление заявками и сдача.")),
                to_java_string(colorize(u"&8&m------------------------")),
                to_java_string(colorize(u"&e▶ Нажмите для просмотра"))
            ])
            item_my.setItemMeta(m_my)
        self.inventory.setItem(12, item_my)

        # Слот 14: Взятые контракты (где я исполнитель)
        item_act = ItemStack(Material.COMPASS, 1)
        m_act = item_act.getItemMeta()
        if m_act:
            m_act.setDisplayName(to_java_string(colorize(u"&b&l▶ Взятые контракты")))
            m_act.setLore([
                to_java_string(colorize(u"&8&m------------------------")),
                to_java_string(colorize(u"&7Заказы, где вы являетесь")),
                to_java_string(colorize(u"&7подтвержденным исполнителем.")),
                to_java_string(colorize(u"&8&m------------------------")),
                to_java_string(colorize(u"&e▶ Нажмите для просмотра"))
            ])
            item_act.setItemMeta(m_act)
        self.inventory.setItem(14, item_act)

        # Слот 16: Создать заказ
        item_add = ItemStack(Material.EMERALD, 1)
        m_add = item_add.getItemMeta()
        if m_add:
            m_add.setDisplayName(to_java_string(colorize(u"&2&l✚ Создать новый заказ")))
            m_add.setLore([
                to_java_string(colorize(u"&8&m------------------------")),
                to_java_string(colorize(u"&7Запустить мастер создания заказа.")),
                to_java_string(colorize(u"&7Данные будут запрошены в чате.")),
                to_java_string(colorize(u"&8&m------------------------")),
                to_java_string(colorize(u"&a▶ Нажмите для создания"))
            ])
            item_add.setItemMeta(m_add)
        self.inventory.setItem(16, item_add)

        if is_contract_admin(self.player):
            admin_item = ItemStack(Material.COMMAND_BLOCK, 1)
            admin_meta = admin_item.getItemMeta()
            if admin_meta:
                admin_meta.setDisplayName(to_java_string(colorize(u"&c&lАдминистрирование контрактов")))
                admin_meta.setLore([
                    to_java_string(colorize(u"&7Все действующие контракты и споры.")),
                    to_java_string(colorize(u"&7Проверка деталей, выполнения и эскроу.")),
                    to_java_string(colorize(u"&eНажмите, чтобы открыть"))
                ])
                admin_item.setItemMeta(admin_meta)
            self.inventory.setItem(22, admin_item)

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 10:
            gui = ContractsListGUI(player, page=1)
            gui.open(player)
        elif raw_slot == 12:
            gui = MyContractsGUI(player)
            gui.open(player)
        elif raw_slot == 14:
            gui = ActiveContractsGUI(player)
            gui.open(player)
        elif raw_slot == 16:
            if hasattr(player, "closeInventory"):
                player.closeInventory()
            start_contract_creation_wizard(player)
        elif raw_slot == 22 and is_contract_admin(player):
            AdminContractsGUI(player, page=1).open(player)


# --- 1. Главный список всех контрактов (/contracts) ---
class ContractsListGUI(BaseGUI):
    def __init__(self, player, page=1):
        super(ContractsListGUI, self).__init__(u"&6&lОбъявления и Контракты", rows=6)
        self.player = player
        self.page = page
        self.slot_mapping = {}
        self.build()

    def build(self):
        if not self.inventory:
            return
        self.inventory.clear()
        self.slot_mapping.clear()

        mgr = ContractManager()
        all_contracts = mgr.get_all_open_or_active_contracts()
        all_contracts.sort(key=lambda c: c.created_at, reverse=True)

        items_per_page = 45
        total_items = len(all_contracts)
        max_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
        self.page = max(1, min(self.page, max_pages))

        start_idx = (self.page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_items)
        page_contracts = all_contracts[start_idx:end_idx]

        player_uuid = str(self.player.getUniqueId())

        for idx, contract in enumerate(page_contracts):
            item = ItemStack(Material.PAPER, 1)
            meta = item.getItemMeta()
            if meta:
                meta.setDisplayName(to_java_string(colorize(u"&e&l" + contract.title)))

                max_exec_str = u"Без ограничений" if contract.max_executors == -1 else str(contract.max_executors)
                exec_count_str = u"{0}/{1}".format(len(contract.executors), max_exec_str)

                lore = [
                    to_java_string(colorize(u"&8&m------------------------")),
                    to_java_string(colorize(u"&7Заказчик: &f" + contract.customer_name)),
                    to_java_string(colorize(u"&7Описание:"))
                ]
                for d_line in wrap_text(contract.description, max_len=32, color_prefix=u"  &f"):
                    lore.append(to_java_string(colorize(d_line)))
                lore.extend([
                    to_java_string(colorize(u"&7Награда: &a" + contract.reward)),
                    to_java_string(colorize(u"&7Исполнители: &e" + exec_count_str)),
                    to_java_string(colorize(u"&7Статус: " + ContractStatus.get_display_name(contract.status))),
                    to_java_string(colorize(u"&8&m------------------------"))
                ])

                if contract.is_customer(player_uuid):
                    lore.append(to_java_string(colorize(u"&b▶ Вы Заказчик (Нажмите для управления)")))
                elif contract.is_executor(player_uuid):
                    lore.append(to_java_string(colorize(u"&a▶ Вы Исполнитель (Нажмите для просмотра)")))
                elif contract.is_candidate(player_uuid):
                    lore.append(to_java_string(colorize(u"&e▶ Вы подали заявку (Ожидание)")))
                else:
                    lore.append(to_java_string(colorize(u"&e▶ Нажмите, чтобы открыть подробности")))

                meta.setLore(lore)
                item.setItemMeta(meta)

            self.inventory.setItem(idx, item)
            self.slot_mapping[idx] = contract.id

        # Кнопка Предыдущая страница
        if self.page > 1:
            p_item = ItemStack(Material.ARROW, 1)
            p_meta = p_item.getItemMeta()
            p_meta.setDisplayName(to_java_string(colorize(u"&a◄ Предыдущая страница")))
            p_item.setItemMeta(p_meta)
            self.inventory.setItem(45, p_item)

        # Кнопка Назад в главное меню
        b_item = ItemStack(Material.BARRIER, 1)
        b_meta = b_item.getItemMeta()
        b_meta.setDisplayName(to_java_string(colorize(u"&c◄ Главное меню")))
        b_item.setItemMeta(b_meta)
        self.inventory.setItem(49, b_item)

        # Кнопка Следующая страница
        if self.page < max_pages:
            n_item = ItemStack(Material.ARROW, 1)
            n_meta = n_item.getItemMeta()
            n_meta.setDisplayName(to_java_string(colorize(u"&aСледующая страница ►")))
            n_item.setItemMeta(n_meta)
            self.inventory.setItem(53, n_item)

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 45 and self.page > 1:
            self.page -= 1
            self.build()
            return
        elif raw_slot == 53:
            self.page += 1
            self.build()
            return
        elif raw_slot == 49:
            gui = ContractsMainMenuGUI(player)
            gui.open(player)
            return

        if raw_slot in self.slot_mapping:
            cid = self.slot_mapping[raw_slot]
            gui = ContractDetailsGUI(player, cid, parent_gui="contracts")
            gui.open(player)


# --- 2. GUI "Мои созданные контракты" (/contract my) ---
class MyContractsGUI(BaseGUI):
    def __init__(self, player):
        super(MyContractsGUI, self).__init__(u"&6&lМои созданные контракты", rows=6)
        self.player = player
        self.slot_mapping = {}
        self.build()

    def build(self):
        if not self.inventory:
            return
        self.inventory.clear()
        self.slot_mapping.clear()

        mgr = ContractManager()
        p_uuid = str(self.player.getUniqueId())
        my_contracts = mgr.get_contracts_by_customer(p_uuid)

        for idx, contract in enumerate(my_contracts[:45]):
            item = ItemStack(Material.WRITABLE_BOOK, 1)
            meta = item.getItemMeta()
            if meta:
                meta.setDisplayName(to_java_string(colorize(u"&e&l" + contract.title)))

                c_count = len(contract.candidates)
                e_count = len(contract.executors)

                lore = [
                    to_java_string(colorize(u"&8&m------------------------")),
                    to_java_string(colorize(u"&7Описание:"))
                ]
                for d_line in wrap_text(contract.description, max_len=32, color_prefix=u"  &f"):
                    lore.append(to_java_string(colorize(d_line)))
                lore.extend([
                    to_java_string(colorize(u"&7Награда: &a" + contract.reward)),
                    to_java_string(colorize(u"&7Кандидаты: &b{0} чел.".format(c_count))),
                    to_java_string(colorize(u"&7Исполнители: &e{0} чел.".format(e_count))),
                    to_java_string(colorize(u"&7Статус: " + ContractStatus.get_display_name(contract.status))),
                    to_java_string(colorize(u"&8&m------------------------")),
                    to_java_string(colorize(u"&e▶ Нажмите для управления контрактом"))
                ])
                meta.setLore(lore)
                item.setItemMeta(meta)

            self.inventory.setItem(idx, item)
            self.slot_mapping[idx] = contract.id

        # Кнопка Назад в главное меню
        b_item = ItemStack(Material.BARRIER, 1)
        b_meta = b_item.getItemMeta()
        b_meta.setDisplayName(to_java_string(colorize(u"&c◄ Главное меню")))
        b_item.setItemMeta(b_meta)
        self.inventory.setItem(49, b_item)

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 49:
            gui = ContractsMainMenuGUI(player)
            gui.open(player)
            return

        if raw_slot in self.slot_mapping:
            cid = self.slot_mapping[raw_slot]
            gui = ContractDetailsGUI(player, cid, parent_gui="my")
            gui.open(player)


# --- 3. GUI "Взятые контракты" (/contract active) ---
class ActiveContractsGUI(BaseGUI):
    def __init__(self, player):
        super(ActiveContractsGUI, self).__init__(u"&b&lВзятые контракты", rows=6)
        self.player = player
        self.slot_mapping = {}
        self.build()

    def build(self):
        if not self.inventory:
            return
        self.inventory.clear()
        self.slot_mapping.clear()

        mgr = ContractManager()
        p_uuid = str(self.player.getUniqueId())
        active_contracts = mgr.get_contracts_by_executor(p_uuid)

        for idx, contract in enumerate(active_contracts[:45]):
            item = ItemStack(Material.COMPASS, 1)
            meta = item.getItemMeta()
            if meta:
                meta.setDisplayName(to_java_string(colorize(u"&e&l" + contract.title)))
                lore = [
                    to_java_string(colorize(u"&8&m------------------------")),
                    to_java_string(colorize(u"&7Заказчик: &f" + contract.customer_name)),
                    to_java_string(colorize(u"&7Описание:"))
                ]
                for d_line in wrap_text(contract.description, max_len=32, color_prefix=u"  &f"):
                    lore.append(to_java_string(colorize(d_line)))
                lore.extend([
                    to_java_string(colorize(u"&7Оговоренная награда: &a" + contract.reward)),
                    to_java_string(colorize(u"&7Статус: " + ContractStatus.get_display_name(contract.status))),
                    to_java_string(colorize(u"&8&m------------------------")),
                    to_java_string(colorize(u"&e▶ Нажмите, чтобы сдать работу или отказаться"))
                ])
                meta.setLore(lore)
                item.setItemMeta(meta)

            self.inventory.setItem(idx, item)
            self.slot_mapping[idx] = contract.id

        # Кнопка Назад в главное меню
        b_item = ItemStack(Material.BARRIER, 1)
        b_meta = b_item.getItemMeta()
        b_meta.setDisplayName(to_java_string(colorize(u"&c◄ Главное меню")))
        b_item.setItemMeta(b_meta)
        self.inventory.setItem(49, b_item)

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 49:
            gui = ContractsMainMenuGUI(player)
            gui.open(player)
            return

        if raw_slot in self.slot_mapping:
            cid = self.slot_mapping[raw_slot]
            gui = ContractDetailsGUI(player, cid, parent_gui="active")
            gui.open(player)


# --- 4. GUI "Сдать работу (Отметить готовым)" (/contract done) ---
class DoneContractsGUI(BaseGUI):
    def __init__(self, player):
        super(DoneContractsGUI, self).__init__(u"&2&lСдача выполненных работ", rows=6)
        self.player = player
        self.slot_mapping = {}
        self.build()

    def build(self):
        if not self.inventory:
            return
        self.inventory.clear()
        self.slot_mapping.clear()

        mgr = ContractManager()
        p_uuid = str(self.player.getUniqueId())
        active_contracts = mgr.get_contracts_by_executor(p_uuid)

        for idx, contract in enumerate(active_contracts[:45]):
            item = ItemStack(Material.EMERALD, 1)
            meta = item.getItemMeta()
            if meta:
                meta.setDisplayName(to_java_string(colorize(u"&a&l" + contract.title)))
                lore = [
                    to_java_string(colorize(u"&8&m------------------------")),
                    to_java_string(colorize(u"&7Заказчик: &f" + contract.customer_name)),
                    to_java_string(colorize(u"&7Награда: &a" + contract.reward)),
                    to_java_string(colorize(u"&7Текущий статус: " + ContractStatus.get_display_name(contract.status))),
                    to_java_string(colorize(u"&8&m------------------------")),
                    to_java_string(colorize(u"&a▶ Нажмите ЛКМ, чтобы ОТМЕТИТЬ КАК ВЫПОЛНЕННОЕ!"))
                ]
                meta.setLore(lore)
                item.setItemMeta(meta)

            self.inventory.setItem(idx, item)
            self.slot_mapping[idx] = contract.id

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot in self.slot_mapping:
            cid = self.slot_mapping[raw_slot]
            mgr = ContractManager()
            success, msg = mgr.mark_done(player, cid)
            send_contract_msg(player, msg)
            if success:
                safe_play_sound(player, ["ENTITY_PLAYER_LEVELUP", "LEVEL_UP"], 1.0, 1.2)
            self.build()


# --- 5. GUI Подробностей контракта & Кнопки действий (ContractDetailsGUI) ---
def _admin_gui_item(material, name, lore, amount=1):
    item = ItemStack(material, max(1, min(64, int(amount))))
    meta = item.getItemMeta()
    if meta:
        meta.setDisplayName(to_java_string(colorize(name)))
        meta.setLore([to_java_string(colorize(line)) for line in lore])
        item.setItemMeta(meta)
    return item


class AdminContractsGUI(BaseGUI):
    def __init__(self, player, page=1):
        super(AdminContractsGUI, self).__init__(u"&4&lАдминистрирование контрактов", rows=6)
        self.player = player
        self.page = page
        self.slot_mapping = {}
        self.build()

    def build(self):
        if not self.inventory or not is_contract_admin(self.player):
            return
        self.inventory.clear()
        self.slot_mapping.clear()
        contracts = list(ContractManager().contracts.values())
        contracts.sort(key=lambda c: (0 if c.status == ContractStatus.DISPUTED else 1, -c.created_at))
        per_page = 45
        max_pages = max(1, (len(contracts) + per_page - 1) // per_page)
        self.page = max(1, min(self.page, max_pages))
        start = (self.page - 1) * per_page
        for slot, contract in enumerate(contracts[start:start + per_page]):
            material = Material.REDSTONE_TORCH if contract.status == ContractStatus.DISPUTED else Material.PAPER
            lore = [
                u"&7ID: &f" + contract.id,
                u"&7Заказчик: &f" + contract.customer_name,
                u"&7Награда: &a" + contract.reward,
                u"&7Эскроу: &f" + to_unicode(contract.escrow_status),
                u"&7Исполнители: &f{0} &8| &7кандидаты: &f{1}".format(
                    len(contract.executors), len(contract.candidates)),
                u"&7Статус: " + ContractStatus.get_display_name(contract.status),
                u"&eНажмите для полной карточки"
            ]
            self.inventory.setItem(slot, _admin_gui_item(material, u"&e&l" + contract.title, lore))
            self.slot_mapping[slot] = contract.id
        if self.page > 1:
            self.inventory.setItem(45, _admin_gui_item(Material.ARROW, u"&aПредыдущая страница", []))
        self.inventory.setItem(49, _admin_gui_item(Material.BARRIER, u"&cГлавное меню", []))
        if self.page < max_pages:
            self.inventory.setItem(53, _admin_gui_item(Material.ARROW, u"&aСледующая страница", []))

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if not is_contract_admin(player):
            player.closeInventory()
            return
        if raw_slot in self.slot_mapping:
            AdminContractDetailsGUI(player, self.slot_mapping[raw_slot], self.page).open(player)
        elif raw_slot == 45 and self.page > 1:
            AdminContractsGUI(player, self.page - 1).open(player)
        elif raw_slot == 49:
            ContractsMainMenuGUI(player).open(player)
        elif raw_slot == 53:
            AdminContractsGUI(player, self.page + 1).open(player)


class AdminContractDetailsGUI(BaseGUI):
    def __init__(self, player, contract_id, parent_page=1):
        super(AdminContractDetailsGUI, self).__init__(u"&4&lАдмин: подробности контракта", rows=6)
        self.player = player
        self.contract_id = contract_id
        self.parent_page = parent_page
        self.build()

    def build(self):
        if not self.inventory or not is_contract_admin(self.player):
            return
        self.inventory.clear()
        contract = ContractManager().get_contract(self.contract_id)
        if not contract:
            self.inventory.setItem(22, _admin_gui_item(Material.BARRIER, u"&cКонтракт уже закрыт", []))
            self.inventory.setItem(49, _admin_gui_item(Material.ARROW, u"&eНазад", []))
            return

        deadline_text = time.strftime("%Y-%m-%d %H:%M", time.localtime(contract.deadline_at))
        info_lore = [u"&7ID: &f" + contract.id, u"&7Заказчик: &f" + contract.customer_name]
        info_lore.extend(wrap_text(contract.description, max_len=42, color_prefix=u"&f"))
        info_lore.extend([
            u"&7Награда: &a" + contract.reward,
            u"&7Деньги: &a{0:.2f}$ &8| &7предметов: &f{1}".format(
                contract.reward_money, contract.reward_item_count),
            u"&7Эскроу: &f" + to_unicode(contract.escrow_status),
            u"&7Срок: &f" + to_unicode(deadline_text),
            u"&7Статус: " + ContractStatus.get_display_name(contract.status)
        ])
        self.inventory.setItem(13, _admin_gui_item(Material.WRITTEN_BOOK, u"&e&l" + contract.title, info_lore))

        executor_lore = []
        for executor in contract.executors:
            status = contract.executor_status.get(executor.get("uuid"), "WORKING")
            executor_lore.append(u"&f{0} &7— {1}".format(executor.get("name"), status))
        if not executor_lore:
            executor_lore = [u"&8Нет исполнителей"]
        self.inventory.setItem(10, _admin_gui_item(
            Material.PLAYER_HEAD, u"&bИсполнители ({0})".format(len(contract.executors)), executor_lore,
            len(contract.executors) or 1))

        candidate_lore = [u"&f" + to_unicode(c.get("name")) for c in contract.candidates]
        if not candidate_lore:
            candidate_lore = [u"&8Нет кандидатов"]
        self.inventory.setItem(12, _admin_gui_item(
            Material.NAME_TAG, u"&eКандидаты ({0})".format(len(contract.candidates)), candidate_lore,
            len(contract.candidates) or 1))

        milestone_lore = []
        for milestone in contract.milestones:
            milestone_lore.append(u"&f#{0} {1} &7({2}/{3})".format(
                milestone.get("id"), milestone.get("title"), len(milestone.get("done_by", [])),
                len(contract.executors)))
        self.inventory.setItem(14, _admin_gui_item(
            Material.OAK_SIGN, u"&6Этапы ({0})".format(len(contract.milestones)),
            milestone_lore or [u"&8Этапов нет"]))

        dispute = contract.dispute if isinstance(contract.dispute, dict) else {}
        dispute_lore = [u"&7Открыл: &f" + to_unicode(dispute.get("name", u"—")), u"&7Причина:"]
        dispute_lore.extend(wrap_text(
            to_unicode(dispute.get("reason", u"—")), max_len=42, color_prefix=u"&f"))
        dispute_lore.append(u"&7Денежных долей выдано: &f{0}".format(
            len(dispute.get("paid_money", []))))
        dispute_lore.append(u"&7Предметных долей выдано: &f{0}".format(
            len(dispute.get("paid_items", []))))
        transfer = dispute.get("transfer_in_progress")
        if isinstance(transfer, dict):
            dispute_lore.append(u"&cНезавершённый перевод:")
            dispute_lore.append(u"&f{0} → {1} ({2})".format(
                transfer.get("kind", u"?"), transfer.get("name", transfer.get("uuid", u"?")),
                transfer.get("amount", u"?")))
        else:
            dispute_lore.append(u"&7Незавершённый перевод: &aнет")
        self.inventory.setItem(16, _admin_gui_item(
            Material.REDSTONE_TORCH, u"&cСпор и журнал выплаты", dispute_lore))

        self.inventory.setItem(29, _admin_gui_item(Material.EMERALD,
            u"&aОтметить всё выполненным", [u"&7Не выдаёт награду.", u"&7Подтверждает всех исполнителей и этапы."]))
        self.inventory.setItem(31, _admin_gui_item(Material.DIAMOND_BLOCK,
            u"&aПодтвердить и выдать награду", [u"&cShift + клик для подтверждения", u"&7Выплата делится между исполнителями."]))
        self.inventory.setItem(33, _admin_gui_item(Material.REDSTONE_BLOCK,
            u"&cВернуть эскроу заказчику", [u"&cShift + клик для подтверждения", u"&7Контракт будет закрыт."]))

        if isinstance(dispute.get("transfer_in_progress"), dict):
            self.inventory.setItem(38, _admin_gui_item(Material.LIME_DYE,
                u"&aПеревод уже прошёл", [u"&cТолько после ручной сверки!", u"&cShift + клик"]))
            self.inventory.setItem(42, _admin_gui_item(Material.ORANGE_DYE,
                u"&6Перевод не прошёл — повторить", [u"&cТолько после ручной сверки!", u"&cShift + клик"]))
        self.inventory.setItem(49, _admin_gui_item(Material.ARROW, u"&eНазад к списку", []))

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if not is_contract_admin(player):
            player.closeInventory()
            return
        if raw_slot == 49:
            AdminContractsGUI(player, self.parent_page).open(player)
            return
        manager = ContractManager()
        contract = manager.get_contract(self.contract_id)
        if not contract:
            AdminContractsGUI(player, self.parent_page).open(player)
            return
        if raw_slot == 29:
            success, message = manager.admin_mark_all_done(player, contract.id)
        elif raw_slot == 31:
            if not is_shift:
                send_contract_msg(player, u"&cДля выплаты используйте Shift + клик.")
                return
            success, message = manager.admin_confirm_and_pay(player, contract.id)
        elif raw_slot == 33:
            if not is_shift:
                send_contract_msg(player, u"&cДля возврата используйте Shift + клик.")
                return
            success, message = manager.admin_refund_and_close(player, contract.id)
        elif raw_slot in (38, 42):
            if not is_shift:
                send_contract_msg(player, u"&cДля сверки перевода используйте Shift + клик.")
                return
            success, message = manager.resolve_dispute(
                player, contract.id, "paid" if raw_slot == 38 else "retry")
        else:
            return
        send_contract_msg(player, message)
        if success:
            safe_play_sound(player, ["ENTITY_EXPERIENCE_ORB_PICKUP", "ENTITY_VILLAGER_YES"], 1.0, 1.0)
        if manager.get_contract(self.contract_id):
            self.build()
        else:
            AdminContractsGUI(player, self.parent_page).open(player)


class ContractDetailsGUI(BaseGUI):
    def __init__(self, player, contract_id, parent_gui="contracts"):
        super(ContractDetailsGUI, self).__init__(u"&6&lПодробности контракта", rows=4)
        self.player = player
        self.contract_id = contract_id
        self.parent_gui = parent_gui
        self.build()

    def build(self):
        if not self.inventory:
            return
        self.inventory.clear()

        mgr = ContractManager()
        contract = mgr.get_contract(self.contract_id)
        if not contract:
            return

        p_uuid = str(self.player.getUniqueId())
        is_cust = contract.is_customer(p_uuid)
        is_exec = contract.is_executor(p_uuid)
        is_cand = contract.is_candidate(p_uuid)

        # Слот 13 (Центральный инфо-предмет)
        info_item = ItemStack(Material.PAPER, 1)
        meta = info_item.getItemMeta()
        if meta:
            meta.setDisplayName(to_java_string(colorize(u"&e&l" + contract.title)))
            max_exec_str = u"Без ограничений" if contract.max_executors == -1 else str(contract.max_executors)
            lore = [
                to_java_string(colorize(u"&8&m------------------------")),
                to_java_string(colorize(u"&7Заказчик: &f" + contract.customer_name)),
                to_java_string(colorize(u"&7Описание:"))
            ]
            for d_line in wrap_text(contract.description, max_len=32, color_prefix=u"  &f"):
                lore.append(to_java_string(colorize(d_line)))
            lore.extend([
                to_java_string(colorize(u"&7Награда: &a" + contract.reward)),
                to_java_string(colorize(u"&7Исполнители: &e{0}/{1}".format(len(contract.executors), max_exec_str))),
                to_java_string(colorize(u"&7Кандидаты: &b{0} чел.".format(len(contract.candidates)))),
                to_java_string(colorize(u"&7Статус: " + ContractStatus.get_display_name(contract.status))),
                to_java_string(colorize(u"&8&m------------------------"))
            ])
            meta.setLore(lore)
            info_item.setItemMeta(meta)
        self.inventory.setItem(13, info_item)

        # Кнопки в зависимости от роли игрока:
        if is_cust:
            # Заказчик: просмотр кандидатов (Слот 20), Подтверждение (Слот 22), Отмена (Слот 24)
            cand_btn = ItemStack(Material.PLAYER_HEAD if hasattr(Material, "PLAYER_HEAD") else Material.SKULL_ITEM, 1)
            c_meta = cand_btn.getItemMeta()
            c_meta.setDisplayName(to_java_string(colorize(u"&b&lПросмотр кандидатов (&f{0}&b)".format(len(contract.candidates)))))
            c_meta.setLore([to_java_string(colorize(u"&7Нажмите для принятия/отклонения заявок"))])
            cand_btn.setItemMeta(c_meta)
            self.inventory.setItem(20, cand_btn)

            if contract.status == ContractStatus.WAITING_CONFIRMATION:
                conf_btn = ItemStack(Material.EMERALD_BLOCK, 1)
                cf_meta = conf_btn.getItemMeta()
                cf_meta.setDisplayName(to_java_string(colorize(u"&a&l✔ ПОДТВЕРДИТЬ ВЫПОЛНЕНИЕ")))
                cf_meta.setLore([to_java_string(colorize(u"&7Нажмите, если работа сдана и вы рассчитались"))])
                conf_btn.setItemMeta(cf_meta)
                self.inventory.setItem(22, conf_btn)

            del_btn = ItemStack(Material.REDSTONE_BLOCK, 1)
            d_meta = del_btn.getItemMeta()
            d_meta.setDisplayName(to_java_string(colorize(u"&c&l✖ Отменить контракт")))
            d_meta.setLore([to_java_string(colorize(u"&7Удаляет контракт из системы"))])
            del_btn.setItemMeta(d_meta)
            self.inventory.setItem(24, del_btn)

        elif is_exec:
            # Исполнитель: Сдать работу (Слот 20) и Отказаться (Слот 24)
            done_btn = ItemStack(Material.EMERALD, 1)
            dn_meta = done_btn.getItemMeta()
            dn_meta.setDisplayName(to_java_string(colorize(u"&a&l✔ Отметить выполненным")))
            dn_meta.setLore([to_java_string(colorize(u"&7Отправляет уведомление заказчику для проверки"))])
            done_btn.setItemMeta(dn_meta)
            self.inventory.setItem(20, done_btn)

            quit_btn = ItemStack(Material.BARRIER, 1)
            q_meta = quit_btn.getItemMeta()
            q_meta.setDisplayName(to_java_string(colorize(u"&c&l✖ Отказаться от выполнения")))
            q_meta.setLore([to_java_string(colorize(u"&7Удаляет вас из списка исполнителей"))])
            quit_btn.setItemMeta(q_meta)
            self.inventory.setItem(24, quit_btn)

        elif is_cand:
            status_item = ItemStack(Material.GOLD_INGOT, 1)
            st_meta = status_item.getItemMeta()
            st_meta.setDisplayName(to_java_string(colorize(u"&e&lЗаявка подана (Ожидание решения)")))
            status_item.setItemMeta(st_meta)
            self.inventory.setItem(22, status_item)

        else:
            # Гость: Подать заявку
            if contract.status in [ContractStatus.OPEN, ContractStatus.ACTIVE] and contract.can_accept_more():
                apply_btn = ItemStack(Material.LIME_DYE if hasattr(Material, "LIME_DYE") else Material.EMERALD, 1)
                a_meta = apply_btn.getItemMeta()
                a_meta.setDisplayName(to_java_string(colorize(u"&a&l▶ ПОДАТЬ ЗАЯВКУ")))
                a_meta.setLore([to_java_string(colorize(u"&7Отправляет заявку заказчику"))])
                apply_btn.setItemMeta(a_meta)
                self.inventory.setItem(22, apply_btn)

        # Кнопка Назад (Слот 31)
        back_btn = ItemStack(Material.BARRIER, 1)
        b_meta = back_btn.getItemMeta()
        b_meta.setDisplayName(to_java_string(colorize(u"&c◄ Назад")))
        back_btn.setItemMeta(b_meta)
        self.inventory.setItem(31, back_btn)

    def handle_click(self, player, raw_slot, click_type, is_shift):
        mgr = ContractManager()
        contract = mgr.get_contract(self.contract_id)
        if not contract:
            return

        p_uuid = str(player.getUniqueId())
        is_cust = contract.is_customer(p_uuid)
        is_exec = contract.is_executor(p_uuid)
        is_cand = contract.is_candidate(p_uuid)

        if raw_slot == 31:
            # Назад
            if self.parent_gui == "my":
                gui = MyContractsGUI(player)
            elif self.parent_gui == "active":
                gui = ActiveContractsGUI(player)
            else:
                gui = ContractsListGUI(player)
            gui.open(player)
            return

        if is_cust:
            if raw_slot == 20:
                # Просмотр кандидатов
                gui = CandidatesManageGUI(player, self.contract_id)
                gui.open(player)
            elif raw_slot == 22 and contract.status == ContractStatus.WAITING_CONFIRMATION:
                # Подтверждение
                success, msg = mgr.confirm_completion(player, self.contract_id)
                send_contract_msg(player, msg)
                gui = MyContractsGUI(player)
                gui.open(player)
            elif raw_slot == 24:
                # Отмена
                success, msg = mgr.cancel_contract(player, self.contract_id)
                send_contract_msg(player, msg)
                gui = MyContractsGUI(player)
                gui.open(player)

        elif is_exec:
            if raw_slot == 20:
                # Отметить готовым
                success, msg = mgr.mark_done(player, self.contract_id)
                send_contract_msg(player, msg)
                self.build()
            elif raw_slot == 24:
                # Отказаться
                success, msg = mgr.quit_contract(player, self.contract_id)
                send_contract_msg(player, msg)
                gui = ActiveContractsGUI(player)
                gui.open(player)

        elif not is_cand and not is_cust and not is_exec:
            if raw_slot == 22:
                # Подать заявку
                success, msg = mgr.apply_for_contract(player, self.contract_id)
                send_contract_msg(player, msg)
                if success:
                    safe_play_sound(player, ["ENTITY_EXPERIENCE_ORB_PICKUP", "ENTITY_ITEM_PICKUP"], 1.0, 1.1)
                self.build()


# --- 6. GUI Управления Кандидатами (для Заказчика) ---
class CandidatesManageGUI(BaseGUI):
    def __init__(self, player, contract_id):
        super(CandidatesManageGUI, self).__init__(u"&6&lУправление кандидатами", rows=6)
        self.player = player
        self.contract_id = contract_id
        self.slot_mapping = {}  # slot -> cand_uuid
        self.build()

    def build(self):
        if not self.inventory:
            return
        self.inventory.clear()
        self.slot_mapping.clear()

        mgr = ContractManager()
        contract = mgr.get_contract(self.contract_id)
        if not contract:
            return

        for idx, cand in enumerate(contract.candidates[:45]):
            c_name = cand.get("name", "Unknown")
            c_uuid = cand.get("uuid")

            item = ItemStack(Material.PLAYER_HEAD if hasattr(Material, "PLAYER_HEAD") else Material.SKULL_ITEM, 1)
            meta = item.getItemMeta()
            if meta:
                meta.setDisplayName(to_java_string(colorize(u"&e&lИгрок: &f" + c_name)))
                meta.setLore([
                    to_java_string(colorize(u"&8&m------------------------")),
                    to_java_string(colorize(u"&a✔ ЛКМ — ПРИНЯТЬ в исполнители")),
                    to_java_string(colorize(u"&c✖ ПКМ — ОТКЛОНИТЬ заявку")),
                    to_java_string(colorize(u"&8&m------------------------"))
                ])

                if hasattr(meta, "setOwner") and BUKKIT_AVAILABLE:
                    try:
                        meta.setOwner(c_name)
                    except Exception:
                        pass
                item.setItemMeta(meta)

            self.inventory.setItem(idx, item)
            self.slot_mapping[idx] = c_uuid

        # Назад
        back_btn = ItemStack(Material.BARRIER, 1)
        b_meta = back_btn.getItemMeta()
        b_meta.setDisplayName(to_java_string(colorize(u"&c◄ Назад к контракту")))
        back_btn.setItemMeta(b_meta)
        self.inventory.setItem(49, back_btn)

    def handle_click(self, player, raw_slot, click_type, is_shift):
        if raw_slot == 49:
            gui = ContractDetailsGUI(player, self.contract_id, parent_gui="my")
            gui.open(player)
            return

        if raw_slot in self.slot_mapping:
            cand_uuid = self.slot_mapping[raw_slot]
            mgr = ContractManager()

            is_right = "RIGHT" in str(click_type)

            if is_right:
                # Отклонить
                success, msg = mgr.decline_candidate(player, self.contract_id, cand_uuid)
                send_contract_msg(player, msg)
            else:
                # Принять
                success, msg = mgr.accept_candidate(player, self.contract_id, cand_uuid)
                send_contract_msg(player, msg)

            self.build()


# -----------------------------------------------------------------------------
# ОБРАБОТЧИКИ ИВЕНТОВ (EVENTS)
# -----------------------------------------------------------------------------
def on_inventory_click(event):
    if not BUKKIT_AVAILABLE or event is None:
        return
    try:
        player = event.getWhoClicked()
        if not player or not hasattr(player, "getOpenInventory"):
            return

        top_inv = event.getView().getTopInventory() if hasattr(event, "getView") else None
        if not top_inv:
            return

        holder = top_inv.getHolder() if hasattr(top_inv, "getHolder") else None

        # Проверяем, является ли держатель открытого окна нашим SmartYInventoryHolder
        if holder is not None and isinstance(holder, SmartYInventoryHolder):
            gui_instance = holder.gui_instance

            clicked_inv = event.getClickedInventory() if hasattr(event, "getClickedInventory") else None
            raw_slot = event.getRawSlot() if hasattr(event, "getRawSlot") else -1
            is_shift = event.isShiftClick() if hasattr(event, "isShiftClick") else False

            # Безусловная отмена любого клика для защиты предметов
            if is_shift:
                event.setCancelled(True)

            if clicked_inv == top_inv or (raw_slot >= 0 and raw_slot < top_inv.getSize()):
                event.setCancelled(True)

                click_type = str(event.getClick()) if hasattr(event, "getClick") else "LEFT"
                gui_instance.handle_click(player, raw_slot, click_type, is_shift)

    except Exception as e:
        log_error(u"Error in InventoryClickEvent: {0}".format(e))


# -----------------------------------------------------------------------------
# ИНТЕРАКТИВНЫЙ МЕНЕДЖЕР СОЗДАНИЯ КОНТРАКТОВ В ЧАТЕ
# -----------------------------------------------------------------------------
creation_sessions = {}  # player_uuid -> {"step": 1..4, "data": {}, "time": float}


def start_contract_creation_wizard(player):
    if not player or not hasattr(player, "getUniqueId"):
        return
    p_uuid = str(player.getUniqueId())
    creation_sessions[p_uuid] = {
        "step": 1,
        "data": {},
        "time": time.time(),
        "last_input_time": 0
    }
    send_contract_msg(player, u"&eСоздание контракта (1/4): &7Напишите &fНазвание &7в чат (или &cотмена&7)")
    safe_play_sound(player, ["BLOCK_NOTE_BLOCK_PLING", "NOTE_PLING"], 0.8, 1.2)


def handle_creation_chat_input(player, message):
    if not player or not hasattr(player, "getUniqueId"):
        return False

    p_uuid = str(player.getUniqueId())
    if p_uuid not in creation_sessions:
        return False

    session = creation_sessions[p_uuid]
    now = time.time()

    # Защита от дублирования обработки однократного сообщения (200мс)
    if now - session.get("last_input_time", 0) < 0.2:
        return True

    session["last_input_time"] = now

    if now - session.get("time", now) > 120:
        creation_sessions.pop(p_uuid, None)
        send_contract_msg(player, u"&cВремя создания контракта истекло.")
        return False

    text = to_unicode(message).strip()

    if text.lower() in [u"отмена", u"cancel", u"stop", u"exit"]:
        creation_sessions.pop(p_uuid, None)
        send_contract_msg(player, u"&cСоздание контракта отменено.")
        safe_play_sound(player, ["ENTITY_VILLAGER_NO", "VILLAGER_NO"], 0.8, 1.0)
        return True

    step = session.get("step", 1)
    data = session.get("data", {})

    if step == 1:
        if not text:
            send_contract_msg(player, u"&cНазвание не может быть пустым! Напишите название:")
            return True
        data["title"] = text
        session["step"] = 2
        session["time"] = now
        send_contract_msg(player, u"&a✔ Название: &f" + text)
        send_contract_msg(player, u"&eОписание (2/4): &7Напишите &fПодробное описание &7в чат (или &cотмена&7)")
        safe_play_sound(player, ["BLOCK_NOTE_BLOCK_PLING", "NOTE_PLING"], 0.8, 1.2)
        return True

    elif step == 2:
        if not text:
            send_contract_msg(player, u"&cОписание не может быть пустым! Напишите описание:")
            return True
        data["description"] = text
        session["step"] = 3
        session["time"] = now
        send_contract_msg(player, u"&a✔ Описание сохранено!")
        send_contract_msg(player, u"&eНаграда (3/4): &7Укажите &fНаграду &7(например: &f100000$&7 или &f32 алмаза&7)")
        safe_play_sound(player, ["BLOCK_NOTE_BLOCK_PLING", "NOTE_PLING"], 0.8, 1.2)
        return True

    elif step == 3:
        if not text:
            send_contract_msg(player, u"&cНаграда не может быть пустой! Укажите награду:")
            return True
        data["reward"] = text
        session["step"] = 4
        session["time"] = now
        send_contract_msg(player, u"&a✔ Награда: &f" + text)
        send_contract_msg(player, u"&eИсполнители (4/4): &7Укажите &fКоличество &7(&f1&7, &f2&7, &f5&7 или &f-1&7 для безлимита)")
        safe_play_sound(player, ["BLOCK_NOTE_BLOCK_PLING", "NOTE_PLING"], 0.8, 1.2)
        return True

    elif step == 4:
        try:
            max_exec = int(text)
            if max_exec != -1 and max_exec < 1:
                max_exec = 1
        except ValueError:
            send_contract_msg(player, u"&cВведите число! (например: 1, 2, 5 или -1):")
            return True

        data["max_executors"] = max_exec
        creation_sessions.pop(p_uuid, None)

        p_name = to_unicode(player.getName())
        mgr = ContractManager()
        contract = mgr.create_contract(
            customer_uuid=p_uuid,
            customer_name=p_name,
            title=data["title"],
            description=data["description"],
            reward=data["reward"],
            max_executors=data["max_executors"],
            customer_player=player
        )

        if contract is None:
            send_contract_msg(player, u"&cКонтракт не создан: {0}".format(mgr.last_error))
            return True

        send_contract_msg(player, u"&a&lКонтракт &f\"{0}\" &a&lуспешно создан и опубликован!".format(contract.title))
        safe_play_sound(player, ["ENTITY_PLAYER_LEVELUP", "LEVEL_UP"], 1.0, 1.2)
        return True

    return False


def on_player_chat(event):
    if not BUKKIT_AVAILABLE or event is None:
        return
    try:
        player = event.getPlayer()
        if not player or not hasattr(player, "getUniqueId"):
            return

        p_uuid = str(player.getUniqueId())
        if p_uuid in creation_sessions:
            msg = event.getMessage()
            event.setCancelled(True)
            is_async = bool(event.isAsynchronous()) if hasattr(event, "isAsynchronous") else False
            if is_async:
                class CreationChatTask(Runnable):
                    def run(self):
                        handle_creation_chat_input(player, msg)
                plugin = get_pyspigot_plugin()
                if plugin:
                    Bukkit.getScheduler().runTask(plugin, CreationChatTask())
                else:
                    log_error(u"Cannot schedule contract wizard input: PySpigot plugin not found")
            else:
                handle_creation_chat_input(player, msg)
    except Exception as e:
        log_error(u"Error in PlayerChatEvent: {0}".format(e))


def on_inventory_close(event):
    pass


def on_player_join(event):
    try:
        ContractManager().deliver_notifications(event.getPlayer())
    except Exception as e:
        log_error(u"Error delivering contract notifications: {0}".format(e))


def on_player_quit(event):
    try:
        creation_sessions.pop(str(event.getPlayer().getUniqueId()), None)
    except Exception:
        pass


def on_inventory_drag(event):
    if not BUKKIT_AVAILABLE or event is None:
        return
    try:
        top_inv = event.getView().getTopInventory() if hasattr(event, "getView") else None
        if top_inv:
            holder = top_inv.getHolder() if hasattr(top_inv, "getHolder") else None
            if holder is not None and isinstance(holder, SmartYInventoryHolder):
                event.setCancelled(True)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# ОБРАБОТЧИК КОМАНД (COMMANDS)
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


def parse_deadline_hours(value):
    """Parse a player-entered hour count without relying on JVM locale."""
    raw = to_unicode(value).strip().replace(u",", u".")
    if not re.match(u"^[0-9]+(?:[.][0-9]+)?$", raw):
        raise ValueError("hours must be numeric")
    hours = float(raw.encode("ascii"))
    if hours <= 0.0:
        raise ValueError("hours must be positive")
    return hours


def cmd_contracts(*args):
    sender, cmd_args = parse_cmd_args(*args)
    if not hasattr(sender, "getUniqueId"):
        safe_console_send(u"Console cannot open Contracts GUI.")
        return True

    gui = ContractsMainMenuGUI(sender)
    gui.open(sender)
    return True


def cmd_contract_dispatcher(*args):
    sender, cmd_args = parse_cmd_args(*args)
    if not hasattr(sender, "getUniqueId"):
        safe_console_send(u"Console cannot use /contract.")
        return True

    if len(cmd_args) == 0:
        gui = ContractsMainMenuGUI(sender)
        gui.open(sender)
        return True

    sub = cmd_args[0].lower()

    if sub in ["menu", "hub", "main"]:
        gui = ContractsMainMenuGUI(sender)
        gui.open(sender)
        return True

    elif sub in ["list", "all"]:
        gui = ContractsListGUI(sender, page=1)
        gui.open(sender)
        return True

    elif sub in ["my", "created"]:
        gui = MyContractsGUI(sender)
        gui.open(sender)
        return True

    elif sub in ["active", "executing"]:
        gui = ActiveContractsGUI(sender)
        gui.open(sender)
        return True

    elif sub in ["admin", "moderate", "moderation"]:
        if not is_contract_admin(sender):
            send_contract_msg(sender, u"&cНет права contracts.admin.")
            return True
        AdminContractsGUI(sender, page=1).open(sender)
        return True

    elif sub in ["done", "finish"]:
        if len(cmd_args) >= 2:
            success, msg = ContractManager().mark_done(sender, cmd_args[1])
            send_contract_msg(sender, msg)
            return True
        gui = DoneContractsGUI(sender)
        gui.open(sender)
        return True

    elif sub in ["add", "create", "new"]:
        if len(cmd_args) == 1 or len(cmd_args) < 4:
            start_contract_creation_wizard(sender)
            return True

        reward = cmd_args[1]

        try:
            max_exec = int(cmd_args[2])
            if max_exec != -1 and max_exec < 1:
                max_exec = 1
        except ValueError:
            send_contract_msg(sender, u"&cМаксимальное количество исполнителей должно быть числом (например: 1, 2, 5 или -1)!")
            return True

        rest_text = u" ".join(cmd_args[3:])
        if u"|" in rest_text:
            parts = rest_text.split(u"|", 1)
            title = parts[0].strip()
            desc = parts[1].strip()
        else:
            title = rest_text.strip()
            desc = u"Без подробного описания"

        if not title:
            send_contract_msg(sender, u"&cУкажите название контракта!")
            return True

        p_uuid = str(sender.getUniqueId())
        p_name = to_unicode(sender.getName())

        mgr = ContractManager()
        contract = mgr.create_contract(p_uuid, p_name, title, desc, reward, max_exec, customer_player=sender)

        if contract is None:
            send_contract_msg(sender, u"&cКонтракт не создан: {0}".format(mgr.last_error))
            return True

        send_contract_msg(sender, u"&a&lКонтракт &f\"{0}\" &a&lуспешно создан!".format(title))
        safe_play_sound(sender, ["ENTITY_PLAYER_LEVELUP", "LEVEL_UP"], 1.0, 1.2)
        return True

    elif sub == "cancel" and len(cmd_args) >= 2:
        cid = cmd_args[1]
        mgr = ContractManager()
        success, msg = mgr.cancel_contract(sender, cid)
        send_contract_msg(sender, msg)
        return True

    elif sub == "confirm" and len(cmd_args) >= 2:
        cid = cmd_args[1]
        mgr = ContractManager()
        success, msg = mgr.confirm_completion(sender, cid)
        send_contract_msg(sender, msg)
        return True

    elif sub == "quit" and len(cmd_args) >= 2:
        cid = cmd_args[1]
        mgr = ContractManager()
        success, msg = mgr.quit_contract(sender, cid)
        send_contract_msg(sender, msg)
        return True

    elif sub == "deadline" and len(cmd_args) >= 3:
        try:
            hours = parse_deadline_hours(cmd_args[2])
            success, msg = ContractManager().set_deadline(sender, cmd_args[1], hours)
        except (ValueError, TypeError):
            success, msg = False, u"&cКоличество часов должно быть числом."
        send_contract_msg(sender, msg)
        return True

    elif sub == "milestone" and len(cmd_args) >= 4:
        action = cmd_args[1].lower()
        if action == "add":
            success, msg = ContractManager().add_milestone(sender, cmd_args[2], u" ".join(cmd_args[3:]))
        elif action == "done":
            success, msg = ContractManager().mark_milestone_done(sender, cmd_args[2], cmd_args[3])
        else:
            success, msg = False, u"&cИспользуйте milestone add|done."
        send_contract_msg(sender, msg)
        return True

    elif sub == "dispute" and len(cmd_args) >= 3:
        success, msg = ContractManager().open_dispute(sender, cmd_args[1], u" ".join(cmd_args[2:]))
        send_contract_msg(sender, msg)
        return True

    elif sub == "resolve" and len(cmd_args) >= 3:
        success, msg = ContractManager().resolve_dispute(sender, cmd_args[1], cmd_args[2])
        send_contract_msg(sender, msg)
        return True

    elif sub == "rate" and len(cmd_args) >= 4:
        try:
            success, msg = ContractManager().rate_player(sender, cmd_args[1], cmd_args[2], int(cmd_args[3]))
        except ValueError:
            success, msg = False, u"&cОценка должна быть от 1 до 5."
        send_contract_msg(sender, msg)
        return True

    elif sub == "history":
        ContractManager().show_history(sender, int(cmd_args[1]) if len(cmd_args) > 1 and cmd_args[1].isdigit() else 10)
        return True

    else:
        send_contract_msg(sender, u"&cНеизвестная подкоманда! Доступно:")
        send_contract_msg(sender, u"&e/contracts &7— Все открытые контракты")
        send_contract_msg(sender, u"&e/contract add &7— Создать новый контракт")
        send_contract_msg(sender, u"&e/contract my &7— Мои созданные контракты")
        send_contract_msg(sender, u"&e/contract active &7— Мои контракты (где я исполнитель)")
        send_contract_msg(sender, u"&e/contract done &7— Сдать работу за выполнение")
        send_contract_msg(sender, u"&e/contract deadline <id> <часы> &7— срок исполнения")
        send_contract_msg(sender, u"&e/contract milestone <add|done> <id> ... &7— этапы")
        send_contract_msg(sender, u"&e/contract dispute <id> <причина> &7— открыть спор")
        send_contract_msg(sender, u"&e/contract rate <id> <игрок> <1-5> &7— оценка участника")
        send_contract_msg(sender, u"&e/contract history [лимит] &7— архив сделок")
        if is_contract_admin(sender):
            send_contract_msg(sender, u"&e/contract admin &7— административная панель контрактов")
            send_contract_msg(sender, u"&e/contract resolve <id> <customer|executors|paid|retry> &7— решить спор/сверить перевод")
        return True


# -----------------------------------------------------------------------------
# РЕГИСТРАЦИЯ КОМАНД В BUKKIT И PYSPIGOT
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

        def tabComplete(self, sender, alias, args):
            try:
                subcommands = ["create", "add", "my", "active", "done", "cancel", "deadline",
                               "milestone", "dispute", "resolve", "rate", "history"]
                if is_contract_admin(sender):
                    subcommands.append("admin")
                if not args or len(args) <= 1:
                    prefix = str(args[0]).lower() if args and len(args) > 0 else ""
                    matched = [s for s in subcommands if s.startswith(prefix)]
                    return build_java_list(matched)
            except Exception:
                pass
            return build_java_list([])

        def onTabComplete(self, sender, command, alias, args):
            return self.tabComplete(sender, alias, args)
else:
    class PyBukkitCommand(object):
        def __init__(self, name, description="", usage="", aliases=[], executor=None, completer=None):
            self.cmd_name = name
            self.executor = executor
            self.completer = completer


def build_java_list(py_list):
    if not BUKKIT_AVAILABLE:
        return py_list
    try:
        from java.util import ArrayList
        al = ArrayList()
        for item in py_list:
            al.add(to_java_string(item))
        return al
    except Exception:
        return py_list


def force_register_bukkit_command(fallback_prefix, cmd_obj, aliases=[]):
    if not BUKKIT_AVAILABLE:
        return
    try:
        server = Bukkit.getServer()
        cmap = None
        if hasattr(server, "getCommandMap"):
            cmap = server.getCommandMap()
        else:
            try:
                field = server.getClass().getDeclaredField("commandMap")
                field.setAccessible(True)
                cmap = field.get(server)
            except Exception:
                pass

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


registered_contract_listeners = []   # dummy_listener'ы, сохранённые для HandlerList.unregisterAll()
registered_contract_commands = []    # (name, aliases) - для полного снятия при выгрузке


def register_event_directly(event_class, handler_func):
    if not BUKKIT_AVAILABLE or event_class is None:
        return False
    try:
        plugin = get_pyspigot_plugin()
        if not plugin:
            return False

        class DirectPyBukkitListener(Listener):
            pass

        class DirectPyBukkitEventExecutor(EventExecutor):
            def __init__(self, func):
                self.func = func
            def execute(self, listener, event):
                try:
                    self.func(event)
                except Exception as ex:
                    log_error(u"Error executing event handler: {0}".format(ex))

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
        # ВАЖНО: раньше dummy_listener нигде не сохранялся, из-за чего его было
        # физически невозможно снять через HandlerList.unregisterAll() при выгрузке -
        # listener навсегда оставался в PluginManager до полной остановки JVM/сервера.
        registered_contract_listeners.append(dummy_listener)
        return True
    except Exception as e:
        log_error(u"Failed direct event registration: {0}".format(e))
        return False


def unregister_contract_listeners():
    try:
        from org.bukkit.event import HandlerList
        for listener in list(registered_contract_listeners):
            try:
                HandlerList.unregisterAll(listener)
            except Exception:
                pass
        del registered_contract_listeners[:]
    except Exception:
        pass


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
    except Exception as e:
        log_error(u"Command unregistration error: {0}".format(e))


def unregister_contract_commands():
    for name, aliases in list(registered_contract_commands):
        force_unregister_bukkit_command("smarty-contracts", name, aliases)
    del registered_contract_commands[:]
    try:
        if BUKKIT_AVAILABLE and hasattr(Bukkit.getServer(), "syncCommands"):
            Bukkit.getServer().syncCommands()
    except Exception:
        pass


def register_contracts_commands():
    commands_def = [
        ("contracts", "Open list of contracts", "/contracts", ["contractboard", "jobs"], cmd_contracts, None),
        ("contract", "Contract management dispatcher", "/contract <add|my|active|done>", ["job"], cmd_contract_dispatcher, None)
    ]

    for item in commands_def:
        name, desc, usage, aliases, handler, tab_handler = item[0], item[1], item[2], item[3], item[4], item[5]
        cmd_obj = PyBukkitCommand(name, desc, usage, aliases, handler, tab_handler)
        force_register_bukkit_command("smarty-contracts", cmd_obj, aliases)
        registered_contract_commands.append((name, aliases))

    log_info(u"Contracts commands force-registered (/contracts, /contract).")


# -----------------------------------------------------------------------------
# ЖИЗНЕННЫЙ ЦИКЛ СКРИПТА PYSPIGOT (LIFECYCLE HOOKS)
# -----------------------------------------------------------------------------
def on_enable():
    log_info(u"=== Starting {0} v{1} ===".format(ContractConfig.PLUGIN_NAME, ContractConfig.VERSION))
    try:
        mgr = ContractManager()
        log_info(u"Contract database loaded ({0} active contracts).".format(len(mgr.contracts)))

        # На случай повторного on_enable() без выгрузки (например /pyspigot reload) -
        # снимаем всё, что могло остаться от предыдущего запуска, прежде чем
        # регистрировать заново (иначе получим дублирующиеся listeners/команды).
        unregister_contract_listeners()
        unregister_contract_commands()

        if BUKKIT_AVAILABLE:
            register_event_directly(InventoryClickEvent, on_inventory_click)
            register_event_directly(InventoryCloseEvent, on_inventory_close)
            register_event_directly(InventoryDragEvent, on_inventory_drag)
            register_event_directly(PlayerJoinEvent, on_player_join)
            register_event_directly(PlayerQuitEvent, on_player_quit)
            if AsyncPlayerChatEvent is not None:
                register_event_directly(AsyncPlayerChatEvent, on_player_chat)
            elif PlayerChatEvent is not None:
                register_event_directly(PlayerChatEvent, on_player_chat)
            log_info(u"Contracts GUI & Chat event listeners registered.")

        register_contracts_commands()
        log_info(u"{0} successfully enabled and ready!".format(ContractConfig.PLUGIN_NAME))

    except Exception as e:
        log_error(u"Critical error in contracts on_enable: {0}".format(e))
        import traceback
        traceback.print_exc()


def on_disable():
    log_info(u"=== Disabling {0} ===".format(ContractConfig.PLUGIN_NAME))
    unregister_contract_listeners()
    unregister_contract_commands()
    try:
        mgr = ContractManager()
        mgr.save_all()
        log_info(u"Contracts data saved to contracts.json.")
    except Exception:
        pass


def start(script=None):
    on_enable()


def stop(script=None):
    # ВАЖНО: PySpigot вызывает автоматически именно stop() (не on_disable()) при
    # /pyspigot unload <script>. Раньше эта функция отсутствовала, и вдобавок
    # register_event_directly() даже не сохранял свои dummy_listener'ы - то есть
    # listeners InventoryClick/Close/Drag и AsyncPlayerChat, а также команды
    # /contracts и /contract (внедрённые напрямую в CommandMap в обход
    # command_manager) продолжали бы работать вечно, независимо от вызова
    # /pyspigot unload.
    on_disable()


if __name__ == "__main__" or "ps" in globals() or "command_manager" in globals():
    on_enable()

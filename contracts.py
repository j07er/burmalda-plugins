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
    from java.lang import String as JavaString, System
    JAVA_STRING_AVAILABLE = True
except ImportError:
    JAVA_STRING_AVAILABLE = False
    JavaString = str
    System = None


# -----------------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ УТИЛИТЫ КОДИРОВКИ, ЦВЕТОВ И ЗВУКОВ
# -----------------------------------------------------------------------------
def to_unicode(text):
    if text is None:
        return u""
    if isinstance(text, unicode):
        u_text = text
    elif isinstance(text, str):
        try:
            u_text = text.decode("utf-8")
        except Exception:
            try:
                u_text = text.decode("cp1251")
            except Exception:
                u_text = unicode(text, "utf-8", "ignore")
    else:
        u_text = unicode(str(text))

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
    VERSION = u"1.0.0"
    PREFIX = u"&b&l[Контракты]&r "

    SCRIPT_DIR = get_script_dir()
    DATA_DIR = os.path.join(SCRIPT_DIR, "data")
    CONTRACTS_FILE = os.path.join(DATA_DIR, "contracts.json")


# -----------------------------------------------------------------------------
# СТА ТУСЫ И МОДЕЛИ ДАННЫХ (MODELS)
# -----------------------------------------------------------------------------
class ContractStatus:
    OPEN = "OPEN"                         # Идет набор кандидатов/исполнителей
    ACTIVE = "ACTIVE"                     # Есть хотя бы один подтвержденный исполнитель
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"  # Исполнитель отметил работу выполненной
    COMPLETED = "COMPLETED"               # Завершено и подтверждено заказчиком
    CANCELLED = "CANCELLED"               # Отменено заказчиком

    @staticmethod
    def get_display_name(status):
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
                 max_executors=1, status=ContractStatus.OPEN, candidates=None, executors=None, created_at=None):
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
            "created_at": self.created_at
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
            created_at=data.get("created_at")
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
        try:
            json_str = json.dumps(data, indent=2, ensure_ascii=False)
            if not isinstance(json_str, unicode):
                json_str = to_unicode(json_str)

            with io.open(temp_file, "w", encoding="utf-8") as f:
                f.write(json_str)

            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
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

    def load_contracts(self):
        if not os.path.exists(self.file_path):
            return {}
        try:
            with io.open(self.file_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                contracts_dict = {}
                for cid, cdata in raw_data.get("contracts", {}).items():
                    if isinstance(cdata, dict):
                        contract = Contract.from_dict(cdata)
                        contracts_dict[cid] = contract
                return contracts_dict
        except Exception as e:
            log_error(u"Error reading contracts.json: {0}".format(e))
            return {}

    def save_contracts(self, contracts_dict):
        data = {
            "contracts": {cid: c.to_dict() for cid, c in contracts_dict.items()}
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
        self.contracts = {}  # contract_id -> Contract
        self.load_all()

    def load_all(self):
        self.contracts = self.storage.load_contracts()
        log_info(u"Loaded {0} active contracts from storage.".format(len(self.contracts)))

    def save_all(self):
        self.storage.save_contracts(self.contracts)

    def create_contract(self, customer_uuid, customer_name, title, description, reward, max_executors=1):
        cid = "contract_" + str(int(time.time())) + "_" + str(uuid.uuid4())[:8]
        contract = Contract(
            contract_id=cid,
            title=title,
            description=description,
            reward=reward,
            customer_uuid=customer_uuid,
            customer_name=customer_name,
            max_executors=max_executors,
            status=ContractStatus.OPEN
        )
        self.contracts[cid] = contract
        self.save_all()
        log_info(u"Contract created: {0} by {1}".format(title, customer_name))
        return contract

    def get_contract(self, contract_id):
        return self.contracts.get(str(contract_id))

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

        contract.status = ContractStatus.WAITING_CONFIRMATION
        self.save_all()

        send_to_player_by_name(contract.customer_name, u"&e&lИгрок &f{0} &e&lотметил контракт &f\"{1}\" &e&lкак выполненный! Проверьте и подтвердите через /contract my.".format(
            exec_name, contract.title
        ))
        cust_player = Bukkit.getPlayer(contract.customer_name) if BUKKIT_AVAILABLE else None
        if cust_player:
            safe_play_sound(cust_player, ["ENTITY_EXPERIENCE_ORB_PICKUP", "ENTITY_VILLAGER_YES"], 1.0, 1.0)

        return True, u"&aВы отметите работу как выполненную! Заказчик получил уведомление."

    # --- 6. Подтверждение выполнения заказчиком ---
    def confirm_completion(self, customer, contract_id):
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден!"

        cust_uuid = str(customer.getUniqueId())
        if not contract.is_customer(cust_uuid):
            return False, u"&cТолько заказчик может подтверждать выполнение!"

        contract.status = ContractStatus.COMPLETED

        # Удаляем контракт из списка активных в хранилище
        self.contracts.pop(contract.id, None)
        self.save_all()

        # Уведомляем всех исполнителей
        for ex in contract.executors:
            ename = ex.get("name")
            send_to_player_by_name(ename, u"&a&lКонтракт &f\"{0}\" &a&lуспешно ЗАВЕРШЕН и закрыт заказчиком! Не забудьте рассчитаться между собой.".format(
                contract.title
            ))
            e_player = Bukkit.getPlayer(ename) if BUKKIT_AVAILABLE else None
            if e_player:
                safe_play_sound(e_player, ["ENTITY_PLAYER_LEVELUP", "LEVEL_UP"], 1.0, 1.2)

        return True, u"&aВы успешно подтвердили выполнение контракта &f\"{0}\"&a! Контракт закрыт.".format(contract.title)

    # --- 7. Отмена контракта заказчиком ---
    def cancel_contract(self, customer, contract_id):
        contract = self.get_contract(contract_id)
        if not contract:
            return False, u"&cКонтракт не найден!"

        cust_uuid = str(customer.getUniqueId())
        if not contract.is_customer(cust_uuid):
            return False, u"&cТолько заказчик может отменить контракт!"

        contract.status = ContractStatus.CANCELLED
        self.contracts.pop(contract.id, None)
        self.save_all()

        # Уведомляем кандидатов и исполнителей
        all_notified = set()
        for c in contract.candidates:
            all_notified.add(c.get("name"))
        for e in contract.executors:
            all_notified.add(e.get("name"))

        for name in all_notified:
            send_to_player_by_name(name, u"&cЗаказчик отменил контракт &f\"{0}\"&c.".format(contract.title))

        return True, u"&cКонтракт &f\"{0}\" &cбыл отменен.".format(contract.title)


# -----------------------------------------------------------------------------
# GUI LAYER (СУНДУЧНЫЕ ИНВЕНТАРИ, BASE_GUI И МЕНЮ)
# -----------------------------------------------------------------------------
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

                if hasattr(player, "setItemOnCursor") and ItemStack is not None and Material is not None:
                    try:
                        player.setItemOnCursor(ItemStack(Material.AIR, 1))
                    except Exception:
                        pass

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
            max_executors=data["max_executors"]
        )

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
            if handle_creation_chat_input(player, msg):
                event.setCancelled(True)
    except Exception as e:
        log_error(u"Error in PlayerChatEvent: {0}".format(e))


def on_inventory_close(event):
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

    elif sub in ["done", "finish"]:
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
        contract = mgr.create_contract(p_uuid, p_name, title, desc, reward, max_exec)

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

    else:
        send_contract_msg(sender, u"&cНеизвестная подкоманда! Доступно:")
        send_contract_msg(sender, u"&e/contracts &7— Все открытые контракты")
        send_contract_msg(sender, u"&e/contract add &7— Создать новый контракт")
        send_contract_msg(sender, u"&e/contract my &7— Мои созданные контракты")
        send_contract_msg(sender, u"&e/contract active &7— Мои контракты (где я исполнитель)")
        send_contract_msg(sender, u"&e/contract done &7— Сдать работу за выполнение")
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
                subcommands = ["create", "add", "my", "active", "done", "cancel"]
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

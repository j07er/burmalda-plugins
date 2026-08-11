# -*- coding: utf-8 -*-
"""
tradehall_shop.py — Двухсторонние торговые сундуки Трейдхолла (Продажа и Скупка)
Для PySpigot 0.9.1 (Jython 2.7) + Paper 1.21.11

Особенности:
 - Создание лавки: возьми предмет-товар в руку → §e/tradehall create §7→ ЛКМ по сундуку → в чат "продать 100" или "купить 50".
   Альтернативно: §aShift+ЛКМ§7 предметом-товаром по СВОБОДНОМУ сундуку без инструмента в руке.
 - Автоматическое создание таблички (Oak Wall Sign) на лицевой стороне сундука.
 - Двухсторонний режим SELL / BUY.
 - Защита сундука.
 - Фильтр предметов.
 - GUI-витрина.
 - SmartY-Economy.
 - Визуальные частицы.

Команды:
 /tradehall help
 /tradehall create        — включает режим создания лавки на 30 сек
 /tradehall list
 /tradehall remove
 /tradehall reload
"""

import os
import io
import json
import time
import shutil
import threading
import uuid

import pyspigot as ps
from java.lang import System, Byte as JByte, Long as JLong
from java.util import ArrayList, HashMap, HashSet

from org.bukkit import Bukkit, Material, Sound, Particle, Location, GameMode, NamespacedKey
from org.bukkit.block import Chest, Barrel, BlockFace
from org.bukkit.entity import Player
from org.bukkit.command import Command, TabCompleter
from org.bukkit.event.block import BlockBreakEvent, BlockPlaceEvent
from org.bukkit.event.player import PlayerInteractEvent, AsyncPlayerChatEvent, PlayerQuitEvent, PlayerJoinEvent
from org.bukkit.event.inventory import InventoryClickEvent, InventoryDragEvent, InventoryCloseEvent
from org.bukkit.inventory import ItemStack
from org.bukkit.persistence import PersistentDataType
from org.bukkit.configuration.file import YamlConfiguration

# Инициализация менеджеров PySpigot
cmd_mgr = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler = ps.scheduler

# -------------------------------------------------------------------------
# КОНСТАНТЫ И PDC
# -------------------------------------------------------------------------
KEY_GUI_ACTION = NamespacedKey.fromString("tradehall:action")
KEY_GUI_PARAM = NamespacedKey.fromString("tradehall:param")

DATA_DIR = os.path.join("plugins", "PySpigot", "scripts", "data")
DATA_FILE = os.path.join(DATA_DIR, "trade_shops.json")

ADMIN_NAMES = set([u"blueredtronce"])

# -------------------------------------------------------------------------
# ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# -------------------------------------------------------------------------
# {
#   "shops": {
#       "world:x,y,z": {
#           "world": "world",
#           "x": 10, "y": 64, "z": 10,
#           "owner_uuid": "...",
#           "owner_name": u"Steve",
#           "mode": "SELL",  # "SELL" (продажа) или "BUY" (скупка)
#           "price_per_item": 100.0,
#           "item_yaml": "...",
#           "created_at": 1722000000
#       }
#   }
# }
state = {
    "shops": {},
    "transactions": {},
    "sales_history": [],
    "notifications": {},
    "next_transaction_id": 1
}
trade_lock = threading.RLock()
HISTORY_LIMIT = 2000
NOTIFICATION_LIMIT = 100
EMPTY_WARNING_COOLDOWN = 6 * 60 * 60
DEFAULT_TRADE_TAX_PERCENT = 5.0

# Ожидание ввода цены в чат: uuid_str -> { "world", "x", "y", "z", "item": ItemStack }
pending_creations = {}

# ---------------------------------------------------------------------------
# CREATE-MODE: игрок должен явно активировать создание лавки через
# /tradehall create. Иначе ЛКМ по сундуку топором ломает сундук, а не
# запускает создание. Без этого режима случайные ЛКМ по чужим сундукам
# инструментами (топор/кирка) вызывали ложное предложение продать инструмент.
# uid_player -> deadline_tick_ms
creation_mode = {}
CREATION_MODE_DURATION_MS = 30 * 1000   # 30 сек на активацию режима

# Материалы-инструменты — с ними ЛКМ по сундуку это ЛОМКА, а не создание.
# (Игрок вряд ли захочет продавать НЕЗЕРИТОВЫЙ ТОПОР через торговый сундук —
# для инструментов есть отдельные аукционы, а сам сундук ЛКМ ломается.)
_TOOL_SUFFIXES = (
    "_AXE", "_PICKAXE", "_SHOVEL", "_HOE", "_SWORD",
)
_TOOL_EXACT = set([
    "SHEARS", "FISHING_ROD", "FLINT_AND_STEEL", "BOW", "CROSSBOW",
    "TRIDENT", "MACE", "BRUSH", "SPYGLASS", "SHIELD",
    "LEAD", "COMPASS", "CLOCK", "RECOVERY_COMPASS",
    "CARROT_ON_A_STICK", "WARPED_FUNGUS_ON_A_STICK",
    "GOAT_HORN", "BUCKET", "WATER_BUCKET", "LAVA_BUCKET",
    "MILK_BUCKET", "POWDER_SNOW_BUCKET",
    "DEBUG_STICK", "STRUCTURE_VOID",
])


def _is_tool_material(mat):
    """True если материал — инструмент (топор/кирка/меч/удочка/лук/...)."""
    try:
        name = mat.name()
    except Exception:
        return False
    if name in _TOOL_EXACT:
        return True
    for suf in _TOOL_SUFFIXES:
        if name.endswith(suf):
            return True
    return False


def _now_ms():
    return long(System.currentTimeMillis())


def _is_in_creation_mode(player_uid):
    """Проверка что игрок активировал режим создания и он ещё не истёк."""
    deadline = creation_mode.get(player_uid)
    if deadline is None:
        return False
    if _now_ms() > deadline:
        creation_mode.pop(player_uid, None)
        return False
    return True

# Открытые GUI: uuid_str -> { "shop_key": "world:x,y,z" }
open_guis = {}


# -------------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# -------------------------------------------------------------------------
def uid(e):
    return e.getUniqueId().toString()

def now_sec():
    return long(System.currentTimeMillis() / 1000)

def java_list(it):
    lst = ArrayList()
    for x in it:
        lst.add(x)
    return lst

def _to_unicode(s):
    if s is None:
        return u""
    if isinstance(s, unicode):
        return s
    try:
        return unicode(s, "utf-8", "replace")
    except Exception:
        try:
            return unicode(s)
        except Exception:
            return u""

def _norm(s):
    return _to_unicode(s).strip().lower()

def _is_admin(sender):
    if not isinstance(sender, Player):
        return True
    # ИСПРАВЛЕНО: раньше здесь по ошибке (copy-paste) проверялось право
    # "smarty.cities.admin" - право СОВЕРШЕННО ДРУГОГО плагина (система городов).
    # Это была настоящая эскалация привилегий: любой игрок с правом городского
    # администратора (например, мэр или модератор городов через LuckPerms)
    # автоматически получал полные права администратора Трейдхолла - мог удалять
    # чужие торговые лавки, обходить защиту владения сундуком, релоадить базу
    # данных - хотя ему никогда не выдавали именно "smarty.tradehall.admin".
    return sender.getName().lower() in ADMIN_NAMES or sender.isOp() or sender.hasPermission("smarty.tradehall.admin")

def get_block_key(block):
    if not block:
        return ""
    return "%s:%d,%d,%d" % (block.getWorld().getName(), block.getX(), block.getY(), block.getZ())

def format_currency(amount):
    try:
        val = float(amount)
        # ФИКС "nan$": round/format в Jython 2.7 молча пропускают NaN/Infinity,
        # возвращая строку "nan$"/"inf$" вместо ошибки. Явный гард ниже.
        if val != val or val == float("inf") or val == float("-inf"):
            return u"0$"
        return _to_unicode("{:,.2f}".format(val)).replace(".00", "").replace(",", " ") + u"$"
    except Exception:
        return u"0$"

# -------------------------------------------------------------------------
# СЕРИАЛИЗАЦИЯ И СРАВНЕНИЕ ИГРОВЫХ ПРЕДМЕТОВ (YAML)
# -------------------------------------------------------------------------
def item_to_yaml(item):
    if not item or item.getType() == Material.AIR:
        return ""
    copy = item.clone()
    copy.setAmount(1)
    conf = YamlConfiguration()
    conf.set("item", copy)
    return conf.saveToString()

def yaml_to_item(yaml_str):
    if not yaml_str:
        return None
    try:
        conf = YamlConfiguration()
        conf.loadFromString(yaml_str)
        return conf.getItemStack("item")
    except Exception as ex:
        Bukkit.getLogger().warning("[tradehall_shop] error parsing item yaml: " + str(ex))
        return None

def is_same_item(item1, item2):
    if not item1 or not item2:
        return False
    if item1.getType() != item2.getType():
        return False
    c1 = item1.clone()
    c1.setAmount(1)
    c2 = item2.clone()
    c2.setAmount(1)
    return c1.isSimilar(c2)

def get_item_display_name(item):
    if not item:
        return u"Предмет"
    meta = item.getItemMeta()
    if meta and meta.hasDisplayName():
        return _to_unicode(meta.getDisplayName())
    return _to_unicode(item.getType().name()).replace("_", " ").title()

# -------------------------------------------------------------------------
# ОПРЕДЕЛЕНИЕ ЛИЦЕВОЙ СТОРОНЫ СУНДУКА И УПРАВЛЕНИЕ ТАБЛИЧКАМИ
# -------------------------------------------------------------------------
def get_chest_front_face(block):
    if not block:
        return None
    try:
        data = block.getBlockData()
        if hasattr(data, "getFacing"):
            facing = data.getFacing()
            if str(facing.name()) in ("NORTH", "SOUTH", "EAST", "WEST"):
                return facing
    except Exception:
        pass
    # Если не удалось определить через getFacing, ищем свободный блок по сторонам
    try:
        for f_name in ("NORTH", "SOUTH", "EAST", "WEST"):
            f = BlockFace.valueOf(f_name)
            rel = block.getRelative(f)
            if rel.getType() == Material.AIR:
                return f
    except Exception:
        pass
    return None

def update_shop_sign(shop, sample_item):
    """
    Создаёт или обновляет настенную табличку на лицевой стороне сундука:
      [ПРОДАЖА] или [СКУПКА]
      Название товара
      Цена$ / шт.
      Ник владельца
    """
    try:
        world = Bukkit.getWorld(shop["world"])
        if not world:
            return
        block = world.getBlockAt(int(shop["x"]), int(shop["y"]), int(shop["z"]))
        if not block or block.getType() == Material.AIR:
            return
        facing = get_chest_front_face(block)
        if not facing:
            return
        sign_block = block.getRelative(facing)
        is_air = (sign_block.getType() in (Material.AIR, Material.CAVE_AIR))
        is_sign = str(sign_block.getType().name()).endswith("_SIGN")
        if is_air or is_sign:
            if not is_sign:
                sign_block.setType(Material.OAK_WALL_SIGN)
            try:
                s_data = sign_block.getBlockData()
                if hasattr(s_data, "setFacing"):
                    s_data.setFacing(facing)
                    sign_block.setBlockData(s_data)
            except Exception:
                pass
            sign_state = sign_block.getState()
            if hasattr(sign_state, "setLine"):
                mode_str = u"§a§l[ПРОДАЖА]" if shop.get("mode") == "SELL" else u"§b§l[СКУПКА]"
                name_str = u"§f" + get_item_display_name(sample_item)[:14]
                price_str = u"§e" + format_currency(shop.get("price_per_item", 0.0)) + u" / шт."
                owner_str = u"§8" + shop.get("owner_name", u"?")[:14]
                sign_state.setLine(0, _to_unicode(mode_str))
                sign_state.setLine(1, _to_unicode(name_str))
                sign_state.setLine(2, _to_unicode(price_str))
                sign_state.setLine(3, _to_unicode(owner_str))
                sign_state.update(True)
    except Exception as ex:
        Bukkit.getLogger().warning("[tradehall_shop] error updating sign: " + str(ex))

def remove_shop_sign(shop):
    try:
        world = Bukkit.getWorld(shop["world"])
        if not world:
            return
        block = world.getBlockAt(int(shop["x"]), int(shop["y"]), int(shop["z"]))
        if not block:
            return
        facing = get_chest_front_face(block)
        if facing:
            sign_block = block.getRelative(facing)
            if str(sign_block.getType().name()).endswith("_SIGN"):
                sign_block.setType(Material.AIR)
    except Exception:
        pass

def find_shop_by_clicked_block(block):
    """
    Возвращает b_key сундука, если игрок кликнул либо по самому сундуку,
    либо по табличке, прикреплённой к нему.
    """
    if not block:
        return None
    b_key = get_block_key(block)
    if b_key in state["shops"]:
        return b_key
    # Если кликнули по табличке, проверяем соседние блоки на наличие лавки
    if str(block.getType().name()).endswith("_SIGN"):
        try:
            for f_name in ("NORTH", "SOUTH", "EAST", "WEST", "UP", "DOWN"):
                f = BlockFace.valueOf(f_name)
                adj = block.getRelative(f)
                adj_key = get_block_key(adj)
                if adj_key in state["shops"]:
                    return adj_key
        except Exception:
            pass
    return None

# -------------------------------------------------------------------------
# ИНТЕГРАЦИЯ ЭКОНОМИКИ (SmartY-Economy / PySpigot)
# -------------------------------------------------------------------------
class EconomyHelper(object):
    @staticmethod
    def get_manager():
        try:
            props = System.getProperties()
            mgr = props.get("SmartY_EconomyManager")
            if not mgr:
                mgr = props.get("PySpigot_EconomyManager")
            return mgr
        except Exception:
            return None

    @staticmethod
    def get_balance(uuid_str):
        mgr = EconomyHelper.get_manager()
        if mgr:
            try:
                return float(mgr.get_balance(uuid_str))
            except Exception:
                pass
        return 0.0

    @staticmethod
    def withdraw(uuid_str, amount):
        mgr = EconomyHelper.get_manager()
        if mgr:
            try:
                return bool(mgr.withdraw(uuid_str, float(amount)))
            except Exception:
                pass
        return False

    @staticmethod
    def deposit(uuid_str, amount, name=None):
        mgr = EconomyHelper.get_manager()
        if mgr:
            try:
                return float(mgr.deposit(uuid_str, float(amount), name if name else u"Unknown"))
            except Exception:
                pass
        return 0.0

    @staticmethod
    def deposit_checked(uuid_str, amount, name=None):
        mgr = EconomyHelper.get_manager()
        if not mgr:
            return False
        try:
            if hasattr(mgr, "deposit_checked"):
                result = mgr.deposit_checked(uuid_str, float(amount), name if name else u"Unknown")
                return bool(result[0] if isinstance(result, (tuple, list)) else result)
            mgr.deposit(uuid_str, float(amount), name if name else u"Unknown")
            return True
        except Exception:
            return False


class TownHelper(object):
    @staticmethod
    def manager():
        try:
            return System.getProperties().get("SmartY_TownState")
        except Exception:
            return None

    @staticmethod
    def get_city(uuid_str):
        manager = TownHelper.manager()
        if manager and hasattr(manager, "get_city_by_player"):
            try:
                return manager.get_city_by_player(str(uuid_str))
            except Exception:
                pass
        return None

    @staticmethod
    def get_city_by_name(name):
        manager = TownHelper.manager()
        if name and manager and hasattr(manager, "get_city_by_name"):
            try:
                return manager.get_city_by_name(_to_unicode(name))
            except Exception:
                pass
        return None

    @staticmethod
    def city_name(city):
        if city is None:
            return u""
        try:
            return _to_unicode(city.get("name"))
        except Exception:
            try:
                return _to_unicode(city["name"])
            except Exception:
                return u""

    @staticmethod
    def tax_percent(city):
        name = TownHelper.city_name(city)
        manager = TownHelper.manager()
        if name and manager and hasattr(manager, "get_company_tax_percent"):
            try:
                return max(0.0, min(100.0, float(manager.get_company_tax_percent(
                    name, "tradehall", DEFAULT_TRADE_TAX_PERCENT))))
            except Exception:
                pass
        return 0.0

    @staticmethod
    def add_tax(city, amount):
        if amount <= 0:
            return True
        name = TownHelper.city_name(city)
        manager = TownHelper.manager()
        if not name or not manager or not hasattr(manager, "add_company_tax"):
            return False
        try:
            result = manager.add_company_tax(name, float(amount))
            return bool(result[0] if isinstance(result, (tuple, list)) else result)
        except Exception:
            return False


def queue_notification(uuid_str, text):
    queue = state.setdefault("notifications", {}).setdefault(str(uuid_str), [])
    queue.append({"time": now_sec(), "text": _to_unicode(text)})
    if len(queue) > NOTIFICATION_LIMIT:
        del queue[:-NOTIFICATION_LIMIT]


def notify_player(uuid_str, name, text):
    try:
        player = Bukkit.getPlayer(name)
    except Exception:
        player = None
    if player and player.isOnline():
        player.sendMessage(_to_unicode(text))
    else:
        queue_notification(uuid_str, text)


def on_player_join(event):
    player = event.getPlayer()
    player_uuid = uid(player)
    queued = list(state.setdefault("notifications", {}).get(player_uuid, []))
    if queued:
        state["notifications"].pop(player_uuid, None)
        if not _save():
            state["notifications"][player_uuid] = queued
            player.sendMessage(u"§6§l[Трейдхолл] §cНе удалось подтвердить выдачу офлайн-уведомлений; они сохранены до следующего входа.")
            return
        player.sendMessage(u"§6§l[Трейдхолл] §eОфлайн-уведомления:")
        for entry in queued:
            player.sendMessage(_to_unicode(entry.get("text", u"")))

# -------------------------------------------------------------------------
# ЗАГРУЗКА И СОХРАНЕНИЕ БАЗЫ ДАННЫХ
# -------------------------------------------------------------------------
def _load():
    global state
    try:
        if not os.path.exists(DATA_FILE) and not os.path.exists(DATA_FILE + ".bak"):
            state = {"shops": {}, "transactions": {}, "sales_history": [],
                     "notifications": {}, "next_transaction_id": 1}
            return
        loaded = None
        for candidate in [DATA_FILE, DATA_FILE + ".bak"]:
            if not os.path.exists(candidate):
                continue
            try:
                f = io.open(candidate, "r", encoding="utf-8")
                try:
                    raw = f.read()
                finally:
                    f.close()
                if raw.strip():
                    loaded = json.loads(raw)
                    break
            except Exception as ex:
                Bukkit.getLogger().warning("[tradehall_shop] load candidate error: " + str(ex))
        if loaded is None:
            raise IOError("primary and backup tradehall storage are unreadable")
        state = loaded
        state.setdefault("shops", {})
        state.setdefault("transactions", {})
        state.setdefault("sales_history", [])
        state.setdefault("notifications", {})
        state.setdefault("next_transaction_id", 1)
        for shop in state["shops"].values():
            shop.setdefault("empty_warned_at", 0)
            shop.setdefault("sales_count", 0)
            shop.setdefault("sales_volume", 0.0)
    except Exception as ex:
        Bukkit.getLogger().warning("[tradehall_shop] load error: " + str(ex))
        raise

def _save():
    try:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        text = json.dumps(state, ensure_ascii=False, indent=2)
        if isinstance(text, str):
            text = text.decode("utf-8", "replace")
        temp_file = DATA_FILE + ".tmp"
        if os.path.exists(DATA_FILE):
            try:
                shutil.copy2(DATA_FILE, DATA_FILE + ".bak")
            except Exception:
                pass
        f = io.open(temp_file, "w", encoding="utf-8")
        try:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        finally:
            f.close()
        try:
            from java.nio.file import Files, Paths, StandardCopyOption
            Files.move(Paths.get(temp_file), Paths.get(DATA_FILE), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        except Exception:
            if os.path.exists(DATA_FILE):
                os.remove(DATA_FILE)
            os.rename(temp_file, DATA_FILE)
        return True
    except Exception as ex:
        Bukkit.getLogger().warning("[tradehall_shop] save error: " + str(ex))
        return False

# -------------------------------------------------------------------------
# РАБОТА С ИНВЕНТАРЁМ СУНДУКА
# -------------------------------------------------------------------------
def get_shop_chest_inventory(shop):
    world = Bukkit.getWorld(shop["world"])
    if not world:
        return None
    block = world.getBlockAt(int(shop["x"]), int(shop["y"]), int(shop["z"]))
    if not block or block.getType() == Material.AIR:
        return None
    state_obj = block.getState()
    if hasattr(state_obj, "getInventory"):
        return state_obj.getInventory()
    return None

def count_items_in_chest(inv, sample_item):
    if not inv or not sample_item:
        return 0
    total = 0
    for item in inv.getContents():
        if is_same_item(item, sample_item):
            total += item.getAmount()
    return total

def count_free_space_in_chest(inv, sample_item):
    if not inv or not sample_item:
        return 0
    max_stack = sample_item.getMaxStackSize()
    space = 0
    for item in inv.getContents():
        if not item or item.getType() == Material.AIR:
            space += max_stack
        elif is_same_item(item, sample_item):
            space += max(0, max_stack - item.getAmount())
    return space

def remove_items_from_chest(inv, sample_item, amount_to_remove):
    if not inv or not sample_item or amount_to_remove <= 0:
        return False
    if count_items_in_chest(inv, sample_item) < amount_to_remove:
        return False
    rem = amount_to_remove
    for i, item in enumerate(inv.getContents()):
        if is_same_item(item, sample_item):
            if item.getAmount() <= rem:
                rem -= item.getAmount()
                inv.setItem(i, None)
            else:
                item.setAmount(item.getAmount() - rem)
                rem = 0
            if rem <= 0:
                break
    return True

def add_items_to_chest(inv, sample_item, amount_to_add):
    if not inv or not sample_item or amount_to_add <= 0:
        return False
    if count_free_space_in_chest(inv, sample_item) < amount_to_add:
        return False
    # Bukkit does not guarantee that an over-sized ItemStack will be split on
    # every inventory implementation. Add only legal stacks.
    remaining = int(amount_to_add)
    max_stack = max(1, int(sample_item.getMaxStackSize()))
    inserted = 0
    while remaining > 0:
        copy = sample_item.clone()
        batch = min(max_stack, remaining)
        copy.setAmount(batch)
        leftovers = inv.addItem(copy)
        if leftovers and len(leftovers) > 0:
            if inserted > 0:
                remove_matching_items(inv, sample_item, inserted)
            return False
        inserted += batch
        remaining -= batch
    return True

# -------------------------------------------------------------------------
# ГЕНЕРАТОРЫ ИКОНОК ДЛЯ GUI
# -------------------------------------------------------------------------
def make_item(mat, name, lore_list=None, action=None, param=None):
    item = ItemStack(mat, 1)
    meta = item.getItemMeta()
    if name:
        meta.setDisplayName(name)
    if lore_list:
        meta.setLore(java_list(lore_list))
    if action:
        meta.getPersistentDataContainer().set(KEY_GUI_ACTION, PersistentDataType.STRING, _to_unicode(action))
    if param:
        meta.getPersistentDataContainer().set(KEY_GUI_PARAM, PersistentDataType.STRING, _to_unicode(param))
    item.setItemMeta(meta)
    return item

def make_shop_display_icon(shop, sample_item):
    copy = sample_item.clone()
    copy.setAmount(1)
    meta = copy.getItemMeta()

    mode = shop.get("mode", "SELL")
    owner_name = shop.get("owner_name", u"Неизвестно")
    price = float(shop.get("price_per_item", 100.0))
    inv = get_shop_chest_inventory(shop)
    in_stock = count_items_in_chest(inv, sample_item)
    free_space = count_free_space_in_chest(inv, sample_item)
    owner_bal = EconomyHelper.get_balance(shop.get("owner_uuid"))

    existing_lore = []
    if meta and meta.hasLore() and meta.getLore():
        for line in meta.getLore():
            existing_lore.append(_to_unicode(line))

    if mode == "SELL":
        header_lore = [
            u"§8---------------------------",
            u"§7Продавец: §6" + owner_name,
            u"§7Тип лавки: §a§lПРОДАЖА ТОВАРА",
            u"§7Цена за 1 шт.: §e" + format_currency(price),
            u"§7В сундуке в наличии: §a" + str(in_stock) + u" шт.",
            u"§8---------------------------"
        ]
    else:
        header_lore = [
            u"§8---------------------------",
            u"§7Скупщик: §6" + owner_name,
            u"§7Тип лавки: §b§lСКУПКА ТОВАРА",
            u"§7Скупает по цене: §e" + format_currency(price) + u" / шт.",
            u"§7Свободного места в сундуке: §a" + str(free_space) + u" шт.",
            u"§7Баланс скупщика: §a" + format_currency(owner_bal),
            u"§8---------------------------"
        ]

    full_lore = header_lore + existing_lore
    meta.setLore(java_list(full_lore))
    copy.setItemMeta(meta)
    return copy

# -------------------------------------------------------------------------
# ОТРИСОВКА GUI ПОКУПКИ / ПРОДАЖИ (27 СЛОТОВ)
# -------------------------------------------------------------------------
def open_shop_gui(player, shop_key):
    shop = state["shops"].get(shop_key)
    if not shop:
        player.sendMessage(u"§c✗ §7Этот торговый сундук больше не существует!")
        return

    sample_item = yaml_to_item(shop.get("item_yaml"))
    if not sample_item:
        player.sendMessage(u"§c✗ §7Ошибка данных товара в торговом сундуке!")
        return

    mode = shop.get("mode", "SELL")
    title = u"§8[Трейдхолл] §0" + (u"Покупка: " if mode == "SELL" else u"Скупка: ") + get_item_display_name(sample_item)[:16]
    inv = Bukkit.createInventory(None, 27, title)

    # Слот 4: Главная карточка осмотра предмета
    inv.setItem(4, make_shop_display_icon(shop, sample_item))

    price = float(shop.get("price_per_item", 100.0))

    if mode == "SELL":
        lore_1 = [
            u"§7Купить 1 штуку товара.",
            u"§7Стоимость: §e" + format_currency(price),
            u"",
            u"§eЛКМ §7— купить 1 шт."
        ]
        inv.setItem(10, make_item(Material.EMERALD, u"§a§lКупить 1 шт.", lore_1, "trade", "1"))

        lore_16 = [
            u"§7Купить 16 штук товара.",
            u"§7Стоимость: §e" + format_currency(price * 16),
            u"",
            u"§eЛКМ §7— купить 16 шт."
        ]
        inv.setItem(12, make_item(Material.EMERALD, u"§a§lКупить 16 шт.", lore_16, "trade", "16"))

        lore_64 = [
            u"§7Купить стак (64 шт.) товара.",
            u"§7Стоимость: §e" + format_currency(price * 64),
            u"",
            u"§eЛКМ §7— купить стак"
        ]
        inv.setItem(14, make_item(Material.EMERALD_BLOCK, u"§a§lКупить стак (64 шт.)", lore_64, "trade", "64"))

        lore_all = [
            u"§7Купить всё доступное в сундуке",
            u"§7(на сколько хватит монет и места).",
            u"",
            u"§eЛКМ §7— купить всё доступное"
        ]
        inv.setItem(16, make_item(Material.GOLD_BLOCK, u"§e§lКупить ВСЁ доступное", lore_all, "trade", "all"))

    else:
        lore_1 = [
            u"§7Продать 1 шт. вашего товара скупщику.",
            u"§7Вы получите: §a" + format_currency(price),
            u"",
            u"§eЛКМ §7— продать 1 шт."
        ]
        inv.setItem(10, make_item(Material.GOLD_NUGGET, u"§b§lПродать 1 шт.", lore_1, "trade", "1"))

        lore_16 = [
            u"§7Продать 16 шт. вашего товара скупщику.",
            u"§7Вы получите: §a" + format_currency(price * 16),
            u"",
            u"§eЛКМ §7— продать 16 шт."
        ]
        inv.setItem(12, make_item(Material.GOLD_INGOT, u"§b§lПродать 16 шт.", lore_16, "trade", "16"))

        lore_64 = [
            u"§7Продать стак (64 шт.) скупщику.",
            u"§7Вы получите: §a" + format_currency(price * 64),
            u"",
            u"§eЛКМ §7— продать стак"
        ]
        inv.setItem(14, make_item(Material.GOLD_BLOCK, u"§b§lПродать стак (64 шт.)", lore_64, "trade", "64"))

        lore_all = [
            u"§7Продать все предметы этого типа",
            u"§7из вашего инвентаря скупщику.",
            u"",
            u"§eЛКМ §7— продать всё из инвентаря"
        ]
        inv.setItem(16, make_item(Material.DIAMOND_BLOCK, u"§e§lПродать ВСЁ из инвентаря", lore_all, "trade", "all"))

    inv.setItem(22, make_item(Material.DARK_OAK_DOOR, u"§c§lЗакрыть меню", [u"§7Закрыть окно лавки"], "close_gui"))

    player.openInventory(inv)
    open_guis[uid(player)] = {"shop_key": shop_key}

# -------------------------------------------------------------------------
# ОБРАБОТЧИК КЛИКОВ В GUI ТОРГОВЛИ
# -------------------------------------------------------------------------
def on_inventory_click(event):
    who = event.getWhoClicked()
    if not isinstance(who, Player):
        return
    u_key = uid(who)

    if u_key in open_guis and u"§8[Трейдхолл]" in event.getView().getTitle():
        event.setCancelled(True)
        clicked = event.getCurrentItem()
        if not clicked or clicked.getType() == Material.AIR:
            return
        meta = clicked.getItemMeta()
        if not meta:
            return
        pdc = meta.getPersistentDataContainer()
        if not pdc.has(KEY_GUI_ACTION, PersistentDataType.STRING):
            return

        action = pdc.get(KEY_GUI_ACTION, PersistentDataType.STRING)
        param = pdc.get(KEY_GUI_PARAM, PersistentDataType.STRING) if pdc.has(KEY_GUI_PARAM, PersistentDataType.STRING) else None

        who.playSound(who.getLocation(), Sound.UI_BUTTON_CLICK, 0.7, 1.0)

        if action == u"close_gui":
            who.closeInventory()
            return
        elif action == u"trade":
            shop_key = open_guis[u_key]["shop_key"]
            shop = state["shops"].get(shop_key)
            if not shop:
                who.sendMessage(u"§c✗ §7Лавка больше не существует!")
                who.closeInventory()
                return
            execute_trade(who, shop, param)
            return

    # Защита сундука: блокировка посторонних предметов в торговом сундуке
    inv_clicked = event.getClickedInventory()
    if inv_clicked and hasattr(inv_clicked, "getLocation") and inv_clicked.getLocation():
        loc = inv_clicked.getLocation()
        b_key = get_block_key(loc.getBlock())
        if b_key in state["shops"]:
            shop = state["shops"][b_key]
            sample = yaml_to_item(shop.get("item_yaml"))
            cursor = event.getCursor()
            if cursor and cursor.getType() != Material.AIR:
                if not is_same_item(cursor, sample):
                    event.setCancelled(True)
                    who.sendMessage(u"§c✗ §7В эту торговую лавку можно складывать только: §f" + get_item_display_name(sample))
                    return

def on_inventory_drag(event):
    inv = event.getInventory()
    if inv and hasattr(inv, "getLocation") and inv.getLocation():
        loc = inv.getLocation()
        b_key = get_block_key(loc.getBlock())
        if b_key in state["shops"]:
            shop = state["shops"][b_key]
            sample = yaml_to_item(shop.get("item_yaml"))
            cursor = event.getOldCursor()
            if cursor and cursor.getType() != Material.AIR:
                if not is_same_item(cursor, sample):
                    event.setCancelled(True)
                    event.getWhoClicked().sendMessage(u"§c✗ §7В эту торговую лавку можно складывать только: §f" + get_item_display_name(sample))

def on_inventory_close(event):
    who = event.getPlayer()
    if isinstance(who, Player):
        open_guis.pop(uid(who), None)

# -------------------------------------------------------------------------
# СОЗДАНИЕ И ВЗАИМОДЕЙСТВИЕ С СУНДУКОМ / ТАБЛИЧКОЙ (PLAYER INTERACT EVENT)
# -------------------------------------------------------------------------
def _transaction_update(tx, status, error=None):
    tx["status"] = status
    tx["updated_at"] = now_sec()
    if error:
        tx["error"] = _to_unicode(error)
    _save()


def _archive_sale(tx, shop):
    record = dict(tx)
    record.pop("error", None)
    state.setdefault("sales_history", []).append(record)
    if len(state["sales_history"]) > HISTORY_LIMIT:
        del state["sales_history"][:-HISTORY_LIMIT]
    shop["sales_count"] = int(shop.get("sales_count", 0)) + 1
    shop["sales_volume"] = round(float(shop.get("sales_volume", 0.0)) + float(tx.get("gross", 0.0)), 2)
    state.setdefault("transactions", {}).pop(tx["id"], None)
    _save()


def _warn_empty_stock(shop, sample_item, inv_chest):
    if shop.get("mode") != "SELL" or count_items_in_chest(inv_chest, sample_item) > 0:
        if count_items_in_chest(inv_chest, sample_item) > 0:
            shop["empty_warned_at"] = 0
        return
    now = now_sec()
    if now - int(shop.get("empty_warned_at", 0)) < EMPTY_WARNING_COOLDOWN:
        return
    shop["empty_warned_at"] = now
    notify_player(shop.get("owner_uuid"), shop.get("owner_name"),
                  u"§6§l[Трейдхолл] §cВ лавке закончился товар: §f%s§c." % get_item_display_name(sample_item))
    _save()


def _trade_failure(player, tx, message):
    _transaction_update(tx, "ROLLED_BACK", message)
    player.sendMessage(u"§c✗ §7Сделка отменена: " + _to_unicode(message))
    try:
        player.playSound(player.getLocation(), Sound.ENTITY_VILLAGER_NO, 1.0, 1.0)
    except Exception:
        pass


def _trade_compensation_failure(player, tx, message):
    _transaction_update(tx, "AMBIGUOUS_COMPENSATION", message)
    player.sendMessage(u"§cСделка остановлена; компенсацию нужно проверить администратору. ID: §f" + tx.get("id"))


def execute_trade(buyer_or_seller, shop, param):
    """Journaled trade service with compensating inventory/money rollbacks."""
    with trade_lock:
        mode = shop.get("mode", "SELL")
        sample_item = yaml_to_item(shop.get("item_yaml"))
        inv_chest = get_shop_chest_inventory(shop)
        if not sample_item or not inv_chest:
            buyer_or_seller.sendMessage(u"§c✗ §7Лавка или образец товара недоступны.")
            return
        owner_uuid = shop.get("owner_uuid")
        owner_name = shop.get("owner_name", u"Владелец")
        actor_uuid = uid(buyer_or_seller)
        if actor_uuid == owner_uuid:
            buyer_or_seller.sendMessage(u"§c✗ §7Нельзя торговать в собственной лавке.")
            return
        price = max(0.01, float(shop.get("price_per_item", 0.0)))

        if mode == "SELL":
            available = count_items_in_chest(inv_chest, sample_item)
            affordable = int(EconomyHelper.get_balance(actor_uuid) // price)
            capacity = count_free_space_in_chest(buyer_or_seller.getInventory(), sample_item)
            qty = min(available, affordable, capacity) if param == u"all" else int(param)
            if qty <= 0 or qty > available or qty > affordable or qty > capacity:
                buyer_or_seller.sendMessage(u"§c✗ §7Недостаточно товара, денег или места в инвентаре.")
                _warn_empty_stock(shop, sample_item, inv_chest)
                return
            payer_uuid, payer_name = actor_uuid, buyer_or_seller.getName()
            receiver_uuid, receiver_name = owner_uuid, owner_name
        else:
            player_items = count_items_in_chest(buyer_or_seller.getInventory(), sample_item)
            capacity = count_free_space_in_chest(inv_chest, sample_item)
            affordable = int(EconomyHelper.get_balance(owner_uuid) // price)
            qty = min(player_items, affordable, capacity) if param == u"all" else int(param)
            if qty <= 0 or qty > player_items or qty > affordable or qty > capacity:
                buyer_or_seller.sendMessage(u"§c✗ §7Недостаточно товара, денег скупщика или места на складе.")
                return
            payer_uuid, payer_name = owner_uuid, owner_name
            receiver_uuid, receiver_name = actor_uuid, buyer_or_seller.getName()

        gross = round(float(qty) * price, 2)
        # The shop keeps its city affiliation from creation; changing the
        # owner's residence later must not silently reroute local sales tax.
        city = TownHelper.get_city_by_name(shop.get("town")) or TownHelper.get_city(owner_uuid)
        tax_percent = TownHelper.tax_percent(city)
        tax = round(gross * tax_percent / 100.0, 2)
        net = round(gross - tax, 2)
        tx_id = "th-{0}-{1}".format(now_sec(), str(uuid.uuid4())[:8])
        tx = {"id": tx_id, "shop_key": "%s:%s,%s,%s" % (shop.get("world"), shop.get("x"), shop.get("y"), shop.get("z")),
              "mode": mode, "actor_uuid": actor_uuid, "actor_name": buyer_or_seller.getName(),
              "owner_uuid": owner_uuid, "owner_name": owner_name, "item": get_item_display_name(sample_item),
              "item_yaml": shop.get("item_yaml"), "quantity": qty, "unit_price": price,
              "gross": gross, "tax": tax, "tax_percent": tax_percent,
              "town": TownHelper.city_name(city), "status": "PREPARED", "created_at": now_sec()}
        state.setdefault("transactions", {})[tx_id] = tx
        if not _save():
            state["transactions"].pop(tx_id, None)
            buyer_or_seller.sendMessage(u"§c✗ §7Не удалось подготовить атомарную сделку.")
            return

        if not EconomyHelper.withdraw(payer_uuid, gross):
            _trade_failure(buyer_or_seller, tx, u"списание денег не прошло")
            return
        _transaction_update(tx, "MONEY_RESERVED")

        source_inv = inv_chest if mode == "SELL" else buyer_or_seller.getInventory()
        target_inv = buyer_or_seller.getInventory() if mode == "SELL" else inv_chest
        if not remove_items_from_chest(source_inv, sample_item, qty):
            if EconomyHelper.deposit_checked(payer_uuid, gross, payer_name):
                _trade_failure(buyer_or_seller, tx, u"товар исчез со склада до завершения сделки")
            else:
                _trade_compensation_failure(buyer_or_seller, tx, u"товар исчез, возврат денег не подтверждён")
            return
        if not add_items_to_chest(target_inv, sample_item, qty):
            item_ok = add_items_to_chest(source_inv, sample_item, qty)
            money_ok = EconomyHelper.deposit_checked(payer_uuid, gross, payer_name)
            if item_ok and money_ok:
                _trade_failure(buyer_or_seller, tx, u"не удалось переместить товар")
            else:
                _trade_compensation_failure(buyer_or_seller, tx, u"неполный откат товара/денег после ошибки перемещения")
            return
        _transaction_update(tx, "ITEMS_MOVED")

        if net > 0 and not EconomyHelper.deposit_checked(receiver_uuid, net, receiver_name):
            removed_ok = remove_items_from_chest(target_inv, sample_item, qty)
            restored_ok = removed_ok and add_items_to_chest(source_inv, sample_item, qty)
            money_ok = EconomyHelper.deposit_checked(payer_uuid, gross, payer_name)
            if restored_ok and money_ok:
                _trade_failure(buyer_or_seller, tx, u"не удалось выплатить деньги получателю")
            else:
                _trade_compensation_failure(buyer_or_seller, tx, u"неполный откат после ошибки выплаты получателю")
            return

        applied_tax = tax
        if tax > 0 and not TownHelper.add_tax(city, tax):
            # A missing town integration must never eat the player's money.
            if not EconomyHelper.deposit_checked(receiver_uuid, tax, receiver_name):
                _transaction_update(tx, "AMBIGUOUS_TAX_PAYOUT", u"налог не принят городом и не возвращён получателю")
                buyer_or_seller.sendMessage(u"§cСделка проведена, но налоговая выплата требует проверки администратора: " + tx_id)
                return
            applied_tax = 0.0
        tx["tax"] = applied_tax
        tx["net"] = gross - applied_tax
        tx["status"] = "COMPLETED"

        _archive_sale(tx, shop)
        buyer_or_seller.sendMessage(u"§a✓ §7Сделка завершена: §f%d шт. %s §7за §e%s§7 (налог: §6%s§7)." %
                                    (qty, get_item_display_name(sample_item), format_currency(gross), format_currency(applied_tax)))
        buyer_or_seller.playSound(buyer_or_seller.getLocation(), Sound.ENTITY_EXPERIENCE_ORB_PICKUP, 1.0, 1.2)
        notify_player(owner_uuid, owner_name,
                      u"§6§l[Трейдхолл] §7Сделка в вашей лавке: §f%d шт. %s§7, оборот §e%s§7, налог §6%s§7." %
                      (qty, get_item_display_name(sample_item), format_currency(gross), format_currency(applied_tax)))
        _warn_empty_stock(shop, sample_item, inv_chest)
        _save()
        open_shop_gui(buyer_or_seller, tx["shop_key"])


def on_player_interact(event):
    player = event.getPlayer()
    block = event.getClickedBlock()
    if not block or block.getType() == Material.AIR:
        return

    b_key = get_block_key(block)
    is_container = (block.getType() in (Material.CHEST, Material.TRAPPED_CHEST, Material.BARREL))
    action_name = str(event.getAction().name())
    u_player = uid(player)

    # =========================================================================
    # 1. СОЗДАНИЕ ЛАВКИ — только по явному триггеру, чтобы не мешать ломке.
    # =========================================================================
    #
    # Раньше здесь стояло: "ЛЮБОЙ ЛКМ предметом по сундуку → предложить продать".
    # Это ломало UX: игрок пытался разбить сундук топором, а скрипт отменял
    # событие и предлагал продать топор.
    #
    # Теперь создание запускается ТОЛЬКО в одном из следующих случаев:
    #   (a) LEFT_CLICK_BLOCK по сундуку + режим создания активен
    #       (игрок ввёл §e/tradehall create§7 в течение 30 сек).
    #   (b) SHIFT+LEFT_CLICK по сундуку предметом-товаром — быстрый способ
    #       без команды, но только если в руке НЕ инструмент.
    #
    # Оба варианта требуют:
    #   - сундук свободен (не занят другой лавкой),
    #   - предмет в руке не воздух и не инструмент,
    #   - в руке есть предмет для торговли.
    # =========================================================================
    if action_name == "LEFT_CLICK_BLOCK" and is_container:
        in_hand = player.getInventory().getItemInMainHand()
        has_item = (in_hand is not None and in_hand.getType() != Material.AIR)

        # 1a. Существующая лавка + владелец/админ + Shift+ЛКМ → выход (ломка
        #     обработается в on_block_break).
        if b_key in state["shops"]:
            shop = state["shops"][b_key]
            is_owner = (shop.get("owner_uuid") == u_player) or _is_admin(player)
            if is_owner and player.isSneaking():
                # Пусть штатный BlockBreakEvent обработает ломку.
                return
            # Владелец без Shift просто кликнул — подсказка, что нужен Shift.
            if is_owner and not player.isSneaking():
                # Не отменяем событие: если он держит топор, пусть ломает нормально.
                # Просто подсказка в actionbar.
                try:
                    player.sendActionBar(
                        u"§e[Трейдхолл] §7Ваша лавка. §fShift+ЛКМ§7 чтобы сломать, §fПКМ§7 чтобы открыть меню.")
                except Exception:
                    pass
                return
            # Чужая лавка — без всяких подсказок продажи; просто предупреждаем.
            # Не отменяем событие, чтобы Paper обработал стандартно (защита ломки
            # уже в on_block_break).
            try:
                player.sendActionBar(
                    u"§c✗ §7Лавка игрока §f" + shop.get("owner_name", u"?"))
            except Exception:
                pass
            return

        # 1b. Пустой сундук + условия создания.
        if not has_item:
            # Пустая рука — 100% ломка. Ничего не делаем.
            return
        if _is_tool_material(in_hand.getType()):
            # В руке инструмент — 100% ломка. Не мешаем.
            return

        # Триггер: либо активирован режим создания, либо Shift-клик.
        creation_ok = _is_in_creation_mode(u_player) or player.isSneaking()
        if not creation_ok:
            # Обычный ЛКМ товаром по свободному сундуку — не создаём лавку,
            # но подсказываем как правильно.
            try:
                player.sendActionBar(
                    u"§8[Трейдхолл] §7Чтобы создать лавку: §e/tradehall create §7или §fShift+ЛКМ")
            except Exception:
                pass
            return

        # Всё ок — запускаем создание лавки.
        creation_mode.pop(u_player, None)   # снимаем режим сразу
        copy = in_hand.clone()
        copy.setAmount(1)
        pending_creations[u_player] = {
            "world": block.getWorld().getName(),
            "x": block.getX(), "y": block.getY(), "z": block.getZ(),
            "item": copy
        }
        player.sendMessage(u"§a§l[Трейдхолл] §7Создание торговой точки для: §f" + get_item_display_name(copy))
        player.sendMessage(u"§7Напишите в чат цену за 1 шт. в формате:")
        player.sendMessage(u"  §eпродать 100 §7(вы продаёте товар игрокам по 100$ / шт.)")
        player.sendMessage(u"  §bкупить 50 §7(вы скупаете товар у игроков по 50$ / шт.)")
        player.sendMessage(u"§8(Напишите «отмена» для выхода)")
        event.setCancelled(True)
        return

    # =========================================================================
    # 2. ПКМ по сундуку/табличке лавки — GUI покупки/продажи.
    # =========================================================================
    if action_name == "RIGHT_CLICK_BLOCK":
        shop_key = find_shop_by_clicked_block(block)
        if shop_key:
            shop = state["shops"][shop_key]
            owner_uuid = shop.get("owner_uuid")

            # Если владелец или админ открывает сундук с Shift — пополнение.
            if player.isSneaking() and is_container and (u_player == owner_uuid or _is_admin(player)):
                return

            event.setCancelled(True)
            open_shop_gui(player, shop_key)
            return

# -------------------------------------------------------------------------
# ЧАТ-ОБРАБОТЧИК: ВВОД ЦЕНЫ ПРИ СОЗДАНИИ ЛАВКИ
# -------------------------------------------------------------------------
def on_player_chat(event):
    player = event.getPlayer()
    u_player = uid(player)
    if u_player not in pending_creations:
        return

    if hasattr(event, "isAsynchronous") and event.isAsynchronous():
        captured_message = _to_unicode(event.getMessage())
        event.setCancelled(True)

        class SyncCreationEvent(object):
            def getPlayer(self):
                return player
            def getMessage(self):
                return captured_message
            def setCancelled(self, value):
                pass

        scheduler.runTask(lambda: on_player_chat(SyncCreationEvent()))
        return

    msg = _norm(event.getMessage())
    event.setCancelled(True)

    if msg in (u"отмена", u"cancel", u"exit"):
        pending_creations.pop(u_player, None)
        player.sendMessage(u"§e[Трейдхолл] §7Создание лавки отменено.")
        return

    parts = msg.split()
    if len(parts) < 2:
        player.sendMessage(u"§c✗ §7Формат: §eпродать <цена> §7или §bкупить <цена>")
        return

    action_word = parts[0]
    try:
        price = float(parts[1])
        # ФИКС: NaN/Infinity раньше проходили проверку "price <= 0" молча
        # (сравнения с NaN всегда False в Python/Jython), позволяя создать
        # лавку с "битой" ценой — теперь такие значения явно отклоняются.
        if price != price or price == float("inf") or price == float("-inf"):
            raise ValueError()
        if price <= 0:
            raise ValueError()
    except Exception:
        player.sendMessage(u"§c✗ §7Укажите корректное положительное число для цены!")
        return

    mode = "SELL" if action_word in (u"продать", u"sell", u"s") else ("BUY" if action_word in (u"купить", u"buy", u"b") else None)
    if not mode:
        player.sendMessage(u"§c✗ §7Напишите §eпродать 100 §7или §bкупить 50")
        return

    req = pending_creations.pop(u_player)
    b_key = "%s:%d,%d,%d" % (req["world"], req["x"], req["y"], req["z"])

    item_yaml = item_to_yaml(req["item"])
    shop_data = {
        "world": req["world"],
        "x": req["x"], "y": req["y"], "z": req["z"],
        "owner_uuid": u_player,
        "owner_name": _to_unicode(player.getName()),
        "mode": mode,
        "price_per_item": round(price, 2),
        "item_yaml": item_yaml,
        "created_at": now_sec(),
        "town": TownHelper.city_name(TownHelper.get_city(u_player)),
        "empty_warned_at": 0,
        "sales_count": 0,
        "sales_volume": 0.0
    }
    state["shops"][b_key] = shop_data
    _save()

    # АВТОМАТИЧЕСКИ УСТАНАВЛИВАЕМ ТАБЛИЧКУ НА ЛИЦЕВОЙ СТОРОНЕ СУНДУКА
    scheduler.runTask(lambda: update_shop_sign(shop_data, req["item"]))

    mode_display = u"§a§lПРОДАЖА" if mode == "SELL" else u"§b§lСКУПКА"
    player.sendMessage(u"§a§l✓ Трейд-сундук успешно создан!")
    player.sendMessage(u"  §7Тип: " + mode_display + u" §8| §7Товар: §f" + get_item_display_name(req["item"]) + u" §8| §7Цена: §e" + format_currency(price))
    player.sendMessage(u"§8(На лицевой стороне сундука появилась табличка; чтобы открыть сундук для пополнения, нажмите Shift+ПКМ)")
    player.playSound(player.getLocation(), Sound.ENTITY_PLAYER_LEVELUP, 1.0, 1.2)

# -------------------------------------------------------------------------
# ЗАЩИТА ОТ РАЗРУШЕНИЯ СУНДУКОВ И ТАБЛИЧЕК (BLOCK BREAK EVENT)
# -------------------------------------------------------------------------
def on_block_break(event):
    block = event.getBlock()
    b_key = find_shop_by_clicked_block(block)
    if b_key in state["shops"]:
        player = event.getPlayer()
        shop = state["shops"][b_key]
        if shop.get("owner_uuid") == uid(player) or _is_admin(player):
            remove_shop_sign(shop)
            state["shops"].pop(b_key, None)
            _save()
            player.sendMessage(u"§e[Трейдхолл] §7Торговая лавка удалена.")
        else:
            event.setCancelled(True)
            player.sendMessage(u"§c✗ §7Вы не можете разрушить торговую лавку §f" + shop.get("owner_name", u"Неизвестно"))

# -------------------------------------------------------------------------
# ЧАСТИЦЫ НАЛИЧИЯ ТОВАРА (ВОКРУГ АКТИВНЫХ СУНДУКОВ)
# -------------------------------------------------------------------------
def _tick_shop_particles():
    try:
        for b_key, shop in state["shops"].items():
            world = Bukkit.getWorld(shop["world"])
            if not world:
                continue
            loc = Location(world, shop["x"] + 0.5, shop["y"] + 1.1, shop["z"] + 0.5)
            inv = get_shop_chest_inventory(shop)
            sample = yaml_to_item(shop.get("item_yaml"))
            if not inv or not sample:
                continue

            mode = shop.get("mode", "SELL")
            if mode == "SELL":
                if count_items_in_chest(inv, sample) > 0:
                    world.spawnParticle(Particle.HAPPY_VILLAGER, loc, 2, 0.2, 0.1, 0.2, 0.01)
                else:
                    _warn_empty_stock(shop, sample, inv)
            else:
                if count_free_space_in_chest(inv, sample) > 0 and EconomyHelper.get_balance(shop.get("owner_uuid")) >= float(shop.get("price_per_item", 10.0)):
                    world.spawnParticle(Particle.WAX_ON, loc, 2, 0.2, 0.1, 0.2, 0.01)
    except Exception as ex:
        pass
    scheduler.runTaskLater(_tick_shop_particles, 40)

# -------------------------------------------------------------------------
# КОМАНДЫ (/tradehall) — ПРАВИЛЬНАЯ РЕГИСТРАЦИЯ В PYSPIGOT 0.9.1
# -------------------------------------------------------------------------
def on_tradehall_command(sender, label, args):
    args_list = [_norm(x) for x in args]
    sub = args_list[0] if len(args_list) > 0 else u"help"

    if sub in [u"search", u"find", u"поиск"]:
        if not isinstance(sender, Player):
            sender.sendMessage(u"Поиск по предмету в руке доступен только игроку.")
            return True
        sample = sender.getInventory().getItemInMainHand()
        if not sample or sample.getType() == Material.AIR:
            sender.sendMessage(u"§cВозьмите искомый предмет в основную руку.")
            return True
        matches = []
        for shop_key, shop in state.get("shops", {}).items():
            shop_sample = yaml_to_item(shop.get("item_yaml"))
            if shop_sample and is_same_item(sample, shop_sample):
                inv = get_shop_chest_inventory(shop)
                amount = count_items_in_chest(inv, shop_sample) if shop.get("mode") == "SELL" else count_free_space_in_chest(inv, shop_sample)
                if amount > 0:
                    matches.append((float(shop.get("price_per_item", 0.0)), shop_key, shop, amount))
        matches.sort(key=lambda row: row[0])
        sender.sendMessage(u"§6§l[Трейдхолл] §7Найдено лавок: §f%d" % len(matches))
        for price, shop_key, shop, amount in matches[:20]:
            mode_text = u"§aПРОДАЖА" if shop.get("mode") == "SELL" else u"§bСКУПКА"
            sender.sendMessage(u"  %s §7| §e%s §7| §f%d шт. §7| §8%s" %
                               (mode_text, format_currency(price), amount, shop_key))
        return True

    if sub in [u"history", u"sales", u"журнал"]:
        if not isinstance(sender, Player) and not _is_admin(sender):
            return True
        sender_uuid = uid(sender) if isinstance(sender, Player) else None
        records = [r for r in reversed(state.get("sales_history", []))
                   if sender_uuid is None or sender_uuid in [r.get("owner_uuid"), r.get("actor_uuid")]][:15]
        sender.sendMessage(u"§6§l[Трейдхолл] §eПоследние сделки:")
        for record in records:
            sender.sendMessage(u"  §8%s §7| §f%dx %s §7| §e%s §7| налог §6%s" %
                               (record.get("id"), int(record.get("quantity", 0)), record.get("item"),
                                format_currency(record.get("gross", 0)), format_currency(record.get("tax", 0))))
        if not records:
            sender.sendMessage(u"  §7Записей нет.")
        return True

    if sub in [u"journal", u"pending"] and _is_admin(sender):
        entries = state.get("transactions", {})
        sender.sendMessage(u"§6§l[Трейдхолл] §eНезакрытые/откаченные операции: §f%d" % len(entries))
        for tx_id, tx in list(entries.items())[-20:]:
            sender.sendMessage(u"  §8%s §7| §f%s §7| §c%s" % (tx_id, tx.get("status"), tx.get("error", u"-")))
        return True

    if sub == u"list":
        sender.sendMessage(u"§8[Трейдхолл] §7Список торговых сундуков сервера: §a%d шт." % len(state["shops"]))
        for b_key, shop in list(state["shops"].items())[:15]:
            mode_str = u"§a[ПРОДАЖА]" if shop.get("mode") == "SELL" else u"§b[СКУПКА]"
            sample = yaml_to_item(shop.get("item_yaml"))
            sender.sendMessage(u"  %s §f%s §7по §e%s §7(Владелец: %s)" % (
                mode_str, get_item_display_name(sample), format_currency(shop.get("price_per_item", 0.0)), shop.get("owner_name", u"?")
            ))
        return True

    if sub == u"create":
        # Активируем режим создания лавки на 30 секунд.
        if not isinstance(sender, Player):
            sender.sendMessage(u"§cЭта команда только для игроков.")
            return True
        in_hand = sender.getInventory().getItemInMainHand()
        if not in_hand or in_hand.getType() == Material.AIR:
            sender.sendMessage(u"§c✗ §7Возьмите в руку предмет-товар, который будет продаваться/скупаться.")
            return True
        if _is_tool_material(in_hand.getType()):
            sender.sendMessage(u"§c✗ §7Инструменты нельзя выставлять в этот тип лавки (топоры/кирки/мечи и т.п.).")
            return True
        creation_mode[uid(sender)] = _now_ms() + CREATION_MODE_DURATION_MS
        sender.sendMessage(u"§a§l[Трейдхолл] §7Режим создания активен §a30 сек§7.")
        sender.sendMessage(u"  §7ЛКМ по свободному сундуку/барреллу с товаром §f" + get_item_display_name(in_hand) + u"§7 в руке.")
        sender.sendMessage(u"  §8(Или используйте §fShift+ЛКМ§8 без команды.)")
        return True

    if sub == u"remove":
        # Удаление лавки владельцем: наведись на свою лавку и введи команду.
        if not isinstance(sender, Player):
            sender.sendMessage(u"§cЭта команда только для игроков.")
            return True
        target = sender.getTargetBlockExact(6)
        if target is None:
            sender.sendMessage(u"§c✗ §7Наведитесь на сундук или табличку своей лавки (≤6 бл).")
            return True
        shop_key = find_shop_by_clicked_block(target)
        if shop_key is None or shop_key not in state["shops"]:
            sender.sendMessage(u"§c✗ §7Этот блок не является торговой лавкой.")
            return True
        shop = state["shops"][shop_key]
        if shop.get("owner_uuid") != uid(sender) and not _is_admin(sender):
            sender.sendMessage(u"§c✗ §7Эта лавка принадлежит §f" + shop.get("owner_name", u"?"))
            return True
        remove_shop_sign(shop)
        state["shops"].pop(shop_key, None)
        _save()
        sender.sendMessage(u"§a✓ §7Лавка удалена. Сундук стал обычным контейнером.")
        return True

    if sub == u"reload" and _is_admin(sender):
        _load()
        sender.sendMessage(u"§a✓ §7База данных Трейдхолла перезагружена.")
        return True

    sender.sendMessage(u"§8[Трейдхолл] §7Помощь:")
    sender.sendMessage(u"  §7• §e/tradehall create §7— активирует режим создания на 30 сек, затем ЛКМ по сундуку.")
    sender.sendMessage(u"  §7• Или §fShift+ЛКМ§7 предметом по свободному сундуку (без команды).")
    sender.sendMessage(u"  §7• После клика напишите в чат §eпродать 100§7 или §bкупить 50§7.")
    sender.sendMessage(u"  §7• §fПКМ§7 по чужой лавке — открыть меню покупки/продажи.")
    sender.sendMessage(u"  §7• §fShift+ПКМ§7 по своей лавке — пополнить сундук.")
    sender.sendMessage(u"  §7• §fShift+ЛКМ§7 по своей лавке (или §e/tradehall remove§7) — удалить лавку.")
    sender.sendMessage(u"  §e/tradehall list §7— список активных лавок сервера.")
    sender.sendMessage(u"  §e/tradehall search §7— найти лавки с предметом из основной руки.")
    sender.sendMessage(u"  §e/tradehall history §7— журнал ваших покупок и продаж.")
    if _is_admin(sender):
        sender.sendMessage(u"  §e/tradehall journal §7— незавершённые и спорные транзакции.")
    return True

# Резервная регистрация через CommandMap для мгновенного появления в Tab-Completion Bukkit
class PyBukkitCommand(Command, TabCompleter):
    def __init__(self, name, description, usage, aliases, executor):
        Command.__init__(self, name, description, usage, aliases)
        self.executor = executor

    def execute(self, sender, commandLabel, args):
        try:
            return self.executor(sender, commandLabel, list(args))
        except Exception as exc:
            Bukkit.getLogger().warning("[tradehall_shop] command error: " + str(exc))
            return True

    def tabComplete(self, *args):
        return java_list([])

    def onTabComplete(self, *args):
        return self.tabComplete(*args)

def force_register_bukkit_command(fallback_prefix, cmd_obj, aliases=[]):

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

                    alias_cmd = PyBukkitCommand(a_str, cmd_obj.getDescription(), cmd_obj.getUsage(), [], cmd_obj.executor)

                    known_commands.put(a_str, alias_cmd)

                    known_commands.put(fallback_prefix + ":" + a_str, alias_cmd)

    except Exception as e:

        Bukkit.getLogger().warning("[tradehall_shop] error force-registering Bukkit command: " + str(e))


def force_unregister_bukkit_command(fallback_prefix, name, aliases):
    """Симметрична force_register_bukkit_command - снимает команду и её алиасы
    из Bukkit CommandMap. Без этого /tradehall и /th (внедрённые напрямую в
    CommandMap в дополнение к штатной регистрации через cmd_mgr) продолжали бы
    отвечать даже после /pyspigot unload, т.к. эта копия команды находится вне
    зоны видимости PySpigot и он не может её снять сам."""
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
        Bukkit.getLogger().warning("[tradehall_shop] error force-unregistering Bukkit command: " + str(e))

# -------------------------------------------------------------------------
# РЕГИСТРАЦИЯ СЛУШАТЕЛЕЙ И КОМАНД
# -------------------------------------------------------------------------
def on_enable():
    _load()
    listener_mgr.registerListener(on_player_interact, PlayerInteractEvent)
    listener_mgr.registerListener(on_player_chat, AsyncPlayerChatEvent)
    listener_mgr.registerListener(on_block_break, BlockBreakEvent)
    listener_mgr.registerListener(on_inventory_click, InventoryClickEvent)
    listener_mgr.registerListener(on_inventory_drag, InventoryDragEvent)
    listener_mgr.registerListener(on_inventory_close, InventoryCloseEvent)
    listener_mgr.registerListener(on_player_join, PlayerJoinEvent)

    # В PySpigot 0.9.1 первым аргументом передаётся функция-обработчик (PyFunction)
    try:
        cmd_mgr.registerCommand(on_tradehall_command, "tradehall")
        cmd_mgr.registerCommand(on_tradehall_command, "th")
        cmd_mgr.registerCommand(on_tradehall_command, "thall")
    except TypeError:
        try:
            cmd_mgr.registerCommand(on_tradehall_command)
        except Exception as ex:
            Bukkit.getLogger().warning("[tradehall_shop] registerCommand fallback: " + str(ex))

    # Прямая регистрация в Bukkit CommandMap для Tab-Completion / алиасов / гарантии работы
    cmd_obj = PyBukkitCommand("tradehall", "TradeHall buy/sell shops", "/tradehall <search|list|history|reload|help>", ["th", "thall"], on_tradehall_command)
    force_register_bukkit_command("smarty-tradehall", cmd_obj, ["th", "thall"])

    scheduler.runTaskLater(_tick_shop_particles, 40)
    Bukkit.getLogger().info("[tradehall_shop] Buy & Sell TradeHall chests loaded successfully.")

def on_disable():
    _save()
    # Команды /tradehall и /th, зарегистрированные через cmd_mgr.registerCommand(),
    # PySpigot снимает автоматически. Но их ДУБЛИРУЮЩАЯ прямая копия в CommandMap
    # (force_register_bukkit_command выше) находится вне видимости PySpigot и её
    # нужно снять вручную - иначе команда продолжит работать даже после выгрузки.
    force_unregister_bukkit_command("smarty-tradehall", "tradehall", ["th", "thall"])
    try:
        if hasattr(Bukkit.getServer(), "syncCommands"):
            Bukkit.getServer().syncCommands()
    except Exception:
        pass
    Bukkit.getLogger().info("[tradehall_shop] Disabled.")


def stop(script=None):
    # ВАЖНО: PySpigot вызывает автоматически именно stop() (не on_disable()) при
    # /pyspigot unload <script>. Без этой функции on_disable() никогда не выполнялся
    # бы при ручной выгрузке - в частности, дублирующая прямая регистрация /tradehall
    # и /th в CommandMap (в обход cmd_mgr) продолжала бы отвечать даже после unload.
    on_disable()


on_enable()

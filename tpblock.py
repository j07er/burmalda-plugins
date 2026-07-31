# -*- coding: utf-8 -*-
"""
===============================================================================
SmartY-TPBlocks — Парные телепорт-блоки (Цветущий аметист)
Для PySpigot 0.9.1 (Jython 2.7) + Paper 1.21.11
===============================================================================
Механика (версия 2.0 — один общий ID на пару):
  1. Пара телепорт-блоков выдаётся администратором командой /tpblock give
     <ник> [кол-во пар]. Каждая ПАРА — это ОДИН предмет с количеством 2:
     у обоих блоков пары ОДИН И ТОТ ЖЕ уникальный ID, поэтому они СТАКАЮТСЯ
     друг с другом (максимум стака принудительно ограничен до 2 через
     ItemMeta.setMaxStackSize). Разные пары НЕ стакаются между собой, так
     как у каждой пары свой уникальный ID (разный PersistentData -> разный
     ItemMeta -> Bukkit не объединяет их в один стак).
  2. Игрок ставит оба блока пары в двух разных местах.
  3. Встаёт на один из блоков пары и нажимает Shift (крадётся) -> телепорт
     на ВТОРОЙ блок с ТЕМ ЖЕ ID (если он тоже установлен где-то в мире).
  4. Защита от мгновенного телепорта туда-обратно: после прибытия на блок
     нужно ФИЗИЧЕСКИ сойти с него (даже на секунду) и вернуться обратно,
     прежде чем Shift на этом блоке сработает снова.
  5. Если сломать один блок пары — второй перестаёт телепортировать (некуда),
     пока не будет поставлен новый блок с тем же ID. Ломание возвращает
     игроку ИМЕННО телепорт-блок (с тем же общим ID пары), а не ванильный
     цветущий аметист — если у игрока уже есть блок этой же пары в
     инвентаре, они снова СЛИПНУТСЯ в стак (т.к. ID совпадает).

Команда:
  /tpblock give <ник> [кол-во_пар=1] — выдать пару(ы) телепорт-блоков
    (только администраторам: /op или ADMIN_NAMES). Каждая запрошенная пара
    выдаётся ОДНИМ стаком из 2 одинаковых (по ID) предметов.

Крафт пока не реализован по запросу — блоки выдаются только командой.
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

import sys
try:
    if hasattr(sys, "setdefaultencoding"):
        reload(sys)
        sys.setdefaultencoding("utf-8")
except Exception:
    pass

# -----------------------------------------------------------------------------
# ИМПОРТ PYSPIGOT / BUKKIT / JAVA
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
    from org.bukkit import Bukkit, ChatColor, Material, Sound, Particle, Location
    from org.bukkit.entity import Player
    from org.bukkit.block import BlockFace
    from org.bukkit.inventory import ItemStack
    from org.bukkit.persistence import PersistentDataType
    from org.bukkit import NamespacedKey
    from org.bukkit.event.block import BlockPlaceEvent, BlockBreakEvent
    from org.bukkit.event.player import PlayerToggleSneakEvent, PlayerMoveEvent, PlayerQuitEvent
    BUKKIT_AVAILABLE = True
except ImportError:
    BUKKIT_AVAILABLE = False
    ChatColor = None
    Material = None
    Sound = None
    Particle = None
    Location = None
    Player = object
    BlockFace = None
    ItemStack = None
    PersistentDataType = None
    NamespacedKey = None
    BlockPlaceEvent = None
    BlockBreakEvent = None
    PlayerToggleSneakEvent = None
    PlayerMoveEvent = None
    PlayerQuitEvent = None

try:
    from java.lang import String as JavaString, StringBuilder, Integer as JavaInteger
    JAVA_STRING_AVAILABLE = True
except ImportError:
    JAVA_STRING_AVAILABLE = False
    JavaString = str
    StringBuilder = None
    JavaInteger = int

try:
    from java.util import UUID as JavaUUID, ArrayList as JavaArrayList
except ImportError:
    JavaUUID = None
    JavaArrayList = list


# -----------------------------------------------------------------------------
# КОНФИГУРАЦИЯ
# -----------------------------------------------------------------------------
class TPBlocksConfig(object):
    PLUGIN_NAME = u"SmartY-TPBlocks"
    VERSION = u"2.0.0"
    PREFIX = u"&5&l[\u0422\u041f-\u0431\u043b\u043e\u043a]&r "

    # Блок-основа — Цветущий аметист (визуально выделяется, в ванильном
    # выживании не добывается без Шёлкового касания, хорошо сочетается
    # с идеей уникального предмета).
    BLOCK_MATERIAL_NAME = u"BUDDING_AMETHYST"

    # Максимальный размер стака ОДНОЙ пары (оба блока с одинаковым ID).
    PAIR_MAX_STACK_SIZE = 2

    # Ник теста + админы (тот же паттерн, что и в остальных скриптах).
    ADMIN_NAMES = set([u"blueredtronce"])

    SCRIPT_DIR = None
    DATA_DIR = None
    DATA_FILE = None


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


TPBlocksConfig.SCRIPT_DIR = get_script_dir()
TPBlocksConfig.DATA_DIR = os.path.join(TPBlocksConfig.SCRIPT_DIR, "data")
TPBlocksConfig.DATA_FILE = os.path.join(TPBlocksConfig.DATA_DIR, "tp_blocks.json")


# -----------------------------------------------------------------------------
# UNICODE / ЦВЕТ / СООБЩЕНИЯ / ЛОГИ
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


def log_info(text):
    # Windows-консоль (cp866) - только ASCII в Bukkit.getLogger().
    if BUKKIT_AVAILABLE:
        try:
            Bukkit.getLogger().info("[SmartY-TPBlocks] " + str(text))
        except Exception:
            pass


def log_error(text):
    if BUKKIT_AVAILABLE:
        try:
            Bukkit.getLogger().warning("[SmartY-TPBlocks] [ERROR] " + str(text))
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


def is_admin(sender):
    if not isinstance(sender, Player):
        return True
    try:
        if sender.isOp():
            return True
    except Exception:
        pass
    try:
        return to_unicode(sender.getName()).lower() in TPBlocksConfig.ADMIN_NAMES
    except Exception:
        return False


def safe_play_sound(player, sound_candidates, volume=1.0, pitch=1.0):
    if not BUKKIT_AVAILABLE or player is None:
        return
    for s_name in sound_candidates:
        try:
            sound_enum = Sound.valueOf(s_name)
            player.playSound(player.getLocation(), sound_enum, float(volume), float(pitch))
            return
        except Exception:
            pass


def safe_spawn_particle(loc, particle_candidates, count=20):
    if not BUKKIT_AVAILABLE or loc is None or loc.getWorld() is None:
        return
    for p_name in particle_candidates:
        try:
            particle_enum = Particle.valueOf(p_name)
            loc.getWorld().spawnParticle(particle_enum, loc, count, 0.3, 0.5, 0.3, 0.01)
            return
        except Exception:
            pass


def location_key(loc):
    """Строковый ключ для местоположения БЛОКА (без дробной части)."""
    try:
        return u"{0}:{1}:{2}:{3}".format(
            to_unicode(loc.getWorld().getName()),
            int(loc.getBlockX()),
            int(loc.getBlockY()),
            int(loc.getBlockZ())
        )
    except Exception:
        return None


# -----------------------------------------------------------------------------
# PERSISTENT DATA CONTAINER — ЕДИНЫЙ ОБЩИЙ ID НА ВСЮ ПАРУ
# -----------------------------------------------------------------------------
KEY_TPBLOCK_PAIR_ID = None

if BUKKIT_AVAILABLE and NamespacedKey is not None:
    try:
        KEY_TPBLOCK_PAIR_ID = NamespacedKey.fromString("tpblocks:pair_id")
    except Exception:
        KEY_TPBLOCK_PAIR_ID = None


def make_new_pair_id():
    # Читаемый короткий уникальный ID (достаточно для избежания коллизий
    # в рамках одного сервера; не криптографический, а идентификационный).
    if JavaUUID is not None:
        try:
            return str(JavaUUID.randomUUID())
        except Exception:
            pass
    import random
    return u"{0:x}-{1:x}".format(int(time.time() * 1000), random.randint(0, 0xFFFFFF))


def create_tp_block_item(pair_id, short_label, amount=1):
    """
    Создаёт предмет(ы) телепорт-блока с ОБЩИМ для всей пары ID.
    Все предметы с одинаковым pair_id имеют идентичный ItemMeta (включая
    PersistentDataContainer), поэтому Bukkit считает их ОДИНАКОВЫМИ для
    целей стакинга — они сольются в один стак. Максимальный размер стака
    принудительно ограничен PAIR_MAX_STACK_SIZE (2), чтобы нельзя было
    натаскать больше двух блоков одной пары в один слот.
    """
    mat = Material.valueOf(TPBlocksConfig.BLOCK_MATERIAL_NAME)
    item = ItemStack(mat, int(amount))
    meta = item.getItemMeta()
    meta.setDisplayName(to_java_string(colorize(u"&d&l\u0422\u0435\u043b\u0435\u043f\u043e\u0440\u0442-\u0431\u043b\u043e\u043a &7#" + short_label)))
    lore = [
        colorize(u"&7\u041f\u043e\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u043e\u0431\u0430 \u0431\u043b\u043e\u043a\u0430 \u043f\u0430\u0440\u044b \u0432 \u0440\u0430\u0437\u043d\u044b\u0445 \u043c\u0435\u0441\u0442\u0430\u0445."),
        colorize(u"&7\u0412\u0441\u0442\u0430\u043d\u044c\u0442\u0435 \u043d\u0430 \u043e\u0434\u0438\u043d \u0438 \u043d\u0430\u0436\u043c\u0438\u0442\u0435 &fShift&7,"),
        colorize(u"&7\u0447\u0442\u043e\u0431\u044b \u0442\u0435\u043b\u0435\u043f\u043e\u0440\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c\u0441\u044f \u043d\u0430 \u0434\u0440\u0443\u0433\u043e\u0439."),
        colorize(u"&8ID \u043f\u0430\u0440\u044b: " + short_label),
    ]
    try:
        j_lore = JavaArrayList()
        for line in lore:
            j_lore.add(to_java_string(line))
        meta.setLore(j_lore)
    except Exception:
        pass

    pdc = meta.getPersistentDataContainer()
    if KEY_TPBLOCK_PAIR_ID is not None:
        pdc.set(KEY_TPBLOCK_PAIR_ID, PersistentDataType.STRING, to_java_string(pair_id))

    # ФИКС по запросу: ограничиваем стак именно до 2 (Paper API,
    # появилось в 1.20.5+; оборачиваем в try/except на случай отсутствия
    # метода на более старых сборках — тогда просто не ограничиваем стак,
    # но раздельность пар по ID продолжает работать).
    try:
        meta.setMaxStackSize(JavaInteger(TPBlocksConfig.PAIR_MAX_STACK_SIZE))
    except Exception:
        try:
            meta.setMaxStackSize(TPBlocksConfig.PAIR_MAX_STACK_SIZE)
        except Exception:
            pass

    item.setItemMeta(meta)
    return item


def create_tp_block_pair_stack():
    """Создаёт ОДИН ItemStack с количеством 2 — оба блока пары с общим ID,
    уже слипшиеся в стак (т.к. у них идентичный ItemMeta)."""
    pair_id = make_new_pair_id()
    short_label = pair_id[:8]
    return create_tp_block_item(pair_id, short_label, amount=TPBlocksConfig.PAIR_MAX_STACK_SIZE)


def get_pair_id_from_item(item):
    """Возвращает pair_id, если предмет — телепорт-блок, иначе None."""
    if item is None or KEY_TPBLOCK_PAIR_ID is None:
        return None
    try:
        if item.getType() != Material.valueOf(TPBlocksConfig.BLOCK_MATERIAL_NAME):
            return None
        if not item.hasItemMeta():
            return None
        meta = item.getItemMeta()
        pdc = meta.getPersistentDataContainer()
        if not pdc.has(KEY_TPBLOCK_PAIR_ID, PersistentDataType.STRING):
            return None
        return to_unicode(pdc.get(KEY_TPBLOCK_PAIR_ID, PersistentDataType.STRING))
    except Exception:
        return None


# -----------------------------------------------------------------------------
# ХРАНИЛИЩЕ РАЗМЕЩЁННЫХ БЛОКОВ (JSON, переживает рестарт сервера)
# -----------------------------------------------------------------------------
class TPBlocksStorage(object):
    """
    data["pairs"][pair_id] = { loc_key: {"world":..,"x":..,"y":..,"z":..}, ... }
        -- список МЕСТ, где сейчас установлен блок с этим pair_id (обычно 0-2).
    data["locations"][loc_key] = pair_id
        -- обратный индекс: по месту блока быстро находим его pair_id
           (нужен для BlockBreakEvent и для поиска "с какого блока стоим").
    """
    def __init__(self):
        self.data = {"pairs": {}, "locations": {}}
        self.load()

    def load(self):
        self.data = {"pairs": {}, "locations": {}}
        if not os.path.exists(TPBlocksConfig.DATA_FILE):
            return
        try:
            with open(TPBlocksConfig.DATA_FILE, "r") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    self.data["pairs"] = raw.get("pairs", {}) or {}
                    self.data["locations"] = raw.get("locations", {}) or {}
        except Exception as e:
            log_error(u"Failed to read tp_blocks.json: {0}".format(e))

    def save(self):
        try:
            if not os.path.exists(TPBlocksConfig.DATA_DIR):
                os.makedirs(TPBlocksConfig.DATA_DIR)
            temp_file = TPBlocksConfig.DATA_FILE + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            if hasattr(os, "replace"):
                os.replace(temp_file, TPBlocksConfig.DATA_FILE)
            else:
                if os.path.exists(TPBlocksConfig.DATA_FILE):
                    try:
                        os.remove(TPBlocksConfig.DATA_FILE)
                    except Exception:
                        pass
                os.rename(temp_file, TPBlocksConfig.DATA_FILE)
        except Exception as e:
            log_error(u"Failed to save tp_blocks.json: {0}".format(e))

    def register_placement(self, pair_id, loc):
        loc_key = location_key(loc)
        if not loc_key:
            return False

        # Если эта локация раньше была привязана к ДРУГОЙ паре (например,
        # блок сломали, а сверху построили что-то другое с этим же скриптом
        # без корректного снятия) — сначала отвязываем её от старой пары.
        old_pair_id = self.data["locations"].get(loc_key)
        if old_pair_id and old_pair_id != pair_id:
            self.data["pairs"].get(old_pair_id, {}).pop(loc_key, None)

        self.data["pairs"].setdefault(pair_id, {})[loc_key] = {
            "world": to_unicode(loc.getWorld().getName()),
            "x": int(loc.getBlockX()),
            "y": int(loc.getBlockY()),
            "z": int(loc.getBlockZ())
        }
        self.data["locations"][loc_key] = pair_id
        self.save()
        return True

    def unregister_by_location(self, loc):
        """Снимает регистрацию блока по местоположению (при поломке).
        Возвращает pair_id снятого блока, либо None."""
        loc_key = location_key(loc)
        if not loc_key:
            return None
        pair_id = self.data["locations"].pop(loc_key, None)
        if not pair_id:
            return None
        pair_entry = self.data["pairs"].get(pair_id)
        if pair_entry:
            pair_entry.pop(loc_key, None)
            if not pair_entry:
                self.data["pairs"].pop(pair_id, None)
        self.save()
        return pair_id

    def get_pair_id_by_location(self, loc):
        loc_key = location_key(loc)
        if not loc_key:
            return None
        return self.data["locations"].get(loc_key)

    def get_other_placed_location(self, pair_id, current_loc_key):
        """
        Возвращает координаты ДРУГОГО установленного блока той же пары
        (не совпадающего с current_loc_key), либо None, если такого нет.
        В норме у пары ровно 2 записи (текущая + партнёр), но на случай
        дублирования (баг/эксплойт вне рамок этого скрипта) просто берём
        первую отличную от текущей — этого достаточно для механики.
        """
        pair_entry = self.data["pairs"].get(pair_id, {})
        for other_key in sorted(pair_entry.keys()):
            if other_key != current_loc_key:
                return pair_entry[other_key]
        return None


storage = TPBlocksStorage()

# Защита от мгновенного телепорта туда-обратно: uuid_str -> location_key
# блока, на который игрок только что телепортировался. Сбрасывается, как
# только игрок физически сходит с этого блока (см. on_player_move).
guard_by_player = {}


# -----------------------------------------------------------------------------
# ХЕЛПЕР: БЛОК, НА КОТОРОМ СТОИТ ИГРОК (ПОД НОГАМИ)
# -----------------------------------------------------------------------------
def get_block_under_feet(player):
    try:
        return player.getLocation().getBlock().getRelative(BlockFace.DOWN)
    except Exception:
        return None


def is_tpblock_material(block):
    if block is None or Material is None:
        return False
    try:
        return block.getType() == Material.valueOf(TPBlocksConfig.BLOCK_MATERIAL_NAME)
    except Exception:
        return False


# -----------------------------------------------------------------------------
# ОБРАБОТЧИКИ СОБЫТИЙ
# -----------------------------------------------------------------------------
def on_block_place(event):
    try:
        item = event.getItemInHand()
        pair_id = get_pair_id_from_item(item)
        if not pair_id:
            return  # обычный блок (или ванильный цветущий аметист) - не наш случай

        block = event.getBlockPlaced()
        storage.register_placement(pair_id, block.getLocation())

        player = event.getPlayer()
        send_message(player, TPBlocksConfig.PREFIX + u"&7\u0422\u0435\u043b\u0435\u043f\u043e\u0440\u0442-\u0431\u043b\u043e\u043a \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d.")
    except Exception as e:
        log_error(u"Error in on_block_place: {0}".format(e))


def on_block_break(event):
    try:
        block = event.getBlock()
        if not is_tpblock_material(block):
            return  # обычный блок этого материала - не трогаем (может быть ванильный аметист)

        pair_id = storage.unregister_by_location(block.getLocation())
        if not pair_id:
            return  # не наш зарегистрированный телепорт-блок (ванильный аметист где-то ещё)

        # ФИКС по ТЗ: сломать можно, но должен выпасть ИМЕННО телепорт-блок
        # с тем же ID пары - не ванильный цветущий аметист. Если у игрока
        # уже есть в инвентаре второй блок этой же пары - они СЛИПНУТСЯ в
        # стак, т.к. у них идентичный ID/ItemMeta.
        event.setDropItems(False)
        short_label = pair_id[:8]
        replacement_item = create_tp_block_item(pair_id, short_label, amount=1)

        player = event.getPlayer()
        loc = block.getLocation()
        if player is not None:
            leftover = player.getInventory().addItem(replacement_item)
            if leftover:
                for extra_item in leftover.values():
                    loc.getWorld().dropItemNaturally(loc, extra_item)
            send_message(player, TPBlocksConfig.PREFIX + u"&7\u0422\u0435\u043b\u0435\u043f\u043e\u0440\u0442-\u0431\u043b\u043e\u043a \u0441\u043b\u043e\u043c\u0430\u043d \u0438 \u0432\u043e\u0437\u0432\u0440\u0430\u0449\u0451\u043d \u0432 \u0438\u043d\u0432\u0435\u043d\u0442\u0430\u0440\u044c.")
        else:
            loc.getWorld().dropItemNaturally(loc, replacement_item)

        # Чистим guard для всех, кто был "привязан" к этой локации - блок
        # больше не существует, нет смысла держать защиту на нём.
        loc_key = location_key(loc)
        for p_uuid in list(guard_by_player.keys()):
            if guard_by_player.get(p_uuid) == loc_key:
                guard_by_player.pop(p_uuid, None)

    except Exception as e:
        log_error(u"Error in on_block_break: {0}".format(e))


def _attempt_teleport(player):
    """Пытается телепортировать игрока с текущего телепорт-блока на второй
    блок той же пары (с тем же общим ID)."""
    block = get_block_under_feet(player)
    if not is_tpblock_material(block):
        return

    current_loc_key = location_key(block.getLocation())
    pair_id = storage.get_pair_id_by_location(block.getLocation())
    if not pair_id:
        return  # обычный блок материала, не зарегистрированный телепорт-блок

    p_uuid = uid(player)

    # ФИКС "мгновенный телепорт туда-обратно": если игрок стоит именно на
    # том блоке, на который только что прибыл (и ещё не сходил с него),
    # повторный Shift не сработает.
    if p_uuid and guard_by_player.get(p_uuid) == current_loc_key:
        send_message(player, TPBlocksConfig.PREFIX + u"&c\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0441\u043e\u0439\u0434\u0438\u0442\u0435 \u0441 \u0431\u043b\u043e\u043a\u0430, \u043f\u0440\u0435\u0436\u0434\u0435 \u0447\u0435\u043c \u0442\u0435\u043b\u0435\u043f\u043e\u0440\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c\u0441\u044f \u0441\u043d\u043e\u0432\u0430.")
        return

    target_entry = storage.get_other_placed_location(pair_id, current_loc_key)
    if not target_entry:
        # Второй блок этой пары ещё ни разу не устанавливался, либо был
        # сломан (paired-break: пара не работает, пока не переустановят
        # второй блок с тем же ID).
        send_message(player, TPBlocksConfig.PREFIX + u"&c\u0412\u0442\u043e\u0440\u043e\u0439 \u0431\u043b\u043e\u043a \u044d\u0442\u043e\u0439 \u043f\u0430\u0440\u044b \u043d\u0435 \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d!")
        return

    if not BUKKIT_AVAILABLE:
        return

    world = Bukkit.getWorld(to_java_string(target_entry.get("world")))
    if world is None:
        send_message(player, TPBlocksConfig.PREFIX + u"&c\u041c\u0438\u0440 \u0432\u0442\u043e\u0440\u043e\u0433\u043e \u0431\u043b\u043e\u043a\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.")
        return

    target_x = float(target_entry.get("x")) + 0.5
    target_y = float(target_entry.get("y")) + 1.0
    target_z = float(target_entry.get("z")) + 0.5
    cur_loc = player.getLocation()
    target_loc = Location(world, target_x, target_y, target_z, cur_loc.getYaw(), cur_loc.getPitch())

    try:
        player.teleport(target_loc)
        try:
            player.setFallDistance(0.0)
        except Exception:
            pass

        target_key = u"{0}:{1}:{2}:{3}".format(
            to_unicode(target_entry.get("world")),
            int(target_entry.get("x")), int(target_entry.get("y")), int(target_entry.get("z"))
        )
        if p_uuid:
            guard_by_player[p_uuid] = target_key

        safe_play_sound(player, ["BLOCK_AMETHYST_BLOCK_CHIME", "ENTITY_ENDERMAN_TELEPORT"], 1.0, 1.0)
        safe_spawn_particle(target_loc, ["ELECTRIC_SPARK", "END_ROD", "PORTAL"], 20)
        send_message(player, TPBlocksConfig.PREFIX + u"&a\u2713 \u0422\u0435\u043b\u0435\u043f\u043e\u0440\u0442\u0438\u0440\u043e\u0432\u0430\u043b\u0438\u0441\u044c \u043d\u0430 \u043f\u0430\u0440\u043d\u044b\u0439 \u0431\u043b\u043e\u043a.")
    except Exception as e:
        log_error(u"Teleport failed: {0}".format(e))
        send_message(player, TPBlocksConfig.PREFIX + u"&c\u041e\u0448\u0438\u0431\u043a\u0430 \u0442\u0435\u043b\u0435\u043f\u043e\u0440\u0442\u0430\u0446\u0438\u0438.")


def on_toggle_sneak(event):
    try:
        if not event.isSneaking():
            return  # реагируем только на момент НАЧАЛА приседания
        player = event.getPlayer()
        _attempt_teleport(player)
    except Exception as e:
        log_error(u"Error in on_toggle_sneak: {0}".format(e))


def on_player_move(event):
    try:
        p_uuid = uid(event.getPlayer())
        if not p_uuid or p_uuid not in guard_by_player:
            return  # нет активной защиты для этого игрока - не тратим ресурсы

        frm = event.getFrom()
        to = event.getTo()
        if to is None:
            return
        # Реагируем только если игрок реально сменил блок под ногами
        # (не просто повернул голову) - экономим CPU на частых move-событиях.
        if (frm.getBlockX() == to.getBlockX() and
                frm.getBlockY() == to.getBlockY() and
                frm.getBlockZ() == to.getBlockZ()):
            return

        block_now = get_block_under_feet(event.getPlayer())
        current_key = location_key(block_now.getLocation()) if block_now else None
        if current_key != guard_by_player.get(p_uuid):
            # Игрок физически сошёл с охраняемого блока - снимаем защиту.
            guard_by_player.pop(p_uuid, None)
    except Exception as e:
        log_error(u"Error in on_player_move: {0}".format(e))


def on_player_quit(event):
    try:
        p_uuid = uid(event.getPlayer())
        if p_uuid:
            guard_by_player.pop(p_uuid, None)
    except Exception as e:
        log_error(u"Error in on_player_quit: {0}".format(e))


# -----------------------------------------------------------------------------
# КОМАНДА /tpblock give <ник> [кол-во_пар]
# -----------------------------------------------------------------------------
def cmd_tpblock(sender, label, args):
    args_list = list(args) if args else []

    if len(args_list) < 2 or to_unicode(args_list[0]).lower() != u"give":
        send_message(sender, TPBlocksConfig.PREFIX + u"&c\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: &f/tpblock give <\u043d\u0438\u043a> [\u043a\u043e\u043b-\u0432\u043e_\u043f\u0430\u0440]")
        return True

    if not is_admin(sender):
        send_message(sender, TPBlocksConfig.PREFIX + u"&c\u0423 \u0432\u0430\u0441 \u043d\u0435\u0442 \u043f\u0440\u0430\u0432 \u043d\u0430 \u044d\u0442\u0443 \u043a\u043e\u043c\u0430\u043d\u0434\u0443.")
        return True

    target_name = to_unicode(args_list[1])
    target_player = Bukkit.getPlayer(to_java_string(target_name)) if BUKKIT_AVAILABLE else None
    if not target_player or not target_player.isOnline():
        send_message(sender, TPBlocksConfig.PREFIX + u"&c\u0418\u0433\u0440\u043e\u043a &f" + target_name + u" &c\u0441\u0435\u0439\u0447\u0430\u0441 \u043e\u0444\u0444\u043b\u0430\u0439\u043d!")
        return True

    pairs_count = 1
    if len(args_list) >= 3:
        try:
            pairs_count = max(1, min(64, int(args_list[2])))
        except ValueError:
            pairs_count = 1

    for _ in range(pairs_count):
        # Каждая пара - ОДИН стак из 2 одинаковых (по ID) предметов.
        pair_stack = create_tp_block_pair_stack()
        leftover = target_player.getInventory().addItem(pair_stack)
        if leftover:
            loc = target_player.getLocation()
            for extra_item in leftover.values():
                loc.getWorld().dropItemNaturally(loc, extra_item)

    send_message(sender, TPBlocksConfig.PREFIX + u"&a\u2713 \u0412\u044b\u0434\u0430\u043d\u043e &f" + str(pairs_count) + u" &a\u043f\u0430\u0440(\u044b) \u0442\u0435\u043b\u0435\u043f\u043e\u0440\u0442-\u0431\u043b\u043e\u043a\u043e\u0432 \u0438\u0433\u0440\u043e\u043a\u0443 &f" + target_player.getName() + u"&a.")
    send_message(target_player, TPBlocksConfig.PREFIX + u"&a\u0412\u044b \u043f\u043e\u043b\u0443\u0447\u0438\u043b\u0438 &f" + str(pairs_count) + u" &a\u043f\u0430\u0440(\u044b) \u0442\u0435\u043b\u0435\u043f\u043e\u0440\u0442-\u0431\u043b\u043e\u043a\u043e\u0432!")
    return True


def tab_tpblock(sender, alias, args):
    args_list = list(args) if args else []
    if len(args_list) <= 1:
        prefix = to_unicode(args_list[0]).lower() if args_list else u""
        return [item for item in ["give"] if item.startswith(prefix)]
    if len(args_list) == 2 and BUKKIT_AVAILABLE:
        prefix = to_unicode(args_list[1]).lower()
        try:
            return [str(p.getName()) for p in Bukkit.getOnlinePlayers() if str(p.getName()).lower().startswith(prefix)]
        except Exception:
            return []
    if len(args_list) == 3:
        return ["1", "2", "5"]
    return []


# -----------------------------------------------------------------------------
# РЕГИСТРАЦИЯ / ЖИЗНЕННЫЙ ЦИКЛ СКРИПТА
# -----------------------------------------------------------------------------
def register_listeners():
    if not PYSPIGOT_AVAILABLE or not BUKKIT_AVAILABLE:
        return
    if BlockPlaceEvent is not None:
        listener_mgr.registerListener(on_block_place, BlockPlaceEvent)
    if BlockBreakEvent is not None:
        listener_mgr.registerListener(on_block_break, BlockBreakEvent)
    if PlayerToggleSneakEvent is not None:
        listener_mgr.registerListener(on_toggle_sneak, PlayerToggleSneakEvent)
    if PlayerMoveEvent is not None:
        listener_mgr.registerListener(on_player_move, PlayerMoveEvent)
    if PlayerQuitEvent is not None:
        listener_mgr.registerListener(on_player_quit, PlayerQuitEvent)


def register_commands():
    if not PYSPIGOT_AVAILABLE:
        return
    cmd_mgr.registerCommand(cmd_tpblock, tab_tpblock, "tpblock", "Manage teleport block pairs", "/tpblock give <player> [pairs]", [])


def on_enable():
    log_info("Starting SmartY-TPBlocks v{0}".format(TPBlocksConfig.VERSION))
    storage.load()
    register_listeners()
    register_commands()
    log_info("Enabled. Tracked tp-block pairs: {0}".format(len(storage.data.get("pairs", {}))))


def on_disable():
    log_info("Disabling SmartY-TPBlocks")
    storage.save()
    guard_by_player.clear()
    # Команды и listeners этого скрипта зарегистрированы ТОЛЬКО через штатные
    # cmd_mgr/listener_mgr PySpigot - их снятие PySpigot делает сам при
    # выгрузке скрипта, здесь дополнительно ничего снимать не нужно.


def start(script=None):
    on_enable()


def stop(script=None):
    # ВАЖНО: PySpigot вызывает автоматически именно stop() (не on_disable())
    # при /pyspigot unload <script>. Без этой функции on_disable() никогда бы
    # не выполнился при ручной выгрузке, и накопленные данные о размещённых
    # телепорт-блоках не сохранились бы перед выгрузкой.
    on_disable()

# -*- coding: utf-8 -*-
"""
xray.py — Статистический монитор добычи и спектаторская панель
Для PySpigot 0.9.1 (Jython 2.7) + Paper 1.21.11

Особенности:
 - Учёт всех типов обычной и глубинной (Deepslate) руды
 - Защита от ложных срабатываний (дедупликация жил, фильтр высоты, защита от Silk Touch)
 - Жёсткий порог чувствительности (>6% алмазов/камня или 2 алмазные жилы за 2 минуты)
 - Спектаторский инструментарий (/xray spec <ник> с авто-сохранением точки и /xray back)
 - Интерактивное GUI-меню (/xray gui) со списком подозреваемых и детальной карточкой
 - Долговременное хранение истории добычи в data/xray_stats.json
"""

import os
import io
import json

import pyspigot as ps
from java.lang import System
from java.util import ArrayList

from org.bukkit import Bukkit, Material, Sound, GameMode, NamespacedKey
from org.bukkit.entity import Player
from org.bukkit.event.block import BlockBreakEvent, BlockPlaceEvent
from org.bukkit.event.inventory import InventoryClickEvent, InventoryCloseEvent
from org.bukkit.event.player import PlayerQuitEvent
from org.bukkit.inventory import ItemStack
from org.bukkit.inventory.meta import SkullMeta
from org.bukkit.persistence import PersistentDataType

# Инициализация менеджеров PySpigot
cmd_mgr = ps.command_manager()
listener_mgr = ps.listener_manager()

# -------------------------------------------------------------------------
# КОНСТАНТЫ И ТИПЫ РУД
# -------------------------------------------------------------------------
KEY_GUI_ACTION = NamespacedKey.fromString("xray:action")
KEY_GUI_PARAM = NamespacedKey.fromString("xray:param")

DATA_DIR = os.path.join("plugins", "PySpigot", "scripts", "data")
DATA_FILE = os.path.join(DATA_DIR, "xray_stats.json")

ADMIN_NAMES = set([u"blueredtronce"])

ORE_TYPES = set([
    Material.ANCIENT_DEBRIS,
    Material.DIAMOND_ORE,
    Material.DEEPSLATE_DIAMOND_ORE,
    Material.EMERALD_ORE,
    Material.DEEPSLATE_EMERALD_ORE,
    Material.GOLD_ORE,
    Material.DEEPSLATE_GOLD_ORE,
    Material.NETHER_GOLD_ORE,
    Material.IRON_ORE,
    Material.DEEPSLATE_IRON_ORE,
    Material.LAPIS_ORE,
    Material.DEEPSLATE_LAPIS_ORE,
    Material.COAL_ORE,
    Material.DEEPSLATE_COAL_ORE,
    Material.COPPER_ORE,
    Material.DEEPSLATE_COPPER_ORE,
    Material.REDSTONE_ORE,
    Material.DEEPSLATE_REDSTONE_ORE,
    Material.NETHER_QUARTZ_ORE,
])

# Пустые породы (для знаменателя статистики)
STONE_TYPES = set([
    Material.STONE,
    Material.DEEPSLATE,
    Material.TUFF,
    Material.GRANITE,
    Material.DIORITE,
    Material.ANDESITE,
    Material.CALCITE,
    Material.SMOOTH_BASALT,
    Material.NETHERRACK,
    Material.BASALT,
    Material.BLACKSTONE
])

# Пороги тревоги (Strict - Жёсткий)
MIN_STONE_SAMPLE = 80           # Минимум пустых блоков перед расчётом процента
ALERT_DIAMOND_RATIO = 6.0       # > 6.0% алмазов к камню = Тревога
ALERT_DEBRIS_RATIO = 4.0        # > 4.0% незерита к камню = Тревога
FAST_VEIN_DIAMOND_SEC = 120     # 2 алмазные жилы за 120 сек (2 минуты)
FAST_VEIN_DEBRIS_SEC = 180      # 2 незеритовые жилы за 180 сек (3 минуты)

# -------------------------------------------------------------------------
# ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# -------------------------------------------------------------------------
state = {
    "players": {}
}

# LRU кеш поставленных игроками блоков (защита от Silk Touch дома): set("world:x,y,z")
placed_ores = set()
placed_ores_queue = []
MAX_PLACED_CACHE = 2000

# Оперативное отслеживание жил в памяти: uuid -> [ (timestamp_sec, ore_group, X, Y, Z) ]
vein_history = {}

# Сохранение позиций спектаторов: uuid_admin -> { "loc": Location, "gamemode": GameMode }
spec_back_cache = {}

# Открытые GUI: uuid_admin -> dict
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
    # автоматически получал полные права администратора X-Ray детектора - мог
    # телепортироваться в spectator-режиме к любому игроку, открывать
    # чужие инвентари, сбрасывать чужие подозрения и открывать GUI-монитор -
    # хотя ему никогда не выдавали именно "smarty.xray.admin".
    return sender.getName().lower() in ADMIN_NAMES or sender.isOp() or sender.hasPermission("smarty.xray.admin")

def format_coords(loc):
    if not loc:
        return u"?"
    return u"%d, %d, %d (%s)" % (loc.getBlockX(), loc.getBlockY(), loc.getBlockZ(), loc.getWorld().getName())

# -------------------------------------------------------------------------
# ЗАГРУЗКА И СОХРАНЕНИЕ ДАННЫХ
# -------------------------------------------------------------------------
def _load():
    global state
    try:
        if not os.path.exists(DATA_FILE):
            state = {"players": {}}
            return
        f = io.open(DATA_FILE, "r", encoding="utf-8")
        try:
            raw = f.read()
        finally:
            f.close()
        if raw.strip():
            state = json.loads(raw)
            if "players" not in state:
                state["players"] = {}
            for pdata in state["players"].values():
                pdata.pop("weighted_score", None)
    except Exception as ex:
        Bukkit.getLogger().warning("[xray_detector] load error: " + str(ex))
        state = {"players": {}}

def _save():
    try:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        text = json.dumps(state, ensure_ascii=False, indent=2)
        if isinstance(text, str):
            text = text.decode("utf-8", "replace")
        f = io.open(DATA_FILE, "w", encoding="utf-8")
        try:
            f.write(text)
        finally:
            f.close()
    except Exception as ex:
        Bukkit.getLogger().warning("[xray_detector] save error: " + str(ex))

def get_player_stats(player):
    u = uid(player)
    pdata = state["players"].get(u)
    if not pdata:
        pdata = {
            "nick": _to_unicode(player.getName()),
            "stone_mined": 0,
            "diamond_blocks": 0,
            "diamond_veins": 0,
            "debris_blocks": 0,
            "debris_veins": 0,
            "suspicious": False,
            "alarms_count": 0,
            "ores_breakdown": {}
        }
        state["players"][u] = pdata
    else:
        pdata["nick"] = _to_unicode(player.getName())
    return pdata

# -------------------------------------------------------------------------
# ГЕНЕРАТОРЫ ИКОНОК GUI
# -------------------------------------------------------------------------
def make_item(mat, name, lore_list=None, action=None, param=None, glow=False):
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

def make_player_head(nick, name, lore_list, action=None, param=None):
    item = ItemStack(Material.PLAYER_HEAD, 1)
    meta = item.getItemMeta()
    meta.setDisplayName(name)
    if lore_list:
        meta.setLore(java_list(lore_list))
    if action:
        meta.getPersistentDataContainer().set(KEY_GUI_ACTION, PersistentDataType.STRING, _to_unicode(action))
    if param:
        meta.getPersistentDataContainer().set(KEY_GUI_PARAM, PersistentDataType.STRING, _to_unicode(param))
    try:
        if isinstance(meta, SkullMeta):
            meta.setOwner(nick)
    except Exception:
        pass
    item.setItemMeta(meta)
    return item

# -------------------------------------------------------------------------
# GUI: СПИСОК ПОДОЗРЕВАЕМЫХ (XrayMonitorGUI — 54 СЛОТА)
# -------------------------------------------------------------------------
def open_monitor_gui(player, page=0):
    if not _is_admin(player):
        player.sendMessage(u"§c✗ §7Доступ к монитору X-Ray только для администрации.")
        return

    inv = Bukkit.createInventory(None, 54, u"§8[XRAY] §0Подозреваемые (Стр. %d)" % (page + 1))

    flagged_players = []
    for u_key, pdata in state["players"].items():
        if pdata.get("suspicious") or pdata.get("alarms_count", 0) > 0 or pdata.get("diamond_blocks", 0) > 20:
            flagged_players.append((u_key, pdata))

    flagged_players.sort(key=lambda x: (-x[1].get("alarms_count", 0), x[1].get("nick", u"").lower()))

    lore_summary = [
        u"§7Подозреваемых игроков в базе: §c" + str(len(flagged_players)),
        u"§8---------------------------",
        u"§7Сортировка по количеству тревог.",
        u"",
        u"§eЛКМ по игроку §7— открыть карточку проверки"
    ]
    inv.setItem(4, make_item(Material.REDSTONE_LAMP, u"§c§lМонитор X-Ray", lore_summary))

    start_idx = page * 36
    end_idx = min(start_idx + 36, len(flagged_players))

    for i in range(start_idx, end_idx):
        slot = 9 + (i - start_idx)
        u_key, pdata = flagged_players[i]
        nick = pdata.get("nick", u"Игрок")
        is_on = (Bukkit.getPlayerExact(nick) is not None)
        status_str = u"§a● Онлайн" if is_on else u"§c○ Оффлайн"

        stone = max(1, pdata.get("stone_mined", 0))
        d_blocks = pdata.get("diamond_blocks", 0)
        d_ratio = (d_blocks / float(stone)) * 100.0
        deb_blocks = pdata.get("debris_blocks", 0)
        deb_ratio = (deb_blocks / float(stone)) * 100.0
        alarms = pdata.get("alarms_count", 0)

        lore_head = [
            u"§7Статус: " + status_str,
            u"§7Срабатываний тревоги: §c§l%d" % alarms,
            u"§8---------------------------",
            u"§7Выкопано пустой породы: §f%d" % stone,
            u"§7Алмазная руда: §b%d §7(§b%.1f%%§7)" % (d_blocks, d_ratio),
            u"§7Древние обломки: §6%d §7(§6%.1f%%§7)" % (deb_blocks, deb_ratio),
            u"§8---------------------------",
            u"§eЛКМ §7— Открыть управление и спектатор"
        ]
        inv.setItem(slot, make_player_head(nick, u"§c§l" + nick if pdata.get("suspicious") else u"§e§l" + nick, lore_head, "open_player_submenu", nick))

    if start_idx > 0:
        inv.setItem(45, make_item(Material.ARROW, u"§a§l<- Предыдущая страница", [u"§7На страницу назад"], "page", str(page - 1)))
    if end_idx < len(flagged_players):
        inv.setItem(53, make_item(Material.ARROW, u"§a§lСледующая страница ->", [u"§7На страницу вперед"], "page", str(page + 1)))

    inv.setItem(49, make_item(Material.BARRIER, u"§c§lЗакрыть меню", [u"§7Закрыть окно монитора"], "close_gui"))

    player.openInventory(inv)
    open_guis[uid(player)] = {"view": "monitor", "page": page}

# -------------------------------------------------------------------------
# GUI: ПОДМЕНЮ ПОДОЗРЕВАЕМОГО ИГРОКА (27 СЛОТОВ)
# -------------------------------------------------------------------------
def open_player_submenu(admin, target_nick):
    if not _is_admin(admin):
        return

    target_player = Bukkit.getPlayerExact(target_nick)
    is_on = (target_player is not None)
    status_str = u"§a● Онлайн" if is_on else u"§c○ Оффлайн"

    pdata = None
    for u_key, d in state["players"].items():
        if d.get("nick", u"").lower() == target_nick.lower():
            pdata = d
            break

    if not pdata:
        admin.sendMessage(u"§c✗ §7Данные игрока §f" + target_nick + u" §7не найдены в базе X-Ray.")
        open_monitor_gui(admin, 0)
        return

    inv = Bukkit.createInventory(None, 27, u"§8[XRAY] §0Проверка: " + target_nick)

    stone = max(1, pdata.get("stone_mined", 0))
    d_blocks = pdata.get("diamond_blocks", 0)
    d_veins = pdata.get("diamond_veins", 0)
    d_ratio = (d_blocks / float(stone)) * 100.0
    deb_blocks = pdata.get("debris_blocks", 0)
    deb_veins = pdata.get("debris_veins", 0)
    deb_ratio = (deb_blocks / float(stone)) * 100.0
    alarms = pdata.get("alarms_count", 0)

    breakdown = pdata.get("ores_breakdown", {})
    breakdown_lines = []
    for mat_name, cnt in sorted(breakdown.items(), key=lambda x: -x[1])[:6]:
        breakdown_lines.append(u"  §7• %s: §f%d" % (mat_name, cnt))
    if not breakdown_lines:
        breakdown_lines.append(u"  §7• Нет записей по другим рудам")

    lore_card = [
        u"§7Статус: " + status_str,
        u"§7Тревог сработало: §c§l%d" % alarms,
        u"§8---------------------------",
        u"§7Камень / Сланец: §f%d" % stone,
        u"§7Алмазы: §b%d шт. §7(%d жил, §b%.1f%%§7)" % (d_blocks, d_veins, d_ratio),
        u"§7Древние обломки: §6%d шт. §7(%d жил, §6%.1f%%§7)" % (deb_blocks, deb_veins, deb_ratio),
        u"§8---------------------------",
        u"§7Детализация добычи:"
    ] + breakdown_lines

    inv.setItem(4, make_player_head(target_nick, u"§c§lПрофиль: §f§l" + target_nick, lore_card))

    lore_spec = [
        u"§7Телепорт в GameMode.SPECTATOR",
        u"§7к выбранному игроку.",
        u"",
        u"§eЛКМ §7— ТП Наблюдателем к " + target_nick,
        u"§a(Для возврата назад введите /xray back)"
    ]
    inv.setItem(10, make_item(Material.ENDER_EYE, u"§a§lТП Наблюдателем", lore_spec, "spec_player", target_nick))

    lore_inv = [
        u"§7Просмотр инвентаря подозреваемого,",
        u"§7чтобы увидеть сколько стаков руды при нём.",
        u"",
        u"§eЛКМ §7— Открыть инвентарь " + target_nick
    ]
    inv.setItem(12, make_item(Material.CHEST, u"§e§lПроверить Инвентарь", lore_inv, "inv_player", target_nick))

    lore_reset = [
        u"§7Обнулить счётчики подозрения и тревоги,",
        u"§7если игрок копает честно.",
        u"",
        u"§eЛКМ §7— Сбросить статистику " + target_nick
    ]
    inv.setItem(14, make_item(Material.MILK_BUCKET, u"§c§lСбросить подозрение", lore_reset, "reset_player", target_nick))

    lore_jail = [
        u"§7Если вы записали видео и убедились в X-Ray:",
        u"§7отправить игрока в Городскую Тюрьму / Шахту.",
        u"",
        u"§eЛКМ §7— Телепортировать на спавн тюрьмы"
    ]
    inv.setItem(16, make_item(Material.IRON_BARS, u"§4§lАрестовать / В Тюрьму", lore_jail, "jail_player", target_nick))

    inv.setItem(22, make_item(Material.DARK_OAK_DOOR, u"§c§lНазад к списку", [u"§7Вернуться к общему монитору"], "open_monitor"))

    admin.openInventory(inv)
    open_guis[uid(admin)] = {"view": "player_submenu", "target_nick": target_nick}

# -------------------------------------------------------------------------
# ОБРАБОТЧИКИ КЛИКОВ В GUI
# -------------------------------------------------------------------------
def on_inventory_click(event):
    who = event.getWhoClicked()
    if not isinstance(who, Player):
        return
    u = uid(who)
    if u not in open_guis:
        return
    title = event.getView().getTitle()
    if u"§8[XRAY]" not in title:
        return

    event.setCancelled(True)
    clicked = event.getCurrentItem()
    if clicked is None or clicked.getType() == Material.AIR:
        return
    meta = clicked.getItemMeta()
    if meta is None:
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
    elif action == u"open_monitor":
        open_monitor_gui(who, 0)
        return
    elif action == u"page":
        open_monitor_gui(who, int(param))
        return
    elif action == u"open_player_submenu":
        open_player_submenu(who, param)
        return
    elif action == u"spec_player":
        who.closeInventory()
        execute_spec(who, param)
        return
    elif action == u"inv_player":
        target_player = Bukkit.getPlayerExact(param)
        if not target_player or not target_player.isOnline():
            who.sendMessage(u"§c✗ §7Игрок §f" + param + u" §7сейчас оффлайн!")
            return
        who.openInventory(target_player.getInventory())
        return
    elif action == u"reset_player":
        execute_reset(who, param)
        open_player_submenu(who, param)
        return
    elif action == u"jail_player":
        target_player = Bukkit.getPlayerExact(param)
        if not target_player or not target_player.isOnline():
            who.sendMessage(u"§c✗ §7Игрок §f" + param + u" §7сейчас оффлайн!")
            return
        target_player.teleport(target_player.getWorld().getSpawnLocation())
        who.sendMessage(u"§a✓ §7Игрок §f" + param + u" §7отправлен на спавн/тюрьму.")
        target_player.sendMessage(u"§4§l[Суд] §cВаша добыча руд признана нечестной! Вы арестованы.")
        who.closeInventory()
        return

def on_inventory_close(event):
    who = event.getPlayer()
    if isinstance(who, Player):
        open_guis.pop(uid(who), None)

# -------------------------------------------------------------------------
# ЗАЩИТА ОТ SILK TOUCH: ОТСЛЕЖИВАНИЕ ПОСТАВЛЕННЫХ БЛОКОВ
# -------------------------------------------------------------------------
def on_block_place(event):
    block = event.getBlock()
    mat = block.getType()
    if mat in ORE_TYPES:
        key = "%s:%d,%d,%d" % (block.getWorld().getName(), block.getX(), block.getY(), block.getZ())
        placed_ores.add(key)
        placed_ores_queue.append(key)
        if len(placed_ores_queue) > MAX_PLACED_CACHE:
            old = placed_ores_queue.pop(0)
            placed_ores.discard(old)

# -------------------------------------------------------------------------
# ОСНОВНОЙ ОБРАБОТЧИК ДОБЫЧИ БЛОКОВ (BLOCK BREAK EVENT)
# -------------------------------------------------------------------------
def on_block_break(event):
    player = event.getPlayer()
    block = event.getBlock()
    mat = block.getType()

    if player.getGameMode() == GameMode.CREATIVE:
        return

    b_key = "%s:%d,%d,%d" % (block.getWorld().getName(), block.getX(), block.getY(), block.getZ())
    if b_key in placed_ores:
        placed_ores.discard(b_key)
        return

    y = block.getY()
    is_nether = (block.getWorld().getEnvironment().name() == "NETHER")

    if not is_nether:
        if y > 64 and mat in ORE_TYPES:
            return
        if y > 20 and mat in (Material.DIAMOND_ORE, Material.DEEPSLATE_DIAMOND_ORE):
            return

    pdata = get_player_stats(player)
    u_key = uid(player)

    if mat in STONE_TYPES:
        pdata["stone_mined"] = pdata.get("stone_mined", 0) + 1
        return

    if mat in ORE_TYPES:
        mat_name = str(mat.name())
        breakdown = pdata.setdefault("ores_breakdown", {})
        breakdown[mat_name] = breakdown.get(mat_name, 0) + 1

        now = now_sec()
        bx, by, bz = block.getX(), block.getY(), block.getZ()

        is_diamond = mat in (Material.DIAMOND_ORE, Material.DEEPSLATE_DIAMOND_ORE)
        is_debris = (mat == Material.ANCIENT_DEBRIS)
        group_name = "DIAMOND" if is_diamond else ("DEBRIS" if is_debris else "OTHER")

        hist = vein_history.setdefault(u_key, [])
        is_new_vein = True
        for (t_prev, g_prev, x_prev, y_prev, z_prev) in reversed(hist):
            if g_prev == group_name and (now - t_prev) <= 15:
                dist_sq = (bx - x_prev)**2 + (by - y_prev)**2 + (bz - z_prev)**2
                if dist_sq <= 16:
                    is_new_vein = False
                    break

        hist.append((now, group_name, bx, by, bz))
        if len(hist) > 50:
            vein_history[u_key] = hist[-50:]

        if is_diamond:
            pdata["diamond_blocks"] = pdata.get("diamond_blocks", 0) + 1
            if is_new_vein:
                pdata["diamond_veins"] = pdata.get("diamond_veins", 0) + 1
        elif is_debris:
            pdata["debris_blocks"] = pdata.get("debris_blocks", 0) + 1
            if is_new_vein:
                pdata["debris_veins"] = pdata.get("debris_veins", 0) + 1

        stone = pdata.get("stone_mined", 0)
        if stone >= MIN_STONE_SAMPLE:
            d_ratio = (pdata.get("diamond_blocks", 0) / float(stone)) * 100.0
            deb_ratio = (pdata.get("debris_blocks", 0) / float(stone)) * 100.0
            fast_diamond_veins = 0
            fast_debris_veins = 0
            for (t_v, g_v, _, _, _) in hist:
                if g_v == "DIAMOND" and (now - t_v) <= FAST_VEIN_DIAMOND_SEC:
                    fast_diamond_veins += 1
                elif g_v == "DEBRIS" and (now - t_v) <= FAST_VEIN_DEBRIS_SEC:
                    fast_debris_veins += 1

            triggered = False

            if d_ratio >= ALERT_DIAMOND_RATIO and is_diamond:
                triggered = True
            elif deb_ratio >= ALERT_DEBRIS_RATIO and is_debris:
                triggered = True
            elif fast_diamond_veins >= 2 and is_diamond and is_new_vein:
                triggered = True
            elif fast_debris_veins >= 2 and is_debris and is_new_vein:
                triggered = True

            if triggered:
                pdata["suspicious"] = True
                pdata["alarms_count"] = pdata.get("alarms_count", 0) + 1
                _save()

# -------------------------------------------------------------------------
# КОМАНДЫ МОДЕРАЦИИ И РЕЖИМ НАБЛЮДАТЕЛЯ (/xray spec, /xray back)
# -------------------------------------------------------------------------
def execute_spec(sender, target_nick):
    if not _is_admin(sender):
        sender.sendMessage(u"§c✗ §7Команда доступна только администрации.")
        return

    target_player = Bukkit.getPlayerExact(target_nick)
    if not target_player or not target_player.isOnline():
        sender.sendMessage(u"§c✗ §7Игрок §f" + target_nick + u" §7сейчас оффлайн!")
        return

    u_admin = uid(sender)
    if u_admin not in spec_back_cache:
        spec_back_cache[u_admin] = {
            "loc": sender.getLocation().clone(),
            "gamemode": sender.getGameMode()
        }

    sender.setGameMode(GameMode.SPECTATOR)
    sender.teleport(target_player.getLocation())
    sender.sendMessage(u"§a✓ §7Вы перешли в §aGameMode.SPECTATOR §7к §f" + target_nick + u"§7.")
    sender.sendMessage(u"§7Для возврата на исходную точку введите §e/xray back§7.")

def execute_back(sender):
    if not _is_admin(sender):
        return
    u_admin = uid(sender)
    cache = spec_back_cache.get(u_admin)
    if not cache:
        sender.sendMessage(u"§c✗ §7Сохранённая точка возврата не найдена!")
        return

    # Возвращаем на исходную точку и восстанавливаем игровой режим.
    sender.teleport(cache["loc"])
    sender.setGameMode(cache["gamemode"])
    spec_back_cache.pop(u_admin, None)
    sender.sendMessage(u"§a✓ §7Вы вернулись на исходную точку и в прежний игровой режим.")

def execute_reset(sender, target_nick):
    if not _is_admin(sender):
        return
    found = False
    for u_key, d in state["players"].items():
        if d.get("nick", u"").lower() == target_nick.lower():
            d["suspicious"] = False
            d["alarms_count"] = 0
            d["stone_mined"] = 0
            d["diamond_blocks"] = 0
            d["diamond_veins"] = 0
            d["debris_blocks"] = 0
            d["debris_veins"] = 0
            d.pop("weighted_score", None)
            d["ores_breakdown"] = {}
            vein_history.pop(u_key, None)
            found = True
            break
    if found:
        _save()
        sender.sendMessage(u"§a✓ §7Статистика и подозрения для §f" + target_nick + u" §aсброшены.")
    else:
        sender.sendMessage(u"§c✗ §7Игрок §f" + target_nick + u" §7не найден в базе.")

def execute_stats(sender, target_nick):
    if not _is_admin(sender):
        return
    for u_key, pdata in state["players"].items():
        if pdata.get("nick", u"").lower() == target_nick.lower():
            stone = max(1, pdata.get("stone_mined", 0))
            d_ratio = (pdata.get("diamond_blocks", 0) / float(stone)) * 100.0
            deb_ratio = (pdata.get("debris_blocks", 0) / float(stone)) * 100.0
            sender.sendMessage(u"§8[XRAY] §7Статистика §f" + target_nick + u"§7:")
            sender.sendMessage(u"  §7Камень: §f%d §8| §7Алмазы: §b%.1f%% §8| §7Незерит: §6%.1f%%" % (stone, d_ratio, deb_ratio))
            sender.sendMessage(u"  §7Срабатываний: §c%d" % pdata.get("alarms_count", 0))
            return
    sender.sendMessage(u"§c✗ §7Игрок §f" + target_nick + u" §7не найден в базе.")

def on_xray_command(sender, label, args):
    args_list = [_norm(x) for x in args]
    sub = args_list[0] if len(args_list) > 0 else u"gui"

    if sub in (u"gui", u"menu"):
        if isinstance(sender, Player):
            open_monitor_gui(sender, 0)
        else:
            sender.sendMessage(u"Команда GUI только для игроков!")
        return True

    if sub == u"spec" and len(args_list) >= 2:
        if isinstance(sender, Player):
            execute_spec(sender, _to_unicode(args[1]))
        return True

    if sub == u"back":
        if isinstance(sender, Player):
            execute_back(sender)
        return True

    if sub == u"inv" and len(args_list) >= 2:
        if isinstance(sender, Player):
            target_player = Bukkit.getPlayerExact(_to_unicode(args[1]))
            if target_player:
                sender.openInventory(target_player.getInventory())
            else:
                sender.sendMessage(u"§c✗ Игрок оффлайн!")
        return True

    if sub == u"reset" and len(args_list) >= 2:
        execute_reset(sender, _to_unicode(args[1]))
        return True

    if sub == u"stats" and len(args_list) >= 2:
        execute_stats(sender, _to_unicode(args[1]))
        return True

    sender.sendMessage(u"§8[XRAY] §7Команды модератора:")
    sender.sendMessage(u"  §e/xray gui §7— открыть монитор подозреваемых")
    sender.sendMessage(u"  §e/xray spec <ник> §7— телепорт к игроку в режиме наблюдателя")
    sender.sendMessage(u"  §e/xray back §7— возврат на свою точку из спека")
    sender.sendMessage(u"  §e/xray inv <ник> §7— проверить инвентарь игрока")
    sender.sendMessage(u"  §e/xray reset <ник> §7— обнулить подозрения")
    sender.sendMessage(u"  §e/xray stats <ник> §7— вывести статистику в чат")
    return True

# -------------------------------------------------------------------------
# ОБРАБОТЧИК ВЫХОДА АДМИНА ИЗ ИГРЫ (ЧИСТКА КЕША СПЕКТАТОРА)
# -------------------------------------------------------------------------
def on_player_quit(event):
    player = event.getPlayer()
    u = uid(player)
    if u in spec_back_cache:
        spec_back_cache.pop(u, None)

# -------------------------------------------------------------------------
# РЕГИСТРАЦИЯ СЛУШАТЕЛЕЙ И КОМАНД
# -------------------------------------------------------------------------
def on_enable():
    _load()
    listener_mgr.registerListener(on_block_break, BlockBreakEvent)
    listener_mgr.registerListener(on_block_place, BlockPlaceEvent)
    listener_mgr.registerListener(on_inventory_click, InventoryClickEvent)
    listener_mgr.registerListener(on_inventory_close, InventoryCloseEvent)
    listener_mgr.registerListener(on_player_quit, PlayerQuitEvent)

    try:
        cmd_mgr.registerCommand(on_xray_command, "xray")
    except TypeError:
        try:
            cmd_mgr.registerCommand(on_xray_command)
        except Exception as ex:
            Bukkit.getLogger().warning("[xray_detector] registerCommand fallback: " + str(ex))

    Bukkit.getLogger().info("[xray_detector] X-Ray monitor and spectator toolkit loaded.")

def on_disable():
    _save()
    Bukkit.getLogger().info("[xray_detector] Disabled.")


def stop(script=None):
    # ВАЖНО: PySpigot вызывает автоматически именно stop() (не on_disable()) при
    # /pyspigot unload <script>. Без этой функции on_disable() никогда не выполнялся
    # бы при ручной выгрузке скрипта, и накопленная статистика X-Ray не сохранялась
    # бы перед выгрузкой. Команды и listeners этого скрипта регистрируются через
    # штатные cmd_mgr/listener_mgr PySpigot, поэтому их снятие PySpigot делает сам -
    # здесь достаточно досохранить данные.
    on_disable()

on_enable()

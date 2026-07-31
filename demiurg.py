# -*- coding: utf-8 -*-
"""
==============================================================================
  ДЕМИУРГ / blueredtronce
  Character script for vanilla PvP/RP server
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  Command dispatcher:
    /test demiurg          — give Staff of Creation (via test_dispatcher.py)
  Own commands:
    /demiurg добавить <текст>   — add message to Voice of Creation
    /demiurg устсуд <роль>       — remember court coords
        роли: судья | подсудимый | зритель | очистить | показать
    /demiurg отмена              — cancel ultimate law selection / voice mode
    /demiurg суд стоп            — end court session, return everyone
------------------------------------------------------------------------------
  Only Демиург (blueredtronce) can use the Staff.
==============================================================================
"""

import os
import json
import codecs

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, Math as JMath
from java.util import UUID as JUUID, ArrayList, HashMap, HashSet

from org.bukkit import (
    Bukkit, Material, Particle, Sound, Location,
    NamespacedKey, Registry, GameMode
)
from org.bukkit.entity import (
    Player, LivingEntity, Projectile
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerItemHeldEvent, PlayerDropItemEvent,
    PlayerRespawnEvent, PlayerMoveEvent, PlayerInteractEntityEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, PlayerDeathEvent
)
from org.bukkit.event.inventory import InventoryClickEvent, InventoryAction
from org.bukkit.event.block import Action, BlockBreakEvent
from org.bukkit.enchantments import Enchantment
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.potion import PotionEffect
from org.bukkit.persistence import PersistentDataType
from org.bukkit.util import Vector
from org.bukkit.boss import BarColor, BarStyle

# =============================================================================
#  CONSTANTS
# =============================================================================

DEMIURG_NAMES = set([u"blueredtronce"])

KEY_STAFF   = NamespacedKey.fromString("demiurg:staff")
KEY_OWNER   = NamespacedKey.fromString("demiurg:owner")

DATA_DIR    = os.path.join("plugins", "PySpigot", "scripts", "data")
DATA_FILE   = os.path.join(DATA_DIR, "demiurg.json")

# Способности (обычный режим скролла)
ABILITIES = [u"Глас Мироздания", u"Остановка Времени", u"Карающая Десница", u"Суд Мироздания", u"Ультимейт"]
ABILITY_COLORS = [u"§b", u"§5", u"§e", u"§6", u"§4"]
ABILITY_MAX = len(ABILITIES) - 1

# Ультимейт-законы
LAWS = [u"Закон Тишины", u"Закон Слабости", u"Закон Света", u"Закон Гравитации", u"Закон Справедливости"]
LAW_COLORS = [u"§8", u"§7", u"§e", u"§b", u"§d"]
LAW_MAX = len(LAWS) - 1

# JVM-глобальный set UUID-ов игроков, у которых способности "заглушены".
# Другие скрипты (spider/doom) могут это читать и блокировать свои способности.
_props = System.getProperties()
SILENCED_KEY = "demiurg.silenced_uuids"
if _props.get(SILENCED_KEY) is None:
    _props.put(SILENCED_KEY, HashSet())
silenced_uuids = _props.get(SILENCED_KEY)


# =============================================================================
#  EFFECT / ENCHANT LOOKUP
# =============================================================================

def _effect(key): return Registry.EFFECT.get(NamespacedKey.minecraft(key))
def _enchant(key): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(key))

E_SLOWNESS     = _effect("slowness")
E_JUMP         = _effect("jump_boost")
E_MINING_FTG   = _effect("mining_fatigue")
E_GLOWING      = _effect("glowing")
E_SLOW_FALLING = _effect("slow_falling")
E_WEAKNESS     = _effect("weakness")

ENC_EFFICIENCY = _enchant("efficiency")
ENC_UNBREAKING = _enchant("unbreaking")
ENC_MENDING    = _enchant("mending")


# =============================================================================
#  PERSISTENT DATA
# =============================================================================

_data = {
    "messages": [],
    "court": {"judge": None, "defendant": None, "viewers": []},
}

def _ensure_data_dir():
    try:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
    except Exception as ex:
        Bukkit.getLogger().warning("[demiurg] cannot create data dir: " + str(ex))

def load_data():
    global _data
    _ensure_data_dir()
    if not os.path.exists(DATA_FILE):
        save_data()
        return
    try:
        f = codecs.open(DATA_FILE, "r", "utf-8")
        raw = f.read()
        f.close()
        loaded = json.loads(raw)
        # Мержим, чтобы старые поля не потерялись.
        if "messages" in loaded and isinstance(loaded["messages"], list):
            _data["messages"] = [unicode(x) for x in loaded["messages"]]
        if "court" in loaded and isinstance(loaded["court"], dict):
            c = loaded["court"]
            _data["court"]["judge"]      = c.get("judge")
            _data["court"]["defendant"]  = c.get("defendant")
            v = c.get("viewers")
            _data["court"]["viewers"] = v if isinstance(v, list) else []
    except Exception as ex:
        Bukkit.getLogger().warning("[demiurg] data load failed: " + str(ex))

def save_data():
    _ensure_data_dir()
    try:
        f = codecs.open(DATA_FILE, "w", "utf-8")
        f.write(json.dumps(_data, ensure_ascii=False, indent=2))
        f.close()
    except Exception as ex:
        Bukkit.getLogger().warning("[demiurg] data save failed: " + str(ex))


def _loc_to_dict(loc):
    return {
        "world": loc.getWorld().getName(),
        "x": loc.getX(), "y": loc.getY(), "z": loc.getZ(),
        "yaw": loc.getYaw(), "pitch": loc.getPitch(),
    }

def _loc_from_dict(d):
    if d is None:
        return None
    w = Bukkit.getWorld(d["world"])
    if w is None:
        return None
    return Location(w, d["x"], d["y"], d["z"], d["yaw"], d["pitch"])


# =============================================================================
#  STATE
# =============================================================================

# Режим посоха: 0..4 (ABILITIES)
staff_ability_idx = {}
# Sub-mode: None | "voice" | "law"
staff_submode     = {}
voice_msg_idx     = {}   # uid -> int, индекс сообщения в предпросмотре
law_idx           = {}   # uid -> int, индекс закона в предпросмотре

# Bossbar активного выбора (voice/law) — по uid
active_bossbar    = {}   # uid -> BossBar

# Времязамораживающие зоны:
#   frozen_zone_by_owner: uid_of_demiurg -> {"center_supplier": lambda, "radius": 20, "kind": "time"|"justice", "allow_touch": bool}
frozen_zones      = {}

# Замороженные игроки (в любой зоне): uid -> Location (куда возвращать)
frozen_positions  = {}

# Активные Suit / court state:
# Сохраняем «откуда пришёл каждый игрок», чтобы вернуть после суда.
court_original    = {}   # uid -> Location
court_active      = False

# Закон-эффекты области: uid_of_demiurg -> {"kind":..., "end_tick":..., "center_supplier":...}
active_laws       = {}

# Точки возврата после “Суда” без верхнего Закона Справедливости.

def uid(entity):
    return entity.getUniqueId().toString()

def now_tick():
    return long(System.currentTimeMillis() / 50)


# =============================================================================
#  UTILS
# =============================================================================

def is_demiurg(player):
    return player.getName().lower() in DEMIURG_NAMES

def java_list(py_iterable):
    lst = ArrayList()
    for it in py_iterable:
        lst.add(it)
    return lst

def is_staff(item):
    if item is None or item.getType() == Material.AIR:
        return False
    meta = item.getItemMeta()
    if meta is None:
        return False
    return meta.getPersistentDataContainer().has(KEY_STAFF, PersistentDataType.BYTE)

def get_staff_owner(item):
    meta = item.getItemMeta()
    if meta is None:
        return None
    pdc = meta.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING):
        return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def player_holds_staff(player):
    inv = player.getInventory()
    it = inv.getItemInMainHand()
    return is_staff(it)

def player_has_staff_anywhere(player):
    for it in player.getInventory().getContents():
        if is_staff(it):
            return True
    return False

def can_use_staff(player, item):
    """True если игрок — Демиург И является владельцем этого посоха."""
    if not is_demiurg(player):
        return False
    if not is_staff(item):
        return False
    owner = get_staff_owner(item)
    if owner is None:
        return True   # старый посох без владельца
    return owner == uid(player)


# =============================================================================
#  STAFF ITEM
# =============================================================================

def create_staff(owner_uuid=None):
    it = ItemStack(Material.NETHERITE_HOE, 1)
    meta = it.getItemMeta()
    meta.setDisplayName(u"§4§lПосох Мироздания")
    lore = [
        u"§7Артефакт, через который",
        u"§7Демиург управляет законами",
        u"§7мироздания.",
        u"",
        u"§8Shift + Колесо мыши — способность",
        u"§8ПКМ — активация",
    ]
    meta.setLore(java_list(lore))
    meta.setUnbreakable(True)

    pdc = meta.getPersistentDataContainer()
    pdc.set(KEY_STAFF, PersistentDataType.BYTE, JByte(1))
    if owner_uuid is not None:
        pdc.set(KEY_OWNER, PersistentDataType.STRING, owner_uuid)

    if ENC_EFFICIENCY: meta.addEnchant(ENC_EFFICIENCY, 5, True)
    # Прочность/Починка убраны — предмет и так неразрушим (setUnbreakable).

    it.setItemMeta(meta)
    return it


def give_staff(player):
    inv = player.getInventory()
    # Ищем свободный слот в хотбаре.
    placed = False
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_staff(uid(player)))
            placed = True
            break
    if not placed:
        inv.setItem(0, create_staff(uid(player)))
    staff_ability_idx[uid(player)] = 0
    staff_submode[uid(player)] = None
    player.sendMessage(u"§4§l✦ §cПосох Мироздания вручён Демиургу.")
    player.sendMessage(u"§7Способность: " + ability_label(0))


def kit_entry(player, args_list):
    if not is_demiurg(player):
        player.sendMessage(u"§cТолько Демиург достоин Посоха.")
        return
    give_staff(player)


# =============================================================================
#  ABILITY / MODE LABELS
# =============================================================================

def ability_label(idx):
    return ABILITY_COLORS[idx] + ABILITIES[idx]

def law_label(idx):
    return LAW_COLORS[idx] + LAWS[idx]

def get_ability(player):
    return staff_ability_idx.get(uid(player), 0)

def set_ability(player, idx):
    idx = idx % (ABILITY_MAX + 1)
    staff_ability_idx[uid(player)] = idx
    player.sendMessage(u"§8⌬ §fСпособность: " + ability_label(idx))
    player.playSound(player.getLocation(), Sound.UI_BUTTON_CLICK, 0.6, 1.7)


# =============================================================================
#  BOSSBAR HELPERS (для подрежимов voice/law)
# =============================================================================

def open_bossbar(player, title, color=BarColor.PURPLE):
    close_bossbar(player)
    bar = Bukkit.createBossBar(title, color, BarStyle.SOLID)
    bar.addPlayer(player)
    bar.setProgress(1.0)
    active_bossbar[uid(player)] = bar

def update_bossbar(player, title):
    bar = active_bossbar.get(uid(player))
    if bar is None:
        return
    bar.setTitle(title)

def close_bossbar(player):
    bar = active_bossbar.pop(uid(player), None)
    if bar is None:
        return
    try:
        bar.removeAll()
    except Exception:
        pass


# =============================================================================
#  ABILITY 1 — ГЛАС МИРОЗДАНИЯ
# =============================================================================

def enter_voice_mode(player):
    if not _data["messages"]:
        player.sendMessage(u"§cБиблиотека Гласа пуста. §7Добавь: §f/demiurg добавить <текст>")
        return
    u = uid(player)
    staff_submode[u] = "voice"
    voice_msg_idx[u] = 0
    _render_voice(player)
    player.sendMessage(u"§7Колесо мыши — листать, §fПКМ§7 — огласить, §f/demiurg отмена§7 — выйти.")

def _render_voice(player):
    u = uid(player)
    idx = voice_msg_idx.get(u, 0)
    total = len(_data["messages"])
    if total == 0:
        exit_submode(player)
        return
    idx = idx % total
    voice_msg_idx[u] = idx
    text = _data["messages"][idx]
    if len(text) > 60:
        preview = text[:57] + u"..."
    else:
        preview = text
    title = u"§d§lГлас §7[" + str(idx+1) + u"/" + str(total) + u"] §f" + preview
    if uid(player) in active_bossbar:
        update_bossbar(player, title)
    else:
        open_bossbar(player, title, BarColor.PURPLE)

def confirm_voice(player):
    u = uid(player)
    idx = voice_msg_idx.get(u, 0)
    if idx >= len(_data["messages"]):
        return
    text = _data["messages"][idx]
    exit_submode(player)
    broadcast_voice(text)

def broadcast_voice(text):
    for p in Bukkit.getOnlinePlayers():
        p.sendTitle(u"§d§l" + text, u"§7— Глас Мироздания —", 10, 60, 20)
        # Раскат грома + свечение
        p.getWorld().playSound(p.getLocation(), Sound.ENTITY_LIGHTNING_BOLT_THUNDER, 1.0, 0.8)
        p.addPotionEffect(PotionEffect(E_GLOWING, 3 * 20, 0, False, False, True))


# =============================================================================
#  ABILITY 2 — ОСТАНОВКА ВРЕМЕНИ
# =============================================================================

TIME_STOP_RADIUS = 20.0

def toggle_time_stop(player):
    u = uid(player)
    if u in frozen_zones:
        stop_time_stop(player)
        return
    start_time_stop(player)

def start_time_stop(player):
    u = uid(player)
    # Центр движется вместе с Демиургом.
    frozen_zones[u] = {
        "kind": "time",
        "owner_uid": u,
        "player_ref": player,
        "radius": TIME_STOP_RADIUS,
        "start_tick": now_tick(),
    }
    player.getWorld().playSound(player.getLocation(), Sound.ITEM_TRIDENT_RIPTIDE_3, 1.0, 0.4)
    player.sendMessage(u"§5§l✦ Время остановлено. §7ПКМ Посохом ещё раз — снять.")

def stop_time_stop(player):
    u = uid(player)
    if u not in frozen_zones:
        return
    del frozen_zones[u]
    player.sendMessage(u"§7Течение времени восстановлено.")
    player.getWorld().playSound(player.getLocation(), Sound.BLOCK_BEACON_DEACTIVATE, 0.7, 0.9)


# =============================================================================
#  ABILITY 3 — КАРАЮЩАЯ ДЕСНИЦА
# =============================================================================

STRIKE_RANGE  = 30.0
STRIKE_RADIUS = 4.0

def cast_smite(player):
    # rayTraceBlocks 30 блоков.
    result = player.rayTraceBlocks(STRIKE_RANGE)
    world = player.getWorld()
    if result is not None and result.getHitBlock() is not None:
        target_loc = result.getHitPosition().toLocation(world)
    else:
        # В воздух — в конечную точку взгляда.
        eye = player.getEyeLocation()
        target_loc = eye.clone().add(eye.getDirection().multiply(STRIKE_RANGE))

    # Прицел — метка + звук зарядки.
    world.spawnParticle(Particle.END_ROD, target_loc, 20, 0.3, 0.3, 0.3, 0.05)
    world.spawnParticle(Particle.ELECTRIC_SPARK, target_loc, 30, 1.0, 1.0, 1.0, 0.1)
    world.playSound(target_loc, Sound.BLOCK_BEACON_ACTIVATE, 0.8, 1.5)
    player.sendMessage(u"§e⚡ Карающая Десница нацелена.")

    def strike():
        world.strikeLightningEffect(target_loc)
        world.playSound(target_loc, Sound.ENTITY_LIGHTNING_BOLT_THUNDER, 1.5, 1.0)
        for e in world.getNearbyEntities(target_loc, STRIKE_RADIUS, STRIKE_RADIUS, STRIKE_RADIUS):
            if not isinstance(e, LivingEntity):
                continue
            if e.getUniqueId().equals(player.getUniqueId()):
                continue
            try:
                e.damage(4.0, player)
            except Exception:
                pass
            kb = e.getLocation().toVector().subtract(target_loc.toVector())
            if kb.lengthSquared() < 0.01:
                kb = Vector(0, 1, 0)
            else:
                kb = kb.normalize()
            kb.setY(0.9)
            kb = kb.multiply(2.5)
            e.setVelocity(kb)
            e.addPotionEffect(PotionEffect(E_GLOWING, 10 * 20, 0, False, True, True))

    scheduler.runTaskLater(strike, 20)


# =============================================================================
#  ABILITY 4 — СУД МИРОЗДАНИЯ
# =============================================================================

def cast_court(player):
    global court_active
    court = _data["court"]
    if court["judge"] is None or court["defendant"] is None:
        player.sendMessage(u"§cСуд не настроен. §7Используй §f/demiurg устсуд <роль>§7.")
        return

    # Ищем подсудимого — тот, на кого смотрит Демиург (rayTrace 30 блоков), должен быть игрок.
    defendant = None
    result = player.rayTraceEntities(30)
    if result is not None and result.getHitEntity() is not None:
        cand = result.getHitEntity()
        if isinstance(cand, Player) and not cand.equals(player):
            defendant = cand
    if defendant is None:
        player.sendMessage(u"§cПрицелься Посохом на обвиняемого (до 30 блоков).")
        return

    begin_court_session(player, defendant)


def begin_court_session(judge, defendant):
    global court_active
    if court_active:
        judge.sendMessage(u"§cСуд уже идёт. §7Заверши: §f/demiurg суд стоп§7.")
        return

    court = _data["court"]
    judge_loc     = _loc_from_dict(court["judge"])
    defendant_loc = _loc_from_dict(court["defendant"])
    viewer_locs   = [_loc_from_dict(v) for v in court["viewers"] if v is not None]
    viewer_locs   = [v for v in viewer_locs if v is not None]

    if judge_loc is None or defendant_loc is None:
        judge.sendMessage(u"§cКоординаты Суда некорректны (мир не найден).")
        return

    court_active = True
    court_original.clear()

    # Сохраняем и телепортируем.
    court_original[uid(judge)] = judge.getLocation().clone()
    judge.teleport(judge_loc)

    court_original[uid(defendant)] = defendant.getLocation().clone()
    defendant.teleport(defendant_loc)

    # Остальных — на места зрителей.
    others = [p for p in Bukkit.getOnlinePlayers()
              if not p.equals(judge) and not p.equals(defendant)]
    for i in range(len(others)):
        p = others[i]
        if i < len(viewer_locs):
            court_original[uid(p)] = p.getLocation().clone()
            p.teleport(viewer_locs[i])
        # Если зрителей больше чем мест — оставляем на месте.

    # Уведомления.
    for p in Bukkit.getOnlinePlayers():
        p.sendTitle(u"§4§l⚖ СУД МИРОЗДАНИЯ ⚖", u"§7Демиург открывает заседание", 10, 60, 20)
        p.playSound(p.getLocation(), Sound.ENTITY_WITHER_SPAWN, 0.5, 1.4)

    judge.sendMessage(u"§7Суд начат. Завершить: §f/demiurg суд стоп")


def end_court_session():
    global court_active
    if not court_active:
        return
    for u, loc in list(court_original.items()):
        p = Bukkit.getPlayer(JUUID.fromString(u))
        if p is not None and p.isOnline() and loc is not None:
            p.teleport(loc)
            p.sendMessage(u"§7Заседание окончено. Ты возвращён.")
    court_original.clear()
    court_active = False


# =============================================================================
#  ABILITY 5 — УЛЬТИМЕЙТ (выбор Закона)
# =============================================================================

def enter_law_mode(player):
    u = uid(player)
    staff_submode[u] = "law"
    law_idx[u] = 0
    _render_law(player)
    player.sendMessage(u"§7Колесо мыши — листать Закон, §fПКМ§7 — подтвердить, §f/demiurg отмена§7 — выйти.")

def _render_law(player):
    u = uid(player)
    idx = law_idx.get(u, 0) % (LAW_MAX + 1)
    law_idx[u] = idx
    title = u"§4§lЗакон §7[" + str(idx+1) + u"/" + str(LAW_MAX+1) + u"] " + law_label(idx)
    if uid(player) in active_bossbar:
        update_bossbar(player, title)
    else:
        open_bossbar(player, title, BarColor.RED)

def confirm_law(player):
    u = uid(player)
    idx = law_idx.get(u, 0)
    exit_submode(player)
    apply_law(player, idx)


LAW_RADIUS   = 20.0
LAW_DURATION = 15 * 20   # 15 сек

def apply_law(demiurg, law_idx_v):
    if law_idx_v == 0:
        apply_law_silence(demiurg)
    elif law_idx_v == 1:
        apply_law_weakness(demiurg)
    elif law_idx_v == 2:
        apply_law_light(demiurg)
    elif law_idx_v == 3:
        apply_law_gravity(demiurg)
    elif law_idx_v == 4:
        toggle_law_justice(demiurg)


def _players_in_law_zone(demiurg):
    center = demiurg.getLocation()
    world = demiurg.getWorld()
    result = []
    for e in world.getNearbyEntities(center, LAW_RADIUS, LAW_RADIUS, LAW_RADIUS):
        if isinstance(e, Player) and not e.equals(demiurg):
            result.append(e)
    return result


def apply_law_silence(demiurg):
    demiurg.sendMessage(u"§8§l✦ Закон Тишины §7— 15 сек.")
    demiurg.getWorld().playSound(demiurg.getLocation(), Sound.BLOCK_BEACON_DEACTIVATE, 1.0, 0.6)
    end_tick = now_tick() + LAW_DURATION
    # Запоминаем, кого именно заглушили — чтобы точечно снять.
    affected_uids = []
    for p in _players_in_law_zone(demiurg):
        u = uid(p)
        silenced_uuids.add(u)
        affected_uids.append(u)
        p.sendMessage(u"§8Твои способности заглушены Демиургом.")
    active_laws[uid(demiurg)] = {
        "kind": "silence",
        "end_tick": end_tick,
        "demiurg_ref": demiurg,
        "affected": affected_uids,
    }

    def finish():
        law = active_laws.get(uid(demiurg))
        if law is None or law.get("kind") != "silence":
            return
        active_laws.pop(uid(demiurg), None)
        # Снимаем метки только с тех, кого сами наложили.
        # У Java HashSet remove(o) возвращает boolean и не бросает — но Jython
        # обёртывает set-подобно и .remove у отсутствующего кидает KeyError.
        # Используем безопасный вызов.
        for u in law.get("affected", []):
            try:
                silenced_uuids.remove(u)
            except Exception:
                # Уже удалён (например, повторным Тишины) — игнорируем.
                pass
        demiurg.sendMessage(u"§7Закон Тишины истёк.")
    scheduler.runTaskLater(finish, LAW_DURATION)


def apply_law_weakness(demiurg):
    demiurg.sendMessage(u"§7§l✦ Закон Слабости §7— 15 сек.")
    end_tick = now_tick() + LAW_DURATION
    center_supplier = lambda: demiurg.getLocation()
    active_laws[uid(demiurg)] = {
        "kind": "weakness", "end_tick": end_tick,
        "demiurg_ref": demiurg,
    }

    def finish():
        law = active_laws.get(uid(demiurg))
        if law and law.get("kind") == "weakness":
            active_laws.pop(uid(demiurg), None)
            demiurg.sendMessage(u"§7Закон Слабости истёк.")
    scheduler.runTaskLater(finish, LAW_DURATION)


def apply_law_light(demiurg):
    demiurg.sendMessage(u"§e§l✦ Закон Света §7— 15 сек.")
    for p in _players_in_law_zone(demiurg):
        p.addPotionEffect(PotionEffect(E_GLOWING, LAW_DURATION, 0, False, True, True))
    # Демиург тоже светится, для симметрии эффекта — по желанию, добавим.
    demiurg.addPotionEffect(PotionEffect(E_GLOWING, LAW_DURATION, 0, False, True, True))
    demiurg.getWorld().playSound(demiurg.getLocation(), Sound.BLOCK_BEACON_POWER_SELECT, 0.8, 1.6)


def apply_law_gravity(demiurg):
    demiurg.sendMessage(u"§b§l✦ Закон Гравитации §7— 15 сек.")
    for p in list(_players_in_law_zone(demiurg)) + [demiurg]:
        p.addPotionEffect(PotionEffect(E_SLOW_FALLING, LAW_DURATION, 0, False, True, True))
        p.addPotionEffect(PotionEffect(E_JUMP,         LAW_DURATION, 0, False, True, True))
    demiurg.getWorld().playSound(demiurg.getLocation(), Sound.ENTITY_PHANTOM_FLAP, 0.8, 1.4)


def toggle_law_justice(demiurg):
    u = uid(demiurg)
    # Повторная активация — завершение.
    if u in frozen_zones and frozen_zones[u].get("kind") == "justice":
        del frozen_zones[u]
        demiurg.sendMessage(u"§7Закон Справедливости отменён.")
        return
    frozen_zones[u] = {
        "kind": "justice",
        "owner_uid": u,
        "player_ref": demiurg,
        "radius": LAW_RADIUS,
        "start_tick": now_tick(),
        "allow_touch": True,   # Демиург может коснуться игрока Посохом
    }
    demiurg.sendMessage(u"§d§l✦ Закон Справедливости §r§7— всё замерло.")
    demiurg.sendMessage(u"§7Коснись игрока Посохом (ПКМ) — вызов на Суд.")
    demiurg.getWorld().playSound(demiurg.getLocation(), Sound.ITEM_TOTEM_USE, 0.9, 0.8)


# =============================================================================
#  FROZEN ZONE ENGINE (Time Stop + Law Justice)
# =============================================================================

FREEZE_SLOWNESS_AMP = 249
FREEZE_JUMP_AMP     = 128
FREEZE_MINING_AMP   = 4

def _iter_frozen_zones():
    """yield (demiurg_player, zone_dict)"""
    for u, zone in list(frozen_zones.items()):
        p = zone.get("player_ref")
        if p is None or not p.isOnline():
            frozen_zones.pop(u, None)
            continue
        yield p, zone

def _is_frozen_by_any_zone(target_uid):
    return target_uid in frozen_positions


def frozen_zones_tick():
    # Собираем текущий список замороженных.
    new_frozen_uids = set()
    for demiurg, zone in _iter_frozen_zones():
        center = demiurg.getLocation()
        world = demiurg.getWorld()
        radius = zone["radius"]

        # Визуал круга — окружность из частиц (каждые 4 тика, чтобы не спамить).
        if (now_tick() - zone["start_tick"]) % 4 == 0:
            _draw_zone_circle(world, center, radius, zone["kind"])

        for e in world.getNearbyEntities(center, radius, radius+3, radius):
            # Замораживаем игроков.
            if isinstance(e, Player):
                if e.equals(demiurg):
                    continue
                eu = uid(e)
                new_frozen_uids.add(eu)
                if eu not in frozen_positions:
                    frozen_positions[eu] = e.getLocation().clone()
                    e.sendMessage(u"§d§lВремя остановлено. §7Ты не можешь двигаться.")
                # Постоянно "накатываем" эффекты.
                e.addPotionEffect(PotionEffect(E_SLOWNESS,   20, FREEZE_SLOWNESS_AMP, False, False, False))
                e.addPotionEffect(PotionEffect(E_JUMP,       20, FREEZE_JUMP_AMP,     False, False, False))
                e.addPotionEffect(PotionEffect(E_MINING_FTG, 20, FREEZE_MINING_AMP,   False, False, False))
                # Если сдвинулся с исходной точки — телепортируем обратно (сохраняем yaw/pitch).
                orig = frozen_positions[eu]
                cur = e.getLocation()
                if orig.getWorld().equals(cur.getWorld()):
                    if orig.distanceSquared(cur) > 0.35:
                        # Возвращаем позицию, но yaw/pitch берём текущий (голову вращать можно).
                        back = orig.clone()
                        back.setYaw(cur.getYaw())
                        back.setPitch(cur.getPitch())
                        e.teleport(back)
                        e.setVelocity(Vector(0, 0, 0))
            # Обнуляем снаряды.
            elif isinstance(e, Projectile):
                e.setVelocity(Vector(0, 0, 0))
                try:
                    e.setGravity(False)
                except Exception:
                    pass

    # Освобождаем тех, кто больше не в зоне.
    for eu in list(frozen_positions.keys()):
        if eu not in new_frozen_uids:
            frozen_positions.pop(eu, None)


def _draw_zone_circle(world, center, radius, kind):
    steps = 60
    y = center.getY() + 0.1
    if kind == "justice":
        particle = Particle.END_ROD
    else:
        particle = Particle.ENCHANT
    for i in range(steps):
        angle = (2.0 * JMath.PI * i) / steps
        x = center.getX() + radius * JMath.cos(angle)
        z = center.getZ() + radius * JMath.sin(angle)
        loc = Location(world, x, y, z)
        world.spawnParticle(particle, loc, 1, 0.0, 0.6, 0.0, 0.0)


# =============================================================================
#  SUBMODE EXIT
# =============================================================================

def exit_submode(player):
    u = uid(player)
    staff_submode[u] = None
    close_bossbar(player)
    voice_msg_idx.pop(u, None)
    law_idx.pop(u, None)


# =============================================================================
#  MAIN ACTIVATION (right-click)
# =============================================================================

def activate_current(player):
    u = uid(player)
    sub = staff_submode.get(u)

    if sub == "voice":
        confirm_voice(player)
        return
    if sub == "law":
        confirm_law(player)
        return

    ability = get_ability(player)
    if   ability == 0: enter_voice_mode(player)
    elif ability == 1: toggle_time_stop(player)
    elif ability == 2: cast_smite(player)
    elif ability == 3: cast_court(player)
    elif ability == 4: enter_law_mode(player)


# =============================================================================
#  LISTENERS
# =============================================================================

def on_item_held(event):
    player = event.getPlayer()
    if not player.isSneaking():
        return
    inv = player.getInventory()
    prev = event.getPreviousSlot()
    nxt  = event.getNewSlot()
    if not (is_staff(inv.getItem(prev)) or is_staff(inv.getItem(nxt))):
        return

    diff = nxt - prev
    if   diff ==  8: direction = -1
    elif diff == -8: direction =  1
    elif diff  >  0: direction =  1
    else:            direction = -1

    u = uid(player)
    sub = staff_submode.get(u)
    if sub == "voice":
        voice_msg_idx[u] = voice_msg_idx.get(u, 0) + direction
        _render_voice(player)
    elif sub == "law":
        law_idx[u] = law_idx.get(u, 0) + direction
        _render_law(player)
    else:
        set_ability(player, get_ability(player) + direction)
    event.setCancelled(True)


def on_interact(event):
    if event.getHand() != EquipmentSlot.HAND:
        return
    p = event.getPlayer()
    item = event.getItem()

    # Замороженные игроки — режем все ПКМ.
    if _is_frozen_by_any_zone(uid(p)):
        event.setCancelled(True)
        return

    if item is None or not is_staff(item):
        return

    # Только настоящий владелец.
    if not can_use_staff(p, item):
        event.setCancelled(True)
        p.sendMessage(u"§cПосох отвергает тебя.")
        return

    action = event.getAction()
    if action != Action.RIGHT_CLICK_AIR and action != Action.RIGHT_CLICK_BLOCK:
        return

    event.setCancelled(True)
    activate_current(p)


def on_interact_entity(event):
    if event.getHand() != EquipmentSlot.HAND:
        return
    p = event.getPlayer()
    item = p.getInventory().getItemInMainHand()

    # Замороженный игрок не может тыкать по сущностям.
    if _is_frozen_by_any_zone(uid(p)):
        event.setCancelled(True)
        return

    if not is_staff(item) or not can_use_staff(p, item):
        return

    target = event.getRightClicked()
    if not isinstance(target, Player):
        return

    # В режиме "Закон Справедливости" — касание вызывает Суд.
    zone = frozen_zones.get(uid(p))
    if zone is not None and zone.get("kind") == "justice" and zone.get("allow_touch"):
        # Отключаем зону и запускаем сессию суда.
        frozen_zones.pop(uid(p), None)
        p.sendMessage(u"§d§lСуд да свершится!")
        begin_court_session(p, target)
        event.setCancelled(True)


def on_drop(event):
    it = event.getItemDrop().getItemStack()
    if is_staff(it):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cПосох Мироздания нельзя выбросить.")


def on_move(event):
    p = event.getPlayer()
    if _is_frozen_by_any_zone(uid(p)):
        # Отсекаем движение тела, вращение головы разрешаем.
        f = event.getFrom()
        t = event.getTo()
        if t is not None:
            if (f.getX() != t.getX()) or (f.getY() != t.getY()) or (f.getZ() != t.getZ()):
                new_to = f.clone()
                new_to.setYaw(t.getYaw())
                new_to.setPitch(t.getPitch())
                event.setTo(new_to)


def on_block_break(event):
    p = event.getPlayer()
    if _is_frozen_by_any_zone(uid(p)):
        event.setCancelled(True)


def on_damage_generic(event):
    ent = event.getEntity()
    if not isinstance(ent, Player):
        return
    u = uid(ent)
    # Игроки в зоне Закона Справедливости — не получают и не наносят урон.
    if u in frozen_positions:
        # Проверяем, что зона именно justice (не time stop).
        for zone_uid, zone in frozen_zones.items():
            if zone.get("kind") == "justice":
                event.setCancelled(True)
                return


def on_damage_by(event):
    dmg = event.getDamager()
    ent = event.getEntity()
    if isinstance(dmg, Player):
        u = uid(dmg)
        # Атакующий сам заморожен.
        if u in frozen_positions:
            event.setCancelled(True)
            return
        # Атакующий в зоне действия Закона Слабости — 50% урона.
        for zone_uid, law in active_laws.items():
            if law.get("kind") != "weakness":
                continue
            d = law.get("demiurg_ref")
            if d is None or not d.isOnline():
                continue
            if dmg.getLocation().distanceSquared(d.getLocation()) <= (LAW_RADIUS * LAW_RADIUS):
                event.setDamage(event.getDamage() * 0.5)
                return
    if isinstance(ent, Player):
        u = uid(ent)
        # Атакуют замороженного — обнуляем.
        if u in frozen_positions:
            event.setCancelled(True)
            return


def on_death(event):
    """
    Soulbound сам сохраняет предмет героя.
    """
    return



_needs_respawn_staff = set()

def on_respawn(event):
    """
    Проверяем через 40 тиков, вернул ли soulbound предмет.
    """

    player = event.getPlayer()

    if not is_demiurg(player):
        return

    def _check_and_restore():
        try:
            if not player.isOnline():
                return

            if player_has_staff_anywhere(player) is None:
                give_staff(player)
                player.sendMessage(u"§7[demiurg] Комплект восстановлен.")

        except Exception:
            import traceback
            traceback.print_exc()

    scheduler.runTaskLater(_check_and_restore, 40)



def on_inv_click(event):
    # Не даём положить посох ни в какой контейнер, кроме собственного инвентаря.
    it = event.getCurrentItem()
    cursor = event.getCursor()
    top_inv = event.getView().getTopInventory()
    bot_inv = event.getView().getBottomInventory()

    # Если куда-то тянут посох, а верхний инвентарь — не Player-inv.
    holder_top = top_inv.getHolder() if top_inv is not None else None
    is_container = holder_top is not None and not isinstance(holder_top, Player)

    if is_container:
        if (it is not None and is_staff(it)) or (cursor is not None and is_staff(cursor)):
            # Дополнительно блокируем shift-click в контейнер.
            action = event.getAction()
            if action == InventoryAction.MOVE_TO_OTHER_INVENTORY and event.getClickedInventory() == bot_inv:
                event.setCancelled(True)
                event.getWhoClicked().sendMessage(u"§cПосох Мироздания нельзя убрать в контейнер.")
                return
            if event.getClickedInventory() == top_inv:
                event.setCancelled(True)
                event.getWhoClicked().sendMessage(u"§cПосох Мироздания нельзя убрать в контейнер.")
                return


# =============================================================================
#  COMMAND /demiurg
# =============================================================================

def cmd_demiurg(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cКоманда доступна только игрокам.")
        return True
    if not is_demiurg(sender):
        sender.sendMessage(u"§cТолько Демиург может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/demiurg добавить <текст> §8— добавить в Глас")
        sender.sendMessage(u"  §f/demiurg удалить <номер> §8— удалить сообщение")
        sender.sendMessage(u"  §f/demiurg список §8— показать сообщения")
        sender.sendMessage(u"  §f/demiurg устсуд <роль> §8— судья|подсудимый|зритель|очистить|показать")
        sender.sendMessage(u"  §f/demiurg суд стоп §8— завершить заседание")
        sender.sendMessage(u"  §f/demiurg отмена §8— выйти из подрежима Посоха")
        return True

    sub = args[0].lower()

    if sub in (u"добавить", u"add"):
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/demiurg добавить <текст>")
            return True
        text = u" ".join(args[1:])
        _data["messages"].append(text)
        save_data()
        sender.sendMessage(u"§aДобавлено сообщение #" + str(len(_data["messages"])) + u": §7" + text)
        return True

    if sub in (u"удалить", u"remove", u"del"):
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/demiurg удалить <номер>")
            return True
        try:
            i = int(args[1]) - 1
        except ValueError:
            sender.sendMessage(u"§cНомер должен быть числом.")
            return True
        if 0 <= i < len(_data["messages"]):
            removed = _data["messages"].pop(i)
            save_data()
            sender.sendMessage(u"§aУдалено: §7" + removed)
        else:
            sender.sendMessage(u"§cНеверный номер.")
        return True

    if sub in (u"список", u"list"):
        if not _data["messages"]:
            sender.sendMessage(u"§7Библиотека Гласа пуста.")
            return True
        sender.sendMessage(u"§7Сообщения Гласа:")
        for i, m in enumerate(_data["messages"]):
            sender.sendMessage(u"  §f" + str(i+1) + u". §7" + m)
        return True

    if sub in (u"устсуд", u"court"):
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/demiurg устсуд <судья|подсудимый|зритель|очистить|показать>")
            return True
        role = args[1].lower()
        loc = sender.getLocation()
        if role in (u"судья", u"judge"):
            _data["court"]["judge"] = _loc_to_dict(loc)
            save_data()
            sender.sendMessage(u"§aМесто Судьи сохранено.")
        elif role in (u"подсудимый", u"defendant"):
            _data["court"]["defendant"] = _loc_to_dict(loc)
            save_data()
            sender.sendMessage(u"§aМесто Подсудимого сохранено.")
        elif role in (u"зритель", u"viewer"):
            _data["court"]["viewers"].append(_loc_to_dict(loc))
            save_data()
            sender.sendMessage(u"§aМесто зрителя #" + str(len(_data["court"]["viewers"])) + u" сохранено.")
        elif role in (u"очистить", u"clear"):
            _data["court"] = {"judge": None, "defendant": None, "viewers": []}
            save_data()
            sender.sendMessage(u"§aНастройки Суда очищены.")
        elif role in (u"показать", u"show"):
            c = _data["court"]
            sender.sendMessage(u"§7Судья: §f"      + (u"задан" if c["judge"] else u"—"))
            sender.sendMessage(u"§7Подсудимый: §f" + (u"задан" if c["defendant"] else u"—"))
            sender.sendMessage(u"§7Зрителей: §f"   + str(len(c["viewers"])))
        else:
            sender.sendMessage(u"§cНеизвестная роль.")
        return True

    if sub in (u"суд", u"court_control"):
        if len(args) >= 2 and args[1].lower() in (u"стоп", u"stop", u"end"):
            end_court_session()
            sender.sendMessage(u"§aЗаседание завершено.")
            return True
        sender.sendMessage(u"§7Использование: §f/demiurg суд стоп")
        return True

    if sub in (u"отмена", u"cancel"):
        exit_submode(sender)
        sender.sendMessage(u"§7Выбор отменён.")
        return True

    sender.sendMessage(u"§cНеизвестный подпункт: §f" + sub)
    return True


# =============================================================================
#  TICK LOOP
# =============================================================================

def _tick():
    try:
        frozen_zones_tick()
    except Exception as ex:
        Bukkit.getLogger().warning("[demiurg] tick error: " + str(ex))
    scheduler.runTaskLater(_tick, 4)


# =============================================================================
#  REGISTRATION
# =============================================================================

load_data()

cmd_mgr.registerCommand(cmd_demiurg, "demiurg")

listener_mgr.registerListener(on_item_held,        PlayerItemHeldEvent)
listener_mgr.registerListener(on_interact,         PlayerInteractEvent)
listener_mgr.registerListener(on_interact_entity,  PlayerInteractEntityEvent)
listener_mgr.registerListener(on_drop,             PlayerDropItemEvent)
listener_mgr.registerListener(on_move,             PlayerMoveEvent)
listener_mgr.registerListener(on_block_break,      BlockBreakEvent)
listener_mgr.registerListener(on_damage_generic,   EntityDamageEvent)
listener_mgr.registerListener(on_damage_by,        EntityDamageByEntityEvent)
listener_mgr.registerListener(on_death,            PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,          PlayerRespawnEvent)
listener_mgr.registerListener(on_inv_click,        InventoryClickEvent)

_tick()

# Регистрация набора в JVM-глобальном реестре /test-диспетчера.
_REGISTRY_KEY = "pyspigot.character_kits"
_props2 = System.getProperties()
_reg = _props2.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props2.put(_REGISTRY_KEY, _reg)
_reg.put("demiurg", (kit_entry, u"Демиург (Посох Мироздания)"))

# --- Публикация владельцев для admin-скрипта ---
_OWNERS_KEY = "character_owners"
_owners_reg = _props2.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props2.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("demiurg", list(DEMIURG_NAMES))

# --- Публикация в каталог Зеркала Души Арчера ---
def _demiurg_mirror_staff(owner_uuid):
    # Посох Мироздания для копии Арчера — материал + Efficiency V (тир I,
    # без Unbreaking/Mending — они убраны из оригинала).
    it = ItemStack(Material.NETHERITE_HOE, 1)
    meta = it.getItemMeta()
    meta.setDisplayName(u"§4Посох Мироздания")
    if ENC_EFFICIENCY: meta.addEnchant(ENC_EFFICIENCY, 5, True)
    it.setItemMeta(meta)
    return it

_MIRROR_CATALOG_KEY = "archer.mirror_catalog"
_mirror_cat = _props2.get(_MIRROR_CATALOG_KEY)
if _mirror_cat is None:
    _mirror_cat = HashMap()
    _props2.put(_MIRROR_CATALOG_KEY, _mirror_cat)

def _mirror_publish(entry_id, name, display, factory):
    e = HashMap()
    e.put("name", name)
    e.put("display", display)
    e.put("factory", factory)
    _mirror_cat.put(entry_id, e)

_mirror_publish("demiurg:staff", u"посох мироздания", u"§4Посох Мироздания", _demiurg_mirror_staff)

Bukkit.getLogger().info("[demiurg] Demiurg loaded. Command: /demiurg, kit: /test demiurg")

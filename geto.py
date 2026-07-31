# -*- coding: utf-8 -*-
"""
==============================================================================
  СУГУРУ ГЕТО (SSafari) — Поглощение мобов
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test geto                       — активирует роль (нет особого предмета)
  /geto <способность>              — способности
      поглотить | ульт
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, IllegalArgumentException, Long as JLong
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, GameMode, Location
)
from org.bukkit.entity import (
    Player, LivingEntity, EntityType,
    Warden, Ravager, ElderGuardian, Shulker, Wither, EnderDragon
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent, PlayerRespawnEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDeathEvent,
    EntityTargetLivingEntityEvent, PlayerDeathEvent
)
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.event.block import Action, BlockPlaceEvent, BlockBreakEvent
from org.bukkit.event.player import PlayerBucketEmptyEvent, PlayerBucketFillEvent
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.potion import PotionEffect
from org.bukkit.persistence import PersistentDataType
from org.bukkit.util import Vector
from org.bukkit.attribute import Attribute, AttributeModifier

# ============================================================================
# ATTRIBUTE RESOLVER (Paper 1.21.4+ переименовал GENERIC_* → без префикса)
# ============================================================================
def _attr(name):
    for full_name in (name, "GENERIC_" + name):
        a = getattr(Attribute, full_name, None)
        if a is not None:
            return a
    return None

ATTR_MAX_HEALTH           = _attr("MAX_HEALTH")
ATTR_ARMOR                = _attr("ARMOR")
ATTR_MOVEMENT_SPEED       = _attr("MOVEMENT_SPEED")
ATTR_KNOCKBACK_RESISTANCE = _attr("KNOCKBACK_RESISTANCE")
ATTR_ATTACK_DAMAGE        = _attr("ATTACK_DAMAGE")
ATTR_ATTACK_SPEED         = _attr("ATTACK_SPEED")
ATTR_FOLLOW_RANGE         = _attr("FOLLOW_RANGE")


# =============================================================================
#  CONSTANTS
# =============================================================================

GETO_NAMES      = set([u"ssafari", u"xx_ssafi_xx", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_EGG_MOB    = NamespacedKey.fromString("geto:egg_mob_type")   # STRING — имя EntityType
KEY_EGG_OWNER  = NamespacedKey.fromString("geto:egg_owner")      # STRING — uid владельца
KEY_EGG        = NamespacedKey.fromString("geto:egg_marker")     # BYTE — флаг

# Способности
CD_ABSORB       = 2 * 60 * 20     # 10 минут
CD_SUMMON       = 15 * 20          # 15 сек
CD_ULT          = 4 * 60 * 20      # 4 минуты
ULT_DUR         = 1 * 60 * 20      # 1 минута
ULT_TP_RADIUS   = 10.0

MAX_SUMMONS     = 8
SUMMON_LIFE     = 10 * 60 * 20     # 10 минут

MAX_HEALTH_MOD_UUID = JUUID.fromString("cccc1111-2222-3333-4444-555566667777")

# Мобы, которых нельзя поглотить (боссы и особые сущности).
FORBIDDEN_TYPES = set([
    EntityType.WARDEN,
    EntityType.RAVAGER,
    EntityType.ELDER_GUARDIAN,
    EntityType.SHULKER,
    EntityType.WITHER,
    EntityType.ENDER_DRAGON,
])


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k): return Registry.EFFECT.get(NamespacedKey.minecraft(k))

E_NAUSEA     = _effect("nausea")
E_WEAKNESS   = _effect("weakness")
E_STRENGTH   = _effect("strength")
E_REGEN      = _effect("regeneration")
E_SATURATION = _effect("saturation")
E_RESISTANCE = _effect("resistance")
E_FIRE_RES   = _effect("fire_resistance")
E_SPEED      = _effect("speed")


# =============================================================================
#  STATE
# =============================================================================

cooldowns    = {}
_max_hp_applied = set()

# Активные призванные существа: uid_owner -> list of {uuid, expire_tick}.
summons = {}   # uid_owner -> [ {"uuid": entity_uuid_str, "expire_tick": t}, ... ]

# Ульт-состояние
ult_active = {}   # uid -> end_tick
# Активные ульты: geto_uid -> { "saved_locs": {player_uid: Location},
#                               "trapped_uids": set(player_uid) }
# Используется PlayerDeathEvent'ом чтобы удалить умерших из возврата.
active_ults = {}


def uid(e): return e.getUniqueId().toString()
def now_tick(): return long(System.currentTimeMillis() / 50)
def is_free_cd(p): return p.getName().lower() in FREE_CD_PLAYERS

def _test_mode_on():
    try:
        v = System.getProperties().get("arena.test_mode")
        return v is None or str(v) == "1"
    except Exception:
        return True

def is_geto(p):
    name = p.getName().lower()
    if name not in GETO_NAMES:
        return False
    if name == u"blueredtronce":
        return _test_mode_on()
    return True

def is_silenced_by_demiurg(p):
    try:
        sil = System.getProperties().get("demiurg.silenced_uuids")
        return sil is not None and sil.contains(uid(p))
    except Exception:
        return False

def add_effect(e, pt, ticks, amp, ambient=False, particles=True):
    if pt is None: return
    e.addPotionEffect(PotionEffect(pt, ticks, amp, ambient, particles, True))

def java_list(it):
    lst = ArrayList()
    for x in it: lst.add(x)
    return lst

def get_cd(p, name):
    if is_free_cd(p): return 0
    d = cooldowns.get(uid(p))
    if not d: return 0
    r = d.get(name, 0) - now_tick()
    return r if r > 0 else 0

def set_cd(p, name, ticks):
    if is_free_cd(p): return
    u = uid(p)
    if u not in cooldowns: cooldowns[u] = {}
    cooldowns[u][name] = now_tick() + ticks

def check_cd(p, name, label=None):
    r = get_cd(p, name)
    if r > 0:
        secs = (r + 19) // 20
        p.sendMessage(u"§cПерезарядка%s: §f%d§7 сек." % ((u" "+label) if label else u"", secs))
        return False
    return True


# =============================================================================
#  EGG ITEM
# =============================================================================

_SPAWN_EGG_MATERIALS = {
    # Наиболее часто поглощаемые мобы. Fallback — PIG_SPAWN_EGG.
    "ZOMBIE": Material.ZOMBIE_SPAWN_EGG,
    "SKELETON": Material.SKELETON_SPAWN_EGG,
    "CREEPER": Material.CREEPER_SPAWN_EGG,
    "SPIDER": Material.SPIDER_SPAWN_EGG,
    "PIG": Material.PIG_SPAWN_EGG,
    "COW": Material.COW_SPAWN_EGG,
    "SHEEP": Material.SHEEP_SPAWN_EGG,
    "CHICKEN": Material.CHICKEN_SPAWN_EGG,
    "ENDERMAN": Material.ENDERMAN_SPAWN_EGG,
    "WITCH": Material.WITCH_SPAWN_EGG,
    "BLAZE": Material.BLAZE_SPAWN_EGG,
    "GHAST": Material.GHAST_SPAWN_EGG,
    "WOLF": Material.WOLF_SPAWN_EGG,
    "SLIME": Material.SLIME_SPAWN_EGG,
    "MAGMA_CUBE": Material.MAGMA_CUBE_SPAWN_EGG,
    "PILLAGER": Material.PILLAGER_SPAWN_EGG,
    "VINDICATOR": Material.VINDICATOR_SPAWN_EGG,
    "EVOKER": Material.EVOKER_SPAWN_EGG,
    "GUARDIAN": Material.GUARDIAN_SPAWN_EGG,
    "DROWNED": Material.DROWNED_SPAWN_EGG,
    "HUSK": Material.HUSK_SPAWN_EGG,
    "STRAY": Material.STRAY_SPAWN_EGG,
    "PHANTOM": Material.PHANTOM_SPAWN_EGG,
    "ZOMBIE_VILLAGER": Material.ZOMBIE_VILLAGER_SPAWN_EGG,
    "PIGLIN": Material.PIGLIN_SPAWN_EGG,
    "PIGLIN_BRUTE": Material.PIGLIN_BRUTE_SPAWN_EGG,
    "HOGLIN": Material.HOGLIN_SPAWN_EGG,
    "ZOGLIN": Material.ZOGLIN_SPAWN_EGG,
    "WITHER_SKELETON": Material.WITHER_SKELETON_SPAWN_EGG,
    "BREEZE": Material.BREEZE_SPAWN_EGG,
    "BOGGED": Material.BOGGED_SPAWN_EGG,
}

def _egg_material_for(entity_type):
    name = entity_type.name()
    m = _SPAWN_EGG_MATERIALS.get(name)
    if m is None:
        # Fallback: свинья.
        return Material.PIG_SPAWN_EGG
    return m


def create_personal_egg(entity_type, owner_uuid):
    mat = _egg_material_for(entity_type)
    it = ItemStack(mat, 1)
    m = it.getItemMeta()
    display_name = entity_type.name().replace("_", " ").title()
    m.setDisplayName(u"§d§lПоглощение: §f" + display_name)
    m.setLore(java_list([
        u"§7Персональное яйцо призыва Сугуру Гето.",
        u"§8Тип: §f" + display_name,
        u"",
        u"§8ПКМ по земле — выпустить существо.",
        u"§8Не выбрасывается, не передаётся.",
    ]))
    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_EGG,       PersistentDataType.BYTE,   JByte(1))
    pdc.set(KEY_EGG_MOB,   PersistentDataType.STRING, entity_type.name())
    pdc.set(KEY_EGG_OWNER, PersistentDataType.STRING, owner_uuid)
    it.setItemMeta(m)
    return it


def is_geto_egg(item):
    if item is None or item.getType() == Material.AIR: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_EGG, PersistentDataType.BYTE)

def get_egg_owner(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_EGG_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_EGG_OWNER, PersistentDataType.STRING)

def get_egg_entity_type(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_EGG_MOB, PersistentDataType.STRING): return None
    name = pdc.get(KEY_EGG_MOB, PersistentDataType.STRING)
    try:
        return EntityType.valueOf(name)
    except Exception:
        return None


def kit_entry(player, args_list):
    if not is_geto(player):
        player.sendMessage(u"§cТолько Сугуру Гето может активировать эту роль.")
        return
    player.sendMessage(u"§d§l✦ Роль Сугуру Гето активирована.")
    player.sendMessage(u"§7Способности: §f/geto поглотить§7, §f/geto ульт")
    player.sendMessage(u"§8Особого предмета нет — работаешь пустыми руками.")


# =============================================================================
#  ABILITY 1 — ПОГЛОЩЕНИЕ
# =============================================================================

def ability_absorb(player):
    if not is_geto(player): return
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
    if not check_cd(player, "absorb", u"«Поглощение»"):
        return

    # Ищем моба, на которого смотрит.
    result = player.rayTraceEntities(30)
    if result is None or result.getHitEntity() is None:
        player.sendMessage(u"§cНавидись на моба (до 30 блоков).")
        return
    target = result.getHitEntity()
    if not isinstance(target, LivingEntity) or isinstance(target, Player):
        player.sendMessage(u"§cПоглощать можно только мобов.")
        return
    et = target.getType()
    if et in FORBIDDEN_TYPES:
        player.sendMessage(u"§cЭту сущность нельзя поглотить.")
        return

    # Проверка здоровья ≤ 10%.
    hp_ratio = target.getHealth() / target.getMaxHealth()
    if hp_ratio > 0.10:
        player.sendMessage(u"§eМоб слишком силён. §7HP: §f%.1f§7/§f%.1f §8(нужно ≤ 10%%)" %
                           (target.getHealth(), target.getMaxHealth()))
        return

    # Свободный слот?
    inv = player.getInventory()
    free_slot = -1
    for i in range(inv.getSize()):
        it = inv.getItem(i)
        if it is None or it.getType() == Material.AIR:
            free_slot = i
            break
    if free_slot < 0:
        player.sendMessage(u"§cНет свободных слотов в инвентаре.")
        return

    # Поглощаем.
    egg = create_personal_egg(et, uid(player))
    inv.setItem(free_slot, egg)
    target.getWorld().spawnParticle(Particle.SOUL, target.getLocation().add(0, 1, 0),
                                    40, 0.6, 1.0, 0.6, 0.05)
    target.getWorld().playSound(target.getLocation(), Sound.ENTITY_ENDERMAN_TELEPORT, 1.0, 0.5)
    # Удаляем без drop.
    target.remove()

    player.sendMessage(u"§d§l✦ Поглощено: §f" + et.name())

    # Последствия — Nausea + Weakness II на 10 сек.
    add_effect(player, E_NAUSEA,   10 * 20, 0)
    add_effect(player, E_WEAKNESS, 10 * 20, 1)

    set_cd(player, "absorb", CD_ABSORB)


# =============================================================================
#  ABILITY 2 — ВЫПУСТИТЬ ЗВЕРЯ (через ПКМ по земле яйцом)
# =============================================================================

def _release_summon(player, egg_item, click_loc):
    """Вызывается когда игрок кликает яйцом по земле."""
    if not is_geto(player):
        return False
    owner = get_egg_owner(egg_item)
    if owner is None or owner != uid(player):
        player.sendMessage(u"§cЭто яйцо принадлежит другому магу.")
        return True   # cancel event

    et = get_egg_entity_type(egg_item)
    if et is None:
        player.sendMessage(u"§cЯйцо повреждено.")
        return True

    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return True

    if not check_cd(player, "summon", u"«Выпустить зверя»"):
        return True

    # Проверяем лимит.
    u = uid(player)
    _cleanup_expired_summons(u)
    active_list = summons.get(u, [])
    if len(active_list) >= MAX_SUMMONS:
        player.sendMessage(u"§cЛимит призывов: §f" + str(MAX_SUMMONS) + u"§c.")
        return True

    # Спавним.
    world = click_loc.getWorld()
    spawn_loc = click_loc.clone().add(0.5, 1.0, 0.5)
    try:
        entity = world.spawnEntity(spawn_loc, et)
    except Exception as ex:
        player.sendMessage(u"§cНе удалось призвать: §f" + str(ex))
        return True

    # Кастомное имя над мобом — «Призванный <Тип>».
    try:
        pretty = et.name().replace("_", " ").title()
        entity.setCustomName(u"§fПризванный " + pretty)
        entity.setCustomNameVisible(True)
        entity.setRemoveWhenFarAway(False)   # чтобы не деспавнился при уходе игрока
    except Exception:
        pass

    # Записываем.
    entity_uid = entity.getUniqueId().toString()
    active_list.append({
        "uuid": entity_uid,
        "expire_tick": now_tick() + SUMMON_LIFE,
        "assigned_target": None,   # UUID цели, которую разрешено атаковать
    })
    summons[u] = active_list

    # Помечаем моба как "пассивного" — сразу снимаем таргет и на всякий случай
    # пробуем отключить AI-агрессию через setAware(False) на 5 тиков? Нет, это
    # ломает поведение. Достаточно EntityTargetLivingEntityEvent cancel.
    try:
        if hasattr(entity, "setTarget"):
            entity.setTarget(None)
    except Exception:
        pass

    # Удаляем яйцо (одноразовое).
    egg_item.setAmount(egg_item.getAmount() - 1)
    if egg_item.getAmount() <= 0:
        player.getInventory().removeItem(egg_item)

    # Автовыпил через 10 минут.
    def despawn():
        try:
            for ent in world.getEntitiesByClass(LivingEntity):
                if ent.getUniqueId().toString() == entity_uid and not ent.isDead():
                    ent.getWorld().spawnParticle(Particle.SOUL, ent.getLocation().add(0, 1, 0),
                                                  20, 0.4, 0.6, 0.4, 0.02)
                    ent.remove()
                    break
        except Exception:
            pass
        _cleanup_expired_summons(u)

    scheduler.runTaskLater(despawn, SUMMON_LIFE)

    player.sendMessage(u"§d§l✦ Призван §f" + et.name() + u" §7(осталось " +
                       str(MAX_SUMMONS - len(active_list)) + u"/" + str(MAX_SUMMONS) + u")")
    world.spawnParticle(Particle.SOUL_FIRE_FLAME, spawn_loc, 30, 0.4, 0.4, 0.4, 0.05)
    world.playSound(spawn_loc, Sound.ENTITY_ENDERMAN_TELEPORT, 1.0, 0.8)
    set_cd(player, "summon", CD_SUMMON)
    return True


def _find_entity_by_uuid(uuid_str):
    """Ищет LivingEntity по строковому UUID во всех мирах.
       Возвращает None, если моб не найден или мёртв."""
    try:
        j_uuid = JUUID.fromString(uuid_str)
    except Exception:
        return None
    try:
        # Bukkit.getEntity(UUID) — есть в Paper с 1.20+.
        ent = Bukkit.getEntity(j_uuid)
        if ent is None: return None
        if not isinstance(ent, LivingEntity): return None
        if ent.isDead() or not ent.isValid(): return None
        return ent
    except Exception:
        # Fallback: обход всех миров.
        for world in Bukkit.getWorlds():
            for ent in world.getLivingEntities():
                if ent.getUniqueId().toString() == uuid_str:
                    if ent.isDead() or not ent.isValid():
                        return None
                    return ent
        return None


def _cleanup_expired_summons(u):
    """Убирает из реестра призывов те, что истекли по TTL ИЛИ мертвы/удалены."""
    lst = summons.get(u, [])
    if not lst:
        return
    now = now_tick()
    alive = []
    for s in lst:
        if s["expire_tick"] <= now:
            continue
        ent = _find_entity_by_uuid(s["uuid"])
        if ent is None:
            # Моб мёртв или де-спавнен.
            continue
        alive.append(s)
    summons[u] = alive


def _get_summon_uids_for_owner(player):
    """Возвращает set UUID-строк активных призывов игрока (без итерации по миру)."""
    u = uid(player)
    _cleanup_expired_summons(u)
    return set([s["uuid"] for s in summons.get(u, [])])


def _get_owner_of_summon(summon_entity):
    """По моб-сущности возвращает Player-владельца или None."""
    s_uid = summon_entity.getUniqueId().toString()
    for owner_uid, lst in summons.items():
        for s in lst:
            if s["uuid"] == s_uid:
                try:
                    return Bukkit.getPlayer(JUUID.fromString(owner_uid))
                except Exception:
                    return None
    return None


def _is_summon(entity):
    """Быстрый чекер: этот моб — чей-то призыв?"""
    if entity is None: return False
    try:
        s_uid = entity.getUniqueId().toString()
    except Exception:
        return False
    for lst in summons.values():
        for s in lst:
            if s["uuid"] == s_uid:
                return True
    return False


def _get_owner_summons(player):
    """Возвращает список LivingEntity — активных призывов игрока."""
    u = uid(player)
    _cleanup_expired_summons(u)
    lst = summons.get(u, [])
    if not lst: return []
    result = []
    for s in lst:
        ent = _find_entity_by_uuid(s["uuid"])
        if ent is not None:
            result.append(ent)
    return result


# =============================================================================
#  AI: призванные атакуют цель, которую атаковал/атакует владелец
# =============================================================================

def _make_summons_attack(player, target):
    """Заставляет всех призывов игрока атаковать target.
       Дополнительно ЗАПИСЫВАЕТ target как 'разрешённого' для каждого призыва —
       другие цели on_target отменит."""
    if target is None or not isinstance(target, LivingEntity): return
    tgt_uid = target.getUniqueId().toString()
    u = uid(player)
    lst = summons.get(u, [])
    for s in lst:
        s["assigned_target"] = tgt_uid
    for summon in _get_owner_summons(player):
        try:
            if hasattr(summon, "setTarget"):
                summon.setTarget(target)
        except Exception:
            pass


def _clear_summons_target(player):
    """Убирает assigned_target у всех призывов игрока — они снова пассивны."""
    u = uid(player)
    lst = summons.get(u, [])
    for s in lst:
        s["assigned_target"] = None
    for summon in _get_owner_summons(player):
        try:
            if hasattr(summon, "setTarget"):
                summon.setTarget(None)
        except Exception:
            pass


def _get_assigned_target(summon_entity):
    """Возвращает UUID разрешённой цели для конкретного призыва (или None)."""
    s_uid = summon_entity.getUniqueId().toString()
    for lst in summons.values():
        for s in lst:
            if s["uuid"] == s_uid:
                return s.get("assigned_target")
    return None


# ============================================================================
#  ПАССИВНЫЙ FOLLOWER-ТИКЕР
# ============================================================================
# Мобы (Zombie/Skeleton/...) по природе идут к ближайшему игроку через
# vanilla-pathfinding. Отмена EntityTargetLivingEntityEvent не мешает
# движению — только factos atack. Поэтому дополнительно:
#   1. Раз в 10 тиков (0.5 сек) проходим по призывам.
#   2. Если у призыва НЕТ assigned_target — принудительно ставим target=None
#      и, если моб дальше 20 блоков от владельца, телепортируем чуть ближе.
#   3. Если ЕСТЬ assigned_target — гарантируем что setTarget сохраняется.
#
# Так призывы "следуют" за Гето (не убегают на другой конец карты) но
# и не бегут на всех игроков автоматически.

FOLLOW_DIST_MAX  = 30.0   # если дальше — телепорт ближе (было 25)
FOLLOW_DIST_TP   = 5.0    # телепорт в 3-5 бл от владельца (было 8)
FOLLOW_DIST_WALK = 8.0    # ближе — стоят рядом; дальше — идут пешком к игроку
FOLLOW_WALK_SPEED = 1.15  # множитель ванильной скорости движения при follow

def _find_safe_tp_location(world, owner_loc, min_r=3.0, max_r=5.0):
    """
    Ищет безопасную точку для телепорта моба возле владельца.
    Проверяет:
      - Внизу твёрдый (не air, не жидкость) блок.
      - Сверху 2 блока воздуха (или passable) чтобы моб влез.
      - Не яма (перепад <= 3 бл от Y владельца).
    Возвращает Location или None если не нашли.
    """
    import random as _rnd
    import math as _m
    try:
        base_y = int(owner_loc.getY())
        cx = owner_loc.getX()
        cz = owner_loc.getZ()
        # 12 попыток случайных точек в кольце [min_r..max_r].
        for _ in range(12):
            ang = _rnd.uniform(0.0, 6.2831853)
            r = _rnd.uniform(min_r, max_r)
            tx = cx + r * _m.cos(ang)
            tz = cz + r * _m.sin(ang)
            bx = int(_m.floor(tx))
            bz = int(_m.floor(tz))
            # Сканируем колонку от +2 до -3 от Y владельца — ищем твёрдый блок.
            for dy in (0, -1, 1, -2, 2, -3):
                y = base_y + dy
                try:
                    below = world.getBlockAt(bx, y - 1, bz)
                    at    = world.getBlockAt(bx, y, bz)
                    above = world.getBlockAt(bx, y + 1, bz)
                    if below.getType().isSolid() and \
                       (not at.getType().isSolid() or at.isPassable()) and \
                       (not above.getType().isSolid() or above.isPassable()):
                        # Твёрдый блок под ногами + 2 воздуха над.
                        return Location(world, bx + 0.5, y, bz + 0.5,
                                        owner_loc.getYaw(), 0.0)
                except Exception:
                    continue
        return None
    except Exception:
        return None


def _follower_tick():
    try:
        for owner_uid, lst in list(summons.items()):
            try:
                owner = Bukkit.getPlayer(JUUID.fromString(owner_uid))
            except Exception:
                owner = None
            if owner is None or not owner.isOnline():
                continue
            owner_loc = owner.getLocation()
            owner_world = owner.getWorld()
            # Собираем живых призывов.
            for s in list(lst):
                try:
                    ent = Bukkit.getEntity(JUUID.fromString(s["uuid"]))
                except Exception:
                    ent = None
                if ent is None or not ent.isValid() or ent.isDead():
                    continue
                assigned = s.get("assigned_target")

                # === СЛУЧАЙ 1: Есть assigned_target (моб дерётся) ===
                if assigned is not None:
                    try:
                        tgt_ent = Bukkit.getEntity(JUUID.fromString(assigned))
                        if tgt_ent is not None and tgt_ent.isValid() and \
                           not tgt_ent.isDead() and \
                           isinstance(tgt_ent, LivingEntity):
                            # Дистанция до цели.
                            try:
                                d_target = ent.getLocation().distance(tgt_ent.getLocation()) \
                                    if ent.getWorld().equals(tgt_ent.getWorld()) else 9999.0
                            except Exception:
                                d_target = 9999.0
                            # Если цель слишком далеко (>40 бл) — забываем.
                            if d_target > 40.0:
                                s["assigned_target"] = None
                            else:
                                # Гарантируем таргет.
                                cur_target = ent.getTarget() if hasattr(ent, "getTarget") else None
                                if cur_target is None or not cur_target.equals(tgt_ent):
                                    if hasattr(ent, "setTarget"):
                                        ent.setTarget(tgt_ent)
                                # Приоритет БОЯ — не трогаем follow-логику.
                                continue
                        else:
                            # Цель умерла — сбрасываем и переходим в follow-режим.
                            s["assigned_target"] = None
                    except Exception:
                        s["assigned_target"] = None

                # === СЛУЧАЙ 2: Нет цели → follow владельца как собака ===
                # Не трогаем текущий getTarget если это НЕ владелец и НЕ игрок:
                # если моб случайно заагрил зомби — пусть добьёт. Но игрока
                # (кроме владельца) не даём атаковать.
                try:
                    if hasattr(ent, "getTarget"):
                        cur = ent.getTarget()
                        if cur is not None:
                            if isinstance(cur, Player) and not cur.equals(owner):
                                # Заагрил чужого игрока сам — сбрасываем.
                                ent.setTarget(None)
                            # Иначе (моб или владелец) — оставляем как есть.
                except Exception: pass

                # Дистанция до владельца.
                try:
                    if not ent.getWorld().equals(owner_world):
                        # Другой мир — телепорт.
                        safe = _find_safe_tp_location(owner_world, owner_loc,
                                                     min_r=3.0, max_r=FOLLOW_DIST_TP)
                        if safe is not None:
                            ent.teleport(safe)
                        else:
                            ent.teleport(owner_loc.clone())
                        continue

                    d = ent.getLocation().distance(owner_loc)

                    if d > FOLLOW_DIST_MAX:
                        # Далеко → безопасный TP.
                        safe = _find_safe_tp_location(owner_world, owner_loc,
                                                     min_r=3.0, max_r=FOLLOW_DIST_TP)
                        if safe is not None:
                            ent.teleport(safe)
                    elif d > FOLLOW_DIST_WALK:
                        # Средняя дистанция → Paper Pathfinder API.
                        pf_ok = False
                        try:
                            if hasattr(ent, "getPathfinder"):
                                pf = ent.getPathfinder()
                                if pf is not None:
                                    # moveTo(loc, speedMultiplier).
                                    pf.moveTo(owner_loc, FOLLOW_WALK_SPEED)
                                    pf_ok = True
                        except Exception:
                            pf_ok = False
                        if not pf_ok:
                            # Pathfinder недоступен — безопасный TP.
                            safe = _find_safe_tp_location(owner_world, owner_loc,
                                                         min_r=3.0, max_r=FOLLOW_DIST_TP)
                            if safe is not None:
                                ent.teleport(safe)
                    else:
                        # Близко — просто стоят рядом, ничего не делаем.
                        pass
                except Exception:
                    pass
    except Exception as ex:
        Bukkit.getLogger().warning("[geto] follower_tick: " + str(ex))
    scheduler.runTaskLater(_follower_tick, 10)


def on_damage_by(event):
    dmg = event.getDamager()
    ent = event.getEntity()

    # ---- 1) Дружественный огонь: призывы НЕ бьют владельца и соратников. ----
    # Настоящий damager может быть Projectile — тогда шутер = призванный моб.
    actual_attacker = dmg
    try:
        if hasattr(dmg, "getShooter"):
            s = dmg.getShooter()
            if isinstance(s, LivingEntity):
                actual_attacker = s
    except Exception:
        pass

    if _is_summon(actual_attacker):
        owner = _get_owner_of_summon(actual_attacker)
        if owner is not None:
            # Владелец?
            if isinstance(ent, Player) and ent.equals(owner):
                event.setCancelled(True)
                return
            # Соратник (другой призыв того же владельца)?
            if _is_summon(ent):
                other_owner = _get_owner_of_summon(ent)
                if other_owner is not None and other_owner.equals(owner):
                    event.setCancelled(True)
                    return

    # ---- 2) Гето получает магический урон — +20%. ----
    if isinstance(ent, Player) and is_geto(ent):
        cause = event.getCause()
        C = EntityDamageEvent.DamageCause
        try:
            from org.bukkit.damage import DamageType
            src = event.getDamageSource()
            if src is not None and src.getDamageType() == DamageType.MAGIC:
                event.setDamage(event.getDamage() * 1.20)
                return
        except Exception:
            pass
        if cause == C.MAGIC:
            event.setDamage(event.getDamage() * 1.20)

    # ---- 3) Гето атакует — направляем призывов на цель. ----
    if isinstance(dmg, Player) and is_geto(dmg):
        if isinstance(ent, LivingEntity) and not ent.equals(dmg) and not _is_summon(ent):
            _make_summons_attack(dmg, ent)

    # ---- 4) Гето получает удар — направляем призывов на атакующего. ----
    if isinstance(ent, Player) and is_geto(ent):
        atk = None
        if isinstance(dmg, LivingEntity):
            atk = dmg
        elif hasattr(dmg, "getShooter"):
            try:
                s = dmg.getShooter()
                if isinstance(s, LivingEntity):
                    atk = s
            except Exception:
                pass
        # Не таргетим собственных призывов (защита от бесконечного цикла).
        if atk is not None and not atk.equals(ent) and not _is_summon(atk):
            _make_summons_attack(ent, atk)


def on_target(event):
    """AI-хук: призыв может таргетить ТОЛЬКО назначенную владельцем цель.
       Всё остальное — cancel. Так мы гарантируем пассивное поведение по умолчанию."""
    target = event.getTarget()
    entity = event.getEntity()
    if not _is_summon(entity):
        return

    owner = _get_owner_of_summon(entity)
    if owner is None:
        return

    # target=None (моб сам сбросил цель) — всегда пропускаем.
    if target is None:
        return

    # Целится в владельца — режем.
    if isinstance(target, Player) and target.equals(owner):
        event.setCancelled(True)
        try: event.setTarget(None)
        except Exception: pass
        return

    # Целится в соратника (другой призыв того же владельца) — режем.
    if _is_summon(target):
        other_owner = _get_owner_of_summon(target)
        if other_owner is not None and other_owner.equals(owner):
            event.setCancelled(True)
            try: event.setTarget(None)
            except Exception: pass
            return

    # Разрешаем ТОЛЬКО назначенную цель. Всё остальное (ближайший игрок,
    # закрытая цель, ретаргет по звуку и т.д.) — cancel.
    assigned = _get_assigned_target(entity)
    if assigned is None:
        # Владелец пока никого не назначил — призыв пассивен.
        event.setCancelled(True)
        try: event.setTarget(None)
        except Exception: pass
        return

    if target.getUniqueId().toString() != assigned:
        event.setCancelled(True)
        try: event.setTarget(None)
        except Exception: pass


def on_death(event):
    """Когда призыв умирает — сразу чистим его из реестра."""
    ent = event.getEntity()
    if not _is_summon(ent):
        return
    s_uid = ent.getUniqueId().toString()
    for owner_uid, lst in list(summons.items()):
        summons[owner_uid] = [s for s in lst if s["uuid"] != s_uid]
    # Уведомление владельцу.
    owner = _get_owner_of_summon(ent)   # уже удалён из реестра, вернёт None
    # Ничего страшного, реестр очищен.
    try:
        # Отключаем drop опыта.
        event.setDroppedExp(0)
        # Удаляем drop предметов (призванные мобы не дают лут).
        event.getDrops().clear()
    except Exception:
        pass


def on_player_death(event):
    """
    Если игрок (Гето или пойманный внутри домена) умер во время активного
    ульта — удаляем его из saved_locs, чтобы при окончании ульта его не
    телепортировало обратно в точку захвата (он ведь уже респавнился на
    своей точке спавна).

    Если умер САМ Гето — сворачиваем ульт немедленно (иначе тепанёт трупа
    обратно, а живого — оставит в бедроке).
    """
    try:
        victim = event.getEntity()
        if not isinstance(victim, Player):
            return
        v_uid = uid(victim)

        # Гето умер внутри ульта — сворачиваем ульт немедленно.
        if v_uid in active_ults:
            info = active_ults.get(v_uid)
            if info is not None:
                # Убираем самого Гето из saved_locs, чтобы его не тепнуло
                # обратно после респа.
                info["saved_locs"].pop(v_uid, None)
                # А finish() выпустит остальных.
                # Специально НЕ вызываем finish() тут — пусть scheduler
                # доработает штатно, там разберём бедрок.
            return

        # Игрок пойман в чьём-то домене — удаляем его из saved_locs
        # умершего Гето, чтобы после респа его не тепнуло обратно.
        for geto_uid, info in list(active_ults.items()):
            trapped = info.get("trapped_uids") or set()
            if v_uid in trapped:
                info["saved_locs"].pop(v_uid, None)
                trapped.discard(v_uid)
                try:
                    Bukkit.getLogger().info(
                        "[geto][ult] player " + victim.getName()
                        + " died inside domain, removed from return list."
                    )
                except Exception:
                    pass
    except Exception as ex:
        try:
            Bukkit.getLogger().warning("[geto] on_player_death: " + str(ex))
        except Exception:
            pass


# =============================================================================
#  ABILITY 3 — УЛЬТ «РАСШИРЕНИЕ ТЕРРИТОРИИ»
# =============================================================================

def ability_ult(player):
    if not is_geto(player): return
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return

    # В Незере — не работает (нет столько сил, слишком жарко).
    try:
        env = player.getWorld().getEnvironment().name()
    except Exception:
        env = "NORMAL"
    if env == "NETHER":
        player.sendMessage(u"§c§oЗдесь слишком жарко... §7Гето не хватает сил для Расширения Территории.")
        try:
            player.getWorld().playSound(player.getLocation(),
                Sound.BLOCK_FIRE_EXTINGUISH, 0.9, 0.7)
        except Exception: pass
        return

    if not check_cd(player, "ult", u"«Расширение территории»"):
        return

    world = player.getWorld()
    center = player.getLocation()
    view_dir = center.getDirection().normalize()

    # Собираем до 2 ближайших игроков в конусе взгляда.
    candidates = []
    for e in world.getNearbyEntities(center, ULT_TP_RADIUS, ULT_TP_RADIUS, ULT_TP_RADIUS):
        if not isinstance(e, Player): continue
        if e.equals(player): continue
        to_e = e.getLocation().toVector().subtract(center.toVector())
        if to_e.lengthSquared() < 0.01: continue
        try:
            dot = to_e.normalize().dot(view_dir)
        except Exception:
            continue
        if dot >= 0.4:  # ~66° конус
            d = e.getLocation().distanceSquared(center)
            candidates.append((d, e))
    candidates.sort(key=lambda x: x[0])
    trapped = [e for _, e in candidates[:2]]

    # ==== ПОДПРОСТРАНСТВО: небесная камера из бедрока ====
    # Изменение 2026-07-28: y=300 в ТЕХ ЖЕ XZ координатах игрока (было random ±3000).
    # Так домен всегда над Гето, никаких телепортаций на края мира.
    y_max = min(world.getMaxHeight() - 20, 300)
    domain_y = y_max
    domain_x = center.getBlockX()
    domain_z = center.getBlockZ()

    domain_center = Location(world, domain_x + 0.5, domain_y + 1.0, domain_z + 0.5)

    # Размеры комнаты: 13×7×13, стенки-пол-потолок из бедрока.
    # R = 6 → внутри 11×11 свободной площади (dx от -5 до +5).
    # H = 6 → потолок на dy=6, внутри 5 блоков воздуха (dy=1..5).
    R = 6         # радиус пола (по X/Z) — было 4, стало 6 (+2 в каждую сторону)
    H = 6         # высота изнутри — было 4, стало 6 (для высоких мобов)
    placed_blocks = []   # список (x,y,z, prev_material_name)
    for dx in range(-R, R + 1):
        for dz in range(-R, R + 1):
            for dy in range(0, H + 1):
                # Только оболочка: стены (|dx|=R или |dz|=R), пол (dy=0), потолок (dy=H).
                is_wall  = (abs(dx) == R) or (abs(dz) == R)
                is_floor = (dy == 0)
                is_ceil  = (dy == H)
                if not (is_wall or is_floor or is_ceil):
                    continue
                b = world.getBlockAt(domain_x + dx, domain_y + dy, domain_z + dz)
                prev_mat = b.getType().name()
                placed_blocks.append((domain_x + dx, domain_y + dy,
                                       domain_z + dz, prev_mat))
                try:
                    b.setType(Material.BEDROCK)
                except Exception:
                    pass

    # Место для игроков внутри — на dy=1 (сразу над полом), в разных углах.
    inner_positions = [
        Location(world, domain_x + 1.5, domain_y + 1.0, domain_z + 0.5),
        Location(world, domain_x - 1.5, domain_y + 1.0, domain_z + 0.5),
    ]

    # Сохраняем позиции откуда взяли — чтобы вернуть в конце.
    saved_locs = {}   # uid -> Location

    for i, e in enumerate(trapped):
        saved_locs[uid(e)] = e.getLocation().clone()
        try:
            tp_loc = inner_positions[min(i, len(inner_positions) - 1)].clone()
            # Смотрим на центр (на Гето, который будет посередине).
            tp_loc.setYaw(e.getLocation().getYaw())
            tp_loc.setPitch(0.0)
            e.teleport(tp_loc)
            e.setFallDistance(0.0)
            e.sendTitle(u"§d§l« Расширение Территории »",
                        u"§7Ты в подпространстве Гето", 10, 60, 20)
            e.playSound(e.getLocation(), Sound.ENTITY_ENDER_DRAGON_GROWL, 1.0, 0.5)
        except Exception:
            pass

    # Гето — сам в центр комнаты.
    saved_locs[uid(player)] = player.getLocation().clone()
    try:
        geto_tp = Location(world, domain_x + 0.5, domain_y + 1.0, domain_z + 0.5)
        geto_tp.setYaw(player.getLocation().getYaw())
        geto_tp.setPitch(player.getLocation().getPitch())
        player.teleport(geto_tp)
        player.setFallDistance(0.0)
    except Exception:
        pass

    # Наши призывы — тоже в комнату + бустаем баффами.
    # Проблема которая была: мобы TP-лись в углы прямо в стену бедрока.
    # Теперь ищем БЕЗОПАСНЫЕ точки внутри комнаты (dy>=1, не в стене),
    # с учётом высоты моба (некоторые мобы 2-3 бл ростом).

    # Кандидатные позиции: сетка по внутренней области комнаты, отступ от стен 1.
    # Приоритет — по краям, чтобы не толпились в центре с Гето.
    candidate_positions = []
    edge = R - 1   # отступ от стен на 1 блок → координаты -edge..+edge
    # Сначала — угловая зона (dx, dz близко к краю), потом — центр.
    for dx in range(-edge, edge + 1):
        for dz in range(-edge, edge + 1):
            # Не в центре (там сам Гето).
            if abs(dx) <= 1 and abs(dz) <= 1:
                continue
            candidate_positions.append((dx, dz))
    # Сортируем по убыванию расстояния от центра — сначала дальние.
    candidate_positions.sort(key=lambda p: -(p[0] * p[0] + p[1] * p[1]))

    def _find_safe_summon_spot(entity):
        """Находит безопасную точку в комнате с учётом высоты моба.
        Проверяет: над полом (dy>=1), достаточно воздуха вверх для высоты моба,
        внутренняя область (не в стене)."""
        try:
            eh = entity.getHeight()
        except Exception:
            eh = 1.8
        # Нужное количество блоков воздуха над dy=1 (пол на dy=0).
        needed_air = max(1, int(eh) + 1)
        # Ограничиваем максимум H-1 (не выше внутреннего потолка).
        needed_air = min(needed_air, H - 1)

        for dx, dz in candidate_positions:
            # Пробуем dy=1 (сразу над полом).
            ok = True
            for check_dy in range(1, 1 + needed_air):
                b = world.getBlockAt(domain_x + dx, domain_y + check_dy, domain_z + dz)
                if b.getType() != Material.AIR:
                    ok = False
                    break
            if ok:
                return Location(world,
                                domain_x + dx + 0.5,
                                domain_y + 1.0,
                                domain_z + dz + 0.5)
        # Fallback — самая безопасная точка на 2 бл сбоку от Гето.
        return Location(world, domain_x + 2.5, domain_y + 1.0, domain_z + 0.5)

    used_spots = set()  # чтобы два моба не заняли одну точку
    summons_in_domain = []
    for summon in _get_owner_summons(player):
        try:
            # Ищем свободную безопасную точку, которую ещё не заняли.
            spot = None
            for dx, dz in candidate_positions:
                if (dx, dz) in used_spots:
                    continue
                # Проверка высоты моба.
                try:
                    eh = summon.getHeight()
                except Exception:
                    eh = 1.8
                needed_air = max(1, int(eh) + 1)
                needed_air = min(needed_air, H - 1)
                ok = True
                for check_dy in range(1, 1 + needed_air):
                    b = world.getBlockAt(domain_x + dx, domain_y + check_dy, domain_z + dz)
                    if b.getType() != Material.AIR:
                        ok = False
                        break
                if ok:
                    used_spots.add((dx, dz))
                    spot = Location(world,
                                    domain_x + dx + 0.5,
                                    domain_y + 1.0,
                                    domain_z + dz + 0.5)
                    break

            if spot is None:
                # Крайний случай: используем универсальный поиск.
                spot = _find_safe_summon_spot(summon)

            summon.teleport(spot)
            try:
                summon.setFallDistance(0.0)
            except Exception: pass
            summons_in_domain.append(summon)
        except Exception:
            pass

    # Применяем баффы призывам ЧЕРЕЗ 5 ТИКОВ — после TP моб может ещё не быть
    # полностью валидным, и add_effect молча теряется. Задержка это фиксит.
    # Плюс каждые 5 сек переприменяем эффекты — на случай если моб их сбросил
    # (Regeneration/Strength могут перезаписаться при получении урона).
    def _apply_summon_buffs(summons_list, ticks_left):
        try:
            alive = []
            for smn in summons_list:
                try:
                    if smn is None: continue
                    if not smn.isValid() or smn.isDead(): continue
                    # Мощные баффы внутри домена:
                    #   Strength II (amp=1) → +6 HP к базе.
                    #   Resistance I (amp=0) → -20% входящего.
                    #   Regeneration II (amp=1) → быстрое лечение.
                    #   Fire Resistance (для сафари в стенах бедрока).
                    #   Speed I (amp=0) → быстрее добегают до цели.
                    dur = max(60, ticks_left + 40)   # чуть дольше чтобы не мигало
                    add_effect(smn, E_STRENGTH,   dur, 1)
                    if E_RESISTANCE is not None:
                        add_effect(smn, E_RESISTANCE, dur, 0)
                    add_effect(smn, E_REGEN,      dur, 1)
                    if E_FIRE_RES is not None:
                        add_effect(smn, E_FIRE_RES,   dur, 0)
                    if E_SPEED is not None:
                        add_effect(smn, E_SPEED,      dur, 0)
                    alive.append(smn)
                except Exception:
                    pass
            # Переприменяем каждые 5 сек пока ульт активен.
            if ticks_left > 100 and alive:
                scheduler.runTaskLater(
                    lambda: _apply_summon_buffs(alive, ticks_left - 100),
                    100
                )
        except Exception as ex:
            Bukkit.getLogger().warning("[geto][ult] apply_summon_buffs: " + str(ex))

    scheduler.runTaskLater(lambda: _apply_summon_buffs(summons_in_domain, ULT_DUR), 5)

    # Гето — Регенерация I + Насыщение I на 10 сек.
    add_effect(player, E_REGEN,      10 * 20, 0)
    add_effect(player, E_SATURATION, 10 * 20, 0)

    world.spawnParticle(Particle.END_ROD, geto_tp, 80, 3.0, 2.0, 3.0, 0.05)
    world.spawnParticle(Particle.SOUL_FIRE_FLAME, geto_tp, 60, 3.0, 1.5, 3.0, 0.03)
    world.playSound(geto_tp, Sound.ENTITY_WITHER_SPAWN, 0.9, 0.5)
    world.playSound(geto_tp, Sound.ITEM_TOTEM_USE, 0.9, 0.7)

    player.sendMessage(u"§d§l✦ Расширение Территории §r§7— 1 минута.")
    player.sendMessage(u"§8Захвачено: §f" + str(len(trapped)) + u" §8игроков.")
    ult_active[uid(player)] = now_tick() + ULT_DUR

    # Список тех, кто внутри — чтобы вернуть их обратно.
    inside_uids = [uid(e) for e in trapped] + [uid(player)]

    # Регистрируем ульт глобально, чтобы PlayerDeathEvent мог удалить
    # умерших игроков из saved_locs (иначе после смерти + респа их
    # телепортирует обратно в старую точку захвата).
    # Bounds — координатные границы домена, используются в on_block_place/
    # on_block_break/on_bucket, чтобы блокировать любое редактирование внутри.
    geto_uid = uid(player)
    active_ults[geto_uid] = {
        "saved_locs":   saved_locs,       # dict, изменяется по ссылке
        "trapped_uids": set(uid(e) for e in trapped),
        "world_name":   world.getName(),
        "min_x":        domain_x - R,
        "max_x":        domain_x + R,
        "min_y":        domain_y,
        "max_y":        domain_y + H,
        "min_z":        domain_z - R,
        "max_z":        domain_z + R,
    }

    def finish():
        ult_active.pop(uid(player), None)
        active_ults.pop(geto_uid, None)

        # Возвращаем всех обратно.
        # saved_locs мог быть модифицирован on_player_death — умершие уже удалены.
        for u_str, orig in list(saved_locs.items()):
            try:
                p_ret = Bukkit.getPlayer(JUUID.fromString(u_str))
                if p_ret is None or not p_ret.isOnline():
                    continue
                # Дополнительная защита: если игрок недавно умер (isDead),
                # не тепаем — пусть респавнится нормально.
                if p_ret.isDead():
                    continue
                p_ret.teleport(orig)
                p_ret.setFallDistance(0.0)
                if u_str != uid(player):
                    p_ret.sendMessage(u"§7Территория распалась. Ты возвращён.")
            except Exception:
                pass

        # Разбираем бедрок-камеру: восстанавливаем прежние блоки.
        for (bx, by, bz, prev_mat_name) in placed_blocks:
            try:
                b = world.getBlockAt(bx, by, bz)
                # Только если сейчас там всё ещё наш бедрок.
                if b.getType() != Material.BEDROCK:
                    continue
                mat = Material.getMaterial(prev_mat_name)
                if mat is None:
                    b.setType(Material.AIR)
                else:
                    b.setType(mat)
            except Exception:
                pass

        if player.isOnline():
            player.sendMessage(u"§7Территория распалась.")

    scheduler.runTaskLater(finish, ULT_DUR)
    set_cd(player, "ult", CD_ULT + ULT_DUR)   # КД начинается ПОСЛЕ окончания


# =============================================================================
#  PASSIVES
# =============================================================================

def _enforce_max_health(player):
    u = uid(player)
    if u in _max_hp_applied:
        try:
            if player.getHealth() > 16.0:
                player.setHealth(16.0)
        except Exception:
            pass
        return
    try:
        attr = player.getAttribute(ATTR_MAX_HEALTH)
        mod = AttributeModifier(
            MAX_HEALTH_MOD_UUID, "geto_max_hp", -4.0,
            AttributeModifier.Operation.ADD_NUMBER
        )
        try:
            attr.addModifier(mod)
        except IllegalArgumentException:
            pass
        except Exception:
            pass
        _max_hp_applied.add(u)
        try:
            if player.getHealth() > 16.0:
                player.setHealth(16.0)
        except Exception:
            pass
    except Exception:
        pass


def _passives_tick():
    try:
        for pl in Bukkit.getOnlinePlayers():
            if not is_geto(pl): continue
            _enforce_max_health(pl)

            # Показываем HP цели при наведении на подходящего моба.
            try:
                res = pl.rayTraceEntities(15)
                if res is not None and res.getHitEntity() is not None:
                    tgt = res.getHitEntity()
                    if isinstance(tgt, LivingEntity) and not isinstance(tgt, Player):
                        et = tgt.getType()
                        if et not in FORBIDDEN_TYPES:
                            ratio = tgt.getHealth() / tgt.getMaxHealth()
                            if ratio <= 0.10:
                                pl.sendActionBar(u"§d§l⚡ §fГотов к поглощению §7(§c%.1f§7/§c%.1f HP)" %
                                                 (tgt.getHealth(), tgt.getMaxHealth()))
                            else:
                                pl.sendActionBar(u"§7HP §f%.1f§7/§f%.1f §8(нужно ≤ 10%%)" %
                                                 (tgt.getHealth(), tgt.getMaxHealth()))
            except Exception:
                pass
    except Exception as ex:
        Bukkit.getLogger().warning("[geto] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


# =============================================================================
#  EVENT HANDLERS
# =============================================================================

def on_interact(event):
    """Обработка ПКМ по земле яйцом Гето."""
    if event.getHand() != EquipmentSlot.HAND: return
    p = event.getPlayer()
    item = event.getItem()
    if item is None: return
    if not is_geto_egg(item):
        return
    # Только правый клик по блоку.
    action = event.getAction()
    if action != Action.RIGHT_CLICK_BLOCK:
        event.setCancelled(True)
        return
    event.setCancelled(True)
    click_loc = event.getClickedBlock().getLocation()
    _release_summon(p, item, click_loc)


def on_drop(event):
    it = event.getItemDrop().getItemStack()
    if is_geto_egg(it):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cЯйцо поглощения нельзя выбросить.")


def on_inv_click(event):
    it = event.getCurrentItem()
    cursor = event.getCursor()
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        if is_geto_egg(it) or is_geto_egg(cursor):
            event.setCancelled(True)
            event.getWhoClicked().sendMessage(u"§cЯйцо нельзя убрать в контейнер.")


# =============================================================================
#  COMMAND
# =============================================================================

def cmd_geto(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько для игроков.")
        return True
    if not is_geto(sender):
        sender.sendMessage(u"§cТолько Сугуру Гето может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/geto поглотить §7— поглотить ослабленного моба")
        sender.sendMessage(u"  §f/geto ульт §7— Расширение Территории")
        sender.sendMessage(u"  §f/geto призывы §7— показать активные призывы")
        return True

    sub = args[0].lower()

    if sub in (u"поглотить", u"absorb", u"consume"):
        ability_absorb(sender)
        return True

    if sub in (u"ульт", u"ult", u"расширение", u"территория"):
        ability_ult(sender)
        return True

    if sub in (u"призывы", u"summons", u"мобы"):
        active = _get_owner_summons(sender)
        sender.sendMessage(u"§7Активных призывов: §f" + str(len(active)) + u"§7 / §f" + str(MAX_SUMMONS))
        for e in active:
            sender.sendMessage(u"  §f- " + e.getType().name())
        return True

    sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
    return True


# =============================================================================
#  RESET STATE (для /admin resethp)
# =============================================================================

def _geto_reset_state(target_player):
    _max_hp_applied.discard(uid(target_player))
    ult_active.pop(uid(target_player), None)
    try:
        attr = target_player.getAttribute(ATTR_MAX_HEALTH)
        for m in list(attr.getModifiers()):
            try:
                attr.removeModifier(m)
            except Exception:
                pass
    except Exception:
        pass


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_geto, "geto")

def _is_inside_any_active_domain(block_or_location):
    """
    Проверяет: находится ли блок/локация внутри бокса активного домена
    какого-либо Гето. Возвращает True если да.
    Используется в BlockPlaceEvent/BlockBreakEvent/PlayerBucket*Event.
    """
    try:
        if hasattr(block_or_location, "getWorld"):
            loc_world = block_or_location.getWorld()
            bx = block_or_location.getX()
            by = block_or_location.getY()
            bz = block_or_location.getZ()
        else:
            return False
        world_name = loc_world.getName()

        for geto_uid, info in active_ults.items():
            if info.get("world_name") != world_name:
                continue
            if not (info["min_x"] <= bx <= info["max_x"]): continue
            if not (info["min_y"] <= by <= info["max_y"]): continue
            if not (info["min_z"] <= bz <= info["max_z"]): continue
            return True
    except Exception: pass
    return False


def on_block_place_in_domain(event):
    """Запрещаем ставить блоки внутри активного домена Гето."""
    try:
        block = event.getBlockPlaced()
        if block is None: return
        if _is_inside_any_active_domain(block):
            event.setCancelled(True)
            try:
                p = event.getPlayer()
                p.sendActionBar(u"§8В подпространстве Гето нельзя строить.")
            except Exception: pass
    except Exception: pass


def on_block_break_in_domain(event):
    """Запрещаем ломать блоки внутри активного домена (кроме бедрока — он и так неломаем)."""
    try:
        block = event.getBlock()
        if block is None: return
        if _is_inside_any_active_domain(block):
            event.setCancelled(True)
            try:
                p = event.getPlayer()
                p.sendActionBar(u"§8В подпространстве Гето нельзя ломать блоки.")
            except Exception: pass
    except Exception: pass


def on_bucket_empty_in_domain(event):
    """Запрещаем выливать воду/лаву в домене."""
    try:
        block = event.getBlockClicked()
        if block is None: return
        # Проверяем ту клетку, куда собираются вылить (block + face).
        try:
            face = event.getBlockFace()
            target = block.getRelative(face)
        except Exception:
            target = block
        if _is_inside_any_active_domain(target):
            event.setCancelled(True)
            try:
                event.getPlayer().sendActionBar(u"§8В подпространстве Гето нельзя выливать жидкости.")
            except Exception: pass
    except Exception: pass


def on_bucket_fill_in_domain(event):
    """Запрещаем набирать воду/лаву из домена."""
    try:
        block = event.getBlockClicked()
        if block is None: return
        if _is_inside_any_active_domain(block):
            event.setCancelled(True)
            try:
                event.getPlayer().sendActionBar(u"§8В подпространстве Гето нельзя забирать жидкости.")
            except Exception: pass
    except Exception: pass


listener_mgr.registerListener(on_interact,   PlayerInteractEvent)
listener_mgr.registerListener(on_drop,       PlayerDropItemEvent)
listener_mgr.registerListener(on_inv_click,  InventoryClickEvent)
listener_mgr.registerListener(on_damage_by,  EntityDamageByEntityEvent)
listener_mgr.registerListener(on_target,     EntityTargetLivingEntityEvent)
listener_mgr.registerListener(on_death,      EntityDeathEvent)
listener_mgr.registerListener(on_player_death, PlayerDeathEvent)
listener_mgr.registerListener(on_block_place_in_domain, BlockPlaceEvent)
listener_mgr.registerListener(on_block_break_in_domain, BlockBreakEvent)
listener_mgr.registerListener(on_bucket_empty_in_domain, PlayerBucketEmptyEvent)
listener_mgr.registerListener(on_bucket_fill_in_domain,  PlayerBucketFillEvent)

_passives_tick()

# --- Реестры /test, владельцев, reset ---
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("geto", (kit_entry, u"Сугуру Гето (без предмета)"))

_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("geto", list(GETO_NAMES))

_RESET_KEY = "character_reset_functions"
_reset_reg = _props.get(_RESET_KEY)
if _reset_reg is None:
    _reset_reg = HashMap()
    _props.put(_RESET_KEY, _reset_reg)
_reset_reg.put("geto", _geto_reset_state)

# Особого предмета нет → в каталог Зеркала Арчера не публикуем.

# Стартуем follower-тикер (мобы следуют за Гето, а не бегут на других).
scheduler.runTaskLater(_follower_tick, 40)

Bukkit.getLogger().info("[geto] Geto loaded. Commands: /test geto, /geto")

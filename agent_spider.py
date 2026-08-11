# -*- coding: utf-8 -*-
"""
==============================================================================
  АГЕНТ-ПАУК / ItsArtemiy
  Скрипт персонажа для vanilla PvP/RP сервера
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  Команды:
    /test spider           — выдать комплект (маска + эжектор)
    /spider <способность>  — способности "на игроке" (маска обязательна)
        рефлексы | сенсоры | прыжок | ульт
------------------------------------------------------------------------------
  Тестовый аккаунт без КД: blueredtronce
==============================================================================
"""

import pyspigot as ps
import math
import random

# В PySpigot 0.9.1:
#   command_manager() / listener_manager() — функции-геттеры  → со скобками
#   scheduler — уже готовый BukkitTaskManager-объект            → без скобок
cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, Float as JFloat
from java.util import UUID as JUUID, ArrayList

from org.bukkit import (
    Bukkit, Material, Color, Particle, Sound,
    NamespacedKey, Registry
)
from org.bukkit.entity import (
    Player, Snowball, LivingEntity, ArmorStand, Vex, Evoker, Item, TNTPrimed
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerItemHeldEvent, PlayerDropItemEvent,
    PlayerToggleSneakEvent, PlayerMoveEvent, PlayerQuitEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, ProjectileHitEvent,
    EntityDeathEvent
)
from org.bukkit.event.block import Action, BlockBreakEvent, BlockDispenseEvent, BlockRedstoneEvent
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.inventory.meta import LeatherArmorMeta
from org.bukkit.potion import PotionEffect
from org.bukkit.persistence import PersistentDataType
from org.bukkit.util import Vector
from org.bukkit.attribute import Attribute


# =============================================================================
#  КОНСТАНТЫ
# =============================================================================

# Персонажи, к которым применяется пассивка (повышенный урон огня).
SPIDER_OWNERS   = set([u"itsartemiy", u"blueredtronce"])
# Аккаунты, которым отключены все КД (для тестирования).
FREE_CD_PLAYERS = set([u"blueredtronce"])

# PDC-ключи. fromString — публичное API, без warning'ов о deprecated-конструкторе.
KEY_MASK    = NamespacedKey.fromString("spideragent:mask")
KEY_EJECTOR = NamespacedKey.fromString("spideragent:ejector")
KEY_PROJ    = NamespacedKey.fromString("spideragent:proj_mode")
KEY_OWNER   = NamespacedKey.fromString("spideragent:proj_owner")
KEY_WINGS   = NamespacedKey.fromString("spideragent:wings")
KEY_TEMP_ENTITY = NamespacedKey.fromString("spideragent:temporary_entity")

# КД (в тиках, 20 tick = 1 сек).
CD_REFLEX   = 60 * 20
CD_SENSES   = 90 * 20
CD_JUMP     = 30 * 20
CD_ULT      = 4 * 60 * 20

CD_SWING    = 1  * 20
CD_LINE     = 10 * 20
CD_BALL     = 5  * 20
CD_IMPACT   = 10 * 20
CD_GRENADE  = 20 * 20
CD_SHOCK    = 15 * 20
CD_FIREWEB  = 10 * 20

# Новая квестовая ветка. Боевые КД немного ниже исходного ТЗ, но массовые
# способности всё ещё нельзя чередовать без окон для ответа противника.
CD_MACE       = 25 * 20
CD_TRAP       = 24 * 20
CD_LUNGE      = 16 * 20
CD_WINGS      = 60 * 20
CD_DRONE      = 60 * 20
CD_BOUNCE     = 10 * 20
CD_COCOON     = 90 * 20
CD_HURRICANE  = 24 * 20
CD_GRAVITY    = 25 * 20
CD_HORIZON    = 25 * 20

# Магазин боевых выстрелов: 10 патронов, полная перезарядка 15 сек.
# Каждый боевой выстрел (не полёт) тратит 1 патрон. Кончились — жди.
# Первый выстрел после кулдауна автоматически даёт полный магазин.
EJECTOR_MAX_AMMO      = 10
EJECTOR_RELOAD_TICKS  = 15 * 20   # полная перезарядка магазина
# Радиус попадания снаряда: если Snowball не задел цель прямо, ищем в
# кубе +-HITBOX_RADIUS блоков вокруг точки его удара о блок.
HIT_RADIUS            = 1.5

# Ровно 13 режимов эжектора. Масочные пассивы (уворот, крылья, отскок)
# живут отдельно и не раздувают колесо режимов.
MODE_INFO = {
    0: (u"Полёт на паутине",  u"§b"),
    1: (u"Паутинная нить",    u"§e"),
    2: (u"Паутинная булава",  u"§f"),
    3: (u"Паутинное шенбяо",  u"§2"),
    4: (u"Паучий выпад",      u"§6"),
    5: (u"Паучий дрон",       u"§d"),
    6: (u"Паучий кокон",      u"§7"),
    7: (u"Паутинный ураган",  u"§b"),
    8: (u"Гравиколодец",      u"§5"),
    9: (u"Паутинный горизонт",u"§4"),
    10:(u"Шок-Паутина",       u"§9"),
    11:(u"Огненная паутина",  u"§c"),
    12:(u"Ударная паутина",   u"§a"),
}
MODE_MAX = 12

MODE_QUEST = {
    2: "mace", 3: "trap", 4: "lunge", 5: "drone", 6: "cocoon",
    7: "hurricane", 8: "gravity", 9: "horizon"
}


# =============================================================================
#  ЭФФЕКТЫ (Paper 1.21 → Registry.EFFECT)
# =============================================================================

def _effect(key):
    return Registry.EFFECT.get(NamespacedKey.minecraft(key))

E_SPEED      = _effect("speed")
E_JUMP       = _effect("jump_boost")
E_RESISTANCE = _effect("resistance")
E_GLOWING    = _effect("glowing")
E_BLINDNESS  = _effect("blindness")
E_SLOWNESS   = _effect("slowness")
E_LEVITATION = _effect("levitation")
E_REGEN      = _effect("regeneration")
E_WEAKNESS   = _effect("weakness")
E_DARKNESS   = _effect("darkness")


# =============================================================================
#  СОСТОЯНИЕ (in-memory, per-uuid)
# =============================================================================

cooldowns     = {}     # uid -> {ability_name: end_tick}
player_mode   = {}     # uid -> int
swing_active  = set()  # uid, чей "полёт на паутине" ещё в воздухе
ultimate_lock = set()  # uid игроков в фазе ультимейта
lunge_invulnerable = set()
fall_immune_until = {}

# Магазин боевых выстрелов эжектора.
# uid -> {"ammo": int, "reload_end": tick_when_reload_finishes}
ejector_ammo = {}
spider_drones = {}     # vex uuid -> owner uuid
spider_traps = []      # активные одноразовые ловушки
temporary_anchors = [] # невидимые стойки булавы/гравиколодца
wings_active = {}      # player uuid -> {old_chest, active}
fall_tracks = {}       # player uuid -> {top, invalid}
levitation_tracks = {} # player uuid -> стартовая высота
recent_tripwire_pulses = []  # [{location, tick}], один импульс = один запуск раздатчика

def quest_unlocked(player, key):
    if is_free_cd(player): return True
    try:
        fn = System.getProperties().get("quest_tracker.ability_unlocked")
        return bool(fn(player, "spider", key)) if fn is not None else False
    except Exception:
        return False

def add_quest_progress(player, key, amount=1):
    # Тестовый аккаунт без КД всё равно должен уметь проверять прогресс квестов.
    if not is_free_cd(player) and quest_unlocked(player, key): return
    try:
        fn = System.getProperties().get("quest_tracker.increment")
        if fn is not None: fn("spider_" + key, player, int(amount), "progress")
    except Exception as ex:
        Bukkit.getLogger().warning("[spider_agent] quest event: " + str(ex))

def require_quest(player, key):
    if quest_unlocked(player, key): return True
    player.sendMessage(u"§cСпособность ещё не открыта. §7Прогресс: §f/quests")
    return False

def _get_ammo_state(player):
    """Возвращает актуальное состояние магазина. Если перезарядка кончилась —
    восстанавливает полный магазин."""
    u = uid(player)
    st = ejector_ammo.get(u)
    if st is None:
        st = {"ammo": EJECTOR_MAX_AMMO, "reload_end": 0}
        ejector_ammo[u] = st
    # Если магазин пуст и перезарядка завершена — восстанавливаем.
    if st["ammo"] <= 0 and st["reload_end"] > 0 and now_tick() >= st["reload_end"]:
        st["ammo"] = EJECTOR_MAX_AMMO
        st["reload_end"] = 0
        try:
            player.sendActionBar(u"§a§lЭжектор перезаряжен §7[§f%d§7/§f%d§7]" %
                                 (EJECTOR_MAX_AMMO, EJECTOR_MAX_AMMO))
            player.getWorld().playSound(player.getLocation(),
                Sound.BLOCK_IRON_TRAPDOOR_CLOSE, 0.8, 1.5)
        except Exception: pass
    return st

def _try_consume_ammo(player, label):
    """Пытается потратить 1 патрон боевого магазина. True если получилось."""
    if player.getName().lower() in FREE_CD_PLAYERS:
        return True
    st = _get_ammo_state(player)
    if st["ammo"] <= 0:
        rem = max(0, (st["reload_end"] - now_tick()) / 20.0)
        player.sendMessage(u"§7Магазин " + label + u" §7пуст. Перезарядка: §c%.1f §7сек." % rem)
        try:
            player.getWorld().playSound(player.getLocation(), Sound.BLOCK_DISPENSER_FAIL, 0.7, 0.8)
        except Exception: pass
        return False
    st["ammo"] -= 1
    # Если только что опустошили — стартуем перезарядку.
    if st["ammo"] <= 0:
        st["reload_end"] = now_tick() + EJECTOR_RELOAD_TICKS
        try:
            player.sendActionBar(u"§c§lЭжектор пуст! §7Перезарядка §f%d §7сек." %
                                 (EJECTOR_RELOAD_TICKS // 20))
            player.getWorld().playSound(player.getLocation(),
                Sound.BLOCK_IRON_TRAPDOOR_OPEN, 0.9, 0.6)
        except Exception: pass
    else:
        # Иначе — показываем остаток.
        try:
            player.sendActionBar(u"§7Патроны эжектора: §f%d§7/§f%d" %
                                 (st["ammo"], EJECTOR_MAX_AMMO))
        except Exception: pass
    return True


# =============================================================================
#  УТИЛИТЫ
# =============================================================================

def uid(p):
    return p.getUniqueId().toString()

def now_tick():
    return long(System.currentTimeMillis() / 50)

def _test_mode_on():
    try:
        v = System.getProperties().get("arena.test_mode")
        return v is None or str(v) == "1"
    except Exception:
        return True

def _is_spider_role(player):
    name = player.getName().lower()
    if name not in SPIDER_OWNERS:
        return False
    if name == u"blueredtronce":
        return _test_mode_on()
    return True


def is_free_cd(player):
    return player.getName().lower() in FREE_CD_PLAYERS

def is_silenced_by_demiurg(player):
    """True если UUID игрока в глобальном set'е заглушённых Демиургом."""
    try:
        sil = System.getProperties().get("demiurg.silenced_uuids")
        if sil is None:
            return False
        return sil.contains(player.getUniqueId().toString())
    except Exception:
        return False

def get_cd(player, name):
    if is_free_cd(player):
        return 0
    d = cooldowns.get(uid(player))
    if not d:
        return 0
    remain = d.get(name, 0) - now_tick()
    return remain if remain > 0 else 0

def set_cd(player, name, ticks):
    if is_free_cd(player):
        return
    u = uid(player)
    if u not in cooldowns:
        cooldowns[u] = {}
    cooldowns[u][name] = now_tick() + ticks

def check_cd(player, name, label=None):
    r = get_cd(player, name)
    if r > 0:
        secs = (r + 19) // 20
        tag = (u" " + label) if label else u""
        player.sendMessage(u"§cПерезарядка%s: §f%d§7 сек." % (tag, secs))
        return False
    return True

def add_effect(entity, ptype, ticks, amp, ambient=False, particles=True):
    if ptype is None:
        return
    entity.addPotionEffect(PotionEffect(ptype, ticks, amp, ambient, particles, True))

def has_pdc_flag(item, key):
    if item is None or item.getType() == Material.AIR:
        return False
    meta = item.getItemMeta()
    if meta is None:
        return False
    return meta.getPersistentDataContainer().has(key, PersistentDataType.BYTE)

def set_pdc_flag(meta, key):
    # PersistentDataType.BYTE требует именно java.lang.Byte — Python int бросает IllegalArgumentException.
    meta.getPersistentDataContainer().set(key, PersistentDataType.BYTE, JByte(1))

def is_mask(item):     return has_pdc_flag(item, KEY_MASK)
def is_ejector(item):  return has_pdc_flag(item, KEY_EJECTOR)

def wearing_mask(player):
    return is_mask(player.getInventory().getHelmet())

def java_list(py_iterable):
    lst = ArrayList()
    for it in py_iterable:
        lst.add(it)
    return lst


# =============================================================================
#  ПРЕДМЕТЫ: маска и эжектор
# =============================================================================

def create_mask():
    it = ItemStack(Material.LEATHER_HELMET, 1)
    meta = it.getItemMeta()
    meta.setDisplayName(u"§c§lМаска Агент-Паука")
    meta.setLore(java_list([
        u"§7Алая маска с подвижными линзами.",
        u"§7Нейроны внутри маски активируют",
        u"§7паучий ген носителя.",
        u"",
        u"§8Обязательна для использования способностей.",
    ]))
    if isinstance(meta, LeatherArmorMeta):
        meta.setColor(Color.fromRGB(178, 34, 34))
    meta.setUnbreakable(True)
    set_pdc_flag(meta, KEY_MASK)
    it.setItemMeta(meta)
    return it

def create_ejector():
    it = ItemStack(Material.PRISMARINE_SHARD, 1)
    meta = it.getItemMeta()
    meta.setDisplayName(u"§f§lЭжектор паутины")
    meta.setLore(java_list([
        u"§7Компактный механизм выброса паутины",
        u"§7с 13 боевыми режимами.",
        u"",
        u"§8Режим: §bПолёт на паутине §7[0]",
        u"§8Shift + Колесо мыши — смена режима",
        u"§8ПКМ — выстрел",
    ]))
    meta.setUnbreakable(True)
    set_pdc_flag(meta, KEY_EJECTOR)
    it.setItemMeta(meta)
    return it

def update_ejector_lore(player):
    inv = player.getInventory()
    for i in range(9):
        item = inv.getItem(i)
        if not is_ejector(item):
            continue
        mode = get_mode(player)
        name, color = MODE_INFO[mode]
        meta = item.getItemMeta()
        meta.setLore(java_list([
            u"§7Компактный механизм выброса паутины",
            u"§7с 13 боевыми режимами.",
            u"",
            u"§8Режим: " + color + name + u" §7[" + str(mode) + u"]",
            u"§8Shift + Колесо мыши — смена режима",
            u"§8ПКМ — выстрел",
        ]))
        item.setItemMeta(meta)


# =============================================================================
#  РЕЖИМЫ ЭЖЕКТОРА
# =============================================================================

def get_mode(player):
    return player_mode.get(uid(player), 0)

def set_mode(player, mode):
    mode = mode % (MODE_MAX + 1)
    player_mode[uid(player)] = mode
    name, color = MODE_INFO[mode]
    player.sendMessage(u"§8⌬ §fРежим эжектора: " + color + name + u" §7[" + str(mode) + u"]")
    player.playSound(player.getLocation(), Sound.UI_BUTTON_CLICK, 0.6, 1.7)
    update_ejector_lore(player)


# =============================================================================
#  ВЫДАЧА КОМПЛЕКТА
# =============================================================================

def give_kit(player):
    inv = player.getInventory()
    inv.setHelmet(create_mask())

    # Ставим эжектор в первый свободный хотбар-слот, либо в 0.
    placed = False
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_ejector())
            placed = True
            break
    if not placed:
        inv.setItem(0, create_ejector())

    player_mode[uid(player)] = 0
    update_ejector_lore(player)
    player.sendMessage(u"§a✔ Комплект Агент-Паука выдан.")


def kit_entry(player, args_list):
    """Обёртка для test_dispatcher: (player, args) -> None."""
    give_kit(player)


# =============================================================================
#  СПОСОБНОСТИ "НА ИГРОКЕ"
# =============================================================================

def ability_reflexes(player):
    if not check_cd(player, "reflex", u"«Паучьи рефлексы»"):
        return
    dur = 20 * 20
    add_effect(player, E_SPEED,      dur, 1)
    add_effect(player, E_JUMP,       dur, 1)
    add_effect(player, E_RESISTANCE, dur, 0)
    set_cd(player, "reflex", CD_REFLEX)
    add_quest_progress(player, "cocoon", 1)
    player.sendMessage(u"§c⚡ Паучьи рефлексы §7активированы на 20 сек.")
    player.getWorld().playSound(player.getLocation(), Sound.ENTITY_SPIDER_AMBIENT, 1.0, 1.4)


def ability_senses(player):
    if not check_cd(player, "senses", u"«Паучьи сенсоры»"):
        return
    dur = 10 * 20
    r = 25.0
    world = player.getWorld()
    loc = player.getLocation()
    marked = 0
    for e in world.getNearbyEntities(loc, r, r, r):
        if isinstance(e, LivingEntity) and e != player:
            e.addPotionEffect(PotionEffect(E_GLOWING, dur, 0, False, False, True))
            marked += 1
    set_cd(player, "senses", CD_SENSES)
    player.sendMessage(u"§c⚡ Паучьи сенсоры §7— подсвечено §f%d§7 целей на 10 сек." % marked)
    world.playSound(loc, Sound.ENTITY_ENDERMAN_STARE, 0.8, 1.6)

    # Отложенный дебафф слепоты.
    def apply_blind():
        if player.isOnline():
            add_effect(player, E_BLINDNESS, 5 * 20, 0)
            player.sendMessage(u"§8Сенсоры перегружены — §7слепота 5 сек.")
    scheduler.runTaskLater(apply_blind, dur)


def ability_jump(player):
    if not check_cd(player, "jump", u"«Паучий прыжок»"):
        return
    d = player.getLocation().getDirection()
    # Y ≈ 1.6 даёт высоту ~14–15 блоков.
    vel = Vector(d.getX() * 0.85, 1.6, d.getZ() * 0.85)
    player.setVelocity(vel)
    player.setFallDistance(0.0)
    # Гасим fall damage на всём протяжении дуги.
    for t in (10, 20, 30, 40, 60, 80, 100):
        scheduler.runTaskLater(lambda p=player: (p.isOnline() and p.setFallDistance(0.0)), t)
    set_cd(player, "jump", CD_JUMP)
    player.sendMessage(u"§c⚡ Паучий прыжок!")
    player.getWorld().playSound(player.getLocation(), Sound.ENTITY_ENDER_DRAGON_FLAP, 0.7, 1.8)


def ability_ultimate(player):
    if not check_cd(player, "ult", u"«Паутинный цветок»"):
        return
    set_cd(player, "ult", CD_ULT)
    u = uid(player)
    ultimate_lock.add(u)
    world = player.getWorld()

    player.sendMessage(u"§c§l✦ Паутинный цветок! §r§7— 6 сек. паралича воздуха.")
    player.setVelocity(Vector(0.0, 1.0, 0.0))
    world.playSound(player.getLocation(), Sound.ENTITY_WITHER_SPAWN, 0.7, 1.4)

    # Замораживаем в воздухе (без гравитации) через 8 тиков — успевает подпрыгнуть.
    def freeze_air():
        if player.isOnline() and u in ultimate_lock:
            player.setGravity(False)
            player.setVelocity(Vector(0.0, 0.0, 0.0))
    scheduler.runTaskLater(freeze_air, 8)

    # Одномоментный "выстрел" паутины во все стороны + урон.
    def unleash():
        if not player.isOnline():
            return
        c = player.getLocation()
        world.spawnParticle(Particle.EXPLOSION, c, 5, 2.0, 1.0, 2.0)
        world.spawnParticle(Particle.CLOUD, c, 80, 6.0, 2.0, 6.0, 0.02)
        world.playSound(c, Sound.ENTITY_GENERIC_EXPLODE, 1.0, 0.5)
        for e in world.getNearbyEntities(c, 10.0, 6.0, 10.0):
            if isinstance(e, LivingEntity) and e != player:
                e.damage(3.0, player)
                place_web_pillar(e.getLocation())
    scheduler.runTaskLater(unleash, 12)

    # Периодические частицы вокруг игрока.
    def tick_particles(state=[0]):
        if not player.isOnline() or u not in ultimate_lock:
            return
        l = player.getLocation()
        world.spawnParticle(Particle.END_ROD, l, 20, 1.5, 1.0, 1.5, 0.03)
        state[0] += 5
        if state[0] < 6 * 20:
            scheduler.runTaskLater(tick_particles, 5)
    scheduler.runTaskLater(tick_particles, 5)

    # Финал — возврат гравитации + дебафф.
    def finish():
        ultimate_lock.discard(u)
        if player.isOnline():
            player.setGravity(True)
            player.setFallDistance(0.0)
            add_effect(player, E_SLOWNESS, 5 * 20, 1)
            player.sendMessage(u"§8Ультимейт истощил тело — §7Замедление II на 5 сек.")
    scheduler.runTaskLater(finish, 6 * 20)


# =============================================================================
#  КВЕСТОВЫЕ СПОСОБНОСТИ
# =============================================================================

def _deal_pure_damage(target, amount, attacker):
    """Небольшой истинный урон без повторного прохождения через броню."""
    if not isinstance(target, LivingEntity) or target.isDead(): return
    hp = max(0.0, target.getHealth() - float(amount))
    if hp <= 0.0:
        try: target.damage(target.getMaxHealth() * 4.0, attacker)
        except Exception: target.setHealth(0.0)
    else:
        target.setHealth(hp)

def _nearby_living(world, center, radius, owner):
    result = []
    for entity in world.getNearbyEntities(center, radius, radius, radius):
        if not isinstance(entity, LivingEntity): continue
        if owner is not None and entity.getUniqueId().equals(owner.getUniqueId()): continue
        result.append(entity)
    return result

def ability_web_mace(player):
    if not require_quest(player, "mace") or not check_cd(player, "web_mace", u"«Паутинная булава»"): return
    world = player.getWorld()
    anchor = world.spawn(player.getLocation(), ArmorStand)
    anchor.setInvisible(True); anchor.setGravity(False); anchor.setMarker(True); anchor.setSilent(True)
    anchor.getPersistentDataContainer().set(KEY_TEMP_ENTITY, PersistentDataType.BYTE, JByte(1))
    try: anchor.setInvulnerable(True)
    except Exception: pass
    temporary_anchors.append(anchor)
    end = now_tick() + 10 * 20
    last_hits = {}
    state = {"phase": 0.0}
    particle = getattr(Particle, "WHITE_ASH", Particle.CLOUD)
    def tick():
        if now_tick() >= end or not player.isOnline() or not anchor.isValid():
            try: anchor.remove()
            except Exception: pass
            try: temporary_anchors.remove(anchor)
            except Exception: pass
            return
        center = player.getLocation().clone().add(0.0, 1.0, 0.0)
        try: anchor.teleport(center)
        except Exception: pass
        phase = state["phase"]
        for i in range(10):
            angle = phase + (2.0 * math.pi * i / 10.0)
            point = center.clone().add(math.cos(angle) * 3.0, 0.15 * math.sin(angle * 2.0), math.sin(angle) * 3.0)
            world.spawnParticle(particle, point, 1, 0.0, 0.0, 0.0, 0.0)
        state["phase"] = phase + 0.3
        for entity in _nearby_living(world, center, 3.2, player):
            eu = uid(entity)
            if now_tick() >= last_hits.get(eu, 0):
                entity.damage(2.0, player)  # 1 сердце; ниже предложенных 3 HP для PvP-баланса
                last_hits[eu] = now_tick() + 10
        scheduler.runTaskLater(tick, 1)
    tick()
    set_cd(player, "web_mace", CD_MACE)
    player.sendMessage(u"§f§l✦ Паутинная булава §7— орбита активна на 10 сек.")

def _find_look_target(player, max_distance):
    try:
        target = player.getTargetEntity(int(max_distance))
        if isinstance(target, LivingEntity) and not target.equals(player): return target
    except Exception: pass
    eye = player.getEyeLocation(); direction = eye.getDirection().normalize()
    best = None; best_score = 999999.0
    for entity in _nearby_living(player.getWorld(), eye, max_distance, player):
        delta = entity.getLocation().add(0.0, 0.8, 0.0).toVector().subtract(eye.toVector())
        distance = delta.length()
        if distance <= max_distance and distance > 0.01 and delta.normalize().dot(direction) > 0.975 and distance < best_score:
            best = entity; best_score = distance
    return best

def ability_drone(player):
    if not require_quest(player, "drone") or not check_cd(player, "drone", u"«Паучий дрон»"): return
    world = player.getWorld()
    vex = world.spawn(player.getEyeLocation().add(player.getLocation().getDirection()), Vex)
    vex.setCustomName(u"§cПаучий дрон §7[" + player.getName() + u"]")
    vex.setCustomNameVisible(True)
    try:
        attr = vex.getAttribute(Attribute.ATTACK_DAMAGE)
        if attr is not None: attr.setBaseValue(6.0)
    except Exception: pass
    spider_drones[uid(vex)] = uid(player)
    vex.getPersistentDataContainer().set(KEY_TEMP_ENTITY, PersistentDataType.BYTE, JByte(1))
    end = now_tick() + 15 * 20
    def drone_tick():
        if now_tick() >= end or not vex.isValid() or not player.isOnline():
            spider_drones.pop(uid(vex), None)
            if vex.isValid():
                world.spawnParticle(Particle.POOF, vex.getLocation(), 18, 0.4, 0.4, 0.4, 0.02)
                vex.remove()
            return
        best = None; best_d = 40.0 * 40.0
        for entity in _nearby_living(world, vex.getLocation(), 40.0, player):
            if uid(entity) in spider_drones: continue
            d = entity.getLocation().distanceSquared(vex.getLocation())
            if d < best_d: best = entity; best_d = d
        try: vex.setTarget(best)
        except Exception: pass
        scheduler.runTaskLater(drone_tick, 10)
    drone_tick()
    set_cd(player, "drone", CD_DRONE)
    player.sendMessage(u"§d§l✦ Паучий дрон §7призван на 15 секунд.")

def ability_cocoon(player):
    if not require_quest(player, "cocoon") or not check_cd(player, "cocoon", u"«Паучий кокон»"): return
    add_effect(player, E_RESISTANCE, 10 * 20, 3, particles=False)
    add_effect(player, E_SLOWNESS, 10 * 20, 2, particles=False)
    add_effect(player, E_WEAKNESS, 10 * 20, 2, particles=False)
    add_effect(player, E_REGEN, 10 * 20, 1, particles=False)
    base = player.getLocation().getBlock()
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            for dy in (0, 1):
                _spawn_temp_web(base.getRelative(dx, dy, dz), lifetime=10 * 20)
    player.getWorld().playSound(player.getLocation(), Sound.BLOCK_WOOL_PLACE, 1.0, 0.6)
    set_cd(player, "cocoon", CD_COCOON)
    player.sendMessage(u"§7§l✦ Паучий кокон §r§7— защита и восстановление на 10 сек.")

def ability_hurricane(player):
    if not require_quest(player, "hurricane") or not check_cd(player, "hurricane", u"«Паутинный ураган»"): return
    center = player.getLocation(); affected = 0
    for entity in player.getWorld().getNearbyEntities(center, 5.0, 5.0, 5.0):
        if entity.equals(player): continue
        delta = entity.getLocation().toVector().subtract(center.toVector())
        if delta.lengthSquared() < 0.01: delta = player.getLocation().getDirection()
        velocity = delta.normalize().multiply(1.65); velocity.setY(max(0.35, velocity.getY()))
        try: entity.setVelocity(velocity); affected += 1
        except Exception: pass
    if affected: add_quest_progress(player, "hurricane", affected)
    world = player.getWorld()
    world.spawnParticle(Particle.CLOUD, center.add(0, 1, 0), 70, 3.0, 1.0, 3.0, 0.08)
    world.playSound(center, Sound.ENTITY_GENERIC_EXPLODE, 0.9, 1.4)
    set_cd(player, "hurricane", CD_HURRICANE)

def ability_bounce(player):
    if not require_quest(player, "bounce") or not check_cd(player, "bounce", u"«Паучий отскок»"): return
    if player.isOnGround() or player.isInWater() or player.isInLava():
        player.sendMessage(u"§cОтскок доступен только в воздухе, вне воды и лавы.")
        return
    look = player.getEyeLocation().getDirection().normalize()
    velocity = look.multiply(-1.8)
    if velocity.getY() < 0.35: velocity.setY(0.55)
    if look.getY() < -0.55: velocity.setY(1.35)
    player.setVelocity(velocity); player.setFallDistance(0.0)
    player.getWorld().spawnParticle(Particle.CLOUD, player.getLocation(), 22, 0.4, 0.4, 0.4, 0.05)
    set_cd(player, "bounce", CD_BOUNCE)

def start_gravity_well(owner, center):
    end = now_tick() + 12 * 20
    state = {"phase": 0.0}
    world = center.getWorld()
    anchor = world.spawn(center, ArmorStand)
    anchor.setInvisible(True); anchor.setGravity(False); anchor.setMarker(True); anchor.setSilent(True)
    anchor.getPersistentDataContainer().set(KEY_TEMP_ENTITY, PersistentDataType.BYTE, JByte(1))
    try: anchor.setInvulnerable(True)
    except Exception: pass
    temporary_anchors.append(anchor)
    def tick():
        if now_tick() >= end or not owner.isOnline() or not anchor.isValid():
            try: anchor.remove()
            except Exception: pass
            try: temporary_anchors.remove(anchor)
            except Exception: pass
            return
        well_center = anchor.getLocation()
        for entity in _nearby_living(world, well_center, 5.0, owner):
            add_effect(entity, E_LEVITATION, 30, 1, particles=False)
            add_effect(entity, E_SLOWNESS, 30, 2, particles=False)
            world.spawnParticle(getattr(Particle, "WHITE_ASH", Particle.CLOUD), entity.getLocation(), 4, 0.3, 0.1, 0.3, 0.0)
        phase = state["phase"]
        for i in range(16):
            a = phase + 2.0 * math.pi * i / 16.0
            p = well_center.clone().add(math.cos(a) * 5.0, 0.15, math.sin(a) * 5.0)
            world.spawnParticle(Particle.WITCH, p, 1, 0.0, 0.0, 0.0, 0.0)
        state["phase"] = phase + 0.25
        scheduler.runTaskLater(tick, 10)
    tick()

def start_web_horizon(owner, center):
    world = center.getWorld(); end = now_tick() + 30
    def pull_tick():
        if now_tick() >= end:
            victims = _nearby_living(world, center, 1.5, owner)
            for entity in victims: _deal_pure_damage(entity, 5.0, owner)
            world.spawnParticle(Particle.DRAGON_BREATH, center, 80,
                                1.5, 1.5, 1.5, 0.1, JFloat(1.0))
            world.spawnParticle(Particle.EXPLOSION, center, 4, 0.4, 0.4, 0.4, 0.0)
            world.playSound(center, Sound.ENTITY_ENDER_DRAGON_GROWL, 1.0, 1.5)
            return
        for entity in _nearby_living(world, center, 5.0, owner):
            delta = center.toVector().subtract(entity.getLocation().toVector())
            if delta.lengthSquared() > 0.01: entity.setVelocity(delta.normalize().multiply(1.25))
            _draw_web_line(world, entity.getLocation().add(0, 1, 0), center, 5)
        scheduler.runTaskLater(pull_tick, 2)
    pull_tick()

def start_web_trap(owner, center):
    """Одноразовая невидимая ловушка; владелец видит слабый маркер."""
    end = now_tick() + 120 * 20
    record = {"owner": uid(owner), "center": center.clone(), "end": end}
    spider_traps.append(record)
    def tick():
        if record not in spider_traps: return
        if now_tick() >= end or not owner.isOnline():
            spider_traps.remove(record)
            return
        try:
            owner.spawnParticle(getattr(Particle, "WHITE_ASH", Particle.CLOUD), center, 8, 0.5, 0.15, 0.5, 0.0)
        except Exception: pass
        for target in center.getWorld().getNearbyPlayers(center, 5.0):
            if target.equals(owner): continue
            delta = center.toVector().subtract(target.getLocation().toVector())
            if delta.lengthSquared() > 0.01:
                target.setVelocity(delta.normalize().multiply(1.1))
            add_effect(target, E_SLOWNESS, 10 * 20, 2, particles=False)
            target.sendMessage(u"§f§lПаутинное шенбяо! §7Вас затянуло в ловушку.")
            spider_traps.remove(record)
            return
        scheduler.runTaskLater(tick, 5)
    tick()

def start_spider_lunge(owner, target):
    start = owner.getLocation().clone(); start_y = start.getY()
    end = now_tick() + 22
    # Урон на маршруте отменяется обработчиком on_damage_by.
    lunge_invulnerable.add(uid(owner))
    def tick():
        if not owner.isOnline() or not target.isValid() or target.isDead() or now_tick() >= end:
            lunge_invulnerable.discard(uid(owner)); owner.setFallDistance(0.0); return
        delta = target.getLocation().add(0.0, 0.6, 0.0).toVector().subtract(owner.getLocation().toVector())
        distance = delta.length()
        _draw_web_line(owner.getWorld(), owner.getEyeLocation(), target.getLocation().add(0, 1, 0), 8)
        if distance <= 1.35:
            travelled = start.distance(owner.getLocation())
            damage = min(8.0, 3.0 + travelled / 4.0)
            if start_y - target.getLocation().getY() > 3.0: damage = min(10.0, damage + 2.0)
            target.damage(damage, owner)
            push = target.getLocation().toVector().subtract(owner.getLocation().toVector())
            if push.lengthSquared() < 0.01: push = owner.getLocation().getDirection()
            push = push.normalize().multiply(1.65); push.setY(0.8)
            target.setVelocity(push)
            owner.setVelocity(push.clone().multiply(-0.28)); owner.setFallDistance(0.0)
            fall_immune_until[uid(owner)] = now_tick() + 40
            owner.getWorld().spawnParticle(Particle.CLOUD, target.getLocation(), 35, 0.6, 0.8, 0.6, 0.08)
            owner.getWorld().playSound(target.getLocation(), Sound.ENTITY_PLAYER_ATTACK_STRONG, 1.0, 0.8)
            lunge_invulnerable.discard(uid(owner))
            return
        owner.setVelocity(delta.normalize().multiply(2.4))
        owner.setFallDistance(0.0)
        scheduler.runTaskLater(tick, 1)
    tick()

def _draw_web_line(world, start, end, steps=8):
    for i in range(1, steps + 1):
        f = float(i) / float(steps)
        p = start.clone().add((end.getX()-start.getX())*f,
                              (end.getY()-start.getY())*f,
                              (end.getZ()-start.getZ())*f)
        world.spawnParticle(getattr(Particle, "WHITE_ASH", Particle.CLOUD), p, 1, 0, 0, 0, 0)


# =============================================================================
#  СТРЕЛЬБА ЭЖЕКТОРА
# =============================================================================

def fire_ejector(player, mode):
    if not wearing_mask(player):
        player.sendMessage(u"§cДля активации эжектора нужна маска.")
        return
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
    if uid(player) in ultimate_lock:
        return
    quest_key = MODE_QUEST.get(mode)
    if quest_key is not None and not require_quest(player, quest_key):
        return
    # Сначала проверяем личный КД режима, чтобы не сжечь патрон впустую.
    cd_preflight = {
        1:("line",u"«Паутинная нить»"), 2:("web_mace",u"«Паутинная булава»"),
        3:("trap",u"«Паутинное шенбяо»"), 4:("lunge",u"«Паучий выпад»"),
        5:("drone",u"«Паучий дрон»"), 6:("cocoon",u"«Паучий кокон»"),
        7:("hurricane",u"«Паутинный ураган»"), 8:("gravity",u"«Гравиколодец»"),
        9:("horizon",u"«Паутинный горизонт»"), 10:("shock",u"«Шок-Паутина»"),
        11:("fireweb",u"«Огненная паутина»"), 12:("impact",u"«Ударная паутина»")
    }
    if mode in cd_preflight and not check_cd(player, cd_preflight[mode][0], cd_preflight[mode][1]):
        return
    if mode == 4 and _find_look_target(player, 40.0) is None:
        player.sendMessage(u"§cНет цели в прицеле на расстоянии до 40 блоков.")
        return
    # Боевой режим тратит патрон только после успешных preflight-проверок.
    if mode != 0 and not _try_consume_ammo(player, u"эжектора"):
        return

    if   mode == 0: do_web_swing(player)
    elif mode == 1: do_web_line(player)
    elif mode == 2: ability_web_mace(player)
    elif mode == 3:
        if check_cd(player, "trap", u"«Паутинное шенбяо»"):
            launch_web(player, 3, 1.9); set_cd(player, "trap", CD_TRAP)
    elif mode == 4:
        if check_cd(player, "lunge", u"«Паучий выпад»"):
            target = _find_look_target(player, 40.0)
            if target is None:
                player.sendMessage(u"§cНет цели в прицеле на расстоянии до 40 блоков.")
                return
            proj = launch_web(player, 4, 2.0)
            try: proj.setVelocity(target.getLocation().add(0, 0.8, 0).toVector().subtract(proj.getLocation().toVector()).normalize().multiply(2.0))
            except Exception: pass
            set_cd(player, "lunge", CD_LUNGE)
    elif mode == 5: ability_drone(player)
    elif mode == 6: ability_cocoon(player)
    elif mode == 7: ability_hurricane(player)
    elif mode == 8:
        if check_cd(player, "gravity", u"«Гравиколодец»"):
            launch_web(player, 8, 1.7); set_cd(player, "gravity", CD_GRAVITY)
    elif mode == 9:
        if check_cd(player, "horizon", u"«Паутинный горизонт»"):
            launch_web(player, 9, 1.8); set_cd(player, "horizon", CD_HORIZON)
    elif mode == 10: do_web_shock(player, 10)
    elif mode == 11: do_web_fire(player, 11)
    elif mode == 12: do_web_impact(player, 12)


def launch_web(player, mode_id, speed=1.8):
    proj = player.launchProjectile(Snowball)
    try:
        if mode_id == 3:
            proj.setItem(ItemStack(Material.COBWEB, 1))
        elif mode_id in (8, 9):
            proj.setItem(ItemStack(Material.PRISMARINE_SHARD, 1))
    except Exception: pass
    proj.setVelocity(player.getLocation().getDirection().multiply(speed))
    pdc = proj.getPersistentDataContainer()
    pdc.set(KEY_PROJ,  PersistentDataType.INTEGER, mode_id)
    pdc.set(KEY_OWNER, PersistentDataType.STRING,  uid(player))
    # Слегка "паучий" визуал на старте:
    player.getWorld().spawnParticle(
        Particle.ITEM_SNOWBALL,
        proj.getLocation(),
        6, 0.05, 0.05, 0.05, 0.02
    )
    player.getWorld().playSound(player.getLocation(), Sound.ENTITY_SPIDER_STEP, 0.6, 1.9)

    # Тик-функция: рисует белую "паутинную нить" от игрока к текущей точке
    # снаряда. Работает пока snowball жив.
    def _trail_tick(state=[0]):
        try:
            if not proj.isValid() or proj.isDead():
                return
            world = proj.getWorld()
            proj_loc = proj.getLocation()
            # Точка "запястья" игрока: чуть впереди и вниз от глаз.
            try:
                if not player.isOnline():
                    return
                eye = player.getEyeLocation()
                hand_offset = eye.getDirection().clone().multiply(0.3)
                start_loc = eye.clone().add(hand_offset)
                start_loc.setY(start_loc.getY() - 0.2)
            except Exception:
                start_loc = proj_loc.clone()

            # Рисуем 8 частиц линии от start_loc до proj_loc.
            steps = 8
            dx = (proj_loc.getX() - start_loc.getX()) / float(steps)
            dy = (proj_loc.getY() - start_loc.getY()) / float(steps)
            dz = (proj_loc.getZ() - start_loc.getZ()) / float(steps)
            for i in range(1, steps + 1):
                px = start_loc.getX() + dx * i
                py = start_loc.getY() + dy * i
                pz = start_loc.getZ() + dz * i
                point = start_loc.clone()
                point.setX(px); point.setY(py); point.setZ(pz)
                # Белая точечная частица (0-скорость, минимальный размер).
                try:
                    # Particle.DUST_PLUME или DUST — самые "белые/нейтральные".
                    # Используем END_ROD — белая длинная искра.
                    world.spawnParticle(Particle.END_ROD, point, 1, 0.0, 0.0, 0.0, 0.0)
                except Exception:
                    try:
                        world.spawnParticle(Particle.CRIT, point, 1, 0.0, 0.0, 0.0, 0.0)
                    except Exception: pass
            state[0] += 1
            if state[0] < 60:   # максимум ~3 сек, снаряд быстрее упадёт
                scheduler.runTaskLater(_trail_tick, 1)
        except Exception:
            pass

    scheduler.runTaskLater(_trail_tick, 1)
    return proj


def do_web_swing(player):
    if uid(player) in swing_active:
        player.sendMessage(u"§cПаутина ещё в полёте.")
        return
    if not check_cd(player, "swing", u"полёта"):
        return
    launch_web(player, 0, speed=2.8)
    swing_active.add(uid(player))
    set_cd(player, "swing", CD_SWING)

def do_web_line(player):
    if not check_cd(player, "line", u"«Паутинная нить»"):
        return
    launch_web(player, 1, 2.2)
    set_cd(player, "line", CD_LINE)

def do_web_ball(player):
    if not check_cd(player, "ball", u"«Паутинный шар»"):
        return
    launch_web(player, 2, 1.8)
    set_cd(player, "ball", CD_BALL)

def do_web_impact(player, projectile_mode=3):
    if not check_cd(player, "impact", u"«Ударная паутина»"):
        return
    launch_web(player, projectile_mode, 2.4)
    set_cd(player, "impact", CD_IMPACT)

def do_web_grenade(player):
    if not check_cd(player, "grenade", u"«Паутинная граната»"):
        return
    launch_web(player, 4, 1.6)
    set_cd(player, "grenade", CD_GRENADE)

def do_web_shock(player, projectile_mode=5):
    if not check_cd(player, "shock", u"«Шок-Паутина»"):
        return
    launch_web(player, projectile_mode, 2.0)
    set_cd(player, "shock", CD_SHOCK)

def do_web_fire(player, projectile_mode=6):
    if not check_cd(player, "fireweb", u"«Огненная паутина»"):
        return
    launch_web(player, projectile_mode, 2.0)
    set_cd(player, "fireweb", CD_FIREWEB)


# =============================================================================
#  МЕХАНИКИ ПРИТЯЖЕНИЯ / БЛОКОВ / ЗАМОРОЗКИ
# =============================================================================

def _reset_fall(player):
    if player.isOnline():
        player.setFallDistance(0.0)

def pull_shooter_to(player, target_loc):
    """Тянет самого стрелка к точке (полёт на паутине)."""
    from_loc = player.getLocation()
    dv = target_loc.toVector().subtract(from_loc.toVector())
    dist = dv.length()
    if dist < 0.01:
        return
    dv = dv.normalize()
    speed = 0.4 + min(2.4, dist * 0.28)
    vel = dv.multiply(speed)
    if vel.getY() < 0.35:
        vel.setY(0.45)
    player.setVelocity(vel)
    player.setFallDistance(0.0)
    for t in (10, 20, 30, 40, 60, 80):
        scheduler.runTaskLater(lambda p=player: _reset_fall(p), t)


def pull_target_to(target, dest_loc):
    """Тянет цель к стрелку (паутинная нить)."""
    dv = dest_loc.toVector().subtract(target.getLocation().toVector())
    if dv.lengthSquared() < 0.01:
        return
    dist = dv.length()
    dv = dv.normalize()
    speed = 0.35 + min(2.0, dist * 0.24)
    vel = dv.multiply(speed)
    if vel.getY() < 0.3:
        vel.setY(0.35)
    target.setVelocity(vel)
    if isinstance(target, Player):
        target.setFallDistance(0.0)


def _is_replaceable(block):
    m = block.getType()
    return m.isAir() or m == Material.WATER or m == Material.SHORT_GRASS or m == Material.TALL_GRASS

# Реестр всех временных паутин, заспавненных скриптом.
# Ключ — строка "world,x,y,z", значение — tick времени спавна (не используется, но пригодится для отладки).
web_blocks   = {}
WEB_LIFETIME = 10 * 20   # увеличено вдвое: было 5 секунд

def _block_key(block):
    l = block.getLocation()
    return u"%s,%d,%d,%d" % (l.getWorld().getName(), l.getBlockX(), l.getBlockY(), l.getBlockZ())

def _spawn_temp_web(block, lifetime=None):
    """Ставит временную паутину и затем возвращает исходный BlockData."""
    if not _is_replaceable(block):
        return
    old_data = block.getBlockData().clone()
    block.setType(Material.COBWEB)
    key = _block_key(block)
    web_blocks[key] = {"spawn": now_tick(), "old": old_data}

    def remove():
        # Удаляем только если это по-прежнему наша паутина.
        cur = block.getType()
        if cur == Material.COBWEB and key in web_blocks:
            try: block.setBlockData(web_blocks[key]["old"], False)
            except Exception: block.setType(Material.AIR)
        web_blocks.pop(key, None)
    scheduler.runTaskLater(remove, int(lifetime or WEB_LIFETIME))

def place_web_single(loc):
    _spawn_temp_web(loc.getBlock())

def place_web_under(entity_loc):
    _spawn_temp_web(entity_loc.getBlock())

def place_web_pillar(loc):
    base = loc.getBlock()
    for dy in (0, 1):
        _spawn_temp_web(base.getRelative(0, dy, 0))


def apply_freeze(entity, duration_ticks):
    """Держит entity в состоянии frozen нужное время, "подкачивая" freeze ticks."""
    if not isinstance(entity, LivingEntity):
        return
    max_freeze = entity.getMaxFreezeTicks()
    state = {"left": duration_ticks}
    def tick():
        if not entity.isValid() or entity.isDead():
            return
        if state["left"] <= 0:
            return
        entity.setFreezeTicks(max_freeze + 40)
        state["left"] -= 4
        scheduler.runTaskLater(tick, 4)
    tick()


# =============================================================================
#  ОБРАБОТКА ПОПАДАНИЯ СНАРЯДА
# =============================================================================

def _get_shooter(pdc):
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING):
        return None
    try:
        return Bukkit.getPlayer(JUUID.fromString(pdc.get(KEY_OWNER, PersistentDataType.STRING)))
    except:
        return None


def _find_nearby_target(world, loc, shooter, radius=HIT_RADIUS):
    """Толстый хитбокс: если снаряд попал в блок рядом с целью — ищем
    ближайшего LivingEntity в кубе (radius x radius x radius) вокруг точки.
    Не считаем самого стрелка."""
    try:
        candidates = world.getNearbyEntities(loc, radius, radius, radius)
    except Exception:
        return None
    best = None
    best_dist_sq = 999.0
    for e in candidates:
        if not isinstance(e, LivingEntity): continue
        if shooter is not None and e.equals(shooter): continue
        try:
            d = e.getLocation().distanceSquared(loc)
        except Exception:
            continue
        if d < best_dist_sq:
            best_dist_sq = d
            best = e
    return best


def on_proj_hit(event):
    proj = event.getEntity()
    if not isinstance(proj, Snowball):
        return
    pdc = proj.getPersistentDataContainer()
    if not pdc.has(KEY_PROJ, PersistentDataType.INTEGER):
        return

    mode        = pdc.get(KEY_PROJ, PersistentDataType.INTEGER)
    shooter     = _get_shooter(pdc)
    hit_entity  = event.getHitEntity()
    hit_block   = event.getHitBlock()
    loc         = proj.getLocation()
    world       = proj.getWorld()

    # Полёт на паутине: сбрасываем "занят" в любом случае.
    if mode == 0:
        if shooter is not None:
            swing_active.discard(uid(shooter))
        if shooter is not None and hit_block is not None:
            target = hit_block.getLocation().add(0.5, 0.5, 0.5)
            pull_shooter_to(shooter, target)
            world.spawnParticle(Particle.CRIT, target, 15, 0.3, 0.3, 0.3, 0.05)
            world.playSound(target, Sound.BLOCK_LADDER_STEP, 0.8, 1.7)
        return

    # Стрелок нужен для боевых режимов.
    if shooter is None:
        return

    # ТОЛСТЫЙ ХИТБОКС: если снаряд попал в блок вплотную к цели, но прямого
    # entity-хита не было — ищем ближайшего LivingEntity в кубе HIT_RADIUS.
    if hit_entity is None:
        found = _find_nearby_target(world, loc, shooter)
        if found is not None:
            hit_entity = found

    if mode == 1:
        # Паутинная нить: тянем противника к стрелку.
        if isinstance(hit_entity, LivingEntity) and hit_entity != shooter:
            pull_target_to(hit_entity, shooter.getLocation())
            add_quest_progress(shooter, "bounce", 1)
            world.spawnParticle(Particle.CLOUD, hit_entity.getLocation(), 20, 0.4, 0.6, 0.4)
            world.playSound(hit_entity.getLocation(), Sound.ENTITY_SPIDER_STEP, 0.9, 1.3)

    elif mode == 2:
        # Паутинный шар: замедление 3 сек + блок паутины в точке.
        if isinstance(hit_entity, LivingEntity) and hit_entity != shooter:
            add_effect(hit_entity, E_SLOWNESS, 3 * 20, 1)
            place_web_single(hit_entity.getLocation())
        else:
            place_web_single(loc)
        world.playSound(loc, Sound.BLOCK_WOOL_HIT, 1.0, 1.0)

    elif mode == 3:
        # Паутинное шенбяо: точка столкновения становится ловушкой.
        center = hit_entity.getLocation() if hit_entity is not None else loc
        start_web_trap(shooter, center)
        world.playSound(center, Sound.BLOCK_TRIPWIRE_ATTACH, 1.0, 0.8)

    elif mode == 4:
        # Снаряд нашёл цель — Паук начинает управляемый быстрый рывок.
        if isinstance(hit_entity, LivingEntity) and hit_entity != shooter:
            start_spider_lunge(shooter, hit_entity)
        else:
            shooter.sendMessage(u"§7Паучий выпад не зацепил цель.")

    elif mode == 12:
        # Ударная паутина: базовый откид, которым открывается Ураган.
        if isinstance(hit_entity, LivingEntity) and hit_entity != shooter:
            hit_entity.damage(2.0, shooter)
            dv = hit_entity.getLocation().toVector().subtract(shooter.getLocation().toVector())
            if dv.lengthSquared() < 0.01:
                dv = shooter.getLocation().getDirection()
            dv = dv.normalize()
            dv.setY(0.4)
            hit_entity.setVelocity(dv.multiply(1.6))
            add_quest_progress(shooter, "hurricane", 1)
            world.spawnParticle(Particle.CRIT, hit_entity.getLocation(), 20, 0.4, 0.5, 0.4)
            world.playSound(hit_entity.getLocation(), Sound.ENTITY_PLAYER_ATTACK_STRONG, 1.0, 0.9)

    elif mode == 14:
        # Паутинная граната: паутина под всеми живыми в радиусе 5 (кроме самого стрелка).
        center = hit_entity.getLocation() if hit_entity is not None else loc
        world.spawnParticle(Particle.CLOUD, center, 60, 3.0, 1.0, 3.0, 0.02)
        world.playSound(center, Sound.ENTITY_SNOWBALL_THROW, 1.2, 0.7)
        affected = 0
        for e in world.getNearbyEntities(center, 5.0, 4.0, 5.0):
            if not isinstance(e, LivingEntity):
                continue
            if e.getUniqueId().equals(shooter.getUniqueId()):
                continue
            place_web_under(e.getLocation())
            affected += 1
        # Если никого не задело — ставим одиночную паутину в точке взрыва,
        # чтобы способность имела визуальный эффект даже "в молоко".
        if affected == 0:
            place_web_single(center)

    elif mode == 10:
        # Шок-Паутина: заморозка 6 сек.
        if isinstance(hit_entity, LivingEntity) and hit_entity != shooter:
            apply_freeze(hit_entity, 6 * 20)
            add_effect(hit_entity, E_SLOWNESS, 6 * 20, 4)   # чтобы визуально стоял
            world.spawnParticle(Particle.SNOWFLAKE, hit_entity.getLocation(), 40, 0.6, 1.0, 0.6, 0.02)
            world.playSound(hit_entity.getLocation(), Sound.BLOCK_GLASS_BREAK, 1.0, 1.5)

    elif mode == 11:
        # Огненная паутина: поджиг 8 сек + вспышка.
        if isinstance(hit_entity, LivingEntity) and hit_entity != shooter:
            hit_entity.setFireTicks(8 * 20)
            world.spawnParticle(Particle.FLAME, hit_entity.getLocation(), 30, 0.4, 0.6, 0.4, 0.03)
        else:
            world.spawnParticle(Particle.FLAME, loc, 30, 0.6, 0.6, 0.6, 0.05)
        world.playSound(loc, Sound.ITEM_FIRECHARGE_USE, 1.0, 1.2)

    elif mode == 8:
        center = hit_entity.getLocation() if hit_entity is not None else loc
        start_gravity_well(shooter, center)
        world.playSound(center, Sound.BLOCK_BEACON_ACTIVATE, 1.0, 0.55)

    elif mode == 9:
        center = hit_entity.getLocation() if hit_entity is not None else loc
        start_web_horizon(shooter, center)


# =============================================================================
#  СЛУШАТЕЛИ
# =============================================================================

def _remember_tripwire_pulse(location, player=None):
    if location is None or location.getWorld() is None:
        return
    tick = now_tick()
    cutoff = tick - 20
    recent_tripwire_pulses[:] = [
        pulse for pulse in recent_tripwire_pulses
        if int(pulse.get("tick", 0)) >= cutoff
    ]
    # PlayerInteractEvent and BlockRedstoneEvent can describe the same press.
    # Merge nearby records so one physical activation cannot count twice.
    for pulse in recent_tripwire_pulses:
        old = pulse.get("location")
        if old is None or old.getWorld() != location.getWorld():
            continue
        if tick - int(pulse.get("tick", 0)) <= 4 and old.distanceSquared(location) <= 64.0:
            pulse["tick"] = tick
            if player is not None:
                pulse["player_uuid"] = uid(player)
            return
    recent_tripwire_pulses.append({
        "location": location.clone(), "tick": tick,
        "player_uuid": uid(player) if player is not None else None
    })


def on_tripwire_redstone(event):
    block = event.getBlock()
    if block.getType() not in (Material.TRIPWIRE, Material.TRIPWIRE_HOOK):
        return
    if event.getNewCurrent() > 0 and event.getOldCurrent() <= 0:
        _remember_tripwire_pulse(block.getLocation())


def on_interact(event):
    action = event.getAction()
    if action == Action.PHYSICAL:
        block = event.getClickedBlock()
        if block is not None and block.getType() == Material.TRIPWIRE:
            _remember_tripwire_pulse(block.getLocation(), event.getPlayer())
        return
    if action != Action.RIGHT_CLICK_AIR and action != Action.RIGHT_CLICK_BLOCK:
        return
    # Отсекаем повторный вызов для off-hand.
    if event.getHand() != EquipmentSlot.HAND:
        return
    item = event.getItem()

    # Квест Паутинного горизонта обрабатывается здесь же: PySpigot 0.9.1
    # допускает только один listener одного Event-класса на скрипт.
    player = event.getPlayer()
    block = event.getClickedBlock()
    if (_is_spider_role(player) and block is not None and
            block.getType() == Material.TNT and item is not None and
            item.getType() in (Material.FLINT_AND_STEEL, Material.FIRE_CHARGE)):
        add_quest_progress(player, "horizon", 1)

    if not is_ejector(item):
        return
    event.setCancelled(True)
    fire_ejector(player, get_mode(player))


def on_item_held(event):
    player = event.getPlayer()
    if not player.isSneaking():
        return
    inv = player.getInventory()
    prev = event.getPreviousSlot()
    nxt  = event.getNewSlot()
    if not (is_ejector(inv.getItem(prev)) or is_ejector(inv.getItem(nxt))):
        return

    diff = nxt - prev
    # Компенсация обёртки 8→0 и 0→8.
    if   diff ==  8: direction = -1
    elif diff == -8: direction =  1
    elif diff  >  0: direction =  1
    else:            direction = -1

    new_mode = (get_mode(player) + direction) % (MODE_MAX + 1)
    set_mode(player, new_mode)
    event.setCancelled(True)   # откатывает слот автоматически


def on_drop(event):
    it = event.getItemDrop().getItemStack()
    if is_ejector(it) or is_mask(it):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cЭтот предмет нельзя выбросить.")


def on_block_break(event):
    # Запрещаем ломать нашу временную паутину.
    block = event.getBlock()
    if block.getType() != Material.COBWEB:
        return
    if _block_key(block) in web_blocks:
        event.setCancelled(True)


def on_damage(event):
    ent = event.getEntity()
    if not isinstance(ent, Player):
        return
    if not _is_spider_role(ent):
        return
    if uid(ent) in lunge_invulnerable:
        event.setCancelled(True)
        return
    C = EntityDamageEvent.DamageCause
    cause = event.getCause()
    if cause == C.FALL and now_tick() < fall_immune_until.get(uid(ent), 0):
        event.setCancelled(True); ent.setFallDistance(0.0); return
    if cause == C.FALL:
        rec = fall_tracks.get(uid(ent))
        if rec is not None: rec["invalid"] = True
    if cause == C.FIRE or cause == C.FIRE_TICK or cause == C.LAVA or cause == C.HOT_FLOOR:
        event.setDamage(event.getDamage() * 1.15)

def _free_dodge_directions(player, attacker):
    away = player.getLocation().toVector().subtract(attacker.getLocation().toVector())
    away.setY(0.0)
    if away.lengthSquared() < 0.01: away = player.getLocation().getDirection().multiply(-1.0)
    away.normalize()
    side = Vector(-away.getZ(), 0.0, away.getX())
    candidates = [away, away.clone().multiply(-1.0), side, side.clone().multiply(-1.0)]
    random.shuffle(candidates)
    result = []
    for vec in candidates:
        test = player.getLocation().clone().add(vec.clone().multiply(1.2))
        if test.getBlock().isPassable() and test.clone().add(0, 1, 0).getBlock().isPassable():
            result.append(vec)
    return result

def on_damage_by(event):
    victim = event.getEntity(); damager = event.getDamager()
    # Паучий дрон никогда не атакует хозяина.
    if isinstance(damager, Vex) and uid(damager) in spider_drones and isinstance(victim, Player):
        if spider_drones[uid(damager)] == uid(victim):
            event.setCancelled(True); return
    if isinstance(victim, Player) and _is_spider_role(victim) and wearing_mask(victim):
        if victim.isBlocking(): add_quest_progress(victim, "dodge", 1)
        if quest_unlocked(victim, "dodge") and random.random() < 0.25 and hasattr(damager, "getLocation"):
            directions = _free_dodge_directions(victim, damager)
            if directions:
                event.setCancelled(True)
                velocity = directions[0].multiply(0.6); velocity.setY(0.18)
                victim.setVelocity(velocity)
                victim.getWorld().spawnParticle(Particle.CLOUD, victim.getLocation(), 18, 0.35, 0.5, 0.35, 0.04)
                add_effect(victim, E_DARKNESS, 5, 0, particles=False)
                return
    if isinstance(damager, Player) and _is_spider_role(damager) and isinstance(victim, Player):
        held = damager.getInventory().getItemInMainHand()
        if held is not None and held.getType() == Material.MACE and damager.getFallDistance() >= 3.0:
            add_quest_progress(damager, "lunge", 1)

def _remove_wings(player, start_cooldown=True):
    rec = wings_active.pop(uid(player), None)
    if rec is None: return
    inv = player.getInventory()
    # Удаляем временные элитры даже если игрок успел переложить их из нагрудника.
    for slot in range(inv.getSize()):
        item = inv.getItem(slot)
        if has_pdc_flag(item, KEY_WINGS): inv.setItem(slot, None)
    old_chest = rec.get("old_chest")
    current = inv.getChestplate()
    if old_chest is not None:
        if current is None or current.getType() == Material.AIR:
            inv.setChestplate(old_chest)
        else:
            leftovers = inv.addItem(old_chest)
            for item in leftovers.values(): player.getWorld().dropItemNaturally(player.getLocation(), item)
    if start_cooldown: set_cd(player, "wings", CD_WINGS)
    player.sendActionBar(u"§7Паучьи крылья сложены.")

def on_toggle_sneak(event):
    player = event.getPlayer()
    if not event.isSneaking() or not _is_spider_role(player) or not wearing_mask(player): return
    if player.isOnGround() or uid(player) in wings_active: return
    if not require_quest(player, "wings") or not check_cd(player, "wings", u"«Паучьи крылья»"): return
    old = player.getInventory().getChestplate()
    wings = ItemStack(Material.ELYTRA, 1); meta = wings.getItemMeta()
    meta.setDisplayName(u"§c§lПаучьи крылья"); meta.setUnbreakable(True); set_pdc_flag(meta, KEY_WINGS)
    wings.setItemMeta(meta)
    wings_active[uid(player)] = {"old_chest": old.clone() if old is not None else None}
    player.getInventory().setChestplate(wings)
    try: player.setGliding(True)
    except Exception: pass
    player.sendActionBar(u"§c§lПаучьи крылья раскрыты")

def on_move(event):
    player = event.getPlayer()
    if not _is_spider_role(player): return
    pu = uid(player); y = player.getLocation().getY()
    if not player.isOnGround():
        rec = fall_tracks.get(pu)
        if rec is None: fall_tracks[pu] = {"top": y, "invalid": False}
        elif y > rec["top"]: rec["top"] = y
    else:
        rec = fall_tracks.pop(pu, None)
        if rec is not None and not rec.get("invalid") and rec.get("top", y) - y >= 200.0:
            add_quest_progress(player, "wings", 1)
    if E_LEVITATION is not None and player.hasPotionEffect(E_LEVITATION):
        start_y = levitation_tracks.setdefault(pu, y)
        if y - start_y >= 40.0:
            add_quest_progress(player, "gravity", 40)
            levitation_tracks.pop(pu, None)
    else:
        levitation_tracks.pop(pu, None)
    if pu in wings_active:
        if player.isOnGround() or (not player.isGliding() and player.getVelocity().getY() < -0.5):
            _remove_wings(player, True)

def on_entity_death(event):
    entity = event.getEntity()
    if isinstance(entity, Player) and uid(entity) in wings_active:
        rec = wings_active.pop(uid(entity), None)
        for item in list(event.getDrops()):
            if has_pdc_flag(item, KEY_WINGS): event.getDrops().remove(item)
        old_chest = rec.get("old_chest") if rec else None
        if old_chest is not None: event.getDrops().add(old_chest)
        set_cd(entity, "wings", CD_WINGS)
    if isinstance(entity, Evoker):
        killer = entity.getKiller()
        if killer is not None and _is_spider_role(killer): add_quest_progress(killer, "drone", 1)

def on_dispense(event):
    block = event.getBlock()
    tick = now_tick()
    matched_index = None
    matched_age = 999999
    for index, pulse in enumerate(recent_tripwire_pulses):
        location = pulse.get("location")
        age = tick - int(pulse.get("tick", 0))
        if location is None or age < 0 or age > 20:
            continue
        if location.getWorld() != block.getWorld():
            continue
        dx = abs(location.getBlockX() - block.getX())
        dy = abs(location.getBlockY() - block.getY())
        dz = abs(location.getBlockZ() - block.getZ())
        # A full redstone-dust line carries a signal for 15 blocks, so the
        # tripwire does not have to stand directly beside the dispenser.
        if dx <= 16 and dy <= 8 and dz <= 16 and age < matched_age:
            matched_index = index
            matched_age = age
    if matched_index is None:
        return
    # Consume the pulse before awarding: redstone clocks cannot turn one press
    # of the tripwire into several quest points.
    pulse = recent_tripwire_pulses.pop(matched_index)
    best = None
    pulse_player_uuid = pulse.get("player_uuid")
    if pulse_player_uuid:
        try:
            candidate = Bukkit.getPlayer(JUUID.fromString(pulse_player_uuid))
            if candidate is not None and candidate.isOnline() and _is_spider_role(candidate):
                best = candidate
        except Exception:
            pass
    best_d = 16.0 * 16.0
    if best is None:
        for player in Bukkit.getOnlinePlayers():
            if not _is_spider_role(player) or player.getWorld() != block.getWorld(): continue
            d = player.getLocation().distanceSquared(block.getLocation())
            if d < best_d: best = player; best_d = d
    if best is not None: add_quest_progress(best, "trap", 1)

def on_quit(event):
    player = event.getPlayer()
    if uid(player) in wings_active: _remove_wings(player, False)
    fall_tracks.pop(uid(player), None); levitation_tracks.pop(uid(player), None)


def on_proj_hit_safe(event):
    # Простая защита от того, чтобы исключение в обработчике попадания не всплывало в консоль.
    try:
        on_proj_hit(event)
    except Exception as ex:
        Bukkit.getLogger().warning("[spider_agent] ProjectileHit error: " + str(ex))


# =============================================================================
#  КОМАНДЫ
# =============================================================================

def cmd_spider(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cКоманда доступна только игрокам.")
        return True

    if not _is_spider_role(sender):
        sender.sendMessage(u"§cТолько Агент-Паук может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование: §f/spider <способность>")
        sender.sendMessage(u"§7Доступно: §fрефлексы§7, §fсенсоры§7, §fпрыжок§7, §fотскок§7, §fквесты§7, §fульт§7.")
        return True

    ability = args[0].lower()
    if ability in (u"квест", u"квесты", u"quests"):
        sender.performCommand("quests")
        return True

    if not wearing_mask(sender):
        sender.sendMessage(u"§cДля использования способностей нужна §cМаска Агент-Паука§c.")
        return True
    if is_silenced_by_demiurg(sender):
        sender.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return True
    if uid(sender) in ultimate_lock:
        sender.sendMessage(u"§cВо время ультимейта другие способности недоступны.")
        return True

    if ability in (u"рефлексы", u"reflex", u"reflexes"):
        ability_reflexes(sender)
    elif ability in (u"сенсоры", u"senses", u"sense"):
        ability_senses(sender)
    elif ability in (u"прыжок", u"jump"):
        ability_jump(sender)
    elif ability in (u"отскок", u"bounce"):
        ability_bounce(sender)
    elif ability in (u"ульт", u"ультимейт", u"ult", u"ultimate"):
        ability_ultimate(sender)
    else:
        sender.sendMessage(u"§cНеизвестная способность: §f" + ability)
        sender.sendMessage(u"§7Доступно: §fрефлексы§7, §fсенсоры§7, §fпрыжок§7, §fотскок§7, §fквесты§7, §fульт§7.")
    return True


# =============================================================================
#  РЕГИСТРАЦИЯ
# =============================================================================

cmd_mgr.registerCommand(cmd_spider, "spider")

# ---- Регистрация набора в JVM-глобальном реестре /test-диспетчера ----
# Модуль pyspigot в PySpigot 0.9.1 не шарится между скриптами, поэтому
# используем System.getProperties() — единый Hashtable на всю JVM.
from java.util import HashMap as _JHashMap
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = _JHashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("spider", (kit_entry, u"Агент-Паук (маска + эжектор)"))

# --- Публикация владельцев для admin-скрипта ---
_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = _JHashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("spider", list(SPIDER_OWNERS))

# --- Публикация особых предметов в каталог Зеркала Души Арчера ---
# Фабрика возвращает ЧИСТЫЙ ItemStack I тира — без PDC, без наших флагов,
# без владельца. Всю Арчер-обёртку (санитайзинг, TTL, kind=mirror) делает сам
# скрипт Арчера в _sanitize_mirror(); нам достаточно вернуть материал + внешний вид.
def _spider_mirror_mask(owner_uuid):
    it = ItemStack(Material.LEATHER_HELMET, 1)
    meta = it.getItemMeta()
    meta.setDisplayName(u"§cМаска Агент-Паука")
    if isinstance(meta, LeatherArmorMeta):
        try:
            meta.setColor(Color.fromRGB(178, 34, 34))
        except Exception:
            pass
    it.setItemMeta(meta)
    return it

def _spider_mirror_ejector(owner_uuid):
    it = ItemStack(Material.PRISMARINE_SHARD, 1)
    meta = it.getItemMeta()
    meta.setDisplayName(u"§fЭжектор паутины")
    it.setItemMeta(meta)
    return it

_MIRROR_CATALOG_KEY = "archer.mirror_catalog"
_mirror_cat = _props.get(_MIRROR_CATALOG_KEY)
if _mirror_cat is None:
    _mirror_cat = _JHashMap()
    _props.put(_MIRROR_CATALOG_KEY, _mirror_cat)

def _mirror_publish(entry_id, name, display, factory):
    e = _JHashMap()
    e.put("name", name)
    e.put("display", display)
    e.put("factory", factory)
    _mirror_cat.put(entry_id, e)

_mirror_publish("spider:mask",    u"маска агент-паука", u"§cМаска Агент-Паука", _spider_mirror_mask)
_mirror_publish("spider:ejector", u"эжектор паутины",   u"§fЭжектор паутины",   _spider_mirror_ejector)

listener_mgr.registerListener(on_interact,      PlayerInteractEvent)
listener_mgr.registerListener(on_item_held,     PlayerItemHeldEvent)
listener_mgr.registerListener(on_drop,          PlayerDropItemEvent)
listener_mgr.registerListener(on_damage,        EntityDamageEvent)
listener_mgr.registerListener(on_damage_by,     EntityDamageByEntityEvent)
listener_mgr.registerListener(on_proj_hit_safe, ProjectileHitEvent)
listener_mgr.registerListener(on_block_break,   BlockBreakEvent)
listener_mgr.registerListener(on_toggle_sneak,  PlayerToggleSneakEvent)
listener_mgr.registerListener(on_move,          PlayerMoveEvent)
listener_mgr.registerListener(on_entity_death,  EntityDeathEvent)
listener_mgr.registerListener(on_tripwire_redstone, BlockRedstoneEvent)
listener_mgr.registerListener(on_dispense,      BlockDispenseEvent)
listener_mgr.registerListener(on_quit,          PlayerQuitEvent)

def _cleanup_stale_spider_entities():
    try:
        for world in Bukkit.getWorlds():
            for cls in (ArmorStand, Vex):
                for entity in world.getEntitiesByClass(cls):
                    if entity.getPersistentDataContainer().has(KEY_TEMP_ENTITY, PersistentDataType.BYTE):
                        entity.remove()
    except Exception as ex:
        Bukkit.getLogger().warning("[spider_agent] stale entity cleanup: " + str(ex))

_cleanup_stale_spider_entities()

def stop(script=None):
    # Не оставляем временные крылья/дронов после /pyspigot reload.
    for player_uuid in list(wings_active.keys()):
        try:
            player = Bukkit.getPlayer(JUUID.fromString(player_uuid))
            if player is not None: _remove_wings(player, False)
        except Exception: pass
    for vex_uuid in list(spider_drones.keys()):
        try:
            entity = Bukkit.getEntity(JUUID.fromString(vex_uuid))
            if entity is not None: entity.remove()
        except Exception: pass
    spider_drones.clear(); spider_traps[:] = []; recent_tripwire_pulses[:] = []
    for anchor in list(temporary_anchors):
        try:
            if anchor.isValid(): anchor.remove()
        except Exception: pass
    temporary_anchors[:] = []

Bukkit.getLogger().info("[spider_agent] Agent Spider loaded. Commands: /test spider, /spider <ability>")

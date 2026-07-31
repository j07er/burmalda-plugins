# -*- coding: utf-8 -*-
"""
==============================================================================
  SHANKS (Shardus_Official) — Грифон
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test shanks [1..6]        — выдать саблю нужного уровня
  /shanks <способность>      — способности
      воля | ульт | тир <n>
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, IllegalArgumentException
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, Location
)
from org.bukkit.entity import (
    Player, LivingEntity, AbstractArrow
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent, PlayerRespawnEvent,
    PlayerSwapHandItemsEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, PlayerDeathEvent
)
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.event.block import Action
from org.bukkit.enchantments import Enchantment
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

# DamageSource
_HAS_DAMAGE_API = True
try:
    from org.bukkit.damage import DamageSource, DamageType
except ImportError:
    _HAS_DAMAGE_API = False


# =============================================================================
#  CONSTANTS
# =============================================================================

SHANKS_NAMES    = set([u"shardus_official", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_GRIFFON = NamespacedKey.fromString("shanks:griffon")
KEY_TIER    = NamespacedKey.fromString("shanks:tier")
KEY_OWNER   = NamespacedKey.fromString("shanks:owner")

TIER_MATERIAL = {
    1: Material.WOODEN_SWORD,
    2: Material.STONE_SWORD,
    3: Material.IRON_SWORD,
    4: Material.GOLDEN_SWORD,
    5: Material.DIAMOND_SWORD,
    6: Material.NETHERITE_SWORD,
}
TIER_NAME = {
    1: u"§7§lДеревянный клинок §f§oI",
    2: u"§7§lКаменный клинок §f§oII",
    3: u"§7§lЖелезный клинок §f§oIII",
    4: u"§e§lЗолотой клинок §f§oIV",
    5: u"§b§lАлмазный клинок §f§oV",
    6: u"§4§l§oГрифон §r§4— Легендарная сабля §f§oVI",
}

# Королевская воля (переработка 2026-07-28: CC вместо DPS)
# Радиус 5, урон 1 HP чистого/сек, + Slowness II + Nausea + Darkness.
# Шанкс НЕ получает эффекты в своей ауре.
WILL_RADIUS      = 5.0
WILL_DURATION    = 5 * 20         # 5 секунд
WILL_TICK_PERIOD = 20             # раз в секунду
WILL_TICK_DMG    = 1.0            # 0.5 сердца чистого в секунду
CD_WILL          = 3 * 60 * 20    # 3 минуты

# Воля Наблюдения (новая): активная, подсвечивает всех игроков в радиусе 30.
OBSERVE_DURATION = 10 * 20
OBSERVE_RADIUS   = 30.0
CD_OBSERVE       = 60 * 20        # 1 минута

# Воля Вооружения (новая): следующий удар в течение 10 сек добавляет
# +1.5 HP чистого урона, игнорируя броню и Prot-чары.
ARMAMENT_WINDOW  = 10 * 20
ARMAMENT_BONUS   = 1.5
CD_ARMAMENT      = 30 * 20        # 30 сек

# Атрибуты
DAMAGE_MOD_UUID     = JUUID.fromString("bbbb1111-2222-3333-4444-555566667777")
MAX_HEALTH_MOD_UUID = JUUID.fromString("bbbb1111-2222-3333-4444-888899990000")
ATTACK_SPEED_MOD_UUID = JUUID.fromString("bbbb1111-2222-3333-4444-aaaabbbbcccc")


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k):  return Registry.EFFECT.get(NamespacedKey.minecraft(k))
def _enchant(k): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

E_NAUSEA     = _effect("nausea")
E_DARKNESS   = _effect("darkness")
E_SLOWNESS   = _effect("slowness")
E_GLOWING    = _effect("glowing")

ENC_SHARPNESS  = _enchant("sharpness")
ENC_UNBREAKING = _enchant("unbreaking")
ENC_SWEEPING   = _enchant("sweeping_edge")
ENC_KNOCKBACK  = _enchant("knockback")
ENC_MENDING    = _enchant("mending")


# =============================================================================
#  STATE
# =============================================================================

cooldowns    = {}
will_active  = {}     # uid -> end_tick
armament_active = {}  # uid -> end_tick (Воля Вооружения активна, следующий удар усилен)
observe_active  = {}  # uid -> end_tick (Воля Наблюдения активна)

_pure_dmg_in_progress = set()

# Set для max-hp guard (Paper 1.21 bug с getUniqueId).
_max_hp_applied = set()


# =============================================================================
#  UTILS
# =============================================================================

def uid(e): return e.getUniqueId().toString()
def now_tick(): return long(System.currentTimeMillis() / 50)
def is_shanks(p):
    name = p.getName().lower()
    if name not in SHANKS_NAMES:
        return False
    if name == u"blueredtronce":
        return _test_mode_on()
    return True

def _test_mode_on():
    try:
        v = System.getProperties().get("arena.test_mode")
        return v is None or str(v) == "1"
    except Exception:
        return True
def is_free_cd(p): return p.getName().lower() in FREE_CD_PLAYERS

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

def is_griffon(item):
    if item is None or item.getType() == Material.AIR: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_GRIFFON, PersistentDataType.BYTE)

def get_griffon_tier(item):
    m = item.getItemMeta()
    if m is None: return 0
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER): return 0
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)

def get_griffon_owner(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def can_wield(p, item):
    if not is_shanks(p): return False
    if not is_griffon(item): return False
    o = get_griffon_owner(item)
    return o is None or o == uid(p)

def griffon_anywhere(player):
    for it in player.getInventory().getContents():
        if is_griffon(it): return True
    return False

def current_griffon_tier(player):
    best = 0
    for it in player.getInventory().getContents():
        if is_griffon(it):
            t = get_griffon_tier(it)
            if t > best: best = t
    return best


# =============================================================================
#  ITEM
# =============================================================================

def create_griffon(tier, owner_uuid):
    if tier < 1: tier = 1
    if tier > 6: tier = 6
    it = ItemStack(TIER_MATERIAL[tier], 1)
    m = it.getItemMeta()
    m.setDisplayName(TIER_NAME[tier])
    lore = [
        u"§7Сабля Императора Шанкса.",
        u"§8Уровень: §f" + [u"", u"I", u"II", u"III", u"IV", u"V", u"VI"][tier],
        u"",
        u"§8Только Шанкс может держать этот клинок.",
    ]
    if tier == 6:
        lore.insert(2, u"§4§lГрифон §r§7— Легендарная сабля")
        lore.insert(3, u"§8Урон: §f4.5❤")
    m.setLore(java_list(lore))

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_GRIFFON, PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_TIER,    PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER,   PersistentDataType.STRING,  owner_uuid)

    # Зачарования по тиру.
    if tier == 1:
        if ENC_SHARPNESS: m.addEnchant(ENC_SHARPNESS, 1, True)
    elif tier == 2:
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 1, True)
    elif tier == 3:
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 2, True)
        if ENC_SWEEPING:   m.addEnchant(ENC_SWEEPING, 1, True)
    elif tier == 4:
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 3, True)
        if ENC_SWEEPING:   m.addEnchant(ENC_SWEEPING, 2, True)
    elif tier == 5:
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 4, True)
        if ENC_SWEEPING:   m.addEnchant(ENC_SWEEPING, 3, True)
        if ENC_KNOCKBACK:  m.addEnchant(ENC_KNOCKBACK, 1, True)
    else:  # 6 — Грифон
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 5, True)
        if ENC_SWEEPING:   m.addEnchant(ENC_SWEEPING, 3, True)
        if ENC_KNOCKBACK:  m.addEnchant(ENC_KNOCKBACK, 2, True)
        # Урон 9 HP (4.5 сердца) — vanilla незер = 8 (base 1.0 + default mod +7).
        # Целимся на 9.0. Bukkit-quirk: ЛЮБОЙ модификатор на HAND стирает
        # дефолтные атрибуты материала (см. фикс Криса/Барсика/Михока).
        # Поэтому bonus = target - 1.0 = 8.0.
        try:
            mod_dmg = AttributeModifier(
                DAMAGE_MOD_UUID, "shanks_dmg", 8.0,   # было 1.0 — но дефолт стирается!
                AttributeModifier.Operation.ADD_NUMBER,
                EquipmentSlot.HAND
            )
            m.addAttributeModifier(ATTR_ATTACK_DAMAGE, mod_dmg)
        except Exception as ex:
            Bukkit.getLogger().warning("[shanks] damage attr: " + str(ex))
        # Возвращаем ATTACK_SPEED меча = 1.6/сек (base 4.0 + mod -2.4).
        try:
            mod_spd = AttributeModifier(
                ATTACK_SPEED_MOD_UUID, "shanks_spd", -2.4,
                AttributeModifier.Operation.ADD_NUMBER,
                EquipmentSlot.HAND
            )
            m.addAttributeModifier(ATTR_ATTACK_SPEED, mod_spd)
        except Exception as ex:
            Bukkit.getLogger().warning("[shanks] attack speed attr: " + str(ex))

    # Все тиры сабли неразрушимы.
    m.setUnbreakable(True)

    it.setItemMeta(m)
    return it


def replace_griffon(player, tier):
    inv = player.getInventory()
    contents = inv.getContents()
    for i in range(len(contents)):
        if is_griffon(contents[i]):
            inv.setItem(i, create_griffon(tier, uid(player)))
            return True
    return False


def give_griffon(player, tier=1):
    inv = player.getInventory()
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_griffon(tier, uid(player)))
            player.sendMessage(u"§4§l✦ §rСабля вручена Шанксу. §7Уровень §f" +
                               [u"", u"I", u"II", u"III", u"IV", u"V", u"VI"][tier])
            return
    inv.setItem(0, create_griffon(tier, uid(player)))
    player.sendMessage(u"§4§l✦ §rСабля вручена Шанксу. §7Уровень §f" +
                       [u"", u"I", u"II", u"III", u"IV", u"V", u"VI"][tier])


def kit_entry(player, args_list):
    if not is_shanks(player):
        player.sendMessage(u"§cТолько Шанкс достоин Грифона.")
        return
    tier = 1
    if args_list and len(args_list) >= 1:
        try:
            tier = int(args_list[0])
            if tier < 1 or tier > 6: tier = 1
        except (ValueError, TypeError):
            tier = 1
    give_griffon(player, tier)


# =============================================================================
#  PURE DAMAGE
# =============================================================================

def deal_pure_damage(target, amount, attacker):
    if not isinstance(target, LivingEntity): return
    if _HAS_DAMAGE_API:
        try:
            src = (DamageSource.builder(DamageType.MAGIC)
                   .withDirectEntity(attacker)
                   .withCausingEntity(attacker)
                   .build())
            _pure_dmg_in_progress.add(uid(attacker))
            try:
                target.damage(amount, src)
            finally:
                _pure_dmg_in_progress.discard(uid(attacker))
            return
        except Exception:
            pass
    new_hp = target.getHealth() - amount
    if new_hp <= 0.0:
        try: target.damage(target.getMaxHealth() * 2, attacker)
        except Exception: target.setHealth(0.0)
    else:
        target.setHealth(new_hp)


# =============================================================================
#  ABILITY — КОРОЛЕВСКАЯ ВОЛЯ
# =============================================================================

def ability_will(player):
    if not griffon_anywhere(player):
        player.sendMessage(u"§cДля способности нужен Грифон в инвентаре.")
        return
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
    if not check_cd(player, "will", u"«Королевская воля»"):
        return

    end = now_tick() + WILL_DURATION
    will_active[uid(player)] = end
    world = player.getWorld()

    world.playSound(player.getLocation(), Sound.ENTITY_WITHER_SPAWN, 0.8, 0.6)
    world.playSound(player.getLocation(), Sound.ITEM_TOTEM_USE, 0.8, 0.6)
    player.sendMessage(u"§4§l✦ КОРОЛЕВСКАЯ ВОЛЯ §r§7— 5 сек. Все вокруг ошеломлены.")

    state = {"tick": 0}
    def will_tick():
        if now_tick() >= end:
            will_active.pop(uid(player), None)
            return
        if not player.isOnline():
            will_active.pop(uid(player), None)
            return

        center = player.getLocation()
        r = WILL_RADIUS

        # 1) Кольцо частиц на уровне ног.
        _draw_will_ring(world, center, r)

        # 2) Раз в секунду — CC-эффекты + чистый урон 1 HP.
        if state["tick"] % WILL_TICK_PERIOD == 0:
            for e in world.getNearbyEntities(center, r + 1, r + 2, r + 1):
                if not isinstance(e, LivingEntity): continue
                if e.equals(player): continue
                # Шанкс не задевает сам себя — он сам НЕ в списке.
                # 2D-дистанция по XZ.
                d2 = (e.getLocation().getX() - center.getX())**2 + \
                     (e.getLocation().getZ() - center.getZ())**2
                if d2 > r * r + 4.0:
                    continue
                # Чистый урон 1 HP/сек (0.5 сердца/сек).
                deal_pure_damage(e, WILL_TICK_DMG, player)
                # CC-эффекты: Slowness II + Nausea + Darkness. Обновляются
                # каждую секунду, длительность 25 тиков — с запасом.
                add_effect(e, E_NAUSEA, WILL_TICK_PERIOD + 20, 0)
                if E_SLOWNESS is not None:
                    add_effect(e, E_SLOWNESS, WILL_TICK_PERIOD + 20, 1)   # Slowness II
                if E_DARKNESS is not None:
                    add_effect(e, E_DARKNESS, WILL_TICK_PERIOD + 20, 0)

        # 3) Каждый тик — пинок обратно тех, кто пытается выйти за границу.
        # Сам Шанкс исключён.
        for e in world.getNearbyEntities(center, r + 3, r + 3, r + 3):
            if not isinstance(e, LivingEntity): continue
            if e.equals(player): continue
            eloc = e.getLocation()
            dx = eloc.getX() - center.getX()
            dz = eloc.getZ() - center.getZ()
            dist2d = (dx * dx + dz * dz) ** 0.5
            if dist2d > r - 0.5:
                if dist2d < 0.01: continue
                nx = -dx / dist2d
                nz = -dz / dist2d
                vel = Vector(nx * 0.9, 0.15, nz * 0.9)
                e.setVelocity(vel)

        state["tick"] += 1
        scheduler.runTaskLater(will_tick, 1)

    will_tick()
    set_cd(player, "will", CD_WILL)


# =============================================================================
#  ВОЛЯ НАБЛЮДЕНИЯ (новая, 2026-07-28)
# =============================================================================
#
# Активная. На 10 сек все игроки в радиусе 30 блоков получают Glowing —
# видны сквозь стены, их ники высвечиваются. Сам Шанкс получает Night Vision
# чтобы не терять цели в темноте.
# КД 60 сек.

def ability_observe(player):
    if not griffon_anywhere(player):
        player.sendMessage(u"§cДля способности нужен Грифон в инвентаре.")
        return
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
    if not check_cd(player, "observe", u"«Воля Наблюдения»"):
        return

    end = now_tick() + OBSERVE_DURATION
    observe_active[uid(player)] = end
    world = player.getWorld()

    try:
        world.playSound(player.getLocation(), Sound.ENTITY_ENDER_EYE_LAUNCH, 1.0, 1.4)
    except Exception: pass

    # Ночное зрение самому Шанксу.
    nv = _effect("night_vision")
    if nv is not None:
        add_effect(player, nv, OBSERVE_DURATION, 0)

    def observe_tick():
        if now_tick() >= end:
            observe_active.pop(uid(player), None)
            return
        if not player.isOnline():
            observe_active.pop(uid(player), None)
            return

        center = player.getLocation()
        found_names = []
        try:
            for e in world.getNearbyEntities(center, OBSERVE_RADIUS, OBSERVE_RADIUS, OBSERVE_RADIUS):
                if not isinstance(e, Player): continue
                if e.equals(player): continue
                if E_GLOWING is not None:
                    add_effect(e, E_GLOWING, 30, 0, ambient=True, particles=False)
                try:
                    d = e.getLocation().distance(center)
                except Exception:
                    d = 0.0
                found_names.append((d, e.getName()))
        except Exception:
            pass

        # ActionBar Шанкса: 3 ближайших игрока.
        found_names.sort()
        if found_names:
            display = u"§b§l👁 " + u" §8│ ".join(
                [u"§f" + name + u" §7(%.0fм)" % d for d, name in found_names[:3]]
            )
        else:
            display = u"§b§l👁 §7Никого в радиусе %d бл" % int(OBSERVE_RADIUS)
        try:
            player.sendActionBar(display)
        except Exception: pass

        scheduler.runTaskLater(observe_tick, 10)

    player.sendMessage(u"§b§l✦ ВОЛЯ НАБЛЮДЕНИЯ §r§7— 10 сек. Все игроки в 30 бл подсвечены.")
    observe_tick()
    set_cd(player, "observe", CD_OBSERVE)


# =============================================================================
#  ВОЛЯ ВООРУЖЕНИЯ (новая, 2026-07-28)
# =============================================================================
#
# Активная. На 10 сек следующий удар Грифоном по игроку добавляет
# +1.5 HP чистого урона (игнорирует броню, Prot-чары).
# КД 30 сек.

def ability_armament(player):
    if not griffon_anywhere(player):
        player.sendMessage(u"§cДля способности нужен Грифон в инвентаре.")
        return
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
    if not check_cd(player, "armament", u"«Воля Вооружения»"):
        return

    end = now_tick() + ARMAMENT_WINDOW
    armament_active[uid(player)] = end

    try:
        world = player.getWorld()
        world.playSound(player.getLocation(), Sound.ITEM_ARMOR_EQUIP_NETHERITE, 1.2, 1.1)
        world.spawnParticle(Particle.CRIT, player.getLocation().add(0, 1, 0),
                            25, 0.3, 0.5, 0.3, 0.05)
    except Exception: pass

    player.sendMessage(u"§8§l✦ ВОЛЯ ВООРУЖЕНИЯ §r§7— следующий удар нанесёт §f+%.1f HP §7чистого." % ARMAMENT_BONUS)
    set_cd(player, "armament", CD_ARMAMENT)


def _draw_will_ring(world, center, radius):
    """Красное кольцо частиц на уровне ног игрока."""
    import math
    steps = 36
    y = center.getY() + 0.1
    for i in range(steps):
        a = (2.0 * math.pi * i) / steps
        x = center.getX() + radius * math.cos(a)
        z = center.getZ() + radius * math.sin(a)
        loc = Location(center.getWorld(), x, y, z)
        world.spawnParticle(Particle.DUST, loc, 1, 0.0, 0.0, 0.0, 0.0,
                            _red_dust_options())

_dust_cache = [None]

def _red_dust_options():
    """Красный цвет частиц DUST — из Particle.DustOptions."""
    if _dust_cache[0] is not None:
        return _dust_cache[0]
    try:
        from org.bukkit import Color as BukkitColor
        opt = Particle.DustOptions(BukkitColor.fromRGB(220, 20, 20), 1.2)
        _dust_cache[0] = opt
        return opt
    except Exception:
        return None


# =============================================================================
#  PASSIVES: max HP, off-hand block, damage modifiers
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
            MAX_HEALTH_MOD_UUID, "shanks_max_hp", -4.0,
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


def _clear_offhand(player):
    """Отсутствие левой руки — очищаем off-hand постоянно."""
    inv = player.getInventory()
    off = inv.getItemInOffHand()
    if off is None or off.getType() == Material.AIR:
        return
    # Возвращаем предмет в основной инвентарь.
    inv.setItemInOffHand(ItemStack(Material.AIR))
    leftover = inv.addItem(off)
    if leftover:
        for drop in leftover.values():
            player.getWorld().dropItemNaturally(player.getLocation(), drop)
    player.sendMessage(u"§8Шанкс не пользуется левой рукой.")


def _passives_tick():
    try:
        for pl in Bukkit.getOnlinePlayers():
            if not is_shanks(pl): continue
            _enforce_max_health(pl)
            _clear_offhand(pl)
    except Exception as ex:
        Bukkit.getLogger().warning("[shanks] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


# =============================================================================
#  EVENT HANDLERS
# =============================================================================

def on_swap_hands(event):
    """Блок F (swap main/off hand) — левая рука недоступна."""
    p = event.getPlayer()
    if not is_shanks(p): return
    event.setCancelled(True)


def on_inv_click(event):
    """Блок ручной раскладки в off-hand slot."""
    who = event.getWhoClicked()
    if not isinstance(who, Player): return
    if not is_shanks(who): return
    slot = event.getSlot()
    # Off-hand слот в PlayerInventory = 40.
    if slot == 40:
        event.setCancelled(True)
        who.sendMessage(u"§8Шанкс не пользуется левой рукой.")
        return

    # Блок положить Грифон в контейнер.
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        it = event.getCurrentItem()
        cursor = event.getCursor()
        if is_griffon(it) or is_griffon(cursor):
            event.setCancelled(True)
            who.sendMessage(u"§cГрифон нельзя убрать в контейнер.")


def on_drop(event):
    if is_griffon(event.getItemDrop().getItemStack()):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cГрифон нельзя выбросить.")


def on_damage_by(event):
    dmg = event.getDamager()
    ent = event.getEntity()

    # === Шанкс бьёт: проверяем Волю Вооружения ===
    if isinstance(dmg, Player) and is_shanks(dmg):
        u = uid(dmg)
        end = armament_active.get(u, 0)
        if end > 0 and now_tick() < end and isinstance(ent, LivingEntity) and not ent.equals(dmg):
            # Тратим окно — только один удар.
            armament_active.pop(u, None)
            # Наносим бонус чистым уроном через отложенный тик (после ванильного).
            def _do_armament_bonus():
                try:
                    if not ent.isValid() or ent.isDead(): return
                    deal_pure_damage(ent, ARMAMENT_BONUS, dmg)
                    try:
                        w = ent.getWorld()
                        w.spawnParticle(Particle.CRIT, ent.getLocation().add(0, 1, 0),
                                        15, 0.3, 0.5, 0.3, 0.05)
                        w.playSound(ent.getLocation(), Sound.ITEM_TRIDENT_HIT, 1.0, 0.9)
                    except Exception: pass
                    try:
                        dmg.sendActionBar(u"§8§l✦ ВООРУЖЕНИЕ §r§7— +%.1f HP чистого" % ARMAMENT_BONUS)
                    except Exception: pass
                except Exception: pass
            scheduler.runTaskLater(_do_armament_bonus, 1)

    # === Шанкс получает урон от стрелы/арбалета — +25%. ===
    if isinstance(ent, Player) and is_shanks(ent):
        if uid(ent) in _pure_dmg_in_progress:
            return
        if isinstance(dmg, AbstractArrow):
            shooter = dmg.getShooter()
            # Учитываем только если стрелял не сам Шанкс.
            if not (isinstance(shooter, Player) and shooter.equals(ent)):
                event.setCancelled(False)
                event.setDamage(event.getDamage() * 1.25)


def on_interact(event):
    if event.getHand() != EquipmentSlot.HAND: return
    p = event.getPlayer()
    item = event.getItem()
    if not is_griffon(item): return
    if not can_wield(p, item):
        event.setCancelled(True)
        p.sendMessage(u"§cГрифон отвергает тебя.")


# --- Death / Respawn -----------------------------------------------------

_need_respawn = set()

def on_death(event):
    """
    Soulbound (soulbound.py) сам обрабатывает предметы с PDC-меткой
    'shanks:*' и сохраняет их со ВСЕМИ данными (включая tier).
    Раньше здесь стояло drops.remove(item) — это ломало сохранение тира.
    """
    return



def on_respawn(event):
    """
    Soulbound возвращает предметы через 2 тика. Мы даём ему 40 тиков
    (2 сек) форы, потом проверяем: если предмета всё равно нет — выдаём
    базовый T1. Это защита на случай, если предмет был утерян
    (не через смерть) — например, глюк инвентаря.
    """
    player = event.getPlayer()
    if not is_shanks(player):
        return

    def _check_and_restore():
        try:
            if not player.isOnline():
                return
            # Проверяем есть ли предмет героя в инвентаре после отработки soulbound.
            if not griffon_anywhere(player):
                give_griffon(player, 1)
                player.sendMessage(u"§7[shanks] Комплект восстановлен на I тире (базовый).")
        except Exception:
            pass

    scheduler.runTaskLater(_check_and_restore, 40)



# =============================================================================
#  COMMAND
# =============================================================================

def cmd_shanks(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько для игроков.")
        return True
    if not is_shanks(sender):
        sender.sendMessage(u"§cТолько Шанкс может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/shanks воля §7— Королевская Воля (CC-аура, 5 сек)")
        sender.sendMessage(u"  §f/shanks наблюдение §7— Воля Наблюдения (подсветка игроков, 10 сек)")
        sender.sendMessage(u"  §f/shanks вооружение §7— Воля Вооружения (+1.5 HP чистого)")
        sender.sendMessage(u"  §f/shanks тир <1..6>")
        return True

    sub = args[0].lower()

    if sub in (u"тир", u"tier"):
        if not _test_mode_on():
            sender.sendMessage(u"§cТестовый режим выключен — команда недоступна.")
            return True
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/shanks тир <1..6>")
            return True
        try:
            t = int(args[1])
        except ValueError:
            sender.sendMessage(u"§cТир — число.")
            return True
        if t < 1 or t > 6:
            sender.sendMessage(u"§cТиры: 1..6.")
            return True
        if not replace_griffon(sender, t):
            give_griffon(sender, t)
        else:
            sender.sendMessage(u"§aТир: §f" + [u"", u"I", u"II", u"III", u"IV", u"V", u"VI"][t])
        return True

    if sub in (u"воля", u"королевская", u"will", u"ульт", u"ult"):
        ability_will(sender)
        return True

    if sub in (u"наблюдение", u"наблюдения", u"observe", u"observation"):
        ability_observe(sender)
        return True

    if sub in (u"вооружение", u"вооружения", u"armament", u"буски"):
        ability_armament(sender)
        return True

    sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_shanks, "shanks")

listener_mgr.registerListener(on_swap_hands, PlayerSwapHandItemsEvent)
listener_mgr.registerListener(on_inv_click,  InventoryClickEvent)
listener_mgr.registerListener(on_drop,       PlayerDropItemEvent)
listener_mgr.registerListener(on_damage_by,  EntityDamageByEntityEvent)
listener_mgr.registerListener(on_interact,   PlayerInteractEvent)
listener_mgr.registerListener(on_death,      PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,    PlayerRespawnEvent)

_passives_tick()

# --- Реестры /test, владельцев, тиров, каталога Арчера ---
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("shanks", (kit_entry, u"Шанкс (Грифон [1..6])"))

_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("shanks", list(SHANKS_NAMES))

def _shanks_set_tier(target_player, tier):
    if tier < 1 or tier > 6: return False
    if not replace_griffon(target_player, tier):
        give_griffon(target_player, tier)
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("shanks", _shanks_set_tier)


# --- Публикация функции сброса состояния (используется /admin resethp) ---
def _shanks_reset_state(target_player):
    _max_hp_applied.discard(uid(target_player))
    will_active.pop(uid(target_player), None)
    try:
        attr = target_player.getAttribute(ATTR_MAX_HEALTH)
        for m in list(attr.getModifiers()):
            try:
                attr.removeModifier(m)
            except Exception:
                pass
    except Exception:
        pass

_RESET_KEY = "character_reset_functions"
_reset_reg = _props.get(_RESET_KEY)
if _reset_reg is None:
    _reset_reg = HashMap()
    _props.put(_RESET_KEY, _reset_reg)
_reset_reg.put("shanks", _shanks_reset_state)


def _shanks_mirror_griffon(owner_uuid):
    # I тир — деревянный меч, Sharpness I.
    it = ItemStack(Material.WOODEN_SWORD, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§4Грифон")
    if ENC_SHARPNESS is not None:
        m.addEnchant(ENC_SHARPNESS, 1, True)
    it.setItemMeta(m)
    return it

_MIRROR_CATALOG_KEY = "archer.mirror_catalog"
_mirror_cat = _props.get(_MIRROR_CATALOG_KEY)
if _mirror_cat is None:
    _mirror_cat = HashMap()
    _props.put(_MIRROR_CATALOG_KEY, _mirror_cat)

def _mirror_publish(entry_id, name, display, factory):
    e = HashMap()
    e.put("name", name)
    e.put("display", display)
    e.put("factory", factory)
    _mirror_cat.put(entry_id, e)

_mirror_publish("shanks:griffon", u"грифон", u"§4Грифон", _shanks_mirror_griffon)


Bukkit.getLogger().info("[shanks] Shanks loaded. Commands: /test shanks, /shanks")

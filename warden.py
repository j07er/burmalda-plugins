# -*- coding: utf-8 -*-
"""
==============================================================================
  ВАРДЕН (dni214 / idinahuo)
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test warden [1..3]           — выдать Сердце Скалка нужного тира
  /warden <способность>         — способности
      звук | скалк | размножение | ульт | слепой | улучшить | прогресс
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
    Player, LivingEntity, Warden as WardenEntity, Monster
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent, PlayerRespawnEvent,
    PlayerJoinEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDeathEvent,
    EntityTargetLivingEntityEvent, PlayerDeathEvent
)
from org.bukkit.event.block import (
    Action, BlockBreakEvent
)
from org.bukkit.event.inventory import InventoryClickEvent
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

WARDEN_NAMES    = set([u"dni214", u"idinahuo", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_PICK  = NamespacedKey.fromString("warden:pick")
KEY_TIER  = NamespacedKey.fromString("warden:tier")
KEY_OWNER = NamespacedKey.fromString("warden:owner")

# Тиры
TIER_MATERIAL = {
    1: Material.STONE_PICKAXE,
    2: Material.DIAMOND_PICKAXE,
    3: Material.NETHERITE_PICKAXE,
}
TIER_NAME = {
    1: u"§7§lИсследователь Скалка §f§oI",
    2: u"§b§lГолос Глубин §f§oII",
    3: u"§3§lИстинный Варден §f§oIII",
}

# Прогресс блоков.
T2_BLOCKS = 200
T3_BLOCKS = 1000

# CDs (тики).
CD_SONIC_PER_CHARGE = 30 * 20    # 30 сек на восстановление одного заряда
CD_SCULK_STRIKE     = 20 * 20    # 20 сек
CD_SCULK_SPREAD     = 30 * 20    # 30 сек
CD_ULT              = 120 * 20   # 2 минуты
CD_BLIND_INSTINCT   = 45 * 20    # 45 сек

# Способности
SONIC_MAX_CHARGES   = 3
SONIC_RANGE         = 20.0
SONIC_DAMAGE        = 4.0        # 2 сердца чистого урона

SCULK_STRIKE_BONUS  = 4.0        # +2 сердца физ.
SCULK_STRIKE_SLOW_DUR = 2 * 20

SCULK_SPREAD_R      = 2          # 5×5 = радиус 2
SCULK_SPREAD_DUR    = 12 * 20    # 12 секунд

ULT_DURATION        = 15 * 20    # 15 сек
ULT_AOE_RADIUS      = 6.0

BLIND_INSTINCT_DUR  = 20 * 20    # 20 сек
BLIND_INSTINCT_DMG_MULT = 1.75   # +75% исход. урона

# Атрибуты
MAX_HEALTH_MOD_UUID = JUUID.fromString("dddd1111-2222-3333-4444-555566667777")

# Урон от мобов -15%.
MOB_DMG_REDUCTION = 0.85

# Пассив: каждые 5 минут Blindness 15 сек.
PASSIVE_BLIND_INTERVAL = 5 * 60 * 20
PASSIVE_BLIND_DUR      = 15 * 20

# Пассив: если HP < 20%, Blindness 10 сек.
LOW_HP_BLIND_DUR    = 10 * 20
LOW_HP_COOLDOWN     = 30 * 20    # чтобы не спамило каждый тик


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k): return Registry.EFFECT.get(NamespacedKey.minecraft(k))
def _enchant(k): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

E_SPEED       = _effect("speed")
E_REGEN       = _effect("regeneration")
E_SLOWNESS    = _effect("slowness")
E_BLINDNESS   = _effect("blindness")
E_WEAKNESS    = _effect("weakness")
E_STRENGTH    = _effect("strength")
E_RESIST      = _effect("resistance")
E_GLOWING     = _effect("glowing")

ENC_EFFICIENCY = _enchant("efficiency")
ENC_FORTUNE    = _enchant("fortune")


# =============================================================================
#  STATE
# =============================================================================

cooldowns   = {}

# Прогресс: uid -> {"blocks": int}
progress = {}

# Заряды звукового удара: uid -> {"charges": int, "recharge_end": tick}
sonic_state = {}

# Скалковый удар "зарядка" следующего удара: uid -> end_tick
sculk_strike_ready = {}

# Ультимейт-состояние: uid -> {"end_tick": t, "first_hit_used": bool}
ult_active = {}

# Инстинкт слепого: uid -> end_tick
blind_instinct_active = {}

# Наши блоки скалка: key "world,x,y,z" -> end_tick + previous material
sculk_blocks = {}

# Пассивные таймеры.
last_passive_blind = {}   # uid -> tick следующего Blindness
last_low_hp_blind  = {}   # uid -> tick следующего допустимого срабатывания
_max_hp_applied    = set()

_pure_dmg_in_progress = set()


# =============================================================================
#  UTILS
# =============================================================================

def uid(e): return e.getUniqueId().toString()
def now_tick(): return long(System.currentTimeMillis() / 50)

def _test_mode_on():
    try:
        v = System.getProperties().get("arena.test_mode")
        return v is None or str(v) == "1"
    except Exception:
        return True

def is_warden(p):
    name = p.getName().lower()
    if name not in WARDEN_NAMES:
        return False
    if name == u"blueredtronce":
        return _test_mode_on()
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

def is_pick(item):
    if item is None or item.getType() == Material.AIR: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_PICK, PersistentDataType.BYTE)

def get_pick_tier(item):
    m = item.getItemMeta()
    if m is None: return 0
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER): return 0
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)

def get_pick_owner(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def can_wield(p, item):
    if not is_warden(p): return False
    if not is_pick(item): return False
    o = get_pick_owner(item)
    return o is None or o == uid(p)

def pick_in_hand(player):
    return is_pick(player.getInventory().getItemInMainHand())

def pick_anywhere(player):
    for it in player.getInventory().getContents():
        if is_pick(it): return True
    return False

def current_pick_tier(player):
    best = 0
    for it in player.getInventory().getContents():
        if is_pick(it):
            t = get_pick_tier(it)
            if t > best: best = t
    return best


def _get_progress(player):
    u = uid(player)
    if u not in progress:
        progress[u] = {"blocks": 0}
    return progress[u]


# =============================================================================
#  ITEM
# =============================================================================

def create_pick(tier, owner_uuid):
    if tier < 1: tier = 1
    if tier > 3: tier = 3
    it = ItemStack(TIER_MATERIAL[tier], 1)
    m = it.getItemMeta()
    m.setDisplayName(TIER_NAME[tier])
    lore = [
        u"§7Ритуальная кирка Вардена.",
        u"§8Уровень: §f" + [u"", u"I", u"II", u"III"][tier],
    ]
    if tier == 3:
        lore.append(u"§8Удача II")
    lore.append(u"")
    lore.append(u"§8Только Варден может использовать эту кирку.")
    m.setLore(java_list(lore))
    m.setUnbreakable(True)   # все тиры неразрушимы

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_PICK,  PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_TIER,  PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER, PersistentDataType.STRING,  owner_uuid)

    if tier == 1:
        if ENC_EFFICIENCY: m.addEnchant(ENC_EFFICIENCY, 1, True)
    elif tier == 2:
        if ENC_EFFICIENCY: m.addEnchant(ENC_EFFICIENCY, 3, True)
    else:
        if ENC_EFFICIENCY: m.addEnchant(ENC_EFFICIENCY, 4, True)
        if ENC_FORTUNE:    m.addEnchant(ENC_FORTUNE, 2, True)

    it.setItemMeta(m)
    return it


def replace_pick(player, tier):
    inv = player.getInventory()
    contents = inv.getContents()
    for i in range(len(contents)):
        if is_pick(contents[i]):
            inv.setItem(i, create_pick(tier, uid(player)))
            return True
    return False


def give_pick(player, tier=1):
    inv = player.getInventory()
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_pick(tier, uid(player)))
            player.sendMessage(u"§3§l✦ §rСердце Скалка вручено. §7Уровень §f" +
                               [u"", u"I", u"II", u"III"][tier])
            return
    inv.setItem(0, create_pick(tier, uid(player)))
    player.sendMessage(u"§3§l✦ §rСердце Скалка вручено. §7Уровень §f" +
                       [u"", u"I", u"II", u"III"][tier])


def kit_entry(player, args_list):
    if not is_warden(player):
        player.sendMessage(u"§cТолько Варден достоин Сердца Скалка.")
        return
    tier = 1
    if args_list and len(args_list) >= 1:
        try:
            tier = int(args_list[0])
            if tier < 1 or tier > 3: tier = 1
        except (ValueError, TypeError):
            tier = 1
    give_pick(player, tier)


# =============================================================================
#  UPGRADE
# =============================================================================

def try_upgrade(player):
    cur = current_pick_tier(player)
    if cur >= 3:
        player.sendMessage(u"§7Кирка уже в финальной форме.")
        return
    next_tier = cur + 1
    st = _get_progress(player)
    need = T2_BLOCKS if next_tier == 2 else T3_BLOCKS
    if st["blocks"] < need:
        player.sendMessage(u"§cДобыто §f" + str(st["blocks"]) + u"§c/§f" + str(need) +
                           u" §cблоков.")
        return
    replace_pick(player, next_tier)
    player.sendMessage(u"§3§l✦ Кирка улучшена до Тира " +
                       [u"", u"I", u"II", u"III"][next_tier] + u"§7.")
    player.getWorld().playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)


def show_progress(player):
    st = _get_progress(player)
    cur = current_pick_tier(player)
    player.sendMessage(u"§7Прогресс Вардена (тир §f" + str(cur) + u"§7):")
    player.sendMessage(u"  §f- Блоков добыто: §f" + str(st["blocks"]))
    if cur < 2:
        player.sendMessage(u"  §7Для Тира II: §f" + str(T2_BLOCKS) + u" блоков")
    elif cur < 3:
        player.sendMessage(u"  §7Для Тира III: §f" + str(T3_BLOCKS) + u" блоков")


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
#  ABILITIES
# =============================================================================

def _check_common(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return False
    # По ТЗ: если кирки нет в руке, способности недоступны.
    if not pick_in_hand(player):
        player.sendMessage(u"§cДля способностей нужна §fкирка в руке§c.")
        return False
    return True


# --- 1. Звуковой удар (3 заряда) --------------------------------------------

def _get_sonic_state(player):
    u = uid(player)
    st = sonic_state.get(u)
    if st is None:
        st = {"charges": SONIC_MAX_CHARGES, "recharge_end": 0}
        sonic_state[u] = st
    # Автоматическое восстановление зарядов, если время истекло.
    while (st["charges"] < SONIC_MAX_CHARGES and
           st["recharge_end"] > 0 and
           now_tick() >= st["recharge_end"]):
        st["charges"] += 1
        if st["charges"] < SONIC_MAX_CHARGES:
            st["recharge_end"] += CD_SONIC_PER_CHARGE   # плановая точка
        else:
            st["recharge_end"] = 0
    return st


def ability_sonic(player):
    if not _check_common(player): return
    # Инстинкт слепого блокирует Звуковой удар.
    if uid(player) in blind_instinct_active and blind_instinct_active[uid(player)] > now_tick():
        player.sendMessage(u"§8В Инстинкте слепого Звуковой удар недоступен.")
        return

    st = _get_sonic_state(player)
    if st["charges"] <= 0:
        secs = (st["recharge_end"] - now_tick() + 19) // 20
        player.sendMessage(u"§cНет зарядов. Следующий через §f" + str(secs) + u"§7 сек.")
        return

    # Трата заряда.
    st["charges"] -= 1
    if st["charges"] < SONIC_MAX_CHARGES and st["recharge_end"] == 0:
        st["recharge_end"] = now_tick() + CD_SONIC_PER_CHARGE

    world = player.getWorld()
    eye = player.getEyeLocation()
    dir_v = eye.getDirection().normalize()

    # Луч частиц.
    steps = int(SONIC_RANGE * 3)
    step_v = dir_v.clone().multiply(1.0 / 3.0)
    p = eye.clone()
    hit_uids = set()
    for i in range(steps):
        p.add(step_v)
        world.spawnParticle(Particle.SONIC_BOOM, p, 1, 0.0, 0.0, 0.0, 0.0)
        # Наносим урон всем LivingEntity в радиусе 1.5 от точки луча (проходит сквозь).
        for e in world.getNearbyEntities(p, 1.5, 1.5, 1.5):
            if not isinstance(e, LivingEntity): continue
            if e.equals(player): continue
            if uid(e) in hit_uids: continue
            hit_uids.add(uid(e))
            deal_pure_damage(e, SONIC_DAMAGE, player)

    world.playSound(eye, Sound.ENTITY_WARDEN_SONIC_BOOM, 1.2, 1.0)
    player.sendMessage(u"§3§l✦ Звуковой удар! §7Осталось зарядов: §f" + str(st["charges"]) + u"§7/§f" + str(SONIC_MAX_CHARGES))


# --- 2. Скалковый удар ------------------------------------------------------

def ability_sculk_strike(player):
    if not _check_common(player): return
    if not check_cd(player, "sculk_strike", u"«Скалковый удар»"):
        return
    sculk_strike_ready[uid(player)] = now_tick() + 10 * 20  # 10 секунд на использование
    player.sendMessage(u"§3§l✦ §rСледующий удар киркой усилен.")
    player.getWorld().spawnParticle(Particle.SCULK_SOUL,
                                    player.getLocation().add(0, 1, 0),
                                    20, 0.4, 0.6, 0.4, 0.02)
    set_cd(player, "sculk_strike", CD_SCULK_STRIKE)


# --- 3. Размножение скалка --------------------------------------------------

def _place_temp_sculk(block, ticks_life):
    """Замещает блок на SCULK, сохраняя BlockData оригинала для точного возврата.
       Пропускаем bedrock, спавнеры и жидкости-lava (чтобы не потерять их)."""
    mat = block.getType()
    # Не трогаем неразрушимое / опасное.
    if mat in (Material.BEDROCK, Material.SPAWNER, Material.END_PORTAL,
               Material.END_PORTAL_FRAME, Material.NETHER_PORTAL, Material.LAVA):
        return
    l = block.getLocation()
    key = u"%s,%d,%d,%d" % (l.getWorld().getName(), l.getBlockX(), l.getBlockY(), l.getBlockZ())
    if key in sculk_blocks:
        # Уже наш — не перезаписываем оригинал.
        return

    try:
        block_data_str = block.getBlockData().getAsString()
    except Exception:
        block_data_str = None

    sculk_blocks[key] = {
        "end_tick": now_tick() + ticks_life,
        "prev": mat.name(),
        "data": block_data_str,
        "world": l.getWorld().getName(),
        "x": l.getBlockX(), "y": l.getBlockY(), "z": l.getBlockZ(),
    }
    try:
        block.setType(Material.SCULK)
    except Exception:
        sculk_blocks.pop(key, None)
        return

    def remove():
        rec = sculk_blocks.get(key)
        if rec is None: return
        sculk_blocks.pop(key, None)
        w = Bukkit.getWorld(rec["world"])
        if w is None: return
        b = w.getBlockAt(rec["x"], rec["y"], rec["z"])
        # Только если сейчас там SCULK — не затираем то, что игрок построил взамен.
        if b.getType() != Material.SCULK:
            return
        try:
            if rec.get("data"):
                bd = Bukkit.createBlockData(rec["data"])
                b.setBlockData(bd)
            else:
                mat_r = Material.getMaterial(rec["prev"])
                if mat_r is not None:
                    b.setType(mat_r)
                else:
                    b.setType(Material.AIR)
        except Exception:
            b.setType(Material.AIR)
    scheduler.runTaskLater(remove, ticks_life)


def _is_on_our_sculk(player):
    """True если игрок стоит на нашей заспавненной сculk-плитке."""
    loc = player.getLocation()
    below = loc.getBlock().getRelative(0, -1, 0)
    if below.getType() != Material.SCULK: return False
    l = below.getLocation()
    key = u"%s,%d,%d,%d" % (l.getWorld().getName(), l.getBlockX(), l.getBlockY(), l.getBlockZ())
    return key in sculk_blocks


def ability_sculk_spread(player):
    if not _check_common(player): return
    if not check_cd(player, "sculk_spread", u"«Размножение скалка»"):
        return

    center = player.getLocation()
    world = player.getWorld()
    base = center.getBlock().getRelative(0, -1, 0)

    for dx in range(-SCULK_SPREAD_R, SCULK_SPREAD_R + 1):
        for dz in range(-SCULK_SPREAD_R, SCULK_SPREAD_R + 1):
            b = base.getRelative(dx, 0, dz)
            _place_temp_sculk(b, SCULK_SPREAD_DUR)

    world.spawnParticle(Particle.SCULK_SOUL, center, 60, 2.5, 0.5, 2.5, 0.02)
    world.playSound(center, Sound.BLOCK_SCULK_SPREAD, 1.0, 0.8)
    player.sendMessage(u"§3§l✦ Размножение скалка §r§7— 12 секунд.")
    set_cd(player, "sculk_spread", CD_SCULK_SPREAD)


# --- 4. Ультимейт: Заражение ------------------------------------------------

def ability_ult(player):
    if not _check_common(player): return
    if not check_cd(player, "ult", u"«Заражение»"):
        return

    end = now_tick() + ULT_DURATION
    ult_active[uid(player)] = {"end_tick": end, "first_hit_used": False}

    # AoE эффекты противникам в 6 блоков.
    world = player.getWorld()
    center = player.getLocation()
    for e in world.getNearbyEntities(center, ULT_AOE_RADIUS, ULT_AOE_RADIUS, ULT_AOE_RADIUS):
        if not isinstance(e, LivingEntity): continue
        if e.equals(player): continue
        add_effect(e, E_WEAKNESS, ULT_DURATION, 0)
        add_effect(e, E_SLOWNESS, ULT_DURATION, 0)

    # Себе: Сила I + Сопротивление I.
    add_effect(player, E_STRENGTH, ULT_DURATION, 0)
    add_effect(player, E_RESIST,   ULT_DURATION, 0)

    world.spawnParticle(Particle.SCULK_SOUL, center.add(0, 1, 0), 60, 3.0, 1.5, 3.0, 0.02)
    world.playSound(center, Sound.ENTITY_WARDEN_ROAR, 1.0, 0.7)
    player.sendMessage(u"§3§l✦ ЗАРАЖЕНИЕ! §7— первый удар отметит цель.")
    set_cd(player, "ult", CD_ULT)


# --- 5. Инстинкт слепого ----------------------------------------------------

def ability_blind_instinct(player):
    # Инстинкт слепого НЕ требует кирки в руке (в отличие от других способностей).
    # Обоснование: это внутренняя ментальная способность Вардена, срабатывает
    # автономно, а не через оружие.
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
    if not check_cd(player, "blind", u"«Инстинкт слепого»"):
        return

    end = now_tick() + BLIND_INSTINCT_DUR
    blind_instinct_active[uid(player)] = end

    add_effect(player, E_BLINDNESS, BLIND_INSTINCT_DUR, 0)
    add_effect(player, E_SPEED,     BLIND_INSTINCT_DUR, 0)

    # Игроки в радиусе 5 бл — Glowing.
    world = player.getWorld()
    center = player.getLocation()
    for e in world.getNearbyEntities(center, 5.0, 5.0, 5.0):
        if isinstance(e, Player) and not e.equals(player):
            add_effect(e, E_GLOWING, BLIND_INSTINCT_DUR, 0)

    world.spawnParticle(Particle.SCULK_SOUL, center.add(0, 1, 0), 40, 1.5, 1.0, 1.5, 0.02)
    world.playSound(center, Sound.ENTITY_WARDEN_LISTENING, 1.0, 0.7)
    # Исправлено сообщение: реальный множитель 1.75, а не +20% как было в тексте.
    player.sendMessage(u"§8§l✦ Инстинкт слепого §r§7— 20 сек. §b+75%§7 исходящего урона.")
    set_cd(player, "blind", CD_BLIND_INSTINCT)


# =============================================================================
#  DAMAGE HOOKS
# =============================================================================

def on_damage_by(event):
    dmg = event.getDamager()
    ent = event.getEntity()

    # ==== Варден бьёт ====
    if isinstance(dmg, Player) and is_warden(dmg):
        if uid(dmg) in _pure_dmg_in_progress:
            return
        if isinstance(ent, LivingEntity) and not ent.equals(dmg):
            u = uid(dmg)

            # Скалковый удар: +2 сердца физ + Slowness I на 2 сек.
            if u in sculk_strike_ready and now_tick() < sculk_strike_ready[u]:
                sculk_strike_ready.pop(u, None)
                event.setDamage(event.getDamage() + SCULK_STRIKE_BONUS)
                add_effect(ent, E_SLOWNESS, SCULK_STRIKE_SLOW_DUR, 0)
                dmg.getWorld().spawnParticle(Particle.SCULK_SOUL,
                                              ent.getLocation().add(0, 1, 0),
                                              15, 0.3, 0.5, 0.3, 0.03)

            # Ультимейт: первый удар — Weakness II + Blindness цели.
            if u in ult_active:
                ust = ult_active[u]
                if now_tick() < ust["end_tick"] and not ust["first_hit_used"]:
                    ust["first_hit_used"] = True
                    add_effect(ent, E_WEAKNESS,  5 * 20, 1)
                    add_effect(ent, E_BLINDNESS, 5 * 20, 0)
                    dmg.sendMessage(u"§3§l✦ Метка Заражения наложена!")

            # Инстинкт слепого: +75% исходящего урона.
            # ВАЖНО: setDamage(value) без указания DamageModifier устанавливает
            # BASE damage (по Bukkit-контракту). В Paper 1.21 это работает
            # корректно, но пересчитывает броню/эффекты — для нас это то, что
            # нужно: множитель применяется к базе, а армор считается заново.
            if u in blind_instinct_active and now_tick() < blind_instinct_active[u]:
                try:
                    DM = EntityDamageEvent.DamageModifier
                    base_before = event.getDamage(DM.BASE)
                    new_base = base_before * BLIND_INSTINCT_DMG_MULT
                    event.setDamage(DM.BASE, new_base)
                except Exception:
                    # Fallback на упрощённый setDamage.
                    event.setDamage(event.getDamage() * BLIND_INSTINCT_DMG_MULT)
                # Визуальный фидбек тестеру/атакующему.
                try:
                    dmg.sendActionBar(u"§b§l✦ ИНСТИНКТ §r§7x1.75 §8│ §f%.2f §7HP" % event.getFinalDamage())
                except Exception:
                    pass

    # ==== Варден получает ====
    if isinstance(ent, Player) and is_warden(ent):
        # -15% урона от мобов (только LivingEntity, не Player).
        if isinstance(dmg, LivingEntity) and not isinstance(dmg, Player):
            event.setDamage(event.getDamage() * MOB_DMG_REDUCTION)


# =============================================================================
#  CREATURE TARGETING: обычный Варден не атакует
# =============================================================================

def on_target(event):
    target = event.getTarget()
    if not isinstance(target, Player): return
    if not is_warden(target): return
    ent = event.getEntity()
    if isinstance(ent, WardenEntity):
        # Warden-моб не должен агриться на Вардена-игрока.
        # Даже если EntityTargetLivingEntityEvent не срабатывает — второй слой
        # защиты в тикере ниже (_warden_pacify_tick) чистит anger вручную.
        event.setCancelled(True)
        try:
            event.setTarget(None)
        except Exception:
            pass
        try:
            ent.clearAnger(target)
        except Exception:
            pass


# =============================================================================
#  ТИКЕР: Обнуляем anger Warden-мобов на Warden-игроков
# =============================================================================
# Проблема: EntityTargetLivingEntityEvent не всегда срабатывает для Warden'а,
# потому что его агр идёт через отдельный WardenAngerManager (vibrations).
# Решение: каждую секунду проходим по всем Warden-мобам в радиусе 50 бл
# вокруг игроков-Варденов и чистим anger на них через Warden.clearAnger().

def _warden_pacify_tick():
    try:
        for pl in Bukkit.getOnlinePlayers():
            if not is_warden(pl): continue
            world = pl.getWorld()
            try:
                nearby = world.getNearbyEntities(pl.getLocation(), 50.0, 50.0, 50.0)
            except Exception:
                continue
            for e in nearby:
                if not isinstance(e, WardenEntity): continue
                try:
                    e.clearAnger(pl)
                except Exception:
                    pass
                # Плюс сбрасываем таргет если он на нашего игрока.
                try:
                    target = e.getTarget()
                    if target is not None and target.equals(pl):
                        e.setTarget(None)
                except Exception:
                    pass
    except Exception as ex:
        Bukkit.getLogger().warning("[warden] pacify_tick: " + str(ex))
    scheduler.runTaskLater(_warden_pacify_tick, 20)


scheduler.runTaskLater(_warden_pacify_tick, 40)


# =============================================================================
#  BLOCK BREAK: прогрессия + защита нашего скалка
# =============================================================================

def on_block_break(event):
    b = event.getBlock()

    # Защита временного скалка.
    if b.getType() == Material.SCULK:
        l = b.getLocation()
        key = u"%s,%d,%d,%d" % (l.getWorld().getName(), l.getBlockX(), l.getBlockY(), l.getBlockZ())
        if key in sculk_blocks:
            event.setCancelled(True)
            return

    # Прогресс — только для Вардена, только если есть кирка.
    p = event.getPlayer()
    if not is_warden(p): return
    if not pick_anywhere(p): return
    st = _get_progress(p)
    st["blocks"] += 1
    # Показываем прогресс каждые 25 блоков.
    if st["blocks"] % 25 == 0:
        need = T2_BLOCKS if current_pick_tier(p) < 2 else (T3_BLOCKS if current_pick_tier(p) < 3 else 0)
        if need > 0:
            p.sendActionBar(u"§3§oБлоков: §f" + str(st["blocks"]) + u"§7/§f" + str(need))


# =============================================================================
#  PASSIVES
# =============================================================================

def _enforce_max_health(player):
    """Постоянные +4 HP (2 сердца) через AttributeModifier."""
    u = uid(player)
    if u in _max_hp_applied:
        return
    try:
        attr = player.getAttribute(ATTR_MAX_HEALTH)
        mod = AttributeModifier(
            MAX_HEALTH_MOD_UUID, "warden_max_hp", 4.0,   # +2 сердца
            AttributeModifier.Operation.ADD_NUMBER
        )
        try:
            attr.addModifier(mod)
        except IllegalArgumentException:
            pass
        except Exception:
            pass
        _max_hp_applied.add(u)
    except Exception:
        pass


def _passives_tick():
    try:
        for pl in Bukkit.getOnlinePlayers():
            if not is_warden(pl): continue
            u = uid(pl)

            # +2 сердца макс. HP.
            _enforce_max_health(pl)

            # На скалке (любом) — Speed I + иммун к Slowness.
            below = pl.getLocation().getBlock().getRelative(0, -1, 0)
            if below.getType() == Material.SCULK:
                add_effect(pl, E_SPEED, 40, 0, ambient=True, particles=False)
                # Иммунитет к замедлению = снимаем эффект если есть.
                if E_SLOWNESS is not None and pl.hasPotionEffect(E_SLOWNESS):
                    pl.removePotionEffect(E_SLOWNESS)

            # На НАШЕМ скалке — доп. Regeneration I, а вражеские получают Slowness I.
            if _is_on_our_sculk(pl):
                add_effect(pl, E_REGEN, 40, 0, ambient=True, particles=False)

            # Слепота каждые 5 минут.
            next_blind = last_passive_blind.get(u, now_tick() + PASSIVE_BLIND_INTERVAL)
            last_passive_blind.setdefault(u, next_blind)
            if now_tick() >= next_blind:
                add_effect(pl, E_BLINDNESS, PASSIVE_BLIND_DUR, 0)
                pl.sendActionBar(u"§8Древняя тьма поглощает взор...")
                last_passive_blind[u] = now_tick() + PASSIVE_BLIND_INTERVAL

            # HP < 20% → Blindness 10 сек.
            try:
                max_hp = pl.getAttribute(ATTR_MAX_HEALTH).getValue()
                if pl.getHealth() < max_hp * 0.20:
                    last_low = last_low_hp_blind.get(u, 0)
                    if now_tick() - last_low >= LOW_HP_COOLDOWN:
                        add_effect(pl, E_BLINDNESS, LOW_HP_BLIND_DUR, 0)
                        last_low_hp_blind[u] = now_tick()
            except Exception:
                pass

            # Врагам на любом скалке — Slowness I (только сculk, поставленный нами).
            _apply_sculk_slowness_around(pl)

    except Exception as ex:
        Bukkit.getLogger().warning("[warden] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


def _apply_sculk_slowness_around(warden_player):
    """Всем врагам, стоящим на наших SCULK-блоках рядом — Slowness I."""
    world = warden_player.getWorld()
    for e in world.getNearbyEntities(warden_player.getLocation(), 10.0, 5.0, 10.0):
        if not isinstance(e, LivingEntity): continue
        if e.equals(warden_player): continue
        below = e.getLocation().getBlock().getRelative(0, -1, 0)
        if below.getType() != Material.SCULK: continue
        l = below.getLocation()
        key = u"%s,%d,%d,%d" % (l.getWorld().getName(), l.getBlockX(), l.getBlockY(), l.getBlockZ())
        if key in sculk_blocks:
            add_effect(e, E_SLOWNESS, 40, 0, ambient=True, particles=False)


# =============================================================================
#  FIRST JOIN — Ancient City
# =============================================================================

def on_join(event):
    """При первом входе телепортируем игрока в Древний город (если найден).
    Ищем безопасное место (не в блоках), поднимаемся вверх от Y=-52 пока
    не найдём воздух с воздухом над головой."""
    p = event.getPlayer()
    if not is_warden(p): return
    # Проверка "впервые".
    if p.hasPlayedBefore(): return

    # Ищем ближайший ancient_city — через Paper API.
    world = None
    for w in Bukkit.getWorlds():
        if w.getEnvironment().name() == "NORMAL":
            world = w
            break
    if world is None: return

    def _find_safe_y(loc):
        """Поднимается по Y от loc.getY() ищет 2 подряд AIR-блока с solid снизу.
        Возвращает Location или None если не нашли."""
        try:
            from org.bukkit import Material as _Mat
            bx = loc.getBlockX(); bz = loc.getBlockZ()
            world_ = loc.getWorld()
            # В Ancient City пол на Y=-52. Пробуем от Y=-52 до Y=-40.
            for y in range(-52, -30):
                below = world_.getBlockAt(bx, y - 1, bz)
                feet  = world_.getBlockAt(bx, y,     bz)
                head  = world_.getBlockAt(bx, y + 1, bz)
                if below.getType().isSolid() and not feet.getType().isSolid() and not head.getType().isSolid():
                    # Нашли: ноги в пустоте, голова в пустоте, снизу твёрдое.
                    result = loc.clone()
                    result.setX(bx + 0.5)
                    result.setY(float(y))
                    result.setZ(bz + 0.5)
                    return result
            return None
        except Exception as ex:
            Bukkit.getLogger().warning("[warden] find_safe_y: " + str(ex))
            return None

    def attempt_teleport():
        if not p.isOnline(): return
        try:
            # Paper API: World.locateNearestStructure.
            from org.bukkit.generator.structure import Structure
            structure = Structure.ANCIENT_CITY
            result = world.locateNearestStructure(p.getLocation(), structure, 5000, False)
            if result is None:
                Bukkit.getLogger().info("[warden] No Ancient City found within 5000 blocks.")
                return
            struct_loc = result.getLocation()

            # Ищем безопасное место в самой структуре. Пробуем центр + 8 точек в радиусе.
            safe = None
            candidates = [(0, 0)]
            # 8 точек в радиусе 3 и 6 блоков.
            for dx in (-6, -3, 0, 3, 6):
                for dz in (-6, -3, 0, 3, 6):
                    if dx == 0 and dz == 0: continue
                    candidates.append((dx, dz))
            for dx, dz in candidates:
                try_loc = struct_loc.clone()
                try_loc.setX(struct_loc.getX() + dx)
                try_loc.setZ(struct_loc.getZ() + dz)
                s = _find_safe_y(try_loc)
                if s is not None:
                    safe = s
                    break

            if safe is None:
                # Fallback: телепорт на структуру, но НА ПОВЕРХНОСТЬ мира, а не в глубину.
                # Пусть игрок сам спустится — это безопаснее, чем застрять в блоке.
                Bukkit.getLogger().warning("[warden] No safe spot in Ancient City. Fallback to surface.")
                safe = struct_loc.clone()
                # getHighestBlockYAt даёт Y самой высокой точки.
                try:
                    hy = world.getHighestBlockYAt(int(safe.getX()), int(safe.getZ()))
                    safe.setY(float(hy + 1))
                except Exception:
                    safe.setY(70.0)

            safe.setYaw(p.getLocation().getYaw())
            safe.setPitch(0.0)
            p.teleport(safe)
            p.sendTitle(u"§3§lДревний Город", u"§7Дом Вардена", 10, 60, 20)
            p.sendMessage(u"§3§oТы вернулся домой.")
        except Exception as ex:
            Bukkit.getLogger().warning("[warden] first-join teleport: " + str(ex))

    scheduler.runTaskLater(attempt_teleport, 40)   # 2 сек после входа


# =============================================================================
#  ITEM PROTECTION / DEATH
# =============================================================================

def on_interact(event):
    if event.getHand() != EquipmentSlot.HAND: return
    p = event.getPlayer()
    item = event.getItem()
    if not is_pick(item): return
    if not can_wield(p, item):
        event.setCancelled(True)
        p.sendMessage(u"§cКирка отвергает тебя.")


def on_drop(event):
    if is_pick(event.getItemDrop().getItemStack()):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cКирку нельзя выбросить.")


def on_inv_click(event):
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        it = event.getCurrentItem()
        cursor = event.getCursor()
        if is_pick(it) or is_pick(cursor):
            event.setCancelled(True)
            event.getWhoClicked().sendMessage(u"§cКирку нельзя убрать в контейнер.")


_need_respawn = set()

def on_death(event):
    """
    Soulbound сам сохраняет предмет героя.
    """
    return




def on_respawn(event):
    """
    Проверяем через 40 тиков, вернул ли soulbound предмет.
    """

    player = event.getPlayer()

    if not is_warden(player):
        return

    def _check_and_restore():
        try:
            if not player.isOnline():
                return

            if pick_anywhere(player) is None:
                give_pick(player, 1)
                player.sendMessage(u"§7[warden] Комплект восстановлен.")

        except Exception:
            import traceback
            traceback.print_exc()

    scheduler.runTaskLater(_check_and_restore, 40)




# =============================================================================
#  RESET (для /admin resethp)
# =============================================================================

def _warden_reset_state(target_player):
    u = uid(target_player)
    _max_hp_applied.discard(u)
    sonic_state.pop(u, None)
    sculk_strike_ready.pop(u, None)
    ult_active.pop(u, None)
    blind_instinct_active.pop(u, None)
    last_passive_blind.pop(u, None)
    last_low_hp_blind.pop(u, None)
    try:
        attr = target_player.getAttribute(ATTR_MAX_HEALTH)
        for m in list(attr.getModifiers()):
            try: attr.removeModifier(m)
            except Exception: pass
    except Exception: pass


# =============================================================================
#  COMMAND
# =============================================================================

def cmd_warden(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько для игроков.")
        return True
    if not is_warden(sender):
        sender.sendMessage(u"§cТолько Варден может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/warden <звук|скалк|размножение|ульт|слепой>")
        sender.sendMessage(u"  §f/warden улучшить §7или §fпрогресс§7 / §fтир <n>")
        return True

    sub = args[0].lower()

    if sub in (u"улучшить", u"upgrade"):
        try_upgrade(sender)
        return True

    if sub in (u"прогресс", u"progress"):
        show_progress(sender)
        return True

    if sub in (u"тир", u"tier"):
        if not _test_mode_on():
            sender.sendMessage(u"§cТестовый режим выключен — команда недоступна.")
            return True
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/warden тир <1..3>")
            return True
        try:
            t = int(args[1])
        except ValueError:
            sender.sendMessage(u"§cТир — число.")
            return True
        if t < 1 or t > 3:
            sender.sendMessage(u"§cТиры: 1..3.")
            return True
        if not replace_pick(sender, t):
            give_pick(sender, t)
        else:
            sender.sendMessage(u"§aТир: §f" + [u"", u"I", u"II", u"III"][t])
        return True

    if sub in (u"звук", u"sonic", u"звуковой"):
        ability_sonic(sender)
        return True
    if sub in (u"скалк", u"sculk", u"удар"):
        ability_sculk_strike(sender)
        return True
    if sub in (u"размножение", u"spread", u"расстелить"):
        ability_sculk_spread(sender)
        return True
    if sub in (u"ульт", u"ult", u"заражение"):
        ability_ult(sender)
        return True
    if sub in (u"слепой", u"инстинкт", u"blind"):
        ability_blind_instinct(sender)
        return True

    sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_warden, "warden")

listener_mgr.registerListener(on_interact,   PlayerInteractEvent)
listener_mgr.registerListener(on_drop,       PlayerDropItemEvent)
listener_mgr.registerListener(on_inv_click,  InventoryClickEvent)
listener_mgr.registerListener(on_death,      PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,    PlayerRespawnEvent)
listener_mgr.registerListener(on_damage_by,  EntityDamageByEntityEvent)
listener_mgr.registerListener(on_target,     EntityTargetLivingEntityEvent)
listener_mgr.registerListener(on_block_break, BlockBreakEvent)
listener_mgr.registerListener(on_join,       PlayerJoinEvent)

_passives_tick()

# --- Реестры ---
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("warden", (kit_entry, u"Варден (Сердце Скалка [1..3])"))

_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("warden", list(WARDEN_NAMES))

def _warden_set_tier(target_player, tier):
    if tier < 1 or tier > 3: return False
    if not replace_pick(target_player, tier):
        give_pick(target_player, tier)
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("warden", _warden_set_tier)

_RESET_KEY = "character_reset_functions"
_reset_reg = _props.get(_RESET_KEY)
if _reset_reg is None:
    _reset_reg = HashMap()
    _props.put(_RESET_KEY, _reset_reg)
_reset_reg.put("warden", _warden_reset_state)


# --- Публикация в каталог Зеркала Души Арчера ---
def _warden_mirror_pick(owner_uuid):
    it = ItemStack(Material.STONE_PICKAXE, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§3Сердце Скалка")
    if ENC_EFFICIENCY is not None:
        m.addEnchant(ENC_EFFICIENCY, 1, True)
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

_mirror_publish("warden:pick", u"сердце скалка", u"§3Сердце Скалка", _warden_mirror_pick)


# quest_tracker: публикуем stat-функцию.
def _warden_stat(player, key):
    try:
        u = uid(player)
        st = progress.get(u, {"blocks": 0})
        if key == "blocks": return int(st.get("blocks", 0))
    except Exception: pass
    return 0

try:
    System.getProperties().put("quest_tracker.stat.warden", _warden_stat)
except Exception: pass


Bukkit.getLogger().info("[warden] Warden loaded. Commands: /test warden, /warden")

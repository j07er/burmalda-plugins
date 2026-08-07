# -*- coding: utf-8 -*-
"""
==============================================================================
  ДРАКОН (goldkot)
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test dragon [1..3]           — выдать Око Дракона нужного тира
  /dragon <способность>         — способности
      дыхание | полёт | фаербол | ульт | улучшить | прогресс
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, Float as JFloat, IllegalArgumentException
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, GameMode, Location, Color
)
from org.bukkit.entity import (
    Player, LivingEntity, DragonFireball, EnderCrystal, Fireball, Projectile
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent, PlayerRespawnEvent,
    PlayerItemBreakEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDeathEvent,
    ProjectileHitEvent, PlayerDeathEvent
)
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.event.block import Action, BlockBreakEvent
from org.bukkit.enchantments import Enchantment
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.inventory.meta import LeatherArmorMeta
from org.bukkit.potion import PotionEffect
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
from org.bukkit.persistence import PersistentDataType
from org.bukkit.util import Vector

_HAS_DAMAGE_API = True
try:
    from org.bukkit.damage import DamageSource, DamageType
except ImportError:
    _HAS_DAMAGE_API = False


# =============================================================================
#  CONSTANTS
# =============================================================================

DRAGON_NAMES    = set([u"goldkot", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_EYE   = NamespacedKey.fromString("dragon:eye")
KEY_TIER  = NamespacedKey.fromString("dragon:tier")
KEY_OWNER = NamespacedKey.fromString("dragon:owner")
KEY_FIREBALL = NamespacedKey.fromString("dragon:fireball_marker")

# Тиры: (материал, макс. прочность для отслеживания порога)
TIER_MATERIAL = {
    1: Material.LEATHER_HELMET,      # ванильная прочность 55
    2: Material.IRON_HELMET,         # 165
    3: Material.NETHERITE_HELMET,    # 407
}
TIER_NAME = {
    1: u"§8§lМалое Око §f§oI",
    2: u"§b§lДраконье Око §f§oII",
    3: u"§5§lИстинное Око Дракона §f§oIII",
}

# Пороги прочности для апгрейда.
T2_THRESHOLD_PCT = 20   # II → III при <20% (то есть Тир I → II при <20%)
T3_THRESHOLD_PCT = 10

# CDs (тики)
CD_BREATH       = 20 * 20
CD_FLIGHT       = 45 * 20
CD_FIREBALL_PER_CHARGE = 15 * 20
CD_ULT          = 3 * 60 * 20

# Способности
BREATH_DURATION       = 10 * 20
BREATH_TICK_DAMAGE    = 1.0    # 0.5 сердца
BREATH_RADIUS         = 1.0    # 2×2 → радиус 1
BREATH_LENGTH         = 4      # блоков перед игроком
FLIGHT_DURATION       = 15 * 20
FLIGHT_POST_SPEED     = 15 * 20
FLIGHT_POST_SLOWNESS  = 5 * 20
BLOCK_RESTORE_TICKS   = 30 * 20

FIREBALL_MAX_CHARGES  = 2
FIREBALL_CLOUD_DUR    = 8 * 20
FIREBALL_CLOUD_R      = 1.5    # 3×3 → радиус 1.5

ULT_FIREBALL_INTERVAL = 20     # 1 сек между выстрелами
ULT_FIREBALL_COUNT    = 3
ULT_UP_HEIGHT         = 7      # блоков

# Пассив: урон в воде
WATER_DAMAGE_INTERVAL = 40     # 2 сек
WATER_DAMAGE          = 1.0    # 0.5 сердца

# Пассив: эндер-кристаллы лечат
CRYSTAL_HEAL_RADIUS   = 8.0
CRYSTAL_HEAL          = 1.0    # 0.5 сердца каждые 2 сек
CRYSTAL_HEAL_INTERVAL = 40
CRYSTAL_EXPLOSION_HEAL = 12.0  # 6 сердец при взрыве кристалла рядом
CRYSTAL_EXPLOSION_RADIUS = 10.0

# Пассив: бонус в Энде
END_DAMAGE_MULT = 1.20

# Дебафф: +15% от стрел/арбалетов/трезубцев
PROJECTILE_VULN_MULT = 1.15

# Блоки, которые НЕ ломает Полёт дракона.
PROTECTED_BLOCKS = set([
    Material.CHEST, Material.TRAPPED_CHEST, Material.ENDER_CHEST, Material.BARREL,
    Material.SHULKER_BOX,
    Material.WHITE_SHULKER_BOX, Material.ORANGE_SHULKER_BOX, Material.MAGENTA_SHULKER_BOX,
    Material.LIGHT_BLUE_SHULKER_BOX, Material.YELLOW_SHULKER_BOX, Material.LIME_SHULKER_BOX,
    Material.PINK_SHULKER_BOX, Material.GRAY_SHULKER_BOX, Material.LIGHT_GRAY_SHULKER_BOX,
    Material.CYAN_SHULKER_BOX, Material.PURPLE_SHULKER_BOX, Material.BLUE_SHULKER_BOX,
    Material.BROWN_SHULKER_BOX, Material.GREEN_SHULKER_BOX, Material.RED_SHULKER_BOX,
    Material.BLACK_SHULKER_BOX,
    Material.FURNACE, Material.BLAST_FURNACE, Material.SMOKER,
    Material.HOPPER, Material.DISPENSER, Material.DROPPER,
    Material.BREWING_STAND,
    Material.SPAWNER,
    Material.BEDROCK, Material.OBSIDIAN, Material.CRYING_OBSIDIAN,
    Material.NETHERITE_BLOCK,
    Material.END_PORTAL_FRAME, Material.END_PORTAL, Material.NETHER_PORTAL,
    Material.REINFORCED_DEEPSLATE,
    Material.RESPAWN_ANCHOR,
    Material.BEACON, Material.CONDUIT,
    Material.ANVIL, Material.CHIPPED_ANVIL, Material.DAMAGED_ANVIL,
    Material.ENCHANTING_TABLE, Material.CRAFTING_TABLE,
    Material.LOOM, Material.STONECUTTER, Material.CARTOGRAPHY_TABLE, Material.SMITHING_TABLE,
    Material.LECTERN, Material.JUKEBOX,
    Material.WATER, Material.LAVA,
])


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k): return Registry.EFFECT.get(NamespacedKey.minecraft(k))
def _enchant(k): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

E_WATER_BR   = _effect("water_breathing")
E_CONDUIT    = _effect("conduit_power")
E_SPEED      = _effect("speed")
E_SLOWNESS   = _effect("slowness")

ENC_PROT       = _enchant("protection")
ENC_UNBREAKING = _enchant("unbreaking")
ENC_RESPIRATION = _enchant("respiration")
ENC_AQUA_AFF  = _enchant("aqua_affinity")
ENC_MENDING   = _enchant("mending")
ENC_THORNS    = _enchant("thorns")


# =============================================================================
#  STATE
# =============================================================================

cooldowns    = {}
fireball_state = {}       # uid -> {"charges": int, "recharge_end": tick}
flight_end   = {}         # uid -> end_tick
water_last_dmg   = {}     # uid -> tick последнего урона в воде
crystal_last_heal = {}    # uid -> tick последнего лечения

# Восстановление блоков после полёта.
pending_restore = {}      # key -> {"world","x","y","z","type","data","restore_tick"}
active_flight_broken = {} # uid -> set блоков сломанных этим полётом (для отдельного восстановления)

_max_hp_applied = set()   # (не используется — макс HP не меняем)


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

def is_dragon(p):
    name = p.getName().lower()
    if name not in DRAGON_NAMES:
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

def spawn_dragon_breath(world, location, count,
                        offset_x=0.0, offset_y=0.0, offset_z=0.0,
                        extra=0.0, power=1.0):
    """Paper 1.21.11 требует java.lang.Float как data для DRAGON_BREATH."""
    world.spawnParticle(Particle.DRAGON_BREATH, location, int(count),
                        float(offset_x), float(offset_y), float(offset_z),
                        float(extra), JFloat(float(power)))

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


def is_eye(item):
    if item is None or item.getType() == Material.AIR: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_EYE, PersistentDataType.BYTE)

def get_eye_tier(item):
    m = item.getItemMeta()
    if m is None: return 0
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER): return 0
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)

def get_eye_owner(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def get_worn_eye(player):
    """Возвращает шлем-Око если он надет, иначе None."""
    helmet = player.getInventory().getHelmet()
    if is_eye(helmet):
        return helmet
    return None

def eye_anywhere(player):
    if is_eye(player.getInventory().getHelmet()): return True
    for it in player.getInventory().getContents():
        if is_eye(it): return True
    return False

def current_eye_tier(player):
    best = 0
    if is_eye(player.getInventory().getHelmet()):
        best = get_eye_tier(player.getInventory().getHelmet())
    for it in player.getInventory().getContents():
        if is_eye(it):
            t = get_eye_tier(it)
            if t > best: best = t
    return best


# =============================================================================
#  ITEM
# =============================================================================

def create_eye(tier, owner_uuid):
    if tier < 1: tier = 1
    if tier > 3: tier = 3
    it = ItemStack(TIER_MATERIAL[tier], 1)
    m = it.getItemMeta()
    m.setDisplayName(TIER_NAME[tier])

    # Кожаный тир I — окрашиваем в чёрный.
    if tier == 1 and isinstance(m, LeatherArmorMeta):
        try:
            m.setColor(Color.fromRGB(20, 20, 20))
        except Exception:
            pass

    lore = [
        u"§7Шлем Дракона.",
        u"§8Уровень: §f" + [u"", u"I", u"II", u"III"][tier],
    ]
    lore.append(u"")
    lore.append(u"§8Только Дракон может использовать этот шлем.")
    m.setLore(java_list(lore))

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_EYE,   PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_TIER,  PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER, PersistentDataType.STRING,  owner_uuid)

    if tier == 1:
        if ENC_PROT:        m.addEnchant(ENC_PROT, 1, True)
        if ENC_UNBREAKING:  m.addEnchant(ENC_UNBREAKING, 1, True)
        if ENC_RESPIRATION: m.addEnchant(ENC_RESPIRATION, 1, True)
    elif tier == 2:
        if ENC_PROT:        m.addEnchant(ENC_PROT, 2, True)
        if ENC_UNBREAKING:  m.addEnchant(ENC_UNBREAKING, 2, True)
        if ENC_RESPIRATION: m.addEnchant(ENC_RESPIRATION, 2, True)
        if ENC_AQUA_AFF:    m.addEnchant(ENC_AQUA_AFF, 1, True)
    else:
        if ENC_PROT:        m.addEnchant(ENC_PROT, 4, True)
        if ENC_UNBREAKING:  m.addEnchant(ENC_UNBREAKING, 3, True)
        if ENC_RESPIRATION: m.addEnchant(ENC_RESPIRATION, 3, True)
        if ENC_AQUA_AFF:    m.addEnchant(ENC_AQUA_AFF, 1, True)
        if ENC_MENDING:     m.addEnchant(ENC_MENDING, 1, True)
        if ENC_THORNS:      m.addEnchant(ENC_THORNS, 2, True)

    # Око всех тиров не расходует прочность.
    m.setUnbreakable(True)
    it.setItemMeta(m)
    return it


def replace_eye(player, tier):
    inv = player.getInventory()
    # Если Око на голове.
    if is_eye(inv.getHelmet()):
        inv.setHelmet(create_eye(tier, uid(player)))
        return True
    # Иначе — в общем инвентаре.
    contents = inv.getContents()
    for i in range(len(contents)):
        if is_eye(contents[i]):
            inv.setItem(i, create_eye(tier, uid(player)))
            return True
    return False


def give_eye(player, tier=1):
    inv = player.getInventory()
    # Пытаемся надеть на голову, если слот пуст.
    if inv.getHelmet() is None or inv.getHelmet().getType() == Material.AIR:
        inv.setHelmet(create_eye(tier, uid(player)))
        player.sendMessage(u"§5§l✦ §rОко надето. §7Уровень §f" +
                           [u"", u"I", u"II", u"III"][tier])
        return
    # Иначе в хотбар.
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_eye(tier, uid(player)))
            player.sendMessage(u"§5§l✦ §rОко Дракона выдано. §7Уровень §f" +
                               [u"", u"I", u"II", u"III"][tier])
            return
    inv.setItem(0, create_eye(tier, uid(player)))
    player.sendMessage(u"§5§l✦ §rОко Дракона выдано. §7Уровень §f" +
                       [u"", u"I", u"II", u"III"][tier])


def kit_entry(player, args_list):
    if not is_dragon(player):
        player.sendMessage(u"§cТолько Дракон достоин Ока.")
        return
    tier = 1
    if args_list and len(args_list) >= 1:
        try:
            tier = int(args_list[0])
            if tier < 1 or tier > 3: tier = 1
        except (ValueError, TypeError):
            tier = 1
    give_eye(player, tier)


# =============================================================================
#  UPGRADE (по прочности)
# =============================================================================

def _durability_pct(item):
    """Возвращает процент оставшейся прочности (0..100). Если предмет неразрушим — 100."""
    m = item.getItemMeta()
    if m is None: return 100
    try:
        if m.isUnbreakable(): return 100
    except Exception:
        pass
    try:
        max_dur = item.getType().getMaxDurability()
        if max_dur <= 0: return 100
        # В новом API прочность через Damageable.getDamage().
        damage = m.getDamage() if hasattr(m, "getDamage") else 0
        remain = max_dur - damage
        return int((remain * 100) / max_dur)
    except Exception:
        return 100


def try_upgrade(player):
    # Ищем Око (в приоритете — на голове).
    inv = player.getInventory()
    eye_item = inv.getHelmet() if is_eye(inv.getHelmet()) else None
    if eye_item is None:
        contents = inv.getContents()
        for it in contents:
            if is_eye(it):
                eye_item = it
                break
    if eye_item is None:
        player.sendMessage(u"§cОко не найдено. Надень его для проверки прочности.")
        return

    cur_tier = get_eye_tier(eye_item)
    if cur_tier >= 3:
        player.sendMessage(u"§7Око уже в финальной форме.")
        return

    pct = _durability_pct(eye_item)
    threshold = T2_THRESHOLD_PCT if cur_tier == 1 else T3_THRESHOLD_PCT
    if pct > threshold:
        player.sendMessage(u"§cДля улучшения прочность должна быть §f<" + str(threshold) +
                           u"%§c. Сейчас: §f" + str(pct) + u"%§c.")
        return

    new_tier = cur_tier + 1
    replace_eye(player, new_tier)
    player.sendMessage(u"§5§l✦ Око улучшено до §f" +
                       [u"", u"I", u"II", u"III"][new_tier] + u"§7 (прочность восстановлена).")
    player.getWorld().playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)


def show_progress(player):
    inv = player.getInventory()
    eye_item = inv.getHelmet() if is_eye(inv.getHelmet()) else None
    if eye_item is None:
        for it in inv.getContents():
            if is_eye(it):
                eye_item = it
                break
    if eye_item is None:
        player.sendMessage(u"§7У тебя нет Ока.")
        return
    tier = get_eye_tier(eye_item)
    pct = _durability_pct(eye_item)
    player.sendMessage(u"§7Око Дракона (Тир §f" + str(tier) + u"§7): прочность §f" + str(pct) + u"%")
    if tier == 1:
        player.sendMessage(u"§7Для Тира II — <" + str(T2_THRESHOLD_PCT) + u"%")
    elif tier == 2:
        player.sendMessage(u"§7Для Тира III — <" + str(T3_THRESHOLD_PCT) + u"%")


# =============================================================================
#  ABILITIES
# =============================================================================

def _check_common(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return False
    if not eye_anywhere(player):
        player.sendMessage(u"§cДля способностей нужно Око Дракона.")
        return False
    return True


# --- 1. Драконье дыхание -----------------------------------------------------

def ability_breath(player):
    if not _check_common(player): return
    if not check_cd(player, "breath", u"«Драконье дыхание»"):
        return

    world = player.getWorld()
    origin = player.getEyeLocation()
    dir_v = origin.getDirection().normalize()

    world.playSound(origin, Sound.ENTITY_ENDER_DRAGON_SHOOT, 1.0, 0.9)
    player.sendMessage(u"§5§l✦ Драконье дыхание §r§7— 10 секунд.")

    state = {"tick": 0}
    def cloud_tick():
        if state["tick"] >= BREATH_DURATION:
            return
        if not player.isOnline():
            return

        # Обновляем позицию облака ПЕРЕД игроком (движется вместе с ним).
        eye = player.getEyeLocation()
        dv = eye.getDirection().normalize()
        # Расставляем частицы вдоль конуса 2×2 перед игроком.
        for step in range(1, BREATH_LENGTH + 1):
            center = eye.clone().add(dv.clone().multiply(step))
            spawn_dragon_breath(world, center, 20,
                                BREATH_RADIUS, BREATH_RADIUS, BREATH_RADIUS, 0.01)

        # Урон раз в 20 тиков.
        if state["tick"] % 20 == 0:
            # Ищем цели во всех точках вдоль конуса.
            damaged = set()
            for step in range(1, BREATH_LENGTH + 1):
                center = eye.clone().add(dv.clone().multiply(step))
                for e in world.getNearbyEntities(center, BREATH_RADIUS + 0.2,
                                                  BREATH_RADIUS + 0.2, BREATH_RADIUS + 0.2):
                    if not isinstance(e, LivingEntity): continue
                    if e.equals(player): continue
                    eu = uid(e)
                    if eu in damaged: continue
                    damaged.add(eu)
                    # Магический урон 0.5 сердца.
                    _deal_magic_damage(e, BREATH_TICK_DAMAGE, player)

        state["tick"] += 4
        scheduler.runTaskLater(cloud_tick, 4)

    cloud_tick()
    set_cd(player, "breath", CD_BREATH)


def _deal_magic_damage(target, amount, attacker):
    """Магический урон 0.5 сердца через DamageType.MAGIC (пробивает броню)."""
    if not isinstance(target, LivingEntity): return
    if _HAS_DAMAGE_API:
        try:
            src = (DamageSource.builder(DamageType.MAGIC)
                   .withDirectEntity(attacker)
                   .withCausingEntity(attacker)
                   .build())
            target.damage(amount, src)
            return
        except Exception:
            pass
    new_hp = target.getHealth() - amount
    if new_hp <= 0.0:
        try: target.damage(target.getMaxHealth() * 2, attacker)
        except Exception: target.setHealth(0.0)
    else:
        target.setHealth(new_hp)


# --- 2. Полёт дракона --------------------------------------------------------

def ability_flight(player):
    if not _check_common(player): return
    if not check_cd(player, "flight", u"«Полёт дракона»"):
        return
    if player.getGameMode() == GameMode.CREATIVE or player.getGameMode() == GameMode.SPECTATOR:
        player.sendMessage(u"§7В креативе полёт и так доступен.")
        return

    u = uid(player)
    player.setAllowFlight(True)
    player.setFlying(True)
    flight_end[u] = now_tick() + FLIGHT_DURATION
    active_flight_broken[u] = set()

    world = player.getWorld()
    spawn_dragon_breath(world, player.getLocation().add(0, 1, 0),
                        40, 0.5, 0.5, 0.5, 0.03)
    world.playSound(player.getLocation(), Sound.ENTITY_ENDER_DRAGON_FLAP, 1.0, 1.0)
    player.sendMessage(u"§5§l✦ Полёт дракона §r§7— 15 секунд.")

    # Тикер разрушения блоков на пути.
    def fly_tick():
        if now_tick() >= flight_end.get(u, 0):
            return
        if not player.isOnline():
            return

        # 3×3 в направлении текущего движения игрока.
        # Определяем направление: если игрок реально движется — по velocity,
        # иначе — по направлению взгляда.
        vel = player.getVelocity()
        move = Vector(vel.getX(), 0, vel.getZ())
        if move.lengthSquared() < 0.01:
            look = player.getLocation().getDirection()
            move = Vector(look.getX(), 0, look.getZ())
        if move.lengthSquared() < 0.01:
            scheduler.runTaskLater(fly_tick, 2)
            return
        move = move.normalize()

        # Основной вектор + перпендикуляр (влево/вправо).
        # up = вверх; right = перпендикуляр к move.
        up = Vector(0, 1, 0)
        right = move.clone().crossProduct(up)
        if right.lengthSquared() < 0.001:
            right = Vector(1, 0, 0)
        right = right.normalize()

        # Центр 3×3 — на 1 блок впереди от глаз игрока, на уровне туловища.
        base = player.getLocation().add(0, 1, 0).add(move.clone().multiply(1.0))

        # Строим 3×3 плоскость: right×up.
        blocks_to_break = []
        for dh in (-1, 0, 1):     # горизонтальный сдвиг (влево/центр/вправо)
            for dv in (-1, 0, 1): # вертикальный (вниз/центр/вверх)
                point = base.clone().add(right.clone().multiply(float(dh)))
                point.add(up.clone().multiply(float(dv)))
                blocks_to_break.append(point.getBlock())

        for b in blocks_to_break:
            if b is None: continue
            mat = b.getType()
            if mat.isAir(): continue
            if mat in PROTECTED_BLOCKS: continue
            _save_and_break_block(b, u)

        scheduler.runTaskLater(fly_tick, 2)
    fly_tick()

    # Финал полёта.
    def stop_flight():
        if not player.isOnline():
            return
        if flight_end.get(u, 0) > now_tick():
            return   # ещё не время
        if player.getGameMode() not in (GameMode.CREATIVE, GameMode.SPECTATOR):
            player.setFlying(False)
            player.setAllowFlight(False)
        # После посадки: Speed I на 15 сек + Slowness I на 5 сек (дебафф).
        add_effect(player, E_SPEED, FLIGHT_POST_SPEED, 0)
        add_effect(player, E_SLOWNESS, FLIGHT_POST_SLOWNESS, 0)
        player.sendMessage(u"§7Полёт окончен. §fСкорость I §7на 15 сек, §7Slowness I §fна 5 сек.")

    scheduler.runTaskLater(stop_flight, FLIGHT_DURATION)
    set_cd(player, "flight", CD_FLIGHT)


def _block_key(loc):
    return u"%s,%d,%d,%d" % (loc.getWorld().getName(),
                              loc.getBlockX(), loc.getBlockY(), loc.getBlockZ())


# Хрупкие блоки — те, что "падают" через physics update когда сосед снят.
# Их предзачищаем через setType(AIR, false) — без физики → без item drop.
def _is_fragile(mat):
    try: name = mat.name()
    except Exception: return False
    if name.endswith("_TORCH"):          return True
    if name.endswith("_BUTTON"):         return True
    if name.endswith("_SIGN"):           return True
    if name.endswith("_WALL_SIGN"):      return True
    if name.endswith("_HANGING_SIGN"):   return True
    if name.endswith("_PRESSURE_PLATE"): return True
    if name.endswith("_SAPLING"):        return True
    if name.endswith("_CARPET"):         return True
    if name.startswith("POTTED_"):       return True
    if "REDSTONE" in name:               return True
    if "RAIL" in name:                   return True
    if name in ("LEVER", "TRIPWIRE", "TRIPWIRE_HOOK",
                "STRING", "TORCH", "SOUL_TORCH", "REDSTONE_WIRE",
                "REPEATER", "COMPARATOR", "OBSERVER",
                "SUGAR_CANE", "BAMBOO", "BAMBOO_SAPLING",
                "WHEAT", "CARROTS", "POTATOES", "BEETROOTS",
                "MELON_STEM", "PUMPKIN_STEM",
                "COCOA", "SWEET_BERRY_BUSH", "GLOW_LICHEN",
                "VINE", "TWISTING_VINES", "WEEPING_VINES",
                "CAVE_VINES", "CAVE_VINES_PLANT",
                "LADDER", "SCAFFOLDING"):
        return True
    return False


def _save_and_break_block(block, owner_uid):
    """Сохраняет состояние и ломает блок БЕЗ ФИЗИКИ.
    Восстановление через BLOCK_RESTORE_TICKS. Предзачищает хрупкие соседи."""
    mat = block.getType()
    if mat.isAir(): return
    if mat in PROTECTED_BLOCKS: return

    loc = block.getLocation()
    key = _block_key(loc)
    if key in pending_restore:
        try: block.setType(Material.AIR, False)
        except Exception: block.setType(Material.AIR)
        return

    # Предзачистка хрупких соседей — чтобы не было item drop от physics update.
    for dx, dy, dz in ((0,1,0),(0,-1,0),(1,0,0),(-1,0,0),(0,0,1),(0,0,-1)):
        try:
            nb = block.getRelative(dx, dy, dz)
            nmat = nb.getType()
            if nmat.isAir(): continue
            if nmat in PROTECTED_BLOCKS: continue
            if not _is_fragile(nmat): continue
            nkey = _block_key(nb.getLocation())
            if nkey in pending_restore: continue
            try: nbd = nb.getBlockData().getAsString()
            except Exception: nbd = None
            nloc = nb.getLocation()
            pending_restore[nkey] = {
                "world": nloc.getWorld().getName(),
                "x": nloc.getBlockX(), "y": nloc.getBlockY(), "z": nloc.getBlockZ(),
                "type": nmat.name(),
                "data": nbd,
                "restore_tick": now_tick() + BLOCK_RESTORE_TICKS,
            }
            try: nb.setType(Material.AIR, False)
            except Exception: nb.setType(Material.AIR)
            if owner_uid in active_flight_broken:
                active_flight_broken[owner_uid].add(nkey)
            _dragon_schedule_restore(nkey)
        except Exception: pass

    try:
        block_data_str = block.getBlockData().getAsString()
    except Exception:
        block_data_str = None

    pending_restore[key] = {
        "world": loc.getWorld().getName(),
        "x": loc.getBlockX(), "y": loc.getBlockY(), "z": loc.getBlockZ(),
        "type": mat.name(),
        "data": block_data_str,
        "restore_tick": now_tick() + BLOCK_RESTORE_TICKS,
    }
    try: block.setType(Material.AIR, False)
    except Exception: block.setType(Material.AIR)

    # Регистрируем в наборе полёта.
    if owner_uid in active_flight_broken:
        active_flight_broken[owner_uid].add(key)

    _dragon_schedule_restore(key)


def _dragon_schedule_restore(key):
    """Общая логика планирования восстановления."""
    def restore():
        rec = pending_restore.get(key)
        if rec is None: return
        pending_restore.pop(key, None)
        w = Bukkit.getWorld(rec["world"])
        if w is None: return
        b = w.getBlockAt(rec["x"], rec["y"], rec["z"])
        if b.getType() != Material.AIR:
            return
        try:
            if rec.get("data"):
                bd = Bukkit.createBlockData(rec["data"])
                b.setBlockData(bd, False)
            else:
                mat_r = Material.getMaterial(rec["type"])
                if mat_r is not None:
                    b.setType(mat_r, False)
        except Exception:
            pass

    scheduler.runTaskLater(restore, BLOCK_RESTORE_TICKS)


# --- 3. Драконий фаербол -----------------------------------------------------

def _get_fireball_state(player):
    u = uid(player)
    st = fireball_state.get(u)
    if st is None:
        st = {"charges": FIREBALL_MAX_CHARGES, "recharge_end": 0}
        fireball_state[u] = st
    if st["charges"] < FIREBALL_MAX_CHARGES and st["recharge_end"] > 0:
        if now_tick() >= st["recharge_end"]:
            st["charges"] += 1
            if st["charges"] < FIREBALL_MAX_CHARGES:
                st["recharge_end"] = now_tick() + CD_FIREBALL_PER_CHARGE
            else:
                st["recharge_end"] = 0
    return st


def ability_fireball(player):
    if not _check_common(player): return

    st = _get_fireball_state(player)
    if st["charges"] <= 0:
        secs = (st["recharge_end"] - now_tick() + 19) // 20
        player.sendMessage(u"§cНет зарядов. Следующий через §f" + str(secs) + u"§7 сек.")
        return

    st["charges"] -= 1
    if st["charges"] < FIREBALL_MAX_CHARGES and st["recharge_end"] == 0:
        st["recharge_end"] = now_tick() + CD_FIREBALL_PER_CHARGE

    _spawn_dragon_fireball(player)
    player.sendMessage(u"§5§l✦ Драконий фаербол! §7Зарядов: §f" + str(st["charges"]) +
                       u"§7/§f" + str(FIREBALL_MAX_CHARGES))


def _spawn_dragon_fireball(player):
    """Спавнит DragonFireball, помеченный нашим PDC-тегом.
       Спавним ЧУТЬ ДАЛЬШЕ от глаз игрока, чтобы не хиткстовать по себе."""
    world = player.getWorld()
    eye = player.getEyeLocation()
    dir_v = eye.getDirection().normalize()
    # 2.5 блока впереди — гарантированно за пределами хитбокса игрока.
    spawn_loc = eye.clone().add(dir_v.clone().multiply(2.5))
    try:
        fb = world.spawn(spawn_loc, DragonFireball)
        try:
            fb.setDirection(dir_v.multiply(1.5))
        except Exception:
            fb.setVelocity(dir_v.multiply(1.5))
        # Помечаем и владельца, и сам фаербол как "нашего".
        pdc = fb.getPersistentDataContainer()
        pdc.set(KEY_FIREBALL, PersistentDataType.STRING, uid(player))
        # ВАЖНО: устанавливаем shooter, чтобы vanilla-логика не задевала стрелка.
        try:
            fb.setShooter(player)
        except Exception:
            pass
        world.playSound(eye, Sound.ENTITY_ENDER_DRAGON_SHOOT, 1.0, 1.0)
    except Exception as ex:
        Bukkit.getLogger().warning("[dragon] fireball spawn: " + str(ex))


def on_proj_hit(event):
    proj = event.getEntity()
    if not isinstance(proj, DragonFireball): return
    pdc = proj.getPersistentDataContainer()
    if not pdc.has(KEY_FIREBALL, PersistentDataType.STRING):
        return
    owner_uid_str = pdc.get(KEY_FIREBALL, PersistentDataType.STRING)
    try:
        owner = Bukkit.getPlayer(JUUID.fromString(owner_uid_str))
    except Exception:
        owner = None

    world = proj.getWorld()
    loc = proj.getLocation()
    # Отменяем ванильное создание AreaEffectCloud фаербола (у него слишком слабый эффект).
    # Ставим свой циклический "дыхательный" AoE.
    _start_breath_cloud(world, loc, owner, FIREBALL_CLOUD_R, FIREBALL_CLOUD_DUR)
    spawn_dragon_breath(world, loc, 60, 1.5, 0.5, 1.5, 0.02)
    world.playSound(loc, Sound.ENTITY_GENERIC_EXPLODE, 0.8, 1.3)


def _start_breath_cloud(world, center, owner, radius, duration_ticks):
    """Наносит 0.5 сердца магии всем в 3×3 каждые 20 тиков, duration_ticks."""
    state = {"tick": 0}
    def cloud():
        if state["tick"] >= duration_ticks:
            return
        # Визуал.
        spawn_dragon_breath(world, center, 30, radius, 0.3, radius, 0.01)
        # Урон раз в 20 тиков.
        if state["tick"] % 20 == 0:
            for e in world.getNearbyEntities(center, radius, 2.0, radius):
                if not isinstance(e, LivingEntity): continue
                if owner is not None and e.equals(owner): continue
                _deal_magic_damage(e, BREATH_TICK_DAMAGE, owner if owner is not None else e)
        state["tick"] += 4
        scheduler.runTaskLater(cloud, 4)
    cloud()


# --- 4. Ультимейт: Столб Дракона --------------------------------------------

def ability_ult(player):
    if not _check_common(player): return
    if not check_cd(player, "ult", u"«Столб Дракона»"):
        return

    # Взлёт на 7 блоков.
    player.setVelocity(Vector(0.0, 1.5, 0.0))
    player.setFallDistance(0.0)
    # Гасим fall damage.
    for t in (20, 40, 60, 80, 100, 120, 140):
        scheduler.runTaskLater(lambda p=player: (p.isOnline() and p.setFallDistance(0.0)), t)

    player.sendMessage(u"§5§l✦ СТОЛБ ДРАКОНА! §7— 3 фаербола.")
    world = player.getWorld()
    world.playSound(player.getLocation(), Sound.ENTITY_ENDER_DRAGON_GROWL, 1.0, 0.7)

    # Три фаербола с интервалом 1 сек, после подъёма.
    state = {"n": 0}
    def shoot_next():
        if state["n"] >= ULT_FIREBALL_COUNT:
            return
        if not player.isOnline():
            return
        _spawn_dragon_fireball(player)
        state["n"] += 1
        scheduler.runTaskLater(shoot_next, ULT_FIREBALL_INTERVAL)
    # Стартуем через 20 тиков (после набора высоты).
    scheduler.runTaskLater(shoot_next, 20)

    set_cd(player, "ult", CD_ULT)


# =============================================================================
#  PASSIVES
# =============================================================================

def _passives_tick():
    try:
        for pl in Bukkit.getOnlinePlayers():
            if not is_dragon(pl): continue
            # Make already issued Eyes from earlier versions unbreakable too.
            # New Eyes receive this flag in create_eye().
            for eye in [pl.getInventory().getHelmet()] + list(pl.getInventory().getContents()):
                if not is_eye(eye):
                    continue
                try:
                    meta = eye.getItemMeta()
                    if meta is not None and not meta.isUnbreakable():
                        meta.setUnbreakable(True)
                        eye.setItemMeta(meta)
                except Exception:
                    pass
            u = uid(pl)

            # Урон в воде каждые 2 сек.
            try:
                in_water = pl.isInWater() or pl.getLocation().getBlock().getType() == Material.WATER
            except Exception:
                in_water = False
            if in_water:
                last = water_last_dmg.get(u, 0)
                if now_tick() - last >= WATER_DAMAGE_INTERVAL:
                    water_last_dmg[u] = now_tick()
                    try:
                        pl.damage(WATER_DAMAGE)
                    except Exception:
                        pass

            # Эндер-кристаллы лечат в 8 блоков.
            world = pl.getWorld()
            last_h = crystal_last_heal.get(u, 0)
            if now_tick() - last_h >= CRYSTAL_HEAL_INTERVAL:
                for e in world.getNearbyEntities(pl.getLocation(),
                                                  CRYSTAL_HEAL_RADIUS,
                                                  CRYSTAL_HEAL_RADIUS,
                                                  CRYSTAL_HEAL_RADIUS):
                    if isinstance(e, EnderCrystal):
                        try:
                            max_hp = pl.getAttribute(pl.getAttribute(None) if False else _get_max_hp_attr(pl))
                        except Exception:
                            max_hp = None
                        # Простой хил без attr:
                        try:
                            new_hp = min(pl.getMaxHealth(), pl.getHealth() + CRYSTAL_HEAL)
                            pl.setHealth(new_hp)
                        except Exception:
                            pass
                        crystal_last_heal[u] = now_tick()
                        world.spawnParticle(Particle.HEART, pl.getLocation().add(0, 2, 0),
                                            3, 0.3, 0.2, 0.3)
                        break

    except Exception as ex:
        Bukkit.getLogger().warning("[dragon] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


def _get_max_hp_attr(player):
    try:
        return ATTR_MAX_HEALTH
    except Exception:
        return None


# =============================================================================
#  DAMAGE HOOKS
# =============================================================================

# Последние места взрыва эндер-кристаллов: список (world_name, x, y, z, tick).
recent_crystal_explosions = []


def _crystal_bonus_heal(player):
    """Хил дракону при взрыве эндер-кристалла рядом: +6 сердец."""
    try:
        new_hp = min(player.getMaxHealth(), player.getHealth() + CRYSTAL_EXPLOSION_HEAL)
        player.setHealth(new_hp)
        player.getWorld().spawnParticle(Particle.HEART,
                                         player.getLocation().add(0, 2, 0),
                                         10, 0.6, 0.4, 0.6)
        player.getWorld().playSound(player.getLocation(),
                                     Sound.ENTITY_PLAYER_LEVELUP, 0.7, 1.5)
        player.sendMessage(u"§5§l✦ §rВзрыв кристалла напитал тебя силой! §7+6❤")
    except Exception:
        pass


def on_damage(event):
    ent = event.getEntity()

    # ---- Сначала — трекинг взрыва кристаллов (для любой сущности EnderCrystal). ----
    if isinstance(ent, EnderCrystal):
        try:
            loc = ent.getLocation()
            recent_crystal_explosions.append(
                (loc.getWorld().getName(), loc.getX(), loc.getY(), loc.getZ(), now_tick())
            )
            cutoff = now_tick() - 200
            while recent_crystal_explosions and recent_crystal_explosions[0][4] < cutoff:
                recent_crystal_explosions.pop(0)
        except Exception:
            pass
        return

    # ---- Дальше — только Дракон. ----
    if not isinstance(ent, Player): return
    if not is_dragon(ent): return

    cause = event.getCause()
    C = EntityDamageEvent.DamageCause

    if cause == C.DRAGON_BREATH:
        event.setCancelled(True)
        return

    # Взрывы: проверяем, есть ли рядом Ender Crystal (живой или только что уничтоженный).
    if cause in (C.ENTITY_EXPLOSION, C.BLOCK_EXPLOSION):
        world = ent.getWorld()
        crystal_nearby = False

        # 1) Живой кристалл в радиусе.
        for e in world.getNearbyEntities(ent.getLocation(),
                                          CRYSTAL_EXPLOSION_RADIUS,
                                          CRYSTAL_EXPLOSION_RADIUS,
                                          CRYSTAL_EXPLOSION_RADIUS):
            if isinstance(e, EnderCrystal):
                crystal_nearby = True
                break

        # 2) Недавно взорвавшийся (за последние 2 сек) в радиусе.
        if not crystal_nearby:
            loc = ent.getLocation()
            wname = world.getName()
            threshold_tick = now_tick() - 40
            for (wn, cx, cy, cz, ct) in recent_crystal_explosions:
                if wn != wname: continue
                if ct < threshold_tick: continue
                dx = cx - loc.getX()
                dy = cy - loc.getY()
                dz = cz - loc.getZ()
                if dx*dx + dy*dy + dz*dz <= CRYSTAL_EXPLOSION_RADIUS * CRYSTAL_EXPLOSION_RADIUS:
                    crystal_nearby = True
                    break

        if crystal_nearby:
            event.setCancelled(True)
            _crystal_bonus_heal(ent)
            return


def on_damage_by(event):
    dmg = event.getDamager()
    ent = event.getEntity()

    # Наши собственные фаерболы не наносят урон Дракону-владельцу.
    if isinstance(ent, Player) and is_dragon(ent):
        if isinstance(dmg, DragonFireball):
            try:
                pdc = dmg.getPersistentDataContainer()
                if pdc.has(KEY_FIREBALL, PersistentDataType.STRING):
                    owner_str = pdc.get(KEY_FIREBALL, PersistentDataType.STRING)
                    if owner_str == uid(ent):
                        event.setCancelled(True)
                        return
            except Exception:
                pass
        # Дракон получает урон от стрел/арбалетов/трезубцев — +15%.
        if isinstance(dmg, Projectile):
            event.setDamage(event.getDamage() * PROJECTILE_VULN_MULT)

    # Дракон в Энде наносит +20% урона.
    if isinstance(dmg, Player) and is_dragon(dmg):
        try:
            env = dmg.getWorld().getEnvironment().name()
            if env == "THE_END":
                event.setDamage(event.getDamage() * END_DAMAGE_MULT)
        except Exception:
            pass


# =============================================================================
#  ITEM PROTECTION / DEATH
# =============================================================================

def on_interact(event):
    if event.getHand() != EquipmentSlot.HAND: return
    p = event.getPlayer()
    item = event.getItem()
    if not is_eye(item): return
    o = get_eye_owner(item)
    if o is not None and o != uid(p):
        event.setCancelled(True)
        p.sendMessage(u"§cОко отвергает тебя.")


def on_drop(event):
    it = event.getItemDrop().getItemStack()
    if is_eye(it):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cОко нельзя выбросить.")


def on_inv_click(event):
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        it = event.getCurrentItem()
        cursor = event.getCursor()
        if is_eye(it) or is_eye(cursor):
            event.setCancelled(True)
            event.getWhoClicked().sendMessage(u"§cОко нельзя убрать в контейнер.")


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

    if not is_dragon(player):
        return

    def _check_and_restore():
        try:
            if not player.isOnline():
                return

            if eye_anywhere(player) is None:
                give_eye(player, 1)
                player.sendMessage(u"§7[dragon] Комплект восстановлен.")

        except Exception:
            import traceback
            traceback.print_exc()

    scheduler.runTaskLater(_check_and_restore, 40)





# Защита сломанных блоков от повторного разрушения (пока в pending_restore).
def on_block_break(event):
    b = event.getBlock()
    l = b.getLocation()
    key = _block_key(l)
    if key in pending_restore:
        event.setCancelled(True)


# =============================================================================
#  COMMAND
# =============================================================================

def cmd_dragon(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько для игроков.")
        return True
    if not is_dragon(sender):
        sender.sendMessage(u"§cТолько Дракон может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/dragon <дыхание|полёт|фаербол|ульт>")
        sender.sendMessage(u"  §f/dragon улучшить §7или §fпрогресс§7 / §fтир <n>")
        return True

    sub = args[0].lower()

    if sub in (u"улучшить", u"upgrade"):
        try_upgrade(sender); return True
    if sub in (u"прогресс", u"progress"):
        show_progress(sender); return True
    if sub in (u"тир", u"tier"):
        if not _test_mode_on():
            sender.sendMessage(u"§cТестовый режим выключен — команда недоступна.")
            return True
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/dragon тир <1..3>"); return True
        try:
            t = int(args[1])
        except ValueError:
            sender.sendMessage(u"§cТир — число."); return True
        if t < 1 or t > 3:
            sender.sendMessage(u"§cТиры: 1..3."); return True
        if not replace_eye(sender, t):
            give_eye(sender, t)
        else:
            sender.sendMessage(u"§aТир: §f" + [u"", u"I", u"II", u"III"][t])
        return True

    if sub in (u"дыхание", u"breath"):
        ability_breath(sender); return True
    if sub in (u"полёт", u"полет", u"flight"):
        ability_flight(sender); return True
    if sub in (u"фаербол", u"fireball"):
        ability_fireball(sender); return True
    if sub in (u"ульт", u"ult", u"столб"):
        ability_ult(sender); return True

    sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
    return True


# =============================================================================
#  RESET
# =============================================================================

def _dragon_reset_state(target_player):
    u = uid(target_player)
    fireball_state.pop(u, None)
    flight_end.pop(u, None)
    water_last_dmg.pop(u, None)
    crystal_last_heal.pop(u, None)
    active_flight_broken.pop(u, None)


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_dragon, "dragon")

listener_mgr.registerListener(on_interact,   PlayerInteractEvent)
listener_mgr.registerListener(on_drop,       PlayerDropItemEvent)
listener_mgr.registerListener(on_inv_click,  InventoryClickEvent)
listener_mgr.registerListener(on_death,      PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,    PlayerRespawnEvent)
listener_mgr.registerListener(on_damage,     EntityDamageEvent)
listener_mgr.registerListener(on_damage_by,  EntityDamageByEntityEvent)
listener_mgr.registerListener(on_proj_hit,   ProjectileHitEvent)
listener_mgr.registerListener(on_block_break, BlockBreakEvent)

_passives_tick()

# --- Реестры ---
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("dragon", (kit_entry, u"Дракон (Око Дракона [1..3])"))

_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("dragon", list(DRAGON_NAMES))

def _dragon_set_tier(target_player, tier):
    if tier < 1 or tier > 3: return False
    if not replace_eye(target_player, tier):
        give_eye(target_player, tier)
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("dragon", _dragon_set_tier)

_RESET_KEY = "character_reset_functions"
_reset_reg = _props.get(_RESET_KEY)
if _reset_reg is None:
    _reset_reg = HashMap()
    _props.put(_RESET_KEY, _reset_reg)
_reset_reg.put("dragon", _dragon_reset_state)


# --- Публикация в каталог Зеркала Души Арчера ---
def _dragon_mirror_eye(owner_uuid):
    return create_eye(2, owner_uuid)

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

_mirror_publish("dragon:eye", u"око дракона", u"§5Око Дракона", _dragon_mirror_eye)


# quest_tracker: публикуем stat-функцию.
# Ключ "damage_amount" — процент изношенности Ока (100 - pct прочности).
def _dragon_stat(player, key):
    try:
        eye = eye_anywhere(player)
        if eye is None: return 0
        pct = _durability_pct(eye)   # 0..100 оставшейся прочности
        if key == "damage_amount":
            return int(100 - pct)
    except Exception: pass
    return 0

try:
    System.getProperties().put("quest_tracker.stat.dragon", _dragon_stat)
except Exception: pass


Bukkit.getLogger().info("[dragon] Dragon loaded. Commands: /test dragon, /dragon")

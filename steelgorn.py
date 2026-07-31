# -*- coding: utf-8 -*-
"""
==============================================================================
  СТАЛЬГОРН / Steelgorn — Хранитель Гор (танк / фронтлайн-боец)
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  Владельцы: Kristalik228113 (+ blueredtronce для теста)

  Легендарный предмет: Топор Стальгорна (I железный -> II алмазный -> III
  незеритовый). Прогрессия по убийствам + добыче древесины. Автоапгрейд.

  Пассив: -1 сердце max HP, +N брони (только с топором в руке),
          удары накладывают "Тяжесть" (замедление + больше урона от падения).

  Способности:
    - Рывок лесоруба     (/steelgorn рывок)   — 10 бл, 6 HP, Slow IV 1.5 сек
    - Каменная броня     (/steelgorn броня)   — 7 сек Resist I + KB immune,
                                                 первый удар -60%
    - Землетрясение      (/steelgorn ульт)    — r=7, подброс + 4 HP + 5 сек
                                                 нестабильность, 3 сек стан
  Слабости:
    - -1 сердце max HP
    - 3 сек полный стан после ульта
    - Нельзя off-hand (щит, тотем, факел и пр.)
    - x2 урон от летающих существ (Phantom, Ghast, EnderDragon, Vex)
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, Long as JLong, IllegalArgumentException
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, Location, Tag
)
from org.bukkit.entity import Player, LivingEntity
# Летающие: пробуем импортировать с fallback.
_FLYING_TYPES = []
for _cls_name in ("Phantom", "Ghast", "EnderDragon", "Vex", "Allay"):
    try:
        _mod = __import__("org.bukkit.entity", globals(), locals(), [_cls_name])
        _cls = getattr(_mod, _cls_name)
        _FLYING_TYPES.append(_cls)
    except Exception:
        pass

from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerItemHeldEvent, PlayerJoinEvent,
    PlayerRespawnEvent, PlayerDropItemEvent, PlayerSwapHandItemsEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDeathEvent
)
from org.bukkit.event.block import BlockBreakEvent
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.persistence import PersistentDataType
from org.bukkit.enchantments import Enchantment
from org.bukkit.attribute import Attribute, AttributeModifier
from org.bukkit.util import Vector
from org.bukkit.potion import PotionEffect

# ============================================================================
# ATTRIBUTE RESOLVER (Paper 1.21.4+ переименовал GENERIC_* → без префикса)
# ============================================================================
# В 1.21.4+ атрибуты называются MAX_HEALTH, ARMOR и т.д.
# В 1.21.1- они назывались GENERIC_MAX_HEALTH, GENERIC_ARMOR.
# Мы поддерживаем оба варианта через _attr(name).

def _attr(name):
    """Возвращает Attribute по короткому имени. Пробует новое (без префикса),
    потом старое (GENERIC_*). Возвращает None если атрибута нет."""
    for full_name in (name, "GENERIC_" + name):
        a = getattr(Attribute, full_name, None)
        if a is not None:
            return a
    return None

ATTR_MAX_HEALTH           = _attr("MAX_HEALTH")
ATTR_ARMOR                = _attr("ARMOR")
ATTR_MOVEMENT_SPEED       = _attr("MOVEMENT_SPEED")
ATTR_KNOCKBACK_RESISTANCE = _attr("KNOCKBACK_RESISTANCE")

# DamageSource (Paper 1.20.5+) — на всякий случай.
_HAS_DAMAGE_API = True
try:
    from org.bukkit.damage import DamageSource, DamageType
except Exception:
    _HAS_DAMAGE_API = False


# ============================================================================
# CONFIG
# ============================================================================

STEELGORN_NAMES = set([u"Kristalik228113", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

# PDC keys
KEY_AXE         = NamespacedKey.fromString("steelgorn:axe")
KEY_TIER        = NamespacedKey.fromString("steelgorn:tier")
KEY_OWNER       = NamespacedKey.fromString("steelgorn:owner")
KEY_MOB_KILLS   = NamespacedKey.fromString("steelgorn:mobs")
KEY_WOOD        = NamespacedKey.fromString("steelgorn:wood")

# На цели
KEY_HEAVY_END   = NamespacedKey.fromString("steelgorn:heavy_until")
KEY_HEAVY_TIER  = NamespacedKey.fromString("steelgorn:heavy_tier")

# На самом Стальгорне
KEY_STONE_END   = NamespacedKey.fromString("steelgorn:stone_end")
KEY_STONE_FIRST = NamespacedKey.fromString("steelgorn:stone_first_pending")
KEY_ULT_STUN    = NamespacedKey.fromString("steelgorn:ult_stun_end")

# Материалы топора по тирам
TIER_MATERIAL = {
    1: Material.IRON_AXE,
    2: Material.DIAMOND_AXE,
    3: Material.NETHERITE_AXE,
}
TIER_NAME = {
    1: u"§7§lТопор Стальгорна §f§oI §8— Зародыш гор",
    2: u"§b§lТопор Стальгорна §f§oII §8— Пробуждение",
    3: u"§5§lТопор Стальгорна §f§oIII §8— Наследие Стальгорна",
}

# Прогрессия улучшения
TIER_UPGRADE_MOBS = {1: 200, 2: 300}
TIER_UPGRADE_WOOD = {1: 300, 2: 500}

# Пассив
TIER_PASSIVE_PCT   = {1: 0.50, 2: 0.75, 3: 1.00}    # для лора
TIER_ARMOR_BONUS   = {1: 1.0,  2: 1.5,  3: 2.0}
TIER_HEAVY_SLOW    = {1: -0.10, 2: -0.15, 3: -0.20}  # множитель MULTIPLY_SCALAR_1
TIER_HEAVY_FALL    = {1: 1.25,  2: 1.35,  3: 1.50}   # финальный множитель fall damage
HEAVY_DURATION     = 3 * 20                          # 3 сек

# Cooldowns
# Ребаланс 2026-07-28 (лёгкая коррекция):
#   Каменная броня: 8->7 сек, CD 45->50 сек, первый удар -75% -> -60% (проходит 40%)
#   Рывок: Slowness IV -> III
#   Ульт: нестабильность 5->4 сек
CD_DASH   = 30 * 20
CD_STONE  = 50 * 20                       # было 45
CD_ULT    = 180 * 20

# Rush
DASH_DISTANCE          = 10
DASH_DAMAGE            = 6.0
DASH_SLOWNESS_DURATION = int(1.5 * 20)   # 30 тиков
DASH_SLOWNESS_AMP      = 2               # Slowness III (было 3 = IV)

# Stone armor
STONE_DURATION            = 7 * 20        # было 8 сек
STONE_FIRST_HIT_PASSTHRU  = 0.40          # проходит 40% (уменьшение 60%). Было 0.25 (-75%).

# Ult
ULT_RADIUS          = 7.0
ULT_LAUNCH_Y        = 1.0                 # velocity Y (~4 бл подброс)
ULT_DAMAGE          = 4.0
ULT_INSTABILITY_DUR = 4 * 20              # было 5 сек
ULT_STUN_DURATION   = 3 * 20

# Слабости
MAX_HP_REDUCTION = -2.0                    # -1 сердце
FLYING_DMG_MULT  = 2.0

# Attribute modifier UUIDs (стабильные, чтобы можно было чистить)
MAX_HP_MOD_UUID       = JUUID.fromString("aa11bbcc-1111-2222-3333-444455556666")
ARMOR_MOD_UUID        = JUUID.fromString("aa11bbcc-1111-2222-3333-777788889999")
KB_RESIST_MOD_UUID    = JUUID.fromString("aa11bbcc-1111-2222-3333-aaaabbbbcccc")
HEAVY_SLOW_MOD_UUID   = JUUID.fromString("aa11bbcc-1111-2222-3333-ccccddddeeee")


# ============================================================================
# UTILS
# ============================================================================

def uid(e):
    return e.getUniqueId().toString()

def now_tick():
    return long(System.currentTimeMillis() / 50)

def _to_unicode(s):
    if s is None: return u""
    if isinstance(s, unicode): return s
    try: return unicode(s, "utf-8", "replace")
    except Exception:
        try: return unicode(s)
        except Exception: return u""

def _norm(s):
    return _to_unicode(s).strip().lower()

def java_list(it):
    lst = ArrayList()
    for x in it: lst.add(x)
    return lst

def _test_mode_on():
    try:
        tm = System.getProperties().get("arena.test_mode")
        if tm is None: return True
        return tm == "1"
    except Exception:
        return True

def is_steelgorn(player):
    if not isinstance(player, Player): return False
    n = player.getName().lower()
    matched = False
    for real in STEELGORN_NAMES:
        if real.lower() == n:
            matched = True
            break
    if not matched: return False
    # blueredtronce разрешён только в тестовом режиме.
    if n == u"blueredtronce":
        return _test_mode_on()
    return True

def is_silenced_by_demiurg(player):
    try:
        silenced = System.getProperties().get("demiurg.silenced_uuids")
        if silenced is None: return False
        return silenced.contains(uid(player))
    except Exception:
        return False

def _effect(k):
    return Registry.EFFECT.get(NamespacedKey.minecraft(k))

def _enchant(k):
    return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

E_SLOWNESS   = _effect("slowness")
E_RESISTANCE = _effect("resistance")
E_MINING_FTG = _effect("mining_fatigue")
E_JUMP       = _effect("jump_boost")

ENC_SHARPNESS  = _enchant("sharpness")
ENC_EFFICIENCY = _enchant("efficiency")

def add_effect(entity, ptype, ticks, amp, ambient=True, particles=False):
    if ptype is None or entity is None: return
    try:
        entity.addPotionEffect(PotionEffect(ptype, ticks, amp, ambient, particles, True))
    except Exception:
        pass


# Cooldown storage
cooldowns = {}   # uid -> {ability: end_tick}

def _is_free_cd(player):
    return player.getName().lower() in FREE_CD_PLAYERS

def check_cd(player, name, label=None):
    if _is_free_cd(player): return True
    d = cooldowns.get(uid(player))
    if d is None: return True
    end = d.get(name, 0)
    if now_tick() < end:
        rem = (end - now_tick()) / 20.0
        if label:
            player.sendMessage(u"§7Способность " + label + u" §7перезаряжается: §c%.1f §7сек." % rem)
        return False
    return True

def set_cd(player, name, ticks):
    if _is_free_cd(player): return
    u = uid(player)
    if u not in cooldowns:
        cooldowns[u] = {}
    cooldowns[u][name] = now_tick() + ticks


# ============================================================================
# ITEM
# ============================================================================

def is_axe(item):
    if item is None: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_AXE, PersistentDataType.BYTE)

def get_axe_tier(item):
    if item is None: return 0
    m = item.getItemMeta()
    if m is None: return 0
    p = m.getPersistentDataContainer()
    if not p.has(KEY_TIER, PersistentDataType.INTEGER): return 0
    return p.get(KEY_TIER, PersistentDataType.INTEGER)

def axe_in_hand(player):
    it = player.getInventory().getItemInMainHand()
    if is_axe(it):
        return it
    return None

def axe_anywhere(player):
    for it in player.getInventory().getContents():
        if is_axe(it):
            return it
    return None

def get_progress(item):
    m = item.getItemMeta()
    if m is None: return (0, 0)
    p = m.getPersistentDataContainer()
    mobs = p.get(KEY_MOB_KILLS, PersistentDataType.INTEGER) if p.has(KEY_MOB_KILLS, PersistentDataType.INTEGER) else 0
    wood = p.get(KEY_WOOD,      PersistentDataType.INTEGER) if p.has(KEY_WOOD,      PersistentDataType.INTEGER) else 0
    return (mobs, wood)

def _apply_lore(item, tier, mobs, wood):
    m = item.getItemMeta()
    if m is None: return
    pct = int(TIER_PASSIVE_PCT[tier] * 100)
    lore = [
        u"§7Древнее оружие хранителей гор.",
        u"§8Уровень: §f" + [u"", u"I", u"II", u"III"][tier],
        u"§8Пассивная сила: §f" + str(pct) + u"%",
        u"",
    ]
    if tier < 3:
        need_m = TIER_UPGRADE_MOBS[tier]
        need_w = TIER_UPGRADE_WOOD[tier]
        mc = u"§a" if mobs >= need_m else u"§e"
        wc = u"§a" if wood >= need_w else u"§e"
        lore.append(u"§8Прогресс улучшения:")
        lore.append(u"  " + mc + u"Убито мобов: §f%d§7/§f%d" % (mobs, need_m))
        lore.append(u"  " + wc + u"Дерева добыто: §f%d§7/§f%d" % (wood, need_w))
        lore.append(u"")
    else:
        lore.append(u"§d§lПолностью развит.")
        lore.append(u"")
    lore.extend([
        u"§8Пассив §fСердце гор§8:",
        u"§8  +брoня, эффект §7Тяжесть §8при ударе.",
        u"§8Активные: §f/steelgorn <способность>",
        u"",
        u"§8Только Стальгорн может использовать этот топор.",
    ])
    m.setLore(java_list(lore))
    item.setItemMeta(m)

def set_progress(item, mobs, wood):
    m = item.getItemMeta()
    if m is None: return
    p = m.getPersistentDataContainer()
    p.set(KEY_MOB_KILLS, PersistentDataType.INTEGER, mobs)
    p.set(KEY_WOOD,      PersistentDataType.INTEGER, wood)
    item.setItemMeta(m)
    tier = get_axe_tier(item)
    _apply_lore(item, tier, mobs, wood)

def create_axe(tier, owner_uuid, mobs=0, wood=0):
    if tier < 1: tier = 1
    if tier > 3: tier = 3
    it = ItemStack(TIER_MATERIAL[tier], 1)
    m = it.getItemMeta()
    m.setDisplayName(TIER_NAME[tier])
    # По правилу проекта — предмет неразрушим (прогрессия не завязана на прочность).
    m.setUnbreakable(True)

    # Зачарования (без Mending/Unbreaking — правило проекта).
    if tier == 1:
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 3, True)
        if ENC_EFFICIENCY: m.addEnchant(ENC_EFFICIENCY, 3, True)
    elif tier == 2:
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 4, True)
        if ENC_EFFICIENCY: m.addEnchant(ENC_EFFICIENCY, 4, True)
    else:
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 5, True)
        if ENC_EFFICIENCY: m.addEnchant(ENC_EFFICIENCY, 5, True)

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_AXE,       PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_TIER,      PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER,     PersistentDataType.STRING,  owner_uuid)
    pdc.set(KEY_MOB_KILLS, PersistentDataType.INTEGER, mobs)
    pdc.set(KEY_WOOD,      PersistentDataType.INTEGER, wood)

    it.setItemMeta(m)
    _apply_lore(it, tier, mobs, wood)
    return it

def replace_axe(player, tier, mobs=0, wood=0):
    inv = player.getInventory()
    contents = inv.getContents()
    for i in range(len(contents)):
        if is_axe(contents[i]):
            inv.setItem(i, create_axe(tier, uid(player), mobs, wood))
            return True
    return False

def give_kit(player, tier=1):
    if not replace_axe(player, tier, 0, 0):
        player.getInventory().addItem(create_axe(tier, uid(player), 0, 0))


# ============================================================================
# PROGRESSION
# ============================================================================

def _is_wood_block(mat):
    try:
        if Tag.LOGS.isTagged(mat):
            return True
    except Exception:
        pass
    name = mat.name()
    return (name.endswith("_LOG") or
            name.endswith("_WOOD") or
            name.endswith("_STEM") or
            name.startswith("STRIPPED_"))

def _try_upgrade(player, item):
    tier = get_axe_tier(item)
    if tier >= 3: return
    mobs, wood = get_progress(item)
    need_m = TIER_UPGRADE_MOBS.get(tier)
    need_w = TIER_UPGRADE_WOOD.get(tier)
    if need_m is None or need_w is None: return
    if mobs < need_m or wood < need_w:
        return
    new_tier = tier + 1
    inv = player.getInventory()
    for i in range(inv.getSize()):
        it = inv.getItem(i)
        if it is not None and is_axe(it) and get_axe_tier(it) == tier:
            inv.setItem(i, create_axe(new_tier, uid(player), 0, 0))
            break
    player.sendMessage(u"§d§l✦ Топор Стальгорна улучшен до уровня " +
                       [u"", u"I", u"II", u"III"][new_tier] + u"!")
    try:
        w = player.getWorld()
        w.playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)
        w.spawnParticle(Particle.END_ROD, player.getLocation().add(0, 1, 0),
                        60, 0.5, 1.0, 0.5, 0.1)
    except Exception:
        pass
    _refresh_passive(player)


# ============================================================================
# PASSIVE: max HP -1 сердце, +armor если топор в руке
# ============================================================================
#
# Paper 1.21 БАГ: getUniqueId() на чужих AttributeModifier'ах бросает
# IllegalArgumentException("UUID string too large"), потому что модификаторы
# ванильных атрибутов (например minecraft:armor.item) идут через NamespacedKey,
# а не UUID. Итерироваться по attr.getModifiers() — НЕЛЬЗЯ.
#
# Правильный подход:
#   - хранить сами модификаторы, которые мы применили (по uid игрока);
#   - вызывать attr.removeModifier(модификатор) с той же ссылкой;
#   - при add ловить IllegalArgumentException (уже применён).
# ============================================================================

# uid(player) -> AttributeModifier
_max_hp_mod  = {}
_armor_mod   = {}
_kb_mod      = {}
# uid(target) -> AttributeModifier (для Тяжести)
_heavy_mod   = {}


def _try_add(attr, mod):
    """Пытается добавить модификатор, глотает IllegalArgumentException."""
    if attr is None or mod is None: return False
    try:
        attr.addModifier(mod)
        return True
    except IllegalArgumentException:
        return False
    except Exception as ex:
        Bukkit.getLogger().warning("[steelgorn] addModifier: " + str(ex))
        return False

def _try_remove(attr, mod):
    """Пытается снять модификатор по ссылке (безопасно)."""
    if attr is None or mod is None: return
    try:
        attr.removeModifier(mod)
    except Exception:
        pass


def _ensure_max_hp_reduction(player):
    u = uid(player)
    if u in _max_hp_mod:
        return   # уже применено
    try:
        attr = player.getAttribute(ATTR_MAX_HEALTH)
        if attr is None: return
        mod = AttributeModifier(
            MAX_HP_MOD_UUID, "steelgorn_max_hp", MAX_HP_REDUCTION,
            AttributeModifier.Operation.ADD_NUMBER
        )
        _try_add(attr, mod)
        _max_hp_mod[u] = mod
        max_hp = attr.getValue()
        if player.getHealth() > max_hp:
            try: player.setHealth(max_hp)
            except Exception: pass
    except Exception as ex:
        Bukkit.getLogger().warning("[steelgorn] max_hp apply: " + str(ex))

def _remove_max_hp_reduction(player):
    u = uid(player)
    mod = _max_hp_mod.pop(u, None)
    if mod is None: return
    try:
        attr = player.getAttribute(ATTR_MAX_HEALTH)
        _try_remove(attr, mod)
    except Exception:
        pass


def _apply_armor_bonus(player, tier):
    u = uid(player)
    try:
        attr = player.getAttribute(ATTR_ARMOR)
        if attr is None: return
        # Снимаем свой предыдущий (если был).
        old = _armor_mod.pop(u, None)
        if old is not None:
            _try_remove(attr, old)
        bonus = TIER_ARMOR_BONUS.get(tier, 0.0)
        if bonus <= 0: return
        mod = AttributeModifier(
            ARMOR_MOD_UUID, "steelgorn_armor", bonus,
            AttributeModifier.Operation.ADD_NUMBER
        )
        _try_add(attr, mod)
        _armor_mod[u] = mod
    except Exception as ex:
        Bukkit.getLogger().warning("[steelgorn] armor apply: " + str(ex))

def _remove_armor_bonus(player):
    u = uid(player)
    mod = _armor_mod.pop(u, None)
    if mod is None: return
    try:
        attr = player.getAttribute(ATTR_ARMOR)
        _try_remove(attr, mod)
    except Exception:
        pass

def _refresh_passive(player):
    """Синхронизация: если топор в основной руке — есть броня,
    если нет — брони нет. Max HP отниматься не перестаёт."""
    if not is_steelgorn(player): return
    _ensure_max_hp_reduction(player)
    ax = axe_in_hand(player)
    if ax is not None:
        _apply_armor_bonus(player, get_axe_tier(ax))
    else:
        _remove_armor_bonus(player)


# ============================================================================
# "Тяжесть" на цели
# ============================================================================

def _mark_heavy(target, tier):
    if not isinstance(target, LivingEntity): return
    end = now_tick() + HEAVY_DURATION
    tu = uid(target)
    try:
        pdc = target.getPersistentDataContainer()
        pdc.set(KEY_HEAVY_END,  PersistentDataType.LONG,    JLong(end))
        pdc.set(KEY_HEAVY_TIER, PersistentDataType.INTEGER, tier)
    except Exception:
        pass
    # Замедление через AttributeModifier MULTIPLY_SCALAR_1 — точнее чем Slowness.
    try:
        attr = target.getAttribute(ATTR_MOVEMENT_SPEED)
        if attr is not None:
            # Снять свой предыдущий (если был).
            old = _heavy_mod.pop(tu, None)
            if old is not None:
                _try_remove(attr, old)
            amt = TIER_HEAVY_SLOW.get(tier, -0.10)
            mod = AttributeModifier(
                HEAVY_SLOW_MOD_UUID, "steelgorn_heavy",
                amt,
                AttributeModifier.Operation.MULTIPLY_SCALAR_1
            )
            _try_add(attr, mod)
            _heavy_mod[tu] = mod
    except Exception:
        pass
    # Снятие через 3 сек (даже если метку кто-то обновил заново — этот таймер
    # снимет старую метку, но новая уже поставила новую с новым end).
    def _cleanup():
        try:
            if not target.isValid(): return
            pdc2 = target.getPersistentDataContainer()
            if pdc2.has(KEY_HEAVY_END, PersistentDataType.LONG):
                cur_end = pdc2.get(KEY_HEAVY_END, PersistentDataType.LONG)
                if now_tick() >= cur_end:
                    try:
                        pdc2.remove(KEY_HEAVY_END)
                        if pdc2.has(KEY_HEAVY_TIER, PersistentDataType.INTEGER):
                            pdc2.remove(KEY_HEAVY_TIER)
                    except Exception:
                        pass
                    # Снимаем свой сохранённый модификатор скорости.
                    mod2 = _heavy_mod.pop(tu, None)
                    if mod2 is not None:
                        attr2 = target.getAttribute(ATTR_MOVEMENT_SPEED)
                        _try_remove(attr2, mod2)
        except Exception:
            pass
    scheduler.runTaskLater(_cleanup, HEAVY_DURATION + 2)
    # Визуал.
    try:
        target.getWorld().spawnParticle(
            Particle.BLOCK,
            target.getLocation().add(0, 0.3, 0),
            10, 0.3, 0.1, 0.3,
            Material.STONE.createBlockData()
        )
    except Exception:
        pass

def _get_heavy_tier(target):
    """Возвращает тир источника Тяжести или 0 если метки нет / истекла."""
    if not isinstance(target, LivingEntity): return 0
    try:
        pdc = target.getPersistentDataContainer()
        if not pdc.has(KEY_HEAVY_END, PersistentDataType.LONG): return 0
        end = pdc.get(KEY_HEAVY_END, PersistentDataType.LONG)
        if now_tick() >= end: return 0
        if pdc.has(KEY_HEAVY_TIER, PersistentDataType.INTEGER):
            return pdc.get(KEY_HEAVY_TIER, PersistentDataType.INTEGER)
        return 1
    except Exception:
        return 0


# ============================================================================
# ABILITIES
# ============================================================================

def _is_ult_stunned(player):
    try:
        pdc = player.getPersistentDataContainer()
        if not pdc.has(KEY_ULT_STUN, PersistentDataType.LONG): return False
        end = pdc.get(KEY_ULT_STUN, PersistentDataType.LONG)
        return now_tick() < end
    except Exception:
        return False

def _check_common(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return False
    if axe_in_hand(player) is None:
        player.sendMessage(u"§cДля способностей нужен §fТопор Стальгорна §cв основной руке.")
        return False
    if _is_ult_stunned(player):
        player.sendMessage(u"§8Земля ещё нестабильна. Дай ей успокоиться.")
        return False
    return True

# --- 1. Рывок лесоруба -------------------------------------------------------

def ability_dash(player):
    if not _check_common(player): return
    if not check_cd(player, "dash", u"«Рывок лесоруба»"): return

    world = player.getWorld()
    start = player.getLocation().clone()
    dir_v = start.getDirection().normalize()

    # Импульс. ~2.2 velocity XZ + 0.35 Y — стабильные ~10 блоков.
    vel = dir_v.clone().multiply(2.2)
    vel.setY(0.35)
    player.setVelocity(vel)
    player.setFallDistance(0.0)

    world.playSound(start, Sound.ENTITY_IRON_GOLEM_ATTACK, 1.2, 1.2)
    try:
        world.spawnParticle(Particle.SWEEP_ATTACK, start.clone().add(0, 1, 0), 15, 0.5, 0.5, 0.5)
    except Exception:
        pass

    ax = axe_in_hand(player)
    tier = get_axe_tier(ax) if ax is not None else 1

    # Ищем цели вдоль трассы. Один удар на цель.
    hit = set()
    for step in range(1, DASH_DISTANCE + 1):
        point = start.clone().add(dir_v.clone().multiply(float(step)))
        try:
            world.spawnParticle(Particle.CRIT, point, 6, 0.3, 0.5, 0.3, 0.02)
        except Exception:
            pass
        for e in world.getNearbyEntities(point, 1.5, 1.5, 1.5):
            if not isinstance(e, LivingEntity): continue
            if e.equals(player): continue
            eu = uid(e)
            if eu in hit: continue
            hit.add(eu)
            try:
                e.damage(DASH_DAMAGE, player)
            except Exception:
                pass
            add_effect(e, E_SLOWNESS, DASH_SLOWNESS_DURATION, DASH_SLOWNESS_AMP, False, False)
            _mark_heavy(e, tier)

    player.sendMessage(u"§7§l✦ Рывок лесоруба!")
    set_cd(player, "dash", CD_DASH)

# --- 2. Каменная броня -------------------------------------------------------

def ability_stone(player):
    if not _check_common(player): return
    if not check_cd(player, "stone", u"«Каменная броня»"): return

    end = now_tick() + STONE_DURATION
    try:
        pdc = player.getPersistentDataContainer()
        pdc.set(KEY_STONE_END,   PersistentDataType.LONG, JLong(end))
        pdc.set(KEY_STONE_FIRST, PersistentDataType.BYTE, JByte(1))
    except Exception:
        pass

    add_effect(player, E_RESISTANCE, STONE_DURATION, 0)

    # Полный иммунитет к отбрасыванию — KNOCKBACK_RESISTANCE = 1.0
    try:
        attr = player.getAttribute(ATTR_KNOCKBACK_RESISTANCE)
        if attr is not None:
            u = uid(player)
            old = _kb_mod.pop(u, None)
            if old is not None:
                _try_remove(attr, old)
            mod = AttributeModifier(
                KB_RESIST_MOD_UUID, "steelgorn_kb_resist", 1.0,
                AttributeModifier.Operation.ADD_NUMBER
            )
            _try_add(attr, mod)
            _kb_mod[u] = mod
    except Exception:
        pass

    def _clear_stone():
        try:
            if not player.isValid(): return
            u2 = uid(player)
            kbm = _kb_mod.pop(u2, None)
            if kbm is not None:
                attr = player.getAttribute(ATTR_KNOCKBACK_RESISTANCE)
                _try_remove(attr, kbm)
            pdc2 = player.getPersistentDataContainer()
            if pdc2.has(KEY_STONE_FIRST, PersistentDataType.BYTE):
                try: pdc2.remove(KEY_STONE_FIRST)
                except Exception: pass
            if pdc2.has(KEY_STONE_END, PersistentDataType.LONG):
                try: pdc2.remove(KEY_STONE_END)
                except Exception: pass
        except Exception:
            pass
    scheduler.runTaskLater(_clear_stone, STONE_DURATION)

    world = player.getWorld()
    world.playSound(player.getLocation(), Sound.BLOCK_STONE_PLACE, 1.4, 0.7)
    try:
        world.spawnParticle(
            Particle.BLOCK,
            player.getLocation().add(0, 1, 0),
            40, 0.5, 1.0, 0.5,
            Material.STONE.createBlockData()
        )
    except Exception:
        pass
    player.sendMessage(u"§8§l✦ Каменная броня §r§7— 7 сек. Первый удар §f-60%§7.")
    set_cd(player, "stone", CD_STONE)

# --- 3. Ультимейт: Землетрясение --------------------------------------------

def ability_ult(player):
    if not _check_common(player): return
    if not check_cd(player, "ult", u"«Землетрясение»"): return

    world = player.getWorld()
    center = player.getLocation()

    world.playSound(center, Sound.ENTITY_GENERIC_EXPLODE, 1.5, 0.5)
    world.playSound(center, Sound.ENTITY_WITHER_BREAK_BLOCK, 1.2, 0.7)
    try:
        world.spawnParticle(Particle.EXPLOSION, center, 5, 2.0, 0.5, 2.0)
        world.spawnParticle(
            Particle.BLOCK, center.clone().add(0, 0.5, 0),
            120, ULT_RADIUS * 0.6, 0.5, ULT_RADIUS * 0.6,
            Material.DIRT.createBlockData()
        )
    except Exception:
        pass

    # Основной эффект: урон + подброс.
    for e in world.getNearbyEntities(center, ULT_RADIUS, ULT_RADIUS, ULT_RADIUS):
        if not isinstance(e, LivingEntity): continue
        if e.equals(player): continue
        try:
            e.damage(ULT_DAMAGE, player)
        except Exception:
            pass
        # Подброс.
        try:
            v = Vector(0.0, ULT_LAUNCH_Y, 0.0)
            h = e.getLocation().toVector().subtract(center.toVector())
            h.setY(0.0)
            if h.lengthSquared() > 0.01:
                h = h.normalize().multiply(0.3)
                v.setX(h.getX())
                v.setZ(h.getZ())
            e.setVelocity(v)
            if isinstance(e, Player):
                e.setFallDistance(0.0)
        except Exception:
            pass

    # 3 секунды полный стан Стальгорна.
    ult_end = now_tick() + ULT_STUN_DURATION
    try:
        player.getPersistentDataContainer().set(
            KEY_ULT_STUN, PersistentDataType.LONG, JLong(ult_end))
    except Exception:
        pass
    # Slowness с гигантским amp = обездвиживание, MiningFatigue = не может копать/бить эффективно.
    add_effect(player, E_SLOWNESS,    ULT_STUN_DURATION, 249, False, False)
    if E_MINING_FTG:
        add_effect(player, E_MINING_FTG, ULT_STUN_DURATION, 4, False, False)
    if E_JUMP:
        add_effect(player, E_JUMP,     ULT_STUN_DURATION, 128, False, False)
    # Чистим стан-метку через таймер.
    def _clear_stun():
        try:
            pdc2 = player.getPersistentDataContainer()
            if pdc2.has(KEY_ULT_STUN, PersistentDataType.LONG):
                try: pdc2.remove(KEY_ULT_STUN)
                except Exception: pass
        except Exception: pass
    scheduler.runTaskLater(_clear_stun, ULT_STUN_DURATION + 2)

    # Нестабильность земли: 5 сек, каждые 10 тиков освежаем эффекты
    # и рисуем "трещины" в зоне.
    def tick_instability(state=[0]):
        if not player.isValid(): return
        if state[0] >= ULT_INSTABILITY_DUR: return
        try:
            for e in world.getNearbyEntities(center, ULT_RADIUS, 3.0, ULT_RADIUS):
                if not isinstance(e, LivingEntity): continue
                if e.equals(player): continue
                add_effect(e, E_SLOWNESS, 25, 3, False, False)   # Slowness IV
                if E_MINING_FTG:
                    add_effect(e, E_MINING_FTG, 25, 0, False, False)
                # Наносим Тяжесть T3 для fall damage бонуса.
                _mark_heavy(e, 3)
        except Exception:
            pass
        # Визуал трещин.
        try:
            for dx in (-4, 0, 4):
                for dz in (-4, 0, 4):
                    if dx == 0 and dz == 0: continue
                    p = center.clone().add(dx, 0.1, dz)
                    world.spawnParticle(
                        Particle.BLOCK, p, 8, 0.6, 0.05, 0.6,
                        Material.COARSE_DIRT.createBlockData()
                    )
        except Exception:
            pass
        state[0] += 10
        scheduler.runTaskLater(tick_instability, 10)
    scheduler.runTaskLater(tick_instability, 5)

    player.sendMessage(u"§4§l✦ ЗЕМЛЕТРЯСЕНИЕ! §7— 3 сек. отдыха, 5 сек. нестабильности.")
    set_cd(player, "ult", CD_ULT)


# ============================================================================
# EVENT HANDLERS
# ============================================================================

def _is_flying_attacker(dmg):
    """Проверяет, летающий ли атакующий (или его снаряд)."""
    ent = dmg
    if hasattr(dmg, "getShooter"):
        try:
            s = dmg.getShooter()
            if s is not None: ent = s
        except Exception:
            pass
    for cls in _FLYING_TYPES:
        try:
            if isinstance(ent, cls):
                return True
        except Exception:
            pass
    return False


def on_damage_by(event):
    dmg = event.getDamager()
    ent = event.getEntity()

    # === Стальгорн бьёт ===
    if isinstance(dmg, Player) and is_steelgorn(dmg):
        # Проверяем, что во время ульт-стана Стальгорн не может атаковать.
        if _is_ult_stunned(dmg):
            event.setCancelled(True)
            try: dmg.sendActionBar(u"§8Земля ещё нестабильна.")
            except Exception: pass
            return
        ax = axe_in_hand(dmg)
        if ax is not None and isinstance(ent, LivingEntity) and not ent.equals(dmg):
            tier = get_axe_tier(ax)
            # Пассив «Сердце гор»: наложение Тяжести.
            _mark_heavy(ent, tier)

    # === Стальгорн получает ===
    if isinstance(ent, Player) and is_steelgorn(ent):
        # x2 от летающих (проверяем ДО каменной брони — множитель до редукции).
        if _is_flying_attacker(dmg):
            try:
                DM = EntityDamageEvent.DamageModifier
                base = event.getDamage(DM.BASE)
                event.setDamage(DM.BASE, base * FLYING_DMG_MULT)
            except Exception:
                event.setDamage(event.getDamage() * FLYING_DMG_MULT)

        # Каменная броня: первый удар — проходит только 40% (уменьшение 60%).
        try:
            pdc = ent.getPersistentDataContainer()
            if pdc.has(KEY_STONE_END, PersistentDataType.LONG) and \
               pdc.has(KEY_STONE_FIRST, PersistentDataType.BYTE):
                end = pdc.get(KEY_STONE_END, PersistentDataType.LONG)
                if now_tick() < end:
                    try:
                        DM = EntityDamageEvent.DamageModifier
                        base = event.getDamage(DM.BASE)
                        event.setDamage(DM.BASE, base * STONE_FIRST_HIT_PASSTHRU)
                    except Exception:
                        event.setDamage(event.getDamage() * STONE_FIRST_HIT_PASSTHRU)
                    try:
                        pdc.remove(KEY_STONE_FIRST)
                    except Exception: pass
                    try:
                        ent.sendActionBar(u"§8§l✦ КАМЕННЫЙ ПАНЦИРЬ §r§7поглотил 60% удара")
                    except Exception: pass
        except Exception:
            pass


def on_damage_generic(event):
    ent = event.getEntity()
    cause = event.getCause()

    # Fall damage бонус: цель с активной "Тяжестью" получает +25/35/50% от падения.
    if cause == EntityDamageEvent.DamageCause.FALL:
        htier = _get_heavy_tier(ent)
        if htier > 0:
            mult = TIER_HEAVY_FALL.get(htier, 1.25)
            try:
                DM = EntityDamageEvent.DamageModifier
                base = event.getDamage(DM.BASE)
                event.setDamage(DM.BASE, base * mult)
            except Exception:
                event.setDamage(event.getDamage() * mult)


def on_death(event):
    """Счётчик убийств мобов для прогрессии топора."""
    victim = event.getEntity()
    if isinstance(victim, Player): return   # игроки не считаются "мобами"
    killer = victim.getKiller()
    if killer is None or not isinstance(killer, Player): return
    if not is_steelgorn(killer): return
    ax = axe_in_hand(killer)
    if ax is None: return
    mobs, wood = get_progress(ax)
    mobs += 1
    set_progress(ax, mobs, wood)
    _try_upgrade(killer, ax)


def on_block_break(event):
    p = event.getPlayer()
    if not isinstance(p, Player): return
    if not is_steelgorn(p): return
    ax = axe_in_hand(p)
    if ax is None: return
    if not _is_wood_block(event.getBlock().getType()): return
    mobs, wood = get_progress(ax)
    wood += 1
    set_progress(ax, mobs, wood)
    _try_upgrade(p, ax)


def on_item_held(event):
    p = event.getPlayer()
    if not is_steelgorn(p): return
    def _later():
        try: _refresh_passive(p)
        except Exception: pass
    scheduler.runTaskLater(_later, 1)


def on_join(event):
    p = event.getPlayer()
    if not is_steelgorn(p): return
    _ensure_max_hp_reduction(p)
    _refresh_passive(p)


def on_respawn(event):
    p = event.getPlayer()
    if not is_steelgorn(p): return
    def _later():
        try:
            _ensure_max_hp_reduction(p)
            _refresh_passive(p)
        except Exception: pass
    scheduler.runTaskLater(_later, 5)


def on_drop(event):
    it = event.getItemDrop().getItemStack()
    if is_axe(it):
        event.setCancelled(True)
        try:
            event.getPlayer().sendMessage(u"§cТопор Стальгорна нельзя выбросить.")
        except Exception:
            pass


def on_swap_hands(event):
    """Запрет использования off-hand."""
    p = event.getPlayer()
    if not is_steelgorn(p): return
    event.setCancelled(True)
    try:
        p.sendActionBar(u"§8Стальгорн не может использовать вторую руку.")
    except Exception:
        pass


def on_inv_click(event):
    """Запрет положить что-либо в off-hand слот."""
    who = event.getWhoClicked()
    if not isinstance(who, Player): return
    if not is_steelgorn(who): return
    # rawSlot 45 у стандартного player inventory = off-hand
    try:
        raw = event.getRawSlot()
    except Exception:
        raw = -1
    if raw == 45:
        cursor = event.getCursor()
        cur_item = event.getCurrentItem()
        # Не даём положить и не даём вытащить пустое (пустое сразу — норм).
        if (cursor is not None and cursor.getType() != Material.AIR) or \
           (cur_item is not None and cur_item.getType() != Material.AIR):
            event.setCancelled(True)
            try:
                who.sendActionBar(u"§8Стальгорн не может использовать вторую руку.")
            except Exception: pass


# ============================================================================
# COMMAND
# ============================================================================

def _ability_from_alias(arg):
    a = _norm(arg)
    if a in (u"рывок", u"dash", u"lumberjack", u"лесоруб"):       return "dash"
    if a in (u"броня", u"каменная", u"stone", u"armor", u"панцирь"): return "stone"
    if a in (u"ульт", u"землетрясение", u"ult", u"ultimate", u"earth", u"землетрус"): return "ult"
    if a in (u"тир", u"tier"):                                    return "tier"
    return None

def cmd_steelgorn(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cКоманда только для игроков.")
        return True
    if not is_steelgorn(sender):
        sender.sendMessage(u"§cТы не Стальгорн.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7/steelgorn §f<способность>")
        sender.sendMessage(u"  §f/steelgorn рывок §7— рывок лесоруба (6 HP + Slow IV)")
        sender.sendMessage(u"  §f/steelgorn броня §7— каменная броня (8 сек)")
        sender.sendMessage(u"  §f/steelgorn ульт §7— землетрясение")
        return True

    ab = _ability_from_alias(args[0])

    # Тестовый режим: /steelgorn тир <n>
    if ab == "tier":
        if not _test_mode_on():
            sender.sendMessage(u"§cТестовый режим выключен.")
            return True
        if sender.getName().lower() not in FREE_CD_PLAYERS and not sender.isOp():
            sender.sendMessage(u"§cДоступно только в тест-режиме.")
            return True
        if len(args) < 2:
            sender.sendMessage(u"§7/steelgorn тир <1..3>")
            return True
        try:
            t = int(args[1])
        except Exception:
            sender.sendMessage(u"§cНеверный тир.")
            return True
        if not _set_tier(sender, t):
            sender.sendMessage(u"§cТир вне диапазона.")
            return True
        sender.sendMessage(u"§a✓ Тир §f" + str(t) + u"§a установлен.")
        return True

    if ab == "dash":  ability_dash(sender);  return True
    if ab == "stone": ability_stone(sender); return True
    if ab == "ult":   ability_ult(sender);   return True

    sender.sendMessage(u"§cНеизвестная способность.")
    return True


# ============================================================================
# TEST DISPATCHER KIT
# ============================================================================

def kit_entry(player, args):
    tier = 1
    if args and len(args) > 0:
        try:
            t = int(args[0])
            if 1 <= t <= 3: tier = t
        except Exception:
            pass
    give_kit(player, tier)
    _ensure_max_hp_reduction(player)
    _refresh_passive(player)
    player.sendMessage(u"§a✓ Комплект Стальгорна выдан (T%d)." % tier)


def _reset_state(player):
    """Полный сброс состояния (для /admin resethp)."""
    u = uid(player)
    # Снимаем все свои модификаторы по сохранённым ссылкам.
    _remove_max_hp_reduction(player)
    _remove_armor_bonus(player)
    kbm = _kb_mod.pop(u, None)
    if kbm is not None:
        try: _try_remove(player.getAttribute(ATTR_KNOCKBACK_RESISTANCE), kbm)
        except Exception: pass
    heavym = _heavy_mod.pop(u, None)   # если сам Стальгорн был под Тяжестью
    if heavym is not None:
        try: _try_remove(player.getAttribute(ATTR_MOVEMENT_SPEED), heavym)
        except Exception: pass

    cooldowns.pop(u, None)
    try:
        pdc = player.getPersistentDataContainer()
        for k in (KEY_STONE_END, KEY_ULT_STUN, KEY_HEAVY_END):
            if pdc.has(k, PersistentDataType.LONG):
                try: pdc.remove(k)
                except Exception: pass
        if pdc.has(KEY_STONE_FIRST, PersistentDataType.BYTE):
            try: pdc.remove(KEY_STONE_FIRST)
            except Exception: pass
        if pdc.has(KEY_HEAVY_TIER, PersistentDataType.INTEGER):
            try: pdc.remove(KEY_HEAVY_TIER)
            except Exception: pass
    except Exception:
        pass


def _set_tier(target_player, tier):
    if tier < 1 or tier > 3: return False
    if not replace_axe(target_player, tier, 0, 0):
        give_kit(target_player, tier)
    _refresh_passive(target_player)
    return True


# ============================================================================
# REGISTRATION
# ============================================================================

cmd_mgr.registerCommand(cmd_steelgorn, "steelgorn")

listener_mgr.registerListener(on_damage_by,      EntityDamageByEntityEvent)
listener_mgr.registerListener(on_damage_generic, EntityDamageEvent)
listener_mgr.registerListener(on_death,          EntityDeathEvent)
listener_mgr.registerListener(on_block_break,    BlockBreakEvent)
listener_mgr.registerListener(on_item_held,      PlayerItemHeldEvent)
listener_mgr.registerListener(on_join,           PlayerJoinEvent)
listener_mgr.registerListener(on_respawn,        PlayerRespawnEvent)
listener_mgr.registerListener(on_drop,           PlayerDropItemEvent)
listener_mgr.registerListener(on_swap_hands,     PlayerSwapHandItemsEvent)
listener_mgr.registerListener(on_inv_click,      InventoryClickEvent)

# JVM registry
_props = System.getProperties()

_REGISTRY_KEY = "pyspigot.character_kits"
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("steelgorn", (kit_entry, u"Стальгорн (Топор [тир 1..3], танк)"))

_OWNERS_KEY = "character_owners"
_owners = _props.get(_OWNERS_KEY)
if _owners is None:
    _owners = HashMap()
    _props.put(_OWNERS_KEY, _owners)
_owners.put("steelgorn", list(STEELGORN_NAMES))

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("steelgorn", _set_tier)

_RESET_KEY = "character_reset_functions"
_reset_reg = _props.get(_RESET_KEY)
if _reset_reg is None:
    _reset_reg = HashMap()
    _props.put(_RESET_KEY, _reset_reg)
_reset_reg.put("steelgorn", _reset_state)

# quest_tracker: публикуем stat-функцию для чтения счётчиков из PDC топора.
def _steelgorn_stat(player, key):
    """Возвращает счётчик 'mobs' или 'wood' из PDC текущего топора в инвентаре.
    Ищет топор с любым тиром — берёт самый высокий (обычно один)."""
    try:
        ax = axe_anywhere(player)
        if ax is None: return 0
        mobs, wood = get_progress(ax)
        if key == "mobs": return int(mobs)
        if key == "wood": return int(wood)
    except Exception:
        pass
    return 0

try:
    _props.put("quest_tracker.stat.steelgorn", _steelgorn_stat)
except Exception:
    pass

# Восстанавливаем пассив для уже онлайн-игроков (при hot-reload скрипта).
try:
    for _pl in Bukkit.getOnlinePlayers():
        if is_steelgorn(_pl):
            _ensure_max_hp_reduction(_pl)
            _refresh_passive(_pl)
except Exception:
    pass

Bukkit.getLogger().info("[steelgorn] Steelgorn loaded. Command: /steelgorn")

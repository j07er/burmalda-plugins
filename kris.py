# -*- coding: utf-8 -*-
"""
==============================================================================
  КРИС / Kris — Истинный клинок
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test kris             — выдать Сломанный клинок (Tier I)
  /kris <ability>        — способности
      сила | ульт
  /kris улучшить         — попытка улучшить клинок (расход материалов)
  /kris тир <1..5>       — [admin/тест] мгновенно выставить тир
------------------------------------------------------------------------------
  Тестовый аккаунт без КД: blueredtronce
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, GameMode
)
from org.bukkit.entity import (
    Player, LivingEntity, Animals, Monster, Villager, WanderingTrader
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent, PlayerItemConsumeEvent,
    PlayerRespawnEvent, PlayerBedEnterEvent, PlayerInteractEntityEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityTargetLivingEntityEvent,
    EntityPotionEffectEvent, PlayerDeathEvent
)
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.event.block import Action
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

# Range-атрибуты. Paper 1.21.4+ переименовал:
#   PLAYER_ENTITY_INTERACTION_RANGE -> ENTITY_INTERACTION_RANGE
#   PLAYER_BLOCK_INTERACTION_RANGE  -> BLOCK_INTERACTION_RANGE
def _range_attr(short_name, legacy_name):
    for candidate in (short_name, legacy_name):
        a = getattr(Attribute, candidate, None)
        if a is not None:
            return a
    return None

ATTR_ENTITY_RANGE = _range_attr("ENTITY_INTERACTION_RANGE", "PLAYER_ENTITY_INTERACTION_RANGE")
ATTR_BLOCK_RANGE  = _range_attr("BLOCK_INTERACTION_RANGE",  "PLAYER_BLOCK_INTERACTION_RANGE")

# DamageSource (Paper 1.20.5+)
_HAS_DAMAGE_API = True
try:
    from org.bukkit.damage import DamageSource, DamageType
except ImportError:
    _HAS_DAMAGE_API = False


# =============================================================================
#  CONSTANTS
# =============================================================================

KRIS_NAMES      = set([u"smellwhattherock", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_BLADE = NamespacedKey.fromString("kris:blade")
KEY_TIER  = NamespacedKey.fromString("kris:tier")
KEY_OWNER = NamespacedKey.fromString("kris:owner")

# Damage per tier (в HP: 1 сердце = 2 HP). Используется для лора.
TIER_DAMAGE = {
    1: 6.0,   # 3 сердца
    2: 7.0,   # 3.5
    3: 7.0,
    4: 7.0,
    5: 8.0,   # 4
}

# --- Истинный удар (новая механика) ---
TRUE_STRIKE_COOLDOWN = 3 * 20   # 3 секунды между истинными ударами
TRUE_STRIKE_DAMAGE   = 4.0      # 2 сердца чистого урона поверх обычного

# Время последнего истинного удара — uid -> tick.
true_strike_last = {}
TIER_NAME = {
    1: (u"§8§lСломанный клинок",       Material.STONE_SWORD),
    2: (u"§7§lВосстановленный клинок", Material.IRON_SWORD),
    3: (u"§f§lСветлый клинок",         Material.DIAMOND_SWORD),
    4: (u"§4§lТёмный клинок",          Material.NETHERITE_SWORD),
    5: (u"§d§lИстинный клинок",        Material.NETHERITE_SWORD),
}

# Cooldowns
CD_SOUL = 50 * 20
CD_ULT  = 2 * 60 * 20

SOUL_BARRIER_HP  = 8.0
SOUL_RESIST_DUR  = 10 * 20

ULT_RANGE     = 20.0
ULT_RADIUS    = 5.0
ULT_DAMAGE    = 12.0    # 6 hearts
ULT_STUN_DUR  = 3 * 20

# Attribute modifier UUID для дальности атаки (фиксированный, чтобы не дублировать)
RANGE_MOD_UUID = JUUID.fromString("11111111-2222-3333-4444-555555555555")
DAMAGE_MOD_UUID = JUUID.fromString("11111111-2222-3333-4444-777777777777")


# =============================================================================
#  EFFECT / ENCHANT LOOKUP
# =============================================================================

def _effect(k):  return Registry.EFFECT.get(NamespacedKey.minecraft(k))
def _enchant(k): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

E_POISON     = _effect("poison")
E_WITHER     = _effect("wither")
E_NIGHT_VIS  = _effect("night_vision")
E_RESIST     = _effect("resistance")
E_SLOWNESS   = _effect("slowness")
E_JUMP       = _effect("jump_boost")
E_MINING_FTG = _effect("mining_fatigue")
E_HUNGER     = _effect("hunger")
E_ABSORPTION = _effect("absorption")

ENC_SWEEPING = _enchant("sweeping_edge")


# =============================================================================
#  STATE
# =============================================================================

cooldowns    = {}
soul_shield  = {}   # (не используется после перехода на Absorption, оставлено на случай отладки)
stunned      = {}   # uid -> end_tick

# UUID мобов, которых Крис недавно ударил — им разрешён таргет на Криса.
aggroed_mobs = {}   # mob_uid -> expire_tick
AGGRO_DURATION = 30 * 20   # 30 сек агра после удара

# Re-entry guard для чистого урона: пока Крис внутри собственного deal_pure_damage,
# рекурсивные EntityDamageByEntityEvent от target.damage(...) должны пропускаться.
_pure_dmg_in_progress = set()   # UUID атакующих, чей клинок сейчас "стреляет"

# Пометка: у этих целей входящий MAGIC-урон должен обнулить ВСЕ модификаторы
# (Armor/Protection/Resistance/Absorption) — то есть быть настоящим true damage.
# Заполняется прямо перед deal_pure_damage, чистится сразу после.
_true_strike_targets = set()   # UUID целей


# =============================================================================
#  UTILS
# =============================================================================

def uid(e): return e.getUniqueId().toString()
def now_tick(): return long(System.currentTimeMillis() / 50)

def is_kris(player):
    name = player.getName().lower()
    if name not in KRIS_NAMES:
        return False
    # Тест-аккаунт blueredtronce: только если тестовый режим включён.
    if name == u"blueredtronce":
        return _test_mode_on()
    return True

def _test_mode_on():
    """Читает флаг тестового режима из общего JVM-реестра (публикуется admin_controller)."""
    try:
        v = System.getProperties().get("arena.test_mode")
        # По умолчанию — включён.
        return v is None or str(v) == "1"
    except Exception:
        return True

def is_free_cd(player):
    return player.getName().lower() in FREE_CD_PLAYERS

def is_silenced_by_demiurg(player):
    try:
        sil = System.getProperties().get("demiurg.silenced_uuids")
        if sil is None: return False
        return sil.contains(uid(player))
    except Exception:
        return False

def get_cd(player, name):
    if is_free_cd(player): return 0
    d = cooldowns.get(uid(player))
    if not d: return 0
    r = d.get(name, 0) - now_tick()
    return r if r > 0 else 0

def set_cd(player, name, ticks):
    if is_free_cd(player): return
    u = uid(player)
    if u not in cooldowns: cooldowns[u] = {}
    cooldowns[u][name] = now_tick() + ticks

def check_cd(player, name, label=None):
    r = get_cd(player, name)
    if r > 0:
        secs = (r + 19) // 20
        player.sendMessage(u"§cПерезарядка%s: §f%d§7 сек." % ((u" "+label) if label else u"", secs))
        return False
    return True

def add_effect(entity, pt, ticks, amp, ambient=False, particles=True):
    if pt is None: return
    entity.addPotionEffect(PotionEffect(pt, ticks, amp, ambient, particles, True))

def is_exposed_to_curse_sun(player):
    """True, если солнечная слабость Криса должна поддерживать горение."""
    try:
        world = player.getWorld()
        if world.getEnvironment().name() != "NORMAL" or not world.isDayTime():
            return False
        helmet = player.getInventory().getHelmet()
        if helmet is not None and helmet.getType() != Material.AIR:
            return False
        return player.getLocation().getBlock().getLightFromSky() >= 15
    except Exception:
        return False

def java_list(it):
    lst = ArrayList()
    for x in it: lst.add(x)
    return lst

def is_blade(item):
    if item is None or item.getType() == Material.AIR: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_BLADE, PersistentDataType.BYTE)

def get_blade_tier(item):
    m = item.getItemMeta()
    if m is None: return 0
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER): return 0
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)

def get_blade_owner(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def can_wield(player, item):
    if not is_kris(player): return False
    if not is_blade(item):  return False
    owner = get_blade_owner(item)
    return owner is None or owner == uid(player)

def blade_in_hand(player):
    it = player.getInventory().getItemInMainHand()
    if is_blade(it) and can_wield(player, it):
        return it
    return None

def blade_anywhere(player):
    for it in player.getInventory().getContents():
        if is_blade(it):
            return it
    return None


# =============================================================================
#  BLADE ITEM
# =============================================================================

def create_blade(tier, owner_uuid):
    if tier < 1: tier = 1
    if tier > 5: tier = 5
    name, mat = TIER_NAME[tier]
    it = ItemStack(mat, 1)
    m = it.getItemMeta()
    m.setDisplayName(name)
    lore = [
        u"§7Легендарный клинок Криса.",
        u"§8Тир: §f" + [u"", u"I", u"II", u"III", u"IV", u"V"][tier],
    ]
    # Показываем базу на всех тирах.
    _base_hp_by_tier = {1: 5.0, 2: 6.0, 3: 7.0, 4: 8.0, 5: 10.0}
    _base = _base_hp_by_tier.get(tier, 5.0)
    lore.append(u"§8Базовый урон: §f%.0f❤" % (_base / 2.0))
    lore.append(u"§d✦ Истинный удар: §f+2❤ §7чистого раз в §f3 §7сек.")
    lore.append(u"")
    lore.append(u"§8Только Крис может использовать этот клинок.")
    m.setLore(java_list(lore))
    m.setUnbreakable(True)

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_BLADE, PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_TIER,  PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER, PersistentDataType.STRING,  owner_uuid)

    # Sweeping Edge по тиру.
    if ENC_SWEEPING is not None:
        m.addEnchant(ENC_SWEEPING, min(5, tier), True)

    # === КРИТИЧНО ===
    # Если ниже добавим ЛЮБОЙ AttributeModifier с EquipmentSlot.HAND
    # (RANGE или DAMAGE), Minecraft автоматически СКРЫВАЕТ дефолтные
    # модификаторы материала — ATTACK_DAMAGE меча превращается из 5/6/7/8
    # обратно в базовые 1.0 HP. Поэтому мы обязаны САМИ вернуть
    # ATTACK_DAMAGE = (ванильное значение материала) через свой модификатор.
    # Плюс атаковую скорость возвращаем — иначе меч будет как топор (1.6 → 1.6 всё равно, но явно).
    #
    # Ванильные ATTACK_DAMAGE (base 1.0 + modifier):
    #   wooden/stone:  base 1 + mod +4  = 5.0  (T1: Stone)
    #   iron:          base 1 + mod +5  = 6.0  (T2)
    #   diamond:       base 1 + mod +6  = 7.0  (T3)
    #   netherite:     base 1 + mod +7  = 8.0  (T4, T5)
    # Скорость атаки: base 4.0 + mod -2.4 = 1.6 для всех мечей.
    needs_default_restore = (tier >= 2)
    if needs_default_restore:
        vanilla_dmg_by_mat = {
            Material.WOODEN_SWORD:    4.0,
            Material.STONE_SWORD:     4.0,
            Material.IRON_SWORD:      5.0,
            Material.GOLDEN_SWORD:    4.0,
            Material.DIAMOND_SWORD:   6.0,
            Material.NETHERITE_SWORD: 7.0,
        }
        base_bonus = vanilla_dmg_by_mat.get(mat, 5.0)
        # Дополнительный бонус для T5 (+2 сверху итого 10 HP).
        if tier >= 5:
            base_bonus += 2.0
        try:
            attr_dmg = ATTR_ATTACK_DAMAGE
            mod_dmg = AttributeModifier(
                DAMAGE_MOD_UUID, "kris_dmg", base_bonus,
                AttributeModifier.Operation.ADD_NUMBER,
                EquipmentSlot.HAND
            )
            m.addAttributeModifier(attr_dmg, mod_dmg)
        except Exception as ex:
            Bukkit.getLogger().warning("[kris] damage attr failed: " + str(ex))
        # Возвращаем ATTACK_SPEED.
        try:
            attr_spd = ATTR_ATTACK_SPEED
            spd_uuid = JUUID.fromString("11111111-2222-3333-4444-888888888888")
            mod_spd = AttributeModifier(
                spd_uuid, "kris_spd", -2.4,
                AttributeModifier.Operation.ADD_NUMBER,
                EquipmentSlot.HAND
            )
            m.addAttributeModifier(attr_spd, mod_spd)
        except Exception as ex:
            Bukkit.getLogger().warning("[kris] attack speed attr failed: " + str(ex))

    # Range +1 для тиров II+.
    if tier >= 2 and ATTR_ENTITY_RANGE is not None:
        try:
            mod = AttributeModifier(
                RANGE_MOD_UUID, "kris_range", 1.0,
                AttributeModifier.Operation.ADD_NUMBER,
                EquipmentSlot.HAND
            )
            m.addAttributeModifier(ATTR_ENTITY_RANGE, mod)
        except Exception as ex:
            Bukkit.getLogger().warning("[kris] range attribute failed: " + str(ex))

    it.setItemMeta(m)
    return it


def replace_blade(player, tier):
    inv = player.getInventory()
    contents = inv.getContents()
    for i in range(len(contents)):
        if is_blade(contents[i]):
            inv.setItem(i, create_blade(tier, uid(player)))
            return True
    return False


def give_kit(player, tier=1):
    inv = player.getInventory()
    placed = False
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_blade(tier, uid(player)))
            placed = True
            break
    if not placed:
        inv.setItem(0, create_blade(tier, uid(player)))
    player.sendMessage(u"§d§l✦ §rКлинок вручён Крису. §7Тир §f" +
                       [u"", u"I", u"II", u"III", u"IV", u"V"][tier])


def kit_entry(player, args_list):
    if not is_kris(player):
        player.sendMessage(u"§cТолько Крис достоин Истинного клинка.")
        return
    tier = 1
    if args_list and len(args_list) >= 1:
        try:
            tier = int(args_list[0])
            if tier < 1 or tier > 5: tier = 1
        except (ValueError, TypeError):
            tier = 1
    give_kit(player, tier)


# =============================================================================
#  UPGRADE
# =============================================================================

# Каждый тир: словарь material_name (str) -> count, а также special:
#   "xp_levels": N — требуется уровней опыта
#   "either": [(mat, count), (mat, count)] — принимается ЛЮБОЙ из вариантов
UPGRADE_RECIPES = {
    2: {
        "items": {"IRON_INGOT": 16, "REDSTONE": 8, "DIAMOND": 1},
    },
    3: {
        "items": {"DIAMOND": 8, "OBSIDIAN": 16, "QUARTZ": 4},
    },
    4: {
        "items": {"NETHERITE_INGOT": 1, "GOLD_INGOT": 16},
        "either": [("ANCIENT_DEBRIS", 8), ("NETHERITE_SCRAP", 8)],
    },
    5: {
        "items": {"NETHERITE_INGOT": 2},
        "either": [("HEART_OF_THE_SEA", 1), ("TOTEM_OF_UNDYING", 1)],
        "xp_levels": 32,
    },
}

def _count_items(player, mat_name):
    m = Material.getMaterial(mat_name)
    if m is None: return 0
    total = 0
    for it in player.getInventory().getContents():
        if it is not None and it.getType() == m:
            total += it.getAmount()
    return total

def _remove_items(player, mat_name, amount):
    m = Material.getMaterial(mat_name)
    if m is None: return False
    inv = player.getInventory()
    need = amount
    contents = inv.getContents()
    for i in range(len(contents)):
        it = contents[i]
        if it is None or it.getType() != m: continue
        take = min(need, it.getAmount())
        if take >= it.getAmount():
            inv.setItem(i, ItemStack(Material.AIR))
        else:
            it.setAmount(it.getAmount() - take)
            inv.setItem(i, it)
        need -= take
        if need <= 0: break
    return need <= 0

def try_upgrade(player):
    blade = blade_anywhere(player)
    if blade is None:
        player.sendMessage(u"§cКлинок не найден в инвентаре.")
        return
    cur_tier = get_blade_tier(blade)
    next_tier = cur_tier + 1
    if next_tier > 5:
        player.sendMessage(u"§7Клинок уже в финальной форме (Тир V).")
        return
    recipe = UPGRADE_RECIPES.get(next_tier)
    if recipe is None:
        player.sendMessage(u"§cРецепт для тира " + str(next_tier) + u" не задан.")
        return

    # Проверка обычных предметов.
    items = recipe.get("items", {})
    missing = []
    for mat_name, need in items.items():
        have = _count_items(player, mat_name)
        if have < need:
            missing.append(u"§7- §f" + mat_name + u"§7: " + str(have) + u"/" + str(need))

    # either
    either = recipe.get("either")
    either_choice = None
    if either:
        for mat_name, need in either:
            if _count_items(player, mat_name) >= need:
                either_choice = (mat_name, need)
                break
        if either_choice is None:
            opts = u" или ".join([o[0] + u" x" + str(o[1]) for o in either])
            missing.append(u"§7- §f" + opts)

    # XP
    xp_needed = recipe.get("xp_levels", 0)
    if xp_needed > 0 and player.getLevel() < xp_needed:
        missing.append(u"§7- §fОпыт§7: " + str(player.getLevel()) + u"/" + str(xp_needed))

    if missing:
        player.sendMessage(u"§cНедостаточно ресурсов для Тира " +
                           [u"", u"I", u"II", u"III", u"IV", u"V"][next_tier] + u":")
        for line in missing:
            player.sendMessage(line)
        return

    # Всё есть — забираем.
    for mat_name, need in items.items():
        _remove_items(player, mat_name, need)
    if either_choice is not None:
        _remove_items(player, either_choice[0], either_choice[1])
    if xp_needed > 0:
        player.setLevel(player.getLevel() - xp_needed)

    replace_blade(player, next_tier)
    player.sendMessage(u"§d§l✦ Клинок улучшен до Тира " +
                       [u"", u"I", u"II", u"III", u"IV", u"V"][next_tier] + u"§7.")
    player.getWorld().playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)


# =============================================================================
#  PURE DAMAGE
# =============================================================================

def deal_pure_damage(target, amount, attacker):
    """Настоящий true damage: игнорирует ВСЁ (Armor, Protection, Resistance,
    Absorption). Работает через штатный target.damage() с DamageSource.MAGIC,
    но параллельно в EntityDamageEvent обнуляем все DamageModifier'ы."""
    if not isinstance(target, LivingEntity): return
    tid = uid(target)
    _true_strike_targets.add(tid)
    try:
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
        try:
            target.damage(amount, attacker)
            return
        except Exception:
            pass
        # Fallback: прямой setHealth (Absorption не учтётся).
        new_hp = target.getHealth() - amount
        if new_hp <= 0.0:
            try: target.damage(target.getMaxHealth() * 2, attacker)
            except Exception: target.setHealth(0.0)
        else:
            target.setHealth(new_hp)
    finally:
        # Убираем метку в следующем тике: событие уже отработало.
        try:
            def _clear():
                _true_strike_targets.discard(tid)
            scheduler.runTaskLater(_clear, 1)
        except Exception:
            _true_strike_targets.discard(tid)


# =============================================================================
#  ABILITIES
# =============================================================================

def ability_soul(player):
    if not check_cd(player, "soul", u"«Сила души»"):
        return
    # Снимаем негативные эффекты.
    harmful = [E_POISON, E_WITHER, E_SLOWNESS, E_MINING_FTG, E_HUNGER,
               _effect("blindness"), _effect("darkness"),
               _effect("weakness"), _effect("nausea")]
    for pt in harmful:
        if pt is not None and player.hasPotionEffect(pt):
            player.removePotionEffect(pt)

    # Тушим обычный огонь, горение после атаки и остаточное горение после лавы.
    # Прямое солнце остаётся врождённой слабостью и не очищается способностью.
    if not is_exposed_to_curse_sun(player):
        player.setFireTicks(0)

    # Барьер — нативная Absorption II (4 золотых сердечка = 8 HP).
    # Ставим на всю длительность (10 сек), Resistance I тоже 10 сек.
    add_effect(player, E_ABSORPTION, SOUL_RESIST_DUR, 1)   # II
    add_effect(player, E_RESIST,     SOUL_RESIST_DUR, 0)   # I
    player.setAbsorptionAmount(8.0)                        # гарантированно 8 HP

    world = player.getWorld()
    world.spawnParticle(Particle.SOUL, player.getLocation().add(0, 1, 0), 30, 0.6, 1.0, 0.6, 0.05)
    world.spawnParticle(Particle.HEART, player.getLocation().add(0, 2, 0), 5, 0.4, 0.2, 0.4)
    world.playSound(player.getLocation(), Sound.BLOCK_BEACON_ACTIVATE, 0.9, 1.6)
    player.sendMessage(u"§d§l✦ Сила души §r§7— §f8 HP §7щита + Сопротивление I на 10 сек.")
    set_cd(player, "soul", CD_SOUL)


def _find_target_in_cone(player, max_range, cone_dot=0.85, prefer_players=True):
    """Ищет ближайшую цель в конусе взгляда. Приоритет — игроки.
       cone_dot: косинус угла раствора конуса (0.85 ~ 32°)."""
    eye = player.getEyeLocation()
    dir_v = eye.getDirection().normalize()
    world = player.getWorld()

    best_player = None
    best_player_d = max_range * max_range + 1
    best_mob = None
    best_mob_d = max_range * max_range + 1

    for e in world.getNearbyEntities(eye, max_range, max_range, max_range):
        if not isinstance(e, LivingEntity):
            continue
        if e.equals(player):
            continue
        # Вектор от глаз до центра сущности.
        to_e = e.getLocation().add(0, e.getHeight() * 0.5, 0).toVector().subtract(eye.toVector())
        d2 = to_e.lengthSquared()
        if d2 > max_range * max_range:
            continue
        # Угол между взглядом и направлением на цель.
        try:
            dot = to_e.normalize().dot(dir_v)
        except Exception:
            continue
        if dot < cone_dot:
            continue

        if isinstance(e, Player):
            if d2 < best_player_d:
                best_player_d = d2
                best_player = e
        else:
            if d2 < best_mob_d:
                best_mob_d = d2
                best_mob = e

    if prefer_players and best_player is not None:
        return best_player
    return best_mob if best_mob is not None else best_player


def ability_ultimate(player):
    if not check_cd(player, "ult", u"«Тёмный вызов»"):
        return

    # Приоритет: 1) точный raytrace, если попал → используем; иначе:
    # 2) игрок в конусе взгляда 20 блоков; 3) моб в конусе взгляда 20 блоков.
    target = None
    result = player.rayTraceEntities(int(ULT_RANGE))
    if result is not None and result.getHitEntity() is not None:
        e = result.getHitEntity()
        if isinstance(e, LivingEntity) and not e.equals(player):
            target = e

    if target is None:
        target = _find_target_in_cone(player, ULT_RANGE, cone_dot=0.80, prefer_players=True)

    if target is None:
        player.sendMessage(u"§cНет цели в 20 блоках.")
        return

    set_cd(player, "ult", CD_ULT)
    world = player.getWorld()

    # Прыжок-телепорт: короткая анимация полёта через частицы.
    src = player.getLocation().add(0, 1, 0)
    dst = target.getLocation()
    steps = 12
    dv = dst.toVector().subtract(src.toVector()).multiply(1.0 / steps)
    p = src.clone()
    for i in range(steps):
        p.add(dv)
        world.spawnParticle(Particle.SOUL_FIRE_FLAME, p, 3, 0.15, 0.15, 0.15, 0.0)

    # Телепорт за спину цели.
    dir_v = target.getLocation().getDirection().multiply(-1.5)
    land = target.getLocation().add(dir_v)
    land.setYaw(target.getLocation().getYaw())
    land.setPitch(0.0)
    player.teleport(land)
    player.setFallDistance(0.0)

    # AoE удар.
    world.spawnParticle(Particle.EXPLOSION, land, 3, 1.0, 0.3, 1.0)
    world.spawnParticle(Particle.LARGE_SMOKE, land, 40, 3.0, 0.5, 3.0, 0.05)
    world.playSound(land, Sound.ENTITY_WITHER_HURT, 1.0, 0.6)
    world.playSound(land, Sound.ENTITY_GENERIC_EXPLODE, 0.8, 1.3)

    for e in world.getNearbyEntities(land, ULT_RADIUS, ULT_RADIUS, ULT_RADIUS):
        if not isinstance(e, LivingEntity): continue
        if e.equals(player): continue
        try:
            e.damage(ULT_DAMAGE, player)
        except Exception:
            pass
        # Помечаем каждого мобика в AoE как оглушённого. Таргетинг — на усмотрение vanilla.
        add_effect(e, E_SLOWNESS,   ULT_STUN_DUR, 249, False, False)
        add_effect(e, E_JUMP,       ULT_STUN_DUR, 128, False, False)
        add_effect(e, E_MINING_FTG, ULT_STUN_DUR, 4)
        stunned[uid(e)] = now_tick() + ULT_STUN_DUR

    player.sendMessage(u"§d§l✦ Тёмный вызов §r§7— цель поражена.")


# =============================================================================
#  ON-HIT: PURE DAMAGE + EFFECTS
# =============================================================================

def _on_hit_effects(tier, victim):
    """Эффекты по тиру при попадании клинком."""
    if not isinstance(victim, LivingEntity): return
    if tier == 1:
        add_effect(victim, E_POISON, 5 * 20, 0)
    elif tier == 2:
        add_effect(victim, E_POISON, 5 * 20, 0)
        add_effect(victim, E_WITHER, 5 * 20, 1)
    else:   # 3, 4, 5
        add_effect(victim, E_WITHER, 5 * 20, 1)


def on_damage_by(event):
    dmg = event.getDamager()
    ent = event.getEntity()

    # ---- Крис бьёт клинком: обычный удар + истинный удар раз в 5 сек ----
    if isinstance(dmg, Player):
        if uid(dmg) in _pure_dmg_in_progress:
            return

        blade = blade_in_hand(dmg)
        if blade is not None and isinstance(ent, LivingEntity) and not ent.equals(dmg):
            tier = get_blade_tier(blade)

            # ВАНИЛЬНЫЙ УРОН НЕ ТРОГАЕМ — пусть работают зачарования (Sharpness/
            # Sweeping/Fire Aspect), баффы (Strength), Weakness и т.д.
            # Только добавляем on-hit эффекты.
            _on_hit_effects(tier, ent)

            # Истинный удар: раз в 5 секунд следующий удар добавляет 4 сердца
            # чистого урона поверх обычного.
            u = uid(dmg)
            last = true_strike_last.get(u, 0)
            if now_tick() - last >= TRUE_STRIKE_COOLDOWN:
                true_strike_last[u] = now_tick()
                # Даём ванильному урону сначала пройти — потом добавляем
                # 4 сердца пробойного отдельным damage-source.
                def do_true_strike():
                    if not ent.isValid() or ent.isDead():
                        return
                    deal_pure_damage(ent, TRUE_STRIKE_DAMAGE, dmg)
                    world = ent.getWorld()
                    world.spawnParticle(Particle.CRIT, ent.getLocation().add(0, 1, 0),
                                         25, 0.4, 0.5, 0.4, 0.05)
                    world.spawnParticle(Particle.SOUL, ent.getLocation().add(0, 1, 0),
                                         15, 0.3, 0.4, 0.3, 0.03)
                    world.playSound(ent.getLocation(), Sound.ITEM_TRIDENT_HIT, 1.0, 0.7)
                    if isinstance(dmg, Player):
                        dmg.sendActionBar(u"§d§l✦ ИСТИННЫЙ УДАР §r§7— +4❤ чистого урона")
                scheduler.runTaskLater(do_true_strike, 1)
            return

    # ---- Крис получает урон
    if isinstance(ent, Player) and is_kris(ent):
        # (Барьер теперь — нативный Absorption II из ability_soul, обработка не нужна.)

        # Отражение 10% на живого атакующего.
        # Также защита от рекурсии: не отражаем, если этот атакующий уже "в процессе" урона.
        if isinstance(dmg, LivingEntity) and not dmg.equals(ent):
            if uid(dmg) in _pure_dmg_in_progress:
                return
            reflect = event.getFinalDamage() * 0.20
            if reflect > 0:
                _pure_dmg_in_progress.add(uid(ent))
                try:
                    dmg.damage(reflect, ent)
                except Exception:
                    pass
                finally:
                    _pure_dmg_in_progress.discard(uid(ent))


def on_damage_generic(event):
    ent = event.getEntity()

    # === Настоящий true damage: обнуляем ВСЕ модификаторы ===
    # Если сейчас идёт наш deal_pure_damage по этой цели — Armor, Protection,
    # Resistance и Absorption не должны снижать урон.
    try:
        if uid(ent) in _true_strike_targets:
            DM = EntityDamageEvent.DamageModifier
            for mod_name in ("ARMOR", "MAGIC", "RESISTANCE", "ABSORPTION",
                             "HARD_HAT", "BLOCKING", "FREEZING"):
                try:
                    mod = getattr(DM, mod_name)
                    if event.isApplicable(mod):
                        event.setDamage(mod, 0.0)
                except Exception:
                    pass
    except Exception:
        pass

    if not isinstance(ent, Player): return
    if not is_kris(ent): return
    # +15% входящего урона. Не применяем к событию, порождённому нашим же
    # отражением/рекурсией, чтобы не накручивать множитель.
    if uid(ent) in _pure_dmg_in_progress:
        return
    event.setDamage(event.getDamage() * 1.15)


# =============================================================================
#  PASSIVES
# =============================================================================

def _is_wither_type(potion_type):
    """Надёжное сравнение типа эффекта с 'wither' по ключу — не по объекту."""
    if potion_type is None:
        return False
    try:
        k = potion_type.getKey()
        if k is not None and k.getKey() == "wither":
            return True
    except Exception:
        pass
    try:
        if potion_type.getName() == "WITHER":
            return True
    except Exception:
        pass
    return False


def _is_hunger_type(potion_type):
    if potion_type is None:
        return False
    try:
        k = potion_type.getKey()
        if k is not None and k.getKey() == "hunger":
            return True
    except Exception:
        pass
    try:
        if potion_type.getName() == "HUNGER":
            return True
    except Exception:
        pass
    return False


def _strip_wither(player):
    """Снимает Wither с игрока перебором активных эффектов по ключу.
       Работает даже если объект E_WITHER != экземпляру из Registry (совместимость с Purpur)."""
    to_remove = []
    for eff in player.getActivePotionEffects():
        if _is_wither_type(eff.getType()):
            to_remove.append(eff.getType())
    for pt in to_remove:
        try:
            player.removePotionEffect(pt)
        except Exception:
            pass


def _wither_tick():
    """Каждый тик снимает Wither с Криса. Один игрок — накладных расходов почти нет."""
    try:
        for pl in Bukkit.getOnlinePlayers():
            if is_kris(pl):
                _strip_wither(pl)
    except Exception as ex:
        Bukkit.getLogger().warning("[kris] wither tick: " + str(ex))
    scheduler.runTaskLater(_wither_tick, 1)


def _passives_tick():
    """Тик каждые 20 тиков: ночное зрение, солнце, огонь на солнце, ремонт стана."""
    try:
        # Чистим просроченные агра-метки мобов.
        nt = now_tick()
        for k in list(aggroed_mobs.keys()):
            if aggroed_mobs[k] <= nt:
                aggroed_mobs.pop(k, None)

        for pl in Bukkit.getOnlinePlayers():
            if not is_kris(pl): continue
            # Ночное зрение (постоянно).
            add_effect(pl, E_NIGHT_VIS, 400, 0, ambient=True, particles=False)
            # Wither чистим каждый тик отдельным циклом (_wither_tick), здесь — просто ещё раз для страховки.
            _strip_wither(pl)
            # Горит на солнце: только в оверворлде, днём, sky-light 15, нет шлема.
            world = pl.getWorld()
            if is_exposed_to_curse_sun(pl) and pl.getFireTicks() < 40:
                pl.setFireTicks(80)

            # Друж-мобы разбегаются: лёгкий отгон в радиусе 6 блоков.
            if nt % 40 == 0:
                for e in world.getNearbyEntities(pl.getLocation(), 6.0, 4.0, 6.0):
                    if isinstance(e, Animals):
                        away = e.getLocation().toVector().subtract(pl.getLocation().toVector())
                        if away.lengthSquared() > 0.01:
                            away = away.normalize().multiply(0.35)
                            away.setY(0.15)
                            e.setVelocity(away)
    except Exception as ex:
        Bukkit.getLogger().warning("[kris] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


def on_target(event):
    """Хостильные и нейтральные мобы игнорируют Криса, пока он первым не проявит агрессию.
       Разрешаем таргет только по 'атакующим' reasons — та самая версия,
       где обычные мобы аггрятся после удара, а крипер иногда багуется."""
    target = event.getTarget()
    if not isinstance(target, Player): return
    if not is_kris(target): return

    reason = event.getReason()
    ok_reasons = ("TARGET_ATTACKED_ENTITY", "TARGET_ATTACKED_OWNER",
                  "TARGET_ATTACKED_NEARBY_ENTITY")
    if reason.name() in ok_reasons:
        return

    event.setCancelled(True)
    try:
        event.setTarget(None)
    except Exception:
        pass


def on_potion_effect(event):
    """Отмена ADDED только для Wither и еда-Hunger. Всё остальное — нативное."""
    ent = event.getEntity()
    if not isinstance(ent, Player): return
    if not is_kris(ent): return

    try:
        action = event.getAction().name()
    except Exception:
        action = ""
    if action != "ADDED":
        return

    new_effect = event.getNewEffect()
    if new_effect is None:
        return
    t = new_effect.getType()

    # Полный иммунитет к Wither.
    if _is_wither_type(t):
        event.setCancelled(True)
        return

    # Голод от еды — отменяем.
    try:
        cause = event.getCause().name()
    except Exception:
        cause = ""
    if _is_hunger_type(t) and cause == "FOOD":
        event.setCancelled(True)
        return


MEAT_TYPES = set([
    Material.PORKCHOP, Material.COOKED_PORKCHOP,
    Material.BEEF, Material.COOKED_BEEF,
    Material.CHICKEN, Material.COOKED_CHICKEN,
    Material.MUTTON, Material.COOKED_MUTTON,
    Material.RABBIT, Material.COOKED_RABBIT,
    Material.COD, Material.COOKED_COD,
    Material.SALMON, Material.COOKED_SALMON,
    Material.PUFFERFISH, Material.TROPICAL_FISH,
    # ROTTEN_FLESH и SPIDER_EYE — НЕ мясо для Криса, гнилая плоть = обычная еда.
])

def on_consume(event):
    p = event.getPlayer()
    if not is_kris(p): return
    mat = event.getItem().getType()
    if mat in MEAT_TYPES:
        # Голод II на 8 сек, cause=PLUGIN — не режется нашим же on_potion_effect.
        def apply():
            if p.isOnline():
                add_effect(p, E_HUNGER, 8 * 20, 1)
                p.sendMessage(u"§8Мясная пища не по нутру...")
        scheduler.runTaskLater(apply, 2)


def on_bed_enter(event):
    p = event.getPlayer()
    if not is_kris(p): return
    result = event.getBedEnterResult()
    if result is not None and result.name() == "NOT_SAFE":
        # Позволяем засыпать рядом с мобами.
        try:
            from org.bukkit.event import Event as _E
            event.setUseBed(_E.Result.ALLOW)
        except Exception:
            pass


def on_villager_trade(event):
    p = event.getPlayer()
    if not is_kris(p): return
    ent = event.getRightClicked()
    if isinstance(ent, Villager) or isinstance(ent, WanderingTrader):
        event.setCancelled(True)
        p.sendMessage(u"§8Торговцы отказываются иметь с тобой дело.")


# =============================================================================
#  STUN / SILENCE VIA MOVE / INTERACT
# =============================================================================

def _is_stunned(u):
    if u not in stunned: return False
    if now_tick() >= stunned[u]:
        stunned.pop(u, None)
        return False
    return True

def on_interact(event):
    p = event.getPlayer()
    if _is_stunned(uid(p)):
        event.setCancelled(True)
        return

    if event.getHand() != EquipmentSlot.HAND: return
    item = event.getItem()
    if item is None or not is_blade(item): return
    if not can_wield(p, item):
        event.setCancelled(True)
        p.sendMessage(u"§cКлинок отвергает тебя.")


# =============================================================================
#  DROP / DEATH / RESPAWN — auto-return
# =============================================================================

def on_drop(event):
    it = event.getItemDrop().getItemStack()
    if is_blade(it):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cИстинный клинок нельзя выбросить.")

_need_respawn = set()

def on_death(event):
    """
    Клинок Криса — soulbound-предмет: он не должен дропаться на землю.
    Но убирать его из event.getDrops() здесь НЕЛЬЗЯ, потому что soulbound.py
    сам обрабатывает все предметы с PDC-меткой "kris:blade" (наш неймспейс
    входит в CUSTOM_NAMESPACES) и сохраняет их со ВСЕМИ PDC-данными,
    включая tier. Затем возвращает на PlayerRespawnEvent.

    Раньше здесь стояло event.getDrops().remove(blade) + give_kit(p, 1)
    в on_respawn — это ломало сохранение тира: клинок пропадал до того,
    как soulbound.on_death его увидел, а на респе создавался новый T1.

    Теперь мы просто НЕ трогаем drops. Soulbound делает свою работу.
    """
    return


def on_respawn(event):
    """
    Тоже ничего не делаем: soulbound.on_respawn вернёт клинок с исходным
    tier'ом через 2 тика после респа. Мы вмешиваемся ТОЛЬКО если игрок
    действительно потерял клинок каким-то иным путём (напр. глюк
    инвентаря) — с задержкой 40 тиков (2 сек), чтобы soulbound успел
    отработать первым.
    """
    p = event.getPlayer()
    if not is_kris(p): return

    def _check_and_restore():
        try:
            if not p.isOnline(): return
            if blade_anywhere(p) is None:
                # Soulbound не восстановил (или предмет никогда не выдавался).
                # Даём стартовый набор T1.
                give_kit(p, 1)
                p.sendMessage(u"§7[Крис] Клинок восстановлен на I тире (базовый).")
        except Exception:
            pass

    scheduler.runTaskLater(_check_and_restore, 40)


def on_inv_click(event):
    # Запрещаем класть клинок в контейнеры.
    it = event.getCurrentItem()
    cursor = event.getCursor()
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        if (it is not None and is_blade(it)) or (cursor is not None and is_blade(cursor)):
            event.setCancelled(True)
            event.getWhoClicked().sendMessage(u"§cКлинок нельзя убрать в контейнер.")


# =============================================================================
#  COMMAND /kris
# =============================================================================

def cmd_kris(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cКоманда доступна только игрокам.")
        return True
    if not is_kris(sender):
        sender.sendMessage(u"§cТолько Крис может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование: §f/kris <способность>")
        sender.sendMessage(u"§7Доступно: §fсила§7, §fульт§7, §fулучшить§7, §fтир <n>§7")
        return True

    sub = args[0].lower()

    # Улучшение и тир — не блокируются "Тишиной".
    if sub in (u"улучшить", u"upgrade"):
        try_upgrade(sender)
        return True

    if sub in (u"тир", u"tier"):
        if not _test_mode_on():
            sender.sendMessage(u"§cТестовый режим выключен — команда недоступна.")
            return True
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/kris тир <1..5>")
            return True
        try:
            t = int(args[1])
        except ValueError:
            sender.sendMessage(u"§cТир должен быть числом.")
            return True
        if t < 1 or t > 5:
            sender.sendMessage(u"§cТиры: 1..5.")
            return True
        if not replace_blade(sender, t):
            give_kit(sender, t)
        else:
            sender.sendMessage(u"§aТир клинка выставлен: §f" +
                               [u"", u"I", u"II", u"III", u"IV", u"V"][t])
        return True

    # Способности — проверяем "Закон Тишины".
    if is_silenced_by_demiurg(sender):
        sender.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return True

    if blade_anywhere(sender) is None:
        sender.sendMessage(u"§cДля использования способностей нужен клинок в инвентаре.")
        return True

    if sub in (u"сила", u"soul", u"силадуши", u"душа"):
        ability_soul(sender)
    elif sub in (u"ульт", u"ультимейт", u"ult", u"ultimate", u"вызов"):
        ability_ultimate(sender)
    else:
        sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
        sender.sendMessage(u"§7Доступно: §fсила§7, §fульт§7, §fулучшить§7, §fтир <n>§7")
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_kris, "kris")

listener_mgr.registerListener(on_damage_by,       EntityDamageByEntityEvent)
listener_mgr.registerListener(on_damage_generic,  EntityDamageEvent)
listener_mgr.registerListener(on_target,          EntityTargetLivingEntityEvent)
listener_mgr.registerListener(on_potion_effect,   EntityPotionEffectEvent)
listener_mgr.registerListener(on_consume,         PlayerItemConsumeEvent)
listener_mgr.registerListener(on_bed_enter,       PlayerBedEnterEvent)
listener_mgr.registerListener(on_villager_trade,  PlayerInteractEntityEvent)
listener_mgr.registerListener(on_interact,        PlayerInteractEvent)
listener_mgr.registerListener(on_drop,            PlayerDropItemEvent)
listener_mgr.registerListener(on_death,           PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,         PlayerRespawnEvent)
listener_mgr.registerListener(on_inv_click,       InventoryClickEvent)

_passives_tick()
_wither_tick()

# Регистрация набора в JVM-глобальном реестре /test.
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("kris", (kit_entry, u"Крис (Истинный клинок [тир 1..5])"))

# --- Публикация владельцев для admin-скрипта ---
_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("kris", list(KRIS_NAMES))

# --- Публикация функции смены тира для admin-скрипта ---
def _kris_set_tier(target_player, tier):
    if tier < 1 or tier > 5:
        return False
    if not replace_blade(target_player, tier):
        give_kit(target_player, tier)
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("kris", _kris_set_tier)

# --- Публикация в каталог Зеркала Души Арчера ---
def _kris_mirror_blade(owner_uuid):
    # I тир Криса — каменный меч + Sweeping Edge I.
    # Poison I — это on-hit механика скрипта Криса, а не зачарование, поэтому
    # в копию она не переходит (по ТЗ Зеркала: способности не копируются).
    it = ItemStack(Material.STONE_SWORD, 1)
    meta = it.getItemMeta()
    meta.setDisplayName(u"§8Истинный клинок")
    if ENC_SWEEPING is not None:
        meta.addEnchant(ENC_SWEEPING, 1, True)
    it.setItemMeta(meta)
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

_mirror_publish("kris:blade", u"истинный клинок", u"§8Истинный клинок", _kris_mirror_blade)

Bukkit.getLogger().info("[kris] Kris loaded. Commands: /test kris [tier], /kris <ability>")

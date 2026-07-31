# -*- coding: utf-8 -*-
"""
==============================================================================
  ДРАКУЛЬ МИХОК / Ёру (Profihvofi)
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test mihawk [1..5]              — выдать Ёру нужного уровня
  /mihawk <способность>            — способности
      разрез | ульт (алиас разреза)
  /mihawk tier <1..5>              — админ-переключение тира
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, GameMode, Location
)
from org.bukkit.entity import (
    Player, LivingEntity, Projectile, Snowball, ThrownPotion, Arrow, AbstractArrow,
    SpectralArrow, Trident
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent, PlayerRespawnEvent,
    PlayerItemHeldEvent, PlayerInteractEntityEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDeathEvent,
    PlayerDeathEvent, ProjectileLaunchEvent, EntityShootBowEvent
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

# DamageSource (Paper 1.20.5+)
_HAS_DAMAGE_API = True
try:
    from org.bukkit.damage import DamageSource, DamageType
except ImportError:
    _HAS_DAMAGE_API = False


# =============================================================================
#  CONSTANTS
# =============================================================================

MIHAWK_NAMES    = set([u"profihvofi", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_YORU  = NamespacedKey.fromString("mihawk:yoru")
KEY_TIER  = NamespacedKey.fromString("mihawk:tier")
KEY_OWNER = NamespacedKey.fromString("mihawk:owner")
KEY_RESTORE = NamespacedKey.fromString("mihawk:restore_block")

# Тиры
TIER_MATERIAL = {
    1: Material.STONE_SWORD,
    2: Material.IRON_SWORD,
    3: Material.GOLDEN_SWORD,
    4: Material.DIAMOND_SWORD,
    5: Material.NETHERITE_SWORD,
}
TIER_NAME = {
    1: u"§8§lКаменный клинок §7§o(I)",
    2: u"§7§lЖелезный клинок §7§o(II)",
    3: u"§6§lЗолотой клинок §7§o(III)",
    4: u"§b§lАлмазный клинок §7§o(IV)",
    5: u"§4§l§oЁру §r§4— Легендарный клинок §7§o(V)",
}

# Cooldowns
CD_SLASH = 45 * 20   # было 59 сек -> 45 (ребаланс 2026-07-28)

# Great Slash
SLASH_LENGTH = 12       # блоков вперёд
SLASH_WIDTH  = 3        # ширина (± 1)
SLASH_HEIGHT = 4        # высота
SLASH_DURATION_TICKS = 3 * 20    # 3 сек
SLASH_STEP_TICKS = 3             # раз в 3 тика двигаем волну
SLASH_DAMAGE = 6.0               # 3 сердца чистого урона (ребаланс 2026-07-28, было 4.0)
BLOCK_RESTORE_TICKS = 60 * 20    # восстановление блока через 1 мин

# Блоки, которые НЕ ломает Великий Разрез (контейнеры).
CONTAINER_BLOCKS = set([
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
    Material.BEACON, Material.CONDUIT,
    Material.ENCHANTING_TABLE,
    Material.CRAFTING_TABLE, Material.ANVIL, Material.CHIPPED_ANVIL, Material.DAMAGED_ANVIL,
    Material.LOOM, Material.STONECUTTER, Material.CARTOGRAPHY_TABLE, Material.SMITHING_TABLE,
    Material.LECTERN, Material.JUKEBOX,
    Material.BEDROCK, Material.END_PORTAL_FRAME, Material.END_PORTAL, Material.NETHER_PORTAL,
    Material.RESPAWN_ANCHOR,
    Material.SPAWNER,
])


# Оружие/предметы, запрещённые Верностью клинку.
# Проверяем через флаг: если предмет не Ёру и это оружие/стрелковое/снежок/зелье-вред —
# Михок не может им пользоваться.
#
# Обновлено 2026-07-28: добавлены материалы 1.21.9 + 1.21.11:
#   - медный меч (1.21.9)
#   - копья 7 материалов (1.21.11)
# Динамический lookup через getattr — если PySpigot ещё не увидел материал,
# просто пропускаем (обратная совместимость с 1.21.8-).

def _mat(name):
    """Безопасный lookup Material по имени. Возвращает None если материала нет."""
    return getattr(Material, name, None)

FORBIDDEN_MATERIALS = set()

# Мечи всех материалов (включая медный из 1.21.9).
for _n in ("WOODEN_SWORD", "STONE_SWORD", "COPPER_SWORD", "IRON_SWORD",
           "GOLDEN_SWORD", "DIAMOND_SWORD", "NETHERITE_SWORD"):
    _m = _mat(_n)
    if _m is not None: FORBIDDEN_MATERIALS.add(_m)

# Копья (1.21.11) — новое оружие ближнего боя с большей дальностью.
# По той же логике "Верности клинку" запрещено всё, кроме Ёру.
for _n in ("WOODEN_SPEAR", "STONE_SPEAR", "COPPER_SPEAR", "IRON_SPEAR",
           "GOLDEN_SPEAR", "DIAMOND_SPEAR", "NETHERITE_SPEAR"):
    _m = _mat(_n)
    if _m is not None: FORBIDDEN_MATERIALS.add(_m)

# Стрелковое / метательное.
for _n in ("BOW", "CROSSBOW", "TRIDENT", "MACE",
           "SNOWBALL", "EGG",
           "ARROW", "SPECTRAL_ARROW", "TIPPED_ARROW",
           "SPLASH_POTION", "LINGERING_POTION"):
    _m = _mat(_n)
    if _m is not None: FORBIDDEN_MATERIALS.add(_m)

# Cleanup служебного имени.
del _n
try: del _m
except NameError: pass


# Атака (Attribute)
YORU_ATTACK_MOD_UUID = JUUID.fromString("22221111-3333-4444-5555-666677778888")


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k):  return Registry.EFFECT.get(NamespacedKey.minecraft(k))
def _enchant(k): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

ENC_UNBREAKING = _enchant("unbreaking")
ENC_SWEEPING   = _enchant("sweeping_edge")
ENC_SHARPNESS  = _enchant("sharpness")
ENC_KNOCKBACK  = _enchant("knockback")


# =============================================================================
#  STATE
# =============================================================================

cooldowns    = {}
saved_walk   = {}
active_slashes = {}   # uid -> {"end_tick", "state", "affected"}
# Восстановление блоков: key -> {"world", "x", "y", "z", "type", "block_data_str", "restore_tick"}
pending_restore = {}

# Guard для чистого урона.
_pure_dmg_in_progress = set()


# =============================================================================
#  UTILS
# =============================================================================

def uid(e): return e.getUniqueId().toString()
def now_tick(): return long(System.currentTimeMillis() / 50)
def is_mihawk(p):
    name = p.getName().lower()
    if name not in MIHAWK_NAMES:
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


def is_yoru(item):
    if item is None or item.getType() == Material.AIR: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_YORU, PersistentDataType.BYTE)

def get_yoru_tier(item):
    m = item.getItemMeta()
    if m is None: return 0
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER): return 0
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)

def get_yoru_owner(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def can_wield(p, item):
    if not is_mihawk(p): return False
    if not is_yoru(item): return False
    o = get_yoru_owner(item)
    return o is None or o == uid(p)

def yoru_anywhere(player):
    for it in player.getInventory().getContents():
        if is_yoru(it): return True
    return False

def yoru_in_hand(player):
    return is_yoru(player.getInventory().getItemInMainHand())


# =============================================================================
#  ITEM
# =============================================================================

def create_yoru(tier, owner_uuid):
    if tier < 1: tier = 1
    if tier > 5: tier = 5
    it = ItemStack(TIER_MATERIAL[tier], 1)
    m = it.getItemMeta()
    m.setDisplayName(TIER_NAME[tier])
    lore = [
        u"§7Легендарный клинок Дракуля Михока.",
        u"§8Уровень: §f" + [u"", u"I", u"II", u"III", u"IV", u"V"][tier],
        u"",
        u"§8Только Михок может держать этот клинок.",
    ]
    if tier == 5:
        lore.insert(2, u"§4§lЁру§r §7— Легендарный клинок")
        lore.insert(3, u"§8Урон: §f4.5❤")
    m.setLore(java_list(lore))

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_YORU,  PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_TIER,  PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER, PersistentDataType.STRING,  owner_uuid)

    # Тир-специфичные зачарования и характеристики.
    if tier == 1:
        if ENC_SWEEPING:   m.addEnchant(ENC_SWEEPING, 1, True)
    elif tier == 2:
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 1, True)
        if ENC_SWEEPING:   m.addEnchant(ENC_SWEEPING, 2, True)
    elif tier == 3:
        # Ребаланс 2026-07-28: Sharpness 3 -> 5, чтобы урон вышел в spec-диапазон 9-11 HP.
        # T3 Diamond (base 7) + Sharp5 (+2.5) + Sweep3 = ~9.5 HP.
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 5, True)
        if ENC_SWEEPING:   m.addEnchant(ENC_SWEEPING, 3, True)
    elif tier == 4:
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 4, True)
        if ENC_SWEEPING:   m.addEnchant(ENC_SWEEPING, 3, True)
    else:  # 5 — Ёру
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 5, True)
        if ENC_SWEEPING:   m.addEnchant(ENC_SWEEPING, 3, True)
        if ENC_KNOCKBACK:  m.addEnchant(ENC_KNOCKBACK, 1, True)

    # Все тиры Ёру неразрушимы (Unbreaking убран — избыточен).
    m.setUnbreakable(True)

    if tier == 5:
        # Урон 9 HP (4.5 сердца) — атрибут ATTACK_DAMAGE. Vanilla незер = 7 бонус к базе 1.0 = 8.
        # Целимся на 9. НО как только к слоту HAND добавляется ЛЮБОЙ AttributeModifier,
        # Bukkit СТИРАЕТ дефолтный ATK материала (см. фикс Криса/Барсика).
        # Поэтому bonus = target - 1.0 = 8.0.
        try:
            attr_dmg = ATTR_ATTACK_DAMAGE
            mod_dmg = AttributeModifier(
                JUUID.fromString("22221111-3333-4444-5555-777788889999"),
                "yoru_damage", 8.0,   # target 9.0 - base 1.0
                AttributeModifier.Operation.ADD_NUMBER,
                EquipmentSlot.HAND
            )
            m.addAttributeModifier(attr_dmg, mod_dmg)
        except Exception as ex:
            Bukkit.getLogger().warning("[mihawk] attack damage mod: " + str(ex))

        # Замедленный удар: атрибут ATTACK_SPEED. Целимся на 1.2 атаки/сек.
        # base 4.0 + mod = 1.2 => mod = -2.8.
        try:
            attr_spd = ATTR_ATTACK_SPEED
            mod_spd = AttributeModifier(
                YORU_ATTACK_MOD_UUID,
                "yoru_speed", -2.8,   # было -0.4 (полагая что дефолт -2.4 сохранится) — но он стирается!
                AttributeModifier.Operation.ADD_NUMBER,
                EquipmentSlot.HAND
            )
            m.addAttributeModifier(attr_spd, mod_spd)
        except Exception as ex:
            Bukkit.getLogger().warning("[mihawk] attack speed mod: " + str(ex))

    it.setItemMeta(m)
    return it


def replace_yoru(player, tier):
    inv = player.getInventory()
    contents = inv.getContents()
    for i in range(len(contents)):
        if is_yoru(contents[i]):
            inv.setItem(i, create_yoru(tier, uid(player)))
            return True
    return False


def give_yoru(player, tier=1):
    inv = player.getInventory()
    placed = False
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_yoru(tier, uid(player)))
            placed = True
            break
    if not placed:
        inv.setItem(0, create_yoru(tier, uid(player)))
    player.sendMessage(u"§4§l✦ §rКлинок вручён Михоку. §7Уровень §f" +
                       [u"", u"I", u"II", u"III", u"IV", u"V"][tier])


def kit_entry(player, args_list):
    if not is_mihawk(player):
        player.sendMessage(u"§cТолько Михок достоин Ёру.")
        return
    tier = 1
    if args_list and len(args_list) >= 1:
        try:
            tier = int(args_list[0])
            if tier < 1 or tier > 5: tier = 1
        except (ValueError, TypeError):
            tier = 1
    give_yoru(player, tier)


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
#  ABILITY — ВЕЛИКИЙ РАЗРЕЗ
# =============================================================================

def _block_key(loc):
    return u"%s,%d,%d,%d" % (loc.getWorld().getName(),
                              loc.getBlockX(), loc.getBlockY(), loc.getBlockZ())


# Хрупкие блоки (redstone/факелы/растения/ковры и т.д.) — предзачищаем без
# физики, чтобы избежать item drop от physics update соседей.
# См. amonra.py::_is_fragile — тот же принцип.
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


def _save_and_break_block(block):
    """Сохраняет состояние блока для восстановления и разбивает его.
    Используем setType(AIR, False) — БЕЗ физики, чтобы предотвратить дюп
    хрупких соседей (redstone/растения/факелы)."""
    mat = block.getType()
    if mat.isAir(): return
    if mat in CONTAINER_BLOCKS: return
    if mat == Material.WATER or mat == Material.LAVA: return

    loc = block.getLocation()
    key = _block_key(loc)
    if key in pending_restore:
        try: block.setType(Material.AIR, False)
        except Exception: block.setType(Material.AIR)
        return

    # Предзачистка хрупких соседей.
    for dx, dy, dz in ((0,1,0),(0,-1,0),(1,0,0),(-1,0,0),(0,0,1),(0,0,-1)):
        try:
            nb = block.getRelative(dx, dy, dz)
            nmat = nb.getType()
            if nmat.isAir(): continue
            if nmat in CONTAINER_BLOCKS: continue
            if nmat == Material.WATER or nmat == Material.LAVA: continue
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
            _mihawk_schedule_restore(nkey)
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

    _mihawk_schedule_restore(key)


def _mihawk_schedule_restore(key):
    """Планирование восстановления блока (общее для основного и хрупких соседей)."""
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
            mat_r = Material.getMaterial(rec["type"])
            if mat_r is None: return
            b.setType(mat_r, False)
            if rec.get("data"):
                try:
                    bd = Bukkit.createBlockData(rec["data"])
                    b.setBlockData(bd, False)
                except Exception: pass
        except Exception as ex:
            Bukkit.getLogger().warning("[mihawk] block restore: " + str(ex))
    scheduler.runTaskLater(restore, BLOCK_RESTORE_TICKS)


def ability_slash(player):
    if not check_cd(player, "slash", u"«Великий Разрез»"):
        return
    if not yoru_anywhere(player):
        player.sendMessage(u"§cДля Разреза нужен клинок Ёру в инвентаре.")
        return

    world = player.getWorld()
    origin = player.getEyeLocation()
    state = {
        "player": player,
        "world": world,
        "origin": origin.clone(),
        "progress": 0,          # сколько тиков прошло
        "affected": set(),      # UUID уже задетых сущностей
        "current_dir": player.getLocation().getDirection().normalize(),
    }
    active_slashes[uid(player)] = state

    world.playSound(origin, Sound.ENTITY_PLAYER_ATTACK_STRONG, 1.2, 0.5)
    world.playSound(origin, Sound.ITEM_TRIDENT_RIPTIDE_1, 0.9, 0.8)
    player.sendMessage(u"§4§l✦ Великий Разрез!")

    # Каждые SLASH_STEP_TICKS тиков: обновляем направление, двигаем волну,
    # ломаем блоки и наносим урон.
    total_steps = SLASH_DURATION_TICKS // SLASH_STEP_TICKS
    # За total_steps шагов пройти SLASH_LENGTH блоков.
    step_dist = float(SLASH_LENGTH) / float(total_steps)

    def tick():
        st = active_slashes.get(uid(player))
        if st is None: return
        if st["progress"] >= SLASH_DURATION_TICKS:
            # quest_tracker: отчёт о числе целей.
            try:
                fn = System.getProperties().get("quest_tracker.report_mihawk_great_slash")
                if fn is not None:
                    fn(player, len(st.get("affected", [])))
            except Exception: pass
            active_slashes.pop(uid(player), None)
            return

        # Обновляем текущее направление по взгляду игрока.
        if player.isOnline():
            st["current_dir"] = player.getLocation().getDirection().normalize()

        # Позиция фронта волны от исходной точки, но следуя за игроком.
        # Считаем "плоскость волны" как перпендикулярную текущему направлению.
        dir_v = st["current_dir"]
        # Индекс текущего слоя (0 .. total_steps-1)
        step_idx = st["progress"] // SLASH_STEP_TICKS
        front_dist = (step_idx + 1) * step_dist   # блоков от игрока до фронта

        # Центр волны сейчас — от текущей позиции игрока по направлению взгляда.
        base = player.getLocation().add(0, 1.0, 0)  # уровень пояса
        # Ось "вправо" перпендикулярна направлению и вверх.
        up = Vector(0, 1, 0)
        right = dir_v.clone().crossProduct(up)
        if right.lengthSquared() < 0.001:
            right = Vector(1, 0, 0)
        right = right.normalize()

        # Строим "тонкий слой" на дистанции front_dist от игрока.
        # Ширина ±(SLASH_WIDTH-1)/2, высота ±(SLASH_HEIGHT-1)/2.
        half_w = (SLASH_WIDTH - 1) // 2
        half_h = (SLASH_HEIGHT - 1) // 2

        # Отдельный слой на этот шаг (чтобы не сканировать всю область каждый тик).
        for dw in range(-half_w, half_w + 1):
            for dh in range(-half_h, half_h + 1):
                offset = dir_v.clone().multiply(front_dist)
                offset.add(right.clone().multiply(float(dw)))
                offset.add(up.clone().multiply(float(dh)))
                point = base.clone().add(offset)

                # Ломаем блок в этой точке.
                block = point.getBlock()
                _save_and_break_block(block)

                # Визуал.
                world.spawnParticle(Particle.SWEEP_ATTACK, point, 1, 0.0, 0.0, 0.0, 0.0)
                world.spawnParticle(Particle.CRIT, point, 2, 0.15, 0.15, 0.15, 0.02)

        # Проверяем попадания по сущностям в этом фронте.
        # Берём центр фронта и ищем в радиусе max(width, height)/2 + 1.
        center = base.clone().add(dir_v.clone().multiply(front_dist))
        r = float(max(SLASH_WIDTH, SLASH_HEIGHT)) / 2.0 + 0.5
        for e in world.getNearbyEntities(center, r, r, r):
            if not isinstance(e, LivingEntity): continue
            if e.equals(player): continue
            eu = uid(e)
            if eu in st["affected"]: continue
            st["affected"].add(eu)
            deal_pure_damage(e, SLASH_DAMAGE, player)
            world.spawnParticle(Particle.CRIT, e.getLocation().add(0, 1, 0), 15, 0.4, 0.5, 0.4, 0.05)
            world.playSound(e.getLocation(), Sound.ENTITY_PLAYER_ATTACK_STRONG, 1.0, 0.8)

        st["progress"] += SLASH_STEP_TICKS
        scheduler.runTaskLater(tick, SLASH_STEP_TICKS)

    scheduler.runTaskLater(tick, 2)
    set_cd(player, "slash", CD_SLASH)


# =============================================================================
#  PASSIVES: скорость, верность клинку
# =============================================================================

BASE_SPEED = 0.2
MIHAWK_SPEED = 0.2 * 0.92   # -8%

def _passives_tick():
    try:
        for pl in Bukkit.getOnlinePlayers():
            u = uid(pl)
            if is_mihawk(pl) and yoru_anywhere(pl):
                if pl.getWalkSpeed() > MIHAWK_SPEED + 0.001:
                    if u not in saved_walk:
                        saved_walk[u] = pl.getWalkSpeed()
                    pl.setWalkSpeed(MIHAWK_SPEED)
            else:
                if u in saved_walk:
                    try:
                        pl.setWalkSpeed(saved_walk[u])
                    except Exception:
                        pl.setWalkSpeed(BASE_SPEED)
                    saved_walk.pop(u, None)
    except Exception as ex:
        Bukkit.getLogger().warning("[mihawk] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


# =============================================================================
#  ВЕРНОСТЬ КЛИНКУ — блокировка чужого оружия
# =============================================================================

def _potion_is_harmful(item):
    """True если зелье имеет вредный эффект (Harm, Poison, Weakness, Slowness)."""
    if item is None: return False
    if item.getType() not in (Material.SPLASH_POTION, Material.LINGERING_POTION):
        return False
    m = item.getItemMeta()
    if m is None: return False
    try:
        effects = m.getCustomEffects()
        for eff in effects:
            t = eff.getType()
            try:
                key = t.getKey().getKey()
                if key in ("harm", "poison", "weakness", "slowness", "wither", "hunger"):
                    return True
            except Exception:
                pass
        # Также базовый тип зелья (INSTANT_DAMAGE, POISON и т.п.).
        try:
            base = m.getBasePotionType()
            if base is not None:
                name = base.name().lower()
                if any(x in name for x in ("harm", "poison", "weakness", "slowness")):
                    return True
        except Exception:
            pass
    except Exception:
        pass
    return False


def _is_forbidden_for_mihawk(item):
    """True если Михоку нельзя это использовать (не-Ёру оружие/стрелковое/снежок/зелье-вред)."""
    if item is None or item.getType() == Material.AIR: return False
    mat = item.getType()
    if mat in FORBIDDEN_MATERIALS:
        # Меч Ёру — исключение.
        if is_yoru(item):
            return False
        # Обычные зелья без вредных эффектов — можно.
        if mat in (Material.SPLASH_POTION, Material.LINGERING_POTION):
            return _potion_is_harmful(item)
        return True
    return False


# =============================================================================
#  LISTENERS
# =============================================================================

def on_interact(event):
    if event.getHand() != EquipmentSlot.HAND: return
    p = event.getPlayer()
    if not is_mihawk(p): return
    item = event.getItem()

    # Верность клинку — блокируем ПКМ с запрещённым оружием.
    if _is_forbidden_for_mihawk(item):
        event.setCancelled(True)
        p.sendMessage(u"§8Верность клинку: §7ты не можешь использовать это оружие.")
        return

    # Активация Разреза: ПКМ с Ёру.
    action = event.getAction()
    if action != Action.RIGHT_CLICK_AIR and action != Action.RIGHT_CLICK_BLOCK: return
    if item is None or not is_yoru(item): return
    if not can_wield(p, item):
        event.setCancelled(True)
        p.sendMessage(u"§cКлинок отвергает тебя.")
        return
    if is_silenced_by_demiurg(p):
        p.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
    event.setCancelled(True)
    ability_slash(p)


def on_interact_entity(event):
    # Правый клик по мобу-торговцу и т.п. со стрелой в руке — не блокируем (это разгрузка).
    # Но если Михок пытается ткнуть луком в моба — блокируем.
    if event.getHand() != EquipmentSlot.HAND: return
    p = event.getPlayer()
    if not is_mihawk(p): return
    item = p.getInventory().getItemInMainHand()
    if _is_forbidden_for_mihawk(item):
        event.setCancelled(True)


def on_damage_by(event):
    dmg = event.getDamager()
    ent = event.getEntity()

    # Верность клинку — блок урона от снаряда, выпущенного Михоком.
    if isinstance(dmg, Projectile):
        shooter = dmg.getShooter()
        if isinstance(shooter, Player) and is_mihawk(shooter):
            # Разрешаем только стрелы, выпущенные не-Михоком, или снежки другими.
            event.setCancelled(True)
            shooter.sendMessage(u"§8Верность клинку: §7снаряды бесполезны в твоих руках.")
            return

    # Верность клинку — блок урона от Михока не-Ёру оружием.
    if isinstance(dmg, Player) and is_mihawk(dmg):
        item = dmg.getInventory().getItemInMainHand()
        if item is not None and item.getType() != Material.AIR:
            # Разрешаем: Ёру, пустая рука (кулаки).
            if not is_yoru(item):
                # Если это ЛЮБОЕ из запрещённых — блокируем.
                if _is_forbidden_for_mihawk(item):
                    event.setCancelled(True)
                    dmg.sendMessage(u"§8Верность клинку: §7ты можешь атаковать только Ёру.")
                    return


def on_projectile_launch(event):
    proj = event.getEntity()
    shooter = proj.getShooter()
    if not isinstance(shooter, Player): return
    if not is_mihawk(shooter): return
    # Блокируем стрелы (лук, арбалет), трезубцы, снежки, яйца, вредные зелья.
    if isinstance(proj, AbstractArrow) or isinstance(proj, Snowball) or isinstance(proj, Trident):
        event.setCancelled(True)
        shooter.sendMessage(u"§8Верность клинку: §7снаряды не для тебя.")
        return
    if isinstance(proj, ThrownPotion):
        item = proj.getItem() if hasattr(proj, "getItem") else None
        if _potion_is_harmful(item):
            event.setCancelled(True)
            shooter.sendMessage(u"§8Верность клинку: §7вредные зелья запрещены.")


def on_shoot_bow(event):
    ent = event.getEntity()
    if isinstance(ent, Player) and is_mihawk(ent):
        event.setCancelled(True)
        ent.sendMessage(u"§8Верность клинку: §7луки запрещены.")


def on_drop(event):
    if is_yoru(event.getItemDrop().getItemStack()):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cЁру нельзя выбросить.")


def on_inv_click(event):
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        it = event.getCurrentItem()
        cursor = event.getCursor()
        if is_yoru(it) or is_yoru(cursor):
            event.setCancelled(True)
            event.getWhoClicked().sendMessage(u"§cЁру нельзя убрать в контейнер.")


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

    if not is_mihawk(player):
        return

    def _check_and_restore():
        try:
            if not player.isOnline():
                return

            if yoru_anywhere(player) is None:
                give_yoru(player, 1)
                player.sendMessage(u"§7[mihawk] Комплект восстановлен.")

        except Exception:
            import traceback
            traceback.print_exc()

    scheduler.runTaskLater(_check_and_restore, 40)




# =============================================================================
#  COMMAND /mihawk
# =============================================================================

def cmd_mihawk(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько для игроков.")
        return True
    if not is_mihawk(sender):
        sender.sendMessage(u"§cТолько Михок может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/mihawk <разрез>")
        sender.sendMessage(u"  §f/mihawk tier <1..5>")
        return True

    sub = args[0].lower()

    if sub == u"tier":
        if not _test_mode_on():
            sender.sendMessage(u"§cТестовый режим выключен — команда недоступна.")
            return True
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/mihawk tier <1..5>")
            return True
        try:
            t = int(args[1])
        except ValueError:
            sender.sendMessage(u"§cТир — число.")
            return True
        if t < 1 or t > 5:
            sender.sendMessage(u"§cТиры: 1..5.")
            return True
        if not replace_yoru(sender, t):
            give_yoru(sender, t)
        else:
            sender.sendMessage(u"§aЁру перекован до уровня " +
                               [u"", u"I", u"II", u"III", u"IV", u"V"][t])
        return True

    if sub in (u"разрез", u"великийразрез", u"slash", u"ульт", u"ult"):
        if is_silenced_by_demiurg(sender):
            sender.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
            return True
        ability_slash(sender)
        return True

    sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_mihawk, "mihawk")

listener_mgr.registerListener(on_interact,           PlayerInteractEvent)
listener_mgr.registerListener(on_interact_entity,    PlayerInteractEntityEvent)
listener_mgr.registerListener(on_damage_by,          EntityDamageByEntityEvent)
listener_mgr.registerListener(on_projectile_launch,  ProjectileLaunchEvent)
listener_mgr.registerListener(on_shoot_bow,          EntityShootBowEvent)
listener_mgr.registerListener(on_drop,               PlayerDropItemEvent)
listener_mgr.registerListener(on_inv_click,          InventoryClickEvent)
listener_mgr.registerListener(on_death,              PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,            PlayerRespawnEvent)

_passives_tick()

# --- Регистрация набора в /test-диспетчере ---
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("mihawk", (kit_entry, u"Дракуль Михок (Ёру [tier 1..5])"))

# --- Публикация владельцев для admin-скрипта ---
_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("mihawk", list(MIHAWK_NAMES))

# --- Публикация функции смены тира для admin-скрипта ---
def _mihawk_set_tier(target_player, tier):
    if tier < 1 or tier > 5:
        return False
    if not replace_yoru(target_player, tier):
        give_yoru(target_player, tier)
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("mihawk", _mihawk_set_tier)


# --- Публикация в каталог Зеркала Души Арчера ---
def _mihawk_mirror_yoru(owner_uuid):
    it = ItemStack(Material.STONE_SWORD, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§4Ёру")
    if ENC_SWEEPING: m.addEnchant(ENC_SWEEPING, 1, True)
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

_mirror_publish("mihawk:yoru", u"ёру", u"§4Ёру", _mihawk_mirror_yoru)


Bukkit.getLogger().info("[mihawk] Mihawk loaded. Commands: /test mihawk, /mihawk")

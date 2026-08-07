# -*- coding: utf-8 -*-
"""
==============================================================================
  АМОН-РА (Ares_Yusu)
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test amonra             — выдать «Нур»
  /amonra <способность>    — способности
      луч | форма | ульт
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
    Player, LivingEntity
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent, PlayerRespawnEvent,
    PlayerMoveEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDeathEvent,
    PlayerDeathEvent
)
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.event.block import Action, BlockBreakEvent
from org.bukkit.enchantments import Enchantment
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.potion import PotionEffect
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

AMONRA_NAMES    = set([u"ares_yusu", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_NUR   = NamespacedKey.fromString("amonra:nur")
KEY_OWNER = NamespacedKey.fromString("amonra:owner")
KEY_TIER  = NamespacedKey.fromString("amonra:tier")

# =============================================================================
#  TIER SPEC — Копьё Нур (T1..T3)
# =============================================================================
#
# Paper 1.21.11 добавил Material.*_SPEAR (Wooden, Stone, Iron, Gold, Diamond,
# Netherite). Если по каким-то причинам материал не существует в текущем
# билде — падаем на TRIDENT как fallback.
#
# Тиры:
#   T1: Iron Spear    + Sharpness II
#   T2: Diamond Spear + Sharpness IV + Knockback I
#   T3: Netherite Spear + Sharpness V + Knockback I + Fire Aspect I
#
def _mat_or(name, fallback_name):
    try:
        m = Material.getMaterial(name)
        if m is not None:
            return m
    except Exception:
        pass
    try:
        return Material.getMaterial(fallback_name)
    except Exception:
        return Material.TRIDENT

TIER_MATERIALS = {
    1: _mat_or("IRON_SPEAR",      "TRIDENT"),
    2: _mat_or("DIAMOND_SPEAR",   "TRIDENT"),
    3: _mat_or("NETHERITE_SPEAR", "TRIDENT"),
}
TIER_SHARP = {1: 2, 2: 4, 3: 5}
TIER_KNOCK = {1: 0, 2: 1, 3: 1}
TIER_FIRE  = {1: 0, 2: 0, 3: 1}
TIER_NAMES = {
    1: u"§e§lСветовое копьё §6§l«Нур» §7[§fI§7]",
    2: u"§e§lСветовое копьё §6§l«Нур» §7[§bII§7]",
    3: u"§e§lСветовое копьё §6§l«Нур» §7[§dIII§7]",
}
TIER_LORES = {
    1: u"§8Тир §fI§8 · Iron Spear · Sharpness II",
    2: u"§8Тир §bII§8 · Diamond Spear · Sharpness IV · Knockback I",
    3: u"§8Тир §dIII§8 · Netherite Spear · Sharpness V · Knockback I · Fire Aspect I",
}

# Cooldowns (тики)
CD_BEAM        = 30 * 20
CD_LIGHT_FORM  = 90 * 20     # 1 мин 30 сек
CD_ULT         = 5 * 60 * 20

# Способности
BEAM_DURATION       = 10 * 20
BEAM_TICK_INTERVAL  = 20       # раз в секунду
BEAM_TICK_DAMAGE    = 2.5      # 2.5 сердца чистого урона за попадание
BEAM_RANGE          = 20.0
BEAM_FIRE_TICKS     = 40       # 2 сек горения

LIGHT_FORM_DURATION = 10 * 20

ULT_CONCENTRATION   = 2 * 20   # 2 секунды концентрации
ULT_RADIUS          = 7.0
ULT_DAMAGE          = 10.0     # 5 сердец
ULT_FIRE_TICKS      = 100      # 5 сек горения
BLOCK_RESTORE_TICKS = 2 * 60 * 20  # 2 минуты (ребаланс 2026-07-28: было 10 сек)

# Пассив: Дитя света.
DARK_TIME_LIMIT = 20 * 20      # 20 секунд в темноте
DARK_MIN_LIGHT  = 1            # уровень освещения ниже которого считаем тьмой

# Блоки, которые НЕ ломает ульт.
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
    Material.OBSIDIAN, Material.CRYING_OBSIDIAN, Material.BEDROCK,
    Material.NETHERITE_BLOCK, Material.REINFORCED_DEEPSLATE,
    Material.END_PORTAL_FRAME, Material.END_PORTAL, Material.NETHER_PORTAL,
    Material.RESPAWN_ANCHOR,
    Material.BEACON, Material.CONDUIT,
    Material.WATER, Material.LAVA,
    Material.ANVIL, Material.CHIPPED_ANVIL, Material.DAMAGED_ANVIL,
    Material.ENCHANTING_TABLE, Material.CRAFTING_TABLE,
    Material.SMITHING_TABLE, Material.LOOM, Material.CARTOGRAPHY_TABLE,
    Material.STONECUTTER, Material.LECTERN, Material.JUKEBOX,
])


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k): return Registry.EFFECT.get(NamespacedKey.minecraft(k))
def _enchant(k): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

E_INVIS       = _effect("invisibility")
E_RESIST      = _effect("resistance")
E_SPEED       = _effect("speed")
E_REGEN       = _effect("regeneration")
E_WEAKNESS    = _effect("weakness")
E_HUNGER      = _effect("hunger")
E_BLINDNESS   = _effect("blindness")
E_FIRE_RESIST = _effect("fire_resistance")

ENC_SHARP     = _enchant("sharpness")
ENC_KNOCKBACK = _enchant("knockback")
ENC_FIRE      = _enchant("fire_aspect")


# =============================================================================
#  STATE
# =============================================================================

cooldowns    = {}

# Активный солнечный луч: uid -> end_tick
beam_active  = {}

# Световая форма: uid -> {"end_tick", "prev_flight", "prev_allow_flight"}
light_form_active = {}

# Ульт-концентрация: uid -> {"end_tick": start+2s, "location": Location}
ult_charging = {}

# Дегидратация света: uid -> tick начала непрерывной темноты (0 = не в темноте)
dark_since   = {}

# Восстановление блоков после ульта.
pending_restore = {}


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

def is_amonra(p):
    name = p.getName().lower()
    if name not in AMONRA_NAMES:
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


def is_nur(item):
    if item is None or item.getType() == Material.AIR: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_NUR, PersistentDataType.BYTE)

def get_nur_owner(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def get_nur_tier(item):
    if item is None or item.getType() == Material.AIR: return 0
    m = item.getItemMeta()
    if m is None: return 0
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER): return 1
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)


def can_wield(p, item):
    if not is_amonra(p): return False
    if not is_nur(item): return False
    o = get_nur_owner(item)
    return o is None or o == uid(p)

def nur_anywhere(player):
    for it in player.getInventory().getContents():
        if is_nur(it): return True
    return False


def find_nur_tier_in_hand_or_hotbar(player):
    """Возвращает текущий тир копья: сначала в руке, потом в хотбаре, иначе 0."""
    inv = player.getInventory()
    it = inv.getItemInMainHand()
    if is_nur(it):
        return get_nur_tier(it)
    for i in range(9):
        it = inv.getItem(i)
        if is_nur(it):
            return get_nur_tier(it)
    return 0


# =============================================================================
#  ITEM
# =============================================================================

def create_nur(tier, owner_uuid):
    if tier < 1: tier = 1
    if tier > 3: tier = 3

    mat = TIER_MATERIALS.get(tier, TIER_MATERIALS[1])
    it = ItemStack(mat, 1)
    m = it.getItemMeta()

    m.setDisplayName(TIER_NAMES.get(tier, TIER_NAMES[1]))
    lore = [
        u"§7Легендарное оружие Амон-Ра.",
        TIER_LORES.get(tier, TIER_LORES[1]),
        u"",
        u"§8Только Амон-Ра может держать это копьё.",
    ]
    m.setLore(java_list(lore))
    m.setUnbreakable(True)   # правило: Unbreakable, без Unbreaking/Mending

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_NUR,   PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_OWNER, PersistentDataType.STRING,  owner_uuid)
    pdc.set(KEY_TIER,  PersistentDataType.INTEGER, tier)

    # Зачарования по тиру.
    sharp = TIER_SHARP.get(tier, 2)
    knock = TIER_KNOCK.get(tier, 0)
    fire  = TIER_FIRE.get(tier, 0)
    if ENC_SHARP and sharp > 0:     m.addEnchant(ENC_SHARP, sharp, True)
    if ENC_KNOCKBACK and knock > 0: m.addEnchant(ENC_KNOCKBACK, knock, True)
    if ENC_FIRE and fire > 0:       m.addEnchant(ENC_FIRE, fire, True)

    it.setItemMeta(m)
    return it


def replace_nur(player, tier):
    """Заменяет ВСЕ копья в инвентаре на новые с указанным тиром.
    Возвращает True если было заменено хотя бы одно."""
    inv = player.getInventory()
    contents = inv.getContents()
    replaced = False
    for i in range(len(contents)):
        if is_nur(contents[i]):
            inv.setItem(i, create_nur(tier, uid(player)))
            replaced = True
    return replaced


def give_nur(player, tier=1):
    if tier < 1: tier = 1
    if tier > 3: tier = 3
    inv = player.getInventory()
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_nur(tier, uid(player)))
            player.sendMessage(u"§e§l✦ §rКопьё «Нур» §7[тир " + str(tier) + u"]§r вручено.")
            return
    inv.setItem(0, create_nur(tier, uid(player)))
    player.sendMessage(u"§e§l✦ §rКопьё «Нур» §7[тир " + str(tier) + u"]§r вручено.")


def kit_entry(player, args_list):
    if not is_amonra(player):
        player.sendMessage(u"§cТолько Амон-Ра достоин копья Нур.")
        return
    tier = 1
    if args_list:
        try: tier = int(args_list[0])
        except Exception: tier = 1
    give_nur(player, tier)


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


# =============================================================================
#  ABILITIES
# =============================================================================

def _check_common(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return False
    if not nur_anywhere(player):
        player.sendMessage(u"§cДля способностей нужно копьё Нур.")
        return False
    # Световая форма блокирует остальные способности.
    if uid(player) in light_form_active and light_form_active[uid(player)]["end_tick"] > now_tick():
        player.sendMessage(u"§8В Световой форме нельзя использовать способности.")
        return False
    return True


# --- 1. Солнечный луч --------------------------------------------------------

def ability_beam(player):
    if not _check_common(player): return
    if not check_cd(player, "beam", u"«Солнечный луч»"):
        return

    end = now_tick() + BEAM_DURATION
    beam_active[uid(player)] = end

    world = player.getWorld()
    world.playSound(player.getLocation(), Sound.ITEM_TRIDENT_THROW, 0.8, 1.6)
    player.sendMessage(u"§e§l✦ Солнечный луч §r§7— 10 секунд.")

    state = {"tick": 0}
    def beam_tick():
        if state["tick"] >= BEAM_DURATION:
            return
        if not player.isOnline():
            return
        # Если игрок ушёл в Световую форму — прерываем луч.
        if uid(player) in light_form_active and light_form_active[uid(player)]["end_tick"] > now_tick():
            beam_active.pop(uid(player), None)
            return

        eye = player.getEyeLocation()
        dir_v = eye.getDirection().normalize()

        # Луч не проходит сквозь непрозрачные блоки — используем rayTraceBlocks
        # с FLUID_COLLIDE_NEVER и IGNORE_PASSABLE_BLOCKS = True.
        # Простая версия: max_range = BEAM_RANGE, ищем первый блок.
        blk_res = player.rayTraceBlocks(BEAM_RANGE)
        if blk_res is not None and blk_res.getHitBlock() is not None:
            end_loc = blk_res.getHitPosition().toLocation(world)
        else:
            end_loc = eye.clone().add(dir_v.clone().multiply(BEAM_RANGE))

        # Партиклы луча.
        dv = end_loc.toVector().subtract(eye.toVector())
        length = dv.length()
        if length > 0.1:
            steps = int(length * 3)
            step_v = dv.multiply(1.0 / max(1, steps))
            p = eye.clone()
            for i in range(steps):
                p.add(step_v)
                world.spawnParticle(Particle.END_ROD, p, 1, 0.02, 0.02, 0.02, 0.0)
                world.spawnParticle(Particle.FLAME, p, 1, 0.05, 0.05, 0.05, 0.0)

        # Урон каждые BEAM_TICK_INTERVAL тиков.
        if state["tick"] % BEAM_TICK_INTERVAL == 0:
            # Ищем цели вдоль луча — проходит сквозь мобов.
            hit_uids = set()
            dist = 0.0
            step_len = 0.6
            check_p = eye.clone()
            dv_norm = dir_v.clone()
            while dist < length:
                check_p.add(dv_norm.clone().multiply(step_len))
                dist += step_len
                for e in world.getNearbyEntities(check_p, 0.8, 0.8, 0.8):
                    if not isinstance(e, LivingEntity): continue
                    if e.equals(player): continue
                    eu = uid(e)
                    if eu in hit_uids: continue
                    hit_uids.add(eu)
                    deal_pure_damage(e, BEAM_TICK_DAMAGE, player)
                    try:
                        cur_fire = e.getFireTicks()
                        if cur_fire < BEAM_FIRE_TICKS:
                            e.setFireTicks(BEAM_FIRE_TICKS)
                    except Exception:
                        pass
                    add_effect(e, E_BLINDNESS, 20, 0)   # 1 сек

        state["tick"] += 2
        scheduler.runTaskLater(beam_tick, 2)

    beam_tick()
    set_cd(player, "beam", CD_BEAM)


# --- 2. Световая форма -------------------------------------------------------

def ability_light_form(player):
    if not _check_common(player): return
    if not check_cd(player, "light_form", u"«Световая форма»"):
        return

    end = now_tick() + LIGHT_FORM_DURATION
    prev_allow = player.getAllowFlight()
    prev_flying = player.isFlying()

    light_form_active[uid(player)] = {
        "end_tick": end,
        "prev_allow_flight": prev_allow,
        "prev_flying": prev_flying,
    }

    # Полёт (только не в креативе — там и так есть).
    if player.getGameMode() not in (GameMode.CREATIVE, GameMode.SPECTATOR):
        player.setAllowFlight(True)
        player.setFlying(True)

    add_effect(player, E_INVIS,  LIGHT_FORM_DURATION, 0)
    add_effect(player, E_RESIST, LIGHT_FORM_DURATION, 1)   # Resistance II

    try:
        player.setCollidable(False)
    except Exception:
        pass

    world = player.getWorld()
    world.spawnParticle(Particle.END_ROD, player.getLocation().add(0, 1, 0),
                        40, 0.5, 1.0, 0.5, 0.02)
    world.playSound(player.getLocation(), Sound.BLOCK_BEACON_ACTIVATE, 0.9, 1.6)
    player.sendMessage(u"§e§l✦ Световая форма §r§7— 10 сек. §8Атаковать нельзя.")

    def finish():
        if uid(player) not in light_form_active:
            return
        state = light_form_active.pop(uid(player))
        if not player.isOnline():
            return
        # Восстанавливаем полёт.
        if player.getGameMode() not in (GameMode.CREATIVE, GameMode.SPECTATOR):
            player.setFlying(state.get("prev_flying", False))
            player.setAllowFlight(state.get("prev_allow_flight", False))
        try:
            player.setCollidable(True)
        except Exception:
            pass
        # Снимаем эффекты досрочно.
        try:
            if player.hasPotionEffect(E_INVIS): player.removePotionEffect(E_INVIS)
        except Exception: pass
        player.sendMessage(u"§7Световая форма развеялась.")

    scheduler.runTaskLater(finish, LIGHT_FORM_DURATION)
    set_cd(player, "light_form", CD_LIGHT_FORM)


def cancel_light_form_early(player):
    """Досрочная отмена Световой формы."""
    if uid(player) not in light_form_active:
        player.sendMessage(u"§7Ты не в Световой форме.")
        return
    state = light_form_active.pop(uid(player))
    if player.getGameMode() not in (GameMode.CREATIVE, GameMode.SPECTATOR):
        player.setFlying(state.get("prev_flying", False))
        player.setAllowFlight(state.get("prev_allow_flight", False))
    try:
        player.setCollidable(True)
    except Exception:
        pass
    try:
        if player.hasPotionEffect(E_INVIS): player.removePotionEffect(E_INVIS)
        if player.hasPotionEffect(E_RESIST): player.removePotionEffect(E_RESIST)
    except Exception: pass
    player.sendMessage(u"§7Световая форма отменена досрочно.")


# --- 3. Ультимейт — Взрыв Солнца -------------------------------------------

def ability_ult(player):
    if not _check_common(player): return
    if not check_cd(player, "ult", u"«Взрыв Солнца»"):
        return

    world = player.getWorld()
    start_loc = player.getLocation().clone()
    ult_charging[uid(player)] = {"end_tick": now_tick() + ULT_CONCENTRATION, "loc": start_loc}

    player.sendMessage(u"§6§l✦ Концентрация солнечной энергии... §72 секунды.")
    world.playSound(start_loc, Sound.BLOCK_BEACON_ACTIVATE, 1.2, 0.6)

    # Партиклы концентрации.
    state = {"t": 0}
    def charge_tick():
        if state["t"] >= ULT_CONCENTRATION:
            _detonate_ult(player, start_loc)
            return
        if not player.isOnline():
            ult_charging.pop(uid(player), None)
            return
        loc = player.getLocation().add(0, 1, 0)
        world.spawnParticle(Particle.FLAME, loc, 30, 1.0, 1.0, 1.0, 0.05)
        world.spawnParticle(Particle.SOUL_FIRE_FLAME, loc, 15, 0.6, 0.8, 0.6, 0.03)
        state["t"] += 4
        scheduler.runTaskLater(charge_tick, 4)
    charge_tick()

    set_cd(player, "ult", CD_ULT)


def _detonate_ult(player, prev_loc):
    """Собственно взрыв."""
    ult_charging.pop(uid(player), None)
    if not player.isOnline():
        return

    world = player.getWorld()
    center = player.getLocation()

    world.spawnParticle(Particle.EXPLOSION_EMITTER, center, 3, 2.0, 1.0, 2.0)
    world.spawnParticle(Particle.FLAME, center, 100, ULT_RADIUS, 2.0, ULT_RADIUS, 0.1)
    world.spawnParticle(Particle.END_ROD, center, 80, ULT_RADIUS, 2.0, ULT_RADIUS, 0.08)
    world.playSound(center, Sound.ENTITY_GENERIC_EXPLODE, 1.5, 0.7)
    world.playSound(center, Sound.ENTITY_LIGHTNING_BOLT_IMPACT, 1.0, 1.0)

    # Урон + отбрасывание + горение.
    for e in world.getNearbyEntities(center, ULT_RADIUS, ULT_RADIUS, ULT_RADIUS):
        if not isinstance(e, LivingEntity): continue
        if e.equals(player): continue
        try:
            e.damage(ULT_DAMAGE, player)
        except Exception:
            pass
        # Горение.
        try:
            cur_fire = e.getFireTicks()
            if cur_fire < ULT_FIRE_TICKS:
                e.setFireTicks(ULT_FIRE_TICKS)
        except Exception:
            pass
        # Отбрасывание 8-10 блоков.
        kb = e.getLocation().toVector().subtract(center.toVector())
        if kb.lengthSquared() < 0.01:
            kb = Vector(0, 1, 0)
        else:
            kb = kb.normalize().multiply(2.8)
        kb.setY(0.9)
        e.setVelocity(kb)
        if isinstance(e, Player):
            e.setFallDistance(0.0)

    # Разрушение блоков в радиусе.
    r = int(ULT_RADIUS)
    base = center.getBlock()
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            for dz in range(-r, r + 1):
                # Только внутри сферы.
                if dx*dx + dy*dy + dz*dz > r * r:
                    continue
                b = base.getRelative(dx, dy, dz)
                mat = b.getType()
                if mat.isAir(): continue
                if mat in PROTECTED_BLOCKS: continue
                _save_and_break_block(b)

    # Дебафф после ульта.
    player.setFoodLevel(0)
    player.setSaturation(0.0)
    add_effect(player, E_WEAKNESS, 10 * 20, 0)
    player.sendMessage(u"§8Солнце иссушило тебя — §7Голод + Слабость I на 10 сек.")


def _block_key(loc):
    return u"%s,%d,%d,%d" % (loc.getWorld().getName(),
                              loc.getBlockX(), loc.getBlockY(), loc.getBlockZ())


# Хрупкие блоки — те, что "падают" когда сосед-опора уничтожен: redstone,
# факелы, рельсы, растения, кнопки, рычаги, картины, знаки, лампы, ковры и т.д.
# Мы их предзачищаем без физики перед основным блоком, чтобы избежать дюпа.
def _is_fragile(mat):
    try:
        name = mat.name()
    except Exception:
        return False
    if name.endswith("_TORCH"):          return True
    if name.endswith("_BUTTON"):         return True
    if name.endswith("_SIGN"):           return True
    if name.endswith("_WALL_SIGN"):      return True
    if name.endswith("_HANGING_SIGN"):   return True
    if name.endswith("_PRESSURE_PLATE"): return True
    if name.endswith("_SAPLING"):        return True
    if name.endswith("_CARPET"):         return True
    if name.startswith("POTTED_"):       return True
    if "REDSTONE" in name:               return True   # wire, torch, lamp, comparator, repeater
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
                "LADDER", "SCAFFOLDING",
                "SOUL_SAND", "SOUL_SOIL",   # сами по себе не падают, но vines под ними падают
                "SNOW", "PODZOL"):
        # Игнорируем soul_sand/podzol (они не хрупкие), но некоторые ловятся выше по namesuffix.
        # Оставили в списке только реально хрупкие (не soul_sand/podzol).
        if name in ("SOUL_SAND", "SOUL_SOIL", "PODZOL", "SNOW"): return False
        return True
    return False


def _save_and_break_block(block):
    """Сохраняет BlockData и ставит air БЕЗ ФИЗИКИ. Восстанавливается через
    BLOCK_RESTORE_TICKS. Предзачищает хрупкие соседи, чтобы не было дюпа."""
    mat = block.getType()
    if mat.isAir(): return
    if mat in PROTECTED_BLOCKS: return

    loc = block.getLocation()
    key = _block_key(loc)
    if key in pending_restore: return

    # === Шаг 1: Предзачистка хрупких соседей (в т.ч. redstone-wires сверху) ===
    # Проходим по 6 соседям + 4 диагональных сверху. Если сосед хрупкий и
    # опирается на наш блок (или прилегает) — сохраняем и убираем БЕЗ физики.
    # Это ловит: факелы/redstone/кнопки на стенках, растения/торч сверху,
    # ковёр над кактусом и т.д.
    neighbor_offsets = [
        (0, 1, 0), (0, -1, 0),
        (1, 0, 0), (-1, 0, 0),
        (0, 0, 1), (0, 0, -1),
    ]
    for dx, dy, dz in neighbor_offsets:
        try:
            nb = block.getRelative(dx, dy, dz)
            nmat = nb.getType()
            if nmat.isAir(): continue
            if nmat in PROTECTED_BLOCKS: continue
            if not _is_fragile(nmat): continue
            nkey = _block_key(nb.getLocation())
            if nkey in pending_restore: continue
            try:
                nbd = nb.getBlockData().getAsString()
            except Exception:
                nbd = None
            nloc = nb.getLocation()
            pending_restore[nkey] = {
                "world": nloc.getWorld().getName(),
                "x": nloc.getBlockX(), "y": nloc.getBlockY(), "z": nloc.getBlockZ(),
                "type": nmat.name(),
                "data": nbd,
                "restore_tick": now_tick() + BLOCK_RESTORE_TICKS,
            }
            # setType(AIR, false) — не запускает physics update, item НЕ выпадает.
            try:
                nb.setType(Material.AIR, False)
            except Exception:
                nb.setType(Material.AIR)
            # Планируем восстановление этого хрупкого блока.
            _schedule_restore(nkey)
        except Exception:
            pass

    # === Шаг 2: Основной блок — тоже без физики ===
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
    try:
        block.setType(Material.AIR, False)
    except Exception:
        block.setType(Material.AIR)

    _schedule_restore(key)


def _schedule_restore(key):
    """Общая логика планирования восстановления одного блока."""
    def restore():
        rec = pending_restore.get(key)
        if rec is None: return
        pending_restore.pop(key, None)
        w = Bukkit.getWorld(rec["world"])
        if w is None: return
        b = w.getBlockAt(rec["x"], rec["y"], rec["z"])
        # Восстанавливаем только если сейчас там воздух — если игрок построил
        # что-то на этом месте, не ломаем его постройку.
        if b.getType() != Material.AIR:
            return
        try:
            if rec.get("data"):
                bd = Bukkit.createBlockData(rec["data"])
                b.setBlockData(bd, False)   # без физики
            else:
                mat_r = Material.getMaterial(rec["type"])
                if mat_r is not None:
                    b.setType(mat_r, False)
        except Exception:
            pass
    scheduler.runTaskLater(restore, BLOCK_RESTORE_TICKS)


# =============================================================================
#  PASSIVES
# =============================================================================

def _is_under_open_sky(player):
    """True если над игроком нет крыши до максимальной высоты мира."""
    loc = player.getLocation()
    world = loc.getWorld()
    x = loc.getBlockX()
    z = loc.getBlockZ()
    y_start = loc.getBlockY() + 2
    try:
        y_max = world.getMaxHeight()
    except Exception:
        y_max = 320
    for y in range(y_start, y_max):
        try:
            m = world.getBlockAt(x, y, z).getType()
            if m.isAir(): continue
            return False
        except Exception:
            continue
    return True


def _passives_tick():
    try:
        for pl in Bukkit.getOnlinePlayers():
            if not is_amonra(pl): continue
            u = uid(pl)
            world = pl.getWorld()

            # Солнечная природа Амон-Ра: постоянная огнестойкость без частиц.
            # Эффект обновляется раз в секунду и имеет небольшой запас времени,
            # поэтому не мигает при кратковременной просадке TPS.
            add_effect(pl, E_FIRE_RESIST, 60, 0, ambient=True, particles=False)

            # --- Благословение Ра: день + под открытым небом ---
            try:
                env = world.getEnvironment().name()
                is_day = world.isDayTime()
            except Exception:
                env = "NORMAL"; is_day = False
            if env == "NORMAL" and is_day and _is_under_open_sky(pl):
                add_effect(pl, E_SPEED, 60, 0, ambient=True, particles=False)
                add_effect(pl, E_REGEN, 60, 0, ambient=True, particles=False)
                # Голод расходуется -30%: каждый тик восстанавливаем 30% сытости
                # обратно (проще, чем перехватывать FoodLevelChangeEvent).
                # Это не идеально по TPS, но простая эвристика — раз в 5 сек
                # добавляем 1 к сытости, если она < max.
                if now_tick() % 100 == 0:
                    try:
                        f = pl.getFoodLevel()
                        if f < 20:
                            pl.setFoodLevel(min(20, f + 1))
                    except Exception:
                        pass

            # --- Дитя света: 20 сек в полной темноте ---
            try:
                light = pl.getLocation().getBlock().getLightLevel()
            except Exception:
                light = 15
            if light <= DARK_MIN_LIGHT:
                if u not in dark_since:
                    dark_since[u] = now_tick()
                elif now_tick() - dark_since[u] >= DARK_TIME_LIMIT:
                    add_effect(pl, E_HUNGER,   40, 0, ambient=True, particles=False)
                    add_effect(pl, E_WEAKNESS, 40, 0, ambient=True, particles=False)
            else:
                # Вышел на свет — таймер сбрасывается, эффекты сами истекают.
                dark_since.pop(u, None)

    except Exception as ex:
        Bukkit.getLogger().warning("[amonra] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


# =============================================================================
#  EVENT HANDLERS
# =============================================================================

def on_interact(event):
    if event.getHand() != EquipmentSlot.HAND: return
    p = event.getPlayer()
    item = event.getItem()
    if not is_nur(item): return
    if not can_wield(p, item):
        event.setCancelled(True)
        p.sendMessage(u"§cКопьё отвергает тебя.")


def on_damage(event):
    ent = event.getEntity()
    if not isinstance(ent, Player): return
    if not is_amonra(ent): return

    # Амон-Ра неуязвим к урону собственного взрыва (пока идёт ульт).
    cause = event.getCause()
    C = EntityDamageEvent.DamageCause
    if cause in (C.ENTITY_EXPLOSION, C.BLOCK_EXPLOSION):
        # Простая эвристика: если ульт идёт или недавно закончился (последняя секунда) —
        # рядом взрыв Амон-Ра. Отменяем свой урон.
        # Проверяем cooldown ульта — если КД только что установлено (< 2 сек назад).
        cd_rem = get_cd(ent, "ult")
        if cd_rem >= CD_ULT - 40:   # 2 сек с момента установки
            event.setCancelled(True)
            return


def on_damage_by(event):
    dmg = event.getDamager()
    # Световая форма блокирует атаки.
    if isinstance(dmg, Player) and is_amonra(dmg):
        if uid(dmg) in light_form_active and light_form_active[uid(dmg)]["end_tick"] > now_tick():
            event.setCancelled(True)
            dmg.sendMessage(u"§8В Световой форме нельзя атаковать.")
            return


def on_drop(event):
    if is_nur(event.getItemDrop().getItemStack()):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cКопьё Нур нельзя выбросить.")


def on_inv_click(event):
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        it = event.getCurrentItem()
        cursor = event.getCursor()
        if is_nur(it) or is_nur(cursor):
            event.setCancelled(True)
            event.getWhoClicked().sendMessage(u"§cКопьё нельзя убрать в контейнер.")


_need_respawn = set()

def on_death(event):
    """
    Soulbound (soulbound.py) сам обрабатывает предметы с PDC-меткой
    'amonra:*' и сохраняет их со ВСЕМИ данными (включая tier).
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
    if not is_amonra(player):
        return

    def _check_and_restore():
        try:
            if not player.isOnline():
                return
            # Проверяем есть ли предмет героя в инвентаре после отработки soulbound.
            if not nur_anywhere(player):
                give_nur(player, 1)
                player.sendMessage(u"§7[amonra] Копьё восстановлено на I тире (базовый).")
        except Exception:
            pass

    scheduler.runTaskLater(_check_and_restore, 40)



def on_block_break(event):
    b = event.getBlock()
    key = _block_key(b.getLocation())
    if key in pending_restore:
        event.setCancelled(True)


# =============================================================================
#  COMMAND
# =============================================================================

def cmd_amonra(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько для игроков.")
        return True
    if not is_amonra(sender):
        sender.sendMessage(u"§cТолько Амон-Ра может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/amonra <луч|форма|ульт>")
        sender.sendMessage(u"  §f/amonra форма отмена §7— досрочно выйти из Световой формы")
        return True

    sub = args[0].lower()

    if sub in (u"луч", u"beam", u"солнечный"):
        ability_beam(sender); return True
    if sub in (u"форма", u"light", u"свет"):
        if len(args) >= 2 and args[1].lower() in (u"отмена", u"cancel", u"stop"):
            cancel_light_form_early(sender)
            return True
        ability_light_form(sender); return True
    if sub in (u"ульт", u"ult", u"взрыв", u"солнце"):
        ability_ult(sender); return True

    sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
    return True


# =============================================================================
#  RESET STATE
# =============================================================================

def _amonra_reset_state(target_player):
    u = uid(target_player)
    beam_active.pop(u, None)
    if u in light_form_active:
        state = light_form_active.pop(u)
        try:
            if target_player.getGameMode() not in (GameMode.CREATIVE, GameMode.SPECTATOR):
                target_player.setFlying(state.get("prev_flying", False))
                target_player.setAllowFlight(state.get("prev_allow_flight", False))
            target_player.setCollidable(True)
        except Exception:
            pass
    ult_charging.pop(u, None)
    dark_since.pop(u, None)


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_amonra, "amonra")

listener_mgr.registerListener(on_interact,   PlayerInteractEvent)
listener_mgr.registerListener(on_damage,     EntityDamageEvent)
listener_mgr.registerListener(on_damage_by,  EntityDamageByEntityEvent)
listener_mgr.registerListener(on_drop,       PlayerDropItemEvent)
listener_mgr.registerListener(on_inv_click,  InventoryClickEvent)
listener_mgr.registerListener(on_death,      PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,    PlayerRespawnEvent)
listener_mgr.registerListener(on_block_break, BlockBreakEvent)

_passives_tick()

# --- Реестры ---
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("amonra", (kit_entry, u"Амон-Ра (Копьё Нур)"))

_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("amonra", list(AMONRA_NAMES))

_RESET_KEY = "character_reset_functions"
_reset_reg = _props.get(_RESET_KEY)
if _reset_reg is None:
    _reset_reg = HashMap()
    _props.put(_RESET_KEY, _reset_reg)
_reset_reg.put("amonra", _amonra_reset_state)


# --- Публикация функции смены тира для admin-скрипта ---
def _amonra_set_tier(target_player, tier):
    if tier < 1 or tier > 3:
        return False
    if not replace_nur(target_player, tier):
        give_nur(target_player, tier)
    try:
        target_player.sendMessage(u"§e§l⚡ §rКопьё «Нур» усилено до тира §f" + str(tier))
    except Exception: pass
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("amonra", _amonra_set_tier)


# --- Публикация в каталог Зеркала Души Арчера ---
def _amonra_mirror_nur(owner_uuid):
    return create_nur(2, owner_uuid)

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

_mirror_publish("amonra:nur", u"копьё нур", u"§eКопьё Нур", _amonra_mirror_nur)


Bukkit.getLogger().info("[amonra] Amon-Ra loaded. Commands: /test amonra, /amonra")

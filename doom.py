# -*- coding: utf-8 -*-
"""
==============================================================================
  DOCTOR DOOM / Victor von Doom (ElavetYT)
  Character script for vanilla PvP/RP server
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  Commands:
    /test doom             — give kit (Monarch Scepter, tier I)
    /doom <ability>        — abilities (require Doom sword in inventory)
        дезинтегратор | левитация | репульсор | цепи | ремонт | ульт
------------------------------------------------------------------------------
  Testing account (no cooldowns): blueredtronce
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte
from java.util import UUID as JUUID, ArrayList

from org.bukkit import (
    Bukkit, Material, Particle, Sound,
    NamespacedKey, Registry, GameMode
)
from org.bukkit.entity import (
    Player, LivingEntity, EntityType
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent,
    PlayerToggleSprintEvent, PlayerItemHeldEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDeathEvent
)
from org.bukkit.event.block import Action
from org.bukkit.enchantments import Enchantment
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.potion import PotionEffect
from org.bukkit.persistence import PersistentDataType
from org.bukkit.util import Vector

# Paper 1.20.5+ DamageSource API — обёрнуто в try, если сборка вдруг вырежет.
_HAS_DAMAGE_API = True
try:
    from org.bukkit.damage import DamageSource, DamageType
except ImportError:
    _HAS_DAMAGE_API = False


# =============================================================================
#  CONSTANTS
# =============================================================================

DOOM_OWNERS     = set([u"elavetyt", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_SWORD  = NamespacedKey.fromString("doomlord:sword")
KEY_TIER   = NamespacedKey.fromString("doomlord:tier")

# CDs (ticks).
# Ребаланс от 2026-07-28: КД Репульсора и Дезинтегратора сокращены ~в 3 раза.
# Причина: тесты показали урон 3 HP (Репульсор) и 4 HP (Дезинтегратор) при
# ожидании 6-10 и 10-16 соответственно. Вместо повышения урона (что дало бы
# ваншот-магию) увеличиваем DPS через частоту применения: персонаж становится
# активным "давящим" бойцом с постоянным техно-прессингом, а не разовыми
# крупными хитами.
CD_DISINT   = 8 * 20      # было 25 сек -> 8 сек (~3x чаще)
CD_FLIGHT   = 45 * 20
CD_REPULSOR = 7 * 20      # было 20 сек -> 7 сек (~3x чаще)
CD_CHAINS   = 35 * 20
CD_REPAIR   = 60 * 20
CD_ULT      = 4 * 60 * 20

FLIGHT_DURATION = 15 * 20
ULT_BUFF_DUR    = 15 * 20

# Progression thresholds.
TIER2_MOB_KILLS    = 500
TIER2_PLAYER_KILLS = 15


# =============================================================================
#  EFFECT / ENCHANT LOOKUP (Paper 1.21 Registry-based)
# =============================================================================

def _effect(key):
    return Registry.EFFECT.get(NamespacedKey.minecraft(key))

def _enchant(key):
    return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(key))

E_SPEED       = _effect("speed")
E_SLOWNESS    = _effect("slowness")
E_JUMP        = _effect("jump_boost")
E_STRENGTH    = _effect("strength")
E_WEAKNESS    = _effect("weakness")
E_REGEN       = _effect("regeneration")
E_RESISTANCE  = _effect("resistance")
E_ABSORPTION  = _effect("absorption")
E_MINING_FTG  = _effect("mining_fatigue")
E_NAUSEA      = _effect("nausea")
E_DARKNESS    = _effect("darkness")

ENC_SHARPNESS     = _enchant("sharpness")
ENC_FIRE_ASPECT   = _enchant("fire_aspect")
ENC_SWEEPING_EDGE = _enchant("sweeping_edge")


# =============================================================================
#  STATE
# =============================================================================

cooldowns    = {}   # uid -> {ability: end_tick}
flight_end   = {}   # uid -> tick when flight expires
repair_lock  = set()
ult_active   = set()

# Progression: uid -> {"mobs": int, "players": int}
progress = {}


# =============================================================================
#  UTILS
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

def _is_doom_role(player):
    name = player.getName().lower()
    if name not in DOOM_OWNERS:
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

def java_list(py_iterable):
    lst = ArrayList()
    for it in py_iterable:
        lst.add(it)
    return lst

def has_doom_sword(player):
    """True если в инвентаре есть меч Дума любого тира."""
    for it in player.getInventory().getContents():
        if it is None or it.getType() == Material.AIR:
            continue
        meta = it.getItemMeta()
        if meta is None:
            continue
        if meta.getPersistentDataContainer().has(KEY_SWORD, PersistentDataType.BYTE):
            return True
    return False

def is_doom_sword(item):
    if item is None or item.getType() == Material.AIR:
        return False
    meta = item.getItemMeta()
    if meta is None:
        return False
    return meta.getPersistentDataContainer().has(KEY_SWORD, PersistentDataType.BYTE)

def get_sword_tier(item):
    meta = item.getItemMeta()
    if meta is None:
        return 0
    pdc = meta.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER):
        return 0
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)


# =============================================================================
#  ITEMS
# =============================================================================

TIER_NAMES = {
    1: u"§c§lМонарший Скипетр §7§oI",
    2: u"§c§lМонарший Скипетр §6§oII",
    3: u"§4§lМонарший Скипетр §e§oIII",
}
TIER_LORE = {
    1: [
        u"§7Повреждённый клинок из сплава",
        u"§7Stark Industries, перепрошитый",
        u"§7под управление Дума.",
        u"",
        u"§8Тир: §fI §7— базовая форма.",
    ],
    2: [
        u"§7Системы стабилизированы,",
        u"§7клинок напитан магической",
        u"§7энергией Латверии.",
        u"",
        u"§8Тир: §6II §7— развитая форма.",
    ],
    3: [
        u"§7Финальная форма оружия.",
        u"§7Технологическое совершенство Старка,",
        u"§7объединённое с магией Бога-Императора.",
        u"",
        u"§8Тир: §eIII §7— легендарная форма.",
    ],
}

def create_doom_sword(tier):
    if tier <= 1:
        material = Material.STONE_SWORD
    elif tier == 2:
        material = Material.DIAMOND_SWORD
    else:
        material = Material.NETHERITE_SWORD

    it = ItemStack(material, 1)
    meta = it.getItemMeta()
    meta.setDisplayName(TIER_NAMES.get(tier, TIER_NAMES[1]))
    meta.setLore(java_list(TIER_LORE.get(tier, TIER_LORE[1])))
    meta.setUnbreakable(True)

    pdc = meta.getPersistentDataContainer()
    pdc.set(KEY_SWORD, PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_TIER,  PersistentDataType.INTEGER, tier)

    # Enchantments per tier.
    if tier == 1:
        if ENC_SHARPNESS: meta.addEnchant(ENC_SHARPNESS, 2, True)
    elif tier == 2:
        if ENC_SHARPNESS: meta.addEnchant(ENC_SHARPNESS, 4, True)
    else:
        # Тир III: Острота IV + Разящий клинок II (без Заговора огня).
        if ENC_SHARPNESS:     meta.addEnchant(ENC_SHARPNESS, 4, True)
        if ENC_SWEEPING_EDGE: meta.addEnchant(ENC_SWEEPING_EDGE, 2, True)

    it.setItemMeta(meta)
    return it


def replace_sword_in_inventory(player, new_tier):
    """Заменяет меч Дума в инвентаре на новый тир (первый найденный)."""
    inv = player.getInventory()
    contents = inv.getContents()
    for i in range(len(contents)):
        it = contents[i]
        if is_doom_sword(it):
            inv.setItem(i, create_doom_sword(new_tier))
            return True
    return False


def give_kit(player, tier=1):
    if tier < 1: tier = 1
    if tier > 3: tier = 3
    inv = player.getInventory()
    # Ищем первый свободный слот в хотбаре.
    placed = False
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_doom_sword(tier))
            placed = True
            break
    if not placed:
        inv.setItem(0, create_doom_sword(tier))
    # Инициализируем прогресс.
    if uid(player) not in progress:
        progress[uid(player)] = {"mobs": 0, "players": 0}
    tier_label = {1: u"§fI", 2: u"§6II", 3: u"§eIII"}[tier]
    player.sendMessage(u"§4✦ §cКомплект Доктора Дума выдан. §7Тир " + tier_label + u"§7.")


def kit_entry(player, args_list):
    """Обёртка для test_dispatcher: (player, args) -> None. args[0] = тир 1/2/3."""
    tier = 1
    if args_list and len(args_list) >= 1:
        try:
            tier = int(args_list[0])
        except (ValueError, TypeError):
            player.sendMessage(u"§cТир должен быть числом 1, 2 или 3. Использую 1.")
            tier = 1
        if tier < 1 or tier > 3:
            player.sendMessage(u"§cДоступные тиры: §f1§c, §62§c, §e3§c. Использую 1.")
            tier = 1
    give_kit(player, tier)


# =============================================================================
#  PROGRESSION
# =============================================================================

def _get_progress(player):
    u = uid(player)
    if u not in progress:
        progress[u] = {"mobs": 0, "players": 0}
    return progress[u]

def _current_tier_of_player(player):
    inv = player.getInventory()
    best = 0
    for it in inv.getContents():
        if is_doom_sword(it):
            t = get_sword_tier(it)
            if t > best:
                best = t
    return best

def try_upgrade_to_tier2(player):
    if _current_tier_of_player(player) >= 2:
        return
    st = _get_progress(player)
    if st["mobs"] >= TIER2_MOB_KILLS or st["players"] >= TIER2_PLAYER_KILLS:
        if replace_sword_in_inventory(player, 2):
            player.sendMessage(u"§6§l✦ Клинок стабилизирован!")
            player.sendMessage(u"§7Монарший Скипетр перешёл на §6Тир II§7.")
            player.getWorld().playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)

def try_upgrade_to_tier3(player, reason):
    if _current_tier_of_player(player) >= 3:
        player.sendMessage(u"§7Скипетр уже в финальной форме.")
        return False
    if replace_sword_in_inventory(player, 3):
        player.sendMessage(u"§e§l✦ Финальная форма достигнута!")
        player.sendMessage(u"§7Монарший Скипетр перешёл на §eТир III§7. §8(" + reason + u")")
        player.getWorld().playSound(player.getLocation(), Sound.ENTITY_ENDER_DRAGON_DEATH, 0.5, 1.4)
        return True
    return False


# =============================================================================
#  PURE / ARMOR-BYPASSING DAMAGE
# =============================================================================

def deal_pure_damage(target, amount, attacker):
    """
    Пробивает броню. Использует MAGIC damage type (в теге bypasses_armor).
    Если задан causing entity — обязателен direct entity (Paper 1.21).
    Fallback: hit-trigger + ручное списание HP.
    """
    if not isinstance(target, LivingEntity):
        return
    if _HAS_DAMAGE_API:
        try:
            src = (DamageSource.builder(DamageType.MAGIC)
                   .withDirectEntity(attacker)
                   .withCausingEntity(attacker)
                   .build())
            target.damage(amount, src)
            return
        except Exception as ex:
            Bukkit.getLogger().warning("[doom] DamageSource failed, using fallback: " + str(ex))
    # Fallback ветка.
    try:
        target.damage(0.01, attacker)
    except Exception:
        pass
    new_hp = target.getHealth() - amount
    if new_hp <= 0.0:
        try:
            target.damage(target.getMaxHealth() * 2, attacker)
        except Exception:
            target.setHealth(0.0)
    else:
        target.setHealth(new_hp)


# =============================================================================
#  ABILITIES
# =============================================================================

def _draw_beam(world, from_loc, to_loc, particle, count_per_step=2):
    dv = to_loc.toVector().subtract(from_loc.toVector())
    steps = int(dv.length() * 3)
    if steps <= 0:
        return
    step = dv.multiply(1.0 / steps)
    p = from_loc.clone()
    for i in range(steps):
        p.add(step)
        world.spawnParticle(particle, p, count_per_step, 0.02, 0.02, 0.02, 0.0)


def _find_target_generous(player, max_dist=20.0, box_radius=1.0):
    """Обёртка над hitbox_helper. Если helper не загружен — fallback
    на стандартный rayTraceEntities."""
    try:
        fn = System.getProperties().get("hitbox.find_target_in_cone")
        if fn is not None:
            return fn(player, float(max_dist), float(box_radius), 0.98, None)
    except Exception: pass
    # Fallback.
    try:
        r = player.rayTraceEntities(int(max_dist))
        if r is not None:
            h = r.getHitEntity()
            if isinstance(h, LivingEntity) and h != player:
                return h
    except Exception: pass
    return None


def ability_disintegrator(player):
    if not check_cd(player, "disint", u"«Магический Дезинтегратор»"):
        return
    world = player.getWorld()
    eye = player.getEyeLocation()

    # Ищем цель через щедрый хитбокс (raytrace + бокс 1.0 + конус 11°).
    target = _find_target_generous(player, 20.0, 1.0)

    # Визуал луча — до цели или до конца дистанции.
    if target is not None:
        end_loc = target.getEyeLocation()
    else:
        end_loc = eye.clone().add(eye.getDirection().multiply(20))
    _draw_beam(world, eye, end_loc, Particle.SOUL_FIRE_FLAME, 2)
    world.playSound(eye, Sound.ITEM_TRIDENT_THROW, 0.7, 0.6)
    world.playSound(eye, Sound.BLOCK_BEACON_DEACTIVATE, 0.6, 1.8)

    if target is not None:
        deal_pure_damage(target, 4.0, player)
        add_effect(target, E_WEAKNESS, 5 * 20, 1)
        add_effect(target, E_SLOWNESS, 5 * 20, 0)
        world.spawnParticle(Particle.SOUL, target.getLocation().add(0, 1, 0), 25, 0.4, 0.6, 0.4, 0.05)
        player.sendMessage(u"§c⚡ Дезинтегратор поразил §f" +
                           (target.getName() if isinstance(target, Player) else target.getType().name()))
    else:
        player.sendMessage(u"§7Дезинтегратор ушёл в пустоту.")

    set_cd(player, "disint", CD_DISINT)


def ability_repulsor(player):
    if not check_cd(player, "repulsor", u"«Репульсорный Импульс»"):
        return
    world = player.getWorld()
    eye = player.getEyeLocation()

    target = _find_target_generous(player, 20.0, 1.0)

    if target is not None:
        end_loc = target.getEyeLocation()
    else:
        end_loc = eye.clone().add(eye.getDirection().multiply(20))
    _draw_beam(world, eye, end_loc, Particle.END_ROD, 1)
    world.playSound(eye, Sound.ENTITY_BLAZE_SHOOT, 0.9, 1.6)

    if target is not None:
        deal_pure_damage(target, 3.0, player)
        # Отбрасывание 4-5 блоков.
        kb = player.getLocation().getDirection()
        kb.setY(0.35)
        kb = kb.normalize().multiply(2.2)
        kb.setY(0.55)
        target.setVelocity(kb)
        if isinstance(target, Player):
            target.setFallDistance(0.0)
        world.spawnParticle(Particle.EXPLOSION, target.getLocation().add(0, 1, 0), 3, 0.2, 0.4, 0.2)
        world.playSound(target.getLocation(), Sound.ENTITY_GENERIC_EXPLODE, 0.7, 1.6)
    else:
        player.sendMessage(u"§7Импульс ушёл в пустоту.")

    set_cd(player, "repulsor", CD_REPULSOR)


def ability_flight(player):
    if not check_cd(player, "flight", u"«Реактивная Левитация»"):
        return
    if player.getGameMode() == GameMode.CREATIVE or player.getGameMode() == GameMode.SPECTATOR:
        player.sendMessage(u"§7В креативе полёт и так доступен.")
        return
    u = uid(player)
    player.setAllowFlight(True)
    player.setFlying(True)
    # Абсолютное серверное время окончания фазы (в тиках wall-clock).
    flight_end[u] = now_tick() + FLIGHT_DURATION

    world = player.getWorld()
    world.spawnParticle(Particle.FLAME, player.getLocation(), 30, 0.4, 0.2, 0.4, 0.05)
    world.playSound(player.getLocation(), Sound.ENTITY_BLAZE_AMBIENT, 0.8, 1.2)
    player.sendMessage(u"§c⚡ §fДвигатели брони активированы. §715 секунд полёта.")
    set_cd(player, "flight", CD_FLIGHT)


def _find_nearest_living(player, radius):
    """Ищет ближайшего живого моба/игрока в радиусе (кроме самого игрока)."""
    world = player.getWorld()
    origin = player.getLocation()
    best = None
    best_dist = radius * radius + 1
    for e in world.getNearbyEntities(origin, radius, radius, radius):
        if not isinstance(e, LivingEntity):
            continue
        if e.getUniqueId().equals(player.getUniqueId()):
            continue
        d = e.getLocation().distanceSquared(origin)
        if d < best_dist:
            best_dist = d
            best = e
    return best


def ability_chains(player):
    if not check_cd(player, "chains", u"«Цепи Бездны»"):
        return

    # Щедрый поиск цели (raytrace + бокс 1.0 + конус 11°).
    target = _find_target_generous(player, 25.0, 1.0)

    # Тестовый фолбэк для blueredtronce: если и щедрый не нашёл —
    # берём ближайшего живого в 25 блоках (моба или игрока).
    if target is None and is_free_cd(player):
        target = _find_nearest_living(player, 25)
        if target is not None:
            player.sendMessage(u"§8[тест] Цепи наведены на ближайшего: §7" +
                               (target.getName() if isinstance(target, Player) else target.getType().name()))

    if target is None:
        player.sendMessage(u"§7Нет цели в 25 блоках.")
        return

    world = target.getWorld()
    tloc = target.getLocation()

    # Визуал цепей вырывающихся из земли.
    for dy in range(0, 3):
        world.spawnParticle(Particle.SQUID_INK, tloc.clone().add(0, dy * 0.7, 0), 15, 0.35, 0.15, 0.35, 0.02)
    world.spawnParticle(Particle.SOUL, tloc, 25, 0.4, 0.1, 0.4, 0.05)
    world.playSound(tloc, Sound.BLOCK_CHAIN_PLACE, 1.0, 0.6)
    world.playSound(tloc, Sound.ENTITY_WITHER_AMBIENT, 0.6, 1.4)

    add_effect(target, E_SLOWNESS,   4 * 20, 4)   # Slowness V
    add_effect(target, E_NAUSEA,     4 * 20, 0)
    add_effect(target, E_MINING_FTG, 4 * 20, 0)

    player.sendMessage(u"§c⚡ Цепи Бездны сковали §f" +
                       (target.getName() if isinstance(target, Player) else target.getType().name()))
    set_cd(player, "chains", CD_CHAINS)


def ability_repair(player):
    if not check_cd(player, "repair", u"«Система Авторемонта»"):
        return
    u = uid(player)
    repair_lock.add(u)
    world = player.getWorld()

    # Подготовка 3 секунды: жёсткая иммобилизация.
    add_effect(player, E_SLOWNESS, 3 * 20, 249)
    add_effect(player, E_JUMP,     3 * 20, 128)   # jump boost 128 = "негативный" прыжок, блокирует
    add_effect(player, E_MINING_FTG, 3 * 20, 4)

    player.sendMessage(u"§c⚡ §fПротокол авторемонта запущен. §73 сек. подготовки...")
    world.playSound(player.getLocation(), Sound.BLOCK_ANVIL_USE, 0.6, 1.4)

    def emit_particles(state=[0]):
        if not player.isOnline() or u not in repair_lock:
            return
        world.spawnParticle(Particle.ENCHANT, player.getLocation().add(0, 1, 0), 20, 0.6, 1.0, 0.6, 0.5)
        state[0] += 5
        if state[0] < 3 * 20:
            scheduler.runTaskLater(emit_particles, 5)
    scheduler.runTaskLater(emit_particles, 5)

    def finish():
        repair_lock.discard(u)
        if not player.isOnline():
            return
        cur = player.getHealth()
        max_hp = player.getMaxHealth()
        player.setHealth(min(max_hp, cur + 4.0))   # 2 сердца
        add_effect(player, E_ABSORPTION, 10 * 20, 1)  # Absorption II (2 золотых сердца)
        world.spawnParticle(Particle.HEART, player.getLocation().add(0, 2, 0), 6, 0.4, 0.2, 0.4)
        world.playSound(player.getLocation(), Sound.ENTITY_PLAYER_LEVELUP, 1.0, 1.6)
        player.sendMessage(u"§a✔ Броня восстановлена. §7+2❤ и §6Поглощение II §7на 10 сек.")

    scheduler.runTaskLater(finish, 3 * 20)
    set_cd(player, "repair", CD_REPAIR)


def ability_ultimate(player):
    if not check_cd(player, "ult", u"«Приговор Латверии»"):
        return
    u = uid(player)
    ult_active.add(u)
    world = player.getWorld()
    center = player.getLocation()

    world.spawnParticle(Particle.EXPLOSION, center, 3, 1.5, 0.5, 1.5)
    world.spawnParticle(Particle.LARGE_SMOKE, center, 60, 4.0, 0.5, 4.0, 0.05)
    world.playSound(center, Sound.ENTITY_ENDER_DRAGON_GROWL, 0.9, 0.7)
    world.playSound(center, Sound.ITEM_TOTEM_USE, 0.8, 0.6)

    enemies_hit = 0
    for e in world.getNearbyEntities(center, 7.0, 5.0, 7.0):
        if not isinstance(e, LivingEntity):
            continue
        if e.getUniqueId().equals(player.getUniqueId()):
            continue
        add_effect(e, E_SLOWNESS,   8 * 20, 0)
        add_effect(e, E_MINING_FTG, 8 * 20, 0)
        add_effect(e, E_DARKNESS,   8 * 20, 0)
        enemies_hit += 1

    # Баффы себе.
    add_effect(player, E_STRENGTH,   ULT_BUFF_DUR, 0)
    add_effect(player, E_REGEN,      ULT_BUFF_DUR, 1)
    add_effect(player, E_RESISTANCE, ULT_BUFF_DUR, 0)

    player.sendMessage(u"§4§l✦ Приговор Латверии! §r§7— §f" + str(enemies_hit) + u"§7 целей поражено.")

    # Дебафф после завершения ульты.
    def after_ult():
        ult_active.discard(u)
        if not player.isOnline():
            return
        add_effect(player, E_WEAKNESS, 12 * 20, 2)   # Weakness III
        add_effect(player, E_SLOWNESS, 12 * 20, 2)   # Slowness III
        player.sendMessage(u"§8Энергетический перегруз — §7Слабость III и Медлительность III на 12 сек.")

    scheduler.runTaskLater(after_ult, ULT_BUFF_DUR)
    set_cd(player, "ult", CD_ULT)


# =============================================================================
#  PASSIVES (single repeating task)
# =============================================================================

def passives_tick():
    tick = now_tick()
    for pl in Bukkit.getOnlinePlayers():
        u = uid(pl)

        # ---- Управление полётом (даже без меча в инвентаре: способность уже запущена)
        if u in flight_end:
            end = flight_end[u]
            in_creative = (pl.getGameMode() == GameMode.CREATIVE or pl.getGameMode() == GameMode.SPECTATOR)
            if tick >= end:
                # Фаза истекла — выключаем полёт (только если не креатив).
                if not in_creative:
                    pl.setFlying(False)
                    pl.setAllowFlight(False)
                    pl.sendMessage(u"§8Двигатели брони отключены.")
                del flight_end[u]
            else:
                # Фаза активна — поддерживаем возможность летать.
                if not in_creative and not pl.getAllowFlight():
                    pl.setAllowFlight(True)

        # Пассивы применяются только при наличии меча Дума.
        if not has_doom_sword(pl):
            continue

        # 1) Тяжёлая броня: постоянная Slowness I (обновляем на 60 тиков).
        add_effect(pl, E_SLOWNESS, 60, 0, ambient=True, particles=False)
        # 2) Технико-магическая нестабильность в воде: Weakness II.
        if pl.isInWater() or pl.getLocation().getBlock().getType() == Material.WATER:
            add_effect(pl, E_WEAKNESS, 40, 1, ambient=True, particles=False)
        # 3) Удаляем щиты — Абсолютная Гордыня.
        inv = pl.getInventory()
        if inv.getItemInMainHand().getType() == Material.SHIELD:
            inv.setItemInMainHand(ItemStack(Material.AIR))
            pl.sendMessage(u"§cДум не пользуется щитами.")
        if inv.getItemInOffHand().getType() == Material.SHIELD:
            inv.setItemInOffHand(ItemStack(Material.AIR))
            pl.sendMessage(u"§cДум не пользуется щитами.")


def start_passives_task():
    def loop():
        try:
            passives_tick()
        except Exception as ex:
            Bukkit.getLogger().warning("[doom] passives tick error: " + str(ex))
        scheduler.runTaskLater(loop, 20)
    scheduler.runTaskLater(loop, 20)


# =============================================================================
#  LISTENERS
# =============================================================================

def on_toggle_sprint(event):
    p = event.getPlayer()
    if not has_doom_sword(p):
        return
    if event.isSprinting():
        event.setCancelled(True)


def on_interact(event):
    if event.getHand() != EquipmentSlot.HAND:
        return
    action = event.getAction()
    if action != Action.RIGHT_CLICK_AIR and action != Action.RIGHT_CLICK_BLOCK:
        return
    p = event.getPlayer()
    item = event.getItem()
    if item is None:
        return

    # ПКМ с мечом Дума + нетерская звезда в оффхенде → апгрейд до Тира III.
    if is_doom_sword(item):
        off = p.getInventory().getItemInOffHand()
        if off is not None and off.getType() == Material.NETHER_STAR:
            event.setCancelled(True)
            if try_upgrade_to_tier3(p, u"жертва Звезды Незера"):
                off.setAmount(off.getAmount() - 1)
                if off.getAmount() <= 0:
                    p.getInventory().setItemInOffHand(ItemStack(Material.AIR))
            return

    # Блокируем использование щита.
    if item.getType() == Material.SHIELD and has_doom_sword(p):
        event.setCancelled(True)


def on_drop(event):
    it = event.getItemDrop().getItemStack()
    if is_doom_sword(it):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cМонарший Скипетр нельзя выбросить.")


def on_damage(event):
    ent = event.getEntity()
    if not isinstance(ent, Player):
        return
    if not _is_doom_role(ent):
        return
    # Гордыня — щит не должен блокировать. isBlocking() → если каким-то образом
    # ушёл в блок, обнуляем блокировку удара.
    if ent.isBlocking():
        try:
            # В Paper 1.21 есть возможность отменить блокировку через setNoDamageTicks(0)
            # + reset shield cooldown. Проще: считаем что урон применяется полностью.
            pass
        except Exception:
            pass


def on_kill(event):
    """Отслеживаем убийства для прогрессии меча."""
    victim = event.getEntity()
    killer = victim.getKiller()
    if killer is None or not isinstance(killer, Player):
        return
    if not has_doom_sword(killer):
        return

    st = _get_progress(killer)
    is_player = isinstance(victim, Player)

    if is_player:
        st["players"] += 1
        if _current_tier_of_player(killer) < 2 and st["players"] <= TIER2_PLAYER_KILLS:
            left = TIER2_PLAYER_KILLS - st["players"]
            if left > 0:
                killer.sendActionBar(u"§7Дуэлей до Тира II: §f" + str(left))
    else:
        st["mobs"] += 1
        # Wither → мгновенный Тир III.
        if victim.getType() == EntityType.WITHER:
            try_upgrade_to_tier3(killer, u"убийство Иссушителя")
            return
        if _current_tier_of_player(killer) < 2 and st["mobs"] % 50 == 0:
            left = TIER2_MOB_KILLS - st["mobs"]
            if left > 0:
                killer.sendActionBar(u"§7Мобов до Тира II: §f" + str(left))

    try_upgrade_to_tier2(killer)


# =============================================================================
#  COMMANDS
# =============================================================================

def cmd_doom(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cКоманда доступна только игрокам.")
        return True

    if not _is_doom_role(sender):
        sender.sendMessage(u"§cТолько Доктор Дум может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование: §f/doom <способность>")
        sender.sendMessage(u"§7Доступно: §fдезинтегратор§7, §fлевитация§7, §fрепульсор§7, §fцепи§7, §fремонт§7, §fульт§7.")
        return True

    if not has_doom_sword(sender):
        sender.sendMessage(u"§cДля использования способностей нужен §cМонарший Скипетр§c в инвентаре.")
        return True

    if is_silenced_by_demiurg(sender):
        sender.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return True

    if uid(sender) in repair_lock:
        sender.sendMessage(u"§cВо время авторемонта другие способности недоступны.")
        return True

    ability = args[0].lower()

    if   ability in (u"дезинтегратор", u"disint", u"disintegrator", u"deзинтегратор"):
        ability_disintegrator(sender)
    elif ability in (u"левитация", u"flight", u"полёт", u"полет"):
        ability_flight(sender)
    elif ability in (u"репульсор", u"repulsor", u"импульс"):
        ability_repulsor(sender)
    elif ability in (u"цепи", u"chains", u"chain"):
        ability_chains(sender)
    elif ability in (u"ремонт", u"repair", u"авторемонт"):
        ability_repair(sender)
    elif ability in (u"ульт", u"ультимейт", u"ult", u"ultimate", u"приговор"):
        ability_ultimate(sender)
    else:
        sender.sendMessage(u"§cНеизвестная способность: §f" + ability)
        sender.sendMessage(u"§7Доступно: §fдезинтегратор§7, §fлевитация§7, §fрепульсор§7, §fцепи§7, §fремонт§7, §fульт§7.")

    return True


def cmd_doomtier(sender, label, args):
    """Админ-команда: мгновенно установить тир меча Дума в основной руке.
       Доступна только в тестовом режиме."""
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cКоманда доступна только игрокам.")
        return True
    if not _is_doom_role(sender):
        sender.sendMessage(u"§cТолько Доктор Дум может использовать эту команду.")
        return True
    if not _test_mode_on():
        sender.sendMessage(u"§cТестовый режим выключен — команда недоступна.")
        return True
    if len(args) == 0:
        sender.sendMessage(u"§7Использование: §f/doomtier <1|2|3>")
        cur = _current_tier_of_player(sender)
        if cur > 0:
            sender.sendMessage(u"§7Текущий тир в инвентаре: §f" + str(cur))
        return True
    try:
        tier = int(args[0])
    except ValueError:
        sender.sendMessage(u"§cТир должен быть числом 1, 2 или 3.")
        return True
    if tier < 1 or tier > 3:
        sender.sendMessage(u"§cДоступные тиры: §f1§c, §62§c, §e3§c.")
        return True

    hand = sender.getInventory().getItemInMainHand()
    if is_doom_sword(hand):
        # Заменяем меч в руке напрямую.
        sender.getInventory().setItemInMainHand(create_doom_sword(tier))
    else:
        # Пробуем найти любой меч Дума в инвентаре и заменить.
        if not replace_sword_in_inventory(sender, tier):
            # Если меча нет вообще — выдаём новый в свободный слот.
            give_kit(sender, tier)
            return True

    tier_label = {1: u"§fI", 2: u"§6II", 3: u"§eIII"}[tier]
    sender.sendMessage(u"§a✔ Тир Монаршего Скипетра установлен: §7Тир " + tier_label + u"§7.")
    sender.getWorld().playSound(sender.getLocation(), Sound.BLOCK_ANVIL_USE, 0.5, 1.6)
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_doom, "doom")
cmd_mgr.registerCommand(cmd_doomtier, "doomtier")

# ---- Регистрация набора в JVM-глобальном реестре /test-диспетчера ----
from java.util import HashMap as _JHashMap
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = _JHashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("doom", (kit_entry, u"Доктор Дум (меч [тир 1|2|3])"))

# --- Публикация владельцев для admin-скрипта ---
_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = _JHashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("doom", list(DOOM_OWNERS))

# --- Публикация функции смены тира для admin-скрипта ---
def _doom_set_tier(target_player, tier):
    if tier < 1 or tier > 3:
        return False
    if not replace_sword_in_inventory(target_player, tier):
        # Меча в инвентаре нет — выдаём новый.
        give_kit(target_player, tier)
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = _JHashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("doom", _doom_set_tier)

# --- Публикация особых предметов в каталог Зеркала Души Арчера ---
def _doom_mirror_sword(owner_uuid):
    # I тир Дума — каменный меч + Sharpness II.
    # Арчер сам обернёт результат через свой sanitize и повесит TTL/kind=mirror.
    it = ItemStack(Material.STONE_SWORD, 1)
    meta = it.getItemMeta()
    meta.setDisplayName(u"§cМонарший Скипетр")
    if ENC_SHARPNESS is not None:
        meta.addEnchant(ENC_SHARPNESS, 2, True)
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

_mirror_publish("doom:sceptre", u"монарший скипетр", u"§cМонарший Скипетр", _doom_mirror_sword)

listener_mgr.registerListener(on_toggle_sprint, PlayerToggleSprintEvent)
listener_mgr.registerListener(on_interact,      PlayerInteractEvent)
listener_mgr.registerListener(on_drop,          PlayerDropItemEvent)
listener_mgr.registerListener(on_damage,        EntityDamageEvent)
listener_mgr.registerListener(on_kill,          EntityDeathEvent)

start_passives_task()

# quest_tracker: публикуем stat-функцию для чтения прогресса.
def _doom_stat(player, key):
    try:
        u = uid(player)
        st = progress.get(u, {"mobs": 0, "players": 0})
        if key == "mobs":    return int(st.get("mobs", 0))
        if key == "players": return int(st.get("players", 0))
        if key == "wither":
            # У Doom нет отдельного счётчика — считаем достижение по тиру.
            try:
                return 1 if _current_tier_of_player(player) >= 3 else 0
            except Exception:
                return 0
    except Exception: pass
    return 0

try:
    System.getProperties().put("quest_tracker.stat.doom", _doom_stat)
except Exception: pass

Bukkit.getLogger().info("[doom] Doctor Doom script loaded. Commands: /test doom, /doom <ability>")

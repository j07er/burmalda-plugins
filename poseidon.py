# -*- coding: utf-8 -*-
"""
==============================================================================
  ПОСЕЙДОН (_jeezus)
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test poseidon [1..3]        — выдать Трезубец нужного тира
  /poseidon <способность>      — способности
      волна | стремнина | ульт | улучшить | прогресс
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
    Player, LivingEntity, ElderGuardian, Guardian
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent, PlayerRespawnEvent,
    PlayerMoveEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDeathEvent,
    EntityCombustEvent, PlayerDeathEvent
)
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.event.block import Action, BlockPlaceEvent
from org.bukkit.enchantments import Enchantment
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.potion import PotionEffect
from org.bukkit.persistence import PersistentDataType
from org.bukkit.util import Vector

# DamageSource (не используется — весь урон обычный)
_HAS_DAMAGE_API = True
try:
    from org.bukkit.damage import DamageSource, DamageType
except ImportError:
    _HAS_DAMAGE_API = False


# =============================================================================
#  CONSTANTS
# =============================================================================

POSEIDON_NAMES  = set([u"_jeezus", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_TRIDENT = NamespacedKey.fromString("poseidon:trident")
KEY_TIER    = NamespacedKey.fromString("poseidon:tier")
KEY_OWNER   = NamespacedKey.fromString("poseidon:owner")

# CDs
CD_TIDE_WAVE = 20 * 20        # Приливная волна — 20 сек
CD_RAPIDS    = 30 * 20        # Стремнина — 30 сек
CD_ULT       = 4 * 60 * 20    # Ультимейт — 4 минуты

# Способности
TIDE_RADIUS       = 3.0
TIDE_STUN_TICKS   = 10        # 0.5 сек
TIDE_DAMAGE       = 8.0       # 4 сердца AoE-урона (ребаланс 2026-07-28)
RAPIDS_DISTANCE   = 7.0
RAPIDS_NO_FALL_TICKS = 3 * 20 # 3 сек игнора урона от падения
ULT_DURATION      = 6 * 20    # 6 сек
ULT_TICK_DAMAGE   = 1.0       # 0.5 сердца
ULT_WAVE_SIZE     = 5         # 5×5×5
ULT_MAX_RANGE     = 20.0

# Дегидратация: без воды 7 минут = Slowness II
DRY_TIME_LIMIT = 7 * 60 * 20

# Тиры
TIER_NAME = {
    1: u"§7§lОбычный Трезубец §f§oI",
    2: u"§b§lВерный Трезубец §f§oII",
    3: u"§9§lТрезубец Посейдона §f§oIII",
}

# Прогресс для Тира II (Сокровищница) — ресурсы в инвентаре.
T2_COSTS = [
    ("HEART_OF_THE_SEA",   1),
    ("NAUTILUS_SHELL",     8),
    ("SPONGE",             1),
    ("SEA_LANTERN",        6),
    ("MUSIC_DISC_MELLOHI", 1),
    ("MUSIC_DISC_WAIT",    1),
]

# Прогресс для Тира III.
T3_PRISMARINE_PLACED   = 36
T3_SEA_LANTERN_PLACED  = 6
T3_ELDER_GUARDIAN_KILLS = 4
T3_GUARDIAN_KILLS       = 32
T3_BURIED_TREASURE     = 2
T3_BIOMES_REQUIRED = [
    ("shipwreck",            u"Затонувший корабль"),
    ("ocean_ruins",          u"Подводные руины"),
    ("underwater_ruin",      u"Подводные руины"),   # альтернативные имена
    ("monument",             u"Подводный монумент"),
    ("warm_ocean",           u"Тёплый океан"),
    ("frozen_ocean",         u"Замёрзший океан"),
    ("deep_frozen_ocean",    u"Замёрзший океан"),
]
# Упрощённо: игрок должен побывать в биомах Warm Ocean / Frozen Ocean
# (Shipwreck/Monument/Ruins — структуры, но детектим по факту стояния рядом).


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k): return Registry.EFFECT.get(NamespacedKey.minecraft(k))
def _enchant(k): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

E_DOLPHINS_GRACE = _effect("dolphins_grace")
E_SLOWNESS       = _effect("slowness")
E_JUMP           = _effect("jump_boost")
E_MINING_FTG     = _effect("mining_fatigue")
E_WATER_BR       = _effect("water_breathing")

ENC_LOYALTY    = _enchant("loyalty")
ENC_UNBREAKING = _enchant("unbreaking")
ENC_MENDING    = _enchant("mending")


# =============================================================================
#  STATE
# =============================================================================

cooldowns = {}

# UID → tick, до которого игрок игнорирует урон от падения (после Стремнины).
rapids_no_fall = {}

# UID → tick последнего контакта с водой (для дегидратации).
last_water_touch = {}

# Прогресс: uid -> dict
# {
#   "prismarine_placed":    int,
#   "sea_lantern_placed":   int,
#   "elder_kills":          int,
#   "guardian_kills":       int,
#   "buried_treasure":      int,
#   "biomes_visited":       set of biome_key,
# }
progress = {}


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

def is_poseidon(p):
    name = p.getName().lower()
    if name not in POSEIDON_NAMES:
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


def is_trident(item):
    if item is None or item.getType() == Material.AIR: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_TRIDENT, PersistentDataType.BYTE)

def get_trident_tier(item):
    m = item.getItemMeta()
    if m is None: return 0
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER): return 0
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)

def get_trident_owner(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def can_wield(p, item):
    if not is_poseidon(p): return False
    if not is_trident(item): return False
    o = get_trident_owner(item)
    return o is None or o == uid(p)

def trident_anywhere(player):
    for it in player.getInventory().getContents():
        if is_trident(it): return True
    return False

def current_trident_tier(player):
    best = 0
    for it in player.getInventory().getContents():
        if is_trident(it):
            t = get_trident_tier(it)
            if t > best: best = t
    return best


def _get_progress(player):
    u = uid(player)
    if u not in progress:
        progress[u] = {
            "prismarine_placed": 0,
            "sea_lantern_placed": 0,
            "elder_kills": 0,
            "guardian_kills": 0,
            "buried_treasure": 0,
            "biomes_visited": set(),
        }
    return progress[u]


# =============================================================================
#  ITEM
# =============================================================================

def create_trident(tier, owner_uuid):
    if tier < 1: tier = 1
    if tier > 3: tier = 3
    it = ItemStack(Material.TRIDENT, 1)
    m = it.getItemMeta()
    m.setDisplayName(TIER_NAME[tier])
    lore = [
        u"§7Оружие Владыки морей.",
        u"§8Уровень: §f" + [u"", u"I", u"II", u"III"][tier],
    ]
    if tier == 2:
        lore.append(u"§8Верность I, Прочность I")
    elif tier == 3:
        lore.append(u"§8Верность III, Прочность III, Починка")
    lore.append(u"")
    lore.append(u"§8Только Посейдон может держать этот трезубец.")
    m.setLore(java_list(lore))
    m.setUnbreakable(True)

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_TRIDENT, PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_TIER,    PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER,   PersistentDataType.STRING,  owner_uuid)

    if tier == 2:
        if ENC_LOYALTY: m.addEnchant(ENC_LOYALTY, 1, True)
    elif tier == 3:
        if ENC_LOYALTY: m.addEnchant(ENC_LOYALTY, 3, True)

    it.setItemMeta(m)
    return it


def replace_trident(player, tier):
    inv = player.getInventory()
    contents = inv.getContents()
    for i in range(len(contents)):
        if is_trident(contents[i]):
            inv.setItem(i, create_trident(tier, uid(player)))
            return True
    return False


def give_trident(player, tier=1):
    inv = player.getInventory()
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_trident(tier, uid(player)))
            player.sendMessage(u"§9§l✦ §rТрезубец вручён. §7Уровень §f" +
                               [u"", u"I", u"II", u"III"][tier])
            return
    inv.setItem(0, create_trident(tier, uid(player)))
    player.sendMessage(u"§9§l✦ §rТрезубец вручён. §7Уровень §f" +
                       [u"", u"I", u"II", u"III"][tier])


def kit_entry(player, args_list):
    if not is_poseidon(player):
        player.sendMessage(u"§cТолько Посейдон достоин Трезубца.")
        return
    tier = 1
    if args_list and len(args_list) >= 1:
        try:
            tier = int(args_list[0])
            if tier < 1 or tier > 3: tier = 1
        except (ValueError, TypeError):
            tier = 1
    give_trident(player, tier)


# =============================================================================
#  UPGRADE
# =============================================================================

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
    cur = current_trident_tier(player)
    if cur >= 3:
        player.sendMessage(u"§7Трезубец уже в финальной форме.")
        return
    next_tier = cur + 1

    if next_tier == 2:
        # Проверяем "Сокровищницу".
        missing = []
        for mat, cnt in T2_COSTS:
            have = _count_items(player, mat)
            if have < cnt:
                missing.append(u"§7- §f" + mat + u"§7: " + str(have) + u"/" + str(cnt))
        if missing:
            player.sendMessage(u"§cНедостаточно для Тира II (Сокровищница):")
            for line in missing:
                player.sendMessage(line)
            return
        for mat, cnt in T2_COSTS:
            _remove_items(player, mat, cnt)
        replace_trident(player, 2)
        player.sendMessage(u"§b§l✦ Трезубец улучшен: §fВерный Трезубец §7(Тир II)")
        player.getWorld().playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)
        return

    if next_tier == 3:
        st = _get_progress(player)
        missing = []
        if st["prismarine_placed"] < T3_PRISMARINE_PLACED:
            missing.append(u"§7- §fПризмарин установлен§7: " +
                           str(st["prismarine_placed"]) + u"/" + str(T3_PRISMARINE_PLACED))
        if st["sea_lantern_placed"] < T3_SEA_LANTERN_PLACED:
            missing.append(u"§7- §fМорские фонари установлены§7: " +
                           str(st["sea_lantern_placed"]) + u"/" + str(T3_SEA_LANTERN_PLACED))
        if st["elder_kills"] < T3_ELDER_GUARDIAN_KILLS:
            missing.append(u"§7- §fДревние Стражи§7: " +
                           str(st["elder_kills"]) + u"/" + str(T3_ELDER_GUARDIAN_KILLS))
        if st["guardian_kills"] < T3_GUARDIAN_KILLS:
            missing.append(u"§7- §fОбычные Стражи§7: " +
                           str(st["guardian_kills"]) + u"/" + str(T3_GUARDIAN_KILLS))
        if st["buried_treasure"] < T3_BURIED_TREASURE:
            missing.append(u"§7- §fЗакопанные сокровища§7: " +
                           str(st["buried_treasure"]) + u"/" + str(T3_BURIED_TREASURE))
        # Биомы: проверяем как минимум warm_ocean, frozen_ocean, shipwreck, monument.
        required_biome_keys = {u"warm_ocean", u"frozen_ocean", u"shipwreck", u"monument", u"ocean_ruins"}
        visited = st["biomes_visited"]
        not_visited = required_biome_keys - visited
        if not_visited:
            missing.append(u"§7- §fОсталось посетить§7: §f" + u", ".join(sorted(not_visited)))

        if missing:
            player.sendMessage(u"§cНедостаточно для Тира III:")
            for line in missing:
                player.sendMessage(line)
            return
        replace_trident(player, 3)
        player.sendMessage(u"§9§l✦ Трезубец Посейдона достигнут!")
        player.getWorld().playSound(player.getLocation(), Sound.ENTITY_ENDER_DRAGON_DEATH, 0.5, 1.4)


def show_progress(player):
    st = _get_progress(player)
    cur = current_trident_tier(player)
    player.sendMessage(u"§7Прогресс Посейдона (текущий тир: §f" + str(cur) + u"§7):")
    if cur < 2:
        player.sendMessage(u"§8Для Тира II нужны предметы Сокровищницы:")
        for mat, cnt in T2_COSTS:
            have = _count_items(player, mat)
            player.sendMessage(u"  §f- §7" + mat + u": §f" + str(have) + u"§7/" + str(cnt))
    if cur < 3:
        player.sendMessage(u"§8Для Тира III:")
        player.sendMessage(u"  §f- Призмарин: §f" + str(st["prismarine_placed"]) + u"§7/" + str(T3_PRISMARINE_PLACED))
        player.sendMessage(u"  §f- Морские фонари: §f" + str(st["sea_lantern_placed"]) + u"§7/" + str(T3_SEA_LANTERN_PLACED))
        player.sendMessage(u"  §f- Древние Стражи: §f" + str(st["elder_kills"]) + u"§7/" + str(T3_ELDER_GUARDIAN_KILLS))
        player.sendMessage(u"  §f- Стражи: §f" + str(st["guardian_kills"]) + u"§7/" + str(T3_GUARDIAN_KILLS))
        player.sendMessage(u"  §f- Сокровища: §f" + str(st["buried_treasure"]) + u"§7/" + str(T3_BURIED_TREASURE))
        player.sendMessage(u"  §f- Биомы: §f" + u", ".join(sorted(st["biomes_visited"])) if st["biomes_visited"] else u"  §f- Биомы: §7(нет)")


# =============================================================================
#  ABILITIES
# =============================================================================

def _check_common(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return False
    if not trident_anywhere(player):
        player.sendMessage(u"§cНужен Трезубец в инвентаре.")
        return False
    return True


# --- 1. Приливная волна --------------------------------------------------

def ability_tide(player):
    if not _check_common(player): return
    if not check_cd(player, "tide", u"«Приливная волна»"):
        return

    world = player.getWorld()
    center = player.getLocation()

    world.playSound(center, Sound.ITEM_TRIDENT_RIPTIDE_1, 1.2, 1.0)
    world.spawnParticle(Particle.SPLASH, center, 80, TIDE_RADIUS, 0.5, TIDE_RADIUS, 0.05)
    world.spawnParticle(Particle.BUBBLE, center, 40, TIDE_RADIUS, 0.3, TIDE_RADIUS, 0.02)

    for e in world.getNearbyEntities(center, TIDE_RADIUS, TIDE_RADIUS, TIDE_RADIUS):
        if not isinstance(e, LivingEntity): continue
        if e.equals(player): continue

        # Урон AoE (ребаланс 2026-07-28). Наносится ДО setVelocity, чтобы наш
        # knockback перекрыл ванильный урона-knockback.
        try:
            e.damage(TIDE_DAMAGE, player)
        except Exception:
            pass

        # Отбрасывание.
        kb = e.getLocation().toVector().subtract(center.toVector())
        if kb.lengthSquared() < 0.01:
            kb = Vector(0, 0.5, 0)
        else:
            kb = kb.normalize().multiply(1.6)
        kb.setY(0.6)
        e.setVelocity(kb)
        if isinstance(e, Player):
            e.setFallDistance(0.0)

        # Обездвиживание 0.5 сек.
        add_effect(e, E_SLOWNESS,   TIDE_STUN_TICKS, 249, False, False)
        add_effect(e, E_JUMP,       TIDE_STUN_TICKS, 128, False, False)
        add_effect(e, E_MINING_FTG, TIDE_STUN_TICKS, 4)

    player.sendMessage(u"§b§l✦ Приливная волна!")
    set_cd(player, "tide", CD_TIDE_WAVE)


# --- 2. Стремнина --------------------------------------------------------

def ability_rapids(player):
    if not _check_common(player): return
    if not check_cd(player, "rapids", u"«Стремнина»"):
        return

    dv = player.getLocation().getDirection().normalize()
    # 7 блоков в направлении взгляда.
    vel = dv.multiply(2.1)
    if vel.getY() < 0.2:
        vel.setY(0.2)
    player.setVelocity(vel)
    player.setFallDistance(0.0)

    # Игнорируем урон от падения 3 секунды.
    rapids_no_fall[uid(player)] = now_tick() + RAPIDS_NO_FALL_TICKS

    world = player.getWorld()
    origin = player.getLocation()
    world.playSound(origin, Sound.ITEM_TRIDENT_RIPTIDE_2, 1.1, 1.2)
    world.spawnParticle(Particle.SPLASH, origin, 40, 0.5, 0.5, 0.5, 0.1)
    world.spawnParticle(Particle.BUBBLE, origin, 30, 0.4, 0.4, 0.4, 0.05)

    # Дополнительно гасим fallDistance тикер-циклом, чтобы клиент не показывал урон.
    def clear_fall(state=[0]):
        if not player.isOnline(): return
        if state[0] >= RAPIDS_NO_FALL_TICKS: return
        player.setFallDistance(0.0)
        state[0] += 5
        scheduler.runTaskLater(clear_fall, 5)
    clear_fall()

    player.sendMessage(u"§b§l✦ Стремнина!")
    set_cd(player, "rapids", CD_RAPIDS)


# --- 3. Ультимейт: Смерть Атлантиды -------------------------------------

def ability_ult(player):
    if not _check_common(player): return
    if not check_cd(player, "ult", u"«Смерть Атлантиды»"):
        return

    world = player.getWorld()
    dir_v = player.getLocation().getDirection().normalize()
    start = player.getEyeLocation()

    world.playSound(start, Sound.ENTITY_ELDER_GUARDIAN_CURSE, 1.0, 0.5)
    world.playSound(start, Sound.ITEM_TRIDENT_RIPTIDE_3, 1.2, 0.6)
    player.sendMessage(u"§9§l✦ Смерть Атлантиды! §7— 6 секунд волны.")
    set_cd(player, "ult", CD_ULT)

    state = {"tick": 0}
    hit_this_second = {"uids": set(), "sec": -1}

    def wave_tick():
        if state["tick"] >= ULT_DURATION:
            return
        if not player.isOnline():
            return

        # Волна движется вперёд каждый тик, до ULT_MAX_RANGE=20 блоков.
        speed_bl_per_tick = 0.6
        distance = min(ULT_MAX_RANGE, state["tick"] * speed_bl_per_tick)
        wave_center = start.clone().add(dir_v.clone().multiply(distance))

        # Визуал: столб 5×5×5.
        half = ULT_WAVE_SIZE // 2   # 2
        for dx in range(-half, half + 1):
            for dy in range(-half, half + 1):
                for dz in range(-half, half + 1):
                    # Только «оболочка» + случайные пузыри внутри (иначе тормозит).
                    is_edge = (abs(dx) == half or abs(dy) == half or abs(dz) == half)
                    if is_edge:
                        p = wave_center.clone().add(dx, dy, dz)
                        world.spawnParticle(Particle.SPLASH, p, 3, 0.3, 0.3, 0.3, 0.02)
                    elif (dx + dy + dz) % 2 == 0:
                        p = wave_center.clone().add(dx, dy, dz)
                        world.spawnParticle(Particle.BUBBLE, p, 2, 0.2, 0.2, 0.2, 0.01)

        # Урон + отталкивание + Slowness I всем в 5×5×5.
        current_sec = state["tick"] // 20
        if current_sec != hit_this_second["sec"]:
            hit_this_second["sec"] = current_sec
            hit_this_second["uids"].clear()

        box_r = ULT_WAVE_SIZE / 2.0 + 0.5   # 3.0
        for e in world.getNearbyEntities(wave_center, box_r, box_r, box_r):
            if not isinstance(e, LivingEntity): continue
            if e.equals(player): continue

            # Slowness I пока внутри волны (обновляется каждые 2 тика).
            add_effect(e, E_SLOWNESS, 20, 0, ambient=True, particles=False)

            # Урон — раз в секунду на цель.
            eu = uid(e)
            if eu in hit_this_second["uids"]: continue
            hit_this_second["uids"].add(eu)

            try:
                e.damage(ULT_TICK_DAMAGE, player)
            except Exception:
                pass

            # Толчок в направлении волны.
            push = dir_v.clone().multiply(1.4)
            push.setY(0.4)
            e.setVelocity(push)
            if isinstance(e, Player):
                e.setFallDistance(0.0)

        state["tick"] += 2
        scheduler.runTaskLater(wave_tick, 2)

    wave_tick()


# =============================================================================
#  PASSIVES: дельфинья грация в воде
# =============================================================================

def _is_in_water(player):
    try:
        if player.isInWater(): return True
    except Exception: pass
    try:
        return player.getLocation().getBlock().getType() == Material.WATER
    except Exception:
        return False


def _passives_tick():
    try:
        for pl in Bukkit.getOnlinePlayers():
            if not is_poseidon(pl): continue

            # Дельфинья грация III.
            if _is_in_water(pl):
                if E_DOLPHINS_GRACE is not None:
                    add_effect(pl, E_DOLPHINS_GRACE, 60, 2, ambient=True, particles=False)
                # Дышать под водой — стилистическое дополнение.
                if E_WATER_BR is not None:
                    add_effect(pl, E_WATER_BR, 60, 0, ambient=True, particles=False)
                last_water_touch[uid(pl)] = now_tick()

            # Прогресс биомов + слабости по биому/измерению.
            try:
                biome = pl.getLocation().getBlock().getBiome()
                bname = biome.getKey().getKey() if hasattr(biome, "getKey") else str(biome)
                st = _get_progress(pl)
                if bname in [u"warm_ocean", u"frozen_ocean", u"deep_frozen_ocean"]:
                    key = u"warm_ocean" if bname == u"warm_ocean" else u"frozen_ocean"
                    if key not in st["biomes_visited"]:
                        st["biomes_visited"].add(key)
                        pl.sendActionBar(u"§b§oПосещён биом: §f" + key)

                # ---- Слабость: пустыня / Незер / Энд → Slowness II ----
                env = pl.getWorld().getEnvironment().name()   # "NORMAL"/"NETHER"/"THE_END"
                in_bad_env = env in ("NETHER", "THE_END")
                in_desert_biome = "desert" in bname   # "desert", "desert_hills" и т.п.
                if in_bad_env or in_desert_biome:
                    add_effect(pl, E_SLOWNESS, 40, 1, ambient=True, particles=False)
            except Exception:
                pass

            # ---- Дегидратация: 7 минут без воды → Slowness II ----
            u = uid(pl)
            if u in last_water_touch:
                dry_ticks = now_tick() - last_water_touch[u]
                if dry_ticks >= DRY_TIME_LIMIT:
                    add_effect(pl, E_SLOWNESS, 40, 1, ambient=True, particles=False)
            else:
                # Инициализация: если игрок только что залогинился и никогда не касался воды,
                # берём момент входа за точку отсчёта — иначе Slowness сработал бы сразу.
                last_water_touch[u] = now_tick()

    except Exception as ex:
        Bukkit.getLogger().warning("[poseidon] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


# =============================================================================
#  DAMAGE HOOKS: +50% огня, +50% длительность горения
# =============================================================================

def on_damage(event):
    ent = event.getEntity()
    if not isinstance(ent, Player): return
    if not is_poseidon(ent): return

    cause = event.getCause()
    C = EntityDamageEvent.DamageCause

    # +50% от огня и лавы.
    if cause in (C.FIRE, C.FIRE_TICK, C.LAVA, C.HOT_FLOOR):
        event.setDamage(event.getDamage() * 1.5)
        return

    # Игнор урона от падения 3 сек после Стремнины.
    if cause == C.FALL:
        u = uid(ent)
        if u in rapids_no_fall and rapids_no_fall[u] > now_tick():
            event.setCancelled(True)
            return


def on_combust(event):
    """Продлеваем время горения на 50%."""
    ent = event.getEntity()
    if not isinstance(ent, Player): return
    if not is_poseidon(ent): return
    orig = event.getDuration()
    event.setDuration(int(orig * 1.5))


# =============================================================================
#  KILL / PLACE TRACKING (progression)
# =============================================================================

def on_kill(event):
    victim = event.getEntity()
    killer = victim.getKiller()
    if killer is None or not isinstance(killer, Player): return
    if not is_poseidon(killer): return
    st = _get_progress(killer)

    if isinstance(victim, ElderGuardian):
        st["elder_kills"] += 1
        killer.sendActionBar(u"§b§oДревний Страж: §f" + str(st["elder_kills"]) + u"§7/" + str(T3_ELDER_GUARDIAN_KILLS))
    elif isinstance(victim, Guardian):
        st["guardian_kills"] += 1
        if st["guardian_kills"] % 4 == 0:
            killer.sendActionBar(u"§b§oСтражи: §f" + str(st["guardian_kills"]) + u"§7/" + str(T3_GUARDIAN_KILLS))


def on_block_place(event):
    p = event.getPlayer()
    if not is_poseidon(p): return
    mat = event.getBlock().getType()
    name = mat.name()
    st = _get_progress(p)
    # Все виды призмарина.
    if "PRISMARINE" in name:
        st["prismarine_placed"] += 1
        if st["prismarine_placed"] % 6 == 0:
            p.sendActionBar(u"§b§oПризмарин: §f" + str(st["prismarine_placed"]) + u"§7/" + str(T3_PRISMARINE_PLACED))
    elif mat == Material.SEA_LANTERN:
        st["sea_lantern_placed"] += 1
        p.sendActionBar(u"§b§oМорские фонари: §f" + str(st["sea_lantern_placed"]) + u"§7/" + str(T3_SEA_LANTERN_PLACED))


# =============================================================================
#  ITEM PROTECTION / DEATH
# =============================================================================

def on_interact(event):
    if event.getHand() != EquipmentSlot.HAND: return
    p = event.getPlayer()
    item = event.getItem()
    if not is_trident(item): return
    if not can_wield(p, item):
        event.setCancelled(True)
        p.sendMessage(u"§cТрезубец отвергает тебя.")


def on_drop(event):
    if is_trident(event.getItemDrop().getItemStack()):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cТрезубец нельзя выбросить.")


def on_inv_click(event):
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        it = event.getCurrentItem()
        cursor = event.getCursor()
        if is_trident(it) or is_trident(cursor):
            event.setCancelled(True)
            event.getWhoClicked().sendMessage(u"§cТрезубец нельзя убрать в контейнер.")


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

    if not is_poseidon(player):
        return

    def _check_and_restore():
        try:
            if not player.isOnline():
                return

            if trident_anywhere(player) is None:
                give_trident(player, 1)
                player.sendMessage(u"§7[poseidon] Комплект восстановлен.")

        except Exception:
            import traceback
            traceback.print_exc()

    scheduler.runTaskLater(_check_and_restore, 40)




# =============================================================================
#  COMMAND
# =============================================================================

def cmd_poseidon(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько для игроков.")
        return True
    if not is_poseidon(sender):
        sender.sendMessage(u"§cТолько Посейдон может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/poseidon <волна|стремнина|ульт>")
        sender.sendMessage(u"  §f/poseidon улучшить §7— прокачать Трезубец")
        sender.sendMessage(u"  §f/poseidon прогресс §7— показать прогресс")
        sender.sendMessage(u"  §f/poseidon тир <1..3> §7— админ-тир (тест-мод)")
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
            sender.sendMessage(u"§7Использование: §f/poseidon тир <1..3>")
            return True
        try:
            t = int(args[1])
        except ValueError:
            sender.sendMessage(u"§cТир — число.")
            return True
        if t < 1 or t > 3:
            sender.sendMessage(u"§cТиры: 1..3.")
            return True
        if not replace_trident(sender, t):
            give_trident(sender, t)
        else:
            sender.sendMessage(u"§aТир: §f" + [u"", u"I", u"II", u"III"][t])
        return True

    if sub in (u"волна", u"tide", u"приливная"):
        ability_tide(sender)
        return True

    if sub in (u"стремнина", u"rapids", u"рывок"):
        ability_rapids(sender)
        return True

    if sub in (u"ульт", u"ult", u"атлантида"):
        ability_ult(sender)
        return True

    sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_poseidon, "poseidon")

listener_mgr.registerListener(on_interact,   PlayerInteractEvent)
listener_mgr.registerListener(on_drop,       PlayerDropItemEvent)
listener_mgr.registerListener(on_inv_click,  InventoryClickEvent)
listener_mgr.registerListener(on_death,      PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,    PlayerRespawnEvent)
listener_mgr.registerListener(on_damage,     EntityDamageEvent)
listener_mgr.registerListener(on_combust,    EntityCombustEvent)
listener_mgr.registerListener(on_kill,       EntityDeathEvent)
listener_mgr.registerListener(on_block_place, BlockPlaceEvent)

_passives_tick()

# --- Реестры ---
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("poseidon", (kit_entry, u"Посейдон (Трезубец [1..3])"))

_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("poseidon", list(POSEIDON_NAMES))

def _poseidon_set_tier(target_player, tier):
    if tier < 1 or tier > 3: return False
    if not replace_trident(target_player, tier):
        give_trident(target_player, tier)
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("poseidon", _poseidon_set_tier)


# --- Публикация в каталог Зеркала Души Арчера ---
def _poseidon_mirror_trident(owner_uuid):
    it = ItemStack(Material.TRIDENT, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§9Трезубец Посейдона")
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

_mirror_publish("poseidon:trident", u"трезубец посейдона", u"§9Трезубец Посейдона", _poseidon_mirror_trident)


# quest_tracker: публикуем stat-функцию.
# Спека quest_tracker: prismarine_placed, sea_lantern_placed, elder_guardians,
# guardians, buried_treasure. Внутри poseidon: prismarine_placed, sea_lantern_placed,
# elder_kills, guardian_kills, buried_treasure.
def _poseidon_stat(player, key):
    try:
        u = uid(player)
        st = progress.get(u, {})
        if key == "prismarine_placed":  return int(st.get("prismarine_placed", 0))
        if key == "sea_lantern_placed": return int(st.get("sea_lantern_placed", 0))
        if key == "elder_guardians":    return int(st.get("elder_kills", 0))
        if key == "guardians":          return int(st.get("guardian_kills", 0))
        if key == "buried_treasure":    return int(st.get("buried_treasure", 0))
    except Exception: pass
    return 0

try:
    System.getProperties().put("quest_tracker.stat.poseidon", _poseidon_stat)
except Exception: pass


Bukkit.getLogger().info("[poseidon] Poseidon loaded. Commands: /test poseidon, /poseidon")

# -*- coding: utf-8 -*-
"""
==============================================================================
  АРХИТЕКТОР
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test architect [1|2|3]           — выдать Мульти-Ключ нужного тира
  /architect <способность>          — активные режимы
      дым | крюк | барьер | импульс | ульт
  /architect tier <1..3>            — админ-переключение тира (для тестов)
------------------------------------------------------------------------------
  Переключение режимов Мульти-Ключа: Shift + Колесо мыши
  Активация текущего режима: ПКМ
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
    Player, LivingEntity, EnderPearl
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerItemHeldEvent, PlayerDropItemEvent,
    PlayerRespawnEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDeathEvent,
    EntityPickupItemEvent, PlayerDeathEvent, ProjectileLaunchEvent,
    EntityToggleGlideEvent
)
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.event.block import Action, BlockBreakEvent
from org.bukkit.enchantments import Enchantment
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.potion import PotionEffect
from org.bukkit.persistence import PersistentDataType
from org.bukkit.util import Vector

# DamageSource (Paper 1.20.5+)
_HAS_DAMAGE_API = True
try:
    from org.bukkit.damage import DamageSource, DamageType
except ImportError:
    _HAS_DAMAGE_API = False


# =============================================================================
#  CONSTANTS
# =============================================================================

ARCHITECT_NAMES = set([u"kawkawch"])   # тестовый набор ников
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_KEY   = NamespacedKey.fromString("architect:key")     # флаг предмета
KEY_TIER  = NamespacedKey.fromString("architect:tier")    # int тира
KEY_OWNER = NamespacedKey.fromString("architect:owner")   # uuid владельца
KEY_TEMP_BLOCK = NamespacedKey.fromString("architect:temp_block")  # маркер обсидиана

# Режимы
MODE_INFO = {
    0: (u"Дымовая Завеса",         u"§7"),
    1: (u"Магнитный Крюк",         u"§b"),
    2: (u"Паутинный Барьер",       u"§f"),
    3: (u"Кинетический Импульс",   u"§6"),
    4: (u"Ультимейт: Изоляция",    u"§5"),
}
MODE_MAX = 4

# Тиры
TIER_MATERIAL = {1: Material.IRON_PICKAXE, 2: Material.DIAMOND_PICKAXE, 3: Material.NETHERITE_PICKAXE}
TIER_NAME = {
    1: u"§7§lМульти-Ключ §f§oI",
    2: u"§b§lМульти-Ключ §f§oII",
    3: u"§4§lМульти-Ключ §f§oIII",
}
# Уменьшение урона от взрывов: множитель для входящего урона
TIER_EXPL_MULT = {1: 1.00, 2: 0.60, 3: 0.25}

# Cooldowns (тики)
CD_SMOKE   = 40 * 20
CD_HOOK    = 20 * 20
CD_BARRIER = 18 * 20
# Ребаланс от 2026-07-28: КД Кинетического Импульса сокращён 15 -> 6 сек.
# Причина: тесты показали 2 HP урона при ожидании 4-10, но по задумке это
# CC-способность (knockback first, damage second). Увеличивать урон опасно
# — быстрее давать право на очередной толчок. Аналогичный подход у Дума.
CD_PULSE   = 6 * 20       # было 15 сек -> 6 сек (2.5x чаще)
CD_ULT     = 4 * 60 * 20

# Длительности
SMOKE_DUR    = 5 * 20
HOOK_EFFECT  = 4 * 20
BARRIER_DUR  = 3 * 20
BARRIER_GLOW = 7 * 20
ULT_DUR      = 12 * 20

HOOK_RANGE   = 30.0
BARRIER_R    = 3.0
PULSE_R      = 4.0
ULT_R        = 5   # радиус куба (по X/Z)
ULT_HEIGHT   = 3

# Auto-utility шанс
AUTO_UTIL_CHANCE = 0.425

# Стакаемые материалы Сжатия Материи (вагонетки, лодки, рельсы уже 64)
STACKABLE_MATERIALS = set([
    Material.MINECART,
    Material.CHEST_MINECART,
    Material.FURNACE_MINECART,
    Material.TNT_MINECART,
    Material.HOPPER_MINECART,
    Material.COMMAND_BLOCK_MINECART,
    Material.OAK_BOAT, Material.SPRUCE_BOAT, Material.BIRCH_BOAT, Material.JUNGLE_BOAT,
    Material.ACACIA_BOAT, Material.DARK_OAK_BOAT, Material.MANGROVE_BOAT, Material.CHERRY_BOAT,
    Material.BAMBOO_RAFT,
    Material.OAK_CHEST_BOAT, Material.SPRUCE_CHEST_BOAT, Material.BIRCH_CHEST_BOAT,
    Material.JUNGLE_CHEST_BOAT, Material.ACACIA_CHEST_BOAT, Material.DARK_OAK_CHEST_BOAT,
    Material.MANGROVE_CHEST_BOAT, Material.CHERRY_CHEST_BOAT, Material.BAMBOO_CHEST_RAFT,
])


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k):  return Registry.EFFECT.get(NamespacedKey.minecraft(k))
def _enchant(k): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

E_INVIS       = _effect("invisibility")
E_BLINDNESS   = _effect("blindness")
E_SLOWNESS    = _effect("slowness")
E_GLOWING     = _effect("glowing")
E_STRENGTH    = _effect("strength")
E_RESIST      = _effect("resistance")
E_MINING_FTG  = _effect("mining_fatigue")
E_DARKNESS    = _effect("darkness")

ENC_EFFICIENCY = _enchant("efficiency")
ENC_FORTUNE    = _enchant("fortune")


# =============================================================================
#  STATE
# =============================================================================

cooldowns    = {}         # uid -> {name: end_tick}
player_mode  = {}         # uid -> mode idx
in_ult       = set()      # uid тех, кто сейчас в ульте
temp_blocks  = {}         # ключ "world,x,y,z" -> end_tick (наши временные обсидиан-блоки)
saved_walk_speed = {}     # uid -> прежний walkSpeed, чтобы вернуть


# Re-entry guard для чистого урона.
_pure_dmg_in_progress = set()


# =============================================================================
#  UTILS
# =============================================================================

def uid(e): return e.getUniqueId().toString()
def now_tick(): return long(System.currentTimeMillis() / 50)
def is_architect(p):
    name = p.getName().lower()
    if name not in ARCHITECT_NAMES:
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

def is_key(item):
    if item is None or item.getType() == Material.AIR: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_KEY, PersistentDataType.BYTE)

def get_key_tier(item):
    m = item.getItemMeta()
    if m is None: return 0
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER): return 0
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)

def get_key_owner(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def can_wield(p, item):
    if not is_architect(p): return False
    if not is_key(item): return False
    o = get_key_owner(item)
    return o is None or o == uid(p)

def key_in_hotbar_or_hand(player):
    inv = player.getInventory()
    for i in range(9):
        if is_key(inv.getItem(i)): return True
    if is_key(inv.getItemInOffHand()):
        return True
    return False

def key_in_main_hand(player):
    return is_key(player.getInventory().getItemInMainHand())

def key_anywhere(player):
    for it in player.getInventory().getContents():
        if is_key(it): return True
    return False

def find_key_tier_in_hand_or_hotbar(player):
    """Возвращает наибольший тир Мульти-Ключа в руке/хотбаре (для расчёта резиста)."""
    best = 0
    inv = player.getInventory()
    for i in range(9):
        it = inv.getItem(i)
        if is_key(it):
            t = get_key_tier(it)
            if t > best: best = t
    it = inv.getItemInOffHand()
    if is_key(it):
        t = get_key_tier(it)
        if t > best: best = t
    return best


# =============================================================================
#  MULTI-KEY ITEM
# =============================================================================

def create_key(tier, owner_uuid):
    if tier < 1: tier = 1
    if tier > 3: tier = 3
    it = ItemStack(TIER_MATERIAL[tier], 1)
    m = it.getItemMeta()
    m.setDisplayName(TIER_NAME[tier])
    lore = [
        u"§7Инженерный артефакт Архитектора.",
        u"§8Тир: §f" + [u"", u"I", u"II", u"III"][tier],
        u"",
        u"§8Shift + Колесо мыши — режим",
        u"§8ПКМ — активация режима",
    ]
    if tier == 2:
        lore.append(u"§8§oУрон от взрывов снижен на 40%.")
    elif tier == 3:
        lore.append(u"§8§oУрон от взрывов ТНТ и кристаллов снижен на 75%.")
    m.setLore(java_list(lore))
    m.setUnbreakable(True)

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_KEY,   PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_TIER,  PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER, PersistentDataType.STRING,  owner_uuid)

    # Зачарования по тиру.
    if tier == 1:
        if ENC_EFFICIENCY: m.addEnchant(ENC_EFFICIENCY, 2, True)
    elif tier == 2:
        if ENC_EFFICIENCY: m.addEnchant(ENC_EFFICIENCY, 4, True)
        if ENC_FORTUNE:    m.addEnchant(ENC_FORTUNE, 2, True)
    else:
        if ENC_EFFICIENCY: m.addEnchant(ENC_EFFICIENCY, 5, True)
        if ENC_FORTUNE:    m.addEnchant(ENC_FORTUNE, 3, True)

    it.setItemMeta(m)
    return it


def replace_key(player, tier):
    inv = player.getInventory()
    contents = inv.getContents()
    for i in range(len(contents)):
        if is_key(contents[i]):
            inv.setItem(i, create_key(tier, uid(player)))
            return True
    return False


def give_key(player, tier=1):
    inv = player.getInventory()
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_key(tier, uid(player)))
            player_mode[uid(player)] = 0
            player.sendMessage(u"§b§l✦ §rМульти-Ключ выдан. §7Тир §f" +
                               [u"", u"I", u"II", u"III"][tier])
            return
    inv.setItem(0, create_key(tier, uid(player)))
    player_mode[uid(player)] = 0
    player.sendMessage(u"§b§l✦ §rМульти-Ключ выдан. §7Тир §f" +
                       [u"", u"I", u"II", u"III"][tier])


def kit_entry(player, args_list):
    if not is_architect(player):
        player.sendMessage(u"§cТолько Архитектор может получить Мульти-Ключ.")
        return
    tier = 1
    if args_list and len(args_list) >= 1:
        try:
            tier = int(args_list[0])
            if tier < 1 or tier > 3: tier = 1
        except (ValueError, TypeError):
            tier = 1
    give_key(player, tier)


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
#  MODES: LABEL / SCROLL
# =============================================================================

def get_mode(p):
    return player_mode.get(uid(p), 0)

def set_mode(p, idx):
    idx = idx % (MODE_MAX + 1)
    player_mode[uid(p)] = idx
    name, color = MODE_INFO[idx]
    p.sendMessage(u"§8⌬ §fРежим: " + color + name + u" §7[" + str(idx) + u"]")
    p.playSound(p.getLocation(), Sound.UI_BUTTON_CLICK, 0.6, 1.7)
    _update_key_lore(p)

def _update_key_lore(player):
    inv = player.getInventory()
    for i in range(9):
        it = inv.getItem(i)
        if not is_key(it): continue
        m = it.getItemMeta()
        if m is None: continue
        tier = get_key_tier(it)
        mode = get_mode(player)
        name, color = MODE_INFO[mode]
        lore = [
            u"§7Инженерный артефакт Архитектора.",
            u"§8Тир: §f" + [u"", u"I", u"II", u"III"][tier],
            u"§8Режим: " + color + name + u" §7[" + str(mode) + u"]",
            u"",
            u"§8Shift + Колесо мыши — режим",
            u"§8ПКМ — активация",
        ]
        if tier == 2:
            lore.append(u"§8§o-40% урона от взрывов.")
        elif tier == 3:
            lore.append(u"§8§o-75% урона от ТНТ и кристаллов.")
        m.setLore(java_list(lore))
        it.setItemMeta(m)


# =============================================================================
#  ABILITY 1 — ДЫМОВАЯ ЗАВЕСА
# =============================================================================

def ability_smoke(player):
    if not check_cd(player, "smoke", u"«Дымовая Завеса»"):
        return
    world = player.getWorld()
    loc = player.getLocation()

    add_effect(player, E_INVIS, SMOKE_DUR, 0)
    player.sendMessage(u"§7§l✦ Дымовая Завеса §r§7— 5 сек. невидимости.")

    # Наносим врагам эффекты.
    for e in world.getNearbyEntities(loc, 3.0, 3.0, 3.0):
        if isinstance(e, LivingEntity) and not e.equals(player):
            add_effect(e, E_BLINDNESS, SMOKE_DUR, 0)
            add_effect(e, E_SLOWNESS,  SMOKE_DUR, 1)

    # Пульсация облака дыма 5 секунд.
    state = {"t": 0}
    def puff():
        if state["t"] >= SMOKE_DUR: return
        c = player.getLocation()
        world.spawnParticle(Particle.LARGE_SMOKE, c, 40, 3.0, 1.5, 3.0, 0.02)
        world.spawnParticle(Particle.CLOUD,       c, 20, 2.5, 1.0, 2.5, 0.01)
        state["t"] += 10
        scheduler.runTaskLater(puff, 10)
    puff()
    world.playSound(loc, Sound.BLOCK_FIRE_EXTINGUISH, 1.0, 0.7)
    set_cd(player, "smoke", CD_SMOKE)


# =============================================================================
#  ABILITY 2 — МАГНИТНЫЙ СПУСКОВОЙ КРЮК (ЛУЧ)
# =============================================================================

def _draw_beam(world, from_loc, to_loc, particle):
    dv = to_loc.toVector().subtract(from_loc.toVector())
    dist = dv.length()
    if dist < 0.01: return
    steps = int(dist * 3)
    if steps < 1: steps = 1
    step = dv.multiply(1.0 / steps)
    p = from_loc.clone()
    for i in range(steps):
        p.add(step)
        world.spawnParticle(particle, p, 1, 0.02, 0.02, 0.02, 0.0)

def _find_target_generous(player, max_dist, box_radius=1.0):
    """Обёртка над hitbox_helper. Fallback на rayTraceEntities если helper не загружен."""
    try:
        fn = System.getProperties().get("hitbox.find_target_in_cone")
        if fn is not None:
            return fn(player, float(max_dist), float(box_radius), 0.98, None)
    except Exception: pass
    try:
        r = player.rayTraceEntities(int(max_dist))
        if r is not None:
            h = r.getHitEntity()
            if isinstance(h, LivingEntity) and h != player:
                return h
    except Exception: pass
    return None


def ability_hook(player):
    if not check_cd(player, "hook", u"«Магнитный Крюк»"):
        return
    world = player.getWorld()
    eye = player.getEyeLocation()

    # Приоритет: щедрый поиск живой цели. Если не нашли — крюк цепляется за блок.
    target_entity = _find_target_generous(player, HOOK_RANGE, 1.0)
    blk_res = player.rayTraceBlocks(HOOK_RANGE)

    end_loc = eye.clone().add(eye.getDirection().multiply(HOOK_RANGE))

    if target_entity is not None:
        end_loc = target_entity.getLocation().add(0, target_entity.getHeight() * 0.5, 0)
    elif blk_res is not None and blk_res.getHitPosition() is not None:
        end_loc = blk_res.getHitPosition().toLocation(world)

    # Мгновенный луч частиц.
    _draw_beam(world, eye, end_loc, Particle.END_ROD)
    world.playSound(eye, Sound.ITEM_CROSSBOW_SHOOT, 0.9, 1.6)

    if target_entity is not None:
        # ============ ПОЙМАЛИ ИГРОКА / МОБА ============
        # 1. Определяем состояние жертвы: летит? скользит на элитрах? стоит?
        was_gliding = False
        was_flying  = False
        on_ground   = True
        try:
            if hasattr(target_entity, "isGliding"):
                was_gliding = bool(target_entity.isGliding())
        except Exception: pass
        try:
            if hasattr(target_entity, "isOnGround"):
                on_ground = bool(target_entity.isOnGround())
        except Exception:
            on_ground = True
        if isinstance(target_entity, Player):
            try:
                was_flying = bool(target_entity.isFlying())
            except Exception:
                was_flying = False

        # 2. Отключаем полёт/элитры ДО применения velocity — иначе flight гасит его.
        if isinstance(target_entity, Player):
            gm = target_entity.getGameMode()
            if gm not in (GameMode.CREATIVE, GameMode.SPECTATOR):
                try:
                    if target_entity.isFlying():
                        target_entity.setFlying(False)
                    if target_entity.getAllowFlight():
                        target_entity.setAllowFlight(False)
                except Exception: pass
        try:
            if hasattr(target_entity, "setGliding"):
                target_entity.setGliding(False)
        except Exception: pass

        # 3. МАГНИТНЫЙ УДАР.
        #  * Летящий/глайдящий/в воздухе → slam вниз (сбить с воздуха).
        #  * Стоячий на земле → тянем ЖЕРТВУ к Архитектору (velocity в его
        #    сторону + teleport lift чтобы Paper/Leaf не откатили velocity
        #    из-за isOnGround-rewind). Дублируем velocity 1 и 3 тик спустя.
        try:
            target_entity.setFallDistance(0.0)
        except Exception: pass

        in_air = (was_gliding or was_flying or not on_ground)

        if in_air:
            # ---- ЛЕТЕЛ: slam вниз ----
            try:
                target_entity.setVelocity(Vector(0.0, -1.8, 0.0))
            except Exception: pass
            def _slam_down(t=target_entity):
                try:
                    if t.isValid() and not t.isDead():
                        t.setVelocity(Vector(0.0, -1.8, 0.0))
                        t.setFallDistance(0.0)
                except Exception: pass
            scheduler.runTaskLater(_slam_down, 1)
            scheduler.runTaskLater(_slam_down, 3)
        else:
            # ---- СТОЯЛ НА ЗЕМЛЕ: тянем к Архитектору ----
            # Не разовый толчок (velocity затухает быстро), а поддерживаемая
            # тяга: каждые 2 тика проверяем расстояние и подталкиваем к
            # Архитектору. Останавливаемся когда близко или прошло 20 тиков.

            # 3a. Teleport lift на 0.35 бл — сбрасываем isOnGround,
            #     иначе Paper/Leaf откатят velocity.
            if isinstance(target_entity, Player):
                try:
                    lift_loc = target_entity.getLocation().clone()
                    lift_loc.setY(lift_loc.getY() + 0.35)
                    target_entity.teleport(lift_loc)
                except Exception: pass

            # 3b. Тикер поддерживающей тяги.
            STOP_DIST     = 2.0   # блока: ближе не тянем
            MAX_PULL_TICK = 20    # 1 сек максимум
            state = {"t": 0}

            def _pull_tick(t=target_entity, arch=player, st=state):
                try:
                    if not (t.isValid() and not t.isDead()):
                        return
                    if not (arch.isOnline() and arch.isValid()):
                        return
                    if st["t"] >= MAX_PULL_TICK:
                        return

                    aloc = arch.getLocation()
                    tloc = t.getLocation()
                    dx = aloc.getX() - tloc.getX()
                    dy = aloc.getY() - tloc.getY()
                    dz = aloc.getZ() - tloc.getZ()
                    dist3d = (dx * dx + dy * dy + dz * dz) ** 0.5
                    dist_h = (dx * dx + dz * dz) ** 0.5

                    # Если уже близко — стоп.
                    if dist3d <= STOP_DIST:
                        return

                    # Скорость пропорциональна оставшейся дистанции.
                    # Формула: за 2 тика при v0 и drag 0.91 жертва пролетит
                    # S ≈ v0 * (1 + 0.91) = v0 * 1.91. Так что чтобы пройти
                    # (dist - STOP_DIST) за одно применение velocity:
                    # v0 = (dist - STOP_DIST) / 1.91.
                    remaining = max(0.0, dist_h - STOP_DIST)
                    speed = min(1.6, max(0.5, remaining / 1.91))

                    if dist_h < 0.3:
                        # Прямо на нас — не толкаем горизонтально.
                        nx = 0.0; nz = 0.0
                    else:
                        nx = dx / dist_h
                        nz = dz / dist_h

                    # Y-компонента: если жертва ниже Архитектора — чуть
                    # поднимаем; выше — тянем вниз; примерно на одном уровне —
                    # маленький подскок чтобы isOnGround сбрасывался.
                    if dy > 1.0:
                        vy = min(0.6, dy * 0.25)   # снизу вверх
                    elif dy < -1.0:
                        vy = max(-0.6, dy * 0.20)  # сверху вниз
                    else:
                        vy = 0.20

                    try:
                        t.setVelocity(Vector(nx * speed, vy, nz * speed))
                        t.setFallDistance(0.0)
                    except Exception:
                        return

                    st["t"] += 2
                    scheduler.runTaskLater(_pull_tick, 2)
                except Exception: pass

            _pull_tick()

        # 3d. Звук приземления/захвата через 6 тиков.
        def _land_sound(t=target_entity):
            try:
                if t.isValid() and not t.isDead():
                    tw = t.getWorld()
                    tl = t.getLocation()
                    tw.playSound(tl, Sound.BLOCK_ANVIL_LAND, 0.7, 1.2)
                    tw.spawnParticle(Particle.CRIT, tl.clone().add(0, 0.3, 0),
                                     30, 0.5, 0.2, 0.5, 0.1)
            except Exception: pass
        scheduler.runTaskLater(_land_sound, 8)

        # 4. Эффект замедления (Slowness II, 4 сек).
        add_effect(target_entity, E_SLOWNESS, HOOK_EFFECT, 1)

        # 5. Визуал + звук магнитного захвата.
        try:
            twloc = target_entity.getLocation()
            twworld = target_entity.getWorld()
            twworld.playSound(twloc, Sound.ITEM_TRIDENT_HIT_GROUND, 1.0, 1.0)
            twworld.playSound(twloc, Sound.BLOCK_CHAIN_BREAK, 1.1, 0.7)
            # Кольцо электрических частиц вокруг жертвы.
            try:
                twworld.spawnParticle(Particle.ELECTRIC_SPARK,
                                      twloc.clone().add(0, 1.0, 0),
                                      30, 0.6, 0.9, 0.6, 0.3)
            except Exception:
                twworld.spawnParticle(Particle.END_ROD,
                                      twloc.clone().add(0, 1.0, 0),
                                      20, 0.4, 0.6, 0.4, 0.05)
        except Exception: pass

        # 6. Сообщения обеим сторонам.
        tname = target_entity.getName() if isinstance(target_entity, Player) else target_entity.getType().name()
        player.sendMessage(u"§b§l✦ §rКрюк захватил §f" + tname)
        try:
            player.sendActionBar(u"§b⚡ §fМагнитный захват §7» §f" + tname
                                 + u" §7(Slowness II, 4 сек)")
        except Exception: pass
        if isinstance(target_entity, Player):
            try:
                target_entity.sendActionBar(u"§c§l⚡ §rМагнитный захват! §7Slowness II 4 сек")
            except Exception: pass
            if was_flying or was_gliding:
                target_entity.sendMessage(u"§c§l⚡ §rАрхитектор сбил тебя с воздуха!")

    elif blk_res is not None and blk_res.getHitBlock() is not None:
        # Притягиваем сами.
        dv = end_loc.toVector().subtract(player.getLocation().toVector())
        dist = dv.length()
        if dist > 0.1:
            dv = dv.normalize()
            speed = 0.5 + min(2.5, dist * 0.28)
            vel = dv.multiply(speed)
            if vel.getY() < 0.35: vel.setY(0.45)
            player.setVelocity(vel)
            player.setFallDistance(0.0)
            # Гасим падение периодически.
            for t in (10, 20, 30, 40, 60):
                scheduler.runTaskLater(
                    lambda p=player: (p.isOnline() and p.setFallDistance(0.0)),
                    t
                )
        player.sendMessage(u"§b§l✦ §rКрюк зацепился.")
    else:
        player.sendMessage(u"§7Крюк ушёл в пустоту.")

    set_cd(player, "hook", CD_HOOK)


# =============================================================================
#  ABILITY 3 — ПАУТИННЫЙ БАРЬЕР
# =============================================================================

def _place_temp_obsidian(block, ticks_life):
    """Ставит наш обсидиан и планирует снятие."""
    mat = block.getType()
    if not (mat.isAir() or mat == Material.WATER or mat == Material.SHORT_GRASS or mat == Material.TALL_GRASS):
        return None
    block.setType(Material.OBSIDIAN)
    l = block.getLocation()
    key = u"%s,%d,%d,%d" % (l.getWorld().getName(), l.getBlockX(), l.getBlockY(), l.getBlockZ())
    temp_blocks[key] = now_tick() + ticks_life
    def remove():
        cur = block.getType()
        if cur == Material.OBSIDIAN and key in temp_blocks:
            block.setType(Material.AIR)
        temp_blocks.pop(key, None)
    scheduler.runTaskLater(remove, ticks_life)
    return key

def _place_temp_cobweb(block, ticks_life):
    mat = block.getType()
    if not (mat.isAir() or mat == Material.WATER or mat == Material.SHORT_GRASS or mat == Material.TALL_GRASS):
        return
    block.setType(Material.COBWEB)
    l = block.getLocation()
    key = u"%s,%d,%d,%d" % (l.getWorld().getName(), l.getBlockX(), l.getBlockY(), l.getBlockZ())
    temp_blocks[key] = now_tick() + ticks_life
    def remove():
        cur = block.getType()
        if cur == Material.COBWEB and key in temp_blocks:
            block.setType(Material.AIR)
        temp_blocks.pop(key, None)
    scheduler.runTaskLater(remove, ticks_life)


def ability_barrier(player):
    if not check_cd(player, "barrier", u"«Паутинный Барьер»"):
        return
    world = player.getWorld()
    center = player.getLocation()
    # Клетка 7×3×7 (радиус 3): стены + КРЫША (потолок на dy=2).
    # Пол не ставим — игрок стоит нормально.
    r = int(BARRIER_R)
    for dx in range(-r, r + 1):
        for dy in range(0, 3):
            for dz in range(-r, r + 1):
                # Стенки — на самом радиусе.
                is_wall = (abs(dx) == r or abs(dz) == r)
                # Крыша — верхний слой (dy=2), покрываем ВСЮ плоскость.
                is_roof = (dy == 2)
                if is_wall or is_roof:
                    b = center.getBlock().getRelative(dx, dy, dz)
                    _place_temp_cobweb(b, BARRIER_DUR)

    world.spawnParticle(Particle.CLOUD, center, 60, 3.0, 1.5, 3.0, 0.02)
    world.playSound(center, Sound.BLOCK_WOOL_PLACE, 1.0, 1.2)

    # Свечение всех живых в радиусе 3.
    for e in world.getNearbyEntities(center, BARRIER_R, BARRIER_R, BARRIER_R):
        if isinstance(e, LivingEntity) and not e.equals(player):
            add_effect(e, E_GLOWING, BARRIER_GLOW, 0)
            add_effect(e, E_SLOWNESS, BARRIER_DUR, 2)
            if isinstance(e, Player):
                # Блокируем элитры на 7 сек через флаг + снятие glide.
                try:
                    if hasattr(e, "setGliding"): e.setGliding(False)
                except Exception: pass

    player.sendMessage(u"§f§l✦ Паутинный Барьер §r§7— 3 сек. клетка, 7 сек. свечения.")
    set_cd(player, "barrier", CD_BARRIER)


# =============================================================================
#  ABILITY 4 — КИНЕТИЧЕСКИЙ ИМПУЛЬС
# =============================================================================

# Множество uid'ов Архитекторов, которые сейчас в "полёте" после Кинетического
# Импульса. В on_damage отменяем FALL-урон для них. Флаг снимается через 15 сек.
_pulse_no_fall = set()


def ability_pulse(player):
    if not check_cd(player, "pulse", u"«Кинетический Импульс»"):
        return
    world = player.getWorld()
    center = player.getLocation()

    world.spawnParticle(Particle.EXPLOSION, center, 3, 1.0, 0.5, 1.0)
    world.spawnParticle(Particle.LARGE_SMOKE, center, 40, PULSE_R, 0.5, PULSE_R, 0.05)
    world.playSound(center, Sound.ENTITY_GENERIC_EXPLODE, 0.9, 1.6)

    for e in world.getNearbyEntities(center, PULSE_R, PULSE_R, PULSE_R):
        if not isinstance(e, LivingEntity): continue
        if e.equals(player): continue
        deal_pure_damage(e, 2.0, player)   # 1 сердце
        # Откид на 5 блоков.
        kb = e.getLocation().toVector().subtract(center.toVector())
        if kb.lengthSquared() < 0.01:
            kb = player.getLocation().getDirection()
        kb = kb.normalize().multiply(1.9)
        kb.setY(0.7)
        e.setVelocity(kb)

    # Себя вверх на ~4 блока.
    player.setVelocity(Vector(0.0, 1.15, 0.0))
    player.setFallDistance(0.0)

    # Иммунитет к падению на 15 секунд.
    # ВНИМАНИЕ: раньше стоял setFallDistance(0.0) через тики (10..100), но если
    # игрок падал дольше 5 сек — урон всё равно проходил. Теперь просто отменяем
    # FALL-урон в on_damage через флаг _pulse_no_fall.
    u_str = uid(player)
    _pulse_no_fall.add(u_str)

    def _clear_immunity():
        try:
            _pulse_no_fall.discard(u_str)
        except Exception: pass

    scheduler.runTaskLater(_clear_immunity, 15 * 20)

    player.sendMessage(u"§6§l✦ Кинетический Импульс!")
    set_cd(player, "pulse", CD_PULSE)
    # quest_tracker: отчёт о касте импульса.
    try:
        fn = System.getProperties().get("quest_tracker.report_architect_pulse")
        if fn is not None: fn(player)
    except Exception: pass


# =============================================================================
#  ABILITY 5 — УЛЬТИМЕЙТ: ПРОТОКОЛ ИЗОЛЯЦИЯ
# =============================================================================

def ability_ult(player):
    if not check_cd(player, "ult", u"«Протокол: Изоляция»"):
        return
    world = player.getWorld()
    center = player.getLocation()
    cb = center.getBlock()

    # Собираем всех сущностей внутри клетки — для дебаффа.
    trapped_uids = set()
    for e in world.getNearbyEntities(center, ULT_R, ULT_R, ULT_R):
        if isinstance(e, LivingEntity) and not e.equals(player):
            trapped_uids.add(uid(e))
            add_effect(e, E_MINING_FTG, ULT_DUR, 0)

    # Строим "клетку": стены на радиусе ±R по X/Z, крыша над центром на высоте ULT_HEIGHT,
    # пол — не трогаем (Архитектор стоит на земле).
    my_keys = []
    for dy in range(0, ULT_HEIGHT + 1):
        # Крыша сверху — на dy == ULT_HEIGHT.
        if dy == ULT_HEIGHT:
            for dx in range(-ULT_R, ULT_R + 1):
                for dz in range(-ULT_R, ULT_R + 1):
                    b = cb.getRelative(dx, dy, dz)
                    k = _place_temp_obsidian(b, ULT_DUR)
                    if k: my_keys.append(k)
        else:
            # Стены — только на радиусе.
            for dx in range(-ULT_R, ULT_R + 1):
                for dz in range(-ULT_R, ULT_R + 1):
                    if abs(dx) == ULT_R or abs(dz) == ULT_R:
                        b = cb.getRelative(dx, dy, dz)
                        k = _place_temp_obsidian(b, ULT_DUR)
                        if k: my_keys.append(k)

    add_effect(player, E_STRENGTH, ULT_DUR, 0)
    add_effect(player, E_RESIST,   ULT_DUR, 0)
    in_ult.add(uid(player))
    world.playSound(center, Sound.ENTITY_WITHER_SPAWN, 0.9, 0.7)
    player.sendMessage(u"§5§l✦ Протокол: Изоляция §r§7— 12 сек. Ты неуязвим внутри клетки.")

    def finish():
        in_ult.discard(uid(player))
        if not player.isOnline(): return
        # Дебаффы после ульта.
        add_effect(player, E_SLOWNESS,  5 * 20, 2)   # III
        add_effect(player, E_BLINDNESS, 5 * 20, 0)
        player.sendMessage(u"§8Системы перегружены — §7Медлительность III + Слепота на 5 сек.")
    scheduler.runTaskLater(finish, ULT_DUR)

    set_cd(player, "ult", CD_ULT)


# =============================================================================
#  PASSIVES: скорость, сжатие материи, авто-утилизатор, взрывы
# =============================================================================

BASE_SPEED = 0.2
ARCH_SPEED = 0.2 * 0.93   # -7%

def _apply_compaction(item):
    """Ставит stack size = 64 для вагонеток/лодок."""
    if item is None or item.getType() == Material.AIR: return
    if item.getType() not in STACKABLE_MATERIALS: return
    m = item.getItemMeta()
    if m is None: return
    try:
        # Paper 1.20.5+
        m.setMaxStackSize(64)
        item.setItemMeta(m)
    except Exception:
        pass


def _passives_tick():
    try:
        for pl in Bukkit.getOnlinePlayers():
            u = uid(pl)
            has_key = key_anywhere(pl)

            # Тяжёлая экипировка: -7% скорости пока ключ в инвентаре.
            if has_key:
                if pl.getWalkSpeed() > ARCH_SPEED + 0.001:
                    if u not in saved_walk_speed:
                        saved_walk_speed[u] = pl.getWalkSpeed()
                    pl.setWalkSpeed(ARCH_SPEED)
            else:
                if u in saved_walk_speed:
                    try:
                        pl.setWalkSpeed(saved_walk_speed[u])
                    except Exception:
                        pl.setWalkSpeed(BASE_SPEED)
                    saved_walk_speed.pop(u, None)

            # Сжатие материи: пробегаем инвентарь Архитектора.
            if is_architect(pl):
                inv = pl.getInventory()
                for i in range(inv.getSize()):
                    _apply_compaction(inv.getItem(i))
    except Exception as ex:
        Bukkit.getLogger().warning("[architect] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


# =============================================================================
#  EVENT HANDLERS
# =============================================================================

def on_item_held(event):
    player = event.getPlayer()
    if not player.isSneaking(): return
    inv = player.getInventory()
    prev = event.getPreviousSlot()
    nxt  = event.getNewSlot()
    if not (is_key(inv.getItem(prev)) or is_key(inv.getItem(nxt))):
        return

    diff = nxt - prev
    if   diff ==  8: direction = -1
    elif diff == -8: direction =  1
    elif diff  >  0: direction =  1
    else:            direction = -1

    set_mode(player, get_mode(player) + direction)
    event.setCancelled(True)


def on_interact(event):
    if event.getHand() != EquipmentSlot.HAND: return
    action = event.getAction()
    if action != Action.RIGHT_CLICK_AIR and action != Action.RIGHT_CLICK_BLOCK:
        return
    p = event.getPlayer()
    item = event.getItem()
    if not is_key(item): return
    if not can_wield(p, item):
        event.setCancelled(True)
        p.sendMessage(u"§cМульти-Ключ отвергает тебя.")
        return
    event.setCancelled(True)

    if is_silenced_by_demiurg(p):
        p.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return

    mode = get_mode(p)
    if   mode == 0: ability_smoke(p)
    elif mode == 1: ability_hook(p)
    elif mode == 2: ability_barrier(p)
    elif mode == 3: ability_pulse(p)
    elif mode == 4: ability_ult(p)


def on_drop(event):
    if is_key(event.getItemDrop().getItemStack()):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cМульти-Ключ нельзя выбросить.")


def on_inv_click(event):
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        it = event.getCurrentItem()
        cursor = event.getCursor()
        if is_key(it) or is_key(cursor):
            event.setCancelled(True)
            event.getWhoClicked().sendMessage(u"§cМульти-Ключ нельзя убрать в контейнер.")


_need_respawn = set()

def on_death(event):
    """
    Soulbound (soulbound.py) сам обрабатывает предметы с PDC-меткой
    'architect:*' и сохраняет их со ВСЕМИ данными (включая tier).
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
    if not is_architect(player):
        return

    def _check_and_restore():
        try:
            if not player.isOnline():
                return
            # Проверяем есть ли предмет героя в инвентаре после отработки soulbound.
            if not key_anywhere(player):
                give_key(player, 1)
                player.sendMessage(u"§7[architect] Комплект восстановлен на I тире (базовый).")
        except Exception:
            pass

    scheduler.runTaskLater(_check_and_restore, 40)



def on_damage(event):
    ent = event.getEntity()
    if not isinstance(ent, Player): return

    # +10% урона от магии/зелий (Уязвимость к магии).
    cause = event.getCause()
    C = EntityDamageEvent.DamageCause
    if is_architect(ent):
        # Иммунитет к падению после Кинетического Импульса.
        if cause == C.FALL and uid(ent) in _pulse_no_fall:
            event.setCancelled(True)
            try:
                ent.setFallDistance(0.0)
            except Exception: pass
            return
        if cause in (C.MAGIC,):
            event.setDamage(event.getDamage() * 1.10)
        # Взрывной урон снижаем по тиру ключа.
        if cause in (C.ENTITY_EXPLOSION, C.BLOCK_EXPLOSION):
            tier = find_key_tier_in_hand_or_hotbar(ent)
            mult = TIER_EXPL_MULT.get(tier, 1.0)
            if mult < 1.0:
                event.setDamage(event.getDamage() * mult)


def on_damage_by(event):
    # Уязвимость к магии от чужих способностей: даже если cause не MAGIC,
    # но атакующий явно использует "магический" урон (DamageSource.type == MAGIC).
    ent = event.getEntity()
    if not isinstance(ent, Player): return
    if not is_architect(ent): return
    if uid(ent) in _pure_dmg_in_progress: return
    if _HAS_DAMAGE_API:
        try:
            src = event.getDamageSource()
            if src is not None:
                dt = src.getDamageType()
                if dt is not None and dt == DamageType.MAGIC:
                    event.setDamage(event.getDamage() * 1.10)
                    return
        except Exception:
            pass


def on_kill(event):
    """Авто-утилизатор."""
    victim = event.getEntity()
    if isinstance(victim, Player): return
    killer = victim.getKiller()
    if killer is None or not isinstance(killer, Player): return
    if not is_architect(killer): return
    if not key_anywhere(killer): return

    import random
    if random.random() > AUTO_UTIL_CHANCE:
        return

    if random.random() < 0.5:
        # Набор детонации: 3 пороха + 2 железа.
        _give_or_drop(killer, ItemStack(Material.GUNPOWDER, 3))
        _give_or_drop(killer, ItemStack(Material.IRON_INGOT, 2))
        killer.sendActionBar(u"§8§oАвто-Утилизатор: §fНабор детонации")
    else:
        _give_or_drop(killer, ItemStack(Material.REDSTONE, 4))
        _give_or_drop(killer, ItemStack(Material.SLIME_BALL, 1))
        killer.sendActionBar(u"§8§oАвто-Утилизатор: §fНабор механизмов")


def _give_or_drop(player, item):
    leftover = player.getInventory().addItem(item)
    if leftover:
        # Jython не поддерживает tuple-unpacking для Map.Entry — берём .values().
        for drop in leftover.values():
            player.getWorld().dropItemNaturally(player.getLocation(), drop)


def on_pickup(event):
    """Сжатие материи: заходящий предмет получает stack=64."""
    ent = event.getEntity()
    if not isinstance(ent, Player): return
    if not is_architect(ent): return
    item = event.getItem().getItemStack()
    if item is None or item.getType() == Material.AIR: return
    if item.getType() in STACKABLE_MATERIALS:
        _apply_compaction(item)
        event.getItem().setItemStack(item)


def on_block_break(event):
    """Не даём ломать нашу временную клетку/паутину."""
    b = event.getBlock()
    if b.getType() not in (Material.OBSIDIAN, Material.COBWEB):
        return
    l = b.getLocation()
    key = u"%s,%d,%d,%d" % (l.getWorld().getName(), l.getBlockX(), l.getBlockY(), l.getBlockZ())
    if key in temp_blocks:
        event.setCancelled(True)


def on_projectile_launch(event):
    """В зоне Паутинного Барьера — блокируем эндер-перл."""
    proj = event.getEntity()
    if not isinstance(proj, EnderPearl): return
    shooter = proj.getShooter()
    if not isinstance(shooter, Player): return
    if not shooter.hasPotionEffect(E_GLOWING): return
    # Свечение может быть от чего угодно, но в связке с "внутри барьера" —
    # проверяем близость к любому нашему временному COBWEB.
    loc = shooter.getLocation()
    for k in temp_blocks.keys():
        try:
            parts = k.split(",")
            if parts[0] != loc.getWorld().getName(): continue
            x = int(parts[1]); y = int(parts[2]); z = int(parts[3])
            dx = loc.getBlockX() - x
            dy = loc.getBlockY() - y
            dz = loc.getBlockZ() - z
            if abs(dx) <= 4 and abs(dz) <= 4 and abs(dy) <= 3:
                event.setCancelled(True)
                shooter.sendMessage(u"§8Паутинный Барьер блокирует эндер-перл.")
                return
        except Exception:
            continue


def on_glide(event):
    """В зоне Паутинного Барьера — блок элитры.
       Используем EntityToggleGlideEvent (более широкий, чем Paper-only PlayerToggleGlideEvent),
       но фильтруем только игроков."""
    ent = event.getEntity()
    if not isinstance(ent, Player):
        return
    if not event.isGliding():
        return
    if not ent.hasPotionEffect(E_GLOWING):
        return
    loc = ent.getLocation()
    for k in temp_blocks.keys():
        try:
            parts = k.split(",")
            if parts[0] != loc.getWorld().getName(): continue
            x = int(parts[1]); y = int(parts[2]); z = int(parts[3])
            if abs(loc.getBlockX() - x) <= 4 and abs(loc.getBlockZ() - z) <= 4:
                event.setCancelled(True)
                ent.sendMessage(u"§8Паутинный Барьер блокирует элитру.")
                return
        except Exception:
            continue


# =============================================================================
#  COMMAND /architect
# =============================================================================

def cmd_architect(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько для игроков.")
        return True
    if not is_architect(sender):
        sender.sendMessage(u"§cТолько Архитектор может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/architect <дым|крюк|барьер|импульс|ульт>")
        sender.sendMessage(u"  §f/architect tier <1..3>")
        return True

    sub = args[0].lower()

    if sub == u"tier":
        if not _test_mode_on():
            sender.sendMessage(u"§cТестовый режим выключен — команда недоступна.")
            return True
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/architect tier <1..3>")
            return True
        try:
            t = int(args[1])
        except ValueError:
            sender.sendMessage(u"§cТир — число.")
            return True
        if t < 1 or t > 3:
            sender.sendMessage(u"§cТиры: 1..3")
            return True
        if not replace_key(sender, t):
            give_key(sender, t)
        else:
            sender.sendMessage(u"§aМульти-Ключ обновлён до тира " + [u"", u"I", u"II", u"III"][t])
        _update_key_lore(sender)
        return True

    # Способности требуют ключ.
    if not key_anywhere(sender):
        sender.sendMessage(u"§cДля использования способностей нужен §fМульти-Ключ§c.")
        return True

    if is_silenced_by_demiurg(sender):
        sender.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return True

    if   sub in (u"дым", u"завеса", u"smoke"):    ability_smoke(sender)
    elif sub in (u"крюк", u"магнит", u"hook"):    ability_hook(sender)
    elif sub in (u"барьер", u"паутина"):          ability_barrier(sender)
    elif sub in (u"импульс", u"толчок", u"pulse"):ability_pulse(sender)
    elif sub in (u"ульт", u"ультимейт", u"ult", u"изоляция"):
                                                  ability_ult(sender)
    else:
        sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_architect, "architect")

listener_mgr.registerListener(on_item_held,         PlayerItemHeldEvent)
listener_mgr.registerListener(on_interact,          PlayerInteractEvent)
listener_mgr.registerListener(on_drop,              PlayerDropItemEvent)
listener_mgr.registerListener(on_inv_click,         InventoryClickEvent)
listener_mgr.registerListener(on_death,             PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,           PlayerRespawnEvent)
listener_mgr.registerListener(on_damage,            EntityDamageEvent)
listener_mgr.registerListener(on_damage_by,         EntityDamageByEntityEvent)
listener_mgr.registerListener(on_kill,              EntityDeathEvent)
listener_mgr.registerListener(on_pickup,            EntityPickupItemEvent)
listener_mgr.registerListener(on_block_break,       BlockBreakEvent)
listener_mgr.registerListener(on_projectile_launch, ProjectileLaunchEvent)
listener_mgr.registerListener(on_glide,             EntityToggleGlideEvent)

_passives_tick()

# --- Регистрация набора в /test-диспетчере ---
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("architect", (kit_entry, u"Архитектор (Мульти-Ключ [тир 1..3])"))

# --- Публикация владельцев для admin-скрипта ---
_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("architect", list(ARCHITECT_NAMES))

# --- Публикация функции смены тира для admin-скрипта ---
def _architect_set_tier(target_player, tier):
    if tier < 1 or tier > 3:
        return False
    if not replace_key(target_player, tier):
        give_key(target_player, tier)
    _update_key_lore(target_player)
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("architect", _architect_set_tier)


# --- Публикация в каталог Зеркала Души Арчера ---
# Фабрика возвращает ЧИСТЫЙ ItemStack I-тира: правильный материал, имя,
# зачарования I тира. Арчер сам обернёт через _sanitize_mirror и повесит TTL.
def _arch_mirror_key(owner_uuid):
    it = ItemStack(Material.IRON_PICKAXE, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§7Мульти-Ключ")
    if ENC_EFFICIENCY is not None:
        m.addEnchant(ENC_EFFICIENCY, 2, True)
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

_mirror_publish("architect:key", u"мульти-ключ", u"§7Мульти-Ключ", _arch_mirror_key)


Bukkit.getLogger().info("[architect] Architect loaded. Commands: /test architect, /architect")

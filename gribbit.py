# -*- coding: utf-8 -*-
"""
==============================================================================
  ГРИББИТ (kwaksha) — человек-лягушка, страж болот
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test griblet [1..3]     — выдать Посох болотного стража нужного тира
  /griblet <способность>   — способности
      прыжок | язык | ульт | улучшить | тир <n>
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, Long as JLong
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, GameMode, Location
)
from org.bukkit.entity import (
    Player, LivingEntity, Slime
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent, PlayerRespawnEvent,
    PlayerMoveEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDeathEvent,
    EntityRegainHealthEvent, PlayerDeathEvent
)
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.event.block import Action
from org.bukkit.enchantments import Enchantment
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.potion import PotionEffect
from org.bukkit.persistence import PersistentDataType
from org.bukkit.util import Vector

# DamageSource
_HAS_DAMAGE_API = True
try:
    from org.bukkit.damage import DamageSource, DamageType
except ImportError:
    _HAS_DAMAGE_API = False


# =============================================================================
#  CONSTANTS
# =============================================================================

GRIBLET_NAMES    = set([u"kwaksha_"])
FREE_CD_PLAYERS  = set([u"blueredtronce"])

KEY_STAFF = NamespacedKey.fromString("griblet:staff")
KEY_TIER  = NamespacedKey.fromString("griblet:tier")
KEY_OWNER = NamespacedKey.fromString("griblet:owner")

# Тиры
TIER_MATERIAL = {1: Material.IRON_SWORD, 2: Material.DIAMOND_SWORD, 3: Material.NETHERITE_SWORD}
TIER_NAME = {
    1: u"§7§lПосох болотного стража §f§oI",
    2: u"§b§lПосох болотного стража §f§oII",
    3: u"§2§lПосох болотного стража §f§oIII §7(Легендарный)",
}

# CDs (ticks)
CD_JUMP    = 18 * 20
CD_TONGUE  = 60 * 20
CD_ULT     = int(4.5 * 60) * 20

# Способности
JUMP_DISTANCE     = 8.0
JUMP_RESIST_DUR   = 2 * 20
SLOW_CLOUD_DUR    = 3 * 20

TONGUE_MAX_RANGE  = 30.0
TONGUE_CLOSE      = 15.0
TONGUE_STUN_DUR   = 1 * 20

ULT_UP_HEIGHT     = 17     # блоков вверх
ULT_HANG_TICKS    = 2 * 20 # 2 сек висит
ULT_R_INNER       = 5.0
ULT_R_OUTER       = 7.0
ULT_DMG_INNER     = 8.0    # 4 сердца
ULT_DMG_OUTER     = 3.0    # 1.5 сердца

# Прогресс — Тир II
T2_SLIMES_KILLED  = 40
T2_MUD_BLOCKS     = 32

# Прогресс — Тир III (рецепт-ресурсы)
T3_SLIME_BLOCKS   = 64
T3_NETHERITE_BLK  = 2
T3_DIAMONDS       = 64

# Тир III — авто-триггер на низком HP
T3_LOW_HP           = 6.0    # 3 сердца
T3_RESIST_DUR       = 8 * 20
T3_REGEN_DUR        = 2 * 20
T3_LOW_HP_COOLDOWN  = 5 * 60 * 20

# Высыхание — 2 минуты на суше
DRY_TIME_TICKS = 2 * 60 * 20


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k):  return Registry.EFFECT.get(NamespacedKey.minecraft(k))
def _enchant(k): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

E_SLOWNESS   = _effect("slowness")
E_JUMP       = _effect("jump_boost")
E_MINING_FTG = _effect("mining_fatigue")
E_WEAKNESS   = _effect("weakness")
E_RESIST     = _effect("resistance")
E_REGEN      = _effect("regeneration")
E_NAUSEA     = _effect("nausea")
E_INVIS      = _effect("invisibility")
E_WATER_BREATH = _effect("water_breathing")   # для пассива в воде
E_DOLPHIN    = _effect("dolphins_grace")

ENC_SHARPNESS  = _enchant("sharpness")
ENC_UNBREAKING = _enchant("unbreaking")
ENC_KNOCKBACK  = _enchant("knockback")
ENC_MENDING    = _enchant("mending")


# =============================================================================
#  STATE
# =============================================================================

cooldowns   = {}
stunned     = {}     # uid -> end_tick
hit_counter = {}     # uid_kris_style — uid Гриббита -> счётчик атак (для тира II)
low_hp_last = {}     # uid -> tick последнего триггера тира III
progress    = {}     # uid -> {"slimes": int, "mud": int}
dry_ticks   = {}     # uid -> сколько тиков не в воде
last_water_msg = {}  # uid -> tick последнего сообщения о высыхании

# Ульт-состояние
ult_state = {}       # uid -> {"start_tick", "orig_loc"}
# Множество uid'ов Гриблетов, у которых активен ульт-полёт.
# Пока флаг активен — FALL-урон отменяется полностью (даже пассивный -60%).
# Флаг устанавливается на старте ability_ult, снимается через 3 сек после impact_at.
_ult_no_fall = set()

# Re-entry guard.
_pure_dmg_in_progress = set()


# =============================================================================
#  UTILS
# =============================================================================

def uid(e): return e.getUniqueId().toString()
def now_tick(): return long(System.currentTimeMillis() / 50)
def is_griblet(p):
    name = p.getName().lower()
    if name not in GRIBLET_NAMES:
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

def is_staff(item):
    if item is None or item.getType() == Material.AIR: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_STAFF, PersistentDataType.BYTE)

def get_staff_tier(item):
    m = item.getItemMeta()
    if m is None: return 0
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER): return 0
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)

def get_staff_owner(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def can_wield(p, item):
    if not is_griblet(p): return False
    if not is_staff(item): return False
    o = get_staff_owner(item)
    return o is None or o == uid(p)

def staff_anywhere(player):
    for it in player.getInventory().getContents():
        if is_staff(it): return True
    return False

def staff_in_hand(player):
    return is_staff(player.getInventory().getItemInMainHand())

def current_staff_tier(player):
    best = 0
    for it in player.getInventory().getContents():
        if is_staff(it):
            t = get_staff_tier(it)
            if t > best: best = t
    return best

def _get_progress(player):
    u = uid(player)
    if u not in progress:
        progress[u] = {"slimes": 0, "mud": 0}
    return progress[u]


# =============================================================================
#  ITEM
# =============================================================================

def create_staff(tier, owner_uuid):
    if tier < 1: tier = 1
    if tier > 3: tier = 3
    it = ItemStack(TIER_MATERIAL[tier], 1)
    m = it.getItemMeta()
    m.setDisplayName(TIER_NAME[tier])
    lore = [
        u"§7Символ силы стража болот.",
        u"§8Тир: §f" + [u"", u"I", u"II", u"III"][tier],
    ]
    if tier == 2:
        lore.append(u"§8§oКаждый 7-й удар: Слабость I на 1 сек.")
    elif tier == 3:
        lore.append(u"§8§oАвто-щит при HP ≤ 3❤ (КД 5 мин).")
    lore.append(u"")
    lore.append(u"§8Только Гриббит может использовать этот посох.")
    m.setLore(java_list(lore))

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_STAFF, PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_TIER,  PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER, PersistentDataType.STRING,  owner_uuid)

    if tier == 1:
        if ENC_SHARPNESS: m.addEnchant(ENC_SHARPNESS, 2, True)
    elif tier == 2:
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 3, True)
    else:
        if ENC_SHARPNESS:  m.addEnchant(ENC_SHARPNESS, 4, True)
        if ENC_KNOCKBACK:  m.addEnchant(ENC_KNOCKBACK, 1, True)

    # Все тиры Посоха неразрушимы (Unbreaking/Mending убраны — они лишние).
    m.setUnbreakable(True)

    it.setItemMeta(m)
    return it


def replace_staff(player, tier):
    inv = player.getInventory()
    contents = inv.getContents()
    for i in range(len(contents)):
        if is_staff(contents[i]):
            inv.setItem(i, create_staff(tier, uid(player)))
            return True
    return False


def give_staff(player, tier=1):
    inv = player.getInventory()
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_staff(tier, uid(player)))
            player.sendMessage(u"§2§l✦ §rПосох болотного стража. §7Тир §f" +
                               [u"", u"I", u"II", u"III"][tier])
            return
    inv.setItem(0, create_staff(tier, uid(player)))
    player.sendMessage(u"§2§l✦ §rПосох болотного стража. §7Тир §f" +
                       [u"", u"I", u"II", u"III"][tier])


def kit_entry(player, args_list):
    if not is_griblet(player):
        player.sendMessage(u"§cТолько Гриббит владеет Посохом.")
        return
    tier = 1
    if args_list and len(args_list) >= 1:
        try:
            tier = int(args_list[0])
            if tier < 1 or tier > 3: tier = 1
        except (ValueError, TypeError):
            tier = 1
    give_staff(player, tier)


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
    cur = current_staff_tier(player)
    if cur >= 3:
        player.sendMessage(u"§7Посох уже в финальной форме.")
        return
    next_tier = cur + 1

    if next_tier == 2:
        # 40 слизней + 32 грязи
        prog = _get_progress(player)
        missing = []
        if prog["slimes"] < T2_SLIMES_KILLED:
            missing.append(u"§7- §fслизней убито§7: " + str(prog["slimes"]) + u"/" + str(T2_SLIMES_KILLED))
        if prog["mud"] < T2_MUD_BLOCKS:
            missing.append(u"§7- §fблоков грязи§7: " + str(prog["mud"]) + u"/" + str(T2_MUD_BLOCKS))
        if missing:
            player.sendMessage(u"§cНедостаточно для Тира II:")
            for line in missing:
                player.sendMessage(line)
            return
        # Не сбрасываем счётчики — оставляем для истории.
        replace_staff(player, 2)
        player.sendMessage(u"§d§l✦ Посох улучшен до Тира II!")
        player.getWorld().playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)
        return

    if next_tier == 3:
        # 64 слизи (блоков) + 2 незеритовых блока + 64 алмаза
        need = [
            ("SLIME_BLOCK",       T3_SLIME_BLOCKS),
            ("NETHERITE_BLOCK",   T3_NETHERITE_BLK),
            ("DIAMOND",           T3_DIAMONDS),
        ]
        missing = []
        for mat_name, cnt in need:
            have = _count_items(player, mat_name)
            if have < cnt:
                missing.append(u"§7- §f" + mat_name + u"§7: " + str(have) + u"/" + str(cnt))
        if missing:
            player.sendMessage(u"§cНедостаточно для Тира III:")
            for line in missing:
                player.sendMessage(line)
            return
        for mat_name, cnt in need:
            _remove_items(player, mat_name, cnt)
        replace_staff(player, 3)
        player.sendMessage(u"§d§l✦ Легендарный Посох болотного стража!")
        player.getWorld().playSound(player.getLocation(), Sound.ENTITY_ENDER_DRAGON_DEATH, 0.5, 1.4)


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
#  ABILITY 1 — СКОЛЬЗЯЩИЙ ПРЫЖОК
# =============================================================================

def ability_jump(player):
    if not check_cd(player, "jump", u"«Скользящий прыжок»"):
        return
    world = player.getWorld()
    origin = player.getLocation()

    # Направление: горизонтальный компонент взгляда.
    dv = player.getLocation().getDirection()
    dv.setY(0)
    if dv.lengthSquared() < 0.01:
        dv = Vector(0, 0, 1)
    dv = dv.normalize().multiply(1.7)   # горизонтальная скорость
    dv.setY(0.6)                        # немного вверх, чтобы был "рывок"
    player.setVelocity(dv)
    player.setFallDistance(0.0)

    add_effect(player, E_RESIST, JUMP_RESIST_DUR, 1)   # Сопротивление II

    world.playSound(origin, Sound.ENTITY_FROG_LONG_JUMP, 1.0, 1.2)
    world.spawnParticle(Particle.CLOUD, origin, 25, 0.3, 0.3, 0.3, 0.05)

    # Оставляем облако Замедления на позиции старта на 3 сек.
    center = origin.clone()
    state = {"t": 0}
    def cloud_tick():
        if state["t"] >= SLOW_CLOUD_DUR:
            return
        world.spawnParticle(Particle.MYCELIUM, center, 25, 1.2, 0.5, 1.2, 0.01)
        # Наносим Slowness I всем в радиусе 2 блока.
        for e in world.getNearbyEntities(center, 2.0, 2.0, 2.0):
            if isinstance(e, LivingEntity) and not e.equals(player):
                add_effect(e, E_SLOWNESS, 20, 0)
        state["t"] += 10
        scheduler.runTaskLater(cloud_tick, 10)
    cloud_tick()

    # Гасим fall damage на протяжении полёта.
    for t in (10, 20, 30, 40, 60, 80):
        scheduler.runTaskLater(lambda p=player: (p.isOnline() and p.setFallDistance(0.0)), t)

    set_cd(player, "jump", CD_JUMP)


# =============================================================================
#  ABILITY 2 — ЛИПКИЙ ЯЗЫК
# =============================================================================

def _find_target_generous(player, max_dist=30.0, box_radius=1.5):
    """Обёртка над hitbox_helper: aim-assist поиск цели.
    Даёт «толстый» хитбокс (1.5 бл) + конус, так что далёкие цели не мажут."""
    try:
        fn = System.getProperties().get("hitbox.find_target_in_cone")
        if fn is not None:
            return fn(player, float(max_dist), float(box_radius), 0.985, None)
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


def ability_tongue(player):
    if not check_cd(player, "tongue", u"«Липкий язык»"):
        return
    world = player.getWorld()
    eye = player.getEyeLocation()

    # Ищем цель через щедрый aim-assist (толстый хитбокс + конус).
    # Раньше стоял rayTraceEntities — на 30 бл он часто мазал из-за узкого
    # хитбокса. Теперь на дистанции 15+ язык корректно захватывает цель.
    target = _find_target_generous(player, TONGUE_MAX_RANGE, 1.5)
    if target is None:
        player.sendMessage(u"§cНет цели.")
        return

    if not isinstance(target, LivingEntity) or target.equals(player):
        player.sendMessage(u"§cНеверная цель.")
        return

    # Проверяем прямую видимость через rayTraceBlocks — не должен быть блок между.
    blk_res = player.rayTraceBlocks(TONGUE_MAX_RANGE)
    if blk_res is not None and blk_res.getHitBlock() is not None:
        block_dist = eye.distance(blk_res.getHitPosition().toLocation(world))
        target_dist = eye.distance(target.getLocation())
        if block_dist < target_dist - 0.5:
            player.sendMessage(u"§cЯзык не проходит сквозь стены.")
            return

    # Визуал: язык — линия SLIME_BALL / DRIPPING_HONEY.
    end_loc = target.getLocation().add(0, target.getHeight() * 0.5, 0)
    dv = end_loc.toVector().subtract(eye.toVector())
    steps = int(dv.length() * 4)
    if steps < 1: steps = 1
    step = dv.multiply(1.0 / steps)
    p = eye.clone()
    for i in range(steps):
        p.add(step)
        world.spawnParticle(Particle.ITEM_SLIME, p, 2, 0.05, 0.05, 0.05, 0.0)
    world.playSound(eye, Sound.ENTITY_FROG_TONGUE, 1.0, 1.1)

    dist = eye.distance(end_loc)
    if dist <= TONGUE_CLOSE:
        # Ближе 15 блоков — Гриббит подтягивается + 2 сердца + оглушение 1 сек.
        tp_loc = target.getLocation().clone()
        # Останавливаемся чуть перед целью, чтобы не залезть внутрь.
        back = target.getLocation().getDirection().multiply(-1.5)
        tp_loc.add(back)
        tp_loc.setYaw(player.getLocation().getYaw())
        tp_loc.setPitch(player.getLocation().getPitch())
        player.teleport(tp_loc)
        player.setFallDistance(0.0)
        try:
            target.damage(4.0, player)
        except Exception:
            pass
        _apply_stun(target, TONGUE_STUN_DUR)
        world.spawnParticle(Particle.CRIT, target.getLocation().add(0, 1, 0), 15, 0.4, 0.5, 0.4, 0.05)
        player.sendMessage(u"§a§l✦ §rЯзык захватил §f" +
                           (target.getName() if isinstance(target, Player) else target.getType().name()))
    else:
        # Дальше 15 блоков — тянем цель к Гриббиту + Slowness II на 2 сек.
        kb = player.getLocation().toVector().subtract(target.getLocation().toVector())
        if kb.lengthSquared() < 0.01:
            kb = Vector(0, 0.4, 0)
        else:
            dist_scale = kb.length()
            kb = kb.normalize().multiply(min(2.5, 0.4 + dist_scale * 0.15))
            kb.setY(0.4)
        target.setVelocity(kb)
        add_effect(target, E_SLOWNESS, 2 * 20, 1)
        if isinstance(target, Player):
            target.setFallDistance(0.0)
        player.sendMessage(u"§a§l✦ §rЯзык дотянулся до §f" +
                           (target.getName() if isinstance(target, Player) else target.getType().name()))

    set_cd(player, "tongue", CD_TONGUE)


def _apply_stun(target, ticks):
    """Оглушение: не двигается, не атакует, не может юзать. Голова свободна."""
    stunned[uid(target)] = now_tick() + ticks
    add_effect(target, E_SLOWNESS,   ticks, 249, False, False)
    add_effect(target, E_JUMP,       ticks, 128, False, False)
    add_effect(target, E_MINING_FTG, ticks, 4)


# =============================================================================
#  ABILITY 3 — УЛЬТ «ЖАБИЙ МЕТЕОРИТ»
# =============================================================================

def ability_ult(player):
    if not check_cd(player, "ult", u"«Жабий Метеорит»"):
        return
    world = player.getWorld()
    orig_loc = player.getLocation().clone()

    # Подпрыгиваем на 17 блоков.
    player.setVelocity(Vector(0.0, 2.6, 0.0))
    player.setFallDistance(0.0)
    add_effect(player, E_INVIS, ULT_HANG_TICKS + 40, 0)

    # Иммунитет к FALL-урону на всё время полёта + приземления.
    # Раньше здесь стоял setFallDistance(0) на 5 тиков (10..100), но fallDistance
    # копится между тиками и в момент impact_at сервер применяет urodn. Теперь
    # просто отменяем FALL в on_damage через флаг.
    u_str = uid(player)
    _ult_no_fall.add(u_str)

    world.playSound(orig_loc, Sound.ENTITY_FROG_LONG_JUMP, 1.2, 0.8)
    ult_state[u_str] = {"start_tick": now_tick(), "orig_loc": orig_loc}

    # Хвост частиц во время полёта — визуал метеорита.
    def trail(state=[0]):
        try:
            if not player.isOnline(): return
            if state[0] >= 5 * 20: return   # 5 сек максимум
            loc = player.getLocation()
            world.spawnParticle(Particle.CLOUD, loc, 5, 0.2, 0.2, 0.2, 0.02)
            world.spawnParticle(Particle.END_ROD, loc, 2, 0.1, 0.1, 0.1, 0.01)
            state[0] += 2
            scheduler.runTaskLater(trail, 2)
        except Exception: pass
    scheduler.runTaskLater(trail, 2)

    def crash():
        """Через 2 сек в верхней точке — резкий рывок вниз."""
        if not player.isOnline():
            ult_state.pop(uid(player), None)
            return
        # Резкое падение.
        player.setVelocity(Vector(0.0, -3.5, 0.0))
        player.setFallDistance(0.0)
        # Ждём приземление — polling каждые 2 тика, максимум 40 попыток (~4 сек).
        def wait_landing(attempts=[0]):
            try:
                if not player.isOnline():
                    ult_state.pop(uid(player), None)
                    return
                attempts[0] += 1
                try:
                    on_ground = player.isOnGround()
                except Exception:
                    on_ground = False
                if on_ground or attempts[0] > 40:
                    impact_at(player.getLocation())
                    return
                scheduler.runTaskLater(wait_landing, 2)
            except Exception: pass
        wait_landing()

    def impact_at(land):
        """Взрыв в точке приземления: волна из частиц + урон 2 радиуса."""
        try:
            # Звук + большой взрыв частиц.
            world.playSound(land, Sound.ENTITY_GENERIC_EXPLODE, 1.5, 0.7)
            world.playSound(land, Sound.ENTITY_WARDEN_SONIC_BOOM, 0.9, 1.5)
            world.spawnParticle(Particle.EXPLOSION_EMITTER, land, 3, 1.5, 0.5, 1.5)
            world.spawnParticle(Particle.LARGE_SMOKE, land, 80, ULT_R_OUTER, 0.5, ULT_R_OUTER, 0.05)

            # ВОЛНА: рисуем кольца из частиц, расходящиеся от центра.
            def wave_ring(state=[0]):
                try:
                    r = float(state[0]) * 0.7
                    if r > ULT_R_OUTER + 1:
                        return
                    import math
                    steps = max(12, int(r * 8))
                    for i in range(steps):
                        a = (2.0 * math.pi * i) / steps
                        x = land.getX() + r * math.cos(a)
                        z = land.getZ() + r * math.sin(a)
                        p = land.clone()
                        p.setX(x); p.setZ(z)
                        p.setY(land.getY() + 0.5)
                        world.spawnParticle(Particle.CAMPFIRE_COSY_SMOKE, p, 1, 0.0, 0.0, 0.0, 0.0)
                        world.spawnParticle(Particle.SPLASH,               p, 2, 0.1, 0.1, 0.1, 0.0)
                    state[0] += 1
                    scheduler.runTaskLater(wave_ring, 1)
                except Exception: pass
            wave_ring()

            # УРОН. Используем deal_pure_damage — надёжнее чем e.damage() при
            # Invisibility (сервер иногда игнорирует damager).
            for e in world.getNearbyEntities(land, ULT_R_OUTER + 1, ULT_R_OUTER + 1, ULT_R_OUTER + 1):
                if not isinstance(e, LivingEntity): continue
                if e.equals(player): continue
                d = e.getLocation().distance(land)
                if d <= ULT_R_INNER:
                    deal_pure_damage(e, ULT_DMG_INNER, player)
                    kb = e.getLocation().toVector().subtract(land.toVector())
                    if kb.lengthSquared() < 0.01:
                        kb = Vector(0, 1, 0)
                    kb = kb.normalize().multiply(2.5)
                    kb.setY(1.0)
                    try: e.setVelocity(kb)
                    except Exception: pass
                elif d <= ULT_R_OUTER:
                    deal_pure_damage(e, ULT_DMG_OUTER, player)
                    add_effect(e, E_NAUSEA, 3 * 20, 0)
                    kb = e.getLocation().toVector().subtract(land.toVector())
                    if kb.lengthSquared() < 0.01:
                        kb = Vector(0, 0.5, 0)
                    kb = kb.normalize().multiply(1.2)
                    kb.setY(0.5)
                    try: e.setVelocity(kb)
                    except Exception: pass

            player.setFallDistance(0.0)
            player.sendMessage(u"§2§l✦ Жабий Метеорит!")
        except Exception as ex:
            Bukkit.getLogger().warning("[griblet] impact: " + str(ex))
        finally:
            ult_state.pop(uid(player), None)
            # Иммунитет к FALL держим ещё 60 тиков (3 сек) на случай
            # отложенного damage-события от сервера.
            def _clear_ult_no_fall(u_str=uid(player)):
                try:
                    _ult_no_fall.discard(u_str)
                except Exception: pass
            scheduler.runTaskLater(_clear_ult_no_fall, 60)

    scheduler.runTaskLater(crash, ULT_HANG_TICKS)
    # Safety-net: снимаем флаг no-fall через ULT_HANG_TICKS + 200 тиков (10 сек)
    # на случай, если impact_at не выполнился (игрок вылогинился, застрял в мире).
    def _safety_clear_no_fall(u_str=uid(player)):
        try:
            _ult_no_fall.discard(u_str)
        except Exception: pass
    scheduler.runTaskLater(_safety_clear_no_fall, ULT_HANG_TICKS + 200)

    set_cd(player, "ult", CD_ULT)
    player.sendMessage(u"§2§lПрыжок в небо... §7через 2 секунды удар.")


# =============================================================================
#  PASSIVES: скорость в воде, падение, огонь, высыхание, HP-триггер, кваканье
# =============================================================================

def _in_water(player):
    try:
        return player.isInWater() or player.getLocation().getBlock().getType() == Material.WATER
    except Exception:
        return False


def _passives_tick():
    try:
        for pl in Bukkit.getOnlinePlayers():
            if not is_griblet(pl): continue
            u = uid(pl)
            in_water = _in_water(pl)

            # +75% скорости плавания — через Dolphins Grace.
            # Плюс подводное дыхание (пассив Гриббита — жабий, не тонет).
            if in_water:
                if E_DOLPHIN is not None:
                    add_effect(pl, E_DOLPHIN, 40, 0, ambient=True, particles=False)
                if E_WATER_BREATH is not None:
                    add_effect(pl, E_WATER_BREATH, 60, 0, ambient=True, particles=False)
                # Сбрасываем таймер высыхания.
                dry_ticks.pop(u, None)
            else:
                dry_ticks[u] = dry_ticks.get(u, 0) + 20
                if dry_ticks[u] >= DRY_TIME_TICKS:
                    add_effect(pl, E_SLOWNESS, 40, 1)
                    last_msg = last_water_msg.get(u, 0)
                    if now_tick() - last_msg > 20 * 20:
                        pl.sendActionBar(u"§8§oКожа Гриббита пересыхает...")
                        last_water_msg[u] = now_tick()

            # Триггер Тира III на низком HP.
            if current_staff_tier(pl) >= 3 and pl.getHealth() <= T3_LOW_HP:
                last = low_hp_last.get(u, 0)
                if now_tick() - last >= T3_LOW_HP_COOLDOWN:
                    add_effect(pl, E_RESIST, T3_RESIST_DUR, 1)
                    add_effect(pl, E_REGEN,  T3_REGEN_DUR,  0)
                    low_hp_last[u] = now_tick()
                    pl.sendMessage(u"§2§l✦ §rРегенерация болота! §7Сопр. II на 8с + Регенерация I на 2с.")
                    pl.getWorld().playSound(pl.getLocation(), Sound.ENTITY_FROG_HURT, 0.8, 0.9)

    except Exception as ex:
        Bukkit.getLogger().warning("[griblet] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


# =============================================================================
#  EVENT HANDLERS
# =============================================================================

def on_interact(event):
    if event.getHand() != EquipmentSlot.HAND: return
    p = event.getPlayer()
    # Оглушение блокирует использование предметов.
    if _is_stunned(uid(p)):
        event.setCancelled(True)
        return
    if not is_griblet(p): return
    item = event.getItem()
    if not is_staff(item): return
    if not can_wield(p, item):
        event.setCancelled(True)
        p.sendMessage(u"§cПосох отвергает тебя.")
        return


def _is_stunned(u):
    if u not in stunned: return False
    if now_tick() >= stunned[u]:
        stunned.pop(u, None)
        return False
    return True


def on_damage(event):
    ent = event.getEntity()
    if not isinstance(ent, Player): return
    if not is_griblet(ent): return

    cause = event.getCause()
    C = EntityDamageEvent.DamageCause

    # Ульт-полёт: FALL-урон отменяется полностью.
    if cause == C.FALL and uid(ent) in _ult_no_fall:
        event.setCancelled(True)
        try:
            ent.setFallDistance(0.0)
        except Exception: pass
        return

    # -60% урона от падения (пассивная способность Гриблета).
    if cause == C.FALL:
        event.setDamage(event.getDamage() * 0.4)
        return

    # +30% урона от огня и лавы.
    if cause in (C.FIRE, C.FIRE_TICK, C.LAVA, C.HOT_FLOOR):
        event.setDamage(event.getDamage() * 1.30)
        return


def on_damage_by(event):
    dmg = event.getDamager()
    ent = event.getEntity()

    # Гриббит бьёт: Тир II — каждый 7-й удар накладывает Слабость I на 1 сек.
    if isinstance(dmg, Player) and is_griblet(dmg):
        item = dmg.getInventory().getItemInMainHand()
        if is_staff(item):
            tier = get_staff_tier(item)
            if tier >= 2 and isinstance(ent, LivingEntity):
                u = uid(dmg)
                hit_counter[u] = hit_counter.get(u, 0) + 1
                if hit_counter[u] % 7 == 0:
                    add_effect(ent, E_WEAKNESS, 20, 0)
                    ent.getWorld().spawnParticle(
                        Particle.ITEM_SLIME, ent.getLocation().add(0, 1, 0),
                        10, 0.3, 0.5, 0.3, 0.02
                    )

    # Гриббит получает удар — если оглушён, не должен успевать защищаться
    # (Slowness 249 уже блокирует движение).


def on_fire_tick(event):
    """Огонь длится на 30% дольше — при поджоге увеличиваем FireTicks."""
    # setFireTicks меняется через EntityCombustEvent; здесь простая эвристика:
    pass


def on_kill(event):
    """Прогресс убийств слизней."""
    victim = event.getEntity()
    if not isinstance(victim, Slime): return
    killer = victim.getKiller()
    if killer is None or not isinstance(killer, Player): return
    if not is_griblet(killer): return
    prog = _get_progress(killer)
    prog["slimes"] += 1
    if current_staff_tier(killer) < 2 and prog["slimes"] % 5 == 0:
        killer.sendActionBar(u"§7Слизней: §f" + str(prog["slimes"]) +
                             u"§7 / §f" + str(T2_SLIMES_KILLED))


def on_block_break(event):
    """Прогресс сбора грязи."""
    p = event.getPlayer()
    if not is_griblet(p): return
    b = event.getBlock()
    if b.getType() == Material.MUD:
        prog = _get_progress(p)
        prog["mud"] += 1
        if current_staff_tier(p) < 2 and prog["mud"] % 4 == 0:
            p.sendActionBar(u"§7Грязи: §f" + str(prog["mud"]) +
                            u"§7 / §f" + str(T2_MUD_BLOCKS))


def on_move(event):
    """Оглушение блокирует движение (yaw/pitch разрешены)."""
    p = event.getPlayer()
    if not _is_stunned(uid(p)):
        return
    f = event.getFrom()
    t = event.getTo()
    if t is not None:
        if (f.getX() != t.getX()) or (f.getY() != t.getY()) or (f.getZ() != t.getZ()):
            new_to = f.clone()
            new_to.setYaw(t.getYaw())
            new_to.setPitch(t.getPitch())
            event.setTo(new_to)


def on_drop(event):
    if is_staff(event.getItemDrop().getItemStack()):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cПосох нельзя выбросить.")


def on_inv_click(event):
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        it = event.getCurrentItem()
        cursor = event.getCursor()
        if is_staff(it) or is_staff(cursor):
            event.setCancelled(True)
            event.getWhoClicked().sendMessage(u"§cПосох нельзя убрать в контейнер.")


_need_respawn = set()

def on_death(event):
    """
    Soulbound (soulbound.py) сам обрабатывает предметы с PDC-меткой
    'griblet:*' и сохраняет их со ВСЕМИ данными (включая tier).
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
    if not is_griblet(player):
        return

    def _check_and_restore():
        try:
            if not player.isOnline():
                return
            # Проверяем есть ли предмет героя в инвентаре после отработки soulbound.
            if not staff_anywhere(player):
                give_staff(player, 1)
                player.sendMessage(u"§7[griblet] Комплект восстановлен на I тире (базовый).")
        except Exception:
            pass

    scheduler.runTaskLater(_check_and_restore, 40)



# Шумная лягушка — по PlayerJumpEvent (Paper).
_last_croak = {}

def on_jump(event):
    p = event.getPlayer()
    if not is_griblet(p): return
    now = now_tick()
    if now - _last_croak.get(uid(p), 0) < 5:
        return
    _last_croak[uid(p)] = now
    p.getWorld().playSound(p.getLocation(), Sound.ENTITY_FROG_AMBIENT, 1.2, 1.0)


# =============================================================================
#  COMMAND
# =============================================================================

def cmd_griblet(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько для игроков.")
        return True
    if not is_griblet(sender):
        sender.sendMessage(u"§cТолько Гриббит может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/griblet <прыжок|язык|ульт|улучшить|тир <n>>")
        return True

    sub = args[0].lower()

    if sub in (u"улучшить", u"upgrade"):
        try_upgrade(sender)
        return True

    if sub in (u"тир", u"tier"):
        if not _test_mode_on():
            sender.sendMessage(u"§cТестовый режим выключен — команда недоступна.")
            return True
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/griblet тир <1..3>")
            return True
        try:
            t = int(args[1])
        except ValueError:
            sender.sendMessage(u"§cТир — число.")
            return True
        if t < 1 or t > 3:
            sender.sendMessage(u"§cТиры: 1..3.")
            return True
        if not replace_staff(sender, t):
            give_staff(sender, t)
        else:
            sender.sendMessage(u"§aТир выставлен: §f" + [u"", u"I", u"II", u"III"][t])
        return True

    if not staff_anywhere(sender):
        sender.sendMessage(u"§cДля способностей нужен Посох в инвентаре.")
        return True

    if is_silenced_by_demiurg(sender):
        sender.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return True

    if   sub in (u"прыжок", u"скользящий", u"jump"): ability_jump(sender)
    elif sub in (u"язык", u"липкий", u"tongue"):     ability_tongue(sender)
    elif sub in (u"ульт", u"метеорит", u"ult"):      ability_ult(sender)
    else:
        sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_griblet, "griblet")

# PlayerJumpEvent есть только в Paper 1.19+, безопасно оборачиваем.
_JumpEventClass = None
try:
    from com.destroystokyo.paper.event.player import PlayerJumpEvent as _JumpEventClass
except ImportError:
    try:
        from io.papermc.paper.event.player import PlayerJumpEvent as _JumpEventClass
    except ImportError:
        _JumpEventClass = None

listener_mgr.registerListener(on_interact,    PlayerInteractEvent)
listener_mgr.registerListener(on_damage,      EntityDamageEvent)
listener_mgr.registerListener(on_damage_by,   EntityDamageByEntityEvent)
listener_mgr.registerListener(on_kill,        EntityDeathEvent)
listener_mgr.registerListener(on_move,        PlayerMoveEvent)
listener_mgr.registerListener(on_drop,        PlayerDropItemEvent)
listener_mgr.registerListener(on_inv_click,   InventoryClickEvent)
listener_mgr.registerListener(on_death,       PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,     PlayerRespawnEvent)

# Для сбора грязи.
from org.bukkit.event.block import BlockBreakEvent
listener_mgr.registerListener(on_block_break, BlockBreakEvent)

if _JumpEventClass is not None:
    listener_mgr.registerListener(on_jump, _JumpEventClass)
else:
    Bukkit.getLogger().info("[griblet] PlayerJumpEvent unavailable — 'quaking' passive skipped.")

_passives_tick()

# --- Регистрация набора в /test-диспетчере ---
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("griblet", (kit_entry, u"Гриббит (Посох болотного стража [тир 1..3])"))

# --- Публикация владельцев ---
_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("griblet", list(GRIBLET_NAMES))

# --- Публикация функции смены тира ---
def _griblet_set_tier(target_player, tier):
    if tier < 1 or tier > 3:
        return False
    if not replace_staff(target_player, tier):
        give_staff(target_player, tier)
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("griblet", _griblet_set_tier)


# --- Публикация в каталог Зеркала Души Арчера ---
def _griblet_mirror_staff(owner_uuid):
    it = ItemStack(Material.IRON_SWORD, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§2Посох болотного стража")
    if ENC_SHARPNESS is not None:
        m.addEnchant(ENC_SHARPNESS, 2, True)
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

_mirror_publish("griblet:staff", u"посох болотного стража", u"§2Посох болотного стража", _griblet_mirror_staff)


# quest_tracker: публикуем stat-функцию.
# В спеке quest_tracker ключи: slimes, mud_placed. Внутри griblet — slimes, mud.
def _griblet_stat(player, key):	
    try:
        u = uid(player)
        st = progress.get(u, {"slimes": 0, "mud": 0})
        if key == "slimes":     return int(st.get("slimes", 0))
        if key == "mud_placed": return int(st.get("mud", 0))
    except Exception: pass
    return 0

try:
    System.getProperties().put("quest_tracker.stat.griblet", _griblet_stat)
except Exception: pass


Bukkit.getLogger().info("[griblet] Griblet loaded. Commands: /test griblet, /griblet")

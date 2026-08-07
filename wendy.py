# -*- coding: utf-8 -*-
"""
==============================================================================
  ВЕНДИ МАРВЕЛЛ / Wendy Marvell — Небесная Убийца Драконов
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  Владельцы: Minykii (+ blueredtronce для теста)

  Предмет: Заряд ветра (WIND_CHARGE), бесконечный, но с общим КД 3 сек на любое
  применение способности через "трату" заряда. Механически — глобальный CD 3с.

  Магия Небесного Дракона (заклинания в сторону цели впереди):
    - /wendy троя     — Регенерация II на цель (15с)
    - /wendy вернир   — Скорость I           (15с)
    - /wendy армс     — Сила I               (15с)
    - /wendy армор    — Сопротивление I      (15с)
    - /wendy коготь   — отбрасывает всех впереди на ~20 блоков
  (у всей магии общий КД 30 сек)

  Ре-райс:
    - Пассив: иммунитет к урону от удушья (SUFFOCATION).
    - При активации на 5 сек: Glowing всем в r=15, Прыгучесть II, купол
      отражения снарядов, свист.
    - CD 15 сек.

  Ультимейт «Драконья Ярость» (45 сек total):
    - Первые 15 сек: снимает негатив + Regen + Speed II + Resist I + NightVision
      + FireResist + Flight + Sonic Boom (4 заряда, sculkheart механика).
    - Оставшиеся 30 сек: сохраняет "форму" (визуал, подброс при ударе).
    - После окончания: Hunger II + MiningFatigue + Nausea на 15 сек.
    - CD 3 минуты.
    - Во время ульта — блокируется всё, кроме Sonic Boom и обычных атак.
      Внешние баффы кэнселятся (EntityPotionEffectEvent).

  Слабости:
    - -1 сердце max HP (18 HP).
    - Мясо восстанавливает только 0.5 голода (через FoodLevelChangeEvent).
    - +30% урона от POISON эффекта.
    - Любая атака в ульте подбрасывает цель примерно на 15 блоков.
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, Long as JLong, IllegalArgumentException
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, Location
)
from org.bukkit.entity import Player, LivingEntity, Projectile

from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerItemHeldEvent, PlayerJoinEvent,
    PlayerRespawnEvent, PlayerDropItemEvent, PlayerItemConsumeEvent
)
from org.bukkit.event.block import Action
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent,
    EntityPotionEffectEvent, FoodLevelChangeEvent, ProjectileHitEvent,
    EntityRegainHealthEvent
)
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.persistence import PersistentDataType
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
from org.bukkit.util import Vector
from org.bukkit.potion import PotionEffect

# DamageSource (Paper 1.20.5+)
_HAS_DAMAGE_API = True
try:
    from org.bukkit.damage import DamageSource, DamageType
except Exception:
    _HAS_DAMAGE_API = False


# ============================================================================
# CONFIG
# ============================================================================

WENDY_NAMES = set([u"Minykii", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

# PDC keys
KEY_WIND_CHARGE = NamespacedKey.fromString("wendy:wind_charge")
KEY_OWNER       = NamespacedKey.fromString("wendy:owner")
KEY_REFLECT_TICK= NamespacedKey.fromString("wendy:reflect_tick")

# Cooldowns (ticks)
CD_WIND_CHARGE = 3 * 20         # 3 сек — общий "перезарядка заряда"
CD_MAGIC       = 30 * 20        # Магия Небесного Дракона (общий на 5 заклинаний)
CD_RERAISE     = 15 * 20
CD_ULT         = 180 * 20

# Магия
MAGIC_DURATION      = 15 * 20
MAGIC_CLAW_KB       = 20         # блоков отбрасывания
MAGIC_CLAW_RADIUS   = 6.0
MAGIC_TARGET_RANGE  = 30.0

# Ре-райс
RERAISE_DURATION  = 5 * 20
RERAISE_RADIUS    = 15.0
RERAISE_JUMP_AMP  = 1              # Прыгучесть II

# Ульт
ULT_TOTAL_DURATION      = 45 * 20
ULT_BUFF_DURATION       = 15 * 20
ULT_POST_DEBUFF         = 15 * 20
ULT_SONIC_MAX_CHARGES   = 4
ULT_SONIC_DAMAGE        = 4.0      # 4 HP чистого (как у Вардена)
ULT_LAUNCH_Y            = 1.8      # примерно 15 блоков подъёма

# Слабости
MAX_HP_REDUCTION = -2.0            # -1 сердце
POISON_DMG_MULT  = 1.30            # +30% урона
# Мясо восстанавливает ровно половину деления голода (1 food point).
MEAT_FOOD_GAIN   = 1
SWEET_FOOD_GAIN  = 8               # как жареная говядина

# Любое мясо и рыба усваиваются плохо, независимо от приготовления.
MEAT_MATERIALS = set([
    Material.BEEF, Material.COOKED_BEEF,
    Material.PORKCHOP, Material.COOKED_PORKCHOP,
    Material.MUTTON, Material.COOKED_MUTTON,
    Material.CHICKEN, Material.COOKED_CHICKEN,
    Material.RABBIT, Material.COOKED_RABBIT,
    Material.COD, Material.COOKED_COD,
    Material.SALMON, Material.COOKED_SALMON,
    Material.TROPICAL_FISH, Material.PUFFERFISH,
    Material.ROTTEN_FLESH,
])

SWEET_MATERIALS = set([
    Material.COOKIE, Material.APPLE, Material.GOLDEN_APPLE,
    Material.ENCHANTED_GOLDEN_APPLE, Material.MELON_SLICE,
    Material.SWEET_BERRIES, Material.GLOW_BERRIES,
    Material.CHORUS_FRUIT, Material.PUMPKIN_PIE,
    Material.HONEY_BOTTLE,
])

# Attribute mod UUIDs
MAX_HP_MOD_UUID = JUUID.fromString("ccdd1111-2222-3333-4444-555566667777")


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

def is_wendy(player):
    if not isinstance(player, Player): return False
    n = player.getName().lower()
    matched = False
    for real in WENDY_NAMES:
        if real.lower() == n:
            matched = True
            break
    if not matched: return False
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

E_REGEN       = _effect("regeneration")
E_SPEED       = _effect("speed")
E_STRENGTH    = _effect("strength")
E_RESISTANCE  = _effect("resistance")
E_JUMP        = _effect("jump_boost")
E_GLOWING     = _effect("glowing")
E_NIGHT_VIS   = _effect("night_vision")
E_FIRE_RES    = _effect("fire_resistance")
E_INSTANT_HEAL= _effect("instant_health")
E_POISON      = _effect("poison")
E_HUNGER      = _effect("hunger")
E_MINING_FTG  = _effect("mining_fatigue")
E_NAUSEA      = _effect("nausea")
E_SLOWNESS    = _effect("slowness")
E_WEAKNESS    = _effect("weakness")
E_WITHER      = _effect("wither")
E_BLINDNESS   = _effect("blindness")
E_DARKNESS    = _effect("darkness")

# Что считать негативными эффектами (для очистки в ульте).
NEGATIVE_EFFECTS = set([
    _to_unicode("slowness"), _to_unicode("mining_fatigue"),
    _to_unicode("weakness"), _to_unicode("poison"),
    _to_unicode("wither"),   _to_unicode("blindness"),
    _to_unicode("darkness"), _to_unicode("hunger"),
    _to_unicode("nausea"),   _to_unicode("bad_omen"),
    _to_unicode("levitation"), _to_unicode("unluck"),
    _to_unicode("glowing"),
])

def add_effect(entity, ptype, ticks, amp, ambient=True, particles=False):
    if ptype is None or entity is None: return
    try:
        entity.addPotionEffect(PotionEffect(ptype, ticks, amp, ambient, particles, True))
    except Exception:
        pass


# Cooldowns
cooldowns = {}   # uid -> {name: end_tick}

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

def _touch_wind_charge(player, visual_cd=True):
    """Общий 3-сек КД любого использования Заряда ветра."""
    if not check_cd(player, "wind_charge", u"«Заряд ветра»"): return False
    set_cd(player, "wind_charge", CD_WIND_CHARGE)
    if visual_cd and not _is_free_cd(player):
        try: player.setCooldown(Material.WIND_CHARGE, CD_WIND_CHARGE)
        except Exception: pass
    return True


# ============================================================================
# STATE
# ============================================================================

# uid -> AttributeModifier (max HP)
_max_hp_mod = {}

# ЗБТ-состояния (uid -> end_tick или структура)
ult_active     = {}   # uid -> {"total_end", "buff_end", "sonic_charges"}
reraise_active = {}   # uid -> end_tick


# ============================================================================
# ITEM: Заряд ветра (бесконечный)
# ============================================================================

def is_wind_charge(item):
    if item is None: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_WIND_CHARGE, PersistentDataType.BYTE)

def create_wind_charge(owner_uuid):
    it = ItemStack(Material.WIND_CHARGE, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§b§lЗаряд ветра")
    lore = [
        u"§7Магия ветра Небесной Убийцы Драконов.",
        u"§8Бесконечный, но с §fКД 3 сек §8между применениями.",
        u"",
        u"§8Магия Небесного Дракона:",
        u"§8  §f/wendy троя §7— Регенерация II цели",
        u"§8  §f/wendy вернир §7— Скорость I",
        u"§8  §f/wendy армс §7— Сила I",
        u"§8  §f/wendy армор §7— Сопротивление I",
        u"§8  §f/wendy коготь §7— поток воздуха ~20 бл",
        u"§8Ре-райс: §f/wendy рерайс",
        u"§8Ульт: §f/wendy ульт",
        u"",
        u"§8Только Венди может использовать этот предмет.",
    ]
    m.setLore(java_list(lore))
    m.setUnbreakable(True)
    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_WIND_CHARGE, PersistentDataType.BYTE, JByte(1))
    pdc.set(KEY_OWNER,       PersistentDataType.STRING, owner_uuid)
    it.setItemMeta(m)
    return it

def give_kit(player):
    inv = player.getInventory()
    # Проверяем, что предмета ещё нет.
    for it in inv.getContents():
        if is_wind_charge(it):
            return
    inv.addItem(create_wind_charge(uid(player)))


# ============================================================================
# PASSIVE: max HP -1 сердце
# ============================================================================

def _try_add(attr, mod):
    if attr is None or mod is None: return False
    try:
        attr.addModifier(mod)
        return True
    except IllegalArgumentException:
        return False
    except Exception as ex:
        Bukkit.getLogger().warning("[wendy] addModifier: " + str(ex))
        return False

def _try_remove(attr, mod):
    if attr is None or mod is None: return
    try:
        attr.removeModifier(mod)
    except Exception:
        pass

def _ensure_max_hp_reduction(player):
    u = uid(player)
    if u in _max_hp_mod: return
    try:
        attr = player.getAttribute(ATTR_MAX_HEALTH)
        if attr is None: return
        mod = AttributeModifier(
            MAX_HP_MOD_UUID, "wendy_max_hp", MAX_HP_REDUCTION,
            AttributeModifier.Operation.ADD_NUMBER
        )
        _try_add(attr, mod)
        _max_hp_mod[u] = mod
        max_hp = attr.getValue()
        if player.getHealth() > max_hp:
            try: player.setHealth(max_hp)
            except Exception: pass
    except Exception as ex:
        Bukkit.getLogger().warning("[wendy] max_hp apply: " + str(ex))

def _remove_max_hp_reduction(player):
    u = uid(player)
    mod = _max_hp_mod.pop(u, None)
    if mod is None: return
    try:
        attr = player.getAttribute(ATTR_MAX_HEALTH)
        _try_remove(attr, mod)
    except Exception:
        pass


# ============================================================================
# ABILITIES
# ============================================================================

def _check_common(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return False
    # Заряд ветра должен быть где-то в инвентаре.
    inv = player.getInventory()
    has = False
    for it in inv.getContents():
        if is_wind_charge(it):
            has = True
            break
    if not has:
        player.sendMessage(u"§cДля способностей нужен §fЗаряд ветра §cв инвентаре.")
        return False
    return True


def _find_forward_target(player, max_range=MAGIC_TARGET_RANGE):
    """Возвращает LivingEntity, куда смотрит игрок (или None)."""
    try:
        result = player.rayTraceEntities(int(max_range))
        if result is not None:
            e = result.getHitEntity()
            if isinstance(e, LivingEntity) and not e.equals(player):
                return e
    except Exception:
        pass
    return None


def _cast_buff_on_target(player, spell_name, ptype, amp, effect_display):
    """Общий шаблон для Троя/Вернир/Армс/Армор — накладывает эффект на цель впереди."""
    if not _check_common(player): return
    if not check_cd(player, "magic", u"«Магия Небесного Дракона»"): return
    if not _touch_wind_charge(player): return

    target = _find_forward_target(player)
    if target is None:
        player.sendMessage(u"§cНекому дать §f" + spell_name + u"§c. Наводись на существо.")
        # НЕ ставим CD магии — заклинание не сработало (только заряд-CD).
        return

    add_effect(target, ptype, MAGIC_DURATION, amp)
    try:
        world = player.getWorld()
        world.spawnParticle(Particle.CLOUD, target.getLocation().add(0, 1, 0),
                            25, 0.4, 0.6, 0.4, 0.02)
        world.spawnParticle(Particle.END_ROD, target.getLocation().add(0, 1, 0),
                            10, 0.3, 0.5, 0.3, 0.02)
        world.playSound(target.getLocation(), Sound.ENTITY_ALLAY_AMBIENT_WITH_ITEM, 1.0, 1.5)
    except Exception:
        pass

    tgt_name = target.getName() if hasattr(target, "getName") else target.getType().name()
    player.sendMessage(u"§b§l✦ " + spell_name + u" §r§7— " + effect_display + u" на §f" + tgt_name)
    if isinstance(target, Player):
        try:
            target.sendMessage(u"§bВенди усилила тебя: §f" + effect_display)
        except Exception: pass

    set_cd(player, "magic", CD_MAGIC)


def ability_troia(player):
    _cast_buff_on_target(player, u"Троя",    E_REGEN,      1, u"Регенерация II 15с")

def ability_vernier(player):
    _cast_buff_on_target(player, u"Вернир",  E_SPEED,      0, u"Скорость I 15с")

def ability_arms(player):
    _cast_buff_on_target(player, u"Армс",    E_STRENGTH,   0, u"Сила I 15с")

def ability_armor(player):
    _cast_buff_on_target(player, u"Армор",   E_RESISTANCE, 0, u"Сопротивление I 15с")


def ability_claw(player):
    """Коготь небесного дракона — отбрасывает всех впереди на ~20 блоков."""
    if not _check_common(player): return
    if not check_cd(player, "magic", u"«Магия Небесного Дракона»"): return
    if not _touch_wind_charge(player): return

    world = player.getWorld()
    origin = player.getEyeLocation()
    dir_v  = origin.getDirection().normalize()

    hit_count = 0
    # Идём вперёд с шагом 2 блока до 20 бл, ищем цели в конусе.
    checked = set()
    for step in range(1, 21, 2):
        point = origin.clone().add(dir_v.clone().multiply(float(step)))
        try:
            world.spawnParticle(Particle.CLOUD, point, 12, 0.6, 0.4, 0.6, 0.05)
            world.spawnParticle(Particle.SWEEP_ATTACK, point, 1, 0.0, 0.0, 0.0, 0.0)
        except Exception:
            pass
        for e in world.getNearbyEntities(point, MAGIC_CLAW_RADIUS, 3.0, MAGIC_CLAW_RADIUS):
            if not isinstance(e, LivingEntity): continue
            if e.equals(player): continue
            eu = uid(e)
            if eu in checked: continue
            checked.add(eu)
            # Отбрасывание: 20 блоков вперёд по направлению.
            kb = dir_v.clone().multiply(2.8)
            kb.setY(0.7)
            try:
                e.setVelocity(kb)
                if isinstance(e, Player):
                    e.setFallDistance(0.0)
            except Exception:
                pass
            hit_count += 1

    try:
        world.playSound(player.getLocation(), Sound.ENTITY_BREEZE_WIND_BURST, 1.4, 1.0)
    except Exception:
        pass

    player.sendMessage(u"§b§l✦ Коготь Небесного Дракона! §7— задето §f" + str(hit_count))
    set_cd(player, "magic", CD_MAGIC)


# --- Ре-райс -----------------------------------------------------------------

def ability_reraise(player):
    if not _check_common(player): return
    if not check_cd(player, "reraise", u"«Ре-райс»"): return
    if not _touch_wind_charge(player): return

    end = now_tick() + RERAISE_DURATION
    reraise_active[uid(player)] = end

    world = player.getWorld()
    center = player.getLocation()

    # Прыгучесть игроку.
    add_effect(player, E_JUMP, RERAISE_DURATION, RERAISE_JUMP_AMP)

    # Glowing всем в r=15 (кроме себя).
    for e in world.getNearbyEntities(center, RERAISE_RADIUS, RERAISE_RADIUS, RERAISE_RADIUS):
        if not isinstance(e, LivingEntity): continue
        if e.equals(player): continue
        add_effect(e, E_GLOWING, RERAISE_DURATION, 0)

    try:
        world.playSound(center, Sound.ENTITY_BREEZE_SHOOT, 1.2, 1.4)
        world.spawnParticle(Particle.CLOUD, center.clone().add(0, 1, 0),
                            80, 2.0, 1.0, 2.0, 0.05)
    except Exception:
        pass

    # Тик: рисуем купол вокруг.
    def dome_tick(state=[0]):
        if not player.isValid(): return
        if state[0] >= RERAISE_DURATION:
            reraise_active.pop(uid(player), None)
            return
        try:
            loc = player.getLocation()
            # Подсвечиваем не только стартовые цели, но и всех, кто войдёт
            # в область в течение пяти секунд действия Ре-райса.
            for entity in world.getNearbyEntities(loc, RERAISE_RADIUS,
                                                   RERAISE_RADIUS, RERAISE_RADIUS):
                if isinstance(entity, LivingEntity) and not entity.equals(player):
                    add_effect(entity, E_GLOWING, 12, 0)
            import math
            r = 2.5
            # Кольцо снизу вверх.
            for a in range(0, 360, 30):
                rad = a * math.pi / 180.0
                px = loc.getX() + r * math.cos(rad)
                pz = loc.getZ() + r * math.sin(rad)
                py = loc.getY() + 1.0
                try:
                    world.spawnParticle(Particle.CLOUD,
                                        loc.getWorld().getBlockAt(int(px), int(py), int(pz)).getLocation().add(0.5, 0.5, 0.5),
                                        1, 0.0, 0.0, 0.0, 0.0)
                except Exception:
                    pass
        except Exception:
            pass
        state[0] += 5
        scheduler.runTaskLater(dome_tick, 5)
    scheduler.runTaskLater(dome_tick, 2)

    player.sendMessage(u"§b§l✦ Ре-райс! §r§7— 5 сек. Купол отражает снаряды.")
    set_cd(player, "reraise", CD_RERAISE)


# --- Ультимейт: Драконья Ярость ---------------------------------------------

def ability_ult(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
    if not check_cd(player, "ult", u"«Драконья Ярость»"): return
    if not _check_common(player): return

    u = uid(player)
    total_end = now_tick() + ULT_TOTAL_DURATION
    buff_end  = now_tick() + ULT_BUFF_DURATION
    ult_active[u] = {
        "total_end": total_end,
        "buff_end":  buff_end,
        "sonic_charges": ULT_SONIC_MAX_CHARGES,
    }

    # 1. Снимаем все негативные эффекты.
    for etype_name in list(NEGATIVE_EFFECTS):
        pt = _effect(etype_name.encode("ascii", "ignore") if isinstance(etype_name, unicode) else etype_name)
        if pt is not None and player.hasPotionEffect(pt):
            try: player.removePotionEffect(pt)
            except Exception: pass

    # 2. Мгновенное лечение (Instant Health).
    if E_INSTANT_HEAL:
        add_effect(player, E_INSTANT_HEAL, 20, 0)
    else:
        try:
            max_hp = player.getAttribute(ATTR_MAX_HEALTH).getValue()
            player.setHealth(max_hp)
        except Exception: pass

    # 3. Бафы на 15 сек.
    add_effect(player, E_SPEED,      ULT_BUFF_DURATION, 1)   # II
    add_effect(player, E_RESISTANCE, ULT_BUFF_DURATION, 0)
    add_effect(player, E_NIGHT_VIS,  ULT_BUFF_DURATION, 0)
    add_effect(player, E_FIRE_RES,   ULT_BUFF_DURATION, 0)

    # 4. Полёт на 15 сек.
    try:
        player.setAllowFlight(True)
        player.setFlying(True)
    except Exception: pass
    def _end_flight():
        try:
            if player.isValid() and not player.getGameMode().name() in ("CREATIVE", "SPECTATOR"):
                player.setFlying(False)
                player.setAllowFlight(False)
        except Exception: pass
    scheduler.runTaskLater(_end_flight, ULT_BUFF_DURATION)

    # 5. Ульт-конец: пост-дебафы через 45 сек.
    def _end_ult():
        cur = ult_active.get(u)
        if cur is None: return
        if now_tick() < cur["total_end"]: return   # переставили
        ult_active.pop(u, None)
        try:
            if not player.isValid(): return
            add_effect(player, E_HUNGER,     ULT_POST_DEBUFF, 1)
            if E_MINING_FTG:
                add_effect(player, E_MINING_FTG, ULT_POST_DEBUFF, 0)
            if E_NAUSEA:
                add_effect(player, E_NAUSEA,     ULT_POST_DEBUFF, 0)
            player.sendMessage(u"§7Драконья Ярость угасла. Тебе плохо...")
        except Exception:
            pass
    scheduler.runTaskLater(_end_ult, ULT_TOTAL_DURATION + 1)

    world = player.getWorld()
    try:
        world.playSound(player.getLocation(), Sound.ENTITY_ENDER_DRAGON_GROWL, 1.5, 1.4)
        world.spawnParticle(Particle.END_ROD, player.getLocation().add(0, 1, 0),
                            100, 1.0, 1.5, 1.0, 0.1)
        world.spawnParticle(Particle.CLOUD, player.getLocation().add(0, 1, 0),
                            80, 1.5, 1.5, 1.5, 0.05)
    except Exception: pass

    player.sendMessage(u"§b§l✦ ДРАКОНЬЯ ЯРОСТЬ! §r§745 сек (первые 15 — бафы + полёт).")
    player.sendMessage(u"§7  Sonic Boom: §f/wendy сонник §7(до 4 раз)")
    set_cd(player, "ult", CD_ULT)


def _is_ult_active(player):
    st = ult_active.get(uid(player))
    if st is None: return False
    if now_tick() >= st["total_end"]:
        return False
    return True

def _is_ult_buff_active(player):
    st = ult_active.get(uid(player))
    if st is None: return False
    return now_tick() < st["buff_end"]


# --- Sonic Boom из ульта -----------------------------------------------------

def ability_sonic(player):
    if not _is_ult_active(player):
        player.sendMessage(u"§cЗвуковой удар доступен только во время §fДраконьей Ярости§c.")
        return
    st = ult_active[uid(player)]
    if st["sonic_charges"] <= 0:
        player.sendMessage(u"§cЗвуковой удар: зарядов больше нет.")
        return
    if not _touch_wind_charge(player): return

    world = player.getWorld()
    origin = player.getEyeLocation()
    dir_v = origin.getDirection().normalize()

    # Луч 15 блоков, ловим первую цель.
    target = None
    for step in range(1, 16):
        point = origin.clone().add(dir_v.clone().multiply(float(step)))
        try:
            world.spawnParticle(Particle.SONIC_BOOM, point, 1, 0.0, 0.0, 0.0, 0.0)
        except Exception:
            try:
                world.spawnParticle(Particle.EXPLOSION, point, 1, 0.0, 0.0, 0.0, 0.0)
            except Exception: pass
        for e in world.getNearbyEntities(point, 1.5, 1.5, 1.5):
            if not isinstance(e, LivingEntity): continue
            if e.equals(player): continue
            target = e
            break
        if target is not None: break

    if target is None:
        player.sendMessage(u"§7Звуковой удар прошёл в пустоту.")
        st["sonic_charges"] -= 1
        return

    # Чистый урон MAGIC.
    try:
        if _HAS_DAMAGE_API:
            src = (DamageSource.builder(DamageType.MAGIC)
                   .withDirectEntity(player)
                   .withCausingEntity(player)
                   .build())
            target.damage(ULT_SONIC_DAMAGE, src)
        else:
            target.damage(ULT_SONIC_DAMAGE, player)
    except Exception:
        try: target.damage(ULT_SONIC_DAMAGE, player)
        except Exception: pass

    # Подброс.
    try:
        v = Vector(0.0, ULT_LAUNCH_Y, 0.0)
        target.setVelocity(v)
        if isinstance(target, Player):
            target.setFallDistance(0.0)
    except Exception: pass

    try:
        world.playSound(target.getLocation(), Sound.ENTITY_WARDEN_SONIC_BOOM, 1.4, 1.0)
    except Exception: pass

    st["sonic_charges"] -= 1
    player.sendMessage(u"§b§l✦ Звуковой удар! §7осталось §f" + str(st["sonic_charges"]))


# ============================================================================
# EVENT HANDLERS
# ============================================================================

def on_damage(event):
    ent = event.getEntity()
    if not isinstance(ent, Player) or not is_wendy(ent):
        return
    cause = event.getCause()

    # Пассив: иммунитет к удушью.
    if cause == EntityDamageEvent.DamageCause.SUFFOCATION:
        event.setCancelled(True)
        return

    # +30% урона от POISON.
    if cause == EntityDamageEvent.DamageCause.POISON:
        try:
            DM = EntityDamageEvent.DamageModifier
            base = event.getDamage(DM.BASE)
            event.setDamage(DM.BASE, base * POISON_DMG_MULT)
        except Exception:
            event.setDamage(event.getDamage() * POISON_DMG_MULT)


def on_damage_by(event):
    victim = event.getEntity()
    dmg = event.getDamager()

    # Купол должен отменять урон до попадания, а не пытаться исправить его
    # постфактум через ProjectileHitEvent.
    if isinstance(victim, Player) and is_wendy(victim) and isinstance(dmg, Projectile):
        end = reraise_active.get(uid(victim), 0)
        if now_tick() < end:
            event.setCancelled(True)
            _reflect_projectile(dmg, victim)
            return

    attacker = dmg if isinstance(dmg, Player) else None
    if attacker is None and isinstance(dmg, Projectile):
        try:
            shooter = dmg.getShooter()
            if isinstance(shooter, Player): attacker = shooter
        except Exception: pass
    if attacker is None or not is_wendy(attacker) or not _is_ult_active(attacker):
        return
    if not isinstance(victim, LivingEntity) or victim.equals(attacker):
        return

    # В течение всех 45 секунд формы каждая прямая или стрелковая атака
    # Венди подбрасывает цель примерно на 15 блоков.
    try:
        velocity = victim.getVelocity()
        velocity.setY(max(velocity.getY(), ULT_LAUNCH_Y))
        victim.setVelocity(velocity)
        victim.getWorld().spawnParticle(Particle.CLOUD,
            victim.getLocation(), 24, 0.45, 0.2, 0.45, 0.04)
    except Exception: pass


def on_potion_effect(event):
    """Блокируем внешние положительные эффекты во время ульт-баффа."""
    try:
        ent = event.getEntity()
        if not isinstance(ent, Player) or not is_wendy(ent):
            return
        if not _is_ult_buff_active(ent):
            return
        # Разрешаем только "своё": наши бафы даются через add_effect после
        # активации ульта — они уходят в стек ДО того, как _is_ult_buff_active
        # становится True? Нет, порядок: сначала ставим buff_end, потом
        # add_effect. Значит наши бафы тоже попадут в этот хендлер.
        #
        # Решение: пропускаем эффект, если Cause = PLUGIN. При кэсте зелий /
        # маяков / beacon cause будет POTION_DRINK, POTION_SPLASH, BEACON и т.д.
        cause = event.getCause()
        if cause is None: return
        cname = cause.name()
        if cname == "PLUGIN":
            return
        # Проверяем, положительный ли эффект. Отфильтруем негативные.
        new_effect = event.getNewEffect()
        if new_effect is None: return
        etype_name = None
        try:
            etype_name = _to_unicode(new_effect.getType().getKey().getKey())
        except Exception:
            try: etype_name = _to_unicode(new_effect.getType().getName())
            except Exception: return
        # Негативные пропускаем (пусть Венди пьёт яд).
        if etype_name in NEGATIVE_EFFECTS:
            return
        # Блокируем.
        event.setCancelled(True)
    except Exception:
        pass


def on_food_change(event):
    ent = event.getEntity()
    if not isinstance(ent, Player) or not is_wendy(ent):
        return
    try:
        food_kind = _pending_food.pop(uid(ent), None)
        if food_kind is None: return
        old_lvl = ent.getFoodLevel()
        new_lvl = event.getFoodLevel()
        gain = new_lvl - old_lvl
        if gain <= 0: return
        if food_kind == "meat":
            event.setFoodLevel(min(20, old_lvl + MEAT_FOOD_GAIN))
        elif food_kind == "sweet":
            event.setFoodLevel(min(20, old_lvl + SWEET_FOOD_GAIN))
    except Exception:
        pass


# uid -> "meat" | "sweet": тип последней съеденной пищи.
_pending_food = {}

def on_consume(event):
    p = event.getPlayer()
    if not is_wendy(p): return
    it = event.getItem()
    if it is None: return
    if it.getType() in MEAT_MATERIALS:
        _pending_food[uid(p)] = "meat"
    elif it.getType() in SWEET_MATERIALS:
        _pending_food[uid(p)] = "sweet"


def on_projectile_hit(event):
    """Ре-райс: отражаем снаряды, попавшие в Венди или в её купол."""
    try:
        proj = event.getEntity()
        hit_ent = event.getHitEntity()
        # Прямое попадание в Венди.
        if isinstance(hit_ent, Player) and is_wendy(hit_ent):
            if uid(hit_ent) in reraise_active and now_tick() < reraise_active[uid(hit_ent)]:
                _reflect_projectile(proj, hit_ent)
                return
        # Попадание в блок рядом с Венди в куполе (r < 2.5) — тоже отражаем.
        # Тут дороже; проверим ближайших игроков-Венди.
        loc = proj.getLocation()
        for pl in Bukkit.getOnlinePlayers():
            if not is_wendy(pl): continue
            if uid(pl) not in reraise_active: continue
            if now_tick() >= reraise_active[uid(pl)]: continue
            if pl.getLocation().distanceSquared(loc) <= 2.5 * 2.5:
                _reflect_projectile(proj, pl)
                return
    except Exception:
        pass


def _reflect_projectile(proj, wendy):
    try:
        pdc = proj.getPersistentDataContainer()
        last_tick = pdc.get(KEY_REFLECT_TICK, PersistentDataType.LONG)
        if last_tick is not None and now_tick() - long(last_tick) <= 2:
            return
        pdc.set(KEY_REFLECT_TICK, PersistentDataType.LONG, JLong(now_tick()))
        v = proj.getVelocity()
        # Инвертируем + чуть увеличиваем.
        v = v.multiply(-1.1)
        # Сдвинем снаряд наружу купола.
        loc = proj.getLocation().clone()
        dir_out = loc.toVector().subtract(wendy.getLocation().toVector())
        if dir_out.lengthSquared() > 0.01:
            dir_out = dir_out.normalize().multiply(0.5)
            loc.add(dir_out)
        proj.teleport(loc)
        proj.setVelocity(v)
        # Обнуляем shooter, чтобы отражённый снаряд не бил Венди же.
        try:
            proj.setShooter(wendy)
        except Exception:
            pass
        wendy.getWorld().spawnParticle(Particle.CLOUD, loc, 15, 0.3, 0.3, 0.3, 0.05)
        wendy.getWorld().playSound(loc, Sound.ITEM_SHIELD_BLOCK, 1.0, 1.6)
    except Exception:
        pass


def on_interact(event):
    """Даёт бросить ванильный заряд и восстанавливает особый предмет после использования."""
    try:
        p = event.getPlayer()
        if not is_wendy(p):
            return
        action = event.getAction()

        # Торт тоже считается сладкой пищей, хотя съедается кликом по блоку,
        # а не через PlayerItemConsumeEvent.
        if action == Action.RIGHT_CLICK_BLOCK:
            clicked = event.getClickedBlock()
            if clicked is not None and clicked.getType() == Material.CAKE:
                _pending_food[uid(p)] = "sweet"

        if action not in (Action.RIGHT_CLICK_AIR, Action.RIGHT_CLICK_BLOCK):
            return
        it = event.getItem()
        if not is_wind_charge(it):
            return

        # На КД отменяем бросок. При готовом заряде событие НЕ отменяется —
        # Minecraft создаёт настоящий WIND_CHARGE projectile.
        # Визуальный Bukkit-cooldown ставим на следующий тик: если поставить
        # его внутри события, Leaf может отменить ещё не созданный снаряд.
        if not _touch_wind_charge(p, False):
            event.setCancelled(True)
            return

        snapshot = it.clone()
        snapshot.setAmount(1)
        hand = event.getHand()
        held_slot = p.getInventory().getHeldItemSlot()

        def restore_charge():
            try:
                if not p.isOnline(): return
                if not _is_free_cd(p):
                    try: p.setCooldown(Material.WIND_CHARGE, CD_WIND_CHARGE)
                    except Exception: pass
                inv = p.getInventory()

                # В creative или при отмене другим плагином предмет мог не
                # списаться. В таком случае только нормализуем количество.
                for existing in inv.getContents():
                    if is_wind_charge(existing):
                        existing.setAmount(1)
                        return

                if hand == EquipmentSlot.OFF_HAND:
                    current = inv.getItemInOffHand()
                    if current is None or current.getType() == Material.AIR:
                        inv.setItemInOffHand(snapshot)
                        return
                else:
                    current = inv.getItem(held_slot)
                    if current is None or current.getType() == Material.AIR:
                        inv.setItem(held_slot, snapshot)
                        return

                leftovers = inv.addItem(snapshot)
                if not leftovers.isEmpty():
                    p.sendMessage(u"§cОсвободи место в инвентаре для Заряда ветра.")
            except Exception as ex:
                Bukkit.getLogger().warning("[wendy] restore wind charge: " + str(ex))

        scheduler.runTaskLater(restore_charge, 1)
    except Exception:
        pass


def on_drop(event):
    it = event.getItemDrop().getItemStack()
    if is_wind_charge(it):
        event.setCancelled(True)
        try:
            event.getPlayer().sendMessage(u"§cЗаряд ветра нельзя выбросить.")
        except Exception: pass


def on_join(event):
    p = event.getPlayer()
    if is_wendy(p):
        _ensure_max_hp_reduction(p)

def on_respawn(event):
    p = event.getPlayer()
    if is_wendy(p):
        def _later():
            try: _ensure_max_hp_reduction(p)
            except Exception: pass
        scheduler.runTaskLater(_later, 5)


# ============================================================================
# COMMAND
# ============================================================================

def _ability_from_alias(arg):
    a = _norm(arg)
    if a in (u"троя", u"troia", u"troya"):                    return "troia"
    if a in (u"вернир", u"vernier"):                          return "vernier"
    if a in (u"армс", u"arms"):                               return "arms"
    if a in (u"армор", u"armor"):                             return "armor"
    if a in (u"коготь", u"claw"):                             return "claw"
    if a in (u"рерайс", u"ре-райс", u"reraise", u"дыхание"):  return "reraise"
    if a in (u"ульт", u"ult", u"ultimate", u"ярость"):        return "ult"
    if a in (u"сонник", u"соник", u"sonic", u"соник-удар",
             u"звуковой", u"boom"):                           return "sonic"
    if a in (u"кит", u"kit", u"выдать"):                      return "kit"
    return None


def cmd_wendy(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cКоманда только для игроков.")
        return True
    if not is_wendy(sender):
        sender.sendMessage(u"§cТы не Венди Марвелл.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7/wendy <способность>")
        sender.sendMessage(u"  §f/wendy троя §7— Регенерация II цели")
        sender.sendMessage(u"  §f/wendy вернир §7— Скорость I")
        sender.sendMessage(u"  §f/wendy армс §7— Сила I")
        sender.sendMessage(u"  §f/wendy армор §7— Сопротивление I")
        sender.sendMessage(u"  §f/wendy коготь §7— поток воздуха")
        sender.sendMessage(u"  §f/wendy рерайс §7— Ре-райс (5с купол)")
        sender.sendMessage(u"  §f/wendy ульт §7— Драконья Ярость")
        sender.sendMessage(u"  §f/wendy сонник §7— Sonic Boom (в ульте)")
        sender.sendMessage(u"  §f/wendy кит §7— выдать Заряд ветра")
        return True

    ab = _ability_from_alias(args[0])

    if ab == "kit":
        give_kit(sender)
        _ensure_max_hp_reduction(sender)
        sender.sendMessage(u"§a✓ Заряд ветра выдан.")
        return True

    if ab == "troia":   ability_troia(sender);   return True
    if ab == "vernier": ability_vernier(sender); return True
    if ab == "arms":    ability_arms(sender);    return True
    if ab == "armor":   ability_armor(sender);   return True
    if ab == "claw":    ability_claw(sender);    return True
    if ab == "reraise": ability_reraise(sender); return True
    if ab == "ult":     ability_ult(sender);     return True
    if ab == "sonic":   ability_sonic(sender);   return True

    sender.sendMessage(u"§cНеизвестная способность.")
    return True


# ============================================================================
# TEST DISPATCHER KIT
# ============================================================================

def kit_entry(player, args):
    give_kit(player)
    _ensure_max_hp_reduction(player)
    player.sendMessage(u"§a✓ Комплект Венди выдан.")


def _reset_state(player):
    _remove_max_hp_reduction(player)
    u = uid(player)
    cooldowns.pop(u, None)
    ult_active.pop(u, None)
    reraise_active.pop(u, None)
    _pending_food.pop(u, None)


# ============================================================================
# REGISTRATION
# ============================================================================

cmd_mgr.registerCommand(cmd_wendy, "wendy")

listener_mgr.registerListener(on_damage,          EntityDamageEvent)
listener_mgr.registerListener(on_damage_by,       EntityDamageByEntityEvent)
listener_mgr.registerListener(on_potion_effect,   EntityPotionEffectEvent)
listener_mgr.registerListener(on_food_change,     FoodLevelChangeEvent)
listener_mgr.registerListener(on_consume,         PlayerItemConsumeEvent)
listener_mgr.registerListener(on_projectile_hit,  ProjectileHitEvent)
listener_mgr.registerListener(on_drop,            PlayerDropItemEvent)
listener_mgr.registerListener(on_interact,        PlayerInteractEvent)
listener_mgr.registerListener(on_join,            PlayerJoinEvent)
listener_mgr.registerListener(on_respawn,         PlayerRespawnEvent)

_props = System.getProperties()

_REGISTRY_KEY = "pyspigot.character_kits"
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("wendy", (kit_entry, u"Венди Марвелл (Заряд ветра + магия)"))

_OWNERS_KEY = "character_owners"
_owners = _props.get(_OWNERS_KEY)
if _owners is None:
    _owners = HashMap()
    _props.put(_OWNERS_KEY, _owners)
_owners.put("wendy", list(WENDY_NAMES))

_RESET_KEY = "character_reset_functions"
_reset_reg = _props.get(_RESET_KEY)
if _reset_reg is None:
    _reset_reg = HashMap()
    _props.put(_RESET_KEY, _reset_reg)
_reset_reg.put("wendy", _reset_state)

# Восстанавливаем пассив для уже онлайн-игроков (при hot-reload).
try:
    for _pl in Bukkit.getOnlinePlayers():
        if is_wendy(_pl):
            _ensure_max_hp_reduction(_pl)
except Exception:
    pass

Bukkit.getLogger().info("[wendy] Wendy Marvell loaded. Command: /wendy")

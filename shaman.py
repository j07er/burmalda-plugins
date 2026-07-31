# -*- coding: utf-8 -*-
"""
==============================================================================
  ТЁМНЫЙ ШАМАН (Cerberws333)
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test shaman                     — активирует роль (нет особого предмета)
  /shaman <способность>            — способности
      дождь | ясно | время | ульт
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, Location
)
from org.bukkit.entity import (
    Player, LivingEntity
)
from org.bukkit.event.player import (
    PlayerItemConsumeEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent
)
from org.bukkit.potion import PotionEffect


# =============================================================================
#  CONSTANTS
# =============================================================================

SHAMAN_NAMES    = set([u"cerberws333"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

# CDs (тики)
CD_RAIN  = 3 * 60 * 20
CD_CLEAR = 1 * 60 * 20
CD_TIME  = 15 * 60 * 20
CD_ULT   = 2 * 60 * 20

# Ульт
ULT_DURATION      = 20 * 20
ULT_BOX_R         = 7          # 15×15×15 = радиус 7 от центра
ULT_CLEAR_TICK    = 3 * 20     # раз в 3 сек — 1 сердце + поджиг
ULT_STORM_TICK    = 4 * 20     # раз в 4 сек — молния
ULT_DAMAGE        = 2.0        # 1 сердце физ.
ULT_FIRE_DURATION = 2 * 20     # 2 секунды горения

# Дебаффы после ульта
POST_ULT_DUR      = 10 * 20
POST_ULT_VULN_MULT = 1.20      # +20% входящего урона

# Запрещённая еда — мясные продукты.
MEAT_TYPES = set([
    Material.PORKCHOP, Material.COOKED_PORKCHOP,
    Material.BEEF, Material.COOKED_BEEF,
    Material.CHICKEN, Material.COOKED_CHICKEN,
    Material.MUTTON, Material.COOKED_MUTTON,
    Material.RABBIT, Material.COOKED_RABBIT,
    Material.COD, Material.COOKED_COD,
    Material.SALMON, Material.COOKED_SALMON,
    Material.PUFFERFISH, Material.TROPICAL_FISH,
    Material.ROTTEN_FLESH, Material.SPIDER_EYE,
])


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k): return Registry.EFFECT.get(NamespacedKey.minecraft(k))

E_SLOWNESS = _effect("slowness")
E_WEAKNESS = _effect("weakness")


# =============================================================================
#  STATE
# =============================================================================

cooldowns    = {}
# Пост-ульт-состояние: uid -> end_tick уязвимости.
post_ult_vuln = {}


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

def is_shaman(p):
    name = p.getName().lower()
    if name not in SHAMAN_NAMES:
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


def _check_common(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return False
    return True


# =============================================================================
#  ABILITIES
# =============================================================================

def ability_rain(player):
    if not _check_common(player): return
    if not check_cd(player, "rain", u"«Призыв дождя»"):
        return
    world = player.getWorld()
    try:
        world.setStorm(True)
        world.setThundering(True)
        # Держим погоду достаточно долго — 20 минут (ванильно потом сама сменится).
        world.setWeatherDuration(20 * 60 * 20)
        world.setThunderDuration(20 * 60 * 20)
    except Exception as ex:
        player.sendMessage(u"§cОшибка: §f" + str(ex))
        return
    player.sendMessage(u"§8§l✦ Гроза призвана.")
    world.playSound(player.getLocation(), Sound.ITEM_TRIDENT_THUNDER, 1.0, 0.5)
    world.playSound(player.getLocation(), Sound.ENTITY_LIGHTNING_BOLT_THUNDER, 0.6, 0.9)
    set_cd(player, "rain", CD_RAIN)


def ability_clear(player):
    if not _check_common(player): return
    if not check_cd(player, "clear", u"«Призыв ясной погоды»"):
        return
    world = player.getWorld()
    try:
        world.setStorm(False)
        world.setThundering(False)
        world.setClearWeatherDuration(20 * 60 * 20)
    except Exception as ex:
        player.sendMessage(u"§cОшибка: §f" + str(ex))
        return
    player.sendMessage(u"§e§l✦ Ясная погода призвана.")
    world.playSound(player.getLocation(), Sound.BLOCK_BEACON_ACTIVATE, 0.8, 1.6)
    set_cd(player, "clear", CD_CLEAR)


def ability_time_swap(player):
    if not _check_common(player): return
    if not check_cd(player, "time", u"«Смена дня и ночи»"):
        return
    world = player.getWorld()
    try:
        # 0..12000 — день, 12000..24000 — ночь.
        current_time = world.getTime()
        if current_time < 12000:
            world.setTime(13000)   # ночь
            player.sendMessage(u"§9§l✦ Ночь настала.")
        else:
            world.setTime(1000)    # день
            player.sendMessage(u"§e§l✦ День наступил.")
        world.playSound(player.getLocation(), Sound.BLOCK_BEACON_POWER_SELECT, 1.0, 0.7)
    except Exception as ex:
        player.sendMessage(u"§cОшибка: §f" + str(ex))
        return
    set_cd(player, "time", CD_TIME)


def ability_ult(player):
    if not _check_common(player): return
    if not check_cd(player, "ult", u"«Гнев стихий»"):
        return

    world = player.getWorld()
    center = player.getLocation()
    start_tick = now_tick()
    end_tick   = start_tick + ULT_DURATION

    # Определяем режим по стартовой погоде (даже если она поменяется, режим ульта не меняется).
    is_storm = world.hasStorm() or world.isThundering()

    if is_storm:
        player.sendMessage(u"§9§l✦ ГНЕВ ГРОЗЫ! §7— 20 секунд удары молний.")
    else:
        player.sendMessage(u"§6§l✦ ГНЕВ СОЛНЦА! §7— 20 секунд огня.")

    world.playSound(center, Sound.ENTITY_ENDER_DRAGON_GROWL, 1.0, 0.5)
    world.spawnParticle(Particle.LARGE_SMOKE, center, 80, 5.0, 3.0, 5.0, 0.05)

    # Триггеры внутри ульта.
    if is_storm:
        _schedule_storm_ticks(player, world, end_tick)
    else:
        _schedule_clear_ticks(player, world, end_tick)

    # Финал: дебаффы.
    def finish():
        if not player.isOnline():
            return
        add_effect(player, E_SLOWNESS, POST_ULT_DUR, 1)   # Slowness II
        add_effect(player, E_WEAKNESS, POST_ULT_DUR, 0)   # Weakness I
        post_ult_vuln[uid(player)] = now_tick() + POST_ULT_DUR
        player.sendMessage(u"§8Стихии истощили тело — §7Slowness II + Weakness I + §c+20% входящего урона §7на 10 сек.")

    scheduler.runTaskLater(finish, ULT_DURATION)
    set_cd(player, "ult", CD_ULT + POST_ULT_DUR)   # КД начинается после дебаффа


def _schedule_clear_ticks(player, world, end_tick):
    """Раз в 3 сек: 1 сердце + поджиг 2 сек всем в кубе 15×15×15."""
    def tick():
        if now_tick() >= end_tick:
            return
        if not player.isOnline():
            return
        center = player.getLocation()
        for e in world.getNearbyEntities(center, ULT_BOX_R, ULT_BOX_R, ULT_BOX_R):
            if not isinstance(e, LivingEntity): continue
            if e.equals(player): continue
            try:
                e.damage(ULT_DAMAGE, player)
            except Exception:
                pass
            try:
                # Поджиг: setFireTicks увеличиваем на 2 сек, но не меньше уже горящего.
                cur = e.getFireTicks()
                if cur < ULT_FIRE_DURATION:
                    e.setFireTicks(ULT_FIRE_DURATION)
            except Exception:
                pass
            world.spawnParticle(Particle.FLAME, e.getLocation().add(0, 1, 0),
                                20, 0.3, 0.5, 0.3, 0.05)
        # Партиклы куба.
        world.spawnParticle(Particle.LAVA, center, 10, ULT_BOX_R, 2.0, ULT_BOX_R, 0.0)
        scheduler.runTaskLater(tick, ULT_CLEAR_TICK)
    scheduler.runTaskLater(tick, ULT_CLEAR_TICK)


def _schedule_storm_ticks(player, world, end_tick):
    """Раз в 4 сек: молния (без блоков) в каждого противника в кубе."""
    def tick():
        if now_tick() >= end_tick:
            return
        if not player.isOnline():
            return
        center = player.getLocation()
        hit_any = False
        for e in world.getNearbyEntities(center, ULT_BOX_R, ULT_BOX_R, ULT_BOX_R):
            if not isinstance(e, LivingEntity): continue
            if e.equals(player): continue
            hit_any = True
            # Молния без разрушений: strikeLightningEffect + ручной урон.
            try:
                world.strikeLightningEffect(e.getLocation())
            except Exception:
                pass
            try:
                e.damage(ULT_DAMAGE, player)
            except Exception:
                pass
            world.spawnParticle(Particle.ELECTRIC_SPARK, e.getLocation().add(0, 1, 0),
                                30, 0.4, 0.6, 0.4, 0.1)
        # Дополнительный визуал.
        world.spawnParticle(Particle.CLOUD, center, 60, ULT_BOX_R, 3.0, ULT_BOX_R, 0.02)
        scheduler.runTaskLater(tick, ULT_STORM_TICK)
    scheduler.runTaskLater(tick, ULT_STORM_TICK)


# =============================================================================
#  DAMAGE / FOOD HOOKS
# =============================================================================

def on_damage(event):
    ent = event.getEntity()
    if not isinstance(ent, Player): return
    if not is_shaman(ent): return
    # +20% входящего урона в течение 10 сек после ульта.
    u = uid(ent)
    if u in post_ult_vuln and now_tick() < post_ult_vuln[u]:
        event.setDamage(event.getDamage() * POST_ULT_VULN_MULT)


def on_consume(event):
    p = event.getPlayer()
    if not is_shaman(p): return
    mat = event.getItem().getType()
    if mat in MEAT_TYPES:
        event.setCancelled(True)
        p.sendMessage(u"§8Связь с природой отвергает мясную пищу.")


# =============================================================================
#  KIT ENTRY (роль без особого предмета)
# =============================================================================

def kit_entry(player, args_list):
    if not is_shaman(player):
        player.sendMessage(u"§cТолько Тёмный Шаман может активировать эту роль.")
        return
    player.sendMessage(u"§8§l✦ Роль Тёмного Шамана активирована.")
    player.sendMessage(u"§7Способности: §f/shaman <дождь | ясно | время | ульт>")
    player.sendMessage(u"§8Особого предмета нет — работаешь пустыми руками.")


# =============================================================================
#  COMMAND
# =============================================================================

def cmd_shaman(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько для игроков.")
        return True
    if not is_shaman(sender):
        sender.sendMessage(u"§cТолько Тёмный Шаман может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/shaman дождь §7— гроза")
        sender.sendMessage(u"  §f/shaman ясно §7— ясная погода")
        sender.sendMessage(u"  §f/shaman время §7— смена дня/ночи")
        sender.sendMessage(u"  §f/shaman ульт §7— Гнев стихий")
        return True

    sub = args[0].lower()

    if sub in (u"дождь", u"гроза", u"rain", u"storm"):
        ability_rain(sender); return True
    if sub in (u"ясно", u"ясная", u"clear", u"солнце"):
        ability_clear(sender); return True
    if sub in (u"время", u"time", u"деньночь", u"смена"):
        ability_time_swap(sender); return True
    if sub in (u"ульт", u"ult", u"гнев", u"стихии"):
        ability_ult(sender); return True

    sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
    return True


# =============================================================================
#  RESET STATE (для /admin resethp)
# =============================================================================

def _shaman_reset_state(target_player):
    post_ult_vuln.pop(uid(target_player), None)


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_shaman, "shaman")

listener_mgr.registerListener(on_damage,  EntityDamageEvent)
listener_mgr.registerListener(on_consume, PlayerItemConsumeEvent)

# --- Реестры ---
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("shaman", (kit_entry, u"Тёмный Шаман (без предмета)"))

_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("shaman", list(SHAMAN_NAMES))

_RESET_KEY = "character_reset_functions"
_reset_reg = _props.get(_RESET_KEY)
if _reset_reg is None:
    _reset_reg = HashMap()
    _props.put(_RESET_KEY, _reset_reg)
_reset_reg.put("shaman", _shaman_reset_state)


# Особого предмета нет → в каталог Зеркала Арчера не публикуем.


Bukkit.getLogger().info("[shaman] Shadow Shaman loaded. Commands: /test shaman, /shaman")

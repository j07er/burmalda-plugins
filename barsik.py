# -*- coding: utf-8 -*-
"""
==============================================================================
  КОТ БАРСИК (soffo4kka) — Когти Хищника
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test barsik [1..5]           — выдать Когти нужного тира
  /barsik <способность>         — способности
      рывок | когти | охотник | ульт | улучшить | тир <n>
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, IllegalArgumentException
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, GameMode, Location
)
from org.bukkit.entity import (
    Player, LivingEntity, Creeper
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent, PlayerRespawnEvent,
    PlayerItemHeldEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDeathEvent,
    EntityTargetLivingEntityEvent, PlayerDeathEvent
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


# =============================================================================
#  CONSTANTS
# =============================================================================

BARSIK_NAMES    = set([u"soffo4kka", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_CLAWS = NamespacedKey.fromString("barsik:claws")
KEY_TIER  = NamespacedKey.fromString("barsik:tier")
KEY_OWNER = NamespacedKey.fromString("barsik:owner")

TIER_MATERIAL = {
    1: Material.IRON_SWORD,
    2: Material.IRON_SWORD,
    3: Material.GOLDEN_SWORD,
    4: Material.DIAMOND_SWORD,
    5: Material.NETHERITE_SWORD,
}
TIER_NAME = {
    1: u"§7§lОстрые когти §f§oI",
    2: u"§7§lСтальные когти §f§oII",
    3: u"§e§lКогти охотника §f§oIII",
    4: u"§b§lКогти альфы §f§oIV",
    5: u"§4§lЛегендарные когти §f§oV",
}

# Целевой TOTAL Attack Damage по спеке dummy.py:
#   T1=5.0, T2=6.5, T3=8.0, T4=9.5, T5=11.0 (центр диапазонов).
# База предмета всегда 1.0 (ванильно), плюс наш AttributeModifier доводит до target.
# ВНИМАНИЕ: как только к слоту HAND добавляется ЛЮБОЙ AttributeModifier,
# Bukkit СТИРАЕТ дефолтный ATK материала (см. фикс Криса от 2026-07-28).
# Поэтому bonus = target - 1.0, а не target - material_atk.
TIER_TARGET_ATK = {1: 5.0, 2: 6.5, 3: 8.0, 4: 9.5, 5: 11.0}
# Alias для совместимости с внешним кодом (если где-то читалось).
TIER_DAMAGE_BONUS = {t: v - 1.0 for t, v in TIER_TARGET_ATK.items()}

CD_DASH_BASE       = 15 * 20         # тир 2 -5с; тир 5 = 10с (доп -20%)
CD_LIVES           = 3 * 60 * 20
LIVES_DURATION     = 5 * 20
LIVES_EXHAUSTION   = 15 * 20
CD_SHARP_BASE      = 30 * 20         # Острые когти
CD_INVIS_BASE      = 40 * 20         # Невидимый охотник
CD_ULT_BASE        = 2 * 60 * 20
ULT_DUR            = 12 * 20
INVIS_DUR          = 8 * 20

DAMAGE_MOD_UUID     = JUUID.fromString("aaaa1111-bbbb-2222-cccc-3333dddd4444")
MAX_HEALTH_MOD_UUID = JUUID.fromString("aaaa1111-bbbb-2222-cccc-5555ddddffff")
SPEED_MOD_UUID      = JUUID.fromString("aaaa1111-bbbb-2222-cccc-6666eeee7777")

CREEPER_FLEE_R = {1: 0.0, 2: 14.0, 3: 14.0, 4: 18.0, 5: 18.0}


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k):  return Registry.EFFECT.get(NamespacedKey.minecraft(k))
def _enchant(k): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

E_SPEED       = _effect("speed")
E_RESIST      = _effect("resistance")
E_STRENGTH    = _effect("strength")
E_JUMP        = _effect("jump_boost")
E_NIGHT_VIS   = _effect("night_vision")
E_WEAKNESS    = _effect("weakness")
E_SLOWNESS    = _effect("slowness")
E_MINING_FTG  = _effect("mining_fatigue")
E_WITHER      = _effect("wither")
E_INVIS       = _effect("invisibility")


# =============================================================================
#  STATE
# =============================================================================

cooldowns    = {}
lives_exhaust = {}   # uid -> tick окончания истощения
lives_used   = {}    # uid -> tick последнего использования

# Острые когти: uid -> {"hits_left":3, "end_tick":t}
sharp_state = {}
# Невидимый охотник: uid -> {"end_tick": t}
invis_state = {}
# Первый удар после рывка +2 (Тир III+): uid -> end_tick
dash_bonus = {}

# Ульт активен: uid -> end_tick
ult_active = {}

# Таймер выхода из воды (для 3-секундного продолжения дебаффа).
wet_until = {}   # uid -> tick, до которого действует дебафф после высыхания


# =============================================================================
#  UTILS
# =============================================================================

def uid(e): return e.getUniqueId().toString()
def now_tick(): return long(System.currentTimeMillis() / 50)
def is_barsik(p):
    name = p.getName().lower()
    if name not in BARSIK_NAMES:
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

def _cd_multiplier(player):
    if current_claws_tier(player) >= 5:
        return 0.8
    return 1.0

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
    cooldowns[u][name] = now_tick() + int(ticks * _cd_multiplier(p))

def check_cd(p, name, label=None):
    r = get_cd(p, name)
    if r > 0:
        secs = (r + 19) // 20
        p.sendMessage(u"§cПерезарядка%s: §f%d§7 сек." % ((u" "+label) if label else u"", secs))
        return False
    return True

def is_claws(item):
    if item is None or item.getType() == Material.AIR: return False
    m = item.getItemMeta()
    if m is None: return False
    return m.getPersistentDataContainer().has(KEY_CLAWS, PersistentDataType.BYTE)

def get_claws_tier(item):
    m = item.getItemMeta()
    if m is None: return 0
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER): return 0
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)

def get_claws_owner(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def can_wield(p, item):
    if not is_barsik(p): return False
    if not is_claws(item): return False
    o = get_claws_owner(item)
    return o is None or o == uid(p)

def claws_anywhere(player):
    for it in player.getInventory().getContents():
        if is_claws(it): return True
    return False

def current_claws_tier(player):
    best = 0
    for it in player.getInventory().getContents():
        if is_claws(it):
            t = get_claws_tier(it)
            if t > best: best = t
    return best


# =============================================================================
#  ITEM
# =============================================================================

def create_claws(tier, owner_uuid):
    if tier < 1: tier = 1
    if tier > 5: tier = 5
    it = ItemStack(TIER_MATERIAL[tier], 1)
    m = it.getItemMeta()
    m.setDisplayName(TIER_NAME[tier])
    target_atk = TIER_TARGET_ATK[tier]
    lore = [
        u"§7Когти хищника.",
        u"§8Уровень: §f" + [u"", u"I", u"II", u"III", u"IV", u"V"][tier],
        u"§8Урон: §f%.1f❤" % (target_atk / 2.0),
        u"",
        u"§8Только Барсик может использовать эти когти.",
    ]
    m.setLore(java_list(lore))
    m.setUnbreakable(True)

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_CLAWS, PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_TIER,  PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER, PersistentDataType.STRING,  owner_uuid)

    # ATK: как только к слоту HAND добавляется ЛЮБОЙ modifier, Bukkit стирает
    # дефолтный ATK материала. Поэтому bonus = target - 1.0 (голая база).
    try:
        bonus = target_atk - 1.0
        mod = AttributeModifier(
            DAMAGE_MOD_UUID, "barsik_dmg", bonus,
            AttributeModifier.Operation.ADD_NUMBER,
            EquipmentSlot.HAND
        )
        m.addAttributeModifier(ATTR_ATTACK_DAMAGE, mod)
    except Exception as ex:
        Bukkit.getLogger().warning("[barsik] damage attr: " + str(ex))

    # ATTACK_SPEED: тоже стирается вместе с ATK. Возвращаем стандартную меч-скорость 1.6/сек
    # (base 4.0 + mod -2.4).
    try:
        mod_spd = AttributeModifier(
            SPEED_MOD_UUID, "barsik_spd", -2.4,
            AttributeModifier.Operation.ADD_NUMBER,
            EquipmentSlot.HAND
        )
        m.addAttributeModifier(ATTR_ATTACK_SPEED, mod_spd)
    except Exception as ex:
        Bukkit.getLogger().warning("[barsik] speed attr: " + str(ex))

    it.setItemMeta(m)
    return it


def replace_claws(player, tier):
    inv = player.getInventory()
    contents = inv.getContents()
    for i in range(len(contents)):
        if is_claws(contents[i]):
            inv.setItem(i, create_claws(tier, uid(player)))
            return True
    return False


def give_claws(player, tier=1):
    inv = player.getInventory()
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, create_claws(tier, uid(player)))
            player.sendMessage(u"§6§l✦ §rКогти Хищника. §7Уровень §f" +
                               [u"", u"I", u"II", u"III", u"IV", u"V"][tier])
            return
    inv.setItem(0, create_claws(tier, uid(player)))
    player.sendMessage(u"§6§l✦ §rКогти Хищника. §7Уровень §f" +
                       [u"", u"I", u"II", u"III", u"IV", u"V"][tier])


def kit_entry(player, args_list):
    if not is_barsik(player):
        player.sendMessage(u"§cТолько Барсик достоин этих когтей.")
        return
    tier = 1
    if args_list and len(args_list) >= 1:
        try:
            tier = int(args_list[0])
            if tier < 1 or tier > 5: tier = 1
        except (ValueError, TypeError):
            tier = 1
    give_claws(player, tier)


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

UPGRADE_COSTS = {
    2: [("COD", 16)],
    3: [("DIAMOND", 3)],
    4: [("ENDER_EYE", 5)],
    5: [("CRYING_OBSIDIAN", 2)],
}

def try_upgrade(player):
    cur = current_claws_tier(player)
    if cur >= 5:
        player.sendMessage(u"§7Легендарные когти уже достигнуты.")
        return
    next_tier = cur + 1
    cost = UPGRADE_COSTS.get(next_tier)
    if cost is None: return
    missing = []
    for mat, cnt in cost:
        have = _count_items(player, mat)
        if have < cnt:
            missing.append(u"§7- §f" + mat + u"§7: " + str(have) + u"/" + str(cnt))
    if missing:
        player.sendMessage(u"§cНедостаточно для уровня " +
                           [u"", u"I", u"II", u"III", u"IV", u"V"][next_tier] + u":")
        for line in missing: player.sendMessage(line)
        return
    for mat, cnt in cost:
        _remove_items(player, mat, cnt)
    replace_claws(player, next_tier)
    player.sendMessage(u"§6§l✦ Когти улучшены до уровня " +
                       [u"", u"I", u"II", u"III", u"IV", u"V"][next_tier] + u"§7.")
    player.getWorld().playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)


# =============================================================================
#  ABILITIES — только те, что в ТЗ
# =============================================================================

def _check_common(player):
    if uid(player) in lives_exhaust and now_tick() < lives_exhaust[uid(player)]:
        rem = (lives_exhaust[uid(player)] - now_tick() + 19) // 20
        player.sendMessage(u"§8Истощение после Девяти жизней: §7ещё §f" + str(rem) + u" §7сек.")
        return False
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return False
    if not claws_anywhere(player):
        player.sendMessage(u"§cДля способностей нужны Когти Хищника.")
        return False
    return True


# --- 1. Кошачий рывок --------------------------------------------------------

def ability_dash(player):
    if not _check_common(player): return
    tier = current_claws_tier(player)
    # Тир 2+ уменьшает КД на 5 сек.
    cd = CD_DASH_BASE - (5 * 20 if tier >= 2 else 0)
    if not check_cd(player, "dash", u"«Кошачий рывок»"):
        return

    dv = player.getLocation().getDirection()
    dv.setY(0)
    if dv.lengthSquared() < 0.01:
        dv = Vector(0, 0, 1)
    dv = dv.normalize().multiply(2.4)
    dv.setY(0.35)
    player.setVelocity(dv)
    player.setFallDistance(0.0)

    origin = player.getLocation()
    world = player.getWorld()
    world.playSound(origin, Sound.ENTITY_CAT_HISS, 1.0, 1.4)
    world.spawnParticle(Particle.SWEEP_ATTACK, origin.add(0, 1, 0), 5, 0.3, 0.3, 0.3, 0.0)

    # Урон ближайшему противнику на пути.
    state = {"t": 0, "hit": set()}
    def dash_tick():
        if state["t"] >= 15 or not player.isOnline():
            # Тир III+: следующий удар +2 обычного урона (окно 3 сек).
            if current_claws_tier(player) >= 3:
                dash_bonus[uid(player)] = now_tick() + 3 * 20
            return
        loc = player.getLocation()
        for e in loc.getWorld().getNearbyEntities(loc, 2.0, 2.0, 2.0):
            if not isinstance(e, LivingEntity): continue
            if e.equals(player): continue
            if uid(e) in state["hit"]: continue
            state["hit"].add(uid(e))
            try:
                e.damage(4.0, player)   # доп. урон на пути
            except Exception: pass
        player.setFallDistance(0.0)
        state["t"] += 3
        scheduler.runTaskLater(dash_tick, 3)
    scheduler.runTaskLater(dash_tick, 2)

    for t in (10, 20, 30, 40, 60):
        scheduler.runTaskLater(lambda p=player: (p.isOnline() and p.setFallDistance(0.0)), t)

    set_cd(player, "dash", cd)


# --- 2. Девять жизней (авто) — в on_damage ----------------------------------

def _lives_ready(player):
    if is_free_cd(player):
        return True
    last = lives_used.get(uid(player), 0)
    return now_tick() - last >= CD_LIVES

def _trigger_nine_lives(player):
    lives_used[uid(player)] = now_tick()
    player.setHealth(4.0)   # 2 сердца
    add_effect(player, E_SPEED,  LIVES_DURATION, 1)
    add_effect(player, E_RESIST, LIVES_DURATION, 0)
    player.sendMessage(u"§4§l✦ Девять жизней спасли Барсика! §7Скорость II + Сопр. I на 5 сек.")
    player.getWorld().spawnParticle(Particle.HEART, player.getLocation().add(0, 2, 0), 10, 0.5, 0.5, 0.5)
    player.getWorld().playSound(player.getLocation(), Sound.ENTITY_CAT_PURR, 1.0, 0.6)
    lives_exhaust[uid(player)] = now_tick() + LIVES_DURATION + LIVES_EXHAUSTION


# --- 3. Острые когти (открывается на III) -----------------------------------

def ability_sharp(player):
    if current_claws_tier(player) < 3:
        player.sendMessage(u"§cТребуется уровень III+.")
        return
    if not _check_common(player): return
    if not check_cd(player, "sharp", u"«Острые когти»"):
        return
    sharp_state[uid(player)] = {"hits_left": 3, "end_tick": now_tick() + 10 * 20}
    player.sendMessage(u"§6§l✦ Острые когти §r§7— 3 удара усилены.")
    player.getWorld().playSound(player.getLocation(), Sound.ENTITY_CAT_HISS, 0.9, 1.4)
    set_cd(player, "sharp", CD_SHARP_BASE)


# --- 4. Невидимый охотник (открывается на IV) -------------------------------

def ability_hunter(player):
    if current_claws_tier(player) < 4:
        player.sendMessage(u"§cТребуется уровень IV+.")
        return
    if not _check_common(player): return
    if not check_cd(player, "hunter", u"«Невидимый охотник»"):
        return
    add_effect(player, E_INVIS, INVIS_DUR, 0)
    add_effect(player, E_SPEED, INVIS_DUR, 0)
    invis_state[uid(player)] = {"end_tick": now_tick() + INVIS_DUR}
    player.sendMessage(u"§b§l✦ Невидимый охотник §r§7— 8 сек.")
    player.getWorld().playSound(player.getLocation(), Sound.ENTITY_CAT_STRAY_AMBIENT, 0.9, 1.5)
    set_cd(player, "hunter", CD_INVIS_BASE)


# --- 5. Ультимейт — Король Хищников -----------------------------------------

def ability_ult(player):
    if not _check_common(player): return
    if not check_cd(player, "ult", u"«Король Хищников»"):
        return
    ult_active[uid(player)] = now_tick() + ULT_DUR
    add_effect(player, E_SPEED,     ULT_DUR, 1)
    add_effect(player, E_STRENGTH,  ULT_DUR, 0)
    add_effect(player, E_JUMP,      ULT_DUR, 1)
    add_effect(player, E_NIGHT_VIS, ULT_DUR, 0)
    player.sendMessage(u"§4§l✦ КОРОЛЬ ХИЩНИКОВ §r§7— 12 секунд.")
    player.getWorld().spawnParticle(Particle.CRIT, player.getLocation().add(0, 1, 0), 30, 0.5, 0.8, 0.5, 0.1)
    player.getWorld().playSound(player.getLocation(), Sound.ENTITY_ENDER_DRAGON_GROWL, 0.8, 1.3)
    set_cd(player, "ult", CD_ULT_BASE)


# =============================================================================
#  ATTACK HANDLING
# =============================================================================

def on_damage_by(event):
    dmg = event.getDamager()
    ent = event.getEntity()

    # Барсик атакует.
    if isinstance(dmg, Player) and is_barsik(dmg):
        if not isinstance(ent, LivingEntity) or ent.equals(dmg):
            return
        item = dmg.getInventory().getItemInMainHand()
        if not is_claws(item):
            return

        u = uid(dmg)
        tier = get_claws_tier(item)
        extra = 0.0

        # Острые когти: +2 к урону (1 сердце) + Wither I на 3 сек.
        ss = sharp_state.get(u)
        if ss is not None and now_tick() < ss.get("end_tick", 0) and ss.get("hits_left", 0) > 0:
            extra += 2.0
            add_effect(ent, E_WITHER, 3 * 20, 0)
            ss["hits_left"] -= 1
            if ss["hits_left"] <= 0:
                sharp_state.pop(u, None)
            else:
                sharp_state[u] = ss

        # Первый удар после рывка +2 (Тир III+).
        if u in dash_bonus and now_tick() < dash_bonus[u]:
            extra += 2.0
            dash_bonus.pop(u, None)

        # Невидимый охотник: первое попадание — снимаем невидимость, +4 к урону.
        inv_st = invis_state.get(u)
        if inv_st is not None and now_tick() < inv_st.get("end_tick", 0):
            extra += 4.0
            invis_state.pop(u, None)
            try:
                dmg.removePotionEffect(E_INVIS)
            except Exception: pass
            dmg.getWorld().spawnParticle(Particle.CRIT, ent.getLocation().add(0, 1, 0), 25, 0.5, 0.5, 0.5, 0.1)

        # Ульт: атаки накладывают Weakness I на 3 сек.
        # На V + ульт — восстановление 0.5 сердца при ударе.
        if u in ult_active and now_tick() < ult_active[u]:
            add_effect(ent, E_WEAKNESS, 3 * 20, 0)
            if tier >= 5:
                heal = 1.0   # 0.5 сердца
                new_hp = min(dmg.getMaxHealth(), dmg.getHealth() + heal)
                dmg.setHealth(new_hp)
                dmg.getWorld().spawnParticle(Particle.HEART, dmg.getLocation().add(0, 2, 0), 1, 0.2, 0.2, 0.2)

        if extra > 0:
            event.setDamage(event.getDamage() + extra)


def on_damage(event):
    ent = event.getEntity()
    if not isinstance(ent, Player): return
    if not is_barsik(ent): return

    cause = event.getCause()
    C = EntityDamageEvent.DamageCause

    # Пугливость: любой взрыв — Weakness I + Slowness I на 5 сек.
    if cause in (C.ENTITY_EXPLOSION, C.BLOCK_EXPLOSION):
        add_effect(ent, E_WEAKNESS, 5 * 20, 0)
        add_effect(ent, E_SLOWNESS, 5 * 20, 0)

    # Девять жизней — авто-триггер при смертельном уроне.
    final_dmg = event.getFinalDamage()
    if ent.getHealth() - final_dmg <= 0.5:
        if _lives_ready(ent):
            event.setCancelled(True)
            _trigger_nine_lives(ent)


# =============================================================================
#  CREEPER FLEE
# =============================================================================

def on_target(event):
    target = event.getTarget()
    if not isinstance(target, Player): return
    if not is_barsik(target): return
    ent = event.getEntity()

    # Кошки/оцелоты НЕ должны бояться Барсика (одна порода — свои).
    try:
        from org.bukkit.entity import Cat, Ocelot
        if isinstance(ent, Cat) or isinstance(ent, Ocelot):
            # Отменяем "flee" — кошки не убегают и не боятся.
            event.setCancelled(True)
            return
    except Exception:
        pass

    if isinstance(ent, Creeper):
        tier = current_claws_tier(target)
        r = CREEPER_FLEE_R.get(tier, 0.0)
        if r <= 0: return
        event.setCancelled(True)
        away = ent.getLocation().toVector().subtract(target.getLocation().toVector())
        if away.lengthSquared() > 0.01:
            if away.length() < r:
                away = away.normalize().multiply(0.3)
                away.setY(0.1)
                ent.setVelocity(away)


# =============================================================================
#  WATER / RAIN DEBUFF — правильная проверка
# =============================================================================

def _is_head_or_feet_in_water(player):
    """True если ноги или голова игрока в воде."""
    loc = player.getLocation()
    feet_block = loc.getBlock()
    head_block = loc.clone().add(0, 1, 0).getBlock()
    for b in (feet_block, head_block):
        try:
            t = b.getType()
            if t == Material.WATER:
                return True
            # Waterlogged блоки (лестницы, ступени и т.д.) тоже считаются водой.
            bd = b.getBlockData()
            if hasattr(bd, "isWaterlogged"):
                try:
                    if bd.isWaterlogged():
                        return True
                except Exception:
                    pass
        except Exception:
            pass
    # Fallback на API-флаги.
    try:
        if player.isInWater():
            return True
    except Exception: pass
    try:
        if player.isInWaterOrBubbleColumn():
            return True
    except Exception: pass
    return False


def _is_under_open_sky(player):
    """True если над игроком нет крыши (открытое небо до Y=maxHeight)."""
    loc = player.getLocation()
    world = loc.getWorld()
    x = loc.getBlockX()
    z = loc.getBlockZ()
    y_start = loc.getBlockY() + 2   # выше головы
    try:
        y_max = world.getMaxHeight()
    except Exception:
        y_max = 320
    for y in range(y_start, y_max):
        try:
            m = world.getBlockAt(x, y, z).getType()
            if m.isAir(): continue
            # Прозрачные блоки не считаются крышей (стекло — считается).
            # Если что-то есть — крыша.
            return False
        except Exception:
            continue
    return True


def _is_in_rain(player):
    """True если игрок под дождём без крыши. Учитывает биом (в пустыне дождя нет)."""
    world = player.getWorld()
    try:
        if not world.hasStorm():
            return False
    except Exception:
        return False
    loc = player.getLocation()
    # Биом должен принимать осадки.
    try:
        biome = world.getBiome(loc.getBlockX(), loc.getBlockY(), loc.getBlockZ())
        biome_name = biome.getKey().getKey() if hasattr(biome, "getKey") else str(biome)
        # В биомах пустыни / бесплодных земель дождь не идёт (там снег в горах).
        dry_biomes = ("desert", "badlands", "eroded_badlands", "wooded_badlands",
                      "savanna", "savanna_plateau", "windswept_savanna",
                      "the_nether", "nether_wastes", "crimson_forest",
                      "warped_forest", "soul_sand_valley", "basalt_deltas",
                      "the_end", "end_barrens", "end_highlands", "end_midlands",
                      "small_end_islands")
        if any(x in biome_name for x in dry_biomes):
            return False
    except Exception:
        pass
    # Проверяем крышу.
    return _is_under_open_sky(player)


def _passives_tick():
    try:
        now = now_tick()
        for pl in Bukkit.getOnlinePlayers():
            if not is_barsik(pl): continue

            _enforce_max_health(pl)

            world = pl.getWorld()

            # Ночное зрение — по УРОВНЮ БЛОЧНОГО СВЕТА, а не по времени суток.
            # Кошка видит в темноте: в пещерах, за облаками, ночью без факелов.
            # На поверхности днём — обычное зрение.
            try:
                loc = pl.getLocation()
                block = loc.getBlock()
                # getLightFromBlocks - свет от блочных источников (факелы, лава)
                # getLightFromSky - от неба (солнце/луна)
                # Считаем ИТОГОВЫЙ уровень света в позиции игрока.
                light = block.getLightLevel()
                # Ниже 7 — уже "темновато" (мобы могут спавниться при <=7).
                is_dark = (light <= 7)
            except Exception:
                is_dark = False
            if is_dark:
                add_effect(pl, E_NIGHT_VIS, 400, 0, ambient=True, particles=False)
            else:
                # Убираем night_vision если мы его применяли раньше и уже светло.
                # Проверяем: если эффект есть и его amplifier=0 (наш) и ambient=True — снимаем.
                try:
                    if pl.hasPotionEffect(E_NIGHT_VIS):
                        eff = pl.getPotionEffect(E_NIGHT_VIS)
                        # Снимаем только если это наш ambient-эффект.
                        # Оставляем ульт-исцеление и другие явные баффы.
                        if eff is not None and eff.isAmbient() and eff.getAmplifier() == 0:
                            pl.removePotionEffect(E_NIGHT_VIS)
                except Exception:
                    pass

            # ---- Нелюбовь к воде + дождь ----
            u = uid(pl)
            wet_now = _is_head_or_feet_in_water(pl) or _is_in_rain(pl)

            if wet_now:
                # Обновляем "мокрый до" = сейчас + 3 сек (эффект длится минимум 3с после выхода).
                wet_until[u] = now + 3 * 20 + 20   # +1 запас
                add_effect(pl, E_SLOWNESS,   40, 0, ambient=True, particles=False)
                add_effect(pl, E_MINING_FTG, 40, 0, ambient=True, particles=False)
            else:
                # После выхода — ещё 3 сек. дебафф.
                w_until = wet_until.get(u, 0)
                if w_until > now:
                    add_effect(pl, E_SLOWNESS,   40, 0, ambient=True, particles=False)
                    add_effect(pl, E_MINING_FTG, 40, 0, ambient=True, particles=False)
                elif w_until != 0:
                    # Таймер истёк — чистим запись.
                    wet_until.pop(u, None)

    except Exception as ex:
        Bukkit.getLogger().warning("[barsik] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


# Флаги наложенных модификаторов max-HP: uid -> True.
# Не итерируемся по attribute.getModifiers() (в Paper 1.21 сломан UUID для чужих
# модификаторов — .getUniqueId() кидает "UUID string too large").
_max_hp_applied = set()

def _enforce_max_health(player):
    u = uid(player)
    if u in _max_hp_applied:
        # Уже накладывали — гарантируем что HP не выше нового максимума.
        try:
            if player.getHealth() > 16.0:
                player.setHealth(16.0)
        except Exception:
            pass
        return
    try:
        attr = player.getAttribute(ATTR_MAX_HEALTH)
        mod = AttributeModifier(
            MAX_HEALTH_MOD_UUID, "barsik_max_hp", -4.0,
            AttributeModifier.Operation.ADD_NUMBER
        )
        try:
            attr.addModifier(mod)
        except IllegalArgumentException:
            # Уже присутствует у игрока — просто помечаем.
            pass
        except Exception as ex:
            # Даже если "уже есть" — фиксируем факт.
            pass
        _max_hp_applied.add(u)
        try:
            if player.getHealth() > 16.0:
                player.setHealth(16.0)
        except Exception:
            pass
    except Exception:
        pass


# =============================================================================
#  ITEM PROTECTION / RESPAWN / INTERACT
# =============================================================================

def on_drop(event):
    if is_claws(event.getItemDrop().getItemStack()):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cКогти нельзя выбросить.")


def on_inv_click(event):
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        it = event.getCurrentItem()
        cursor = event.getCursor()
        if is_claws(it) or is_claws(cursor):
            event.setCancelled(True)
            event.getWhoClicked().sendMessage(u"§cКогти нельзя убрать в контейнер.")


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

    if not is_barsik(player):
        return

    def _check_and_restore():
        try:
            if not player.isOnline():
                return

            if claws_anywhere(player) is None:
                give_claws(player, 1)
                player.sendMessage(u"§7[barsik] Комплект восстановлен.")

        except Exception:
            import traceback
            traceback.print_exc()

    scheduler.runTaskLater(_check_and_restore, 40)





def on_interact(event):
    if event.getHand() != EquipmentSlot.HAND: return
    p = event.getPlayer()
    item = event.getItem()
    if not is_claws(item): return
    if not can_wield(p, item):
        event.setCancelled(True)
        p.sendMessage(u"§cКогти отвергают тебя.")


# =============================================================================
#  COMMAND
# =============================================================================

def cmd_barsik(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько для игроков.")
        return True
    if not is_barsik(sender):
        sender.sendMessage(u"§cТолько Барсик может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/barsik <рывок|когти|охотник|ульт>")
        sender.sendMessage(u"  §f/barsik улучшить §7или §fтир <1..5>")
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
            sender.sendMessage(u"§7Использование: §f/barsik тир <1..5>")
            return True
        try:
            t = int(args[1])
        except ValueError:
            sender.sendMessage(u"§cТир — число.")
            return True
        if t < 1 or t > 5:
            sender.sendMessage(u"§cТиры: 1..5.")
            return True
        if not replace_claws(sender, t):
            give_claws(sender, t)
        else:
            sender.sendMessage(u"§aТир: §f" + [u"", u"I", u"II", u"III", u"IV", u"V"][t])
        return True

    if   sub in (u"рывок", u"dash"):                        ability_dash(sender)
    elif sub in (u"когти", u"острые", u"sharp"):            ability_sharp(sender)
    elif sub in (u"охотник", u"невидимый", u"hunter"):      ability_hunter(sender)
    elif sub in (u"ульт", u"король", u"ult"):               ability_ult(sender)
    else:
        sender.sendMessage(u"§cНеизвестная способность: §f" + sub)
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_barsik, "barsik")

listener_mgr.registerListener(on_damage_by,   EntityDamageByEntityEvent)
listener_mgr.registerListener(on_damage,      EntityDamageEvent)
listener_mgr.registerListener(on_target,      EntityTargetLivingEntityEvent)
listener_mgr.registerListener(on_drop,        PlayerDropItemEvent)
listener_mgr.registerListener(on_inv_click,   InventoryClickEvent)
listener_mgr.registerListener(on_death,       PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,     PlayerRespawnEvent)
listener_mgr.registerListener(on_interact,    PlayerInteractEvent)

_passives_tick()

# --- Регистрации в глобальных реестрах ---
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("barsik", (kit_entry, u"Кот Барсик (Когти Хищника [1..5])"))

_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("barsik", list(BARSIK_NAMES))

def _barsik_set_tier(target_player, tier):
    if tier < 1 or tier > 5: return False
    if not replace_claws(target_player, tier):
        give_claws(target_player, tier)
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("barsik", _barsik_set_tier)


# --- Публикация функции сброса состояния (используется /admin resethp) ---
def _barsik_reset_state(target_player):
    """Снимает модификатор max-HP у Барсика и очищает внутренний set."""
    _max_hp_applied.discard(uid(target_player))
    lives_exhaust.pop(uid(target_player), None)
    sharp_state.pop(uid(target_player), None)
    invis_state.pop(uid(target_player), None)
    dash_bonus.pop(uid(target_player), None)
    ult_active.pop(uid(target_player), None)
    wet_until.pop(uid(target_player), None)
    try:
        attr = target_player.getAttribute(ATTR_MAX_HEALTH)
        # Итерируемся, НЕ вызывая .getUniqueId() (Paper 1.21 bug).
        for m in list(attr.getModifiers()):
            try:
                attr.removeModifier(m)
            except Exception:
                pass
    except Exception:
        pass

_RESET_KEY = "character_reset_functions"
_reset_reg = _props.get(_RESET_KEY)
if _reset_reg is None:
    _reset_reg = HashMap()
    _props.put(_RESET_KEY, _reset_reg)
_reset_reg.put("barsik", _barsik_reset_state)


def _barsik_mirror_claws(owner_uuid):
    it = ItemStack(Material.IRON_SWORD, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§7Когти Хищника")
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

_mirror_publish("barsik:claws", u"когти хищника", u"§7Когти Хищника", _barsik_mirror_claws)


Bukkit.getLogger().info("[barsik] Barsik loaded. Commands: /test barsik, /barsik")

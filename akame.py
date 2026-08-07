# -*- coding: utf-8 -*-
"""
==============================================================================
  АКАМЕ / Akame — Ichizan Hissatsu: Murasame
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  Владельцы: lokolo556 (+ blueredtronce для теста)

  Особый предмет: Ichizan Hissatsu: Murasame
    Тип: Особый меч Акаме (неразрушаемый, не теряется после смерти).

  Развитие оружия:
    I уровень — «Пробуждение Мурасаме»
      Предмет: Каменный меч (STONE_SWORD)
      Чары: Острота III, Добыча II
      Условие перехода на 2 уровень: Убить 350 любых мобов этим мечом.

    II уровень — «Клинок убийцы»
      Предмет: Алмазный меч (DIAMOND_SWORD)
      Чары: Острота IV, Добыча III
      Условие перехода на 3 уровень: Убить 750 любых мобов + убить не менее 15 видов мобов.

    III уровень — «Ichizan Hissatsu: Murasame»
      Предмет: Незеритовый меч (NETHERITE_SWORD)
      Чары: Острота V, Добыча III
      После получения III уровня открывается полный потенциал персонажа.

  Способности (открываются после получения III уровня):
    Пассивная способность — «Поглощение души»
      Каждое убийство моба или игрока восстанавливает / добавляет ½ золотого сердца (1.0 HP).
      Максимум: 6 золотых сердец (12.0 HP).
      Особенности: золотые сердца не имеют времени действия; сохраняются, пока их не снимет входящий урон;
      после потери могут быть восстановлены новыми убийствами.

    Способность 1 — «Яд Мурасаме»
      Каждый удар мечом имеет 15% шанс (35% во время ультимейта) наложить Иссушение I на 1,5 секунды.
      Пассивная способность, работает постоянно.

    Способность 2 — «Ennoodzuno»
      Акаме получает Сила I, Сопротивление I на 8 секунд.
      Перезарядка: 50 секунд.
      Ограничение: недоступна во время ультимейта.

    Способность 3 — «Парирование»
      В течение 0,5 секунды Акаме входит в стойку.
      Если за это время получает удар: полностью парирует атаку; атакующий получает Замедление III, Слепоту II на 0,8 секунды.
      Перезарядка: 7 секунд.

    Способность 4 — «Рывок»
      Быстрый рывок вперед на 3 блока.
      Перезарядка: 6 секунд.
      Ограничение: недоступен во время ультимейта.

    Ультимейт — «Small War Horn»
      Акаме полностью раскрывает силу Мурасаме на 15 секунд.
      Во время действия получает:
        - шанс Иссушения увеличивается с 15% → 35%;
        - Сила I, Скорость I, увеличенная скорость атаки;
        - 12% шанс при каждом попадании восстановить 1 сердце (2.0 HP).
      Ограничения во время ультимейта:
        - разрешено использовать только Парирование;
        - Ennoodzuno и Рывок недоступны;
        - нельзя получать любые внешние положительные эффекты (бафы).
      Перезарядка: 180 секунд.

    Дебаффы:
      - Максимальное здоровье уменьшено на 1 сердце (9 ♥ / 18 HP).
      - После окончания ультимейта получает: Слабость I — 8 секунд, Голод I — 7 секунд.
      - Во время ультимейта нельзя получать положительные эффекты от других игроков или способностей.
      - Нельзя использовать щит (вторая рука заблокирована).
==============================================================================
"""

import os
import json
import random
import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, Long as JLong, Integer as JavaInteger, IllegalArgumentException
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, Location,
    Color
)
from org.bukkit.entity import Player, LivingEntity, Projectile

from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerJoinEvent, PlayerRespawnEvent, PlayerDropItemEvent, PlayerSwapHandItemsEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityPotionEffectEvent, EntityDeathEvent
)
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.inventory import ItemStack
from org.bukkit.persistence import PersistentDataType
from org.bukkit.attribute import Attribute, AttributeModifier

# ============================================================================
# ATTRIBUTE RESOLVER
# ============================================================================
def _attr(name):
    for full_name in (name, "GENERIC_" + name):
        a = getattr(Attribute, full_name, None)
        if a is not None:
            return a
    return None

ATTR_MAX_HEALTH   = _attr("MAX_HEALTH")
ATTR_ATTACK_SPEED = _attr("ATTACK_SPEED")
ATTR_MAX_ABSORPTION = _attr("MAX_ABSORPTION")

from org.bukkit.potion import PotionEffect

# ============================================================================
# CONFIG
# ============================================================================

AKAME_NAMES = set([u"lokolo556", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

# PDC Keys
KEY_SWORD_IDENTIFIER = NamespacedKey.fromString("akame:murasame")
KEY_SWORD_TIER       = NamespacedKey.fromString("akame:tier")
KEY_SWORD_KILLS      = NamespacedKey.fromString("akame:kills")
KEY_SWORD_MOB_TYPES  = NamespacedKey.fromString("akame:mob_types")
KEY_SWORD_OWNER      = NamespacedKey.fromString("akame:owner")

# Cooldowns (ticks)
CD_ENNOODZUNO = 50 * 20
CD_PARRY      = 7 * 20
CD_DASH       = 6 * 20
CD_ULT        = 180 * 20

# Max HP Reduction: -1 heart = -2.0 HP
MAX_HP_REDUCTION = -2.0
MAX_HP_MOD_UUID = JUUID.fromString("cca00001-1111-2222-3333-444455556666")
ATTACK_SPEED_MOD_UUID = JUUID.fromString("cca00002-1111-2222-3333-444455556666")

NEGATIVE_EFFECTS = set([
    u"slowness", u"mining_fatigue", u"weakness", u"poison",
    u"wither", u"blindness", u"darkness", u"hunger",
    u"nausea", u"bad_omen", u"levitation", u"unluck",
    u"glowing",
])

MOB_RU_NAMES = {
    "ZOMBIE": u"Зомби",
    "SKELETON": u"Скелет",
    "SPIDER": u"Паук",
    "CREEPER": u"Крипер",
    "WITCH": u"Ведьма",
    "ENDERMAN": u"Эндермен",
    "ZOMBIFIED_PIGLIN": u"Зомби-пиглин",
    "PIGLIN": u"Пиглин",
    "SLIME": u"Слизень",
    "MAGMA_CUBE": u"Магма-куб",
    "DROWNED": u"Утопленник",
    "HUSK": u"Кадавр",
    "STRAY": u"Зимогор",
    "CAVE_SPIDER": u"Пещерный паук",
    "BLAZE": u"Ифрит",
    "GHAST": u"Гаст",
    "WITHER_SKELETON": u"Скелет-иссушитель",
    "PIG": u"Свинья",
    "COW": u"Корова",
    "SHEEP": u"Овца",
    "CHICKEN": u"Курица",
    "RABBIT": u"Кролик",
    "IRON_GOLEM": u"Железный голем",
    "VILLAGER": u"Житель",
}

# State mappings
cooldowns = {}      # uid -> {ability_name: end_tick}
_max_hp_mod = {}    # uid -> AttributeModifier
_attack_speed_mod = {} # uid -> AttributeModifier
ult_active = {}     # uid -> end_tick
parry_stance = {}   # uid -> end_tick

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

def is_akame(player):
    if player is None or not hasattr(player, "getName"): return False
    n = player.getName().lower()
    matched = False
    for real in AKAME_NAMES:
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
    try:
        eff = Registry.EFFECT.get(NamespacedKey.minecraft(k))
        if eff is not None:
            return eff
    except Exception:
        pass
    try:
        from org.bukkit.potion import PotionEffectType
        eff = PotionEffectType.getByName(k.upper())
        if eff is not None:
            return eff
    except Exception:
        pass
    return None

E_WITHER      = _effect("wither")
E_STRENGTH    = _effect("strength")
E_RESISTANCE  = _effect("resistance")
E_SLOWNESS    = _effect("slowness")
E_BLINDNESS   = _effect("blindness")
E_SPEED       = _effect("speed")
E_WEAKNESS    = _effect("weakness")
E_HUNGER      = _effect("hunger")

ENC_SHARPNESS = Registry.ENCHANTMENT.get(NamespacedKey.minecraft("sharpness"))
ENC_LOOTING   = Registry.ENCHANTMENT.get(NamespacedKey.minecraft("looting"))

def add_effect(entity, ptype, ticks, amp, ambient=True, particles=False):
    if ptype is None or entity is None: return
    try:
        entity.addPotionEffect(PotionEffect(ptype, ticks, amp, ambient, particles, True))
    except Exception:
        pass

def _is_free_cd(player):
    try:
        return player.getName().lower() in FREE_CD_PLAYERS
    except Exception:
        return False

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

def _check_common(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return False
    # Меч должен быть в инвентаре
    inv = player.getInventory()
    has = False
    for it in inv.getContents():
        if is_murasame(it):
            has = True
            break
    if not has:
        player.sendMessage(u"§cДля способностей нужен меч §fIchizan Hissatsu: Murasame §cв инвентаре.")
        return False
    return True

# ============================================================================
# DATA STORAGE
# ============================================================================

def get_script_dir():
    if "__file__" in globals() and __file__:
        try:
            return os.path.dirname(os.path.abspath(__file__))
        except Exception:
            pass
    cwd = os.getcwd()
    pyspigot_path = os.path.join(cwd, "plugins", "PySpigot", "scripts")
    if os.path.exists(pyspigot_path):
        return pyspigot_path
    return cwd

SCRIPT_DIR = get_script_dir()
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "akame.json")

def _load_akame_progress(player):
    p_uuid = uid(player)
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                if p_uuid in data:
                    entry = data[p_uuid]
                    return entry.get("tier", 1), entry.get("kills", 0), entry.get("mob_types", "")
        except Exception as e:
            Bukkit.getLogger().warning("[akame] Error loading progress for " + player.getName() + ": " + str(e))
    return 1, 0, ""

def _save_akame_progress(player, tier, kills, mob_types_str):
    p_uuid = uid(player)
    data = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            pass
            
    data[p_uuid] = {
        "tier": tier,
        "kills": kills,
        "mob_types": mob_types_str
    }
    
    try:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        temp_file = DATA_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
        if hasattr(os, "replace"):
            os.replace(temp_file, DATA_FILE)
        else:
            if os.path.exists(DATA_FILE):
                try: os.remove(DATA_FILE)
                except Exception: pass
            os.rename(temp_file, DATA_FILE)
    except Exception as e:
        Bukkit.getLogger().warning("[akame] Error saving progress for " + player.getName() + ": " + str(e))

# ============================================================================
# SPECIAL SWORD FACTORY & UTILS
# ============================================================================

def is_murasame(item):
    if not item or item.getType() == Material.AIR:
        return False
    meta = item.getItemMeta()
    if meta is None:
        return False
    pdc = meta.getPersistentDataContainer()
    return pdc.has(KEY_SWORD_IDENTIFIER, PersistentDataType.BYTE)

def create_murasame(owner_uuid, tier=1, kills=0, mob_types_str=""):
    if tier == 1:
        mat = Material.STONE_SWORD
    elif tier == 2:
        mat = Material.DIAMOND_SWORD
    else:
        mat = Material.NETHERITE_SWORD

    item = ItemStack(mat, 1)
    meta = item.getItemMeta()
    
    # Unbreakable
    meta.setUnbreakable(True)
    
    # Display name
    if tier == 1:
        meta.setDisplayName(u"§c§lПробуждение Мурасаме")
    elif tier == 2:
        meta.setDisplayName(u"§c§lКлинок убийцы")
    else:
        meta.setDisplayName(u"§4§lIchizan Hissatsu: Murasame")
        
    # Lore
    lore = ArrayList()
    lore.add(u"§7Особый меч Акаме")
    if tier == 1:
        lore.add(u"§7Уровень: §fI — Пробуждение")
        lore.add(u"")
        lore.add(u"§7Прогресс до II уровня:")
        lore.add(u"§eУбийств: §f" + str(kills) + u" §8/ §7350")
    elif tier == 2:
        lore.add(u"§7Уровень: §fII — Клинок убийцы")
        lore.add(u"")
        lore.add(u"§7Прогресс до III уровня:")
        lore.add(u"§eУбийств: §f" + str(kills) + u" §8/ §7750")
        
        types_list = [t for t in mob_types_str.split(",") if t]
        lore.add(u"§eВидов мобов: §f" + str(len(types_list)) + u" §8/ §715")
        if types_list:
            shown_types = types_list[-3:]
            shown_str = u", ".join([format_mob_type(t) for t in shown_types])
            lore.add(u"  §8(последние: " + shown_str + (u"..." if len(types_list) > 3 else u"") + u")")
    else:
        lore.add(u"§7Уровень: §cIII — Ichizan Hissatsu")
        lore.add(u"")
        lore.add(u"§aПолный потенциал разблокирован!")
        
    lore.add(u"")
    lore.add(u"§8Неразрушимый • Сохраняется при смерти")
    meta.setLore(lore)
    
    # PDC metadata (using STRING for safe serialization without JVM class-cast bugs)
    pdc = meta.getPersistentDataContainer()
    pdc.set(KEY_SWORD_IDENTIFIER, PersistentDataType.BYTE, JByte(1))
    pdc.set(KEY_SWORD_TIER, PersistentDataType.STRING, str(tier))
    pdc.set(KEY_SWORD_KILLS, PersistentDataType.STRING, str(kills))
    pdc.set(KEY_SWORD_MOB_TYPES, PersistentDataType.STRING, mob_types_str)
    pdc.set(KEY_SWORD_OWNER, PersistentDataType.STRING, owner_uuid)
    
    # Enchants
    if tier == 1:
        sharp_lvl = 3
        loot_lvl = 2
    elif tier == 2:
        sharp_lvl = 4
        loot_lvl = 3
    else:
        sharp_lvl = 5
        loot_lvl = 3
        
    if ENC_SHARPNESS is not None:
        meta.addEnchant(ENC_SHARPNESS, sharp_lvl, True)
    if ENC_LOOTING is not None:
        meta.addEnchant(ENC_LOOTING, loot_lvl, True)
        
    item.setItemMeta(meta)
    return item

def format_mob_type(t_name):
    if t_name in MOB_RU_NAMES:
        return MOB_RU_NAMES[t_name]
    return _to_unicode(t_name.replace("_", " ").title())

def give_kit(player):
    p_uuid = uid(player)
    tier, kills, mob_types_str = _load_akame_progress(player)
    
    item = create_murasame(p_uuid, tier, kills, mob_types_str)
    
    # Check for existing Murasame
    has_murasame = False
    inv = player.getInventory()
    for slot in range(inv.getSize()):
        it = inv.getItem(slot)
        if is_murasame(it):
            has_murasame = True
            inv.setItem(slot, item)
              
    if not has_murasame:
        leftover = inv.addItem(item)
        if not leftover.isEmpty():
            for it in leftover.values():
                player.getWorld().dropItemNaturally(player.getLocation(), it)
                  
    _check_shield_and_offhand(player)

# ============================================================================
# STAT MODIFIERS & SHIELD BLOCKING
# ============================================================================

def _try_add(attr, mod):
    if attr is None or mod is None: return False
    try:
        attr.addModifier(mod)
        return True
    except IllegalArgumentException:
        return False
    except Exception as ex:
        Bukkit.getLogger().warning("[akame] addModifier: " + str(ex))
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
        for m in list(attr.getModifiers()):
            if m.getUniqueId() == MAX_HP_MOD_UUID or m.getName() == "akame_max_hp":
                attr.removeModifier(m)
        mod = AttributeModifier(
            MAX_HP_MOD_UUID, "akame_max_hp", MAX_HP_REDUCTION,
            AttributeModifier.Operation.ADD_NUMBER
        )
        _try_add(attr, mod)
        _max_hp_mod[u] = mod
        max_hp = attr.getValue()
        if player.getHealth() > max_hp:
            try: player.setHealth(max_hp)
            except Exception: pass
    except Exception as ex:
        Bukkit.getLogger().warning("[akame] max_hp apply: " + str(ex))

def _remove_max_hp_reduction(player):
    u = uid(player)
    _max_hp_mod.pop(u, None)
    try:
        attr = player.getAttribute(ATTR_MAX_HEALTH)
        if attr is not None:
            for m in list(attr.getModifiers()):
                if m.getUniqueId() == MAX_HP_MOD_UUID or m.getName() == "akame_max_hp":
                    attr.removeModifier(m)
    except Exception:
        pass

def _check_shield_and_offhand(player):
    if not is_akame(player):
        return
    offhand = player.getInventory().getItemInOffHand()
    if offhand is not None and offhand.getType() != Material.AIR:
        player.getInventory().setItemInOffHand(None)
        leftover = player.getInventory().addItem(offhand)
        if not leftover.isEmpty():
            for item in leftover.values():
                player.getWorld().dropItemNaturally(player.getLocation(), item)
        player.sendMessage(u"§cАкаме не может использовать левую руку (вторая рука заблокирована)!")
        player.playSound(player.getLocation(), Sound.ENTITY_ITEM_BREAK, 1.0, 1.0)

def _handle_soul_absorption(player, tier=None):
    if not is_akame(player):
        return
        
    try:
        # Paper 1.21.8+ caps absorption to the MAX_ABSORPTION attribute value.
        # Set its base value to 12.0 to allow up to 6 golden hearts.
        if ATTR_MAX_ABSORPTION is not None:
            try:
                attr = player.getAttribute(ATTR_MAX_ABSORPTION)
                if attr is not None:
                    attr.setBaseValue(12.0)
            except Exception:
                pass
                
        current_absorption = player.getAbsorptionAmount()
        new_absorption = min(12.0, current_absorption + 1.0)
        player.setAbsorptionAmount(new_absorption)
        player.playSound(player.getLocation(), Sound.ENTITY_ITEM_PICKUP, 0.5, 1.5)
        player.sendMessage(u"§d❤ +½ Золотого сердца (Поглощение души)")
    except Exception as ex:
        Bukkit.getLogger().warning("[akame] Error giving absorption: " + str(ex))

# ============================================================================
# ACTIVE ABILITIES
# ============================================================================

def _is_ult_active(player):
    u = uid(player)
    if u not in ult_active:
        return False
    end = ult_active[u]
    if now_tick() >= end:
        ult_active.pop(u, None)
        return False
    return True

# Цвет для окрашиваемых частиц (палево-жёлтый, как искры крита)
FX_COLOR = Color.fromRGB(255, 240, 180)

def _spawn_fx(world, particle, loc, count, ox, oy, oz, extra):
    # На Paper 1.21.9+ часть частиц (CRIT и др.) стали окрашиваемыми: без
    # данных цвета спавн падает с IllegalArgumentException ("missing required
    # data class org.bukkit.Color"). Сначала пробуем с цветом; на старых
    # версиях, где цвет для этой частицы запрещён, — без него.
    try:
        world.spawnParticle(particle, loc, count, ox, oy, oz, extra, FX_COLOR)
    except IllegalArgumentException:
        try:
            world.spawnParticle(particle, loc, count, ox, oy, oz, extra)
        except Exception:
            pass
    except Exception:
        pass

# --- Способность 2: Ennoodzuno ----------------------------------------------
def ability_ennoodzuno(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
        
    if _is_ult_active(player):
        player.sendMessage(u"§cЭта способность недоступна во время действия ультимейта!")
        return
        
    if not check_cd(player, "ennoodzuno", u"«Ennoodzuno»"): return
    if not _check_common(player): return

    duration_ticks = 8 * 20
    add_effect(player, E_STRENGTH, duration_ticks, 0)
    add_effect(player, E_RESISTANCE, duration_ticks, 0)
    
    loc = player.getLocation()
    player.getWorld().playSound(loc, Sound.ENTITY_ILLUSIONER_PREPARE_MIRROR, 1.0, 1.2)
    _spawn_fx(player.getWorld(), Particle.CRIT, loc.add(0, 1, 0), 30, 0.5, 0.5, 0.5, 0.1)
    player.sendMessage(u"§c§l✦ Ennoodzuno! §r§7— Твоё тело усилено (Сила I, Сопротивление I) на 8 сек.")
    
    set_cd(player, "ennoodzuno", CD_ENNOODZUNO)

# --- Способность 3: Парирование ----------------------------------------------
def ability_parry(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
        
    if not check_cd(player, "parry", u"«Парирование»"): return
    if not _check_common(player): return

    u = uid(player)
    parry_stance[u] = now_tick() + 10  # 0.5 sec stance (10 ticks)
    
    loc = player.getLocation()
    player.getWorld().playSound(loc, Sound.BLOCK_IRON_TRAPDOOR_CLOSE, 1.0, 1.5)
    _spawn_fx(player.getWorld(), Particle.SWEEP_ATTACK, loc.add(0, 1, 0), 3, 0.2, 0.2, 0.2, 0.0)
    player.sendMessage(u"§9§l✦ Парирование! §r§7— Ты вошла в стойку парирования на 0.5 сек.")
    
    set_cd(player, "parry", CD_PARRY)

def _handle_parry_check(event):
    entity = event.getEntity()
    if not is_akame(entity):
        return False
        
    u = uid(entity)
    if u in parry_stance:
        if now_tick() < parry_stance[u]:
            event.setCancelled(True)
            
            loc = entity.getLocation()
            entity.getWorld().playSound(loc, Sound.ITEM_SHIELD_BLOCK, 1.2, 1.2)
            _spawn_fx(entity.getWorld(), Particle.CRIT, loc.add(0, 1, 0), 15, 0.2, 0.2, 0.2, 0.2)
            entity.sendMessage(u"§9✓ Успешное парирование атаки!")
            
            if isinstance(event, EntityDamageByEntityEvent) or hasattr(event, "getDamager"):
                try:
                    damager = event.getDamager()
                    if isinstance(damager, Projectile) or hasattr(damager, "getShooter"):
                        try:
                            shooter = damager.getShooter()
                            if isinstance(shooter, LivingEntity) or hasattr(shooter, "getInventory"):
                                damager = shooter
                        except Exception:
                            pass
                    
                    # Apply slowness and blindness to the attacker
                    if isinstance(damager, LivingEntity) or hasattr(damager, "addPotionEffect"):
                        add_effect(damager, E_SLOWNESS, 16, 2)  # Slowness III (amp 2)
                        add_effect(damager, E_BLINDNESS, 16, 1) # Blindness II (amp 1)
                        try:
                            damager.sendMessage(u"§cТвоя атака была спарирована Акаме!")
                            damager.playSound(damager.getLocation(), Sound.ENTITY_ELDER_GUARDIAN_CURSE, 0.8, 1.5)
                        except Exception:
                            pass
                except Exception as ex:
                    Bukkit.getLogger().warning("[akame] Error applying parry effects to attacker: " + str(ex))
            return True
        else:
            parry_stance.pop(u, None)
    return False

# --- Способность 4: Рывок ----------------------------------------------------
def ability_dash(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
        
    if _is_ult_active(player):
        player.sendMessage(u"§cЭта способность недоступна во время действия ультимейта!")
        return
        
    if not check_cd(player, "dash", u"«Рывок»"): return
    if not _check_common(player): return

    direction = player.getLocation().getDirection()
    direction.setY(0.1)  # Slight lift to avoid block friction
    direction.normalize()
    
    velocity = direction.multiply(1.3)  # Velocity scales to ~3 blocks
    player.setVelocity(velocity)
    
    loc = player.getLocation()
    player.getWorld().playSound(loc, Sound.ENTITY_PLAYER_ATTACK_SWEEP, 1.0, 1.2)
    _spawn_fx(player.getWorld(), Particle.CLOUD, loc, 15, 0.3, 0.1, 0.3, 0.05)
    player.sendMessage(u"§a§l✦ Рывок вперед!")
    
    set_cd(player, "dash", CD_DASH)

# --- Ультимейт: Small War Horn ----------------------------------------------
def ability_ult(player):
    if is_silenced_by_demiurg(player):
        player.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
        return
        
    if not check_cd(player, "ult", u"«Small War Horn»"): return
    if not _check_common(player): return

    u = uid(player)
    duration_ticks = 15 * 20  # 15 seconds
    end_tick = now_tick() + duration_ticks
    ult_active[u] = end_tick

    # Sounds & Particles
    loc = player.getLocation()
    player.getWorld().playSound(loc, Sound.EVENT_RAID_HORN, 1.5, 1.0)
    player.getWorld().playSound(loc, Sound.ENTITY_ENDER_DRAGON_GROWL, 1.0, 1.2)
    _spawn_fx(player.getWorld(), Particle.FLAME, loc, 60, 1.0, 1.5, 1.0, 0.1)
    player.sendMessage(u"§4§l✦ Small War Horn! §r§7— Акаме полностью раскрывает силу Мурасаме на 15 сек!")

    # Apply ultimate buffs
    add_effect(player, E_STRENGTH, duration_ticks, 0) # Strength I
    add_effect(player, E_SPEED, duration_ticks, 0)    # Speed I

    # Add Attack Speed Modifier
    try:
        attr = player.getAttribute(ATTR_ATTACK_SPEED)
        if attr is not None:
            for m in list(attr.getModifiers()):
                if m.getUniqueId() == ATTACK_SPEED_MOD_UUID or m.getName() == "akame_attack_speed":
                    attr.removeModifier(m)
            mod = AttributeModifier(
                ATTACK_SPEED_MOD_UUID, "akame_attack_speed", 4.0,
                AttributeModifier.Operation.ADD_NUMBER
            )
            _try_add(attr, mod)
            _attack_speed_mod[u] = mod
    except Exception as ex:
        Bukkit.getLogger().warning("[akame] Attack speed apply error: " + str(ex))

    # End ultimate tasks
    def _end_ult():
        try:
            mod = _attack_speed_mod.pop(u, None)
            if mod is not None:
                attr = player.getAttribute(ATTR_ATTACK_SPEED)
                _try_remove(attr, mod)
        except Exception:
            pass
            
        ult_active.pop(u, None)
        
        # Debuffs
        try:
            if player.isOnline() and player.isValid():
                add_effect(player, E_WEAKNESS, 8 * 20, 0) # Weakness I — 8 sec
                add_effect(player, E_HUNGER, 7 * 20, 0)    # Hunger I — 7 sec
                player.sendMessage(u"§7Small War Horn завершился. Ты чувствуешь упадок сил...")
                player.playSound(player.getLocation(), Sound.ENTITY_PLAYER_BREATH, 1.0, 0.8)
        except Exception:
            pass

    scheduler.runTaskLater(_end_ult, duration_ticks)
    set_cd(player, "ult", CD_ULT)

# ============================================================================
# EVENT LISTENERS
# ============================================================================

def on_damage(event):
    _handle_parry_check(event)

def on_damage_by(event):
    damager = event.getDamager()
    if isinstance(damager, Projectile) or hasattr(damager, "getShooter"):
        try:
            shooter = damager.getShooter()
            if is_akame(shooter):
                damager = shooter
        except Exception:
            pass
            
    if not is_akame(damager):
        return
        
    item = damager.getInventory().getItemInMainHand()
    if not is_murasame(item):
        return
        
    target = event.getEntity()
    if not isinstance(target, LivingEntity):
        return
        
    # Murasame Poison
    is_ult = _is_ult_active(damager)
    chance = 0.35 if is_ult else 0.15
    if random.random() < chance:
        add_effect(target, E_WITHER, 30, 0)  # Wither I, 1.5 seconds (30 ticks)
        _spawn_fx(target.getWorld(), Particle.DAMAGE_INDICATOR, target.getLocation().add(0, 1, 0), 3, 0.1, 0.1, 0.1, 0.0)
        target.getWorld().playSound(target.getLocation(), Sound.ENTITY_WITHER_SHOOT, 0.5, 1.8)
        
    # Ultimate heal on hit
    if is_ult:
        if random.random() < 0.12:
            try:
                max_hp = damager.getAttribute(ATTR_MAX_HEALTH).getValue()
                cur_hp = damager.getHealth()
                new_hp = min(max_hp, cur_hp + 2.0)  # +1 heart = 2.0 HP
                damager.setHealth(new_hp)
                
                damager.sendMessage(u"§d❤ Поглощение ульта восстановило тебе 1 сердце!")
                damager.playSound(damager.getLocation(), Sound.ENTITY_EXPERIENCE_ORB_PICKUP, 0.6, 1.5)
                _spawn_fx(damager.getWorld(), Particle.HEART, damager.getLocation().add(0, 1.2, 0), 3, 0.2, 0.2, 0.2, 0.0)
            except Exception:
                pass

def on_potion_effect(event):
    """Блокируем внешние положительные эффекты во время ультимейта."""
    try:
        ent = event.getEntity()
        if not is_akame(ent):
            return
        if not _is_ult_active(ent):
            return
            
        cause = event.getCause()
        if cause is None: return
        cname = cause.name()
        if cname == "PLUGIN":
            return  # Allow own ultimate buffs
            
        new_effect = event.getNewEffect()
        if new_effect is None: return
        etype_name = None
        try:
            etype_name = _to_unicode(new_effect.getType().getKey().getKey())
        except Exception:
            try: etype_name = _to_unicode(new_effect.getType().getName())
            except Exception: return
            
        if etype_name in NEGATIVE_EFFECTS:
            return  # Let negative effects pass
            
        # Cancel any external positive effect/buff
        event.setCancelled(True)
    except Exception:
        pass

def on_interact(event):
    p = event.getPlayer()
    if is_akame(p):
        _check_shield_and_offhand(p)

def on_drop(event):
    if is_murasame(event.getItemDrop().getItemStack()):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cМеч Murasame нельзя выбросить.")

def on_join(event):
    p = event.getPlayer()
    if is_akame(p):
        _ensure_max_hp_reduction(p)
        _check_shield_and_offhand(p)
        give_kit(p)

def on_respawn(event):
    p = event.getPlayer()
    if is_akame(p):
        def _later():
            try:
                _ensure_max_hp_reduction(p)
                _check_shield_and_offhand(p)
                give_kit(p)
            except Exception: pass
        scheduler.runTaskLater(_later, 5)

def on_entity_death(event):
    entity = event.getEntity()
    killer = entity.getKiller()
    if not is_akame(killer):
        return
        
    item = killer.getInventory().getItemInMainHand()
    if not is_murasame(item):
        return
        
    meta = item.getItemMeta()
    pdc = meta.getPersistentDataContainer()
    
    tier_raw = pdc.get(KEY_SWORD_TIER, PersistentDataType.STRING)
    tier = int(tier_raw) if tier_raw is not None else 1
    
    kills_raw = pdc.get(KEY_SWORD_KILLS, PersistentDataType.STRING)
    kills = int(kills_raw) if kills_raw is not None else 0
    
    mob_types_str = pdc.get(KEY_SWORD_MOB_TYPES, PersistentDataType.STRING)
    if mob_types_str is None:
        mob_types_str = ""
        
    entity_type_name = str(entity.getType().name())
    
    if tier == 1:
        kills += 1
        if kills >= 350:
            tier = 2
            kills = 0
            mob_types_str = ""
            killer.playSound(killer.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)
            killer.sendMessage(u"§a§l⚡ §rТвой меч поднялся до §6§lII уровня — «Клинок убийцы»§r!")
            killer.sendMessage(u"§7Оружие превратилось в Алмазный меч с зачарованиями Острота IV, Добыча III!")
        else:
            if kills % 10 == 0 or kills in (1, 2, 3, 5) or kills >= 345:
                killer.sendMessage(u"§7[Акаме] Убийств мечом: §e" + str(kills) + u" §8/ §7350")
                
    elif tier == 2:
        kills += 1
        types_list = [t for t in mob_types_str.split(",") if t]
        is_new_type = False
        if entity_type_name not in types_list:
            types_list.append(entity_type_name)
            mob_types_str = ",".join(types_list)
            is_new_type = True
            
        types_count = len(types_list)
        
        if kills >= 750 and types_count >= 15:
            tier = 3
            kills = 0
            mob_types_str = ""
            killer.playSound(killer.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)
            killer.sendMessage(u"§4§l⚡⚡⚡ §rТвой меч развился до §c§lIII уровня — «Ichizan Hissatsu: Murasame»§r!")
            killer.sendMessage(u"§aТвой полный потенциал Акаме теперь разблокирован!")
            killer.sendMessage(u"§7Доступны способности: Поглощение души, Яд Мурасаме, Ennoodzuno, Парирование, Рывок, Small War Horn!")
        else:
            if is_new_type:
                mob_name = format_mob_type(entity_type_name)
                killer.sendMessage(u"§a✓ Новый вид моба: §f" + mob_name + u"§a! Всего видов: §e" + str(types_count) + u" §8/ §715")
                killer.playSound(killer.getLocation(), Sound.ENTITY_PLAYER_LEVELUP, 0.5, 1.5)
            elif kills % 25 == 0 or kills >= 740:
                killer.sendMessage(u"§7[Акаме] Убийств мечом: §e" + str(kills) + u" §8/ §7750 §8(Видов мобов: §f" + str(types_count) + u" §8/ §715)")
                
    elif tier >= 3:
        pass
        
    new_item = create_murasame(uid(killer), tier, kills, mob_types_str)
    _save_akame_progress(killer, tier, kills, mob_types_str)
    killer.getInventory().setItemInMainHand(new_item)
    
    _handle_soul_absorption(killer)

def on_inv_click(event):
    player = event.getWhoClicked()
    if not is_akame(player):
        return
        
    # Prevent putting Murasame in chests / containers
    top_inv = event.getView().getTopInventory()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        it = event.getCurrentItem()
        cursor = event.getCursor()
        if is_murasame(it) or is_murasame(cursor):
            event.setCancelled(True)
            player.sendMessage(u"§cМеч Murasame нельзя убрать в контейнер.")
            player.playSound(player.getLocation(), Sound.ENTITY_ITEM_BREAK, 0.5, 1.0)
            return
            
    # Quick block offhand slot clicks
    if event.getSlot() == 40:
        event.setCancelled(True)
        player.sendMessage(u"§cВторая рука заблокирована!")
        player.playSound(player.getLocation(), Sound.ENTITY_ITEM_BREAK, 0.5, 1.0)
        return
        
    def _later():
        try: _check_shield_and_offhand(player)
        except Exception: pass
    scheduler.runTaskLater(_later, 1)

def on_swap_hand(event):
    p = event.getPlayer()
    if is_akame(p):
        event.setCancelled(True)
        p.sendMessage(u"§cАкаме не может использовать левую руку (вторая рука заблокирована)!")
        p.playSound(p.getLocation(), Sound.ENTITY_ITEM_BREAK, 0.5, 1.0)

# ============================================================================
# COMMAND & DISPATCHERS
# ============================================================================

def _ability_from_alias(arg):
    a = _norm(arg)
    if a in (u"кит", u"kit", u"выдать", u"give"):              return "kit"
    if a in (u"энно", u"ennoodzuno", u"2"):                    return "ennoodzuno"
    if a in (u"парирование", u"parry", u"3"):                  return "parry"
    if a in (u"рывок", u"dash", u"4"):                         return "dash"
    if a in (u"ульт", u"ult", u"ultimate", u"horn", u"ярость"): return "ult"
    return None

def cmd_akame(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cКоманда только для игроков.")
        return True
    if not is_akame(sender):
        sender.sendMessage(u"§cТы не Акаме (lokolo556).")
        return True

    if len(args) == 0:
        tier, kills, mob_types_str = _load_akame_progress(sender)
        sender.sendMessage(u"§c§lАкаме — Способности персонажа:")
        sender.sendMessage(u"  §f/akame кит §7— Выдать / Обновить твой меч Murasame")
        sender.sendMessage(u"  §f/akame энно §7— «Ennoodzuno» (Сила I, Сопротивление I на 8с)")
        sender.sendMessage(u"  §f/akame парирование §7— «Парирование» (Стойка на 0.5с)")
        sender.sendMessage(u"  §f/akame рывок §7— «Рывок» вперед на 3 блока")
        sender.sendMessage(u"  §f/akame ульт §7— «Small War Horn» (Ультимейт на 15с)")
        sender.sendMessage(u"")
        sender.sendMessage(u"§eТвой прогресс Murasame:")
        if tier == 1:
            sender.sendMessage(u"  §7Уровень §fI §7— Пробуждение. Убийств: §e" + str(kills) + u" §8/ §7350")
        elif tier == 2:
            types_list = [t for t in mob_types_str.split(",") if t]
            sender.sendMessage(u"  §7Уровень §fII §7— Клинок убийцы. Убийств: §e" + str(kills) + u" §8/ §7750, Видов: §f" + str(len(types_list)) + u" §8/ §715")
        else:
            sender.sendMessage(u"  §aУровень III — Ichizan Hissatsu: Murasame (Полный потенциал!)")
        return True

    ab = _ability_from_alias(args[0])

    if ab == "kit":
        give_kit(sender)
        _ensure_max_hp_reduction(sender)
        sender.sendMessage(u"§a✓ Твой меч Murasame выдан / обновлен.")
        return True

    if ab == "ennoodzuno":
        ability_ennoodzuno(sender)
        return True
    if ab == "parry":
        ability_parry(sender)
        return True
    if ab == "dash":
        ability_dash(sender)
        return True
    if ab == "ult":
        ability_ult(sender)
        return True

    sender.sendMessage(u"§cНеизвестная способность.")
    return True

# ============================================================================
# TEST DISPATCHER KIT & RESET STATE
# ============================================================================

def kit_entry(player, args):
    give_kit(player)
    _ensure_max_hp_reduction(player)
    player.sendMessage(u"§a✓ Комплект Акаме выдан.")

def _reset_state(player):
    _remove_max_hp_reduction(player)
    u = uid(player)
    cooldowns.pop(u, None)
    ult_active.pop(u, None)
    parry_stance.pop(u, None)
    try:
        mod = _attack_speed_mod.pop(u, None)
        if mod is not None:
            attr = player.getAttribute(ATTR_ATTACK_SPEED)
            _try_remove(attr, mod)
    except Exception:
        pass
    try:
        player.getInventory().setItemInOffHand(None)
    except Exception:
        pass

def _akame_set_tier(player, tier):
    if tier < 1 or tier > 3:
        return False
    _, kills, mob_types_str = _load_akame_progress(player)
    _save_akame_progress(player, tier, kills, mob_types_str)
    give_kit(player)
    try:
        player.sendMessage(u"§e§l⚡ §rТвой меч «Ichizan Hissatsu: Murasame» изменен до тира §f" + str(tier))
    except Exception: pass
    return True

# ============================================================================
# LIFECYCLE & REGISTRATION
# ============================================================================

cmd_mgr.registerCommand(cmd_akame, "akame")

listener_mgr.registerListener(on_damage,          EntityDamageEvent)
listener_mgr.registerListener(on_damage_by,       EntityDamageByEntityEvent)
listener_mgr.registerListener(on_potion_effect,   EntityPotionEffectEvent)
listener_mgr.registerListener(on_interact,        PlayerInteractEvent)
listener_mgr.registerListener(on_drop,            PlayerDropItemEvent)
listener_mgr.registerListener(on_join,            PlayerJoinEvent)
listener_mgr.registerListener(on_respawn,         PlayerRespawnEvent)
listener_mgr.registerListener(on_entity_death,    EntityDeathEvent)
listener_mgr.registerListener(on_inv_click,       InventoryClickEvent)
listener_mgr.registerListener(on_swap_hand,       PlayerSwapHandItemsEvent)

# Registering globally via System properties
_props = System.getProperties()

_REGISTRY_KEY = "pyspigot.character_kits"
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("akame", (kit_entry, u"Акаме (lokolo556 — Меч Murasame + Прогресс + Яд)"))

_OWNERS_KEY = "character_owners"
_owners = _props.get(_OWNERS_KEY)
if _owners is None:
    _owners = HashMap()
    _props.put(_OWNERS_KEY, _owners)
_owners.put("akame", list(AKAME_NAMES))

_RESET_KEY = "character_reset_functions"
_reset_reg = _props.get(_RESET_KEY)
if _reset_reg is None:
    _reset_reg = HashMap()
    _props.put(_RESET_KEY, _reset_reg)
_reset_reg.put("akame", _reset_state)

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("akame", _akame_set_tier)

# Add namespace to soulbound.namespaces to make items soulbound (unloseable on death)
try:
    ns = _props.get("soulbound.namespaces")
    if ns is not None:
        ns.add("akame")
except Exception:
    pass

# Ensure HP reduction for online players on hot-reload
try:
    for _pl in Bukkit.getOnlinePlayers():
        if is_akame(_pl):
            _ensure_max_hp_reduction(_pl)
except Exception:
    pass

def stop(script=None):
    # Снимаем все модификаторы и очищаем инвентарь при выгрузке скрипта
    try:
        for _pl in Bukkit.getOnlinePlayers():
            if is_akame(_pl):
                _reset_state(_pl)
    except Exception:
        pass

    # Очищаем регистрационные глобальные реестры
    try:
        _props = System.getProperties()
        
        reg = _props.get("pyspigot.character_kits")
        if reg is not None: reg.remove("akame")
        
        owners = _props.get("character_owners")
        if owners is not None: owners.remove("akame")
        
        reset_reg = _props.get("character_reset_functions")
        if reset_reg is not None: reset_reg.remove("akame")
        
        tier_reg = _props.get("character_tier_setters")
        if tier_reg is not None: tier_reg.remove("akame")
        
        ns = _props.get("soulbound.namespaces")
        if ns is not None: ns.remove("akame")
    except Exception:
        pass

    Bukkit.getLogger().info("[akame] Akame (lokolo556) unloaded.")

Bukkit.getLogger().info("[akame] Akame (lokolo556) loaded. Command: /akame")

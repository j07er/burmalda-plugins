# -*- coding: utf-8 -*-
"""Cthulhu — Sleeping Ancient. PySpigot 0.9.1 / Paper 1.21."""

import pyspigot as ps
from java.lang import System, Byte as JByte
from java.util import ArrayList, HashMap
from org.bukkit import Bukkit, Material, Particle, Sound, NamespacedKey, Registry
from org.bukkit.entity import Player, LivingEntity, Monster, EntityType
from org.bukkit.event.player import PlayerDropItemEvent
from org.bukkit.event.entity import EntityDamageEvent
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.enchantments import Enchantment
from org.bukkit.inventory import ItemStack
from org.bukkit.potion import PotionEffect
from org.bukkit.persistence import PersistentDataType
from org.bukkit.util import Vector

try:
    from org.bukkit.damage import DamageSource, DamageType
    HAS_DAMAGE_API = True
except ImportError:
    HAS_DAMAGE_API = False

cmd_mgr = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler = ps.scheduler

CTHULHU_OWNERS = set([u"lox"])
FREE_CD_PLAYERS = set([u"blueredtronce"])
KEY_TRIDENT = NamespacedKey.fromString("cthulhu:crimson_trident")
KEY_TIER = NamespacedKey.fromString("cthulhu:tier")
CD_WHISPER = 35 * 20
CD_SLEEP = 45 * 20
CD_EYE = 60 * 20
CD_HAND = 45 * 20
CD_MARK = 40 * 20
CD_ULT = 5 * 60 * 20

def effect(name): return Registry.EFFECT.get(NamespacedKey.minecraft(name))
def enchant(name): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(name))
E_BLIND = effect("blindness")
E_SLOW = effect("slowness")
E_WEAK = effect("weakness")
E_NAUSEA = effect("nausea")
E_GLOW = effect("glowing")
E_NIGHT = effect("night_vision")
E_STRENGTH = effect("strength")
E_RESIST = effect("resistance")
ENC_LOYALTY = enchant("loyalty")
ENC_IMPALING = enchant("impaling")
ENC_UNBREAKING = enchant("unbreaking")

cooldowns = {}
marks = {}             # owner UUID -> {target_uuid, until}
surface = {}           # owner UUID -> seconds out of water / seconds recovering

def now(): return long(System.currentTimeMillis() / 50)
def uid(entity): return entity.getUniqueId().toString()
def is_cthulhu(player): return isinstance(player, Player) and player.getName().lower() in CTHULHU_OWNERS
def free_cd(player): return player.getName().lower() in FREE_CD_PLAYERS
def add(entity, e, ticks, amp, particles=False):
    if e is not None: entity.addPotionEffect(PotionEffect(e, ticks, amp, True, particles, True))
def set_cd(player, key, ticks):
    if not free_cd(player): cooldowns.setdefault(uid(player), {})[key] = now() + ticks
def check_cd(player, key, label):
    if free_cd(player): return True
    left = cooldowns.get(uid(player), {}).get(key, 0) - now()
    if left > 0:
        player.sendMessage(u"§7" + label + u" будет доступно через §f" + str((left + 19) // 20) + u"§7 сек.")
        return False
    return True

def is_trident(item):
    if item is None or item.getType() == Material.AIR: return False
    meta = item.getItemMeta()
    return meta is not None and meta.getPersistentDataContainer().has(KEY_TRIDENT, PersistentDataType.BYTE)
def item_tier(item):
    if not is_trident(item): return 0
    return int(item.getItemMeta().getPersistentDataContainer().get(KEY_TIER, PersistentDataType.INTEGER) or 0)
def tier(player):
    best = 0
    for item in player.getInventory().getContents(): best = max(best, item_tier(item))
    return best
def has_trident(player): return tier(player) > 0
def jlist(values):
    out = ArrayList()
    for value in values: out.add(value)
    return out
def create_trident(level):
    level = max(1, min(3, int(level)))
    names = {1: u"§4§lТрезубец Багровой Пучины §f§oI", 2: u"§c§lТрезубец Багровой Пучины §b§oII", 3: u"§5§lТрезубец Багровой Пучины §d§oIII"}
    item = ItemStack(Material.TRIDENT, 1)
    meta = item.getItemMeta(); meta.setDisplayName(names[level])
    meta.setLore(jlist([u"§7Оружие Спящего Древнего.", u"§8Тир: §f" + str(level), u"", u"§8Принадлежит Ктулху."]))
    pdc = meta.getPersistentDataContainer(); pdc.set(KEY_TRIDENT, PersistentDataType.BYTE, JByte(1)); pdc.set(KEY_TIER, PersistentDataType.INTEGER, level)
    if ENC_LOYALTY: meta.addEnchant(ENC_LOYALTY, level, True)
    if level >= 2:
        if ENC_IMPALING: meta.addEnchant(ENC_IMPALING, 2 if level == 2 else 5, True)
        if ENC_UNBREAKING: meta.addEnchant(ENC_UNBREAKING, level, True)
    elif ENC_UNBREAKING: meta.addEnchant(ENC_UNBREAKING, 1, True)
    item.setItemMeta(meta); return item
def replace_trident(player, level):
    inv = player.getInventory()
    for index, item in enumerate(inv.getContents()):
        if is_trident(item): inv.setItem(index, create_trident(level)); return True
    return False
def give_kit(player, level=1):
    if not replace_trident(player, level): player.getInventory().addItem(create_trident(level))
    player.sendMessage(u"§5✦ Трезубец Багровой Пучины выдан. §7Тир §f" + str(level))

def target_in_sight(player, distance):
    try:
        ray = player.rayTraceEntities(float(distance))
        if ray is None: return None
        target = ray.getHitEntity()
        if isinstance(target, LivingEntity) and target != player and player.hasLineOfSight(target): return target
    except Exception: pass
    return None
def nearby_enemies(player, radius):
    result = []
    for target in player.getWorld().getNearbyEntities(player.getLocation(), radius, radius, radius):
        if isinstance(target, LivingEntity) and not target.getUniqueId().equals(player.getUniqueId()) and player.hasLineOfSight(target): result.append(target)
    return result
def near_water(player):
    if player.isInWater(): return True
    loc = player.getLocation(); world = player.getWorld()
    for x in (-2, -1, 0, 1, 2):
        for y in (-1, 0, 1):
            for z in (-2, -1, 0, 1, 2):
                if world.getBlockAt(loc.getBlockX() + x, loc.getBlockY() + y, loc.getBlockZ() + z).getType() == Material.WATER: return True
    return False
def pull(target, player, strength=0.42):
    vector = player.getLocation().toVector().subtract(target.getLocation().toVector())
    vector.setY(0)
    if vector.lengthSquared() > .01:
        target.setVelocity(vector.normalize().multiply(strength))

def pure_damage(target, amount, attacker, cannot_kill=False):
    if cannot_kill: amount = min(amount, max(0.0, target.getHealth() - 1.0))
    if amount <= 0: return
    if HAS_DAMAGE_API:
        try:
            source = DamageSource.builder(DamageType.MAGIC).withDirectEntity(attacker).withCausingEntity(attacker).build()
            target.damage(amount, source); return
        except Exception: pass
    try: target.damage(.01, attacker)
    except Exception: pass
    target.setHealth(max(1.0 if cannot_kill else 0.0, target.getHealth() - amount))

def whisper(player):
    if not check_cd(player, "whisper", u"«Шёпот Бездны»"): return
    target = target_in_sight(player, 15)
    if target is None: player.sendMessage(u"§7Нет цели в прямой видимости до 15 блоков."); return
    add(target, E_BLIND, 4 * 20, 0); add(target, E_SLOW, 6 * 20, 1); add(target, E_WEAK, 6 * 20, 0)
    player.getWorld().spawnParticle(Particle.SOUL, target.getEyeLocation(), 30, .35, .55, .35, .03)
    player.getWorld().playSound(target.getLocation(), Sound.ENTITY_ELDER_GUARDIAN_CURSE, .7, .65)
    set_cd(player, "whisper", CD_WHISPER)

def ancient_sleep(player):
    if not check_cd(player, "sleep", u"«Сон Древнего»"): return
    target = target_in_sight(player, 20)
    if target is None: player.sendMessage(u"§7Нет цели в прямой видимости до 20 блоков."); return
    add(target, E_NAUSEA, 8 * 20, 0); add(target, E_WEAK, 8 * 20, 0)
    player.getWorld().playSound(target.getLocation(), Sound.AMBIENT_UNDERWATER_LOOP_ADDITIONS_RARE, .9, .6)
    def nightmare(step=1):
        if step >= 4 or not target.isValid(): return
        target.getWorld().playSound(target.getLocation(), Sound.AMBIENT_UNDERWATER_LOOP_ADDITIONS_ULTRA_RARE, .65, .5)
        scheduler.runTaskLater(lambda: nightmare(step + 1), 2 * 20)
    scheduler.runTaskLater(nightmare, 2 * 20); set_cd(player, "sleep", CD_SLEEP)

def abyss_eye(player):
    if not check_cd(player, "eye", u"«Глаз Бездны»"): return
    seen = 0
    for target in player.getWorld().getNearbyEntities(player.getLocation(), 25, 25, 25):
        if isinstance(target, Player) or isinstance(target, Monster): add(target, E_GLOW, 10 * 20, 0); seen += 1
    add(player, E_NIGHT, 10 * 20, 0)
    player.getWorld().spawnParticle(Particle.SOUL_FIRE_FLAME, player.getEyeLocation(), 45, .4, .4, .4, .03)
    player.sendMessage(u"§3✦ Глаз Бездны обнаружил §f" + str(seen) + u"§3 целей.")
    set_cd(player, "eye", CD_EYE)

def ancient_hand(player):
    if not check_cd(player, "hand", u"«Рука Древнего»"): return
    if not near_water(player): player.sendMessage(u"§cРука Древнего работает только возле воды."); return
    target = target_in_sight(player, 5)
    if target is None: player.sendMessage(u"§7Нужна цель в прямой видимости до 5 блоков."); return
    player.getWorld().playSound(target.getLocation(), Sound.ENTITY_GLOW_SQUID_SQUIRT, .8, .65)
    def tentacle(step=0):
        if step >= 3 or not player.isOnline() or not target.isValid() or not player.hasLineOfSight(target): return
        add(target, E_SLOW, 45, 1); add(target, E_WEAK, 45, 0); pull(target, player)
        target.getWorld().spawnParticle(Particle.SQUID_INK, target.getLocation(), 18, .45, .3, .45, .04)
        scheduler.runTaskLater(lambda: tentacle(step + 1), 2 * 20)
    tentacle(); set_cd(player, "hand", CD_HAND)

def abyss_mark(player):
    if not check_cd(player, "mark", u"«Метка Бездны»"): return
    target = target_in_sight(player, 18)
    if target is None: player.sendMessage(u"§7Нет цели в прямой видимости до 18 блоков."); return
    marks[uid(player)] = {"target": uid(target), "until": now() + 20 * 20}
    player.sendMessage(u"§5✦ Метка Бездны наложена на §f" + (target.getName() if isinstance(target, Player) else target.getType().name()))
    set_cd(player, "mark", CD_MARK)

def awakening(player):
    if not check_cd(player, "ult", u"«Полное Пробуждение»"): return
    if not player.isInWater(): player.sendMessage(u"§cПолное Пробуждение возможно только в воде."); return
    duration = 15 * 20
    victims = nearby_enemies(player, 7)
    for target in victims:
        pure_damage(target, 4.0, player, cannot_kill=True)
        add(target, E_SLOW, duration, 0); add(target, E_WEAK, duration, 0)
    add(player, E_STRENGTH, duration, 0); add(player, E_RESIST, duration, 0)
    player.getWorld().spawnParticle(Particle.SQUID_INK, player.getLocation(), 130, 3.5, 1, 3.5, .08)
    player.getWorld().playSound(player.getLocation(), Sound.ENTITY_ELDER_GUARDIAN_CURSE, 1, .45)
    def ult_pull(step=0):
        if step >= 5 or not player.isOnline() or not player.isInWater(): return
        for target in nearby_enemies(player, 7): pull(target, player)
        scheduler.runTaskLater(lambda: ult_pull(step + 1), 3 * 20)
    ult_pull(); set_cd(player, "ult", CD_ULT)

def passive_tick():
    for player in Bukkit.getOnlinePlayers():
        if not is_cthulhu(player): continue
        state = surface.setdefault(uid(player), {"out": 0, "water": 0})
        if player.isInWater():
            state["water"] += 1; state["out"] = 0
            if state["water"] >= 5:
                player.removePotionEffect(E_WEAK); player.removePotionEffect(E_SLOW)
        else:
            state["water"] = 0; state["out"] += 1
            if state["out"] >= 30: add(player, E_WEAK, 30, 0)
            if state["out"] >= 60: add(player, E_SLOW, 30, 0)
            if state["out"] >= 70: add(player, E_WEAK, 30, 1)
        mark = marks.get(uid(player))
        if mark and mark["until"] <= now(): marks.pop(uid(player), None)
        elif mark:
            # Visible only to Cthulhu: client-targeted particles, no shared Glow effect.
            for entity in player.getWorld().getNearbyEntities(player.getLocation(), 64, 64, 64):
                if uid(entity) == mark["target"]:
                    player.spawnParticle(Particle.SOUL, entity.getLocation().add(0, 1, 0), 8, .35, .75, .35, .01); break
    scheduler.runTaskLater(passive_tick, 20)

def on_damage(event):
    victim = event.getEntity()
    if isinstance(victim, Player) and is_cthulhu(victim):
        cause = event.getCause().name()
        if cause in ("FIRE", "FIRE_TICK", "LAVA"): event.setDamage(event.getDamage() + 2.0)
    target_id = uid(victim)
    for owner_id, mark in list(marks.items()):
        if mark["until"] > now() and mark["target"] == target_id:
            event.setDamage(event.getDamage() * 1.10)
            break
def on_drop(event):
    if is_trident(event.getItemDrop().getItemStack()): event.setCancelled(True); event.getPlayer().sendMessage(u"§cТрезубец нельзя выбросить.")
def on_inventory(event):
    if is_trident(event.getCurrentItem()) or is_trident(event.getCursor()):
        holder = event.getInventory().getHolder()
        if holder is not None and not isinstance(holder, Player): event.setCancelled(True)

def cmd_cthulhu(sender, label, args):
    if not isinstance(sender, Player) or not is_cthulhu(sender): sender.sendMessage(u"§cТолько Ктулху может использовать эту команду."); return True
    if not args: sender.sendMessage(u"§7/cthulhu <шёпот|сон|глаз|рука|метка|ульт>"); return True
    if not has_trident(sender): sender.sendMessage(u"§cНужен Трезубец Багровой Пучины."); return True
    ability = args[0].lower()
    if ability in (u"шёпот", u"whisper"): whisper(sender)
    elif ability in (u"сон", u"sleep"): ancient_sleep(sender)
    elif ability in (u"глаз", u"eye"): abyss_eye(sender)
    elif ability in (u"рука", u"hand"): ancient_hand(sender)
    elif ability in (u"метка", u"mark"): abyss_mark(sender)
    elif ability in (u"ульт", u"ультимейт", u"ult", u"awakening"): awakening(sender)
    else: sender.sendMessage(u"§cНеизвестная способность.")
    return True
def kit_entry(player, args): give_kit(player, int(args[0]) if args and str(args[0]).isdigit() else 1)
def set_tier(player, level):
    if level < 1 or level > 3: return False
    if not replace_trident(player, level): give_kit(player, level)
    return True

cmd_mgr.registerCommand(cmd_cthulhu, "cthulhu")
listener_mgr.registerListener(on_damage, EntityDamageEvent)
listener_mgr.registerListener(on_drop, PlayerDropItemEvent)
listener_mgr.registerListener(on_inventory, InventoryClickEvent)
props = System.getProperties()
reg = props.get("pyspigot.character_kits")
if reg is None: reg = HashMap(); props.put("pyspigot.character_kits", reg)
reg.put("cthulhu", (kit_entry, u"Ктулху (трезубец [тир 1|2|3])"))
owners = props.get("character_owners")
if owners is None: owners = HashMap(); props.put("character_owners", owners)
owners.put("cthulhu", list(CTHULHU_OWNERS))
tiers = props.get("character_tier_setters")
if tiers is None: tiers = HashMap(); props.put("character_tier_setters", tiers)
tiers.put("cthulhu", set_tier)
scheduler.runTaskLater(passive_tick, 20)
Bukkit.getLogger().info("[cthulhu] Loaded. Command: /cthulhu")

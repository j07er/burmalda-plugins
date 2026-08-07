# -*- coding: utf-8 -*-
"""Luna — Time Criminal. PySpigot 0.9.1 / Paper 1.21."""

import random
import pyspigot as ps

from java.lang import System, Byte as JByte
from java.util import UUID as JUUID
from java.util import ArrayList, HashMap
from org.bukkit import Bukkit, Material, Particle, Sound, NamespacedKey, Registry
from org.bukkit.entity import Player, LivingEntity, Zombie, EntityType
from org.bukkit.event.player import PlayerDropItemEvent, PlayerInteractEvent
from org.bukkit.event.entity import EntityDamageByEntityEvent, EntityTargetLivingEntityEvent
from org.bukkit.event.inventory import InventoryClickEvent
from org.bukkit.enchantments import Enchantment
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.potion import PotionEffect
from org.bukkit.persistence import PersistentDataType

cmd_mgr = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler = ps.scheduler

LUNA_OWNERS = set([u"dni214"])
FREE_CD_PLAYERS = set([u"blueredtronce"])
KEY_SWORD = NamespacedKey.fromString("luna:chrono_dagger")
KEY_TIER = NamespacedKey.fromString("luna:tier")
KEY_CLONE = NamespacedKey.fromString("luna:chrono_clone")
KEY_CLONE_TARGET = NamespacedKey.fromString("luna:chrono_clone_target")

CD_SHADOW = 35 * 20
CD_CLONES = 50 * 20
CD_RIFT = 40 * 20
CD_ULT = 5 * 60 * 20
RIFT_DURATION = 8 * 20
ULT_DURATION = 12 * 20

def _effect(name): return Registry.EFFECT.get(NamespacedKey.minecraft(name))
def _enchant(name): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(name))
E_INVIS = _effect("invisibility")
E_SPEED = _effect("speed")
E_STRENGTH = _effect("strength")
E_RESISTANCE = _effect("resistance")
E_SLOWNESS = _effect("slowness")
E_WEAKNESS = _effect("weakness")
E_NAUSEA = _effect("nausea")
E_DARKNESS = _effect("darkness")
E_MINING = _effect("mining_fatigue")
ENC_SHARPNESS = _enchant("sharpness")
ENC_UNBREAKING = _enchant("unbreaking")
ENC_LOOTING = _enchant("looting")
ENC_FIRE = _enchant("fire_aspect")

cooldowns = {}
shadow_strike = {}       # UUID -> expiry tick
last_enemy = {}          # owner UUID -> {target UUID, expiry tick}
ultimate_effects = {}    # owner UUID -> expiry tick; explicit cleanup guard

def tick(): return long(System.currentTimeMillis() / 50)
def uid(p): return p.getUniqueId().toString()
def is_luna(p): return isinstance(p, Player) and p.getName().lower() in LUNA_OWNERS
def free_cd(p): return p.getName().lower() in FREE_CD_PLAYERS
def add_effect(entity, effect, duration, amp, particles=False):
    if effect is not None:
        entity.addPotionEffect(PotionEffect(effect, duration, amp, True, particles, True))
def get_cd(p, name):
    if free_cd(p): return 0
    return max(0, cooldowns.get(uid(p), {}).get(name, 0) - tick())
def check_cd(p, name, label):
    left = get_cd(p, name)
    if left:
        p.sendMessage(u"§7" + label + u" будет доступно через §f" + str((left + 19) // 20) + u"§7 сек.")
        return False
    return True
def set_cd(p, name, duration):
    if not free_cd(p): cooldowns.setdefault(uid(p), {})[name] = tick() + duration

def is_sword(item):
    if item is None or item.getType() == Material.AIR: return False
    meta = item.getItemMeta()
    return meta is not None and meta.getPersistentDataContainer().has(KEY_SWORD, PersistentDataType.BYTE)
def tier_of_item(item):
    if not is_sword(item): return 0
    return int(item.getItemMeta().getPersistentDataContainer().get(KEY_TIER, PersistentDataType.INTEGER) or 0)
def player_tier(p):
    best = 0
    for item in p.getInventory().getContents(): best = max(best, tier_of_item(item))
    return best
def has_sword(p): return player_tier(p) > 0

def jlist(values):
    result = ArrayList()
    for value in values: result.add(value)
    return result
def create_sword(tier):
    tier = max(1, min(3, int(tier)))
    material = [None, Material.STONE_SWORD, Material.IRON_SWORD, Material.NETHERITE_SWORD][tier]
    names = {1: u"§7§lОсколок Первой Луны §f§oI", 2: u"§f§lСеребряный Хроно-Клинок §b§oII", 3: u"§5§lНезеритовый Разломатель Эпох §d§oIII"}
    item = ItemStack(material, 1)
    meta = item.getItemMeta()
    meta.setDisplayName(names[tier])
    meta.setUnbreakable(True)
    meta.setLore(jlist([u"§7Сломанный Лунный Хроно-Кинжал.", u"§8Тир: §f" + str(tier), u"", u"§8Принадлежит Луне."]))
    pdc = meta.getPersistentDataContainer()
    pdc.set(KEY_SWORD, PersistentDataType.BYTE, JByte(1))
    pdc.set(KEY_TIER, PersistentDataType.INTEGER, tier)
    if ENC_SHARPNESS: meta.addEnchant(ENC_SHARPNESS, tier, True)
    if tier >= 2 and ENC_UNBREAKING: meta.addEnchant(ENC_UNBREAKING, tier - 1, True)
    if tier == 3:
        if ENC_LOOTING: meta.addEnchant(ENC_LOOTING, 2, True)
        if ENC_FIRE: meta.addEnchant(ENC_FIRE, 2, True)
    item.setItemMeta(meta)
    return item
def replace_sword(p, tier):
    inv = p.getInventory()
    for i, item in enumerate(inv.getContents()):
        if is_sword(item):
            inv.setItem(i, create_sword(tier)); return True
    return False
def give_kit(p, tier=1):
    if not replace_sword(p, tier): p.getInventory().addItem(create_sword(tier))
    p.sendMessage(u"§5✦ §rЛунный Хроно-Кинжал выдан. §7Тир §f" + str(tier))

def target_in_sight(p, distance):
    try:
        hit = p.rayTraceEntities(float(distance))
        if hit is not None and isinstance(hit.getHitEntity(), LivingEntity): return hit.getHitEntity()
    except Exception: pass
    return None
def enemy_entities(p, radius):
    return [e for e in p.getWorld().getNearbyEntities(p.getLocation(), radius, radius, radius)
            if isinstance(e, LivingEntity) and not e.getUniqueId().equals(p.getUniqueId())]

def ability_shadow(p):
    if not check_cd(p, "shadow", u"«Лунная Тень»"): return
    tier = player_tier(p)
    duration = 5 if tier == 1 else 7
    add_effect(p, E_INVIS, duration * 20, 0)
    if tier >= 2: add_effect(p, E_SPEED, duration * 20, 0)
    if tier >= 3: shadow_strike[uid(p)] = tick() + duration * 20
    p.getWorld().spawnParticle(Particle.END_ROD, p.getLocation().add(0, 1, 0), 25, .35, .8, .35, .02)
    p.getWorld().playSound(p.getLocation(), Sound.ENTITY_ENDERMAN_AMBIENT, .7, 1.6)
    p.sendMessage(u"§8✦ Лунная Тень: §f" + str(duration) + u"§7 сек.")
    set_cd(p, "shadow", CD_SHADOW)

def ability_clones(p):
    if not check_cd(p, "clones", u"«Хроно-Двойники»"): return
    remembered = last_enemy.get(uid(p))
    target = None
    if remembered and remembered.get("until", 0) > tick():
        try: target = Bukkit.getEntity(JUUID.fromString(remembered.get("target")))
        except Exception: target = None
    if not isinstance(target, LivingEntity) or target.isDead() or not target.isValid() or target.getWorld() != p.getWorld():
        p.sendMessage(u"§7Сначала ударь противника: двойники атакуют именно последнюю поражённую цель.")
        return
    world = p.getWorld()
    for unused in range(2):
        loc = p.getLocation().clone().add(random.uniform(-2.0, 2.0), 0, random.uniform(-2.0, 2.0))
        clone = world.spawnEntity(loc, EntityType.ZOMBIE)
        if not isinstance(clone, Zombie): continue
        clone.setCustomName(u"§8Тень Луны")
        clone.setCustomNameVisible(False)
        clone.setAdult()
        clone.getPersistentDataContainer().set(KEY_CLONE, PersistentDataType.BYTE, JByte(1))
        clone.getPersistentDataContainer().set(KEY_CLONE_TARGET, PersistentDataType.STRING, uid(target))
        try:
            eq = clone.getEquipment()
            eq.setHelmet(ItemStack(Material.LEATHER_HELMET)); eq.setChestplate(ItemStack(Material.LEATHER_CHESTPLATE))
            eq.setLeggings(ItemStack(Material.LEATHER_LEGGINGS)); eq.setBoots(ItemStack(Material.LEATHER_BOOTS))
            eq.setItemInMainHand(ItemStack(Material.STONE_SWORD))
            eq.setHelmetDropChance(0.0); eq.setChestplateDropChance(0.0); eq.setLeggingsDropChance(0.0); eq.setBootsDropChance(0.0); eq.setItemInMainHandDropChance(0.0)
        except Exception: pass
        clone.setTarget(target)
        lifetime = random.randint(10, 14) * 20
        def remove_clone(entity=clone):
            try:
                if entity.isValid(): entity.remove()
            except Exception: pass
        scheduler.runTaskLater(remove_clone, lifetime)
    world.spawnParticle(Particle.PORTAL, p.getLocation().add(0, 1, 0), 45, .7, 1, .7, .08)
    world.playSound(p.getLocation(), Sound.ENTITY_ILLUSIONER_MIRROR_MOVE, .8, 1.2)
    set_cd(p, "clones", CD_CLONES)

ULT_EFFECTS = {u"slow": (E_SLOWNESS, 1, u"Замедление II"), u"weak": (E_WEAKNESS, 0, u"Слабость I"), u"nausea": (E_NAUSEA, 0, u"Тошнота"), u"dark": (E_DARKNESS, 0, u"Тьма"), u"fatigue": (E_MINING, 0, u"Утомление I")}
ULT_ALIASES = {u"замедление": u"slow", u"слабость": u"weak", u"тошнота": u"nausea", u"тьма": u"dark", u"утомление": u"fatigue"}
def ability_ultimate(p, args):
    if len(args) != 2:
        p.sendMessage(u"§7Использование: §f/luna ульт <slow|weak|nausea|dark|fatigue> <эффект>")
        return
    selected = []
    for raw in args:
        key = ULT_ALIASES.get(raw.lower(), raw.lower())
        if key not in ULT_EFFECTS or key in selected:
            p.sendMessage(u"§cВыбери два разных эффекта: §fslow, weak, nausea, dark, fatigue§c."); return
        selected.append(key)
    if not check_cd(p, "ult", u"«Лунный Парадокс»"): return
    for e in enemy_entities(p, 7.0):
        for key in selected:
            effect, amp, unused = ULT_EFFECTS[key]
            add_effect(e, effect, ULT_DURATION, amp)
    add_effect(p, E_STRENGTH, ULT_DURATION, 0); add_effect(p, E_SPEED, ULT_DURATION, 0); add_effect(p, E_RESISTANCE, ULT_DURATION, 0)
    owner_id = uid(p)
    expiry = tick() + ULT_DURATION
    ultimate_effects[owner_id] = expiry
    # The Bukkit duration is normally sufficient.  This cleanup is intentional
    # protection against an old/reloaded task leaving Luna's buffs permanent.
    def clear_ultimate():
        if ultimate_effects.get(owner_id) != expiry:
            return
        ultimate_effects.pop(owner_id, None)
        if not p.isOnline():
            return
        p.removePotionEffect(E_STRENGTH)
        p.removePotionEffect(E_SPEED)
        p.removePotionEffect(E_RESISTANCE)
    scheduler.runTaskLater(clear_ultimate, ULT_DURATION)
    p.getWorld().spawnParticle(Particle.REVERSE_PORTAL, p.getLocation(), 100, 3.5, 1.0, 3.5, .12)
    p.getWorld().playSound(p.getLocation(), Sound.ENTITY_ENDER_DRAGON_GROWL, .6, 1.7)
    p.sendMessage(u"§5§l✦ Лунный Парадокс — §f12§5 сек.")
    set_cd(p, "ult", CD_ULT)

def ability_rift(p):
    if not check_cd(p, "rift", u"«Лунный Разлом»"): return
    end = tick() + RIFT_DURATION
    p.sendMessage(u"§5✦ Лунный Разлом: §f8§7 сек.")
    def pulse():
        if not p.isOnline() or tick() >= end: return
        add_effect(p, E_SPEED, 30, 0)
        for e in enemy_entities(p, 7.0): add_effect(e, E_SLOWNESS, 30, 1)
        # DRAGON_BREATH requires extra particle data on Leaf/Paper 1.21;
        # END_ROD is visually appropriate and needs no data payload.
        p.getWorld().spawnParticle(Particle.END_ROD, p.getLocation(), 35, 3.5, .2, 3.5, .02)
        scheduler.runTaskLater(pulse, 20)
    pulse(); set_cd(p, "rift", CD_RIFT)

def on_damage_by(event):
    damager, victim = event.getDamager(), event.getEntity()
    if not isinstance(damager, Player) or not isinstance(victim, LivingEntity) or not is_luna(damager): return
    # The last enemy struck by Luna becomes the only valid target for her
    # Chrono-Doubles for a short time.
    last_enemy[uid(damager)] = {"target": uid(victim), "until": tick() + 15 * 20}
    expires = shadow_strike.get(uid(damager), 0)
    if expires > tick():
        event.setDamage(event.getDamage() * 1.25)
        damager.sendMessage(u"§5✦ Первый удар Лунной Тени: §f+25%§5 урона.")
    shadow_strike.pop(uid(damager), None)
def on_clone_target(event):
    entity, target = event.getEntity(), event.getTarget()
    try:
        pdc = entity.getPersistentDataContainer()
        if not pdc.has(KEY_CLONE, PersistentDataType.BYTE): return
        expected = pdc.get(KEY_CLONE_TARGET, PersistentDataType.STRING)
        if target is None or uid(target) != expected: event.setCancelled(True)
    except Exception: pass
def on_drop(event):
    if is_sword(event.getItemDrop().getItemStack()): event.setCancelled(True); event.getPlayer().sendMessage(u"§cХроно-Кинжал нельзя выбросить.")
def on_inventory(event):
    if is_sword(event.getCurrentItem()) or is_sword(event.getCursor()):
        holder = event.getInventory().getHolder()
        if holder is not None and not isinstance(holder, Player): event.setCancelled(True)

def cmd_luna(sender, label, args):
    if not isinstance(sender, Player) or not is_luna(sender):
        sender.sendMessage(u"§cТолько Луна может использовать эту команду."); return True
    if not args:
        sender.sendMessage(u"§7/luna <тень|двойники|разлом|ульт> [эффекты]"); return True
    if not has_sword(sender): sender.sendMessage(u"§cНужен Лунный Хроно-Кинжал."); return True
    ability = args[0].lower()
    if ability in (u"тень", u"shadow"): ability_shadow(sender)
    elif ability in (u"двойники", u"клоны", u"clones"): ability_clones(sender)
    elif ability in (u"разлом", u"rift"): ability_rift(sender)
    elif ability in (u"ульт", u"ультимейт", u"ult", u"paradox"): ability_ultimate(sender, args[1:])
    else: sender.sendMessage(u"§cНеизвестная способность.")
    return True
def kit_entry(player, args): give_kit(player, int(args[0]) if args and str(args[0]).isdigit() else 1)
def set_tier(player, tier):
    if tier < 1 or tier > 3: return False
    if not replace_sword(player, tier): give_kit(player, tier)
    return True

cmd_mgr.registerCommand(cmd_luna, "luna")
listener_mgr.registerListener(on_damage_by, EntityDamageByEntityEvent)
listener_mgr.registerListener(on_clone_target, EntityTargetLivingEntityEvent)
listener_mgr.registerListener(on_drop, PlayerDropItemEvent)
listener_mgr.registerListener(on_inventory, InventoryClickEvent)
props = System.getProperties()
reg = props.get("pyspigot.character_kits")
if reg is None: reg = HashMap(); props.put("pyspigot.character_kits", reg)
reg.put("luna", (kit_entry, u"Луна (хроно-кинжал [тир 1|2|3])"))
owners = props.get("character_owners")
if owners is None: owners = HashMap(); props.put("character_owners", owners)
owners.put("luna", list(LUNA_OWNERS))
tiers = props.get("character_tier_setters")
if tiers is None: tiers = HashMap(); props.put("character_tier_setters", tiers)
tiers.put("luna", set_tier)
Bukkit.getLogger().info("[luna] Loaded. Command: /luna")

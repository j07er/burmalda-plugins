# -*- coding: utf-8 -*-
# ============================================================================
# warfare.py — Военные механики: Дроны, Мины, Сапёры, ПВО
# PySpigot 0.9.1 (Jython 2.7) + Paper 1.21.11
#
# Команды:
#   /warfare give <scout|kamikaze|mine|detector|cutters|pvo> [игрок]
#   /warfare list            — список активных мин и ПВО
#   /warfare clear mines|pvo — снять все мины / демонтировать все ПВО
#   /warfare cleanup         — удалить осиротевшие сущности (манекены, остатки ПВО)
#   Алиас команды: /wf
#
# Предметы (CustomModelData, для ресурспака):
#   COMPASS 3001 — пульт дрона-разведчика      COMPASS 3002 — пульт камикадзе
#   POLISHED_BLACKSTONE_BUTTON 3010 — мина     GOLDEN_HOE 3020 — металлоискатель
#   SHEARS 3030 — сапёрные ножницы             ANVIL 3040 — станковое ПВО (пассивное)
#   BREEZE_ROD 3060 — ПЗРК «Игла» (активное ПВО)
#   Модели: ENDER_EYE 3101 (разведчик), TNT 3102 (камикадзе), SPYGLASS 3050 (турель)
#
# Требование: добавить "warfare" в CUSTOM_NAMESPACES скрипта soulbound.py
# (уже делается динамически при загрузке, но лучше продублировать).
# ============================================================================

import os
import io
import json
import shutil
import time

import pyspigot as ps

cmd_mgr      = ps.command_manager()      # функция
listener_mgr = ps.listener_manager()     # функция
scheduler    = ps.scheduler              # атрибут

from java.lang import System, Byte as JByte, Long as JLong, Math, Integer as JInteger
from java.util import UUID as JUUID, ArrayList, Random, Base64

from org.joml import Vector3f, Quaternionf

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, Location,
    GameMode, Color
)
from org.bukkit.block import BlockFace
from org.bukkit.attribute import Attribute
from org.bukkit.entity import (
    Player, LivingEntity, ArmorStand, Interaction,
    Snowball, BlockDisplay, AbstractVillager
)
from org.bukkit.event.player import (
    PlayerJoinEvent, PlayerQuitEvent, PlayerInteractEvent, PlayerMoveEvent,
    PlayerInteractEntityEvent, PlayerAnimationEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDismountEvent,
    EntityDeathEvent
)
from org.bukkit.event.block import BlockPlaceEvent, BlockBreakEvent
from org.bukkit.event.inventory import InventoryClickEvent, InventoryCloseEvent
from org.bukkit.event.block import Action
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.inventory.meta import SkullMeta
from org.bukkit.persistence import PersistentDataType
from org.bukkit.potion import PotionEffect
from org.bukkit.util import Vector, Transformation

# ---------------------------------------------------------------------------
# Константы и конфиг
# ---------------------------------------------------------------------------

LOG_PREFIX = "[warfare] "

ADMIN_NAMES = set([u"blueredtronce"])         # тест-админ (см. arena.test_mode)
FREE_CD_PLAYERS = set([u"blueredtronce", u"dramo_smarty"])    # без кулдаунов

DATA_DIR  = os.path.join("plugins", "PySpigot", "scripts", "data")
DATA_FILE = os.path.join(DATA_DIR, "warfare.json")

# NamespacedKey-ключи PDC (неймспейс "warfare" — занести в soulbound)
KEY_REMOTE_TYPE = NamespacedKey.fromString("warfare:remote_type")   # тип пульта
KEY_MINE_ITEM   = NamespacedKey.fromString("warfare:mine_item")     # предмет-мина
KEY_MINE_MARKER = NamespacedKey.fromString("warfare:mine_type")     # маркер мины
KEY_DUMMY_OWNER = NamespacedKey.fromString("warfare:dummy_owner")   # манекен -> владелец
KEY_TOOL        = NamespacedKey.fromString("warfare:tool")          # инструмент (детектор/ножницы)
KEY_PVO_KIT     = NamespacedKey.fromString("warfare:pvo_kit")       # предмет-установщик ПВО
KEY_PVO_SEAT    = NamespacedKey.fromString("warfare:pvo_seat")      # interaction-сиденье
KEY_PVO_DISPLAY = NamespacedKey.fromString("warfare:pvo_display")   # метка частей башни ПВО
KEY_SHELL       = NamespacedKey.fromString("warfare:shell")         # снаряд ПВО
KEY_CHARGES     = NamespacedKey.fromString("warfare:charges")       # заряды ПЗРК (integer)
KEY_RECOVERY_APPLIED = NamespacedKey.fromString("warfare:recovery_applied")

# CustomModelData предметов
CMD_SCOUT    = 3001
CMD_KAMIKAZE = 3002
CMD_MINE     = 3010
CMD_DETECTOR = 3020
CMD_CUTTERS  = 3030
CMD_PVO      = 3040
CMD_DRONE_SCOUT = 3101
CMD_DRONE_KAMIK = 3102
CMD_PVO_TURRET  = 3050

# Баланс дрона-разведчика
SCOUT_SCAN_RADIUS   = 30.0
SCOUT_GLOW_TICKS    = 200          # 10 сек
SCOUT_SCAN_CD_TICKS = 300          # 15 сек
DRONE_FLY_SPEED     = 0.12
DRONE_SCALE         = 0.5          # масштаб оператора дрона (атрибут scale)
DRONE_HITBOX_Y      = 0.63         # нижняя точка летающего хитбокса модели
                                   # (стойка 1.98 м: покрывает весь корпус)
DRONE_RETURN_SHIELD_TICKS = 60     # иммунитет оператора после выхода (3 сек)
DRONE_RANGE         = 150.0        # дальность управления: за ней связь рвётся
DRONE_WARN_RANGE    = 130.0        # с этой дистанции предупреждаем о слабом сигнале
DRONE_SOUND_INTERVAL_TICKS = 8     # частое перекрытие клипа убирает паузы в полёте

# Баланс камикадзе
KAMIKAZE_POWER      = 3.5          # визуальная/звуковая мощь взрыва (блоки не ломает)
KAMIKAZE_RADIUS     = 6.0
KAMIKAZE_DAMAGE     = 28.0
KAMIKAZE_HIT_RANGE  = 1.6          # хитбокс-столкновение с целью

# Баланс мины
MINE_POWER  = 3.0
MINE_RADIUS = 4.0
MINE_DAMAGE = 32.0
MINE_REVEAL_DIST  = 2.5   # детектор «открывает» мину ближе этой дистанции
MINE_REVEAL_TICKS = 40      # на сколько тиков мина становится видимой (2 c)
MINE_MARKER_DEPTH = 0.95    # насколько маркер утоплен под пол (мина на голове)

# Кирки всех тиров (COPPER_PICKAXE включится сам, если есть в версии)
PICKAXES = set()
for _n in ("WOODEN_PICKAXE", "STONE_PICKAXE", "COPPER_PICKAXE", "IRON_PICKAXE",
           "GOLDEN_PICKAXE", "DIAMOND_PICKAXE", "NETHERITE_PICKAXE"):
    _m = getattr(Material, _n, None)
    if _m is not None:
        PICKAXES.add(_m)

# Металлоискатель
DETECTOR_RADIUS = 10.0

# ПВО
PVO_SCAN_RADIUS   = 50.0
PVO_HIT_CHANCE    = 50             # шанс попадания автомата по дрону
PVO_MANUAL_CD     = 20             # 1 сек — КД ручного выстрела из станка
PVO_AUTO_CD       = 60             # 3 сек — задержка между автозапусками перехватчиков
PVO_SHELL_SPEED   = 8.0            # увеличено (было 6.0) — стабильнее перехват
PVO_SHELL_DAMAGE  = 12.0
PVO_SHELL_LIFE    = 60             # тиков жизни снаряда
PVO_HEAD_H        = 1.75           # ось башни; станина начинается над наковальней
PVO_MODEL_REVISION = 3             # пересобрать старые установки после reload

# Автоматический режим СТАНКА ПВО: True — сам сканирует небо и стреляет,
# False — только ручной огонь стрелка по ЛКМ. (Выключен по запросу.)
AUTO_PVO_ENABLED = False

# АИМ-АССИСТА НЕТ: ни автозахвата, ни самонаведения, ни взрывателя близости.
# Засчитывается ТОЛЬКО прямое попадание снаряда в корпус дрона: сфера этого
# радиуса вокруг силуэта модели (ноги/плечи/голова). 0.55 ≈ габарит тела.
SHELL_HIT_RADIUS  = 0.55

# ПЗРК (активное, ручное ПВО — предмет в руке)
PZRK_CD_TICKS    = 80              # 4 сек между выстрелами
PZRK_MAX_CHARGES = 25              # зарядов в одном ПЗРК
CMD_PZRK         = 3060

# Миниигра обезвреживания: интервал шага ползунка, тики (больше = медленнее/легче)
# Выбор игрока: "чуть легче" — 3 тика (~x0.66 от исходной скорости)
MINIGAME_STEP_TICKS = 3

# Эффекты через Registry (L6)
E_INVIS = Registry.EFFECT.get(NamespacedKey.minecraft("invisibility"))
E_GLOW  = Registry.EFFECT.get(NamespacedKey.minecraft("glowing"))

# Атрибут масштаба: в 1.21+ поле называется SCALE (раньше GENERIC_SCALE)
A_SCALE = getattr(Attribute, "SCALE", None)
if A_SCALE is None:
    A_SCALE = getattr(Attribute, "GENERIC_SCALE", None)

# Партиклы с фоллбэком по именам (переименования в 1.20.5+)
def _particle(*names):
    for n in names:
        p = getattr(Particle, n, None)
        if p is not None:
            return p
    return getattr(Particle, "FLAME")

P_DUST   = _particle("DUST", "REDSTONE")
P_BOOM   = _particle("SONIC_BOOM", "EXPLOSION_EMITTER", "EXPLOSION_LARGE")
P_TRACER = _particle("FLAME")
P_FLASH  = _particle("END_ROD", "FLAME")

DustOptions = Particle.DustOptions
_rand = Random()

# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def uid(e):
    return e.getUniqueId().toString()

def now_tick():
    return long(System.currentTimeMillis() / 50)

def _to_unicode(s):
    if s is None:
        return u""
    if isinstance(s, unicode):
        return s
    try:
        return unicode(s, "utf-8", "replace")
    except Exception:
        try:
            return unicode(s)
        except Exception:
            return u""

def _norm(s):
    return _to_unicode(s).strip().lower()

def java_list(it):
    lst = ArrayList()
    for x in it:
        lst.add(x)
    return lst

def _ascii_safe(s):
    # нерусские символы -> '?' (Windows-консоль cp866, L14)
    if not isinstance(s, str):
        try:
            s = unicode(s)
        except Exception:
            return "?"
    try:
        return s.encode("ascii", "replace")
    except Exception:
        return "?"

def _log(msg):
    Bukkit.getLogger().info(LOG_PREFIX + _ascii_safe(msg))

def _warn(msg):
    Bukkit.getLogger().warning(LOG_PREFIX + _ascii_safe(msg))

def _is_admin(sender):
    if not isinstance(sender, Player):
        return True  # консоль
    return sender.getName().lower() in ADMIN_NAMES or sender.isOp()

def is_silenced_by_demiurg(player):
    # Проверка заглушения Демиургом (активные действия запрещены)
    try:
        silenced = System.getProperties().get("demiurg.silenced_uuids")
        if silenced is None:
            return False
        return silenced.contains(uid(player))
    except Exception:
        return False

def same_team(a, b):
    # Союзники = одна scoreboard-команда. Без команд — все чужие.
    try:
        sb = Bukkit.getScoreboardManager().getMainScoreboard()
        ta = sb.getEntryTeam(a.getName())
        tb = sb.getEntryTeam(b.getName())
        if ta is None or tb is None:
            return False
        return ta.getName() == tb.getName()
    except Exception:
        return False

def _cmd_of(item):
    # CustomModelData предмета или None
    try:
        if item is None:
            return None
        m = item.getItemMeta()
        if m is None or not m.hasCustomModelData():
            return None
        return int(m.getCustomModelData())
    except Exception:
        return None

def _pdc_str(pdc_holder, key):
    try:
        pdc = pdc_holder.getPersistentDataContainer()
        if pdc.has(key, PersistentDataType.STRING):
            return _to_unicode(pdc.get(key, PersistentDataType.STRING))
    except Exception:
        pass
    return None

def _entity_by_uid(s):
    # Резолв сущности по строке UUID
    if s is None:
        return None
    try:
        return Bukkit.getEntity(JUUID.fromString(s))
    except Exception:
        return None

def _make_item(mat, cmd, name, lore):
    # Фабрика кастомных предметов (имя/лор/CustomModelData).
    # cmd=None или 0 — CustomModelData не задаём (GUI-панели).
    it = ItemStack(mat, 1)
    m = it.getItemMeta()
    m.setDisplayName(name)
    if lore:
        m.setLore(java_list(lore))
    if cmd:
        m.setCustomModelData(cmd)
    it.setItemMeta(m)
    return it

def _give_or_drop(player, item):
    left = player.getInventory().addItem(item)
    if left is not None and not left.isEmpty():
        for leftover in left.values():
            player.getWorld().dropItemNaturally(player.getLocation(), leftover)

def _explode(world, x, y, z, power, source, set_fire=False, break_blocks=False):
    # Взрыв без разрушения рельефа; 5-арг версия с fallback на 4-арг
    loc = Location(world, x, y, z)
    try:
        if source is not None:
            world.createExplosion(loc, float(power), set_fire, break_blocks, source)
        else:
            world.createExplosion(loc, float(power), set_fire, break_blocks)
    except TypeError:
        world.createExplosion(loc, float(power), set_fire, break_blocks)

def _play(player, sound, vol, pitch):
    try:
        player.playSound(player.getLocation(), sound, float(vol), float(pitch))
    except Exception:
        pass

def _play_at(world, x, y, z, sound, vol, pitch):
    try:
        world.playSound(Location(world, x, y, z), sound, float(vol), float(pitch))
    except Exception:
        pass

def _consume_one(player, item):
    # расходники: уменьшить стак предмета в главной руке на 1
    try:
        if player.getGameMode() == GameMode.CREATIVE:
            return
        amt = item.getAmount()
        if amt <= 1:
            player.getInventory().setItemInMainHand(None)
        else:
            item.setAmount(amt - 1)
    except Exception:
        pass

def _pdc_int(pdc_holder, key):
    try:
        pdc = pdc_holder.getPersistentDataContainer()
        if pdc.has(key, PersistentDataType.INTEGER):
            return int(pdc.get(key, PersistentDataType.INTEGER))
    except Exception:
        pass
    return None

def _is_protected(ent):
    # Жители (и странствующие торговцы) — ценная инфраструктура:
    # урон от взрывов любого происхождения им не наносится.
    return isinstance(ent, AbstractVillager)

def _drone_aim(player):
    # Точка прицеливания по дрону: ЦЕНТР КОМПОЗИТНОЙ МОДЕЛИ,
    # а не невидимое тело оператора (модель парит ~на 1.6 м выше ног).
    l = player.getLocation()
    return Location(l.getWorld(), l.getX(), l.getY() + 1.62, l.getZ())

# ---------------------------------------------------------------------------
# Кулдауны
# ---------------------------------------------------------------------------

cooldowns = {}   # uid -> {name: end_tick}

def check_cd(player, name, label=None):
    if player.getName().lower() in FREE_CD_PLAYERS:
        return True
    d = cooldowns.get(uid(player))
    if d is None:
        return True
    end = d.get(name, 0)
    if now_tick() < end:
        if label:
            rem = (end - now_tick()) / 20.0
            player.sendMessage(u"§7Способность " + label + u" §7перезаряжается: §c%.1f §7сек." % rem)
        return False
    return True

def set_cd(player, name, ticks):
    if player.getName().lower() in FREE_CD_PLAYERS:
        return
    u = uid(player)
    if u not in cooldowns:
        cooldowns[u] = {}
    cooldowns[u][name] = now_tick() + ticks

# ---------------------------------------------------------------------------
# JSON-хранилище (мины и ПВО переживают рестарт)
# ---------------------------------------------------------------------------

state = {"mines": {}, "pvo": {}, "operator_recovery": {}, "combat_log": []}
COMBAT_LOG_LIMIT = 2000
EFFECT_BUDGET_NORMAL = 240
EFFECT_BUDGET_LOW = 80
EFFECT_BUDGET_CRITICAL = 20
_effect_budget = {"tick": -1, "used": 0, "limit": EFFECT_BUDGET_NORMAL}
_combat_log_dirty = [False]

def _load():
    global state
    try:
        if not os.path.exists(DATA_FILE) and not os.path.exists(DATA_FILE + ".bak"):
            state = {"mines": {}, "pvo": {}, "operator_recovery": {}, "combat_log": []}
            return
        loaded = None
        for candidate in [DATA_FILE, DATA_FILE + ".bak"]:
            if not os.path.exists(candidate):
                continue
            try:
                f = io.open(candidate, "r", encoding="utf-8")
                try:
                    raw = f.read()
                finally:
                    f.close()
                if raw.strip():
                    loaded = json.loads(raw)
                    break
            except Exception as ex:
                _warn("load candidate: " + str(ex))
        if loaded is None:
            raise IOError("warfare primary and backup storage are unreadable")
        state = loaded
        state.setdefault("mines", {})
        state.setdefault("pvo", {})
        state.setdefault("operator_recovery", {})
        state.setdefault("combat_log", [])
        for entry in state["mines"].values():
            entry.setdefault("owner_uuid", u"")
            entry.setdefault("owner_name", entry.get("owner", u"Unknown"))
        for entry in state["pvo"].values():
            entry.setdefault("owner_uuid", u"")
            entry.setdefault("owner_name", u"Unknown")
    except Exception as ex:
        _warn("load: " + str(ex))
        raise

def _save():
    try:
        try:
            os.makedirs(DATA_DIR)
        except Exception:
            pass
        text = json.dumps(state, ensure_ascii=False, indent=2)
        if isinstance(text, str):
            text = text.decode("utf-8", "replace")
        temp_file = DATA_FILE + ".tmp"
        if os.path.exists(DATA_FILE):
            try:
                shutil.copy2(DATA_FILE, DATA_FILE + ".bak")
            except Exception:
                pass
        f = io.open(temp_file, "w", encoding="utf-8")
        try:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        finally:
            f.close()
        try:
            from java.nio.file import Files, Paths, StandardCopyOption
            Files.move(Paths.get(temp_file), Paths.get(DATA_FILE), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        except Exception:
            if os.path.exists(DATA_FILE):
                os.remove(DATA_FILE)
            os.rename(temp_file, DATA_FILE)
        return True
    except Exception as ex:
        _warn("save: " + str(ex))
        return False

def _loc_key(world_name, x, y, z):
    return u"%s:%d:%d:%d" % (world_name, x, y, z)


def _current_tps():
    try:
        values = Bukkit.getServer().getTPS()
        return float(values[0]) if values and len(values) > 0 else 20.0
    except Exception:
        return 20.0


def _effect_limit():
    tps = _current_tps()
    if tps < 15.0:
        return EFFECT_BUDGET_CRITICAL
    if tps < 18.0:
        return EFFECT_BUDGET_LOW
    return EFFECT_BUDGET_NORMAL


def _spawn_particle(world, particle, *args):
    tick = now_tick()
    if _effect_budget["tick"] != tick:
        _effect_budget["tick"] = tick
        _effect_budget["used"] = 0
        _effect_budget["limit"] = _effect_limit()
    count = 1
    try:
        if len(args) >= 2 and hasattr(args[0], "getWorld"):
            count = max(1, int(args[1]))
        elif len(args) >= 4:
            count = max(1, int(args[3]))
    except Exception:
        count = 1
    if _effect_budget["used"] + count > _effect_budget["limit"]:
        return False
    _effect_budget["used"] += count
    try:
        world.spawnParticle(particle, *args)
        return True
    except Exception:
        return False


def _combat_event(kind, actor_uuid=None, actor_name=None, target_uuid=None, target_name=None,
                  world=None, x=None, y=None, z=None, details=None):
    entry = {"time": int(time.time()), "kind": str(kind), "actor_uuid": actor_uuid,
             "actor_name": _to_unicode(actor_name), "target_uuid": target_uuid,
             "target_name": _to_unicode(target_name), "world": world, "x": x, "y": y, "z": z,
             "details": details if isinstance(details, dict) else {}}
    state.setdefault("combat_log", []).append(entry)
    if len(state["combat_log"]) > COMBAT_LOG_LIMIT:
        del state["combat_log"][:-COMBAT_LOG_LIMIT]
    _combat_log_dirty[0] = True


def _item_to_b64(item):
    if item is None:
        return None
    try:
        return str(Base64.getEncoder().encodeToString(item.serializeAsBytes()))
    except Exception:
        return None


def _item_from_b64(encoded):
    if not encoded:
        return None
    try:
        return ItemStack.deserializeBytes(Base64.getDecoder().decode(str(encoded)))
    except Exception:
        return None


def _session_recovery_record(player, sess):
    armor = []
    for item in (sess.get("saved_armor") or []):
        armor.append(_item_to_b64(item))
    recovery_id = sess.get("recovery_id")
    if not recovery_id:
        recovery_id = str(JUUID.randomUUID())
        sess["recovery_id"] = recovery_id
    return {"player_uuid": uid(player), "player_name": player.getName(), "type": sess.get("type"),
            "recovery_id": recovery_id,
            "return": list(sess.get("return", [])), "prev_gm": sess.get("prev_gm", "SURVIVAL"),
            "prev_fly": bool(sess.get("prev_fly", False)),
            "prev_flying": bool(sess.get("prev_flying", False)),
            "prev_fly_speed": float(sess.get("prev_fly_speed", 0.1)),
            "prev_scale": float(sess.get("prev_scale", 1.0)), "saved_armor": armor,
            "prev_invisibility": sess.get("prev_invisibility"),
            "dummy_uid": sess.get("dummy_uid"), "hitbox_uid": sess.get("hitbox_uid"),
            "display_uid": sess.get("display_uid"), "model_uids": list(sess.get("model_uids", [])),
            "created_at": int(time.time())}


def _remove_recovery_entities(record):
    for key in ["dummy_uid", "hitbox_uid", "display_uid"]:
        ent = _entity_by_uid(record.get(key))
        if ent is not None:
            try:
                ent.remove()
            except Exception:
                pass
    for entity_uuid in record.get("model_uids", []):
        ent = _entity_by_uid(entity_uuid)
        if ent is not None:
            try:
                ent.remove()
            except Exception:
                pass


def _restore_operator_record(player, record, notify=True):
    if player is None or not player.isOnline():
        return False
    try:
        recovery_id = record.get("recovery_id")
        if not recovery_id:
            recovery_id = str(JUUID.randomUUID())
            record["recovery_id"] = recovery_id
            # A legacy record needs a durable id before inventory restoration,
            # otherwise a failed final save could duplicate restored armour.
            if not _save():
                return False
        pdc = player.getPersistentDataContainer()
        already_applied = (_pdc_str(player, KEY_RECOVERY_APPLIED) == recovery_id)
        _remove_recovery_entities(record)
        player.removePotionEffect(E_INVIS)
        previous_invis = record.get("prev_invisibility")
        if isinstance(previous_invis, dict):
            player.addPotionEffect(PotionEffect(E_INVIS, int(previous_invis.get("duration", 1)),
                                                int(previous_invis.get("amplifier", 0)),
                                                bool(previous_invis.get("ambient", False)),
                                                bool(previous_invis.get("particles", True)),
                                                bool(previous_invis.get("icon", True))))
        try:
            player.setFlying(False)
        except Exception:
            pass
        player.setGameMode(GameMode.valueOf(record.get("prev_gm", "SURVIVAL")))
        player.setAllowFlight(bool(record.get("prev_fly", False)))
        if record.get("prev_fly", False) and record.get("prev_flying", False):
            player.setFlying(True)
        player.setFlySpeed(float(record.get("prev_fly_speed", 0.1)))
        if A_SCALE is not None:
            attr = player.getAttribute(A_SCALE)
            if attr is not None:
                attr.setBaseValue(float(record.get("prev_scale", 1.0)))
        ret = record.get("return", [])
        if len(ret) >= 4:
            world = Bukkit.getWorld(ret[0])
            if world is not None:
                player.teleport(Location(world, float(ret[1]), float(ret[2]), float(ret[3])))
                player.setVelocity(Vector(0.0, 0.0, 0.0))
        armor = [_item_from_b64(value) for value in record.get("saved_armor", [])]
        if armor and not already_applied:
            inv = player.getInventory()
            setters = (inv.setBoots, inv.setLeggings, inv.setChestplate, inv.setHelmet)
            getters = (inv.getBoots, inv.getLeggings, inv.getChestplate, inv.getHelmet)
            for index in range(min(4, len(armor))):
                piece = armor[index]
                if piece is None:
                    continue
                current = getters[index]()
                if current is None or current.getType() == Material.AIR:
                    setters[index](piece)
                else:
                    _give_or_drop(player, piece)
            pdc.set(KEY_RECOVERY_APPLIED, PersistentDataType.STRING, recovery_id)
        state.setdefault("operator_recovery", {}).pop(uid(player), None)
        if not _save():
            state.setdefault("operator_recovery", {})[uid(player)] = record
            _warn("operator restored, but recovery record could not be closed: " + uid(player))
            return True
        try:
            pdc.remove(KEY_RECOVERY_APPLIED)
        except Exception:
            pass
        if notify:
            player.sendMessage(u"§8§l[Warfare] §aСостояние оператора восстановлено после выхода/перезагрузки.")
        return True
    except Exception as ex:
        _warn("operator recovery: " + str(ex))
        return False

# ============================================================================
# 1. DroneManager — управляемые дроны (разведчик и камикадзе)
# ============================================================================

class DroneManager(object):
    """
    Сессия дрона:
      uid -> {
        "type": u"scout" | u"kamikaze",
        "dummy_uid": str,          # ArmorStand-манекен (остаётся на земле)
        "hitbox_uid": str,         # невидимый летающий хитбокс модели дрона
        "display_uid": str,        # legacy-поле (модель теперь композитная)
        "return": (world_name, x, y, z),
        "prev_gm": str,
        "prev_fly": bool,
        "prev_fly_speed": float,
      }
    """

    REMOTE_NAMES = {
        u"scout":    u"§b§lПульт дрона-разведчика",
        u"kamikaze": u"§c§lПульт дрона-камикадзе",
    }

    # Композитная модель «Шахеда» (камикадзе): узкий фюзеляж, ступенчатое
    # дельта-крыло, утопленный заряд, два киля и толкающий винт.
    # Формат: (материал, ox, oy, oz, sx, sy, sz, rotY°, rotZ°, spin)
    SHAHED_PARTS = [
        # центральная секция и трёхступенчатый нос
        ("SMOOTH_QUARTZ",  0.00, 1.58,  0.02, 0.38, 0.34, 2.35,   0.0,   0.0, 0),
        ("LIGHT_GRAY_CONCRETE", 0.00, 1.76, -0.08, 0.23, 0.10, 1.55, 0.0, 0.0, 0),
        ("LIGHT_GRAY_CONCRETE", 0.00, 1.58,  1.30, 0.30, 0.28, 0.34, 0.0, 0.0, 0),
        ("GRAY_CONCRETE",  0.00, 1.58,  1.51, 0.21, 0.21, 0.19,   0.0,   0.0, 0),
        ("BLACK_CONCRETE", 0.00, 1.58,  1.64, 0.11, 0.11, 0.09,   0.0,   0.0, 0),
        # заряд виден снизу, но не превращает весь аппарат в куб TNT
        ("TNT",            0.00, 1.38,  0.23, 0.28, 0.15, 0.72,   0.0,   0.0, 0),
        # ступени дельта-крыла: хорда уменьшается к законцовкам
        ("SMOOTH_QUARTZ", -0.36, 1.57, -0.10, 0.46, 0.07, 1.78,   0.0, 0.0, 0),
        ("SMOOTH_QUARTZ",  0.36, 1.57, -0.10, 0.46, 0.07, 1.78,   0.0, 0.0, 0),
        ("SMOOTH_QUARTZ", -0.79, 1.57, -0.34, 0.43, 0.07, 1.30,   0.0, 0.0, 0),
        ("SMOOTH_QUARTZ",  0.79, 1.57, -0.34, 0.43, 0.07, 1.30,   0.0, 0.0, 0),
        ("SMOOTH_QUARTZ", -1.18, 1.57, -0.58, 0.36, 0.07, 0.82,   0.0, 0.0, 0),
        ("SMOOTH_QUARTZ",  1.18, 1.57, -0.58, 0.36, 0.07, 0.82,   0.0, 0.0, 0),
        # тёмная передняя кромка связывает ступени в цельный силуэт
        ("LIGHT_GRAY_CONCRETE", -0.78, 1.61, -0.31, 0.09, 0.08, 1.78,  35.0, 0.0, 0),
        ("LIGHT_GRAY_CONCRETE",  0.78, 1.61, -0.31, 0.09, 0.08, 1.78, -35.0, 0.0, 0),
        # хвостовое оперение, мотор, винт и антенна
        ("SMOOTH_QUARTZ", -0.70, 1.76, -0.88, 0.07, 0.38, 0.45,   0.0,  22.0, 0),
        ("SMOOTH_QUARTZ",  0.70, 1.76, -0.88, 0.07, 0.38, 0.45,   0.0, -22.0, 0),
        ("GRAY_CONCRETE",  0.00, 1.58, -1.30, 0.34, 0.31, 0.28,   0.0,   0.0, 0),
        ("BLACK_CONCRETE", 0.00, 1.58, -1.49, 1.16, 0.07, 0.05,   0.0,   0.0, 0),
        ("BLACK_CONCRETE", 0.00, 1.58, -1.49, 0.07, 1.16, 0.05,   0.0,   0.0, 0),
        ("LIGHT_GRAY_CONCRETE", 0.00, 1.98, -0.52, 0.05, 0.38, 0.05, 0.0, 0.0, 0),
    ]

    # Разведчик: обтекаемый белый корпус, синяя оптика, X-рама, четыре тёмных
    # двигателя и полупрозрачные кресты винтов. Деталей достаточно для силуэта,
    # но без декоративной россыпи сущностей, дорогой для тика сервера.
    QUAD_COMMON = [
        # центральная капсула и верхний сигнальный канал
        ("SMOOTH_QUARTZ",  0.00, 1.63,  0.02, 0.56, 0.36, 1.25,    0.0, 0.0, 0),
        ("LIGHT_GRAY_CONCRETE", 0.00, 1.47, -0.04, 0.42, 0.16, 0.92, 0.0, 0.0, 0),
        ("RED_CONCRETE",   0.00, 1.84, -0.18, 0.09, 0.06, 0.58,    0.0, 0.0, 0),
        ("GRAY_CONCRETE",  0.00, 1.63, -0.71, 0.40, 0.27, 0.27,    0.0, 0.0, 0),
        # четыре силовых луча
        ("IRON_BLOCK",    -0.46, 1.64,  0.46, 0.12, 0.10, 1.18,   45.0, 0.0, 0),
        ("IRON_BLOCK",     0.46, 1.64,  0.46, 0.12, 0.10, 1.18,  -45.0, 0.0, 0),
        ("IRON_BLOCK",    -0.46, 1.64, -0.46, 0.12, 0.10, 1.18,  135.0, 0.0, 0),
        ("IRON_BLOCK",     0.46, 1.64, -0.46, 0.12, 0.10, 1.18, -135.0, 0.0, 0),
        # моторы
        ("POLISHED_DEEPSLATE", -0.91, 1.65,  0.91, 0.30, 0.28, 0.30, 0.0, 0.0, 0),
        ("POLISHED_DEEPSLATE",  0.91, 1.65,  0.91, 0.30, 0.28, 0.30, 0.0, 0.0, 0),
        ("POLISHED_DEEPSLATE", -0.91, 1.65, -0.91, 0.30, 0.28, 0.30, 0.0, 0.0, 0),
        ("POLISHED_DEEPSLATE",  0.91, 1.65, -0.91, 0.30, 0.28, 0.30, 0.0, 0.0, 0),
        # полупрозрачные лопасти дают ощущение вращения без мерцания анимации
        ("LIGHT_GRAY_STAINED_GLASS", -0.91, 1.91,  0.91, 1.08, 0.035, 0.12,  45.0, 0.0, 0),
        ("LIGHT_GRAY_STAINED_GLASS", -0.91, 1.91,  0.91, 1.08, 0.035, 0.12, -45.0, 0.0, 0),
        ("LIGHT_GRAY_STAINED_GLASS",  0.91, 1.91,  0.91, 1.08, 0.035, 0.12,  45.0, 0.0, 0),
        ("LIGHT_GRAY_STAINED_GLASS",  0.91, 1.91,  0.91, 1.08, 0.035, 0.12, -45.0, 0.0, 0),
        ("LIGHT_GRAY_STAINED_GLASS", -0.91, 1.91, -0.91, 1.08, 0.035, 0.12,  45.0, 0.0, 0),
        ("LIGHT_GRAY_STAINED_GLASS", -0.91, 1.91, -0.91, 1.08, 0.035, 0.12, -45.0, 0.0, 0),
        ("LIGHT_GRAY_STAINED_GLASS",  0.91, 1.91, -0.91, 1.08, 0.035, 0.12,  45.0, 0.0, 0),
        ("LIGHT_GRAY_STAINED_GLASS",  0.91, 1.91, -0.91, 1.08, 0.035, 0.12, -45.0, 0.0, 0),
        ("LIGHT_GRAY_CONCRETE", 0.00, 2.00, -0.42, 0.045, 0.35, 0.045, 0.0, 0.0, 0),
    ]

    # Синяя оптическая турель и тёмная линза на носу.
    SCOUT_NOSE = [
        ("BLUE_STAINED_GLASS", 0.0, 1.62, 0.72, 0.36, 0.28, 0.24, 0.0, 0.0, 0),
        ("BLACK_CONCRETE", 0.0, 1.62, 0.87, 0.17, 0.15, 0.07, 0.0, 0.0, 0),
    ]

    # Точки контактного теста снарядов ПВО по ВИДИМЫМ частям модели (локальные,
    # поворачиваются по yaw как части). Разведчик: корпус + 4 гондолы/ротора.
    # «Шахед»: нос/центр/корма + консоли крыльев. Радиус — SHELL_HIT_RADIUS.
    HIT_SAMPLES = {
        u"scout":    [(0.0, 1.68, 0.0), (0.0, 1.62, 0.78),
                      (-0.91, 1.72, 0.91), (0.91, 1.72, 0.91),
                      (-0.91, 1.72, -0.91), (0.91, 1.72, -0.91)],
        u"kamikaze": [(0.0, 1.58, 1.45), (0.0, 1.58, 0.45),
                      (0.0, 1.58, -0.65), (0.0, 1.58, -1.35),
                      (-0.72, 1.60, -0.30), (0.72, 1.60, -0.30),
                      (-1.18, 1.60, -0.62), (1.18, 1.60, -0.62)],
    }

    def hit_test_points(self, player):
        # Мировые точки силуэта модели дрона (с учётом yaw) для теста
        # попадания снарядов. Пустой список — у игрока нет активного дрона.
        s = self.sessions.get(uid(player))
        if s is None:
            return []
        samples = self.HIT_SAMPLES.get(s["type"], [(0.0, 1.62, 0.0)])
        base = player.getLocation()
        rad = Math.toRadians(base.getYaw())
        cs = Math.cos(rad)
        sn = Math.sin(rad)
        w = base.getWorld()
        out = []
        for (ox, oy, oz) in samples:
            out.append(Location(w,
                                base.getX() + ox * cs - oz * sn,
                                base.getY() + oy,
                                base.getZ() + ox * sn + oz * cs))
        return out

    def __init__(self):
        self.sessions = {}
        self.recent_booms = []   # недавние взрывы камикадзе (защита своих)
        self.return_shield = {}  # uid -> тик конца иммунитета после выхода

    # --- предметы ---------------------------------------------------------

    def make_remote(self, drone_type):
        if drone_type == u"scout":
            it = _make_item(Material.COMPASS, CMD_SCOUT, self.REMOTE_NAMES[drone_type], [
                u"§7ПКМ §7— запуск дрона и выход",
                u"§7ЛКМ §7— сканирование (радиус §f30§7)",
                u"§7Подсвечивает врагов на §f10 §7сек (КД 15 сек)",
                u"§8Расходник: тратится при запуске.",
                u"§8Дальность связи: 150 м.",
            ])
        else:
            it = _make_item(Material.COMPASS, CMD_KAMIKAZE, self.REMOTE_NAMES[drone_type], [
                u"§7ПКМ §7— запуск дрона и выход",
                u"§7ЛКМ §7или столкновение с целью — детонация",
                u"§8Расходник: тратится при запуске.",
                u"§8Дальность связи: 150 м.",
            ])
        m = it.getItemMeta()
        m.getPersistentDataContainer().set(KEY_REMOTE_TYPE, PersistentDataType.STRING, drone_type)
        it.setItemMeta(m)
        return it

    def remote_type_of(self, item):
        if item is None:
            return None
        m = item.getItemMeta()
        if m is None:
            return None
        t = _pdc_str(m, KEY_REMOTE_TYPE)
        if t in (u"scout", u"kamikaze"):
            return t
        return None

    # --- запуск -----------------------------------------------------------

    def launch(self, player, drone_type, item=None):
        u = uid(player)
        if u in self.sessions:
            return
        if is_silenced_by_demiurg(player):
            player.sendMessage(u"§5§oНеведомая сила глушит радиосигнал...")
            return
        world = player.getWorld()
        loc = player.getLocation()

        # Манекен на месте оператора
        dummy = world.spawn(loc, ArmorStand)
        dummy.setArms(True)
        dummy.setBasePlate(False)
        dummy.setGravity(False)
        dummy.setSilent(True)
        dummy.setCustomName(u"§7" + player.getName())
        dummy.setCustomNameVisible(True)
        dummy.getPersistentDataContainer().set(
            KEY_DUMMY_OWNER, PersistentDataType.STRING, player.getName())
        # манекен нельзя грабить: запрет на снятие/установку экипировки
        try:
            dummy.addDisabledSlots(EquipmentSlot.HEAD, EquipmentSlot.CHEST,
                                   EquipmentSlot.LEGS, EquipmentSlot.FEET,
                                   EquipmentSlot.HAND, EquipmentSlot.OFF_HAND)
        except Exception:
            pass

        # Голова игрока на манекен (SkullMeta + PlayerProfile)
        head = ItemStack(Material.PLAYER_HEAD, 1)
        skm = head.getItemMeta()
        try:
            skm.setPlayerProfile(player.getPlayerProfile())
        except Exception:
            try:
                skm.setOwningPlayer(player)
            except Exception:
                pass
        head.setItemMeta(skm)
        eq = dummy.getEquipment()
        eq.setHelmet(head)
        peq = player.getInventory()
        for getter, setter in (
            (peq.getChestplate, eq.setChestplate),
            (peq.getLeggings,   eq.setLeggings),
            (peq.getBoots,      eq.setBoots),
        ):
            part = getter()
            if part is not None:
                setter(part.clone())

        # Модель дрона: квадрокоптер из BlockDisplay'ов (QUAD_COMMON + нос
        # по типу дрона). Части НЕ пассажиры (иначе складываются в столб) —
        # летят за игроком через tick_models с интерполяцией teleportDuration.
        display = None
        model_uids = []
        model_parts = {}
        if drone_type == u"scout":
            parts_def = list(self.QUAD_COMMON) + list(self.SCOUT_NOSE)
        else:
            parts_def = list(self.SHAHED_PARTS)
        transform_error_logged = False
        for (mat_name, ox, oy, oz, sx, sy, sz, ry, rz, spin) in parts_def:
            mat = getattr(Material, mat_name, None)
            if mat is None:
                continue
            part = world.spawn(loc.clone().add(0.0, oy, 0.0), BlockDisplay)
            part.setBlock(Bukkit.createBlockData(mat))
            try:
                q = Quaternionf()
                if ry != 0.0:
                    q.rotateY(Math.toRadians(ry))
                if rz != 0.0:
                    q.rotateZ(Math.toRadians(rz))
                # центровка части: сдвиг = -(R * scale/2), поворот вокруг центра
                half = Vector3f(float(sx) / 2.0, float(sy) / 2.0, float(sz) / 2.0)
                q.transform(half).negate()
                t = Transformation(half, q,
                                   Vector3f(float(sx), float(sy), float(sz)),
                                   Quaternionf())
                part.setTransformation(t)
            except Exception as ex:
                part.remove()
                if not transform_error_logged:
                    _warn("drone model transformation: " + str(ex))
                    transform_error_logged = True
                continue
            try:
                part.setTeleportDuration(2)   # 10 визуальных кадров/с с интерполяцией
            except Exception:
                pass
            part.getPersistentDataContainer().set(
                KEY_DUMMY_OWNER, PersistentDataType.STRING, player.getName())
            model_uids.append(uid(part))
            model_parts[uid(part)] = (ox, oy, oz, spin)

        # ЛЕТАЮЩИЙ ХИТБОКС ДРОНА: невидимая стойка в центре композитной
        # модели. Без неё попадание засчитывалось лишь по невидимому телу
        # оператора (на ~1.6 м НИЖЕ видимой модели) — по дрону было почти
        # невозможно попасть. Урон по стойке = урон по дрону
        # (см. handle_hitbox_damage). Стойка не ломается (урон отменяется).
        hitbox = world.spawn(loc.clone().add(0.0, DRONE_HITBOX_Y, 0.0),
                             ArmorStand)
        hitbox.setInvisible(True)
        hitbox.setGravity(False)
        hitbox.setSilent(True)
        try:
            hitbox.setTeleportDuration(3)
        except Exception:
            pass
        hitbox.getPersistentDataContainer().set(
            KEY_DUMMY_OWNER, PersistentDataType.STRING, player.getName())

        # Состояние оператора
        prev_gm  = player.getGameMode().name()
        prev_fly = bool(player.getAllowFlight())
        prev_flying = bool(player.isFlying())
        prev_fs  = float(player.getFlySpeed())
        prev_scale = 1.0
        previous_invis = None
        try:
            old_effect = player.getPotionEffect(E_INVIS)
            if old_effect is not None:
                previous_invis = {"duration": int(old_effect.getDuration()),
                                  "amplifier": int(old_effect.getAmplifier()),
                                  "ambient": bool(old_effect.isAmbient()),
                                  "particles": bool(old_effect.hasParticles()),
                                  "icon": bool(old_effect.hasIcon())}
        except Exception:
            previous_invis = None
        try:
            if A_SCALE is not None:
                _attr = player.getAttribute(A_SCALE)
                if _attr is not None:
                    prev_scale = float(_attr.getBaseValue())
        except Exception:
            pass
        self.sessions[u] = {
            "type": drone_type,
            "dummy_uid": uid(dummy),
            "hitbox_uid": uid(hitbox),
            "display_uid": (uid(display) if display is not None else None),
            "model_uids": model_uids,
            "model_parts": model_parts,
            "spin": 0.0,
            "return": (world.getName(), loc.getX(), loc.getY(), loc.getZ()),
            "prev_gm": prev_gm,
            "prev_fly": prev_fly,
            "prev_flying": prev_flying,
            "prev_fly_speed": prev_fs,
            "prev_scale": prev_scale,
            "prev_invisibility": previous_invis,
        }

        # Persist the untouched player state before changing game mode, flight,
        # scale or inventory. A JVM/script failure at any later line is recoverable.
        saved_armor = None
        try:
            inv = player.getInventory()
            saved_armor = []
            for a in inv.getArmorContents():
                saved_armor.append(a.clone() if a is not None else None)
        except Exception:
            saved_armor = None
        self.sessions[u]["saved_armor"] = saved_armor
        state.setdefault("operator_recovery", {})[u] = _session_recovery_record(player, self.sessions[u])
        if not _save():
            state.setdefault("operator_recovery", {}).pop(u, None)
            failed_session = self.sessions.pop(u, None)
            if failed_session is not None:
                self._remove_model_entities(failed_session)
            try:
                dummy.remove()
            except Exception:
                pass
            player.sendMessage(u"§cНе удалось сохранить состояние оператора. Запуск отменён.")
            return

        try:
            player.setGameMode(GameMode.ADVENTURE)
            inv_eff = PotionEffect(E_INVIS, PotionEffect.INFINITE_DURATION, 0,
                                   False, False, False)   # без частиц, без иконки
            player.addPotionEffect(inv_eff)
            player.setAllowFlight(True)
            player.setFlying(True)
            player.setFlySpeed(float(DRONE_FLY_SPEED))
            if A_SCALE is not None:
                _attr2 = player.getAttribute(A_SCALE)
                if _attr2 is not None:
                    _attr2.setBaseValue(float(DRONE_SCALE))
            if saved_armor is not None:
                inv.setHelmet(None)
                inv.setChestplate(None)
                inv.setLeggings(None)
                inv.setBoots(None)
        except Exception as ex:
            _warn("drone operator transform: " + str(ex))
            self._exit(player, apply_penalty=False)
            player.sendMessage(u"§cНе удалось включить режим оператора. Запуск отменён.")
            return

        if display is not None:
            player.addPassenger(display)

        # пульт — расходник: один запуск = минус один пульт из стака
        if item is not None:
            _consume_one(player, item)

        if drone_type == u"scout":
            player.sendMessage(u"§b§lДрон-разведчик запущен. §7ЛКМ — скан, ПКМ — возврат.")
        else:
            player.sendMessage(u"§c§lДрон-камикадзе запущен. §7ЛКМ/столкновение — детонация.")
        _play_at(world, loc.getX(), loc.getY(), loc.getZ(),
                 Sound.ENTITY_PHANTOM_FLAP, 1.0, 1.4)
        _combat_event("drone_launch", u, player.getName(), world=world.getName(),
                      x=loc.getX(), y=loc.getY(), z=loc.getZ(), details={"type": drone_type})

    # --- ЛКМ-действия -----------------------------------------------------

    def handle_lmb(self, player):
        s = self.sessions.get(uid(player))
        if s is None:
            return False
        if s["type"] == u"scout":
            self._scout_scan(player)
        else:
            self.detonate_kamikaze(player, "manual")
        return True

    def _scout_scan(self, player):
        if not check_cd(player, "drone_scan", u"§bСканирование"):
            return
        set_cd(player, "drone_scan", SCOUT_SCAN_CD_TICKS)
        loc = player.getLocation()
        found = 0
        nearby = player.getWorld().getNearbyEntities(
            loc, SCOUT_SCAN_RADIUS, SCOUT_SCAN_RADIUS, SCOUT_SCAN_RADIUS)
        for ent in nearby:
            if not isinstance(ent, LivingEntity):
                continue
            if uid(ent) == uid(player):
                continue
            if isinstance(ent, Player) and same_team(player, ent):
                continue  # союзников не светим
            # собственный манекен — тоже пропускаем
            if isinstance(ent, ArmorStand) \
                    and _pdc_str(ent, KEY_DUMMY_OWNER) == player.getName():
                continue
            if ent.hasPotionEffect(E_GLOW):
                continue
            ent.addPotionEffect(PotionEffect(E_GLOW, SCOUT_GLOW_TICKS, 0,
                                             False, True))
            found += 1
        # Визуал сонара
        try:
            _spawn_particle(player.getWorld(), P_BOOM, loc.clone().add(0, 1.0, 0), 1)
        except Exception:
            pass
        _play_at(player.getWorld(), loc.getX(), loc.getY(), loc.getZ(),
                 Sound.BLOCK_BEACON_ACTIVATE, 0.6, 1.8)
        player.sendMessage(u"§bСканирование завершено. §7Обнаружено целей: §f%d" % found)

    # --- столкновение камикадзе (вызывается из on_move) -------------------

    def check_kamikaze_collision(self, player):
        s = self.sessions.get(uid(player))
        if s is None or s["type"] != u"kamikaze":
            return
        loc = player.getLocation()
        nearby = player.getWorld().getNearbyEntities(
            loc, KAMIKAZE_HIT_RANGE, KAMIKAZE_HIT_RANGE, KAMIKAZE_HIT_RANGE)
        for ent in nearby:
            if not isinstance(ent, LivingEntity):
                continue
            if uid(ent) == uid(player):
                continue
            # не взрываемся о собственный манекен/хитбокс
            if uid(ent) == s.get("dummy_uid") or uid(ent) == s.get("hitbox_uid"):
                continue
            if isinstance(ent, Player) and same_team(player, ent):
                continue
            # хитбокс/манекен СОЮЗНОГО дрона — не цель: насквозь без взрыва
            dname = _pdc_str(ent, KEY_DUMMY_OWNER)
            if dname is not None and dname != player.getName():
                downer = Bukkit.getPlayer(dname)
                if downer is not None and same_team(player, downer):
                    continue
            # столкновение с вражеской целью
            self.detonate_kamikaze(player, "collision")
            return

    # --- детонация камикадзе ----------------------------------------------

    def detonate_kamikaze(self, player, reason):
        s = self.sessions.get(uid(player))
        if s is None:
            return
        loc = player.getLocation().clone()
        world = player.getWorld()
        _combat_event("kamikaze_detonate", uid(player), player.getName(), world=world.getName(),
                      x=loc.getX(), y=loc.getY(), z=loc.getZ(), details={"reason": _to_unicode(reason)})
        # сначала выходим (оператор возвращается в точку запуска),
        # взрыв — с коротким запалом 3 тика, чтобы не задеть оператора
        self._exit(player, apply_penalty=False)
        w_ref = world
        x, y, z = loc.getX(), loc.getY(), loc.getZ()
        owner_name = player.getName()
        def _boom():
            try:
                # фиксируем взрыв: protect_from_kamikaze_blast отменит
                # ВАНИЛЬНЫЙ урон ударной волной по оператору и союзникам
                self.recent_booms.append({
                    "world": w_ref.getName(), "x": x, "y": y, "z": z,
                    "until": now_tick() + 4, "owner": owner_name,
                })
                _explode(w_ref, x, y, z, KAMIKAZE_POWER, None, False, False)
                center = Location(w_ref, x, y, z)
                for ent in w_ref.getNearbyEntities(center, KAMIKAZE_RADIUS,
                                                   KAMIKAZE_RADIUS, KAMIKAZE_RADIUS):
                    if not isinstance(ent, LivingEntity) or _is_protected(ent):
                        continue
                    # добивка 28 урона — только по ЧУЖИМ: оператор и его
                    # союзники (scoreboard-команда) взрывом не задеваются
                    if isinstance(ent, Player):
                        if ent.getName() == owner_name:
                            continue
                        op = Bukkit.getPlayer(owner_name)
                        if op is not None and same_team(op, ent):
                            continue
                    # страховка: игрок под щитом возврата не задевается никогда
                    if isinstance(ent, Player) and self.is_return_shielded(ent):
                        continue
                    try:
                        if isinstance(ent, Player):
                            _log("boom damage to player %s (boom owner %s)" % (
                                ent.getName(), _ascii_safe(owner_name)))
                        ent.damage(KAMIKAZE_DAMAGE)
                    except Exception:
                        pass
            except Exception:
                pass
        _play_at(world, x, y, z, Sound.ENTITY_TNT_PRIMED, 1.0, 1.0)
        scheduler.runTaskLater(_boom, 3)
        _log("kamikaze detonated: %s (%s)" % (player.getName(), _ascii_safe(reason)))

    # --- выход / уничтожение ----------------------------------------------

    def exit_drone(self, player, destroyed=False, penalty=True):
        s = self.sessions.get(uid(player))
        if s is None:
            return
        self._exit(player, apply_penalty=(destroyed and penalty))

    def _exit(self, player, apply_penalty):
        u = uid(player)
        s = self.sessions.pop(u, None)
        if s is None:
            return
        _combat_event("drone_exit", u, player.getName(), details={
            "type": s.get("type"), "destroyed": bool(apply_penalty)})

        # сущности убираем сразу
        display = _entity_by_uid(s.get("display_uid"))
        if display is not None:
            try:
                player.removePassenger(display)
            except Exception:
                pass
        self._remove_model_entities(s)
        dummy = _entity_by_uid(s.get("dummy_uid"))
        if dummy is not None:
            dummy.remove()

        # ЩИТ ВОЗВРАТА: после выхода из дрона (любого: добровольного,
        # уничтожения, детонации камикадзе) оператор N тиков неуязвим ко
        # ВСЕМУ урону — см. is_return_shielded в on_damage. Закрывает утечку
        # «урон прилетает, когда я уже вернулся в операторство»: вражеский
        # камикадзе, врезавшийся в манекен/игрока на точке запуска, отставшие
        # взрывы и волна больше не могут задеть вернувшегося игрока.
        now = now_tick()
        self.return_shield[u] = now + DRONE_RETURN_SHIELD_TICKS
        for k2 in list(self.return_shield.keys()):
            if self.return_shield[k2] < now:
                self.return_shield.pop(k2, None)

        # Возврат оператора — ОТЛОЖЕННО на 1 тик и строго в сохранённые
        # координаты запуска: синхронный телепорт внутри damage-события
        # работал через раз, поэтому восстановление полностью вынесено
        # из контекста события.
        wname, bx, by, bz = s["return"]
        p_ref = player
        sess = s
        def _restore():
            try:
                if not p_ref.isOnline():
                    return
                record = state.setdefault("operator_recovery", {}).get(u)
                if record is None:
                    record = _session_recovery_record(p_ref, sess)
                    state["operator_recovery"][u] = record
                    if not _save():
                        _warn("missing operator recovery record could not be recreated: " + u)
                        return
                if _restore_operator_record(p_ref, record, notify=False):
                    p_ref.sendMessage(u"§7Управление дроном завершено.")
            except Exception as ex:
                _warn("drone restore: " + _ascii_safe(ex))
        scheduler.runTaskLater(_restore, 1)

        # Штрафного урона за уничтоженный дрон НЕТ (по запросу):
        # оператор сидит далеко от дрона, урон «из ниоткуда» — это баг UX.
        if apply_penalty:
            def _note():
                try:
                    if player.isOnline():
                        player.sendMessage(u"§cДрон уничтожен.")
                except Exception:
                    pass
            scheduler.runTaskLater(_note, 3)

    # --- урон по оператору дрона (из on_damage) ----------------------------

    def is_return_shielded(self, ent):
        # Иммунитет оператора на DRONE_RETURN_SHIELD_TICKS после выхода
        # из дрона. Пустота (void) сознательно НЕ блокируется — чтобы щит
        # нельзя было использовать как 3 секунды бессмертия в бездне.
        if not isinstance(ent, Player) or not self.return_shield:
            return False
        return now_tick() < self.return_shield.get(uid(ent), 0)

    def protect_from_kamikaze_blast(self, event):
        # Отменяет ВАНИЛЬНЫЙ урон взрыва камикадзе (ударная волна) по его
        # оператору и его союзникам. Ручная добивка фильтруется в _boom.
        if not self.recent_booms:
            return False
        try:
            cause = event.getCause()
            if cause != EntityDamageEvent.DamageCause.ENTITY_EXPLOSION \
                    and cause != EntityDamageEvent.DamageCause.BLOCK_EXPLOSION:
                return False
        except Exception:
            return False
        ent = event.getEntity()
        if not isinstance(ent, Player):
            return False
        now = now_tick()
        kept = []
        handled = False
        for b in self.recent_booms:
            if now > b["until"]:
                continue
            kept.append(b)
            if handled or b["world"] != ent.getWorld().getName():
                continue
            el = ent.getLocation()
            dx = el.getX() - b["x"]
            dy = el.getY() - b["y"]
            dz = el.getZ() - b["z"]
            if dx * dx + dy * dy + dz * dz > 100.0:
                continue   # дальше 10 блоков — уже не этот взрыв
            if ent.getName() == b["owner"]:
                event.setCancelled(True)
                handled = True
                continue
            op = Bukkit.getPlayer(b["owner"])
            if op is not None and same_team(op, ent):
                event.setCancelled(True)
                handled = True
        self.recent_booms = kept
        return handled

    def handle_operator_damage(self, event):
        ent = event.getEntity()
        if not isinstance(ent, Player):
            return False
        s = self.sessions.get(uid(ent))
        if s is None:
            return False
        # Пустота: дрон гибнет, но оператора отвязываем БЕЗ отмены урона —
        # иначе игрок становился бы бессмертным к void.
        try:
            if event.getCause() == EntityDamageEvent.DamageCause.VOID:
                self.exit_drone(ent, destroyed=False)
                return True
        except Exception:
            pass
        event.setCancelled(True)   # урон принимает дрон, а не оператор
        # ДИАГНОСТИКА: каким источником и где по оператору пришёл урон —
        # видно в логе, если HP всё же потерялись где-то рядом по времени
        try:
            _l = ent.getLocation()
            _log("operator hit: %s cause=%s at %d %d %d" % (
                ent.getName(), _ascii_safe(str(event.getCause())),
                _l.getBlockX(), _l.getBlockY(), _l.getBlockZ()))
        except Exception:
            pass
        if s["type"] == u"kamikaze":
            self.detonate_kamikaze(ent, "shot down")
        else:
            self.exit_drone(ent, destroyed=True, penalty=True)
        return True

    # --- урон по летающему хитбоксу дрона (из EntityDamageEvent) ----------

    def handle_hitbox_damage(self, event):
        # Урон по летающей хитбокс-стойке модели = урон по самому дрону.
        # Стойка не ломается никогда: событие отменяется, а дрон гибнет.
        ent = event.getEntity()
        if not isinstance(ent, ArmorStand):
            return False
        owner_name = _pdc_str(ent, KEY_DUMMY_OWNER)
        if owner_name is None:
            return False
        eu = uid(ent)
        owner = None
        for u, s in self.sessions.items():
            if s.get("hitbox_uid") == eu:
                owner = Bukkit.getPlayer(owner_name)
                break
        if owner is None:
            # не хитбокс дрона (наземный манекен и т.п.) — не наше событие
            return False
        event.setCancelled(True)
        if owner.isOnline() and uid(owner) in self.sessions:
            if self.sessions[uid(owner)]["type"] == u"kamikaze":
                self.detonate_kamikaze(owner, "drone hitbox destroyed")
            else:
                self.exit_drone(owner, destroyed=True, penalty=True)
        return True

    # --- манекен уничтожен (из EntityDeathEvent) ---------------------------

    def handle_dummy_death(self, entity, event):
        owner_name = _pdc_str(entity, KEY_DUMMY_OWNER)
        if owner_name is None:
            return False
        # броня манекена — визуальная копия, дроп запрещаем (защита от дюпа)
        try:
            event.getDrops().clear()
        except Exception:
            pass
        # найти сессию владельца и выкинуть его из дрона
        victim = None
        for u, s in list(self.sessions.items()):
            if s.get("dummy_uid") == uid(entity):
                victim = Bukkit.getPlayer(owner_name)
                break
        if victim is not None and victim.isOnline():
            victim.sendMessage(u"§4§lМанекен-передатчик уничтожен! §cСвязь потеряна.")
            self.exit_drone(victim, destroyed=True, penalty=True)
        return True

    # --- ПКМ: запуск или выход --------------------------------------------

    def handle_rmb(self, player, item):
        s = self.sessions.get(uid(player))
        if s is not None:
            # повторный ПКМ — выход из дрона
            self.exit_drone(player, destroyed=False)
            return True
        drone_type = self.remote_type_of(item)
        if drone_type is None:
            return False
        self.launch(player, drone_type, item)
        return True

    # --- служебное ---------------------------------------------------------

    def restore_on_join(self, player):
        # Игрок вышел из сервера в дроне — завершаем сессию
        record = state.setdefault("operator_recovery", {}).get(uid(player))
        if record is not None:
            self.sessions.pop(uid(player), None)
            _restore_operator_record(player, record)
            return
        s = self.sessions.pop(uid(player), None)
        if s is None:
            return
        try:
            player.removePotionEffect(E_INVIS)
        except Exception:
            pass
        try:
            player.setGameMode(GameMode.valueOf(s["prev_gm"]))
        except Exception:
            pass
        try:
            if not s.get("prev_fly"):
                player.setAllowFlight(False)
        except Exception:
            pass
        try:
            if A_SCALE is not None:
                _a = player.getAttribute(A_SCALE)
                if _a is not None:
                    _a.setBaseValue(float(s.get("prev_scale", 1.0)))
        except Exception:
            pass
        w = Bukkit.getWorld(s["return"][0])
        if w is not None:
            loc_ref = Location(w, s["return"][1], s["return"][2], s["return"][3])
            p_ref = player
            def _tp_back():
                try:
                    if p_ref.isOnline():
                        p_ref.teleport(loc_ref)
                except Exception:
                    pass
            scheduler.runTaskLater(_tp_back, 1)
        dummy = _entity_by_uid(s.get("dummy_uid"))
        if dummy is not None:
            dummy.remove()
        self._remove_model_entities(s)
        self._give_back_armor(player, s)

    def handle_quit(self, player):
        # Сессию не удаляем — восстановим при входе (return-точка сохранена)
        sess = self.sessions.get(uid(player))
        if sess is not None:
            state.setdefault("operator_recovery", {})[uid(player)] = _session_recovery_record(player, sess)
            _save()

    def _give_back_armor(self, player, sess):
        # вернуть броню, снятую на время полёта; если слот занят — выкинуть копию
        saved = sess.get("saved_armor")
        if not saved:
            return
        try:
            inv = player.getInventory()
            getters = (inv.getBoots, inv.getLeggings, inv.getChestplate, inv.getHelmet)
            setters = (inv.setBoots, inv.setLeggings, inv.setChestplate, inv.setHelmet)
            for i in range(4):
                piece = saved[i]
                if piece is None or piece.getType() == Material.AIR:
                    continue
                cur = getters[i]()
                if cur is None or cur.getType() == Material.AIR:
                    setters[i](piece)
                else:
                    player.getWorld().dropItemNaturally(player.getLocation(), piece)
            sess["saved_armor"] = None
        except Exception:
            pass

    def _remove_model_entities(self, s):
        # удалить летающий хитбокс и части модели дрона
        hb = _entity_by_uid(s.get("hitbox_uid"))
        if hb is not None:
            hb.remove()
        display = _entity_by_uid(s.get("display_uid"))
        if display is not None:
            display.remove()
        for pu in s.get("model_uids", []):
            pe = _entity_by_uid(pu)
            if pe is not None:
                pe.remove()

    def tick_models(self):
        # Каждый тик части модели летят за оператором и поворачиваются по его
        # yaw (локальная ось +Z = нос дрона).
        if not self.sessions:
            return
        for u, s in self.sessions.items():
            parts = s.get("model_parts") or {}
            p = Bukkit.getPlayer(JUUID.fromString(u))
            if p is None or not p.isOnline():
                continue
            base = p.getLocation()
            # замер скорости дрона, блоков/тик (тикер идёт каждый тик):
            # нужен станку ПВО для ЧЕСТНОГО упреждения — самонаведения нет
            prev = s.get("last_pos")
            if prev is not None:
                s["vx"] = base.getX() - prev[0]
                s["vy"] = base.getY() - prev[1]
                s["vz"] = base.getZ() - prev[2]
            s["last_pos"] = (base.getX(), base.getY(), base.getZ())
            yaw = base.getYaw()
            rad = Math.toRadians(yaw)
            cs = Math.cos(rad)
            sn = Math.sin(rad)
            w = base.getWorld()
            # Роторы НЕ вращаются: при вращении вместе с интерполяцией teleport
            # лопасти размазывались и выглядели криво. Статичный крест — как
            # на референсе. Вернуть вращение: spin_a = (s["spin"] + 40.0) % 360.
            spin_a = 0.0
            s["spin"] = spin_a
            # Дисплеи достаточно двигать раз в два тика: интерполяция оставляет
            # движение плавным, а хитбокс и скорость ниже обновляются каждый тик.
            if now_tick() % 2 == 0:
                for puid, off in parts.items():
                    part = _entity_by_uid(puid)
                    if part is None:
                        continue
                    if len(off) == 4:
                        ox, oy, oz, sp = off
                    else:
                        ox, oy, oz = off
                        sp = 0
                    wx = base.getX() + ox * cs - oz * sn
                    wy = base.getY() + oy
                    wz = base.getZ() + ox * sn + oz * cs
                    ry = yaw + spin_a if sp else yaw
                    try:
                        part.teleport(Location(w, wx, wy, wz, float(ry), 0.0))
                    except Exception:
                        pass
            # летающий хитбокс следует за центром модели дрона
            hb = _entity_by_uid(s.get("hitbox_uid"))
            if hb is not None:
                try:
                    hb.teleport(Location(w, base.getX(),
                                         base.getY() + DRONE_HITBOX_Y,
                                         base.getZ()))
                except Exception:
                    pass

    def tick_flight_sound(self):
        """Keep the motor audible while its moving sound source follows the drone."""
        if not self.sessions:
            return
        flight_sound = getattr(Sound, "ENTITY_BEE_LOOP", None)
        if flight_sound is None:
            flight_sound = Sound.ENTITY_PHANTOM_FLAP
        for player_uuid, session in list(self.sessions.items()):
            try:
                player = Bukkit.getPlayer(JUUID.fromString(player_uuid))
                if player is None or not player.isOnline():
                    continue
                loc = player.getLocation()
                # A Bukkit positional sound stays at the coordinate where it
                # started.  Refresh it before the drone can fly away from that
                # coordinate; overlapping quiet clips produce one steady motor.
                _play_at(loc.getWorld(), loc.getX(), loc.getY() + 0.7, loc.getZ(),
                         flight_sound, 0.18,
                         0.65 if session.get("type") == u"kamikaze" else 1.25)
            except Exception as ex:
                _warn("drone flight sound: " + _ascii_safe(ex))

    # --- дальность управления / потеря сигнала -----------------------------

    def tick_range(self):
        # Вызывается из _tick_10. Механика:
        #   0..129 м        — норма
        #   130..149 м      — "слабый сигнал": actionbar-предупреждение
        #   150+ м / другой мир — СВЯЗЬ ПОТЕРЯНА: дрон падает.
        #     Разведчик просто отваливается; камикадзе детонирует на месте.
        if not self.sessions:
            return
        if getattr(self, "_warn_at", None) is None:
            self._warn_at = {}
        for u, s in list(self.sessions.items()):
            p = Bukkit.getPlayer(JUUID.fromString(u))
            if p is None or not p.isOnline():
                continue
            wname, bx, by, bz = s["return"]
            lost = False
            dist = 0.0
            if p.getWorld().getName() != wname:
                lost = True
                dist = DRONE_RANGE + 1.0
            else:
                pl = p.getLocation()
                dx = pl.getX() - bx
                dy = pl.getY() - by
                dz = pl.getZ() - bz
                dist = Math.sqrt(dx * dx + dy * dy + dz * dz)
                if dist >= DRONE_RANGE:
                    lost = True
            if lost:
                p.sendMessage(u"§c§lСВЯЗЬ С ДРОНОМ ПОТЕРЯНА! "
                              u"§7Вышел из зоны управления (§f150 м§7).")
                _play(p, Sound.BLOCK_BEACON_DEACTIVATE, 1.0, 0.6)
                if s["type"] == u"kamikaze":
                    self.detonate_kamikaze(p, "signal lost")
                else:
                    self.exit_drone(p, destroyed=True)
                self._warn_at.pop(u, None)
                continue
            if dist >= DRONE_WARN_RANGE:
                # предупреждение не чаще раза в 2 секунды
                if now_tick() < self._warn_at.get(u, 0):
                    continue
                self._warn_at[u] = now_tick() + 40
                try:
                    p.sendActionBar(u"§e§l[!] §eСлабый сигнал: §f%d §7/ §f150 §7м — "
                                    u"возвращайся!" % int(dist))
                except Exception:
                    p.sendMessage(u"§eСлабый сигнал дрона: §f%d §7м" % int(dist))
                _play(p, Sound.BLOCK_NOTE_BLOCK_BIT, 0.6, 0.5)

    def cleanup_orphans(self):
        # Удалить все сущности с нашими PDC-метками (после script reload и т.п.)
        removed = 0
        for w in Bukkit.getWorlds():
            for e in w.getEntities():
                if _pdc_str(e, KEY_DUMMY_OWNER) is not None:
                    e.remove()
                    removed += 1
        self.sessions.clear()
        return removed

# ============================================================================
# 2. MineManager — мины (кнопка + Marker-сущность)
# ============================================================================

class MineManager(object):
    """
    Мина — НЕВИДИМАЯ (физического блока нет): невидимый Marker-стенд + реестр.
    Реестр мин: state["mines"][key] = {
        "world": str, "x": int, "y": int, "z": int, "marker_uid": str, "owner": str
    }
    Ключ — блок ВОЗДУХА над полом, где стоит маркер. Реестр — источник истины.
    Установка: ПКМ миной по верхней грани блока.
    Снятие:   владелец — ПКМ киркой; другие — сапёрный набор (GUI).
    Опорный блок под миной не ломается, пока мина установлена.
    Раскрытие: рядом с металлоискателем мина на 2 с становится видимой.
    """

    def __init__(self):
        self._next_ping = {}   # uid -> до какого тика пауза между писками
        self._revealed = {}    # ключ мины -> тик, до которого она видима

    def make_mine_item(self):
        m = Material.POLISHED_BLACKSTONE_BUTTON
        if m is None:
            m = Material.STONE_BUTTON
        it = _make_item(m, CMD_MINE, u"§4§lМина «Фугас»", [
            u"§7ПКМ по верхней грани блока — установка.",
            u"§7Мина невидима, срабатывает от наступания.",
            u"§8Владелец снимает её киркой (ПКМ).",
            u"§8Обезвредить — сапёрный набор (Shift+ПКМ).",
            u"§8Светится рядом с металлоискателем.",
        ])
        mm = it.getItemMeta()
        mm.getPersistentDataContainer().set(
            KEY_MINE_ITEM, PersistentDataType.STRING, u"high_explosive")
        it.setItemMeta(mm)
        return it

    def is_mine_item(self, item):
        if item is None:
            return False
        m = item.getItemMeta()
        return m is not None and _pdc_str(m, KEY_MINE_ITEM) is not None

    # --- установка: ПКМ миной по верхней грани блока (из on_interact) ------

    def place(self, player, clicked, item):
        # Установка мины. Физический блок НЕ ставится: мина — невидимый
        # маркер-стенд в блоке воздуха над полом, реестр — источник истины.
        if is_silenced_by_demiurg(player):
            player.sendMessage(u"§5§oНеведомая сила не даёт обращаться с миной...")
            return True
        target = clicked.getRelative(BlockFace.UP)
        world = target.getWorld()
        key = _loc_key(world.getName(), target.getX(), target.getY(), target.getZ())
        if key in state["mines"]:
            player.sendMessage(u"§7Здесь уже замаскирована мина.")
            return True
        center = Location(world, target.getX() + 0.5, target.getY() + 0.15,
                          target.getZ() + 0.5)
        # маленький маркер опущен под пол: на его голове — предмет мины,
        # поэтому при «раскрытии» кнопка-мина лежит на уровне земли,
        # а тело стойки не рисуется вовсе (marker=True)
        ground = Location(world, center.getX(),
                          target.getY() - MINE_MARKER_DEPTH, center.getZ())
        marker = world.spawn(ground, ArmorStand)
        marker.setMarker(True)
        marker.setSmall(True)
        marker.setInvisible(True)
        marker.setGravity(False)
        marker.setInvulnerable(True)
        marker.setSilent(True)
        try:
            marker.getEquipment().setHelmet(self.make_mine_item())
        except Exception:
            pass
        marker.getPersistentDataContainer().set(
            KEY_MINE_MARKER, PersistentDataType.STRING, u"high_explosive")
        state["mines"][key] = {
            "world": world.getName(),
            "x": target.getX(), "y": target.getY(), "z": target.getZ(),
            "marker_uid": uid(marker),
            "owner": player.getName(),
            "owner_uuid": uid(player),
            "owner_name": player.getName(),
        }
        if not _save():
            state["mines"].pop(key, None)
            try:
                marker.remove()
            except Exception:
                pass
            player.sendMessage(u"§cМина не установлена: реестр Warfare недоступен.")
            return True
        _combat_event("mine_place", uid(player), player.getName(), world=world.getName(),
                      x=target.getX(), y=target.getY(), z=target.getZ())
        _consume_one(player, item)
        _play_at(world, center.getX(), center.getY(), center.getZ(),
                 Sound.BLOCK_STONE_BUTTON_CLICK_ON, 0.5, 0.6)
        player.sendMessage(u"§4§lМина замаскирована. §7Снять самому: ПКМ киркой.")
        return True

    def owner_remove(self, player, clicked):
        # Снятие мины владельцем: ПКМ киркой по блоку мины (без взрыва).
        # None — мины тут нет (не обрабатывали); True — снята; False — чужая.
        key = self.find_key_at(clicked)
        if key is None:
            return None
        entry = state["mines"].get(key)
        owner = entry.get("owner_uuid") if entry is not None else None
        legacy_owner = entry.get("owner") if entry is not None else None
        if (owner and owner != uid(player)) or (not owner and legacy_owner != player.getName()):
            player.sendMessage(u"§cЧужая мина. §7Её снимет владелец киркой, "
                               u"обезвредить — сапёрный набор (Shift+ПКМ).")
            return False
        state["mines"].pop(key, None)
        if not _save():
            state["mines"][key] = entry
            player.sendMessage(u"§cМину не удалось снять: реестр не сохранён.")
            return False
        self._remove_marker_entry(key, entry)
        w = Bukkit.getWorld(entry["world"])
        if w is not None:
            w.dropItemNaturally(
                Location(w, entry["x"] + 0.5, entry["y"] + 0.4, entry["z"] + 0.5),
                self.make_mine_item())
        _combat_event("mine_remove", uid(player), player.getName(), world=entry.get("world"),
                      x=entry.get("x"), y=entry.get("y"), z=entry.get("z"))
        player.sendMessage(u"§aТы снял свою мину.")
        _play(player, Sound.BLOCK_NOTE_BLOCK_PLING, 1.0, 1.2)
        return True

    # --- наступание (из on_move, уже отфильтровано по смене блока) ---------

    def check_step(self, player, to_block):
        # Реестр — источник истины: физического блока у мины больше нет
        world = to_block.getWorld()
        key = _loc_key(world.getName(), to_block.getX(),
                       to_block.getY(), to_block.getZ())
        if key in state["mines"]:
            self.detonate(key, "stepped on by " + player.getName())
            return True
        return False

    def _remove_marker(self, key):
        entry = state["mines"].get(key)
        if entry is None:
            return
        self._remove_marker_entry(key, entry)

    def _remove_marker_entry(self, key, entry):
        self._revealed.pop(key, None)
        marker = _entity_by_uid(entry.get("marker_uid"))
        if marker is not None:
            marker.remove()
            return
        # fallback: поиск рядом
        w = Bukkit.getWorld(entry["world"])
        if w is None:
            return
        center = Location(w, entry["x"] + 0.5, entry["y"] + 0.5, entry["z"] + 0.5)
        try:
            for e in w.getNearbyEntities(center, 0.8, 1.7, 0.8):
                if isinstance(e, ArmorStand) and _pdc_str(e, KEY_MINE_MARKER) is not None:
                    e.remove()
        except Exception:
            pass

    def _explode_at(self, world, bx, by, bz):
        cx, cy, cz = bx + 0.5, by + 0.35, bz + 0.5
        _explode(world, cx, cy, cz, MINE_POWER, None, False, False)
        # огромный урон по живым существам, ландшафт не страдает (break_blocks=False)
        center = Location(world, cx, cy, cz)
        try:
            for ent in world.getNearbyEntities(center, MINE_RADIUS,
                                               MINE_RADIUS, MINE_RADIUS):
                if isinstance(ent, LivingEntity) and not _is_protected(ent):
                    ent.damage(MINE_DAMAGE)
        except Exception:
            pass

    def detonate(self, key, reason):
        entry = state["mines"].get(key)
        if entry is None:
            return
        state["mines"].pop(key, None)
        if not _save():
            state["mines"][key] = entry
            _warn("mine detonation cancelled because registry save failed: " + key)
            return
        self._remove_marker_entry(key, entry)
        w = Bukkit.getWorld(entry["world"])
        if w is not None:
            self._explode_at(w, entry["x"], entry["y"], entry["z"])
        _combat_event("mine_detonate", entry.get("owner_uuid"), entry.get("owner_name", entry.get("owner")),
                      world=entry.get("world"), x=entry.get("x"), y=entry.get("y"), z=entry.get("z"),
                      details={"reason": _to_unicode(reason)})
        _log("mine detonated at %s (%s)" % (key, _ascii_safe(reason)))

    # --- обезвреживание: успех ---------------------------------------------

    def disarm(self, key, player):
        entry = state["mines"].get(key)
        if entry is None:
            return
        state["mines"].pop(key, None)
        if not _save():
            state["mines"][key] = entry
            player.sendMessage(u"§cОбезвреживание отменено: реестр Warfare недоступен.")
            return
        self._remove_marker_entry(key, entry)
        w = Bukkit.getWorld(entry["world"])
        if w is not None:
            # возвращаем предмет мины
            w.dropItemNaturally(
                Location(w, entry["x"] + 0.5, entry["y"] + 0.3, entry["z"] + 0.5),
                self.make_mine_item())
        _combat_event("mine_disarm", uid(player), player.getName(),
                      target_uuid=entry.get("owner_uuid"), target_name=entry.get("owner_name", entry.get("owner")),
                      world=entry.get("world"), x=entry.get("x"), y=entry.get("y"), z=entry.get("z"))
        player.sendMessage(u"§a§lМина обезврежена! §7Осторожнее в следующий раз.")
        _play(player, Sound.BLOCK_NOTE_BLOCK_PLING, 1.0, 1.6)

    def find_key_at(self, block):
        if block is None:
            return None
        w = block.getWorld()
        key = _loc_key(w.getName(), block.getX(), block.getY(), block.getZ())
        if key in state["mines"]:
            return key
        # мина обычно висит в блоке НАД полом, по которому кликнули
        up = block.getRelative(BlockFace.UP)
        key2 = _loc_key(w.getName(), up.getX(), up.getY(), up.getZ())
        if key2 in state["mines"]:
            return key2
        return None

    def handle_support_break(self, event):
        # Опорный блок ПОД миной ломать нельзя, пока мина стоит — иначе она
        # повиснет в воздухе. Владелец снимает мину киркой (ПКМ), сапёр
        # обезвреживает (Shift+ПКМ) — после этого блок ломается свободно.
        block = event.getBlock()
        w = block.getWorld()
        up_key = _loc_key(w.getName(), block.getX(), block.getY() + 1,
                          block.getZ())
        if up_key not in state["mines"]:
            return False
        event.setCancelled(True)
        event.getPlayer().sendMessage(
            u"§4§lПод миной копать нельзя! "
            u"§7Сними её киркой (ПКМ по блоку над ней).")
        return True

    def keys(self):
        return list(state["mines"].keys())

    def clear_all(self):
        previous = state["mines"]
        state["mines"] = {}
        if not _save():
            state["mines"] = previous
            return False
        for key, entry in previous.items():
            self._remove_marker_entry(key, entry)
        return True

    def tick_detector(self):
        # свернуть просроченные «открытия» мин
        self._tick_reveals()
        # Металлоискатель: обход игроков с детектором в руках
        for player in Bukkit.getOnlinePlayers():
            held = None
            for hand_item in (player.getInventory().getItemInMainHand(),
                              player.getInventory().getItemInOffHand()):
                if hand_item is None:
                    continue
                hm = hand_item.getItemMeta()
                if hm is not None and _pdc_str(hm, KEY_TOOL) == u"detector":
                    held = hand_item
                    break
            if held is None:
                continue
            if is_silenced_by_demiurg(player):
                continue
            self._detector_ping(player)

    def _detector_ping(self, player):
        # ищем ближайшую мину по реестру (дешевле, чем getNearbyEntities)
        pl = player.getLocation()
        wname = player.getWorld().getName()
        best = None
        best_key = None
        best_d2 = None
        for key, entry in state["mines"].items():
            if entry["world"] != wname:
                continue
            dx = entry["x"] + 0.5 - pl.getX()
            dy = entry["y"] + 0.5 - pl.getY()
            dz = entry["z"] + 0.5 - pl.getZ()
            d2 = dx * dx + dy * dy + dz * dz
            if d2 <= DETECTOR_RADIUS * DETECTOR_RADIUS and (best_d2 is None or d2 < best_d2):
                best_d2 = d2
                best = entry
                best_key = key
        if best is None:
            return
        dist = Math.sqrt(best_d2)
        u = uid(player)
        nxt = getattr(self, "_next_ping", None)
        if nxt is None:
            nxt = {}
            self._next_ping = nxt
        if now_tick() < nxt.get(u, 0):
            return
        # чем ближе — тем выше pitch и чаще писк
        closeness = 1.0 - (dist / DETECTOR_RADIUS)
        interval = max(2, int(round(10.0 - closeness * 8.0)))   # 10..2 тиков
        nxt[u] = now_tick() + interval
        pitch = 0.5 + closeness * 1.5                            # 0.5..2.0
        _play(player, Sound.BLOCK_NOTE_BLOCK_BIT, 0.7, pitch)
        if dist < MINE_REVEAL_DIST:
            # «открытие»: мина ненадолго становится видимой + партиклы
            self._reveal(best_key, best)
            try:
                player.sendActionBar(u"§cМина обнаружена §8• §7владелец: §f%s" %
                                     best.get("owner_name", best.get("owner", u"Unknown")))
            except Exception:
                pass
            w = player.getWorld()
            try:
                dust = DustOptions(Color.RED, float(1.4))
                _spawn_particle(w, P_DUST,
                                best["x"] + 0.5, best["y"] + 0.55, best["z"] + 0.5,
                                6, 0.18, 0.06, 0.18, 0.0, dust)
            except Exception:
                pass

    def _reveal(self, key, entry):
        # мина «открывается»: маркер перестаёт быть невидимым — виден
        # только предмет на его голове (тела у marker-стойки нет)
        marker = _entity_by_uid(entry.get("marker_uid"))
        if marker is None:
            return
        try:
            marker.setInvisible(False)
        except Exception:
            return
        until = now_tick() + MINE_REVEAL_TICKS
        if until > self._revealed.get(key, 0):
            self._revealed[key] = until

    def _tick_reveals(self):
        # сворачиваем «открытие»: возвращаем минам невидимость
        if not self._revealed:
            return
        now = now_tick()
        for key in list(self._revealed.keys()):
            entry = state["mines"].get(key)
            if entry is None:
                self._revealed.pop(key, None)
                continue
            if now < self._revealed[key]:
                continue
            marker = _entity_by_uid(entry.get("marker_uid"))
            if marker is not None:
                try:
                    marker.setInvisible(True)
                except Exception:
                    pass
            self._revealed.pop(key, None)


# ============================================================================
# 3. SapperManager — сапёрные ножницы и GUI-миниигра обезвреживания
# ============================================================================

class SapperManager(object):
    """
    GUI 27 слотов: центральный ряд 10..16 — трек ползунка,
    слот 13 — «зелёная зона». Ползунок бегает пинг-понгом каждые 2 тика.
    Клик в GUI = захват: попал в 13 — успех, иначе взрыв.
    Закрытие (ESC) без результата = взрыв.
    sessions: uid -> {"inv": Inventory, "mine_key": str, "pos": int,
                      "dir": int, "resolved": bool}
    """

    TITLE = u"§4§lОбезвреживание мины"
    TRACK_SLOTS = [10, 11, 12, 13, 14, 15, 16]

    def __init__(self, mine_mgr):
        self.mine_mgr = mine_mgr
        self.sessions = {}

    def make_cutters(self):
        it = _make_item(Material.SHEARS, CMD_CUTTERS, u"§e§lСапёрные ножницы", [
            u"§7Shift + ПКМ §7по мине — обезвреживание.",
            u"§7Поймай момент: ползунок должен быть",
            u"§7в §aзелёной зоне§7 (центр).",
        ])
        m = it.getItemMeta()
        m.getPersistentDataContainer().set(KEY_TOOL, PersistentDataType.STRING, u"cutters")
        it.setItemMeta(m)
        return it

    def make_detector(self):
        it = _make_item(Material.GOLDEN_HOE, CMD_DETECTOR, u"§6§lМеталлоискатель", [
            u"§7Держи в руке — писк укажет на мины.",
            u"§7Чем ближе — тем выше и чаще сигнал.",
            u"§7В упор мина начинает светиться.",
        ])
        m = it.getItemMeta()
        m.getPersistentDataContainer().set(KEY_TOOL, PersistentDataType.STRING, u"detector")
        it.setItemMeta(m)
        return it

    def is_cutters(self, item):
        if item is None:
            return False
        m = item.getItemMeta()
        return m is not None and _pdc_str(m, KEY_TOOL) == u"cutters"

    def is_detector(self, item):
        if item is None:
            return False
        m = item.getItemMeta()
        return m is not None and _pdc_str(m, KEY_TOOL) == u"detector"

    # --- открытие GUI -------------------------------------------------------

    def open_defuse(self, player, mine_key):
        if uid(player) in self.sessions:
            return
        inv = Bukkit.createInventory(None, 27, self.TITLE)
        # фон
        bg = _make_item(Material.GRAY_STAINED_GLASS_PANE, 0, u" ", None)
        for i in range(27):
            inv.setItem(i, bg.clone())
        # трек
        track = _make_item(Material.BLACK_STAINED_GLASS_PANE, 0, u"§8Провод", None)
        for s in self.TRACK_SLOTS:
            inv.setItem(s, track.clone())
        # зелёная зона — подсвечена статично
        zone = _make_item(Material.GREEN_STAINED_GLASS_PANE, 0,
                          u"§a§lЗона перерезания", [u"§7Кликни, когда ползунок здесь!"])
        inv.setItem(13, zone)
        start_pos = self.TRACK_SLOTS[0]
        dir_ = 1
        if _rand.nextInt(2) == 1:
            start_pos = self.TRACK_SLOTS[-1]
            dir_ = -1
        sess = {
            "inv": inv,
            "mine_key": mine_key,
            "pos": start_pos,
            "dir": dir_,
            "resolved": False,
        }
        self.sessions[uid(player)] = sess
        self._render(sess)
        player.openInventory(inv)
        _play(player, Sound.BLOCK_TRIPWIRE_CLICK_ON, 0.8, 1.2)

    def _render(self, sess):
        inv = sess["inv"]
        # ползунок: красный; на зелёной зоне становится лаймовым
        zone = _make_item(Material.GREEN_STAINED_GLASS_PANE, 0,
                          u"§a§lЗона перерезания", [u"§7Кликни, когда ползунок здесь!"])
        track = _make_item(Material.BLACK_STAINED_GLASS_PANE, 0, u"§8Провод", None)
        for s in self.TRACK_SLOTS:
            if s == 13:
                inv.setItem(13, zone.clone())
            else:
                inv.setItem(s, track.clone())
        if sess["pos"] == 13:
            cur = _make_item(Material.LIME_STAINED_GLASS_PANE, 0,
                             u"§a§lЖМИ СЕЙЧАС!", None)
        else:
            cur = _make_item(Material.RED_STAINED_GLASS_PANE, 0,
                             u"§cГорячий провод...", None)
        inv.setItem(sess["pos"], cur)

    def tick(self):
        # движение ползунков (вызывается каждые 2 тика)
        if not self.sessions:
            return
        for u, sess in list(self.sessions.items()):
            if sess["resolved"]:
                continue
            p = Bukkit.getPlayer(JUUID.fromString(u))
            if p is None or not p.isOnline():
                continue
            i = self.TRACK_SLOTS.index(sess["pos"])
            i += sess["dir"]
            if i >= len(self.TRACK_SLOTS):
                i = len(self.TRACK_SLOTS) - 2
                sess["dir"] = -1
            if i < 0:
                i = 1
                sess["dir"] = 1
            sess["pos"] = self.TRACK_SLOTS[i]
            self._render(sess)
            if sess["pos"] == 13:
                _play(p, Sound.BLOCK_NOTE_BLOCK_HAT, 0.6, 1.9)

    # --- клик -----------------------------------------------------------

    def handle_click(self, player, event):
        sess = self.sessions.get(uid(player))
        if sess is None:
            return False
        # только верхний инвентарь (наш GUI)
        try:
            if event.getClickedInventory() != event.getView().getTopInventory():
                event.setCancelled(True)
                return True
        except Exception:
            pass
        event.setCancelled(True)
        if sess["resolved"]:
            return True
        sess["resolved"] = True
        mine_key = sess["mine_key"]
        if sess["pos"] == 13:
            # УСПЕХ
            self.sessions.pop(uid(player), None)
            player.closeInventory()
            self.mine_mgr.disarm(mine_key, player)
        else:
            # ПРОВАЛ — взрыв
            self.sessions.pop(uid(player), None)
            player.closeInventory()
            player.sendMessage(u"§c§lНе тот провод!")
            self.mine_mgr.detonate(mine_key, "defuse failed: " + player.getName())
        return True

    # --- закрытие ---------------------------------------------------------

    def handle_close(self, player):
        sess = self.sessions.pop(uid(player), None)
        if sess is None:
            return False
        if not sess["resolved"]:
            # ESC = провал = взрыв
            player.sendMessage(u"§c§lТы отдёрнул руки — мина детонировала!")
            self.mine_mgr.detonate(sess["mine_key"],
                                   "defuse aborted: " + player.getName())
        return True

    def in_gui(self, player):
        return uid(player) in self.sessions

# ============================================================================
# 4. PvoManager — ручное и полуавтоматическое ПВО
# ============================================================================

class PvoManager(object):
    """
    Два вида ПВО:
      1) ПАССИВНОЕ (станок «Зенит»): блок-наковальня + композитная башня
         «Анвил» из BlockDisplay (блюдце, корпус, кожух, 4 рельсы-ствола 2x2,
         крутится yaw+pitch за взглядом) + Interaction (сиденье). Поворот
         стрелка, ЛКМ — огонь (бьёт и по пехоте). Полуавтомат: раз в 20 тиков
         скан полусферы r=50; 50% выстрелов — точные (честное упреждение по
         замеренной скорости дрона), остальные — рассеивание. Без самонаводки.
         state["pvo"][key] = {"world","x","y","z","display_uid","seat_uid"}
      2) АКТИВНОЕ (ПЗРК «Игла»): предмет в руке. ЛКМ/ПКМ — выстрел, КД 4 сек.
         Ракета летит СТРОГО ПРЯМО по прицелу: ни захвата, ни самонаведения.
         Сбивает только прямое касание корпуса дрона.
    Попадание любого снаряда = касание силуэта модели (SHELL_HIT_RADIUS).
    Снаряды: shells[uid_snowball] = {"life": int, "firer": str}
    """

    # Композитный ЗПУ: неподвижный станок, поворотная платформа, люлька и четыре
    # независимых ствола. mode: base = неподвижная деталь, yaw = только азимут,
    # gun = азимут и угол возвышения относительно PVO_HEAD_H.
    # Формат: (материал, ox, oy, oz, sx, sy, sz, mode).
    PVO_TURRET_PARTS = [
        # станина и погон
        ("POLISHED_DEEPSLATE",   0.00, -0.64,  0.00, 0.68, 0.22, 0.68, "base"),
        ("IRON_BLOCK",            0.00, -0.49,  0.00, 1.26, 0.14, 1.26, "base"),
        ("LIGHT_GRAY_CONCRETE",   0.00, -0.38,  0.00, 0.94, 0.12, 0.94, "base"),
        ("GRAY_CONCRETE",         0.00, -0.23,  0.00, 0.42, 0.30, 0.42, "yaw"),
        # поворотная тумба, боковые щёки и короба боекомплекта
        ("LIGHT_GRAY_CONCRETE",   0.00, -0.02, -0.02, 0.72, 0.42, 0.86, "yaw"),
        ("SMOOTH_QUARTZ",        -0.52,  0.02, -0.02, 0.24, 0.58, 0.76, "yaw"),
        ("SMOOTH_QUARTZ",         0.52,  0.02, -0.02, 0.24, 0.58, 0.76, "yaw"),
        ("POLISHED_DEEPSLATE",   -0.73,  0.01, -0.20, 0.28, 0.44, 0.54, "yaw"),
        ("POLISHED_DEEPSLATE",    0.73,  0.01, -0.20, 0.28, 0.44, 0.54, "yaw"),
        # качающаяся люлька и четыре ствола
        ("GRAY_CONCRETE",         0.00,  0.20,  0.28, 0.52, 0.38, 0.72, "gun"),
        ("IRON_BLOCK",           -0.18,  0.12,  0.62, 0.14, 0.14, 0.42, "gun"),
        ("IRON_BLOCK",            0.18,  0.12,  0.62, 0.14, 0.14, 0.42, "gun"),
        ("IRON_BLOCK",           -0.18,  0.36,  0.62, 0.14, 0.14, 0.42, "gun"),
        ("IRON_BLOCK",            0.18,  0.36,  0.62, 0.14, 0.14, 0.42, "gun"),
        ("POLISHED_BASALT",      -0.18,  0.12,  1.53, 0.095, 0.095, 1.52, "gun"),
        ("POLISHED_BASALT",       0.18,  0.12,  1.53, 0.095, 0.095, 1.52, "gun"),
        ("POLISHED_BASALT",      -0.18,  0.36,  1.53, 0.095, 0.095, 1.52, "gun"),
        ("POLISHED_BASALT",       0.18,  0.36,  1.53, 0.095, 0.095, 1.52, "gun"),
        # дульные тормоза и коллиматор
        ("BLACK_CONCRETE",       -0.18,  0.12,  2.34, 0.16, 0.16, 0.18, "gun"),
        ("BLACK_CONCRETE",        0.18,  0.12,  2.34, 0.16, 0.16, 0.18, "gun"),
        ("BLACK_CONCRETE",       -0.18,  0.36,  2.34, 0.16, 0.16, 0.18, "gun"),
        ("BLACK_CONCRETE",        0.18,  0.36,  2.34, 0.16, 0.16, 0.18, "gun"),
        ("RED_STAINED_GLASS",     0.00,  0.52,  0.37, 0.11, 0.11, 0.16, "gun"),
    ]

    def __init__(self, drone_mgr):
        self.drone_mgr = drone_mgr
        self.shells = {}
        self.fire_cd = {}     # uid игрока -> конец КД стрельбы из станка
        self.auto_cd = {}     # key станка -> до какого тика КД автострельбы

    # --- предмет-установщик -------------------------------------------------

    def make_pvo_kit(self):
        it = _make_item(Material.ANVIL, CMD_PVO, u"§8§lСтанковое ПВО «Зенит» §7(пассивное)", [
            u"§7Поставь на землю — развернётся турель.",
            u"§7ПКМ по турели — сесть за установку.",
            u"§7ЛКМ — огонь: бьёт и по пехоте (§f12 §7урона).",
            u"§7По дронам стреляет сама (точность §f50%§7),",
            u"§7пока за ней сидит стрелок.",
        ])
        m = it.getItemMeta()
        m.getPersistentDataContainer().set(KEY_PVO_KIT, PersistentDataType.STRING, u"pvo")
        it.setItemMeta(m)
        return it

    # --- АКТИВНОЕ ПВО: ручной ПЗРК -------------------------------------------

    def _pzrk_lore(self, charges):
        return [
            u"§7ЛКМ/ПКМ §7— выстрел (КД 4 сек).",
            u"§7Прямая ракета: ни захвата, ни самонаведения.",
            u"§7Попади точно в корпус дрона — он сбит.",
            u"§8Попадание по игроку: 12 урона.",
            u"§fЗарядов: §e%d/%d" % (charges, PZRK_MAX_CHARGES),
        ]

    def make_pzrk(self):
        mat = getattr(Material, "BREEZE_ROD", None)
        if mat is None:
            mat = Material.BLAZE_ROD
        it = _make_item(mat, CMD_PZRK, u"§8§lПЗРК «Игла» §7(активное ПВО)",
                         self._pzrk_lore(PZRK_MAX_CHARGES))
        m = it.getItemMeta()
        m.getPersistentDataContainer().set(KEY_TOOL, PersistentDataType.STRING, u"pzrk")
        m.getPersistentDataContainer().set(KEY_CHARGES, PersistentDataType.INTEGER,
                                           JInteger(PZRK_MAX_CHARGES))
        it.setItemMeta(m)
        return it

    def _pzrk_charges_of(self, item):
        m = item.getItemMeta()
        if m is None:
            return None
        c = _pdc_int(m, KEY_CHARGES)
        if c is None:
            c = PZRK_MAX_CHARGES   # старые экземпляры без счётчика
        return c

    def _pzrk_set_charges(self, item, charges):
        m = item.getItemMeta()
        m.getPersistentDataContainer().set(KEY_CHARGES, PersistentDataType.INTEGER,
                                           JInteger(charges))
        m.setLore(java_list(self._pzrk_lore(charges)))
        item.setItemMeta(m)

    def is_pzrk(self, item):
        if item is None:
            return False
        m = item.getItemMeta()
        return m is not None and _pdc_str(m, KEY_TOOL) == u"pzrk"

    def handle_handheld_fire(self, player):
        # выстрел из ручного ПЗРК (ЛКМ через on_animation, ПКМ через on_interact)
        item = player.getInventory().getItemInMainHand()
        if not self.is_pzrk(item):
            return False
        if is_silenced_by_demiurg(player):
            player.sendMessage(u"§5§oНеведомая сила глушит прицел...")
            return True
        # заряды
        charges = self._pzrk_charges_of(item)
        if charges is None:
            return False
        if charges <= 0:
            if check_cd(player, "pzrk_empty"):
                player.sendMessage(u"§c§lПЗРК разряжен! §7Заряды закончились.")
                _play(player, Sound.UI_BUTTON_CLICK, 0.7, 0.4)
            set_cd(player, "pzrk_empty", 20)
            return True
        if not check_cd(player, "pzrk_fire", u"§8ПЗРК «Игла»"):
            return True
        # списываем заряд
        charges -= 1
        self._pzrk_set_charges(item, charges)
        if charges == 0:
            player.sendMessage(u"§e§lЭто был последний заряд ПЗРК!")
        set_cd(player, "pzrk_fire", PZRK_CD_TICKS)
        eye = player.getEyeLocation()
        direction = eye.getDirection().normalize()

        # БЕЗ автозахвата и самонаведения: ракета летит строго по прицелу.
        muzzle = eye.clone().add(direction.clone().multiply(1.5))
        shell = player.getWorld().spawn(muzzle, Snowball)
        shell.setGravity(False)
        shell.setVelocity(direction.multiply(float(PVO_SHELL_SPEED)))
        shell.setShooter(player)
        shell.getPersistentDataContainer().set(
            KEY_SHELL, PersistentDataType.STRING, u"pzrk")
        self.shells[uid(shell)] = {"life": PVO_SHELL_LIFE, "firer": uid(player)}
        _combat_event("pzrk_fire", uid(player), player.getName(), world=player.getWorld().getName(),
                      x=muzzle.getX(), y=muzzle.getY(), z=muzzle.getZ())
        _play_at(player.getWorld(), muzzle.getX(), muzzle.getY(), muzzle.getZ(),
                 Sound.ENTITY_FIREWORK_ROCKET_LAUNCH, 0.9, 0.8)
        return True

    def is_pvo_kit(self, item):
        if item is None:
            return False
        m = item.getItemMeta()
        return m is not None and _pdc_str(m, KEY_PVO_KIT) is not None

    def _spawn_turret(self, world, pivot):
        # Спавн частей башни: BlockDisplay с масштабом, центром на пивоте.
        # Возвращает {uid: (ox, oy, oz, mode)} для раздельной кинематики.
        part_uids = {}
        transform_error_logged = False
        for (mat_name, ox, oy, oz, sx, sy, sz, mode) in self.PVO_TURRET_PARTS:
            mat = getattr(Material, mat_name, None)
            if mat is None:
                continue
            ploc = Location(world, pivot.getX() + ox, pivot.getY() + oy,
                            pivot.getZ() + oz)
            part = world.spawn(ploc, BlockDisplay)
            part.setBlock(Bukkit.createBlockData(mat))
            try:
                t = Transformation(
                    Vector3f(-float(sx) / 2.0, -float(sy) / 2.0,
                             -float(sz) / 2.0),
                    Quaternionf(),
                    Vector3f(float(sx), float(sy), float(sz)),
                    Quaternionf())
                part.setTransformation(t)
            except Exception as ex:
                part.remove()
                if not transform_error_logged:
                    _warn("PVO model transformation: " + str(ex))
                    transform_error_logged = True
                continue
            try:
                part.setTeleportDuration(2)
            except Exception:
                pass
            part.getPersistentDataContainer().set(
                KEY_PVO_DISPLAY, PersistentDataType.STRING, u"pvo_part")
            part_uids[uid(part)] = (ox, oy, oz, mode)
        return part_uids

    def refresh_loaded_models(self):
        # Старые модели пересобираются только в уже загруженных чанках. Так
        # reload не подтягивает с диска удалённые районы мира ради косметики.
        changed = False
        for key, entry in state["pvo"].items():
            try:
                if int(entry.get("model_revision", 0)) >= PVO_MODEL_REVISION:
                    continue
                world = Bukkit.getWorld(entry["world"])
                if world is None:
                    continue
                cx = int(entry["x"]) >> 4
                cz = int(entry["z"]) >> 4
                if not world.isChunkLoaded(cx, cz):
                    continue

                for puid in list((entry.get("part_uids") or {}).keys()):
                    old_part = _entity_by_uid(puid)
                    if old_part is not None:
                        old_part.remove()
                old_display = _entity_by_uid(entry.get("display_uid"))
                if old_display is not None:
                    old_display.remove()

                pivot = Location(world, entry["x"] + 0.5,
                                 entry["y"] + PVO_HEAD_H,
                                 entry["z"] + 0.5)
                entry["part_uids"] = self._spawn_turret(world, pivot)
                entry["display_uid"] = None
                entry["model_revision"] = PVO_MODEL_REVISION
                changed = True
            except Exception as ex:
                _warn("PVO model refresh " + _ascii_safe(key) + ": " + str(ex))
        if changed:
            _save()
        return changed

    def _aim_turret_at(self, entry, yaw, pitch):
        # Основание остаётся горизонтальным; тумба следует только за yaw;
        # люлька и стволы получают yaw+pitch. Старые записи из трёх координат
        # трактуются как gun, поэтому сохранённые данные остаются читаемыми.
        parts = entry.get("part_uids")
        if not parts:
            d = _entity_by_uid(entry.get("display_uid"))
            if d is not None:
                try:
                    d.setRotation(float(yaw), float(pitch))
                except Exception:
                    pass
            return
        w = Bukkit.getWorld(entry["world"])
        if w is None:
            return
        bx = entry["x"] + 0.5
        by = entry["y"] + PVO_HEAD_H
        bz = entry["z"] + 0.5
        rad = Math.toRadians(yaw)
        cs = Math.cos(rad)
        sn = Math.sin(rad)
        pr = Math.toRadians(pitch)
        pc = Math.cos(pr)
        ps = Math.sin(pr)
        for puid, off in parts.items():
            part = _entity_by_uid(puid)
            if part is None:
                continue
            if len(off) >= 4:
                ox, oy, oz, mode = off[0], off[1], off[2], off[3]
            else:
                ox, oy, oz = off
                mode = "gun"
            if mode == "base":
                wx, wy, wz = bx + ox, by + oy, bz + oz
                part_yaw, part_pitch = 0.0, 0.0
            elif mode == "yaw":
                wx = bx + ox * cs - oz * sn
                wy = by + oy
                wz = bz + ox * sn + oz * cs
                part_yaw, part_pitch = yaw, 0.0
            else:
                y1 = oy * pc - oz * ps
                z1 = oy * ps + oz * pc
                wx = bx + ox * cs - z1 * sn
                wy = by + y1
                wz = bz + ox * sn + z1 * cs
                part_yaw, part_pitch = yaw, pitch
            try:
                part.teleport(Location(w, wx, wy, wz,
                                       float(part_yaw), float(part_pitch)))
            except Exception:
                pass

    # --- развёртывание (из BlockPlaceEvent) ---------------------------------

    def handle_place(self, event):
        if not self.is_pvo_kit(event.getItemInHand()):
            return False
        block = event.getBlockPlaced()
        world = block.getWorld()
        key = _loc_key(world.getName(), block.getX(), block.getY(), block.getZ())

        # Композитная башня «Анвил» над блоком (по референсу игрока):
        # блюдце, корпус, кожух, 4 рельсы-ствола. Пивот — над наковальней.
        dloc = Location(world, block.getX() + 0.5, block.getY() + 1.25,
                        block.getZ() + 0.5)
        pivot = Location(world, block.getX() + 0.5, block.getY() + PVO_HEAD_H,
                         block.getZ() + 0.5)
        part_uids = self._spawn_turret(world, pivot)

        # невидимое сиденье (Interaction) на блоке
        sloc = Location(world, block.getX() + 0.5, block.getY() + 1.0,
                        block.getZ() + 0.5)
        seat = world.spawn(sloc, Interaction)
        seat.setInteractionWidth(0.9)
        seat.setInteractionHeight(0.6)
        seat.getPersistentDataContainer().set(KEY_PVO_SEAT, PersistentDataType.STRING, u"pvo")

        # визуальная сидушка (BlockDisplay) — удаляется вместе с установкой
        seat_visual = None
        try:
            seat_visual = world.spawn(sloc.clone().add(0.0, -0.2, 0.0), BlockDisplay)
            seat_visual.setBlock(Bukkit.createBlockData(Material.DARK_OAK_STAIRS))
            seat_visual.getPersistentDataContainer().set(
                KEY_PVO_SEAT, PersistentDataType.STRING, u"pvo_visual")
        except Exception:
            pass

        state["pvo"][key] = {
            "world": world.getName(), "x": block.getX(),
            "y": block.getY(), "z": block.getZ(),
            "display_uid": None, "seat_uid": uid(seat),
            "part_uids": part_uids,
            "model_revision": PVO_MODEL_REVISION,
            "owner_uuid": uid(event.getPlayer()),
            "owner_name": event.getPlayer().getName(),
        }
        if not _save():
            state["pvo"].pop(key, None)
            try:
                event.setCancelled(True)
            except Exception:
                pass
            for entity_uuid in list(part_uids.keys()) + [uid(seat), uid(seat_visual) if seat_visual else None]:
                ent = _entity_by_uid(entity_uuid)
                if ent is not None:
                    try:
                        ent.remove()
                    except Exception:
                        pass
            event.getPlayer().sendMessage(u"§cПВО не установлено: реестр Warfare недоступен.")
            return True
        _combat_event("pvo_place", uid(event.getPlayer()), event.getPlayer().getName(),
                      world=world.getName(), x=block.getX(), y=block.getY(), z=block.getZ())
        _play_at(world, dloc.getX(), dloc.getY(), dloc.getZ(),
                 Sound.BLOCK_ANVIL_PLACE, 0.8, 1.2)
        event.getPlayer().sendMessage(
            u"§8§lПВО развёрнуто. §7ПКМ по установке — занять место стрелка.")
        return True

    # --- посадка (из PlayerInteractEntityEvent) -----------------------------

    def handle_board(self, player, entity):
        if _pdc_str(entity, KEY_PVO_SEAT) is None:
            return False
        key, entry = self._pvo_by_seat(entity)
        if entry is None:
            player.sendMessage(u"§cЭта установка ПВО не зарегистрирована.")
            return True
        owner_uuid = entry.get("owner_uuid")
        if owner_uuid and owner_uuid != uid(player) and not _is_admin(player):
            player.sendMessage(u"§cПВО принадлежит §f%s§c." % entry.get("owner_name", u"Unknown"))
            return True
        if not entity.getPassengers().isEmpty():
            player.sendMessage(u"§7Место стрелка занято.")
            return True
        if player.isInsideVehicle():
            return True
        if is_silenced_by_demiurg(player):
            player.sendMessage(u"§5§oНеведомая сила не пускает тебя к установке...")
            return True
        entity.addPassenger(player)
        player.sendMessage(u"§8§lТы за ПВО. §7ЛКМ — огонь, Shift — сойти.")
        _play(player, Sound.UI_BUTTON_CLICK, 0.8, 1.0)
        return True

    # --- поворот и поиск ПВО по сиденью -------------------------------------

    def _pvo_by_seat(self, seat):
        su = uid(seat)
        for key, entry in state["pvo"].items():
            if entry.get("seat_uid") == su:
                return key, entry
        return None, None

    def tick_rotation(self):
        # 10 визуальных кадров/с; Display интерполирует промежуточный тик.
        if now_tick() % 2 != 0:
            return
        for key, entry in state["pvo"].items():
            seat = _entity_by_uid(entry.get("seat_uid"))
            if seat is None:
                continue
            pax = None
            for p in seat.getPassengers():
                if isinstance(p, Player):
                    pax = p
                    break
            if pax is None:
                continue
            yaw = pax.getLocation().getYaw()
            pitch = pax.getLocation().getPitch()
            if pitch < -60.0:
                pitch = -60.0
            if pitch > 45.0:
                pitch = 45.0
            # тумба получает yaw, качающаяся часть — yaw + pitch
            self._aim_turret_at(entry, yaw, pitch)

    # --- ручной выстрел (ЛКМ из on_animation) --------------------------------

    def handle_manual_fire(self, player):
        veh = player.getVehicle()
        if veh is None or _pdc_str(veh, KEY_PVO_SEAT) is None:
            return False
        u = uid(player)
        if now_tick() < self.fire_cd.get(u, 0) and \
                player.getName().lower() not in FREE_CD_PLAYERS:
            return True
        self.fire_cd[u] = now_tick() + PVO_MANUAL_CD
        eye = player.getEyeLocation()
        direction = eye.getDirection().normalize()
        muzzle = eye.clone().add(direction.clone().multiply(1.8))
        shell = player.getWorld().spawn(muzzle, Snowball)
        shell.setGravity(False)
        shell.setVelocity(direction.multiply(float(PVO_SHELL_SPEED)))
        shell.setShooter(player)
        shell.getPersistentDataContainer().set(
            KEY_SHELL, PersistentDataType.STRING, u"manual")
        self.shells[uid(shell)] = {"life": PVO_SHELL_LIFE,
                                   "firer": uid(player)}
        _combat_event("pvo_manual_fire", uid(player), player.getName(), world=player.getWorld().getName(),
                      x=muzzle.getX(), y=muzzle.getY(), z=muzzle.getZ())
        _play_at(player.getWorld(), muzzle.getX(), muzzle.getY(), muzzle.getZ(),
                 Sound.ENTITY_FIREWORK_ROCKET_BLAST, 0.9, 0.7)
        return True

    # --- полуавтомат (раз в 20 тиков) ----------------------------------------

    def tick_auto(self):
        # Автоматический режим станка выключается настройкой AUTO_PVO_ENABLED
        if not AUTO_PVO_ENABLED:
            return
        if _current_tps() < 15.0:
            return
        for key, entry in state["pvo"].items():
            seat = _entity_by_uid(entry.get("seat_uid"))
            if seat is None:
                continue
            gunner = None
            for p in seat.getPassengers():
                if isinstance(p, Player):
                    gunner = p
                    break
            if gunner is None:
                continue
            w = Bukkit.getWorld(entry["world"])
            if w is None:
                continue
            base = Location(w, entry["x"] + 0.5, entry["y"] + 1.2, entry["z"] + 0.5)
            # скан полусферы: игроки в дроне, не союзники, выше основания
            target = None
            best_d = None
            for u, sess in self.drone_mgr.sessions.items():
                cand = Bukkit.getPlayer(JUUID.fromString(u))
                if cand is None or not cand.isOnline():
                    continue
                if uid(cand) == uid(gunner) or same_team(gunner, cand):
                    continue
                cl = cand.getLocation()
                dx = cl.getX() - base.getX()
                dy = cl.getY() - base.getY()
                dz = cl.getZ() - base.getZ()
                d2 = dx * dx + dy * dy + dz * dz
                if d2 > PVO_SCAN_RADIUS * PVO_SCAN_RADIUS:
                    continue
                if dy < -3.0:
                    continue   # полусфера: цели только выше основания
                if best_d is None or d2 < best_d:
                    best_d = d2
                    target = cand
            if target is None:
                continue
            # КД автоматического выстрела — 4 секунды на установку
            if now_tick() < self.auto_cd.get(key, 0):
                continue
            self.auto_cd[key] = now_tick() + PVO_AUTO_CD
            self._auto_fire(key, entry, base, gunner, target)

    def _auto_fire(self, key, entry, base, gunner, target):
        tl = _drone_aim(target)
        to_target = tl.toVector().subtract(base.toVector())
        dist = to_target.length()
        direction = to_target.clone().normalize()

        # поворачиваем башню на цель
        yaw = Math.toDegrees(Math.atan2(-direction.getX(), direction.getZ()))
        horiz = Math.sqrt(direction.getX() * direction.getX()
                          + direction.getZ() * direction.getZ())
        pitch = Math.toDegrees(-Math.atan2(direction.getY(), horiz))
        if pitch < -60.0:
            pitch = -60.0
        if pitch > 45.0:
            pitch = 45.0
        self._aim_turret_at(entry, yaw, pitch)

        roll = _rand.nextInt(100) + 1   # 1..100
        if roll <= PVO_HIT_CHANCE:
            # точный выстрел: ЧЕСТНОЕ упреждение по замеренной скорости дрона
            # (замер — в DroneManager.tick_models). Самонаведения нет: цель
            # сманеврировала после выстрела — снаряд честно уходит мимо.
            sess = self.drone_mgr.sessions.get(uid(target))
            if sess is not None:
                flight = dist / float(PVO_SHELL_SPEED)
                lead = Vector(sess.get("vx", 0.0) * flight,
                              sess.get("vy", 0.0) * flight,
                              sess.get("vz", 0.0) * flight)
                direction = tl.toVector().add(lead) \
                    .subtract(base.toVector()).normalize()
        else:
            # промах: случайный сдвиг вектора
            offset = Vector(_rand.nextGaussian() * 0.35,
                            _rand.nextGaussian() * 0.25,
                            _rand.nextGaussian() * 0.35)
            direction = direction.add(offset).normalize()

        muzzle = base.clone().add(direction.clone().multiply(1.2)).add(0, 0.4, 0)
        w = Bukkit.getWorld(entry["world"])
        shell = w.spawn(muzzle, Snowball)
        shell.setGravity(False)
        shell.setVelocity(direction.multiply(float(PVO_SHELL_SPEED)))
        shell.getPersistentDataContainer().set(
            KEY_SHELL, PersistentDataType.STRING, u"auto")
        self.shells[uid(shell)] = {"life": PVO_SHELL_LIFE,
                                   "firer": uid(gunner)}
        _combat_event("pvo_auto_fire", uid(gunner), gunner.getName(),
                      target_uuid=uid(target), target_name=target.getName(), world=w.getName(),
                      x=muzzle.getX(), y=muzzle.getY(), z=muzzle.getZ(), details={"hit_roll": int(roll)})
        _play_at(w, muzzle.getX(), muzzle.getY(), muzzle.getZ(),
                 Sound.ENTITY_FIREWORK_ROCKET_BLAST, 1.0, 0.6)
        if roll <= PVO_HIT_CHANCE:
            _log("auto-pvo aimed shot at %s from %s" % (target.getName(), key))

    # --- полёт снаряда: прямой полёт + трейсер (каждый тик) ------------------

    def _segment_dist(self, p, v, t):
        # минимальное расстояние от точки t до отрезка [p, p+v]
        # (trajectory-aware: быстрый снаряд не может "проскочить" цель за тик)
        try:
            vx, vy, vz = v.getX(), v.getY(), v.getZ()
            vv = vx * vx + vy * vy + vz * vz
            if vv <= 0.0001:
                return p.distance(t)
            wx, wy, wz = t.getX() - p.getX(), t.getY() - p.getY(), t.getZ() - p.getZ()
            f = (wx * vx + wy * vy + wz * vz) / vv
            if f < 0.0:
                f = 0.0
            if f > 1.0:
                f = 1.0
            dx = t.getX() - (p.getX() + vx * f)
            dy = t.getY() - (p.getY() + vy * f)
            dz = t.getZ() - (p.getZ() + vz * f)
            return Math.sqrt(dx * dx + dy * dy + dz * dz)
        except Exception:
            return 999.0

    def _interceptor_strike(self, shell, su, target):
        # прямое попадание снаряда в корпус модели дрона:
        # мини-вспышка + дрон сбит (то же, что и физический хит по оператору)
        shell_meta = self.shells.pop(su, None) or {}
        loc = shell.getLocation()
        try:
            _spawn_particle(loc.getWorld(), P_FLASH, loc.getX(), loc.getY(),
                            loc.getZ(), 8, 0.15, 0.15, 0.15, 0.02)
            loc.getWorld().playSound(loc, Sound.ENTITY_FIREWORK_ROCKET_BLAST,
                                     0.7, 1.4)
        except Exception:
            pass
        shell.remove()
        if isinstance(target, Player) and uid(target) in self.drone_mgr.sessions:
            firer_uuid = shell_meta.get("firer")
            _combat_event("pvo_intercept", firer_uuid, u"PVO", uid(target), target.getName(),
                          world=loc.getWorld().getName(), x=loc.getX(), y=loc.getY(), z=loc.getZ())
            sess = self.drone_mgr.sessions[uid(target)]
            if sess["type"] == u"kamikaze":
                self.drone_mgr.detonate_kamikaze(target, "intercepted")
            else:
                self.drone_mgr.exit_drone(target, destroyed=True)
            _log("intercepted drone: " + target.getName())
        return True

    def tick_shells(self):
        if not self.shells:
            return
        for su, meta in list(self.shells.items()):
            shell = _entity_by_uid(su)
            if shell is None or not shell.isValid():
                self.shells.pop(su, None)
                continue
            meta["life"] -= 1
            if meta["life"] <= 0:
                shell.remove()
                self.shells.pop(su, None)
                continue
            loc = shell.getLocation()
            # трейсер
            try:
                _spawn_particle(shell.getWorld(), P_TRACER, loc.getX(), loc.getY(),
                                loc.getZ(), 1, 0.0, 0.0, 0.0, 0.0)
            except Exception:
                pass
            cur_v = shell.getVelocity()
            # ПРЯМОЕ ПОПАДАНИЕ ПО КОРПУСУ МОДЕЛИ (аим-ассист отсутствует):
            # снаряд сбивает дрон, только если отрезок полёта на этом тике
            # КАСАЕТСЯ силуэта — трёх точек по оси тела (ноги/плечи/голова
            # композитной модели). Проверяется отрезок, а не точка: быстрый
            # снаряд (8 бл/тик) не может "проскочить" цель телепортацией.
            # firer/team фильтруют своих.
            firer_uid = meta.get("firer")
            for u2 in list(self.drone_mgr.sessions.keys()):
                if firer_uid is not None and u2 == firer_uid:
                    continue
                tgt = Bukkit.getPlayer(JUUID.fromString(u2))
                if tgt is None or not tgt.isOnline():
                    continue
                if firer_uid is not None:
                    fp = _entity_by_uid(firer_uid)
                    if fp is not None and isinstance(fp, Player) \
                            and same_team(fp, tgt):
                        continue
                # контакт по ВИДИМЫМ частям модели (корпус, гондолы,
                # крылья): DroneManager отдаёт точки силуэта с учётом yaw
                hit = False
                for pt in self.drone_mgr.hit_test_points(tgt):
                    if self._segment_dist(loc, cur_v, pt) <= SHELL_HIT_RADIUS:
                        hit = True
                        break
                if hit:
                    self._interceptor_strike(shell, su, tgt)
                    break

    # --- попадание снаряда (из on_damage_by) ----------------------------------

    def handle_shell_hit(self, event):
        damager = event.getDamager()
        if not isinstance(damager, Snowball):
            return False
        if _pdc_str(damager, KEY_SHELL) is None:
            return False
        self.shells.pop(uid(damager), None)
        ent = event.getEntity()
        # жителей наши снаряды не задевают
        if _is_protected(ent):
            event.setCancelled(True)
            return True
        # попали в оператора дрона — дрон сбит
        if isinstance(ent, Player) and uid(ent) in self.drone_mgr.sessions:
            event.setCancelled(True)
            loc = ent.getLocation()
            try:
                _spawn_particle(ent.getWorld(), P_FLASH, loc.getX(), loc.getY() + 1.0,
                                loc.getZ(), 10, 0.2, 0.2, 0.2, 0.02)
            except Exception:
                pass
            sess = self.drone_mgr.sessions[uid(ent)]
            if sess["type"] == u"kamikaze":
                self.drone_mgr.detonate_kamikaze(ent, "shot down by pvo")
            else:
                self.drone_mgr.exit_drone(ent, destroyed=True, penalty=True)
            _log("drone shot down by pvo: " + ent.getName())
            return True
        # обычное попадание — солидный урон
        event.setDamage(PVO_SHELL_DAMAGE)
        return True

    # --- выход стрелка (EntityDismountEvent) ---------------------------------

    def handle_dismount(self, entity, dismounted):
        if _pdc_str(dismounted, KEY_PVO_SEAT) is None:
            return False
        if not isinstance(entity, Player):
            return True
        entity.sendMessage(u"§7Ты покинул установку ПВО.")
        # аккуратно ставим рядом, чтобы не застрять внутри
        key, entry = self._pvo_by_seat(dismounted)
        if entry is not None:
            w = Bukkit.getWorld(entry["world"])
            if w is not None:
                spot = Location(w, entry["x"] + 1.6, entry["y"] + 1.1, entry["z"] + 0.5)
                p_ref = entity
                loc_ref = spot
                def _tp():
                    try:
                        if p_ref.isOnline():
                            p_ref.teleport(loc_ref)
                    except Exception:
                        pass
                scheduler.runTaskLater(_tp, 1)
        return True

    # --- демонтаж (BlockBreakEvent на наковальне) ------------------------------

    def handle_break(self, event):
        block = event.getBlock()
        w = block.getWorld()
        key = _loc_key(w.getName(), block.getX(), block.getY(), block.getZ())
        entry = state["pvo"].get(key)
        if entry is None:
            return False
        player = event.getPlayer()
        owner_uuid = entry.get("owner_uuid")
        if owner_uuid and owner_uuid != uid(player) and not _is_admin(player):
            event.setCancelled(True)
            player.sendMessage(u"§cЭто ПВО принадлежит §f%s§c." % entry.get("owner_name", u"Unknown"))
            return True
        # снимаем конструкцию целиком, ванильную наковальню не дропаем
        event.setDropItems(False)
        if not self._dismantle(key, give_back=True, around=block.getLocation()):
            event.setCancelled(True)
            event.getPlayer().sendMessage(u"§cПВО не демонтировано: реестр Warfare недоступен.")
            return True
        event.getPlayer().sendMessage(u"§8§lПВО демонтировано.")
        return True

    def _dismantle(self, key, give_back, around=None):
        entry = state["pvo"].pop(key, None)
        if entry is None:
            return False
        if not _save():
            state["pvo"][key] = entry
            return False
        _combat_event("pvo_dismantle", entry.get("owner_uuid"), entry.get("owner_name"),
                      world=entry.get("world"), x=entry.get("x"), y=entry.get("y"), z=entry.get("z"),
                      details={"give_back": bool(give_back)})
        w = Bukkit.getWorld(entry["world"])
        center = None
        if w is not None:
            center = Location(w, entry["x"] + 0.5, entry["y"] + 1.0,
                              entry["z"] + 0.5)
        seat = _entity_by_uid(entry.get("seat_uid"))
        if seat is not None:
            for pax in list(seat.getPassengers()):
                try:
                    seat.removePassenger(pax)
                except Exception:
                    pass
            seat.remove()
        display = _entity_by_uid(entry.get("display_uid"))
        if display is not None:
            display.remove()
        # части композитной башни
        for puid in list((entry.get("part_uids") or {}).keys()):
            pe = _entity_by_uid(puid)
            if pe is not None:
                pe.remove()
        # сам блок-наковальню тоже убираем: clear/демонтаж не оставляет базу
        if w is not None:
            try:
                blk = w.getBlockAt(entry["x"], entry["y"], entry["z"])
                if blk.getType() == Material.ANVIL:
                    blk.setType(Material.AIR)
            except Exception:
                pass
        # дочистить сопутствующие сущности (визуальная сидушка и т.п.)
        if center is not None:
            try:
                for ent in w.getNearbyEntities(center, 2.0, 2.0, 2.0):
                    if _pdc_str(ent, KEY_PVO_SEAT) is not None:
                        ent.remove()
            except Exception:
                pass
        if give_back:
            where = around if around is not None else center
            if where is not None:
                where.getWorld().dropItemNaturally(where, self.make_pvo_kit())
        return True

    def clear_all(self):
        for key in list(state["pvo"].keys()):
            if not self._dismantle(key, give_back=False):
                return False
        return True

    def cleanup_orphans(self):
        # Смести «осиротевшие» сущности ПВО: старую спайглас-трубу
        # (ItemDisplay), Interaction-сиденье и визуальную сидушку — всё,
        # что помечено нашими ключами, но НЕ числится в реестре state["pvo"]
        # (живые установки не трогаем).
        known = set()
        for key, entry in state["pvo"].items():
            for su in (entry.get("seat_uid"), entry.get("display_uid")):
                if su is not None:
                    known.add(su)
            for puid in (entry.get("part_uids") or {}).keys():
                known.add(puid)
        removed = 0
        for w in Bukkit.getWorlds():
            for e in w.getEntities():
                if _pdc_str(e, KEY_PVO_DISPLAY) is None \
                        and _pdc_str(e, KEY_PVO_SEAT) is None:
                    continue
                if uid(e) in known:
                    continue
                try:
                    for pax in list(e.getPassengers()):
                        e.removePassenger(pax)
                except Exception:
                    pass
                e.remove()
                removed += 1
        return removed

    def keys(self):
        return list(state["pvo"].keys())

# ============================================================================
# Инициализация менеджеров
# ============================================================================

_load()

drone_mgr  = DroneManager()
mine_mgr   = MineManager()
sapper_mgr = SapperManager(mine_mgr)
pvo_mgr    = PvoManager(drone_mgr)


def recover_stale_operators():
    """Fail-safe for /pyspigot reload: end every old drone view immediately."""
    restored = 0
    for player_uuid, record in list(state.setdefault("operator_recovery", {}).items()):
        _remove_recovery_entities(record)
        try:
            player = Bukkit.getPlayer(JUUID.fromString(player_uuid))
        except Exception:
            player = None
        if player is not None and player.isOnline() and _restore_operator_record(player, record):
            restored += 1
    if restored:
        _log("restored stale online drone operators: %d" % restored)
    # Migration from older warfare.py versions that had no durable recovery map.
    # The visible ground dummy is the only reliable return point after such a reload.
    migrated_names = set()
    for world in Bukkit.getWorlds():
        for entity in list(world.getEntities()):
            owner_name = _pdc_str(entity, KEY_DUMMY_OWNER)
            if owner_name is None:
                continue
            player = Bukkit.getPlayer(owner_name)
            if (player is not None and player.isOnline() and owner_name not in migrated_names
                    and isinstance(entity, ArmorStand) and not entity.isInvisible()):
                migrated_names.add(owner_name)
                try:
                    player.setFlying(False)
                    player.setAllowFlight(False)
                    player.removePotionEffect(E_INVIS)
                    if player.getGameMode() == GameMode.ADVENTURE:
                        player.setGameMode(GameMode.SURVIVAL)
                    if A_SCALE is not None and player.getAttribute(A_SCALE) is not None:
                        player.getAttribute(A_SCALE).setBaseValue(1.0)
                    player.teleport(entity.getLocation())
                    equipment = entity.getEquipment()
                    for current, setter, source in (
                        (player.getInventory().getChestplate(), player.getInventory().setChestplate, equipment.getChestplate()),
                        (player.getInventory().getLeggings(), player.getInventory().setLeggings, equipment.getLeggings()),
                        (player.getInventory().getBoots(), player.getInventory().setBoots, equipment.getBoots())):
                        if (current is None or current.getType() == Material.AIR) and source is not None:
                            setter(source.clone())
                    player.sendMessage(u"§8§l[Warfare] §eСтарая сессия дрона аварийно завершена после обновления.")
                except Exception as ex:
                    _warn("legacy operator migration: " + str(ex))
            try:
                entity.remove()
            except Exception:
                pass


recover_stale_operators()

# soulbound: помечаем неймспейс как защищённый (предметы не выпадают при смерти)
try:
    ns = System.getProperties().get("soulbound.namespaces")
    if ns is not None:
        ns.add("warfare")
except Exception:
    pass

# ============================================================================
# Диспетчеры событий (один listener на тип события — L5)
# ============================================================================

def on_interact(event):
    # ПКМ: дрона/ПЗРК + мины (установка, снятие киркой, обезвреживание)
    try:
        if event.getHand() != EquipmentSlot.HAND:
            return
        player = event.getPlayer()
        action = event.getAction()
        item = event.getItem()

        if action in (Action.RIGHT_CLICK_AIR, Action.RIGHT_CLICK_BLOCK):
            # обезвреживание: Shift + ПКМ ножницами по замаскированной мине
            if action == Action.RIGHT_CLICK_BLOCK and player.isSneaking() \
                    and sapper_mgr.is_cutters(item):
                clicked = event.getClickedBlock()
                mkey = mine_mgr.find_key_at(clicked)
                if mkey is not None:
                    event.setCancelled(True)
                    sapper_mgr.open_defuse(player, mkey)
                    return
            # снятие СВОЕЙ мины: ПКМ любой киркой по блоку мины / полу под ней
            if action == Action.RIGHT_CLICK_BLOCK and item is not None \
                    and item.getType() in PICKAXES:
                res = mine_mgr.owner_remove(player, event.getClickedBlock())
                if res is not None:
                    event.setCancelled(True)
                    return
            # установка мины: ПКМ предметом мины по верхней грани блока
            if action == Action.RIGHT_CLICK_BLOCK \
                    and event.getBlockFace() == BlockFace.UP \
                    and mine_mgr.is_mine_item(item):
                event.setCancelled(True)
                mine_mgr.place(player, event.getClickedBlock(), item)
                return
            # инструменты не выполняют ванильных действий по блокам:
            # металлоискатель не вскапывает землю, ножницы не стригут
            if action == Action.RIGHT_CLICK_BLOCK and \
                    (sapper_mgr.is_detector(item) or sapper_mgr.is_cutters(item)):
                event.setCancelled(True)
                return
            # дрон: в сессии — выход, вне — запуск пультом
            if drone_mgr.handle_rmb(player, item):
                event.setCancelled(True)
                return
            # ПЗРК: ПКМ — выстрел (вне транспорта)
            if not player.isInsideVehicle() and pvo_mgr.handle_handheld_fire(player):
                return
    except Exception as ex:
        _warn("on_interact: " + str(ex))

listener_mgr.registerListener(on_interact, PlayerInteractEvent)


def on_animation(event):
    # ЛКМ: действия дрона → огонь станка → выстрел ПЗРК
    try:
        player = event.getPlayer()
        if drone_mgr.handle_lmb(player):
            return
        if pvo_mgr.handle_manual_fire(player):
            return
        pvo_mgr.handle_handheld_fire(player)
    except Exception as ex:
        _warn("on_animation: " + str(ex))

listener_mgr.registerListener(on_animation, PlayerAnimationEvent)


def on_move(event):
    # Только при смене блока — оптимизация
    try:
        f = event.getFrom()
        t = event.getTo()
        if t is None:
            return
        if f.getBlockX() == t.getBlockX() and f.getBlockY() == t.getBlockY() \
                and f.getBlockZ() == t.getBlockZ():
            return
        player = event.getPlayer()
        # мины: кнопка в блоке ног
        mine_mgr.check_step(player, t.getBlock())
        # столкновение камикадзе с целью
        drone_mgr.check_kamikaze_collision(player)
    except Exception as ex:
        _warn("on_move: " + str(ex))

listener_mgr.registerListener(on_move, PlayerMoveEvent)


def on_damage(event):
    try:
        ent = event.getEntity()
        # ЩИТ ВОЗВРАТА дрона: полная страховка от урона сразу после выхода
        # (кроме пустоты). Проверка — до любой другой логики урона.
        if drone_mgr.is_return_shielded(ent):
            try:
                if event.getCause() == EntityDamageEvent.DamageCause.VOID:
                    pass
                else:
                    event.setCancelled(True)
                    return
            except Exception:
                event.setCancelled(True)
                return
        # Жители неуязвимы к взрывам — любым, вообще никаким
        # (наши мины/дроны/ПВО + ванильный TNT и криперы).
        if _is_protected(ent):
            try:
                cause = event.getCause()
                if cause == EntityDamageEvent.DamageCause.ENTITY_EXPLOSION or \
                        cause == EntityDamageEvent.DamageCause.BLOCK_EXPLOSION:
                    event.setCancelled(True)
                    return
            except Exception:
                pass
        # Взрыв камикадзе не задевает оператора и его союзников
        if drone_mgr.protect_from_kamikaze_blast(event):
            return
        # Урон по летающему хитбоксу модели дрона = урон по дрону
        if drone_mgr.handle_hitbox_damage(event):
            return
        # Урон по оператору дрона = дрон уничтожен
        drone_mgr.handle_operator_damage(event)
    except Exception as ex:
        _warn("on_damage: " + str(ex))

listener_mgr.registerListener(on_damage, EntityDamageEvent)


def on_damage_by(event):
    # Попадание снаряда ПВО
    try:
        pvo_mgr.handle_shell_hit(event)
    except Exception as ex:
        _warn("on_damage_by: " + str(ex))

listener_mgr.registerListener(on_damage_by, EntityDamageByEntityEvent)


def on_block_place(event):
    # физических блоков у мины больше нет — здесь только станки ПВО
    try:
        pvo_mgr.handle_place(event)
    except Exception as ex:
        _warn("on_block_place: " + str(ex))

listener_mgr.registerListener(on_block_place, BlockPlaceEvent)


def on_block_break(event):
    # мину нельзя сломать физически (её блока нет) — здесь демонтаж ПВО
    # и защита опорного блока под установленной миной
    try:
        if pvo_mgr.handle_break(event):
            return
        mine_mgr.handle_support_break(event)
    except Exception as ex:
        _warn("on_block_break: " + str(ex))

listener_mgr.registerListener(on_block_break, BlockBreakEvent)


def on_interact_entity(event):
    # ПКМ по сиденью ПВО — посадка (фильтр руки: событие двойное main/off)
    try:
        if event.getHand() != EquipmentSlot.HAND:
            return
        pvo_mgr.handle_board(event.getPlayer(), event.getRightClicked())
    except Exception as ex:
        _warn("on_interact_entity: " + str(ex))

listener_mgr.registerListener(on_interact_entity, PlayerInteractEntityEvent)


def on_dismount(event):
    try:
        pvo_mgr.handle_dismount(event.getEntity(), event.getDismounted())
    except Exception as ex:
        _warn("on_dismount: " + str(ex))

listener_mgr.registerListener(on_dismount, EntityDismountEvent)


def on_entity_death(event):
    try:
        ent = event.getEntity()
        if isinstance(ent, ArmorStand):
            drone_mgr.handle_dummy_death(ent, event)
    except Exception as ex:
        _warn("on_entity_death: " + str(ex))

listener_mgr.registerListener(on_entity_death, EntityDeathEvent)


def on_inv_click(event):
    try:
        who = event.getWhoClicked()
        if isinstance(who, Player):
            sapper_mgr.handle_click(who, event)
    except Exception as ex:
        _warn("on_inv_click: " + str(ex))

listener_mgr.registerListener(on_inv_click, InventoryClickEvent)


def on_inv_close(event):
    try:
        who = event.getPlayer()
        if isinstance(who, Player):
            sapper_mgr.handle_close(who)
    except Exception as ex:
        _warn("on_inv_close: " + str(ex))

listener_mgr.registerListener(on_inv_close, InventoryCloseEvent)


def on_quit(event):
    try:
        drone_mgr.handle_quit(event.getPlayer())
    except Exception as ex:
        _warn("on_quit: " + str(ex))

listener_mgr.registerListener(on_quit, PlayerQuitEvent)


def on_join(event):
    try:
        drone_mgr.restore_on_join(event.getPlayer())
    except Exception as ex:
        _warn("on_join: " + str(ex))

listener_mgr.registerListener(on_join, PlayerJoinEvent)

# ============================================================================
# Таймеры (рекурсивный паттерн — runTaskTimer в PySpigot отсутствует)
# ============================================================================

def _tick_1():
    # каждый тик: поворот ПВО за взглядом, полёт снарядов, части «Шахеда»
    try:
        pvo_mgr.tick_rotation()
        pvo_mgr.tick_shells()
        drone_mgr.tick_models()
    except Exception as ex:
        _warn("tick_1: " + str(ex))
    scheduler.runTaskLater(_tick_1, 1)

def _tick_2():
    # ползунок GUI обезвреживания (интервал = скорость миниигры)
    try:
        sapper_mgr.tick()
    except Exception as ex:
        _warn("tick_2: " + str(ex))
    scheduler.runTaskLater(_tick_2, MINIGAME_STEP_TICKS)

def _tick_10():
    # каждые 10 тиков: металлоискатель + дальность управления дронами
    try:
        mine_mgr.tick_detector()
        drone_mgr.tick_range()
    except Exception as ex:
        _warn("tick_10: " + str(ex))
    scheduler.runTaskLater(_tick_10, 10)

def _tick_drone_sound():
    # Отдельный цикл: сбой/бюджет визуальной модели больше не прерывает мотор.
    try:
        drone_mgr.tick_flight_sound()
    except Exception as ex:
        _warn("tick_drone_sound: " + str(ex))
    scheduler.runTaskLater(_tick_drone_sound, DRONE_SOUND_INTERVAL_TICKS)

def _tick_20():
    # каждые 20 тиков: полуавтомат и ленивая миграция моделей ПВО
    try:
        pvo_mgr.refresh_loaded_models()
        pvo_mgr.tick_auto()
        if _combat_log_dirty[0]:
            if _save():
                _combat_log_dirty[0] = False
    except Exception as ex:
        _warn("tick_20: " + str(ex))
    scheduler.runTaskLater(_tick_20, 20)

scheduler.runTaskLater(_tick_1, 1)
scheduler.runTaskLater(_tick_2, MINIGAME_STEP_TICKS)
scheduler.runTaskLater(_tick_10, 10)
scheduler.runTaskLater(_tick_drone_sound, 1)
scheduler.runTaskLater(_tick_20, 20)

# ============================================================================
# Команда /warfare (алиас /wf)
# ============================================================================

ITEM_BUILDERS = {
    u"scout":      (lambda: drone_mgr.make_remote(u"scout"),      u"пульт дрона-разведчика"),
    u"kamikaze":   (lambda: drone_mgr.make_remote(u"kamikaze"),   u"пульт дрона-камикадзе"),
    u"mine":       (lambda: mine_mgr.make_mine_item(),            u"мина"),
    u"detector":   (lambda: sapper_mgr.make_detector(),           u"металлоискатель"),
    u"cutters":    (lambda: sapper_mgr.make_cutters(),            u"сапёрные ножницы"),
    u"pvo":        (lambda: pvo_mgr.make_pvo_kit(),               u"станковое ПВО (пассивное)"),
    u"pzrk":       (lambda: pvo_mgr.make_pzrk(),                  u"ПЗРК (активное ПВО)"),
    # русские алиасы
    u"разведчик":  (lambda: drone_mgr.make_remote(u"scout"),      u"пульт дрона-разведчика"),
    u"камикадзе":  (lambda: drone_mgr.make_remote(u"kamikaze"),   u"пульт дрона-камикадзе"),
    u"мина":       (lambda: mine_mgr.make_mine_item(),            u"мина"),
    u"детектор":   (lambda: sapper_mgr.make_detector(),           u"металлоискатель"),
    u"ножницы":    (lambda: sapper_mgr.make_cutters(),            u"сапёрные ножницы"),
    u"пво":        (lambda: pvo_mgr.make_pvo_kit(),               u"станковое ПВО (пассивное)"),
    u"пзрк":       (lambda: pvo_mgr.make_pzrk(),                  u"ПЗРК (активное ПВО)"),
}

def _cmd_help(sender):
    sender.sendMessage(u"§8§m          §r §8§l[§c§lWarfare§8§l] §8§m          ")
    sender.sendMessage(u"§7/warfare give <§fтип§7> [игрок] §8— выдать предмет")
    sender.sendMessage(u"§7  Типы: §fscout§7, §fkamikaze§7, §fmine§7, §fdetector§7,")
    sender.sendMessage(u"§7        §fcutters§7, §fpvo §8(станок)§7, §fpzrk §8(ручной)")
    sender.sendMessage(u"§7  §8(типы принимаются и по-русски: разведчик, мина, пво, пзрк...)")
    sender.sendMessage(u"§7/warfare list §8— активные мины и ПВО")
    sender.sendMessage(u"§7/warfare clear <mines|pvo> §8— снять все мины/ПВО")
    sender.sendMessage(u"§7/warfare cleanup §8— удалить осиротевшие сущности")
    sender.sendMessage(u"§7/warfare log §8— последние боевые события")
    sender.sendMessage(u"§7/warfare tps §8— TPS и текущий бюджет эффектов")
    sender.sendMessage(u"§7/warfare my §8— ваши мины и установки ПВО")
    return True


def _cmd_owned(sender):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cКоманда доступна только игроку.")
        return True
    player_uuid = uid(sender)
    mines = [(key, entry) for key, entry in state.get("mines", {}).items()
             if entry.get("owner_uuid") == player_uuid or
             (not entry.get("owner_uuid") and entry.get("owner") == sender.getName())]
    pvos = [(key, entry) for key, entry in state.get("pvo", {}).items()
            if entry.get("owner_uuid") == player_uuid]
    sender.sendMessage(u"§8§l[Warfare] §7Ваши объекты: §cмин §f%d §7| §bПВО §f%d" % (len(mines), len(pvos)))
    for key, entry in mines[:10]:
        sender.sendMessage(u"§7  мина: §f%s §8| §7%s %s %s" %
                           (entry.get("world"), entry.get("x"), entry.get("y"), entry.get("z")))
    for key, entry in pvos[:10]:
        sender.sendMessage(u"§7  ПВО: §f%s §8| §7%s %s %s" %
                           (entry.get("world"), entry.get("x"), entry.get("y"), entry.get("z")))
    return True

def cmd_warfare(*call_args):
    # PySpigot 0.9.1 вызывает команду с ТРЕМЯ аргументами (sender, label, args);
    # в старых версиях было два (sender, args). Парсим устойчиво к числу
    # и порядку: sender — первый, одиночная строка среди остальных — label
    # (пропускаем), итерируемое (Java String[]) — аргументы команды.
    if len(call_args) == 0:
        return True
    sender = call_args[0]
    args = []
    for a in call_args[1:]:
        if isinstance(a, (str, unicode)):
            continue            # label (java.lang.String -> str)
        try:
            for x in a:
                args.append(_to_unicode(x))
        except TypeError:
            pass
    sub = _norm(args[0]) if args else u"help"
    if sub in (u"my", u"owned", u"мои"):
        return _cmd_owned(sender)
    if not _is_admin(sender):
        sender.sendMessage(u"§cНедостаточно прав.")
        return True
    if len(args) == 0:
        return _cmd_help(sender)

    if sub in (u"give", u"дать", u"выдать"):
        if len(args) < 2:
            sender.sendMessage(u"§cИспользование: /warfare give <тип> [игрок]")
            return True
        itype = _norm(args[1])
        builder = ITEM_BUILDERS.get(itype)
        if builder is None:
            sender.sendMessage(u"§cНеизвестный тип: §f" + _to_unicode(args[1]))
            sender.sendMessage(u"§7Доступно: scout, kamikaze, mine, detector, cutters, pvo, pzrk")
            return True
        target = None
        if len(args) >= 3:
            target = Bukkit.getPlayer(_to_unicode(args[2]))
            if target is None:
                sender.sendMessage(u"§cИгрок не найден: §f" + _to_unicode(args[2]))
                return True
        else:
            if isinstance(sender, Player):
                target = sender
            else:
                sender.sendMessage(u"§cУкажи игрока (консоль не имеет инвентаря).")
                return True
        item = builder[0]()
        _give_or_drop(target, item)
        sender.sendMessage(u"§aВыдано: §f" + builder[1] + u" §7→ §f" + target.getName())
        if not isinstance(sender, Player) or uid(sender) != uid(target):
            target.sendMessage(u"§8§l[Warfare] §7Получено: §f" + builder[1])
        return True

    if sub in (u"list", u"список"):
        mines = mine_mgr.keys()
        pvos = pvo_mgr.keys()
        sender.sendMessage(u"§8§l[Warfare] §7Мины: §f%d §7| ПВО: §f%d §7| Дроны в воздухе: §f%d"
                           % (len(mines), len(pvos), len(drone_mgr.sessions)))
        for k in mines[:10]:
            entry = state["mines"].get(k, {})
            sender.sendMessage(u"§7    владелец: §f%s §8(%s)" %
                               (entry.get("owner_name", entry.get("owner", u"Unknown")),
                                entry.get("owner_uuid", u"legacy")))
            sender.sendMessage(u"§7  мина: §f" + k)
        for k in pvos[:10]:
            entry = state["pvo"].get(k, {})
            sender.sendMessage(u"§7    владелец: §f%s §8(%s)" %
                               (entry.get("owner_name", u"Unknown"), entry.get("owner_uuid", u"legacy")))
            sender.sendMessage(u"§7  пво:  §f" + k)
        return True

    if sub in (u"clear", u"очистить"):
        if len(args) < 2:
            sender.sendMessage(u"§cИспользование: /warfare clear <mines|pvo>")
            return True
        what = _norm(args[1])
        if what in (u"mines", u"мины"):
            n = len(mine_mgr.keys())
            if mine_mgr.clear_all():
                sender.sendMessage(u"§aСнято мин: §f%d" % n)
            else:
                sender.sendMessage(u"§cМины не сняты: реестр не удалось сохранить.")
            return True
        if what in (u"pvo", u"пво"):
            n = len(pvo_mgr.keys())
            if pvo_mgr.clear_all():
                sender.sendMessage(u"§aДемонтировано ПВО: §f%d" % n)
            else:
                sender.sendMessage(u"§cЧасть ПВО не демонтирована: реестр не удалось сохранить.")
            return True
        sender.sendMessage(u"§cИспользование: /warfare clear <mines|pvo>")
        return True

    if sub in (u"log", u"combatlog", u"журнал"):
        sender.sendMessage(u"§8§l[Warfare] §eПоследние боевые события:")
        for entry in list(reversed(state.get("combat_log", [])))[:20]:
            sender.sendMessage(u"§7  %s §8| §f%s §8→ §f%s §8| §7%s" %
                               (entry.get("kind"), entry.get("actor_name") or u"-",
                                entry.get("target_name") or u"-", entry.get("world") or u"-"))
        return True

    if sub in (u"tps", u"budget"):
        sender.sendMessage(u"§8§l[Warfare] §7TPS: §f%.2f §7| бюджет эффектов/тик: §f%d §7| использовано: §f%d" %
                           (_current_tps(), _effect_limit(), _effect_budget.get("used", 0)))
        return True

    if sub in (u"cleanup", u"чистка"):
        # сироты дронов (манекены/хитбоксы) + сироты ПВО (старая труба, кресло)
        n = drone_mgr.cleanup_orphans() + pvo_mgr.cleanup_orphans()
        sender.sendMessage(u"§aУдалено осиротевших сущностей: §f%d" % n)
        return True

    return _cmd_help(sender)

cmd_mgr.registerCommand(cmd_warfare, "warfare")
cmd_mgr.registerCommand(cmd_warfare, "wf")


def on_disable():
    # Restore online operators synchronously; offline records stay durable for PlayerJoinEvent.
    for player_uuid, record in list(state.setdefault("operator_recovery", {}).items()):
        _remove_recovery_entities(record)
        try:
            player = Bukkit.getPlayer(JUUID.fromString(player_uuid))
        except Exception:
            player = None
        if player is not None and player.isOnline():
            _restore_operator_record(player, record)
    drone_mgr.sessions.clear()
    for shell_uuid in list(pvo_mgr.shells.keys()):
        shell = _entity_by_uid(shell_uuid)
        if shell is not None:
            shell.remove()
    pvo_mgr.shells.clear()
    _save()


def stop(script=None):
    on_disable()

_log("Loaded. Drones/mines/sapper/PVO ready. Command: /warfare")

# -*- coding: utf-8 -*-
"""
==============================================================================
  АРЧЕР / Эмия Широ (Zender_Game)
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /test archer                     — выдать оба комплекта Тир I
  /test archer swords [1|2|3]      — только клинки
  /test archer bow [1|2|3]         — только лук
  /archer <ability>                — способности
      зеркало | астрал | ульт
  /archer bowtier <1|2|3>          — админ: сменить тир лука (квесты)
  /archer master <ник|clear>       — назначить/убрать Мастера
  /archer seal                     — Мастер использует "командное заклинание"
==============================================================================
"""

import pyspigot as ps

import os
import json
import codecs

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, Long as JLong
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, Color
)
from org.bukkit.entity import (
    Player, LivingEntity, Arrow, AbstractArrow
)
from org.bukkit.event.player import (
    PlayerInteractEvent, PlayerDropItemEvent, PlayerRespawnEvent,
    PlayerItemHeldEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, EntityDeathEvent,
    ProjectileLaunchEvent, ProjectileHitEvent, PlayerDeathEvent
)
from org.bukkit.event.inventory import InventoryClickEvent, InventoryCloseEvent
from org.bukkit.event.block import Action
from org.bukkit.enchantments import Enchantment
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.inventory.meta import LeatherArmorMeta
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

ARCHER_NAMES    = set([u"zender_game", u"blueredtronce"])
FREE_CD_PLAYERS = set([u"blueredtronce"])

KEY_ITEM       = NamespacedKey.fromString("archer:item")       # маркер архер-предмета
KEY_KIND       = NamespacedKey.fromString("archer:kind")       # "kanshou"|"bakuya"|"bow"|"mirror"
KEY_TIER       = NamespacedKey.fromString("archer:tier")       # int
KEY_OWNER      = NamespacedKey.fromString("archer:owner")      # uuid
KEY_ARROW      = NamespacedKey.fromString("archer:arrow")      # флаг взрывной стрелы
KEY_MIRROR_EXP = NamespacedKey.fromString("archer:mirror_expire")  # long ms

# Клинок: тир → damage HP
SWORD_DAMAGE = {1: 6.0, 2: 7.6, 3: 13.8}   # в HP (уже в единицах жизни)
# По ТЗ уровень I — стандартный урон, ставим 3 сердца (~6 HP)

SWORD_MATERIAL = {1: Material.STONE_SWORD, 2: Material.IRON_SWORD, 3: Material.NETHERITE_SWORD}
BOW_MATERIAL   = Material.BOW

# Прогресс
SWORD_TIER2_KILLS = 100
SWORD_TIER3_KILLS = 600

# Cooldowns / durations
MIRROR_SLOTS     = 4              # ребаланс: было 7
MIRROR_REGEN     = 90 * 20        # 1.5 мин на слот
MIRROR_ITEM_LIFE = 3 * 60 * 20    # 3 мин жизни созданного предмета
MIRROR_CHAIN_DUR = 15 * 20        # 15 сек баф "Магическая цепь"

ASTRAL_DUR  = 15 * 20
ASTRAL_CD   = 2 * 60 * 20

ULT_DUR         = 20 * 20
ULT_CD          = 5 * 60 * 20
ULT_RADIUS      = 10.0
ULT_TICK_DMG    = 1.0             # ребаланс: 0.5 сердца = 1 HP
ULT_TICK_PERIOD = 20              # раз в секунду (было 10 тиков)

# Стандартная прочность всего "созданного"
CRAFTED_MAX_DUR = 100

# Лук III: взрывы
BOW3_SHOOT_CD_TICKS = 3 * 20
BOW3_EXPLOSION_POWER = 1.5    # ~3×3 без блоков
BOW3_ARMOR_PIERCE = 4.0       # 2 сердца пробойного

# --- Глобальный каталог особых предметов ---------------------------------
# Живёт в System.getProperties() под ключом MIRROR_CATALOG_KEY.
# Каждый скрипт-персонаж сам публикует свои особые предметы.
#
# Формат записи (HashMap):
#     "name":    unicode  — русское название для поиска (без цвет-кодов)
#     "display": unicode  — красивое имя для чата/GUI
#     "factory": callable(owner_uuid) -> ItemStack (I тир, без спец-механик
#                                                    оригинальных легендарных свойств
#                                                    — фабрике не обязательно чистить
#                                                    PDC/атрибуты, это делает Арчер)

MIRROR_CATALOG_KEY = "archer.mirror_catalog"


def _get_catalog():
    """Возвращает глобальный HashMap каталога (создаёт при первом обращении)."""
    props = System.getProperties()
    cat = props.get(MIRROR_CATALOG_KEY)
    if cat is None:
        cat = HashMap()
        props.put(MIRROR_CATALOG_KEY, cat)
    return cat


def _publish_entry(entry_id, name, display, factory):
    """Регистрирует одну запись в каталоге (вызывается самим Арчером
       для своих же предметов; остальные скрипты используют аналогичный код)."""
    cat = _get_catalog()
    entry = HashMap()
    entry.put("name",    _to_unicode(name))
    entry.put("display", _to_unicode(display))
    entry.put("factory", factory)
    cat.put(entry_id, entry)

def _to_unicode(s):
    """Приводит что угодно к unicode без падений на не-ASCII."""
    if s is None:
        return u""
    if isinstance(s, unicode):
        return s
    if isinstance(s, str):
        # Пробуем UTF-8, потом CP-1251, потом — молча выкидываем плохие байты.
        for enc in ("utf-8", "cp1251", "latin-1"):
            try:
                return s.decode(enc)
            except Exception:
                continue
        return u""
    # Java String / любые прочие объекты.
    try:
        return unicode(s)
    except Exception:
        try:
            return unicode(str(s), "utf-8", "ignore")
        except Exception:
            return u""


def _norm(s):
    """Нормализация имени: unicode, нижний регистр, без цвет-кодов, сжатые пробелы."""
    s = _to_unicode(s)
    if not s:
        return u""
    s = s.strip().lower()
    out = []
    i = 0
    n = len(s)
    SECTION = u"\u00a7"
    while i < n:
        if s[i] == SECTION and i + 1 < n:
            i += 2
            continue
        out.append(s[i])
        i += 1
    result = u"".join(out)
    while u"  " in result:
        result = result.replace(u"  ", u" ")
    return result


def _mk_meta_copy(item, display_name, lore_lines, owner_uuid):
    """Общая обёртка: имя, лор, PDC-тег 'mirror' + владелец, прочность 100."""
    m = item.getItemMeta()
    if m is None:
        return item
    m.setDisplayName(display_name)
    m.setLore(java_list(lore_lines))
    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_ITEM,  PersistentDataType.BYTE,   JByte(1))
    pdc.set(KEY_KIND,  PersistentDataType.STRING, "mirror")
    pdc.set(KEY_OWNER, PersistentDataType.STRING, owner_uuid)
    expire_ms = System.currentTimeMillis() + MIRROR_ITEM_LIFE * 50
    pdc.set(KEY_MIRROR_EXP, PersistentDataType.LONG, JLong(expire_ms))
    _set_max_dur(m, CRAFTED_MAX_DUR)
    m.setUnbreakable(False)
    item.setItemMeta(m)
    return item


def _mirror_lore(extra_line=u""):
    lore = [
        u"§7Отражение особого предмета,",
        u"§7созданное Зеркалом Души.",
        u"§8Тир: §fI §8(минимальный)",
        u"§8Прочность: §f100§8. Живёт §f3 §8минуты.",
        u"",
        u"§8Без уникальных способностей и пассивок.",
    ]
    if extra_line:
        lore.append(u"§8" + extra_line)
    return lore


# --- Фабрики копий ---------------------------------------------------------

def _fac_archer_kanshou(owner):
    # Каншо I — каменный меч + Sharpness II (как в оригинале I тира).
    it = ItemStack(Material.STONE_SWORD, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§cКаншо")
    if ENC_SHARP is not None:
        m.addEnchant(ENC_SHARP, 2, True)
    it.setItemMeta(m)
    return it

def _fac_archer_bakuya(owner):
    it = ItemStack(Material.STONE_SWORD, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§bБакуя")
    if ENC_SHARP is not None:
        m.addEnchant(ENC_SHARP, 2, True)
    it.setItemMeta(m)
    return it

def _fac_archer_bow(owner):
    # Каладболг I — обычный лук + Power I.
    it = ItemStack(Material.BOW, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§6Каладболг")
    if ENC_POWER is not None:
        m.addEnchant(ENC_POWER, 1, True)
    it.setItemMeta(m)
    return it


# --- API поверх глобального каталога -------------------------------------

def _catalog_items():
    """Возвращает список (entry_id, entry_dict) из глобального каталога.
       Значения-HashMap приводим к dict-подобному виду через .get()."""
    cat = _get_catalog()
    result = []
    it = cat.entrySet().iterator()
    while it.hasNext():
        e = it.next()
        result.append((e.getKey(), e.getValue()))
    return result


def _find_special_key(query):
    """Возвращает entry_id (внутренний ID из каталога) по русскому названию.
       Сравнение — точное после нормализации (регистр, цвет-коды, пробелы)."""
    q = _norm(query)
    if not q:
        return None
    for entry_id, entry in _catalog_items():
        name = entry.get("name")
        if _norm(name) == q:
            return entry_id
    return None


def _get_entry(entry_id):
    """Возвращает HashMap-запись каталога по внутреннему ID (или None)."""
    if entry_id is None:
        return None
    return _get_catalog().get(entry_id)


def _entry_display(entry_id):
    e = _get_entry(entry_id)
    if e is None:
        return _to_unicode(entry_id)
    return _to_unicode(e.get("display"))


def _entry_name(entry_id):
    e = _get_entry(entry_id)
    if e is None:
        return _to_unicode(entry_id)
    return _to_unicode(e.get("name"))


# --- Хранилище изученных предметов (JSON) ---------------------------------

DATA_DIR   = os.path.join("plugins", "PySpigot", "scripts", "data")
DATA_FILE  = os.path.join(DATA_DIR, "archer_mirror.json")

# uid_of_archer -> set of canonical keys
learned = {}

def _ensure_dir():
    try:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
    except Exception as ex:
        Bukkit.getLogger().warning("[archer] mkdir: " + str(ex))

def load_learned():
    """Загружает изученные предметы из JSON.
       Мы храним НОРМАЛИЗОВАННЫЕ РУССКИЕ ИМЕНА (не entry_id), потому что каталог
       наполняется другими скриптами и на момент загрузки может быть неполным."""
    global learned
    _ensure_dir()
    if not os.path.exists(DATA_FILE):
        save_learned()
        return
    try:
        f = codecs.open(DATA_FILE, "r", "utf-8")
        raw = f.read()
        f.close()
        d = json.loads(raw)
        learned = {}
        for u, names in d.items():
            learned[u] = set([_norm(n) for n in names if _norm(n)])
    except Exception as ex:
        Bukkit.getLogger().warning("[archer] learned load: " + str(ex))

def save_learned():
    _ensure_dir()
    try:
        f = codecs.open(DATA_FILE, "w", "utf-8")
        # Конвертируем set → list для JSON
        d = {u: sorted(list(s)) for u, s in learned.items()}
        f.write(json.dumps(d, ensure_ascii=False, indent=2))
        f.close()
    except Exception as ex:
        Bukkit.getLogger().warning("[archer] learned save: " + str(ex))

def has_learned(archer, entry_id):
    """Хранение по нормализованному русскому имени, чтобы переживать
       перегенерацию entry_id между релоадами скриптов."""
    name = _norm(_entry_name(entry_id))
    return name in learned.get(uid(archer), set())

def mark_learned(archer, entry_id):
    name = _norm(_entry_name(entry_id))
    if not name:
        return
    u = uid(archer)
    if u not in learned:
        learned[u] = set()
    learned[u].add(name)
    save_learned()

def known_entry_ids(archer):
    """Возвращает список entry_id из каталога, которые сейчас известны игроку.
       Игнорирует записи, чей персонаж-скрипт не подгружен (нет фабрики)."""
    known_names = learned.get(uid(archer), set())
    if not known_names:
        return []
    result = []
    for entry_id, entry in _catalog_items():
        n = _norm(entry.get("name"))
        if n in known_names:
            result.append(entry_id)
    return result


# --- Отражения-запросы (Дар отражения) ------------------------------------
# Ключ — uid донора, значение — dict(archer_uid, item_key, expire_tick).
share_requests = {}
SHARE_REQ_TTL = 60 * 20   # 1 минута на подтверждение


# --- GUI ------------------------------------------------------------------
# Открытые GUI Зеркала: uid_arch -> Inventory
open_mirror_gui = {}


# Материалы, которые Зеркало разрешено копировать (оружие + инструменты).
MIRROR_ALLOWED = set([
    # Мечи
    Material.WOODEN_SWORD, Material.STONE_SWORD, Material.IRON_SWORD,
    Material.GOLDEN_SWORD, Material.DIAMOND_SWORD, Material.NETHERITE_SWORD,
    # Топоры
    Material.WOODEN_AXE, Material.STONE_AXE, Material.IRON_AXE,
    Material.GOLDEN_AXE, Material.DIAMOND_AXE, Material.NETHERITE_AXE,
    # Кирки
    Material.WOODEN_PICKAXE, Material.STONE_PICKAXE, Material.IRON_PICKAXE,
    Material.GOLDEN_PICKAXE, Material.DIAMOND_PICKAXE, Material.NETHERITE_PICKAXE,
    # Лопаты
    Material.WOODEN_SHOVEL, Material.STONE_SHOVEL, Material.IRON_SHOVEL,
    Material.GOLDEN_SHOVEL, Material.DIAMOND_SHOVEL, Material.NETHERITE_SHOVEL,
    # Мотыги
    Material.WOODEN_HOE, Material.STONE_HOE, Material.IRON_HOE,
    Material.GOLDEN_HOE, Material.DIAMOND_HOE, Material.NETHERITE_HOE,
    # Дистанционка / прочее оружие
    Material.BOW, Material.CROSSBOW, Material.TRIDENT, Material.MACE,
    Material.SHIELD,
    # Ножницы (полезный инструмент)
    Material.SHEARS,
    # Удочка
    Material.FISHING_ROD,
])
HEAVY_ARMOR = set([
    # Броня тяжелее кольчужной — запрещена Арчеру.
    Material.IRON_HELMET,       Material.IRON_CHESTPLATE,       Material.IRON_LEGGINGS,       Material.IRON_BOOTS,
    Material.GOLDEN_HELMET,     Material.GOLDEN_CHESTPLATE,     Material.GOLDEN_LEGGINGS,     Material.GOLDEN_BOOTS,
    Material.DIAMOND_HELMET,    Material.DIAMOND_CHESTPLATE,    Material.DIAMOND_LEGGINGS,    Material.DIAMOND_BOOTS,
    Material.NETHERITE_HELMET,  Material.NETHERITE_CHESTPLATE,  Material.NETHERITE_LEGGINGS,  Material.NETHERITE_BOOTS,
    Material.TURTLE_HELMET,
])

# Медная броня (1.21.9) — по прочности между кольчужной и железной.
# Добавляем в HEAVY_ARMOR, потому что она даёт защиту тяжелее кольчужной.
# Динамический lookup — работает и на старых версиях без медной брони.
for _n in ("COPPER_HELMET", "COPPER_CHESTPLATE", "COPPER_LEGGINGS", "COPPER_BOOTS"):
    _m = getattr(Material, _n, None)
    if _m is not None: HEAVY_ARMOR.add(_m)
try:
    del _n, _m
except NameError:
    pass


# =============================================================================
#  REGISTRY LOOKUP
# =============================================================================

def _effect(k):  return Registry.EFFECT.get(NamespacedKey.minecraft(k))
def _enchant(k): return Registry.ENCHANTMENT.get(NamespacedKey.minecraft(k))

E_HASTE       = _effect("haste")
E_NIGHT_VIS   = _effect("night_vision")
E_STRENGTH    = _effect("strength")
E_SPEED       = _effect("speed")
E_RESIST      = _effect("resistance")
E_INVIS       = _effect("invisibility")
E_SLOW_FALL   = _effect("slow_falling")
E_JUMP        = _effect("jump_boost")
E_FIRE_RES    = _effect("fire_resistance")
E_WATER_BR    = _effect("water_breathing")
E_REGEN       = _effect("regeneration")
E_INSTANT_HL  = _effect("instant_health")
E_WEAKNESS    = _effect("weakness")
E_HUNGER      = _effect("hunger")

ENC_SHARP     = _enchant("sharpness")
ENC_SMITE     = _enchant("smite")
ENC_BANE      = _enchant("bane_of_arthropods")
ENC_POWER     = _enchant("power")
ENC_PUNCH     = _enchant("punch")
ENC_FLAME     = _enchant("flame")
ENC_INFINITY  = _enchant("infinity")


# =============================================================================
#  STATE
# =============================================================================

cooldowns      = {}   # uid -> {name: end_tick}
kill_progress  = {}   # uid -> int
mirror_used    = {}   # uid -> [end_tick,...]  (окончания КД слотов)
mirror_items   = []   # список (world_name, uuid_of_item_entity) — не используется, храним по владельцу
mirror_ttl     = {}   # (owner_uid, marker_pdc) — не используется, TTL проверяем в тике

astral_active  = {}   # uid -> end_tick
ult_active     = {}   # uid -> end_tick

master_of      = {}   # servant_uid -> master_uid (у Арчера сейчас Мастер)
seals_left     = {}   # master_uid -> int (командные заклинания)

# Гвард для чистого урона
_pure_dmg_in_progress = set()


# =============================================================================
#  UTILS
# =============================================================================

def uid(e): return e.getUniqueId().toString()
def now_tick(): return long(System.currentTimeMillis() / 50)
def is_archer(p):
    name = p.getName().lower()
    if name not in ARCHER_NAMES:
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


# =============================================================================
#  ITEM CHECKS
# =============================================================================

def get_kind(item):
    if item is None or item.getType() == Material.AIR: return None
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_KIND, PersistentDataType.STRING):
        return None
    return pdc.get(KEY_KIND, PersistentDataType.STRING)

def get_tier(item):
    m = item.getItemMeta()
    if m is None: return 0
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_TIER, PersistentDataType.INTEGER): return 0
    return pdc.get(KEY_TIER, PersistentDataType.INTEGER)

def get_owner_uid(item):
    m = item.getItemMeta()
    if m is None: return None
    pdc = m.getPersistentDataContainer()
    if not pdc.has(KEY_OWNER, PersistentDataType.STRING): return None
    return pdc.get(KEY_OWNER, PersistentDataType.STRING)

def is_archer_item(item):
    return get_kind(item) is not None

def is_kanshou(item): return get_kind(item) == "kanshou"
def is_bakuya (item): return get_kind(item) == "bakuya"
def is_arc_bow(item): return get_kind(item) == "bow"
def is_mirror (item): return get_kind(item) == "mirror"

def can_wield(p, item):
    if not is_archer(p): return False
    if not is_archer_item(item): return False
    o = get_owner_uid(item)
    return o is None or o == uid(p)

def find_bow_anywhere(p):
    for it in p.getInventory().getContents():
        if is_arc_bow(it): return it
    return None

def find_sword_anywhere(p, kind):
    for it in p.getInventory().getContents():
        if get_kind(it) == kind: return it
    return None


# =============================================================================
#  BUILDERS
# =============================================================================

def _set_max_dur(meta, dur):
    """Ставит максимальную прочность через Paper 1.20.5+ API."""
    try:
        meta.setMaxDamage(dur)
    except Exception:
        pass

def create_sword(kind, tier, owner):
    """kind = 'kanshou' (Небесная кара) | 'bakuya' (Бич членистоногих)."""
    if tier < 1: tier = 1
    if tier > 3: tier = 3
    mat = SWORD_MATERIAL[tier]
    it = ItemStack(mat, 1)
    m = it.getItemMeta()
    if kind == "kanshou":
        name = u"§c§lКаншо §7§oТир " + [u"", u"I", u"II", u"III"][tier]
    else:
        name = u"§b§lБакуя §7§oТир " + [u"", u"I", u"II", u"III"][tier]
    m.setDisplayName(name)
    m.setLore(java_list([
        u"§7Один из парных клинков Арчера.",
        u"§8Урон: §f" + str(SWORD_DAMAGE[tier] / 2.0) + u"❤",
        u"§8Прочность ограничена §f100§8.",
        u"",
        u"§8Только Арчер может использовать этот клинок.",
    ]))
    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_ITEM,  PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_KIND,  PersistentDataType.STRING,  kind)
    pdc.set(KEY_TIER,  PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER, PersistentDataType.STRING,  owner)

    # Зачарования по тиру и типу.
    if tier == 1:
        if ENC_SHARP: m.addEnchant(ENC_SHARP, 2, True)
    elif tier == 2:
        if kind == "kanshou" and ENC_SMITE: m.addEnchant(ENC_SMITE, 4, True)
        if kind == "bakuya"  and ENC_BANE:  m.addEnchant(ENC_BANE,  4, True)
    else:  # 3
        if kind == "kanshou" and ENC_SMITE: m.addEnchant(ENC_SMITE, 7, True)
        if kind == "bakuya"  and ENC_BANE:  m.addEnchant(ENC_BANE,  7, True)

    _set_max_dur(m, CRAFTED_MAX_DUR)
    it.setItemMeta(m)
    return it


def create_bow(tier, owner):
    if tier < 1: tier = 1
    if tier > 3: tier = 3
    it = ItemStack(BOW_MATERIAL, 1)
    m = it.getItemMeta()
    m.setDisplayName(u"§6§lКаладболг §7§oТир " + [u"", u"I", u"II", u"III"][tier])
    lore = [
        u"§7Легендарный лук Арчера.",
        u"§8Тир: §f" + [u"", u"I", u"II", u"III"][tier],
    ]
    if tier == 1:
        lore.append(u"§8Сила I, ночное зрение владельцу.")
    elif tier == 2:
        lore.append(u"§8Отбрасывание II + Воспламенение.")
        lore.append(u"§8Урон стрелы: §f5.7❤")
    else:
        lore.append(u"§8Бесконечность, взрывные стрелы 3×3.")
        lore.append(u"§8КД между выстрелами: 3 сек.")
    lore.append(u"")
    lore.append(u"§8Только Арчер может использовать этот лук.")
    m.setLore(java_list(lore))

    pdc = m.getPersistentDataContainer()
    pdc.set(KEY_ITEM,  PersistentDataType.BYTE,    JByte(1))
    pdc.set(KEY_KIND,  PersistentDataType.STRING,  "bow")
    pdc.set(KEY_TIER,  PersistentDataType.INTEGER, tier)
    pdc.set(KEY_OWNER, PersistentDataType.STRING,  owner)

    if tier == 1:
        if ENC_POWER: m.addEnchant(ENC_POWER, 1, True)
    elif tier == 2:
        if ENC_PUNCH: m.addEnchant(ENC_PUNCH, 2, True)
        if ENC_FLAME: m.addEnchant(ENC_FLAME, 1, True)
    else:
        if ENC_INFINITY: m.addEnchant(ENC_INFINITY, 1, True)

    # Прочность: I/II — увеличена, III — Unbreakable.
    if tier == 3:
        m.setUnbreakable(True)
    elif tier == 2:
        _set_max_dur(m, 770)
    # I — стандартная прочность лука, не трогаем.

    it.setItemMeta(m)
    return it


def _sanitize_mirror(item, display_override, owner_uuid):
    """Превращает любой ItemStack (в т.ч. созданный чужой фабрикой) в
       безопасное "зеркало Арчера": срезает все PDC-теги оригинала,
       обнуляет прочность до 100, снимает Unbreakable, ставит наши маркеры
       (kind=mirror, owner, TTL). Атрибуты и зачарования сохраняются —
       по ТЗ копируются "сам предмет и его характеристики"."""
    if item is None or item.getType() == Material.AIR:
        return None
    m = item.getItemMeta()
    if m is None:
        return None

    # Срезаем ЛЮБЫЕ чужие PDC-теги (маска, посох, скипетр, эжектор, флаги других
    # персонажей). Проходим по всем ключам и удаляем.
    pdc = m.getPersistentDataContainer()
    try:
        keys = list(pdc.getKeys())
        for k in keys:
            pdc.remove(k)
    except Exception:
        pass

    # Ставим свои маркеры.
    pdc.set(KEY_ITEM,  PersistentDataType.BYTE,   JByte(1))
    pdc.set(KEY_KIND,  PersistentDataType.STRING, "mirror")
    pdc.set(KEY_OWNER, PersistentDataType.STRING, owner_uuid)
    expire_ms = System.currentTimeMillis() + MIRROR_ITEM_LIFE * 50
    pdc.set(KEY_MIRROR_EXP, PersistentDataType.LONG, JLong(expire_ms))

    # Прочность 100 и снятие Unbreakable — чтобы копия жила ограниченно.
    _set_max_dur(m, CRAFTED_MAX_DUR)
    try:
        m.setUnbreakable(False)
    except Exception:
        pass

    # Имя-приставка "Копия" (не трогая цветов оригинала).
    if display_override:
        m.setDisplayName(display_override)
    else:
        orig_name = m.getDisplayName() if m.hasDisplayName() else item.getType().name().replace("_", " ").title()
        m.setDisplayName(u"§d§lКопия §r" + _to_unicode(orig_name))

    # Заменяем лор на нашу стандартную заглушку — чтобы игрок понимал, что это копия.
    m.setLore(java_list(_mirror_lore()))

    item.setItemMeta(m)
    return item


def create_mirror_from_key(entry_id, owner_uuid):
    """Создаёт I-тир копию особого предмета по ID записи в глобальном каталоге.
       Фабрика чужого скрипта возвращает "чистый предмет I тира", Арчер поверх
       очищает всё лишнее и ставит свои маркеры (TTL, kind=mirror, owner)."""
    entry = _get_entry(entry_id)
    if entry is None:
        return None
    factory = entry.get("factory")
    if factory is None:
        return None
    try:
        raw = factory(owner_uuid)
    except Exception as ex:
        Bukkit.getLogger().warning("[archer] mirror factory '" + str(entry_id) + "': " + str(ex))
        return None
    if raw is None:
        return None
    display = _to_unicode(entry.get("display"))
    if display:
        display = u"§d§lКопия §r" + display
    return _sanitize_mirror(raw, display, owner_uuid)


# =============================================================================
#  KIT
# =============================================================================

def give_swords(player, tier=1):
    inv = player.getInventory()
    k = create_sword("kanshou", tier, uid(player))
    b = create_sword("bakuya",  tier, uid(player))
    # Каншо — main hand, Бакуя — off hand (если свободна).
    off = inv.getItemInOffHand()
    if off is None or off.getType() == Material.AIR:
        inv.setItemInOffHand(b)
    else:
        _put_in_hotbar(inv, b)
    _put_in_hotbar(inv, k)
    player.sendMessage(u"§c✦ §rКаншо и §b§lБакуя §rвыданы. §7Тир " +
                       [u"", u"I", u"II", u"III"][tier])

def give_bow(player, tier=1):
    inv = player.getInventory()
    _put_in_hotbar(inv, create_bow(tier, uid(player)))
    player.sendMessage(u"§6✦ §rКаладболг выдан. §7Тир " +
                       [u"", u"I", u"II", u"III"][tier])

def _put_in_hotbar(inv, item):
    for i in range(9):
        cur = inv.getItem(i)
        if cur is None or cur.getType() == Material.AIR:
            inv.setItem(i, item)
            return
    inv.setItem(0, item)


def kit_entry(player, args_list):
    if not is_archer(player):
        player.sendMessage(u"§cТолько Арчер может получить этот комплект.")
        return

    # Первый аргумент нормализуем через _to_unicode + .lower(), чтобы русские слова
    # не ломались.
    first = _to_unicode(args_list[0]).lower() if args_list else u""

    # /test archer list — реестр особых предметов Зеркала.
    if first in (u"list", u"список", u"реестр"):
        entries = _catalog_items()
        if not entries:
            player.sendMessage(u"§7Каталог пуст — ни один персонаж не опубликовал предметы.")
        else:
            player.sendMessage(u"§7Реестр особых предметов Зеркала Души:")
            # Сортируем по русскому имени.
            entries.sort(key=lambda x: _norm(x[1].get("name")))
            for eid, entry in entries:
                disp = _to_unicode(entry.get("display"))
                name = _to_unicode(entry.get("name"))
                player.sendMessage(u"  §f- §7" + disp + u" §8→ §f" + name)
        return

    if not args_list:
        give_swords(player, 1)
        give_bow(player, 1)
        return

    tier = 1
    if len(args_list) >= 2:
        try:
            tier = int(_to_unicode(args_list[1]))
            if tier < 1 or tier > 3: tier = 1
        except:
            tier = 1

    if first in (u"swords", u"клинки", u"мечи"):
        give_swords(player, tier)
    elif first in (u"bow", u"лук"):
        give_bow(player, tier)
    else:
        try:
            t = int(first)
            if 1 <= t <= 3:
                give_swords(player, t)
                give_bow(player, t)
                return
        except:
            pass
        player.sendMessage(u"§cИспользование: §f/test archer [swords|bow] [1..3] §7или §flist")


# =============================================================================
#  PROGRESSION
# =============================================================================

def _current_sword_tier(player):
    best = 0
    for it in player.getInventory().getContents():
        k = get_kind(it)
        if k in ("kanshou", "bakuya"):
            t = get_tier(it)
            if t > best: best = t
    return best

def _replace_sword(player, kind, new_tier):
    inv = player.getInventory()
    contents = inv.getContents()
    for i in range(len(contents)):
        if get_kind(contents[i]) == kind:
            inv.setItem(i, create_sword(kind, new_tier, uid(player)))
            return True
    # off hand?
    off = inv.getItemInOffHand()
    if get_kind(off) == kind:
        inv.setItemInOffHand(create_sword(kind, new_tier, uid(player)))
        return True
    return False

def try_upgrade_swords(player):
    cur = _current_sword_tier(player)
    if cur >= 3: return
    kills = kill_progress.get(uid(player), 0)
    target = None
    if cur < 2 and kills >= SWORD_TIER2_KILLS:
        target = 2
    if cur < 3 and kills >= SWORD_TIER3_KILLS:
        target = 3
    if target is None: return
    _replace_sword(player, "kanshou", target)
    _replace_sword(player, "bakuya",  target)
    player.sendMessage(u"§d§l✦ Парные клинки эволюционировали! §7Тир " +
                       [u"", u"I", u"II", u"III"][target])
    player.getWorld().playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)


def on_kill(event):
    victim = event.getEntity()
    killer = victim.getKiller()
    if killer is None or not isinstance(killer, Player): return
    if not is_archer(killer): return
    if isinstance(victim, Player): return   # только мобы
    u = uid(killer)
    kill_progress[u] = kill_progress.get(u, 0) + 1
    n = kill_progress[u]
    if n % 25 == 0 and _current_sword_tier(killer) < 3:
        cur = _current_sword_tier(killer)
        need = SWORD_TIER2_KILLS if cur < 2 else SWORD_TIER3_KILLS
        killer.sendActionBar(u"§7Убийств: §f" + str(n) + u"§7 / §f" + str(need))
    try_upgrade_swords(killer)


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
#  ABILITY 1 — ЗЕРКАЛО ДУШИ
# =============================================================================

def _cleanup_mirror_slots(player):
    """Убирает завершившиеся КД-слоты."""
    u = uid(player)
    lst = mirror_used.get(u, [])
    now = now_tick()
    lst = [t for t in lst if t > now]
    mirror_used[u] = lst

def _mirror_slots_used(player):
    _cleanup_mirror_slots(player)
    return len(mirror_used.get(uid(player), []))


# --- GUI Зеркала ----------------------------------------------------------

def open_mirror_gui_for(player):
    """Показывает окно 3×9: изученные предметы + инструкции."""
    known_ids = known_entry_ids(player)
    size = 27  # 3 ряда
    inv = Bukkit.createInventory(None, size, u"§d§l⌘ Зеркало Души ⌘")

    def _make_info(mat, name, lore):
        it = ItemStack(mat, 1)
        m = it.getItemMeta()
        m.setDisplayName(name)
        m.setLore(java_list(lore))
        it.setItemMeta(m)
        return it

    if not known_ids:
        empty = _make_info(Material.GRAY_STAINED_GLASS_PANE,
                           u"§7Зеркало ещё пусто",
                           [u"§8Изучи предмет: §f/archer зеркало <название>",
                            u"§8Или прими Дар отражения от другого игрока."])
        inv.setItem(13, empty)
    else:
        slots = list(range(0, 21))
        i = 0
        for entry_id in known_ids:
            if i >= len(slots): break
            entry = _get_entry(entry_id)
            if entry is None: continue
            try:
                # Иконка = чистая копия из фабрики + Арчер-санитайзинг,
                # но без TTL (чтобы GUI-иконку не съел expiry-тикер).
                icon = create_mirror_from_key(entry_id, uid(player))
                if icon is None:
                    continue
                mm = icon.getItemMeta()
                if mm is None:
                    continue
                pdc = mm.getPersistentDataContainer()
                if pdc.has(KEY_MIRROR_EXP, PersistentDataType.LONG):
                    pdc.remove(KEY_MIRROR_EXP)
                pdc.set(NamespacedKey.fromString("archer:gui_key"),
                        PersistentDataType.STRING, _to_unicode(entry_id))
                mm.setLore(java_list([
                    u"§7" + _to_unicode(entry.get("display")),
                    u"",
                    u"§eЛКМ §7— создать копию (I тир)",
                ]))
                icon.setItemMeta(mm)
            except Exception:
                continue
            inv.setItem(slots[i], icon)
            i += 1

    slots_used = _mirror_slots_used(player)
    info_lore = [
        u"§7Занято слотов: §f%d§7 / §f%d" % (slots_used, MIRROR_SLOTS),
        u"§7Копия живёт §f3 §7минуты и имеет прочность §f100§7.",
        u"",
        u"§8Копии не имеют способностей оригинала.",
    ]
    inv.setItem(22, _make_info(Material.ENDER_EYE, u"§dЗеркало Души", info_lore))
    inv.setItem(26, _make_info(Material.BARRIER, u"§cЗакрыть",
                                [u"§7Кликни, чтобы закрыть."]))

    player.openInventory(inv)
    open_mirror_gui[uid(player)] = inv


def _spawn_mirror_from_gui(player, key):
    """Создаёт копию по ключу из GUI-клика."""
    if not check_cd(player, "mirror_gate", u"«Зеркало души»"):
        return

    in_ult = uid(player) in ult_active and ult_active[uid(player)] > now_tick()

    if not in_ult:
        used = _mirror_slots_used(player)
        if used >= MIRROR_SLOTS:
            next_free = min(mirror_used[uid(player)])
            secs = (next_free - now_tick() + 19) // 20
            player.sendMessage(u"§cВсе §f%d§c слотов заняты. Следующий через §f%d§7 сек." %
                               (MIRROR_SLOTS, secs))
            return

    copy = create_mirror_from_key(key, uid(player))
    if copy is None:
        player.sendMessage(u"§cНе удалось создать копию.")
        return

    _put_in_hotbar(player.getInventory(), copy)

    if not in_ult:
        u = uid(player)
        if u not in mirror_used: mirror_used[u] = []
        mirror_used[u].append(now_tick() + MIRROR_REGEN)

    add_effect(player, E_STRENGTH, MIRROR_CHAIN_DUR, 0)
    add_effect(player, E_SPEED,    MIRROR_CHAIN_DUR, 0)
    add_effect(player, E_RESIST,   MIRROR_CHAIN_DUR, 1)
    set_cd(player, "mirror_gate", 5)

    player.getWorld().spawnParticle(Particle.ENCHANT, player.getLocation().add(0, 1, 0),
                                    40, 0.5, 0.8, 0.5, 0.6)
    player.getWorld().playSound(player.getLocation(), Sound.BLOCK_ENCHANTMENT_TABLE_USE, 0.9, 1.3)

    player.sendMessage(u"§d§l✦ Копия отражена: §r" + _entry_display(key))


def ability_mirror(player, args=None):
    """Без аргументов — открывает GUI.
       С аргументом — попытка изучить особый предмет по названию."""
    if args is None or len(args) == 0:
        open_mirror_gui_for(player)
        return

    query = u" ".join([_to_unicode(a) for a in args]).strip()
    entry_id = _find_special_key(query)
    if entry_id is None:
        player.sendMessage(u"§cТакой особый предмет не известен Зеркалу.")
        return

    if has_learned(player, entry_id):
        player.sendMessage(u"§7Предмет уже изучен: §f" + _entry_display(entry_id))
        player.sendMessage(u"§7Открой Зеркало: §f/archer зеркало")
        return

    mark_learned(player, entry_id)
    player.sendMessage(u"§d§l✦ Изучен новый особый предмет: §r" + _entry_display(entry_id))
    player.getWorld().playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 0.9, 1.4)


# Проверка истечения жизни зеркал — раз в секунду.
def _mirror_expiry_tick():
    try:
        now_ms = long(System.currentTimeMillis())
        for pl in Bukkit.getOnlinePlayers():
            inv = pl.getInventory()
            for i in range(inv.getSize()):
                it = inv.getItem(i)
                if it is None or it.getType() == Material.AIR: continue
                m = it.getItemMeta()
                if m is None: continue
                pdc = m.getPersistentDataContainer()
                if not pdc.has(KEY_MIRROR_EXP, PersistentDataType.LONG): continue
                exp = pdc.get(KEY_MIRROR_EXP, PersistentDataType.LONG)
                if now_ms >= exp:
                    inv.setItem(i, ItemStack(Material.AIR))
                    pl.getWorld().spawnParticle(Particle.SMOKE, pl.getLocation().add(0, 1, 0),
                                                8, 0.3, 0.5, 0.3, 0.02)
    except Exception as ex:
        Bukkit.getLogger().warning("[archer] mirror expiry: " + str(ex))
    scheduler.runTaskLater(_mirror_expiry_tick, 20)


# =============================================================================
#  ABILITY 2 — АСТРАЛЬНАЯ ФОРМА
# =============================================================================

def ability_astral(player):
    # В ульте недоступно.
    if uid(player) in ult_active and ult_active[uid(player)] > now_tick():
        player.sendMessage(u"§cВо время ультимейта Астральная форма недоступна.")
        return
    # Без Мастера — недоступно.
    if uid(player) not in master_of:
        player.sendMessage(u"§cБез Мастера Арчер лишён статуса Слуги. §7Астральная форма недоступна.")
        return
    if not check_cd(player, "astral", u"«Астральная форма»"):
        return

    astral_active[uid(player)] = now_tick() + ASTRAL_DUR
    dur = ASTRAL_DUR
    add_effect(player, E_INVIS,     dur, 0)
    add_effect(player, E_SLOW_FALL, dur, 0)
    add_effect(player, E_SPEED,     dur, 1)
    add_effect(player, E_JUMP,      dur, 0)
    add_effect(player, E_FIRE_RES,  dur, 0)
    add_effect(player, E_WATER_BR,  dur, 0)
    add_effect(player, E_REGEN,     dur, 1)

    set_cd(player, "astral", ASTRAL_CD)
    player.sendMessage(u"§b§l✦ Астральная форма §r§7— 15 сек.")
    player.getWorld().spawnParticle(Particle.END_ROD, player.getLocation().add(0, 1, 0),
                                    30, 0.5, 1.0, 0.5, 0.03)
    player.getWorld().playSound(player.getLocation(), Sound.BLOCK_BEACON_ACTIVATE, 0.8, 1.5)


# =============================================================================
#  ABILITY 3 — УЛЬТИМЕЙТ
# =============================================================================

def ability_ult(player):
    if not check_cd(player, "ult", u"«Мрамор реальности»"):
        return
    end = now_tick() + ULT_DUR
    ult_active[uid(player)] = end
    world = player.getWorld()
    center = player.getLocation().clone()   # копия — не двигается за игроком

    # Собираем "перенесённых" — всех живых в радиусе кроме Арчера.
    trapped = []
    for e in world.getNearbyEntities(center, ULT_RADIUS, ULT_RADIUS, ULT_RADIUS):
        if isinstance(e, LivingEntity) and not e.equals(player):
            trapped.append(e)

    # Визуал активации — эпично.
    world.spawnParticle(Particle.LARGE_SMOKE, center, 80, 5.0, 3.0, 5.0, 0.05)
    world.spawnParticle(Particle.SOUL_FIRE_FLAME, center, 60, 4.0, 2.0, 4.0, 0.05)
    try:
        world.spawnParticle(Particle.EXPLOSION_EMITTER, center, 3, 2.0, 1.0, 2.0)
    except Exception: pass
    world.playSound(center, Sound.ENTITY_ENDER_DRAGON_GROWL, 1.0, 0.5)
    world.playSound(center, Sound.ENTITY_WITHER_SPAWN, 0.9, 0.7)
    world.playSound(center, Sound.ITEM_TOTEM_USE, 1.0, 0.8)

    # Уведомление всем в радиусе 60 бл.
    for p in Bukkit.getOnlinePlayers():
        if p.getLocation().distanceSquared(center) < 60 * 60:
            p.sendTitle(u"§4§l« Мрамор Реальности »", u"§7Клинков Бесконечный Край", 10, 40, 20)

    # Уведомления захваченным.
    for t in trapped:
        if isinstance(t, Player):
            try:
                t.sendTitle(u"§4§lВы в подпространстве Арчера!",
                            u"§7Выйдите из радиуса чтобы спастись", 5, 40, 10)
            except Exception: pass

    # Баф Арчеру.
    add_effect(player, E_STRENGTH, ULT_DUR + 20, 0)
    add_effect(player, E_SPEED,    ULT_DUR + 20, 0)
    add_effect(player, E_RESIST,   ULT_DUR + 20, 1)
    # Исцеление II: Regeneration II на 10 сек.
    add_effect(player, E_REGEN,    10 * 20, 1)

    set_cd(player, "ult", ULT_CD)
    player.sendMessage(u"§4§l✦ Ад горящих идеалов §r§7— 20 сек. Клинки не иссякнут.")
    player.sendMessage(u"§8Захвачено: §f" + str(len(trapped)) + u" §8целей.")

    # BossBar для Арчера — отсчёт времени.
    bar = None
    try:
        from org.bukkit.boss import BarColor, BarStyle
        bar = Bukkit.createBossBar(u"§4§lМрамор Реальности §7— %d сек" % (ULT_DUR // 20),
                                    BarColor.RED, BarStyle.SEGMENTED_10)
        bar.addPlayer(player)
        bar.setProgress(1.0)
    except Exception:
        bar = None

    # Список тех, кто "сбежал" (для сообщений только один раз).
    escaped_uids = set()

    def dmg_tick():
        # Финал.
        if now_tick() >= end:
            ult_active.pop(uid(player), None)
            if player.isOnline():
                add_effect(player, E_WEAKNESS, 60 * 20, 0)
                add_effect(player, E_HUNGER,   60 * 20, 0)
                player.sendMessage(u"§8Ад горящих идеалов истощил Арчера — §7Слабость + Голод на 60 сек.")
            if bar is not None:
                try:
                    bar.removeAll()
                    bar.setVisible(False)
                except Exception: pass
            return

        # Обновляем BossBar.
        if bar is not None:
            try:
                remaining_ticks = max(0, end - now_tick())
                progress = float(remaining_ticks) / float(ULT_DUR)
                if progress < 0.0: progress = 0.0
                if progress > 1.0: progress = 1.0
                bar.setProgress(progress)
                bar.setTitle(u"§4§lМрамор Реальности §7— %.1f сек" % (remaining_ticks / 20.0))
            except Exception: pass

        # Проходим по захваченным.
        for t in trapped:
            if t is None or t.isDead() or not t.isValid(): continue
            try:
                d2 = t.getLocation().distanceSquared(center)
            except Exception:
                continue

            # Урон применяется ТОЛЬКО если цель в радиусе.
            if d2 <= ULT_RADIUS * ULT_RADIUS:
                if isinstance(t, LivingEntity):
                    deal_pure_damage(t, ULT_TICK_DMG, player)
                    # Небольшой визуал попадания.
                    try:
                        t.getWorld().spawnParticle(Particle.CRIT, t.getLocation().add(0, 1, 0),
                                                   5, 0.3, 0.5, 0.3, 0.02)
                    except Exception: pass
            else:
                # Цель вышла из радиуса. По дизайну — не тянем обратно
                # (кроме мобов — их вернём чтобы не разбежались).
                tu = uid(t)
                if tu not in escaped_uids and isinstance(t, Player):
                    escaped_uids.add(tu)
                    try:
                        player.sendMessage(u"§7§o" + t.getName() + u" §7вырвался из подпространства.")
                        t.sendMessage(u"§a✓ Ты вырвался из Мрамора Реальности.")
                    except Exception: pass
                elif not isinstance(t, Player):
                    # Мобов тянем обратно.
                    try: t.teleport(center)
                    except Exception: pass

        # ВИЗУАЛ КУПОЛА — кольцо из клинко-подобных частиц + портал.
        try:
            world.spawnParticle(Particle.PORTAL, center, 30, ULT_RADIUS, 3.0, ULT_RADIUS, 0.5)
        except Exception: pass
        # Вращающееся кольцо SWEEP_ATTACK (визуально — клинки Каншо/Бакуя).
        try:
            import math
            phase = float(state["tick"]) * 0.15
            steps = 8
            for i in range(steps):
                a = (2.0 * math.pi * i) / steps + phase
                x = center.getX() + ULT_RADIUS * math.cos(a)
                z = center.getZ() + ULT_RADIUS * math.sin(a)
                p = center.clone()
                p.setX(x); p.setZ(z)
                p.setY(center.getY() + 1.5)
                world.spawnParticle(Particle.SWEEP_ATTACK, p, 1, 0.0, 0.0, 0.0, 0.0)
        except Exception: pass
        # Слабый звук постоянно.
        if state["tick"] % (2 * ULT_TICK_PERIOD) == 0:
            try:
                world.playSound(center, Sound.ITEM_TRIDENT_RETURN, 0.4, 0.5)
            except Exception: pass

        state["tick"] += ULT_TICK_PERIOD
        scheduler.runTaskLater(dmg_tick, ULT_TICK_PERIOD)

    state = {"tick": 0}
    scheduler.runTaskLater(dmg_tick, ULT_TICK_PERIOD)


# =============================================================================
#  PASSIVES
# =============================================================================

def _passives_tick():
    try:
        for pl in Bukkit.getOnlinePlayers():
            if not is_archer(pl): continue

            # Спешка I когда оба клинка в руках.
            main = pl.getInventory().getItemInMainHand()
            off  = pl.getInventory().getItemInOffHand()
            mk = get_kind(main)
            ok = get_kind(off)
            paired = ((mk == "kanshou" and ok == "bakuya") or
                      (mk == "bakuya"  and ok == "kanshou"))
            if paired:
                add_effect(pl, E_HASTE, 40, 0, ambient=True, particles=False)

            # Ночное зрение если в инвентаре есть Каладболг.
            if find_bow_anywhere(pl) is not None:
                add_effect(pl, E_NIGHT_VIS, 400, 0, ambient=True, particles=False)

            # Астрал: блок урона по атаке — делаем в damage-хендлере,
            # здесь просто удаляем из astral_active, если истёк.
            if uid(pl) in astral_active and astral_active[uid(pl)] <= now_tick():
                astral_active.pop(uid(pl), None)
                pl.sendMessage(u"§7Астральная форма растворилась.")

            # Броня: проверка не тяжелее кольчужной.
            _enforce_armor(pl)
    except Exception as ex:
        Bukkit.getLogger().warning("[archer] passive tick: " + str(ex))
    scheduler.runTaskLater(_passives_tick, 20)


def _enforce_armor(player):
    inv = player.getInventory()
    slots = [
        ("helmet",     inv.getHelmet(),     inv.setHelmet),
        ("chestplate", inv.getChestplate(), inv.setChestplate),
        ("leggings",   inv.getLeggings(),   inv.setLeggings),
        ("boots",      inv.getBoots(),      inv.setBoots),
    ]
    for _, item, setter in slots:
        if item is None or item.getType() == Material.AIR: continue
        if item.getType() in HEAVY_ARMOR:
            setter(ItemStack(Material.AIR))
            # Отдаём предмет обратно в инвентарь.
            leftover = player.getInventory().addItem(item)
            if leftover:
                for drop in leftover.values():
                    player.getWorld().dropItemNaturally(player.getLocation(), drop)
            player.sendMessage(u"§cАрчер не носит броню тяжелее кольчужной.")


# =============================================================================
#  BOW: shoot handling
# =============================================================================

def on_launch(event):
    proj = event.getEntity()
    shooter = proj.getShooter()
    if not isinstance(shooter, Player): return
    bow = shooter.getInventory().getItemInMainHand()
    if not is_arc_bow(bow):
        return
    if not can_wield(shooter, bow):
        event.setCancelled(True)
        shooter.sendMessage(u"§cЛук отвергает тебя.")
        return

    tier = get_tier(bow)
    if tier == 3:
        # КД 3 сек между выстрелами.
        rem = shooter.getCooldown(BOW_MATERIAL)
        if rem > 0:
            event.setCancelled(True)
            shooter.sendMessage(u"§cПерезарядка Каладболга: §f%d§7 сек." % ((rem + 19) // 20))
            return
        # Помечаем стрелу как взрывную.
        if isinstance(proj, AbstractArrow):
            pdc = proj.getPersistentDataContainer()
            pdc.set(KEY_ARROW, PersistentDataType.BYTE, JByte(1))
            pdc.set(KEY_OWNER, PersistentDataType.STRING, uid(shooter))
        shooter.setCooldown(BOW_MATERIAL, BOW3_SHOOT_CD_TICKS)


def on_proj_hit(event):
    proj = event.getEntity()
    if not isinstance(proj, AbstractArrow): return
    pdc = proj.getPersistentDataContainer()
    if not pdc.has(KEY_ARROW, PersistentDataType.BYTE):
        return
    world = proj.getWorld()
    loc = proj.getLocation()
    # Взрыв без блоков и без огня.
    world.createExplosion(loc, BOW3_EXPLOSION_POWER, False, False)
    world.spawnParticle(Particle.EXPLOSION_EMITTER, loc, 1)

    # Пробойный урон 4 HP по прямой цели (если попал в моба/игрока).
    hit = event.getHitEntity()
    if isinstance(hit, LivingEntity):
        shooter_uid = None
        if pdc.has(KEY_OWNER, PersistentDataType.STRING):
            shooter_uid = pdc.get(KEY_OWNER, PersistentDataType.STRING)
        shooter = None
        if shooter_uid is not None:
            try:
                shooter = Bukkit.getPlayer(JUUID.fromString(shooter_uid))
            except: pass
        if shooter is not None and shooter.isOnline():
            deal_pure_damage(hit, BOW3_ARMOR_PIERCE, shooter)


# =============================================================================
#  DAMAGE / ASTRAL LOGIC
# =============================================================================

def on_damage_by(event):
    dmg = event.getDamager()
    ent = event.getEntity()

    # Астрал: Арчер не может атаковать.
    if isinstance(dmg, Player) and is_archer(dmg):
        if uid(dmg) in astral_active and astral_active[uid(dmg)] > now_tick():
            event.setCancelled(True)
            dmg.sendMessage(u"§8В Астральной форме нельзя атаковать.")
            return

    # Урон парных клинков.
    if isinstance(dmg, Player) and is_archer(dmg):
        if uid(dmg) in _pure_dmg_in_progress:
            return
        main = dmg.getInventory().getItemInMainHand()
        k = get_kind(main)
        if k in ("kanshou", "bakuya") and isinstance(ent, LivingEntity) and not ent.equals(dmg):
            tier = get_tier(main)
            # Урон нашей формулы, но пусть енчанты сработают через ваниль.
            base = SWORD_DAMAGE.get(tier, 6.0)
            # Множитель ~ base/6 — чтобы не совсем перекрыть ваниль, но подтянуть цифры.
            event.setDamage(max(event.getDamage(), base))


# =============================================================================
#  DROP / DEATH / RESPAWN / ITEM PROTECTION
# =============================================================================

def on_drop(event):
    it = event.getItemDrop().getItemStack()
    k = get_kind(it)
    if k in ("kanshou", "bakuya", "bow"):
        event.setCancelled(True)
        event.getPlayer().sendMessage(u"§cЭтот предмет нельзя выбросить.")


_need_respawn = set()

def on_death(event):
    """
    Soulbound (soulbound.py) сам обрабатывает предметы с PDC-меткой
    'archer:*' и сохраняет их со ВСЕМИ данными (включая tier).
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
    if not is_archer(player):
        return

    def _check_and_restore():
        try:
            if not player.isOnline():
                return
            # У Арчера сложный набор (мечи+лук) — если inventory пуст, восстанавливаем базу.
            if player.getInventory().isEmpty():
                give_kit(player, 1)
                player.sendMessage(u"§7[archer] Комплект восстановлен на I тире (базовый).")
        except Exception:
            pass

    scheduler.runTaskLater(_check_and_restore, 40)



def on_inv_click(event):
    top_inv = event.getView().getTopInventory()
    who = event.getWhoClicked()

    # GUI Зеркала: обрабатываем клик и полностью запрещаем перемещение.
    if isinstance(who, Player) and uid(who) in open_mirror_gui:
        gui_inv = open_mirror_gui[uid(who)]
        if top_inv is not None and top_inv.equals(gui_inv):
            # Любой клик по GUI — cancel.
            event.setCancelled(True)
            clicked = event.getClickedInventory()
            if clicked is not None and clicked.equals(gui_inv):
                cur = event.getCurrentItem()
                if cur is not None and cur.getType() != Material.AIR:
                    # Закрытие?
                    if cur.getType() == Material.BARRIER:
                        who.closeInventory()
                        return
                    # Клик по иконке изученного предмета?
                    m = cur.getItemMeta()
                    if m is not None:
                        pdc = m.getPersistentDataContainer()
                        gui_key = NamespacedKey.fromString("archer:gui_key")
                        if pdc.has(gui_key, PersistentDataType.STRING):
                            key = pdc.get(gui_key, PersistentDataType.STRING)
                            who.closeInventory()
                            _spawn_mirror_from_gui(who, key)
                            return
            return

    # Обычная защита легендарок от контейнеров.
    it = event.getCurrentItem()
    cursor = event.getCursor()
    if top_inv is None: return
    holder = top_inv.getHolder()
    if holder is not None and not isinstance(holder, Player):
        if (get_kind(it) in ("kanshou","bakuya","bow")) or (get_kind(cursor) in ("kanshou","bakuya","bow")):
            event.setCancelled(True)
            who.sendMessage(u"§cЛегендарный предмет нельзя убрать в контейнер.")


def on_inv_close(event):
    who = event.getPlayer()
    if isinstance(who, Player):
        open_mirror_gui.pop(uid(who), None)


# =============================================================================
#  COMMAND /archer
# =============================================================================

def cmd_archer(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cКоманда доступна только игрокам.")
        return True
    if not is_archer(sender):
        sender.sendMessage(u"§cТолько Арчер может использовать эту команду.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/archer <зеркало|астрал|ульт>")
        sender.sendMessage(u"  §f/archer bowtier <1..3> §8— админ-апгрейд лука")
        sender.sendMessage(u"  §f/archer master <ник|clear> §8— назначить Мастера")
        sender.sendMessage(u"  §f/archer seal §8— расход командного заклинания (для Мастера)")
        return True

    sub = _to_unicode(args[0]).lower()

    if sub in (u"зеркало", u"mirror"):
        if is_silenced_by_demiurg(sender):
            sender.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
            return True
        # /archer зеркало           — открыть GUI
        # /archer зеркало <название> — изучить
        rest = list(args[1:])
        ability_mirror(sender, rest)
        return True

    if sub in (u"астрал", u"astral"):
        if is_silenced_by_demiurg(sender):
            sender.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
            return True
        ability_astral(sender)
        return True

    if sub in (u"ульт", u"ult", u"ultimate", u"мрамор"):
        if is_silenced_by_demiurg(sender):
            sender.sendMessage(u"§8Твои способности заглушены §dЗаконом Тишины§8.")
            return True
        ability_ult(sender)
        return True

    if sub == u"bowtier":
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/archer bowtier <1..3>")
            return True
        try:
            t = int(args[1])
        except ValueError:
            sender.sendMessage(u"§cТир должен быть числом 1..3.")
            return True
        if t < 1 or t > 3:
            sender.sendMessage(u"§cДопустимые тиры: §f1§c, §f2§c, §f3§c.")
            return True
        inv = sender.getInventory()
        contents = inv.getContents()
        replaced = False
        for i in range(len(contents)):
            if is_arc_bow(contents[i]):
                inv.setItem(i, create_bow(t, uid(sender)))
                replaced = True
                break
        if not replaced:
            give_bow(sender, t)
        else:
            sender.sendMessage(u"§aЛук перекован до Тира " + [u"", u"I", u"II", u"III"][t])
        return True

    if sub == u"master":
        if len(args) < 2:
            m = master_of.get(uid(sender))
            if m is None:
                sender.sendMessage(u"§7Мастер не назначен.")
            else:
                mp = Bukkit.getPlayer(JUUID.fromString(m))
                sender.sendMessage(u"§7Мастер: §f" + (mp.getName() if mp else m))
            return True
        arg = _to_unicode(args[1]).lower()
        if arg == u"clear":
            m = master_of.pop(uid(sender), None)
            if m is not None:
                seals_left.pop(m, None)
            sender.sendMessage(u"§7Контракт с Мастером расторгнут.")
            return True
        target = Bukkit.getPlayerExact(args[1])
        if target is None or not target.isOnline():
            sender.sendMessage(u"§cИгрок не найден или оффлайн.")
            return True
        master_of[uid(sender)] = uid(target)
        seals_left[uid(target)] = 3
        sender.sendMessage(u"§d§l✦ Контракт заключён. §7Мастер: §f" + target.getName())
        target.sendMessage(u"§d§l✦ Ты стал Мастером Арчера. §7У тебя 3 командных заклинания.")
        return True

    if sub == u"seal":
        # Может использовать ТОЛЬКО текущий Мастер.
        m_uid = master_of.get(uid(sender))
        # Если сам Арчер набрал — говорим что нельзя.
        sender.sendMessage(u"§cКомандные заклинания расходует §fМастер§c командой §f/archerseal§c.")
        return True

    sender.sendMessage(u"§cНеизвестный подпункт.")
    return True


def cmd_archerseal(sender, label, args):
    """Команда для Мастера: тратит один seal и посылает RP-сообщение."""
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cТолько игрок может использовать заклинание.")
        return True
    left = seals_left.get(uid(sender), 0)
    if left <= 0:
        sender.sendMessage(u"§cУ тебя нет статуса Мастера или заклинания исчерпаны.")
        return True
    cmd_text = u" ".join(args) if args else u"«…»"
    seals_left[uid(sender)] = left - 1
    Bukkit.broadcastMessage(u"§d§l✦ КОМАНДНОЕ ЗАКЛИНАНИЕ ✦ §r§7" +
                            sender.getName() + u": §f" + cmd_text)
    # Найдём Арчера.
    for servant_uid, master_uid in list(master_of.items()):
        if master_uid == uid(sender):
            p = Bukkit.getPlayer(JUUID.fromString(servant_uid))
            if p is not None and p.isOnline():
                p.sendTitle(u"§d§lПовеление Мастера", u"§f" + cmd_text, 10, 60, 20)
                p.playSound(p.getLocation(), Sound.ITEM_TOTEM_USE, 0.8, 1.4)
    sender.sendMessage(u"§7Заклинаний осталось: §f" + str(seals_left[uid(sender)]))
    if seals_left[uid(sender)] == 0:
        # Контракт разорван.
        for servant_uid, master_uid in list(master_of.items()):
            if master_uid == uid(sender):
                master_of.pop(servant_uid, None)
        seals_left.pop(uid(sender), None)
        Bukkit.broadcastMessage(u"§8Контракт исчерпан. Мастер §f" + sender.getName() + u" §8лишился статуса.")
    return True


# =============================================================================
#  DAR OTRAZHENIYA — /archershare  /archeraccept
# =============================================================================

def _find_archer_online():
    """Возвращает первого онлайн Арчера (обычно единственный)."""
    for p in Bukkit.getOnlinePlayers():
        if is_archer(p):
            return p
    return None


def cmd_archershare(sender, label, args):
    """/archershare <название особого предмета>
       Донор добровольно делится особым предметом.
       Арчер получает запись знания после подтверждения командой /archeraccept."""
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cДоступно только игрокам.")
        return True
    if is_archer(sender):
        sender.sendMessage(u"§cАрчер не может делиться сам с собой. Используй §f/archer зеркало <название>§c для изучения.")
        return True
    if len(args) == 0:
        sender.sendMessage(u"§7Использование: §f/archershare <название особого предмета>")
        return True

    query = u" ".join([_to_unicode(a) for a in args])
    key = _find_special_key(query)
    if key is None:
        sender.sendMessage(u"§cТакого особого предмета нет в реестре.")
        return True

    archer = _find_archer_online()
    if archer is None:
        sender.sendMessage(u"§cАрчер сейчас оффлайн — некому передавать знание.")
        return True

    share_requests[uid(sender)] = {
        "archer_uid": uid(archer),
        "key": key,
        "expire": now_tick() + SHARE_REQ_TTL,
    }
    disp = _entry_display(key)
    sender.sendMessage(u"§d§l✦ Запрос отправлен §rАрчеру §7о передаче: §f" + disp)
    sender.sendMessage(u"§7Ждём подтверждения (§f1 §7минута).")
    archer.sendMessage(u"§d§l✦ Дар отражения §r§7— §f" + sender.getName() +
                       u" §7предлагает знание: §f" + disp)
    archer.sendMessage(u"§7Прими: §f/archeraccept " + sender.getName())
    archer.playSound(archer.getLocation(), Sound.BLOCK_NOTE_BLOCK_CHIME, 0.8, 1.4)
    return True


def cmd_archeraccept(sender, label, args):
    """Арчер подтверждает получение Дара отражения."""
    if not isinstance(sender, Player):
        sender.sendMessage(u"§cДоступно только игрокам.")
        return True
    if not is_archer(sender):
        sender.sendMessage(u"§cТолько Арчер может принять Дар отражения.")
        return True

    if len(args) == 0:
        # Показываем список активных запросов, адресованных нам.
        active = []
        for donor_uid, req in list(share_requests.items()):
            if req["archer_uid"] != uid(sender): continue
            if req["expire"] <= now_tick():
                share_requests.pop(donor_uid, None)
                continue
            donor = Bukkit.getPlayer(JUUID.fromString(donor_uid))
            donor_name = donor.getName() if donor is not None else u"???"
            disp = _entry_display(req["key"])
            active.append((donor_name, disp))
        if not active:
            sender.sendMessage(u"§7Нет активных предложений Дара отражения.")
            sender.sendMessage(u"§7Использование: §f/archeraccept <ник донора>")
        else:
            sender.sendMessage(u"§7Активные предложения:")
            for name, disp in active:
                sender.sendMessage(u"  §f- §7" + name + u" §8→ §r" + disp)
        return True

    donor_name = args[0]
    donor = Bukkit.getPlayerExact(donor_name)
    if donor is None:
        sender.sendMessage(u"§cИгрок не найден: §f" + donor_name)
        return True

    req = share_requests.get(uid(donor))
    if req is None or req["archer_uid"] != uid(sender):
        sender.sendMessage(u"§cОт этого игрока нет активного предложения.")
        return True
    if req["expire"] <= now_tick():
        share_requests.pop(uid(donor), None)
        sender.sendMessage(u"§cПредложение истекло.")
        return True

    key = req["key"]
    share_requests.pop(uid(donor), None)

    if has_learned(sender, key):
        sender.sendMessage(u"§7Этот предмет уже был в Зеркале.")
        return True

    mark_learned(sender, key)
    disp = _entry_display(key)
    sender.sendMessage(u"§d§l✦ Дар принят: §r" + disp)
    donor.sendMessage(u"§7Арчер принял твой дар: §f" + disp)
    sender.playSound(sender.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 0.9, 1.4)
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_archer,       "archer")
cmd_mgr.registerCommand(cmd_archerseal,   "archerseal")
cmd_mgr.registerCommand(cmd_archershare,  "archershare")
cmd_mgr.registerCommand(cmd_archeraccept, "archeraccept")

listener_mgr.registerListener(on_launch,       ProjectileLaunchEvent)
listener_mgr.registerListener(on_proj_hit,     ProjectileHitEvent)
listener_mgr.registerListener(on_damage_by,    EntityDamageByEntityEvent)
listener_mgr.registerListener(on_drop,         PlayerDropItemEvent)
listener_mgr.registerListener(on_death,        PlayerDeathEvent)
listener_mgr.registerListener(on_respawn,      PlayerRespawnEvent)
listener_mgr.registerListener(on_kill,         EntityDeathEvent)
listener_mgr.registerListener(on_inv_click,    InventoryClickEvent)
listener_mgr.registerListener(on_inv_close,    InventoryCloseEvent)

load_learned()
_passives_tick()
_mirror_expiry_tick()

# Регистрация набора в /test.
_REGISTRY_KEY = "pyspigot.character_kits"
_props = System.getProperties()
_reg = _props.get(_REGISTRY_KEY)
if _reg is None:
    _reg = HashMap()
    _props.put(_REGISTRY_KEY, _reg)
_reg.put("archer", (kit_entry, u"Арчер (клинки + лук [tier]; swords|bow)"))

# --- Публикация владельцев для admin-скрипта ---
_OWNERS_KEY = "character_owners"
_owners_reg = _props.get(_OWNERS_KEY)
if _owners_reg is None:
    _owners_reg = HashMap()
    _props.put(_OWNERS_KEY, _owners_reg)
_owners_reg.put("archer", list(ARCHER_NAMES))

# --- Публикация функции смены тира для admin-скрипта ---
def _archer_set_tier(target_player, tier):
    """У Арчера три предмета: Каншо, Бакуя (общий тир 1..3) и Каладболг (тир 1..3).
       Улучшаем сразу всё до одного и того же уровня."""
    if tier < 1 or tier > 3:
        return False
    # Мечи.
    _replace_sword(target_player, "kanshou", tier)
    _replace_sword(target_player, "bakuya",  tier)
    # Если мечей вообще не было — выдадим.
    if find_sword_anywhere(target_player, "kanshou") is None:
        give_swords(target_player, tier)
    # Лук.
    inv = target_player.getInventory()
    contents = inv.getContents()
    replaced = False
    for i in range(len(contents)):
        if is_arc_bow(contents[i]):
            inv.setItem(i, create_bow(tier, uid(target_player)))
            replaced = True
            break
    if not replaced:
        give_bow(target_player, tier)
    return True

_TIER_SETTERS_KEY = "character_tier_setters"
_tier_reg = _props.get(_TIER_SETTERS_KEY)
if _tier_reg is None:
    _tier_reg = HashMap()
    _props.put(_TIER_SETTERS_KEY, _tier_reg)
_tier_reg.put("archer", _archer_set_tier)

# --- Публикация СВОИХ предметов в глобальный каталог Зеркала ---
_publish_entry("archer:kanshou",    u"каншо",     u"§cКаншо",     _fac_archer_kanshou)
_publish_entry("archer:bakuya",     u"бакуя",     u"§bБакуя",     _fac_archer_bakuya)
_publish_entry("archer:caladbolg",  u"каладболг", u"§6Каладболг", _fac_archer_bow)

# quest_tracker: публикуем stat-функцию.
def _archer_stat(player, key):
    try:
        u = uid(player)
        if key == "kills": return int(kill_progress.get(u, 0))
    except Exception: pass
    return 0

try:
    System.getProperties().put("quest_tracker.stat.archer", _archer_stat)
except Exception: pass


Bukkit.getLogger().info("[archer] Archer loaded. Commands: /test archer, /archer, /archerseal")

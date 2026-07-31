# -_- coding: utf-8 -_-

"""

==============================================================================

  QUEST TRACKER — Единая система квестов для прогрессии тиров

  Paper 1.21 + PySpigot 0.9.1

------------------------------------------------------------------------------

  /quests              — открыть GUI своих квестов

  /quests другой_ник   — посмотреть чужой прогресс (admin)

  /quests reset ник    — сбросить квесты игрока (admin)

  /quests reload       — перечитать JSON

  Что делает:

    1. Ведёт JSON-хранилище data/quest_progress.json — счётчики per-player.

    2. Слушает EntityDeath / BlockPlace / BlockBreak / EntityDamageByEntity /

       PlayerRespawn — увеличивает счётчики соответствующих квестов.

    3. GUI показывает прогресс всех квестов текущего героя игрока.

    4. При выполнении всех условий квеста — автоматически вызывает

       character_tier_setters.<hero>(player, next_tier) из JVM-реестра.

    5. Публикует API в System.getProperties():

         "quest_tracker.increment"(quest_id, player, amount=1)

         "quest_tracker.progress"(player) -> dict

       Скрипты героев могут отправлять свои события (например Архитектор

       публикует каждый каст Кинетического Импульса).

  Категории квестов:

    * VISUAL — визуализация уже существующей прогрессии (Крис/Дум/Барсик/

      Гриблет/Посейдон/Варден/Дракон/Арчер/Стальгорн). quest_tracker их

      не обрабатывает, только читает из PDC/inventory.

    * TRACKED — новые квесты для Михока/Шанкса/Архитектора/Амон-Ра. quest_tracker

      сам считает счётчики и сохраняет в JSON.

==============================================================================

"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()

listener_mgr = ps.listener_manager()

scheduler    = ps.scheduler

import os, io, json

from java.lang import System, Byte as JByte, Long as JLong

from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (

    Bukkit, Material, NamespacedKey, Registry, Particle, Sound

)

from org.bukkit.entity import (

    Player, LivingEntity, Wither, EnderDragon, Guardian, ElderGuardian,

    Squid, Dolphin, Drowned

)

try:

    from org.bukkit.entity import Warden

except Exception:

    Warden = None

try:

    from org.bukkit.entity import GlowSquid

except Exception:

    GlowSquid = None

from org.bukkit.event.entity import (

    EntityDeathEvent, EntityDamageByEntityEvent

)

from org.bukkit.event.player import (

    PlayerRespawnEvent, PlayerJoinEvent

)

from org.bukkit.event.block import (

    BlockPlaceEvent, BlockBreakEvent

)

from org.bukkit.event.inventory import InventoryClickEvent, InventoryCloseEvent

from org.bukkit.inventory import ItemStack

from org.bukkit.persistence import PersistentDataType

# ============================================================================
#  ATTRIBUTE RESOLVER (Paper 1.21.4+ renamed GENERIC_* -> plain names)
# ============================================================================
from org.bukkit.attribute import Attribute

def _attr(name):
    for full_name in (name, "GENERIC_" + name):
        a = getattr(Attribute, full_name, None)
        if a is not None:
            return a
    return None

ATTR_MAX_HEALTH = _attr("MAX_HEALTH")

# ============================================================================

#  CONFIG

# ============================================================================

ADMIN_NAMES = set([u"blueredtronce"])

DATA_DIR = os.path.join("plugins", "PySpigot", "scripts", "data")

DATA_FILE = os.path.join(DATA_DIR, "quest_progress.json")

# GUI-теги

KEY_GUI = NamespacedKey.fromString("questtracker:gui")

# ============================================================================

#  UTILS

# ============================================================================

def uid(e):

    return e.getUniqueId().toString()

def now_tick():

    return long(System.currentTimeMillis() / 50)

def now_ms():

    return long(System.currentTimeMillis())

def _to_unicode(s):

    if s is None: return u""

    if isinstance(s, unicode): return s

    try: return unicode(s, "utf-8", "replace")

    except Exception:

        try: return unicode(s)

        except Exception: return u""

def _is_admin(sender):

    if not isinstance(sender, Player): return True

    return sender.getName().lower() in ADMIN_NAMES or sender.isOp()

def java_list(it):

    lst = ArrayList()

    for x in it: lst.add(x)

    return lst

# ============================================================================

#  STORAGE

# ============================================================================

#

# progress = {

#   "<player_uuid>": {

#       "<quest_id>": {

#           "<counter_key>": int,

#           ...

#       },

#       "meta": {

#           "kills_since_death_ms": int,

#           "last_death_ms": long,

#           "top_leader_since_ms": long | 0,

#       }

#   }

# }

progress = {}

def _load():

    global progress

    try:

        if not os.path.exists(DATA_FILE):

            progress = {}

            return

        f = io.open(DATA_FILE, "r", encoding="utf-8")

        try:

            raw = f.read()

        finally:

            f.close()

        if not raw.strip():

            progress = {}

            return

        progress = json.loads(raw)

        if not isinstance(progress, dict):

            progress = {}

        # Миграция: помечаем _completed=True для квестов, у которых все
        # шаги уже выполнены (защита от повторного title-спама после релоада
        # для игроков, которые прошли квест до этого фикса).

        try:

            for pdata in progress.values():

                if not isinstance(pdata, dict): continue

                for qid, qd in pdata.items():

                    if qid == "meta" or not isinstance(qd, dict): continue

                    if qd.get("_completed"): continue

                    # Ищем квест в реестре и проверяем needed.

                    for hero_quests in QUESTS.values():

                        for qspec in hero_quests:

                            if qspec.get("id") != qid: continue

                            if not qspec.get("tracked"): continue

                            all_done = True

                            for st in qspec.get("steps", []):

                                if qd.get(st["key"], 0) < st["needed"]:

                                    all_done = False; break

                            if all_done:

                                qd["_completed"] = True

        except Exception:

            pass

    except Exception as ex:

        Bukkit.getLogger().warning("[quest_tracker] load: " + str(ex))

        progress = {}

def _save():

    try:

        try: os.makedirs(DATA_DIR)

        except Exception: pass

        text = json.dumps(progress, ensure_ascii=False, indent=2)

        f = io.open(DATA_FILE, "w", encoding="utf-8")

        try:

            if isinstance(text, str):

                text = text.decode("utf-8", "replace")

            f.write(text)

        finally:

            f.close()

    except Exception as ex:

        Bukkit.getLogger().warning("[quest_tracker] save: " + str(ex))

def _pdata(player_uuid):

    d = progress.get(player_uuid)

    if d is None:

        d = {}

        progress[player_uuid] = d

    return d

def _qdata(player_uuid, quest_id):

    p = _pdata(player_uuid)

    q = p.get(quest_id)

    if q is None:

        q = {}

        p[quest_id] = q

    return q

def _meta(player_uuid):

    p = _pdata(player_uuid)

    m = p.get("meta")

    if m is None:

        m = {"kills_since_death_ms": 0,

             "kills_current_session": 0,

             "last_death_ms": 0,

             "no_death_streak_start_ms": now_ms(),

             "top_leader_since_ms": 0}

        p["meta"] = m

    return m

def _inc(player_uuid, quest_id, key, amount=1):

    q = _qdata(player_uuid, quest_id)

    q[key] = q.get(key, 0) + amount

# ============================================================================

#  CHARACTER DETECTION

# ============================================================================

#

# Пытаемся понять, какой персонаж у игрока. Использует character_owners

# из JVM реестра.

def _detect_hero(player):

    """Возвращает hero_id или None."""

    try:

        owners = System.getProperties().get("character_owners")

        if owners is None: return None

        nick = player.getName().lower()

        for hero_id in owners.keySet():

            lst = owners.get(hero_id)

            if lst is None: continue

            for n in lst:

                if n and n.lower() == nick and nick != u"blueredtronce":

                    return hero_id

        # blueredtronce: пробуем определить через инвентарь.

        if nick == u"blueredtronce":

            return _detect_by_inventory(player)

    except Exception:

        pass

    return None

ITEM_PDC_TO_HERO = {

    "kris:blade":         "kris",

    "doomlord:sword":     "doom",

    "demiurg:staff":      "demiurg",

    "spideragent:mask":   "spider",

    "spideragent:ejector":"spider",

    "archer:item":        "archer",

    "architect:key":      "architect",

    "mihawk:yoru":        "mihawk",

    "griblet:staff":      "griblet",

    "barsik:claws":       "barsik",

    "shanks:griffon":     "shanks",

    "poseidon:trident":   "poseidon",

    "warden:pick":        "warden",

    "dragon:eye":         "dragon",

    "amonra:nur":         "amonra",

    "steelgorn:axe":      "steelgorn",

    "wendy:wind_charge":  "wendy",

}

def _detect_by_inventory(player):

    try:

        inv = player.getInventory()

        items = list(inv.getContents())

        try:

            items.append(inv.getItemInOffHand())

        except Exception: pass

        for it in items:

            if it is None: continue

            m = it.getItemMeta()

            if m is None: continue

            pdc = m.getPersistentDataContainer()

            for keystr, hero_id in ITEM_PDC_TO_HERO.items():

                k = NamespacedKey.fromString(keystr)

                if pdc.has(k, PersistentDataType.BYTE):

                    return hero_id

    except Exception: pass

    return None

def _get_tier_from_inventory(player, hero_id):

    """Читает тир текущего предмета в инвентаре."""

    tier_key_by_hero = {

        "kris":       "kris:tier",

        "doom":       "doomlord:tier",

        "archer":     "archer:tier",

        "architect":  "architect:tier",

        "mihawk":     "mihawk:tier",

        "griblet":    "griblet:tier",

        "barsik":     "barsik:tier",

        "shanks":     "shanks:tier",

        "poseidon":   "poseidon:tier",

        "warden":     "warden:tier",

        "dragon":     "dragon:tier",

        "steelgorn":  "steelgorn:tier",

        "amonra":     "amonra:tier",

    }

    tk = tier_key_by_hero.get(hero_id)

    if tk is None: return None

    try:

        inv = player.getInventory()

        for it in inv.getContents():

            if it is None: continue

            m = it.getItemMeta()

            if m is None: continue

            pdc = m.getPersistentDataContainer()

            k = NamespacedKey.fromString(tk)

            if pdc.has(k, PersistentDataType.INTEGER):

                return pdc.get(k, PersistentDataType.INTEGER)

    except Exception: pass

    return None

def _has_hero_item_in_hand(player, hero_pdc_prefix):

    """Проверяет, что в основной руке предмет героя (по префиксу PDC-ключа)."""

    try:

        it = player.getInventory().getItemInMainHand()

        if it is None: return False

        m = it.getItemMeta()

        if m is None: return False

        pdc = m.getPersistentDataContainer()

        # Ищем любой ключ с этим префиксом (обычно есть флаг типа "kris:blade").

        for keystr, hero_id in ITEM_PDC_TO_HERO.items():

            if keystr.startswith(hero_pdc_prefix):

                k = NamespacedKey.fromString(keystr)

                if pdc.has(k, PersistentDataType.BYTE):

                    return True

    except Exception: pass

    return False

# ============================================================================

#  QUEST DEFINITIONS

# ============================================================================

#

# Формат:

#   quests_by_hero[hero_id] = [

#     {

#       "id":        "unique_id",

#       "tier_from": 1,          # с какого тира ведёт

#       "tier_to":   2,          # к какому

#       "name":      u"...",

#       "icon":      Material.X,

#       "tracked":   True|False, # True = quest_tracker считает, False = VISUAL

#       "steps": [

#         {"key": "counter_key", "needed": N, "label": u"...", "src": "pdc"|"tracked"|"inv"}

#       ],

#     }, ...

#   ]

def _q(hero_id, qid, tier_from, tier_to, name, icon, tracked, steps):

    return {

        "hero": hero_id, "id": qid,

        "tier_from": tier_from, "tier_to": tier_to,

        "name": name, "icon": icon,

        "tracked": tracked, "steps": steps,

    }

def _s(key, needed, label, src="tracked"):

    return {"key": key, "needed": needed, "label": label, "src": src}

# --- Определения --------------------------------------------------------

QUESTS = {}

# Крис: VISUAL — рецепты. Показываем через сравнение с текущим инвентарём.

QUESTS["kris"] = [

    _q("kris", "kris_t2", 1, 2, u"Восстановленный клинок", Material.IRON_SWORD, False, [

        _s("iron_ingot", 16, u"Железные слитки", src="inv"),

        _s("redstone",    8, u"Красная пыль",    src="inv"),

        _s("diamond",     1, u"Алмаз",           src="inv"),

    ]),

    _q("kris", "kris_t3", 2, 3, u"Светлый клинок", Material.DIAMOND_SWORD, False, [

        _s("diamond",  8,  u"Алмазы",    src="inv"),

        _s("obsidian", 16, u"Обсидиан",  src="inv"),

        _s("quartz",   4,  u"Кварц",     src="inv"),

    ]),

    _q("kris", "kris_t4", 3, 4, u"Тёмный клинок", Material.NETHERITE_SWORD, False, [

        _s("netherite_ingot", 1,  u"Незерит",   src="inv"),

        _s("gold_ingot",      16, u"Золото",    src="inv"),

        _s("ancient_debris",  8,  u"Обломки",   src="inv"),

    ]),

    _q("kris", "kris_t5", 4, 5, u"Истинный клинок", Material.NETHERITE_SWORD, False, [

        _s("netherite_ingot", 2, u"Незерит",   src="inv"),

        _s("heart_of_the_sea",1, u"Сердце моря", src="inv"),

        _s("xp_levels",       32,u"Уровни XP", src="xp"),

    ]),

]

# Doom: VISUAL — kills. Читаем из скрипта doom_lord через API (пока PDC не завёл).

QUESTS["doom"] = [

    _q("doom", "doom_t2", 1, 2, u"Ученик Латверии", Material.DIAMOND_SWORD, False, [

        _s("mobs",    500, u"Мобов убить",     src="doom_stat"),

        _s("players", 15,  u"Игроков убить",   src="doom_stat"),

    ]),

    _q("doom", "doom_t3", 2, 3, u"Мастер магии", Material.NETHERITE_SWORD, False, [

        _s("wither", 1, u"Убить Иссушителя", src="doom_stat"),

    ]),

]

# Spider — прогрессии нет по дизайну.

QUESTS["spider"] = []

# Archer: kills мечом.

QUESTS["archer"] = [

    _q("archer", "archer_t2", 1, 2, u"Опытный лучник", Material.IRON_SWORD, False, [

        _s("kills", 100, u"Убийств мечом", src="archer_stat"),

    ]),

    _q("archer", "archer_t3", 2, 3, u"Мастер клинков", Material.NETHERITE_SWORD, False, [

        _s("kills", 600, u"Убийств мечом", src="archer_stat"),

    ]),

]

# ==== Architect — НОВЫЕ КВЕСТЫ (tracked=True) ============================

QUESTS["architect"] = [

    _q("architect", "arch_t2", 1, 2, u"Мастер над материей",

       Material.STONE, True, [

        _s("blocks_placed", 500, u"Разместить блоки"),

        _s("blocks_broken", 500, u"Сломать блоки"),

    ]),

    _q("architect", "arch_t3", 2, 3, u"Инженер города",

       Material.OBSIDIAN, True, [

        _s("pulse_casts", 100, u"Кастов Кинетического Импульса"),

    ]),

]

# ==== Mihawk — НОВЫЕ КВЕСТЫ ==============================================

QUESTS["mihawk"] = [

    _q("mihawk", "mihawk_t2", 1, 2, u"Путь одиночки",

       Material.IRON_SWORD, True, [

        _s("solo_kills", 50, u"Solo-килов Ёру"),

    ]),

    _q("mihawk", "mihawk_t3", 2, 3, u"Судьба дуэлянта",

       Material.DIAMOND_SWORD, True, [

        _s("duels_won", 10, u"Чистых дуэлей 1-на-1"),

    ]),

    _q("mihawk", "mihawk_t4", 3, 4, u"Убийца боссов",

       Material.NETHERITE_SWORD, True, [

        _s("boss_kills", 1, u"Убить босса (MaxHP>=100)"),

    ]),

    _q("mihawk", "mihawk_t5", 4, 5, u"Величайший мечник",

       Material.NETHERITE_SWORD, True, [

        _s("great_slash_5plus", 1, u"Великий Разрез задел 5+"),

    ]),

]

# ==== Shanks — НОВЫЕ КВЕСТЫ ==============================================

QUESTS["shanks"] = [

    _q("shanks", "shanks_t2", 1, 2, u"Пират-новичок",

       Material.STONE_SWORD, True, [

        _s("pvp_kills", 20, u"PvP-убийств"),

    ]),

    _q("shanks", "shanks_t3", 2, 3, u"Морской воин",

       Material.PRISMARINE_SHARD, True, [

        _s("sea_kills", 30, u"Морских существ"),

    ]),

    _q("shanks", "shanks_t4", 3, 4, u"Легенда пиратов",

       Material.GOLD_INGOT, True, [

        _s("no_death_min", 60, u"Минут без смерти"),

        _s("no_death_kills", 5, u"PvP-килов за это время"),

    ]),

    _q("shanks", "shanks_t5", 4, 5, u"Император морей",

       Material.NETHER_STAR, True, [

        _s("top_leader_hours", 24, u"Часов топ-1 по PvP"),

    ]),

    _q("shanks", "shanks_t6", 5, 6, u"Йонко",

       Material.NETHERITE_SWORD, True, [

        _s("legendary_kill", 1, u"Убить владельца легендарного оружия T-max"),

    ]),

]

# Griblet: VISUAL (T2) + Ресурсы (T3).

QUESTS["griblet"] = [

    _q("griblet", "griblet_t2", 1, 2, u"Ученик болота", Material.LILY_PAD, False, [

        _s("slimes",     40, u"Слизней убить", src="griblet_stat"),

        _s("mud_placed", 32, u"Грязи разместить", src="griblet_stat"),

    ]),

    _q("griblet", "griblet_t3", 2, 3, u"Страж болот", Material.SLIME_BLOCK, False, [

        _s("slime_block",    64, u"Слайм-блоки", src="inv"),

        _s("netherite_block", 2, u"Незер-блоки", src="inv"),

        _s("diamond",        64, u"Алмазы",       src="inv"),

    ]),

]

# Barsik: ресурсы.

QUESTS["barsik"] = [

    _q("barsik", "barsik_t2", 1, 2, u"Молодой хищник", Material.COD, False, [

        _s("cod", 16, u"Треска", src="inv"),

    ]),

    _q("barsik", "barsik_t3", 2, 3, u"Охотник", Material.DIAMOND, False, [

        _s("diamond", 3, u"Алмазы", src="inv"),

    ]),

    _q("barsik", "barsik_t4", 3, 4, u"Альфа", Material.ENDER_EYE, False, [

        _s("ender_eye", 5, u"Глаза края", src="inv"),

    ]),

    _q("barsik", "barsik_t5", 4, 5, u"Легенда", Material.CRYING_OBSIDIAN, False, [

        _s("crying_obsidian", 2, u"Плачущий обсидиан", src="inv"),

    ]),

]

# Poseidon: сложные квесты, читаем из скрипта Poseidon.

QUESTS["poseidon"] = [

    _q("poseidon", "poseidon_t2", 1, 2, u"Сокровищница океанов",

       Material.HEART_OF_THE_SEA, False, [

        _s("heart_of_the_sea",   1, u"Сердце моря", src="inv"),

        _s("nautilus_shell",     8, u"Наутилус",    src="inv"),

        _s("sponge",             1, u"Губка",       src="inv"),

        _s("sea_lantern",        6, u"Морские лампы", src="inv"),

        _s("music_disc_mellohi", 1, u"Диск Mellohi", src="inv"),

        _s("music_disc_wait",    1, u"Диск Wait",    src="inv"),

    ]),

    _q("poseidon", "poseidon_t3", 2, 3, u"Владыка морей",

       Material.TRIDENT, False, [

        _s("prismarine_placed",  36, u"Призмарин разместить", src="poseidon_stat"),

        _s("sea_lantern_placed", 6,  u"Лампы разместить",    src="poseidon_stat"),

        _s("elder_guardians",    4,  u"Старших стражей",     src="poseidon_stat"),

        _s("guardians",          32, u"Стражей",             src="poseidon_stat"),

        _s("buried_treasure",    2,  u"Открыть сокровища",   src="poseidon_stat"),

    ]),

]

# Warden: блоки.

QUESTS["warden"] = [

    _q("warden", "warden_t2", 1, 2, u"Ученик Скалка", Material.SCULK, False, [

        _s("blocks", 200, u"Скалк-блоки сломать", src="warden_stat"),

    ]),

    _q("warden", "warden_t3", 2, 3, u"Голос Глубин", Material.SCULK_CATALYST, False, [

        _s("blocks", 1000, u"Скалк-блоки сломать", src="warden_stat"),

    ]),

]

# Dragon: прочность. Специфика: нужно pct < threshold, а движок сравнивает

# cur >= needed. Поэтому храним "потери прочности" = 100 - pct, и needed = 100 - threshold.

# Т.е. для T2: нужен pct < 20 → нужно "damage_amount >= 80".

QUESTS["dragon"] = [

    _q("dragon", "dragon_t2", 1, 2, u"Пробуждение Ока", Material.DRAGON_HEAD, False, [

        _s("damage_amount", 80, u"Изношено Ока (нужно >80%)", src="dragon_stat"),

    ]),

    _q("dragon", "dragon_t3", 2, 3, u"Драконье наследие", Material.DRAGON_EGG, False, [

        _s("damage_amount", 90, u"Изношено Ока (нужно >90%)", src="dragon_stat"),

    ]),

]

# Steelgorn: убийства + древесина.

QUESTS["steelgorn"] = [

    _q("steelgorn", "steelgorn_t2", 1, 2, u"Пробуждение", Material.DIAMOND_AXE, False, [

        _s("mobs", 200, u"Убить мобов", src="steelgorn_stat"),

        _s("wood", 300, u"Добыть дерева", src="steelgorn_stat"),

    ]),

    _q("steelgorn", "steelgorn_t3", 2, 3, u"Наследие", Material.NETHERITE_AXE, False, [

        _s("mobs", 300, u"Убить мобов", src="steelgorn_stat"),

        _s("wood", 500, u"Добыть дерева", src="steelgorn_stat"),

    ]),

]

# Демиург, Гето, Шаман, Амон-Ра, Венди — квестов нет.

QUESTS["demiurg"] = []

QUESTS["geto"]    = []

QUESTS["shaman"]  = []

# Амон-Ра: тематические квесты вокруг "Благословения Ра" (пассив копья Нур -
# бонусы работают днём и только под открытым небом) и топового Взрыва Солнца.
# Оба квеста tracked=True: quest_tracker сам считает очки через on_death(),
# используя ту же ветку "hero_id == amonra", что и Михок/Шанкс.
#   T1->T2 "Испытание Солнца": 300 убийств мобов под открытым небом днём.
#   T2->T3 "Гнев Солнца": 900 очков той же природы, где обычный моб под
#          открытым небом днём = 1 очко, а Варден/Иссушитель = 300 очков
#          (т.е. любые 3 таких босса сразу закрывают квест).
QUESTS["amonra"]  = [
    _q("amonra", "amonra_t2", 1, 2, u"Испытание Солнца",
       Material.GOLDEN_SWORD, True, [
        _s("sun_kills", 300, u"Убить мобов под открытым небом днём"),
    ]),
    _q("amonra", "amonra_t3", 2, 3, u"Гнев Солнца",
       Material.NETHER_STAR, True, [
        _s("sun_wrath_points", 900,
           u"Очков (моб днём под небом = 1, Варден/Иссушитель = 300)"),
    ]),
]

QUESTS["wendy"]   = []

# ============================================================================

#  ЧТЕНИЕ СЧЁТЧИКОВ ИЗ ВНЕШНИХ ИСТОЧНИКОВ (VISUAL)

# ============================================================================

def _count_material(player, mat_name):

    """Считает количество предметов данного материала в инвентаре."""

    try:

        mat = Material.getMaterial(mat_name.upper())

        if mat is None: return 0

        total = 0

        for it in player.getInventory().getContents():

            if it is not None and it.getType() == mat:

                total += it.getAmount()

        return total

    except Exception: return 0

def _xp_levels(player):

    try: return int(player.getLevel())

    except Exception: return 0

def _read_ancient_debris(player):

    """Крис T4: либо ancient_debris, либо netherite_scrap. Читаем оба."""

    a = _count_material(player, "ANCIENT_DEBRIS")

    b = _count_material(player, "NETHERITE_SCRAP")

    return a + b

def _get_step_value(player, hero_id, quest_id, step):

    """Возвращает текущее значение счётчика шага."""

    key = step["key"]

    src = step.get("src", "tracked")

    if src == "tracked":

        return _qdata(uid(player), quest_id).get(key, 0)

    if src == "inv":

        # Особые случаи.

        if hero_id == "kris" and quest_id == "kris_t4" and key == "ancient_debris":

            return _read_ancient_debris(player)

        return _count_material(player, key)

    if src == "xp":

        if key == "xp_levels":

            return _xp_levels(player)

        return 0

    # Внешние stat-функции (для героев с уже готовой прогрессией).

    if src.endswith("_stat"):

        # Ищем публикацию в JVM properties: quest_tracker.stat.<src>(player, key)

        hero_stat = src[:-len("_stat")]   # e.g. "doom"

        fn = None

        try:

            fn = System.getProperties().get("quest_tracker.stat." + hero_stat)

        except Exception:

            fn = None

        if fn is None:

            return 0

        try:

            return int(fn(player, key))

        except Exception:

            return 0

    return 0

# ============================================================================

#  ПРОГРЕСС КВЕСТА

# ============================================================================

def _quest_completed(player, hero_id, quest):

    for st in quest["steps"]:

        val = _get_step_value(player, hero_id, quest["id"], st)

        if val < st["needed"]:

            return False

    return True

def _quests_for_current_tier(player, hero_id):

    """Возвращает квесты, ведущие с текущего тира на следующий."""

    all_q = QUESTS.get(hero_id, [])

    if not all_q: return []

    cur_tier = _get_tier_from_inventory(player, hero_id)

    if cur_tier is None:

        # Показываем первый доступный.

        return [q for q in all_q if q["tier_from"] == 1]

    return [q for q in all_q if q["tier_from"] == cur_tier]

def _try_auto_upgrade(player, hero_id, quest):

    """Пытается вызвать character_tier_setters, если квест выполнен."""

    try:

        setters = System.getProperties().get("character_tier_setters")

        if setters is None: return False

        fn = setters.get(hero_id)

        if fn is None: return False

        # Автоапгрейд только если для tracked-квестов. VISUAL идут вручную через

        # /kris улучшить и т.д. — не наше дело.

        if not quest.get("tracked"): return False

        target_tier = quest["tier_to"]

        result = fn(player, target_tier)

        if result:

            player.sendMessage(u"§d§l✦ КВЕСТ ЗАВЕРШЁН! §r§7— " + quest["name"])

            player.sendMessage(u"§7Тир повышен до §fT" + str(target_tier))

            try:

                w = player.getWorld()

                w.playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)

                w.spawnParticle(Particle.END_ROD, player.getLocation().add(0, 1, 0),

                                80, 0.5, 1.0, 0.5, 0.1)

            except Exception:

                pass

        return bool(result)

    except Exception as ex:

        Bukkit.getLogger().warning("[quest_tracker] auto_upgrade: " + str(ex))

        return False

def _check_and_upgrade(player, hero_id, quest_id):

    """Проверяет квест и делает автоапгрейд, если завершён.

    Защита от повторного триггера:
      1. Если в quest-data стоит флаг '_completed' — молча выходим.
      2. Если текущий тир игрока >= tier_to квеста — квест уже пройден,
         ставим флаг и выходим (даже без инвентарного предмета).
      3. Автоапгрейд делаем только один раз, потом ставим флаг навсегда.
    """

    all_q = QUESTS.get(hero_id, [])

    for q in all_q:

        if q["id"] != quest_id: continue

        if not q.get("tracked"): return

        qd = _qdata(uid(player), quest_id)

        # 1. Уже помечен как выполненный — не спамим.

        if qd.get("_completed"):

            return

        # 2. Игрок уже на нужном или более высоком тире — квест устарел.

        cur_tier = _get_tier_from_inventory(player, hero_id)

        if cur_tier is not None and cur_tier >= q["tier_to"]:

            qd["_completed"] = True

            _save()

            return

        # 3. Все шаги выполнены — пробуем апгрейд.

        if _quest_completed(player, hero_id, q):

            ok = _try_auto_upgrade(player, hero_id, q)

            # ВАЖНО: ставим флаг ВСЕГДА когда все шаги выполнены,
            # даже если setter не сработал (иначе на каждом следующем
            # инкременте снова будет вызов и снова title-спам).

            qd["_completed"] = True

            _save()

        return

# ============================================================================

#  PUBLIC API (для скриптов героев)

# ============================================================================

def api_increment(quest_id, player, amount=1, key=None):

    """Внешний API: увеличить счётчик.

    Если key указан — конкретный шаг, иначе — 'default'."""

    try:

        if key is None: key = "default"

        _inc(uid(player), quest_id, key, amount)

        # Определяем героя и пытаемся автоапгрейд.

        hero_id = _detect_hero(player)

        if hero_id:

            _check_and_upgrade(player, hero_id, quest_id)

        _save()

    except Exception as ex:

        Bukkit.getLogger().warning("[quest_tracker] api_increment: " + str(ex))

def api_progress(player):

    """Возвращает копию всего прогресса игрока."""

    try:

        return dict(_pdata(uid(player)))

    except Exception:

        return {}

def api_register_stat(hero_id, fn):

    """Героям с VISUAL-квестами: регистрируют функцию (player, key) -> int

    для чтения счётчиков из их внутреннего состояния."""

    try:

        System.getProperties().put("quest_tracker.stat." + hero_id, fn)

    except Exception:

        pass

# ============================================================================

#  EVENT HANDLERS

# ============================================================================

# Хранилище последних damage-событий для детекта дуэлей Михока.

# victim_uid -> [(damager_uid, tick), ...]

_recent_damage = {}

DAMAGE_MEMORY_TICKS = 200   # 10 сек

def _record_damage(victim_uid, damager_uid):

    if victim_uid not in _recent_damage:

        _recent_damage[victim_uid] = []

    _recent_damage[victim_uid].append((damager_uid, now_tick()))

    # Обрезаем старое.

    cutoff = now_tick() - DAMAGE_MEMORY_TICKS

    _recent_damage[victim_uid] = [(u, t) for u, t in _recent_damage[victim_uid] if t >= cutoff]

def on_damage_by(event):

    """Записываем damage для детекта дуэлей + third-party interference."""

    try:

        dmg = event.getDamager()

        ent = event.getEntity()

        if not isinstance(ent, LivingEntity): return

        actual_dmg = dmg

        if hasattr(dmg, "getShooter"):

            try:

                s = dmg.getShooter()

                if isinstance(s, LivingEntity):

                    actual_dmg = s

            except Exception: pass

        if not isinstance(actual_dmg, LivingEntity): return

        _record_damage(uid(ent), uid(actual_dmg))

    except Exception:

        pass

SEA_ENTITY_TYPES = None

def _get_sea_types():

    global SEA_ENTITY_TYPES

    if SEA_ENTITY_TYPES is not None:

        return SEA_ENTITY_TYPES

    lst = [Squid, Dolphin, Drowned, Guardian, ElderGuardian]

    if GlowSquid is not None:

        lst.append(GlowSquid)

    SEA_ENTITY_TYPES = tuple(lst)

    return SEA_ENTITY_TYPES

# Материалы рыб дополнительно (dropped items — не проверяем, только по entity type).

def _is_under_open_sky_and_day(entity):
    """True если над сущностью нет крыши до потолка мира, сейчас день и мир
    обычного типа (NORMAL). Та же логика, что и пассив "Благословение Ра" в
    amonra.py (_is_under_open_sky) - продублирована здесь намеренно, так как
    quest_tracker.py не импортирует внутренности других скриптов героев,
    только их публичные API через System.getProperties()."""
    try:
        world = entity.getWorld()
        if world.getEnvironment().name() != "NORMAL":
            return False
        if not world.isDayTime():
            return False
        loc = entity.getLocation()
        x = loc.getBlockX()
        z = loc.getBlockZ()
        y_start = loc.getBlockY() + 2
        try:
            y_max = world.getMaxHeight()
        except Exception:
            y_max = 320
        for y in range(y_start, y_max):
            m = world.getBlockAt(x, y, z).getType()
            if m.isAir():
                continue
            return False
        return True
    except Exception:
        return False


def _is_wither_or_warden(ent):
    """Иссушитель или Варден - топовые боссы для очков квеста Амон-Ра T3."""
    if isinstance(ent, Wither):
        return True
    if Warden is not None:
        try:
            if isinstance(ent, Warden):
                return True
        except Exception:
            pass
    return False


def _is_boss(ent):

    """Считается ли ent боссом для квеста Михока."""

    if isinstance(ent, Wither): return True

    if isinstance(ent, EnderDragon): return True

    try:

        if ATTR_MAX_HEALTH is None:
            return False

        attr = ent.getAttribute(ATTR_MAX_HEALTH)

        if attr is not None and attr.getValue() >= 100.0:

            return True

    except Exception: pass

    return False

def _is_legendary_top_tier(victim):

    """Проверяет: был ли на убитом игроке предмет героя max-тира."""

    if not isinstance(victim, Player): return False

    max_tier_by_hero = {

        "kris": 5, "doom": 3, "archer": 3, "architect": 3,

        "mihawk": 5, "griblet": 3, "barsik": 5, "shanks": 6,

        "poseidon": 3, "warden": 3, "dragon": 3, "steelgorn": 3, "amonra": 3,

    }

    tier_key_by_hero = {

        "kris":       "kris:tier",

        "doom":       "doomlord:tier",

        "archer":     "archer:tier",

        "architect":  "architect:tier",

        "mihawk":     "mihawk:tier",

        "griblet":    "griblet:tier",

        "barsik":     "barsik:tier",

        "shanks":     "shanks:tier",

        "poseidon":   "poseidon:tier",

        "warden":     "warden:tier",

        "dragon":     "dragon:tier",

        "steelgorn":  "steelgorn:tier",

        "amonra":     "amonra:tier",

    }

    try:

        inv = victim.getInventory()

        for it in inv.getContents():

            if it is None: continue

            m = it.getItemMeta()

            if m is None: continue

            pdc = m.getPersistentDataContainer()

            for hero_id, tk in tier_key_by_hero.items():

                k = NamespacedKey.fromString(tk)

                if pdc.has(k, PersistentDataType.INTEGER):

                    t = pdc.get(k, PersistentDataType.INTEGER)

                    if t >= max_tier_by_hero.get(hero_id, 999):

                        return True

    except Exception: pass

    return False

def on_death(event):

    victim = event.getEntity()

    killer = victim.getKiller()

    if killer is None or not isinstance(killer, Player):

        return

    hero_id = _detect_hero(killer)

    if hero_id is None: return

    killer_uid = uid(killer)

    victim_uid = uid(victim)

    # === MIHAWK ===

    if hero_id == "mihawk":

        if _has_hero_item_in_hand(killer, "mihawk"):

            # Проверка на солдо: нет других игроков в 20 бл вокруг убийцы.

            solo = _is_solo(killer, radius=20.0)

            if solo:

                _inc(killer_uid, "mihawk_t2", "solo_kills", 1)

                _check_and_upgrade(killer, hero_id, "mihawk_t2")

            # Дуэль: victim — Player + чистый бой 1-на-1 в 10 сек до/после.

            if isinstance(victim, Player) and _is_clean_duel(killer, victim):

                _inc(killer_uid, "mihawk_t3", "duels_won", 1)

                _check_and_upgrade(killer, hero_id, "mihawk_t3")

            # Босс.

            if _is_boss(victim):

                _inc(killer_uid, "mihawk_t4", "boss_kills", 1)

                _check_and_upgrade(killer, hero_id, "mihawk_t4")

        _save()

    # === SHANKS ===

    if hero_id == "shanks":

        if _has_hero_item_in_hand(killer, "shanks"):

            # PvP.

            if isinstance(victim, Player) and not victim.equals(killer):

                _inc(killer_uid, "shanks_t2", "pvp_kills", 1)

                _check_and_upgrade(killer, hero_id, "shanks_t2")

                # No-death streak: считаем PvP-килы за streak.

                m = _meta(killer_uid)

                m["kills_since_death_ms"] = m.get("kills_since_death_ms", 0) + 1

                _inc(killer_uid, "shanks_t4", "no_death_kills", 1)

                _check_and_upgrade(killer, hero_id, "shanks_t4")

                # Легендарный убитый.

                if _is_legendary_top_tier(victim):

                    _inc(killer_uid, "shanks_t6", "legendary_kill", 1)

                    _check_and_upgrade(killer, hero_id, "shanks_t6")

            # Sea kills.

            sea_types = _get_sea_types()

            is_sea = False

            for st in sea_types:

                try:

                    if isinstance(victim, st):

                        is_sea = True; break

                except Exception: pass

            if is_sea:

                _inc(killer_uid, "shanks_t3", "sea_kills", 1)

                _check_and_upgrade(killer, hero_id, "shanks_t3")

        _save()

    # === AMONRA ===
    # Тематика: обе ступени завязаны на пассив "Благословение Ра" (бой под
    # открытым небом днём), т.к. это ключевая механика персонажа. T3 частично
    # ускоряется убийством топовых боссов (Иссушитель/Варден), чтобы не
    # заставлять фармить только рядовых мобов до бесконечности.
    if hero_id == "amonra":

        if _has_hero_item_in_hand(killer, "amonra"):

            if _is_under_open_sky_and_day(killer):

                # T1->T2: обычный счёт "убийство под открытым небом днём".
                _inc(killer_uid, "amonra_t2", "sun_kills", 1)

                _check_and_upgrade(killer, hero_id, "amonra_t2")

                # T2->T3: та же убийства идут в общий пул очков, +1 за штуку.
                _inc(killer_uid, "amonra_t3", "sun_wrath_points", 1)

                _check_and_upgrade(killer, hero_id, "amonra_t3")

            # Боссы (Иссушитель/Варден) дают крупный бонус к очкам T3
            # независимо от того, день сейчас или под открытым небом -
            # такая победа сама по себе весома для "Гнева Солнца".
            if _is_wither_or_warden(victim):

                _inc(killer_uid, "amonra_t3", "sun_wrath_points", 300)

                _check_and_upgrade(killer, hero_id, "amonra_t3")

        _save()

def _is_solo(killer, radius=20.0):

    """Проверяет: рядом с убийцей нет других игроков (только жертва)."""

    try:

        near = killer.getWorld().getNearbyEntities(killer.getLocation(),

                                                    radius, radius, radius)

        for e in near:

            if isinstance(e, Player) and not e.equals(killer):

                return False

    except Exception: pass

    return True

def _is_clean_duel(killer, victim):

    """Проверяет: за последние 10 сек в damage-логе жертвы участвовал только

    killer. Никаких третьих сторон."""

    victim_uid = uid(victim)

    killer_uid = uid(killer)

    log = _recent_damage.get(victim_uid, [])

    cutoff = now_tick() - DAMAGE_MEMORY_TICKS

    for src_uid, t in log:

        if t < cutoff: continue

        if src_uid != killer_uid:

            # Проверяем: это игрок? Если это моб/приспособление — ок.

            try:

                other = Bukkit.getEntity(JUUID.fromString(src_uid))

                if isinstance(other, Player):

                    return False

            except Exception: pass

    # И жертва бьёт кого-то ещё в те же 10 сек — тоже помеха.

    # (упрощённо не проверяем — иначе логика становится тяжёлой)

    return True

def on_block_place(event):

    p = event.getPlayer()

    if not isinstance(p, Player): return

    hero_id = _detect_hero(p)

    if hero_id != "architect": return

    # Если квест уже завершён или игрок на T2+ — не инкрементим.

    qd = _qdata(uid(p), "arch_t2")

    if qd.get("_completed"):

        return

    cur_tier = _get_tier_from_inventory(p, hero_id)

    if cur_tier is not None and cur_tier >= 2:

        qd["_completed"] = True

        return

    _inc(uid(p), "arch_t2", "blocks_placed", 1)

    # Не сохраняем каждый блок — экономим I/O. Сохраним раз в 20 инкрементов.

    if qd.get("blocks_placed", 0) % 20 == 0:

        _save()

        _check_and_upgrade(p, hero_id, "arch_t2")

def on_block_break(event):

    p = event.getPlayer()

    if not isinstance(p, Player): return

    hero_id = _detect_hero(p)

    if hero_id != "architect": return

    qd = _qdata(uid(p), "arch_t2")

    if qd.get("_completed"):

        return

    cur_tier = _get_tier_from_inventory(p, hero_id)

    if cur_tier is not None and cur_tier >= 2:

        qd["_completed"] = True

        return

    _inc(uid(p), "arch_t2", "blocks_broken", 1)

    if qd.get("blocks_broken", 0) % 20 == 0:

        _save()

        _check_and_upgrade(p, hero_id, "arch_t2")

def on_respawn(event):

    p = event.getPlayer()

    hero_id = _detect_hero(p)

    if hero_id != "shanks": return

    m = _meta(uid(p))

    m["last_death_ms"] = now_ms()

    m["no_death_streak_start_ms"] = now_ms()

    m["kills_since_death_ms"] = 0

    # Обнуляем счётчик "kills за стрик" квеста T4.

    q = _qdata(uid(p), "shanks_t4")

    q["no_death_kills"] = 0

    _save()

def on_join(event):

    p = event.getPlayer()

    hero_id = _detect_hero(p)

    if hero_id != "shanks": return

    # Гарантируем инициализацию meta.

    _meta(uid(p))

    _save()

# ============================================================================

#  ТИКЕР: обновление no-death и top-leader счётчиков для Шанкса

# ============================================================================

# Считаем PvP-килы всех Шанксов между собой + вообще всех игроков.

# Простой глобальный тик каждые 60 сек.

_pvp_kill_scores = {}   # player_uuid -> pvp kills за "сегодня" (сброс раз в 24ч)

_scores_reset_ms = now_ms()

def _tick_shanks():

    try:

        # Сброс глобальных PvP счётчиков раз в 24ч.

        global _scores_reset_ms

        if now_ms() - _scores_reset_ms > 24  * 3600 *  1000:

            _pvp_kill_scores.clear()

            _scores_reset_ms = now_ms()

        # Для всех Шанксов онлайн:

        for pl in Bukkit.getOnlinePlayers():

            hero_id = _detect_hero(pl)

            if hero_id != "shanks": continue

            u = uid(pl)

            m = _meta(u)

            # 1. No-death streak: считаем минуты с последней смерти

            #    (или с момента, когда встал в meta).

            start_ms = m.get("no_death_streak_start_ms", now_ms())

            if start_ms <= 0:

                start_ms = now_ms()

                m["no_death_streak_start_ms"] = start_ms

            mins = int((now_ms() - start_ms) / 60000)

            q4 = _qdata(u, "shanks_t4")

            q4["no_death_min"] = mins

            _check_and_upgrade(pl, hero_id, "shanks_t4")

            # 2. Топ-1 24 часа: сравниваем pvp_kill_scores.

            my_score = _qdata(u, "shanks_t2").get("pvp_kills", 0)

            # Обновляем "текущий счёт" из накопленных.

            _pvp_kill_scores[u] = my_score

            # Проверяем: он топ-1?

            is_top = True

            for other_uid, other_score in _pvp_kill_scores.items():

                if other_uid == u: continue

                if other_score > my_score:

                    is_top = False; break

            top_since = m.get("top_leader_since_ms", 0)

            if is_top:

                if top_since == 0:

                    m["top_leader_since_ms"] = now_ms()

                else:

                    hours = (now_ms() - top_since) / 3600000

                    q5 = _qdata(u, "shanks_t5")

                    q5["top_leader_hours"] = int(hours)

                    _check_and_upgrade(pl, hero_id, "shanks_t5")

            else:

                m["top_leader_since_ms"] = 0

                _qdata(u, "shanks_t5")["top_leader_hours"] = 0

        _save()

    except Exception as ex:

        Bukkit.getLogger().warning("[quest_tracker] tick_shanks: " + str(ex))

    scheduler.runTaskLater(_tick_shanks, 20 * 60)   # 60 сек

scheduler.runTaskLater(_tick_shanks, 20 * 60)

# ============================================================================

#  API для отчёта Architect Pulse и Mihawk Great Slash

# ============================================================================

def api_report_architect_pulse(player):

    hero_id = _detect_hero(player)

    if hero_id != "architect": return

    _inc(uid(player), "arch_t3", "pulse_casts", 1)

    _check_and_upgrade(player, hero_id, "arch_t3")

    _save()

def api_report_mihawk_great_slash(player, targets_hit):

    hero_id = _detect_hero(player)

    if hero_id != "mihawk": return

    if targets_hit >= 5:

        _inc(uid(player), "mihawk_t5", "great_slash_5plus", 1)

        _check_and_upgrade(player, hero_id, "mihawk_t5")

    _save()

# ============================================================================

#  GUI: /quests

# ============================================================================

open_guis = {}   # viewer_uid -> target_uid (кого смотрит)

def _fmt_progress_line(cur, need):

    pct = 100.0 * cur / max(1, need)

    col = u"§a" if cur >= need else (u"§e" if pct >= 50 else u"§7")

    return col + str(cur) + u"§7/§f" + str(need)

def open_quests_gui(viewer, target=None):

    if target is None: target = viewer

    hero_id = _detect_hero(target)

    inv = Bukkit.createInventory(None, 54,

        u"§b§lКвесты §7» §f" + target.getName())

    if hero_id is None:

        # Информационная плитка.

        info = ItemStack(Material.BARRIER, 1)

        m = info.getItemMeta()

        m.setDisplayName(u"§cПерсонаж не определён")

        m.setLore(java_list([

            u"§7У игрока §f" + target.getName() + u" §7нет предмета",

            u"§7ни одного из зарегистрированных героев.",

        ]))

        info.setItemMeta(m)

        inv.setItem(22, info)

        viewer.openInventory(inv)

        open_guis[uid(viewer)] = uid(target)

        return

    quests_all = QUESTS.get(hero_id, [])

    cur_tier = _get_tier_from_inventory(target, hero_id)

    # Заголовочная плитка.

    hero_names = {

        "kris": u"Крис", "doom": u"Доктор Дум", "demiurg": u"Демиург",

        "spider": u"Агент-Паук", "archer": u"Арчер", "architect": u"Архитектор",

        "mihawk": u"Михок", "griblet": u"Гриббит", "barsik": u"Барсик",

        "shanks": u"Шанкс", "geto": u"Гето", "poseidon": u"Посейдон",

        "warden": u"Варден", "dragon": u"Дракон", "amonra": u"Амон-Ра",

        "shaman": u"Шаман", "steelgorn": u"Стальгорн", "wendy": u"Венди",

    }

    header = ItemStack(Material.WRITTEN_BOOK, 1)

    m = header.getItemMeta()

    m.setDisplayName(u"§b§l" + hero_names.get(hero_id, hero_id))

    tier_str = str(cur_tier) if cur_tier is not None else u"?"

    m.setLore(java_list([

        u"§7Игрок: §f" + target.getName(),

        u"§7Текущий тир: §fT" + tier_str,

        u"§7Всего квестов: §f" + str(len(quests_all)),

    ]))

    header.setItemMeta(m)

    inv.setItem(4, header)

    if not quests_all:

        info = ItemStack(Material.PAPER, 1)

        m = info.getItemMeta()

        m.setDisplayName(u"§7У этого персонажа нет квестов")

        m.setLore(java_list([u"§8Прогрессия тиров не задумана."]))

        info.setItemMeta(m)

        inv.setItem(22, info)

        viewer.openInventory(inv)

        open_guis[uid(viewer)] = uid(target)

        return

    # Плитки квестов.

    slots = [10, 11, 12, 13, 14, 15, 16,

             19, 20, 21, 22, 23, 24, 25,

             28, 29, 30, 31, 32, 33, 34]

    for i, q in enumerate(quests_all):

        if i >= len(slots): break

        icon = ItemStack(q["icon"], 1)

        m = icon.getItemMeta()

        prefix = u"§a✓ " if _quest_completed(target, hero_id, q) else u"§e» "

        if cur_tier is not None and q["tier_from"] < cur_tier:

            prefix = u"§8§m"   # уже пройден (текущий тир выше)

        elif cur_tier is not None and q["tier_from"] > cur_tier:

            prefix = u"§7[Закрыт] "   # ещё не открыт

        m.setDisplayName(prefix + u"§f" + q["name"] + u" §8(T" +

                         str(q["tier_from"]) + u"→T" + str(q["tier_to"]) + u")")

        lore = []

        for st in q["steps"]:

            cur_val = _get_step_value(target, hero_id, q["id"], st)

            lore.append(u"§8» §7" + st["label"] + u": " +

                        _fmt_progress_line(cur_val, st["needed"]))

        lore.append(u"")

        if q.get("tracked"):

            lore.append(u"§8[авто-улучшение]")

        else:

            lore.append(u"§8[вручную: /" + hero_id + u" улучшить]")

        m.setLore(java_list(lore))

        icon.setItemMeta(m)

        inv.setItem(slots[i], icon)

    # Кнопка обновить.

    refresh = ItemStack(Material.CLOCK, 1)

    m = refresh.getItemMeta()

    m.setDisplayName(u"§eОбновить")

    try:

        m.getPersistentDataContainer().set(KEY_GUI, PersistentDataType.STRING, u"refresh")

    except Exception: pass

    refresh.setItemMeta(m)

    inv.setItem(49, refresh)

    viewer.openInventory(inv)

    open_guis[uid(viewer)] = uid(target)

def on_inv_click(event):

    who = event.getWhoClicked()

    if not isinstance(who, Player): return

    u = uid(who)

    if u not in open_guis: return

    title = event.getView().getTitle() if hasattr(event.getView(), "getTitle") else u""

    if u"Квесты" not in title:

        return

    event.setCancelled(True)

    clicked = event.getCurrentItem()

    if clicked is None or clicked.getType() == Material.AIR: return

    m = clicked.getItemMeta()

    if m is None: return

    pdc = m.getPersistentDataContainer()

    if pdc.has(KEY_GUI, PersistentDataType.STRING):

        action = pdc.get(KEY_GUI, PersistentDataType.STRING)

        if action == u"refresh":

            target_uuid = open_guis.get(u)

            target = None

            try:

                target = Bukkit.getPlayer(JUUID.fromString(target_uuid))

            except Exception: pass

            if target is None or not target.isOnline():

                who.closeInventory()

                return

            open_quests_gui(who, target)

            return

def on_inv_close(event):

    who = event.getPlayer()

    if isinstance(who, Player):

        open_guis.pop(uid(who), None)

# ============================================================================

#  COMMAND

# ============================================================================

def cmd_quests(sender, label, args):

    if not isinstance(sender, Player):

        sender.sendMessage(u"§cКоманда только для игроков.")

        return True

    if len(args) == 0:

        open_quests_gui(sender)

        return True

    sub = args[0].lower()

    if sub in (u"reload", u"reset"):

        if not _is_admin(sender):

            sender.sendMessage(u"§cДоступ только для админов.")

            return True

        if sub == u"reload":

            _load()

            sender.sendMessage(u"§a✓ Прогресс перечитан из JSON.")

            return True

        if sub == u"reset":

            if len(args) < 2:

                sender.sendMessage(u"§7/quests reset <ник>")

                return True

            target = Bukkit.getPlayerExact(args[1])

            if target is None or not target.isOnline():

                sender.sendMessage(u"§cИгрок не онлайн.")

                return True

            progress.pop(uid(target), None)

            _save()

            sender.sendMessage(u"§a✓ Прогресс §f" + target.getName() + u" §aсброшен.")

            return True

    # Смотрим чужой прогресс — admin.

    if not _is_admin(sender):

        sender.sendMessage(u"§cПросмотр чужих квестов только для админов.")

        return True

    target = Bukkit.getPlayerExact(args[0])

    if target is None or not target.isOnline():

        sender.sendMessage(u"§cИгрок §f" + args[0] + u" §cне онлайн.")

        return True

    open_quests_gui(sender, target)

    return True

# ============================================================================

#  REGISTRATION

# ============================================================================

cmd_mgr.registerCommand(cmd_quests, "quests")

listener_mgr.registerListener(on_damage_by,   EntityDamageByEntityEvent)

listener_mgr.registerListener(on_death,       EntityDeathEvent)

listener_mgr.registerListener(on_block_place, BlockPlaceEvent)

listener_mgr.registerListener(on_block_break, BlockBreakEvent)

listener_mgr.registerListener(on_respawn,     PlayerRespawnEvent)

listener_mgr.registerListener(on_join,        PlayerJoinEvent)

listener_mgr.registerListener(on_inv_click,   InventoryClickEvent)

listener_mgr.registerListener(on_inv_close,   InventoryCloseEvent)

# Публикуем API.

_props = System.getProperties()

_props.put("quest_tracker.increment", api_increment)

_props.put("quest_tracker.progress", api_progress)

_props.put("quest_tracker.report_architect_pulse", api_report_architect_pulse)

_props.put("quest_tracker.report_mihawk_great_slash", api_report_mihawk_great_slash)

_props.put("quest_tracker.register_stat", api_register_stat)

_load()

Bukkit.getLogger().info("[quest_tracker] Quest Tracker loaded. Command: /quests")

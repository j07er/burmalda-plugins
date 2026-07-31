# -*- coding: utf-8 -*-
"""
==============================================================================
  DUMMY — Тренировочный Манекен
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /dummy spawn                 — заспавнить манекен в точке перед игроком
  /dummy remove [all]          — удалить манекен, на который смотришь (или все)
  ПКМ по манекену              — открыть GUI настроек
  Удар по манекену             — показывает урон в ActionBar и holo-текст

  Настройки в GUI:
    - Броня: без / кожа / железо / алмаз / незерит / незерит+Prot IV
    - Флаги: игнорировать броню, считать эффекты, бессмертие, автоотхил, лог
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System, Byte as JByte, Long as JLong
from java.util import UUID as JUUID, ArrayList, HashMap

from org.bukkit import (
    Bukkit, Material, Particle, Sound, NamespacedKey, Registry, Location, Color
)
from org.bukkit.entity import (
    Player, LivingEntity, ArmorStand, TextDisplay
)
from org.bukkit.event.player import (
    PlayerInteractEntityEvent, PlayerInteractEvent
)
from org.bukkit.event.entity import (
    EntityDamageEvent, EntityDamageByEntityEvent, ProjectileHitEvent
)
from org.bukkit.event.inventory import (
    InventoryClickEvent, InventoryCloseEvent
)

# Paper-only: PrePlayerAttackEntityEvent — вызывается ДО EntityDamageByEntity,
# в этот момент getAttackCooldown() возвращает реальную перезарядку.
_PrePlayerAttackEntityEvent = None
try:
    from io.papermc.paper.event.player import PrePlayerAttackEntityEvent as _PPAEE
    _PrePlayerAttackEntityEvent = _PPAEE
except Exception:
    try:
        from com.destroystokyo.paper.event.player import PrePlayerAttackEntityEvent as _PPAEE
        _PrePlayerAttackEntityEvent = _PPAEE
    except Exception:
        _PrePlayerAttackEntityEvent = None
from org.bukkit.inventory import ItemStack, EquipmentSlot
from org.bukkit.inventory.meta import LeatherArmorMeta, SkullMeta
from org.bukkit.persistence import PersistentDataType
from org.bukkit.enchantments import Enchantment
import os, time, io


ADMIN_NAMES = set([u"blueredtronce"])

KEY_DUMMY      = NamespacedKey.fromString("dummy:marker")
KEY_ARMOR      = NamespacedKey.fromString("dummy:armor_mode")
KEY_FLAG_IGN   = NamespacedKey.fromString("dummy:flag_ignore_armor")
KEY_FLAG_EFF   = NamespacedKey.fromString("dummy:flag_count_effects")
KEY_FLAG_IMM   = NamespacedKey.fromString("dummy:flag_immortal")
KEY_FLAG_HEAL  = NamespacedKey.fromString("dummy:flag_autoheal")
KEY_FLAG_LOG   = NamespacedKey.fromString("dummy:flag_log")
KEY_ZBT_ACTIVE = NamespacedKey.fromString("dummy:zbt_active")   # BYTE  — включён ли ЗБТ-режим на манекене
KEY_ZBT_TARGET = NamespacedKey.fromString("dummy:zbt_target")   # STRING — UUID тестируемого игрока
KEY_ZBT_HERO   = NamespacedKey.fromString("dummy:zbt_hero")     # STRING — id персонажа

# GUI-теги для кликов.
KEY_GUI_ARMOR  = NamespacedKey.fromString("dummy:gui_armor")
KEY_GUI_FLAG   = NamespacedKey.fromString("dummy:gui_flag")
KEY_GUI_ACTION = NamespacedKey.fromString("dummy:gui_action")   # STRING — id действия
KEY_GUI_PLAYER = NamespacedKey.fromString("dummy:gui_player")   # STRING — UUID игрока в подменю
KEY_GUI_HERO   = NamespacedKey.fromString("dummy:gui_hero")     # STRING — id героя в подменю

# Режимы брони.
ARMOR_MODES = [
    (u"none",       u"§7Без брони",             None),
    (u"leather",    u"§eКожаная",                "leather"),
    (u"iron",       u"§fЖелезная",               "iron"),
    (u"diamond",    u"§bАлмазная",               "diamond"),
    (u"netherite",  u"§8Незеритовая",            "netherite"),
    (u"net_prot4",  u"§4Незерит + Protection IV",  "net_prot4"),
]

# Статистика урона per-attacker: (attacker_uid, dummy_uid) -> {"total": float, "hits": [(tick, damage)], "started_tick": int}
damage_stats = {}

# GUI сессии: uid_player -> dummy_uuid_str
open_guis = {}


def uid(e): return e.getUniqueId().toString()
def now_tick(): return long(System.currentTimeMillis() / 50)

def _is_admin(sender):
    if not isinstance(sender, Player): return True
    return sender.getName().lower() in ADMIN_NAMES or sender.isOp()


# ЗБТ-сессии: dummy_uuid_str -> {
#   "target_uuid": str, "target_name": str, "hero": str,
#   "hits": [ {tick, ability, kind, raw, final, expected_min, expected_max, verdict, extra} ],
#   "checked": set(ability_id),
#   "started_ms": long, "started_by": admin_name,
#   "mode": "auto" | "guided",
#   # guided-only:
#   "playbook":       list of steps,
#   "step_idx":       int,
#   "step_hits":      int (rejected не считается),
#   "step_started":   long tick,
#   "step_rejected":  int,   # сколько ударов отклонили (крит когда нельзя, слабый cd и т.д.)
# }
zbt_sessions = {}

# uid_player -> current GUI screen id ("main"|"zbt_pick_player"|"zbt_pick_hero"|"zbt_status")
gui_screens = {}
# uid_player -> "auto" | "guided" (запомнено между открытиями подменю)
gui_zbt_mode = {}

# uid_player -> последний attack cooldown (0.0..1.0), сохранённый в PrePlayerAttackEntityEvent.
# Читается в on_damage_by. Ключевой момент: getAttackCooldown() в самом
# EntityDamageByEntityEvent уже отброшен в ~0, поэтому надо ловить заранее.
last_attack_cooldown = {}


# =============================================================================
#  ЗБТ — БАЗА ЗНАНИЙ ПО ПЕРСОНАЖАМ
# =============================================================================
#
#  Формат: HERO_SPECS[hero_id] = {
#     "display": u"...",              # красивое имя
#     "item_pdc_keys": ["ns:key",...],# PDC-ключи, по которым узнаём предмет героя
#     "tier_pdc_key":  "ns:tier" | None,
#     "abilities": [ {
#         "id":     "unique_id",
#         "name":   u"Название",
#         "kind":   "melee"|"pure"|"magic"|"projectile"|"aoe"|"buff"|"passive",
#         "expected": [ (min_hp, max_hp), ... ] по тирам, либо (min,max) единично,
#         "note":   u"пояснение как активировать/что проверить",
#         "detect": callable(session, event, cause_name, is_pure, attacker, item) -> True/False
#                   ИЛИ строка с готовым правилом ("default_melee"|"is_pure"|...).
#     }, ... ]
#  }
#
#  Мы НЕ жёстко сравниваем — используем "expected" только как справку для отчёта.
#  Пользователь просил только логировать. Но диапазоны выводятся рядом с каждой
#  строкой отчёта — так внешней нейронке легко оценить, попадает ли в норму.
# =============================================================================

def _spec_kris():
    # Базовый физ урон меча по голому мобу при ПОЛНОМ заряде атаки (cd=1.0).
    # После фикса bukkit-quirk (AttrMod HAND-слота стирает дефолтный ATK материала):
    #   T1: Stone base 5.0 -> ожидание 4.5..5.5
    #   T2: Iron base 6.0  -> ожидание 5.5..6.5
    #   T3: Diamond 7.0    -> ожидание 6.5..7.5
    #   T4: Netherite 8.0  -> ожидание 7.5..8.5
    #   T5: Netherite +2   -> ожидание 9.5..10.5
    tiers_melee = {
        1: (4.5, 5.5),
        2: (5.5, 6.5),
        3: (6.5, 7.5),
        4: (7.5, 8.5),
        5: (9.5, 10.5),
    }
    return {
        "display": u"Крис — Истинный клинок",
        "item_pdc_keys": ["kris:blade"],
        "tier_pdc_key":  "kris:tier",
        "abilities": [
            {"id": "blade_hit", "name": u"Удар клинком (базовый физ)",
             "kind": "melee", "expected_by_tier": tiers_melee,
             "note": u"Просто ЛКМ по манекену. Проверяй урон по каждому тиру: /admin tier kris <n>."},
            {"id": "true_strike", "name": u"Истинный удар (+2❤ чистого)",
             "kind": "pure_bonus", "expected": (4.0, 4.0),
             "note": u"Каждые 3 сек следующий удар даёт +4 HP чистого урона поверх базы. Смотри: сначала обычный физ, следом (тот же тик) MAGIC/CUSTOM +4."},
            {"id": "reflect", "name": u"Отражение урона 20%",
             "kind": "reflect", "expected": None,
             "note": u"Ударь Криса — 20% исходящего отражается обратно. Для теста нужен второй игрок, не манекен."},
            {"id": "soul_ult", "name": u"Ульт-телепорт / Absorption",
             "kind": "buff", "expected": None,
             "note": u"Проверяется отдельно — эффект/телепорт, не урон."},
        ],
    }

def _spec_doom():
    tiers_melee = {
        1: (5.0, 6.5),    # STONE_SWORD + Sharp II
        2: (7.5, 9.5),    # DIAMOND + Sharp IV
        3: (9.5, 11.5),   # NETHERITE + Sharp IV + Sweeping II
    }
    return {
        "display": u"Доктор Дум",
        "item_pdc_keys": ["doomlord:sword"],
        "tier_pdc_key":  "doomlord:tier",
        "abilities": [
            {"id": "sword_hit", "name": u"Удар меча",
             "kind": "melee", "expected_by_tier": tiers_melee,
             "note": u"Проверь урон каждого тира: /admin tier doom <n>."},
            {"id": "repulsor",  "name": u"Репульсорный Импульс",
             "kind": "magic", "expected": (6.0, 10.0),
             "note": u"ПКМ Репульсор. Урон типа MAGIC."},
            {"id": "disintegrator", "name": u"Магический Дезинтегратор",
             "kind": "magic", "expected": (10.0, 16.0),
             "note": u"Отдельная способность, отличная от Репульсора. MAGIC."},
            {"id": "chains", "name": u"Цепи Бездны",
             "kind": "magic", "expected": (4.0, 8.0),
             "note": u"Урон от Цепей."},
            {"id": "ultimate", "name": u"Приговор Латверии (ульт)",
             "kind": "aoe", "expected": (14.0, 24.0),
             "note": u"AoE ульт."},
            {"id": "autorepair","name": u"Авторемонт (+2❤ лечение)",
             "kind": "heal", "expected": None,
             "note": u"Не проверяется по манекену (лечение самого себя)."},
        ],
    }

def _spec_demiurg():
    return {
        "display": u"Демиург",
        "item_pdc_keys": ["demiurg:staff"],
        "tier_pdc_key":  None,
        "abilities": [
            {"id": "staff_hit", "name": u"Удар Посохом", "kind": "melee",
             "expected": (5.0, 8.0), "note": u"Базовый физ."},
            {"id": "smite", "name": u"Карающая Десница", "kind": "magic",
             "expected": (8.0, 14.0), "note": u"MAGIC-урон."},
            {"id": "court", "name": u"Суд", "kind": "magic",
             "expected": (12.0, 20.0), "note": u"MAGIC-урон, сильнее Smite."},
            {"id": "ultimate", "name": u"5 Законов (ульт)", "kind": "aoe",
             "expected": None, "note": u"Проверяется отдельно."},
        ],
    }

def _spec_spider():
    return {
        "display": u"Агент-Паук",
        "item_pdc_keys": ["spideragent:mask", "spideragent:ejector"],
        "tier_pdc_key":  None,
        "abilities": [
            # ВАЖНО: Паук — utility-персонаж. Прямой урон снарядами НЕ является
            # его дизайном; вся сила в CC (slow/freeze/pull/burn), мобильности и
            # площадном давлении. Урон здесь символический.
            {"id": "ejector_hit", "name": u"Удар эжектором (мили)", "kind": "melee",
             "expected": (1.0, 3.0),
             "note": u"Мили НЕ основа Паука. Blaze Rod base 2.0 HP. Не свагер."},
            {"id": "web_shot",   "name": u"Web Shot — полёт на паутине", "kind": "utility",
             "expected": None,
             "note": u"Mode 0. НЕ наносит урон. Проверять: pull-to-block, свист паутины."},
            {"id": "web_line",   "name": u"Паутинная нить — pull цели", "kind": "cc",
             "expected": None,
             "note": u"Mode 1. НЕ наносит урон. Проверять: цель тянет к стрелку."},
            {"id": "web_ball",   "name": u"Паутинный шар — Slowness II 3 сек", "kind": "cc",
             "expected": None,
             "note": u"Mode 2. НЕ наносит урон. Проверять: цель получила Slowness II."},
            {"id": "web_impact", "name": u"Ударная паутина — 2 HP + откид", "kind": "projectile",
             "expected": (1.5, 2.5),
             "note": u"Mode 3. ЕДИНСТВЕННЫЙ снаряд с прямым уроном (2.0 HP по коду)."},
            {"id": "web_grenade","name": u"Паутинная граната — AoE placement", "kind": "cc",
             "expected": None,
             "note": u"Mode 4. НЕ наносит урон. Проверять: паутина поставилась под всеми в r=5."},
            {"id": "web_shock",  "name": u"Шок-Паутина — Freeze 6 сек", "kind": "cc",
             "expected": None,
             "note": u"Mode 5. НЕ наносит урон. Проверять: цель заморожена + Slowness IV."},
            {"id": "web_fire",   "name": u"Огненная паутина — поджиг 8 сек", "kind": "dot",
             "expected": None,
             "note": u"Mode 6. НЕ наносит урон при попадании — только setFireTicks(160). "
                     u"DoT от огня = 1 HP каждые 20 тиков (ванильно), суммарно ~8 HP за 8 сек."},
            {"id": "swing", "name": u"Раскачивание/паутина", "kind": "passive",
             "expected": None, "note": u"Проверяется отдельно (мобильность)."},
        ],
    }

def _spec_archer():
    tiers_melee = {
        1: (6.0, 8.0),
        2: (7.5, 9.5),
        3: (9.0, 11.0),
    }
    return {
        "display": u"Арчер",
        "item_pdc_keys": ["archer:item"],
        "tier_pdc_key":  "archer:tier",
        "abilities": [
            {"id": "kanshou_bakuya", "name": u"Каншо/Бакуя (парный клинок)",
             "kind": "melee", "expected_by_tier": tiers_melee,
             "note": u"ЛКМ клинками по каждому тиру."},
            {"id": "caladbolg", "name": u"Каладболг (взрывная стрела)",
             "kind": "projectile", "expected": (6.0, 12.0),
             "note": u"Выстрели помеченной стрелой (archer:arrow). Урон в момент попадания + AoE."},
            {"id": "mirror", "name": u"Зеркало Души (Дар отражения)",
             "kind": "reflect", "expected": None,
             "note": u"Требует второго игрока-атакующего."},
        ],
    }

def _spec_architect():
    tiers_melee = {
        1: (3.0, 5.0),
        2: (5.0, 7.0),
        3: (7.0, 9.0),
    }
    return {
        "display": u"Архитектор",
        "item_pdc_keys": ["architect:key"],
        "tier_pdc_key":  "architect:tier",
        "abilities": [
            {"id": "key_hit", "name": u"Удар Мульти-Ключом",
             "kind": "melee", "expected_by_tier": tiers_melee,
             "note": u"Базовый физ. По тирам /admin tier architect <n>."},
            {"id": "pulse", "name": u"Кинетический Импульс", "kind": "cc",
             "expected": (1.5, 2.5),
             "note": u"CC-способность (knockback). Урон 2 HP по коду — так задумано. "
                     u"Компенсация — короткий КД (6 сек, ребаланс 2026-07-28)."},
            {"id": "cage_ult", "name": u"Обсидиановая клетка (ульт)",
             "kind": "aoe", "expected": None,
             "note": u"Проверяется вне манекена."},
        ],
    }

def _spec_mihawk():
    tiers_melee = {
        1: (6.0, 8.0),
        2: (7.5, 9.5),
        3: (9.0, 11.0),
        4: (10.5, 13.0),
        5: (12.0, 15.0),
    }
    return {
        "display": u"Дракуль Михок",
        "item_pdc_keys": ["mihawk:yoru"],
        "tier_pdc_key":  "mihawk:tier",
        "abilities": [
            {"id": "yoru_hit", "name": u"Удар Ёру", "kind": "melee",
             "expected_by_tier": tiers_melee,
             "note": u"Проверь каждый тир."},
            {"id": "great_slash", "name": u"Великий Разрез", "kind": "aoe",
             "expected": (5.5, 6.5),
             "note": u"AoE 12x3x4 фронтальный разрез, ломает блоки. 6 HP чистого урона. "
                     u"Компенсация низкого урона — короткий КД (45 сек, ребаланс 2026-07-28)."},
        ],
    }

def _spec_griblet():
    tiers_melee = {
        1: (3.0, 5.0),
        2: (5.0, 7.0),
        3: (7.0, 9.0),
    }
    return {
        "display": u"Гриббит",
        "item_pdc_keys": ["griblet:staff"],
        "tier_pdc_key":  "griblet:tier",
        "abilities": [
            {"id": "staff_hit", "name": u"Удар посохом", "kind": "melee",
             "expected_by_tier": tiers_melee, "note": u"Базовый физ."},
            {"id": "sticky_tongue", "name": u"Липкий язык", "kind": "magic",
             "expected": (2.0, 5.0), "note": u"Проверь тик урона от языка."},
            {"id": "meteor", "name": u"Жабий Метеорит", "kind": "aoe",
             "expected": (6.0, 12.0), "note": u"AoE-урон при падении."},
        ],
    }

def _spec_barsik():
    tiers_melee = {
        1: (4.0, 5.5),
        2: (5.5, 7.0),
        3: (7.0, 8.5),
        4: (8.5, 10.0),
        5: (10.0, 12.0),
    }
    return {
        "display": u"Барсик",
        "item_pdc_keys": ["barsik:claws"],
        "tier_pdc_key":  "barsik:tier",
        "abilities": [
            {"id": "claws_hit", "name": u"Удар когтями", "kind": "melee",
             "expected_by_tier": tiers_melee, "note": u"По каждому тиру."},
            {"id": "dash", "name": u"Кошачий рывок", "kind": "physical",
             "expected": (4.0, 8.0), "note": u"Урон при рывке."},
        ],
    }

def _spec_shanks():
    tiers_melee = {
        1: (5.0, 6.5),
        2: (6.5, 8.0),
        3: (8.0, 9.5),
        4: (9.5, 11.0),
        5: (11.0, 13.0),
        6: (13.0, 16.0),
    }
    return {
        "display": u"Шанкс",
        "item_pdc_keys": ["shanks:griffon"],
        "tier_pdc_key":  "shanks:tier",
        "abilities": [
            {"id": "griffon_hit", "name": u"Удар Грифоном", "kind": "melee",
             "expected_by_tier": tiers_melee, "note": u"По каждому тиру 1..6."},
            {"id": "haoshoku", "name": u"Королевская Воля", "kind": "buff",
             "expected": None, "note": u"Не наносит урон напрямую."},
        ],
    }

def _spec_geto():
    return {
        "display": u"Сугуру Гето",
        "item_pdc_keys": ["geto:egg_marker"],
        "tier_pdc_key":  None,
        "abilities": [
            {"id": "summon_dmg", "name": u"Урон от призванного моба", "kind": "melee",
             "expected": None,
             "note": u"Призыв через spawn-egg. Damager будет мобом, но owner в PDC geto:egg_owner."},
            {"id": "territory", "name": u"Расширение территории", "kind": "aoe",
             "expected": None, "note": u"Проверяется отдельно."},
        ],
    }

def _spec_poseidon():
    tiers_melee = {
        1: (7.0, 9.0),
        2: (8.5, 11.0),
        3: (10.5, 13.0),
    }
    return {
        "display": u"Посейдон",
        "item_pdc_keys": ["poseidon:trident"],
        "tier_pdc_key":  "poseidon:tier",
        "abilities": [
            {"id": "trident_hit", "name": u"Удар Трезубцем", "kind": "melee",
             "expected_by_tier": tiers_melee, "note": u"По каждому тиру."},
            {"id": "trident_throw", "name": u"Бросок Трезубца", "kind": "projectile",
             "expected": (7.0, 12.0), "note": u"Метни трезубец в манекен."},
            {"id": "tidal_wave", "name": u"Приливная волна (AoE)", "kind": "aoe",
             "expected": (7.0, 9.0),
             "note": u"AoE 3-блочный радиус, 8 HP + knockback + stun 0.5 сек. "
                     u"Урон добавлен в ребалансе 2026-07-28."},
        ],
    }

def _spec_warden():
    # Кирки, не мечи. Ванильный ATK материала:
    #   Stone Pickaxe = 3, Diamond = 5, Netherite = 6.
    # Без AttrMod и без Sharpness (только Efficiency для копки).
    tiers_melee = {
        1: (2.5, 4.0),   # Stone Pickaxe ~3.0
        2: (4.5, 6.0),   # Diamond Pickaxe ~5.0
        3: (5.5, 7.5),   # Netherite Pickaxe ~6.0
    }
    return {
        "display": u"Варден",
        "item_pdc_keys": ["warden:pick"],
        "tier_pdc_key":  "warden:tier",
        "abilities": [
            {"id": "pick_hit", "name": u"Удар Сердцем Скалка (кирка)", "kind": "melee",
             "expected_by_tier": tiers_melee,
             "note": u"Кирка, не меч. Основной DPS у Sonic Boom и Sculk Strike."},
            {"id": "sonic_boom", "name": u"Звуковой удар (чистый)", "kind": "pure",
             "expected": (4.0, 4.0),
             "note": u"ПКМ активирует Звуковой удар — 4 HP чистого урона (MAGIC). 3 заряда."},
            {"id": "sculk_strike", "name": u"Скалковый удар", "kind": "physical",
             "expected": (6.0, 12.0), "note": u"Удар скалком (+4 HP бонус к базе)."},
            {"id": "blind_instinct_bonus", "name": u"Инстинкт слепого +75%",
             "kind": "buff_dmg", "expected": None,
             "note": u"Guided-плейбук делает два окна (до/после) — сравнивай средние."},
        ],
    }

def _spec_dragon():
    tiers_melee = {
        1: (6.0, 8.0),
        2: (8.0, 10.0),
        3: (10.0, 12.0),
    }
    return {
        "display": u"Дракон",
        "item_pdc_keys": ["dragon:eye"],
        "tier_pdc_key":  "dragon:tier",
        "abilities": [
            {"id": "eye_hit", "name": u"Удар Оком Дракона", "kind": "melee",
             "expected_by_tier": tiers_melee, "note": u"По каждому тиру 1..3."},
            {"id": "fireball", "name": u"Драконий фаербол", "kind": "projectile",
             "expected": (6.0, 12.0),
             "note": u"ПКМ фаербол (dragon:fireball_marker). 2 заряда."},
            {"id": "breath", "name": u"Драконье дыхание", "kind": "magic",
             "expected": (2.0, 6.0), "note": u"Тик-урон в облаке."},
            {"id": "flight_break", "name": u"Полёт 3x3 (не урон)", "kind": "passive",
             "expected": None, "note": u"Ломает блоки, не бьёт."},
            {"id": "end_bonus", "name": u"+15% от Projectile / +20% в Энде",
             "kind": "buff_dmg", "expected": None,
             "note": u"Проверяй в The End. Сравни фаербол-урон Overworld vs End."},
        ],
    }

def _spec_amonra():
    return {
        "display": u"Амон-Ра",
        "item_pdc_keys": ["amonra:nur"],
        "tier_pdc_key":  None,
        "abilities": [
            {"id": "nur_hit", "name": u"Удар Копьём Нур", "kind": "melee",
             "expected": (9.0, 11.0),
             "note": u"Незер меч + Sharp V + Knockback I."},
            {"id": "sun_ray", "name": u"Солнечный луч (20 блоков)", "kind": "magic",
             "expected": (6.0, 10.0),
             "note": u"ПКМ активирует луч. MAGIC-урон."},
            {"id": "sun_burst", "name": u"Взрыв Солнца (радиус 7)", "kind": "aoe",
             "expected": (8.0, 14.0),
             "note": u"AoE-урон, восстанавливает блоки."},
            {"id": "child_of_light", "name": u"Дитя света (buff)", "kind": "buff_dmg",
             "expected": None, "note": u"20 сек в темноте. Сравни физ ДО и ПОСЛЕ."},
            {"id": "ra_blessing", "name": u"Благословение Ра (buff)", "kind": "buff",
             "expected": None, "note": u"Днём под небом. Не даёт урон напрямую."},
        ],
    }

def _spec_shaman():
    return {
        "display": u"Тёмный Шаман",
        "item_pdc_keys": [],
        "tier_pdc_key":  None,
        "abilities": [
            {"id": "wrath", "name": u"Гнев стихий (ульт)", "kind": "aoe",
             "expected": (8.0, 16.0), "note": u"15x15x15, молнии/огонь."},
        ],
    }


def _spec_steelgorn():
    # Axe damage в Java 1.21 (base ATK материала, не как меч!):
    #   Iron Axe = 9, Diamond Axe = 9, Netherite Axe = 10
    # Sharpness formula: 0.5*L + 0.5 бонуса.
    # T1: Iron 9 + Sharp III (+2.0) = 11.0
    # T2: Diamond 9 + Sharp IV (+2.5) = 11.5
    # T3: Netherite 10 + Sharp V (+3.0) = 13.0
    tiers_melee = {
        1: (10.5, 11.5),
        2: (11.0, 12.0),
        3: (12.5, 13.5),
    }
    return {
        "display": u"Стальгорн",
        "item_pdc_keys": ["steelgorn:axe"],
        "tier_pdc_key":  "steelgorn:tier",
        "abilities": [
            {"id": "axe_hit", "name": u"Удар Топором", "kind": "melee",
             "expected_by_tier": tiers_melee,
             "note": u"Axe base 9/9/10 + Sharpness III/IV/V. При ударе накладывается "
                     u"'Тяжесть' на цель (замедление 10/15/20% + fall +25/35/50%)."},
            {"id": "dash", "name": u"Рывок лесоруба (6 HP + Slow III)", "kind": "physical",
             "expected": (5.5, 6.5),
             "note": u"Рывок 10 блоков, урон и Slow III 1.5 сек всем на пути."},
            {"id": "stone_armor", "name": u"Каменная броня (Resist I + первый удар -60%)",
             "kind": "buff", "expected": None,
             "note": u"Utility: первый входящий удар прошёл на 40%. 7 сек, CD 50 сек."},
            {"id": "earthquake", "name": u"Землетрясение (AoE 4 HP + подброс)",
             "kind": "aoe", "expected": (3.5, 4.5),
             "note": u"Радиус 7 блоков, подброс + 4 HP + 4 сек нестабильности. "
                     u"Стальгорн после ульта 3 сек полностью обездвижен."},
        ],
    }


def _spec_wendy():
    return {
        "display": u"Венди Марвелл",
        "item_pdc_keys": ["wendy:wind_charge"],
        "tier_pdc_key":  None,
        "abilities": [
            {"id": "troia",   "name": u"Троя (Регенерация I)", "kind": "buff",
             "expected": None,
             "note": u"Utility: цель впереди получает Регенерацию I на 15с. Проверь эффект."},
            {"id": "vernier", "name": u"Вернир (Скорость I)", "kind": "buff",
             "expected": None,
             "note": u"Utility: Скорость I на 15с."},
            {"id": "arms",    "name": u"Армс (Сила I)", "kind": "buff",
             "expected": None,
             "note": u"Utility: Сила I на 15с. Не прямой урон."},
            {"id": "armor",   "name": u"Армор (Сопротивление I)", "kind": "buff",
             "expected": None,
             "note": u"Utility: Resistance I на 15с."},
            {"id": "claw",    "name": u"Коготь Небесного Дракона (KB)", "kind": "cc",
             "expected": None,
             "note": u"Utility/CC: отбрасывает всех впереди на ~20 блоков. Урон не наносит."},
            {"id": "reraise", "name": u"Ре-райс (купол/glowing/jump)", "kind": "buff",
             "expected": None,
             "note": u"Utility: 5 сек Glowing r=15, купол отражает снаряды."},
            {"id": "ult",     "name": u"Драконья Ярость", "kind": "buff",
             "expected": None,
             "note": u"Utility: 45 сек трансформация. Первые 15 сек — бафы+полёт."},
            {"id": "sonic",   "name": u"Sonic Boom (в ульте)", "kind": "pure",
             "expected": (4.0, 4.0),
             "note": u"4 HP чистого MAGIC урона + подброс на 10 бл. До 4 зарядов в ульте."},
        ],
    }


# Реестр всех героев.
HERO_SPECS = {
    "kris":       _spec_kris(),
    "doom":       _spec_doom(),
    "demiurg":    _spec_demiurg(),
    "spider":     _spec_spider(),
    "archer":     _spec_archer(),
    "architect":  _spec_architect(),
    "mihawk":     _spec_mihawk(),
    "griblet":    _spec_griblet(),
    "barsik":     _spec_barsik(),
    "shanks":     _spec_shanks(),
    "geto":       _spec_geto(),
    "poseidon":   _spec_poseidon(),
    "warden":     _spec_warden(),
    "dragon":     _spec_dragon(),
    "amonra":     _spec_amonra(),
    "shaman":     _spec_shaman(),
    "steelgorn":  _spec_steelgorn(),
    "wendy":      _spec_wendy(),
}


# =============================================================================
#  ЗБТ ПЛЕЙБУКИ — направляемый режим
# =============================================================================
# Формат шага:
#   {
#     "ability_id":  "blade_hit",           # к какой способности приписывать удары в этом окне
#     "ability_name": u"Удар клинком",       # что показывать
#     "tier":         2 | None,             # если задан — при входе в шаг вызываем tier_setter
#     "hits_needed":  5,                    # сколько ударов должно быть засчитано (не спам, не крит когда нельзя)
#     "must_crit":    None | True | False,  # ограничение по криту
#     "kind":         "physical"|"pure"|"magic"|"projectile"|"aoe"|"buff",
#     "prep_text":    u"Возьми клинок и бей БЕЗ прыжка",
#     "hint":         u"Ждать полную перезарядку (звон)",
#     "cd_required":  True,   # требовать cd>=0.9 (для мили)
#     "skippable":    False,  # можно пропустить (для баф-скиллов)
#     "hero_command": u"/doom repulsor",   # опциональная подсказка команды
#   }
# =============================================================================

def _step(ability_id, ability_name, kind, hits_needed=5, tier=None,
          must_crit=None, prep_text=u"", hint=u"", cd_required=True,
          skippable=False, hero_command=u"", expect_utility=False):
    return {
        "ability_id":     ability_id,
        "ability_name":   ability_name,
        "kind":           kind,
        "hits_needed":    hits_needed,
        "tier":           tier,
        "must_crit":      must_crit,
        "prep_text":      prep_text,
        "hint":           hint,
        "cd_required":    cd_required,
        "skippable":      skippable,
        "hero_command":   hero_command,
        "expect_utility": expect_utility,
    }


def _pb_kris():
    steps = []
    for t in [1, 2, 3, 4, 5]:
        steps.append(_step(
            "blade_hit", u"Удар клинком T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Клинок T%d в правой руке. Стой на земле, НЕ прыгай." % t,
            hint=u"Жди звон меча — потом бей.",
        ))
        steps.append(_step(
            "blade_hit", u"Удар клинком T%d (крит)" % t, "physical",
            hits_needed=2, tier=t, must_crit=True,
            prep_text=u"Прыгни и бей на пике падения.",
            hint=u"Каждый удар должен быть в падении.",
        ))
    # Истинный удар: чистый бонус, автоматически бросается раз в 3 сек.
    steps.append(_step(
        "true_strike", u"Истинный удар (+4 HP чистого)", "pure",
        hits_needed=3, tier=5, must_crit=None, cd_required=False,
        prep_text=u"Клинок T5. Бей раз в 3+ сек, чтобы триггерился Истинный удар.",
        hint=u"На каждый триггер — отдельная запись 4.00 HP.",
    ))
    return steps


def _pb_doom():
    steps = []
    for t in [1, 2, 3]:
        steps.append(_step(
            "sword_hit", u"Удар мечом T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Меч Дума T%d. Стой, НЕ прыгай." % t,
        ))
        steps.append(_step(
            "sword_hit", u"Удар мечом T%d (крит)" % t, "physical",
            hits_needed=2, tier=t, must_crit=True,
            prep_text=u"Прыгай и бей.",
        ))
    steps.append(_step(
        "repulsor", u"Репульсорный Импульс", "magic",
        hits_needed=1, cd_required=False, must_crit=None,
        prep_text=u"Активируй Репульсор (ПКМ или команда).",
        hero_command=u"/doom repulsor",
    ))
    steps.append(_step(
        "disintegrator", u"Магический Дезинтегратор", "magic",
        hits_needed=1, cd_required=False, must_crit=None,
        prep_text=u"Активируй Дезинтегратор (отдельная кнопка/команда).",
        hero_command=u"/doom disint",
    ))
    steps.append(_step(
        "chains", u"Цепи Бездны", "magic",
        hits_needed=1, cd_required=False, must_crit=None, skippable=True,
        prep_text=u"Активируй Цепи Бездны.",
        hero_command=u"/doom chains",
    ))
    steps.append(_step(
        "ultimate", u"Приговор Латверии (ульт)", "aoe",
        hits_needed=1, cd_required=False, must_crit=None, skippable=True,
        prep_text=u"Используй ульт.",
        hero_command=u"/doom ult",
    ))
    return steps


def _pb_demiurg():
    return [
        _step("staff_hit", u"Удар Посохом (обычный)", "physical",
              hits_needed=3, must_crit=False,
              prep_text=u"Посох Демиурга. Стой на земле."),
        _step("staff_hit", u"Удар Посохом (крит)", "physical",
              hits_needed=2, must_crit=True,
              prep_text=u"Прыгай и бей."),
        _step("smite",   u"Карающая Десница (Smite)", "magic",
              hits_needed=1, cd_required=False, prep_text=u"Активируй Карающую Десницу."),
        _step("court",   u"Суд", "magic",
              hits_needed=1, cd_required=False, prep_text=u"Активируй Суд."),
        _step("ultimate", u"5 Законов (ульт)", "aoe",
              hits_needed=1, cd_required=False, skippable=True,
              prep_text=u"Используй ульт."),
    ]


def _pb_spider():
    return [
        _step("ejector_hit", u"Удар эжектором (обычный)", "physical",
              hits_needed=3, must_crit=False,
              prep_text=u"Эжектор в руке. Стой на земле.",
              hint=u"Мили Паука слабый по задумке (~2 HP). Это НЕ баг."),
        _step("ejector_hit", u"Удар эжектором (крит)", "physical",
              hits_needed=2, must_crit=True,
              prep_text=u"Прыгай и бей."),
        # Все режимы паутины — utility. Урон в лог не пишется, засчитывается
        # факт попадания снаряда в манекен.
        _step("web_shot", u"Web Shot (mode 0) — полёт на паутине", "utility",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True, skippable=True,
              prep_text=u"Режим 0 (полёт). ПКМ по блоку рядом с манекеном.",
              hint=u"НЕ проверяем урон — проверяем, что тебя дёрнуло к точке."),
        _step("web_line", u"Паутинная нить (mode 1) — pull цели", "cc",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"Режим 1. ПКМ снаряд в манекен.",
              hint=u"Проверяем: манекен тянет к тебе, урона нет."),
        _step("web_ball", u"Паутинный шар (mode 2) — Slow II 3 сек", "cc",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"Режим 2. ПКМ снаряд в манекен.",
              hint=u"Проверяем: у манекена появился Slowness II на 3 сек."),
        _step("web_impact", u"Ударная паутина (mode 3) — 2 HP + откид", "projectile",
              hits_needed=2, cd_required=False, must_crit=None,
              prep_text=u"Режим 3. ПКМ снаряд в манекен.",
              hint=u"Единственный снаряд с прямым уроном ~2.0 HP + откид."),
        _step("web_grenade", u"Паутинная граната (mode 4) — AoE placement", "cc",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"Режим 4. ПКМ снаряд в манекен.",
              hint=u"Проверяем: паутина поставилась под всеми в радиусе 5."),
        _step("web_shock", u"Шок-Паутина (mode 5) — Freeze 6 сек", "cc",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"Режим 5. ПКМ снаряд в манекен.",
              hint=u"Проверяем: манекен заморожен и получил Slowness IV на 6 сек."),
        _step("web_fire", u"Огненная паутина (mode 6) — поджиг 8 сек", "dot",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"Режим 6. ПКМ снаряд в манекен.",
              hint=u"Проверяем: манекен горит 8 сек. Огонь наносит ~8 HP DoT (ваниль)."),
    ]


def _pb_archer():
    steps = []
    for t in [1, 2, 3]:
        steps.append(_step(
            "kanshou_bakuya", u"Каншо/Бакуя T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Клинки T%d. Стой на земле." % t,
        ))
        steps.append(_step(
            "kanshou_bakuya", u"Каншо/Бакуя T%d (крит)" % t, "physical",
            hits_needed=2, tier=t, must_crit=True,
            prep_text=u"Прыгай и бей.",
        ))
    steps.append(_step(
        "caladbolg", u"Каладболг — взрывная стрела", "projectile",
        hits_needed=2, cd_required=False,
        prep_text=u"Возьми лук с меткой archer:arrow, стреляй в манекен.",
    ))
    return steps


def _pb_architect():
    steps = []
    for t in [1, 2, 3]:
        steps.append(_step(
            "key_hit", u"Удар Ключом T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Мульти-Ключ T%d." % t,
        ))
        steps.append(_step(
            "key_hit", u"Удар Ключом T%d (крит)" % t, "physical",
            hits_needed=2, tier=t, must_crit=True,
            prep_text=u"Прыгай и бей.",
        ))
    steps.append(_step(
        "pulse", u"Кинетический Импульс", "magic",
        hits_needed=1, cd_required=False, prep_text=u"Активируй Импульс."))
    return steps


def _pb_mihawk():
    steps = []
    for t in [1, 2, 3, 4, 5]:
        steps.append(_step(
            "yoru_hit", u"Ёру T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Ёру T%d. Стой на земле." % t,
        ))
        steps.append(_step(
            "yoru_hit", u"Ёру T%d (крит)" % t, "physical",
            hits_needed=2, tier=t, must_crit=True,
            prep_text=u"Прыгай и бей.",
        ))
    steps.append(_step(
        "great_slash", u"Великий Разрез", "aoe",
        hits_needed=1, cd_required=False,
        prep_text=u"Активируй Великий Разрез, попади манекеном в зону.",
    ))
    return steps


def _pb_griblet():
    steps = []
    for t in [1, 2, 3]:
        steps.append(_step(
            "staff_hit", u"Посох T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Посох T%d." % t,
        ))
    steps.append(_step(
        "sticky_tongue", u"Липкий язык", "magic",
        hits_needed=1, cd_required=False, prep_text=u"Активируй Язык."))
    steps.append(_step(
        "meteor", u"Жабий Метеорит (ульт)", "aoe",
        hits_needed=1, cd_required=False, prep_text=u"Активируй Метеорит."))
    return steps


def _pb_barsik():
    steps = []
    for t in [1, 2, 3, 4, 5]:
        steps.append(_step(
            "claws_hit", u"Когти T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Когти T%d." % t,
        ))
        steps.append(_step(
            "claws_hit", u"Когти T%d (крит)" % t, "physical",
            hits_needed=2, tier=t, must_crit=True,
            prep_text=u"Прыгай и бей.",
        ))
    steps.append(_step(
        "dash", u"Кошачий рывок", "physical",
        hits_needed=1, cd_required=False, skippable=True,
        prep_text=u"Активируй рывок и попади в манекен.",
    ))
    return steps


def _pb_shanks():
    steps = []
    for t in [1, 2, 3, 4, 5, 6]:
        steps.append(_step(
            "griffon_hit", u"Грифон T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Грифон T%d." % t,
        ))
        steps.append(_step(
            "griffon_hit", u"Грифон T%d (крит)" % t, "physical",
            hits_needed=2, tier=t, must_crit=True,
            prep_text=u"Прыгай и бей.",
        ))
    return steps


def _pb_geto():
    return [
        _step("summon_dmg", u"Атака призванного зверя", "physical",
              hits_needed=2, cd_required=False,
              prep_text=u"Призови моба. Дай ему подойти и ударить манекен."),
        _step("territory", u"Расширение территории (ульт)", "aoe",
              hits_needed=1, cd_required=False, skippable=True,
              prep_text=u"Активируй ульт рядом с манекеном."),
    ]


def _pb_poseidon():
    steps = []
    for t in [1, 2, 3]:
        steps.append(_step(
            "trident_hit", u"Трезубец T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Трезубец T%d." % t,
        ))
        steps.append(_step(
            "trident_hit", u"Трезубец T%d (крит)" % t, "physical",
            hits_needed=2, tier=t, must_crit=True,
            prep_text=u"Прыгай и бей.",
        ))
    steps.append(_step(
        "trident_throw", u"Бросок Трезубца", "projectile",
        hits_needed=2, cd_required=False,
        prep_text=u"Метни трезубец в манекен.",
    ))
    steps.append(_step(
        "tidal_wave", u"Приливная волна (ульт)", "aoe",
        hits_needed=1, cd_required=False, skippable=True,
        prep_text=u"Активируй волну.",
    ))
    return steps


def _pb_warden():
    steps = []
    for t in [1, 2, 3]:
        steps.append(_step(
            "pick_hit", u"Сердце Скалка T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Сердце Скалка T%d." % t,
        ))
        steps.append(_step(
            "pick_hit", u"Сердце Скалка T%d (крит)" % t, "physical",
            hits_needed=2, tier=t, must_crit=True,
            prep_text=u"Прыгай и бей.",
        ))
    steps.append(_step(
        "sonic_boom", u"Звуковой удар (чистый 4 HP)", "pure",
        hits_needed=3, cd_required=False,
        prep_text=u"ПКМ активирует Звуковой удар. Есть 3 заряда.",
    ))
    steps.append(_step(
        "sculk_strike", u"Скалковый удар", "physical",
        hits_needed=1, cd_required=False, skippable=True,
        prep_text=u"Активируй скалковый удар.",
    ))
    # Инстинкт слепого: +75% исход. Отдельно активируем, потом 5 обычных ударов.
    steps.append(_step(
        "blind_instinct_bonus", u"Инстинкт слепого — базовые удары БЕЗ баффа", "physical",
        hits_needed=3, tier=3, must_crit=False,
        prep_text=u"Убедись, что Инстинкт НЕ активен. Бей нормально T3.",
    ))
    steps.append(_step(
        "blind_instinct_bonus", u"Инстинкт слепого — АКТИВИРУЙ и бей", "physical",
        hits_needed=3, tier=3, must_crit=False,
        prep_text=u"Активируй Инстинкт слепого, потом бей нормально T3.",
        hint=u"Средний урон должен быть в 1.75x выше предыдущего окна.",
    ))
    return steps


def _pb_dragon():
    steps = []
    for t in [1, 2, 3]:
        steps.append(_step(
            "eye_hit", u"Око Дракона T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Око Дракона T%d." % t,
        ))
        steps.append(_step(
            "eye_hit", u"Око Дракона T%d (крит)" % t, "physical",
            hits_needed=2, tier=t, must_crit=True,
            prep_text=u"Прыгай и бей.",
        ))
    steps.append(_step(
        "fireball", u"Драконий фаербол", "projectile",
        hits_needed=2, cd_required=False,
        prep_text=u"ПКМ фаербол, 2 заряда.",
    ))
    steps.append(_step(
        "breath", u"Драконье дыхание", "magic",
        hits_needed=2, cd_required=False,
        prep_text=u"Активируй дыхание, дай манекену стоять в облаке.",
    ))
    return steps


def _pb_amonra():
    return [
        _step("nur_hit", u"Копьё Нур (обычный)", "physical",
              hits_needed=3, must_crit=False, prep_text=u"Копьё Нур. Стой."),
        _step("nur_hit", u"Копьё Нур (крит)", "physical",
              hits_needed=2, must_crit=True, prep_text=u"Прыгай и бей."),
        _step("sun_ray", u"Солнечный луч", "magic",
              hits_needed=1, cd_required=False, prep_text=u"Активируй луч."),
        _step("sun_burst", u"Взрыв Солнца (ульт)", "aoe",
              hits_needed=1, cd_required=False, prep_text=u"Активируй Взрыв Солнца."),
    ]


def _pb_shaman():
    return [
        _step("wrath", u"Гнев стихий (ульт)", "aoe",
              hits_needed=1, cd_required=False,
              prep_text=u"Активируй Гнев стихий рядом с манекеном."),
    ]


def _pb_steelgorn():
    steps = []
    for t in [1, 2, 3]:
        steps.append(_step(
            "axe_hit", u"Удар Топором T%d (обычный)" % t, "physical",
            hits_needed=3, tier=t, must_crit=False,
            prep_text=u"Топор Стальгорна T%d. Стой на земле, НЕ прыгай." % t,
            hint=u"Каждый удар накладывает 'Тяжесть' на цель. Проверь замедление."))
        steps.append(_step(
            "axe_hit", u"Удар Топором T%d (крит)" % t, "physical",
            hits_needed=2, tier=t, must_crit=True,
            prep_text=u"Прыгай и бей."))
    steps.append(_step(
        "dash", u"Рывок лесоруба (6 HP + Slow IV)", "physical",
        hits_needed=1, cd_required=False, must_crit=None,
        prep_text=u"Активируй /steelgorn рывок и попади в манекен.",
        hero_command=u"/steelgorn рывок"))
    steps.append(_step(
        "stone_armor", u"Каменная броня (первый удар -60%)", "buff",
        hits_needed=1, cd_required=False, must_crit=None,
        expect_utility=True,
        prep_text=u"Активируй /steelgorn броня. Затем попроси кого-то ударить тебя.",
        hint=u"Первый удар должен пройти на 40% (actionbar это подтвердит). "
             u"Длит. 7 сек, CD 50 сек.",
        hero_command=u"/steelgorn броня"))
    steps.append(_step(
        "earthquake", u"Землетрясение (AoE 4 HP)", "aoe",
        hits_needed=1, cd_required=False, must_crit=None,
        prep_text=u"Активируй /steelgorn ульт рядом с манекеном.",
        hint=u"После активации Стальгорн 3 сек не может атаковать (проверь).",
        hero_command=u"/steelgorn ульт"))
    return steps


def _pb_wendy():
    return [
        _step("troia", u"Троя — Регенерация I цели", "buff",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"Наведись на манекен. /wendy троя",
              hint=u"У цели должна появиться Регенерация I на 15 сек.",
              hero_command=u"/wendy троя"),
        _step("vernier", u"Вернир — Скорость I цели", "buff",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"Наведись, ждём 30 сек магии-CD, /wendy вернир",
              hint=u"Проверь Speed I на цели.",
              hero_command=u"/wendy вернир"),
        _step("arms", u"Армс — Сила I цели", "buff",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"/wendy армс (ждать CD магии 30 сек)",
              hero_command=u"/wendy армс"),
        _step("armor", u"Армор — Сопротивление I цели", "buff",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"/wendy армор",
              hero_command=u"/wendy армор"),
        _step("claw", u"Коготь Небесного Дракона (KB ~20 бл)", "cc",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"Наведись на манекен, /wendy коготь",
              hint=u"Манекен должен улететь ~20 блоков вперёд.",
              hero_command=u"/wendy коготь"),
        _step("reraise", u"Ре-райс (купол + Glowing + Jump II)", "buff",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"/wendy рерайс — пусть кто-то стрельнёт стрелой в купол.",
              hint=u"Стрела должна отразиться. Манекен получит Glowing 5с.",
              hero_command=u"/wendy рерайс"),
        _step("ult", u"Драконья Ярость — активация", "buff",
              hits_needed=1, cd_required=False, must_crit=None,
              expect_utility=True,
              prep_text=u"/wendy ульт. Проверь бафы: Speed II, Resist I, "
                        u"NightVis, FireRes, Flight на 15 сек.",
              hero_command=u"/wendy ульт"),
        _step("sonic", u"Sonic Boom в ульте (4 HP чистого)", "pure",
              hits_needed=2, cd_required=False, must_crit=None,
              prep_text=u"Во время ульта: /wendy сонник — наведись на манекен.",
              hint=u"4 HP чистого MAGIC + подброс. До 4 зарядов.",
              hero_command=u"/wendy сонник"),
    ]


PLAYBOOKS = {
    "kris":       _pb_kris(),
    "doom":       _pb_doom(),
    "demiurg":    _pb_demiurg(),
    "spider":     _pb_spider(),
    "archer":     _pb_archer(),
    "architect":  _pb_architect(),
    "mihawk":     _pb_mihawk(),
    "griblet":    _pb_griblet(),
    "barsik":     _pb_barsik(),
    "shanks":     _pb_shanks(),
    "geto":       _pb_geto(),
    "poseidon":   _pb_poseidon(),
    "warden":     _pb_warden(),
    "dragon":     _pb_dragon(),
    "amonra":     _pb_amonra(),
    "shaman":     _pb_shaman(),
    "steelgorn":  _pb_steelgorn(),
    "wendy":      _pb_wendy(),
}


def _step_prompt_lines(step, idx, total, hits, target_name):
    """Форматирует «карточку» шага для чата тестеру."""
    tier_str = u"" if step.get("tier") is None else (u" §8[T§f%d§8]" % step["tier"])
    crit_str = u""
    if step.get("must_crit") is True:  crit_str = u" §c§l(ТОЛЬКО КРИТ)"
    elif step.get("must_crit") is False: crit_str = u" §a(без крита)"
    cd_str = u" §7(ждать полный cd)" if step.get("cd_required") else u""
    lines = [
        u"§8§m--------------------§r §b§lШаг %d/%d§r §8§m--------------------§r" % (idx + 1, total),
        u"§b» §f" + step["ability_name"] + tier_str + crit_str + cd_str,
        u"§7» " + step.get("prep_text", u""),
    ]
    if step.get("hint"):
        lines.append(u"§8» " + step["hint"])
    if step.get("hero_command"):
        lines.append(u"§8» команда: §f" + step["hero_command"])
    lines.append(u"§7Прогресс: §f%d§7/§f%d" % (hits, step["hits_needed"]))
    return lines


def _guided_apply_step(session, step, dummy):
    """Вызывается при входе в новый шаг: устанавливает тир, обнуляет счётчик."""
    session["step_hits"] = 0
    session["step_rejected"] = 0
    session["step_started"] = now_tick()
    # Установить тир — вызвать character_tier_setters.<hero>(player, tier).
    tier = step.get("tier")
    if tier is not None:
        try:
            props = System.getProperties()
            setters = props.get("character_tier_setters")
            if setters is not None:
                fn = setters.get(session["hero"])
                if fn is not None:
                    p = Bukkit.getPlayer(JUUID.fromString(session["target_uuid"]))
                    if p is not None and p.isOnline():
                        fn(p, tier)
        except Exception as ex:
            Bukkit.getLogger().warning("[dummy][zbt] tier set failed: " + str(ex))

    # Уведомляем тестера и админов.
    p = None
    try:
        p = Bukkit.getPlayer(JUUID.fromString(session["target_uuid"]))
    except Exception:
        p = None
    lines = _step_prompt_lines(step, session["step_idx"], len(session["playbook"]),
                                0, session["target_name"])
    if p is not None and p.isOnline():
        for ln in lines:
            p.sendMessage(ln)
        try:
            world = p.getWorld()
            world.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_PLING, 1.0, 1.2)
        except Exception:
            pass
    # Админам покажем короткую сводку.
    for pp in Bukkit.getOnlinePlayers():
        if _is_admin(pp) and (p is None or not pp.equals(p)):
            pp.sendMessage(u"§8[ЗБТ-guided] §7шаг %d/%d — §b" % (
                session["step_idx"] + 1, len(session["playbook"])) + step["ability_name"])


def _guided_next_step(session, dummy):
    session["step_idx"] += 1
    if session["step_idx"] >= len(session["playbook"]):
        # Плейбук пройден.
        try:
            p = Bukkit.getPlayer(JUUID.fromString(session["target_uuid"]))
            if p is not None and p.isOnline():
                p.sendMessage(u"§a§l✓ ЗБТ пройден полностью! Спасибо.")
                p.getWorld().playSound(p.getLocation(),
                    Sound.UI_TOAST_CHALLENGE_COMPLETE, 1.0, 1.0)
        except Exception:
            pass
        for pp in Bukkit.getOnlinePlayers():
            if _is_admin(pp):
                pp.sendMessage(u"§a§l[ЗБТ] Плейбук §f" + session["hero"]
                               + u" §aпройден до конца. Останови ЗБТ для сохранения отчёта.")
        return False
    step = session["playbook"][session["step_idx"]]
    _guided_apply_step(session, step, dummy)
    return True


def _guided_skip_current(session, dummy):
    idx = session["step_idx"]
    if idx >= len(session["playbook"]):
        return False
    step = session["playbook"][idx]
    for pp in Bukkit.getOnlinePlayers():
        if _is_admin(pp):
            pp.sendMessage(u"§e[ЗБТ] Шаг §f" + step["ability_name"] + u" §eпропущен админом.")
    return _guided_next_step(session, dummy)


# =============================================================================
# /ЗБТ ПЛЕЙБУКИ
# =============================================================================


def _detect_hero_of_player(player):
    """
    Определяет id персонажа игрока по инвентарю (PDC-меткам предметов героев).
    Возвращает (hero_id, tier_or_None) либо (None, None).
    """
    try:
        inv = player.getInventory()
    except Exception:
        return (None, None)

    items = []
    try:
        for i in range(inv.getSize()):
            it = inv.getItem(i)
            if it is not None and it.getType() != Material.AIR:
                items.append(it)
        for it in [inv.getHelmet(), inv.getChestplate(), inv.getLeggings(), inv.getBoots(), inv.getItemInOffHand()]:
            if it is not None and it.getType() != Material.AIR:
                items.append(it)
    except Exception:
        pass

    # Проверяем каждый предмет.
    for it in items:
        meta = it.getItemMeta()
        if meta is None: continue
        pdc = meta.getPersistentDataContainer()
        for hero_id, spec in HERO_SPECS.items():
            for key_str in spec["item_pdc_keys"]:
                k = NamespacedKey.fromString(key_str)
                if pdc.has(k, PersistentDataType.BYTE):
                    tier = None
                    tk = spec.get("tier_pdc_key")
                    if tk:
                        tkey = NamespacedKey.fromString(tk)
                        if pdc.has(tkey, PersistentDataType.INTEGER):
                            tier = pdc.get(tkey, PersistentDataType.INTEGER)
                    return (hero_id, tier)

    # Fallback — через character_owners (по нику).
    try:
        props = System.getProperties()
        owners_map = props.get("character_owners")
        if owners_map is not None:
            nick = player.getName().lower()
            for hero_id in HERO_SPECS.keys():
                lst = owners_map.get(hero_id)
                if lst is None: continue
                for n in lst:
                    if n and n.lower() == nick and nick != u"blueredtronce":
                        return (hero_id, None)
    except Exception:
        pass

    return (None, None)


def _classify_ability(session, event, is_pure, attacker, item_in_hand):
    """
    По событию и состоянию сессии определяет id способности + подсказку.
    Возвращает (ability_id, ability_name, extra_info).
    """
    hero = session["hero"]
    spec = HERO_SPECS.get(hero)
    if spec is None:
        return ("unknown", u"Неизвестно", u"")

    dmg = event.getDamager()
    cause = event.getCause().name()
    proj_owner_hero = None

    # 1) Снаряды: по PDC-меткам снаряда.
    try:
        if hasattr(dmg, "getPersistentDataContainer"):
            pdc = dmg.getPersistentDataContainer()
            # Spider paint web
            if pdc.has(NamespacedKey.fromString("spideragent:proj_owner"), PersistentDataType.STRING):
                proj_owner_hero = "spider"
            elif pdc.has(NamespacedKey.fromString("archer:arrow"), PersistentDataType.BYTE):
                proj_owner_hero = "archer"
            elif pdc.has(NamespacedKey.fromString("dragon:fireball_marker"), PersistentDataType.BYTE):
                proj_owner_hero = "dragon"
    except Exception:
        pass

    if proj_owner_hero == "spider" and hero == "spider":
        return ("web_shot", u"Паутинный снаряд", u"cause=" + cause)
    if proj_owner_hero == "archer" and hero == "archer":
        return ("caladbolg", u"Каладболг (стрела)", u"cause=" + cause)
    if proj_owner_hero == "dragon" and hero == "dragon":
        return ("fireball", u"Драконий фаербол", u"cause=" + cause)

    # 2) Метательный трезубец Посейдона (Damager — Trident-entity).
    try:
        from org.bukkit.entity import Trident
        if isinstance(dmg, Trident) and hero == "poseidon":
            return ("trident_throw", u"Бросок Трезубца", u"cause=" + cause)
    except Exception:
        pass

    # 3) Чистый/магический урон (без прямого контакта — часто скилл).
    if is_pure:
        # По герою маппим на характерную способность.
        pure_map = {
            "warden":   ("sonic_boom",  u"Звуковой удар"),
            "kris":     ("true_strike", u"Истинный удар (+2❤ чистый)"),
            "doom":     ("repulsor",    u"Репульсор"),
            "demiurg":  ("verdict",     u"Суд/Карающая Десница"),
            "amonra":   ("sun_ray",     u"Солнечный луч"),
            "mihawk":   ("great_slash", u"Великий Разрез"),
            "griblet":  ("sticky_tongue", u"Липкий язык / Метеорит"),
            "dragon":   ("breath",      u"Драконье дыхание"),
            "poseidon": ("tidal_wave",  u"Приливная волна"),
            "shaman":   ("wrath",       u"Гнев стихий"),
            "amonra":   ("sun_ray",     u"Солнечный луч/Взрыв"),
        }
        if hero in pure_map:
            aid, aname = pure_map[hero]
            return (aid, aname, u"cause=" + cause + u" (чистый/магия)")
        return ("pure_unknown", u"Чистый урон", u"cause=" + cause)

    # 4) Мили: смотрим PDC предмета в руке.
    if item_in_hand is not None:
        try:
            meta = item_in_hand.getItemMeta()
            if meta is not None:
                pdc = meta.getPersistentDataContainer()
                # Явное сопоставление
                pairs = [
                    ("kris:blade",       "blade_hit",     u"Удар клинком"),
                    ("doomlord:sword",   "sword_hit",     u"Удар меча"),
                    ("demiurg:staff",    "staff_hit",     u"Удар Посохом"),
                    ("archer:item",      "kanshou_bakuya",u"Каншо/Бакуя"),
                    ("architect:key",    "key_hit",       u"Удар Ключом"),
                    ("mihawk:yoru",      "yoru_hit",      u"Удар Ёру"),
                    ("griblet:staff",    "staff_hit",     u"Удар посохом"),
                    ("barsik:claws",     "claws_hit",     u"Удар когтями"),
                    ("shanks:griffon",   "griffon_hit",   u"Удар Грифоном"),
                    ("poseidon:trident", "trident_hit",   u"Удар Трезубцем"),
                    ("warden:pick",      "pick_hit",      u"Удар Сердцем Скалка"),
                    ("dragon:eye",       "eye_hit",       u"Удар Оком Дракона"),
                    ("amonra:nur",       "nur_hit",       u"Удар Копьём Нур"),
                    ("spideragent:ejector","ejector_hit", u"Удар эжектором"),
                    ("steelgorn:axe",    "axe_hit",       u"Удар Топором"),
                ]
                for keystr, aid, aname in pairs:
                    k = NamespacedKey.fromString(keystr)
                    if pdc.has(k, PersistentDataType.BYTE):
                        return (aid, aname, u"cause=" + cause)
        except Exception:
            pass

    return ("generic_hit", u"Обычный удар (без метки)", u"cause=" + cause)


def _get_expected_for(session, ability_id, tier):
    """Возвращает (min,max) или None."""
    spec = HERO_SPECS.get(session["hero"])
    if spec is None: return None
    for ab in spec["abilities"]:
        if ab["id"] != ability_id: continue
        if "expected" in ab and ab["expected"] is not None:
            return ab["expected"]
        if "expected_by_tier" in ab:
            if tier is None: return None
            return ab["expected_by_tier"].get(tier)
    return None


def _record_hit(session, ability_id, ability_name, kind, raw, final, tier, extra, armor_mode=None,
                expect_utility=False):
    exp = _get_expected_for(session, ability_id, tier)
    exp_in_armor = None
    if exp is not None and armor_mode is not None:
        lo_arm = _expected_after_armor(exp[0], kind, armor_mode)
        hi_arm = _expected_after_armor(exp[1], kind, armor_mode)
        exp_in_armor = (lo_arm, hi_arm)
    is_rejected = False
    try:
        if extra and (u"REJECT" in extra if isinstance(extra, unicode) else "REJECT" in extra):
            is_rejected = True
    except Exception:
        pass
    verdict = "?"
    if is_rejected:
        verdict = "SKIP"
    elif expect_utility:
        # Utility-способность: урон не оценивается. Отчёт покажет 'UTIL'.
        verdict = "UTIL"
    else:
        ref = exp_in_armor if exp_in_armor is not None else exp
        if ref is not None:
            lo, hi = ref
            if final < lo * 0.85:      verdict = "LOW"
            elif final > hi * 1.15:    verdict = "HIGH"
            else:                       verdict = "OK"
    entry = {
        "tick": now_tick(),
        "ability_id": ability_id,
        "ability_name": ability_name,
        "kind": kind,
        "raw": raw,
        "final": final,
        "tier": tier,
        "expected":          exp,
        "expected_in_armor": exp_in_armor,
        "armor_mode":        armor_mode,
        "verdict": verdict,
        "extra": extra,
        "rejected": is_rejected,
        "utility":  expect_utility,
    }
    session["hits"].append(entry)
    if not is_rejected:
        session["checked"].add(ability_id)
    return entry


def _vanilla_armor_reduce(damage, armor_pts, toughness, epf):
    """Считает финальный урон после ванильной формулы Java Edition:
       armor_mit = min(20, max(A/5, A - 4D/(T+8))) / 25
       final = D * (1 - armor_mit) * (1 - min(20,EPF)*0.04)
    Возвращает (final_hp, armor_pct, prot_pct)."""
    if damage <= 0:
        return (0.0, 0.0, 0.0)
    A = float(armor_pts); T = float(toughness); D = float(damage)
    if A <= 0 and epf <= 0:
        return (D, 0.0, 0.0)
    m1 = A - (4.0 * D) / (T + 8.0)
    m2 = A / 5.0
    armor_mit = min(20.0, max(m2, m1)) / 25.0
    after_armor = D * (1.0 - armor_mit)
    prot_mit = min(20.0, float(epf)) * 0.04
    final = after_armor * (1.0 - prot_mit)
    return (final, armor_mit, prot_mit)


# Профили брони манекена (соответствуют ARMOR_MODES).
# (armor_points, toughness, epf_general).
# ВАЖНО: манекен — Zombie, у которого ванильно 2 armor points базово.
# Значения ниже включают эти 2 point'а для профиля "none" и не меняются
# для остальных, потому что ArmorSet заменяет их.
ARMOR_PROFILES = {
    u"none":      (2.0,  0.0,  0.0),   # Zombie base armor
    u"leather":   (7.0,  0.0,  0.0),
    u"iron":      (15.0, 0.0,  0.0),
    u"diamond":   (20.0, 8.0,  0.0),
    u"netherite": (20.0, 12.0, 0.0),
    u"net_prot4": (20.0, 12.0, 16.0),   # 4x Protection IV = 16 EPF
}


def _expected_after_armor(base_dmg, kind, armor_mode):
    """Возвращает ожидаемое финальное значение с учётом брони.
       kind: 'physical' / 'pure' / 'magic'.
       Для 'pure' (наш true damage) броня и Protection игнорируются.
       Для 'physical' — полная формула.
       Для 'magic' — armor points игнорируются (mit=0), но Protection работает."""
    prof = ARMOR_PROFILES.get(armor_mode or u"none", (0.0, 0.0, 0.0))
    A, T, EPF = prof
    if kind == "pure":
        return base_dmg
    if kind == "magic":
        # Только Protection.
        prot_mit = min(20.0, EPF) * 0.04
        return base_dmg * (1.0 - prot_mit)
    # physical
    final, _, _ = _vanilla_armor_reduce(base_dmg, A, T, EPF)
    return final


def _fmt_report(session):
    def U(x):
        if isinstance(x, unicode): return x
        try:    return unicode(x, "utf-8", "replace")
        except Exception:
            try:    return unicode(x)
            except Exception: return u"?"

    lines = []
    lines.append(u"=" * 78)
    lines.append(u"MINECRAFT ZBT DAMAGE REPORT")
    lines.append(u"=" * 78)
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session["started_ms"] / 1000.0))
    lines.append(u"Started        : " + U(ts))
    lines.append(u"Started by     : " + U(session.get("started_by", "unknown")))
    lines.append(u"Target player  : " + U(session["target_name"]) + u" (" + U(session["target_uuid"]) + u")")
    lines.append(u"Detected hero  : " + U(session["hero"]))
    lines.append(u"Dummy UUID     : " + U(session["dummy_uuid"]))
    lines.append(u"Total hits     : " + U(str(len(session["hits"]))))
    if session["checked"]:
        lines.append(u"Abilities seen : " + U(", ".join(sorted(session["checked"]))))
    else:
        lines.append(u"Abilities seen : (none)")
    lines.append(u"")
    lines.append(u"SPEC SUMMARY (expected damage in HP; 1 heart = 2 HP)")
    lines.append(u"-" * 78)
    spec = HERO_SPECS.get(session["hero"], {})
    for ab in spec.get("abilities", []):
        line = u"  * [%s] %s (kind=%s)" % (U(ab["id"]), U(ab["name"]), U(ab["kind"]))
        if "expected" in ab and ab["expected"] is not None:
            line += u"  expected=%.1f..%.1f HP" % (ab["expected"][0], ab["expected"][1])
        elif "expected_by_tier" in ab:
            parts = [u"T%d:%.1f..%.1f" % (t, v[0], v[1]) for t, v in sorted(ab["expected_by_tier"].items())]
            line += u"  " + u" ".join(parts)
        lines.append(line)
        note = ab.get("note", u"")
        if note:
            lines.append(u"      note: " + U(note))
        seen_str = u"  [OBSERVED]" if ab["id"] in session["checked"] else u"  [NOT OBSERVED]"
        lines.append(u"     " + seen_str)
    lines.append(u"")
    # Guided-плейбук — сводка по шагам.
    if session.get("mode") == "guided":
        pb = session.get("playbook", [])
        idx = session.get("step_idx", 0)
        lines.append(u"GUIDED PLAYBOOK PROGRESS")
        lines.append(u"-" * 78)
        step_stats = {}
        for h in session["hits"]:
            ex = h.get("extra", u"") or u""
            if isinstance(ex, unicode): ex_ascii = ex.encode("ascii", "replace")
            else: ex_ascii = ex
            step_n = None
            try:
                tokens = ex_ascii.split()
                for i, t in enumerate(tokens):
                    if t == "step" and i + 1 < len(tokens):
                        step_n = int(tokens[i + 1]) - 1
                        break
            except Exception:
                step_n = None
            if step_n is not None:
                step_stats.setdefault(step_n, []).append(h)
        for si, st in enumerate(pb):
            hits_here = step_stats.get(si, [])
            valid    = [h for h in hits_here if not h.get("rejected")]
            rejected = [h for h in hits_here if h.get("rejected")]
            if len(valid) >= st["hits_needed"]:
                status = u"[DONE]"
            elif si == idx:
                status = u"[CURRENT]"
            elif si < idx:
                status = u"[SKIPPED]"
            else:
                status = u"[PENDING]"
            avg_str = u"-"
            if valid:
                avg = sum(h["final"] for h in valid) / float(len(valid))
                avg_str = u"avg=%.2f" % avg
            crit_tag = u""
            if st.get("must_crit") is True:  crit_tag = u" crit-only"
            elif st.get("must_crit") is False: crit_tag = u" no-crit"
            tier_tag = u"" if st.get("tier") is None else (u" T%d" % st["tier"])
            lines.append(u"  %2d. %-9s %s%s%s : %d/%d hits (rej %d)  %s" % (
                si + 1, status, U(st["ability_name"]), tier_tag, crit_tag,
                len(valid), st["hits_needed"], len(rejected), avg_str))
        lines.append(u"")

    lines.append(u"HITS LOG")
    lines.append(u"-" * 78)
    lines.append(u"%-6s %-24s %-10s %-8s %-8s %-6s %-6s %-14s %-14s %s" %
                 (u"tick", u"ability", u"kind", u"raw", u"final", u"tier", u"armor",
                  u"exp_bare", u"exp_in_armor", u"verdict|extra"))
    for h in session["hits"]:
        exp_str = u"-"
        if h["expected"]:
            exp_str = u"%.1f..%.1f" % (h["expected"][0], h["expected"][1])
        exp_arm_str = u"-"
        if h.get("expected_in_armor"):
            exp_arm_str = u"%.2f..%.2f" % (h["expected_in_armor"][0], h["expected_in_armor"][1])
        armor_str = h.get("armor_mode") or u"?"
        extra = U(h.get("extra", u"") or u"")
        lines.append(u"%-6d %-24s %-10s %-8.2f %-8.2f %-6s %-6s %-14s %-14s %s | %s" % (
            int(h["tick"] - session["started_tick"]),
            U(h["ability_id"]),
            U(h["kind"]),
            h["raw"], h["final"],
            U(str(h["tier"])) if h["tier"] is not None else u"-",
            U(armor_str[:6]),
            exp_str,
            exp_arm_str,
            U(h["verdict"]),
            extra,
        ))
    lines.append(u"")
    lines.append(u"AGGREGATED DAMAGE (only full-charge hits, cd >= 0.9)")
    lines.append(u"-" * 78)
    lines.append(u"Physical melee: attack cooldown must be ~1.0 for realistic damage.")
    lines.append(u"Hits with cd < 0.9 are excluded here (they were spam-clicks).")
    lines.append(u"expected_bare  = SPEC damage vs naked target (armor=none).")
    lines.append(u"expected_armor = SPEC damage after applying vanilla armor+prot formula.")
    lines.append(u"Verdict is ALWAYS compared against expected_armor (what player actually sees).")
    lines.append(u"")
    from collections import defaultdict
    groups = defaultdict(list)
    all_by_key = defaultdict(list)
    for h in session["hits"]:
        # Rejected удары (guided) полностью исключаем — они не показатель.
        if h.get("rejected"):
            continue
        # Utility-удары (нет прямого урона по задумке) исключаем из статистики
        # OK/LOW/HIGH: у них verdict=UTIL и попадания важны как факт, не как HP.
        if h.get("utility") or h.get("verdict") == "UTIL":
            continue
        # Извлекаем cd из extra.
        cd_val = None
        ex = h.get("extra", u"") or u""
        if isinstance(ex, unicode): ex_ascii = ex.encode("ascii", "replace")
        else: ex_ascii = ex
        try:
            for tok in ex_ascii.split():
                if tok.startswith("cd="):
                    v = tok[3:]
                    if v != "n/a":
                        cd_val = float(v)
                        break
        except Exception:
            cd_val = None
        armor_mode = h.get("armor_mode") or u"none"
        # Определяем крит по метке "CRIT" в extra.
        was_crit = False
        try:
            if isinstance(ex, unicode):
                was_crit = (u"CRIT" in ex)
            else:
                was_crit = ("CRIT" in ex_ascii)
        except Exception:
            pass
        key = (h["ability_id"], h["tier"], armor_mode, h["kind"], was_crit)
        all_by_key[key].append(h["final"])
        if h["kind"] != "physical" or (cd_val is not None and cd_val >= 0.9) or cd_val is None:
            groups[key].append(h["final"])

    lines.append(u"%-22s %-4s %-9s %-5s %-5s %-4s %-8s %-8s %-8s %-14s %-14s %s" %
                 (u"ability", u"tier", u"armor", u"kind", u"crit", u"n", u"min", u"max", u"avg",
                  u"exp_bare", u"exp_armored", u"verdict"))
    for key, vals in sorted(groups.items()):
        aid, tier, armor_mode, kind, was_crit = key
        n_total = len(all_by_key[key])
        n_full  = len(vals)
        if not vals: continue
        mn, mx = min(vals), max(vals)
        avg = sum(vals) / float(len(vals))
        exp = None
        spec = HERO_SPECS.get(session["hero"], {})
        for ab in spec.get("abilities", []):
            if ab["id"] != aid: continue
            if "expected" in ab and ab["expected"] is not None:
                exp = ab["expected"]
            elif "expected_by_tier" in ab and tier is not None:
                exp = ab["expected_by_tier"].get(tier)
            break
        exp_str = (u"%.1f..%.1f" % exp) if exp else u"-"
        # Ожидание в текущей броне. Для крита базу × 1.5 ДО брони.
        exp_arm = None
        if exp is not None:
            lo0, hi0 = exp
            if was_crit and kind == "physical":
                lo0 *= 1.5; hi0 *= 1.5
            lo_a = _expected_after_armor(lo0, kind, armor_mode)
            hi_a = _expected_after_armor(hi0, kind, armor_mode)
            exp_arm = (lo_a, hi_a)
        exp_arm_str = (u"%.2f..%.2f" % exp_arm) if exp_arm else u"-"
        verdict = u"?"
        ref = exp_arm if exp_arm else exp
        if ref is not None:
            lo, hi = ref
            if avg < lo * 0.85: verdict = u"LOW"
            elif avg > hi * 1.15: verdict = u"HIGH"
            else: verdict = u"OK"
        note_spam = u"" if n_full == n_total else (u" (excluded %d spam-hits)" % (n_total - n_full))
        crit_tag = u"YES" if was_crit else u"no"
        lines.append(u"%-22s %-4s %-9s %-5s %-5s %-4d %-8.2f %-8.2f %-8.2f %-14s %-14s %s%s" % (
            U(aid),
            U(str(tier) if tier is not None else "-"),
            U(armor_mode[:9]),
            U(kind[:5]),
            crit_tag,
            n_full, mn, mx, avg,
            exp_str, exp_arm_str, verdict, note_spam
        ))

    lines.append(u"")
    lines.append(u"=" * 78)
    lines.append(u"PROMPT FOR EXTERNAL REVIEWER (paste to another AI):")
    lines.append(u"-" * 78)
    lines.append(u"You are a Minecraft PvP balance reviewer for a Paper 1.21 PvP/RP server.")
    lines.append(u"Below is a damage log collected on a training dummy against character")
    lines.append(u"'" + U(session["hero"]) + u"'. The dummy is a vanilla Zombie with configurable")
    lines.append(u"armor; if the armor row shows 'diff=X' in raw vs final, that was armor.")
    lines.append(u"")
    lines.append(u"IMPORTANT CONTEXT ABOUT MINECRAFT DAMAGE MECHANICS:")
    lines.append(u"  * Session mode: " + U(session.get("mode", "auto")) + u".")
    lines.append(u"    - 'auto'   = ability auto-classified by PDC tags & damage type.")
    lines.append(u"    - 'guided' = every hit is HARD-assigned to the current playbook step,")
    lines.append(u"      so e.g. Doom's 'Repulsor' vs 'Disintegrator' cannot be confused.")
    lines.append(u"      Rejected hits (verdict=SKIP, extra contains REJECT:) are the ones")
    lines.append(u"      that broke the step constraint (crit when not allowed, cd<0.9,")
    lines.append(u"      etc.). They are already excluded from AGGREGATED.")
    lines.append(u"  * Verdict values:")
    lines.append(u"      OK   -> avg damage within expected range.")
    lines.append(u"      LOW  -> avg below expected by >15%.")
    lines.append(u"      HIGH -> avg above expected by >15%.")
    lines.append(u"      UTIL -> ability is UTILITY / CC / DoT by design (pull, freeze,")
    lines.append(u"              slow, place-web, teleport). Zero-damage hits are EXPECTED.")
    lines.append(u"              Do NOT report these as bugs. Verify by note/hint what")
    lines.append(u"              effect should have been observed.")
    lines.append(u"      SKIP -> hit rejected by guided step constraint.")
    lines.append(u"  * Java Edition formula: armor_mit = min(20, max(A/5, A-4D/(T+8)))/25;")
    lines.append(u"    final = D * (1 - armor_mit) * (1 - min(20,EPF)*0.04).")
    lines.append(u"  * Full Netherite + Protection IV on 4 pieces = 20 armor, 12 toughness,")
    lines.append(u"    16 EPF. This gives ~89-92% total reduction for physical damage.")
    lines.append(u"    So a 10-HP hit leaving ~1.0 HP damage IS the intended vanilla value,")
    lines.append(u"    NOT a bug. The report already computes expected_armored for you.")
    lines.append(u"  * Critical hits multiply base damage by 1.5. If tester was jump-hitting,")
    lines.append(u"    expect ~1.5x values interleaved with normal ones.")
    lines.append(u"  * Attack cooldown < 0.9 reduces damage to 20-45% of base -- excluded")
    lines.append(u"    from AGGREGATED already; see 'excluded N spam-hits' note.")
    lines.append(u"  * True Strike (Kris) is now bypass-armor+prot+resistance+absorption ->")
    lines.append(u"    expect the same ~4.0 HP hit regardless of target's armor.")
    lines.append(u"")
    lines.append(u"Please evaluate:")
    lines.append(u"  1) Look at AGGREGATED DAMAGE section, column 'avg' vs 'expected_armored'.")
    lines.append(u"     Verdict is already OK/LOW/HIGH pre-computed against expected_armored.")
    lines.append(u"     DO NOT re-compare avg to expected_bare -- that ignores armor.")
    lines.append(u"  2) Do buff-abilities (Warden 'Blind Instinct' +75%, Kris 'True Strike'")
    lines.append(u"     +4 HP pure) show up as separate entries with expected bonus?")
    lines.append(u"  3) Any ability marked [NOT OBSERVED] that should have been tested.")
    lines.append(u"  4) Any true LOW/HIGH outliers (not caused by cooldown or armor).")
    lines.append(u"Reply with per-ability verdict and short reasoning.")
    lines.append(u"=" * 78)
    return u"\n".join(lines)


def _save_report(session):
    try:
        base = os.path.join("plugins", "PySpigot", "scripts", "data", "dummy_reports")
        try:
            os.makedirs(base)
        except Exception:
            pass
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(session["started_ms"] / 1000.0))
        safe_name = "".join(c for c in session["target_name"] if c.isalnum() or c in "_-")
        if not safe_name: safe_name = "unknown"
        fname = "%s_%s_%s.txt" % (safe_name, session["hero"], ts)
        fpath = os.path.join(base, fname)
        text = _fmt_report(session)
        f = io.open(fpath, "w", encoding="utf-8")
        try:
            if isinstance(text, str):
                text = text.decode("utf-8", "replace")
            f.write(text)
        finally:
            f.close()
        return fpath
    except Exception as ex:
        Bukkit.getLogger().warning("[dummy][zbt] save_report failed: " + str(ex))
        return None


def _get_zbt_session_for_dummy(dummy):
    if dummy is None: return None
    return zbt_sessions.get(uid(dummy))


def _zbt_is_active(dummy):
    return _get_flag(dummy, KEY_ZBT_ACTIVE) and (uid(dummy) in zbt_sessions)


def _start_zbt(admin, dummy, target_player, hero_override=None, mode="auto"):
    hero, tier = (None, None)
    if hero_override:
        hero = hero_override
    else:
        hero, tier = _detect_hero_of_player(target_player)
    if hero is None:
        admin.sendMessage(u"§cНе удалось определить персонажа игрока §f" + target_player.getName()
                          + u"§c. Возьми ему предмет героя в инвентарь или выбери класс вручную.")
        return False

    dummy_id = uid(dummy)
    session = {
        "dummy_uuid":   dummy_id,
        "target_uuid":  uid(target_player),
        "target_name":  target_player.getName(),
        "hero":         hero,
        "hits":         [],
        "checked":      set(),
        "started_ms":   long(System.currentTimeMillis()),
        "started_tick": now_tick(),
        "started_by":   admin.getName(),
        "armor_mode":   _get_armor_mode(dummy),
        "mode":         mode,
    }
    if mode == "guided":
        playbook = PLAYBOOKS.get(hero)
        if not playbook:
            admin.sendMessage(u"§cДля §f" + hero + u" §cплейбук не задан. Используй auto-режим.")
            return False
        session["playbook"]      = playbook
        session["step_idx"]      = 0
        session["step_hits"]     = 0
        session["step_rejected"] = 0
        session["step_started"]  = now_tick()

    zbt_sessions[dummy_id] = session
    _set_flag(dummy, KEY_ZBT_ACTIVE, True)
    try:
        pdc = dummy.getPersistentDataContainer()
        pdc.set(KEY_ZBT_TARGET, PersistentDataType.STRING, uid(target_player))
        pdc.set(KEY_ZBT_HERO,   PersistentDataType.STRING, hero)
    except Exception:
        pass

    mode_tag = u" §8(guided)" if mode == "guided" else u" §8(auto)"
    try:
        dummy.setCustomName(u"§b§lМанекен ЗБТ §7— §e" + target_player.getName()
                            + u" §8[§d" + HERO_SPECS[hero]["display"] + u"§8]" + mode_tag)
    except Exception:
        pass

    admin.sendMessage(u"§a§l✓ ЗБТ-режим активирован" + mode_tag + u".")
    admin.sendMessage(u"§7Тестируем: §f" + target_player.getName()
                      + u" §8→ §d" + HERO_SPECS[hero]["display"])
    if mode == "guided":
        admin.sendMessage(u"§7Плейбук из §f" + str(len(session["playbook"])) + u" §7шагов. Следи за прогрессом.")
    else:
        admin.sendMessage(u"§7Все удары этого игрока по манекену будут залогированы (auto-classify).")

    if target_player.isOnline():
        target_player.sendMessage(u"§8§l[ЗБТ] §7Ты в режиме тестирования от §f"
                                  + admin.getName() + u"§7. Персонаж: §d"
                                  + HERO_SPECS[hero]["display"] + mode_tag)
        if mode == "guided":
            # Сразу показываем первый шаг.
            _guided_apply_step(session, session["playbook"][0], dummy)
        else:
            target_player.sendMessage(u"§7Бей манекен всеми способностями — я сам их распознаю.")
    return True


def _stop_zbt(admin, dummy, save=True):
    dummy_id = uid(dummy)
    session = zbt_sessions.pop(dummy_id, None)
    _set_flag(dummy, KEY_ZBT_ACTIVE, False)
    try:
        pdc = dummy.getPersistentDataContainer()
        if pdc.has(KEY_ZBT_TARGET, PersistentDataType.STRING):
            pdc.remove(KEY_ZBT_TARGET)
        if pdc.has(KEY_ZBT_HERO, PersistentDataType.STRING):
            pdc.remove(KEY_ZBT_HERO)
    except Exception:
        pass
    try:
        dummy.setCustomName(u"§b§lТренировочный Манекен")
    except Exception:
        pass
    if session is None:
        admin.sendMessage(u"§7ЗБТ уже был выключен.")
        return None
    if not save:
        admin.sendMessage(u"§eЗБТ остановлен без сохранения отчёта.")
        return None
    fpath = _save_report(session)
    if fpath:
        admin.sendMessage(u"§a§l✓ Отчёт сохранён: §f" + fpath)
        admin.sendMessage(u"§7Ударов зарегистрировано: §f" + str(len(session["hits"])))
        admin.sendMessage(u"§7Способностей замечено: §f" + str(len(session["checked"])))
    else:
        admin.sendMessage(u"§cНе удалось сохранить отчёт. См. консоль.")
    return fpath


# =============================================================================
#  DUMMY ENTITY (существующее)
# =============================================================================

def is_dummy(entity):
    if entity is None: return False
    try:
        pdc = entity.getPersistentDataContainer()
        return pdc.has(KEY_DUMMY, PersistentDataType.BYTE)
    except Exception:
        return False


def _get_flag(entity, key):
    try:
        pdc = entity.getPersistentDataContainer()
        if not pdc.has(key, PersistentDataType.BYTE): return False
        return pdc.get(key, PersistentDataType.BYTE) == JByte(1)
    except Exception:
        return False

def _set_flag(entity, key, value):
    try:
        pdc = entity.getPersistentDataContainer()
        pdc.set(key, PersistentDataType.BYTE, JByte(1 if value else 0))
    except Exception:
        pass

def _get_armor_mode(entity):
    try:
        pdc = entity.getPersistentDataContainer()
        if not pdc.has(KEY_ARMOR, PersistentDataType.STRING):
            return u"none"
        return pdc.get(KEY_ARMOR, PersistentDataType.STRING)
    except Exception:
        return u"none"

def _set_armor_mode(entity, mode_id):
    try:
        pdc = entity.getPersistentDataContainer()
        pdc.set(KEY_ARMOR, PersistentDataType.STRING, mode_id)
        _apply_armor(entity, mode_id)
    except Exception:
        pass


def _apply_armor(dummy, mode_id):
    """Надевает набор брони на манекен согласно режиму."""
    try:
        eq = dummy.getEquipment()
    except Exception:
        return
    if eq is None:
        return

    def _piece(mat, prot4=False):
        it = ItemStack(mat, 1)
        m = it.getItemMeta()
        try:
            m.setUnbreakable(True)
            if prot4:
                enc = Registry.ENCHANTMENT.get(NamespacedKey.minecraft("protection"))
                if enc is not None:
                    m.addEnchant(enc, 4, True)
        except Exception:
            pass
        it.setItemMeta(m)
        return it

    # Сначала снимаем всё.
    empty = ItemStack(Material.AIR)
    try:
        eq.setHelmet(empty)
        eq.setChestplate(empty)
        eq.setLeggings(empty)
        eq.setBoots(empty)
    except Exception:
        pass

    if mode_id == u"leather":
        eq.setHelmet(_piece(Material.LEATHER_HELMET))
        eq.setChestplate(_piece(Material.LEATHER_CHESTPLATE))
        eq.setLeggings(_piece(Material.LEATHER_LEGGINGS))
        eq.setBoots(_piece(Material.LEATHER_BOOTS))
    elif mode_id == u"iron":
        eq.setHelmet(_piece(Material.IRON_HELMET))
        eq.setChestplate(_piece(Material.IRON_CHESTPLATE))
        eq.setLeggings(_piece(Material.IRON_LEGGINGS))
        eq.setBoots(_piece(Material.IRON_BOOTS))
    elif mode_id == u"diamond":
        eq.setHelmet(_piece(Material.DIAMOND_HELMET))
        eq.setChestplate(_piece(Material.DIAMOND_CHESTPLATE))
        eq.setLeggings(_piece(Material.DIAMOND_LEGGINGS))
        eq.setBoots(_piece(Material.DIAMOND_BOOTS))
    elif mode_id == u"netherite":
        eq.setHelmet(_piece(Material.NETHERITE_HELMET))
        eq.setChestplate(_piece(Material.NETHERITE_CHESTPLATE))
        eq.setLeggings(_piece(Material.NETHERITE_LEGGINGS))
        eq.setBoots(_piece(Material.NETHERITE_BOOTS))
    elif mode_id == u"net_prot4":
        eq.setHelmet(_piece(Material.NETHERITE_HELMET, prot4=True))
        eq.setChestplate(_piece(Material.NETHERITE_CHESTPLATE, prot4=True))
        eq.setLeggings(_piece(Material.NETHERITE_LEGGINGS, prot4=True))
        eq.setBoots(_piece(Material.NETHERITE_BOOTS, prot4=True))


def spawn_dummy(location):
    """Спавнит Zombie-манекен (полноценная живая цель с броней)."""
    world = location.getWorld()
    # Используем зомби — они принимают удары корректно, не двигаются с NoAI,
    # получают брoню через getEquipment.
    from org.bukkit.entity import EntityType
    dummy = world.spawnEntity(location, EntityType.ZOMBIE)
    try:
        dummy.setAI(False)
        dummy.setInvulnerable(False)
        dummy.setSilent(True)
        dummy.setCanPickupItems(False)
        dummy.setRemoveWhenFarAway(False)
        dummy.setCustomName(u"§b§lТренировочный Манекен")
        dummy.setCustomNameVisible(True)
        # Даём ему много HP чтобы можно было долго тестить.
        try:
            from org.bukkit.attribute import Attribute
            attr = dummy.getAttribute(Attribute.GENERIC_MAX_HEALTH)
            attr.setBaseValue(2000.0)
            dummy.setHealth(2000.0)
        except Exception:
            pass
    except Exception as ex:
        Bukkit.getLogger().warning("[dummy] spawn config: " + str(ex))

    # PDC-флаги дефолтные.
    try:
        pdc = dummy.getPersistentDataContainer()
        pdc.set(KEY_DUMMY, PersistentDataType.BYTE, JByte(1))
        pdc.set(KEY_ARMOR, PersistentDataType.STRING, u"none")
        # Настройки по умолчанию.
        _set_flag(dummy, KEY_FLAG_IGN,  False)
        _set_flag(dummy, KEY_FLAG_EFF,  True)   # считать эффекты по умолчанию
        _set_flag(dummy, KEY_FLAG_IMM,  True)   # бессмертие по умолчанию
        _set_flag(dummy, KEY_FLAG_HEAL, True)   # автоотхил по умолчанию
        _set_flag(dummy, KEY_FLAG_LOG,  False)
    except Exception:
        pass

    return dummy


def find_dummy_by_uuid(uuid_str):
    try:
        e = Bukkit.getEntity(JUUID.fromString(uuid_str))
        if e is not None and is_dummy(e):
            return e
    except Exception:
        pass
    return None


# =============================================================================
#  GUI
# =============================================================================

def open_dummy_gui(player, dummy):
    inv = Bukkit.createInventory(None, 27, u"§b§lТренировочный Манекен")

    # Ряд 1: режимы брони (слоты 0..5).
    for i, (mid, name, _) in enumerate(ARMOR_MODES):
        # Дефолтная иконка "нет брони" — прозрачное стекло.
        mat = Material.LIGHT_GRAY_STAINED_GLASS_PANE
        if   mid == u"none":      mat = Material.BARRIER
        elif mid == u"leather":   mat = Material.LEATHER_CHESTPLATE
        elif mid == u"iron":      mat = Material.IRON_CHESTPLATE
        elif mid == u"diamond":   mat = Material.DIAMOND_CHESTPLATE
        elif mid == u"netherite": mat = Material.NETHERITE_CHESTPLATE
        elif mid == u"net_prot4": mat = Material.NETHERITE_CHESTPLATE

        icon = ItemStack(mat, 1)
        meta = icon.getItemMeta()
        current = _get_armor_mode(dummy)
        prefix = u"§a▶ " if mid == current else u"§7  "
        meta.setDisplayName(prefix + name)
        lore = [u"§8Режим брони манекена"]
        if mid == current:
            lore.append(u"§aВыбрано")
        icon.setItemMeta(meta)
        # Сохраняем ID режима в PDC иконки для клика.
        try:
            m2 = icon.getItemMeta()
            m2.getPersistentDataContainer().set(
                NamespacedKey.fromString("dummy:gui_armor"),
                PersistentDataType.STRING, mid)
            icon.setItemMeta(m2)
        except Exception:
            pass
        m3 = icon.getItemMeta()
        m3.setLore(_java_list(lore))
        icon.setItemMeta(m3)
        inv.setItem(i, icon)

    # Ряд 2 (слоты 9-13): флаги.
    # Каждый флаг: (PDC-ключ, имя, иконка, описание что делает).
    flags = [
        (KEY_FLAG_IGN,  u"Игнорировать броню",  Material.NETHERITE_CHESTPLATE, [
            u"§7Броня манекена не поглощает урон.",
            u"§7Все удары считаются как по голому мобу.",
            u"§8Полезно чтобы увидеть чистые цифры оружия.",
        ]),
        (KEY_FLAG_EFF,  u"Считать эффекты",     Material.POTION, [
            u"§7Учитывать потион-эффекты атакующего:",
            u"§7Strength, Weakness и прочие модификаторы.",
            u"§8Выключено — эффекты игнорируются.",
        ]),
        (KEY_FLAG_IMM,  u"Бессмертие",          Material.TOTEM_OF_UNDYING, [
            u"§7Манекен НЕ умирает.",
            u"§7Урон близкий к смерти отменяется,",
            u"§7HP восстанавливается до максимума.",
        ]),
        (KEY_FLAG_HEAL, u"Автоотхил",           Material.GLISTERING_MELON_SLICE, [
            u"§7Через 1 секунду после удара",
            u"§7HP восстанавливается до максимума.",
            u"§8Работает только при выключенном Бессмертии.",
        ]),
        (KEY_FLAG_LOG,  u"Лог урона",           Material.WRITABLE_BOOK, [
            u"§7Пишет каждый удар в чат:",
            u"§7  §fdamage §7HP (§fтип§7, raw=§f...§7, cause=§f...§7)",
            u"§8Удобно для отладки способностей.",
        ]),
    ]
    for i, (key, name, mat, desc) in enumerate(flags):
        icon = ItemStack(mat, 1)
        meta = icon.getItemMeta()
        val = _get_flag(dummy, key)
        marker = u"§a[✔] " if val else u"§c[ ] "
        meta.setDisplayName(marker + u"§f" + name)
        lore_lines = list(desc)
        lore_lines.append(u"")
        lore_lines.append(u"§eЛКМ §7— переключить")
        lore_lines.append(u"§aСейчас: Включено" if val else u"§cСейчас: Выключено")
        meta.setLore(_java_list(lore_lines))
        # Ключ флага в PDC иконки.
        try:
            pdc_ic = meta.getPersistentDataContainer()
            pdc_ic.set(
                NamespacedKey.fromString("dummy:gui_flag"),
                PersistentDataType.STRING, key.toString())
        except Exception:
            pass
        icon.setItemMeta(meta)
        inv.setItem(9 + i, icon)

    # Ряд 3 (слот 22): сброс статистики.
    reset = ItemStack(Material.TNT, 1)
    meta = reset.getItemMeta()
    meta.setDisplayName(u"§c§lСбросить статистику урона")
    meta.setLore(_java_list([u"§7Обнуляет DPS-счётчик."]))
    reset.setItemMeta(meta)
    inv.setItem(22, reset)

    # Слот 18: ЗБТ-режим (auto — автоклассификация).
    zbt_active = _zbt_is_active(dummy)
    zbt_item = ItemStack(Material.ENCHANTED_BOOK if not zbt_active else Material.BEACON, 1)
    zm = zbt_item.getItemMeta()
    if zbt_active:
        session = _get_zbt_session_for_dummy(dummy)
        target_name = session["target_name"] if session else u"?"
        hero_disp   = HERO_SPECS.get(session["hero"], {}).get("display", u"?") if session else u"?"
        mode_tag = session.get("mode", "auto") if session else "auto"
        step_line = u""
        if session and mode_tag == "guided":
            idx = session.get("step_idx", 0)
            pb  = session.get("playbook", [])
            if 0 <= idx < len(pb):
                st = pb[idx]
                step_line = u"§7Шаг §f%d§7/§f%d§7: §b" % (idx + 1, len(pb)) + st["ability_name"]
        zm.setDisplayName(u"§b§l§oРежим ЗБТ активен §8(" + mode_tag + u")")
        lore = [
            u"§7Тестируется: §f" + target_name,
            u"§7Персонаж: §d" + hero_disp,
        ]
        if step_line:
            lore.append(step_line)
            lore.append(u"§7Прогресс шага: §f" + str(session.get("step_hits", 0)) + u"§7/§f"
                        + str(pb[idx]["hits_needed"]))
        lore.extend([
            u"§7Ударов записано: §f" + (str(len(session["hits"])) if session else u"0"),
            u"",
            u"§eЛКМ §7— остановить и сохранить отчёт",
            u"§eShift+ЛКМ §7— остановить БЕЗ сохранения",
        ])
        if session and mode_tag == "guided":
            lore.append(u"§eПКМ §7— пропустить текущий шаг")
        zm.setLore(_java_list(lore))
    else:
        zm.setDisplayName(u"§b§lРежим ЗБТ (auto)")
        zm.setLore(_java_list([
            u"§7Автоопределение способностей по PDC-меткам",
            u"§7и типу урона. Быстро, но может путать",
            u"§7разные способности одного типа (напр. Репульсор",
            u"§7и Дезинтегратор — оба MAGIC).",
            u"",
            u"§eЛКМ §7— выбрать игрока для теста",
        ]))
    try:
        zm.getPersistentDataContainer().set(
            KEY_GUI_ACTION, PersistentDataType.STRING,
            u"zbt_stop" if zbt_active else u"zbt_pick_auto")
    except Exception:
        pass
    zbt_item.setItemMeta(zm)
    inv.setItem(18, zbt_item)

    # Слот 20: ЗБТ Guided (направляемый).
    if not zbt_active:
        gitem = ItemStack(Material.KNOWLEDGE_BOOK, 1)
        gm = gitem.getItemMeta()
        gm.setDisplayName(u"§b§lРежим ЗБТ Guided §8(направляемый)")
        gm.setLore(_java_list([
            u"§7Плейбук ведёт тестера по шагам:",
            u"§7 - какая способность,",
            u"§7 - какой тир,",
            u"§7 - крит / без крита,",
            u"§7 - сколько ударов нужно.",
            u"",
            u"§7Скрипт САМ выставляет тир,",
            u"§7различает Репульсор vs Дезинтегратор,",
            u"§7отклоняет неправильные удары.",
            u"",
            u"§eЛКМ §7— выбрать игрока для guided-теста",
        ]))
        try:
            gm.getPersistentDataContainer().set(
                KEY_GUI_ACTION, PersistentDataType.STRING, u"zbt_pick_guided")
        except Exception:
            pass
        gitem.setItemMeta(gm)
        inv.setItem(20, gitem)

    # Слот 26: закрыть.
    close = ItemStack(Material.RED_STAINED_GLASS_PANE, 1)
    meta = close.getItemMeta()
    meta.setDisplayName(u"§cЗакрыть")
    close.setItemMeta(meta)
    inv.setItem(26, close)

    player.openInventory(inv)
    open_guis[uid(player)] = dummy.getUniqueId().toString()
    gui_screens[uid(player)] = "main"


def open_zbt_pick_player_gui(admin, dummy, mode="auto"):
    """Меню выбора игрока (сетка голов онлайн-игроков)."""
    title_suffix = u" §8(guided)" if mode == "guided" else u" §8(auto)"
    inv = Bukkit.createInventory(None, 54, u"§b§lЗБТ § — выбери игрока" + title_suffix)
    players = list(Bukkit.getOnlinePlayers())
    # Ставим админа последним, чтобы не мешал (но не убираем).
    players.sort(key=lambda p: p.getName().lower())

    slot = 0
    for p in players:
        if slot >= 45: break
        try:
            head = ItemStack(Material.PLAYER_HEAD, 1)
            sm = head.getItemMeta()
            try:
                sm.setOwningPlayer(p)
            except Exception:
                pass
            # Пытаемся определить героя.
            hero_id, tier = _detect_hero_of_player(p)
            hero_disp = HERO_SPECS[hero_id]["display"] if hero_id else u"§7не определён"
            sm.setDisplayName(u"§e" + p.getName())
            lore = [
                u"§7Персонаж: §d" + hero_disp,
                u"§7Тир: §f" + (str(tier) if tier is not None else u"-"),
                u"",
            ]
            if hero_id:
                lore.append(u"§aЛКМ §7— запустить ЗБТ с этим персонажем")
            else:
                lore.append(u"§eЛКМ §7— выбрать персонажа вручную")
            sm.setLore(_java_list(lore))
            try:
                sm.getPersistentDataContainer().set(KEY_GUI_PLAYER,
                    PersistentDataType.STRING, uid(p))
            except Exception:
                pass
            head.setItemMeta(sm)
            inv.setItem(slot, head)
        except Exception:
            pass
        slot += 1

    # Слот 49: назад.
    back = ItemStack(Material.ARROW, 1)
    bm = back.getItemMeta()
    bm.setDisplayName(u"§7← Назад")
    try:
        bm.getPersistentDataContainer().set(KEY_GUI_ACTION, PersistentDataType.STRING, u"back_main")
    except Exception:
        pass
    back.setItemMeta(bm)
    inv.setItem(49, back)

    admin.openInventory(inv)
    open_guis[uid(admin)] = dummy.getUniqueId().toString()
    gui_screens[uid(admin)] = "zbt_pick_player"
    # Запоминаем режим для последующих кликов.
    gui_zbt_mode[uid(admin)] = mode


def open_zbt_pick_hero_gui(admin, dummy, target_uuid, target_name, mode="auto"):
    """Ручной выбор персонажа (когда автоопределение не сработало)."""
    inv = Bukkit.createInventory(None, 27, u"§b§lЗБТ § — выбери персонажа")

    # Иконки-заглушки под каждого героя.
    hero_icons = {
        "kris":       Material.NETHERITE_SWORD,
        "doom":       Material.NETHERITE_HELMET,
        "demiurg":    Material.BLAZE_ROD,
        "spider":     Material.COBWEB,
        "archer":     Material.BOW,
        "architect":  Material.TRIPWIRE_HOOK,
        "mihawk":     Material.NETHERITE_AXE,
        "griblet":    Material.LILY_PAD,
        "barsik":     Material.PRISMARINE_SHARD,
        "shanks":     Material.IRON_SWORD,
        "geto":       Material.SPAWNER,
        "poseidon":   Material.TRIDENT,
        "warden":     Material.SCULK_SHRIEKER,
        "dragon":     Material.DRAGON_HEAD,
        "amonra":     Material.BLAZE_POWDER,
        "shaman":     Material.SKELETON_SKULL,
        "steelgorn":  Material.NETHERITE_AXE,
        "wendy":      Material.WIND_CHARGE,
    }
    slot = 0
    for hero_id, spec in HERO_SPECS.items():
        if slot >= 24: break
        icon = ItemStack(hero_icons.get(hero_id, Material.PAPER), 1)
        m = icon.getItemMeta()
        m.setDisplayName(u"§d" + spec["display"])
        m.setLore(_java_list([
            u"§7Способностей: §f" + str(len(spec["abilities"])),
            u"",
            u"§eЛКМ §7— выбрать этого персонажа",
        ]))
        try:
            m.getPersistentDataContainer().set(KEY_GUI_HERO, PersistentDataType.STRING, hero_id)
            m.getPersistentDataContainer().set(KEY_GUI_PLAYER, PersistentDataType.STRING, target_uuid)
        except Exception:
            pass
        icon.setItemMeta(m)
        inv.setItem(slot, icon)
        slot += 1

    # Назад.
    back = ItemStack(Material.ARROW, 1)
    bm = back.getItemMeta()
    bm.setDisplayName(u"§7← Назад к выбору игрока")
    try:
        bm.getPersistentDataContainer().set(KEY_GUI_ACTION, PersistentDataType.STRING, u"back_zbt_pick")
    except Exception:
        pass
    back.setItemMeta(bm)
    inv.setItem(26, back)

    admin.openInventory(inv)
    open_guis[uid(admin)] = dummy.getUniqueId().toString()
    gui_screens[uid(admin)] = "zbt_pick_hero"


def _java_list(it):
    lst = ArrayList()
    for x in it: lst.add(x)
    return lst


# =============================================================================
#  EVENT HANDLERS
# =============================================================================

def on_interact_entity(event):
    """ПКМ по манекену → GUI."""
    if event.getHand() != EquipmentSlot.HAND: return
    ent = event.getRightClicked()
    if not is_dummy(ent): return
    p = event.getPlayer()
    if not _is_admin(p):
        p.sendMessage(u"§cНастройка манекена доступна только администратору.")
        event.setCancelled(True)
        return
    event.setCancelled(True)
    open_dummy_gui(p, ent)


def on_inv_click(event):
    who = event.getWhoClicked()
    if not isinstance(who, Player): return
    u = uid(who)
    if u not in open_guis: return
    view_title = event.getView().getTitle() if hasattr(event.getView(), "getTitle") else u""
    if u"Тренировочный Манекен" not in view_title and u"ЗБТ" not in view_title:
        return

    event.setCancelled(True)
    clicked = event.getCurrentItem()
    if clicked is None or clicked.getType() == Material.AIR:
        return

    screen = gui_screens.get(u, "main")
    dummy = find_dummy_by_uuid(open_guis[u])
    if dummy is None:
        who.sendMessage(u"§cМанекен потерян.")
        who.closeInventory()
        return

    m = clicked.getItemMeta()
    pdc = m.getPersistentDataContainer() if m is not None else None
    action = None
    if pdc is not None and pdc.has(KEY_GUI_ACTION, PersistentDataType.STRING):
        action = pdc.get(KEY_GUI_ACTION, PersistentDataType.STRING)

    # ---- Универсальные действия навигации ----
    if action == u"back_main":
        open_dummy_gui(who, dummy); return
    if action == u"back_zbt_pick":
        mode = gui_zbt_mode.get(u, "auto")
        open_zbt_pick_player_gui(who, dummy, mode); return
    if action == u"zbt_pick_auto":
        open_zbt_pick_player_gui(who, dummy, "auto"); return
    if action == u"zbt_pick_guided":
        open_zbt_pick_player_gui(who, dummy, "guided"); return
    if action == u"zbt_stop":
        session = _get_zbt_session_for_dummy(dummy)
        if event.isRightClick() and session and session.get("mode") == "guided":
            # ПКМ = пропустить текущий шаг.
            _guided_skip_current(session, dummy)
            open_dummy_gui(who, dummy)
            return
        if event.isShiftClick():
            _stop_zbt(who, dummy, save=False)
        else:
            _stop_zbt(who, dummy, save=True)
        open_dummy_gui(who, dummy); return

    # ---- Экран выбора игрока ----
    if screen == "zbt_pick_player":
        if pdc is not None and pdc.has(KEY_GUI_PLAYER, PersistentDataType.STRING):
            target_uuid = pdc.get(KEY_GUI_PLAYER, PersistentDataType.STRING)
            try:
                p = Bukkit.getPlayer(JUUID.fromString(target_uuid))
            except Exception:
                p = None
            if p is None or not p.isOnline():
                who.sendMessage(u"§cИгрок не онлайн.")
                return
            mode = gui_zbt_mode.get(u, "auto")
            hero_id, tier = _detect_hero_of_player(p)
            if hero_id is None:
                open_zbt_pick_hero_gui(who, dummy, target_uuid, p.getName(), mode=mode)
            else:
                if _start_zbt(who, dummy, p, mode=mode):
                    open_dummy_gui(who, dummy)
        return

    # ---- Экран ручного выбора персонажа ----
    if screen == "zbt_pick_hero":
        if pdc is not None and pdc.has(KEY_GUI_HERO, PersistentDataType.STRING) \
                and pdc.has(KEY_GUI_PLAYER, PersistentDataType.STRING):
            hero_id = pdc.get(KEY_GUI_HERO, PersistentDataType.STRING)
            target_uuid = pdc.get(KEY_GUI_PLAYER, PersistentDataType.STRING)
            try:
                p = Bukkit.getPlayer(JUUID.fromString(target_uuid))
            except Exception:
                p = None
            if p is None or not p.isOnline():
                who.sendMessage(u"§cИгрок не онлайн.")
                return
            mode = gui_zbt_mode.get(u, "auto")
            if _start_zbt(who, dummy, p, hero_override=hero_id, mode=mode):
                open_dummy_gui(who, dummy)
        return

    # ---- Главное меню ----
    if clicked.getType() == Material.RED_STAINED_GLASS_PANE:
        who.closeInventory()
        return
    if clicked.getType() == Material.TNT:
        _reset_stats_for_dummy(open_guis[u])
        who.sendMessage(u"§a✓ Статистика урона сброшена.")
        open_dummy_gui(who, dummy)
        return

    if pdc is not None:
        armor_key = KEY_GUI_ARMOR
        if pdc.has(armor_key, PersistentDataType.STRING):
            mid = pdc.get(armor_key, PersistentDataType.STRING)
            _apply_armor_choice(who, mid)
            return
        flag_key = KEY_GUI_FLAG
        if pdc.has(flag_key, PersistentDataType.STRING):
            key_str = pdc.get(flag_key, PersistentDataType.STRING)
            _toggle_flag(who, key_str)
            return


def _apply_armor_choice(player, mode_id):
    u = uid(player)
    dummy_uuid = open_guis.get(u)
    if dummy_uuid is None: return
    dummy = find_dummy_by_uuid(dummy_uuid)
    if dummy is None:
        player.sendMessage(u"§cМанекен не найден.")
        return
    _set_armor_mode(dummy, mode_id)
    player.sendMessage(u"§a✓ Броня: §f" + mode_id)
    open_dummy_gui(player, dummy)


def _toggle_flag(player, key_str):
    u = uid(player)
    dummy_uuid = open_guis.get(u)
    if dummy_uuid is None: return
    dummy = find_dummy_by_uuid(dummy_uuid)
    if dummy is None: return
    # Восстанавливаем ключ.
    key = NamespacedKey.fromString(key_str)
    cur = _get_flag(dummy, key)
    _set_flag(dummy, key, not cur)
    open_dummy_gui(player, dummy)


def _reset_stats_for_dummy(dummy_uuid):
    keys_to_remove = [k for k in damage_stats.keys() if k[1] == dummy_uuid]
    for k in keys_to_remove:
        del damage_stats[k]


def on_inv_close(event):
    who = event.getPlayer()
    if isinstance(who, Player):
        open_guis.pop(uid(who), None)
        gui_screens.pop(uid(who), None)


# =============================================================================
#  DAMAGE HANDLING
# =============================================================================

def on_damage(event):
    """Ловим ЛЮБОЙ урон по манекену — до отработки брони и эффектов."""
    ent = event.getEntity()
    if not is_dummy(ent): return

    if _get_flag(ent, KEY_FLAG_IGN):
        # Игнорировать броню — обнуляем reduction от armor.
        # Это влияет на getFinalDamage, но проще ставим final = raw.
        try:
            event.setDamage(EntityDamageEvent.DamageModifier.ARMOR, 0)
            event.setDamage(EntityDamageEvent.DamageModifier.MAGIC, 0)
            event.setDamage(EntityDamageEvent.DamageModifier.RESISTANCE, 0)
            event.setDamage(EntityDamageEvent.DamageModifier.ABSORPTION, 0)
        except Exception:
            pass


def on_damage_by(event):
    ent = event.getEntity()
    if not is_dummy(ent): return
    dmg = event.getDamager()
    attacker = None
    if isinstance(dmg, Player):
        attacker = dmg
    elif hasattr(dmg, "getShooter"):
        try:
            s = dmg.getShooter()
            if isinstance(s, Player):
                attacker = s
        except Exception:
            pass
    if attacker is None:
        return

    # Бессмертие — восстанавливаем HP после урона.
    immortal = _get_flag(ent, KEY_FLAG_IMM)
    autoheal = _get_flag(ent, KEY_FLAG_HEAL)

    # Считаем финальный урон (после брони).
    raw_damage = event.getDamage()
    final_damage = event.getFinalDamage()

    # Определяем "чистый ли урон": грубая эвристика — если у события отсутствует
    # armor reduction (final==raw), либо cause=MAGIC/CUSTOM.
    C = EntityDamageEvent.DamageCause
    cause = event.getCause()
    is_pure = cause in (C.MAGIC, C.CUSTOM)

    # Записываем статистику.
    key = (uid(attacker), uid(ent))
    if key not in damage_stats:
        damage_stats[key] = {
            "physical_total": 0.0,
            "pure_total":     0.0,
            "physical_hits":  [],   # (tick, damage) — для DPS
            "pure_hits":      [],
            "last_physical":  0.0,
            "last_pure":      0.0,
            "started_tick":   now_tick(),
        }
    st = damage_stats[key]

    if is_pure:
        st["pure_total"] += final_damage
        st["pure_hits"].append((now_tick(), final_damage))
        st["last_pure"] = final_damage
    else:
        st["physical_total"] += final_damage
        st["physical_hits"].append((now_tick(), final_damage))
        st["last_physical"] = final_damage

    # Обрезаем hit-лог старше 10 сек.
    cutoff = now_tick() - 200
    st["physical_hits"] = [(t, d) for (t, d) in st["physical_hits"] if t >= cutoff]
    st["pure_hits"]     = [(t, d) for (t, d) in st["pure_hits"]     if t >= cutoff]

    # DPS считаем отдельно.
    dps_window = 10.0
    dps_phys = sum(d for _, d in st["physical_hits"]) / dps_window
    dps_pure = sum(d for _, d in st["pure_hits"])     / dps_window

    # В сердцах.
    h_last_p = st["last_physical"] / 2.0
    h_last_c = st["last_pure"]     / 2.0
    h_tot_p  = st["physical_total"] / 2.0
    h_tot_c  = st["pure_total"]     / 2.0
    dps_h_p  = dps_phys / 2.0
    dps_h_c  = dps_pure / 2.0
    diff     = (raw_damage - final_damage) / 2.0   # что съела броня

    # ActionBar — две отдельные метрики.
    line = (u"§c⚔ Физ: §f%.1f §8(всего §f%.1f§8, DPS §f%.1f§8)  " +
            u"§d✦ Чистый: §f%.1f §8(всего §f%.1f§8, DPS §f%.1f§8)  " +
            u"§7🛡 Съела броня: §f%.1f") % (
        h_last_p, h_tot_p, dps_h_p,
        h_last_c, h_tot_c, dps_h_c,
        diff
    )
    attacker.sendActionBar(line)

    # Всплывающий текст над мобом.
    if is_pure:
        hologram_text = u"§d✦-%.1f❤" % (final_damage / 2.0)
    else:
        hologram_text = u"§c-%.1f❤" % (final_damage / 2.0)
    _spawn_hologram(ent.getLocation().add(0, ent.getHeight() + 0.5, 0), hologram_text)

    # Лог урона.
    if _get_flag(ent, KEY_FLAG_LOG):
        kind = u"чистый" if is_pure else u"физ"
        attacker.sendMessage(u"§8[Лог] §f%.2f §7HP (§f%s§7, raw=%.2f, cause=%s)" %
                             (final_damage, kind, raw_damage, cause.name()))

    # ==== ЗБТ-хук: если на манекене активен ЗБТ-режим и бьёт целевой игрок ====
    session = _get_zbt_session_for_dummy(ent)
    if session is not None and uid(attacker) == session["target_uuid"]:
        try:
            # Определяем предмет в руке.
            item_in_hand = None
            try:
                item_in_hand = attacker.getInventory().getItemInMainHand()
            except Exception:
                pass

            # === ВЫБОР ClaSSIFY: guided vs auto ===
            mode = session.get("mode", "auto")
            forced_step = None
            if mode == "guided":
                idx = session.get("step_idx", 0)
                pb = session.get("playbook", [])
                if 0 <= idx < len(pb):
                    forced_step = pb[idx]

            if forced_step is not None:
                # Жёстко приписываем удар к текущему шагу.
                ab_id   = forced_step["ability_id"]
                ab_name = forced_step["ability_name"]
                extra   = u"guided step %d" % (session["step_idx"] + 1)
            else:
                ab_id, ab_name, extra = _classify_ability(session, event, is_pure, attacker, item_in_hand)

            # Пытаемся вытащить тир предмета для лога.
            cur_tier = None
            spec_h = HERO_SPECS.get(session["hero"], {})
            tier_key_str = spec_h.get("tier_pdc_key")
            if item_in_hand is not None and tier_key_str:
                try:
                    m = item_in_hand.getItemMeta()
                    if m is not None:
                        pdc = m.getPersistentDataContainer()
                        tkey = NamespacedKey.fromString(tier_key_str)
                        if pdc.has(tkey, PersistentDataType.INTEGER):
                            cur_tier = pdc.get(tkey, PersistentDataType.INTEGER)
                except Exception:
                    pass
            # В guided-режиме тир диктуется шагом.
            if forced_step is not None and forced_step.get("tier") is not None:
                cur_tier = forced_step["tier"]

            # Attack cooldown — сохранён PrePlayerAttackEntityEvent'ом.
            cd = last_attack_cooldown.get(uid(attacker), None)
            cd_str = ("%.2f" % cd) if cd is not None else "n/a"
            # Крит: пытаемся получить isCritical() (Paper).
            was_crit = False
            try:
                if hasattr(event, "isCritical"):
                    was_crit = bool(event.isCritical())
            except Exception:
                was_crit = False
            cur_armor_mode = _get_armor_mode(ent)

            # === Валидация в guided-режиме ===
            reject_reason = None
            if forced_step is not None:
                # Utility-шаги не проверяются по крит/cd — они не про удар.
                if not forced_step.get("expect_utility"):
                    mc = forced_step.get("must_crit")
                    if mc is True and not was_crit and not is_pure:
                        reject_reason = u"нужен КРИТ (прыгать при ударе)"
                    elif mc is False and was_crit:
                        reject_reason = u"был КРИТ, а нужно БЕЗ крита"
                    if reject_reason is None and forced_step.get("cd_required") and not is_pure:
                        if cd is not None and cd < 0.9:
                            reject_reason = u"cd=%.2f — жди полной перезарядки" % cd

            extra_full = (extra or u"") + u" cd=" + cd_str + u" armor=" + cur_armor_mode \
                       + (u" CRIT" if was_crit else u"") \
                       + (u" REJECT:" + reject_reason if reject_reason else u"")

            hit = _record_hit(session, ab_id, ab_name, ("pure" if is_pure else "physical"),
                              raw_damage, final_damage, cur_tier, extra_full,
                              armor_mode=cur_armor_mode,
                              expect_utility=bool(forced_step and forced_step.get("expect_utility")))

            # В guided — счётчик прогресса и авто-переход.
            step_progress_msg = None
            if forced_step is not None:
                if reject_reason is not None:
                    session["step_rejected"] = session.get("step_rejected", 0) + 1
                    step_progress_msg = (u"§c✗ ОТКЛОНЕНО: §f" + reject_reason
                                         + u" §8(§f%d§8/§f%d§8)" % (
                                            session.get("step_hits", 0),
                                            forced_step["hits_needed"]))
                else:
                    session["step_hits"] = session.get("step_hits", 0) + 1
                    n = session["step_hits"]; k = forced_step["hits_needed"]
                    step_progress_msg = u"§a✓ §f%d§7/§f%d" % (n, k)
                    if n >= k:
                        step_progress_msg = u"§a§l✓ ШАГ ПРОЙДЕН §f%d§7/§f%d" % (n, k)
                        # Переходим к следующему шагу в конце тика.
                        def _advance():
                            if _get_zbt_session_for_dummy(ent) is session:
                                _guided_next_step(session, ent)
                        scheduler.runTaskLater(_advance, 15)

            # Сообщение в чат админам.
            verdict_col = {"OK": u"§a", "LOW": u"§e", "HIGH": u"§c", "?": u"§7"}.get(hit["verdict"], u"§7")
            exp_str = u""
            if hit["expected"]:
                exp_str = u" §8(ожид. §f%.1f..%.1f§8)" % (hit["expected"][0], hit["expected"][1])
            tier_str = u"" if cur_tier is None else (u" §8T§f" + str(cur_tier))
            cd_col = u"§a" if (cd is not None and cd >= 0.9) else (u"§c" if cd is not None else u"§7")
            cd_disp = (u" " + cd_col + u"cd=" + cd_str) if cd is not None else u""
            crit_disp = u" §6§lCRIT" if was_crit else u""
            reject_disp = (u" §c§l[REJECTED: " + reject_reason + u"]") if reject_reason else u""
            adm_msg = (u"§8[ЗБТ] §f" + session["target_name"] + tier_str + u" §7→ §b" + ab_name
                       + u" §7: §f%.2f §7HP " % final_damage
                       + (u"§8(чистый) " if is_pure else u"§8(физ) ")
                       + exp_str + cd_disp + crit_disp + reject_disp
                       + u" " + verdict_col + u"[" + hit["verdict"] + u"]")
            for p in Bukkit.getOnlinePlayers():
                if _is_admin(p):
                    p.sendMessage(adm_msg)

            # ActionBar тестеру.
            if forced_step is not None and step_progress_msg is not None:
                attacker.sendActionBar(u"§8§l[ЗБТ] §r" + step_progress_msg
                                        + u" §8│ §f%.2f §7HP" % final_damage
                                        + crit_disp)
            elif not is_pure and cd is not None:
                if cd < 0.9:
                    ab_line = (u"§c§lСПАМ-КЛИК §r§7cd=§c%.2f §8│ §b" % cd + ab_name
                               + u" §f%.2f §7HP " % final_damage
                               + verdict_col + u"[" + hit["verdict"] + u"]")
                else:
                    ab_line = (u"§a§l✓ ЗАРЯД §r§7cd=§a%.2f §8│ §b" % cd + ab_name
                               + u" §f%.2f §7HP " % final_damage
                               + verdict_col + u"[" + hit["verdict"] + u"]")
                attacker.sendActionBar(ab_line)
            else:
                attacker.sendActionBar(u"§8§lЗБТ §7» §b" + ab_name + u" §f%.2f §7HP " % final_damage
                                        + verdict_col + u"[" + hit["verdict"] + u"]")

            # Голограмма.
            holo = u"§8ЗБТ §b" + ab_name + u"§7: §f%.1f❤" % (final_damage / 2.0)
            if was_crit: holo += u" §6§lCRIT"
            if reject_reason: holo = u"§c✗ " + reject_reason
            try:
                _spawn_hologram(ent.getLocation().add(0, ent.getHeight() + 1.2, 0), holo)
            except Exception:
                pass
        except Exception as ex:
            Bukkit.getLogger().warning("[dummy][zbt] hit-hook: " + str(ex))
    # ==== /ЗБТ ====

    # Бессмертие: если HP упадёт до <= 0 — отменяем.
    if immortal:
        try:
            after = ent.getHealth() - final_damage
            if after <= 1.0:
                event.setCancelled(True)
                # Полное восстановление.
                try:
                    from org.bukkit.attribute import Attribute
                    max_hp = ent.getAttribute(Attribute.GENERIC_MAX_HEALTH).getValue()
                    ent.setHealth(max_hp)
                except Exception:
                    ent.setHealth(2000.0)
        except Exception:
            pass

    # Автоотхил через 1 секунду.
    if autoheal and not immortal:
        def heal():
            try:
                if ent.isValid() and not ent.isDead():
                    from org.bukkit.attribute import Attribute
                    max_hp = ent.getAttribute(Attribute.GENERIC_MAX_HEALTH).getValue()
                    ent.setHealth(max_hp)
            except Exception:
                pass
        scheduler.runTaskLater(heal, 20)


def _spawn_hologram(loc, text):
    """Спавнит короткий TextDisplay над манекеном, автоуничтожается через 20 тиков."""
    world = loc.getWorld()
    try:
        from org.bukkit.entity import EntityType
        display = world.spawnEntity(loc, EntityType.TEXT_DISPLAY)
        try:
            from net.kyori.adventure.text import Component
            display.text(Component.text(text))
        except Exception:
            try:
                display.setText(text)
            except Exception:
                pass
        try:
            display.setBillboard(display.getBillboard().CENTER)
        except Exception:
            pass
        # Небольшой подъём вверх с течением времени.
        state = {"t": 0, "y": loc.getY()}
        def rise():
            if state["t"] >= 20 or not display.isValid():
                try: display.remove()
                except Exception: pass
                return
            try:
                l = display.getLocation()
                l.setY(state["y"] + state["t"] * 0.05)
                display.teleport(l)
            except Exception: pass
            state["t"] += 2
            scheduler.runTaskLater(rise, 2)
        scheduler.runTaskLater(rise, 2)
    except Exception as ex:
        # Fallback: обычный ArmorStand с CustomName.
        try:
            from org.bukkit.entity import EntityType
            as_ent = world.spawnEntity(loc, EntityType.ARMOR_STAND)
            as_ent.setVisible(False)
            as_ent.setGravity(False)
            as_ent.setMarker(True)
            as_ent.setCustomName(text)
            as_ent.setCustomNameVisible(True)
            def cleanup():
                try:
                    if as_ent.isValid(): as_ent.remove()
                except Exception: pass
            scheduler.runTaskLater(cleanup, 20)
        except Exception:
            pass


# =============================================================================
#  COMMAND
# =============================================================================

def cmd_dummy(sender, label, args):
    if not _is_admin(sender):
        sender.sendMessage(u"§cНет доступа.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/dummy spawn §7— заспавнить манекен")
        sender.sendMessage(u"  §f/dummy remove §7— удалить манекен по взгляду")
        sender.sendMessage(u"  §f/dummy remove all §7— удалить все")
        sender.sendMessage(u"  §f/dummy zbt <ник> [hero] §7— ЗБТ (auto) на манекене под взглядом")
        sender.sendMessage(u"  §f/dummy zbtguided <ник> [hero] §7— ЗБТ направляемый (плейбук)")
        sender.sendMessage(u"  §f/dummy zbtskip §7— пропустить текущий шаг в guided")
        sender.sendMessage(u"  §f/dummy zbtstop §7— остановить ЗБТ и сохранить отчёт")
        sender.sendMessage(u"  §f/dummy zbtstatus §7— показать статус ЗБТ")
        return True

    if not isinstance(sender, Player):
        sender.sendMessage(u"§cКоманда только для игроков.")
        return True

    sub = args[0].lower()
    if sub == u"spawn":
        loc = sender.getLocation().clone()
        # Перед игроком, на 2 блока.
        dir_v = loc.getDirection()
        dir_v.setY(0)
        if dir_v.lengthSquared() > 0.01:
            dir_v = dir_v.normalize().multiply(2.0)
            loc.add(dir_v)
        loc.setYaw(loc.getYaw() + 180.0)   # разворачиваем лицом к нам
        dummy = spawn_dummy(loc)
        sender.sendMessage(u"§a✓ Манекен создан. §7ПКМ по нему — настроить.")
        return True

    if sub == u"remove":
        if len(args) >= 2 and args[1].lower() == u"all":
            n = 0
            for world in Bukkit.getWorlds():
                for ent in world.getLivingEntities():
                    if is_dummy(ent):
                        try:
                            ent.remove()
                            n += 1
                        except Exception:
                            pass
            sender.sendMessage(u"§a✓ Удалено манекенов: §f" + str(n))
            return True

        # По взгляду.
        result = sender.rayTraceEntities(20)
        if result is not None and result.getHitEntity() is not None:
            e = result.getHitEntity()
            if is_dummy(e):
                try:
                    e.remove()
                    sender.sendMessage(u"§a✓ Манекен удалён.")
                except Exception as ex:
                    sender.sendMessage(u"§cОшибка: §f" + str(ex))
                return True
        sender.sendMessage(u"§cНавидись на манекен.")
        return True

    if sub == u"zbt" or sub == u"zbtguided":
        mode = "guided" if sub == u"zbtguided" else "auto"
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/dummy " + sub + u" <ник> [hero]")
            return True
        target_name = args[1]
        target = Bukkit.getPlayerExact(target_name)
        if target is None or not target.isOnline():
            sender.sendMessage(u"§cИгрок §f" + target_name + u" §cне онлайн.")
            return True
        dummy = None
        result = sender.rayTraceEntities(30)
        if result is not None and result.getHitEntity() is not None and is_dummy(result.getHitEntity()):
            dummy = result.getHitEntity()
        if dummy is None:
            sender.sendMessage(u"§cНавидись на манекен, на котором хочешь включить ЗБТ.")
            return True
        hero_override = args[2].lower() if len(args) >= 3 else None
        if hero_override is not None and hero_override not in HERO_SPECS:
            sender.sendMessage(u"§cНеизвестный hero id. Доступные: §f"
                               + ", ".join(sorted(HERO_SPECS.keys())))
            return True
        _start_zbt(sender, dummy, target, hero_override=hero_override, mode=mode)
        return True

    if sub == u"zbtskip":
        # Пропустить текущий шаг в guided-сессии на манекене под взглядом.
        dummy = None
        result = sender.rayTraceEntities(30)
        if result is not None and result.getHitEntity() is not None and is_dummy(result.getHitEntity()):
            dummy = result.getHitEntity()
        if dummy is None:
            # Если только одна активная guided-сессия — пропускаем в ней.
            guided = [s for s in zbt_sessions.values() if s.get("mode") == "guided"]
            if len(guided) == 1:
                d = find_dummy_by_uuid(guided[0]["dummy_uuid"])
                if d is not None:
                    _guided_skip_current(guided[0], d)
                    return True
            sender.sendMessage(u"§cНавидись на манекен с guided-сессией.")
            return True
        session = _get_zbt_session_for_dummy(dummy)
        if session is None or session.get("mode") != "guided":
            sender.sendMessage(u"§cНа этом манекене нет guided-сессии.")
            return True
        _guided_skip_current(session, dummy)
        return True

    if sub == u"zbtstop":
        # Найдём любой манекен под взглядом или все активные.
        dummy = None
        result = sender.rayTraceEntities(30)
        if result is not None and result.getHitEntity() is not None and is_dummy(result.getHitEntity()):
            dummy = result.getHitEntity()
        if dummy is None:
            # Останавливаем все ЗБТ-сессии.
            if not zbt_sessions:
                sender.sendMessage(u"§7Нет активных ЗБТ-сессий.")
                return True
            for did in list(zbt_sessions.keys()):
                d = find_dummy_by_uuid(did)
                if d is not None:
                    _stop_zbt(sender, d, save=True)
            return True
        _stop_zbt(sender, dummy, save=True)
        return True

    if sub == u"zbtstatus":
        if not zbt_sessions:
            sender.sendMessage(u"§7Активных ЗБТ-сессий нет.")
            return True
        sender.sendMessage(u"§b§lАктивные ЗБТ-сессии:")
        for did, s in zbt_sessions.items():
            mode = s.get("mode", "auto")
            line = (u"  §7- манекен §f" + did[:8] + u"§7… игрок §f" + s["target_name"]
                    + u" §7персонаж §d" + HERO_SPECS[s["hero"]]["display"]
                    + u" §8[" + mode + u"] §7удары §f" + str(len(s["hits"]))
                    + u" §7способ. §f" + str(len(s["checked"])))
            if mode == "guided":
                idx = s.get("step_idx", 0); pb = s.get("playbook", [])
                if 0 <= idx < len(pb):
                    st = pb[idx]
                    line += u" §7шаг §f%d§7/§f%d§7: §b" % (idx + 1, len(pb)) + st["ability_name"]
                    line += u" §7(§f%d§7/§f%d§7)" % (s.get("step_hits", 0), st["hits_needed"])
            sender.sendMessage(line)
        return True

    sender.sendMessage(u"§cНеизвестная подкоманда: §f" + sub)
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_dummy, "dummy")

listener_mgr.registerListener(on_interact_entity, PlayerInteractEntityEvent)
listener_mgr.registerListener(on_inv_click,       InventoryClickEvent)
listener_mgr.registerListener(on_inv_close,       InventoryCloseEvent)
listener_mgr.registerListener(on_damage,          EntityDamageEvent)
listener_mgr.registerListener(on_damage_by,       EntityDamageByEntityEvent)


def on_projectile_hit(event):
    """Для guided utility-шагов: если снаряд игрока попал в наш ЗБТ-манекен,
    засчитываем как выполнение шага, даже если способность не вызывает damage()
    (Web Ball, Shock, Grenade, Web Shot и т.д. — CC-снаряды без прямого урона)."""
    try:
        proj = event.getEntity()
        hit_ent = event.getHitEntity()
        if hit_ent is None or not is_dummy(hit_ent):
            return
        session = _get_zbt_session_for_dummy(hit_ent)
        if session is None or session.get("mode") != "guided":
            return
        # Определяем стрелка.
        shooter = None
        try:
            s = proj.getShooter()
            if isinstance(s, Player):
                shooter = s
        except Exception:
            return
        if shooter is None or uid(shooter) != session["target_uuid"]:
            return
        # Только для текущего utility-шага, чтобы не задваивать с on_damage_by.
        idx = session.get("step_idx", 0)
        pb  = session.get("playbook", [])
        if not (0 <= idx < len(pb)):
            return
        step = pb[idx]
        if not step.get("expect_utility"):
            return
        # Засчитываем «удар» без damage.
        cur_armor_mode = _get_armor_mode(hit_ent)
        extra_full = (u"guided step %d" % (idx + 1)) + u" utility-projectile armor=" + cur_armor_mode
        hit = _record_hit(session, step["ability_id"], step["ability_name"],
                          "utility", 0.0, 0.0, step.get("tier"), extra_full,
                          armor_mode=cur_armor_mode, expect_utility=True)
        session["step_hits"] = session.get("step_hits", 0) + 1
        n = session["step_hits"]; k = step["hits_needed"]
        try:
            shooter.sendActionBar(u"§8§l[ЗБТ] §a✓ utility-попадание §f%d§7/§f%d §8│ §b" % (n, k) + step["ability_name"])
        except Exception:
            pass
        for pp in Bukkit.getOnlinePlayers():
            if _is_admin(pp):
                pp.sendMessage(u"§8[ЗБТ] §7utility-попадание §b" + step["ability_name"]
                               + u" §7(§f%d§7/§f%d§7)" % (n, k))
        if n >= k:
            def _advance():
                if _get_zbt_session_for_dummy(hit_ent) is session:
                    _guided_next_step(session, hit_ent)
            scheduler.runTaskLater(_advance, 15)
    except Exception as ex:
        Bukkit.getLogger().warning("[dummy][zbt] projectile-hook: " + str(ex))


listener_mgr.registerListener(on_projectile_hit,  ProjectileHitEvent)

# Paper-only: перехватываем cooldown ДО удара.
def on_pre_attack(event):
    try:
        p = event.getPlayer()
        cd = float(p.getAttackCooldown())
        last_attack_cooldown[uid(p)] = cd
    except Exception:
        pass

if _PrePlayerAttackEntityEvent is not None:
    try:
        listener_mgr.registerListener(on_pre_attack, _PrePlayerAttackEntityEvent)
        Bukkit.getLogger().info("[dummy] PrePlayerAttackEntityEvent hook registered.")
    except Exception as ex:
        Bukkit.getLogger().warning("[dummy] failed to register PrePlayerAttackEntityEvent: " + str(ex))
else:
    Bukkit.getLogger().info("[dummy] PrePlayerAttackEntityEvent not available; cooldown detection disabled.")

Bukkit.getLogger().info("[dummy] Training Dummy loaded. Command: /dummy")

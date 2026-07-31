# -*- coding: utf-8 -*-
"""
==============================================================================
  HITBOX HELPER — Утилита поиска цели луча со "щедрым" хитбоксом
  Paper 1.21.11 + PySpigot 0.9.1
------------------------------------------------------------------------------
  Проблема: в vanilla-Minecraft хитбокс игрока узкий (0.6×1.8×0.6). Точный
  rayTraceEntities часто промахивается, особенно в бою с движущимися целями.

  Решение — комбо raytrace + aim-assist:
    1. Точный raytrace вдоль луча (стандартный Player.rayTraceEntities).
    2. Если raytrace промазал — толстый бокс-поиск: увеличенный радиус
       вокруг каждой точки луча (шаг 1 блок).
    3. Дополнительный aim-assist: конус ~0.98 (примерно 11°) вокруг взгляда,
       выбирает ближайшую по расстоянию цель.

  Публикуется в System.getProperties() как:
     "hitbox.find_target_in_cone" — основная функция
     "hitbox.find_target_generous" — упрощённая

  Использование в скриптах героев:
     _find_target = System.getProperties().get("hitbox.find_target_in_cone")
     target = _find_target(player, max_dist=20.0, box_radius=1.0)
     if target is None:
         player.sendMessage(u"§7Нет цели.")
         return
==============================================================================
"""

import pyspigot as ps

from java.lang import System

from org.bukkit import Bukkit
from org.bukkit.entity import Player, LivingEntity


# ============================================================================
#  UTILS
# ============================================================================

def _norm_vec(v):
    """Возвращает нормализованный Vector или None если нулевой."""
    try:
        if v.lengthSquared() < 0.0001:
            return None
        return v.normalize()
    except Exception:
        return None


# ============================================================================
#  MAIN API
# ============================================================================

def find_target_in_cone(player, max_dist=20.0, box_radius=1.0,
                        cone_dot=0.98, exclude=None):
    """
    Ищет живую цель для лучевой способности игрока.

    Стратегия:
      1. Точный rayTraceEntities(max_dist).
      2. Толстый бокс-поиск вдоль луча (в кубе box_radius вокруг каждой
         точки шагом ~1 блок).
      3. Aim-assist в конусе взгляда (cone_dot: 0.98 = ~11°, 0.94 = ~20°).

    player     — Player, кто кастует.
    max_dist   — максимальная дистанция луча (блоки).
    box_radius — сколько блоков "толщина" вокруг луча (1.0 = довольно щедро).
    cone_dot   — минимальный dot-product взгляда и направления на цель.
                 Ближе к 1.0 = уже конус (точнее прицел).
    exclude    — set/list из UUID сущностей, которых пропускать (обычно сам
                 игрок автоматически исключается).

    Возвращает LivingEntity или None.
    """
    if not isinstance(player, Player):
        return None

    world = player.getWorld()
    origin = player.getEyeLocation()
    direction = origin.getDirection()
    dir_norm = _norm_vec(direction.clone())
    if dir_norm is None:
        return None

    exclude_set = set()
    exclude_set.add(player.getUniqueId().toString())
    if exclude is not None:
        for e in exclude:
            try:
                if isinstance(e, LivingEntity):
                    exclude_set.add(e.getUniqueId().toString())
                elif isinstance(e, (str, unicode)):
                    exclude_set.add(str(e))
            except Exception: pass

    def _is_valid(ent):
        if ent is None: return False
        if not isinstance(ent, LivingEntity): return False
        try:
            if ent.isDead() or not ent.isValid(): return False
        except Exception: return False
        try:
            if ent.getUniqueId().toString() in exclude_set:
                return False
        except Exception: pass
        return True

    # === Уровень 1: Точный raytrace ===
    try:
        result = player.rayTraceEntities(int(max_dist))
        if result is not None:
            hit = result.getHitEntity()
            if _is_valid(hit):
                return hit
    except Exception:
        pass

    # === Уровень 2: Толстый бокс-поиск вдоль луча ===
    # Идём шагом 1 блок от игрока к концу луча, на каждой точке ищем цель
    # в кубе (box_radius × box_radius × box_radius).
    best = None
    best_dist_sq = float(max_dist * max_dist * 4)   # начальный "worst"
    steps = int(max_dist)
    for i in range(1, steps + 1):
        point = origin.clone().add(dir_norm.clone().multiply(float(i)))
        try:
            near = world.getNearbyEntities(point, box_radius, box_radius, box_radius)
        except Exception:
            continue
        for e in near:
            if not _is_valid(e): continue
            try:
                d_sq = e.getLocation().distanceSquared(origin)
            except Exception:
                continue
            if d_sq < best_dist_sq:
                best_dist_sq = d_sq
                best = e
    if best is not None:
        return best

    # === Уровень 3: Aim-assist в конусе взгляда ===
    # Ищем всех LivingEntity в кубе max_dist вокруг игрока, фильтруем по
    # cone_dot (угловое отклонение от взгляда).
    try:
        candidates = world.getNearbyEntities(origin, max_dist, max_dist, max_dist)
    except Exception:
        candidates = []
    best_cone = None
    best_cone_dist_sq = float(max_dist * max_dist * 4)
    for e in candidates:
        if not _is_valid(e): continue
        try:
            to_e = e.getLocation().toVector().subtract(origin.toVector())
            d_sq = to_e.lengthSquared()
            if d_sq > max_dist * max_dist:
                continue
            to_e_n = _norm_vec(to_e)
            if to_e_n is None: continue
            dot = to_e_n.dot(dir_norm)
            if dot < cone_dot:
                continue
            if d_sq < best_cone_dist_sq:
                best_cone_dist_sq = d_sq
                best_cone = e
        except Exception:
            continue

    return best_cone


def find_target_generous(player, max_dist=20.0):
    """Упрощённая: щедрый бокс 1.0 + конус ~11°. Один вызов вместо тьюнинга."""
    return find_target_in_cone(player, max_dist=max_dist,
                                box_radius=1.0, cone_dot=0.98)


# ============================================================================
#  РЕГИСТРАЦИЯ
# ============================================================================

_props = System.getProperties()
_props.put("hitbox.find_target_in_cone", find_target_in_cone)
_props.put("hitbox.find_target_generous", find_target_generous)

Bukkit.getLogger().info("[hitbox_helper] Loaded. API: hitbox.find_target_in_cone(player, max_dist, box_radius, cone_dot)")

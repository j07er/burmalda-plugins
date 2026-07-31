# -*- coding: utf-8 -*-
"""
rp_actions.py - Ролевые команды-приколы для PySpigot 0.9.1 (Jython 2.7) + Paper 1.21.11

Команды:
  /pee   - Начать/закончить "писать". Направленная (по взгляду игрока) струя частиц
           с параболической траекторией и радиусом ~3.5 блока, останавливается о
           стены/пол/воду. Отменяется ТОЛЬКО повторным вводом /pee.
  /spit  - Плюнуть в направлении взгляда. Анимация летящего плевка (частицы Particle.SPIT),
           при попадании по живому существу наносится "фейк-урон" (реальный урон применяется
           и тут же полностью восстанавливается) - жертва получает ванильную красную вспышку
           экрана и звук удара, но не теряет HP по-настоящему.
  /sit   - [ОСНОВНАЯ, НЕ ТРОГАТЬ] Сесть прямо там, где стоите, через невидимый
           ArmorStand-Marker (нулевой хитбокс, никого не блокирует). Направление сидения
           фиксируется в момент посадки - если нужен вариант со свободным поворотом
           камеры, используйте /esit.
  /esit  - ЭКСПЕРИМЕНТАЛЬНАЯ версия /sit со свободным поворотом камеры без "поломки" вида
           на развороте. Отличие от /sit: угол сидушки (ArmorStand) синхронизируется с
           текущим взглядом игрока каждый тик, поэтому расхождение между углом сидушки и
           углом обзора никогда не накапливается - клиенту не приходится "довращать" через
           короткую/длинную сторону круга, из-за чего у ванильных seat-реализаций на большом
           повороте (в т.ч. ~180°) ломается картинка. Полностью независима от /sit: свой
           реестр сидушек, свой тикер, свой обработчик схода - можно вырезать блок
           "БЛОК /esit" целиком без влияния на /sit.
  /lay   - Лечь / ползти-плыть на месте БЕЗ ограничения движения. Реализовано через приём
           "фейковый потолок": игроку лично (sendBlockChange, блок не существует в мире по-
           настоящему) отправляется невидимый барьер на 1 блок над головой. Ванильный
           клиент сам решает, что видит потолок ниже 2 блоков, и переходит в настоящую
           клиентскую позу заплыва/ползка - с корректной камерой, хитбоксом и синхронизацией
           позы для других игроков (в отличие от Entity.setPose(), который не меняет
           отображение у самого игрока - см. PaperMC/Paper#7016 / PR #8781). Барьер следует
           за игроком при смене блока над головой, поэтому ползать можно бесконечно в любом
           направлении, WASD работает как обычно, другие игроки не ограничены никакими
           барьерами (они реальны только на экране лежащего).

Особенности реализации:
 - Сидение (и /sit, и /esit) и лёжа дополнительно снимаются при получении реального урона
   (защита от нелепых ситуаций в бою) и при выходе игрока с сервера.
 - /pee, /sit, /esit и /lay взаимоисключающие: включение одной позы автоматически снимает
   остальные.
 - Один listener на каждый тип события в скрипте (ограничение PySpigot 0.9.1).
"""

import math
import random

import pyspigot as ps
from java.lang import System
from java.util import UUID as JUUID

from org.bukkit import Bukkit, Material, Particle, Sound, GameMode
from org.bukkit.block import BlockFace
from org.bukkit.util import Vector
from org.bukkit.entity import Player, LivingEntity, ArmorStand
from org.bukkit.event.player import PlayerQuitEvent, PlayerMoveEvent
from org.bukkit.event.entity import EntityDamageEvent, EntityDismountEvent

# -------------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ МЕНЕДЖЕРОВ PYSPIGOT
# -------------------------------------------------------------------------
cmd_mgr = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler = ps.scheduler

# -------------------------------------------------------------------------
# ОБЩИЕ УТИЛИТЫ (единый стиль проекта)
# -------------------------------------------------------------------------
FREE_CD_PLAYERS = set([u"blueredtronce"])


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


# -------------------------------------------------------------------------
# КУЛДАУНЫ (защита от спама частицами/звуками при быстром повторе команды)
# -------------------------------------------------------------------------
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
            player.sendMessage(u"§7" + label + u" §7ещё восстанавливается: §c%.1f §7сек." % rem)
        return False
    return True


def set_cd(player, name, ticks):
    if player.getName().lower() in FREE_CD_PLAYERS:
        return
    u = uid(player)
    if u not in cooldowns:
        cooldowns[u] = {}
    cooldowns[u][name] = now_tick() + ticks


# -------------------------------------------------------------------------
# ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# -------------------------------------------------------------------------
peeing_players = set()     # set(uid) - кто сейчас "писяет"
laying_players = set()     # set(uid) - кто сейчас лежит/ползёт
lay_barrier_loc = {}       # uid -> Location текущего фейкового барьера над головой
seat_stands = {}           # uid -> ArmorStand (посадочное место /sit)
esit_stands = {}           # uid -> ArmorStand (посадочное место /esit, независимо от /sit)


def _clear_other_states(player, keep):
    """Снимает все позы кроме той, что сейчас активируется
    (keep: 'pee' / 'sit' / 'esit' / 'lay')."""
    if keep != "pee":
        _stop_pee(player, silent=True)
    if keep != "sit":
        _stop_sit(player, silent=True)
    if keep != "esit":
        _stop_esit(player, silent=True)
    if keep != "lay":
        _stop_lay(player, silent=True)


# =========================================================================
# /pee - НАПРАВЛЕННАЯ СТРУЯ С ФИЗИКОЙ (ПАРАБОЛА, РАДИУС ~3.5 БЛОКА)
# =========================================================================
PEE_RADIUS = 3.5             # максимальная дальность струи в блоках (было 2.0, +1.5)
PEE_GRAVITY = 1.05           # коэффициент "тяжести" параболы (снижен - струя летит дальше и более настильно)
PEE_STREAM_SPEED = 3.1       # условная скорость струи вдоль дуги
PEE_STEPS = 34               # число расчётных точек дуги (с запасом на увеличенную дальность)
PEE_TICK_INTERVAL = 2        # анимация обновляется раз в 2 тика (~0.1 сек)
PEE_JITTER = 0.045           # небольшой боковой дребезг струи для живости эффекта


def _draw_pee_stream(player):
    loc = player.getLocation()
    world = player.getWorld()
    from org.bukkit import Color

    direction = loc.getDirection().clone()
    direction.setY(0.0)
    if direction.lengthSquared() < 1e-6:
        direction = Vector(0.0, 0.0, 1.0)
    direction.normalize()

    # Перпендикуляр к направлению взгляда (для бокового дребезга струи)
    side = Vector(-direction.getZ(), 0.0, direction.getX())

    pitch_rad = math.radians(loc.getPitch())
    vertical_aim = -math.sin(pitch_rad)   # управление углом струи взглядом вверх/вниз

    origin = loc.clone().add(direction.clone().multiply(0.35))
    origin.setY(loc.getY() + 0.9)   # примерная высота "пояса"

    color = Color.fromRGB(214, 200, 60)
    dust_opts = Particle.DustOptions(color, 0.55)

    prev_point = origin.clone()
    hit_something = False
    for i in range(1, PEE_STEPS + 1):
        t = i * 0.045
        horiz = PEE_STREAM_SPEED * t
        if horiz > PEE_RADIUS:
            break
        drop = 0.5 * PEE_GRAVITY * t * t
        wobble = math.sin(t * 9.0 + (now_tick() % 20)) * PEE_JITTER

        point = origin.clone().add(direction.clone().multiply(horiz))
        point.add(side.clone().multiply(wobble))
        point.setY(origin.getY() + vertical_aim * horiz * 0.6 - drop)

        block = point.getBlock()
        try:
            block_type = block.getType()
            solid = block_type.isSolid()
            liquid = block_type.isLiquid()
        except Exception:
            solid = False
            liquid = False

        if solid or liquid:
            _pee_splash(world, prev_point, color)
            hit_something = True
            break

        try:
            world.spawnParticle(Particle.DUST, point, 2, 0.03, 0.03, 0.03, 0.0, dust_opts)
        except Exception:
            pass
        prev_point = point.clone()

    if not hit_something:
        # Долетела до предела дальности, не встретив препятствий - лёгкий всплеск в воздухе
        _pee_splash(world, prev_point, color)

    if random.random() < 0.25:
        try:
            world.playSound(origin, Sound.ITEM_BUCKET_EMPTY, 0.15, 1.8)
        except Exception:
            pass


def _pee_splash(world, point, color):
    try:
        dust_opts = Particle.DustOptions(color, 0.6)
        world.spawnParticle(Particle.DUST, point, 6, 0.08, 0.02, 0.08, 0.0, dust_opts)
    except Exception:
        pass
    try:
        world.spawnParticle(Particle.SPLASH, point, 3, 0.1, 0.0, 0.1, 0.01)
    except Exception:
        pass


def _pee_ticker():
    try:
        if peeing_players:
            for u in list(peeing_players):
                try:
                    p = Bukkit.getPlayer(JUUID.fromString(u))
                except Exception:
                    p = None
                if p is None or not p.isOnline() or p.isDead():
                    peeing_players.discard(u)
                    continue
                if p.getGameMode() == GameMode.SPECTATOR:
                    peeing_players.discard(u)
                    continue
                _draw_pee_stream(p)
    except Exception as ex:
        Bukkit.getLogger().warning("[rp_actions] pee ticker error: " + str(ex))
    scheduler.runTaskLater(_pee_ticker, PEE_TICK_INTERVAL)


def _stop_pee(player, silent=False):
    u = uid(player)
    if u in peeing_players:
        peeing_players.discard(u)
        if not silent:
            player.sendMessage(u"§a✓ §7Вы закончили.")


def on_pee_command(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"Команда доступна только игрокам.")
        return True

    u = uid(sender)
    if u in peeing_players:
        _stop_pee(sender)
        return True

    if not check_cd(sender, "pee", u"Действие"):
        return True

    _clear_other_states(sender, keep="pee")
    peeing_players.add(u)
    set_cd(sender, "pee", 10)
    sender.sendMessage(u"§b§l~ §7Процесс начат. Струя направляется туда, куда вы смотрите. "
                        u"Повторите §e/pee §7, чтобы остановиться (только так это можно отменить).")
    return True


# =========================================================================
# /spit - ПЛЕВОК С ФЕЙК-УРОНОМ ("КРАСНЫЙ ЭКРАН" БЕЗ РЕАЛЬНОЙ ПОТЕРИ HP)
# =========================================================================
SPIT_MAX_DIST = 20.0
SPIT_RAY_RADIUS = 0.6        # эффективный радиус попадания вокруг линии взгляда
SPIT_TRAVEL_TICKS = 5        # количество кадров полёта плевка
SPIT_STEP_INTERVAL = 1       # интервал между кадрами анимации (в тиках)
SPIT_FAKE_DAMAGE = 1.0       # условная величина "фейкового" урона (пол-сердца)
SPIT_COOLDOWN_TICKS = 40     # 2 секунды анти-спама


def _find_spit_target(player):
    """Ищет ближайшую живую цель вдоль линии взгляда игрока (или точку в стене/воздухе)."""
    eye = player.getEyeLocation()
    direction = eye.getDirection().normalize()
    world = player.getWorld()
    eye_vec = eye.toVector()

    block_hit = world.rayTraceBlocks(eye, direction, SPIT_MAX_DIST)
    if block_hit is not None:
        max_check_dist = block_hit.getHitPosition().distance(eye_vec)
    else:
        max_check_dist = SPIT_MAX_DIST

    best_entity = None
    best_dist = max_check_dist

    for e in player.getNearbyEntities(SPIT_MAX_DIST, SPIT_MAX_DIST, SPIT_MAX_DIST):
        if not isinstance(e, LivingEntity):
            continue
        try:
            target_point = e.getLocation().toVector().add(Vector(0.0, e.getHeight() * 0.5, 0.0))
        except Exception:
            target_point = e.getLocation().toVector()
        to_e = target_point.subtract(eye_vec)
        proj = to_e.dot(direction)
        if proj <= 0.2 or proj > best_dist:
            continue
        closest_point = direction.clone().multiply(proj)
        perp_dist = to_e.clone().subtract(closest_point).length()
        if perp_dist <= SPIT_RAY_RADIUS:
            best_dist = proj
            best_entity = e

    end_vec = eye_vec.clone().add(direction.clone().multiply(best_dist))
    return best_entity, eye_vec, end_vec, world


def _apply_fake_damage(target):
    """Наносит визуальный "фейк-урон": реальный damage() применяется и тут же откатывается,
    чтобы жертва увидела ванильную красную вспышку экрана и услышала звук удара, но не
    потеряла HP по-настоящему. Если HP слишком мало - только безопасная анимация без урона."""
    try:
        current_hp = target.getHealth()
        if current_hp is None or current_hp <= 1.0:
            try:
                target.playHurtAnimation(0.0)
            except Exception:
                pass
            return
        target.damage(SPIT_FAKE_DAMAGE)
        target.setHealth(current_hp)
    except Exception as ex:
        Bukkit.getLogger().warning("[rp_actions] fake damage error: " + str(ex))


def _finish_spit(player, end_vec, world, hit_entity):
    end_loc = end_vec.toLocation(world)
    try:
        world.spawnParticle(Particle.SPIT, end_loc, 6, 0.08, 0.08, 0.08, 0.01)
    except Exception:
        try:
            world.spawnParticle(Particle.CLOUD, end_loc, 6, 0.08, 0.08, 0.08, 0.01)
        except Exception:
            pass
    try:
        world.playSound(end_loc, Sound.ENTITY_LLAMA_SPIT, 0.5, 1.0)
    except Exception:
        pass

    if hit_entity is not None:
        try:
            still_valid = hit_entity.isValid() and not hit_entity.isDead()
        except Exception:
            still_valid = False
        if still_valid:
            _apply_fake_damage(hit_entity)
            if isinstance(hit_entity, Player):
                target_name = hit_entity.getName()
            else:
                target_name = str(hit_entity.getType())
            player.sendMessage(u"§a✓ §7Плевок попал в §f" + _to_unicode(target_name) + u"§7!")
            return
    player.sendMessage(u"§7Плевок улетел в никуда...")


def _animate_spit(player, start_vec, end_vec, world, hit_entity, step):
    try:
        if step > SPIT_TRAVEL_TICKS:
            _finish_spit(player, end_vec, world, hit_entity)
            return
        t = step / float(SPIT_TRAVEL_TICKS)
        diff = end_vec.clone().subtract(start_vec)
        cur_vec = start_vec.clone().add(diff.multiply(t))
        cur_loc = cur_vec.toLocation(world)
        try:
            world.spawnParticle(Particle.SPIT, cur_loc, 1, 0.0, 0.0, 0.0, 0.0)
        except Exception:
            try:
                world.spawnParticle(Particle.CLOUD, cur_loc, 1, 0.02, 0.02, 0.02, 0.0)
            except Exception:
                pass
    except Exception as ex:
        Bukkit.getLogger().warning("[rp_actions] spit animate error: " + str(ex))

    scheduler.runTaskLater(
        lambda: _animate_spit(player, start_vec, end_vec, world, hit_entity, step + 1),
        SPIT_STEP_INTERVAL
    )


def on_spit_command(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"Команда доступна только игрокам.")
        return True

    if not check_cd(sender, "spit", u"Плевок"):
        return True
    set_cd(sender, "spit", SPIT_COOLDOWN_TICKS)

    hit_entity, start_vec, end_vec, world = _find_spit_target(sender)
    try:
        world.playSound(sender.getEyeLocation(), Sound.ENTITY_LLAMA_SPIT, 0.35, 1.4)
    except Exception:
        pass

    _animate_spit(sender, start_vec, end_vec, world, hit_entity, 0)
    return True


# =========================================================================
# /sit - [ОСНОВНАЯ КОМАНДА, НЕ ИЗМЕНЯЛАСЬ] СЕСТЬ ПРЯМО ГДЕ СТОИШЬ
# =========================================================================
SIT_SEAT_Y_OFFSET = -0.6   # высота посадки; подберите иначе (-0.9..-0.3), если сидит криво


def _stop_sit(player, silent=False):
    u = uid(player)
    stand = seat_stands.pop(u, None)
    if stand is None:
        return
    try:
        vehicle = player.getVehicle()
        if vehicle is not None and vehicle.getEntityId() == stand.getEntityId():
            player.leaveVehicle()
    except Exception:
        pass
    try:
        stand.remove()
    except Exception:
        pass
    if not silent:
        player.sendMessage(u"§a✓ §7Вы встали.")


def on_sit_command(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"Команда доступна только игрокам.")
        return True

    u = uid(sender)
    if u in seat_stands:
        _stop_sit(sender)
        return True

    try:
        if sender.isInsideVehicle():
            sender.sendMessage(u"§c✗ §7Вы уже сидите верхом или находитесь в транспорте.")
            return True
    except Exception:
        pass

    if not sender.isOnGround():
        sender.sendMessage(u"§c✗ §7Сесть можно только стоя на твёрдой поверхности.")
        return True

    if not check_cd(sender, "sit", u"Сесть"):
        return True

    _clear_other_states(sender, keep="sit")

    seat_loc = sender.getLocation().clone()
    seat_loc.setY(seat_loc.getY() + SIT_SEAT_Y_OFFSET)

    stand = sender.getWorld().spawn(seat_loc, ArmorStand)
    stand.setVisible(False)
    stand.setMarker(True)          # нулевой хитбокс - никого не толкает и не блокирует
    stand.setGravity(False)
    stand.setInvulnerable(True)
    stand.setSilent(True)
    stand.setSmall(True)
    stand.setBasePlate(False)
    stand.setCustomNameVisible(False)
    try:
        stand.setPersistent(False)
    except Exception:
        pass
    stand.addPassenger(sender)

    seat_stands[u] = stand
    set_cd(sender, "sit", 10)
    sender.sendMessage(u"§a✓ §7Вы сели. Повторите §e/sit§7, спрыгните (пробел) или "
                        u"пригнитесь (шифт), чтобы встать.")
    return True


# =========================================================================
# БЛОК /esit - ЭКСПЕРИМЕНТАЛЬНАЯ АЛЬТЕРНАТИВА /sit СО СВОБОДНЫМ ПОВОРОТОМ
# (не связана с /sit ни одной структурой данных - можно вырезать целиком)
# =========================================================================
ESIT_SEAT_Y_OFFSET = -0.6      # высота посадки (не влияет на /sit)
ESIT_ROTATE_INTERVAL = 1       # синхронизация угла сидушки каждый тик - без этого
                                # накапливается расхождение между углом сидушки и взглядом
                                # игрока, из-за чего клиент "ломает" картинку на развороте


def _esit_rotation_ticker():
    """Каждый тик подстраивает поворот ArmorStand-сидушки под текущий взгляд игрока.
    Именно расхождение между этими двумя углами и вызывает поломку камеры на развороте
    у обычных seat-реализаций (в т.ч. и у нашего /sit) - здесь оно никогда не накапливается."""
    try:
        if esit_stands:
            for u in list(esit_stands.keys()):
                stand = esit_stands.get(u)
                if stand is None or not stand.isValid():
                    esit_stands.pop(u, None)
                    continue
                try:
                    p = Bukkit.getPlayer(JUUID.fromString(u))
                except Exception:
                    p = None
                if p is None or not p.isOnline():
                    try:
                        stand.remove()
                    except Exception:
                        pass
                    esit_stands.pop(u, None)
                    continue
                try:
                    stand.setRotation(p.getLocation().getYaw(), 0.0)
                except Exception:
                    pass
    except Exception as ex:
        Bukkit.getLogger().warning("[rp_actions] esit rotation ticker error: " + str(ex))
    scheduler.runTaskLater(_esit_rotation_ticker, ESIT_ROTATE_INTERVAL)


def _stop_esit(player, silent=False):
    u = uid(player)
    stand = esit_stands.pop(u, None)
    if stand is None:
        return
    try:
        vehicle = player.getVehicle()
        if vehicle is not None and vehicle.getEntityId() == stand.getEntityId():
            player.leaveVehicle()
    except Exception:
        pass
    try:
        stand.remove()
    except Exception:
        pass
    if not silent:
        player.sendMessage(u"§a✓ §7Вы встали.")


def on_esit_command(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"Команда доступна только игрокам.")
        return True

    u = uid(sender)
    if u in esit_stands:
        _stop_esit(sender)
        return True

    try:
        if sender.isInsideVehicle():
            sender.sendMessage(u"§c✗ §7Вы уже сидите верхом или находитесь в транспорте.")
            return True
    except Exception:
        pass

    if not sender.isOnGround():
        sender.sendMessage(u"§c✗ §7Сесть можно только стоя на твёрдой поверхности.")
        return True

    if not check_cd(sender, "esit", u"Сесть"):
        return True

    _clear_other_states(sender, keep="esit")

    seat_loc = sender.getLocation().clone()
    seat_loc.setY(seat_loc.getY() + ESIT_SEAT_Y_OFFSET)

    stand = sender.getWorld().spawn(seat_loc, ArmorStand)
    stand.setVisible(False)
    stand.setMarker(True)          # нулевой хитбокс - никого не толкает и не блокирует
    stand.setGravity(False)
    stand.setInvulnerable(True)
    stand.setSilent(True)
    stand.setSmall(True)
    stand.setBasePlate(False)
    stand.setCustomNameVisible(False)
    try:
        stand.setPersistent(False)
    except Exception:
        pass
    stand.setRotation(sender.getLocation().getYaw(), 0.0)
    stand.addPassenger(sender)

    esit_stands[u] = stand
    set_cd(sender, "esit", 10)
    sender.sendMessage(u"§a✓ §7Вы сели (свободный поворот камеры). Повторите §e/esit§7, "
                        u"спрыгните (пробел) или пригнитесь (шифт), чтобы встать.")
    return True
# =========================================================================
# КОНЕЦ БЛОКА /esit
# =========================================================================


def on_entity_dismount(event):
    entity = event.getEntity()
    if not isinstance(entity, Player):
        return
    u = uid(entity)
    dismounted = event.getDismounted()

    stand = seat_stands.get(u)
    if stand is not None:
        try:
            same = dismounted.getEntityId() == stand.getEntityId()
        except Exception:
            same = (dismounted == stand)
        if same:
            seat_stands.pop(u, None)
            try:
                stand.remove()
            except Exception:
                pass
            entity.sendMessage(u"§7Вы встали.")
            return

    # --- БЛОК /esit: обработка схода с сидушки /esit, независимо от /sit ---
    estand = esit_stands.get(u)
    if estand is not None:
        try:
            same = dismounted.getEntityId() == estand.getEntityId()
        except Exception:
            same = (dismounted == estand)
        if same:
            esit_stands.pop(u, None)
            try:
                estand.remove()
            except Exception:
                pass
            entity.sendMessage(u"§7Вы встали.")
    # --- конец блока /esit ---


# =========================================================================
# /lay - ЛЕЧЬ / ПОЛЗТИ-ПЛЫТЬ БЕСКОНЕЧНО (ФЕЙКОВЫЙ КЛИЕНТСКИЙ "ПОТОЛОК")
# =========================================================================
# Приём: игроку лично (sendBlockChange - блок никогда не появляется в мире по-настоящему,
# другие игроки его не видят и не задеваются им) отправляется невидимый BARRIER на 1 блок
# выше головы. Ванильный клиент Minecraft сам определяет, что высота прохода <2 блоков,
# и переключает САМОГО игрока (не только его отображение для других) в позу заплыва/ползка -
# с корректной камерой и хитбоксом, точно как при протискивании в вентиляцию/пещеру.
# Так делает GSit и официально задокументированный приём из открытых источников
# (MineAcademy "Crawling", CowCannon Crawl.java) - в отличие от Entity.setPose(), который
# не обновляет отображение у самого игрока (см. PaperMC/Paper issue #7016 / PR #8781).
BARRIER_BLOCK_DATA = None   # инициализируется лениво в on_enable (Bukkit ещё не готов при импорте)


def _get_barrier_data():
    global BARRIER_BLOCK_DATA
    if BARRIER_BLOCK_DATA is None:
        BARRIER_BLOCK_DATA = Material.BARRIER.createBlockData()
    return BARRIER_BLOCK_DATA


def _lay_clear_barrier(player):
    """Убирает фейковый барьер (если есть), возвращая игроку реальное состояние блока."""
    u = uid(player)
    old_loc = lay_barrier_loc.pop(u, None)
    if old_loc is None:
        return
    try:
        real_block = old_loc.getBlock()
        player.sendBlockChange(old_loc, real_block.getBlockData())
    except Exception:
        pass


def _lay_update_barrier(player):
    """Проверяет блок над головой игрока и при необходимости пересоздаёт фейковый барьер
    на новом месте (вызывается при активации /lay и при каждой смене блока игроком)."""
    u = uid(player)
    loc = player.getLocation()
    try:
        block_above = loc.getBlock().getRelative(BlockFace.UP)
    except Exception:
        return

    old_loc = lay_barrier_loc.get(u)
    same_block = False
    if old_loc is not None:
        try:
            same_block = (old_loc.getBlockX() == block_above.getX() and
                          old_loc.getBlockY() == block_above.getY() and
                          old_loc.getBlockZ() == block_above.getZ())
        except Exception:
            same_block = False

    if same_block:
        return

    _lay_clear_barrier(player)

    try:
        already_solid = block_above.getType().isSolid()
    except Exception:
        already_solid = False

    if already_solid:
        # Настоящий низкий потолок уже есть - ваниль сама заставит игрока ползти,
        # свой фейковый барьер тут не нужен.
        return

    try:
        fake_loc = block_above.getLocation()
        player.sendBlockChange(fake_loc, _get_barrier_data())
        lay_barrier_loc[u] = fake_loc
    except Exception as ex:
        Bukkit.getLogger().warning("[rp_actions] lay barrier error: " + str(ex))


def _stop_lay(player, silent=False):
    u = uid(player)
    if u not in laying_players:
        return
    laying_players.discard(u)
    _lay_clear_barrier(player)
    if not silent:
        player.sendMessage(u"§a✓ §7Вы поднялись на ноги.")


def on_lay_command(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"Команда доступна только игрокам.")
        return True

    u = uid(sender)
    if u in laying_players:
        _stop_lay(sender)
        return True

    try:
        if sender.isInsideVehicle():
            sender.sendMessage(u"§c✗ §7Нельзя лечь, находясь в транспорте/сидя верхом.")
            return True
    except Exception:
        pass

    if not check_cd(sender, "lay", u"Лечь"):
        return True

    _clear_other_states(sender, keep="lay")

    laying_players.add(u)
    _lay_update_barrier(sender)
    set_cd(sender, "lay", 10)
    sender.sendMessage(u"§a✓ §7Вы легли и можете ползти/плыть в любом направлении сколько "
                        u"угодно (движение WASD не ограничено). Повторите §e/lay§7, чтобы встать.")
    return True


def on_player_move(event):
    """Единственный listener PlayerMoveEvent в скрипте: отслеживает смену блока у лежащих
    игроков, чтобы вовремя переносить фейковый барьер над головой."""
    try:
        if not event.hasChangedBlock():
            return
    except Exception:
        pass

    player = event.getPlayer()
    u = uid(player)
    if u in laying_players:
        _lay_update_barrier(player)


# =========================================================================
# АВТО-СНЯТИЕ ПОЗ ПРИ РЕАЛЬНОМ УРОНЕ И ПРИ ВЫХОДЕ ИГРОКА
# =========================================================================
def on_entity_damage(event):
    entity = event.getEntity()
    if not isinstance(entity, Player):
        return
    u = uid(entity)
    if u in seat_stands:
        _stop_sit(entity, silent=True)
        entity.sendMessage(u"§e⚠ §7Вас подняло на ноги полученным уроном.")
    if u in esit_stands:
        _stop_esit(entity, silent=True)
        entity.sendMessage(u"§e⚠ §7Вас подняло на ноги полученным уроном.")
    if u in laying_players:
        _stop_lay(entity, silent=True)
        entity.sendMessage(u"§e⚠ §7Вы вскочили на ноги от полученного урона.")


def on_player_quit(event):
    player = event.getPlayer()
    u = uid(player)
    peeing_players.discard(u)
    laying_players.discard(u)
    lay_barrier_loc.pop(u, None)   # реальный блок восстанавливать некому - игрок уже вышел

    stand = seat_stands.pop(u, None)
    if stand is not None:
        try:
            stand.remove()
        except Exception:
            pass

    estand = esit_stands.pop(u, None)
    if estand is not None:
        try:
            estand.remove()
        except Exception:
            pass

    cooldowns.pop(u, None)


# -------------------------------------------------------------------------
# РЕГИСТРАЦИЯ СЛУШАТЕЛЕЙ И КОМАНД
# -------------------------------------------------------------------------
def _register_command(handler, name):
    try:
        cmd_mgr.registerCommand(handler, name)
    except TypeError:
        try:
            cmd_mgr.registerCommand(handler)
        except Exception as ex:
            Bukkit.getLogger().warning("[rp_actions] registerCommand fallback (" + name + "): " + str(ex))


def on_enable():
    _get_barrier_data()

    listener_mgr.registerListener(on_entity_dismount, EntityDismountEvent)
    listener_mgr.registerListener(on_entity_damage, EntityDamageEvent)
    listener_mgr.registerListener(on_player_quit, PlayerQuitEvent)
    listener_mgr.registerListener(on_player_move, PlayerMoveEvent)

    _register_command(on_pee_command, "pee")
    _register_command(on_spit_command, "spit")
    _register_command(on_sit_command, "sit")
    _register_command(on_esit_command, "esit")
    _register_command(on_lay_command, "lay")

    scheduler.runTaskLater(_pee_ticker, PEE_TICK_INTERVAL)
    scheduler.runTaskLater(_esit_rotation_ticker, ESIT_ROTATE_INTERVAL)

    Bukkit.getLogger().info("[rp_actions] RP action commands loaded: /pee /spit /sit /esit /lay")


def on_disable():
    for u in list(seat_stands.keys()):
        stand = seat_stands.pop(u, None)
        if stand is not None:
            try:
                stand.remove()
            except Exception:
                pass

    for u in list(esit_stands.keys()):
        stand = esit_stands.pop(u, None)
        if stand is not None:
            try:
                stand.remove()
            except Exception:
                pass

    for u in list(laying_players):
        try:
            p = Bukkit.getPlayer(JUUID.fromString(u))
        except Exception:
            p = None
        if p is not None:
            _lay_clear_barrier(p)

    laying_players.clear()
    lay_barrier_loc.clear()
    peeing_players.clear()
    Bukkit.getLogger().info("[rp_actions] Disabled.")


on_enable()

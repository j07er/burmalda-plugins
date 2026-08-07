# -*- coding: utf-8 -*-
"""
rp_actions.py - Ролевые команды-приколы для PySpigot 0.9.1 (Jython 2.7) + Paper 1.21.11

Команды:
  /pee   - Начать/закончить "писать". Направленная (по взгляду игрока) струя частиц,
           летящая по параболе с наложенной вертикальной синусоидой (естественное
           "гуляние" струи вверх-вниз под напором, как у настоящей жидкости) вдоль
           направления взгляда, дальность ~3.5 блока, останавливается о стены/пол/воду.
           Отменяется ТОЛЬКО повторным вводом /pee.
  /spit  - Плюнуть в направлении взгляда. Быстрый бросок (скорость и время полёта считаются
           от реальной дистанции до цели, а не фиксированным числом тиков) с анимацией частиц
           Particle.SPIT; при попадании по живому существу наносится "фейк-урон" (реальный
           урон применяется и тут же полностью восстанавливается) - жертва получает
           ванильную красную вспышку экрана и звук удара, но не теряет HP по-настоящему.
  /sit   - Сесть прямо там, где стоите, через невидимый ArmorStand-Marker (нулевой хитбокс,
           никого не блокирует). Направление сидения фиксируется в момент посадки - если
           нужен вариант со свободным поворотом камеры, используйте /esit. При вставании
           (в т.ч. через шифт) игрок принудительно телепортируется на точку, где стоял до
           посадки - без этого ванильный алгоритм высадки с нулевого хитбокса Marker'а
           иногда роняет игрока на блок ниже.
  /esit  - ЭКСПЕРИМЕНТАЛЬНАЯ версия /sit со свободным поворотом камеры без "поломки" вида
           на развороте. Отличие от /sit: угол сидушки (ArmorStand) синхронизируется с
           текущим взглядом игрока каждый тик, поэтому расхождение между углом сидушки и
           углом обзора никогда не накапливается - клиенту не приходится "довращать" через
           короткую/длинную сторону круга, из-за чего у ванильных seat-реализаций на большом
           повороте (в т.ч. ~180°) ломается картинка. Та же защита от падения при вставании,
           что и в /sit. Полностью независима от /sit: свой реестр сидушек, свой тикер -
           можно вырезать блок "БЛОК /esit" целиком без влияния на /sit.
  /lay   - Лечь / ползти-плыть на месте БЕЗ ограничения движения. Реализация - комбинация
           ДВУХ приёмов, каждый из которых закрывает дыру другого:
             1) "Фейковый потолок" (sendBlockChange - блок не существует в мире по-
                настоящему, виден только самому игроку): невидимый барьер на 1 блок над
                головой. Ванильный клиент сам решает, что видит потолок ниже 2 блоков, и
                переходит САМ ИСПОЛНИТЕЛЬ (не только его отображение для других) в
                настоящую клиентскую позу заплыва/ползка - с корректной камерой и
                хитбоксом. Но sendBlockChange меняет мир только для одного игрока -
                другие как видели, так и продолжают видеть исполнителя обычно стоящим.
             2) Entity.setPose(Pose.SWIMMING, fixed=True) - наоборот, корректно
                транслирует позу ДРУГИМ игрокам (подтверждено авторами API в обсуждении
                PaperMC/Paper#8781), но НЕ обновляет отображение у самого исполнителя
                (см. issue #7016) - сам игрок в отрыве от приёма (1) видел бы себя стоящим.
           Барьер (1) пересчитывается на КАЖДОЕ реальное перемещение игрока (используя
           event.getTo(), а не устаревшую на момент события player.getLocation() - см.
           комментарий в _lay_update_barrier), поэтому не отстаёт даже при быстром
           ползании; ползать можно бесконечно в любом направлении, WASD работает как
           обычно, другие игроки не ограничены никакими барьерами (барьер реален только
           на экране лежащего - его позу они видят через (2)).

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
from org.bukkit.boss import BarColor, BarStyle
from org.bukkit.block import BlockFace
from org.bukkit.util import Vector
from org.bukkit.entity import Player, LivingEntity, ArmorStand, Pose
from org.bukkit.event import EventPriority
from org.bukkit.event.player import PlayerQuitEvent, PlayerMoveEvent, PlayerCommandPreprocessEvent, PlayerToggleFlightEvent
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
seat_return_loc = {}       # uid -> Location, куда точно телепортировать при вставании с /sit
esit_stands = {}           # uid -> ArmorStand (посадочное место /esit, независимо от /sit)
esit_return_loc = {}       # uid -> Location, куда точно телепортировать при вставании с /esit


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
PEE_TICK_INTERVAL = 2        # анимация обновляется раз в 2 тика (~0.1 сек)


def _draw_pee_stream(player):
    """Draw one gaze-controlled ballistic arc (no repeating sine wave)."""
    loc = player.getLocation()
    world = player.getWorld()
    from org.bukkit import Color

    aim = loc.getDirection().clone()
    if aim.lengthSquared() < 1e-6:
        aim = Vector(0.0, 0.0, 1.0)
    aim.normalize()

    # The source is near the waist. Full pitch is deliberately preserved:
    # looking straight up sends the arc through the player's face before it falls.
    horizontal_hint = Vector(aim.getX(), 0.0, aim.getZ())
    if horizontal_hint.lengthSquared() > 1e-6:
        horizontal_hint.normalize().multiply(0.24)
    origin = loc.clone().add(horizontal_hint)
    origin.setY(loc.getY() + 0.82)

    launch_speed = 3.65
    gravity = 5.8
    # A small upward impulse gives a readable single arc when looking forward;
    # pitch then raises/lowers it. Looking straight up still sends it through
    # the face line, but the clamp keeps the effect compact.
    vertical_speed = max(-1.5, min(4.4, aim.getY() * launch_speed + 2.25))
    max_time = 1.65
    steps = 44
    color = Color.fromRGB(214, 200, 60)
    dust_opts = Particle.DustOptions(color, 0.55)
    previous = origin.clone()
    hit = False

    for i in range(1, steps + 1):
        t = max_time * float(i) / float(steps)
        displacement = Vector(aim.getX() * launch_speed * t,
                              vertical_speed * t,
                              aim.getZ() * launch_speed * t)
        point = origin.clone().add(displacement)
        point.setY(point.getY() - 0.5 * gravity * t * t)

        # Stop after the returning branch reaches the source height; this keeps
        # the effect a single large arc instead of an endless falling trace.
        if t > max(0.12, vertical_speed / gravity) and point.getY() < origin.getY() - 0.18:
            _pee_splash(world, previous, color)
            hit = True
            break

        block = point.getBlock()
        try:
            blocked = block.getType().isSolid() or block.getType().isLiquid()
        except Exception:
            blocked = False
        if blocked:
            _pee_splash(world, previous, color)
            hit = True
            break
        try:
            world.spawnParticle(Particle.DUST, point, 2, 0.025, 0.025, 0.025, 0.0, dust_opts)
        except Exception:
            pass
        previous = point.clone()

    if not hit:
        _pee_splash(world, previous, color)
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
SPIT_SPEED = 4.5             # скорость плевка, блоков за тик (~90 блоков/сек - быстрый бросок)
SPIT_TRAIL_SUBSTEPS = 3      # доп. промежуточные точки на кадр - убирает "рваность" при высокой скорости
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


def _animate_spit(player, start_vec, end_vec, world, hit_entity, travel_ticks, step):
    try:
        diff = end_vec.clone().subtract(start_vec)
        # На каждый тик рисуем несколько промежуточных точек вдоль отрезка - при высокой
        # скорости полёта (по требованию - "плевок летит слишком медленно") одна точка
        # за тик выглядела бы как редкие рывки, а не как быстрый цельный бросок.
        for sub in range(SPIT_TRAIL_SUBSTEPS + 1):
            frac_step = step + (sub / float(SPIT_TRAIL_SUBSTEPS + 1))
            if frac_step > travel_ticks:
                break
            t = frac_step / float(travel_ticks) if travel_ticks > 0 else 1.0
            cur_vec = start_vec.clone().add(diff.clone().multiply(t))
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

    if step >= travel_ticks:
        _finish_spit(player, end_vec, world, hit_entity)
        return

    scheduler.runTaskLater(
        lambda: _animate_spit(player, start_vec, end_vec, world, hit_entity, travel_ticks, step + 1),
        1
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

    distance = start_vec.distance(end_vec)
    # Число тиков полёта считаем от реальной дистанции и скорости, а не фиксированной
    # константой - раньше на любой дистанции плевок летел одинаковые 5 тиков (0.25 сек),
    # из-за чего на близких дистанциях он казался "тягучим". Минимум 1 тик, чтобы даже
    # плевок в упор не был мгновенно телепортирован без анимации.
    travel_ticks = max(1, int(math.ceil(distance / SPIT_SPEED)))

    _animate_spit(sender, start_vec, end_vec, world, hit_entity, travel_ticks, 0)
    return True


# =========================================================================
# /sit - СЕСТЬ ПРЯМО ГДЕ СТОИШЬ
# =========================================================================
# ВАЖНО про Y-смещение: Location.getY() стоящего на земле игрока - это уже ВЕРХНЯЯ грань
# блока, на котором он стоит (блок под ногами занимает диапазон [Y-1, Y)). Поэтому
# смещение сидушки ДОЛЖНО быть >= 0.0 - любое отрицательное значение вмуровывает
# невидимый ArmorStand прямо внутрь твёрдого блока пола. Раньше тут стояло -0.6, из-за
# чего при leaveVehicle() игра выталкивала игрока из блока вниз, под пол (падение).
#
# ВАЖНО про падение на 1 блок вниз при вставании (в т.ч. через шифт): у ArmorStand с
# Marker=true нулевой bounding box, и ванильный алгоритм поиска "безопасного места для
# высадки" (используется при leaveVehicle()/шифте) не может по нулевому хитбоксу понять,
# где у сидушки "верх", и промахивается на блок вниз. Это системное ограничение движка,
# а не баг именно этого скрипта - поэтому решение не "поправить смещение", а вообще не
# полагаться на ванильную высадку: запоминаем точную точку, где игрок стоял ДО посадки,
# и сразу после схода принудительно телепортируем его туда же.
SIT_SEAT_Y_OFFSET = 0.0    # 0.0 = сидушка строго в воздухе над блоком, без вмуровки


def _stop_sit(player, silent=False):
    u = uid(player)
    stand = seat_stands.pop(u, None)
    return_loc = seat_return_loc.pop(u, None)
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
    if return_loc is not None:
        try:
            # Принудительно возвращаем игрока туда, где он стоял до посадки - без этого
            # ванильная высадка с Marker-ArmorStand может уронить его на блок ниже.
            player.teleport(return_loc)
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

    # Точка, куда игрок вернётся при вставании - фиксируем ДО любых изменений позиции.
    stand_up_loc = sender.getLocation().clone()

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

    # Проверяем, что монтирование реально произошло (при вмуровке в блок оно могло
    # тихо провалиться) - если нет, откатываем и сообщаем игроку вместо "молчаливого сбоя".
    if sender.getVehicle() is None or sender.getVehicle().getEntityId() != stand.getEntityId():
        try:
            stand.remove()
        except Exception:
            pass
        sender.sendMessage(u"§c✗ §7Не удалось сесть здесь (недостаточно места). Попробуйте в другом месте.")
        return True

    seat_stands[u] = stand
    seat_return_loc[u] = stand_up_loc
    set_cd(sender, "sit", 10)
    sender.sendMessage(u"§a✓ §7Вы сели. Повторите §e/sit§7, спрыгните (пробел) или "
                        u"пригнитесь (шифт), чтобы встать.")
    return True


# =========================================================================
# БЛОК /esit - ЭКСПЕРИМЕНТАЛЬНАЯ АЛЬТЕРНАТИВА /sit СО СВОБОДНЫМ ПОВОРОТОМ
# (не связана с /sit ни одной структурой данных - можно вырезать целиком)
# =========================================================================
ESIT_SEAT_Y_OFFSET = 0.0       # см. пояснение к SIT_SEAT_Y_OFFSET выше - не должно быть отрицательным
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
    return_loc = esit_return_loc.pop(u, None)
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
    if return_loc is not None:
        try:
            # См. пояснение к /sit - принудительная телепортация нужна, потому что
            # ванильный алгоритм высадки не понимает нулевой хитбокс Marker-ArmorStand
            # и роняет игрока на блок ниже.
            player.teleport(return_loc)
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

    # Точка, куда игрок вернётся при вставании - фиксируем ДО любых изменений позиции.
    stand_up_loc = sender.getLocation().clone()

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

    # Та же проверка успешного монтирования, что и в /sit - без неё вмуровка в блок
    # выглядит как "сел ниже, но движение не ограничено" (сущность-то есть, а посадки нет).
    if sender.getVehicle() is None or sender.getVehicle().getEntityId() != stand.getEntityId():
        try:
            stand.remove()
        except Exception:
            pass
        sender.sendMessage(u"§c✗ §7Не удалось сесть здесь (недостаточно места). Попробуйте в другом месте.")
        return True

    esit_stands[u] = stand
    esit_return_loc[u] = stand_up_loc
    set_cd(sender, "esit", 10)
    sender.sendMessage(u"§a✓ §7Вы сели (свободный поворот камеры). Повторите §e/esit§7, "
                        u"спрыгните (пробел) или пригнитесь (шифт), чтобы встать.")
    return True
# =========================================================================
# КОНЕЦ БЛОКА /esit
# =========================================================================


def on_entity_dismount(event):
    """Срабатывает при ЛЮБОМ сходе с транспорта - в т.ч. при нажатии шифта или прыжка.
    Именно поэтому вся логика телепортации на точку возврата вынесена в _stop_sit()/
    _stop_esit() и просто переиспользуется здесь, а не дублируется - раньше тут была
    отдельная урезанная копия без вызова player.teleport(), из-за чего "падение под блок"
    происходило именно при выходе через шифт (через саму команду /sit оно уже чинилось)."""
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
            _stop_sit(entity)
            return

    # --- БЛОК /esit: обработка схода с сидушки /esit, независимо от /sit ---
    estand = esit_stands.get(u)
    if estand is not None:
        try:
            same = dismounted.getEntityId() == estand.getEntityId()
        except Exception:
            same = (dismounted == estand)
        if same:
            _stop_esit(entity)
    # --- конец блока /esit ---


# =========================================================================
# /lay - ЛЕЧЬ / ПОЛЗТИ-ПЛЫТЬ БЕСКОНЕЧНО (КОМБИНАЦИЯ БАРЬЕРА + Entity.setPose)
# =========================================================================
# Почему нужны ОБА приёма сразу (раньше был только барьер, из-за чего другие игроки
# видели исполнителя обычно стоящим - "стою у игроков"):
#   1) sendBlockChange (фейковый BARRIER на 1 блок над головой) - меняет мир ТОЛЬКО в
#      глазах самого игрока, который его вызвал. Ванильный клиент сам определяет, что
#      высота прохода <2 блоков, и переключает САМОГО игрока (не только отображение)
#      в позу заплыва/ползка - с корректной камерой и хитбоксом, точно как при
#      протискивании в вентиляцию/пещеру. Так делает GSit и открытые источники
#      (MineAcademy "Crawling", CowCannon Crawl.java). НО: другие игроки этот пакет не
#      получают - для них ничего не меняется, барьер не работает как "трансляция позы".
#   2) Entity.setPose(Pose.SWIMMING, fixed=True) - работает ровно наоборот: корректно
#      транслирует позу ДРУГИМ игрокам (подтверждено автором PR в обсуждении
#      PaperMC/Paper#8781: "other players will see the pose correctly... having it fixed
#      won't let the player reset it next tick"), но НЕ обновляет отображение у самого
#      исполнителя (см. issue #7016) - без барьера (1) сам игрок видел бы себя стоящим.
# Поэтому оба вызова используются вместе: (1) даёт исполнителю настоящее ползание,
# (2) даёт окружающим корректную картинку.
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


def _lay_update_barrier(player, loc=None):
    """Проверяет блок над головой игрока и при необходимости пересоздаёт фейковый барьер
    на новом месте (вызывается при активации /lay и при каждой смене блока игроком).

    ВАЖНО: если вызов идёт из обработчика PlayerMoveEvent, сюда нужно передавать именно
    event.getTo(), а НЕ player.getLocation(). Bukkit применяет перемещение к игроку только
    ПОСЛЕ обработки события - то есть player.getLocation() внутри обработчика всё ещё
    возвращает СТАРУЮ позицию. Из-за этого барьер раньше пересчитывался на шаг позади
    реального движения и при быстром ползании заметно отставал ("не успевал"). Эталонная
    реализация ползания в GSit (Crawl.java) по той же причине берёт event.getTo(), а не
    getLocation() игрока."""
    u = uid(player)
    if loc is None:
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
    try:
        # Возвращаем обычную позу для ДРУГИХ игроков (fixed=False - клиент дальше сам
        # управляет своей позой как обычно).
        player.setPose(Pose.STANDING, False)
    except Exception:
        pass
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
    try:
        # Фейковый барьер (sendBlockChange) решает картинку ТОЛЬКО для самого игрока -
        # без этого другие игроки продолжают видеть его обычно стоящим (баг "стою у
        # игроков"). Entity.setPose(..., fixed=True), наоборот, корректно транслируется
        # ДРУГИМ игрокам (подтверждено авторами API в обсуждении PaperMC/Paper#8781 -
        # "other players will see the pose correctly... having it fixed won't let the
        # player reset it next tick"), но не обновляет отображение у самого исполнителя.
        # Оба приёма закрывают ровно те дыры, которые оставляет друг друга - поэтому
        # используются вместе, а не как альтернативы.
        sender.setPose(Pose.SWIMMING, True)
    except Exception:
        pass
    set_cd(sender, "lay", 10)
    sender.sendMessage(u"§a✓ §7Вы легли и можете ползти/плыть в любом направлении сколько "
                        u"угодно (движение WASD не ограничено). Повторите §e/lay§7, чтобы встать.")
    return True


# =========================================================================
# TEMPORARY ROLEPLAY ZONES
# =========================================================================
RP_ZONE_DEFAULT_RADIUS = 12.0
RP_ZONE_MAX_RADIUS = 40.0
RP_ZONE_LIFETIME_TICKS = 2 * 60 * 60 * 20
RP_INVITE_COOLDOWN_TICKS = 60 * 20
RP_BLOCKED_COMMANDS = set([
    "fly", "gamemode", "gm", "tp", "teleport", "tpa", "tpaccept", "tpahere",
    "home", "sethome", "spawn", "warp", "back", "rtp", "randomtp", "vanish",
    "heal", "feed", "repair", "arena", "duel", "casino"
])

rp_zones = {}              # id -> live zone
rp_zone_sequence = [1]
rp_invite_cooldowns = {}   # player_uuid:zone_id -> end tick


def _zone_contains(zone, location, margin=0.0):
    if not zone or not location or location.getWorld() != zone["center"].getWorld():
        return False
    dx = location.getX() - zone["center"].getX()
    dz = location.getZ() - zone["center"].getZ()
    radius = float(zone["radius"]) + float(margin)
    return dx * dx + dz * dz <= radius * radius and abs(location.getY() - zone["center"].getY()) <= 12.0


def _find_zone_for_player(player, require_member=False):
    puid = uid(player)
    for zone in rp_zones.values():
        if _zone_contains(zone, player.getLocation()):
            if not require_member or puid in zone["members"]:
                return zone
    return None


def _send_zone_invite(player, zone):
    player.sendMessage(u"§d§l[RP] §fВ зоне «§e%s§f» игроки ведут ролевую сцену." % zone["title"])
    try:
        from net.md_5.bungee.api.chat import TextComponent, ClickEvent, HoverEvent, ComponentBuilder
        button = TextComponent(u"§a§l[ПРИСОЕДИНИТЬСЯ]")
        button.setClickEvent(ClickEvent(ClickEvent.Action.RUN_COMMAND, "/rpzone join " + zone["id"]))
        button.setHoverEvent(HoverEvent(HoverEvent.Action.SHOW_TEXT,
                                       ComponentBuilder(u"§7Войти в RP-сцену и принять её правила").create()))
        player.spigot().sendMessage(button)
    except Exception:
        player.sendMessage(u"§7Введите §a/rpzone join %s§7, чтобы присоединиться." % zone["id"])
    try:
        player.sendActionBar(u"§dRP-зона рядом §8• §f/rpzone join %s" % zone["id"])
    except Exception:
        pass


def _refresh_zone_bar(zone):
    bar = zone.get("bar")
    if bar is None:
        return
    online_inside = []
    for member_uuid in list(zone["members"]):
        try:
            member = Bukkit.getPlayer(JUUID.fromString(member_uuid))
        except Exception:
            member = None
        if member and member.isOnline() and _zone_contains(zone, member.getLocation(), 1.0):
            online_inside.append(member)
    try:
        bar.setTitle(u"§dRP: §f%s §8• §a%d участн." % (zone["title"], len(online_inside)))
        remaining = max(0.0, float(zone["expires_tick"] - now_tick()) / float(RP_ZONE_LIFETIME_TICKS))
        bar.setProgress(min(1.0, remaining))
        bar.removeAll()
        for member in online_inside:
            bar.addPlayer(member)
    except Exception:
        pass


def _end_rp_zone(zone_id, reason=None):
    zone = rp_zones.pop(str(zone_id), None)
    if not zone:
        return False
    try:
        if zone.get("bar"):
            zone["bar"].removeAll()
    except Exception:
        pass
    if reason:
        for member_uuid in list(zone["members"]):
            try:
                member = Bukkit.getPlayer(JUUID.fromString(member_uuid))
                if member and member.isOnline():
                    member.sendMessage(u"§d§l[RP] §7%s" % _to_unicode(reason))
            except Exception:
                pass
    return True


def _rp_zone_ticker():
    try:
        for zone_id, zone in list(rp_zones.items()):
            if now_tick() >= zone["expires_tick"]:
                _end_rp_zone(zone_id, u"RP-зона завершена по лимиту времени.")
                continue
            _refresh_zone_bar(zone)
            center = zone["center"]
            world = center.getWorld()
            # 24 cheap points make the border readable without a heavy particle wall.
            for index in range(24):
                angle = 2.0 * math.pi * float(index) / 24.0
                point = center.clone().add(math.cos(angle) * zone["radius"], 0.15,
                                           math.sin(angle) * zone["radius"])
                try:
                    world.spawnParticle(Particle.END_ROD, point, 1, 0.0, 0.0, 0.0, 0.0)
                except Exception:
                    pass
    except Exception as ex:
        Bukkit.getLogger().warning("[rp_actions] RP-zone ticker error: " + str(ex))
    scheduler.runTaskLater(_rp_zone_ticker, 20)


def on_rpzone_command(sender, label, args):
    if not isinstance(sender, Player):
        sender.sendMessage(u"Команда доступна только игрокам.")
        return True
    sub = _norm(args[0]) if args and len(args) > 0 else u"info"
    player_uuid = uid(sender)

    if sub in [u"help", u"помощь", u"?"]:
        sender.sendMessage(u"§d§lRP-зоны — команды")
        sender.sendMessage(u"§e/rpzone create [радиус] [название] §7— создать сцену")
        sender.sendMessage(u"§e/rpzone join <ID> §7— присоединиться к сцене")
        sender.sendMessage(u"§e/rpzone list §7— участники вашей сцены")
        sender.sendMessage(u"§e/rpzone info §7— сведения о зоне рядом")
        sender.sendMessage(u"§e/rpzone leave §7— покинуть сцену")
        sender.sendMessage(u"§e/rpzone end §7— завершить созданную вами сцену")
        return True

    if sub in [u"list", u"players", u"список", u"игроки"]:
        zone = next((z for z in rp_zones.values() if player_uuid in z["members"]), None)
        if zone is None and sender.hasPermission("roleplay.zone.admin") and len(args) > 1:
            zone = rp_zones.get(str(args[1]))
        if zone is None:
            sender.sendMessage(u"§cВы не состоите в активной RP-зоне.")
            return True
        sender.sendMessage(u"§d§l[RP] §fУчастники зоны #%s «%s» §7(%d):" %
                           (zone["id"], zone["title"], len(zone["members"])))
        for member_uuid in list(zone["members"]):
            member = None
            name = member_uuid
            try:
                java_uuid = JUUID.fromString(member_uuid)
                member = Bukkit.getPlayer(java_uuid)
                if member is not None:
                    name = member.getName()
                else:
                    offline = Bukkit.getOfflinePlayer(java_uuid)
                    if offline is not None and offline.getName():
                        name = offline.getName()
            except Exception:
                pass
            if member is not None and member.isOnline():
                status = u"§aв зоне" if _zone_contains(zone, member.getLocation(), 1.0) else u"§eвне зоны"
            else:
                status = u"§8не в сети"
            owner_mark = u" §6[владелец]" if member_uuid == zone["owner_uuid"] else u""
            sender.sendMessage(u" §8• §f%s%s §7— %s" % (name, owner_mark, status))
        return True

    if sub in [u"create", u"start", u"создать"]:
        owned = next((z for z in rp_zones.values() if z["owner_uuid"] == player_uuid), None)
        if owned:
            sender.sendMessage(u"§cУ вас уже есть RP-зона #%s." % owned["id"])
            return True
        try:
            radius = float(args[1]) if len(args) > 1 else RP_ZONE_DEFAULT_RADIUS
        except Exception:
            radius = RP_ZONE_DEFAULT_RADIUS
        radius = max(5.0, min(RP_ZONE_MAX_RADIUS, radius))
        title = u" ".join([_to_unicode(a) for a in args[2:]]).strip() if len(args) > 2 else u"Ролевая сцена"
        zone_id = str(rp_zone_sequence[0])
        rp_zone_sequence[0] += 1
        try:
            bar = Bukkit.createBossBar(u"§dRP: §f" + title, BarColor.PURPLE, BarStyle.SOLID)
        except Exception:
            bar = None
        zone = {"id": zone_id, "owner_uuid": player_uuid, "owner_name": sender.getName(),
                "title": title[:60], "center": sender.getLocation().clone(), "radius": radius,
                "members": set([player_uuid]), "created_tick": now_tick(),
                "expires_tick": now_tick() + RP_ZONE_LIFETIME_TICKS, "bar": bar}
        rp_zones[zone_id] = zone
        _refresh_zone_bar(zone)
        sender.sendMessage(u"§aRP-зона #%s «%s» создана, радиус %.0f блоков." % (zone_id, title, radius))
        sender.sendMessage(u"§7Игроки у границы получат приглашение. Завершить: §e/rpzone end")
        return True

    if sub in [u"join", u"accept", u"войти"] and len(args) > 1:
        zone = rp_zones.get(str(args[1]))
        if not zone or not _zone_contains(zone, sender.getLocation(), 6.0):
            sender.sendMessage(u"§cRP-зона не найдена или вы слишком далеко.")
            return True
        another = next((z for z in rp_zones.values()
                        if z["id"] != zone["id"] and player_uuid in z["members"]), None)
        if another:
            sender.sendMessage(u"§cСначала покиньте RP-зону #%s." % another["id"])
            return True
        zone["members"].add(player_uuid)
        _refresh_zone_bar(zone)
        sender.sendMessage(u"§aВы присоединились к RP-сцене «%s»." % zone["title"])
        for member_uuid in zone["members"]:
            if member_uuid == player_uuid:
                continue
            try:
                member = Bukkit.getPlayer(JUUID.fromString(member_uuid))
                if member and member.isOnline():
                    member.sendMessage(u"§d§l[RP] §f%s §7присоединился к сцене." % sender.getName())
            except Exception:
                pass
        return True

    if sub in [u"leave", u"quit", u"выйти"]:
        zone = next((z for z in rp_zones.values() if player_uuid in z["members"]), None)
        if not zone:
            sender.sendMessage(u"§cВы не участвуете в RP-сцене.")
            return True
        if zone["owner_uuid"] == player_uuid:
            sender.sendMessage(u"§cВладелец должен использовать /rpzone end.")
            return True
        zone["members"].discard(player_uuid)
        _refresh_zone_bar(zone)
        sender.sendMessage(u"§7Вы покинули RP-сцену.")
        return True

    if sub in [u"end", u"stop", u"закончить"]:
        zone = next((z for z in rp_zones.values() if z["owner_uuid"] == player_uuid), None)
        if not zone and sender.hasPermission("roleplay.zone.admin") and len(args) > 1:
            zone = rp_zones.get(str(args[1]))
        if not zone:
            sender.sendMessage(u"§cУ вас нет активной RP-зоны.")
            return True
        _end_rp_zone(zone["id"], u"RP-сцена завершена владельцем.")
        return True

    zone = _find_zone_for_player(sender, False)
    if zone:
        joined = u"да" if player_uuid in zone["members"] else u"нет"
        sender.sendMessage(u"§dRP-зона #%s §f«%s» §7| владелец: §f%s §7| участник: §f%s" %
                           (zone["id"], zone["title"], zone["owner_name"], joined))
        if player_uuid not in zone["members"]:
            sender.sendMessage(u"§7Присоединиться: §a/rpzone join %s" % zone["id"])
    else:
        sender.sendMessage(u"§7RP-зоны рядом нет. Создать: §e/rpzone create [радиус] [название]")
    return True


def on_rp_command_preprocess(event):
    player = event.getPlayer()
    if player.hasPermission("roleplay.zone.bypass"):
        return
    zone = _find_zone_for_player(player, True)
    if not zone:
        return
    raw = _norm(event.getMessage()).lstrip(u"/")
    command = raw.split(u" ", 1)[0].split(u":")[-1]
    if command in RP_BLOCKED_COMMANDS:
        event.setCancelled(True)
        player.sendMessage(u"§d§l[RP] §cЭта команда отключена на время RP-сцены. Сначала: §e/rpzone leave")


def on_rp_toggle_flight(event):
    player = event.getPlayer()
    if event.isFlying() and not player.hasPermission("roleplay.zone.bypass") and _find_zone_for_player(player, True):
        event.setCancelled(True)
        player.sendMessage(u"§d§l[RP] §cПолёт отключён внутри RP-сцены.")


def on_player_move(event):
    """Единственный listener PlayerMoveEvent в скрипте: отслеживает движение лежащих
    игроков, чтобы вовремя переносить фейковый барьер над головой.

    Реагируем на ЛЮБОЕ реальное перемещение (не только смену блока через
    hasChangedBlock()) - барьер над головой должен пересчитываться сразу, как только
    игрок физически сдвинулся, иначе при быстром ползании (особенно по диагонали или
    вверх/вниз по лестнице пещеры) видимое положение барьера начинает отставать от
    игрока на доли секунды, что и ощущалось как "барьеры не успевают". Дешёвая проверка
    hasChangedPosition() отсекает события без реального смещения (только поворот камеры)."""
    try:
        if not event.hasChangedPosition():
            return
    except Exception:
        pass

    player = event.getPlayer()
    u = uid(player)
    if u in laying_players:
        # event.getTo() - позиция, куда игрок переместится ПРЯМО СЕЙЧАС; используем именно
        # её, а не player.getLocation() (см. пояснение в _lay_update_barrier).
        target_loc = event.getTo()
        if target_loc is not None:
            _lay_update_barrier(player, target_loc)

    target_loc = event.getTo()
    if target_loc is not None:
        for zone in rp_zones.values():
            if u in zone["members"]:
                continue
            if _zone_contains(zone, target_loc, 3.0):
                invite_key = u + ":" + zone["id"]
                if now_tick() >= rp_invite_cooldowns.get(invite_key, 0):
                    rp_invite_cooldowns[invite_key] = now_tick() + RP_INVITE_COOLDOWN_TICKS
                    _send_zone_invite(player, zone)
                break


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
    seat_return_loc.pop(u, None)
    if stand is not None:
        try:
            stand.remove()
        except Exception:
            pass

    estand = esit_stands.pop(u, None)
    esit_return_loc.pop(u, None)
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
    listener_mgr.registerListener(on_rp_command_preprocess, PlayerCommandPreprocessEvent)
    listener_mgr.registerListener(on_rp_toggle_flight, PlayerToggleFlightEvent)
    try:
        # HIGHEST + ignoreCancelled - как в эталонной реализации GSit (Crawl.java),
        # чтобы обновление барьера произошло максимально близко к финальной позиции
        # игрока за тик и не срабатывало на уже отменённые другими плагинами перемещения.
        # ВАЖНО: PySpigot ожидает здесь настоящий Java-enum EventPriority, а не строку -
        # передача "HIGHEST" как str роняет скрипт с ClassCastException при загрузке
        # (несовместимость типов ловится JVM до входа в тело метода, поэтому обычный
        # Python try/except TypeError её не перехватывает).
        listener_mgr.registerListener(on_player_move, PlayerMoveEvent, EventPriority.HIGHEST, True)
    except Exception as ex:
        Bukkit.getLogger().warning("[rp_actions] PlayerMoveEvent priority fallback: " + str(ex))
        listener_mgr.registerListener(on_player_move, PlayerMoveEvent)

    _register_command(on_pee_command, "pee")
    _register_command(on_pee_command, "p")
    _register_command(on_spit_command, "spit")
    _register_command(on_sit_command, "sit")
    _register_command(on_esit_command, "esit")
    _register_command(on_lay_command, "lay")
    _register_command(on_rpzone_command, "rpzone")
    _register_command(on_rpzone_command, "rp")

    scheduler.runTaskLater(_pee_ticker, PEE_TICK_INTERVAL)
    scheduler.runTaskLater(_esit_rotation_ticker, ESIT_ROTATE_INTERVAL)
    scheduler.runTaskLater(_rp_zone_ticker, 20)

    Bukkit.getLogger().info("[rp_actions] RP action commands loaded: /pee (/p) /spit /sit /esit /lay")


def on_disable():
    for zone_id in list(rp_zones.keys()):
        _end_rp_zone(zone_id, u"RP-зона закрыта из-за перезагрузки скрипта.")
    rp_invite_cooldowns.clear()
    for u in list(seat_stands.keys()):
        stand = seat_stands.pop(u, None)
        seat_return_loc.pop(u, None)
        if stand is not None:
            try:
                stand.remove()
            except Exception:
                pass

    for u in list(esit_stands.keys()):
        stand = esit_stands.pop(u, None)
        esit_return_loc.pop(u, None)
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
            try:
                p.setPose(Pose.STANDING, False)
            except Exception:
                pass

    laying_players.clear()
    lay_barrier_loc.clear()
    peeing_players.clear()
    Bukkit.getLogger().info("[rp_actions] Disabled.")


def stop(script=None):
    # PySpigot 0.9.1 invokes stop() on unload; close bossbars and pose entities.
    on_disable()


on_enable()

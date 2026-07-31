# -*- coding: utf-8 -*-
"""
==============================================================================
  ADMIN — управление персонажами
  Paper 1.21 + PySpigot 0.9.1
------------------------------------------------------------------------------
  /admin give <персонаж> [аргументы...]
      Выдать комплект персонажа его ПРИВЯЗАННОМУ игроку.
      Если владельцев несколько — всем онлайн.
  /admin give <персонаж> to <ник> [аргументы...]
      Принудительно выдать конкретному игроку.
  /admin giveall
      Выдать всем ОНЛАЙН игрокам их персонажей автоматически (по привязке).
      Тест-аккаунты из GIVEALL_SKIP_NAMES (blueredtronce) — ПРОПУСКАЮТСЯ.
      Игрок без привязки — пропускается.
  /admin giveblue [ник]
      Выдать ВСЕ комплекты одному тест-аккаунту (по умолчанию blueredtronce).
      Работает только для ников из GIVEALL_SKIP_NAMES.
  /admin tier <ник> <тир>
      Улучшить/понизить тир персонажа игроку по нику (авто-детект персонажа
      из привязки). У Арчера меняются одновременно клинки И лук.
  /admin tier <персонаж> <ник> <тир>
      Явно указать, какого персонажа улучшать (если игрок привязан к нескольким).
  /admin list
      Показать привязки: персонаж -> ники владельцев.
  /admin who <ник>
      Показать, к каким персонажам привязан игрок.
==============================================================================
"""

import pyspigot as ps

cmd_mgr = ps.command_manager()

from java.lang import System
from java.util import HashMap

from org.bukkit import Bukkit
from org.bukkit.entity import Player


# =============================================================================
#  CONSTANTS
# =============================================================================

ADMIN_NAMES = set([u"blueredtronce"])

# Ники, которые НЕ должны получать автоматическую выдачу через /admin giveall
# и /admin give <char> (без явного "to <ник>"). Это тестовые аккаунты админов,
# которые могут владеть многими персонажами формально, но не должны получать
# всё разом при массовой выдаче — иначе инвентарь забивается 18 комплектами.
# Отдельная команда /admin giveblue выдаёт всё этим аккаунтам вручную.
GIVEALL_SKIP_NAMES = set([u"blueredtronce"])

# =============================================================================
#  TEST MODE
# =============================================================================
# По умолчанию режим ВКЛЮЧЁН (для отладки).
# Флаг живёт в System.getProperties() под ключом "arena.test_mode".
# Значения: "1" (включен) / "0" (выключен).
# Скрипты персонажей могут читать его функцией is_test_mode() ниже — она
# опубликована в JVM-глобальный реестр для внешнего доступа.

_TEST_MODE_KEY = "arena.test_mode"

def is_test_mode():
    v = System.getProperties().get(_TEST_MODE_KEY)
    if v is None:
        # По умолчанию — ВКЛЮЧЕН.
        System.getProperties().put(_TEST_MODE_KEY, "1")
        return True
    return str(v) == "1"

def set_test_mode(enabled):
    System.getProperties().put(_TEST_MODE_KEY, "1" if enabled else "0")

# Инициализация значения по умолчанию.
is_test_mode()


def _is_admin(sender):
    if not isinstance(sender, Player):
        return True   # консоль
    if sender.getName().lower() in ADMIN_NAMES:
        return True
    if sender.isOp():
        return True
    return False


# =============================================================================
#  REGISTRIES ACCESS
# =============================================================================

def _get_kits_registry():
    return System.getProperties().get("pyspigot.character_kits")

def _get_owners_registry():
    return System.getProperties().get("character_owners")

def _get_tier_setters_registry():
    return System.getProperties().get("character_tier_setters")

def _get_reset_functions_registry():
    return System.getProperties().get("character_reset_functions")


def _all_characters():
    kits = _get_kits_registry()
    if kits is None:
        return []
    result = []
    it = kits.keySet().iterator()
    while it.hasNext():
        result.append(it.next())
    return sorted(result)


def _get_owners_of(char_name):
    owners = _get_owners_registry()
    if owners is None:
        return []
    lst = owners.get(char_name)
    if lst is None:
        return []
    result = []
    it = lst.iterator() if hasattr(lst, "iterator") else None
    if it is not None:
        while it.hasNext():
            result.append(str(it.next()).lower())
    else:
        for x in lst:
            result.append(str(x).lower())
    return result


def _find_chars_by_nick(nick):
    """Список персонажей, к которым привязан данный ник."""
    owners = _get_owners_registry()
    if owners is None:
        return []
    nick_l = nick.lower()
    result = []
    it = owners.entrySet().iterator()
    while it.hasNext():
        e = it.next()
        char = e.getKey()
        lst = e.getValue()
        for x in lst:
            if str(x).lower() == nick_l:
                result.append(char)
                break
    return result


def _kit_fn_of(char_name):
    kits = _get_kits_registry()
    if kits is None:
        return None
    entry = kits.get(char_name)
    if entry is None:
        return None
    try:
        return entry[0]
    except Exception:
        return entry


def _tier_fn_of(char_name):
    reg = _get_tier_setters_registry()
    if reg is None:
        return None
    return reg.get(char_name)


# =============================================================================
#  HELPERS
# =============================================================================

def _give_to_player(sender, target_player, char_name, extra_args):
    fn = _kit_fn_of(char_name)
    if fn is None:
        sender.sendMessage(u"§cПерсонаж не зарегистрирован: §f" + char_name)
        return False
    try:
        fn(target_player, list(extra_args))
    except Exception as ex:
        sender.sendMessage(u"§cОшибка выдачи: §f" + str(ex))
        Bukkit.getLogger().warning("[admin] give '" + char_name + "' -> " +
                                    target_player.getName() + ": " + str(ex))
        return False
    return True


def _set_tier_for(sender, target_player, char_name, tier):
    fn = _tier_fn_of(char_name)
    if fn is None:
        sender.sendMessage(u"§cПерсонаж §f" + char_name +
                           u" §cне поддерживает смену тира.")
        return False
    try:
        ok = fn(target_player, tier)
    except Exception as ex:
        sender.sendMessage(u"§cОшибка смены тира: §f" + str(ex))
        Bukkit.getLogger().warning("[admin] tier '" + char_name + "' -> " +
                                    target_player.getName() + ": " + str(ex))
        return False
    if not ok:
        sender.sendMessage(u"§cНе удалось выставить тир §f" + str(tier) +
                           u" §cдля §f" + char_name + u"§c.")
        return False
    return True


# =============================================================================
#  COMMAND
# =============================================================================

def cmd_admin(sender, label, args):
    if not _is_admin(sender):
        sender.sendMessage(u"§cНет доступа.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§7Использование:")
        sender.sendMessage(u"  §f/admin give <персонаж> [args] §8— выдать привязанным")
        sender.sendMessage(u"  §f/admin give <персонаж> to <ник> [args] §8— выдать конкретному")
        sender.sendMessage(u"  §f/admin giveall §8— всем онлайн выдать их персонажей (без тест-аккаунтов)")
        sender.sendMessage(u"  §f/admin giveblue [ник] §8— выдать ВСЕ комплекты тест-аккаунту")
        sender.sendMessage(u"  §f/admin tier <ник> <n> §8— поднять/сменить тир игрока")
        sender.sendMessage(u"  §f/admin tier <персонаж> <ник> <n> §8— явное указание персонажа")
        sender.sendMessage(u"  §f/admin resethp [ник] §8— сброс max-HP + полное восстановление")
        sender.sendMessage(u"  §f/admin testmode <on|off|status> §8— переключить тестовый режим")
        sender.sendMessage(u"  §f/admin list §8— привязки")
        sender.sendMessage(u"  §f/admin who <ник> §8— к чему привязан игрок")
        return True

    sub = args[0].lower()

    # -----------------------------------------------------------------------
    if sub == u"list":
        chars = _all_characters()
        if not chars:
            sender.sendMessage(u"§7Персонажи ещё не загружены.")
            return True
        sender.sendMessage(u"§7Привязки персонажей:")
        for c in chars:
            owners = _get_owners_of(c)
            has_tier = _tier_fn_of(c) is not None
            tier_str = u" §8[тиры]" if has_tier else u""
            if not owners:
                sender.sendMessage(u"  §f- " + c + u" §8→ §cне указано" + tier_str)
            else:
                sender.sendMessage(u"  §f- " + c + u" §8→ §f" + u", ".join(owners) + tier_str)
        return True

    # -----------------------------------------------------------------------
    if sub == u"who":
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/admin who <ник>")
            return True
        nick = args[1]
        chars = _find_chars_by_nick(nick)
        if not chars:
            sender.sendMessage(u"§7Игрок §f" + nick + u" §7ни к кому не привязан.")
        else:
            sender.sendMessage(u"§7Игрок §f" + nick + u" §7привязан к:")
            for c in chars:
                sender.sendMessage(u"  §f- " + c)
        return True

    # -----------------------------------------------------------------------
    if sub == u"giveall":
        chars = _all_characters()
        given = []
        skipped_admin = set()
        for c in chars:
            owners = _get_owners_of(c)
            for nick in owners:
                # Пропускаем тест-аккаунты (blueredtronce и т.п.) — для них
                # есть отдельная команда /admin giveblue.
                if nick.lower() in GIVEALL_SKIP_NAMES:
                    tp = Bukkit.getPlayerExact(nick)
                    if tp is not None and tp.isOnline():
                        skipped_admin.add(tp.getName())
                    continue
                tp = Bukkit.getPlayerExact(nick)
                if tp is None or not tp.isOnline():
                    continue
                if _give_to_player(sender, tp, c, []):
                    given.append(tp.getName() + u" (" + c + u")")
        if given:
            sender.sendMessage(u"§a✓ Выдано онлайн: §f" + u", ".join(given))
        else:
            sender.sendMessage(u"§7Нет онлайн-игроков с привязкой к персонажам.")
        if skipped_admin:
            sender.sendMessage(u"§7Пропущены тест-аккаунты: §f" +
                               u", ".join(sorted(skipped_admin)) +
                               u" §8(используй §f/admin giveblue§8)")
        return True

    # -----------------------------------------------------------------------
    if sub == u"giveblue":
        # Выдать ВСЕ комплекты персонажей одному тест-аккаунту.
        # По умолчанию — самому blueredtronce, либо указанному нику из
        # списка GIVEALL_SKIP_NAMES.
        target_nick = args[1] if len(args) >= 2 else u"blueredtronce"
        if target_nick.lower() not in GIVEALL_SKIP_NAMES:
            sender.sendMessage(u"§cЭта команда только для тест-аккаунтов: §f" +
                               u", ".join(sorted(GIVEALL_SKIP_NAMES)))
            return True
        tp = Bukkit.getPlayerExact(target_nick)
        if tp is None or not tp.isOnline():
            sender.sendMessage(u"§cИгрок не в сети: §f" + target_nick)
            return True

        chars = _all_characters()
        if not chars:
            sender.sendMessage(u"§7Нет зарегистрированных персонажей.")
            return True

        given = []
        failed = []
        for c in chars:
            if _give_to_player(sender, tp, c, []):
                given.append(c)
            else:
                failed.append(c)

        if given:
            sender.sendMessage(u"§a✓ §f" + tp.getName() +
                               u" §aполучил все комплекты (§f" + str(len(given)) +
                               u"§a): §7" + u", ".join(given))
        if failed:
            sender.sendMessage(u"§eНе удалось выдать: §f" + u", ".join(failed))
        return True

    # -----------------------------------------------------------------------
    if sub == u"give":
        if len(args) < 2:
            sender.sendMessage(u"§7Использование: §f/admin give <персонаж> [args]")
            sender.sendMessage(u"§7Доступно: §f" + u", ".join(_all_characters()))
            return True

        char_name = args[1].lower()
        if char_name not in _all_characters():
            sender.sendMessage(u"§cНеизвестный персонаж: §f" + char_name)
            return True

        # /admin give <char> to <nick> [args]
        if len(args) >= 4 and args[2].lower() == u"to":
            target_nick = args[3]
            extra = list(args[4:])
            tp = Bukkit.getPlayerExact(target_nick)
            if tp is None or not tp.isOnline():
                sender.sendMessage(u"§cИгрок не в сети: §f" + target_nick)
                return True
            if _give_to_player(sender, tp, char_name, extra):
                sender.sendMessage(u"§a✓ '" + char_name + u"' выдан §f" +
                                    tp.getName() + u"§a.")
            return True

        extra = list(args[2:])
        owners = _get_owners_of(char_name)
        if not owners:
            sender.sendMessage(u"§cПерсонаж §f" + char_name +
                               u" §cне имеет привязанных ников.")
            return True

        given = []
        offline = []
        for nick in owners:
            tp = Bukkit.getPlayerExact(nick)
            if tp is None or not tp.isOnline():
                offline.append(nick)
                continue
            if _give_to_player(sender, tp, char_name, extra):
                given.append(tp.getName())

        if given:
            sender.sendMessage(u"§a✓ '" + char_name + u"' выдан: §f" + u", ".join(given))
        if offline:
            sender.sendMessage(u"§8Оффлайн (пропущены): §7" + u", ".join(offline))
        if not given and not offline:
            sender.sendMessage(u"§cНикого из владельцев нет в сети.")
        return True

    # -----------------------------------------------------------------------
    # -----------------------------------------------------------------------
    # -----------------------------------------------------------------------
    if sub in (u"testmode", u"test"):
        # /admin testmode [on|off|status]
        if len(args) >= 2:
            arg = args[1].lower()
            if arg in (u"on", u"вкл", u"1", u"true"):
                set_test_mode(True)
                sender.sendMessage(u"§a✓ Тестовый режим §fВКЛЮЧЁН§a.")
            elif arg in (u"off", u"выкл", u"0", u"false"):
                set_test_mode(False)
                sender.sendMessage(u"§c✓ Тестовый режим §fВЫКЛЮЧЕН§c.")
            elif arg in (u"status", u"состояние"):
                s = u"§aВКЛЮЧЁН" if is_test_mode() else u"§cВЫКЛЮЧЕН"
                sender.sendMessage(u"§7Тестовый режим: " + s)
            else:
                sender.sendMessage(u"§7Использование: §f/admin testmode <on|off|status>")
        else:
            s = u"§aВКЛЮЧЁН" if is_test_mode() else u"§cВЫКЛЮЧЕН"
            sender.sendMessage(u"§7Тестовый режим: " + s)
            sender.sendMessage(u"§7Использование: §f/admin testmode <on|off>")
        return True

    # -----------------------------------------------------------------------
    if sub in (u"resethp", u"resetstate", u"reset", u"heal", u"fixhp"):
        # /admin resethp [ник]  — если без ника, применяем к отправителю
        if len(args) >= 2:
            target_nick = args[1]
            tp = Bukkit.getPlayerExact(target_nick)
        else:
            if not isinstance(sender, Player):
                sender.sendMessage(u"§7Использование: §f/admin resethp <ник>")
                return True
            tp = sender

        if tp is None or not tp.isOnline():
            sender.sendMessage(u"§cИгрок не в сети.")
            return True

        # Вызываем reset_state у КАЖДОГО зарегистрированного персонажа —
        # так почистятся модификаторы max-HP всех скриптов сразу.
        reset_reg = _get_reset_functions_registry()
        cleaned = []
        if reset_reg is not None:
            it = reset_reg.entrySet().iterator()
            while it.hasNext():
                e = it.next()
                char = e.getKey()
                fn = e.getValue()
                try:
                    fn(tp)
                    cleaned.append(char)
                except Exception as ex:
                    sender.sendMessage(u"§8Не удалось сбросить §f" + char + u"§8: " + str(ex))

        # На всякий случай — жёстко чистим ВСЕ модификаторы max-HP,
        # даже если какие-то скрипты не публиковали reset.
        try:
            from org.bukkit.attribute import Attribute
            attr = tp.getAttribute(Attribute.GENERIC_MAX_HEALTH)
            if attr is not None:
                for m in list(attr.getModifiers()):
                    try:
                        attr.removeModifier(m)
                    except Exception:
                        pass
        except Exception as ex:
            sender.sendMessage(u"§cОшибка чистки max-HP: §f" + str(ex))

        # Полное восстановление здоровья + сытости.
        try:
            max_hp = tp.getMaxHealth()   # После сброса = 20.0
            tp.setHealth(max_hp)
            tp.setFoodLevel(20)
            tp.setSaturation(20.0)
            tp.setFireTicks(0)
            # Снимаем все негативные потион-эффекты.
            for eff in list(tp.getActivePotionEffects()):
                try:
                    tp.removePotionEffect(eff.getType())
                except Exception:
                    pass
        except Exception as ex:
            sender.sendMessage(u"§cОшибка восстановления: §f" + str(ex))

        sender.sendMessage(u"§a✓ Игрок §f" + tp.getName() +
                           u" §aполностью восстановлен. §7Очищены персонажи: §f" +
                           (u", ".join(cleaned) if cleaned else u"—"))
        if tp != sender:
            tp.sendMessage(u"§a✓ Твоё состояние сброшено администратором.")
        return True

    # -----------------------------------------------------------------------
    if sub == u"tier":
        # Форматы:
        #   /admin tier <ник> <n>              — auto-detect по привязке
        #   /admin tier <персонаж> <ник> <n>   — явное указание
        # Доступно ТОЛЬКО в тестовом режиме — иначе персонажи получают тиры
        # честно, через прогресс/квесты.
        if not is_test_mode():
            sender.sendMessage(u"§cТестовый режим выключен. §7Игроки должны получать тиры честно.")
            sender.sendMessage(u"§7Включи: §f/admin testmode on")
            return True

        if len(args) < 3:
            sender.sendMessage(u"§7Использование:")
            sender.sendMessage(u"  §f/admin tier <ник> <тир>")
            sender.sendMessage(u"  §f/admin tier <персонаж> <ник> <тир>")
            return True

        # Пытаемся понять, какой формат.
        char_name = None
        nick = None
        tier_str = None
        if len(args) >= 4:
            # Явный формат: args[1] должен быть именем персонажа.
            first = args[1].lower()
            if first in _all_characters():
                char_name = first
                nick = args[2]
                tier_str = args[3]
        if char_name is None:
            # Авто-формат.
            nick = args[1]
            tier_str = args[2]

        try:
            tier = int(tier_str)
        except ValueError:
            sender.sendMessage(u"§cТир — число.")
            return True

        tp = Bukkit.getPlayerExact(nick)
        if tp is None or not tp.isOnline():
            sender.sendMessage(u"§cИгрок не в сети: §f" + nick)
            return True

        if char_name is None:
            # Auto-detect: смотрим, к кому привязан этот ник.
            candidates = _find_chars_by_nick(nick)
            # Оставляем только тех, у кого есть set_tier.
            candidates = [c for c in candidates if _tier_fn_of(c) is not None]
            if not candidates:
                sender.sendMessage(u"§cИгрок §f" + nick +
                                   u" §cне привязан к персонажу с тирами.")
                sender.sendMessage(u"§7Укажи явно: §f/admin tier <персонаж> " +
                                   nick + u" " + str(tier))
                return True
            if len(candidates) > 1:
                sender.sendMessage(u"§7Игрок §f" + nick +
                                   u" §7привязан к нескольким: §f" +
                                   u", ".join(candidates))
                sender.sendMessage(u"§7Уточни: §f/admin tier <персонаж> " +
                                   nick + u" " + str(tier))
                return True
            char_name = candidates[0]

        if _set_tier_for(sender, tp, char_name, tier):
            sender.sendMessage(u"§a✓ Тир §f" + str(tier) + u" §aвыставлен для §f" +
                                tp.getName() + u" §7(персонаж §f" + char_name + u"§7).")
        return True

    # -----------------------------------------------------------------------
    sender.sendMessage(u"§cНеизвестная подкоманда: §f" + sub)
    return True


# =============================================================================
#  REGISTRATION
# =============================================================================

cmd_mgr.registerCommand(cmd_admin, "admin")

Bukkit.getLogger().info("[admin] Admin controller loaded. Command: /admin")

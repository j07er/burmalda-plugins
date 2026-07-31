# -*- coding: utf-8 -*-
"""
death_messages.py — Перехватчик сообщений о смерти + лог координат.

1) Перехват translate-keys.
   Когда скрипты героев наносят кастомный урон через
   DamageSource.builder(DamageType.MAGIC).withDirectEntity(attacker).build(),
   Minecraft генерирует translate-key вида "death.attack.magic.item".
   Клиент не всегда его переводит — этот скрипт заменяет сырые ключи
   на нормальные русские сообщения.

2) Логирование смертей.
   Каждая смерть пишется в файл plugins/PySpigot/scripts/data/deaths.log
   с координатами, миром, ником убийцы (если есть) и причиной.

Paper 1.21 + PySpigot 0.9.1.
"""

import pyspigot as ps
listener_mgr = ps.listener_manager()

import os
import io
import time

from java.lang import System
from org.bukkit import Bukkit
from org.bukkit.entity import Player
from org.bukkit.event.entity import PlayerDeathEvent


# ---------------------------------------------------------------------------
# Пути к логу
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join("plugins", "PySpigot", "scripts", "data")
DEATH_LOG_PATH = os.path.join(DATA_DIR, "deaths.log")


def _ensure_data_dir():
    try:
        os.makedirs(DATA_DIR)
    except Exception:
        pass


def _write_death_log(line_unicode):
    """Дописывает строку в файл в UTF-8."""
    try:
        _ensure_data_dir()
        f = io.open(DEATH_LOG_PATH, "a", encoding="utf-8")
        try:
            if isinstance(line_unicode, str):
                line_unicode = line_unicode.decode("utf-8", "replace")
            f.write(line_unicode)
            if not line_unicode.endswith(u"\n"):
                f.write(u"\n")
        finally:
            f.close()
    except Exception as ex:
        try:
            Bukkit.getLogger().warning("[death_messages] log write failed: " + str(ex))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Карта: translate-key -> шаблон вывода.
# {0} = имя жертвы, {1} = имя атакующего (или "неизвестно").
# ---------------------------------------------------------------------------
DEATH_MESSAGES = {
    # Magic (наши способности deal_pure_damage).
    u"death.attack.magic":           u"§7{0} §fпал от магии §7{1}",
    u"death.attack.magic.item":      u"§7{0} §fпал от магии §7{1}",
    u"death.attack.magic.player":    u"§7{0} §fпал от магии §7{1}",

    # Sonic Boom / Warden.
    u"death.attack.sonic_boom":      u"§7{0} §fразорвало звуком §7{1}",
    u"death.attack.sonic_boom.item": u"§7{0} §fразорвало звуком §7{1}",

    # Indirect magic (снаряды с magic-типом).
    u"death.attack.indirectMagic":       u"§7{0} §fповерг снаряд §7{1}",
    u"death.attack.indirectMagic.item":  u"§7{0} §fповерг снаряд §7{1}",

    # Wither.
    u"death.attack.wither":          u"§7{0} §fувял §7{1}",
    u"death.attack.wither.player":   u"§7{0} §fувял по вине §7{1}",

    # Thorns.
    u"death.attack.thorns":          u"§7{0} §fнаколол себя об шипы §7{1}",
    u"death.attack.thorns.item":     u"§7{0} §fнаколол себя об шипы §7{1}",

    # Sweet Berry Bush.
    u"death.attack.sweetBerryBush":  u"§7{0} §fзапутался в сладких ягодах",
    u"death.attack.sweetBerryBush.player": u"§7{0} §fзапутался в сладких ягодах",

    # Cactus.
    u"death.attack.cactus":          u"§7{0} §fнаколот кактусом",
    u"death.attack.cactus.player":   u"§7{0} §fнаколот кактусом §7{1}",
}


def _looks_like_translate_key(msg):
    """True если строка похожа на сырой translate-ключ (не переведённый)."""
    if not msg:
        return False
    if u" " in msg:
        return False
    return msg.startswith(u"death.")


def _log_death(victim, event, resolved_msg):
    """Пишет одну строку в deaths.log."""
    try:
        loc = victim.getLocation()
        world_name = loc.getWorld().getName()
        x = loc.getX()
        y = loc.getY()
        z = loc.getZ()

        killer_name = u"-"
        try:
            killer = victim.getKiller()
            if killer is not None:
                killer_name = killer.getName()
        except Exception:
            pass

        # Причина смерти — берём из последнего damage-эвента жертвы.
        cause = u"-"
        try:
            ldc = victim.getLastDamageCause()
            if ldc is not None:
                cause = unicode(ldc.getCause().name())
        except Exception:
            pass

        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        # Формат: TSV — легко парсить, читаемо глазами.
        # ts | victim | world | x | y | z | killer | cause | display_msg
        parts = [
            ts,
            victim.getName(),
            world_name,
            u"%.2f" % x,
            u"%.2f" % y,
            u"%.2f" % z,
            killer_name,
            cause,
            (resolved_msg or u"").replace(u"\t", u" ").replace(u"\n", u" "),
        ]
        line = u"\t".join(parts)
        _write_death_log(line)
    except Exception as ex:
        try:
            Bukkit.getLogger().warning("[death_messages] log failed: " + str(ex))
        except Exception:
            pass


def on_player_death(event):
    victim = None
    try:
        victim = event.getEntity()
        if not isinstance(victim, Player):
            return

        # ---- 1. Подмена translate-ключа ----
        raw = event.getDeathMessage()
        display_msg = u""
        if raw is not None:
            try:
                msg = unicode(raw)
            except Exception:
                msg = raw
            display_msg = msg

            if _looks_like_translate_key(msg):
                victim_name = victim.getName()
                killer_name = u"неизвестно"
                try:
                    killer = victim.getKiller()
                    if killer is not None:
                        killer_name = killer.getName()
                except Exception:
                    pass

                template = DEATH_MESSAGES.get(msg)
                if template is None:
                    template = u"§7{0} §fпогиб (§8" + msg + u"§f) от §7{1}"

                final = template.replace(u"{0}", victim_name).replace(u"{1}", killer_name)
                event.setDeathMessage(final)
                display_msg = final

        # ---- 2. Лог смерти в файл ----
        _log_death(victim, event, display_msg)

    except Exception as ex:
        try:
            Bukkit.getLogger().warning("[death_messages] on_player_death: " + str(ex))
        except Exception:
            pass


listener_mgr.registerListener(on_player_death, PlayerDeathEvent)

_ensure_data_dir()
Bukkit.getLogger().info("[death_messages] Loaded. Death log: " + DEATH_LOG_PATH)

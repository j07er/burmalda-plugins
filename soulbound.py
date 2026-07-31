# -*- coding: utf-8 -*-
"""
==============================================================================
  SOULBOUND — Кастомные предметы не выпадают при смерти
  Paper 1.21.11 + PySpigot 0.9.1
------------------------------------------------------------------------------
  Причина: PlayerDropItemEvent (Q-key) уже блокируется в каждом скрипте героя.
  Но при смерти игрока весь инвентарь выпадает через PlayerDeathEvent —
  и его никто не фильтровал. Теперь фильтруем здесь.

  Что делает:
    * При смерти любого игрока проходит по event.getDrops(), удаляет оттуда
      кастомные предметы (по PDC-неймспейсам героев) и переносит их в
      event.getItemsToKeep() — Paper API, предметы остаются в инвентаре
      после респауна.
    * Если getItemsToKeep недоступен (не Paper) — fallback: сохраняем
      предметы во внутренний dict и восстанавливаем на PlayerRespawnEvent.
    * PlayerDropItemEvent-фильтр как второй слой защиты (если какой-то
      скрипт героя забудет свой on_drop).

  Команды:
    /soulbound              — показать список защищённых неймспейсов
    /soulbound reload       — перечитать неймспейсы из скриптов героев
    /soulbound add <ns>     — временно добавить неймспейс
    /soulbound remove <ns>  — временно убрать
    /soulbound check <ник>  — показать сколько кастомных предметов в инвентаре
==============================================================================
"""

import pyspigot as ps

cmd_mgr      = ps.command_manager()
listener_mgr = ps.listener_manager()
scheduler    = ps.scheduler

from java.lang import System
from java.util import ArrayList

from org.bukkit import Bukkit, Material
from org.bukkit.entity import Player
from org.bukkit.event.entity import PlayerDeathEvent
from org.bukkit.event.player import (
    PlayerRespawnEvent, PlayerDropItemEvent, PlayerJoinEvent
)


# ============================================================================
#  CONFIG
# ============================================================================

ADMIN_NAMES = set([u"blueredtronce"])

# Неймспейсы всех кастомных предметов проекта. Любой предмет с PDC-ключом
# из этих неймспейсов считается кастомным и не выпадает при смерти.
#
# ПРАВИЛО: когда добавляешь нового героя, добавь его неймспейс сюда.
CUSTOM_NAMESPACES = set([
    "kris",
    "doomlord",
    "demiurg",
    "spideragent",
    "archer",
    "architect",
    "mihawk",
    "griblet",
    "barsik",
    "shanks",
    "geto",
    "poseidon",
    "warden",
    "dragon",
    "amonra",
    "steelgorn",
    "wendy",
    # Инфраструктура — тоже не должна выпадать.
    "dummy",           # маркеры тренировочных манекенов (на всякий случай)
    "questtracker",    # если появятся сохраняемые предметы
])


# ============================================================================
#  UTILS
# ============================================================================

def uid(e):
    return e.getUniqueId().toString()

def _is_admin(sender):
    if not isinstance(sender, Player): return True
    return sender.getName().lower() in ADMIN_NAMES or sender.isOp()


def is_custom_item(item):
    """True если у предмета есть хотя бы один PDC-ключ из CUSTOM_NAMESPACES."""
    if item is None: return False
    try:
        if item.getType() == Material.AIR: return False
    except Exception:
        return False
    try:
        m = item.getItemMeta()
        if m is None: return False
        pdc = m.getPersistentDataContainer()
        for k in pdc.getKeys():
            try:
                ns = k.getNamespace()
                if ns in CUSTOM_NAMESPACES:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


# ============================================================================
#  FALLBACK STORAGE (если Paper.getItemsToKeep недоступен)
# ============================================================================

# uid(player) -> [ItemStack, ...] — предметы, которые надо вернуть при респауне.
_pending_restore = {}


def _try_add_to_keep(event, item):
    """Пытается использовать Paper API getItemsToKeep. Возвращает True если получилось."""
    try:
        keep_list = event.getItemsToKeep()
        if keep_list is not None:
            keep_list.add(item)
            return True
    except Exception:
        pass
    return False


# ============================================================================
#  EVENT HANDLERS
# ============================================================================

def on_death(event):
    """Главный хук: убираем кастомные предметы из drops."""
    try:
        victim = event.getEntity()
        if not isinstance(victim, Player): return

        drops = event.getDrops()
        if drops is None or drops.isEmpty(): return

        # Собираем кастомные предметы и убираем их из drops.
        kept = []
        # Копируем список, чтобы не модифицировать коллекцию во время итерации.
        drops_copy = list(drops)
        for drop in drops_copy:
            if is_custom_item(drop):
                kept.append(drop)
                try:
                    drops.remove(drop)
                except Exception:
                    pass

        if not kept:
            return

        # Пытаемся использовать Paper.getItemsToKeep — тогда сервер сам вернёт
        # предметы в инвентарь на респауне.
        api_used = False
        for it in kept:
            if _try_add_to_keep(event, it):
                api_used = True
            else:
                api_used = False
                break

        # Fallback: сохраняем и вернём на PlayerRespawnEvent.
        if not api_used:
            _pending_restore[uid(victim)] = list(kept)

        # Инфо в чат админам.
        info = (u"§8[Soulbound] §7Сохранено §f" + str(len(kept)) +
                u" §7кастомных предметов при смерти §f" + victim.getName())
        for adm in Bukkit.getOnlinePlayers():
            if _is_admin(adm) and not adm.equals(victim):
                adm.sendMessage(info)
    except Exception as ex:
        Bukkit.getLogger().warning("[soulbound] on_death: " + str(ex))


def on_respawn(event):
    """Fallback-восстановление если Paper API недоступен."""
    try:
        p = event.getPlayer()
        u = uid(p)
        items = _pending_restore.pop(u, None)
        if not items: return

        def _give_back():
            try:
                if not p.isOnline(): return
                inv = p.getInventory()
                for it in items:
                    try:
                        left = inv.addItem(it)
                        # Если инвентарь переполнен — бросим у ног.
                        if left is not None and not left.isEmpty():
                            for remain in left.values():
                                p.getWorld().dropItemNaturally(p.getLocation(), remain)
                    except Exception:
                        pass
                p.sendMessage(u"§a✓ §7Кастомные предметы возвращены.")
            except Exception as ex:
                Bukkit.getLogger().warning("[soulbound] restore: " + str(ex))

        # Респаун через тик — инвентарь ещё не готов.
        scheduler.runTaskLater(_give_back, 2)
    except Exception:
        pass


def on_drop(event):
    """Второй слой защиты: если игрок Q-key дропает кастомный предмет,
    у которого забыли повесить свой хук в скрипте героя — блокируем."""
    try:
        it = event.getItemDrop().getItemStack()
        if is_custom_item(it):
            # НЕ отменяем, если предмет уже отменяли где-то ещё
            # (event уже cancelled — не трогаем).
            if event.isCancelled():
                return
            event.setCancelled(True)
            try:
                event.getPlayer().sendMessage(u"§cКастомный предмет нельзя выбросить.")
            except Exception:
                pass
    except Exception:
        pass


def on_join(event):
    """Восстановление, если игрок вышел до респауна с pending items."""
    try:
        p = event.getPlayer()
        u = uid(p)
        items = _pending_restore.get(u)
        if items:
            def _give_back():
                try:
                    if not p.isOnline(): return
                    inv = p.getInventory()
                    for it in items:
                        try: inv.addItem(it)
                        except Exception: pass
                    _pending_restore.pop(u, None)
                    p.sendMessage(u"§a✓ §7Кастомные предметы возвращены.")
                except Exception:
                    pass
            scheduler.runTaskLater(_give_back, 10)
    except Exception:
        pass


# ============================================================================
#  COMMAND
# ============================================================================

def cmd_soulbound(sender, label, args):
    if not _is_admin(sender):
        sender.sendMessage(u"§cДоступ только для админов.")
        return True

    if len(args) == 0:
        sender.sendMessage(u"§8§m----- §r§b§lSoulbound§r §8§m-----")
        sender.sendMessage(u"§7Защищённых неймспейсов: §f" + str(len(CUSTOM_NAMESPACES)))
        # Показываем в 3 колонки.
        sorted_ns = sorted(CUSTOM_NAMESPACES)
        for i in range(0, len(sorted_ns), 3):
            chunk = sorted_ns[i:i+3]
            line = u"  " + u"  ".join([u"§f" + n for n in chunk])
            sender.sendMessage(line)
        sender.sendMessage(u"§7Команды:")
        sender.sendMessage(u"  §f/soulbound add <ns>    §8— добавить неймспейс")
        sender.sendMessage(u"  §f/soulbound remove <ns> §8— убрать")
        sender.sendMessage(u"  §f/soulbound check <ник> §8— посчитать кастомных предметов")
        return True

    sub = args[0].lower()

    if sub == u"add":
        if len(args) < 2:
            sender.sendMessage(u"§7/soulbound add <namespace>")
            return True
        ns = args[1].lower()
        CUSTOM_NAMESPACES.add(ns)
        sender.sendMessage(u"§a✓ Неймспейс §f" + ns + u" §aдобавлен.")
        return True

    if sub == u"remove":
        if len(args) < 2:
            sender.sendMessage(u"§7/soulbound remove <namespace>")
            return True
        ns = args[1].lower()
        if ns in CUSTOM_NAMESPACES:
            CUSTOM_NAMESPACES.discard(ns)
            sender.sendMessage(u"§a✓ Неймспейс §f" + ns + u" §aубран.")
        else:
            sender.sendMessage(u"§7Неймспейса §f" + ns + u" §7нет в списке.")
        return True

    if sub == u"check":
        if len(args) < 2:
            sender.sendMessage(u"§7/soulbound check <ник>")
            return True
        target = Bukkit.getPlayerExact(args[1])
        if target is None or not target.isOnline():
            sender.sendMessage(u"§cИгрок не онлайн.")
            return True
        inv = target.getInventory()
        found = []
        for i in range(inv.getSize()):
            it = inv.getItem(i)
            if is_custom_item(it):
                found.append((i, it))
        sender.sendMessage(u"§b§l" + target.getName() + u"§r §7— кастомных предметов: §f" +
                           str(len(found)))
        for slot, it in found[:20]:
            name = it.getType().name()
            try:
                m = it.getItemMeta()
                if m is not None and m.hasDisplayName():
                    name = m.getDisplayName()
            except Exception: pass
            sender.sendMessage(u"  §8slot §f" + str(slot) + u"§8: §7" + name)
        return True

    sender.sendMessage(u"§cНеизвестная подкоманда: §f" + sub)
    return True


# ============================================================================
#  REGISTRATION
# ============================================================================

cmd_mgr.registerCommand(cmd_soulbound, "soulbound")

listener_mgr.registerListener(on_death,   PlayerDeathEvent)
listener_mgr.registerListener(on_respawn, PlayerRespawnEvent)
listener_mgr.registerListener(on_drop,    PlayerDropItemEvent)
listener_mgr.registerListener(on_join,    PlayerJoinEvent)

# Публикуем API — другие скрипты могут добавлять неймспейсы динамически.
try:
    System.getProperties().put("soulbound.namespaces", CUSTOM_NAMESPACES)
    System.getProperties().put("soulbound.is_custom", is_custom_item)
except Exception:
    pass

Bukkit.getLogger().info("[soulbound] Soulbound loaded. Command: /soulbound. "
                        "Protected " + str(len(CUSTOM_NAMESPACES)) + " namespaces.")

# -*- coding: utf-8 -*-
"""
SmartY Bounty for PySpigot / Paper 1.21.

Commands:
  /bounty <player> <amount>
  /bounty <player>
  /bountylist
  /bountyadmin <reload|clear|set|add>
"""

import json
import os
import re
import shutil
import sys
import time

try:
    unicode
except NameError:
    unicode = str

try:
    if hasattr(sys, "setdefaultencoding"):
        reload(sys)
        sys.setdefaultencoding("utf-8")
except Exception:
    pass

try:
    from org.bukkit import Bukkit, ChatColor, Material, Sound
    from org.bukkit.command import Command, TabCompleter
    from org.bukkit.entity import Player
    from org.bukkit.event import EventPriority, HandlerList, Listener
    from org.bukkit.event.entity import PlayerDeathEvent
    from org.bukkit.event.inventory import InventoryClickEvent, InventoryCloseEvent
    from org.bukkit.event.player import PlayerJoinEvent
    from org.bukkit.inventory import ItemStack
    from org.bukkit.plugin import EventExecutor
    BUKKIT_AVAILABLE = True
except ImportError:
    Bukkit = None
    ChatColor = None
    Sound = None
    Material = None
    Command = object
    TabCompleter = object
    Player = object
    EventPriority = None
    HandlerList = None
    Listener = object
    PlayerDeathEvent = None
    InventoryClickEvent = None
    InventoryCloseEvent = None
    PlayerJoinEvent = None
    ItemStack = None
    EventExecutor = object
    BUKKIT_AVAILABLE = False

try:
    from java.lang import Runnable, String as JavaString, StringBuilder, System
    JAVA_STRING_AVAILABLE = True
except ImportError:
    Runnable = object
    JavaString = str
    StringBuilder = None
    System = None
    JAVA_STRING_AVAILABLE = False

try:
    from java.util import ArrayList
except ImportError:
    ArrayList = list


def get_script_dir():
    if "__file__" in globals() and __file__:
        try:
            return os.path.dirname(os.path.abspath(__file__))
        except Exception:
            pass
    cwd = os.getcwd()
    pyspigot_path = os.path.join(cwd, "plugins", "PySpigot", "scripts")
    if os.path.exists(pyspigot_path):
        return pyspigot_path
    return cwd


def to_unicode(value):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    if JAVA_STRING_AVAILABLE and hasattr(value, "getBytes"):
        try:
            return unicode(value.getBytes("UTF-8"), "utf-8")
        except Exception:
            pass
    if isinstance(value, str):
        try:
            return value.decode("utf-8")
        except Exception:
            try:
                return value.decode("cp1251")
            except Exception:
                return unicode(value, "utf-8", "ignore")
    return unicode(str(value))


def to_java_string(value):
    text = to_unicode(value)
    if JAVA_STRING_AVAILABLE:
        if isinstance(text, JavaString):
            return text
        if StringBuilder is not None:
            try:
                builder = StringBuilder()
                for ch in text:
                    builder.appendCodePoint(ord(ch))
                return builder.toString()
            except Exception:
                pass
        try:
            return JavaString(text)
        except Exception:
            pass
    return text


def colorize(value):
    text = to_unicode(value)
    if not text:
        return u""
    if BUKKIT_AVAILABLE and ChatColor is not None:
        try:
            return to_unicode(ChatColor.translateAlternateColorCodes('&', to_java_string(text)))
        except Exception:
            pass
    return re.sub(r'&([0-9a-fk-or])', u'', text, flags=re.IGNORECASE)


def send_message(target, value):
    message = colorize(value)
    if BUKKIT_AVAILABLE and target is not None:
        try:
            target.sendMessage(to_java_string(message))
            return
        except Exception:
            pass
    print("[SmartY-Bounty] " + to_unicode(message))


def log_info(value):
    if BUKKIT_AVAILABLE:
        send_message(Bukkit.getConsoleSender(), u"&6[SmartY-Bounty] &7" + to_unicode(value))
    else:
        print("[SmartY-Bounty] " + str(value))


def build_java_list(values):
    if not BUKKIT_AVAILABLE:
        return values
    result = ArrayList()
    for value in values:
        result.add(to_java_string(value))
    return result


def format_currency(amount):
    try:
        value = float(amount)
        # ФИКС "nan$": round/format в Jython 2.7 молча пропускают NaN/Infinity,
        # возвращая строку "nan$"/"inf$" вместо ошибки. Явный гард ниже.
        if value != value or value == float("inf") or value == float("-inf"):
            return u"0$"
        text = "{:,.0f}".format(value).replace(",", " ")
        return to_unicode(text) + u"$"
    except Exception:
        return u"0$"


def parse_amount(raw):
    text = to_unicode(raw).replace(",", ".").replace(" ", "")
    amount = float(text)
    # ФИКС: та же дыра, что и в companies.py — NaN/Infinity обходили
    # проверку "amount <= 0", так как сравнения с NaN всегда возвращают False.
    if amount != amount or amount == float("inf") or amount == float("-inf"):
        raise ValueError()
    if amount <= 0:
        raise ValueError()
    return round(amount, 2)


def get_player_uuid(player):
    try:
        return str(player.getUniqueId())
    except Exception:
        return None


def get_player_name(player):
    try:
        return to_unicode(player.getName())
    except Exception:
        return u"Unknown"


def get_pyspigot_plugin():
    if not BUKKIT_AVAILABLE:
        return None
    try:
        plugin = Bukkit.getPluginManager().getPlugin("PySpigot")
        if plugin:
            return plugin
        for item in Bukkit.getPluginManager().getPlugins():
            if "pyspigot" in str(item.getName()).lower():
                return item
    except Exception:
        pass
    return None


class BountyConfig(object):
    PLUGIN_NAME = u"SmartY-Bounty"
    VERSION = u"1.0.0"
    PREFIX = u"&6&l[Баунти]&r "
    SCRIPT_DIR = get_script_dir()
    DATA_DIR = os.path.join(SCRIPT_DIR, "data")
    DATA_FILE = os.path.join(DATA_DIR, "bounty.json")

    MIN_PLAYER_BOUNTY = 100.0
    AUTO_BOUNTY_BASE = 500.0
    AUTO_BOUNTY_STREAK_BONUS = 250.0
    MAX_AUTO_BOUNTY_PER_KILL = 5000.0
    SURVIVAL_INTERVAL_SECONDS = 300
    SURVIVAL_BOUNTY_PER_STREAK = 100.0
    MAX_SURVIVAL_BOUNTY_PER_INTERVAL = 2000.0
    RECENT_KILL_COOLDOWN_SECONDS = 600
    BOUNTY_EXPIRE_SECONDS = 7 * 24 * 60 * 60
    LIST_PAGE_SIZE = 8
    HISTORY_LIMIT = 200
    NOTIFICATION_LIMIT = 30

    DEFAULT_STATE = {
        "bounties": {},
        "kill_streaks": {},
        "recent_kills": {},
        "pending_payouts": {},
        "notifications": {},
        "history": []
    }


class JsonStorage(object):
    def __init__(self, path, defaults):
        self.path = path
        self.backup_path = path + ".bak"
        self.defaults = defaults
        self.primary_valid = not os.path.exists(path)

    def load(self):
        self.ensure_dir()
        if not os.path.exists(self.path):
            return self.merge_defaults({})
        try:
            with open(self.path, "r") as handle:
                data = self.merge_defaults(json.load(handle))
                self.primary_valid = True
                return data
        except Exception as exc:
            log_info(u"Cannot read bounty data: {0}".format(exc))
        if os.path.exists(self.backup_path):
            try:
                with open(self.backup_path, "r") as handle:
                    data = self.merge_defaults(json.load(handle))
                    self.primary_valid = False
                    log_info(u"Loaded bounty data from backup.")
                    return data
            except Exception as exc:
                log_info(u"Cannot read bounty backup: {0}".format(exc))
        self.primary_valid = False
        raise RuntimeError("bounty.json and backup are unreadable")

    def save(self, data):
        self.ensure_dir()
        temp_path = self.path + ".tmp"
        try:
            with open(temp_path, "w") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except Exception:
                    pass
            if os.path.exists(self.path) and self.primary_valid:
                shutil.copy2(self.path, self.backup_path)
            if hasattr(os, "replace"):
                os.replace(temp_path, self.path)
            else:
                if os.path.exists(self.path):
                    os.remove(self.path)
                os.rename(temp_path, self.path)
            self.primary_valid = True
            return True
        except Exception as exc:
            log_info(u"Cannot save bounty data: {0}".format(exc))
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            return False

    def ensure_dir(self):
        folder = os.path.dirname(self.path)
        if not os.path.exists(folder):
            os.makedirs(folder)

    def merge_defaults(self, data):
        result = {}
        for key, value in self.defaults.items():
            result[key] = dict(value) if isinstance(value, dict) else value
        if isinstance(data, dict):
            for key, value in data.items():
                result[key] = value
        return result


class EconomyGateway(object):
    def __init__(self):
        self.manager = self.find_manager()

    def refresh(self):
        self.manager = self.find_manager()

    def find_manager(self):
        if JAVA_STRING_AVAILABLE and System is not None:
            try:
                manager = System.getProperties().get("PySpigot_EconomyManager")
                if not manager:
                    manager = System.getProperties().get("SmartY_EconomyManager")
                if manager:
                    return manager
            except Exception:
                pass
        if "economy" in sys.modules:
            module = sys.modules["economy"]
            if hasattr(module, "EconomyManager"):
                return module.EconomyManager()
        try:
            from economy import EconomyManager
            return EconomyManager()
        except Exception:
            return None

    def is_ready(self):
        if self.manager is None:
            self.refresh()
        return self.manager is not None

    def get_account_by_name(self, name):
        if not self.is_ready():
            return None
        return self.manager.get_account_by_name(name)

    def get_or_create(self, uuid_str, name):
        if not self.is_ready():
            return None
        return self.manager.get_or_create_account(uuid_str, name)

    def withdraw(self, uuid_str, amount):
        if not self.is_ready():
            return False
        return bool(self.manager.withdraw(uuid_str, amount))

    def deposit(self, uuid_str, amount, name):
        success, balance = self.deposit_checked(uuid_str, amount, name)
        return balance if success else 0.0

    def deposit_checked(self, uuid_str, amount, name):
        if not self.is_ready():
            return False, 0.0
        if hasattr(self.manager, "deposit_checked"):
            return self.manager.deposit_checked(uuid_str, amount, name)
        try:
            return True, self.manager.deposit(uuid_str, amount, name)
        except Exception:
            return False, 0.0

    def get_online_names(self):
        names = []
        if BUKKIT_AVAILABLE:
            try:
                for player in Bukkit.getOnlinePlayers():
                    names.append(to_unicode(player.getName()))
            except Exception:
                pass
        if self.is_ready():
            try:
                for account in self.manager.accounts.values():
                    if account.name:
                        names.append(to_unicode(account.name))
            except Exception:
                pass
        return sorted(list(set(names)), key=lambda item: item.lower())


class BountyState(object):
    def __init__(self, storage):
        self.storage = storage
        self.data = self.storage.load()
        self.normalize()

    def normalize(self):
        for key, default in BountyConfig.DEFAULT_STATE.items():
            self.data.setdefault(key, dict(default) if isinstance(default, dict) else list(default) if isinstance(default, list) else default)
        now = int(time.time())
        for record in self.data.get("bounties", {}).values():
            record.setdefault("created_at", int(record.get("updated_at", now)))
            record.setdefault("expires_at", now + BountyConfig.BOUNTY_EXPIRE_SECONDS)
            record.setdefault("contributions", [])

    def reload(self):
        self.data = self.storage.load()
        self.normalize()

    def save(self):
        return bool(self.storage.save(self.data))

    def get_record(self, uuid_str):
        return self.data.get("bounties", {}).get(str(uuid_str))

    def get_amount(self, uuid_str):
        record = self.get_record(uuid_str)
        if not record:
            return 0.0
        try:
            return float(record.get("amount", 0.0))
        except Exception:
            return 0.0

    def add_amount(self, uuid_str, name, amount, source, contributor_uuid=None, contributor_name=None):
        uuid_key = str(uuid_str)
        bounties = self.data.setdefault("bounties", {})
        record = bounties.get(uuid_key, {})
        record["uuid"] = uuid_key
        record["name"] = to_unicode(name)
        record["amount"] = round(float(record.get("amount", 0.0)) + float(amount), 2)
        record["updated_at"] = int(time.time())
        record.setdefault("created_at", int(time.time()))
        record["expires_at"] = int(time.time()) + BountyConfig.BOUNTY_EXPIRE_SECONDS
        record[source] = round(float(record.get(source, 0.0)) + float(amount), 2)
        if contributor_uuid and source == "player_funded":
            record.setdefault("contributions", []).append({
                "uuid": str(contributor_uuid),
                "name": to_unicode(contributor_name or u"Unknown"),
                "amount": round(float(amount), 2),
                "created_at": int(time.time())
            })
        bounties[uuid_key] = record
        if not self.save():
            raise RuntimeError("cannot save bounty state")
        return record["amount"]

    def set_amount(self, uuid_str, name, amount):
        uuid_key = str(uuid_str)
        bounties = self.data.setdefault("bounties", {})
        if amount <= 0:
            if uuid_key in bounties:
                del bounties[uuid_key]
        else:
            record = bounties.get(uuid_key, {})
            record["uuid"] = uuid_key
            record["name"] = to_unicode(name)
            record["amount"] = round(float(amount), 2)
            record["updated_at"] = int(time.time())
            bounties[uuid_key] = record
        return self.save()

    def claim(self, uuid_str):
        uuid_key = str(uuid_str)
        record = self.data.setdefault("bounties", {}).pop(uuid_key, None)
        if not record:
            return None
        claim_id = u"claim_{0}_{1}".format(int(time.time() * 1000), uuid_key[:8])
        pending = {
            "id": claim_id,
            "victim_uuid": uuid_key,
            "record": record,
            "amount": round(float(record.get("amount", 0.0)), 2),
            "status": "prepared",
            "created_at": int(time.time())
        }
        self.data.setdefault("pending_payouts", {})[claim_id] = pending
        if not self.save():
            self.data["pending_payouts"].pop(claim_id, None)
            self.data["bounties"][uuid_key] = record
            return None
        return pending

    def rollback_claim(self, claim_id):
        pending = self.data.setdefault("pending_payouts", {}).pop(str(claim_id), None)
        if not pending:
            return False
        self.data.setdefault("bounties", {})[pending["victim_uuid"]] = pending["record"]
        return self.save()

    def mark_claim_crediting(self, claim_id, killer_uuid, killer_name):
        pending = self.data.setdefault("pending_payouts", {}).get(str(claim_id))
        if not pending:
            return False
        pending["status"] = "crediting"
        pending["killer_uuid"] = str(killer_uuid)
        pending["killer_name"] = to_unicode(killer_name)
        return self.save()

    def finish_claim(self, claim_id):
        pending = self.data.setdefault("pending_payouts", {}).pop(str(claim_id), None)
        if not pending:
            return False
        pending["status"] = "paid"
        pending["finished_at"] = int(time.time())
        pending.pop("record", None)
        history = self.data.setdefault("history", [])
        history.append(pending)
        if len(history) > BountyConfig.HISTORY_LIMIT:
            del history[:-BountyConfig.HISTORY_LIMIT]
        return self.save()

    def queue_notification(self, uuid_str, message):
        notes = self.data.setdefault("notifications", {}).setdefault(str(uuid_str), [])
        notes.append(to_unicode(message))
        if len(notes) > BountyConfig.NOTIFICATION_LIMIT:
            del notes[:-BountyConfig.NOTIFICATION_LIMIT]
        return self.save()

    def pop_notifications(self, uuid_str):
        key = str(uuid_str)
        notes = list(self.data.setdefault("notifications", {}).get(key, []))
        if notes:
            self.data["notifications"].pop(key, None)
            if not self.save():
                self.data["notifications"][key] = notes
                return []
        return notes

    def get_streak(self, uuid_str):
        try:
            return int(self.data.get("kill_streaks", {}).get(str(uuid_str), 0))
        except Exception:
            return 0

    def set_streak(self, uuid_str, value):
        self.data.setdefault("kill_streaks", {})[str(uuid_str)] = max(0, int(value))
        self.save()

    def is_recent_pair(self, killer_uuid, victim_uuid):
        key = u"{0}|{1}".format(killer_uuid, victim_uuid)
        last = float(self.data.get("recent_kills", {}).get(key, 0.0))
        return time.time() - last < BountyConfig.RECENT_KILL_COOLDOWN_SECONDS

    def mark_recent_pair(self, killer_uuid, victim_uuid):
        key = u"{0}|{1}".format(killer_uuid, victim_uuid)
        self.data.setdefault("recent_kills", {})[key] = int(time.time())
        self.prune_recent_pairs()
        self.save()

    def prune_recent_pairs(self):
        recent = self.data.setdefault("recent_kills", {})
        now = time.time()
        for key in list(recent.keys()):
            try:
                if now - float(recent.get(key, 0.0)) > BountyConfig.RECENT_KILL_COOLDOWN_SECONDS * 6:
                    del recent[key]
            except Exception:
                del recent[key]

    def list_bounties(self):
        records = list(self.data.get("bounties", {}).values())
        records = [record for record in records if float(record.get("amount", 0.0)) > 0]
        return sorted(records, key=lambda item: float(item.get("amount", 0.0)), reverse=True)


class BountyService(object):
    def __init__(self, state, economy):
        self.state = state
        self.economy = economy

    def place_bounty(self, sender, target_name, amount):
        sender_uuid = get_player_uuid(sender)
        sender_name = get_player_name(sender)
        if not sender_uuid:
            send_message(sender, BountyConfig.PREFIX + u"&cТолько игрок может объявить награду.")
            return

        if amount < BountyConfig.MIN_PLAYER_BOUNTY:
            send_message(sender, BountyConfig.PREFIX + u"&cМинимальная награда: &e{0}&c.".format(
                format_currency(BountyConfig.MIN_PLAYER_BOUNTY)
            ))
            return

        target = self.resolve_target(target_name)
        if not target:
            send_message(sender, BountyConfig.PREFIX + u"&cИгрок &e{0}&c не найден в экономике.".format(target_name))
            return
        if str(target.uuid) == sender_uuid:
            send_message(sender, BountyConfig.PREFIX + u"&cНельзя объявить награду за самого себя.")
            return

        self.economy.get_or_create(sender_uuid, sender_name)
        if not self.economy.withdraw(sender_uuid, amount):
            send_message(sender, BountyConfig.PREFIX + u"&cНедостаточно денег для награды.")
            return

        try:
            total = self.state.add_amount(
                target.uuid, target.name, amount, "player_funded",
                contributor_uuid=sender_uuid, contributor_name=sender_name
            )
        except Exception as exc:
            refunded, balance = self.economy.deposit_checked(sender_uuid, amount, sender_name)
            log_info(u"Bounty placement rollback for {0}: {1}".format(sender_name, exc))
            if refunded:
                send_message(sender, BountyConfig.PREFIX + u"&cНаграда не сохранена; деньги возвращены.")
            else:
                send_message(sender, BountyConfig.PREFIX + u"&4Критическая ошибка: награда не сохранена и возврат не прошёл. Обратитесь к администратору.")
            return
        send_message(sender, BountyConfig.PREFIX + u"&aНаграда за &e{0}&a увеличена на &e{1}&a. Всего: &6{2}&a.".format(
            target.name, format_currency(amount), format_currency(total)
        ))
        self.broadcast(u"&e{0} &7назначил награду &6{1} &7за &c{2}&7. Общая награда: &6{3}&7.".format(
            sender_name, format_currency(amount), target.name, format_currency(total)
        ))
        target_player = Bukkit.getPlayer(to_java_string(target.name)) if BUKKIT_AVAILABLE else None
        notice = BountyConfig.PREFIX + u"&cЗа вашу голову назначена награда &6{0}&c. Всего: &6{1}&c.".format(
            format_currency(amount), format_currency(total))
        if target_player is not None and target_player.isOnline():
            send_message(target_player, notice)
        else:
            self.state.queue_notification(target.uuid, notice)

    def handle_death(self, event):
        if not self.is_player_death_event(event):
            return
        victim = event.getEntity()
        killer = victim.getKiller()
        if not self.is_player(victim):
            return
        if killer is None:
            self.reset_victim_streak(victim)
            return
        if not self.is_player(killer):
            return

        victim_uuid = get_player_uuid(victim)
        killer_uuid = get_player_uuid(killer)
        if not victim_uuid or not killer_uuid or victim_uuid == killer_uuid:
            return

        if self.state.is_recent_pair(killer_uuid, victim_uuid):
            send_message(killer, BountyConfig.PREFIX + u"&7Повторное убийство этой жертвы не выдаёт награду и не увеличивает серию.")
            self.reset_victim_streak(victim)
            return

        self.pay_victim_bounty(killer, victim)
        self.update_killer_bounty(killer, victim)
        self.reset_victim_streak(victim)

    def is_player_death_event(self, event):
        try:
            return isinstance(event, PlayerDeathEvent)
        except Exception:
            return event.__class__.__name__ == "PlayerDeathEvent"

    def is_player(self, entity):
        try:
            return isinstance(entity, Player)
        except Exception:
            try:
                return entity.getType().name() == "PLAYER"
            except Exception:
                return False

    def pay_victim_bounty(self, killer, victim):
        if not self.is_player(killer) or not self.is_player(victim):
            return
        victim_uuid = get_player_uuid(victim)
        amount = self.state.get_amount(victim_uuid)
        if amount <= 0:
            return

        killer_uuid = get_player_uuid(killer)
        killer_name = get_player_name(killer)
        pending = self.state.claim(victim_uuid)
        if not pending:
            send_message(killer, BountyConfig.PREFIX + u"&cНаграду не удалось зарезервировать. Выплата отменена без потери баунти.")
            return
        claim_id = pending.get("id")
        if not self.state.mark_claim_crediting(claim_id, killer_uuid, killer_name):
            self.state.rollback_claim(claim_id)
            send_message(killer, BountyConfig.PREFIX + u"&cНаграду не удалось подготовить к выплате.")
            return
        deposited, balance = self.economy.deposit_checked(killer_uuid, amount, killer_name)
        if not deposited:
            self.state.rollback_claim(claim_id)
            send_message(killer, BountyConfig.PREFIX + u"&cЭкономика недоступна; награда возвращена на голову жертвы.")
            return
        self.state.finish_claim(claim_id)
        self.broadcast(u"&6{0} &7получил награду &e{1} &7за убийство &c{2}&7.".format(
            killer_name, format_currency(amount), get_player_name(victim)
        ))
        self.play_sound(killer, "ENTITY_PLAYER_LEVELUP", 1.0, 1.15)

    def update_killer_bounty(self, killer, victim):
        if not self.is_player(killer) or not self.is_player(victim):
            return
        killer_uuid = get_player_uuid(killer)
        victim_uuid = get_player_uuid(victim)
        if self.state.is_recent_pair(killer_uuid, victim_uuid):
            send_message(killer, BountyConfig.PREFIX + u"&7Авто-баунти не выросло: повторное убийство этого игрока слишком быстро.")
            return

        streak = self.state.get_streak(killer_uuid) + 1
        self.state.set_streak(killer_uuid, streak)
        self.state.mark_recent_pair(killer_uuid, victim_uuid)
        auto_amount = self.calculate_auto_bounty(streak)
        total = self.state.add_amount(killer_uuid, get_player_name(killer), auto_amount, "auto_funded")

        self.broadcast(u"&c{0} &7становится опаснее: серия убийств &e{1}&7, баунти выросло на &6{2}&7. Всего: &6{3}&7.".format(
            get_player_name(killer), streak, format_currency(auto_amount), format_currency(total)
        ))

    def wanted_level(self, amount):
        amount = float(amount)
        if amount >= 50000:
            return u"§4★★★★★ Легендарная цель"
        if amount >= 20000:
            return u"§c★★★★ Опаснейший"
        if amount >= 7500:
            return u"§6★★★ Разыскивается"
        if amount >= 2500:
            return u"§e★★ Опасный"
        if amount > 0:
            return u"§f★ Подозреваемый"
        return u"§7Нет розыска"

    def expire_bounties(self):
        now = int(time.time())
        changed = False
        for victim_uuid, record in list(self.state.data.setdefault("bounties", {}).items()):
            if int(record.get("expires_at", now + 1)) > now:
                continue
            refund_failed = False
            for index, contribution in enumerate(record.get("contributions", [])):
                if contribution.get("refunded"):
                    continue
                if contribution.get("refund_status") == "crediting":
                    # The server stopped after durable intent but before the
                    # result was recorded. Automatic retry could mint money.
                    refund_failed = True
                    continue
                amount = float(contribution.get("amount", 0.0))
                if amount <= 0:
                    contribution["refunded"] = True
                    continue
                claim_id = u"refund_{0}_{1}_{2}".format(victim_uuid[:8], index, int(time.time() * 1000))
                contribution["refund_status"] = "crediting"
                contribution["refund_claim_id"] = claim_id
                self.state.data.setdefault("pending_payouts", {})[claim_id] = {
                    "id": claim_id, "kind": "expiry_refund", "victim_uuid": victim_uuid,
                    "contribution_index": index, "recipient_uuid": contribution.get("uuid"),
                    "recipient_name": contribution.get("name"), "amount": amount,
                    "status": "crediting", "created_at": now
                }
                if not self.state.save():
                    self.state.data["pending_payouts"].pop(claim_id, None)
                    contribution.pop("refund_claim_id", None)
                    contribution["refund_status"] = "failed"
                    refund_failed = True
                    continue
                ok, balance = self.economy.deposit_checked(
                    contribution.get("uuid"), amount, contribution.get("name", u"Hunter"))
                if not ok:
                    contribution["refund_status"] = "failed"
                    contribution.pop("refund_claim_id", None)
                    self.state.data["pending_payouts"].pop(claim_id, None)
                    refund_failed = True
                    self.state.save()
                    continue
                contribution["refunded"] = True
                contribution["refund_status"] = "paid"
                contribution.pop("refund_claim_id", None)
                self.state.data["pending_payouts"].pop(claim_id, None)
                self.state.queue_notification(
                    contribution.get("uuid"),
                    BountyConfig.PREFIX + u"&7Награда за &e{0}&7 истекла; вам возвращено &6{1}&7.".format(
                        record.get("name", u"игрока"), format_currency(amount)))
            if refund_failed:
                record["expires_at"] = now + 3600
                changed = True
                continue
            self.state.data["bounties"].pop(victim_uuid, None)
            changed = True
        if changed:
            self.state.save()

    def deliver_notifications(self, player):
        for note in self.state.pop_notifications(get_player_uuid(player)):
            send_message(player, note)

    def apply_survival_bounties(self):
        if not BUKKIT_AVAILABLE:
            return
        self.expire_bounties()
        for player in Bukkit.getOnlinePlayers():
            uuid_str = get_player_uuid(player)
            if not uuid_str:
                continue
            streak = self.state.get_streak(uuid_str)
            if streak <= 0:
                continue
            amount = min(
                BountyConfig.MAX_SURVIVAL_BOUNTY_PER_INTERVAL,
                BountyConfig.SURVIVAL_BOUNTY_PER_STREAK * streak
            )
            total = self.state.add_amount(uuid_str, get_player_name(player), amount, "survival_funded")
            send_message(player, BountyConfig.PREFIX + u"&7Вы все еще живы с серией &e{0}&7. Баунти выросло на &6{1}&7. Всего: &6{2}&7.".format(
                streak, format_currency(amount), format_currency(total)
            ))

    def reset_victim_streak(self, victim):
        uuid_str = get_player_uuid(victim)
        if uuid_str:
            self.state.set_streak(uuid_str, 0)

    def calculate_auto_bounty(self, streak):
        amount = BountyConfig.AUTO_BOUNTY_BASE + (max(0, int(streak) - 1) * BountyConfig.AUTO_BOUNTY_STREAK_BONUS)
        return min(BountyConfig.MAX_AUTO_BOUNTY_PER_KILL, amount)

    def resolve_target(self, name):
        if BUKKIT_AVAILABLE:
            try:
                player = Bukkit.getPlayer(to_java_string(name))
                if player and player.isOnline():
                    return self.economy.get_or_create(get_player_uuid(player), get_player_name(player))
            except Exception:
                pass
        return self.economy.get_account_by_name(name)

    def broadcast(self, message):
        if BUKKIT_AVAILABLE:
            Bukkit.broadcastMessage(to_java_string(colorize(BountyConfig.PREFIX + message)))
        else:
            log_info(message)

    def play_sound(self, player, sound_name, volume, pitch):
        if not BUKKIT_AVAILABLE or Sound is None:
            return
        try:
            sound = Sound.valueOf(sound_name)
            player.playSound(player.getLocation(), sound, float(volume), float(pitch))
        except Exception:
            pass


class BountyCommand(object):
    def __init__(self, service, state, economy):
        self.service = service
        self.state = state
        self.economy = economy

    def execute_bounty(self, sender, label, args):
        args = list(args)
        if len(args) == 0:
            self.send_usage(sender, label)
            return True
        if len(args) == 1:
            self.show_player_bounty(sender, args[0])
            return True

        try:
            amount = parse_amount(args[1])
        except Exception:
            send_message(sender, BountyConfig.PREFIX + u"&cНекорректная сумма.")
            return True

        self.service.place_bounty(sender, args[0], amount)
        return True

    def execute_list(self, sender, label, args):
        page = 1
        if args:
            try:
                page = max(1, int(args[0]))
            except Exception:
                page = 1
        if BUKKIT_AVAILABLE and isinstance(sender, Player):
            self.open_bounty_gui(sender, page)
        else:
            self.send_bounty_list(sender, page)
        return True

    def execute_admin(self, sender, label, args):
        if not self.is_admin(sender):
            send_message(sender, BountyConfig.PREFIX + u"&cКоманда доступна только операторам сервера.")
            return True
        args = list(args)
        if not args:
            self.send_admin_usage(sender, label)
            return True
        sub = args[0].lower()
        if sub == "reload":
            self.state.reload()
            send_message(sender, BountyConfig.PREFIX + u"&aДанные bounty перезагружены.")
        elif sub == "clear" and len(args) >= 2:
            self.set_admin_bounty(sender, args[1], 0.0)
        elif sub in ("set", "add") and len(args) >= 3:
            try:
                amount = parse_amount(args[2])
            except Exception:
                send_message(sender, BountyConfig.PREFIX + u"&cНекорректная сумма.")
                return True
            if sub == "set":
                self.set_admin_bounty(sender, args[1], amount)
            else:
                self.add_admin_bounty(sender, args[1], amount)
        elif sub == "pending":
            self.send_pending(sender)
        elif sub == "resolve" and len(args) >= 3:
            self.resolve_pending(sender, args[1], args[2].lower())
        else:
            self.send_admin_usage(sender, label)
        return True

    def show_player_bounty(self, sender, target_name):
        target = self.service.resolve_target(target_name)
        if not target:
            send_message(sender, BountyConfig.PREFIX + u"&cИгрок &e{0}&c не найден.".format(target_name))
            return
        amount = self.state.get_amount(target.uuid)
        streak = self.state.get_streak(target.uuid)
        send_message(sender, BountyConfig.PREFIX + u"&7Баунти за &e{0}&7: &6{1}&7. Серия убийств: &c{2}&7.".format(
            target.name, format_currency(amount), streak
        ))
        send_message(sender, u"&7Уровень розыска: {0}".format(self.service.wanted_level(amount)))

    def open_bounty_gui(self, player, page):
        records = self.state.list_bounties()
        page_size = 45
        total_pages = max(1, int((len(records) + page_size - 1) / page_size))
        page = min(max(1, int(page)), total_pages)
        inv = Bukkit.createInventory(None, 54, u"§8[БАУНТИ] §0Цели {0}/{1}".format(page, total_pages))
        start = (page - 1) * page_size
        for slot, record in enumerate(records[start:start + page_size]):
            item = ItemStack(Material.PLAYER_HEAD, 1)
            meta = item.getItemMeta()
            name = to_unicode(record.get("name", u"Unknown"))
            try:
                meta.setOwningPlayer(Bukkit.getOfflinePlayer(to_java_string(name)))
            except Exception:
                pass
            meta.setDisplayName(to_java_string(colorize(u"&c&l" + name)))
            expires = max(0, int(record.get("expires_at", int(time.time()))) - int(time.time()))
            lore = [
                colorize(u"&7Награда: &6" + format_currency(record.get("amount", 0.0))),
                self.service.wanted_level(record.get("amount", 0.0)),
                colorize(u"&7Истекает через: &e{0} ч.".format(int(expires / 3600))),
                colorize(u"&eНажмите для подробностей")
            ]
            meta.setLore(build_java_list(lore))
            item.setItemMeta(meta)
            inv.setItem(slot, item)
        if page > 1:
            prev = ItemStack(Material.ARROW, 1)
            pm = prev.getItemMeta(); pm.setDisplayName(u"§aПредыдущая страница"); prev.setItemMeta(pm)
            inv.setItem(45, prev)
        if page < total_pages:
            nxt = ItemStack(Material.ARROW, 1)
            nm = nxt.getItemMeta(); nm.setDisplayName(u"§aСледующая страница"); nxt.setItemMeta(nm)
            inv.setItem(53, nxt)
        player.openInventory(inv)
        open_bounty_guis[get_player_uuid(player)] = {"page": page, "records": records[start:start + page_size]}

    def send_bounty_list(self, sender, page):
        records = self.state.list_bounties()
        if not records:
            send_message(sender, BountyConfig.PREFIX + u"&7Активных наград пока нет.")
            return

        page_size = BountyConfig.LIST_PAGE_SIZE
        total_pages = max(1, int((len(records) + page_size - 1) / page_size))
        page = min(max(1, page), total_pages)
        start = (page - 1) * page_size
        chunk = records[start:start + page_size]

        send_message(sender, BountyConfig.PREFIX + u"&6Топ наград &7(страница &e{0}&7/&e{1}&7)".format(page, total_pages))
        for index, record in enumerate(chunk, start + 1):
            send_message(sender, u"&8#{0} &c{1} &8- &6{2}".format(
                index, record.get("name", "Unknown"), format_currency(record.get("amount", 0.0))
            ))

    def set_admin_bounty(self, sender, target_name, amount):
        target = self.service.resolve_target(target_name)
        if not target:
            send_message(sender, BountyConfig.PREFIX + u"&cИгрок &e{0}&c не найден.".format(target_name))
            return
        self.state.set_amount(target.uuid, target.name, amount)
        send_message(sender, BountyConfig.PREFIX + u"&aБаунти за &e{0}&a установлено: &6{1}&a.".format(
            target.name, format_currency(amount)
        ))

    def add_admin_bounty(self, sender, target_name, amount):
        target = self.service.resolve_target(target_name)
        if not target:
            send_message(sender, BountyConfig.PREFIX + u"&cИгрок &e{0}&c не найден.".format(target_name))
            return
        total = self.state.add_amount(target.uuid, target.name, amount, "admin_funded")
        send_message(sender, BountyConfig.PREFIX + u"&aБаунти за &e{0}&a увеличено. Всего: &6{1}&a.".format(
            target.name, format_currency(total)
        ))

    def send_usage(self, sender, label):
        send_message(sender, BountyConfig.PREFIX + u"&7/{0} <игрок> <сумма> &8- &fобъявить награду".format(label))
        send_message(sender, u"&7/{0} <игрок> &8- &fпосмотреть награду за игрока".format(label))
        send_message(sender, u"&7/bountylist [страница] &8- &fсписок активных наград")

    def send_admin_usage(self, sender, label):
        send_message(sender, BountyConfig.PREFIX + u"&7/{0} reload".format(label))
        send_message(sender, u"&7/{0} clear <игрок>".format(label))
        send_message(sender, u"&7/{0} set <игрок> <сумма>".format(label))
        send_message(sender, u"&7/{0} add <игрок> <сумма>".format(label))
        send_message(sender, u"&7/{0} pending &8- спорные выплаты после сбоя".format(label))
        send_message(sender, u"&7/{0} resolve <id> <paid|restore|retry>".format(label))

    def send_pending(self, sender):
        pending = self.state.data.get("pending_payouts", {})
        if not pending:
            send_message(sender, BountyConfig.PREFIX + u"&7Спорных выплат нет.")
            return
        for claim_id, item in list(pending.items())[:20]:
            send_message(sender, u"&8- &e{0} &7{1}: &6{2} &8({3})".format(
                claim_id, item.get("killer_name", u"?"), format_currency(item.get("amount", 0.0)), item.get("status", "?")))

    def resolve_pending(self, sender, claim_id, action):
        pending = self.state.data.get("pending_payouts", {}).get(str(claim_id))
        if not pending:
            send_message(sender, BountyConfig.PREFIX + u"&cВыплата не найдена.")
            return
        if pending.get("kind") == "expiry_refund":
            victim_record = self.state.data.get("bounties", {}).get(str(pending.get("victim_uuid")))
            contribution = None
            if victim_record:
                for item in victim_record.get("contributions", []):
                    if item.get("refund_claim_id") == str(claim_id):
                        contribution = item
                        break
            if contribution is None:
                send_message(sender, BountyConfig.PREFIX + u"&cСвязанная запись взноса не найдена; требуется ручная сверка.")
                return
            if action == "retry":
                ok, balance = self.economy.deposit_checked(
                    pending.get("recipient_uuid"), pending.get("amount", 0.0), pending.get("recipient_name"))
                if not ok:
                    send_message(sender, BountyConfig.PREFIX + u"&cПовторный возврат не подтверждён.")
                    return
            elif action != "paid":
                send_message(sender, BountyConfig.PREFIX + u"&cДля возврата после сверки используйте paid или retry.")
                return
            contribution["refunded"] = True
            contribution["refund_status"] = "paid"
            contribution.pop("refund_claim_id", None)
            self.state.data["pending_payouts"].pop(str(claim_id), None)
            if self.state.save():
                send_message(sender, BountyConfig.PREFIX + u"&aВозврат взноса закрыт после сверки.")
            else:
                send_message(sender, BountyConfig.PREFIX + u"&cРезультат сверки не удалось сохранить; не повторяйте выплату.")
            return
        if action == "restore":
            if self.state.rollback_claim(claim_id):
                send_message(sender, BountyConfig.PREFIX + u"&aБаунти восстановлено на цели.")
            else:
                send_message(sender, BountyConfig.PREFIX + u"&cНе удалось восстановить запись.")
        elif action == "paid":
            if self.state.finish_claim(claim_id):
                send_message(sender, BountyConfig.PREFIX + u"&aВыплата отмечена как уже зачисленная.")
            else:
                send_message(sender, BountyConfig.PREFIX + u"&cНе удалось закрыть выплату.")
        else:
            send_message(sender, BountyConfig.PREFIX + u"&cИспользуйте paid или restore после проверки economy.json/лога.")

    def tab_player_names(self, args):
        prefix = args[-1].lower() if args else ""
        return build_java_list([name for name in self.economy.get_online_names() if name.lower().startswith(prefix)][:20])

    def tab_bounty(self, sender, alias, args):
        args = list(args)
        if len(args) == 1:
            return self.tab_player_names(args)
        if len(args) == 2:
            return build_java_list(["100", "500", "1000", "5000", "10000"])
        return build_java_list([])

    def tab_list(self, sender, alias, args):
        return build_java_list(["1", "2", "3"] if len(args) == 1 else [])

    def tab_admin(self, sender, alias, args):
        args = list(args)
        if len(args) == 1:
            prefix = args[0].lower()
            return build_java_list([item for item in ["reload", "clear", "set", "add", "pending", "resolve"] if item.startswith(prefix)])
        if len(args) == 2 and args[0].lower() in ("clear", "set", "add"):
            return self.tab_player_names(args)
        if len(args) == 3 and args[0].lower() in ("set", "add"):
            return build_java_list(["500", "1000", "5000", "10000"])
        if len(args) == 3 and args[0].lower() == "resolve":
            return build_java_list(["paid", "restore"])
        return build_java_list([])

    def is_admin(self, sender):
        if sender is None:
            return True
        try:
            return bool(sender.isOp())
        except Exception:
            return False


if BUKKIT_AVAILABLE:
    class PyBukkitCommand(Command, TabCompleter):
        def __init__(self, name, description, usage, aliases, executor, completer):
            Command.__init__(self, name, description, usage, aliases)
            self.executor = executor
            self.completer = completer

        def execute(self, sender, command_label, args):
            try:
                return self.executor(sender, command_label, list(args))
            except Exception as exc:
                log_info(u"Command error: {0}".format(exc))
                return True

        def tabComplete(self, *args):
            try:
                if self.completer and len(args) >= 3:
                    result = self.completer(args[0], args[1], args[2])
                    if result is not None:
                        return result
            except Exception:
                pass
            return build_java_list([])

        def onTabComplete(self, *args):
            return self.tabComplete(*args)
else:
    class PyBukkitCommand(object):
        def __init__(self, name, description, usage, aliases, executor, completer):
            self.name = name


registered_listeners = []
registered_command_names = []   # (name, aliases) вручную зарегистрированных команд - нужно
                                 # хранить отдельно, т.к. PySpigot ничего не знает об этих
                                 # командах (они внедрены напрямую в CommandMap через
                                 # рефлексию, в обход command_manager) и не может снять их
                                 # сам при /pyspigot unload.
survival_task_id = -1
open_bounty_guis = {}
state = None
economy = None
service = None
command_handler = None
initialized = False


def on_bounty_inventory_click(event):
    try:
        player = event.getWhoClicked()
        if not isinstance(player, Player):
            return
        player_uuid = get_player_uuid(player)
        gui = open_bounty_guis.get(player_uuid)
        if gui is None or u"[БАУНТИ]" not in to_unicode(event.getView().getTitle()):
            return
        event.setCancelled(True)
        slot = event.getRawSlot()
        if slot == 45 and gui.get("page", 1) > 1:
            command_handler.open_bounty_gui(player, gui["page"] - 1)
            return
        if slot == 53:
            command_handler.open_bounty_gui(player, gui.get("page", 1) + 1)
            return
        records = gui.get("records", [])
        if 0 <= slot < len(records):
            record = records[slot]
            player.closeInventory()
            command_handler.show_player_bounty(player, record.get("name", u"Unknown"))
    except Exception as exc:
        log_info(u"Bounty GUI click error: {0}".format(exc))


def on_bounty_inventory_close(event):
    try:
        open_bounty_guis.pop(get_player_uuid(event.getPlayer()), None)
    except Exception:
        pass


def on_bounty_player_join(event):
    try:
        if service is not None:
            service.deliver_notifications(event.getPlayer())
    except Exception as exc:
        log_info(u"Bounty notification error: {0}".format(exc))


def force_register_bukkit_command(fallback_prefix, cmd_obj, aliases):
    if not BUKKIT_AVAILABLE:
        return
    try:
        server = Bukkit.getServer()
        command_map = server.getCommandMap() if hasattr(server, "getCommandMap") else None
        if command_map is None:
            field = server.getClass().getDeclaredField("commandMap")
            field.setAccessible(True)
            command_map = field.get(server)

        known_commands = None
        if hasattr(command_map, "getKnownCommands"):
            try:
                known_commands = command_map.getKnownCommands()
            except Exception:
                pass
        if known_commands is None:
            current_class = command_map.getClass()
            while current_class is not None and known_commands is None:
                try:
                    field = current_class.getDeclaredField("knownCommands")
                    field.setAccessible(True)
                    known_commands = field.get(command_map)
                except Exception:
                    current_class = current_class.getSuperclass()
        if known_commands is None:
            log_info(u"Cannot access Bukkit knownCommands map.")
            return

        names = [cmd_obj.getName()] + list(aliases)
        for name in names:
            lowered = str(name).lower()
            for key in [lowered, fallback_prefix + ":" + lowered]:
                try:
                    old_command = known_commands.get(key)
                    if old_command is not None and hasattr(old_command, "unregister"):
                        old_command.unregister(command_map)
                    known_commands.remove(key)
                except Exception:
                    pass

        known_commands.put(cmd_obj.getName().lower(), cmd_obj)
        known_commands.put(fallback_prefix + ":" + cmd_obj.getName().lower(), cmd_obj)
        for alias in aliases:
            alias_command = PyBukkitCommand(
                alias,
                cmd_obj.getDescription(),
                cmd_obj.getUsage(),
                [],
                cmd_obj.executor,
                cmd_obj.completer
            )
            known_commands.put(str(alias).lower(), alias_command)
            known_commands.put(fallback_prefix + ":" + str(alias).lower(), alias_command)
    except Exception as exc:
        log_info(u"Command registration error: {0}".format(exc))


def force_unregister_bukkit_command(fallback_prefix, name, aliases):
    """Полностью снимает команду (и её алиасы) из Bukkit CommandMap. Симметрично
    force_register_bukkit_command - без этой функции команды, внедрённые напрямую
    рефлексией в обход PySpigot.command_manager, остаются рабочими даже после
    /pyspigot unload, т.к. PySpigot ничего не знает об их существовании и не может
    снять их сам."""
    if not BUKKIT_AVAILABLE:
        return
    try:
        server = Bukkit.getServer()
        command_map = server.getCommandMap() if hasattr(server, "getCommandMap") else None
        if command_map is None:
            field = server.getClass().getDeclaredField("commandMap")
            field.setAccessible(True)
            command_map = field.get(server)

        known_commands = None
        if hasattr(command_map, "getKnownCommands"):
            try:
                known_commands = command_map.getKnownCommands()
            except Exception:
                pass
        if known_commands is None:
            current_class = command_map.getClass()
            while current_class is not None and known_commands is None:
                try:
                    field = current_class.getDeclaredField("knownCommands")
                    field.setAccessible(True)
                    known_commands = field.get(command_map)
                except Exception:
                    current_class = current_class.getSuperclass()
        if known_commands is None:
            return

        names = [name] + list(aliases)
        for item_name in names:
            lowered = str(item_name).lower()
            for key in [lowered, fallback_prefix + ":" + lowered]:
                try:
                    old_command = known_commands.get(key)
                    if old_command is not None and hasattr(old_command, "unregister"):
                        old_command.unregister(command_map)
                    known_commands.remove(key)
                except Exception:
                    pass
    except Exception as exc:
        log_info(u"Command unregistration error: {0}".format(exc))


def unregister_commands():
    """Снимает все команды, зарегистрированные этим скриптом напрямую в CommandMap."""
    for name, aliases in list(registered_command_names):
        force_unregister_bukkit_command("smarty-bounty", name, aliases)
    del registered_command_names[:]
    try:
        if BUKKIT_AVAILABLE and hasattr(Bukkit.getServer(), "syncCommands"):
            Bukkit.getServer().syncCommands()
    except Exception:
        pass


def register_event(event_class, handler):
    if not BUKKIT_AVAILABLE or event_class is None:
        return False
    plugin = get_pyspigot_plugin()
    if not plugin:
        return False

    class DirectListener(Listener):
        pass

    class DirectExecutor(EventExecutor):
        def execute(self, listener, event):
            try:
                handler(event)
            except Exception as exc:
                log_info(u"Event error: {0}".format(exc))

    listener = DirectListener()
    Bukkit.getPluginManager().registerEvent(
        event_class,
        listener,
        EventPriority.HIGHEST,
        DirectExecutor(),
        plugin
    )
    registered_listeners.append(listener)
    return True


def unregister_events():
    if HandlerList is None:
        return
    for listener in list(registered_listeners):
        try:
            HandlerList.unregisterAll(listener)
        except Exception:
            pass
    del registered_listeners[:]


class SurvivalBountyRunnable(Runnable):
    def run(self):
        try:
            if service is not None:
                service.apply_survival_bounties()
        except Exception as exc:
            log_info(u"Survival bounty task error: {0}".format(exc))


def start_survival_timer():
    global survival_task_id
    stop_survival_timer()
    if not BUKKIT_AVAILABLE:
        return
    plugin = get_pyspigot_plugin()
    if not plugin:
        return
    try:
        period_ticks = int(BountyConfig.SURVIVAL_INTERVAL_SECONDS * 20)
        task = Bukkit.getScheduler().runTaskTimer(plugin, SurvivalBountyRunnable(), period_ticks, period_ticks)
        survival_task_id = task.getTaskId()
        log_info(u"Started survival bounty timer, task ID {0}.".format(survival_task_id))
    except Exception as exc:
        log_info(u"Cannot start survival bounty timer: {0}".format(exc))


def stop_survival_timer():
    global survival_task_id
    if not BUKKIT_AVAILABLE or survival_task_id == -1:
        return
    try:
        Bukkit.getScheduler().cancelTask(survival_task_id)
    except Exception:
        pass
    survival_task_id = -1


def register_commands():
    command_defs = [
        ("bounty", "Place or view player bounty", "/bounty <player> [amount]", ["hunts"], command_handler.execute_bounty, command_handler.tab_bounty),
        ("bountylist", "Show active bounties", "/bountylist [page]", ["bounties", "hunters"], command_handler.execute_list, command_handler.tab_list),
        ("bountyadmin", "Admin bounty tools", "/bountyadmin <reload|clear|set|add>", ["ba"], command_handler.execute_admin, command_handler.tab_admin)
    ]
    for item in command_defs:
        cmd_obj = PyBukkitCommand(item[0], item[1], item[2], item[3], item[4], item[5])
        force_register_bukkit_command("smarty-bounty", cmd_obj, item[3])
        registered_command_names.append((item[0], item[3]))


def on_enable():
    global state, economy, service, command_handler, initialized
    if initialized:
        return
    log_info(u"Starting {0} v{1}".format(BountyConfig.PLUGIN_NAME, BountyConfig.VERSION))
    storage = JsonStorage(BountyConfig.DATA_FILE, BountyConfig.DEFAULT_STATE)
    state = BountyState(storage)
    state.save()
    economy = EconomyGateway()
    service = BountyService(state, economy)
    command_handler = BountyCommand(service, state, economy)
    unregister_events()
    register_event(PlayerDeathEvent, service.handle_death)
    register_event(InventoryClickEvent, on_bounty_inventory_click)
    register_event(InventoryCloseEvent, on_bounty_inventory_close)
    register_event(PlayerJoinEvent, on_bounty_player_join)
    register_commands()
    start_survival_timer()
    initialized = True
    log_info(u"Enabled.")


def on_disable():
    global initialized
    unregister_events()
    unregister_commands()
    stop_survival_timer()
    open_bounty_guis.clear()
    if state is not None:
        state.save()
    initialized = False
    log_info(u"Disabled.")


def start(script=None):
    on_enable()


def stop(script=None):
    on_disable()


if __name__ == "__main__" or "ps" in globals() or "command_manager" in globals():
    on_enable()

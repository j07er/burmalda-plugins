# -*- coding: utf-8 -*-
"""
===============================================================================
PySpigot Casino - ДИНАМИЧЕСКИЙ ДЖЕКПОТ И ПРИЯТНЫЕ ЗВУКИ (Paper 1.21.x)
===============================================================================
Команды казино:
  /casino <сумма> — Играть в слоты казино
  /jackpot, /casinobank — Просмотреть текущий банк джекпота
  /opjackpot [сумма] — Тестовый 100% ДЖЕКПОТ (Только для /op)
===============================================================================
"""

import os
import sys
import json
import time
import re
import random

# Совместимость unicode в Python 2 (Jython) и Python 3
try:
    unicode
except NameError:
    unicode = str

# Выставляем кодировку UTF-8 в Jython
try:
    if hasattr(sys, "setdefaultencoding"):
        reload(sys)
        sys.setdefaultencoding("utf-8")
except Exception:
    pass

# -----------------------------------------------------------------------------
# ИМПОРТ BUKKIT / PYSPIGOT / JAVA ARRAYLIST
# -----------------------------------------------------------------------------
try:
    from org.bukkit import Bukkit, ChatColor, Sound
    from org.bukkit.command import Command, TabCompleter
    BUKKIT_AVAILABLE = True
except ImportError:
    BUKKIT_AVAILABLE = False
    Command = object
    TabCompleter = object

try:
    from java.lang import String as JavaString, StringBuilder, Runnable, System, Throwable
    from java.util import UUID as JavaUUID
    JAVA_STRING_AVAILABLE = True
except ImportError:
    JAVA_STRING_AVAILABLE = False
    JavaString = str
    StringBuilder = None
    Runnable = object
    System = None
    JavaUUID = None
    Throwable = Exception

try:
    from java.util import ArrayList
except ImportError:
    ArrayList = list


# -----------------------------------------------------------------------------
# ОПРЕДЕЛЕНИЕ РАБОЧЕЙ ДИРЕКТОРИИ
# -----------------------------------------------------------------------------
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


# -----------------------------------------------------------------------------
# ГЛОБАЛЬНЫЕ НАСТРОЙКИ КАЗИНО И ASCII UNICODE ESCAPES
# -----------------------------------------------------------------------------
class CasinoConfig:
    PLUGIN_NAME = u"SmartY-Casino"
    VERSION = u"2.4.0"

    MIN_CASINO_BET = 10.0
    BASE_JACKPOT = 1000.0
    CURRENCY_SYMBOL = u"$"
    PERM_CASINO = u"pyspigot.economy.casino"
    PREFIX = u"&6&l[\u041a\u0430\u0437\u0438\u043d\u043e]&r "

    # ФИКС "3 джекпота за 5 минут": раньше шанс считался от доли ставки к банку
    # (bet/bank >= 20% -> 3% шанс НА КАЖДЫЙ СПИН) — игрок сам выбирал себе шанс
    # размером ставки. Теперь: (1) шанс ФИКСИРОВАН и не зависит
    # от размера ставки, (2) джекпот в принципе НЕВОЗМОЖНО выиграть,
    # пока банк не накопится до JACKPOT_MIN_BANK_TO_WIN — как договаривались,
    # "следующий джекпот только при достижении банка от 20000$".
    JACKPOT_MIN_BANK_TO_WIN = 20000.0
    JACKPOT_FIXED_CHANCE = 0.0005  # 0.05% на спин, ТОЛЬКО когда банк >= порога

    SCRIPT_DIR = get_script_dir()
    DATA_DIR = os.path.join(SCRIPT_DIR, "data")
    DATA_FILE = os.path.join(DATA_DIR, "economy.json")

    MESSAGES = {
        "casino_usage": u"{prefix}&c\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: &f/casino <\u0441\u0443\u043c\u043c\u043e>",
        "casino_min_bet": u"{prefix}&c\u041c\u0438\u043d\u0438\u043c\u0430\u043b\u044c\u043d\u0430\u044f \u0441\u0442\u0430\u0432\u043a\u0430: &e{min_bet}",
        "casino_already_playing": u"{prefix}&c\u0412\u044b \u0443\u0436\u0435 \u043a\u0440\u0443\u0442\u0438\u0442\u0435 \u0441\u043b\u043e\u0442\u044b! \u0414\u043e\u0436\u0434\u0438\u0442\u0435\u0441\u044c \u043e\u043a\u043e\u043d\u0447\u0430\u043d\u0438\u044f.",
        "casino_insufficient_funds": u"{prefix}&c\u0423 \u0432\u0430\u0441 \u043d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u0441\u0440\u0435\u0434\u0441\u0442\u0432! \u0422\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044f: &e{formatted_amount}",
        "casino_lose": u"{prefix}&c\u0412\u044b \u043f\u0440\u043e\u0438\u0433\u0440\u0430\u043b\u0438 &6{formatted_amount}&c. \u041f\u043e\u0432\u0435\u0437\u0435\u0442 \u0432 \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0440\u0430\u0437!",
        "casino_win": u"{prefix}&a\u0412\u044b \u0432\u044b\u0438\u0433\u0440\u0430\u043b\u0438 &e{formatted_amount} &a(x{mult})!",
        "casino_jackpot_win": u"{prefix}&6&l\u0412\u042B \u0421\u041e\u0420\u0412\u0410\u041b\u0418 \u0414\u0416\u0415\u041a\u041f\u041e\u0422: &e{formatted_amount}&6&l!",
        "casino_jackpot_broadcast": u"&6&l\u2605 [\u041a\u0410\u0417\u0418\u041d\u041e] &e\u0418\u0433\u0440\u043e\u043a &f{player} &e\u0441\u043e\u0440\u0432\u0430\u043b &6\u0414\u0416\u0415\u041a\u041f\u041e\u0422 &a{formatted_amount}&e!&r",
        "casino_balance_after": u"{prefix}&7\u0412\u0430\u0448 \u0442\u0435\u043a\u0443\u0449\u0438\u0439 \u0431\u0430\u043b\u0430\u043d\u0441: &e{formatted_balance}",
        "jackpot_info": u"{prefix}&7\u0422\u0435\u043a\u0443\u0449\u0438\u0439 \u043d\u0430\u043a\u043e\u043f\u043b\u0435\u043d\u043d\u044b\u0439 \u0434\u0436\u0435\u043a\u043f\u043e\u0442: &e{formatted_amount}",
        "jackpot_title": u"&6\u2605 \u0414\u0416\u0415\u041a\u041f\u041e\u0422 \u2605",
        "jackpot_subtitle": u"&7\u0418\u0433\u0440\u043e\u043a &f{player} &7\u0437\u0430\u0431\u0440\u0430\u043b &a{formatted_amount}&7!",
        "invalid_amount": u"{prefix}&c\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u0443\u044e \u0441\u0433\u043c\u043c\u0443!",
        "no_permission": u"{prefix}&c\u0423 \u0432\u0430\u0441 \u043d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u043f\u0440\u0430\u0432!"
    }


SLOT_SYMBOLS = [u"7", u"\u2666", u"\u2605", u"\u2606", u"\u25c6"]
active_casino_players = set()


# -----------------------------------------------------------------------------
# ПРЕОБРАЗОВАНИЕ В UNICODE И JAVA STRING
# -----------------------------------------------------------------------------
def to_unicode(text):
    """Преобразование любых объектов Java / Python в Unicode напрямую через UTF-8 байты Java."""
    if text is None:
        return u""
    if isinstance(text, unicode):
        return text

    if JAVA_STRING_AVAILABLE and hasattr(text, "getBytes"):
        try:
            utf8_bytes = text.getBytes("UTF-8")
            return unicode(utf8_bytes, "utf-8")
        except Exception:
            pass

    if isinstance(text, str):
        try:
            return text.decode("utf-8")
        except Exception:
            try:
                return text.decode("cp1251")
            except Exception:
                return unicode(text, "utf-8", "ignore")

    return unicode(str(text))


try:
    from jarray import array
    JARRAY_AVAILABLE = True
except ImportError:
    JARRAY_AVAILABLE = False


def to_java_string(text):
    """Конвертация Python юникода в нативный JavaString через StringBuilder.appendCodePoint."""
    if text is None:
        return JavaString("") if JAVA_STRING_AVAILABLE else u""
    if JAVA_STRING_AVAILABLE:
        if isinstance(text, JavaString):
            return text
        u_text = to_unicode(text)
        if StringBuilder is not None:
            try:
                sb = StringBuilder()
                for ch in u_text:
                    sb.appendCodePoint(ord(ch))
                return sb.toString()
            except:
                pass
        try:
            return JavaString(u_text)
        except:
            pass
    return text


def build_java_list(items):
    """Преобразует список Python в java.util.ArrayList для PaperMC."""
    j_list = ArrayList()
    if items:
        for item in items:
            j_list.add(to_java_string(item))
    return j_list


def colorize(text):
    if not text:
        return u""
    u_text = to_unicode(text)
    if BUKKIT_AVAILABLE:
        j_str = to_java_string(u_text)
        res = ChatColor.translateAlternateColorCodes('&', j_str)
        return to_unicode(res)
    else:
        return re.sub(r'&([0-9a-fk-or])', u'', u_text, flags=re.IGNORECASE)


def safe_console_send(text):
    colored_text = colorize(text)
    if BUKKIT_AVAILABLE:
        try:
            java_msg = to_java_string(colored_text)
            Bukkit.getConsoleSender().sendMessage(java_msg)
            return
        except Exception:
            pass

    try:
        clean = re.sub(r'[\xa7&][0-9a-fk-or]', u'', to_unicode(text))
        if sys.version_info[0] >= 3:
            print("[SmartY-Casino] " + clean)
        else:
            print("[SmartY-Casino] " + clean.encode("utf-8", "replace"))
    except Exception:
        print("[SmartY-Casino] " + str(text))


def format_currency(amount):
    """Красивое форматирование сумм без десятичной точки для целых чисел."""
    try:
        val = float(amount)
        # ФИКС "jackpot nan$": раньше round(nan) в Jython 2.7 НЕ выбрасывал
        # исключение (в отличие от CPython), а "{:,.2f}".format(nan) тихо возвращал строку
        # "nan" — отсюда игроки видели "ВЫ СОРВАЛИ ДЖЕКПОТ: nan$". Теперь NaN/Infinity
        # отсекаются явно ДО любого форматирования, как и в других файлах.
        if val != val or val == float("inf") or val == float("-inf"):
            return u"0$"
        if val.is_integer() or abs(val - round(val)) < 0.001:
            formatted_int = str(int(round(val)))
            res = []
            for i, ch in enumerate(reversed(formatted_int)):
                if i > 0 and i % 3 == 0:
                    res.append(" ")
                res.append(ch)
            formatted = to_unicode("".join(reversed(res)))
        else:
            formatted = to_unicode("{:,.2f}".format(val).replace(",", " "))
        
        cleaned = to_unicode(formatted).replace(u"\u00a0", u" ").replace(u"\u00c2", u"").strip()
        return cleaned + u"$"
    except (ValueError, TypeError):
        return u"0$"


def log_info(text):
    safe_console_send(u"&6[SmartY-Casino] &a[INFO] " + to_unicode(text))


def log_error(text):
    safe_console_send(u"&6[SmartY-Casino] &c[ERROR] " + to_unicode(text))


def send_casino_msg(sender, key, **kwargs):
    if key in CasinoConfig.MESSAGES:
        raw = CasinoConfig.MESSAGES[key]
    else:
        raw = to_unicode(key)

    fmt_args = {"prefix": CasinoConfig.PREFIX, "min_bet": format_currency(CasinoConfig.MIN_CASINO_BET)}
    for k, v in kwargs.items():
        fmt_args[k] = to_unicode(v)

    try:
        text = raw.format(**fmt_args)
    except Exception:
        text = raw

    colored = colorize(text)
    if sender is not None:
        if hasattr(sender, "sendMessage"):
            sender.sendMessage(to_java_string(colored))
        else:
            safe_console_send(colored)


def sync_player_commands():
    """Синхронизирует команды с клиентами Minecraft в PaperMC 1.21."""
    if not BUKKIT_AVAILABLE:
        return
    try:
        server = Bukkit.getServer()
        if hasattr(server, "syncCommands"):
            server.syncCommands()

        for p in Bukkit.getOnlinePlayers():
            if hasattr(p, "updateCommands"):
                p.updateCommands()
    except Exception:
        pass


# -----------------------------------------------------------------------------
# ИЗВЛЕЧЕНИЕ UUID И ИМЕНИ ИГРОКА
# -----------------------------------------------------------------------------
def get_sender_uuid_and_name(sender):
    if sender is None:
        return None, u"Console"

    name = u"Unknown"
    if hasattr(sender, "getName"):
        try:
            name = to_unicode(sender.getName())
        except Exception:
            pass

    uuid_str = None
    if hasattr(sender, "getUniqueId"):
        try:
            u_obj = sender.getUniqueId()
            if u_obj:
                uuid_str = str(u_obj)
        except Exception:
            pass

    if not uuid_str and name != u"Unknown" and name != u"Console":
        try:
            eco = get_economy_manager()
            if eco:
                acc = eco.get_account_by_name(name)
                if acc:
                    uuid_str = acc.uuid
        except Exception:
            pass

    return uuid_str, name


# -----------------------------------------------------------------------------
# ЖИВАЯ ЕДИНАЯ СИНХРОНИЗАЦИЯ С ЭКОНОМИКОЙ (SYSTEM PROPERTIES SINGLETON)
# -----------------------------------------------------------------------------
def get_economy_manager():
    if JAVA_STRING_AVAILABLE and System is not None:
        try:
            inst = System.getProperties().get("PySpigot_EconomyManager")
            if inst:
                return inst
        except Exception:
            pass

    if "economy" in sys.modules:
        mod = sys.modules["economy"]
        if hasattr(mod, "EconomyManager"):
            return mod.EconomyManager()
    try:
        import economy
        return economy.EconomyManager()
    except Exception:
        pass
    return None


def _safe_float(value, default=0.0):
    u"""Защита от NaN/Infinity (фикс дыры бесплатных ставок /casino nan).
    Сравнения вида "x < NaN" или "x > NaN" всегда False в Python,
    поэтому проверки типа "bet < MIN_BET" и "balance < bet" молча
    пропускали NaN-ставки. Данная функция — единая точка санитаризации.
    """
    try:
        val = float(value)
    except (ValueError, TypeError):
        return default
    if val != val:  # NaN
        return default
    if val == float("inf") or val == float("-inf"):
        return default
    return val


class CasinoAccountManager(object):
    """Менеджер счетов казино, работающий напрямую через общий EconomyManager."""
    def __init__(self):
        eco = get_economy_manager()
        if eco:
            self.jackpot_bank = _safe_float(eco.jackpot_bank, default=CasinoConfig.BASE_JACKPOT)
        else:
            self.jackpot_bank = float(CasinoConfig.BASE_JACKPOT)

    def get_balance(self, uuid_str):
        eco = get_economy_manager()
        if eco:
            return eco.get_balance(uuid_str)
        return 100.0

    def modify_balance(self, uuid_str, amount_delta, player_name="Unknown"):
        u"""
        ФИКС: раньше результат eco.withdraw() игнорировался — игра
        продолжалась, даже если списание ставки ФАКТИЧЕСКИ НЕ ПРОШЛО
        (например ставка = NaN). Теперь возвращаем флаг успеха, чтобы
        вызывающий код мог отменить игру при отказе.
        """
        eco = get_economy_manager()
        if eco:
            if amount_delta > 0:
                eco.deposit(uuid_str, amount_delta, player_name)
                return True, eco.get_balance(uuid_str)
            elif amount_delta < 0:
                ok = eco.withdraw(uuid_str, abs(amount_delta))
                return ok, eco.get_balance(uuid_str)
            return True, eco.get_balance(uuid_str)
        return True, 100.0

    def add_to_jackpot(self, amount):
        eco = get_economy_manager()
        if eco:
            eco.add_to_jackpot(amount)
            self.jackpot_bank = _safe_float(eco.jackpot_bank, default=self.jackpot_bank)

    def claim_jackpot(self, bet):
        """ПРИ ПОБЕДЕ: ВЫПЛАТА = СТАВКАИГРОКА + ВЕСЬ НАКОПЛЕННЫЙ БАНК ДЖЕКПОТА!"""
        eco = get_economy_manager()
        bet = _safe_float(bet, default=0.0)
        if eco:
            payout = eco.claim_jackpot(bet)
            self.jackpot_bank = _safe_float(eco.jackpot_bank, default=0.0)
            return round(_safe_float(payout, default=0.0), 2)
        return round(bet + self.jackpot_bank, 2)

    def preview_jackpot_payout(self, bet):
        """Расчет джекпота ДЛЯ ОПЕРАТОРОВ (/opjackpot) БЕЗ ОБНУЛЕНИЯ БАНКА."""
        bet = _safe_float(bet, default=0.0)
        eco = get_economy_manager()
        bank = _safe_float(eco.jackpot_bank if eco else self.jackpot_bank, default=0.0)
        return round(bet + bank, 2)

    def is_jackpot_eligible(self):
        u"""
        ФИКС "3 джекпота за 5 минут": раньше шанс джекпота зависел
        от доли ставки от банка — игрок сам выбирал себе шанс размером ставки
        (до 3% НА КАЖДЫЙ спин). Теперь джекпот ФИКСИРОВАННОй низкой
        вероятности и только при условии, что банк уже накопился до
        JACKPOT_MIN_BANK_TO_WIN (по договорённости: 20000$). Сразу после выплаты
        джекпота банк обнуляется и следующий джекпот становится невозможен,
        пока банк снова не накопится до порога (от проигрышей игроков).
        """
        eco = get_economy_manager()
        bank = _safe_float(eco.jackpot_bank if eco else self.jackpot_bank, default=0.0)
        return bank >= CasinoConfig.JACKPOT_MIN_BANK_TO_WIN

    def calculate_jackpot_chance(self, bet):
        u"""
        ФИКСИРОВАННЫЙ низкий шанс джекпота, не зависит от размера
        ставки или банка (см. is_jackpot_eligible() для условия минимального банка).
        Старая динамическая формула (bet/bank) удалена как эксплойт.
        """
        if not self.is_jackpot_eligible():
            return 0.0
        return CasinoConfig.JACKPOT_FIXED_CHANCE


# -----------------------------------------------------------------------------
# 100% НАДЕЖНЫЕ ФЕЙЕРВЕРКИ И ЧАСТИЦЫ ДЖЕКПОТА
# -----------------------------------------------------------------------------
def spawn_jackpot_celebration_effects(player):
    if not BUKKIT_AVAILABLE or player is None:
        return

    # 1. Золотые частицы тотема бессмертия без иконки предмета
    try:
        from org.bukkit import Particle
        loc = player.getLocation().add(0, 1.0, 0)
        world = player.getWorld()

        particle_enum = None
        for p_name in ["TOTEM_OF_UNDYING", "TOTEM", "FLASH"]:
            try:
                particle_enum = Particle.valueOf(p_name)
                break
            except Exception:
                pass

        if particle_enum:
            world.spawnParticle(particle_enum, loc, 250, 1.0, 1.2, 1.0, 0.4)

        try:
            star_enum = Particle.valueOf("END_ROD")
            world.spawnParticle(star_enum, loc, 80, 0.8, 1.0, 0.8, 0.15)
        except Exception:
            pass

    except Exception as e:
        log_error(u"Error spawning particles: {0}".format(e))

    # 2. Спавн салютов через Firework.class
    try:
        from org.bukkit.entity import Firework
        from org.bukkit import Color, FireworkEffect
        loc = player.getLocation().add(0, 1.0, 0)
        world = player.getWorld()

        color_palettes = [
            [Color.RED, Color.GOLD, Color.YELLOW],
            [Color.AQUA, Color.BLUE, Color.FUCHSIA],
            [Color.GREEN, Color.LIME, Color.YELLOW]
        ]

        offsets = [(0.0, 0.0), (2.0, 2.0), (-2.0, -2.0)]
        for idx, (ox, oz) in enumerate(offsets):
            fw_loc = loc.clone().add(ox, 0.2, oz)
            fw = world.spawn(fw_loc, Firework)
            meta = fw.getFireworkMeta()
            builder = FireworkEffect.builder()

            palette = color_palettes[idx % len(color_palettes)]
            builder.withColor(palette[0], palette[1], palette[2])
            builder.withFade(Color.WHITE, Color.PURPLE)
            getattr(builder, "with")(FireworkEffect.Type.BALL_LARGE)
            builder.trail(True)
            builder.flicker(True)
            meta.addEffect(builder.build())
            meta.setPower(1)
            fw.setFireworkMeta(meta)

    except Exception as e:
        log_error(u"Error spawning fireworks: {0}".format(e))


def safe_play_sound(player, sound_candidates, volume=1.0, pitch=1.0):
    """Воспроизводит ЧИСТЫЙ ПРИЯТНЫЙ ЗВУК НОТНОГО БЛОКА (BLOCK_NOTE_BLOCK_PLING)."""
    if not BUKKIT_AVAILABLE or player is None:
        return
    for s_name in sound_candidates:
        try:
            sound_enum = Sound.valueOf(s_name)
            player.playSound(player.getLocation(), sound_enum, float(volume), float(pitch))
            return
        except Exception:
            pass


def play_sound_all(sound_candidates, volume=1.0, pitch=1.0):
    if not BUKKIT_AVAILABLE:
        return
    try:
        for p in Bukkit.getOnlinePlayers():
            safe_play_sound(p, sound_candidates, volume, pitch)
    except Exception:
        pass


def send_title_all(title_text, subtitle_text, fade_in=10, stay=80, fade_out=20):
    if not BUKKIT_AVAILABLE:
        return
    try:
        j_title = to_java_string(colorize(title_text))
        j_subtitle = to_java_string(colorize(subtitle_text))
        for p in Bukkit.getOnlinePlayers():
            if hasattr(p, "sendTitle"):
                p.sendTitle(j_title, j_subtitle, fade_in, stay, fade_out)
    except Exception as e:
        log_error(u"Error in send_title_all: {0}".format(e))


def broadcast_casino_msg(key, **kwargs):
    if not BUKKIT_AVAILABLE:
        return
    try:
        for p in Bukkit.getOnlinePlayers():
            send_casino_msg(p, key, **kwargs)
    except Exception:
        pass


def get_pyspigot_plugin():
    if BUKKIT_AVAILABLE:
        try:
            return Bukkit.getPluginManager().getPlugin("PySpigot")
        except Exception:
            pass
    return None


# -----------------------------------------------------------------------------
# ЛОГИКА АНИМАЦИИ СЛОТОВ И ИТОГОВ ИГРЫ
# -----------------------------------------------------------------------------
def finish_casino_game(player, bet, outcome, multiplier, payout, final_symbols, reset_bank=True):
    player_uuid, player_name = get_sender_uuid_and_name(player)
    manager = CasinoAccountManager()

    if player_uuid:
        active_casino_players.discard(player_uuid)

    if outcome == "LOSE":
        manager.add_to_jackpot(bet)
        safe_play_sound(player, ["BLOCK_NOTE_BLOCK_PLING", "NOTE_PLING"], 1.0, 0.6)
        send_casino_msg(player, "casino_lose", formatted_amount=format_currency(bet))

    elif outcome == "WIN":
        if player_uuid:
            manager.modify_balance(player_uuid, payout, player_name)  # выигрыш всегда начисляется (deposit всегда успешен)
        safe_play_sound(player, ["BLOCK_NOTE_BLOCK_PLING", "NOTE_PLING"], 1.0, 1.4)
        send_casino_msg(player, "casino_win", formatted_amount=format_currency(payout), mult=multiplier)

    elif outcome == "JACKPOT":
        if player_uuid:
            manager.modify_balance(player_uuid, payout, player_name)

        # 1. Торжественные звуки
        play_sound_all(["UI_TOAST_CHALLENGE_COMPLETE", "ENTITY_FIREWORK_ROCKET_LARGE_BLAST"], 1.0, 1.0)

        # 2. Визуал-эффекты
        spawn_jackpot_celebration_effects(player)

        # 3. Неназойливый заголовок
        t_title = CasinoConfig.MESSAGES["jackpot_title"]
        t_sub = CasinoConfig.MESSAGES["jackpot_subtitle"].format(player=player_name, formatted_amount=format_currency(payout))
        send_title_all(t_title, t_sub, 10, 80, 20)

        # 4. Рассылка в чат
        broadcast_casino_msg("casino_jackpot_broadcast", player=player_name, formatted_amount=format_currency(payout))
        send_casino_msg(player, "casino_jackpot_win", formatted_amount=format_currency(payout))

    # Вывод ТОЧНОГО обновленного баланса после игры
    new_balance = manager.get_balance(player_uuid) if player_uuid else 0.0
    send_casino_msg(player, "casino_balance_after", formatted_balance=format_currency(new_balance))


def start_slot_animation(player, bet, force_jackpot=False, reset_bank=True):
    player_uuid, player_name = get_sender_uuid_and_name(player)

    # ФИКС: санитизация ставки от NaN/Infinity до всякой арифметики.
    bet = _safe_float(bet, default=0.0)

    if player_uuid:
        active_casino_players.add(player_uuid)

    manager = CasinoAccountManager()

    # Списываем ставку перед прокруткой только при обычной игре.
    # ФИКС: раньше результат списания игнорировался — если withdraw() отказывал
    # (например из-за NaN-ставки или гонки баланса между /casino и анимацией),
    # игрок всё равно получал бесплатную прокрутку с шансом на выигрыш.
    if not force_jackpot and player_uuid:
        withdrawn_ok, _ = manager.modify_balance(player_uuid, -bet, player_name)
        if not withdrawn_ok:
            active_casino_players.discard(player_uuid)
            send_casino_msg(player, "casino_insufficient_funds", formatted_amount=format_currency(bet))
            return

    if force_jackpot:
        outcome = "JACKPOT"
        multiplier = 50.0
        payout = manager.preview_jackpot_payout(bet)
        final_symbols = [u"7", u"7", u"7"]
    else:
        # ФИКСИРОВАННЫЙ низкий шанс джекпота; джекпот вообще недоступен,
        # пока банк не достиг JACKPOT_MIN_BANK_TO_WIN (см. CasinoConfig).
        jackpot_chance = manager.calculate_jackpot_chance(bet)

        rand = random.random()
        if rand < jackpot_chance:
            outcome = "JACKPOT"
            multiplier = 50.0
            payout = manager.claim_jackpot(bet)
            final_symbols = [u"7", u"7", u"7"]

        elif rand < (jackpot_chance + 0.30):  # ~30% Выигрыш
            outcome = "WIN"
            win_rand = random.random()
            if win_rand < 0.05:
                multiplier = 5.0  # Супер выигрыш x5
                final_symbols = [u"\u2666", u"\u2666", u"\u2666"]
            elif win_rand < 0.30:
                multiplier = 3.0  # Большой выигрыш x3
                final_symbols = [u"\u2605", u"\u2605", u"\u2605"]
            else:
                multiplier = 2.0  # Обычный выигрыш x2
                final_symbols = [u"\u2606", u"\u2606", u"\u25c6"]
            payout = round(bet * multiplier, 2)

        else:  # Проигрыш
            outcome = "LOSE"
            multiplier = 0.0
            payout = 0.0
            final_symbols = [random.choice(SLOT_SYMBOLS), random.choice(SLOT_SYMBOLS), random.choice(SLOT_SYMBOLS)]
            if final_symbols[0] == final_symbols[1] == final_symbols[2]:
                final_symbols[2] = u"7" if final_symbols[0] != u"7" else u"\u2666"

    plugin = get_pyspigot_plugin()
    if not plugin or not BUKKIT_AVAILABLE:
        finish_casino_game(player, bet, outcome, multiplier, payout, final_symbols, reset_bank)
        return

    class SpinRunnable(Runnable):
        def __init__(self):
            self.step = 0
            self.task_id = -1

        def run(self):
            try:
                self.step += 1

                if not player.isOnline():
                    if self.task_id != -1:
                        Bukkit.getScheduler().cancelTask(self.task_id)
                    if player_uuid:
                        active_casino_players.discard(player_uuid)
                    return

                # ПРИЯТНЫЕ ЗВУКИ НОТНОГО БЛОКА (BLOCK_NOTE_BLOCK_PLING)
                # Шаги 1-5: Быстрая прокрутка
                if self.step <= 5:
                    r_syms = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
                    spin_text = u"&e&l[ &6{0} &e| &6{1} &e| &6{2} &e&l]".format(r_syms[0], r_syms[1], r_syms[2])
                    if hasattr(player, "sendTitle"):
                        player.sendTitle(to_java_string(""), to_java_string(colorize(spin_text)), 0, 15, 0)
                    safe_play_sound(player, ["BLOCK_NOTE_BLOCK_PLING", "NOTE_PLING"], 0.7, 0.8 + (self.step * 0.08))

                # Шаг 6: Фиксация 1-го барабана
                elif self.step == 6:
                    r_syms = [final_symbols[0], random.choice(SLOT_SYMBOLS), random.choice(SLOT_SYMBOLS)]
                    spin_text = u"&e&l[ &6{0} &e| &6{1} &e| &6{2} &e&l]".format(r_syms[0], r_syms[1], r_syms[2])
                    if hasattr(player, "sendTitle"):
                        player.sendTitle(to_java_string(""), to_java_string(colorize(spin_text)), 0, 15, 0)
                    safe_play_sound(player, ["BLOCK_NOTE_BLOCK_PLING", "NOTE_PLING"], 0.8, 1.2)

                # Шаг 7: Фиксация 2-го барабана
                elif self.step == 7:
                    r_syms = [final_symbols[0], final_symbols[1], random.choice(SLOT_SYMBOLS)]
                    spin_text = u"&e&l[ &6{0} &e| &6{1} &e| &6{2} &e&l]".format(r_syms[0], r_syms[1], r_syms[2])
                    if hasattr(player, "sendTitle"):
                        player.sendTitle(to_java_string(""), to_java_string(colorize(spin_text)), 0, 15, 0)
                    safe_play_sound(player, ["BLOCK_NOTE_BLOCK_PLING", "NOTE_PLING"], 0.9, 1.4)

                # Шаг 8: Окончательная фиксация всех 3 барабанов
                elif self.step == 8:
                    spin_text = u"&e&l[ &6{0} &e| &6{1} &e| &6{2} &e&l]".format(final_symbols[0], final_symbols[1], final_symbols[2])
                    if hasattr(player, "sendTitle"):
                        player.sendTitle(to_java_string(""), to_java_string(colorize(spin_text)), 0, 30, 5)
                    safe_play_sound(player, ["BLOCK_NOTE_BLOCK_PLING", "NOTE_PLING"], 1.0, 1.6)

                # Шаг 10: Торжественный замер символов перед выплатным таском
                elif self.step >= 10:
                    if self.task_id != -1:
                        Bukkit.getScheduler().cancelTask(self.task_id)
                    finish_casino_game(player, bet, outcome, multiplier, payout, final_symbols, reset_bank)

            except Exception as e:
                log_error(u"Error in SpinRunnable: {0}".format(e))
                if self.task_id != -1:
                    Bukkit.getScheduler().cancelTask(self.task_id)
                if player_uuid:
                    active_casino_players.discard(player_uuid)

    runner = SpinRunnable()
    try:
        task_obj = Bukkit.getScheduler().runTaskTimer(plugin, runner, 0, 3)
        runner.task_id = task_obj.getTaskId()
    except Exception as e:
        log_error(u"Could not start runTaskTimer in casino: {0}".format(e))
        finish_casino_game(player, bet, outcome, multiplier, payout, final_symbols, reset_bank)


# -----------------------------------------------------------------------------
# ИЗВЛЕЧЕНИЕ АРГУМЕНТОВ И ОБРАБОТЧИКИ КОМАНД КАЗИНО
# -----------------------------------------------------------------------------
def parse_cmd_args(*args):
    if len(args) == 0:
        return None, []
    sender = args[0]
    if len(args) == 1:
        return sender, []

    last_arg = args[-1]
    if isinstance(last_arg, (list, tuple)):
        return sender, [to_unicode(a) for a in last_arg]

    return sender, [to_unicode(a) for a in args[1:]]


def cmd_casino(*args):
    sender, cmd_args = parse_cmd_args(*args)
    manager = CasinoAccountManager()

    uuid_str, name = get_sender_uuid_and_name(sender)
    if not uuid_str and (name == u"Console" or name == u"Unknown"):
        send_casino_msg(sender, "no_permission")
        return True

    if len(cmd_args) < 1:
        send_casino_msg(sender, "casino_usage")
        return True

    try:
        bet = float(cmd_args[0])
    except ValueError:
        send_casino_msg(sender, "invalid_amount")
        return True

    # ФИКС: NaN/Infinity раньше проходили ОБЕ проверки ниже молча
    # (сравнения с NaN всегда False), что позволяло играть бесплатно
    # и портило банк джекпота в NaN навсегда. Сейчас такая ставка отклоняется явно.
    if bet != bet or bet == float("inf") or bet == float("-inf"):
        send_casino_msg(sender, "invalid_amount")
        return True

    if bet < CasinoConfig.MIN_CASINO_BET:
        send_casino_msg(sender, "casino_min_bet")
        return True

    if uuid_str in active_casino_players:
        send_casino_msg(sender, "casino_already_playing")
        return True

    bal = manager.get_balance(uuid_str)
    if bal < bet:
        send_casino_msg(sender, "casino_insufficient_funds", formatted_amount=format_currency(bet))
        return True

    start_slot_animation(sender, bet, force_jackpot=False, reset_bank=True)
    return True


def cmd_jackpot(*args):
    """
    Просмотр банка джекпота для всех игроков.
    """
    sender, cmd_args = parse_cmd_args(*args)
    manager = CasinoAccountManager()
    send_casino_msg(sender, "jackpot_info", formatted_amount=format_currency(manager.jackpot_bank))
    return True


def cmd_opjackpot(*args):
    """
    Спец-команда ТОЛЬКО для операторов (/op): /opjackpot [ставка]
    100% выигрыш ДЖЕКПОТА с салютом и золотыми частицами, при этом основной банк НЕ обнуляется.
    """
    sender, cmd_args = parse_cmd_args(*args)
    is_op = hasattr(sender, "isOp") and sender.isOp()
    if not is_op and BUKKIT_AVAILABLE:
        send_casino_msg(sender, "no_permission")
        return True

    bet = 100.0
    if len(cmd_args) >= 1:
        try:
            bet = float(cmd_args[0])
        except ValueError:
            bet = 100.0

    start_slot_animation(sender, bet, force_jackpot=True, reset_bank=False)
    return True


# -----------------------------------------------------------------------------
# УНИВЕРСАЛЬНЫЕ ТАБ-ОБРАБОТЧИКИ КАЗИНО (*args UNPACKING)
# -----------------------------------------------------------------------------
def get_cmd_args_from_args(args):
    cmd_args = []
    for a in reversed(args):
        if isinstance(a, (list, tuple)):
            cmd_args = [to_unicode(x) for x in a]
            break
        elif hasattr(a, "__iter__") and not isinstance(a, (str, unicode, type(to_java_string("")))):
            try:
                cmd_args = [to_unicode(x) for x in a]
                break
            except Exception:
                pass
    return cmd_args


def tab_casino(*args):
    cmd_args = get_cmd_args_from_args(args)

    if len(cmd_args) <= 1:
        prefix = cmd_args[0].lower() if len(cmd_args) == 1 else ""
        bets = ["10", "50", "100", "250", "500", "1000"]
        return build_java_list([b for b in bets if b.startswith(prefix)])
    return build_java_list([])


def tab_opjackpot(*args):
    cmd_args = get_cmd_args_from_args(args)

    if len(cmd_args) <= 1:
        prefix = cmd_args[0].lower() if len(cmd_args) == 1 else ""
        bets = ["100", "500", "1000", "5000"]
        return build_java_list([b for b in bets if b.startswith(prefix)])
    return build_java_list([])


# -----------------------------------------------------------------------------
# РЕГИСТРАЦИЯ КОМАНД КАЗИНО В BUKKIT И PYSPIGOT
# -----------------------------------------------------------------------------
if BUKKIT_AVAILABLE:
    class PyBukkitCasinoCommand(Command, TabCompleter):
        def __init__(self, name, description="", usage="", aliases=[], executor=None, completer=None):
            Command.__init__(self, name, description, usage, aliases)
            self.cmd_name = name
            self.executor = executor
            self.completer = completer

        def execute(self, sender, commandLabel, args):
            try:
                if self.executor:
                    return self.executor(sender, commandLabel, list(args))
            except Exception as e:
                log_error(u"Error executing /{0}: {1}".format(self.cmd_name, e))
                import traceback
                traceback.print_exc()
            return True

        def tabComplete(self, *args):
            if self.completer:
                try:
                    res = self.completer(*args)
                    if res is not None:
                        if isinstance(res, (list, tuple)):
                            return build_java_list(res)
                        return res
                except Exception as e:
                    log_error(u"Error in tabComplete: {0}".format(e))
            return build_java_list([])

        def onTabComplete(self, *args):
            return self.tabComplete(*args)
else:
    class PyBukkitCasinoCommand(object):
        def __init__(self, name, description="", usage="", aliases=[], executor=None, completer=None):
            self.cmd_name = name
            self.executor = executor
            self.completer = completer


def get_pyspigot_mgr(name):
    g = globals()
    if name in g:
        return g[name]
    if "ps" in g:
        ps_obj = g["ps"]
        getter = "get_" + name
        if hasattr(ps_obj, getter):
            return getattr(ps_obj, getter)()
        camel = "get" + "".join([w.capitalize() for w in name.split("_")])
        if hasattr(ps_obj, camel):
            return getattr(ps_obj, camel)()
    try:
        from com.github.pyspigot import PySpigot
        if name == "command_manager":
            return PySpigot.getCommandManager()
    except Exception:
        pass
    return None


def force_register_bukkit_command(fallback_prefix, cmd_obj, aliases=[]):
    """Прямая инъекция команды в Bukkit knownCommands с гарантированной привязкой TabCompleter."""
    if not BUKKIT_AVAILABLE:
        return
    try:
        server = Bukkit.getServer()
        cmap = None
        if hasattr(server, "getCommandMap"):
            cmap = server.getCommandMap()
        else:
            field = server.getClass().getDeclaredField("commandMap")
            field.setAccessible(True)
            cmap = field.get(server)

        if cmap:
            known_commands = None
            if hasattr(cmap, "getKnownCommands"):
                try:
                    known_commands = cmap.getKnownCommands()
                except Exception:
                    pass

            if known_commands is None:
                curr_cls = cmap.getClass()
                while curr_cls is not None and curr_cls != object:
                    try:
                        f = curr_cls.getDeclaredField("knownCommands")
                        f.setAccessible(True)
                        known_commands = f.get(cmap)
                        break
                    except Exception:
                        curr_cls = curr_cls.getSuperclass()

            if known_commands:
                name = cmd_obj.getName().lower()

                # Снимаем старую регистрацию
                keys_to_remove = []
                iterator = known_commands.keySet().iterator()
                while iterator.hasNext():
                    k = iterator.next()
                    k_str = str(k).lower()
                    if k_str == name or k_str.endswith(":" + name):
                        keys_to_remove.append(k)
                    for alias in aliases:
                        a_str = str(alias).lower()
                        if k_str == a_str or k_str.endswith(":" + a_str):
                            keys_to_remove.append(k)

                for k in keys_to_remove:
                    try:
                        old_cmd = known_commands.get(k)
                        if hasattr(old_cmd, "unregister"):
                            old_cmd.unregister(cmap)
                        known_commands.remove(k)
                    except Exception:
                        pass

                # Прямой форсированный ввод новых команд с TabCompleter
                known_commands.put(name, cmd_obj)
                known_commands.put(fallback_prefix + ":" + name, cmd_obj)

                for alias in aliases:
                    a_str = str(alias).lower()
                    alias_cmd = PyBukkitCasinoCommand(a_str, cmd_obj.getDescription(), cmd_obj.getUsage(), [], cmd_obj.executor, cmd_obj.completer)
                    known_commands.put(a_str, alias_cmd)
                    known_commands.put(fallback_prefix + ":" + a_str, alias_cmd)

    except Exception as e:
        log_error(u"Error force-registering Bukkit command: {0}".format(e))


registered_casino_commands = []   # (name, aliases) - для полного снятия при выгрузке,
                                   # т.к. эти команды внедрены напрямую в CommandMap в
                                   # обход command_manager PySpigot и PySpigot не может
                                   # их снять сам при /pyspigot unload.


def force_unregister_bukkit_command(fallback_prefix, name, aliases):
    """Симметрична force_register_bukkit_command - снимает команду и её алиасы
    из Bukkit CommandMap."""
    if not BUKKIT_AVAILABLE:
        return
    try:
        server = Bukkit.getServer()
        cmap = None
        if hasattr(server, "getCommandMap"):
            cmap = server.getCommandMap()
        else:
            field = server.getClass().getDeclaredField("commandMap")
            field.setAccessible(True)
            cmap = field.get(server)

        if cmap:
            known_commands = None
            if hasattr(cmap, "getKnownCommands"):
                try:
                    known_commands = cmap.getKnownCommands()
                except Exception:
                    pass

            if known_commands is None:
                curr_cls = cmap.getClass()
                while curr_cls is not None and curr_cls != object:
                    try:
                        f = curr_cls.getDeclaredField("knownCommands")
                        f.setAccessible(True)
                        known_commands = f.get(cmap)
                        break
                    except Exception:
                        curr_cls = curr_cls.getSuperclass()

            if known_commands:
                names = [name] + list(aliases)
                for item_name in names:
                    lowered = str(item_name).lower()
                    for key in [lowered, fallback_prefix + ":" + lowered]:
                        try:
                            old_command = known_commands.get(key)
                            if old_command is not None and hasattr(old_command, "unregister"):
                                old_command.unregister(cmap)
                            known_commands.remove(key)
                        except Exception:
                            pass
    except Exception as e:
        log_error(u"Error force-unregistering Bukkit command: {0}".format(e))


def unregister_casino_commands():
    for name, aliases in list(registered_casino_commands):
        force_unregister_bukkit_command("pyspigot-casino", name, aliases)
    del registered_casino_commands[:]
    sync_player_commands()


def register_casino_commands():
    commands_def = [
        ("casino", "Play casino slot machine", "/casino <bet>", [], cmd_casino, tab_casino),
        ("jackpot", "Check casino jackpot pool", "/jackpot", ["casinobank"], cmd_jackpot, None),
        ("opjackpot", "OP test 100% jackpot spin", "/opjackpot [bet]", ["adminjackpot", "jackpotwin"], cmd_opjackpot, tab_opjackpot),
    ]

    command_mgr = get_pyspigot_mgr("command_manager")
    script_obj = globals().get("script", None)
    if command_mgr:
        for item in commands_def:
            name, desc, usage, aliases, handler, tab_handler = item[0], item[1], item[2], item[3], item[4], item[5]
            try:
                if script_obj and hasattr(command_mgr, "registerCommand"):
                    if tab_handler:
                        command_mgr.registerCommand(script_obj, name, handler, tab_handler)
                    else:
                        command_mgr.registerCommand(script_obj, name, handler)
                elif hasattr(command_mgr, "registerCommand"):
                    if tab_handler:
                        command_mgr.registerCommand(name, handler, tab_handler)
                    else:
                        command_mgr.registerCommand(name, handler)
            except Exception:
                pass

    for item in commands_def:
        name, desc, usage, aliases, handler, tab_handler = item[0], item[1], item[2], item[3], item[4], item[5]
        cmd_obj = PyBukkitCasinoCommand(name, desc, usage, aliases, handler, tab_handler)
        force_register_bukkit_command("pyspigot-casino", cmd_obj, aliases)
        registered_casino_commands.append((name, aliases))

    log_info(u"Casino commands force-registered in Bukkit CommandMap (/casino, /jackpot, /opjackpot) with TabCompletion.")
    sync_player_commands()


# -----------------------------------------------------------------------------
# ЖИЗНЕННЫЙ ЦИКЛ СКРИПТА PYSPIGOT (LIFECYCLE HOOKS)
# -----------------------------------------------------------------------------
def on_enable():
    log_info(u"=== Starting {0} v{1} ===".format(CasinoConfig.PLUGIN_NAME, CasinoConfig.VERSION))
    try:
        register_casino_commands()
        log_info(u"{0} successfully enabled!".format(CasinoConfig.PLUGIN_NAME))
    except Exception as e:
        log_error(u"Critical error in casino on_enable: {0}".format(e))
        import traceback
        traceback.print_exc()


def on_disable():
    log_info(u"=== Disabling {0} ===".format(CasinoConfig.PLUGIN_NAME))
    unregister_casino_commands()


def start(script=None):
    on_enable()


def stop(script=None):
    # ВАЖНО: PySpigot вызывает автоматически именно stop() (не on_disable()) при
    # /pyspigot unload <script>. Раньше эта функция отсутствовала, и on_disable()
    # вообще ничего не делал (пустое тело) - команды /casino /jackpot /opjackpot,
    # внедрённые напрямую в CommandMap в обход command_manager, продолжали бы
    # работать даже после выгрузки скрипта.
    on_disable()


if __name__ == "__main__" or "ps" in globals() or "command_manager" in globals():
    on_enable()

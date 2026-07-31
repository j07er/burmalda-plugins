# -*- coding: utf-8 -*-
"""
SmartY Nuclear Bomb for PySpigot / Paper / Leaf 1.21.11.

Survival use:
  1. Craft the fissile core.
  2. Craft the detonation module.
  3. Craft the thermonuclear warhead.
  4. Hold Shift and press Q at least 18 blocks above the ground.

Commands:
  /nuke recipe
  /nuke status
  /nuke give [player]   (OP)
  /nuke cancel          (OP)
"""

import math
import random
import re
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
    from org.bukkit import (
        Bukkit,
        ChatColor,
        Color,
        Location,
        Material,
        NamespacedKey,
        Particle,
        Sound,
    )
    from org.bukkit.command import Command, TabCompleter
    from org.bukkit.enchantments import Enchantment
    from org.bukkit.entity import EntityType, LivingEntity, Player
    from org.bukkit.event import EventPriority, HandlerList, Listener
    from org.bukkit.event.block import BlockPlaceEvent
    from org.bukkit.event.inventory import CraftItemEvent
    from org.bukkit.event.player import PlayerDropItemEvent, PlayerJoinEvent
    from org.bukkit.inventory import ItemFlag, ItemStack, RecipeChoice, ShapedRecipe
    from org.bukkit.persistence import PersistentDataType
    from org.bukkit.plugin import EventExecutor
    from org.bukkit.potion import PotionEffect, PotionEffectType
    from org.bukkit.util import Transformation, Vector
    from org.joml import Quaternionf, Vector3f
    from java.lang import Float, Runnable, String as JavaString, StringBuilder, System
    from java.util import ArrayList
    BUKKIT_AVAILABLE = True
except ImportError:
    Bukkit = None
    ChatColor = None
    Color = None
    Location = None
    Material = None
    NamespacedKey = None
    Particle = None
    Sound = None
    Command = object
    TabCompleter = object
    Enchantment = None
    EntityType = None
    LivingEntity = object
    Player = object
    EventPriority = None
    HandlerList = None
    Listener = object
    BlockPlaceEvent = None
    CraftItemEvent = None
    PlayerDropItemEvent = None
    PlayerJoinEvent = None
    ItemFlag = None
    ItemStack = None
    RecipeChoice = None
    ShapedRecipe = None
    PersistentDataType = None
    EventExecutor = object
    PotionEffect = None
    PotionEffectType = None
    Transformation = None
    Vector = None
    Quaternionf = None
    Vector3f = None
    Float = float
    Runnable = object
    JavaString = str
    StringBuilder = None
    System = None
    ArrayList = list
    BUKKIT_AVAILABLE = False


class NukeConfig(object):
    PLUGIN_NAME = u"SmartY-Nuclear"
    VERSION = u"1.0.0"
    PREFIX = u"&8[&c☢&8] &r"

    MIN_DROP_HEIGHT = 18
    MAX_GROUND_SCAN = 160
    IMPACT_COUNTDOWN_SECONDS = 10
    GLOBAL_COOLDOWN_SECONDS = 120
    SPAWN_PROTECTION_RADIUS = 192
    MAX_FALL_SECONDS = 30

    EXPLOSION_POWER = 144.0
    BLOCK_EXPLOSION_POWER = 16.0
    DEEP_BLASTS = ()
    BREAK_BLOCKS = True
    SET_FIRE = True
    LETHAL_RADIUS = 300.0
    SHOCKWAVE_RADIUS = 4000.0
    FLASH_RADIUS = 4500.0
    SHOCKWAVE_ENTITY_BATCH_SIZE = 48

    CRATER_RADIUS = 64
    CRATER_DEPTH = 36
    CRATER_ABOVE_HEIGHT = 48
    CRATER_BLOCKS_PER_TICK = 800
    CRATER_MIN_BLOCKS_PER_TICK = 80
    CRATER_SCANS_PER_TICK = 5000
    CRATER_TIME_BUDGET_MS = 10.0
    CRATER_PROTECTED_MATERIALS = (
        "BEDROCK",
        "BARRIER",
        "COMMAND_BLOCK",
        "CHAIN_COMMAND_BLOCK",
        "REPEATING_COMMAND_BLOCK",
        "STRUCTURE_BLOCK",
        "JIGSAW",
        "END_PORTAL",
        "END_PORTAL_FRAME",
    )

    MUSHROOM_DURATION_STEPS = 126
    MUSHROOM_PERIOD_TICKS = 5
    MUSHROOM_STEM_HEIGHT = 105.0
    MUSHROOM_CAP_RADIUS = 164.0
    MUSHROOM_GROUND_RING_RADIUS = 308.0

    NAMESPACE = "smarty_nuclear"
    KIND_CORE = "fissile_core"
    KIND_INITIATOR = "detonation_module"
    KIND_NUKE = "thermonuclear_warhead"


registered_listeners = []
registered_commands = {}
registered_recipe_keys = []
active_payloads = {}
active_craters = {}
scheduled_task_ids = set()
particle_cache = {}
missing_advancement_warnings = set()
last_launch_ms = 0
initialized = False


def to_unicode(value):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    if hasattr(value, "getBytes"):
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
                pass
    return unicode(str(value))


def to_java_string(value):
    text = to_unicode(value)
    if not BUKKIT_AVAILABLE:
        return text
    if isinstance(text, JavaString):
        return text
    if StringBuilder is not None:
        try:
            builder = StringBuilder()
            for char in text:
                builder.appendCodePoint(ord(char))
            return builder.toString()
        except Exception:
            pass
    try:
        return JavaString(text)
    except Exception:
        return text


def build_java_list(values):
    if not BUKKIT_AVAILABLE:
        return list(values)
    result = ArrayList()
    for value in values:
        result.add(to_java_string(value))
    return result


def colorize(value):
    text = to_unicode(value)
    if BUKKIT_AVAILABLE and ChatColor is not None:
        try:
            return to_unicode(
                ChatColor.translateAlternateColorCodes("&", to_java_string(text))
            )
        except Exception:
            pass
    return re.sub(r"&[0-9a-fk-or]", u"", text, flags=re.IGNORECASE)


def send_message(target, value):
    message = colorize(value)
    if BUKKIT_AVAILABLE and target is not None:
        try:
            target.sendMessage(to_java_string(message))
            return
        except Exception:
            pass
    print("[SmartY-Nuclear] " + to_unicode(message))


def log_info(value):
    if BUKKIT_AVAILABLE:
        send_message(
            Bukkit.getConsoleSender(),
            NukeConfig.PREFIX + u"&7" + to_unicode(value),
        )
    else:
        print("[SmartY-Nuclear] " + to_unicode(value))


def get_pyspigot_plugin():
    if not BUKKIT_AVAILABLE:
        return None
    try:
        plugin = Bukkit.getPluginManager().getPlugin("PySpigot")
        if plugin is not None:
            return plugin
        for candidate in Bukkit.getPluginManager().getPlugins():
            if "pyspigot" in str(candidate.getName()).lower():
                return candidate
    except Exception:
        pass
    return None


def now_ms():
    if System is not None:
        try:
            return int(System.currentTimeMillis())
        except Exception:
            pass
    return int(time.time() * 1000)


def material(name):
    if not BUKKIT_AVAILABLE:
        return None
    try:
        return Material.valueOf(name)
    except Exception:
        return None


def sound(name):
    if not BUKKIT_AVAILABLE:
        return None
    try:
        return Sound.valueOf(name)
    except Exception:
        return None


def particle(name):
    if not BUKKIT_AVAILABLE:
        return None
    if name in particle_cache:
        return particle_cache[name]
    try:
        value = Particle.valueOf(name)
    except Exception:
        value = None
    particle_cache[name] = value
    return value


def play_sound(world, location, names, volume, pitch):
    for name in names:
        value = sound(name)
        if value is None:
            continue
        try:
            world.playSound(location, value, float(volume), float(pitch))
            return True
        except Exception:
            continue
    return False


def spawn_particles(world, name, location, count, ox=0.0, oy=0.0, oz=0.0, extra=0.0):
    value = particle(name)
    if value is None:
        return False
    try:
        world.spawnParticle(
            value,
            location,
            int(count),
            float(ox),
            float(oy),
            float(oz),
            float(extra),
        )
        return True
    except Exception:
        try:
            world.spawnParticle(value, location, int(count))
            return True
        except Exception:
            return False


def make_key(value):
    return NamespacedKey(NukeConfig.NAMESPACE, value)


ITEM_KIND_KEY = make_key("item_kind") if BUKKIT_AVAILABLE else None
ENTITY_KIND_KEY = make_key("armed_payload") if BUKKIT_AVAILABLE else None

ADVANCEMENT_PATHS = {
    "root": "nuclear/root",
    "crafted": "nuclear/crafted",
    "dropped": "nuclear/dropped",
    "survived_own": "nuclear/survived_own",
    "close_call": "nuclear/close_call",
}

ADVANCEMENT_CHAT = {
    "crafted": (
        u"получил достижение",
        u"Теперь я стал Смертью",
        u"&a",
    ),
    "dropped": (
        u"получил достижение",
        u"Кнопка была красной",
        u"&a",
    ),
    "close_call": (
        u"достиг цели",
        u"Хиросима",
        u"&a",
    ),
    "survived_own": (
        u"завершил испытание",
        u"Оппенгеймер",
        u"&5",
    ),
}


def get_nuclear_advancement(advancement_id):
    if not BUKKIT_AVAILABLE:
        return None
    path = ADVANCEMENT_PATHS.get(advancement_id)
    if path is None:
        return None
    try:
        return Bukkit.getAdvancement(make_key(path))
    except Exception:
        return None


def has_nuclear_advancement(player, advancement_id):
    advancement = get_nuclear_advancement(advancement_id)
    if player is None or advancement is None:
        return False
    try:
        return bool(player.getAdvancementProgress(advancement).isDone())
    except Exception:
        return False


def broadcast_nuclear_advancement(player, advancement_id):
    announcement = ADVANCEMENT_CHAT.get(advancement_id)
    if announcement is None:
        return
    action, title, title_color = announcement
    Bukkit.broadcastMessage(
        to_java_string(
            colorize(
                u"&f{0} {1} {2}[{3}]".format(
                    to_unicode(player.getName()),
                    action,
                    title_color,
                    title,
                )
            )
        )
    )


def grant_nuclear_advancement(player, advancement_id):
    if player is None:
        return False
    if advancement_id != "root":
        grant_nuclear_advancement(player, "root")
    advancement = get_nuclear_advancement(advancement_id)
    if advancement is None:
        if advancement_id not in missing_advancement_warnings:
            missing_advancement_warnings.add(advancement_id)
            log_info(
                u"&eДостижение &f{0}:{1}&e не найдено. Установите датапак SmartY Nuclear Advancements.".format(
                    NukeConfig.NAMESPACE,
                    ADVANCEMENT_PATHS.get(advancement_id, advancement_id),
                )
            )
        return False

    try:
        progress = player.getAdvancementProgress(advancement)
        if progress.isDone():
            return False
        awarded = bool(progress.awardCriteria(to_java_string("grant")))
    except Exception as exc:
        log_info(
            u"&cНе удалось выдать достижение {0} игроку {1}: {2}".format(
                advancement_id,
                to_unicode(player.getName()),
                exc,
            )
        )
        return False

    if awarded:
        broadcast_nuclear_advancement(player, advancement_id)
    return awarded


def prepare_nuclear_advancements(player):
    grant_nuclear_advancement(player, "root")


def verify_nuclear_advancements():
    loaded = 0
    for advancement_id in ADVANCEMENT_PATHS:
        if get_nuclear_advancement(advancement_id) is not None:
            loaded += 1
    if loaded == len(ADVANCEMENT_PATHS):
        log_info(u"Vanilla-вкладка достижений загружена: &f{0}&7 узлов.".format(loaded))
        return True
    log_info(
        u"&eДатапак достижений не загружен полностью: &f{0}/{1}&e. Ядерка продолжит работать без достижений.".format(
            loaded,
            len(ADVANCEMENT_PATHS),
        )
    )
    return False


def set_item_kind(meta, kind):
    try:
        meta.getPersistentDataContainer().set(
            ITEM_KIND_KEY,
            PersistentDataType.STRING,
            to_java_string(kind),
        )
    except Exception as exc:
        log_info(u"&cНе удалось записать PDC предмета: {0}".format(exc))


def get_item_kind(stack):
    if not BUKKIT_AVAILABLE or stack is None:
        return None
    try:
        if stack.getType() == Material.AIR or not stack.hasItemMeta():
            return None
        value = stack.getItemMeta().getPersistentDataContainer().get(
            ITEM_KIND_KEY,
            PersistentDataType.STRING,
        )
        return to_unicode(value) if value is not None else None
    except Exception:
        return None


def add_glint(meta):
    if Enchantment is None:
        return
    enchantment = getattr(Enchantment, "UNBREAKING", None)
    if enchantment is None:
        enchantment = getattr(Enchantment, "DURABILITY", None)
    if enchantment is not None:
        try:
            meta.addEnchant(enchantment, 1, True)
        except Exception:
            pass
    if ItemFlag is not None:
        for flag_name in ("HIDE_ENCHANTS", "HIDE_ATTRIBUTES"):
            flag = getattr(ItemFlag, flag_name, None)
            if flag is not None:
                try:
                    meta.addItemFlags(flag)
                except Exception:
                    pass


def create_custom_item(base_material, kind, title, lore, glow=True, max_stack=None):
    stack = ItemStack(base_material, 1)
    meta = stack.getItemMeta()
    meta.setDisplayName(to_java_string(colorize(title)))
    meta.setLore(build_java_list([colorize(line) for line in lore]))
    set_item_kind(meta, kind)
    if glow:
        add_glint(meta)
    if max_stack is not None and hasattr(meta, "setMaxStackSize"):
        try:
            meta.setMaxStackSize(int(max_stack))
        except Exception:
            pass
    stack.setItemMeta(meta)
    return stack


def create_fissile_core():
    return create_custom_item(
        material("HEAVY_CORE"),
        NukeConfig.KIND_CORE,
        u"&a&lОбогащённое делящееся ядро",
        [
            u"&7Стабилизированная сверхплотная масса.",
            u"&8Компонент термоядерной боеголовки.",
            u"",
            u"&2☢ &aРадиационный фон: критический",
        ],
        True,
        16,
    )


def create_initiator():
    return create_custom_item(
        material("RECOVERY_COMPASS"),
        NukeConfig.KIND_INITIATOR,
        u"&c&lИмплозионный инициатор",
        [
            u"&7Синхронизирует подрыв первичного заряда.",
            u"&8Компонент термоядерной боеголовки.",
            u"",
            u"&cНе ронять. Не нагревать.",
        ],
        True,
        16,
    )


def create_nuke():
    return create_custom_item(
        material("LODESTONE"),
        NukeConfig.KIND_NUKE,
        u"&4&l☢ ТЕРМОЯДЕРНАЯ БОЕГОЛОВКА «СОЛНЦЕПЁК» ☢",
        [
            u"&8Серийный образец стратегического класса",
            u"",
            u"&7Мощность: &c{0}".format(NukeConfig.EXPLOSION_POWER),
            u"&7Смертельная зона: &4{0:.0f} блоков".format(
                NukeConfig.LETHAL_RADIUS
            ),
            u"&7Зона тяжёлого поражения: &c{0:.0f} блоков".format(
                NukeConfig.SHOCKWAVE_RADIUS
            ),
            u"&7Радиус разрушения блоков: &4{0} блоков".format(
                NukeConfig.CRATER_RADIUS
            ),
            u"&7Задержка после удара: &e{0} сек.".format(
                NukeConfig.IMPACT_COUNTDOWN_SECONDS
            ),
            u"&7Минимальная высота сброса: &e{0} блоков".format(
                NukeConfig.MIN_DROP_HEIGHT
            ),
            u"",
            u"&eСБРОС: &fзажмите Shift и нажмите Q",
            u"&c&lОПАСНО: уничтожает блоки и существ",
        ],
        True,
        1,
    )


def exact_choice(stack):
    return RecipeChoice.ExactChoice(stack)


def remove_recipes():
    if not BUKKIT_AVAILABLE:
        return
    for key in list(registered_recipe_keys):
        try:
            Bukkit.removeRecipe(key)
        except Exception:
            pass
    del registered_recipe_keys[:]


def add_recipe(recipe):
    try:
        Bukkit.removeRecipe(recipe.getKey())
    except Exception:
        pass
    if Bukkit.addRecipe(recipe):
        registered_recipe_keys.append(recipe.getKey())
        return True
    return False


def register_recipes():
    remove_recipes()

    core_key = make_key("fissile_core")
    core = ShapedRecipe(core_key, create_fissile_core())
    core.shape("ENE", "NSN", "ENE")
    core.setIngredient("E", material("ECHO_SHARD"))
    core.setIngredient("N", material("NETHERITE_INGOT"))
    core.setIngredient("S", material("NETHER_STAR"))
    add_recipe(core)

    initiator_key = make_key("detonation_module")
    initiator = ShapedRecipe(initiator_key, create_initiator())
    initiator.shape("RDR", "TBT", "RCR")
    initiator.setIngredient("R", material("REDSTONE_BLOCK"))
    initiator.setIngredient("D", material("DRAGON_BREATH"))
    initiator.setIngredient("T", material("TNT"))
    initiator.setIngredient("B", material("BEACON"))
    initiator.setIngredient("C", material("CLOCK"))
    add_recipe(initiator)

    nuke_key = make_key("thermonuclear_warhead")
    nuke = ShapedRecipe(nuke_key, create_nuke())
    nuke.shape("BNB", "CIC", "BNB")
    nuke.setIngredient("B", material("NETHERITE_BLOCK"))
    nuke.setIngredient("N", material("NETHER_STAR"))
    nuke.setIngredient("C", exact_choice(create_fissile_core()))
    nuke.setIngredient("I", exact_choice(create_initiator()))
    add_recipe(nuke)

    log_info(u"Зарегистрировано рецептов: &f{0}&7.".format(len(registered_recipe_keys)))


def discover_recipes(player):
    if player is None:
        return
    for key in registered_recipe_keys:
        try:
            player.discoverRecipe(key)
        except Exception:
            pass


def horizontal_distance(first, second):
    if first is None or second is None or first.getWorld() != second.getWorld():
        return 999999.0
    dx = first.getX() - second.getX()
    dz = first.getZ() - second.getZ()
    return math.sqrt(dx * dx + dz * dz)


def scan_ground(location):
    world = location.getWorld()
    start_y = int(math.floor(location.getY()))
    min_y = max(world.getMinHeight(), start_y - NukeConfig.MAX_GROUND_SCAN)
    for y in range(start_y, min_y - 1, -1):
        try:
            block_type = world.getBlockAt(
                int(math.floor(location.getX())),
                y,
                int(math.floor(location.getZ())),
            ).getType()
            if block_type != Material.AIR and block_type.isSolid():
                return y
        except Exception:
            continue
    return None


def is_admin(sender):
    if sender is None:
        return False
    try:
        return bool(sender.isOp() or sender.hasPermission("smarty.nuclear.admin"))
    except Exception:
        return False


def world_key(world):
    try:
        return str(world.getUID())
    except Exception:
        return str(world.getName())


def format_location(location):
    return u"{0}: {1}, {2}, {3}".format(
        to_unicode(location.getWorld().getName()),
        int(math.floor(location.getX())),
        int(math.floor(location.getY())),
        int(math.floor(location.getZ())),
    )


def broadcast(value):
    if not BUKKIT_AVAILABLE:
        return
    Bukkit.broadcastMessage(to_java_string(colorize(value)))


def safe_title(player, title, subtitle, fade_in=5, stay=35, fade_out=10):
    try:
        player.sendTitle(
            to_java_string(colorize(title)),
            to_java_string(colorize(subtitle)),
            int(fade_in),
            int(stay),
            int(fade_out),
        )
    except Exception:
        pass


def add_task(task):
    try:
        task_id = task.getTaskId()
        scheduled_task_ids.add(task_id)
        return task_id
    except Exception:
        return -1


def cancel_task(task_id):
    if not BUKKIT_AVAILABLE or task_id is None or task_id < 0:
        return
    try:
        Bukkit.getScheduler().cancelTask(task_id)
    except Exception:
        pass
    scheduled_task_ids.discard(task_id)


def make_transform(scale_x, scale_y, scale_z):
    return Transformation(
        Vector3f(-float(scale_x) / 2.0, -float(scale_y) / 2.0, -float(scale_z) / 2.0),
        Quaternionf(),
        Vector3f(float(scale_x), float(scale_y), float(scale_z)),
        Quaternionf(),
    )


def spawn_display_part(world, base_location, block_material, scale, offset_y, glow_color):
    location = base_location.clone().add(0.0, float(offset_y), 0.0)
    display = world.spawnEntity(location, EntityType.BLOCK_DISPLAY)
    display.setBlock(block_material.createBlockData())
    display.setTransformation(make_transform(scale[0], scale[1], scale[2]))
    display.setGlowing(True)
    display.setGlowColorOverride(glow_color)
    display.setInvulnerable(True)
    display.setPersistent(False)
    display.setTeleportDuration(2)
    display.setViewRange(2.5)
    return display


class NuclearPayload(object):
    def __init__(self, owner, location):
        self.owner_uuid = str(owner.getUniqueId())
        self.owner_name = to_unicode(owner.getName())
        self.world = location.getWorld()
        self.location = location.clone()
        self.velocity_y = -0.35
        self.age_ticks = 0
        self.stage = "falling"
        self.parts = []
        self.fall_task_id = -1
        self.countdown_task_id = -1
        self.countdown = NukeConfig.IMPACT_COUNTDOWN_SECONDS
        self.chunk = None

    def spawn_visual(self):
        red = Color.fromRGB(190, 20, 20)
        steel = Color.fromRGB(90, 105, 110)
        specifications = [
            ("GRAY_CONCRETE", (1.15, 2.8, 1.15), 0.0, steel),
            ("POLISHED_BLACKSTONE", (1.38, 0.28, 1.38), -0.72, red),
            ("POLISHED_BLACKSTONE", (1.38, 0.28, 1.38), 0.72, red),
            ("RED_CONCRETE", (0.82, 0.65, 0.82), -1.68, red),
            ("IRON_BLOCK", (0.72, 0.55, 0.72), 1.62, steel),
        ]
        for material_name, scale, offset_y, glow_color in specifications:
            try:
                display = spawn_display_part(
                    self.world,
                    self.location,
                    material(material_name),
                    scale,
                    offset_y,
                    glow_color,
                )
                self.parts.append((display, offset_y))
            except Exception:
                self.cleanup_visual()
                raise
        try:
            self.chunk = self.location.getChunk()
            plugin = get_pyspigot_plugin()
            if plugin is not None and hasattr(self.chunk, "addPluginChunkTicket"):
                self.chunk.addPluginChunkTicket(plugin)
        except Exception:
            self.chunk = None

    def teleport_visual(self):
        for display, offset_y in list(self.parts):
            try:
                display.teleport(self.location.clone().add(0.0, offset_y, 0.0))
            except Exception:
                pass

    def cleanup_visual(self):
        for display, unused_offset in list(self.parts):
            try:
                if display is not None and display.isValid():
                    display.remove()
            except Exception:
                pass
        self.parts = []
        if self.chunk is not None:
            try:
                plugin = get_pyspigot_plugin()
                if plugin is not None and hasattr(self.chunk, "removePluginChunkTicket"):
                    self.chunk.removePluginChunkTicket(plugin)
            except Exception:
                pass
            self.chunk = None

    def start(self):
        self.spawn_visual()
        active_payloads[world_key(self.world)] = self
        plugin = get_pyspigot_plugin()
        runner = PayloadFallRunnable(self)
        task = Bukkit.getScheduler().runTaskTimer(plugin, runner, 0, 2)
        self.fall_task_id = add_task(task)
        runner.task_id = self.fall_task_id

    def find_impact(self, old_y, new_y):
        x = int(math.floor(self.location.getX()))
        z = int(math.floor(self.location.getZ()))
        top = int(math.floor(old_y - 1.65))
        bottom = int(math.floor(new_y - 1.75))
        for y in range(top, bottom - 1, -1):
            if y < self.world.getMinHeight():
                return float(self.world.getMinHeight()) + 1.8
            try:
                block_type = self.world.getBlockAt(x, y, z).getType()
                if block_type != Material.AIR and block_type.isSolid():
                    return float(y) + 1.82
            except Exception:
                pass
        return None

    def tick_fall(self):
        if self.stage != "falling":
            return
        self.age_ticks += 2
        old_y = self.location.getY()
        self.velocity_y = max(-3.2, self.velocity_y - 0.08)
        new_y = old_y + (self.velocity_y * 2.0)
        impact_y = self.find_impact(old_y, new_y)

        if impact_y is not None:
            self.location.setY(impact_y)
            self.teleport_visual()
            self.impact()
            return

        self.location.setY(new_y)
        self.teleport_visual()
        spawn_particles(
            self.world,
            "LARGE_SMOKE",
            self.location.clone().add(0.0, 1.65, 0.0),
            4,
            0.25,
            0.15,
            0.25,
            0.01,
        )
        if self.age_ticks % 10 == 0:
            spawn_particles(
                self.world,
                "FLAME",
                self.location.clone().add(0.0, 1.7, 0.0),
                3,
                0.15,
                0.1,
                0.15,
                0.01,
            )
        if self.age_ticks % 20 == 0:
            play_sound(
                self.world,
                self.location,
                ["ENTITY_TNT_PRIMED", "ENTITY_CREEPER_PRIMED"],
                1.6,
                0.55,
            )

        if self.age_ticks >= NukeConfig.MAX_FALL_SECONDS * 20:
            self.impact()

    def impact(self):
        if self.stage != "falling":
            return
        self.stage = "countdown"
        cancel_task(self.fall_task_id)
        self.fall_task_id = -1
        self.velocity_y = 0.0

        spawn_particles(self.world, "EXPLOSION", self.location, 6, 1.0, 0.4, 1.0, 0.05)
        spawn_particles(self.world, "ELECTRIC_SPARK", self.location, 45, 2.0, 1.0, 2.0, 0.2)
        play_sound(
            self.world,
            self.location,
            ["BLOCK_ANVIL_LAND", "ENTITY_IRON_GOLEM_DAMAGE"],
            4.0,
            0.45,
        )
        broadcast(
            NukeConfig.PREFIX
            + u"&c&lБОЕГОЛОВКА ДОСТИГЛА ЗЕМЛИ! &f"
            + format_location(self.location)
        )

        plugin = get_pyspigot_plugin()
        runner = PayloadCountdownRunnable(self)
        task = Bukkit.getScheduler().runTaskTimer(plugin, runner, 0, 20)
        self.countdown_task_id = add_task(task)
        runner.task_id = self.countdown_task_id

    def tick_countdown(self):
        if self.stage != "countdown":
            return
        if self.countdown <= 0:
            self.detonate()
            return

        pitch = min(2.0, 0.65 + (NukeConfig.IMPACT_COUNTDOWN_SECONDS - self.countdown) * 0.25)
        play_sound(
            self.world,
            self.location,
            ["BLOCK_NOTE_BLOCK_PLING", "BLOCK_NOTE_BLOCK_HAT"],
            4.0,
            pitch,
        )
        spawn_particles(
            self.world,
            "ELECTRIC_SPARK",
            self.location.clone().add(0.0, 0.8, 0.0),
            24,
            1.3,
            1.0,
            1.3,
            0.15,
        )
        for display, unused_offset in self.parts:
            try:
                display.setGlowing(not display.isGlowing())
            except Exception:
                pass

        if self.countdown in (10, 5, 3, 2, 1):
            broadcast(
                NukeConfig.PREFIX
                + u"&4&lДЕТОНАЦИЯ ЧЕРЕЗ &f&l{0} &4&lСЕК.".format(self.countdown)
            )
        for player in self.world.getPlayers():
            if player.getLocation().distanceSquared(self.location) <= NukeConfig.FLASH_RADIUS ** 2:
                safe_title(
                    player,
                    u"&4&l☢ {0} ☢".format(self.countdown),
                    u"&cНЕМЕДЛЕННО ПОКИНЬТЕ ЗОНУ",
                    0,
                    22,
                    0,
                )
        self.countdown -= 1

    def detonate(self):
        if self.stage == "detonated":
            return
        self.stage = "detonated"
        cancel_task(self.countdown_task_id)
        self.countdown_task_id = -1
        self.cleanup_visual()
        active_payloads.pop(world_key(self.world), None)
        detonate_at(self.location, self.owner_name, self.owner_uuid)

    def cancel(self, refund=True):
        if self.stage == "detonated":
            return
        self.stage = "cancelled"
        cancel_task(self.fall_task_id)
        cancel_task(self.countdown_task_id)
        self.fall_task_id = -1
        self.countdown_task_id = -1
        self.cleanup_visual()
        active_payloads.pop(world_key(self.world), None)
        if refund:
            try:
                self.world.dropItemNaturally(self.location, create_nuke())
            except Exception:
                pass


class PayloadFallRunnable(Runnable):
    def __init__(self, payload):
        self.payload = payload
        self.task_id = -1

    def run(self):
        try:
            if self.payload.stage != "falling":
                cancel_task(self.task_id)
                return
            self.payload.tick_fall()
        except Exception as exc:
            log_info(u"&cОшибка полёта боеголовки: {0}".format(exc))
            cancel_task(self.task_id)
            self.payload.cancel(True)


class PayloadCountdownRunnable(Runnable):
    def __init__(self, payload):
        self.payload = payload
        self.task_id = -1

    def run(self):
        try:
            if self.payload.stage != "countdown":
                cancel_task(self.task_id)
                return
            self.payload.tick_countdown()
        except Exception as exc:
            log_info(u"&cОшибка обратного отсчёта: {0}".format(exc))
            cancel_task(self.task_id)
            self.payload.cancel(True)


def add_potion_effect(entity, effect_names, duration, amplifier):
    if PotionEffectType is None:
        return
    effect_type = None
    for name in effect_names:
        effect_type = getattr(PotionEffectType, name, None)
        if effect_type is not None:
            break
    if effect_type is None:
        return
    try:
        entity.addPotionEffect(PotionEffect(effect_type, int(duration), int(amplifier)))
    except Exception:
        pass


def apply_shockwave_to_entity(entity, location, radius):
    try:
        if entity is None or not entity.isValid():
            return
        entity_location = entity.getLocation()
        distance = entity_location.distance(location)
        if distance <= 0.1 or distance > radius:
            return

        strength = max(0.0, 1.0 - (distance / radius))
        is_player = isinstance(entity, Player)

        if distance <= NukeConfig.LETHAL_RADIUS:
            direction = entity_location.toVector().subtract(location.toVector())
            direction.setY(max(0.18, direction.getY()))
            direction.normalize().multiply(2.0 + strength * 4.0)
            direction.setY(min(2.6, direction.getY() + 0.8 + strength))
            entity.setVelocity(direction)
            entity.setFireTicks(max(entity.getFireTicks(), 260))
            entity.damage(2048.0)
            if is_player:
                safe_title(
                    entity,
                    u"&4&l☢ СМЕРТЕЛЬНАЯ ЗОНА ☢",
                    u"&cРасстояние до эпицентра: {0:.0f} м".format(distance),
                    0,
                    50,
                    20,
                )
            return

        if is_player:
            # Outside the lethal zone the blast may reduce health, but never
            # finishes the player. This makes a perfect elytra escape possible.
            progress = (
                (distance - NukeConfig.LETHAL_RADIUS)
                / (radius - NukeConfig.LETHAL_RADIUS)
            )
            target_health = 1.0 + max(0.0, min(1.0, progress)) * 7.0
            try:
                entity.setAbsorptionAmount(0.0)
            except Exception:
                pass

            # Apply real Bukkit damage in bounded pulses. Armor and protection
            # plugins still participate, while no pulse can cross target_health.
            for unused_attempt in range(8):
                try:
                    current_health = entity.getHealth()
                    remaining_damage = current_health - target_health
                    if remaining_damage <= 0.25:
                        break
                    entity.setNoDamageTicks(0)
                    entity.damage(remaining_damage)
                    if entity.getHealth() >= current_health - 0.01:
                        break
                except Exception:
                    break
            safe_title(
                entity,
                u"&e&l☢ ВЫ ПЕРЕЖИЛИ ВСПЫШКУ ☢",
                u"&cОсталось критически мало здоровья",
                0,
                40,
                20,
            )
            try:
                if (
                    distance <= 500.0
                    and not entity.isDead()
                    and entity.getHealth() > 0.0
                ):
                    grant_nuclear_advancement(entity, "close_call")
            except Exception:
                pass
            return

        direction = entity_location.toVector().subtract(location.toVector())
        direction.setY(max(0.18, direction.getY()))
        direction.normalize().multiply(0.45 + strength * 2.5)
        direction.setY(min(1.8, direction.getY() + 0.4 + strength * 0.6))
        entity.setVelocity(direction)
        entity.damage(4.0 + strength * strength * 60.0)
    except Exception:
        pass


class ShockwaveRunnable(Runnable):
    def __init__(self, entities, location):
        self.entities = entities
        self.location = location.clone()
        self.radius = NukeConfig.SHOCKWAVE_RADIUS
        self.index = 0
        self.task_id = -1

    def run(self):
        try:
            end_index = min(
                len(self.entities),
                self.index + NukeConfig.SHOCKWAVE_ENTITY_BATCH_SIZE,
            )
            while self.index < end_index:
                entity = self.entities[self.index]
                self.index += 1
                apply_shockwave_to_entity(entity, self.location, self.radius)

            if self.index >= len(self.entities):
                cancel_task(self.task_id)
        except Exception as exc:
            log_info(u"&cОшибка пакетной ударной волны: {0}".format(exc))
            cancel_task(self.task_id)


def start_shockwave(world, location):
    radius_squared = NukeConfig.SHOCKWAVE_RADIUS ** 2
    entities = []
    player_ids = set()

    # Players go first so their flash and damage are never delayed by large mob lists.
    for player in world.getPlayers():
        try:
            if player.getLocation().distanceSquared(location) <= radius_squared:
                entities.append(player)
                player_ids.add(str(player.getUniqueId()))
        except Exception:
            pass

    # getLivingEntities only returns loaded entities and does not load distant chunks.
    try:
        living_entities = world.getLivingEntities()
    except Exception:
        living_entities = []
    for entity in living_entities:
        try:
            if str(entity.getUniqueId()) in player_ids:
                continue
            if entity.getLocation().distanceSquared(location) <= radius_squared:
                entities.append(entity)
        except Exception:
            pass

    if not entities:
        return
    plugin = get_pyspigot_plugin()
    if plugin is None:
        return
    runner = ShockwaveRunnable(entities, location)
    task = Bukkit.getScheduler().runTaskTimer(plugin, runner, 0, 1)
    runner.task_id = add_task(task)


class MushroomCloudRunnable(Runnable):
    def __init__(self, world, location):
        self.world = world
        self.location = location.clone()
        self.step = 0
        self.task_id = -1

    def run(self):
        try:
            self.step += 1
            if self.step > NukeConfig.MUSHROOM_DURATION_STEPS:
                cancel_task(self.task_id)
                return

            stem_height = min(
                NukeConfig.MUSHROOM_STEM_HEIGHT,
                self.step * 1.0,
            )
            stem_segments = max(3, min(10, int(stem_height / 12.0) + 2))
            for index in range(stem_segments):
                y = 1.5 + (stem_height * float(index) / float(max(1, stem_segments - 1)))
                wobble = math.sin((self.step + index * 5) * 0.13) * 2.0
                point = self.location.clone().add(wobble, y, -wobble * 0.65)
                spawn_particles(self.world, "LARGE_SMOKE", point, 6, 2.8, 2.2, 2.8, 0.025)
                if self.step < 58 and index < 5:
                    spawn_particles(self.world, "FLAME", point, 3, 1.4, 1.0, 1.4, 0.03)

            if self.step >= 18:
                cap_radius = min(
                    NukeConfig.MUSHROOM_CAP_RADIUS,
                    8.0 + (self.step - 18) * 1.5,
                )
                cap_y = min(
                    NukeConfig.MUSHROOM_STEM_HEIGHT,
                    max(30.0, stem_height + 3.0),
                )
                points = 24
                for index in range(points):
                    angle = (math.pi * 2.0 * index / points) + self.step * 0.035
                    radius = cap_radius * (0.68 + random.random() * 0.32)
                    point = self.location.clone().add(
                        math.cos(angle) * radius,
                        cap_y + math.sin(angle * 2.0) * 4.5 + random.random() * 3.0,
                        math.sin(angle) * radius,
                    )
                    spawn_particles(self.world, "LARGE_SMOKE", point, 8, 7.5, 4.5, 7.5, 0.025)

            if self.step <= 70:
                ring_radius = min(
                    NukeConfig.MUSHROOM_GROUND_RING_RADIUS,
                    self.step * 4.4,
                )
                for index in range(24):
                    angle = math.pi * 2.0 * index / 24.0
                    point = self.location.clone().add(
                        math.cos(angle) * ring_radius,
                        1.0,
                        math.sin(angle) * ring_radius,
                    )
                    spawn_particles(self.world, "CLOUD", point, 4, 1.6, 0.6, 1.6, 0.12)
                    if self.step < 18:
                        spawn_particles(self.world, "FLAME", point, 2, 0.7, 0.35, 0.7, 0.03)
        except Exception as exc:
            log_info(u"&cОшибка эффекта грибовидного облака: {0}".format(exc))
            cancel_task(self.task_id)


def start_mushroom_cloud(world, location):
    plugin = get_pyspigot_plugin()
    if plugin is None:
        return
    runner = MushroomCloudRunnable(world, location)
    task = Bukkit.getScheduler().runTaskTimer(
        plugin,
        runner,
        0,
        NukeConfig.MUSHROOM_PERIOD_TICKS,
    )
    runner.task_id = add_task(task)


class CraterCarverRunnable(Runnable):
    def __init__(self, world, location):
        self.world = world
        self.world_id = world_key(world)
        self.center_x = int(math.floor(location.getX()))
        self.center_y = int(math.floor(location.getY()))
        self.center_z = int(math.floor(location.getZ()))
        self.radius = int(NukeConfig.CRATER_RADIUS)
        self.radius_squared = float(self.radius * self.radius)
        self.dx = -self.radius
        self.dz = -self.radius
        self.current_y = None
        self.bottom_y = None
        self.finished = False
        self.changed_blocks = 0
        self.scanned_blocks = 0
        self.task_id = -1
        self.protected_types = set()
        for material_name in NukeConfig.CRATER_PROTECTED_MATERIALS:
            protected_type = material(material_name)
            if protected_type is not None:
                self.protected_types.add(protected_type)

    def advance_column(self):
        while self.dx <= self.radius:
            dx = self.dx
            dz = self.dz
            self.dz += 1
            if self.dz > self.radius:
                self.dx += 1
                self.dz = -self.radius

            horizontal_squared = float(dx * dx + dz * dz)
            if horizontal_squared > self.radius_squared:
                continue

            normalized = horizontal_squared / self.radius_squared
            crater_factor = max(0.0, 1.0 - normalized)
            depth = int(
                round(
                    NukeConfig.CRATER_DEPTH
                    * math.pow(crater_factor, 0.68)
                )
            )
            height = int(
                round(
                    NukeConfig.CRATER_ABOVE_HEIGHT
                    * math.sqrt(crater_factor)
                )
            )
            if depth <= 0 and height <= 0:
                continue

            self.column_x = self.center_x + dx
            self.column_z = self.center_z + dz
            self.current_y = min(
                self.world.getMaxHeight() - 1,
                self.center_y + height,
            )
            self.bottom_y = max(
                self.world.getMinHeight(),
                self.center_y - depth,
            )
            return True

        self.finished = True
        return False

    def get_tick_limits(self):
        max_blocks = int(NukeConfig.CRATER_BLOCKS_PER_TICK)
        min_blocks = int(NukeConfig.CRATER_MIN_BLOCKS_PER_TICK)
        try:
            current_tps = float(Bukkit.getTPS()[0])
            if current_tps < 12.0:
                max_blocks = min_blocks
            elif current_tps < 16.0:
                max_blocks = max(min_blocks, min(max_blocks, 160))
            elif current_tps < 18.0:
                max_blocks = max(min_blocks, min(max_blocks, 300))
            elif current_tps < 19.0:
                max_blocks = max(min_blocks, min(max_blocks, 500))
        except Exception:
            pass
        max_scans = min(
            int(NukeConfig.CRATER_SCANS_PER_TICK),
            max(512, max_blocks * 8),
        )
        return max_blocks, max_scans

    def run(self):
        try:
            changed_this_tick = 0
            scanned_this_tick = 0
            max_blocks, max_scans = self.get_tick_limits()
            deadline_ns = None
            if System is not None:
                try:
                    deadline_ns = System.nanoTime() + int(
                        NukeConfig.CRATER_TIME_BUDGET_MS * 1000000.0
                    )
                except Exception:
                    deadline_ns = None

            while (
                not self.finished
                and changed_this_tick < max_blocks
                and scanned_this_tick < max_scans
            ):
                if (
                    deadline_ns is not None
                    and scanned_this_tick % 64 == 0
                    and System.nanoTime() >= deadline_ns
                ):
                    break
                if self.current_y is None:
                    if not self.advance_column():
                        break

                block = self.world.getBlockAt(
                    self.column_x,
                    self.current_y,
                    self.column_z,
                )
                block_type = block.getType()
                self.current_y -= 1
                scanned_this_tick += 1
                self.scanned_blocks += 1

                if self.current_y < self.bottom_y:
                    self.current_y = None

                if block_type.isAir():
                    continue
                if block_type in self.protected_types:
                    continue

                block.setType(Material.AIR, False)
                changed_this_tick += 1
                self.changed_blocks += 1

            if self.finished:
                cancel_task(self.task_id)
                active_craters.pop(self.world_id, None)
                broadcast(
                    NukeConfig.PREFIX
                    + u"&7Формирование кратера завершено. Удалено блоков: &f{0}&7.".format(
                        self.changed_blocks
                    )
                )
                log_info(
                    u"Кратер завершён: удалено &f{0}&7 блоков, проверено &f{1}&7.".format(
                        self.changed_blocks,
                        self.scanned_blocks,
                    )
                )
        except Exception as exc:
            log_info(u"&cОшибка пакетного формирования кратера: {0}".format(exc))
            cancel_task(self.task_id)
            active_craters.pop(self.world_id, None)

    def cancel(self):
        self.finished = True
        cancel_task(self.task_id)
        active_craters.pop(self.world_id, None)


def start_crater_carver(world, location):
    if not NukeConfig.BREAK_BLOCKS or NukeConfig.CRATER_RADIUS <= 0:
        return
    plugin = get_pyspigot_plugin()
    if plugin is None:
        return
    runner = CraterCarverRunnable(world, location)
    task = Bukkit.getScheduler().runTaskTimer(plugin, runner, 1, 1)
    runner.task_id = add_task(task)
    active_craters[world_key(world)] = runner
    log_info(
        u"Запущено формирование кратера: радиус &f{0}&7, глубина &f{1}&7, до &f{2}&7 блоков/тик, бюджет &f{3:.0f} мс&7.".format(
            NukeConfig.CRATER_RADIUS,
            NukeConfig.CRATER_DEPTH,
            NukeConfig.CRATER_BLOCKS_PER_TICK,
            NukeConfig.CRATER_TIME_BUDGET_MS,
        )
    )


class DeepBlastRunnable(Runnable):
    def __init__(self, world, location):
        self.world = world
        self.location = location.clone()
        self.index = 0
        self.task_id = -1

    def run(self):
        try:
            if self.index >= len(NukeConfig.DEEP_BLASTS):
                cancel_task(self.task_id)
                return

            y_offset, power = NukeConfig.DEEP_BLASTS[self.index]
            blast_location = self.location.clone().add(0.0, y_offset, 0.0)
            minimum_y = float(self.world.getMinHeight() + 4)
            if blast_location.getY() < minimum_y:
                blast_location.setY(minimum_y)

            spawn_particles(
                self.world,
                "EXPLOSION_EMITTER",
                blast_location,
                8,
                3.0,
                2.0,
                3.0,
                0.2,
            )
            play_sound(
                self.world,
                blast_location,
                ["ENTITY_GENERIC_EXPLODE"],
                12.0,
                0.28 + self.index * 0.08,
            )
            self.world.createExplosion(
                blast_location,
                Float(power),
                False,
                bool(NukeConfig.BREAK_BLOCKS),
            )
            self.index += 1
        except Exception as exc:
            log_info(u"&cОшибка подземного ударного импульса: {0}".format(exc))
            cancel_task(self.task_id)


def start_deep_blasts(world, location):
    if not NukeConfig.DEEP_BLASTS:
        return
    plugin = get_pyspigot_plugin()
    if plugin is None:
        return
    runner = DeepBlastRunnable(world, location)
    task = Bukkit.getScheduler().runTaskTimer(plugin, runner, 6, 8)
    runner.task_id = add_task(task)


class OwnerSurvivalRunnable(Runnable):
    def __init__(self, world, location, owner_uuid):
        self.world = world
        self.location = location.clone()
        self.owner_uuid = owner_uuid
        self.task_id = -1

    def run(self):
        scheduled_task_ids.discard(self.task_id)
        try:
            owner = None
            for player in Bukkit.getOnlinePlayers():
                if str(player.getUniqueId()) == self.owner_uuid:
                    owner = player
                    break
            if owner is None or owner.isDead() or owner.getHealth() <= 0.0:
                return
            owner_location = owner.getLocation()
            if owner_location.getWorld() != self.world:
                return
            if owner_location.distance(self.location) <= NukeConfig.LETHAL_RADIUS:
                return
            grant_nuclear_advancement(owner, "survived_own")
        except Exception as exc:
            log_info(u"&cОшибка проверки выживания оператора: {0}".format(exc))


def schedule_owner_survival_check(world, location, owner_uuid):
    plugin = get_pyspigot_plugin()
    if plugin is None or not owner_uuid:
        return
    runner = OwnerSurvivalRunnable(world, location, owner_uuid)
    task = Bukkit.getScheduler().runTaskLater(plugin, runner, 6)
    runner.task_id = add_task(task)


def detonate_at(location, owner_name, owner_uuid):
    world = location.getWorld()
    broadcast(
        NukeConfig.PREFIX
        + u"&4&lТЕРМОЯДЕРНАЯ ДЕТОНАЦИЯ &7(&f{0}&7)".format(
            format_location(location)
        )
    )
    log_info(
        u"Боеголовка игрока &f{0}&7 детонировала: &f{1}".format(
            owner_name,
            format_location(location),
        )
    )

    for player in world.getPlayers():
        try:
            if player.getLocation().distanceSquared(location) <= NukeConfig.FLASH_RADIUS ** 2:
                safe_title(
                    player,
                    u"&f&l☢",
                    u"&4&lТЕРМОЯДЕРНАЯ ДЕТОНАЦИЯ",
                    0,
                    55,
                    30,
                )
        except Exception:
            pass

    spawn_particles(world, "EXPLOSION_EMITTER", location.clone().add(0.0, 2.0, 0.0), 18, 5.5, 3.0, 5.5, 0.3)
    spawn_particles(world, "SONIC_BOOM", location.clone().add(0.0, 2.0, 0.0), 12, 4.0, 2.0, 4.0, 0.0)
    spawn_particles(world, "END_ROD", location.clone().add(0.0, 4.0, 0.0), 180, 7.0, 6.0, 7.0, 0.45)
    play_sound(world, location, ["ENTITY_GENERIC_EXPLODE"], 18.0, 0.35)
    play_sound(world, location, ["ENTITY_WARDEN_SONIC_BOOM"], 14.0, 0.55)
    play_sound(world, location, ["ENTITY_LIGHTNING_BOLT_THUNDER"], 12.0, 0.65)

    for index in range(5):
        angle = math.pi * 2.0 * index / 5.0
        bolt_location = location.clone().add(
            math.cos(angle) * 5.0,
            0.0,
            math.sin(angle) * 5.0,
        )
        try:
            world.strikeLightningEffect(bolt_location)
        except Exception:
            pass

    start_shockwave(world, location)
    try:
        world.createExplosion(
            location,
            Float(NukeConfig.BLOCK_EXPLOSION_POWER),
            bool(NukeConfig.SET_FIRE),
            bool(NukeConfig.BREAK_BLOCKS),
        )
    except Exception as exc:
        log_info(u"&cНе удалось создать основной взрыв: {0}".format(exc))
        try:
            world.createExplosion(location, Float(NukeConfig.BLOCK_EXPLOSION_POWER))
        except Exception:
            pass
    start_crater_carver(world, location)
    start_deep_blasts(world, location)
    start_mushroom_cloud(world, location)
    schedule_owner_survival_check(world, location, owner_uuid)


def can_launch(player, drop_entity):
    global last_launch_ms
    stack = drop_entity.getItemStack()
    if stack.getAmount() != 1:
        send_message(
            player,
            NukeConfig.PREFIX + u"&eДля сброса отделите одну боеголовку от стопки.",
        )
        return False

    location = drop_entity.getLocation()
    current_world_key = world_key(location.getWorld())
    if current_world_key in active_payloads:
        send_message(
            player,
            NukeConfig.PREFIX + u"&cВ этом мире уже есть активная боеголовка.",
        )
        return False
    if current_world_key in active_craters:
        send_message(
            player,
            NukeConfig.PREFIX
            + u"&cВ этом мире ещё формируется кратер предыдущего взрыва.",
        )
        return False

    if not is_admin(player) and NukeConfig.GLOBAL_COOLDOWN_SECONDS > 0:
        remaining_ms = (
            last_launch_ms
            + NukeConfig.GLOBAL_COOLDOWN_SECONDS * 1000
            - now_ms()
        )
        if remaining_ms > 0:
            send_message(
                player,
                NukeConfig.PREFIX
                + u"&eСистема охлаждается ещё &f{0} сек.".format(
                    int(math.ceil(remaining_ms / 1000.0))
                ),
            )
            return False

    if not is_admin(player) and NukeConfig.SPAWN_PROTECTION_RADIUS > 0:
        spawn_location = location.getWorld().getSpawnLocation()
        if horizontal_distance(location, spawn_location) < NukeConfig.SPAWN_PROTECTION_RADIUS:
            send_message(
                player,
                NukeConfig.PREFIX
                + u"&cСброс запрещён ближе {0} блоков от спавна.".format(
                    NukeConfig.SPAWN_PROTECTION_RADIUS
                ),
            )
            return False

    ground_y = scan_ground(location)
    if ground_y is None:
        send_message(
            player,
            NukeConfig.PREFIX + u"&cПод точкой сброса не найдена твёрдая поверхность.",
        )
        return False
    height = location.getY() - float(ground_y + 1)
    if height < NukeConfig.MIN_DROP_HEIGHT:
        send_message(
            player,
            NukeConfig.PREFIX
            + u"&eНедостаточная высота: &f{0:.1f}&e/&f{1} &eблоков.".format(
                height,
                NukeConfig.MIN_DROP_HEIGHT,
            ),
        )
        return False
    return True


def handle_player_drop(event):
    global last_launch_ms
    if event.isCancelled():
        return
    player = event.getPlayer()
    if not player.isSneaking():
        return
    drop_entity = event.getItemDrop()
    if get_item_kind(drop_entity.getItemStack()) != NukeConfig.KIND_NUKE:
        return
    if not can_launch(player, drop_entity):
        return

    launch_location = drop_entity.getLocation().clone()
    try:
        drop_entity.remove()
    except Exception:
        event.setCancelled(True)
        return

    last_launch_ms = now_ms()
    payload = NuclearPayload(player, launch_location)
    try:
        payload.start()
    except Exception as exc:
        log_info(u"&cНе удалось запустить боеголовку: {0}".format(exc))
        payload.cancel(False)
        try:
            launch_location.getWorld().dropItemNaturally(launch_location, create_nuke())
        except Exception:
            pass
        return

    grant_nuclear_advancement(player, "dropped")
    broadcast(
        NukeConfig.PREFIX
        + u"&4&lЗАФИКСИРОВАН ЯДЕРНЫЙ СБРОС! &7Оператор: &f{0}&7, цель: &f{1}".format(
            to_unicode(player.getName()),
            format_location(launch_location),
        )
    )
    play_sound(
        launch_location.getWorld(),
        launch_location,
        ["ENTITY_WITHER_SPAWN", "ENTITY_ENDER_DRAGON_GROWL"],
        8.0,
        0.65,
    )


def handle_player_join(event):
    player = event.getPlayer()
    discover_recipes(player)
    prepare_nuclear_advancements(player)


def handle_craft_item(event):
    if event.isCancelled():
        return
    player = event.getWhoClicked()
    if not isinstance(player, Player):
        return
    result = event.getCurrentItem()
    if get_item_kind(result) != NukeConfig.KIND_NUKE:
        try:
            result = event.getRecipe().getResult()
        except Exception:
            result = None
    if get_item_kind(result) == NukeConfig.KIND_NUKE:
        grant_nuclear_advancement(player, "crafted")


def handle_block_place(event):
    if event.isCancelled():
        return
    if get_item_kind(event.getItemInHand()) != NukeConfig.KIND_NUKE:
        return
    event.setCancelled(True)
    send_message(
        event.getPlayer(),
        NukeConfig.PREFIX + u"&eБоеголовку нельзя установить как блок. Сброс: Shift + Q.",
    )


if BUKKIT_AVAILABLE:
    class PyBukkitCommand(Command, TabCompleter):
        def __init__(self, name, description, usage, aliases, executor, completer):
            Command.__init__(self, name, description, usage, aliases)
            self.executor = executor
            self.completer = completer

        def execute(self, sender, command_label, args):
            try:
                return bool(self.executor(sender, command_label, list(args)))
            except Exception as exc:
                log_info(u"&cОшибка команды: {0}".format(exc))
                send_message(sender, NukeConfig.PREFIX + u"&cОшибка выполнения команды.")
                return True

        def tabComplete(self, *args):
            try:
                if self.completer is not None and len(args) >= 3:
                    result = self.completer(args[0], args[1], list(args[2]))
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


def get_command_map():
    server = Bukkit.getServer()
    command_map = server.getCommandMap() if hasattr(server, "getCommandMap") else None
    if command_map is not None:
        return command_map
    field = server.getClass().getDeclaredField("commandMap")
    field.setAccessible(True)
    return field.get(server)


def get_known_commands(command_map):
    if hasattr(command_map, "getKnownCommands"):
        try:
            return command_map.getKnownCommands()
        except Exception:
            pass
    current_class = command_map.getClass()
    while current_class is not None:
        try:
            field = current_class.getDeclaredField("knownCommands")
            field.setAccessible(True)
            return field.get(command_map)
        except Exception:
            current_class = current_class.getSuperclass()
    return None


def register_bukkit_command():
    if not BUKKIT_AVAILABLE:
        return
    command_map = get_command_map()
    known_commands = get_known_commands(command_map)
    if known_commands is None:
        raise RuntimeError("Cannot access Bukkit knownCommands")

    aliases = ["nuclear", "nuclearbomb"]
    command = PyBukkitCommand(
        "nuke",
        "SmartY nuclear bomb",
        "/nuke <recipe|status|give|cancel>",
        aliases,
        execute_nuke_command,
        tab_nuke_command,
    )

    for key in ["nuke", "nuclear", "nuclearbomb"]:
        for full_key in [key, NukeConfig.NAMESPACE + ":" + key]:
            try:
                previous = known_commands.get(full_key)
                if previous is not None and hasattr(previous, "unregister"):
                    previous.unregister(command_map)
                known_commands.remove(full_key)
            except Exception:
                pass

    command_map.register(NukeConfig.NAMESPACE, command)
    for key in ["nuke", NukeConfig.NAMESPACE + ":nuke"]:
        registered_commands[key] = command


def unregister_bukkit_commands():
    if not BUKKIT_AVAILABLE or not registered_commands:
        return
    try:
        command_map = get_command_map()
        known_commands = get_known_commands(command_map)
        if known_commands is None:
            return
        iterator = known_commands.entrySet().iterator()
        remove_keys = []
        while iterator.hasNext():
            entry = iterator.next()
            if entry.getValue() in registered_commands.values():
                remove_keys.append(str(entry.getKey()))
        for key in remove_keys:
            try:
                known_commands.remove(key)
            except Exception:
                pass
    except Exception:
        pass
    registered_commands.clear()


def send_recipe(sender):
    send_message(sender, u"&8&m------------------------------------------------")
    send_message(sender, u"&4&l☢ ТЕРМОЯДЕРНАЯ БОЕГОЛОВКА: 3 ЭТАПА")
    send_message(sender, u"")
    send_message(sender, u"&a&l1. Обогащённое делящееся ядро")
    send_message(sender, u"&7[Эхо-осколок] [Незеритовый слиток] [Эхо-осколок]")
    send_message(sender, u"&7[Незеритовый слиток] [Звезда Незера] [Незеритовый слиток]")
    send_message(sender, u"&7[Эхо-осколок] [Незеритовый слиток] [Эхо-осколок]")
    send_message(sender, u"")
    send_message(sender, u"&c&l2. Имплозионный инициатор")
    send_message(sender, u"&7[Редстоун-блок] [Дыхание дракона] [Редстоун-блок]")
    send_message(sender, u"&7[TNT] [Маяк] [TNT]")
    send_message(sender, u"&7[Редстоун-блок] [Часы] [Редстоун-блок]")
    send_message(sender, u"")
    send_message(sender, u"&4&l3. Боеголовка «Солнцепёк»")
    send_message(sender, u"&7[Незеритовый блок] [Звезда Незера] [Незеритовый блок]")
    send_message(sender, u"&7[Делящееся ядро] [Инициатор] [Делящееся ядро]")
    send_message(sender, u"&7[Незеритовый блок] [Звезда Незера] [Незеритовый блок]")
    send_message(sender, u"&8&m------------------------------------------------")


def execute_nuke_command(sender, command_label, args):
    args = list(args)
    subcommand = to_unicode(args[0]).lower() if args else "help"

    if subcommand in ("recipe", "craft", "рецепт"):
        send_recipe(sender)
        return True

    if subcommand == "status":
        send_message(
            sender,
            NukeConfig.PREFIX
            + u"&7Боеголовок: &f{0}&7. Кратеров: &f{1}&7. Смертельная зона: &4{2:.0f}&7. Тяжёлое поражение: &c{3:.0f}&7. Кратер: &4{4}&7.".format(
                len(active_payloads),
                len(active_craters),
                NukeConfig.LETHAL_RADIUS,
                NukeConfig.SHOCKWAVE_RADIUS,
                NukeConfig.CRATER_RADIUS,
            ),
        )
        for payload in active_payloads.values():
            send_message(
                sender,
                u"&8 • &f{0} &7— {1}, оператор: &f{2}".format(
                    format_location(payload.location),
                    payload.stage,
                    payload.owner_name,
                ),
            )
        return True

    if subcommand == "give":
        if not is_admin(sender):
            send_message(sender, NukeConfig.PREFIX + u"&cНедостаточно прав.")
            return True
        target = sender if isinstance(sender, Player) else None
        if len(args) >= 2:
            target = Bukkit.getPlayer(to_java_string(args[1]))
        if target is None:
            send_message(sender, NukeConfig.PREFIX + u"&cИгрок не найден.")
            return True
        leftovers = target.getInventory().addItem(create_nuke())
        if not leftovers.isEmpty():
            target.getWorld().dropItemNaturally(target.getLocation(), create_nuke())
        send_message(
            sender,
            NukeConfig.PREFIX + u"&aБоеголовка выдана игроку &f{0}&a.".format(
                to_unicode(target.getName())
            ),
        )
        if target != sender:
            send_message(target, NukeConfig.PREFIX + u"&cВам выдана термоядерная боеголовка.")
        return True

    if subcommand == "cancel":
        if not is_admin(sender):
            send_message(sender, NukeConfig.PREFIX + u"&cНедостаточно прав.")
            return True
        payload = None
        crater = None
        if isinstance(sender, Player):
            current_world_id = world_key(sender.getWorld())
            payload = active_payloads.get(current_world_id)
            crater = active_craters.get(current_world_id)
        else:
            if active_payloads:
                payload = list(active_payloads.values())[0]
            elif active_craters:
                crater = list(active_craters.values())[0]
        if payload is None:
            if crater is not None:
                crater.cancel()
                broadcast(
                    NukeConfig.PREFIX
                    + u"&eФормирование кратера остановлено администратором. Уже удалённые блоки не восстановлены."
                )
                return True
            send_message(sender, NukeConfig.PREFIX + u"&eАктивная боеголовка не найдена.")
            return True
        payload.cancel(True)
        broadcast(NukeConfig.PREFIX + u"&aБоеголовка обезврежена администратором.")
        return True

    send_message(sender, NukeConfig.PREFIX + u"&f/nuke recipe &7— показать сложный крафт")
    send_message(sender, NukeConfig.PREFIX + u"&f/nuke status &7— активные боеголовки")
    if is_admin(sender):
        send_message(sender, NukeConfig.PREFIX + u"&f/nuke give [игрок] &7— выдать")
        send_message(sender, NukeConfig.PREFIX + u"&f/nuke cancel &7— обезвредить или остановить кратер")
    return True


def tab_nuke_command(sender, alias, args):
    args = list(args)
    if len(args) == 1:
        options = ["recipe", "status"]
        if is_admin(sender):
            options.extend(["give", "cancel"])
        prefix = to_unicode(args[0]).lower()
        return build_java_list([value for value in options if value.startswith(prefix)])
    if len(args) == 2 and to_unicode(args[0]).lower() == "give" and is_admin(sender):
        prefix = to_unicode(args[1]).lower()
        names = []
        for player in Bukkit.getOnlinePlayers():
            name = to_unicode(player.getName())
            if name.lower().startswith(prefix):
                names.append(name)
        return build_java_list(names)
    return build_java_list([])


def register_event(event_class, handler):
    if not BUKKIT_AVAILABLE or event_class is None:
        return False
    plugin = get_pyspigot_plugin()
    if plugin is None:
        return False

    class DirectListener(Listener):
        pass

    class DirectExecutor(EventExecutor):
        def execute(self, listener, event):
            try:
                handler(event)
            except Exception as exc:
                log_info(u"&cОшибка обработчика события: {0}".format(exc))

    listener = DirectListener()
    Bukkit.getPluginManager().registerEvent(
        event_class,
        listener,
        EventPriority.HIGHEST,
        DirectExecutor(),
        plugin,
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


def on_enable():
    global initialized
    if initialized or not BUKKIT_AVAILABLE:
        return
    plugin = get_pyspigot_plugin()
    if plugin is None:
        print("[SmartY-Nuclear] PySpigot plugin instance not found.")
        return

    log_info(u"Запуск {0} v{1} для Paper/Leaf 1.21.11.".format(
        NukeConfig.PLUGIN_NAME,
        NukeConfig.VERSION,
    ))
    unregister_events()
    register_recipes()
    verify_nuclear_advancements()
    register_event(PlayerDropItemEvent, handle_player_drop)
    register_event(PlayerJoinEvent, handle_player_join)
    register_event(BlockPlaceEvent, handle_block_place)
    register_event(CraftItemEvent, handle_craft_item)
    register_bukkit_command()
    for player in Bukkit.getOnlinePlayers():
        discover_recipes(player)
        prepare_nuclear_advancements(player)
    initialized = True
    log_info(u"&aВключён. &7Shift + Q с боеголовкой запускает воздушный сброс.")


def on_disable():
    global initialized
    for payload in list(active_payloads.values()):
        try:
            payload.cancel(True)
        except Exception:
            pass
    active_payloads.clear()
    for crater in list(active_craters.values()):
        try:
            crater.cancel()
        except Exception:
            pass
    active_craters.clear()
    for task_id in list(scheduled_task_ids):
        cancel_task(task_id)
    unregister_events()
    unregister_bukkit_commands()
    remove_recipes()
    initialized = False
    log_info(u"Выключен. Активные боеголовки возвращены в мир.")


def start(script=None):
    on_enable()


def stop(script=None):
    on_disable()


if __name__ == "__main__" or "ps" in globals() or "command_manager" in globals():
    on_enable()

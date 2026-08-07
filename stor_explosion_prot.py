# -*- coding: utf-8 -*-
"""Protect every item-holding block/entity from explosion destruction."""

import pyspigot as ps

from org.bukkit import Bukkit
from org.bukkit.inventory import InventoryHolder
from org.bukkit.event.block import BlockExplodeEvent
from org.bukkit.event.entity import EntityDamageEvent, EntityExplodeEvent


listener_mgr = ps.listener_manager()

# Fallback for storage-like blocks whose current Bukkit BlockState does not
# implement InventoryHolder on a particular server build.
STORAGE_MATERIALS = set([
    "CHEST", "TRAPPED_CHEST", "BARREL", "FURNACE", "BLAST_FURNACE", "SMOKER",
    "HOPPER", "DISPENSER", "DROPPER", "BREWING_STAND", "CRAFTER",
    "ENDER_CHEST", "DECORATED_POT", "CHISELED_BOOKSHELF", "JUKEBOX",
    "LECTERN", "CAMPFIRE", "SOUL_CAMPFIRE"
])


def _is_storage_block(block):
    if block is None:
        return False
    try:
        material_name = str(block.getType().name())
        if material_name in STORAGE_MATERIALS or material_name.endswith("_SHULKER_BOX"):
            return True
    except Exception:
        pass
    try:
        return isinstance(block.getState(), InventoryHolder)
    except Exception:
        return False


def _filter_explosion_blocks(event):
    try:
        blocks = event.blockList()
        iterator = blocks.iterator()
        protected = 0
        while iterator.hasNext():
            block = iterator.next()
            if _is_storage_block(block):
                iterator.remove()
                protected += 1
        if protected:
            Bukkit.getLogger().info(
                "[storage-protection] Saved {0} storage block(s) from an explosion.".format(protected))
    except Exception as exc:
        Bukkit.getLogger().warning("[storage-protection] Explosion filter error: " + str(exc))


def on_entity_explode(event):
    _filter_explosion_blocks(event)


def on_block_explode(event):
    _filter_explosion_blocks(event)


def on_inventory_entity_damage(event):
    try:
        cause = str(event.getCause().name())
        if cause not in ("BLOCK_EXPLOSION", "ENTITY_EXPLOSION"):
            return
        if isinstance(event.getEntity(), InventoryHolder):
            event.setCancelled(True)
    except Exception as exc:
        Bukkit.getLogger().warning("[storage-protection] Entity protection error: " + str(exc))


listener_mgr.registerListener(on_entity_explode, EntityExplodeEvent)
listener_mgr.registerListener(on_block_explode, BlockExplodeEvent)
listener_mgr.registerListener(on_inventory_entity_damage, EntityDamageEvent)
Bukkit.getLogger().info("[storage-protection] Storage explosion protection loaded.")

# burmalda-plugins

PySpigot scripts for the Burmalda Minecraft server running Paper/Leaf 1.21.11.

## Layout

- `*.py` - server plugins loaded from `plugins/PySpigot/scripts`.
- `smarty_nuclear_advancements/` - source data pack for the vanilla nuclear advancement tab.
- `data/` - runtime server state; intentionally excluded from Git.

## Nuclear advancements

Package the contents of `smarty_nuclear_advancements/` so that `pack.mcmeta` is
at the archive root, then place the archive in:

```text
<server>/<level-name>/datapacks/smarty_nuclear_advancements.zip
```

Reload data packs before reloading `nuclear_bomb.py`:

```text
/minecraft:reload
/ps reload nuclear_bomb.py
```

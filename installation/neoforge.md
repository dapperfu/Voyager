# NeoForge 1.21.1

Voyager's bot joins a NeoForge dedicated server. The first release speaks Minecraft 1.21.1. A later game version is a new protocol adapter, not a rewrite of the skills or the Python agents.

## Supported matrix

| Piece | First release |
| --- | --- |
| Minecraft | 1.21.1 |
| NeoForge | 21.1.x, tested on 21.1.265 |
| Mineflayer | 4.39.0 |
| mineflayer-pathfinder | 2.4.5 |
| Handshake library | `minecraft-protocol-forge` commit `af4dcd8` |
| Node.js | 22.23.4 |
| Python | 3.11.14 in the image |

`NEOFORGE_VERSION` overrides the server build. A newer 21.1.x server that still speaks this handshake needs no bot change. A handshake break is a new commit pin inside `voyager/env/mineflayer/protocol/1.21.1.js`.

## Run

Ollama must be reachable for `make run`. `make smoke` only checks that the bot can join and observe.

```bash
make build
make smoke
make run
```

The game is published on port 25566 so it can run beside another server on 25565. The bot's HTTP API stays on 127.0.0.1 inside the Voyager container.

The server is Survival and Peaceful, seed `1211`, and the user `bot` is an operator. Spawn protection is off, so mined blocks and mob kills leave drops. While a model call is in progress the bot sends `/tick freeze`. The next action sends `/tick unfreeze`.

`make clean` stops the containers and keeps the world volume.

## Point the same image at another 1.21.1 server

Set `MC_HOST` and `MC_PORT` for the Voyager service. The default channel file is empty, which is what a vanilla NeoForge server needs.

A modpack server also needs its channel list. `MC_CHANNELS_FILE` replaces `voyager/env/mineflayer/protocol/channels/1.21.1.json`. Each entry is an object with `name`, `version`, and optional `flow` (`clientbound` or `serverbound`). A non-empty list turns on the modded packet path: recipe packets the vanilla schema cannot read are skipped, and undecodable play packets are dropped without losing frame alignment. Leave the list empty when the bot should craft, because crafting uses the recipe book.

`MC_VERSION` defaults to `1.21.1`. Any other value is rejected with the list of adapters this build includes.

## Next adapter

1. Confirm Mineflayer and `minecraft-data` both contain the new version.
2. Add `voyager/env/mineflayer/protocol/<version>.js` with `botOptions`, `install`, `dataPatches`, and the freeze commands.
3. Add `voyager/env/mineflayer/protocol/channels/<version>.json`.
4. Register the version in `voyager/env/mineflayer/protocol/index.js`.
5. Run `make smoke` against a server of that version.

## Known limit

`minecrafthawkeye` 1.3.9 is loaded, so bow and trident code can call `bot.hawkEye`. Melee combat uses `mineflayer-pvp` 1.3.2. If a future Mineflayer release changes projectile physics, melee combat remains the path that does not depend on HawkEye.

"use strict";

const fs = require("fs");
const path = require("path");
const minecraftData = require("minecraft-data");
const { ProtoDef } = require("protodef");
const { neoforgeHandshake } = require("minecraft-protocol-forge");

const VERSION = "1.21.1";
const CHANNEL_NAME = /^[a-z0-9_.-]+:[a-z0-9/._-]+$/;

// Mod argument types the vanilla schema does not know. sable:sub_level writes one
// flag byte; singleton infos such as sable:vec3_absolute write nothing.
const ARGUMENT_PROPERTIES = {
    "forge:enum": "string",
    "forge:modid": "void",
    "neoforge:enum": "string",
    "neoforge:modid": "void",
    "minecraft:test_argument": "void",
    "minecraft:test_class": "void",
    "sable:sub_level": "i8",
    "sable:vec3_absolute": "void",
};

const registryProto = new ProtoDef(false);
registryProto.addTypes(
    require("minecraft-protocol-forge/src/client/data/neoforgeRegistries.json").types
);
const commandSchemas = new WeakMap();
const commandNodeTemplate = JSON.parse(
    JSON.stringify(minecraftData(VERSION).protocol.types.command_node)
);

function acknowledge(client, channel) {
    client.write("custom_payload", { channel, data: Buffer.alloc(0) });
}

function modPlayChannels(entries) {
    const channels = {};
    for (const entry of entries) {
        if (
            !CHANNEL_NAME.test(entry.name) ||
            typeof entry.version !== "string" ||
            entry.version.length === 0
        ) {
            throw new Error(`Invalid NeoForge channel entry ${JSON.stringify(entry)}`);
        }
        if (
            entry.flow !== undefined &&
            entry.flow !== "clientbound" &&
            entry.flow !== "serverbound"
        ) {
            throw new Error(`Invalid NeoForge channel flow for ${entry.name}`);
        }
        const spec = { version: entry.version, optional: true };
        if (entry.flow) spec.flow = entry.flow;
        // Serverbound channels are never delivered to the client. Every other
        // channel still needs a handler so negotiation can complete.
        if (entry.flow !== "serverbound") spec.handler = () => {};
        channels[entry.name] = spec;
    }
    return channels;
}

function decodeRegistry(type, bytes) {
    const parsed = registryProto.parsePacketBuffer(type, bytes);
    if (parsed.metadata.size !== bytes.length) {
        throw new Error("Trailing NeoForge registry data");
    }
    return parsed.data;
}

function installCommandArgumentTypes(client, entries) {
    const data = minecraftData(client.version);
    const node = JSON.parse(JSON.stringify(commandNodeTemplate));
    const fields = node[1]
        .find((field) => field.name === "extraNodeData")
        .type[1].fields[2][1];
    const parser = fields.find((field) => field.name === "parser");
    const numeric = parser.type[0] === "mapper";
    if (parser.type !== "string" && !numeric) {
        throw new Error("Unsupported command argument schema");
    }
    if ((numeric && !entries) || (!numeric && entries)) return;

    const properties = fields.find((field) => field.name === "properties").type[1]
        .fields;
    const knownNames = new Set(
        numeric ? Object.values(parser.type[1].mappings) : Object.keys(properties)
    );
    const extra = {
        ...ARGUMENT_PROPERTIES,
        "minecraft:nbt_compound_tag": properties["minecraft:nbt"],
    };
    const mappings = {};
    const names = new Set();
    const ignored = [];
    for (const { key, value } of numeric ? entries : []) {
        if (
            !Number.isInteger(value) ||
            value < 0 ||
            Object.hasOwn(mappings, value) ||
            names.has(key)
        ) {
            throw new Error("Duplicate or invalid Forge command argument registry entry");
        }
        if (!knownNames.has(key) && !Object.hasOwn(extra, key)) {
            extra[key] = "void";
            ignored.push(key);
        }
        mappings[value] = key;
        names.add(key);
    }
    if (ignored.length) {
        console.log(`Command argument types with no extra data: ${ignored.join(", ")}`);
    }
    if (numeric) parser.type[1].mappings = mappings;
    Object.assign(properties, extra);

    const version = data.version.majorVersion;
    const existing = client.customPackets?.[version];
    const ownsExisting =
        existing?.types?.command_node === "forge_command_node" &&
        existing?.types?.forge_command_node === commandSchemas.get(client);
    if (
        !ownsExisting &&
        (existing?.types?.command_node || existing?.types?.forge_command_node)
    ) {
        throw new Error("A custom command_node schema is already installed");
    }
    client.customPackets = {
        ...client.customPackets,
        [version]: {
            ...existing,
            types: {
                ...existing?.types,
                command_node: "forge_command_node",
                forge_command_node: node,
            },
        },
    };
    commandSchemas.set(client, node);
}

function registryChannels(client) {
    let pending;
    let started = false;
    client.on("state", (state) => {
        if (state !== "configuration") return;
        pending = undefined;
        started = false;
        client.neoforgeRegistrySyncComplete = false;
    });
    return {
        "neoforge:frozen_registry_sync_start": {
            version: "1",
            flow: "clientbound",
            optional: true,
            handler: (bytes) => {
                if (started) throw new Error("Duplicate NeoForge registry sync start");
                const names = decodeRegistry("names", bytes);
                pending = new Set(names);
                if (pending.size !== names.length) {
                    throw new Error("Duplicate NeoForge registry name");
                }
                started = true;
                console.log(`NeoForge registry sync started (${names.length} registries)`);
            },
        },
        "neoforge:frozen_registry": {
            version: "1",
            flow: "clientbound",
            optional: true,
            handler: (bytes) => {
                const registry = decodeRegistry("registry", bytes);
                if (!pending?.has(registry.name)) {
                    throw new Error(`Unexpected NeoForge registry ${registry.name}`);
                }
                if (registry.name === "minecraft:command_argument_type") {
                    installCommandArgumentTypes(client, registry.ids);
                }
                if (registry.name === "minecraft:data_component_type") {
                    const vanilla =
                        minecraftData(VERSION).protocol.types.SlotComponentType[1].mappings;
                    const shifted = [];
                    const extra = [];
                    for (const entry of registry.ids) {
                        const vanillaName = vanilla[String(entry.value)];
                        const short = entry.key.startsWith("minecraft:")
                            ? entry.key.slice("minecraft:".length)
                            : null;
                        if (short && vanillaName && short !== vanillaName) {
                            shifted.push(`${entry.value}:${entry.key}!=${vanillaName}`);
                        }
                        if (!entry.key.startsWith("minecraft:")) {
                            extra.push(`${entry.value}:${entry.key}`);
                        }
                    }
                    if (shifted.length || extra.length) {
                        console.log(
                            `Data components: ${registry.ids.length} total, ${extra.length} added by mods`
                        );
                    }
                }
                pending.delete(registry.name);
            },
        },
        "neoforge:frozen_registry_sync_completed": {
            version: "1",
            optional: true,
            handler: (bytes) => {
                if (bytes.length || !pending || pending.size) {
                    const left = pending ? [...pending].join(", ") : "not started";
                    throw new Error(`Incomplete NeoForge registry sync: ${left}`);
                }
                pending = undefined;
                acknowledge(client, "neoforge:frozen_registry_sync_completed");
                client.neoforgeRegistrySyncComplete = true;
                console.log("NeoForge registry sync completed");
            },
        },
    };
}

function skipUndecodablePlayPackets(client) {
    const playPacketNames =
        minecraftData(VERSION).protocol.play.toClient.types.packet[1][0].type[1].mappings;
    client.on("state", (state) => {
        if (state !== "play") return;
        const parser = client.deserializer;
        if (!parser || parser.parsePacketBuffer.__hooked) return;
        parser.noErrorLogging = true;
        const orig = parser.parsePacketBuffer.bind(parser);
        const skipped = new Set();
        const hooked = (chunk) => {
            try {
                return orig(chunk);
            } catch (err) {
                // The frame length is already known, so dropping this body keeps
                // later packets aligned. Mod recipes and item components use data
                // the vanilla schema cannot read.
                let id = 0;
                let shift = 0;
                for (let n = 0; n < 5 && n < chunk.length; n++) {
                    const b = chunk[n];
                    id |= (b & 0x7f) << shift;
                    if ((b & 0x80) === 0) break;
                    shift += 7;
                }
                const name =
                    playPacketNames[`0x${id.toString(16).padStart(2, "0")}`] || String(id);
                if (!skipped.has(name)) {
                    skipped.add(name);
                    console.log(
                        `Skipped ${name} (${chunk.length} bytes): modded data is outside the vanilla protocol schema`
                    );
                }
                return {
                    data: { name: "mod_skipped", params: {} },
                    metadata: { size: chunk.length },
                    buffer: chunk,
                    fullBuffer: chunk,
                };
            }
        };
        hooked.__hooked = true;
        parser.parsePacketBuffer = hooked;
    });
}

function defaultChannelFile() {
    return path.join(__dirname, "channels", `${VERSION}.json`);
}

function readChannelEntries(channelsFile) {
    const file = channelsFile || process.env.MC_CHANNELS_FILE || defaultChannelFile();
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    if (!Array.isArray(parsed)) {
        throw new Error(`NeoForge channel file ${file} must be a JSON array`);
    }
    return parsed;
}

// The server rejects vanilla clients. This speaks NeoForge 21.1's configuration
// handshake without running the Java loader. A non-empty channel list means a
// modpack: recipe bodies and other play packets that the vanilla schema cannot
// read are dropped so the frame stream stays aligned. Vanilla NeoForge keeps
// the recipe book so bot.craft still works.
function install(bot, options = {}) {
    const client = bot._client;
    if (client.version !== VERSION) {
        throw new Error(
            `NeoForge 21.1 handshake requires Minecraft ${VERSION}, client version is ${client.version}`
        );
    }

    const entries = options.channels || readChannelEntries(options.channelsFile);
    const skipRecipes =
        options.skipRecipes !== undefined ? options.skipRecipes : entries.length > 0;

    client.on("custom_payload", (packet) => {
        if (packet.channel !== "neoforge:modded_network_setup_failed") return;
        const detail = packet.data
            .toString("utf8")
            .replace(/[^\x09\x0a\x0d\x20-\x7e]+/g, " ")
            .replace(/ +/g, " ")
            .trim();
        console.error(`NeoForge rejection detail: ${detail}`);
    });

    if (skipRecipes) {
        minecraftData(VERSION).protocol.play.toClient.types.packet_declare_recipes =
            "restBuffer";
        skipUndecodablePlayPackets(client);
    }

    const playChannels = modPlayChannels(entries);
    // Mineflayer already answers configuration pings. A second pong makes the
    // server start the next task while registry sync is still running.
    neoforgeHandshake(client, {
        respondToPing: false,
        configurationChannels: {
            ...playChannels,
            "neoforge:extensible_enum_data": {
                version: "1",
                flow: "clientbound",
                optional: true,
                handler: () => acknowledge(client, "neoforge:extensible_enum_ack"),
            },
            "neoforge:feature_flags": {
                version: "1",
                flow: "clientbound",
                optional: true,
                handler: () => acknowledge(client, "neoforge:feature_flags_ack"),
            },
            ...registryChannels(client),
        },
        playChannels,
    });

    client.on("neoforgeChannels", () => {
        console.log("NeoForge channel negotiation accepted");
    });
    client.on("error", (err) => {
        if (err && err.code === "NEOFORGE_CHANNEL_MISMATCH") {
            console.error(
                "NeoForge rejected the channel list. A required mod channel is missing or its version does not match."
            );
        }
    });
    console.log(
        `NeoForge 21.1 handshake enabled with ${Object.keys(playChannels).length} mod channels`
    );
}

function botOptions(config) {
    const options = {
        host: config.host,
        port: Number(config.port),
        username: config.username,
        auth: config.auth || "offline",
        version: VERSION,
        disableChatSigning: true,
        // Modded entity packets can be one byte longer than the vanilla schema.
        // The frame boundary is already known; this only hides that size notice.
        hideErrors: true,
        checkTimeoutInterval: 60 * 60 * 1000,
    };
    if (config.password) options.password = config.password;
    if (config.profilesFolder) options.profilesFolder = config.profilesFolder;
    return options;
}

function alias(table, from, to) {
    if (table && table[to]) table[from] = table[to];
}

function dataPatches(mcData) {
    alias(mcData.itemsByName, "leather_cap", "leather_helmet");
    alias(mcData.itemsByName, "leather_tunic", "leather_chestplate");
    alias(mcData.itemsByName, "leather_pants", "leather_leggings");
    alias(mcData.itemsByName, "leather_boots", "leather_boots");
    alias(mcData.itemsByName, "lapis_lazuli_ore", "lapis_ore");
    alias(mcData.blocksByName, "lapis_lazuli_ore", "lapis_ore");
    alias(mcData.blocksByName, "grass", "short_grass");
    alias(mcData.itemsByName, "grass", "short_grass");
    return mcData;
}

module.exports = {
    version: VERSION,
    neoforge: "21.1",
    commands: {
        freeze: "/tick freeze",
        unfreeze: "/tick unfreeze",
    },
    botOptions,
    dataPatches,
    install,
};

"use strict";

const fs = require("fs");
const path = require("path");

// First release is Minecraft 1.21.1. A later version is a new adapter file
// plus a line here. Skills, observations, and the Python agents stay put.
const adapters = {
    "1.21.1": () => require("./1.21.1"),
};

function supportedVersions() {
    return Object.keys(adapters);
}

function forVersion(version) {
    const load = adapters[version];
    if (!load) {
        const supported = supportedVersions().join(", ");
        throw new Error(
            `Minecraft ${version} has no adapter. This build supports: ${supported}`
        );
    }
    return load();
}

function channelFileFor(version, channelsFile) {
    if (channelsFile) return channelsFile;
    return path.join(__dirname, "channels", `${version}.json`);
}

function loadChannels(version, channelsFile) {
    const file = channelFileFor(version, channelsFile);
    let parsed;
    try {
        parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    } catch (err) {
        throw new Error(`Cannot read NeoForge channel file ${file}: ${err.message}`);
    }
    if (!Array.isArray(parsed)) {
        throw new Error(`NeoForge channel file ${file} must be a JSON array`);
    }
    return parsed;
}

module.exports = {
    supportedVersions,
    forVersion,
    channelFileFor,
    loadChannels,
};

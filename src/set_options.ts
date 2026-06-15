#!/usr/bin/env node

import { buildConfig, ConfigRule } from "./config_utils.js";

const CSS_THEME: string = "dark";
const DATA_PATH: string = "/data";
const FOUNDRY_PORT: number = 30000;
const LANGUAGE: string = "en.core";
const MAXIMUM_PORT: number = 65535;
const MINIMUM_PORT: number = 1;
const UPDATE_CHANNEL: string = "stable";

const rules: ConfigRule[] = [
  { envVar: "FOUNDRY_AWS_CONFIG", configKey: "awsConfig", type: "string", sensitive: true },
  { envVar: "FOUNDRY_COMPRESS_WEBSOCKET", configKey: "compressSocket", type: "boolean", default: false },
  { envVar: "FOUNDRY_MINIFY_STATIC_FILES", configKey: "compressStatic", type: "boolean", default: false },
  { envVar: "FOUNDRY_CSS_THEME", configKey: "cssTheme", type: "string", default: CSS_THEME },
  { envVar: "FOUNDRY_DELETE_NEDB", configKey: "deleteNEDB", type: "boolean", default: false },
  { envVar: "FOUNDRY_DEMO_CONFIG", configKey: "demo", type: "json" },
  { envVar: "FOUNDRY_HOSTNAME", configKey: "hostname", type: "string" },
  { envVar: "FOUNDRY_HOT_RELOAD", configKey: "hotReload", type: "boolean", default: false },
  { envVar: "FOUNDRY_LANGUAGE", configKey: "language", type: "string", default: LANGUAGE },
  { envVar: "FOUNDRY_LOCAL_HOSTNAME", configKey: "localHostname", type: "string" },
  { envVar: "FOUNDRY_PASSWORD_SALT", configKey: "passwordSalt", type: "string", sensitive: true },
  { envVar: "FOUNDRY_PROTOCOL", configKey: "protocol", type: "string" },
  { envVar: "FOUNDRY_PROXY_PORT", configKey: "proxyPort", type: "clampedInt", min: MINIMUM_PORT, max: MAXIMUM_PORT },
  { envVar: "FOUNDRY_PROXY_SSL", configKey: "proxySSL", type: "boolean", default: false },
  { envVar: "FOUNDRY_ROUTE_PREFIX", configKey: "routePrefix", type: "string" },
  { envVar: "FOUNDRY_SERVICE_CONFIG", configKey: "serviceConfig", type: "string", sensitive: true },
  { envVar: "FOUNDRY_SSL_CERT", configKey: "sslCert", type: "path" },
  { envVar: "FOUNDRY_SSL_KEY", configKey: "sslKey", type: "path" },
  { envVar: "FOUNDRY_TELEMETRY", configKey: "telemetry", type: "triboolean" },
  { envVar: "FOUNDRY_TEMP_DIR", configKey: "tempDir", type: "path" },
  { envVar: "FOUNDRY_UNIX_SOCKET", configKey: "unixSocket", type: "path" },
  { envVar: "FOUNDRY_UPNP", configKey: "upnp", type: "boolean", default: false },
  { envVar: "FOUNDRY_UPNP_LEASE_DURATION", configKey: "upnpLeaseDuration", type: "string" },
  { envVar: "FOUNDRY_WORLD", configKey: "world", type: "string" },
];

const logLevel = process.env.CONTAINER_VERBOSE ? "debug" : "warn";
const options = {
  ...buildConfig(rules, process.env, logLevel),
  dataPath: DATA_PATH,
  fullscreen: false,
  port: FOUNDRY_PORT,
  updateChannel: UPDATE_CHANNEL,
};

process.stdout.write(JSON.stringify(options, null, "  "));

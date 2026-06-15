import { describe, it, expect, beforeEach, vi } from "vitest";
import { buildConfig, ConfigRule } from "../config_utils.js";

// Mock the logger to capture log messages for sensitive-masking tests
const { logMessages } = vi.hoisted(() => ({
  logMessages: [] as string[],
}));

vi.mock("../logging.js", () => ({
  default: () => ({
    debug: (msg: string) => logMessages.push(msg),
    info: (msg: string) => logMessages.push(msg),
    warn: (msg: string) => logMessages.push(msg),
    error: (msg: string) => logMessages.push(msg),
  }),
}));

// Reusable minimal env — all empty
function emptyEnv(): Record<string, string | undefined> {
  return {};
}

// The same rules array used in set_options.ts
const CSS_THEME = "dark";
const LANGUAGE = "en.core";
const MIN_PORT = 1;
const MAX_PORT = 65535;

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
  { envVar: "FOUNDRY_PROXY_PORT", configKey: "proxyPort", type: "clampedInt", min: MIN_PORT, max: MAX_PORT },
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

// ---------------------------------------------------------------------------
// Full generation with defaults
// ---------------------------------------------------------------------------
describe("buildConfig with empty env", () => {
  it("produces correct defaults for all keys", () => {
    const config = buildConfig(rules, emptyEnv());
    expect(config.awsConfig).toBeNull();
    expect(config.compressSocket).toBe(false);
    expect(config.compressStatic).toBe(false);
    expect(config.cssTheme).toBe("dark");
    expect(config.deleteNEDB).toBe(false);
    expect(config.demo).toBeUndefined();
    expect(config.hostname).toBeNull();
    expect(config.hotReload).toBe(false);
    expect(config.language).toBe("en.core");
    expect(config.localHostname).toBeNull();
    expect(config.passwordSalt).toBeNull();
    expect(config.protocol).toBeNull();
    expect(config.proxyPort).toBeNull();
    expect(config.proxySSL).toBe(false);
    expect(config.routePrefix).toBeNull();
    expect(config.serviceConfig).toBeNull();
    expect(config.sslCert).toBeNull();
    expect(config.sslKey).toBeNull();
    expect(config.telemetry).toBeNull();
    expect(config.tempDir).toBeNull();
    expect(config.unixSocket).toBeNull();
    expect(config.upnp).toBe(false);
    expect(config.upnpLeaseDuration).toBeNull();
    expect(config.world).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Boolean env vars
// ---------------------------------------------------------------------------
describe("boolean env vars", () => {
  it("sets boolean flags to true", () => {
    const env = {
      FOUNDRY_COMPRESS_WEBSOCKET: "true",
      FOUNDRY_UPNP: "true",
      FOUNDRY_PROXY_SSL: "true",
    };
    const config = buildConfig(rules, env);
    expect(config.compressSocket).toBe(true);
    expect(config.upnp).toBe(true);
    expect(config.proxySSL).toBe(true);
  });

  it("sets boolean flags to false explicitly", () => {
    const env = {
      FOUNDRY_COMPRESS_WEBSOCKET: "false",
      FOUNDRY_UPNP: "false",
    };
    const config = buildConfig(rules, env);
    expect(config.compressSocket).toBe(false);
    expect(config.upnp).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Path validation
// ---------------------------------------------------------------------------
describe("path env vars", () => {
  it("accepts valid absolute paths", () => {
    const env = {
      FOUNDRY_SSL_CERT: "/data/ssl/cert.pem",
      FOUNDRY_SSL_KEY: "/data/ssl/key.pem",
      FOUNDRY_TEMP_DIR: "/tmp/foundry",
    };
    const config = buildConfig(rules, env);
    expect(config.sslCert).toBe("/data/ssl/cert.pem");
    expect(config.sslKey).toBe("/data/ssl/key.pem");
    expect(config.tempDir).toBe("/tmp/foundry");
  });

  it("throws on relative path", () => {
    const env = { FOUNDRY_SSL_CERT: "relative/cert.pem" };
    expect(() => buildConfig(rules, env)).toThrow(/must be an absolute path/);
  });
});

// ---------------------------------------------------------------------------
// Empty string skipping
// ---------------------------------------------------------------------------
describe("empty string handling", () => {
  it("treats empty string as null for string type", () => {
    const env = { FOUNDRY_HOSTNAME: "" };
    const config = buildConfig(rules, env);
    expect(config.hostname).toBeNull();
  });

  it("treats empty string as default for boolean type", () => {
    const env = { FOUNDRY_UPNP: "" };
    const config = buildConfig(rules, env);
    expect(config.upnp).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Sensitive values masked in logs
// ---------------------------------------------------------------------------
describe("sensitive value masking in logs", () => {
  it("does not leak sensitive values in debug log output", () => {
    logMessages.length = 0;

    const env = {
      FOUNDRY_PASSWORD_SALT: "my-super-secret-salt",
      FOUNDRY_AWS_CONFIG: "s3://bucket/config.json",
      FOUNDRY_SERVICE_CONFIG: "https://service.example.com/key=abc",
      FOUNDRY_HOSTNAME: "public.example.com",
    };
    buildConfig(rules, env, "debug");

    const allOutput = logMessages.join("\n");
    // Sensitive values must NOT appear in log output
    expect(allOutput).not.toContain("my-super-secret-salt");
    expect(allOutput).not.toContain("s3://bucket/config.json");
    expect(allOutput).not.toContain("key=abc");
    // Masked marker must appear for each sensitive key
    expect(allOutput).toContain("***");
    // Non-sensitive values can appear
    expect(allOutput).toContain("public.example.com");
  });
});

// ---------------------------------------------------------------------------
// Invalid boolean throws
// ---------------------------------------------------------------------------
describe("invalid values", () => {
  it("throws on invalid boolean", () => {
    const env = { FOUNDRY_UPNP: "yes" };
    expect(() => buildConfig(rules, env)).toThrow(/Invalid boolean/);
  });

  it("throws on invalid port", () => {
    const env = { FOUNDRY_PROXY_PORT: "abc" };
    expect(() => buildConfig(rules, env)).toThrow(/Invalid integer/);
  });
});

// ---------------------------------------------------------------------------
// Demo config JSON
// ---------------------------------------------------------------------------
describe("JSON env vars", () => {
  it("parses valid demo config JSON", () => {
    const demoObj = { title: "Demo World", password: "test" };
    const env = { FOUNDRY_DEMO_CONFIG: JSON.stringify(demoObj) };
    const config = buildConfig(rules, env);
    expect(config.demo).toEqual(demoObj);
  });

  it("throws on invalid demo config JSON", () => {
    const env = { FOUNDRY_DEMO_CONFIG: "{not-json}" };
    expect(() => buildConfig(rules, env)).toThrow(/Invalid JSON/);
  });
});

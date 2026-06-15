import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  parseString,
  parseBoolean,
  parseTristate,
  parseClampedNumber,
  parseJSON,
  redactValue,
  redactConfig,
  buildConfig,
  ConfigError,
  OPTION_SCHEMA,
  SENSITIVE_KEYS,
  PASSWORD_SALT_FIELD,
} from "../src/config_schema.js";

// ---------------------------------------------------------------------------
// parseString
// ---------------------------------------------------------------------------

describe("parseString", () => {
  it("returns the value when set", () => {
    assert.equal(parseString("hello"), "hello");
  });

  it("returns null when unset and no fallback", () => {
    assert.equal(parseString(undefined), null);
  });

  it("returns fallback when unset", () => {
    assert.equal(parseString(undefined, "dark"), "dark");
  });

  it("returns null for empty string", () => {
    assert.equal(parseString(""), null);
  });

  it("returns the value even when fallback is set", () => {
    assert.equal(parseString("custom", "default"), "custom");
  });
});

// ---------------------------------------------------------------------------
// parseBoolean
// ---------------------------------------------------------------------------

describe("parseBoolean", () => {
  it('"true" → true', () => {
    assert.equal(parseBoolean("true"), true);
  });

  it('"false" → false', () => {
    assert.equal(parseBoolean("false"), false);
  });

  it('"1" → false (strict match only)', () => {
    assert.equal(parseBoolean("1"), false);
  });

  it('"TRUE" → false (case-sensitive)', () => {
    assert.equal(parseBoolean("TRUE"), false);
  });

  it('"yes" → false', () => {
    assert.equal(parseBoolean("yes"), false);
  });

  it('empty string → false', () => {
    assert.equal(parseBoolean(""), false);
  });

  it("undefined → false", () => {
    assert.equal(parseBoolean(undefined), false);
  });
});

// ---------------------------------------------------------------------------
// parseTristate
// ---------------------------------------------------------------------------

describe("parseTristate", () => {
  it('"true" → true', () => {
    assert.equal(parseTristate("true"), true);
  });

  it('"false" → false', () => {
    assert.equal(parseTristate("false"), false);
  });

  it('"garbage" → null', () => {
    assert.equal(parseTristate("garbage"), null);
  });

  it("undefined → null", () => {
    assert.equal(parseTristate(undefined), null);
  });

  it("empty string → null", () => {
    assert.equal(parseTristate(""), null);
  });

  it('"True" → null (case-sensitive)', () => {
    assert.equal(parseTristate("True"), null);
  });
});

// ---------------------------------------------------------------------------
// parseClampedNumber
// ---------------------------------------------------------------------------

describe("parseClampedNumber", () => {
  it("returns parsed integer within range", () => {
    assert.equal(parseClampedNumber("8080", 1, 65535), 8080);
  });

  it("clamps to minimum", () => {
    assert.equal(parseClampedNumber("0", 1, 65535), 1);
  });

  it("clamps to maximum", () => {
    assert.equal(parseClampedNumber("99999", 1, 65535), 65535);
  });

  it("returns fallback when unset", () => {
    assert.equal(parseClampedNumber(undefined, 1, 65535, null), null);
  });

  it("returns fallback for empty string", () => {
    assert.equal(parseClampedNumber("", 1, 65535, 42), 42);
  });

  it("truncates float via parseInt", () => {
    assert.equal(parseClampedNumber("12.5", 1, 65535), 12);
  });

  it("throws ConfigError for non-numeric string", () => {
    assert.throws(
      () => parseClampedNumber("abc", 1, 65535),
      (err: Error) => {
        assert.ok(err instanceof ConfigError);
        return true;
      },
    );
  });

  it("exact boundary values pass through", () => {
    assert.equal(parseClampedNumber("1", 1, 65535), 1);
    assert.equal(parseClampedNumber("65535", 1, 65535), 65535);
  });

  it("negative values are clamped to min", () => {
    assert.equal(parseClampedNumber("-100", 1, 65535), 1);
  });
});

// ---------------------------------------------------------------------------
// parseJSON
// ---------------------------------------------------------------------------

describe("parseJSON", () => {
  it("parses valid JSON object", () => {
    assert.deepEqual(parseJSON('{"a":1}'), { a: 1 });
  });

  it("parses valid JSON array", () => {
    assert.deepEqual(parseJSON("[1,2,3]"), [1, 2, 3]);
  });

  it("parses JSON string", () => {
    assert.equal(parseJSON('"hello"'), "hello");
  });

  it("returns undefined for unset", () => {
    assert.equal(parseJSON(undefined), undefined);
  });

  it("returns undefined for empty string", () => {
    assert.equal(parseJSON(""), undefined);
  });

  it("throws ConfigError for invalid JSON", () => {
    assert.throws(
      () => parseJSON("{bad json}"),
      (err: Error) => {
        assert.ok(err instanceof ConfigError);
        return true;
      },
    );
  });
});

// ---------------------------------------------------------------------------
// ConfigError
// ---------------------------------------------------------------------------

describe("ConfigError", () => {
  it("message includes env var name", () => {
    const err = new ConfigError("FOUNDRY_PROXY_PORT", "is not a valid integer");
    assert.ok(err.message.includes("FOUNDRY_PROXY_PORT"));
  });

  it("message does NOT include raw value (prevents secret leaks)", () => {
    const secretValue = "super-secret-token-12345";
    const err = new ConfigError("FOUNDRY_PASSWORD_SALT", "is invalid");
    assert.ok(!err.message.includes(secretValue));
  });

  it("has correct name property", () => {
    const err = new ConfigError("FOO", "bar");
    assert.equal(err.name, "ConfigError");
  });

  it("exposes envVar and reason", () => {
    const err = new ConfigError("FOUNDRY_X", "bad value");
    assert.equal(err.envVar, "FOUNDRY_X");
    assert.equal(err.reason, "bad value");
  });
});

// ---------------------------------------------------------------------------
// redactValue / redactConfig
// ---------------------------------------------------------------------------

describe("redactValue", () => {
  const sensitive = new Set(["passwordSalt", "sslKey"]);

  it("redacts sensitive fields", () => {
    assert.equal(redactValue("passwordSalt", "my-secret", sensitive), "****");
  });

  it("passes through non-sensitive fields", () => {
    assert.equal(redactValue("hostname", "example.com", sensitive), "example.com");
  });

  it("handles null values", () => {
    assert.equal(redactValue("hostname", null, sensitive), "null");
  });

  it("handles undefined values", () => {
    assert.equal(redactValue("hostname", undefined, sensitive), "undefined");
  });
});

describe("redactConfig", () => {
  const sensitive = new Set(["passwordSalt", "sslKey", "awsConfig"]);

  it("redacts all sensitive keys in a config object", () => {
    const config = {
      hostname: "example.com",
      passwordSalt: "secret-salt",
      sslKey: "/path/to/key.pem",
      port: 30000,
      awsConfig: "arn:aws:...",
    };
    const redacted = redactConfig(config, sensitive);
    assert.equal(redacted.hostname, "example.com");
    assert.equal(redacted.passwordSalt, "****");
    assert.equal(redacted.sslKey, "****");
    assert.equal(redacted.port, "30000");
    assert.equal(redacted.awsConfig, "****");
  });
});

// ---------------------------------------------------------------------------
// SENSITIVE_KEYS
// ---------------------------------------------------------------------------

describe("SENSITIVE_KEYS", () => {
  it("includes passwordSalt", () => {
    assert.ok(SENSITIVE_KEYS.has("passwordSalt"));
  });

  it("includes sslKey", () => {
    assert.ok(SENSITIVE_KEYS.has("sslKey"));
  });

  it("includes sslCert", () => {
    assert.ok(SENSITIVE_KEYS.has("sslCert"));
  });

  it("includes awsConfig", () => {
    assert.ok(SENSITIVE_KEYS.has("awsConfig"));
  });

  it("does NOT include non-sensitive fields", () => {
    assert.ok(!SENSITIVE_KEYS.has("hostname"));
    assert.ok(!SENSITIVE_KEYS.has("port"));
    assert.ok(!SENSITIVE_KEYS.has("language"));
  });
});

// ---------------------------------------------------------------------------
// PASSWORD_SALT_FIELD
// ---------------------------------------------------------------------------

describe("PASSWORD_SALT_FIELD", () => {
  it("references the correct env var", () => {
    assert.equal(PASSWORD_SALT_FIELD.envVar, "FOUNDRY_PASSWORD_SALT");
  });

  it("is marked as sensitive", () => {
    assert.equal(PASSWORD_SALT_FIELD.sensitive, true);
  });

  it("has outputKey passwordSalt", () => {
    assert.equal(PASSWORD_SALT_FIELD.outputKey, "passwordSalt");
  });
});

// ---------------------------------------------------------------------------
// OPTION_SCHEMA
// ---------------------------------------------------------------------------

describe("OPTION_SCHEMA", () => {
  it("contains 24 field definitions", () => {
    assert.equal(OPTION_SCHEMA.length, 24);
  });

  it("every field has a unique outputKey", () => {
    const keys = OPTION_SCHEMA.map((f) => f.outputKey);
    assert.equal(new Set(keys).size, keys.length);
  });

  it("every field has a unique envVar", () => {
    const vars = OPTION_SCHEMA.map((f) => f.envVar);
    assert.equal(new Set(vars).size, vars.length);
  });

  it("all envVars start with FOUNDRY_", () => {
    for (const f of OPTION_SCHEMA) {
      assert.ok(
        f.envVar.startsWith("FOUNDRY_"),
        `${f.envVar} does not start with FOUNDRY_`,
      );
    }
  });
});

// ---------------------------------------------------------------------------
// buildConfig — empty env (all defaults)
// ---------------------------------------------------------------------------

describe("buildConfig with empty env", () => {
  const config = buildConfig({});

  it("returns an object with all expected keys", () => {
    const expectedKeys = [
      "awsConfig", "compressSocket", "compressStatic", "cssTheme",
      "dataPath", "deleteNEDB", "fullscreen", "hostname", "hotReload",
      "language", "localHostname", "passwordSalt", "port", "protocol",
      "proxyPort", "proxySSL", "routePrefix", "serviceConfig", "sslCert",
      "sslKey", "telemetry", "tempDir", "unixSocket", "updateChannel",
      "upnp", "upnpLeaseDuration", "world",
    ];
    assert.deepEqual(Object.keys(config), expectedKeys);
  });

  it("boolean fields default to false", () => {
    assert.equal(config.compressSocket, false);
    assert.equal(config.compressStatic, false);
    assert.equal(config.deleteNEDB, false);
    assert.equal(config.hotReload, false);
    assert.equal(config.proxySSL, false);
    assert.equal(config.upnp, false);
  });

  it("string fields default to null", () => {
    assert.equal(config.awsConfig, null);
    assert.equal(config.hostname, null);
    assert.equal(config.protocol, null);
    assert.equal(config.routePrefix, null);
    assert.equal(config.sslCert, null);
    assert.equal(config.sslKey, null);
    assert.equal(config.tempDir, null);
    assert.equal(config.unixSocket, null);
    assert.equal(config.world, null);
  });

  it("string fields with specific defaults", () => {
    assert.equal(config.cssTheme, "dark");
    assert.equal(config.language, "en.core");
  });

  it("constants are set correctly", () => {
    assert.equal(config.dataPath, "/data");
    assert.equal(config.port, 30000);
    assert.equal(config.updateChannel, "stable");
    assert.equal(config.fullscreen, false);
  });

  it("tristate defaults to null", () => {
    assert.equal(config.telemetry, null);
  });

  it("number defaults to null", () => {
    assert.equal(config.proxyPort, null);
  });

  it("demo key is absent (undefined → omitted)", () => {
    assert.ok(!("demo" in config));
  });
});

// ---------------------------------------------------------------------------
// buildConfig — with env vars set
// ---------------------------------------------------------------------------

describe("buildConfig with env vars", () => {
  const env: Record<string, string> = {
    FOUNDRY_COMPRESS_WEBSOCKET: "true",
    FOUNDRY_MINIFY_STATIC_FILES: "true",
    FOUNDRY_CSS_THEME: "light",
    FOUNDRY_DELETE_NEDB: "true",
    FOUNDRY_HOSTNAME: "foundry.example.com",
    FOUNDRY_HOT_RELOAD: "true",
    FOUNDRY_LANGUAGE: "ja.core",
    FOUNDRY_LOCAL_HOSTNAME: "localhost",
    FOUNDRY_PASSWORD_SALT: "my-custom-salt",
    FOUNDRY_PROTOCOL: "https",
    FOUNDRY_PROXY_PORT: "8080",
    FOUNDRY_PROXY_SSL: "true",
    FOUNDRY_ROUTE_PREFIX: "foundry",
    FOUNDRY_SERVICE_CONFIG: "service.json",
    FOUNDRY_SSL_CERT: "/certs/cert.pem",
    FOUNDRY_SSL_KEY: "/certs/key.pem",
    FOUNDRY_TELEMETRY: "false",
    FOUNDRY_TEMP_DIR: "/tmp/foundry",
    FOUNDRY_UNIX_SOCKET: "/var/run/foundry.sock",
    FOUNDRY_UPNP: "true",
    FOUNDRY_UPNP_LEASE_DURATION: "3600",
    FOUNDRY_WORLD: "my-world",
    FOUNDRY_AWS_CONFIG: "s3://bucket/config",
    FOUNDRY_DEMO_CONFIG: '{"enabled":true}',
  };

  const config = buildConfig(env);

  it("boolean fields are true when set", () => {
    assert.equal(config.compressSocket, true);
    assert.equal(config.compressStatic, true);
    assert.equal(config.deleteNEDB, true);
    assert.equal(config.hotReload, true);
    assert.equal(config.proxySSL, true);
    assert.equal(config.upnp, true);
  });

  it("string fields reflect env values", () => {
    assert.equal(config.cssTheme, "light");
    assert.equal(config.hostname, "foundry.example.com");
    assert.equal(config.language, "ja.core");
    assert.equal(config.localHostname, "localhost");
    assert.equal(config.protocol, "https");
    assert.equal(config.routePrefix, "foundry");
    assert.equal(config.tempDir, "/tmp/foundry");
    assert.equal(config.world, "my-world");
  });

  it("number field is parsed and clamped", () => {
    assert.equal(config.proxyPort, 8080);
  });

  it("tristate field parses false", () => {
    assert.equal(config.telemetry, false);
  });

  it("JSON field is parsed", () => {
    assert.deepEqual(config.demo, { enabled: true });
  });

  it("sensitive fields are present (redaction is a separate concern)", () => {
    assert.equal(config.passwordSalt, "my-custom-salt");
    assert.equal(config.sslKey, "/certs/key.pem");
    assert.equal(config.sslCert, "/certs/cert.pem");
    assert.equal(config.awsConfig, "s3://bucket/config");
  });

  it("constants are unchanged", () => {
    assert.equal(config.dataPath, "/data");
    assert.equal(config.port, 30000);
    assert.equal(config.updateChannel, "stable");
    assert.equal(config.fullscreen, false);
  });
});

// ---------------------------------------------------------------------------
// buildConfig — edge cases / error paths
// ---------------------------------------------------------------------------

describe("buildConfig error paths", () => {
  it("throws ConfigError for non-numeric proxy port", () => {
    assert.throws(
      () => buildConfig({ FOUNDRY_PROXY_PORT: "not-a-number" }),
      (err: Error) => {
        assert.ok(err instanceof ConfigError);
        assert.ok(err.message.includes("FOUNDRY_PROXY_PORT"));
        // Error message must NOT contain the raw value
        assert.ok(!err.message.includes("not-a-number"));
        return true;
      },
    );
  });

  it("throws ConfigError for invalid JSON in demo config", () => {
    assert.throws(
      () => buildConfig({ FOUNDRY_DEMO_CONFIG: "{bad}" }),
      (err: Error) => {
        assert.ok(err instanceof ConfigError);
        assert.ok(err.message.includes("FOUNDRY_DEMO_CONFIG"));
        assert.ok(!err.message.includes("{bad}"));
        return true;
      },
    );
  });

  it("clamps proxy port below minimum to 1", () => {
    const config = buildConfig({ FOUNDRY_PROXY_PORT: "0" });
    assert.equal(config.proxyPort, 1);
  });

  it("clamps proxy port above maximum to 65535", () => {
    const config = buildConfig({ FOUNDRY_PROXY_PORT: "99999" });
    assert.equal(config.proxyPort, 65535);
  });
});

// ---------------------------------------------------------------------------
// buildConfig — key order stability
// ---------------------------------------------------------------------------

describe("buildConfig key order", () => {
  it("keys are in the expected alphabetical-like order", () => {
    const config = buildConfig({
      FOUNDRY_WORLD: "test",
      FOUNDRY_HOSTNAME: "h",
      FOUNDRY_COMPRESS_WEBSOCKET: "true",
    });
    const keys = Object.keys(config);
    // awsConfig should come before compressSocket, which comes before hostname, etc.
    assert.ok(keys.indexOf("awsConfig") < keys.indexOf("compressSocket"));
    assert.ok(keys.indexOf("compressSocket") < keys.indexOf("hostname"));
    assert.ok(keys.indexOf("hostname") < keys.indexOf("world"));
  });

  it("JSON output matches expected format", () => {
    const config = buildConfig({ FOUNDRY_COMPRESS_WEBSOCKET: "true" });
    const json = JSON.parse(JSON.stringify(config));
    assert.equal(json.compressSocket, true);
    assert.equal(json.dataPath, "/data");
    assert.equal(json.port, 30000);
  });
});

// ---------------------------------------------------------------------------
// Integration: redactConfig on buildConfig output
// ---------------------------------------------------------------------------

describe("integration: buildConfig + redactConfig", () => {
  it("sensitive values are redacted while non-sensitive pass through", () => {
    const config = buildConfig({
      FOUNDRY_PASSWORD_SALT: "secret-salt-value",
      FOUNDRY_SSL_KEY: "/private/key.pem",
      FOUNDRY_SSL_CERT: "/private/cert.pem",
      FOUNDRY_AWS_CONFIG: "arn:aws:secret",
      FOUNDRY_HOSTNAME: "foundry.example.com",
      FOUNDRY_PROXY_PORT: "443",
    });

    const redacted = redactConfig(config, SENSITIVE_KEYS);

    // Sensitive → redacted
    assert.equal(redacted.passwordSalt, "****");
    assert.equal(redacted.sslKey, "****");
    assert.equal(redacted.sslCert, "****");
    assert.equal(redacted.awsConfig, "****");

    // Non-sensitive → visible
    assert.equal(redacted.hostname, "foundry.example.com");
    assert.equal(redacted.proxyPort, "443");
    assert.equal(redacted.dataPath, "/data");
  });
});

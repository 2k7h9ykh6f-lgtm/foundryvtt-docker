/**
 * config_schema.ts - Declarative configuration schema for FoundryVTT options.
 *
 * Centralizes environment variable → config value conversion, validation,
 * and sensitive-field redaction.  Used by set_options.ts and set_password.ts.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Supported config value conversion strategies. */
export type ConfigType = "string" | "boolean" | "tristate" | "number" | "json";

/** A single configuration field definition. */
export interface ConfigField {
  /** Environment variable name, e.g. "FOUNDRY_COMPRESS_WEBSOCKET". */
  envVar: string;
  /** Output key in the generated JSON, e.g. "compressSocket". */
  outputKey: string;
  /** Conversion strategy to apply. */
  type: ConfigType;
  /** Value returned when the env var is unset or empty. */
  default?: unknown;
  /** Minimum allowed value (type "number" only). */
  min?: number;
  /** Maximum allowed value (type "number" only). */
  max?: number;
  /** If true, the value is redacted in log/debug output. */
  sensitive?: boolean;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/**
 * Thrown when an environment variable value cannot be converted.
 *
 * The error message intentionally omits the raw value to avoid leaking
 * sensitive data into logs; only the env var name is included.
 */
export class ConfigError extends Error {
  public readonly envVar: string;
  public readonly reason: string;

  constructor(envVar: string, reason: string) {
    super(`Configuration error: ${envVar} ${reason}`);
    this.name = "ConfigError";
    this.envVar = envVar;
    this.reason = reason;
  }
}

// ---------------------------------------------------------------------------
// Conversion functions
// ---------------------------------------------------------------------------

/**
 * Parse a string value.  Returns `fallback` when the env var is unset/empty.
 */
export function parseString(
  val: string | undefined,
  fallback: string | null = null,
): string | null {
  return val || fallback;
}

/**
 * Parse a boolean value.  Only the exact string `"true"` yields `true`;
 * everything else (including unset) yields `false`.
 */
export function parseBoolean(val: string | undefined): boolean {
  return val === "true";
}

/**
 * Parse a tri-state boolean.
 *
 * - `"true"`  → `true`
 * - `"false"` → `false`
 * - anything else / unset → `null`
 */
export function parseTristate(val: string | undefined): boolean | null {
  if (val === "true") return true;
  if (val === "false") return false;
  return null;
}

/**
 * Parse an integer and clamp it to `[min, max]`.
 *
 * Returns `fallback` when the env var is unset/empty.
 * Throws {@link ConfigError} when the value is not a valid integer (NaN).
 */
export function parseClampedNumber(
  val: string | undefined,
  min: number,
  max: number,
  fallback: number | null = null,
): number | null {
  if (!val) return fallback;

  const n = parseInt(val, 10);
  if (Number.isNaN(n)) {
    throw new ConfigError(
      "unknown",
      `value is not a valid integer`,
    );
  }
  return Math.min(Math.max(n, min), max);
}

/**
 * Parse a JSON string.
 *
 * Returns `undefined` when the env var is unset/empty (so the key is omitted
 * from the output object, matching the original behaviour).
 * Throws {@link ConfigError} on invalid JSON.
 */
export function parseJSON(val: string | undefined): unknown {
  if (!val) return undefined;
  try {
    return JSON.parse(val);
  } catch {
    throw new ConfigError("unknown", "value is not valid JSON");
  }
}

// ---------------------------------------------------------------------------
// Redaction
// ---------------------------------------------------------------------------

/**
 * Return a display-safe representation of a config value.
 *
 * Sensitive fields (identified by membership in `sensitiveKeys`) are replaced
 * with `"****"`.
 */
export function redactValue(
  key: string,
  value: unknown,
  sensitiveKeys: ReadonlySet<string>,
): string {
  if (sensitiveKeys.has(key)) return "****";
  if (value === null || value === undefined) return String(value);
  return String(value);
}

/**
 * Build a redacted, human-readable summary of a config object.
 * Useful for debug logging without leaking secrets.
 */
export function redactConfig(
  config: Record<string, unknown>,
  sensitiveKeys: ReadonlySet<string>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(config)) {
    out[k] = redactValue(k, v, sensitiveKeys);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const MINIMUM_PORT = 1;
const MAXIMUM_PORT = 65535;

/** Declarative schema for every option written to options.json. */
export const OPTION_SCHEMA: ConfigField[] = [
  { envVar: "FOUNDRY_AWS_CONFIG", outputKey: "awsConfig", type: "string", default: null, sensitive: true },
  { envVar: "FOUNDRY_COMPRESS_WEBSOCKET", outputKey: "compressSocket", type: "boolean", default: false },
  { envVar: "FOUNDRY_MINIFY_STATIC_FILES", outputKey: "compressStatic", type: "boolean", default: false },
  { envVar: "FOUNDRY_CSS_THEME", outputKey: "cssTheme", type: "string", default: "dark" },
  // dataPath, port, updateChannel, fullscreen are constants — handled in buildConfig
  { envVar: "FOUNDRY_DELETE_NEDB", outputKey: "deleteNEDB", type: "boolean", default: false },
  { envVar: "FOUNDRY_DEMO_CONFIG", outputKey: "demo", type: "json" },
  { envVar: "FOUNDRY_HOSTNAME", outputKey: "hostname", type: "string", default: null },
  { envVar: "FOUNDRY_HOT_RELOAD", outputKey: "hotReload", type: "boolean", default: false },
  { envVar: "FOUNDRY_LANGUAGE", outputKey: "language", type: "string", default: "en.core" },
  { envVar: "FOUNDRY_LOCAL_HOSTNAME", outputKey: "localHostname", type: "string", default: null },
  { envVar: "FOUNDRY_PASSWORD_SALT", outputKey: "passwordSalt", type: "string", default: null, sensitive: true },
  { envVar: "FOUNDRY_PROTOCOL", outputKey: "protocol", type: "string", default: null },
  { envVar: "FOUNDRY_PROXY_PORT", outputKey: "proxyPort", type: "number", min: MINIMUM_PORT, max: MAXIMUM_PORT, default: null },
  { envVar: "FOUNDRY_PROXY_SSL", outputKey: "proxySSL", type: "boolean", default: false },
  { envVar: "FOUNDRY_ROUTE_PREFIX", outputKey: "routePrefix", type: "string", default: null },
  { envVar: "FOUNDRY_SERVICE_CONFIG", outputKey: "serviceConfig", type: "string", default: null },
  { envVar: "FOUNDRY_SSL_CERT", outputKey: "sslCert", type: "string", default: null, sensitive: true },
  { envVar: "FOUNDRY_SSL_KEY", outputKey: "sslKey", type: "string", default: null, sensitive: true },
  { envVar: "FOUNDRY_TELEMETRY", outputKey: "telemetry", type: "tristate", default: null },
  { envVar: "FOUNDRY_TEMP_DIR", outputKey: "tempDir", type: "string", default: null },
  { envVar: "FOUNDRY_UNIX_SOCKET", outputKey: "unixSocket", type: "string", default: null },
  { envVar: "FOUNDRY_UPNP", outputKey: "upnp", type: "boolean", default: false },
  { envVar: "FOUNDRY_UPNP_LEASE_DURATION", outputKey: "upnpLeaseDuration", type: "string", default: null },
  { envVar: "FOUNDRY_WORLD", outputKey: "world", type: "string", default: null },
];

/** Hardcoded constants that always appear in options.json. */
const CONSTANTS: Record<string, unknown> = {
  dataPath: "/data",
  port: 30000,
  updateChannel: "stable",
  fullscreen: false,
};

/** Insertion order matters for JSON output readability.  This array defines it. */
const KEY_ORDER: string[] = [
  "awsConfig",
  "compressSocket",
  "compressStatic",
  "cssTheme",
  "dataPath",
  "deleteNEDB",
  "demo",
  "fullscreen",
  "hostname",
  "hotReload",
  "language",
  "localHostname",
  "passwordSalt",
  "port",
  "protocol",
  "proxyPort",
  "proxySSL",
  "routePrefix",
  "serviceConfig",
  "sslCert",
  "sslKey",
  "telemetry",
  "tempDir",
  "unixSocket",
  "updateChannel",
  "upnp",
  "upnpLeaseDuration",
  "world",
];

/** Set of output keys marked as sensitive — used by redaction helpers. */
export const SENSITIVE_KEYS: ReadonlySet<string> = new Set(
  OPTION_SCHEMA.filter((f) => f.sensitive).map((f) => f.outputKey),
);

/** The password-salt field definition, shared with set_password.ts. */
export const PASSWORD_SALT_FIELD: ConfigField = OPTION_SCHEMA.find(
  (f) => f.outputKey === "passwordSalt",
)!;

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

/**
 * Convert a single raw env string according to a {@link ConfigField}.
 *
 * @internal
 */
function convertField(
  field: ConfigField,
  raw: string | undefined,
): unknown {
  switch (field.type) {
    case "string":
      return parseString(raw, (field.default as string | null) ?? null);

    case "boolean":
      return parseBoolean(raw);

    case "tristate":
      return parseTristate(raw);

    case "number": {
      try {
        return parseClampedNumber(
          raw,
          field.min!,
          field.max!,
          (field.default as number | null) ?? null,
        );
      } catch (e) {
        if (e instanceof ConfigError) {
          // Re-throw with the correct env var name
          throw new ConfigError(field.envVar, e.reason);
        }
        throw e;
      }
    }

    case "json": {
      try {
        return parseJSON(raw);
      } catch (e) {
        if (e instanceof ConfigError) {
          throw new ConfigError(field.envVar, e.reason);
        }
        throw e;
      }
    }
  }
}

/**
 * Build the complete options object from environment variables.
 *
 * The returned object's key order matches the legacy `set_options.ts` output
 * so that `/data/Config/options.json` is byte-identical for the same inputs.
 *
 * @param env - Typically `process.env`.
 * @param schema - The field definitions to process.
 * @returns An ordered plain object ready for `JSON.stringify`.
 */
export function buildConfig(
  env: NodeJS.ProcessEnv | Record<string, string | undefined>,
  schema: ConfigField[] = OPTION_SCHEMA,
): Record<string, unknown> {
  const raw: Record<string, unknown> = {};

  for (const field of schema) {
    const value = convertField(field, env[field.envVar]);
    // Skip undefined values (e.g. unset JSON fields) so the key is omitted
    if (value !== undefined) {
      raw[field.outputKey] = value;
    }
  }

  // Merge constants
  Object.assign(raw, CONSTANTS);

  // Return an ordered object
  const ordered: Record<string, unknown> = {};
  for (const key of KEY_ORDER) {
    if (key in raw) {
      ordered[key] = raw[key];
    }
  }

  return ordered;
}

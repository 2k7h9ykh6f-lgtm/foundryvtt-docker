import createLogger from "./logging.js";

// ---------------------------------------------------------------------------
// Sensitive-key registry
// ---------------------------------------------------------------------------

export const SENSITIVE_KEYS: Set<string> = new Set([
  "passwordSalt",
  "awsConfig",
  "serviceConfig",
]);

export function maskValue(key: string, value: unknown): string {
  if (SENSITIVE_KEYS.has(key) && value != null && value !== "") {
    return "***";
  }
  return String(value);
}

// ---------------------------------------------------------------------------
// Value parsers — pure functions, throw on invalid input
// ---------------------------------------------------------------------------

export function parseBool(
  val: string | undefined,
  defaultVal: boolean,
): boolean {
  if (val === undefined || val === "") return defaultVal;
  if (val === "true") return true;
  if (val === "false") return false;
  throw new Error(
    `Invalid boolean value: "${val}" (expected "true" or "false")`,
  );
}

export function parseTriBool(val: string | undefined): boolean | null {
  if (val === undefined || val === "") return null;
  if (val === "true") return true;
  if (val === "false") return false;
  throw new Error(
    `Invalid tri-boolean value: "${val}" (expected "true", "false", or unset)`,
  );
}

export function parseString(
  val: string | undefined,
  defaultVal: string | null = null,
): string | null {
  if (val === undefined || val === "") return defaultVal;
  return val;
}

export function parseClampedInt(
  val: string | undefined,
  min: number,
  max: number,
  defaultVal: number | null = null,
): number | null {
  if (val === undefined || val === "") return defaultVal;
  const n = parseInt(val, 10);
  if (isNaN(n)) {
    throw new Error(`Invalid integer value: "${val}"`);
  }
  return Math.min(Math.max(n, min), max);
}

export function parseJson(val: string | undefined): unknown | undefined {
  if (val === undefined || val === "") return undefined;
  try {
    return JSON.parse(val);
  } catch {
    throw new Error(`Invalid JSON value: "${val}"`);
  }
}

export function parsePath(val: string | undefined): string | null {
  if (val === undefined || val === "") return null;
  if (!val.startsWith("/")) {
    throw new Error(
      `Invalid path: "${val}" (must be an absolute path starting with "/")`,
    );
  }
  return val;
}

// ---------------------------------------------------------------------------
// Schema-driven config builder
// ---------------------------------------------------------------------------

type ConfigType =
  | "boolean"
  | "triboolean"
  | "string"
  | "clampedInt"
  | "json"
  | "path";

export interface ConfigRule {
  envVar: string;
  configKey: string;
  type: ConfigType;
  default?: boolean | string | number | null;
  sensitive?: boolean;
  min?: number;
  max?: number;
}

function applyRule(
  rule: ConfigRule,
  env: Record<string, string | undefined>,
): unknown {
  const val = env[rule.envVar];
  switch (rule.type) {
    case "boolean":
      return parseBool(val, (rule.default ?? false) as boolean);
    case "triboolean":
      return parseTriBool(val);
    case "string":
      return parseString(val, (rule.default ?? null) as string | null);
    case "clampedInt":
      return parseClampedInt(
        val,
        rule.min ?? 0,
        rule.max ?? Number.MAX_SAFE_INTEGER,
        (rule.default ?? null) as number | null,
      );
    case "json":
      return parseJson(val);
    case "path":
      return parsePath(val);
  }
}

export function buildConfig(
  rules: ConfigRule[],
  env: Record<string, string | undefined>,
  logLevel: string = "warn",
): Record<string, unknown> {
  const logger = createLogger("Options", logLevel);
  const config: Record<string, unknown> = {};

  for (const rule of rules) {
    const value = applyRule(rule, env);
    config[rule.configKey] = value;

    const display = rule.sensitive
      ? maskValue(rule.configKey, value)
      : String(value);
    logger.debug(`${rule.envVar} -> ${rule.configKey} = ${display}`);
  }

  return config;
}

import { describe, it, expect } from "vitest";
import {
  parseBool,
  parseTriBool,
  parseString,
  parseClampedInt,
  parseJson,
  parsePath,
  maskValue,
  SENSITIVE_KEYS,
} from "../config_utils.js";

// ---------------------------------------------------------------------------
// parseBool
// ---------------------------------------------------------------------------
describe("parseBool", () => {
  it("parses 'true' as true", () => {
    expect(parseBool("true", false)).toBe(true);
  });

  it("parses 'false' as false", () => {
    expect(parseBool("false", true)).toBe(false);
  });

  it("returns default for undefined", () => {
    expect(parseBool(undefined, true)).toBe(true);
    expect(parseBool(undefined, false)).toBe(false);
  });

  it("returns default for empty string", () => {
    expect(parseBool("", true)).toBe(true);
    expect(parseBool("", false)).toBe(false);
  });

  it("throws on invalid value", () => {
    expect(() => parseBool("yes", false)).toThrow(/Invalid boolean/);
    expect(() => parseBool("1", false)).toThrow(/Invalid boolean/);
    expect(() => parseBool("TRUE", false)).toThrow(/Invalid boolean/);
  });
});

// ---------------------------------------------------------------------------
// parseTriBool
// ---------------------------------------------------------------------------
describe("parseTriBool", () => {
  it("parses 'true' as true", () => {
    expect(parseTriBool("true")).toBe(true);
  });

  it("parses 'false' as false", () => {
    expect(parseTriBool("false")).toBe(false);
  });

  it("returns null for undefined", () => {
    expect(parseTriBool(undefined)).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(parseTriBool("")).toBeNull();
  });

  it("throws on invalid value", () => {
    expect(() => parseTriBool("1")).toThrow(/Invalid tri-boolean/);
    expect(() => parseTriBool("yes")).toThrow(/Invalid tri-boolean/);
  });
});

// ---------------------------------------------------------------------------
// parseString
// ---------------------------------------------------------------------------
describe("parseString", () => {
  it("returns value when set", () => {
    expect(parseString("hello")).toBe("hello");
  });

  it("returns null for undefined", () => {
    expect(parseString(undefined)).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(parseString("")).toBeNull();
  });

  it("returns custom default when provided", () => {
    expect(parseString(undefined, "fallback")).toBe("fallback");
    expect(parseString("", "fallback")).toBe("fallback");
  });

  it("ignores default when value is set", () => {
    expect(parseString("actual", "fallback")).toBe("actual");
  });
});

// ---------------------------------------------------------------------------
// parseClampedInt
// ---------------------------------------------------------------------------
describe("parseClampedInt", () => {
  it("parses in-range value", () => {
    expect(parseClampedInt("80", 1, 65535)).toBe(80);
  });

  it("clamps below minimum", () => {
    expect(parseClampedInt("-5", 1, 65535)).toBe(1);
  });

  it("clamps above maximum", () => {
    expect(parseClampedInt("99999", 1, 65535)).toBe(65535);
  });

  it("returns default for undefined", () => {
    expect(parseClampedInt(undefined, 1, 65535, 8080)).toBe(8080);
    expect(parseClampedInt(undefined, 1, 65535)).toBeNull();
  });

  it("returns default for empty string", () => {
    expect(parseClampedInt("", 1, 65535, 3000)).toBe(3000);
  });

  it("throws on non-numeric value", () => {
    expect(() => parseClampedInt("abc", 1, 65535)).toThrow(/Invalid integer/);
  });
});

// ---------------------------------------------------------------------------
// parseJson
// ---------------------------------------------------------------------------
describe("parseJson", () => {
  it("parses valid JSON", () => {
    expect(parseJson('{"key":"val"}')).toEqual({ key: "val" });
  });

  it("parses JSON array", () => {
    expect(parseJson("[1,2,3]")).toEqual([1, 2, 3]);
  });

  it("returns undefined for undefined input", () => {
    expect(parseJson(undefined)).toBeUndefined();
  });

  it("returns undefined for empty string", () => {
    expect(parseJson("")).toBeUndefined();
  });

  it("throws on invalid JSON", () => {
    expect(() => parseJson("{bad}")).toThrow(/Invalid JSON/);
  });
});

// ---------------------------------------------------------------------------
// parsePath
// ---------------------------------------------------------------------------
describe("parsePath", () => {
  it("accepts absolute path", () => {
    expect(parsePath("/data/ssl/cert.pem")).toBe("/data/ssl/cert.pem");
  });

  it("returns null for undefined", () => {
    expect(parsePath(undefined)).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(parsePath("")).toBeNull();
  });

  it("throws on relative path", () => {
    expect(() => parsePath("relative/path")).toThrow(/must be an absolute path/);
  });

  it("throws on bare filename", () => {
    expect(() => parsePath("cert.pem")).toThrow(/must be an absolute path/);
  });
});

// ---------------------------------------------------------------------------
// maskValue — sensitive value masking
// ---------------------------------------------------------------------------
describe("maskValue", () => {
  it("masks sensitive keys", () => {
    for (const key of SENSITIVE_KEYS) {
      expect(maskValue(key, "secret-data")).toBe("***");
    }
  });

  it("does not mask non-sensitive keys", () => {
    expect(maskValue("hostname", "example.com")).toBe("example.com");
    expect(maskValue("port", 30000)).toBe("30000");
  });

  it("shows null/empty for sensitive keys without values", () => {
    expect(maskValue("passwordSalt", null)).toBe("null");
    expect(maskValue("passwordSalt", "")).toBe("");
  });

  it("converts non-string values to string", () => {
    expect(maskValue("upnp", true)).toBe("true");
    expect(maskValue("proxyPort", 443)).toBe("443");
  });
});

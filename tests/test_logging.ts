/**
 * Tests for src/logging.ts unified log-level handling.
 * Run: npx tsx tests/test_logging.ts
 */

import { Writable } from "stream";
import createLogger from "../src/logging.js";

let pass = 0;
let fail = 0;

function assert(label: string, condition: boolean): void {
    if (condition) {
        pass++;
    } else {
        console.error(`FAIL [${label}]`);
        fail++;
    }
}

/**
 * Capture all stderr output from a winston logger by temporarily replacing
 * process.stderr.write.
 */
function captureStderr(fn: () => void): string {
    let captured = "";
    const originalWrite = process.stderr.write;
    process.stderr.write = ((
        chunk: string | Uint8Array,
        ...args: any[]
    ): boolean => {
        captured += typeof chunk === "string" ? chunk : chunk.toString();
        return true;
    }) as typeof process.stderr.write;
    try {
        fn();
    } finally {
        process.stderr.write = originalWrite;
    }
    return captured;
}

// ── Test 1: Default level is info (no env var) ─────────────────────────────
{
    delete process.env.CONTAINER_LOG_LEVEL;
    const logger = createLogger("T1", "info");
    const output = captureStderr(() => {
        logger.debug("d");
        logger.info("i");
        logger.warn("w");
        logger.error("e");
    });
    assert("default: no debug", !output.includes("d"));
    assert("default: has info", output.includes("i"));
    assert("default: has warn", output.includes("w"));
    assert("default: has error", output.includes("e"));
}

// ── Test 2: CONTAINER_LOG_LEVEL=debug enables debug ────────────────────────
{
    process.env.CONTAINER_LOG_LEVEL = "debug";
    const logger = createLogger("T2", "info");
    const output = captureStderr(() => {
        logger.debug("d");
        logger.info("i");
    });
    assert("env debug: has debug", output.includes("d"));
    assert("env debug: has info", output.includes("i"));
    delete process.env.CONTAINER_LOG_LEVEL;
}

// ── Test 3: CONTAINER_LOG_LEVEL=quiet suppresses all ───────────────────────
{
    process.env.CONTAINER_LOG_LEVEL = "quiet";
    const logger = createLogger("T3", "info");
    const output = captureStderr(() => {
        logger.debug("d");
        logger.info("i");
        logger.warn("w");
        logger.error("e");
    });
    assert("quiet: empty output", output === "");
    delete process.env.CONTAINER_LOG_LEVEL;
}

// ── Test 4: Explicit --log-level overrides env var ─────────────────────────
{
    process.env.CONTAINER_LOG_LEVEL = "debug";
    // Passing "warn" (not default "info") should override the env var
    const logger = createLogger("T4", "warn");
    const output = captureStderr(() => {
        logger.debug("d");
        logger.info("i");
        logger.warn("w");
        logger.error("e");
    });
    assert("override: no debug", !output.includes("d"));
    assert("override: no info", !output.includes("[info]") && !output.includes("| i\n"));
    assert("override: has warn", output.includes("w"));
    assert("override: has error", output.includes("e"));
    delete process.env.CONTAINER_LOG_LEVEL;
}

// ── Test 5: CONTAINER_LOG_LEVEL=error shows only errors ────────────────────
{
    process.env.CONTAINER_LOG_LEVEL = "error";
    const logger = createLogger("T5", "info");
    const output = captureStderr(() => {
        logger.info("i");
        logger.warn("w");
        logger.error("e");
    });
    assert("error level: no info", !output.includes("i"));
    assert("error level: no warn", !output.includes("w"));
    assert("error level: has error", output.includes("e"));
    delete process.env.CONTAINER_LOG_LEVEL;
}

// ── Test 6: Output format includes logger name and timestamp ───────────────
{
    delete process.env.CONTAINER_LOG_LEVEL;
    const logger = createLogger("MyLogger", "info");
    const output = captureStderr(() => {
        logger.info("hello");
    });
    assert("format: has name", output.includes("MyLogger |"));
    assert("format: has timestamp", /\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(output));
    assert("format: has message", output.includes("hello"));
}

// ── Summary ──────────────────────────────────────────────────────────────────
console.log(`\nResults: ${pass} passed, ${fail} failed`);
if (fail > 0) {
    process.exit(1);
}
console.log("All tests passed.");

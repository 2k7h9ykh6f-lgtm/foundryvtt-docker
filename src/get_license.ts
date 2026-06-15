#!/usr/bin/env node

const doc = `
Retrieve a Foundry Virtual Tabletop license key from a user's account using
cookies from authenticate.js.

The utility will print a license key to standard out.

EXIT STATUS
    This utility exits with one of the following values:
    0   Completed successfully.
    1   Retriable error (transient network failure, HTTP 5xx, empty response).
        The caller should retry after a backoff period.
    2   Non-retriable authentication error (HTTP 4xx, invalid or missing
        cookies).  The caller should NOT retry — credentials must be fixed.
    3   Non-retriable configuration error (no license keys associated with
        the account).  The caller should NOT retry — account must be fixed.

Usage:
  get_license.js [options] <cookiejar>
  get_license.js (-h | --help)

Options:
  -h --help              Show this message.
  --log-level=LEVEL      If specified, then the log level will be set to
                         the specified value.  Valid values are "debug", "info",
                         "warn", and "error". [default: info]
  --select=INDEX         If more than one license key is associated with an
                         account return the one specified by index.  In
                         unspecified, a random license will be returned.  Index
                         starts at 1.
  --user-agent=USERAGENT If specified, then the user-agent header will be set to
                         the specified value. [default: node-fetch]

`;

// Imports
import { CookieJar } from "tough-cookie";
import { ProxyAgent } from "proxy-agent";
import * as cheerio from "cheerio";
import createLogger from "./logging.js";
import docopt from "docopt";
import fetchCookie from "fetch-cookie";
import FileCookieStore from "tough-cookie-file-store";
import nodeFetch, { Headers } from "node-fetch";
import process from "process";
import winston from "winston";

// Setup globals, to be configured in main()
var cookieJar: CookieJar;
var fetch: typeof nodeFetch;
var logger: winston.Logger;

// Constants
const AGENT = new ProxyAgent();
const BASE_URL: string = "https://foundryvtt.com";
const LOCAL_DOMAIN: string = "felddy.com";

// Exit codes — keep in sync with backoff.sh and entrypoint.sh.
// 0 = success
// 1 = retriable (network/5xx) — backoff will retry
// 2 = fatal auth (bad cookies, 4xx) — backoff sleeps indefinitely
// 3 = fatal config (no keys on account) — backoff sleeps indefinitely
const EXIT_SUCCESS = 0;
const EXIT_RETRY = 1;
const EXIT_FATAL_AUTH = 2;
const EXIT_FATAL_CONFIG = 3;

const HEADERS: Headers = new Headers({
    DNT: "1",
    Referer: BASE_URL,
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "node-fetch",
});

/**
 * fetchLicense - Fetch a license key for a user.
 *
 * @param  {string} username Username (not e-mail address) of license owner.
 * @return {string[]}        License keys formatted without dashes.
 * @throws {Error}           On HTTP errors; error.message includes status info
 *                           so callers can classify retriable vs. fatal.
 */
async function fetchLicenses(username: string): Promise<string[]> {
    logger.info("Fetching licenses.");
    const LICENSE_URL = `${BASE_URL}/community/${username}/licenses`;
    logger.debug(`Fetching: ${LICENSE_URL}`);
    const response = await fetch(LICENSE_URL, {
        agent: AGENT,
        headers: HEADERS,
        method: "GET",
    });
    if (!response.ok) {
        // Embed the HTTP status so the caller can distinguish 4xx vs 5xx.
        throw new Error(
            `HTTP ${response.status} ${response.statusText}`,
        );
    }
    const body = await response.text();
    const $ = cheerio.load(body);

    const licenses: string[] = $("div.license label.copy input")
        .map((_, el) => {
            const value = $(el).attr("value");
            return value ? value.replace(/-/g, "") : undefined; // remove dashes
        })
        .get()
        .filter(Boolean);
    return licenses;
}

/**
 * main - Parse command line args, setup logging, do work.
 *
 * @return {number}  exit code
 */
async function main(): Promise<number> {
    // Parse command line options.
    const options = docopt.docopt(doc, { version: "1.0.0" });

    // Extract values from CLI options.
    const cookiejar_filename: string = options["<cookiejar>"];
    const log_level: string = options["--log-level"].toLowerCase();
    const select_mode: string = options["--select"];
    HEADERS.set("User-Agent", options["--user-agent"]);

    // Setup logging.
    logger = createLogger("License", log_level);

    // Setup global cookie jar, storage, and fetch library
    logger.debug(`Reading cookies from: ${cookiejar_filename}`);
    cookieJar = new CookieJar(new FileCookieStore(cookiejar_filename));
    fetch = fetchCookie(nodeFetch, cookieJar);

    // Retrieve username from cookie.
    const local_cookies = cookieJar.getCookiesSync(`http://${LOCAL_DOMAIN}`);
    if (local_cookies.length != 1) {
        logger.error(
            `[FATAL_AUTH] Wrong number of cookies found for ${LOCAL_DOMAIN}.  Expected 1, found ${local_cookies.length}`,
        );
        return EXIT_FATAL_AUTH;
    }
    const loggedInUsername = local_cookies[0].value;

    // Attempt to fetch a license key.
    let license_keys: string[];
    try {
        license_keys = await fetchLicenses(loggedInUsername);
    } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        // Classify based on whether the error message starts with "HTTP 4xx".
        // 4xx = auth/permission problem (fatal); anything else = retriable.
        if (/^HTTP 4\d{2}/.test(message)) {
            logger.error(
                `[FATAL_AUTH] License fetch failed for ${loggedInUsername}: ${message}`,
            );
            return EXIT_FATAL_AUTH;
        }
        logger.error(
            `[RETRY] License fetch failed for ${loggedInUsername}: ${message}`,
        );
        return EXIT_RETRY;
    }
    const key_count = license_keys.length;

    // Handle no license keys found.
    if (key_count == 0) {
        logger.error(
            `[FATAL_CONFIG] Could not find any license keys associated with account ${loggedInUsername}`,
        );
        return EXIT_FATAL_CONFIG;
    } else {
        logger.info(
            `Found ${key_count} license ${
                key_count == 1 ? "key" : "keys"
            } associated with account ${loggedInUsername}`,
        );
    }

    // Handle a single license key found.
    if (key_count == 1) {
        logger.debug("Returning single license.");
        process.stdout.write(license_keys[0]);
        return EXIT_SUCCESS;
    }

    // Handle multiple licenses keys found.
    var select_index: number;

    // Use a 1-based index when communicating with the user.
    if (!parseInt(select_mode)) {
        // No numeric index specified, so select a random license key.
        select_index = Math.floor(Math.random() * key_count) + 1;
        logger.info(`License key #${select_index} randomly selected.`);
        process.stdout.write(license_keys[select_index - 1]);
        return EXIT_SUCCESS;
    } else {
        // mode is integer
        select_index = parseInt(select_mode);
        if (select_index > key_count) {
            logger.warn(
                `Invalid license key index ${select_index} selected by user.  Using ${key_count}.`,
            );
            select_index = key_count;
        }
        if (select_index < 1) {
            logger.warn(
                `Invalid license key index ${select_index} selected by user.  Using 1.`,
            );
            select_index = 1;
        }
        logger.info(`License key #${select_index} selected by user.`);
        process.stdout.write(license_keys[select_index - 1]);
        return EXIT_SUCCESS;
    }
}

(async () => {
    process.exitCode = await main();
})();

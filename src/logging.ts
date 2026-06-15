import winston from "winston";

/**
 * resolveLogLevel - Determine the effective log level.
 *
 * When the caller passes the default "info" level, the CONTAINER_LOG_LEVEL
 * environment variable is checked as an override.  An explicit CLI --log-level
 * value other than "info" always takes precedence.
 *
 * Valid levels: debug, info, warn, error, quiet
 */
function resolveLogLevel(log_level: string): string {
    if (log_level === "info" && process.env.CONTAINER_LOG_LEVEL) {
        return process.env.CONTAINER_LOG_LEVEL.toLowerCase();
    }
    return log_level;
}

/**
 * createLogger - Create a named logger with a level filter.
 *
 * @param  {string} name      Name of the logger shown in log.
 * @param  {string} log_level Filter level to apply to logging.  Valid levels
 *                            are: error, warn, info, debug, quiet
 * @return {winston.Logger}   The logger.
 */
export default function createLogger(
    name: string,
    log_level: string,
): winston.Logger {
    const effective_level = resolveLogLevel(log_level);

    // "quiet" suppresses all output — create a logger with no transports.
    if (effective_level === "quiet") {
        return winston.createLogger({
            silent: true,
        });
    }

    const logger = winston.createLogger({
        level: effective_level,
        format: winston.format.combine(
            winston.format.timestamp({ format: "YYYY-MM-DD HH:mm:ss" }),
            winston.format.errors({ stack: true }),
            winston.format.colorize(),
            winston.format.printf(
                ({ level, message, label, timestamp, stack }) => {
                    let line =
                        name +
                        " | " +
                        timestamp +
                        " | [" +
                        level +
                        "] " +
                        message;
                    if (stack) line += "\n" + stack;
                    return line;
                },
            ),
        ),
        transports: [
            new winston.transports.Console({
                stderrLevels: ["error", "warn", "info", "debug"],
            }),
        ],
    });
    return logger;
}

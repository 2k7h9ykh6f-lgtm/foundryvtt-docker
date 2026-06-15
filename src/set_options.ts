#!/usr/bin/env node

import { buildConfig } from "./config_schema.js";

const options = buildConfig(process.env);
process.stdout.write(JSON.stringify(options, null, "  "));

#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { spawn, spawnSync } = require("child_process");

const candidates = [
  process.env.SIGIL_PYTHON,
  "python3",
  "python",
  process.env.ProgramFiles && path.join(process.env.ProgramFiles, "Sigil", "python3.exe"),
  process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Programs", "Sigil", "python3.exe")
].filter(Boolean);

const python = candidates.find(candidate => {
  if (path.isAbsolute(candidate) && !fs.existsSync(candidate)) return false;
  return spawnSync(candidate, ["--version"], { stdio: "ignore" }).status === 0;
});

if (!python) {
  console.error("Python 3 não encontrado. Defina SIGIL_PYTHON com o caminho do executável.");
  process.exit(1);
}

const server = path.join(__dirname, "..", "mcp_server", "sigil_mcp.py");
const child = spawn(python, [server], { stdio: "inherit", env: process.env });
child.on("error", error => { console.error(error.message); process.exit(1); });
child.on("exit", (code, signal) => signal ? process.kill(process.pid, signal) : process.exit(code || 0));

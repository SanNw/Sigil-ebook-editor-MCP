#!/usr/bin/env python3
"""Build the two GitHub release archives with Python's standard library."""

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
VERSION = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
DIST = ROOT / "dist"
FILES = (
    ".gitignore", "CHANGELOG.md", "LICENSE", "README.md", "SECURITY.md",
    "SigilMCPExternal.cs", "SigilMCPExternal.exe", "build.ps1", "external_bridge.py",
    "package.json", "package_release.py", "test_bridge.py", "test_external_bridge.py",
    "bin/sigil-mcp.js", "mcp_server/sigil_mcp.py",
    "sigil_plugin/SigilMCPBridge/plugin.py", "sigil_plugin/SigilMCPBridge/plugin.xml",
)


def write_archive(path, entries, trim=""):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in entries:
            name = relative[len(trim):] if trim and relative.startswith(trim) else relative
            archive.write(ROOT / relative, name)


def main():
    DIST.mkdir(exist_ok=True)
    write_archive(DIST / f"Sigil-MCP-Bridge_v{VERSION}.zip", FILES)
    plugin = tuple(item for item in FILES if item.startswith("sigil_plugin/"))
    write_archive(DIST / f"SigilMCPBridge_v{VERSION}.zip", plugin, "sigil_plugin/")
    print(DIST)


if __name__ == "__main__":
    main()

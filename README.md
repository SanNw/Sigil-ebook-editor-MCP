# Sigil MCP Bridge

Connects Codex and other Model Context Protocol clients to the EPUB currently open in
[Sigil](https://sigil-ebook.com/).

The recommended external-editor mode runs in the background, keeps Sigil usable and
edits only existing textual resources. Reads return a SHA-256 hash; writes require that
hash and are rejected if the file changed in the meantime.

## Requirements

- Windows 10 or later for the background external-editor launcher
- Sigil 2.x
- Python 3.8 or later for the MCP server (Sigil already bundles Python)
- Node.js 18 or later only when installing the MCP server from npm

The modal `BookContainer` plugin is also included and supports the platforms supported
by Sigil, but it blocks the editor while its window is open.

## Install the non-modal Sigil bridge

1. Download `Sigil-MCP-Bridge_v0.2.0.zip` from the GitHub release and extract it to a
   permanent directory.
2. In Sigil, open **Preferences > General Settings > Preferred external XHTML editor**
   and select `SigilMCPExternal.exe`.
3. Open an EPUB and press **F2** once. The bridge starts invisibly on
   `http://127.0.0.1:8765`.

Opening the external editor in another EPUB replaces the previous bridge instance, so
only the most recently activated book is exposed. If Sigil uses a portable installation
and Python is not found automatically, set `SIGIL_PYTHON` to Sigil's `python3.exe`.

## Configure an MCP client

### npm

```toml
[mcp_servers.sigil]
command = "npx"
args = ["-y", "sigil-mcp-bridge"]

[mcp_servers.sigil.env]
SIGIL_BRIDGE_URL = "http://127.0.0.1:8765"
```

### Python directly

```toml
[mcp_servers.sigil]
command = "python3"
args = ["/absolute/path/to/sigil-mcp-bridge/mcp_server/sigil_mcp.py"]

[mcp_servers.sigil.env]
SIGIL_BRIDGE_URL = "http://127.0.0.1:8765"
```

For a Codex process running in WSL, use Sigil's Windows `python3.exe` as the command if
WSL cannot reach the Windows loopback address.

## Tools

- `sigil_health`
- `sigil_book_info`
- `sigil_list_files`
- `sigil_selected_files`
- `sigil_read_file`
- `sigil_search`
- `sigil_write_file`

The external mode does not add or remove manifest entries. Use the modal
`SigilMCPBridge` plugin for future structural operations. Avoid editing the same XHTML
simultaneously in the agent and Sigil's Code View.

## Optional local token

The service binds only to `127.0.0.1` and rejects browser-originated requests. To also
require a bearer token, set the same `SIGIL_BRIDGE_TOKEN` value in the environment that
launches Sigil and in the MCP server configuration.

## Modal plugin

Install `SigilMCPBridge_v0.2.0.zip` through **Plugins > Manage Plugins**. This mode uses
Sigil's `BookContainer` API and intentionally keeps a plugin window open while active.

## Build and test

Compile the Windows launcher with Windows PowerShell:

```powershell
.\build.ps1
```

Run the dependency-free integration tests:

```powershell
python test_bridge.py
python test_external_bridge.py
```

Create and inspect the npm package:

```bash
npm pack
npm publish --dry-run
```

Validated with Sigil 2.6.2, Python 3.13.2, Node.js 20 and PySide6 6.8.2.1.

## License

[MIT](LICENSE) © 2026 Studio Agartha.

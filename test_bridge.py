#!/usr/bin/env python3
"""Teste integrado mínimo: plugin HTTP + servidor MCP stdio."""

import json
import hashlib
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).parent
spec = spec_from_file_location("sigil_plugin", ROOT / "sigil_plugin/SigilMCPBridge/plugin.py")
plugin = module_from_spec(spec)
spec.loader.exec_module(plugin)


class FakeBook:
    files = {"chapter": "<p>Olá</p>", "style": "p { color: red; }", "image": b"PNG"}
    meta = {
        "chapter": ("Text/chapter.xhtml", "application/xhtml+xml"),
        "style": ("Styles/style.css", "text/css"),
        "image": ("Images/image.png", "image/png"),
    }

    def manifest_iter(self):
        for item_id, (href, mime) in self.meta.items():
            yield item_id, href, mime

    def selected_iter(self):
        yield "manifest", "chapter"

    def id_to_href(self, item_id, fallback=None):
        return self.meta.get(item_id, (fallback,))[0]

    def id_to_mime(self, item_id, fallback=None):
        return self.meta.get(item_id, (None, fallback))[1]

    def readfile(self, item_id):
        return self.files[item_id]

    def writefile(self, item_id, content):
        self.files[item_id] = content

    def epub_version(self):
        return "3.0"

    def get_epub_filepath(self):
        return "test.epub"

    def get_epub_is_modified(self):
        return False


def request(url, path, payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url + path, data=data,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def main():
    plugin.STATE.bk = FakeBook()
    server = plugin.ThreadingHTTPServer((plugin.HOST, 0), plugin.Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{plugin.HOST}:{server.server_port}"
    try:
        assert request(url, "/health")["ok"] is True
        read = request(url, "/read", {"id": "chapter"})
        assert read["content"] == "<p>Olá</p>"
        assert request(url, "/search", {"query": "OLÁ"})["hits"][0]["id"] == "chapter"
        assert request(url, "/write", {"id": "chapter", "content": "<p>Novo</p>",
                                        "expected_sha256": read["sha256"]})["ok"]
        assert plugin.STATE.bk.files["chapter"] == "<p>Novo</p>"
        for path, payload, headers, code in [
            ("/write", {"id": "image", "content": "quebra",
                         "expected_sha256": hashlib.sha256(b"PNG").hexdigest()}, {}, 400),
            ("/health", None, {"Origin": "https://example.com"}, 403),
        ]:
            try:
                request(url, path, payload, headers)
                raise AssertionError(f"{path} deveria falhar")
            except urllib.error.HTTPError as exc:
                assert exc.code == code

        env = {**os.environ, "SIGIL_BRIDGE_URL": url}
        process = subprocess.Popen([sys.executable, str(ROOT / "mcp_server/sigil_mcp.py")],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   text=True, encoding="utf-8", env=env)

        def rpc(message):
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            return json.loads(process.stdout.readline())

        init = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25"}})
        assert init["result"]["serverInfo"]["version"] == "0.2.0"
        health = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "sigil_health", "arguments": {}}})
        assert health["result"]["structuredContent"]["ok"] is True
        discover = rpc({"jsonrpc": "2.0", "id": 3, "method": "server/discover",
                        "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                              "io.modelcontextprotocol/clientCapabilities": {}}}})
        assert discover["result"]["resultType"] == "complete"
        unknown = rpc({"jsonrpc": "2.0", "id": 4, "method": "nope"})
        assert unknown["error"]["code"] == -32601
        process.stdin.write("não é json\n")
        process.stdin.flush()
        assert json.loads(process.stdout.readline())["id"] is None
        process.terminate()
        process.wait(timeout=5)
    finally:
        server.shutdown()
        server.server_close()
    print("OK: plugin HTTP e MCP stdio validados")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Teste integrado mínimo do bridge externo não modal."""

import json
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).parent
spec = spec_from_file_location("external_bridge", ROOT / "external_bridge.py")
bridge = module_from_spec(spec)
spec.loader.exec_module(bridge)


def request(url, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def make_book(root):
    (root / "META-INF").mkdir()
    (root / "OEBPS/Text").mkdir(parents=True)
    (root / "OEBPS/Styles").mkdir()
    (root / "META-INF/container.xml").write_text(
        '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>', encoding="utf-8")
    (root / "OEBPS/content.opf").write_text(
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<manifest><item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="style" href="Styles/style.css" media-type="text/css"/></manifest></package>', encoding="utf-8")
    (root / "OEBPS/Text/chapter.xhtml").write_text("<p>Olá</p>", encoding="utf-8")
    (root / "OEBPS/Styles/style.css").write_text("p { color: red; }", encoding="utf-8")


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_book(root)
        bridge.BOOK = bridge.Book(root / "OEBPS/content.opf")
        server = bridge.ThreadingHTTPServer((bridge.HOST, 0), bridge.Handler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        url = f"http://{bridge.HOST}:{server.server_port}"
        try:
            assert request(url, "/health")["mode"] == "external"
            read = request(url, "/read", {"id": "chapter"})
            assert read["content"] == "<p>Olá</p>"
            assert request(url, "/write", {"id": "chapter", "content": "<p>Novo</p>",
                                            "expected_sha256": read["sha256"]})["ok"]
            assert (root / "OEBPS/Text/chapter.xhtml").read_text(encoding="utf-8") == "<p>Novo</p>"
            try:
                request(url, "/write", {"id": "chapter", "content": "<p>Velho</p>",
                                         "expected_sha256": read["sha256"]})
                raise AssertionError("hash obsoleto deveria falhar")
            except urllib.error.HTTPError as exc:
                assert exc.code == 409

            process = subprocess.Popen([sys.executable, str(ROOT / "mcp_server/sigil_mcp.py")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                env={"SIGIL_BRIDGE_URL": url})
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-11-25"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "sigil_read_file", "arguments": {"id": "chapter"}}},
            ]
            for message in messages:
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
                response = json.loads(process.stdout.readline())
                assert "error" not in response
            process.terminate()
            process.wait(timeout=5)
            bridge.stop_existing(server.server_port)
            server_thread.join(timeout=2)
            assert not server_thread.is_alive()
            threading.Timer(0.2, server.server_close).start()
            replacement = bridge.open_server(server.server_port)
            replacement.server_close()
        finally:
            server.server_close()
    print("OK: bridge externo não modal e proteção contra sobrescrita validados")


if __name__ == "__main__":
    main()

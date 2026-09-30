#!/usr/bin/env python3
"""Bridge não modal para o mecanismo External XHTML Editor do Sigil."""

import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("SIGIL_BRIDGE_PORT", "8765"))
TOKEN = os.environ.get("SIGIL_BRIDGE_TOKEN", "")
VERSION = "0.2.0"
MAX_BODY = 32 * 1024 * 1024
TEXT_MIMES = {
    "application/xhtml+xml", "application/xml", "application/oebps-package+xml",
    "application/x-dtbncx+xml", "application/oebs-page-map+xml", "application/smil+xml",
    "image/svg+xml", "text/css", "text/html", "text/javascript", "application/javascript",
}


class Book:
    def __init__(self, launched_path):
        self.launched_path = Path(launched_path).resolve()
        self.root = self.find_root()
        self.opf = self.find_opf()
        self.lock = threading.RLock()

    def find_root(self):
        start = self.launched_path if self.launched_path.is_dir() else self.launched_path.parent
        for directory in (start, *start.parents):
            if (directory / "META-INF/container.xml").is_file():
                return directory
        raise RuntimeError("não foi possível localizar META-INF/container.xml")

    def find_opf(self):
        if self.launched_path.suffix.lower() == ".opf":
            return self.launched_path
        container = ET.parse(self.root / "META-INF/container.xml").getroot()
        rootfile = container.find(".//{*}rootfile")
        if rootfile is None or not rootfile.get("full-path"):
            raise RuntimeError("container.xml não informa o OPF")
        return (self.root / rootfile.get("full-path")).resolve()

    def manifest(self):
        package = ET.parse(self.opf).getroot()
        rows = []
        for item in package.findall(".//{*}manifest/{*}item"):
            item_id, href, mime = item.get("id"), item.get("href"), item.get("media-type", "")
            if item_id and href:
                rows.append({"id": item_id, "href": href, "mime": mime})
        return rows

    def item(self, item_id):
        row = next((row for row in self.manifest() if row["id"] == item_id), None)
        if row is None:
            raise KeyError("id não encontrado no manifesto")
        path = (self.opf.parent / urllib.parse.unquote(urllib.parse.urlsplit(row["href"]).path)).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            raise ValueError("href fora da raiz do EPUB") from None
        return row, path

    def read(self, item_id):
        row, path = self.item(item_id)
        if row["mime"] not in TEXT_MIMES:
            raise TypeError(f"item binário não é suportado ({row['mime']})")
        raw = path.read_bytes()
        return {**row, "content": raw.decode("utf-8-sig"), "sha256": hashlib.sha256(raw).hexdigest()}

    def write(self, item_id, content, expected_sha256):
        if not isinstance(content, str) or not isinstance(expected_sha256, str):
            raise ValueError("content e expected_sha256 devem ser strings")
        row, path = self.item(item_id)
        if row["mime"] not in TEXT_MIMES:
            raise TypeError(f"item binário não é suportado ({row['mime']})")
        current = path.read_bytes()
        current_hash = hashlib.sha256(current).hexdigest()
        if current_hash != expected_sha256:
            raise FileExistsError("o arquivo mudou desde a leitura; leia novamente antes de escrever")
        data = content.encode("utf-8")
        if current.startswith(b"\xef\xbb\xbf"):
            data = b"\xef\xbb\xbf" + data
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {"ok": True, "id": item_id, "href": row["href"],
                "sha256": hashlib.sha256(data).hexdigest()}


BOOK = None


def stop_existing(port=PORT):
    """Encerra somente outra instância deste bridge antes de trocar de EPUB."""
    url = f"http://{HOST}:{port}"
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "/health", headers=headers),
                                    timeout=0.5) as response:
            health = json.load(response)
    except urllib.error.URLError:
        return
    if health.get("service") != "SigilMCPExternal":
        raise RuntimeError(f"a porta {port} já está em uso por outro serviço")
    request = urllib.request.Request(url + "/shutdown", data=b"{}", headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=1):
        pass
    for _ in range(30):
        time.sleep(0.1)
        try:
            urllib.request.urlopen(url + "/health", timeout=0.1).close()
        except urllib.error.URLError:
            return
        except TimeoutError:
            continue
    raise RuntimeError("a instância anterior do bridge não encerrou")


def open_server(port=PORT):
    for attempt in range(30):
        try:
            return ThreadingHTTPServer((HOST, port), Handler)
        except OSError:
            if attempt == 29:
                raise
            time.sleep(0.1)


class Handler(BaseHTTPRequestHandler):
    server_version = "SigilMCPExternal/" + VERSION

    def log_message(self, *_args):
        pass

    def send_json(self, code, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorize(self):
        if self.headers.get("Origin"):
            self.send_json(403, {"error": "requisições originadas por navegador não são permitidas"})
            return False
        if TOKEN and self.headers.get("Authorization", "") != "Bearer " + TOKEN:
            self.send_json(401, {"error": "não autorizado"})
            return False
        return True

    def payload(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Content-Length inválido") from None
        if not 0 < length <= MAX_BODY:
            raise ValueError(f"corpo deve ter entre 1 e {MAX_BODY} bytes")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("JSON UTF-8 inválido") from None
        if not isinstance(value, dict):
            raise ValueError("o corpo JSON deve ser um objeto")
        return value

    def do_GET(self):
        if not self.authorize():
            return
        with BOOK.lock:
            if self.path == "/health":
                return self.send_json(200, {"ok": True, "service": "SigilMCPExternal",
                                            "version": VERSION, "mode": "external"})
            if self.path == "/manifest":
                return self.send_json(200, {"files": BOOK.manifest()})
            if self.path == "/selected":
                return self.send_json(200, {"files": []})
            if self.path == "/book":
                package = ET.parse(BOOK.opf).getroot()
                return self.send_json(200, {"epub_version": package.get("version", ""),
                                            "mode": "external", "opf": str(BOOK.opf)})
        self.send_json(404, {"error": "não encontrado"})

    def do_POST(self):
        if not self.authorize():
            return
        try:
            data = self.payload()
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        with BOOK.lock:
            try:
                if self.path == "/shutdown":
                    self.send_json(200, {"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                if self.path == "/read":
                    return self.send_json(200, BOOK.read(data["id"]))
                if self.path == "/write":
                    return self.send_json(200, BOOK.write(data["id"], data["content"],
                                                          data["expected_sha256"]))
                if self.path == "/search":
                    query = data.get("query")
                    if not isinstance(query, str) or not query:
                        raise ValueError("query deve ser uma string não vazia")
                    hits = []
                    for row in BOOK.manifest():
                        if row["mime"] in ("application/xhtml+xml", "text/css"):
                            if query.casefold() in BOOK.read(row["id"])["content"].casefold():
                                hits.append(row)
                    return self.send_json(200, {"hits": hits})
            except KeyError as exc:
                return self.send_json(404, {"error": str(exc)})
            except FileExistsError as exc:
                return self.send_json(409, {"error": str(exc)})
            except (TypeError, ValueError) as exc:
                return self.send_json(400, {"error": str(exc)})
            except Exception as exc:
                return self.send_json(500, {"error": str(exc)})
        self.send_json(404, {"error": "não encontrado"})


def stop_when_book_closes(server):
    while BOOK.root.exists() and BOOK.opf.exists():
        time.sleep(1)
    server.shutdown()


def main():
    global BOOK
    if len(sys.argv) < 2:
        return 2
    BOOK = Book(sys.argv[1])
    stop_existing()
    server = open_server()
    server.daemon_threads = True
    threading.Thread(target=stop_when_book_closes, args=(server,), daemon=True).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

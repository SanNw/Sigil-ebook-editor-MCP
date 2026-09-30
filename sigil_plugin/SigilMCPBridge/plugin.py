#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bridge HTTP local entre agentes MCP e o BookContainer do Sigil."""

import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6 import QtWidgets

HOST, PORT, VERSION = "127.0.0.1", 8765, "0.2.0"
MAX_BODY = 32 * 1024 * 1024
TEXT_MIMES = {
    "application/xhtml+xml", "application/xml", "application/oebps-package+xml",
    "application/x-dtbncx+xml", "application/oebs-page-map+xml", "application/smil+xml",
    "image/svg+xml", "text/css", "text/html", "text/javascript", "application/javascript",
}


class State:
    bk = None
    token = ""
    lock = threading.RLock()


STATE = State()


def text_mime(item_id):
    mime = STATE.bk.id_to_mime(item_id, None)
    if mime is None:
        raise KeyError("id não encontrado no manifesto")
    if mime not in TEXT_MIMES:
        raise TypeError(f"item binário não é suportado ({mime})")
    return mime


class Handler(BaseHTTPRequestHandler):
    server_version = "SigilMCPBridge/" + VERSION

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
        if STATE.token and self.headers.get("Authorization", "") != "Bearer " + STATE.token:
            self.send_json(401, {"error": "não autorizado"})
            return False
        return True

    def do_GET(self):
        if not self.authorize():
            return
        with STATE.lock:
            if self.path == "/health":
                return self.send_json(200, {"ok": True, "service": "SigilMCPBridge", "version": VERSION})
            if self.path == "/manifest":
                files = [{"id": i, "href": h, "mime": m} for i, h, m in STATE.bk.manifest_iter()]
                return self.send_json(200, {"files": files})
            if self.path == "/selected":
                files = []
                for kind, item_id in STATE.bk.selected_iter():
                    row = {"type": kind, "id": item_id}
                    if kind == "manifest":
                        row.update(href=STATE.bk.id_to_href(item_id, item_id),
                                   mime=STATE.bk.id_to_mime(item_id, ""))
                    files.append(row)
                return self.send_json(200, {"files": files})
            if self.path == "/book":
                return self.send_json(200, {
                    "epub_version": STATE.bk.epub_version(),
                    "file_path": STATE.bk.get_epub_filepath(),
                    "modified_before_plugin": STATE.bk.get_epub_is_modified(),
                })
        self.send_json(404, {"error": "não encontrado"})

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

    def do_POST(self):
        if not self.authorize():
            return
        try:
            data = self.payload()
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        with STATE.lock:
            try:
                if self.path == "/read":
                    item_id = data["id"]
                    content = STATE.bk.readfile(item_id)
                    return self.send_json(200, {"id": item_id,
                        "href": STATE.bk.id_to_href(item_id, item_id),
                        "mime": text_mime(item_id), "content": content,
                        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
                if self.path == "/write":
                    item_id, content, expected = data["id"], data["content"], data["expected_sha256"]
                    if not isinstance(content, str) or not isinstance(expected, str):
                        raise ValueError("content e expected_sha256 devem ser strings")
                    text_mime(item_id)
                    current = STATE.bk.readfile(item_id)
                    if hashlib.sha256(current.encode("utf-8")).hexdigest() != expected:
                        raise FileExistsError("o arquivo mudou desde a leitura; leia novamente antes de escrever")
                    STATE.bk.writefile(item_id, content)
                    return self.send_json(200, {"ok": True, "id": item_id,
                                                "href": STATE.bk.id_to_href(item_id, item_id),
                                                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
                if self.path == "/search":
                    query = data.get("query")
                    if not isinstance(query, str) or not query:
                        raise ValueError("query deve ser uma string não vazia")
                    hits = []
                    for item_id, href, mime in STATE.bk.manifest_iter():
                        if mime in ("application/xhtml+xml", "text/css"):
                            if query.casefold() in STATE.bk.readfile(item_id).casefold():
                                hits.append({"id": item_id, "href": href, "mime": mime})
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


class Dialog(QtWidgets.QDialog):
    def __init__(self, bk):
        super().__init__()
        STATE.bk = bk
        self.server = None
        self.thread = None
        self.setWindowTitle("Sigil MCP Bridge")
        self.resize(540, 280)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("<h2>Sigil MCP Bridge</h2>"))
        layout.addWidget(QtWidgets.QLabel("Expõe o EPUB aberto apenas em 127.0.0.1 para um MCP local."))
        form = QtWidgets.QFormLayout()
        self.port = QtWidgets.QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(PORT)
        self.token = QtWidgets.QLineEdit()
        self.token.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow("Porta:", self.port)
        form.addRow("Token local (opcional):", self.token)
        layout.addLayout(form)
        self.status = QtWidgets.QLabel("Parado")
        layout.addWidget(self.status)
        layout.addWidget(QtWidgets.QLabel("As alterações são aplicadas ao Sigil quando esta janela é fechada normalmente."))
        row = QtWidgets.QHBoxLayout()
        self.start = QtWidgets.QPushButton("Iniciar bridge")
        self.stop = QtWidgets.QPushButton("Parar")
        self.stop.setEnabled(False)
        self.start.clicked.connect(self.start_server)
        self.stop.clicked.connect(self.stop_server)
        row.addWidget(self.start)
        row.addWidget(self.stop)
        row.addStretch()
        layout.addLayout(row)

    def start_server(self, checked=False):
        if self.server:
            return
        STATE.token = self.token.text()
        try:
            self.server = ThreadingHTTPServer((HOST, self.port.value()), Handler)
            self.server.daemon_threads = True
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.status.setText(f"Ativo em http://{HOST}:{self.port.value()}")
            self.start.setEnabled(False)
            self.stop.setEnabled(True)
        except Exception as exc:
            self.server = None
            QtWidgets.QMessageBox.critical(self, "Bridge", str(exc))

    def stop_server(self, checked=False):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self.status.setText("Parado")
        self.start.setEnabled(True)
        self.stop.setEnabled(False)

    def closeEvent(self, event):
        self.stop_server()
        super().closeEvent(event)


def run(bk):
    app = QtWidgets.QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QtWidgets.QApplication(sys.argv)
    Dialog(bk).exec()
    if owns_app:
        app.quit()
    return 0


def main():
    return -1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Servidor MCP stdio, sem dependências, para o plugin SigilMCPBridge."""

import json
import os
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.environ.get("SIGIL_BRIDGE_URL", "http://127.0.0.1:8765").rstrip("/")
TOKEN = os.environ.get("SIGIL_BRIDGE_TOKEN", "")
TIMEOUT = float(os.environ.get("SIGIL_BRIDGE_TIMEOUT", "20"))
VERSION = "0.2.0"
MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INFO = {"name": "sigil-mcp", "title": "Sigil MCP Bridge", "version": VERSION}
EMPTY = {"type": "object", "additionalProperties": False}


def tool(name, description, properties=None, required=(), write=False):
    schema = EMPTY if properties is None else {
        "type": "object", "properties": properties,
        "required": list(required), "additionalProperties": False,
    }
    return {
        "name": name, "description": description, "inputSchema": schema,
        "annotations": {"readOnlyHint": not write, "destructiveHint": write},
    }


TOOLS = [
    tool("sigil_health", "Verifica se o bridge do Sigil está ativo."),
    tool("sigil_book_info", "Mostra informações do EPUB aberto no Sigil."),
    tool("sigil_list_files", "Lista os arquivos do manifesto do EPUB aberto."),
    tool("sigil_selected_files", "Lista os arquivos selecionados quando o plugin foi aberto."),
    tool("sigil_read_file", "Lê um arquivo textual do EPUB (XHTML, CSS, XML, SVG ou JavaScript).",
         {"id": {"type": "string", "minLength": 1}}, ("id",)),
    tool("sigil_search", "Busca texto não vazio nos arquivos XHTML e CSS.",
         {"query": {"type": "string", "minLength": 1}}, ("query",)),
    tool("sigil_write_file", "Substitui um arquivo textual existente se ele não mudou desde a leitura anterior.",
         {"id": {"type": "string", "minLength": 1}, "content": {"type": "string"},
          "expected_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
         ("id", "content", "expected_sha256"), True),
]

ROUTES = {
    "sigil_health": ("/health", ()), "sigil_book_info": ("/book", ()),
    "sigil_list_files": ("/manifest", ()), "sigil_selected_files": ("/selected", ()),
    "sigil_read_file": ("/read", ("id",)), "sigil_search": ("/search", ("query",)),
    "sigil_write_file": ("/write", ("id", "content", "expected_sha256")),
}


def call(path, payload=None):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(BASE + path, data=data, headers=headers,
                                     method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", exc.reason)
        except Exception:
            detail = exc.reason
        raise RuntimeError(f"Bridge do Sigil retornou HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Bridge indisponível em {BASE}. Abra o plugin no Sigil e clique em 'Iniciar bridge'. ({exc.reason})"
        ) from None


def send(request_id, *, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": request_id}
    message["error" if error else "result"] = error or result
    print(json.dumps(message, ensure_ascii=False, separators=(",", ":")), flush=True)


def modern(params):
    return isinstance(params, dict) and params.get("_meta", {}).get(
        "io.modelcontextprotocol/protocolVersion") == MODERN


def complete(value, is_modern):
    if is_modern:
        value = {"resultType": "complete", **value}
        value["_meta"] = {"io.modelcontextprotocol/serverInfo": INFO}
    return value


def validate(arguments, required):
    if not isinstance(arguments, dict):
        raise ValueError("arguments deve ser um objeto")
    extra = set(arguments) - set(required)
    if extra:
        raise ValueError("argumento inesperado: " + ", ".join(sorted(extra)))
    for key in required:
        if key not in arguments or not isinstance(arguments[key], str):
            raise ValueError(f"{key} deve ser uma string")
        if key != "content" and not arguments[key]:
            raise ValueError(f"{key} não pode ser vazio")


def handle(message):
    request_id, method = message.get("id"), message.get("method")
    params = message.get("params", {})
    is_modern = modern(params)

    if method == "server/discover":
        send(request_id, result=complete({
            "supportedVersions": [MODERN, *LEGACY], "capabilities": {"tools": {}},
            "instructions": "Leia antes de escrever. Apenas arquivos textuais podem ser alterados.",
            "ttlMs": 300000, "cacheScope": "public",
        }, True))
    elif method == "initialize":
        requested = params.get("protocolVersion")
        send(request_id, result={
            "protocolVersion": requested if requested in LEGACY else LEGACY[0],
            "capabilities": {"tools": {"listChanged": False}}, "serverInfo": INFO,
            "instructions": "Leia antes de escrever. Apenas arquivos textuais podem ser alterados.",
        })
    elif method in ("notifications/initialized", "notifications/cancelled"):
        return
    elif method == "ping":
        send(request_id, result=complete({}, is_modern))
    elif method == "tools/list":
        send(request_id, result=complete({"tools": TOOLS}, is_modern))
    elif method == "tools/call":
        name = params.get("name")
        if name not in ROUTES:
            send(request_id, error={"code": -32602, "message": f"Ferramenta desconhecida: {name}"})
            return
        path, required = ROUTES[name]
        arguments = params.get("arguments", {})
        try:
            validate(arguments, required)
        except ValueError as exc:
            send(request_id, error={"code": -32602, "message": str(exc)})
            return
        try:
            data = call(path, arguments if required else None)
            value = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                     "structuredContent": data, "isError": False}
        except Exception as exc:
            value = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        send(request_id, result=complete(value, is_modern))
    elif request_id is not None:
        send(request_id, error={"code": -32601, "message": f"Método desconhecido: {method}"})


def main():
    for line in sys.stdin:
        request_id = None
        try:
            message = json.loads(line)
            request_id = message.get("id") if isinstance(message, dict) else None
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise ValueError("Requisição JSON-RPC inválida")
            handle(message)
        except json.JSONDecodeError:
            send(None, error={"code": -32700, "message": "Erro de parsing"})
        except ValueError as exc:
            send(request_id, error={"code": -32600, "message": str(exc)})
        except Exception as exc:
            send(request_id, error={"code": -32603, "message": str(exc)})


if __name__ == "__main__":
    main()

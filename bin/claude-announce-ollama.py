#!/usr/bin/env python3
"""Small stdlib Ollama client used by Linux setup and runtime.

The HTTP API is the source of truth. This intentionally does not assume
systemd, a local binary, or even that Ollama runs on this machine.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_HOST = "http://127.0.0.1:11434"
ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "answered",
                "verified",
                "investigated",
                "proposed",
                "changed",
                "produced",
                "waiting",
                "recapped",
                "blocked",
                "failed",
                "unknown",
            ],
        },
        "evidence": {"type": "string"},
        "topic": {"type": "string"},
    },
    "required": ["status", "evidence", "topic"],
    "additionalProperties": False,
}


class OllamaError(RuntimeError):
    pass


def normalize_host(value):
    value = (value or DEFAULT_HOST).strip().rstrip("/")
    if not value:
        value = DEFAULT_HOST
    if "://" not in value:
        value = "http://" + value
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("invalid Ollama host: " + value)

    # OLLAMA_HOST is commonly set to a server bind address. Wildcard bind
    # addresses are not useful client destinations, so connect over loopback.
    hostname = parsed.hostname
    if hostname in ("0.0.0.0", "::", "[::]"):
        hostname = "127.0.0.1"
        port = parsed.port
        netloc = hostname + ((":" + str(port)) if port else "")
        parsed = parsed._replace(netloc=netloc)

    path = parsed.path.rstrip("/")
    if path == "/api":
        path = ""
    elif path.endswith("/api"):
        path = path[:-4]
    return urllib.parse.urlunsplit(parsed._replace(path=path, query="", fragment=""))


def request_json(host, path, payload=None, timeout=5, stream=False):
    host = normalize_host(host)
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(host + path, data=data, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        # The response body says WHY the server refused (e.g. an unknown
        # request field on an older server); keep it so callers can react.
        try:
            detail = error.read().decode("utf-8", "replace").strip()
        except OSError:
            detail = ""
        message = str(error) + ((": " + detail[:200]) if detail else "")
        raise OllamaError(message) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise OllamaError(str(error)) from error

    if stream:
        return response
    try:
        with response:
            return json.load(response)
    except (ValueError, OSError) as error:
        raise OllamaError("invalid response from Ollama: " + str(error)) from error


def probe(host, timeout=2):
    host = normalize_host(host)
    try:
        result = request_json(host, "/api/version", timeout=timeout)
        return host, str(result.get("version", "unknown"))
    except OllamaError:
        # Older or proxied servers may omit /api/version while still exposing
        # the core model API.
        request_json(host, "/api/tags", timeout=timeout)
        return host, "unknown"


def models(host, timeout=5):
    result = request_json(host, "/api/tags", timeout=timeout)
    return [item.get("name") or item.get("model") for item in result.get("models", [])]


def has_model(host, wanted, timeout=5):
    names = {name for name in models(host, timeout) if name}
    if wanted in names:
        return True
    # Ollama accepts an omitted :latest tag. Treat the two spellings as equal.
    if ":" not in wanted and wanted + ":latest" in names:
        return True
    if wanted.endswith(":latest") and wanted[:-7] in names:
        return True
    return False


def generate(host, model, prompt, json_output=False, timeout=60):
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "5m",
        # Hybrid-thinking models (the qwen3 family) otherwise spend the whole
        # num_predict budget on thinking tokens and return an empty response.
        # Non-thinking models accept and ignore the field (verified on
        # llama3.2:3b, Ollama 0.30).
        "think": False,
        "options": {
            "temperature": 0 if json_output else 0.2,
            "num_predict": 180 if json_output else 60,
        },
    }
    if json_output:
        payload["format"] = ASSESSMENT_SCHEMA
    try:
        result = request_json(host, "/api/generate", payload, timeout=timeout)
    except OllamaError as error:
        # Servers predating the think field reject the whole request; retry
        # once without it so non-thinking models on old Ollama keep working.
        if "think" not in str(error).lower():
            raise
        del payload["think"]
        result = request_json(host, "/api/generate", payload, timeout=timeout)
    response = result.get("response")
    if not isinstance(response, str) or not response.strip():
        raise OllamaError("Ollama returned an empty response")
    return response.strip()


def pull(host, model, timeout=3600):
    response = request_json(
        host,
        "/api/pull",
        {"model": model, "stream": True},
        timeout=timeout,
        stream=True,
    )
    last_status = ""
    with response:
        for raw in response:
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if item.get("error"):
                raise OllamaError(str(item["error"]))
            status = str(item.get("status", ""))
            total = item.get("total")
            completed = item.get("completed")
            if total and completed is not None:
                percent = min(100, int(completed * 100 / total))
                display = status + " " + str(percent) + "%"
            else:
                display = status
            if display and display != last_status:
                print("    " + display, file=sys.stderr)
                last_status = display
    return True


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("probe", "models"):
        sub = subparsers.add_parser(name)
        sub.add_argument("host", nargs="?", default=DEFAULT_HOST)

    has = subparsers.add_parser("has-model")
    has.add_argument("host")
    has.add_argument("model")

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("host")
    generate_parser.add_argument("model")
    generate_parser.add_argument("--json", action="store_true")
    generate_parser.add_argument("--timeout", type=int, default=60)

    pull_parser = subparsers.add_parser("pull")
    pull_parser.add_argument("host")
    pull_parser.add_argument("model")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "probe":
            host, version = probe(args.host)
            print(host + "\t" + version)
        elif args.command == "models":
            print("\n".join(models(args.host)))
        elif args.command == "has-model":
            return 0 if has_model(args.host, args.model) else 1
        elif args.command == "generate":
            print(generate(
                args.host,
                args.model,
                sys.stdin.read(),
                json_output=args.json,
                timeout=args.timeout,
            ))
        elif args.command == "pull":
            pull(args.host, args.model)
    except (OllamaError, ValueError) as error:
        print("ollama: " + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

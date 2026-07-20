#!/usr/bin/env python3

import importlib.util
import json
import pathlib
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "bin" / "claude-announce-ollama.py"
SPEC = importlib.util.spec_from_file_location("ollama_client", PATH)
ollama = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ollama)


class Handler(BaseHTTPRequestHandler):
    requests = []
    reject_think = False

    def log_message(self, *_args):
        pass

    def send_json(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.requests.append(("GET", self.path, None))
        if self.path == "/api/version":
            self.send_json({"version": "9.8.7"})
        elif self.path == "/api/tags":
            self.send_json({"models": [{"name": "llama3.2:3b"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        self.requests.append(("POST", self.path, payload))
        if self.path == "/api/generate":
            if Handler.reject_think and "think" in payload:
                self.send_json(
                    {"error": 'json: unknown field "think"'}, status=400)
                return
            self.send_json({"response": '{"status":"answered","evidence":"answered it","topic":"foot"}'})
        elif self.path == "/api/pull":
            body = b'{"status":"pulling","total":10,"completed":5}\n{"status":"success"}\n'
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


class OllamaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Handler.requests = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def test_normalize_bind_addresses_and_api_suffix(self):
        self.assertEqual(
            ollama.normalize_host("0.0.0.0:11434/api/"),
            "http://127.0.0.1:11434",
        )
        self.assertEqual(
            ollama.normalize_host("http://[::]:11434"),
            "http://127.0.0.1:11434",
        )

    def test_probe_and_model_detection(self):
        host, version = ollama.probe(self.host)
        self.assertEqual(host, self.host)
        self.assertEqual(version, "9.8.7")
        self.assertTrue(ollama.has_model(self.host, "llama3.2:3b"))
        self.assertFalse(ollama.has_model(self.host, "missing:1b"))

    def test_structured_generation_uses_schema_and_five_minute_keepalive(self):
        result = ollama.generate(self.host, "llama3.2:3b", "prompt", True)
        self.assertIn('"status":"answered"', result)
        payload = [
            request[2]
            for request in Handler.requests
            if request[0] == "POST" and request[1] == "/api/generate"
        ][-1]
        self.assertEqual(payload["keep_alive"], "5m")
        self.assertEqual(payload["format"]["type"], "object")
        self.assertEqual(payload["options"]["temperature"], 0)
        # Hybrid-thinking models return empty responses unless thinking is
        # disabled per request; Modelfiles cannot carry the setting.
        self.assertIs(payload["think"], False)

    def test_think_rejecting_server_gets_one_retry_without_think(self):
        Handler.reject_think = True
        try:
            result = ollama.generate(self.host, "llama3.2:3b", "prompt", True)
        finally:
            Handler.reject_think = False
        self.assertIn('"status":"answered"', result)
        attempts = [
            request[2]
            for request in Handler.requests
            if request[0] == "POST" and request[1] == "/api/generate"
        ][-2:]
        self.assertIn("think", attempts[0])
        self.assertNotIn("think", attempts[1])

    def test_unrelated_server_error_is_not_retried(self):
        with self.assertRaises(ollama.OllamaError) as caught:
            ollama.request_json(self.host, "/api/missing", {"x": 1})
        self.assertIn("404", str(caught.exception))

    def test_pull_stream(self):
        self.assertTrue(ollama.pull(self.host, "llama3.2:3b"))


if __name__ == "__main__":
    unittest.main()

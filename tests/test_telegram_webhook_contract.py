"""Contract tests for the Vercel Telegram webhook boundary.

These tests avoid network access and verify request validation/idempotency shape.
"""
from __future__ import annotations

import io
import json


def invoke(handler, method="GET", body=b"", headers=None):
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": method,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    environ.update(headers or {})
    result = handler(environ, start_response)
    captured["body"] = b"".join(result)
    captured["statusCode"] = int(str(captured["status"]).split()[0])
    return captured


def test_webhook_module_exports_handler():
    from api.telegram.webhook import handler, main

    assert handler is main


def test_invalid_json_is_rejected():
    from api.telegram.webhook import handler

    response = invoke(handler, "POST", b"{")
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "invalid_json"


def test_get_is_health_response():
    from api.telegram.webhook import handler

    response = invoke(handler, "GET")
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["service"] == "mafia-nights-telegram"

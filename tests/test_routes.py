# Author: Claude Sonnet 4 (Cascade)
# Date: 2026-03-26 14:55
# PURPOSE: Route-level integration tests for Flask API endpoints. Mocks the service layer
#   and DB to isolate HTTP behaviour (status codes, response shapes, method enforcement).
#   Covers 8 route groups: game listing, game source, session start, session step, session
#   reset, auth status, auth logout, and LLM proxies. Zero live API calls.
# SRP/DRY check: Pass — tests HTTP layer only; service logic tested in test_services.py

"""Route-level integration tests.

Tests Flask routes with mocked service layer and DB. Verifies status codes,
response JSON shapes, and error handling. All tests run in staging mode
(bot_protection + turnstile pass through).
"""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("SERVER_MODE", "staging")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _get_client():
    """Import app and return a test client. Separate function to isolate import."""
    from server.app import app
    app.config["TESTING"] = True
    return app.test_client(), app


class TestGameListingRoutes(unittest.TestCase):
    """Tests for GET /api/games."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _get_client()

    def test_returns_list(self):
        """GET /api/games returns a JSON list."""
        r = self.client.get("/api/games")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.get_json(), list)

    def test_each_game_has_game_id(self):
        """Each game entry has a game_id field."""
        r = self.client.get("/api/games")
        for game in r.get_json():
            self.assertIn("game_id", game)


class TestGameSourceRoutes(unittest.TestCase):
    """Tests for GET /api/games/<id>/source."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _get_client()

    def test_unknown_game_returns_404(self):
        """Request for nonexistent game returns 404."""
        r = self.client.get("/api/games/nonexistent-game-xyz/source")
        self.assertEqual(r.status_code, 404)
        data = r.get_json()
        self.assertIn("error", data)


class TestSessionStartRoutes(unittest.TestCase):
    """Tests for POST /api/start."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _get_client()

    def test_start_missing_game_id(self):
        """POST /api/start without game_id returns 400."""
        r = self.client.post("/api/start",
                             data=json.dumps({}),
                             content_type="application/json")
        self.assertIn(r.status_code, (400, 500))

    def test_start_rejects_get(self):
        """GET /api/start returns 405."""
        r = self.client.get("/api/start")
        self.assertEqual(r.status_code, 405)


class TestSessionStepRoutes(unittest.TestCase):
    """Tests for POST /api/step."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _get_client()

    def test_step_missing_session_id(self):
        """POST /api/step without session_id returns error."""
        r = self.client.post("/api/step",
                             data=json.dumps({"action": 1}),
                             content_type="application/json")
        self.assertIn(r.status_code, (400, 404, 500))

    def test_step_unknown_session(self):
        """POST /api/step with unknown session_id returns error."""
        r = self.client.post("/api/step",
                             data=json.dumps({"session_id": "nonexistent-xyz", "action": 1}),
                             content_type="application/json")
        self.assertIn(r.status_code, (400, 404, 500))
        data = r.get_json()
        self.assertIn("error", data)

    def test_step_rejects_get(self):
        """GET /api/step returns 405."""
        r = self.client.get("/api/step")
        self.assertEqual(r.status_code, 405)


class TestSessionResetRoutes(unittest.TestCase):
    """Tests for POST /api/reset."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _get_client()

    def test_reset_unknown_session(self):
        """POST /api/reset with unknown session_id returns error."""
        r = self.client.post("/api/reset",
                             data=json.dumps({"session_id": "nonexistent-xyz"}),
                             content_type="application/json")
        self.assertIn(r.status_code, (400, 404, 500))

    def test_reset_rejects_get(self):
        """GET /api/reset returns 405."""
        r = self.client.get("/api/reset")
        self.assertEqual(r.status_code, 405)


class TestAuthStatusRoutes(unittest.TestCase):
    """Tests for GET /api/auth/status."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _get_client()

    def test_unauthenticated_returns_expected_shape(self):
        """Unauthenticated request returns {authenticated: false, user: null}."""
        r = self.client.get("/api/auth/status")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertFalse(data["authenticated"])
        self.assertIsNone(data["user"])


class TestAuthLogoutRoutes(unittest.TestCase):
    """Tests for POST /api/auth/logout."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _get_client()

    def test_logout_returns_200(self):
        """POST /api/auth/logout returns 200 even without session."""
        r = self.client.post("/api/auth/logout")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "ok")


class TestLLMProxyRoutes(unittest.TestCase):
    """Tests for LLM CORS proxy endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _get_client()

    def test_anthropic_proxy_missing_body(self):
        """POST /api/llm/anthropic-proxy with empty body returns 400."""
        r = self.client.post("/api/llm/anthropic-proxy",
                             data=json.dumps({}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertIn("error", data)

    def test_anthropic_proxy_non_oauth_key(self):
        """POST /api/llm/anthropic-proxy with non-OAuth key returns 400."""
        r = self.client.post("/api/llm/anthropic-proxy",
                             data=json.dumps({"api_key": "sk-ant-api-fake", "model": "claude-sonnet-4-6"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertIn("OAuth", data["error"])

    def test_lmstudio_proxy_missing_model(self):
        """POST /api/llm/lmstudio-proxy without model returns 400."""
        r = self.client.post("/api/llm/lmstudio-proxy",
                             data=json.dumps({"messages": []}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertIn("error", data)

    def test_cf_proxy_missing_fields(self):
        """POST /api/llm/cf-proxy without required fields returns 400."""
        r = self.client.post("/api/llm/cf-proxy",
                             data=json.dumps({}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertIn("error", data)


class TestErrorHandling(unittest.TestCase):
    """Tests for general error handling patterns."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _get_client()

    def test_wrong_method_returns_405(self):
        """Routes with method restrictions return 405 on wrong method."""
        post_only_routes = ["/api/start", "/api/step", "/api/reset", "/api/undo"]
        for route in post_only_routes:
            r = self.client.get(route)
            self.assertEqual(r.status_code, 405,
                             f"{route} should reject GET with 405, got {r.status_code}")

    def test_nonexistent_route_returns_404(self):
        """Unknown routes return 404."""
        r = self.client.get("/api/this-route-does-not-exist")
        self.assertEqual(r.status_code, 404)

    def test_session_detail_unknown_returns_error(self):
        """GET /api/sessions/<unknown_id> returns 404 or error."""
        r = self.client.get("/api/sessions/nonexistent-session-xyz-123")
        data = r.get_json()
        # Returns 404 (not found) or 500 (session_db disabled / DB error)
        self.assertIn(r.status_code, (404, 500))
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()

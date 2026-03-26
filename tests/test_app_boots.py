# Author: Claude Sonnet 4 (Cascade)
# Date: 2026-03-26 14:55
# PURPOSE: Flask boot smoke tests — verifies the app object initialises successfully and
#   core routes return expected status codes. Uses Flask test client with SERVER_MODE=staging
#   so bot_protection and turnstile decorators pass through. DB is the real SQLite file
#   (already created at db.py import time by _init_db()). Zero live API calls. Runs in < 2s.
# SRP/DRY check: Pass — one concern: does the app boot and respond?
"""Flask boot smoke tests.

Verifies the app object creates successfully, key routes return expected
status codes, and the response shapes are correct. All tests run against
the real Flask app in staging mode (bot_protection + turnstile pass through).
"""

import os
import sys
import unittest

# Ensure staging mode so bot_protection and turnstile decorators pass through
os.environ.setdefault("SERVER_MODE", "staging")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestAppBoots(unittest.TestCase):
    """Verify the Flask app boots and creates a test client."""

    @classmethod
    def setUpClass(cls):
        from server.app import app
        cls.app = app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_app_exists(self):
        """Flask app object is created."""
        self.assertIsNotNone(self.app)

    def test_app_is_flask_instance(self):
        """App is a Flask instance."""
        from flask import Flask
        self.assertIsInstance(self.app, Flask)

    def test_routes_registered(self):
        """App has a substantial number of routes registered."""
        rules = list(self.app.url_map.iter_rules())
        # The plan says 57+ routes; verify at least 30 to catch gross breakage
        self.assertGreater(len(rules), 30,
                           f"Expected 30+ routes, got {len(rules)}")


class TestCoreRoutes(unittest.TestCase):
    """Test that core routes respond with expected status codes."""

    @classmethod
    def setUpClass(cls):
        from server.app import app
        cls.app = app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_auth_status_returns_200_json(self):
        """GET /api/auth/status returns 200 with JSON body."""
        r = self.client.get("/api/auth/status")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("authenticated", data)

    def test_auth_status_unauthenticated_shape(self):
        """Unauthenticated request returns expected shape."""
        r = self.client.get("/api/auth/status")
        data = r.get_json()
        self.assertFalse(data["authenticated"])
        self.assertIn("user", data)

    def test_auth_logout_returns_200(self):
        """POST /api/auth/logout returns 200."""
        r = self.client.post("/api/auth/logout")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "ok")

    def test_unknown_route_returns_404(self):
        """GET on a nonexistent path returns 404."""
        r = self.client.get("/this/route/does/not/exist")
        self.assertEqual(r.status_code, 404)

    def test_games_api_returns_200_json(self):
        """GET /api/games returns 200 with a JSON list."""
        r = self.client.get("/api/games")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIsInstance(data, list)

    def test_leaderboard_returns_200(self):
        """GET /api/leaderboard returns 200."""
        r = self.client.get("/api/leaderboard")
        self.assertEqual(r.status_code, 200)

    def test_sessions_browse_returns_json(self):
        """GET /api/sessions/browse returns JSON (may 500 if export dir absent)."""
        r = self.client.get("/api/sessions/browse")
        self.assertIn(r.status_code, (200, 500))
        data = r.get_json()
        self.assertIsNotNone(data)

    def test_sessions_public_returns_200(self):
        """GET /api/sessions/public returns 200."""
        r = self.client.get("/api/sessions/public")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("sessions", data)

    def test_llm_models_returns_200(self):
        """GET /api/llm/models returns 200 with models dict."""
        r = self.client.get("/api/llm/models")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIsInstance(data, dict)
        self.assertIn("models", data)


class TestMethodNotAllowed(unittest.TestCase):
    """Verify correct HTTP method enforcement."""

    @classmethod
    def setUpClass(cls):
        from server.app import app
        cls.app = app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_start_rejects_get(self):
        """GET /api/start should return 405 (POST only)."""
        r = self.client.get("/api/start")
        self.assertEqual(r.status_code, 405)

    def test_step_rejects_get(self):
        """GET /api/step should return 405 (POST only)."""
        r = self.client.get("/api/step")
        self.assertEqual(r.status_code, 405)

    def test_reset_rejects_get(self):
        """GET /api/reset should return 405 (POST only)."""
        r = self.client.get("/api/reset")
        self.assertEqual(r.status_code, 405)


if __name__ == "__main__":
    unittest.main()

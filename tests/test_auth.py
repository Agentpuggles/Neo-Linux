"""Session handling: the two OAuth quirks NeoFN actually requires, token storage,
and refresh-before-expiry. No network — every HTTP entry point is stubbed.
"""

import contextlib
import io
import json
import pathlib
import shutil
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests import support
from tests.support import neo

TOKEN = {
    "access_token": "ACCESS",
    "refresh_token": "REFRESH",
    "account_id": "ACCOUNT",
    "display_name": "puggles",
    "expires_at": None,
    "refresh_expires_at": None,
}


class AuthTestCase(unittest.TestCase):
    """Keeps every write inside a throwaway NEO_HOME and stubs out the transport."""

    def setUp(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="auth-", dir=str(support.SANDBOX)))
        stack = contextlib.ExitStack()
        stack.enter_context(support.environment(NEO_HOME=str(tmp / "share")))
        self.addCleanup(stack.close)
        self.addCleanup(shutil.rmtree, tmp, True)
        self.home = tmp / "share"
        self.calls = []

    def stub_json_http(self, response):
        def fake(method, url, body=None, headers=None, timeout=60):
            self.calls.append({"method": method, "url": url, "body": body, "headers": headers})
            return dict(TOKEN, **response) if isinstance(response, dict) else response

        patcher = mock.patch.object(neo, "jhttp", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return self.calls

    def stub_http(self, result=(200, b"{}")):
        def fake(method, url, body=None, headers=None, timeout=60, retries=3):
            self.calls.append({"method": method, "url": url})
            return result

        patcher = mock.patch.object(neo, "http", fake)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestLoginChallenge(AuthTestCase):
    def test_challenge_route_is_case_sensitive(self):
        # lowercase /challenge/discord answers HTTP 500 numericErrorCode 1012
        self.assertIn("/api/oauth/challenge/Discord?", neo.CHALLENGE)
        self.assertNotIn("/challenge/discord", neo.CHALLENGE)

    def test_challenge_carries_the_official_client_and_redirect(self):
        self.assertIn(f"clientId={neo.CLIENT_ID}", neo.CHALLENGE)
        self.assertIn("redirectUri=neolauncher%3A%2F%2Fcallback%2Fauth", neo.CHALLENGE)

    def test_basic_auth_uses_the_launcher_client_credentials(self):
        import base64

        header = neo.basic_auth()["Authorization"]
        self.assertEqual(
            header, "Basic " + base64.b64encode(f"{neo.CLIENT_ID}:{neo.CLIENT_SECRET}".encode()).decode()
        )


class TestTokenExchange(AuthTestCase):
    def test_code_goes_in_the_authorization_code_field(self):
        # NeoFN's endpoint rejects the standard "code" field with
        # 400 common.oauth.invalid_request — gotcha #2 in docs/protocol.md.
        calls = self.stub_json_http({})
        self.stub_http()
        auth = neo.Auth()
        auth.login_code("BK." + "x" * 40)
        body = calls[0]["body"]
        self.assertEqual(calls[0]["method"], "POST")
        self.assertTrue(calls[0]["url"].endswith("/api/oauth/token"))
        self.assertEqual(body["grant_type"], "authorization_code")
        self.assertEqual(body["authorization_code"], "BK." + "x" * 40)
        self.assertNotIn("code", body)

    def test_fresh_login_kills_other_sessions(self):
        self.stub_json_http({})
        self.stub_http()
        neo.Auth().login_code("K" * 30)
        self.assertIn("sessions/kill", json.dumps([c["url"] for c in self.calls]))

    def test_refresh_keeps_other_sessions_alive(self):
        calls = self.stub_json_http({})
        auth = neo.Auth()
        auth.d = dict(TOKEN)
        auth.refresh()
        self.assertEqual(calls[0]["body"], {"grant_type": "refresh_token", "refresh_token": "REFRESH"})
        self.assertNotIn("sessions/kill", json.dumps([c["url"] for c in calls]))

    def test_kill_sessions_failure_does_not_fail_the_login(self):
        self.stub_json_http({})

        def boom(*args, **kwargs):
            raise RuntimeError("network gone")

        patcher = mock.patch.object(neo, "http", boom)
        patcher.start()
        self.addCleanup(patcher.stop)
        auth = neo.Auth()
        auth.login_code("K" * 30)
        self.assertEqual(auth.d["access_token"], "ACCESS")


class TestSessionStore(AuthTestCase):
    def test_tokens_are_written_private_and_reloaded(self):
        auth = neo.Auth()
        auth.d = dict(TOKEN)
        auth.save()
        path = self.home / "auth.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text())["refresh_token"], "REFRESH")
        self.assertTrue(neo.Auth().logged_in)

    def test_logged_in_requires_a_refresh_token(self):
        auth = neo.Auth()
        auth.d = {"access_token": "only-an-access-token"}
        self.assertFalse(auth.logged_in)

    def test_corrupt_session_file_degrades_to_signed_out(self):
        path = self.home / "auth.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json")
        self.assertEqual(neo.Auth().d, {})

    def test_logout_empties_the_file_rather_than_deleting_it(self):
        auth = neo.Auth()
        auth.d = dict(TOKEN)
        auth.save()
        auth.logout()
        self.assertEqual(json.loads((self.home / "auth.json").read_text()), {})
        self.assertFalse(neo.Auth().logged_in)


class TestAccessTokenLifetime(AuthTestCase):
    def _auth_expiring_in(self, delta):
        auth = neo.Auth()
        auth.d = dict(
            TOKEN, access_expires_at=(datetime.now(timezone.utc) + delta).isoformat().replace("+00:00", "Z")
        )
        return auth

    def test_refreshes_when_the_token_is_about_to_expire(self):
        auth = self._auth_expiring_in(timedelta(minutes=1))
        with mock.patch.object(neo.Auth, "refresh", autospec=True) as refresh:
            self.assertEqual(auth.access(), "ACCESS")
        refresh.assert_called_once_with(auth)

    def test_leaves_a_fresh_token_alone(self):
        auth = self._auth_expiring_in(timedelta(hours=4))
        with mock.patch.object(neo.Auth, "refresh", autospec=True) as refresh:
            self.assertEqual(auth.access(), "ACCESS")
        refresh.assert_not_called()

    def test_signed_out_users_are_sent_to_login(self):
        auth = neo.Auth()
        auth.d = {}
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as ctx:
            auth.access()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("neo login", stderr.getvalue())

    def test_unreadable_expiry_is_ignored_rather_than_fatal(self):
        auth = self._auth_expiring_in(timedelta(0))
        auth.d["access_expires_at"] = "sometime next week"
        self.assertEqual(auth.access(), "ACCESS")


class TestExchangeCodes(AuthTestCase):
    def test_both_spelling_of_the_lifetime_field_are_accepted(self):
        for key in ("expiresInSeconds", "expires_in_seconds"):
            with self.subTest(key=key):
                self.stub_json_http({"code": "EXC", key: 30})
                auth = neo.Auth()
                auth.d = dict(TOKEN)
                self.assertEqual(auth.exchange_code(), ("EXC", 30))


if __name__ == "__main__":
    unittest.main()

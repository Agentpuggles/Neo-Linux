"""Friends over XMPP: frame codec, SASL payload, stanza parsing, and an
end-to-end run against a scripted server — no network (localhost sockets only).

The scripted exchange mirrors docs/protocol.md §12: RFC 7395 open, SASL PLAIN
success, bind, session, roster, presence. If the live service diverges, these
tests still pin what *we* send; only the server replies need updating.
"""

import argparse
import base64
import contextlib
import io
import socket
import threading
import unittest
from unittest import mock

from tests import support
from tests.support import neo


class TestFrameCodec(unittest.TestCase):
    def test_client_frames_are_masked_and_roundtrip(self):
        frame = neo.ws_build_text_frame("Hello", mask=b"\x01\x02\x03\x04")
        self.assertEqual(frame[:2], b"\x81\x85")  # FIN+text, masked, len 5
        fin, opcode, payload, consumed = neo.ws_parse_frame(frame)
        self.assertEqual((fin, opcode, payload, consumed), (True, 1, b"Hello", 11))

    def test_unmasked_server_frame(self):
        self.assertEqual(neo.ws_parse_frame(bytes.fromhex("810548656c6c6f")),
                         (True, 1, b"Hello", 7))

    def test_extended_lengths(self):
        for n in (125, 126, 300, 65536):
            with self.subTest(n=n):
                text = "x" * n
                fin, _opcode, payload, _ = neo.ws_parse_frame(
                    neo.ws_build_text_frame(text))
                self.assertTrue(fin)
                self.assertEqual(len(payload), n)

    def test_incomplete_frame_returns_none(self):
        frame = neo.ws_build_text_frame("Hello")
        self.assertIsNone(neo.ws_parse_frame(frame[:-1]))


class TestSaslAndStanzas(unittest.TestCase):
    def test_plain_payload_is_null_separated_base64(self):
        self.assertEqual(neo.sasl_plain("acct", "tok"),
                         base64.b64encode(b"\0acct\0tok").decode())

    def test_presence_parsing(self):
        p = neo.parse_presence("<presence from='a@h/r' type='unavailable'/>")
        self.assertEqual((p["from"], p["type"]), ("a@h/r", "unavailable"))
        p2 = neo.parse_presence('<presence from="b@h"><show>away</show>'
                                "<status>In lobby</status></presence>")
        self.assertEqual((p2["show"], p2["status"]), ("away", "In lobby"))

    def test_non_presence_frames_are_ignored(self):
        self.assertIsNone(neo.parse_presence("<iq type='result'/>"))

    def test_roster_parsing(self):
        xml = ('<iq type="result" id="ros_1"><query xmlns="jabber:iq:roster">'
               '<item jid="a@h" name="A" subscription="both"/>'
               '<item jid="b@h" subscription="pending"/></query></iq>')
        items = neo.parse_roster(xml)
        self.assertEqual([i["jid"] for i in items], ["a@h", "b@h"])
        self.assertEqual(items[1]["subscription"], "pending")

    def test_broken_roster_xml_degrades_to_empty(self):
        self.assertEqual(neo.parse_roster("<not-xml"), [])


class FakeAuth:
    logged_in = True

    def __init__(self):
        self.d = {"account_id": "ACCT", "display_name": "me"}

    def access(self):
        return "TOKEN"


class TestResolveNames(unittest.TestCase):
    def test_batches_the_public_account_endpoint(self):
        def fake_jhttp(method, url, body=None, headers=None, timeout=60):
            self.assertTrue(url.startswith(neo.ACCOUNT + "/api/public/account?"))
            self.assertIn("accountId=a", url)
            self.assertIn("accountId=b", url)
            return [{"id": "a", "displayName": "Alpha"}, {"id": "b", "displayName": "Beta"}]

        with mock.patch.object(neo, "jhttp", fake_jhttp):
            self.assertEqual(neo.resolve_names(FakeAuth(), ["a", "b"]),
                             {"a": "Alpha", "b": "Beta"})

    def test_transport_errors_leave_names_unresolved(self):
        with mock.patch.object(neo, "jhttp", side_effect=RuntimeError("down")):
            self.assertEqual(neo.resolve_names(FakeAuth(), ["a"]), {})


def server_frame(text):
    payload = text.encode()
    n = len(payload)
    if n < 126:
        return bytes([0x81, n]) + payload
    assert n < 65536  # tests never need the 8-byte length form
    return bytes([0x81, 126]) + n.to_bytes(2, "big") + payload


SCRIPTED = [
    ("<open", '<open xmlns="urn:ietf:params:xml:ns:xmpp-framing" from="h" id="1" version="1.0"/>'),
    ("<auth", '<success xmlns="urn:ietf:params:xml:ns:xmpp-sasl"/>'),
    ("xmpp-bind", '<iq type="result" id="bind_1"><bind xmlns="urn:ietf:params:xml:ns:xmpp-bind">'
                  "<jid>ACCT@h/neo_launcher_bind_1</jid></bind></iq>"),
    ("xmpp-session", '<iq type="result" id="sess_1"></iq>'),
    ("jabber:iq:roster", '<iq type="result" id="ros_1"><query xmlns="jabber:iq:roster">'
                         '<item jid="friend1@h" subscription="both"/>'
                         '<item jid="friend2@h" subscription="both"/></query></iq>'),
    ("<presence/>", '<presence from="friend1@h/res"><show>chat</show>'
                    "<status>Online via Neo</status></presence>"),
]


class ScriptedServer(threading.Thread):
    """Speaks exactly the exchange `neo friends` expects, on localhost."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.seen = []

    def run(self):
        try:
            conn, _ = self.sock.accept()
            conn.settimeout(10)
            buf = b""
            while b"\r\n\r\n" not in buf:
                buf += conn.recv(4096)
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                         b"Connection: Upgrade\r\nSec-WebSocket-Accept: placeholder\r\n\r\n")
            buf = b""
            while True:
                frame = neo.ws_parse_frame(buf)
                while frame is None:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    buf += chunk
                    frame = neo.ws_parse_frame(buf)
                _, _, payload, consumed = frame
                buf = buf[consumed:]
                text = payload.decode("utf-8", "replace")
                self.seen.append(text)
                for needle, reply in SCRIPTED:
                    if needle in text:
                        conn.sendall(server_frame(reply))
                        break
                else:
                    if "unavailable" in text:  # snapshot done
                        return
        except Exception:
            pass
        finally:
            try:
                self.sock.close()
            except Exception:
                pass


class TestFriendsEndToEnd(unittest.TestCase):
    def test_roster_and_presence_through_a_scripted_server(self):
        server = ScriptedServer()
        server.start()
        with mock.patch.object(neo, "resolve_names",
                               lambda a, ids: {"friend1": "Friend One",
                                               "friend2": "Friend Two"}), \
             support.environment(NEO_XMPP=f"ws://127.0.0.1:{server.port}"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                neo.cmd_friends(argparse.Namespace(verbose=False, wait=0.6), FakeAuth())
        server.join(timeout=2)  # let the thread record the final unavailable stanza
        text = out.getvalue()
        self.assertIn("2 friend(s)", text)
        self.assertIn("Friend One", text)
        self.assertIn("chat", text)  # the presence show state
        self.assertIn("Online via Neo", text)
        self.assertIn("transport: xmpp", text)
        joined = " ".join(server.seen)  # the client spoke a complete session
        for needle in ("<open", "<auth", "xmpp-bind", "xmpp-session",
                       "jabber:iq:roster", "<presence/>", "unavailable"):
            self.assertIn(needle, joined)
        server.join(timeout=2)

    def test_plain_wire_format_inside_the_exchange(self):
        server = ScriptedServer()
        server.start()
        with mock.patch.object(neo, "resolve_names", lambda a, ids: {}), \
             support.environment(NEO_XMPP=f"ws://127.0.0.1:{server.port}"), \
             contextlib.redirect_stdout(io.StringIO()):
            neo.cmd_friends(argparse.Namespace(verbose=False, wait=0.2), FakeAuth())
        auth_stanza = next(s for s in server.seen if s.startswith("<auth"))
        expected = base64.b64encode(b"\0ACCT\0TOKEN").decode()
        self.assertIn(f'mechanism="PLAIN">{expected}</auth>', auth_stanza)
        server.join(timeout=2)

    def test_rest_fallback_when_websocket_is_down(self):
        with support.environment(NEO_XMPP="ws://127.0.0.1:1"):  # nothing listens
            friends = [{"jid": "f1", "name": "", "subscription": "ACCEPTED"}]
            with mock.patch.object(neo, "friends_http", lambda a: friends), \
                    mock.patch.object(neo, "resolve_names", lambda a, ids: {"f1": "Pal"}):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), \
                        contextlib.redirect_stderr(io.StringIO()):
                    neo.cmd_friends(argparse.Namespace(verbose=False, wait=0.2),
                                    FakeAuth())
        self.assertIn("transport: http", out.getvalue())
        self.assertIn("Pal", out.getvalue())


if __name__ == "__main__":
    unittest.main()

"""Unit tests for the parts that do not need a browser or a model: python3 -m unittest discover tests"""
import os
import tempfile
import unittest

from browser_agent import history
from browser_agent.browser import Browser
from browser_agent.policy import Policy
from browser_agent.secrets import Secrets


class SecretsTest(unittest.TestCase):
    def setUp(self):
        self.f = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False)
        self.f.write("CARD_NUMBER=4242 4242 4242 4242\nSHOP_PASSWORD='s3cret-pass'\n# comment\n")
        self.f.close()
        self.s = Secrets({"provider": "dotenv", "dotenv_path": self.f.name})

    def tearDown(self):
        os.unlink(self.f.name)

    def test_names_never_values(self):
        self.assertEqual(self.s.names(), ["CARD_NUMBER", "SHOP_PASSWORD"])

    def test_fill_nested(self):
        args = {"fields": [{"value": "{{secret:CARD_NUMBER}}"}, {"value": "pw={{secret:SHOP_PASSWORD}}"}]}
        out = self.s.fill(args)
        self.assertEqual(out["fields"][0]["value"], "4242 4242 4242 4242")
        self.assertEqual(out["fields"][1]["value"], "pw=s3cret-pass")
        self.assertIn("{{secret:", args["fields"][0]["value"])  # the original is untouched

    def test_redact_variants(self):
        self.s.fill("{{secret:CARD_NUMBER}} {{secret:SHOP_PASSWORD}}")
        text = "fill('4242424242424242') textbox: 4242-4242-4242-4242 and s3cret-pass"
        red = self.s.redact(text)
        self.assertNotIn("4242", red)
        self.assertNotIn("s3cret", red)
        self.assertEqual(red.count("[secret:CARD_NUMBER]"), 2)

    def test_scrub_dir(self):
        self.s.fill("{{secret:CARD_NUMBER}} {{secret:SHOP_PASSWORD}}")
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "traces"))
        with open(os.path.join(d, "page-1.yml"), "w") as f:
            f.write('- textbox "Card": 4242 4242 4242 4242\n- textbox "Password": s3cret-pass\n')
        with open(os.path.join(d, "traces", "t.network"), "w") as f:
            f.write('{"postData":"card=4242424242424242&pw=s3cret-pass"}')
        with open(os.path.join(d, "shot.png"), "wb") as f:
            f.write(bytes([0x89, 0x50, 0xFF, 0xFE]))
        self.assertEqual(self.s.scrub_dir(d), 2)
        for name in ("page-1.yml", "traces/t.network"):
            text = open(os.path.join(d, name)).read()
            self.assertNotIn("4242", text)
            self.assertNotIn("s3cret", text)

    def test_unknown_secret(self):
        with self.assertRaises(Exception):
            self.s.fill("{{secret:NOPE}}")


class BitwardenSMTest(unittest.TestCase):
    """The bitwarden-sm provider against a stand-in `bws` that checks the token and prints a project's secrets."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        stub = os.path.join(self.dir, "bws")
        with open(stub, "w") as f:
            f.write('#!/bin/sh\n[ "$BWS_ACCESS_TOKEN" = "tok-123" ] || { echo "bad token" >&2; exit 1; }\n'
                    'echo \'[{"id":"1","key":"CARD_NUMBER","value":"4000 0000 0000 0002"},'
                    '{"id":"2","key":"SHOP_PASSWORD","value":"pw-from-bws"}]\'\n')
        os.chmod(stub, 0o755)
        self.token = os.path.join(self.dir, "token")
        with open(self.token, "w") as f:
            f.write("tok-123\n")
        self.path = os.environ["PATH"]
        os.environ["PATH"] = self.dir + os.pathsep + self.path

    def tearDown(self):
        os.environ["PATH"] = self.path

    def test_names_and_values(self):
        s = Secrets({"provider": "bitwarden-sm", "token_file": self.token})
        self.assertEqual(s.names(), ["CARD_NUMBER", "SHOP_PASSWORD"])
        self.assertEqual(s.fill("{{secret:SHOP_PASSWORD}}"), "pw-from-bws")
        self.assertEqual(s.redact("card 4000000000000002"), "card [secret:CARD_NUMBER]") if s.get("CARD_NUMBER") else None

    def test_bad_token(self):
        with open(self.token, "w") as f:
            f.write("wrong")
        with self.assertRaises(Exception):
            Secrets({"provider": "bitwarden-sm", "token_file": self.token}).get("CARD_NUMBER")


class BitwardenVaultTest(unittest.TestCase):
    """The bitwarden provider against a stand-in `bw` that requires a session key."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        item = ('{"id":"i1","folderId":"f1","name":"agent-card","login":null,"card":{"number":"4242424242424242","code":"123",'
                '"expMonth":"12","expYear":"2030","cardholderName":"Test User"},'
                '"fields":[{"name":"pin","value":"9876"}],"notes":"n"}')
        stub = os.path.join(self.dir, "bw")
        with open(stub, "w") as f:
            f.write('#!/bin/sh\n[ "$BW_SESSION" = "sess-1" ] || { echo "locked" >&2; exit 1; }\n'
                    f'case "$1 $2" in "sync"*) exit 0;; "get item") echo \'{item}\';; '
                    '"list folders") echo \'[{"id":"f1","name":"agents"},{"id":"f2","name":"personal"}]\';; '
                    f'"list items") echo \'[{item}]\';; *) exit 1;; esac\n')
        os.chmod(stub, 0o755)
        self.session = os.path.join(self.dir, "session")
        with open(self.session, "w") as f:
            f.write("sess-1")
        self.path = os.environ["PATH"]
        os.environ["PATH"] = self.dir + os.pathsep + self.path
        os.environ.pop("BW_SESSION", None)

    def tearDown(self):
        os.environ["PATH"] = self.path

    def secrets(self, session_file):
        return Secrets({"provider": "bitwarden", "session_file": session_file, "map": {
            "CARD_NUMBER": "Agent test card::number", "CARD_CVC": "Agent test card::code",
            "PIN": "Agent test card::pin"}})

    def test_fields(self):
        s = self.secrets(self.session)
        self.assertEqual(s.get("CARD_NUMBER"), "4242424242424242")
        self.assertEqual(s.get("CARD_CVC"), "123")
        self.assertEqual(s.get("PIN"), "9876")
        self.assertEqual(s.names(), ["CARD_CVC", "CARD_NUMBER", "PIN"])

    def test_folder_allowlist(self):
        ok = Secrets({"provider": "bitwarden", "session_file": self.session, "folders": ["agents"],
                      "map": {"N": "Agent test card::number"}})
        self.assertEqual(ok.get("N"), "4242424242424242")
        no = Secrets({"provider": "bitwarden", "session_file": self.session, "folders": ["personal"],
                      "map": {"N": "Agent test card::number"}})
        with self.assertRaises(Exception) as e:
            no.get("N")
        self.assertIn("allowed folder", str(e.exception))

    def test_discovery(self):
        s = Secrets({"provider": "bitwarden", "session_file": self.session, "folders": ["agents"]})
        names = s.names()
        for n in ("agent-card#number", "agent-card#code", "agent-card#cardholderName", "agent-card#pin"):
            self.assertIn(n, names)
        self.assertEqual(s.fill("{{secret:agent-card#number}}"), "4242424242424242")  # no map needed

    def test_locked(self):
        with self.assertRaises(Exception) as e:
            self.secrets(os.path.join(self.dir, "missing")).get("CARD_NUMBER")
        self.assertIn("locked", str(e.exception))


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.p = Policy({"default": "ask", "rules": [
            {"category": "shop", "pattern": "(?i)place order", "url": "trusted\\.example", "action": "allow"}]})

    def test_payment_asks(self):
        self.assertEqual(self.p.judge("Place order", "https://shop.example/checkout", "button").action, "ask")

    def test_own_rule_first(self):
        self.assertEqual(self.p.judge("Place order", "https://trusted.example/c", "button").action, "allow")

    def test_signature_only_on_wallet_pages(self):
        self.assertEqual(self.p.judge("Approve", "https://dapp.example/quest", "button").action, "allow")
        self.assertEqual(self.p.judge("Approve", "https://x.example/wallet/approve?req=1", "button").action, "ask")

    def test_harmless(self):
        self.assertEqual(self.p.judge("Add to cart", "https://shop.example", "button").action, "allow")
        self.assertEqual(self.p.judge("Checkout", "https://shop.example/cart", "button").action, "allow")

    def test_gated_tools(self):
        self.assertTrue(self.p.needs_check("browser_click", {"target": "e1"}))
        self.assertFalse(self.p.needs_check("browser_type", {"target": "e1", "text": "x"}))
        self.assertTrue(self.p.needs_check("browser_type", {"target": "e1", "text": "x", "submit": True}))
        self.assertTrue(self.p.needs_check("browser_press_key", {"key": "Enter"}))
        self.assertFalse(self.p.needs_check("browser_press_key", {"key": "Tab"}))


SNAP1 = """- main [ref=e1]:
  - button "Add to cart" [ref=e2]
  - link "Cart (0)" [ref=e3]
  - textbox "Search" [ref=e4]"""
SNAP2 = """- main [ref=e1]:
  - button "Add to cart" [ref=e2]
  - link "Cart (1)" [ref=e3]
  - textbox "Search" [ref=e4]
  - status [ref=e9]: Added 1 x Fern to the cart."""


class HistoryTest(unittest.TestCase):
    def test_mark_new(self):
        marked = history.mark_new(SNAP2, SNAP1)
        self.assertIn('link "Cart (1)" [ref=e3] [new]', marked)
        self.assertIn("status [ref=e9] [new]:", marked)
        self.assertNotIn('Add to cart" [ref=e2] [new]', marked)

    def test_new_page_has_no_marks(self):
        self.assertNotIn("[new]", history.mark_new("- heading \"Other\" [ref=e1]\n- link \"x\" [ref=e2]", SNAP1))

    def test_compact_keeps_latest(self):
        msgs = [{"role": "tool", "content": f"step {i}\n```yaml\n{SNAP1}\n```"} for i in range(5)]
        msgs.append({"role": "user", "content": [{"type": "text", "text": "img"}, {"type": "image_url"}]})
        history.compact(msgs, keep_snapshots=2, keep_images=0)
        self.assertEqual(sum("```yaml" in m["content"] for m in msgs[:5]), 2)
        self.assertIn("```yaml", msgs[4]["content"])
        self.assertIsInstance(msgs[5]["content"], str)


class BrowserHelpersTest(unittest.TestCase):
    def setUp(self):
        cfg = {"viewport": "1440x900"}
        self.b = Browser(cfg, tempfile.mkdtemp(), tempfile.mkdtemp())
        self.b.snapshot = SNAP2

    def test_lookup_ref(self):
        self.assertEqual(self.b.lookup_ref("e2"), ("button", "Add to cart"))
        self.assertEqual(self.b.lookup_ref("e9")[0], "status")

    def test_upload_allowlist(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "pic.png"), "w") as f:
            f.write("x")
        run = tempfile.mkdtemp()
        b = Browser({"viewport": "1440x900", "upload_dirs": [d]}, run, tempfile.mkdtemp())
        copy = os.path.realpath(os.path.join(run, "uploads", "pic.png"))
        self.assertEqual(b.resolve_upload("pic.png"), copy)
        self.assertTrue(os.path.isfile(copy))
        self.assertEqual(b.resolve_upload("some/where/pic.png"), copy)
        self.assertIsNone(b.resolve_upload(os.path.expanduser("~/.bashrc")))  # outside the allowed folders
        self.assertIsNone(b.resolve_upload("../../etc/passwd"))

    def test_coords(self):
        self.assertEqual(self.b.to_px(500, 500, "norm1000"), (720, 450))
        self.assertEqual(self.b.to_px(100, 200, "pixels"), (100, 200))


class HumanTest(unittest.TestCase):
    """The approval path must log with the agent's real logger signature (a crash here once stopped a payment)."""

    def test_auto_answer_logs(self):
        import asyncio
        from browser_agent.human import Human
        events = []

        def log(kind, **data):  # same signature as Agent.log
            events.append((kind, data))
        h = Human({"mode": "auto", "auto_answer": "approve"}, tempfile.mkdtemp(), log)
        ok, answer = asyncio.run(h.ask("approval", "Pay?", "page: x"))
        self.assertTrue(ok)
        self.assertEqual([k for k, _ in events], ["human_request", "human_answer"])
        ok, _ = asyncio.run(Human({"mode": "auto"}, tempfile.mkdtemp(), log).ask("approval", "Pay?"))
        self.assertFalse(ok)  # default auto answer is deny


class FinishTest(unittest.TestCase):
    def test_shapes(self):
        from browser_agent.agent import normalize_finish
        self.assertEqual(normalize_finish({"findings": ["Total wrong"]})["findings"][0]["title"], "Total wrong")
        self.assertEqual(normalize_finish({"findings": '[{"title": "A"}]'})["findings"][0]["title"], "A")
        self.assertEqual(normalize_finish({"findings": {"title": "B"}})["findings"][0]["title"], "B")
        self.assertEqual(normalize_finish({})["findings"], [])


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path


class LiepinReadonlyExtensionTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).parents[1]/"tools"/"liepin-readonly-extension"

    def test_manifest_only_allows_liepin_and_local_bridge(self):
        manifest=json.loads((self.root/"manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["host_permissions"],["https://*.liepin.com/*","http://127.0.0.1:19826/*"])

    def test_extension_has_read_actions_without_send_capabilities(self):
        script=(self.root/"background.js").read_text(encoding="utf-8")
        self.assertIn("extract_liepin_chat_overview",script)
        self.assertIn("extract_liepin_chat_history",script)
        for forbidden in ("send-message","sendMessageToRecruiter","batch-greet","send-resume","exchange-contact"):
            self.assertNotIn(forbidden,script)


if __name__=="__main__": unittest.main()

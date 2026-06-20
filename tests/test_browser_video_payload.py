import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


def load_browser_client_module():
    if "playwright" not in sys.modules:
        sys.modules["playwright"] = types.ModuleType("playwright")
    async_api = types.ModuleType("playwright.async_api")
    async_api.async_playwright = lambda: None
    async_api.BrowserContext = object
    async_api.Page = object
    sys.modules["playwright.async_api"] = async_api

    stealth_module = types.ModuleType("playwright_stealth")

    class Stealth:
        async def apply_stealth_async(self, _page):
            return None

    stealth_module.Stealth = Stealth
    sys.modules["playwright_stealth"] = stealth_module

    module_path = Path(__file__).resolve().parents[1] / "doubao2api" / "browser_client.py"
    spec = importlib.util.spec_from_file_location("browser_client", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


browser_client = load_browser_client_module()


class BrowserVideoPayloadTest(unittest.TestCase):
    def test_video_message_contains_all_reference_attachments(self):
        message = browser_client.BrowserClient._build_video_message(
            prompt="animate",
            ratio="16:9",
            image_keys=["tos-a", "tos-b"],
            model="seedance_v2.0",
            duration=5,
        )

        content = json.loads(message["content"])
        self.assertEqual(content["ref_image_key"], "tos-a")
        self.assertEqual(content["reference_image_keys"], ["tos-a", "tos-b"])
        self.assertEqual(
            message["attachments"],
            [
                {"type": "image", "key": "tos-a", "extra": {"refer_types": "overall"}},
                {"type": "image", "key": "tos-b", "extra": {"refer_types": "overall"}},
            ],
        )


if __name__ == "__main__":
    unittest.main()

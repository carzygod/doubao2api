import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "doubao2api" / "account_manager.py"
SPEC = importlib.util.spec_from_file_location("account_manager", MODULE_PATH)
account_manager = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(account_manager)
DoubaoAccountStore = account_manager.DoubaoAccountStore


class AccountQuotaTest(unittest.TestCase):
    def test_reserve_release_and_complete_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_image = os.environ.get("DOUBAO_IMAGE_24H_QUOTA")
            os.environ["DOUBAO_IMAGE_24H_QUOTA"] = "2"
            try:
                store = DoubaoAccountStore(str(Path(tmp) / "accounts.sqlite3"))
                account = store.ensure_default_account()

                self.assertTrue(store.has_quota(account, "image", 2))
                first = store.reserve_quota("default", "image", 1, request_id="image-1")
                snapshot = store.quota_snapshot(account, "image")
                self.assertEqual(snapshot["used"], 1)
                self.assertEqual(snapshot["remaining"], 1)

                store.release_quota(first)
                snapshot = store.quota_snapshot(account, "image")
                self.assertEqual(snapshot["used"], 0)
                self.assertEqual(snapshot["remaining"], 2)

                second = store.reserve_quota("default", "image", 2, request_id="image-2")
                store.complete_quota(second)
                self.assertFalse(store.has_quota(account, "image", 1))
                snapshot = store.quota_snapshot(account, "image")
                self.assertTrue(snapshot["exhausted"])
            finally:
                if old_image is None:
                    os.environ.pop("DOUBAO_IMAGE_24H_QUOTA", None)
                else:
                    os.environ["DOUBAO_IMAGE_24H_QUOTA"] = old_image

    def test_provider_video_quota_from_generation_message_limits_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_video = os.environ.get("DOUBAO_VIDEO_24H_QUOTA")
            os.environ["DOUBAO_VIDEO_24H_QUOTA"] = "10"
            try:
                store = DoubaoAccountStore(str(Path(tmp) / "accounts.sqlite3"))
                store.ensure_default_account()

                account = store.update_provider_quota_from_text(
                    "default",
                    "video",
                    "视频生成好后，我会及时通知你，今日剩余 6 个视频生成额度。",
                    units_completed=2,
                )
                snapshot = store.quota_snapshot(account, "video")

                self.assertEqual(snapshot["provider"]["remaining"], 6)
                self.assertEqual(snapshot["provider"]["limit"], 8)
                self.assertEqual(snapshot["effective_remaining"], 6)
                self.assertTrue(store.has_quota(account, "video", 6))
                self.assertFalse(store.has_quota(account, "video", 7))
            finally:
                if old_video is None:
                    os.environ.pop("DOUBAO_VIDEO_24H_QUOTA", None)
                else:
                    os.environ["DOUBAO_VIDEO_24H_QUOTA"] = old_video


if __name__ == "__main__":
    unittest.main()

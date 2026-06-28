import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "doubao2api" / "account_manager.py"
SPEC = importlib.util.spec_from_file_location("account_manager", MODULE_PATH)
account_manager = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(account_manager)
DoubaoAccountStore = account_manager.DoubaoAccountStore
UNAVAILABLE_ACCOUNT_STATUSES = account_manager.UNAVAILABLE_ACCOUNT_STATUSES


class AccountQuotaTest(unittest.TestCase):
    def test_task_failure_does_not_make_ready_account_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DoubaoAccountStore(str(Path(tmp) / "accounts.sqlite3"))
            store.ensure_default_account()
            store.update_account("default", status="ready", last_error="")

            store.record_task_failure("default", "single video task failed", keep_ready=True)
            account = store.get("default")

            self.assertEqual(account["status"], "ready")
            self.assertEqual(account["last_error"], "single video task failed")
            self.assertNotIn("error", UNAVAILABLE_ACCOUNT_STATUSES)
            self.assertIn("browser_error", UNAVAILABLE_ACCOUNT_STATUSES)

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

    def test_provider_zero_quota_uses_reset_at_instead_of_fake_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_video = os.environ.get("DOUBAO_VIDEO_24H_QUOTA")
            os.environ["DOUBAO_VIDEO_24H_QUOTA"] = "10"
            try:
                store = DoubaoAccountStore(str(Path(tmp) / "accounts.sqlite3"))
                store.ensure_default_account()

                account = store.update_provider_quota(
                    "default",
                    "video",
                    remaining=0,
                    source="quota_error",
                    message="今日视频生成免费次数已用完",
                )
                snapshot = store.quota_snapshot(account, "video")

                self.assertEqual(snapshot["provider"]["remaining"], 0)
                self.assertGreater(snapshot["provider"]["reset_at"], int(time.time()))
                self.assertFalse(store.has_quota(account, "video", 1))

                store.mark_quota_exhausted("default", "video", "今日视频生成免费次数已用完")
                self.assertEqual(store.quota_used("default", "video"), 0)
            finally:
                if old_video is None:
                    os.environ.pop("DOUBAO_VIDEO_24H_QUOTA", None)
                else:
                    os.environ["DOUBAO_VIDEO_24H_QUOTA"] = old_video

    def test_expired_provider_zero_quota_becomes_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_video = os.environ.get("DOUBAO_VIDEO_24H_QUOTA")
            os.environ["DOUBAO_VIDEO_24H_QUOTA"] = "10"
            try:
                store = DoubaoAccountStore(str(Path(tmp) / "accounts.sqlite3"))
                store.ensure_default_account()
                now = int(time.time())
                account = store.update_account(
                    "default",
                    quota_json=json.dumps(
                        {
                            "provider_quota": {
                                "video": {
                                    "remaining": 0,
                                    "synced_at": now,
                                    "reset_at": now - 1,
                                    "source": "quota_error",
                                }
                            }
                        }
                    ),
                )

                snapshot = store.quota_snapshot(account, "video")

                self.assertTrue(snapshot["provider"]["stale"])
                self.assertEqual(snapshot["effective_remaining"], 10)
                self.assertTrue(store.has_quota(account, "video", 1))
            finally:
                if old_video is None:
                    os.environ.pop("DOUBAO_VIDEO_24H_QUOTA", None)
                else:
                    os.environ["DOUBAO_VIDEO_24H_QUOTA"] = old_video


if __name__ == "__main__":
    unittest.main()

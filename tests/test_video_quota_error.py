import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "doubao2api" / "unified_server.py"


def load_quota_helper():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "is_quota_exhaustion_message"
    )
    module = ast.Module(
        body=[
            ast.Import(names=[ast.alias(name="re")]),
            helper,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(MODULE_PATH), "exec"), namespace)
    return namespace["is_quota_exhaustion_message"]


is_quota_exhaustion_message = load_quota_helper()


class VideoQuotaErrorTest(unittest.TestCase):
    def test_positive_remaining_quota_message_is_not_exhausted(self):
        self.assertFalse(
            is_quota_exhaustion_message(
                "本次使用 Seedance 2.0 全能视频模型生成，今日剩余 9 个视频生成额度。"
            )
        )

    def test_zero_or_insufficient_quota_message_is_exhausted(self):
        self.assertTrue(is_quota_exhaustion_message("今日剩余 0 个视频生成额度"))
        self.assertTrue(is_quota_exhaustion_message("视频生成额度不足"))
        self.assertTrue(is_quota_exhaustion_message("quota exceeded"))


if __name__ == "__main__":
    unittest.main()

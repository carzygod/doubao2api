import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "doubao2api" / "video_request.py"
SPEC = importlib.util.spec_from_file_location("video_request", MODULE_PATH)
video_request = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(video_request)
collect_video_reference_values = video_request.collect_video_reference_values
extract_video_prompt = video_request.extract_video_prompt


class VideoRequestParsingTest(unittest.TestCase):
    def test_collects_multi_reference_images_from_common_fields(self):
        body = {
            "prompt": "make a short video",
            "ref_image_key": "tos-key-1",
            "image_url": "https://example.com/one.png",
            "reference_images": [
                {"url": "https://example.com/two.png"},
                {"type": "image_url", "image_url": {"url": "https://example.com/three.png"}},
            ],
            "images": ["data:image/png;base64,AAAA", "tos-key-1"],
            "last_frame_image": {"file_id": "file-last-frame"},
        }

        self.assertEqual(
            collect_video_reference_values(body),
            [
                "tos-key-1",
                "https://example.com/one.png",
                "file-last-frame",
                "https://example.com/two.png",
                "https://example.com/three.png",
                "data:image/png;base64,AAAA",
            ],
        )

    def test_text_input_is_not_treated_as_image_reference(self):
        body = {"input": "a plain text prompt"}

        self.assertEqual(extract_video_prompt(body), "a plain text prompt")
        self.assertEqual(collect_video_reference_values(body), [])

    def test_openai_style_input_array_supports_text_and_images(self):
        body = {
            "input": [
                {"type": "input_text", "text": "animate these frames"},
                {"type": "input_image", "image_url": "https://example.com/a.png"},
                {"type": "image_url", "image_url": {"url": "https://example.com/b.png"}},
            ]
        }

        self.assertEqual(extract_video_prompt(body), "animate these frames")
        self.assertEqual(
            collect_video_reference_values(body),
            ["https://example.com/a.png", "https://example.com/b.png"],
        )

    def test_newapi_doubao_content_array_supports_text_and_images(self):
        body = {
            "model": "doubao-seedance-2-0-fast-260128",
            "content": [
                {"type": "image_url", "image_url": {"url": "https://example.com/start.png"}},
                {"type": "image_url", "image_url": {"url": "https://example.com/end.png"}},
                {"type": "text", "text": "make a transition video"},
            ],
            "duration": 5,
            "ratio": "16:9",
        }

        self.assertEqual(extract_video_prompt(body), "make a transition video")
        self.assertEqual(
            collect_video_reference_values(body),
            ["https://example.com/start.png", "https://example.com/end.png"],
        )

    def test_metadata_content_array_supports_newapi_passthrough(self):
        body = {
            "prompt": "",
            "metadata": {
                "content": [
                    {"type": "image_url", "image_url": {"url": "https://example.com/ref.png"}},
                    {"type": "text", "text": "metadata prompt"},
                ]
            },
        }

        self.assertEqual(extract_video_prompt(body), "metadata prompt")
        self.assertEqual(collect_video_reference_values(body), ["https://example.com/ref.png"])


if __name__ == "__main__":
    unittest.main()

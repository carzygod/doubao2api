from __future__ import annotations

from typing import Any, Dict, List


_TEXT_TYPES = {"text", "input_text"}

_SCALAR_IMAGE_KEYS = (
    "ref_image_key",
    "image_key",
    "file_id",
    "uri",
    "key",
    "url",
    "image_url",
    "image",
    "data",
    "base64",
    "b64_json",
)

_COLLECTION_IMAGE_KEYS = (
    "reference_images",
    "reference_image_urls",
    "reference_image_keys",
    "ref_image_keys",
    "image_urls",
    "images",
    "input_images",
    "input_image",
    "first_frame_images",
    "last_frame_images",
)

_REQUEST_IMAGE_KEYS = (
    "ref_image_key",
    "image_key",
    "file_id",
    "image_url",
    "image",
    "first_frame",
    "first_frame_image",
    "first_frame_url",
    "last_frame",
    "last_frame_image",
    "last_frame_url",
    *_COLLECTION_IMAGE_KEYS,
    "references",
    "content",
    "metadata",
)

_NESTED_IMAGE_KEYS = ("content", "input")


def extract_video_prompt(body: Dict[str, Any]) -> str:
    for key in ("prompt",):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("input", "content"):
        prompt = _extract_prompt_from_value(body.get(key))
        if prompt:
            return prompt

    metadata = body.get("metadata")
    if isinstance(metadata, dict):
        prompt = _extract_prompt_from_value(metadata.get("content") or metadata.get("input"))
        if prompt:
            return prompt
    return ""


def _extract_prompt_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if value.get("type") in _TEXT_TYPES and isinstance(value.get("text"), str):
            return value["text"].strip()
        for key in ("text", "prompt", "content"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
        return ""
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            text = _extract_prompt_from_value(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return ""


def collect_video_reference_values(body: Dict[str, Any]) -> List[str]:
    refs: List[str] = []
    for key in _REQUEST_IMAGE_KEYS:
        _append_image_refs(refs, body.get(key))
    input_value = body.get("input")
    if not isinstance(input_value, str):
        _append_image_refs(refs, input_value)
    return _dedupe(refs)


def _append_image_refs(refs: List[str], value: Any) -> None:
    if value in (None, ""):
        return
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            refs.append(stripped)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _append_image_refs(refs, item)
        return
    if not isinstance(value, dict):
        return

    value_type = str(value.get("type") or "").strip()
    if value_type in _TEXT_TYPES:
        return
    if value_type in {"image_url", "input_image", "reference_image", "file"}:
        image_url = value.get("image_url")
        if isinstance(image_url, dict):
            _append_image_refs(refs, image_url.get("url"))
        else:
            _append_image_refs(refs, image_url)
        _append_image_refs(refs, value.get("file_id"))
        _append_image_refs(refs, value.get("url"))
        _append_image_refs(refs, value.get("image"))
        return

    for key in _SCALAR_IMAGE_KEYS:
        _append_image_refs(refs, value.get(key))
    for key in _COLLECTION_IMAGE_KEYS:
        _append_image_refs(refs, value.get(key))
    for key in _NESTED_IMAGE_KEYS:
        nested = value.get(key)
        if not isinstance(nested, str):
            _append_image_refs(refs, nested)


def _dedupe(values: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

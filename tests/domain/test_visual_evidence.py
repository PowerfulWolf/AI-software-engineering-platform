"""Sealed image bounds, independent of provider or desktop availability."""

import base64
import hashlib
import struct
import zlib

import pytest

from ai_software_engineer.domain.visual_evidence import PngEvidence, PromptImage


def png_evidence() -> PngEvidence:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")
    return PngEvidence(
        data_base64=base64.b64encode(data).decode(),
        sha256=hashlib.sha256(data).hexdigest(),
        width=1,
        height=1,
    )


def prompt_image() -> PromptImage:
    return PromptImage(label="sealed fixture step initial", image=png_evidence())


def test_png_has_exact_digest_dimensions_and_complete_chunks() -> None:
    image = png_evidence()
    assert image.bytes().startswith(b"\x89PNG")
    assert image.data_url().endswith(image.data_base64)
    for update in (
        {"width": 2},
        {"height": 1801},
        {"sha256": "f" * 64},
        {"data_base64": "invalid"},
        {"data_base64": "a" * 540_001},
        {"media_type": "image/svg+xml"},
    ):
        with pytest.raises(ValueError):
            PngEvidence.model_validate({**image.to_wire(), **update})
    for data in (image.bytes()[:-1], image.bytes() + b"trailing", image.bytes()[:40] + b"changed"):
        with pytest.raises(ValueError):
            PngEvidence.model_validate(
                {
                    **image.to_wire(),
                    "data_base64": base64.b64encode(data).decode(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )

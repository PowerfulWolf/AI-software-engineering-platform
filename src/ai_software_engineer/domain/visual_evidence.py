"""Bounded, content-addressed PNG bytes; never a filesystem or remote-image authority."""

import base64
import hashlib
import struct
import zlib
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from ai_software_engineer.domain.model import DomainModel


class PngEvidence(DomainModel):
    media_type: Literal["image/png"] = "image/png"
    data_base64: Annotated[str, StringConstraints(min_length=1, max_length=540_000)] = Field(
        repr=False
    )
    sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    width: int = Field(gt=0, le=1800)
    height: int = Field(gt=0, le=1800)

    @model_validator(mode="after")
    def verified_png(self) -> Self:
        data = self.bytes()
        if len(data) > 400_000 or hashlib.sha256(data).hexdigest() != self.sha256:
            raise ValueError("PNG size or digest mismatch")
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("not PNG evidence")
        offset, image_data, ended = 8, False, False
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset : offset + 4], "big")
            kind = data[offset + 4 : offset + 8]
            end = offset + 12 + size
            if end > len(data):
                raise ValueError("truncated PNG evidence")
            body = data[offset + 8 : end - 4]
            if zlib.crc32(kind + body) != int.from_bytes(data[end - 4 : end], "big"):
                raise ValueError("PNG checksum mismatch")
            if offset == 8 and (
                kind != b"IHDR"
                or size != 13
                or struct.unpack(">II", body[:8]) != (self.width, self.height)
            ):
                raise ValueError("PNG dimensions mismatch")
            image_data |= kind == b"IDAT"
            offset = end
            if kind == b"IEND":
                ended = size == 0 and offset == len(data)
                break
        if not ended or not image_data:
            raise ValueError("incomplete PNG evidence")
        return self

    def bytes(self) -> bytes:
        return base64.b64decode(self.data_base64, validate=True)

    def data_url(self) -> str:
        return f"data:image/png;base64,{self.data_base64}"


class PromptImage(DomainModel):
    label: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    image: PngEvidence

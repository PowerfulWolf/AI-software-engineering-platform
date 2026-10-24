"""Body-free, bounded native pipe observations; never execution authority."""

from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, StrictBool, StrictInt, model_validator

from ai_software_engineer.domain.model import DomainModel

MAX_OBSERVATION_COUNT = (1 << 63) - 1
type ObservationCount = Annotated[StrictInt, Field(ge=0, le=MAX_OBSERVATION_COUNT)]
type ObservationSeconds = Annotated[FiniteFloat, Field(strict=True, ge=0, le=1_000_000_000)]


class NativeStreamObservation(DomainModel):
    raw_bytes: ObservationCount
    saturated: StrictBool
    first_byte_seconds: ObservationSeconds | None = None
    last_byte_seconds: ObservationSeconds | None = None
    eof: StrictBool

    @model_validator(mode="after")
    def byte_times(self) -> Self:
        first, last = self.first_byte_seconds, self.last_byte_seconds
        if (self.raw_bytes == 0) != (first is None and last is None):
            raise ValueError("native byte timing must match observed bytes")
        if (first is None) != (last is None) or (
            first is not None and last is not None and first > last
        ):
            raise ValueError("native byte timing order is invalid")
        if self.saturated and self.raw_bytes != MAX_OBSERVATION_COUNT:
            raise ValueError("native byte saturation must retain its bound")
        return self


class NativeEventObservation(DomainModel):
    observed_lines: ObservationCount
    thread_started: ObservationCount
    turn_started: ObservationCount
    turn_completed: ObservationCount
    turn_failed: ObservationCount
    item_started: ObservationCount
    item_completed: ObservationCount
    error: ObservationCount
    other: ObservationCount
    invalid_lines: ObservationCount
    saturated: StrictBool
    stream_valid: StrictBool
    stdout_eof: StrictBool
    partial_line: StrictBool

    @model_validator(mode="after")
    def trustworthy_completion(self) -> Self:
        if self.stream_valid and (not self.stdout_eof or self.partial_line or self.invalid_lines):
            raise ValueError("native event completion cannot hide invalid or partial input")
        counts = (
            self.thread_started,
            self.turn_started,
            self.turn_completed,
            self.turn_failed,
            self.item_started,
            self.item_completed,
            self.error,
            self.other,
        )
        if self.invalid_lines > 1:
            raise ValueError("invalid event count records only the first poisoned prefix")
        if not self.saturated and sum(counts) > self.observed_lines:
            raise ValueError("parsed native event counts exceed observed complete lines")
        if self.saturated and MAX_OBSERVATION_COUNT not in (self.observed_lines, *counts):
            raise ValueError("native event saturation must retain its bound")
        return self


class NativeOutputObservation(DomainModel):
    schema_version: Literal["v1"] = "v1"
    elapsed_seconds: ObservationSeconds
    stdout: NativeStreamObservation
    stderr: NativeStreamObservation
    events: NativeEventObservation | None = None

    @model_validator(mode="after")
    def complete_pipes(self) -> Self:
        if not self.stdout.eof or not self.stderr.eof:
            raise ValueError("native observation requires actual EOF on both original pipes")
        if self.events is not None and not self.events.stdout_eof:
            raise ValueError("native event observation requires original stdout EOF")
        for stream in (self.stdout, self.stderr):
            if (
                stream.last_byte_seconds is not None
                and stream.last_byte_seconds > self.elapsed_seconds
            ):
                raise ValueError("native byte timing exceeds the original runner elapsed time")
        return self

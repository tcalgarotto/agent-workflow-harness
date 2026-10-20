# SPDX-License-Identifier: Apache-2.0
"""Operator-selected immutable command/environment policy, never candidate input."""
from pydantic import Field, field_validator

from ..coordinator.models import Model
from .artifacts import canonical, sha

PYTHON_IMAGE = "python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83"


class Profile(Model):
    version: str = Field(pattern=r"^m2a$")
    image: str = Field(pattern=r"^python:3\.14-slim-bookworm@sha256:[0-9a-f]{64}$")
    worker_command: list[str] = Field(min_length=2, max_length=32)
    validator_command: list[str] = Field(min_length=2, max_length=32)
    timeout_seconds: int = Field(ge=1, le=120)
    memory_mb: int = Field(ge=64, le=512)
    pids: int = Field(ge=8, le=128)
    cpu_millis: int = Field(ge=250, le=1000)
    workspace_mb: int = Field(ge=16, le=64)
    output_bytes: int = Field(ge=1024, le=1_048_576)

    @field_validator("worker_command", "validator_command")
    @classmethod
    def bounded_command(cls, value):
        if (value[0] != "/usr/local/bin/python" or any("\x00" in v for v in value)
                or sum(len(v.encode()) for v in value) > 16384):
            raise ValueError("profile requires bounded absolute Python commands")
        return value

    def identity(self):
        return sha(canonical(self.model_dump()))

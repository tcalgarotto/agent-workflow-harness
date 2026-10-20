# SPDX-License-Identifier: Apache-2.0
"""Operator-configured project grants. Store token digests, never login caches."""
import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter, field_validator

from ..validation import _unique_pairs
from .models import Identifier, Model


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    projects: frozenset[str]
    capabilities: frozenset[str] = frozenset()


class Credential(Model):
    subject: Identifier
    role: Literal["controller", "worker", "reader", "supervisor", "integrator"]
    projects: list[Identifier] = Field(min_length=1, max_length=100)
    capabilities: list[Identifier] = Field(max_length=64)
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("projects", "capabilities")
    @classmethod
    def unique(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("duplicate grant")
        return values


class Auth:
    def __init__(self, credentials: list[Credential]):
        if not credentials or len({c.token_sha256 for c in credentials}) != len(credentials):
            raise ValueError("empty or duplicate credentials")
        if len({c.subject for c in credentials}) != len(credentials):
            raise ValueError("subjects must be unique; rotate by replacing the credential")
        self._credentials = tuple(credentials)

    @classmethod
    def from_file(cls, path: Path):
        # Keep operational secrets/configuration outside the repository.
        if path.stat().st_size > 1_000_000:
            raise ValueError("credential configuration too large")
        values = TypeAdapter(list[Credential]).validate_python(
            json.loads(path.read_text(), object_pairs_hook=_unique_pairs))
        return cls(values)

    def authenticate(self, token: str):
        digest = hashlib.sha256(token.encode()).hexdigest()
        match = None
        for credential in self._credentials:
            if hmac.compare_digest(credential.token_sha256, digest):
                match = credential
        if match is None:
            return None
        return Principal(match.subject, match.role, frozenset(match.projects),
                         frozenset(match.capabilities))

    def subject(self, subject):
        """Resolve an operator grant, never a role/capability claimed by a worker."""
        for credential in self._credentials:
            if credential.subject == subject:
                return Principal(credential.subject, credential.role, frozenset(credential.projects),
                                 frozenset(credential.capabilities))
        return None

# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from pydantic import Field, field_validator

from ..coordinator.models import Identifier, Model
from ..supervisor.artifacts import canonical, sha
from ..supervisor.profile import Profile
from ..validation import safe_path, contains

# These are always protected, even when omitted from operator additions.
PROTECTED = ("tests/", ".github/", "AGENTS.md", "CLAUDE.md", "pyproject.toml",
             "setup.py", "setup.cfg", "pytest.ini", "tox.ini", ".harness/")
CHECK_BASENAMES = {"conftest.py", "sitecustomize.py", "usercustomize.py"}


class Policy(Model):
    version: str = Field(pattern=r"^m2b$")
    project_id: Identifier
    repository: str = Field(min_length=1, max_length=2000)
    supervisor_state: str = Field(min_length=1, max_length=2000)
    branch: str = Field(pattern=r"^refs/heads/[a-zA-Z0-9][a-zA-Z0-9/_-]{0,127}$")
    profile: Profile
    protected_paths: list[str] = Field(max_length=128)

    @field_validator("repository", "supervisor_state")
    @classmethod
    def absolute(cls, value):
        if not Path(value).is_absolute() or str(Path(value)) != value or ".." in Path(value).parts:
            raise ValueError("operator path must be absolute and canonical")
        return value

    @field_validator("branch")
    @classmethod
    def branch_name(cls, value):
        if "//" in value or value.endswith("/"):
            raise ValueError("invalid branch")
        return value

    @field_validator("profile")
    @classmethod
    def isolated_validator(cls, value):
        if value.validator_command[:4] != ["/usr/local/bin/python", "-I", "-S", "-c"]:
            raise ValueError("M2b requires operator Python -I -S -c validator")
        return value

    @field_validator("protected_paths")
    @classmethod
    def paths(cls, values):
        if len(set(values)) != len(values) or not all(map(safe_path, values)):
            raise ValueError("protected paths must be unique canonical scopes")
        return values

    def identity(self):
        return sha(canonical(self.model_dump()))

    def protected(self, paths):
        return sorted(path for path in paths if
                      any(contains(scope, path) for scope in (*PROTECTED, *self.protected_paths))
                      or Path(path).name in CHECK_BASENAMES or path.endswith(".pth"))

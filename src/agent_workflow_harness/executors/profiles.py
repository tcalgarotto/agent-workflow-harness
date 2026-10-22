# SPDX-License-Identifier: Apache-2.0
"""Safe local profile checks; this module never starts an agent session."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from jsonschema import Draft202012Validator

from ..validation import read_json

_EXPECTED = {
    "codex-cli-1": "codex",
    "codex-cli-2": "codex",
    "codex-cli-3": "codex",
    "codex-cli-4": "codex",
    "antigravity": "antigravity",
    "claude-code": "claude",
}
_EXECUTABLES = {"codex": "codex", "antigravity": "agy", "claude": "claude"}
_VERSION = re.compile(r"(?<![0-9])(?:v)?([0-9]+\.[0-9]+\.[0-9]+)(?![0-9])")


def _schema():
    from importlib.resources import files
    return json.loads(files("agent_workflow_harness").joinpath(
        "schemas", "executor-profiles.schema.json"
    ).read_text(encoding="utf-8"))


def validate_profiles(document) -> list[str]:
    errors = [error.message for error in Draft202012Validator(_schema()).iter_errors(document)]
    if errors:
        return sorted(errors)
    profiles = {profile["profile_id"]: profile for profile in document["profiles"]}
    if set(profiles) != set(_EXPECTED):
        return ["profiles must define four Codex CLI, Antigravity, and Claude Code profile IDs"]
    for profile_id, provider in _EXPECTED.items():
        profile = profiles[profile_id]
        if profile["provider"] != provider:
            errors.append(f"{profile_id}: provider does not match its profile ID")
        if profile["executable"] != _EXECUTABLES[provider]:
            errors.append(f"{profile_id}: executable must be {_EXECUTABLES[provider]}")
        if provider == "codex" and not profile.get("auth_home_env"):
            errors.append(f"{profile_id}: auth_home_env is required for distinct CODEX_HOME")
    home_envs = [p.get("auth_home_env") for p in document["profiles"] if p["provider"] == "codex"]
    if len(home_envs) != len(set(home_envs)):
        errors.append("each Codex profile must reference a distinct auth_home_env")
    return sorted(errors)


def check_profiles(config_path: Path, *, environ=None, which=None, run=None):
    """Check six local CLI binaries and four distinct Codex home directories.

    No auth file is opened, no CLI login/session command is run, and no model
    request is sent. A successful check does not verify login status.
    """
    environ = os.environ if environ is None else environ
    which = shutil.which if which is None else which
    run = subprocess.run if run is None else run
    try:
        document = read_json(config_path)
    except (OSError, ValueError, UnicodeError):
        return {"valid": False, "profiles": [], "errors": ["cannot read valid profile JSON"]}
    errors = validate_profiles(document)
    if errors:
        return {"valid": False, "profiles": [], "errors": errors}

    found = []
    codex_homes = set()
    for profile in document["profiles"]:
        profile_id = profile["profile_id"]
        provider = profile["provider"]
        item = {"profile_id": profile_id, "provider": provider, "available": False}
        if provider == "codex":
            variable = profile["auth_home_env"]
            configured = environ.get(variable)
            if not configured:
                errors.append(f"{profile_id}: required local environment variable is unset")
            else:
                home = Path(configured).expanduser()
                if not home.is_absolute() or not home.is_dir():
                    errors.append(f"{profile_id}: configured CODEX_HOME is not an existing absolute directory")
                else:
                    resolved = str(home.resolve())
                    if resolved in codex_homes:
                        errors.append("Codex profiles must resolve to four distinct CODEX_HOME directories")
                    codex_homes.add(resolved)

        executable = which(profile["executable"])
        if executable is None:
            errors.append(f"{profile_id}: required CLI executable is unavailable")
            found.append(item)
            continue
        try:
            completed = run([executable, "--version"], capture_output=True, text=True,
                            timeout=5, check=False, env=dict(environ))
            version_text = (completed.stdout or "") + "\n" + (completed.stderr or "")
            match = _VERSION.search(version_text) if completed.returncode == 0 else None
            if not match:
                errors.append(f"{profile_id}: CLI version check failed or returned an unrecognized version")
            else:
                item.update({"available": True, "version": match.group(1)})
        except (OSError, subprocess.SubprocessError):
            errors.append(f"{profile_id}: CLI version check could not complete")
        found.append(item)
    return {"valid": not errors, "profiles": found, "errors": sorted(errors),
            "authentication_verified": False, "agent_started": False}

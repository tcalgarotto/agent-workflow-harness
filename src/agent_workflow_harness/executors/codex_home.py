# SPDX-License-Identifier: Apache-2.0
"""Prepare a private, per-run Codex home without copying OAuth material."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tomllib


class CodexHomeError(RuntimeError):
    """A local profile or run home cannot be safely bound."""


@dataclass(frozen=True)
class CodexHomeBinding:
    profile_id: str
    profile_home: Path
    run_home: Path
    runtime_home: str
    workspace: str
    permission_profile: str = "awh-task"


def prepare_codex_home(profile_id: str, profile_home: Path, state_root: Path,
                       run_id: str) -> CodexHomeBinding:
    """Create an isolated run CODEX_HOME with auth.json as a reference only.

    The run home and source profile must be private to the current user. The
    symlink is the only auth-related entry created; its target remains the
    operator-managed profile file. This function never opens that file.
    """
    if profile_id not in {f"codex-cli-{number}" for number in range(1, 5)}:
        raise CodexHomeError("unknown Codex profile")
    if not isinstance(run_id, str) or not run_id or len(run_id) > 128:
        raise CodexHomeError("invalid run identifier")
    source = Path(profile_home).expanduser()
    root = Path(state_root).expanduser()
    if not source.is_absolute() or not root.is_absolute():
        raise CodexHomeError("profile and state roots must be absolute")
    try:
        source = source.resolve(strict=True)
        root = root.resolve(strict=True)
    except OSError:
        raise CodexHomeError("profile or state root is unavailable") from None
    _private_owned_directory(source)
    _private_owned_directory(root)
    auth = source / "auth.json"
    try:
        metadata = auth.lstat()
    except OSError:
        raise CodexHomeError("selected profile auth reference is unavailable") from None
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077):
        raise CodexHomeError("selected profile auth reference has unsafe metadata")

    # Opaque path contains only a one-way run identifier digest.
    import hashlib
    run_digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:24]
    run_home = root / "codex-runs" / run_digest
    if run_home.exists() and not run_home.is_dir():
        raise CodexHomeError("run home path is not a directory")
    run_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(run_home, 0o700)
    _private_owned_directory(run_home)

    link = run_home / "auth.json"
    if link.is_symlink():
        try:
            existing = (run_home / os.readlink(link)).resolve(strict=True)
        except OSError:
            raise CodexHomeError("existing auth reference is broken") from None
        if existing != auth:
            raise CodexHomeError("existing run home references another profile")
    elif link.exists():
        raise CodexHomeError("run home auth path is not a symlink")
    else:
        try:
            link.symlink_to(auth)
        except OSError:
            raise CodexHomeError("cannot create private auth reference") from None

    runtime_home = "/run/awh/codex-home"
    workspace = "/workspace"
    config = _config_text(source, runtime_home, workspace)
    config_path = run_home / "config.toml"
    temporary = run_home / ".config.toml.tmp"
    try:
        temporary.write_text(config, encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(config_path)
        os.chmod(config_path, 0o600)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise CodexHomeError("cannot write isolated Codex run configuration") from None

    return CodexHomeBinding(profile_id, source, run_home, runtime_home, workspace)


def _private_owned_directory(path: Path):
    try:
        metadata = path.stat()
    except OSError:
        raise CodexHomeError("required private directory is unavailable") from None
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077):
        raise CodexHomeError("directory must be owned by this user and mode 0700")


def _toml_string(value: str) -> str:
    import json
    # JSON strings are a compatible subset of TOML basic strings.
    return json.dumps(value, ensure_ascii=False)


def _config_text(profile_home: Path, runtime_home: str, workspace: str) -> str:
    profile = _toml_string(str(profile_home))
    run_home = _toml_string(runtime_home)
    workspace = _toml_string(workspace)
    text = f'''default_permissions = "awh-task"
cli_auth_credentials_store = "file"
history = {{ persistence = "none" }}

[analytics]
enabled = false

[permissions.awh-task.filesystem]
":workspace_roots" = "write"
{run_home} = "deny"
{profile} = "deny"

[permissions.awh-task.network]
enabled = false

[projects.{workspace}]
trust_level = "untrusted"
'''
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise CodexHomeError("generated Codex permissions config is invalid") from None
    return text

# SPDX-License-Identifier: Apache-2.0
"""Bounded content snapshots and private authenticated artifacts; never extract tar."""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import uuid

from ..validation import safe_path

MAX_FILES = 512
MAX_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE = 16 * 1024 * 1024


class UnsafeExecution(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def file_name(name):
    return (safe_path(name) and not name.endswith("/") and len(name) <= 240
            and all(len(part) <= 120 for part in name.split("/")))


def check_tree(tree):
    if len(tree) > MAX_FILES or sum(len(data) for data in tree.values()) > MAX_BYTES:
        raise UnsafeExecution("snapshot_limit")
    if not all(file_name(name) and ".git" not in name.split("/") and isinstance(data, bytes)
               for name, data in tree.items()):
        raise UnsafeExecution("unsafe_snapshot_name")
    names = set(tree)
    for name in names:
        parts = name.split("/")
        if any("/".join(parts[:i]) in names for i in range(1, len(parts))):
            raise UnsafeExecution("file_directory_collision")


def encode_tree(tree):
    check_tree(tree)
    return canonical({name: base64.b64encode(data).decode() for name, data in tree.items()})


def decode_tree(raw):
    if len(raw) > MAX_ARCHIVE:
        raise UnsafeExecution("snapshot_limit")
    try:
        tree = {name: base64.b64decode(data, validate=True) for name, data in json.loads(raw).items()}
        check_tree(tree)
        return tree
    except (ValueError, TypeError, AttributeError) as error:
        raise UnsafeExecution("invalid_snapshot") from error


def snapshot(directory: Path):
    """Read via directory FDs/O_NOFOLLOW; exclude repository/auth/runtime metadata."""
    tree = {}
    excluded = {".git", ".venv", "venv", "__pycache__", "node_modules", ".ssh", ".aws", ".harness"}

    def walk(fd, prefix):
        for name in sorted(os.listdir(fd)):
            if name in excluded or name == ".env" or name.startswith(".env."):
                continue
            relative = prefix + name
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                if not file_name(relative) or relative.count("/") > 20:
                    raise UnsafeExecution("unsafe_directory")
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    walk(child, relative + "/")
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(file_fd, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                        raise UnsafeExecution("special_or_linked_file")
                    data = stream.read(MAX_BYTES + 1)
                tree[relative] = data
                check_tree(tree)
            else:
                raise UnsafeExecution("special_or_linked_file")

    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(fd, "")
    finally:
        os.close(fd)
    return tree


def from_archive(chunks):
    raw = bytearray()
    for chunk in chunks:
        if len(raw) + len(chunk) > MAX_ARCHIVE:
            raise UnsafeExecution("archive_limit")
        raw.extend(chunk)
    tree, total, seen = {}, 0, set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for index, member in enumerate(archive):
            if index > MAX_FILES * 4 or not (member.name == "workspace" or member.name.startswith("workspace/")):
                raise UnsafeExecution("archive_entry_limit_or_root")
            name = member.name.removeprefix("workspace").removeprefix("/")
            if not name and member.isdir():
                continue
            if member.isdir():
                if not file_name(name.rstrip("/")):
                    raise UnsafeExecution("unsafe_archive_directory")
                continue
            if not member.isfile() or not file_name(name) or name in seen:
                raise UnsafeExecution("unsafe_archive_member")
            seen.add(name)
            total += member.size
            if total > MAX_BYTES or len(seen) > MAX_FILES or member.size < 0:
                raise UnsafeExecution("snapshot_limit")
            tree[name] = archive.extractfile(member).read()
    check_tree(tree)
    return tree


class Artifacts:
    def __init__(self, root: Path):
        root = Path(root)
        if root.is_symlink():
            raise UnsafeExecution("symlink_state_root")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = root.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise UnsafeExecution("state_root_must_be_private_and_owned")
        self.root = root.resolve()
        for name in ["blobs", "operations", "locks", "cancel"]:
            (self.root / name).mkdir(mode=0o700, exist_ok=True)
        key = self.root / "receipt.key"
        if not key.exists():
            temporary = self.root / ("key-" + uuid.uuid4().hex)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(os.urandom(32))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, key)
            except FileExistsError:
                pass
            finally:
                temporary.unlink()
        self.key = key.read_bytes()
        if len(self.key) != 32 or key.is_symlink() or stat.S_IMODE(key.stat().st_mode) & 0o077:
            raise UnsafeExecution("invalid_receipt_key")

    def put(self, data):
        if len(data) > MAX_ARCHIVE:
            raise UnsafeExecution("artifact_limit")
        identity = sha(data)
        path = self.root / "blobs" / identity
        if not path.exists():
            temporary = path.with_name("tmp-" + uuid.uuid4().hex)
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o400)
            # Link publishes only a fully written artifact; no partial reads.
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
            finally:
                temporary.unlink()
        if self.get(identity) != data:
            raise UnsafeExecution("artifact_hash_mismatch")
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return identity

    def get(self, identity):
        if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise UnsafeExecution("invalid_artifact_id")
        path = self.root / "blobs" / identity
        if path.is_symlink() or path.stat().st_size > MAX_ARCHIVE:
            raise UnsafeExecution("unsafe_artifact")
        data = path.read_bytes()
        if sha(data) != identity:
            raise UnsafeExecution("artifact_hash_mismatch")
        return data

    def write_state(self, identity, state):
        self._operation_id(identity)
        path = self.root / "operations" / (identity + ".json")
        temporary = path.with_suffix(".tmp-" + uuid.uuid4().hex)
        with temporary.open("xb") as stream:
            stream.write(canonical(state))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def state(self, identity):
        self._operation_id(identity)
        return json.loads((self.root / "operations" / (identity + ".json")).read_bytes())

    def _operation_id(self, identity):
        if len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
            raise UnsafeExecution("invalid_execution_id")

    @contextmanager
    def lock(self, name):
        if not name.replace("-", "").isalnum() or len(name) > 100:
            raise UnsafeExecution("invalid_lock")
        with (self.root / "locks" / name).open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise UnsafeExecution("execution_or_slot_busy") from error
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def cancel(self, identity):
        self._operation_id(identity)
        (self.root / "cancel" / identity).touch(mode=0o600)

    def cancelled(self, identity):
        return (self.root / "cancel" / identity).exists()

    def receipt(self, payload):
        signature = hmac.new(self.key, canonical(payload), "sha256").hexdigest()
        return self.put(canonical({"payload": payload, "hmac_sha256": signature}))

    def verify(self, receipt_id, candidate_id, profile_hash):
        signed = json.loads(self.get(receipt_id))
        expected = hmac.new(self.key, canonical(signed["payload"]), "sha256").hexdigest()
        if not hmac.compare_digest(expected, signed["hmac_sha256"]):
            raise UnsafeExecution("receipt_authentication_failed")
        payload = signed["payload"]
        if payload["candidate_hash"] != candidate_id or payload["profile_hash"] != profile_hash:
            raise UnsafeExecution("receipt_input_mismatch")
        decode_tree(self.get(candidate_id))
        return payload

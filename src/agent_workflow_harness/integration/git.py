# SPDX-License-Identifier: Apache-2.0
"""Git plumbing only: no checkout, hooks, filters, user config or network."""
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

from ..supervisor.artifacts import MAX_ARCHIVE, MAX_BYTES, MAX_FILES, UnsafeExecution, check_tree


class Git:
    def __init__(self, repository: str, branch: str):
        path = Path(repository)
        info = path.stat()
        if (path.is_symlink() or path.resolve() != path or not path.is_dir()
                or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise UnsafeExecution("git_repository_must_be_private_owned_bare_directory")
        self.repository, self.branch = repository, branch
        self.executable = shutil.which("git")
        if not self.executable:
            raise UnsafeExecution("git_unavailable")
        version = re.search(rb"git version (\d+)\.(\d+)", self.call("version"))
        if version is None or tuple(map(int, version.groups())) < (2, 43):
            raise UnsafeExecution("git_2_43_or_newer_required")
        if self.call("rev-parse", "--is-bare-repository").strip() != b"true":
            raise UnsafeExecution("bare_repository_required")
        self.head()
        code, _ = self.call("symbolic-ref", "-q", branch, allow_failure=True)
        if code != 1:
            raise UnsafeExecution("accepted_branch_must_be_a_direct_ref")

    def call(self, *args, data=None, allow_failure=False):
        # Local repository configuration is operator-owned. Disable mechanisms
        # which can execute programs or substitute objects even in plumbing.
        env = {"PATH": os.defpath, "HOME": "/nonexistent", "LC_ALL": "C",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1",
               "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "",
               "GIT_AUTHOR_NAME": "AWH integration", "GIT_AUTHOR_EMAIL": "awh@localhost",
               "GIT_COMMITTER_NAME": "AWH integration", "GIT_COMMITTER_EMAIL": "awh@localhost"}
        command = [self.executable, "--no-optional-locks", "--git-dir", self.repository,
                   "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                   "-c", "core.attributesFile=/dev/null", "-c", "commit.gpgSign=false",
                   "-c", "core.fsync=all", "-c", "core.fsyncMethod=fsync",
                   "-c", "maintenance.auto=false", "-c", "gc.auto=0", *args]
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run(command, input=data, stdout=output, stderr=subprocess.DEVNULL,
                                        env=env, timeout=10, check=False)
            except subprocess.TimeoutExpired as error:
                raise UnsafeExecution("git_timeout_recover_before_retry") from error
            if result.returncode and not allow_failure:
                raise UnsafeExecution("git_operation_failed")
            if output.tell() > MAX_ARCHIVE:
                raise UnsafeExecution("git_output_limit")
            output.seek(0)
            value = output.read()
        return (result.returncode, value) if allow_failure else value

    @staticmethod
    def oid(value):
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
            raise UnsafeExecution("full_git_object_id_required")
        return value

    def ref(self, name):
        code, value = self.call("rev-parse", "--verify", "--quiet", name, allow_failure=True)
        if code == 1:
            return None
        if code:
            raise UnsafeExecution("git_ref_read_failed")
        return self.oid(value.decode().strip())

    def head(self):
        result = self.ref(self.branch)
        if result is None:
            raise UnsafeExecution("accepted_branch_missing")
        return result

    def ancestor(self, older, newer):
        code, _ = self.call("merge-base", "--is-ancestor", self.oid(older), self.oid(newer),
                            allow_failure=True)
        if code not in (0, 1):
            raise UnsafeExecution("invalid_git_ancestry")
        return code == 0

    def tree(self, revision):
        self.oid(revision)
        if self.call("cat-file", "-t", revision).strip() != b"commit":
            raise UnsafeExecution("git_commit_required")
        entries = self.call("ls-tree", "-rzl", "--full-tree", revision).split(b"\0")
        tree, modes, total = {}, {}, 0
        for entry in filter(None, entries):
            meta, raw_name = entry.split(b"\t", 1)
            mode, kind, oid, size = meta.split()
            total += int(size) if size != b"-" else MAX_BYTES + 1
            if mode not in (b"100644", b"100755") or kind != b"blob":
                raise UnsafeExecution("git_only_regular_files_supported")
            if total > MAX_BYTES or len(tree) >= MAX_FILES:
                raise UnsafeExecution("snapshot_limit")
            name = raw_name.decode("utf-8", errors="strict")
            tree[name] = self.call("cat-file", "blob", oid.decode())
            modes[name] = mode.decode()
        check_tree(tree)
        return tree, modes

    def commit(self, tree, modes, parent, identity, guard=None):
        check_tree(tree)
        def check():
            if guard is not None and not guard():
                raise UnsafeExecution("git_preparation_authority_lost")

        root = {}
        for name, content in sorted(tree.items()):
            check()
            node = root
            parts = name.split("/")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            blob = self.call("hash-object", "-w", "--stdin", data=content).strip().decode()
            node[parts[-1]] = (modes.get(name, "100644"), blob)

        def make(node):
            check()
            entries = []
            for name, value in sorted(node.items()):
                if isinstance(value, dict):
                    mode, kind, oid = "040000", "tree", make(value)
                else:
                    mode, oid = value
                    kind = "blob"
                entries.append(f"{mode} {kind} {oid}\t{name}".encode() + b"\0")
            return self.call("mktree", "-z", data=b"".join(entries)).strip().decode()

        tree_id = make(root)
        check()
        return self.call("commit-tree", tree_id, "-p", self.oid(parent),
                         data=f"AWH integration {identity}\n".encode()).strip().decode()

    def marker(self, project, identity):
        # Both identifiers are validated by the gateway before reaching plumbing.
        return f"refs/awh/integrations/{project}/{identity}"

    def integrate(self, project, identity, expected, commit):
        marker = self.marker(project, identity)
        transaction = (f"start\nupdate {self.branch} {self.oid(commit)} {self.oid(expected)}\n"
                       f"create {marker} {commit}\nprepare\ncommit\n").encode()
        self.call("update-ref", "--no-deref", "--stdin", data=transaction)

    def effect(self, project, identity, expected, commit):
        marker = self.ref(self.marker(project, identity))
        accepted = self.ancestor(commit, self.head())
        if marker is None and not accepted:
            return False
        if (marker is not None and marker != commit) or not accepted:
            raise UnsafeExecution("git_effect_inconsistent_quarantine")
        # Files-backend ref transactions serialize competing writers but are
        # not a distributed/durable atomic transaction with SQL (nor a guarantee
        # against a host crash between individual ref renames). The planned
        # immutable commit in accepted ancestry also proves the effect when its
        # auxiliary marker was not published before a crash.
        parents = self.call("rev-list", "--parents", "-n", "1", self.oid(commit)).decode().split()
        if parents != [commit, expected]:
            raise UnsafeExecution("git_effect_parent_mismatch")
        return True


def combine(base, candidate, current):
    """File-level optimistic merge. Never guess a textual conflict resolution."""
    changed = sorted(name for name in set(base) | set(candidate) if base.get(name) != candidate.get(name))
    result = dict(current)
    for name in changed:
        if current.get(name) not in (base.get(name), candidate.get(name)):
            raise UnsafeExecution("candidate_conflicts_with_accepted_base")
        if name in candidate:
            result[name] = candidate[name]
        else:
            result.pop(name, None)
    check_tree(result)  # Includes add/delete and file/directory conflicts.
    return result, changed

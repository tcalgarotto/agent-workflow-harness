# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path
import tempfile
import unittest

from agent_workflow_harness.executors.codex_home import (
    CodexHomeError,
    prepare_codex_home,
)


class CodexHomeTest(unittest.TestCase):
    def test_creates_private_run_home_and_references_only_selected_oauth_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "codex-cli-1"
            state = root / "state"
            profile.mkdir(mode=0o700)
            state.mkdir(mode=0o700)
            auth = profile / "auth.json"
            auth.write_text('{"token":"must-not-be-copied"}', encoding="utf-8")
            auth.chmod(0o600)

            binding = prepare_codex_home("codex-cli-1", profile, state, "run-1")
            run_auth = binding.run_home / "auth.json"
            self.assertTrue(run_auth.is_symlink())
            self.assertEqual(auth, run_auth.resolve())
            self.assertEqual(0o700, os.stat(binding.run_home).st_mode & 0o777)
            config_path = binding.run_home / "config.toml"
            self.assertEqual(0o600, os.stat(config_path).st_mode & 0o777)
            config = config_path.read_text(encoding="utf-8")
            self.assertIn('default_permissions = "awh-task"', config)
            self.assertIn('":workspace_roots" = "write"', config)
            self.assertIn('enabled = false', config)
            self.assertNotIn("must-not-be-copied", config)
            self.assertEqual("/run/awh/codex-home", binding.runtime_home)
            self.assertEqual("/workspace", binding.workspace)

    def test_rejects_unsafe_profile_and_existing_auth_file_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "profile"
            state = root / "state"
            profile.mkdir(mode=0o700)
            state.mkdir(mode=0o700)
            (profile / "auth.json").write_text("{}", encoding="utf-8")
            (profile / "auth.json").chmod(0o600)
            with self.assertRaises(CodexHomeError):
                prepare_codex_home("claude-cli", profile, state, "run-1")
            run_home = state / "codex-runs" / __import__("hashlib").sha256(
                b"run-1").hexdigest()[:24]
            run_home.mkdir(mode=0o700, parents=True)
            (run_home / "auth.json").write_text("not a reference", encoding="utf-8")
            with self.assertRaises(CodexHomeError):
                prepare_codex_home("codex-cli-1", profile, state, "run-1")


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
import copy
import json
from pathlib import Path
import tempfile
import unittest

from agent_workflow_harness.executors.profiles import check_profiles, validate_profiles
from agent_workflow_harness.validation import read_json

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "executors" / "profiles.example.json"


class ExecutorProfilesTest(unittest.TestCase):
    def setUp(self):
        self.document = read_json(EXAMPLE)

    def test_example_describes_six_provider_profiles(self):
        self.assertEqual([], validate_profiles(self.document))

    def test_rejects_duplicate_codex_home_reference(self):
        doc = copy.deepcopy(self.document)
        doc["profiles"][1]["auth_home_env"] = doc["profiles"][0]["auth_home_env"]
        self.assertTrue(any("distinct auth_home_env" in e for e in validate_profiles(doc)))

    def test_rejects_provider_mismatch(self):
        doc = copy.deepcopy(self.document)
        doc["profiles"][4]["provider"] = "claude"
        self.assertTrue(any("provider does not match" in e for e in validate_profiles(doc)))

    def test_preflight_checks_only_cli_version_and_hides_home_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            homes = [root / f"codex-home-{i}" for i in range(4)]
            for home in homes:
                home.mkdir()
            env = {f"AWH_CODEX_HOME_{index}": str(home)
                   for index, home in enumerate(homes, 1)}
            calls = []

            def run(argv, **kwargs):
                calls.append(argv)
                self.assertEqual(["--version"], argv[1:])
                self.assertEqual(5, kwargs["timeout"])
                return type("Result", (), {"returncode": 0, "stdout": "codex 1.2.3", "stderr": ""})()

            config = root / "profiles.json"
            config.write_text(json.dumps(self.document), encoding="utf-8")
            result = check_profiles(config, environ=env,
                                    which=lambda command: f"/mock/{command}", run=run)
            self.assertTrue(result["valid"], result["errors"])
            self.assertFalse(result["authentication_verified"])
            self.assertFalse(result["agent_started"])
            self.assertEqual(6, len(calls))
            self.assertNotIn(str(root), json.dumps(result))

    def test_preflight_rejects_same_codex_home(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            env = {f"AWH_CODEX_HOME_{index}": str(home) for index in range(1, 5)}
            config = home / "profiles.json"
            config.write_text(json.dumps(self.document), encoding="utf-8")
            result = check_profiles(config, environ=env,
                                    which=lambda command: f"/mock/{command}",
                                    run=lambda *args, **kwargs: type("Result", (), {
                                        "returncode": 0, "stdout": "1.2.3", "stderr": ""
                                    })())
            self.assertFalse(result["valid"])
            self.assertTrue(any("four distinct CODEX_HOME" in e for e in result["errors"]))

    def test_preflight_reports_missing_cli_without_starting_any_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            homes = [root / f"home-{i}" for i in range(4)]
            for home in homes:
                home.mkdir()
            env = {f"AWH_CODEX_HOME_{index}": str(home)
                   for index, home in enumerate(homes, 1)}
            config = root / "profiles.json"
            config.write_text(json.dumps(self.document), encoding="utf-8")
            result = check_profiles(config, environ=env,
                                    which=lambda command: None if command == "agy" else f"/mock/{command}",
                                    run=lambda *args, **kwargs: type("Result", (), {
                                        "returncode": 0, "stdout": "1.2.3", "stderr": ""
                                    })())
            self.assertFalse(result["valid"])
            self.assertTrue(any("executable is unavailable" in e for e in result["errors"]))

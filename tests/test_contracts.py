# SPDX-License-Identifier: Apache-2.0
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator
from agent_workflow_harness.validation import (
    KINDS, MAX_DOCUMENT_BYTES, read_json, schema_for, validate_bundle, validate_document,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "minimal"


class ContractsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.documents = {kind: read_json(EXAMPLES / f"{kind}.json") for kind in KINDS}

    def check(self):
        for kind, document in self.documents.items():
            (self.directory / f"{kind}.json").write_text(json.dumps(document))
        return validate_bundle(self.directory)

    def reject(self, needle):
        self.assertTrue(any(needle in error for error in self.check()), needle)

    def test_schemas_and_examples_are_valid(self):
        for kind in KINDS:
            Draft202012Validator.check_schema(schema_for(kind))
            self.assertEqual([], validate_document(kind, self.documents[kind]))
        self.assertEqual([], self.check())

    def test_cross_project_reference_is_rejected(self):
        self.documents["task"]["project_id"] = "another-project"
        self.reject("project_id differs")

    def test_unknown_fields_are_rejected(self):
        self.documents["task"]["ignore_policy"] = True
        self.reject("Additional properties")

    def test_missing_acceptance_criteria_are_rejected(self):
        self.documents["task"]["acceptance_criteria"] = []
        self.reject("acceptance_criteria")

    def test_unknown_adapter_is_rejected(self):
        self.documents["task"]["adapter_id"] = "other-adapter"
        self.reject("adapter_id does not reference")

    def test_unknown_policy_is_rejected(self):
        self.documents["project"]["policy_id"] = "other-policy"
        self.reject("policy_id does not reference")

    def test_unknown_workflow_is_rejected(self):
        self.documents["task"]["workflow_id"] = "other-workflow"
        self.reject("workflow_id does not reference")

    def test_project_cannot_raise_concurrency_limit(self):
        self.documents["project"]["max_active_runs"] = 4
        self.reject("max_active_runs exceeds")

    def test_task_cannot_raise_tool_budget(self):
        self.documents["task"]["max_tool_calls"] = 41
        self.reject("max_tool_calls exceeds")

    def test_inadequate_enforcement_is_rejected(self):
        self.documents["policy"]["minimum_enforcement"] = "execution"
        self.reject("below the effective minimum")

    def test_missing_capability_is_rejected(self):
        self.documents["task"]["required_capabilities"].append("confirmed-cancellation")
        self.reject("missing task required_capabilities")

    def test_task_cannot_add_policy_denied_tool(self):
        self.documents["task"]["tools"].append("deploy-production")
        self.reject("tools exceed policy")

    def test_adapter_must_declare_requested_tools(self):
        self.documents["adapter"]["tools"].remove("run-tests")
        self.reject("missing task tools")

    def test_scope_boundary_is_not_a_string_prefix(self):
        self.documents["task"]["allowed_paths"] = ["src-other/file.py"]
        self.reject("outside policy")

    def test_nested_scope_is_allowed(self):
        self.documents["task"]["allowed_paths"] = ["src/parsers/value.py"]
        self.assertEqual([], self.check())

    def test_noncanonical_paths_are_rejected(self):
        for path in ["../outside", "/etc/config", "C:/config", "src\\file", "src/../secret", "src//x", "src/./x", "src/*", "src/x\n"]:
            with self.subTest(path=path):
                self.documents["task"]["allowed_paths"] = [path]
                self.reject("unsafe or noncanonical")

    def test_ancestor_of_protected_path_is_rejected(self):
        self.documents["policy"]["protected_paths"].append("src/private/")
        self.documents["task"]["allowed_paths"] = ["src/"]
        self.reject("overlaps a protected path")

    def test_descendant_of_protected_path_is_rejected(self):
        self.documents["policy"]["protected_paths"].append("src/private/")
        self.documents["task"]["allowed_paths"] = ["src/private/key.py"]
        self.reject("overlaps a protected path")

    def test_cycle_is_rejected(self):
        self.documents["workflow"]["nodes"][0]["depends_on"] = ["accept"]
        self.reject("dependency cycle")

    def test_unknown_node_is_rejected(self):
        self.documents["workflow"]["nodes"][0]["depends_on"] = ["missing"]
        self.reject("unknown dependency")

    def test_duplicate_node_id_is_rejected(self):
        extra = copy.deepcopy(self.documents["workflow"]["nodes"][0])
        extra["kind"] = "implement"
        self.documents["workflow"]["nodes"].append(extra)
        self.reject("duplicate node IDs")

    def test_integration_cannot_bypass_review(self):
        self.documents["workflow"]["nodes"][-1]["depends_on"] = ["checks"]
        self.reject("upstream gate 'review'")

    def test_checks_before_implementation_are_rejected(self):
        nodes = self.documents["workflow"]["nodes"]
        nodes[2]["depends_on"] = ["prepare"]
        nodes[-1]["depends_on"] = ["assessment", "change"]
        self.reject("validate must follow all implement")

    def test_disconnected_implementation_is_rejected(self):
        self.documents["workflow"]["nodes"].append({"id":"late-change","kind":"implement","depends_on":[]})
        self.reject("outside the integration dependency chain")

    def test_integrate_node_is_required(self):
        self.documents["workflow"]["nodes"].pop()
        self.reject("exactly one integrate")

    def test_missing_bundle_file_fails_closed(self):
        self.assertTrue(validate_bundle(self.directory))

    def test_duplicate_json_keys_are_rejected(self):
        p = self.directory / "duplicate.json"
        p.write_text('{"project_id":"first","project_id":"second"}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            read_json(p)

    def test_large_documents_are_rejected(self):
        p = self.directory / "large.json"
        p.write_bytes(b" " * (MAX_DOCUMENT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            read_json(p)

    def test_nonfinite_json_is_rejected(self):
        p = self.directory / "nonfinite.json"
        p.write_text('{"value": NaN}')
        with self.assertRaisesRegex(ValueError, "non-finite"):
            read_json(p)

    def test_cli_reports_valid_bundle(self):
        result = subprocess.run([sys.executable,"-m","agent_workflow_harness","check",str(EXAMPLES)], capture_output=True,text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_cli_invalid_bundle_exits_nonzero(self):
        result = subprocess.run([sys.executable,"-m","agent_workflow_harness","check",str(self.directory)], capture_output=True,text=True)
        self.assertEqual(1, result.returncode)
        self.assertFalse(json.loads(result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()

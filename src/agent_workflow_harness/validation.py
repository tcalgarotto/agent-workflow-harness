# SPDX-License-Identifier: Apache-2.0
"""Schema and cross-contract checks for local workflow bundles.

Validation inspects declarations. It does not verify adapter capabilities, enforce
filesystem permissions, acquire leases, execute tools, or authorize an integration.
"""
from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path

from jsonschema import Draft202012Validator

KINDS = ("project", "policy", "adapter", "task", "workflow")
LEVELS = {"advised": 0, "delivery": 1, "execution": 2}
MAX_DOCUMENT_BYTES = 1_000_000


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("document exceeds 1 MB limit")
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON value: {value}")
        ),
    )


def schema_for(kind: str):
    if kind not in KINDS:
        raise ValueError(f"unknown document kind: {kind}")
    resource = files("agent_workflow_harness").joinpath("schemas", f"{kind}.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_document(kind: str, document) -> list[str]:
    validator = Draft202012Validator(schema_for(kind))
    result = []
    for error in validator.iter_errors(document):
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        result.append(f"{kind}:{location}: {error.message}")
    return sorted(result)


def safe_path(path: str) -> bool:
    if not path or path.startswith("/") or "\\" in path or ":" in path:
        return False
    if any(char in path for char in "*?[]{}"):
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        return False
    parts = path.removesuffix("/").split("/")
    return all(part not in ("", ".", "..") for part in parts)


def contains(parent: str, child: str) -> bool:
    return parent == child or (parent.endswith("/") and child.startswith(parent))


def overlaps(first: str, second: str) -> bool:
    return contains(first, second) or contains(second, first)


def validate_bundle(directory: Path) -> list[str]:
    documents = {}
    errors = []
    for kind in KINDS:
        try:
            document = read_json(directory / f"{kind}.json")
        except (OSError, ValueError, UnicodeError) as error:
            errors.append(f"{kind}: {error}")
            continue
        found = validate_document(kind, document)
        errors.extend(found)
        if not found:
            documents[kind] = document
    if len(documents) != len(KINDS):
        return sorted(errors)

    project, policy, adapter, task, workflow = (documents[kind] for kind in KINDS)
    project_id = project["project_id"]
    for kind, document in documents.items():
        if kind != "project" and document["project_id"] != project_id:
            errors.append(f"{kind}: project_id differs from project")
    for field, target, key in [
        ("policy_id", policy, "policy_id"),
        ("workflow_id", workflow, "workflow_id"),
    ]:
        if project[field] != target[key]:
            errors.append(f"project: {field} does not reference the supplied {key}")
    if task["workflow_id"] != workflow["workflow_id"]:
        errors.append("task: workflow_id does not reference the supplied workflow")
    if task["adapter_id"] != adapter["adapter_id"]:
        errors.append("task: adapter_id does not reference the supplied adapter")
    if project["max_active_runs"] > policy["max_active_runs"]:
        errors.append("project: max_active_runs exceeds policy")
    minimum = max(LEVELS[project["minimum_enforcement"]], LEVELS[policy["minimum_enforcement"]])
    if LEVELS[adapter["enforcement_level"]] < minimum:
        errors.append("adapter: enforcement_level is below the effective minimum")
    if not set(task["required_capabilities"]) <= set(adapter["capabilities"]):
        errors.append("adapter: missing task required_capabilities")
    tools = set(task["tools"])
    if not tools <= set(policy["allowed_tools"]):
        errors.append("task: tools exceed policy allowed_tools")
    if not tools <= set(adapter["tools"]):
        errors.append("adapter: missing task tools")
    if task["max_tool_calls"] > policy["max_tool_calls"]:
        errors.append("task: max_tool_calls exceeds policy")

    path_sets = [
        ("policy.writable_paths", policy["writable_paths"]),
        ("policy.protected_paths", policy["protected_paths"]),
        ("task.allowed_paths", task["allowed_paths"]),
    ]
    unsafe = False
    for label, paths in path_sets:
        for path in paths:
            if not safe_path(path):
                errors.append(f"{label}: unsafe or noncanonical path {path!r}")
                unsafe = True
    if not unsafe:
        for path in task["allowed_paths"]:
            if not any(contains(parent, path) for parent in policy["writable_paths"]):
                errors.append(f"task: path {path!r} is outside policy writable_paths")
            if any(overlaps(path, protected) for protected in policy["protected_paths"]):
                errors.append(f"task: path {path!r} overlaps a protected path")

    nodes = workflow["nodes"]
    node_ids = [node["id"] for node in nodes]
    if len(node_ids) != len(set(node_ids)):
        errors.append("workflow: duplicate node IDs")
        return sorted(errors)
    by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        for dependency in node["depends_on"]:
            if dependency not in by_id:
                errors.append(f"workflow: unknown dependency {dependency!r}")
    if errors:
        return sorted(errors)
    remaining = set(by_id)
    resolved = set()
    ancestors = {}
    while remaining:
        eligible = sorted(
            node_id for node_id in remaining
            if set(by_id[node_id]["depends_on"]) <= resolved
        )
        if not eligible:
            errors.append("workflow: dependency cycle")
            return sorted(errors)
        for node_id in eligible:
            dependencies = by_id[node_id]["depends_on"]
            ancestors[node_id] = set(dependencies)
            for dependency in dependencies:
                ancestors[node_id].update(ancestors[dependency])
            resolved.add(node_id)
            remaining.remove(node_id)
    integrations = [node for node in nodes if node["kind"] == "integrate"]
    if len(integrations) != 1:
        errors.append("workflow: exactly one integrate node is required")
    else:
        integration = integrations[0]
        gate_kinds = {by_id[node_id]["kind"] for node_id in ancestors[integration["id"]]}
        for required in policy["required_gates"]:
            if required not in gate_kinds:
                errors.append(f"workflow: integrate lacks required upstream gate {required!r}")
        # Every change-producing node must precede every required verification gate.
        implementations = {node["id"] for node in nodes if node["kind"] == "implement"}
        if not implementations:
            errors.append("workflow: an implement node is required")
        if not implementations <= ancestors[integration["id"]]:
            errors.append("workflow: an implement node is outside the integration dependency chain")
        for gate_kind in policy["required_gates"]:
            gates = [
                node for node in nodes
                if node["kind"] == gate_kind and node["id"] in ancestors[integration["id"]]
            ]
            if gates and not any(implementations <= ancestors[node["id"]] for node in gates):
                errors.append(f"workflow: {gate_kind} must follow all implement nodes")
    return sorted(errors)

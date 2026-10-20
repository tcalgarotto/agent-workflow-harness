# SPDX-License-Identifier: Apache-2.0
"""Durable local execution journal plus fresh M1 authority at every stage."""
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import uuid

from ..validation import contains
from .artifacts import Artifacts, UnsafeExecution, canonical, decode_tree, encode_tree, sha, snapshot


class Supervisor:
    def __init__(self, artifacts: Artifacts, backend):
        self.artifacts, self.backend = artifacts, backend

    def _slots(self, stack):
        for index in range(3):
            try:
                stack.enter_context(self.artifacts.lock(f"slot-{index}"))
                return
            except UnsafeExecution:
                continue
        raise UnsafeExecution("local_supervisor_slots_exhausted")

    def run(self, authority, source: Path, profile, execution_id=None):
        identity = execution_id or uuid.uuid4().hex
        self.artifacts._operation_id(identity)
        with ExitStack() as stack:
            stack.enter_context(self.artifacts.lock(identity))
            self._slots(stack)
            if (self.artifacts.root / "operations" / (identity + ".json")).exists():
                raise UnsafeExecution("execution_exists_use_recover")
            environment = self.backend.preflight(profile)
            tree = snapshot(source)
            base_hash = self.artifacts.put(encode_tree(tree))
            info = authority.info()
            run, task = info["run"], info["task"]
            writable = [resource[5:] for resource in task["document"]["resources"] if resource.startswith("path:")]
            binding = {key: run[key] for key in ["project_id", "run_id", "task_id", "fence",
                                                 "accepted_revision", "contract_hash", "owner"]}
            manifest = {"protocol": "m2a", "execution_id": identity, "binding": binding,
                        "base_hash": base_hash, "profile_hash": profile.identity(),
                        "environment": environment, "writable_paths": writable}
            manifest_hash = self.artifacts.put(canonical(manifest))
            names = [f"awh-m2a-{identity}-worker", f"awh-m2a-{identity}-validator"]
            state = {"execution_id": identity, "manifest_hash": manifest_hash, "manifest": manifest,
                     "containers": names, "state": "prepared", "receipt_hash": None,
                     "candidate_hash": None, "stopped_confirmed": False}
            self.artifacts.write_state(identity, state)  # Before admission or any create request.
            try:
                authority.begin(identity, manifest_hash)
                state["state"] = "admitted"
                self.artifacts.write_state(identity, state)
                def guard():
                    if self.artifacts.cancelled(identity):
                        return False
                    try:
                        current = authority.check(identity)
                        return (current["execution"]["manifest_hash"] == manifest_hash
                                and current["run"]["fence"] == run["fence"]
                                and current["run"]["contract_hash"] == run["contract_hash"])
                    except Exception:
                        return False

                if not guard():
                    raise UnsafeExecution("authority_lost")
                worker = self.backend.create(names[0], identity, manifest_hash, profile)
                self.backend.populate(worker, tree, writable)
                work = self.backend.execute(worker, profile.worker_command, profile, guard)
                state["worker_output_hash"] = self.artifacts.put(work.pop("output"))
                state["worker"] = work
                if work["status"] != "exited" or work["exit_code"] != 0:
                    raise UnsafeExecution(work["status"] if work["status"] != "exited" else "worker_failed")
                candidate = self.backend.capture(worker)
                changed = {name for name in set(tree) | set(candidate) if tree.get(name) != candidate.get(name)}
                if any(not any(contains(path, name) for path in writable) for name in changed):
                    raise UnsafeExecution("candidate_outside_write_scope")
                state["candidate_hash"] = self.artifacts.put(encode_tree(candidate))
                if not self.backend.stop(names[0], identity, manifest_hash):
                    raise UnsafeExecution("worker_stop_unconfirmed")
                state["state"] = "validating"
                self.artifacts.write_state(identity, state)
                if not guard():
                    raise UnsafeExecution("authority_lost")
                validator = self.backend.create(names[1], identity, manifest_hash, profile)
                # Always re-read the content-addressed snapshot; never the mutable source.
                self.backend.populate(validator, decode_tree(self.artifacts.get(state["candidate_hash"])), [])
                validation = self.backend.execute(validator, profile.validator_command, profile, guard)
                state["validator_output_hash"] = self.artifacts.put(validation.pop("output"))
                state["validator"] = validation
                if validation["status"] != "exited" or validation["exit_code"] != 0:
                    raise UnsafeExecution(validation["status"] if validation["status"] != "exited" else "validator_failed")
                validated = self.backend.capture(validator)
                if sha(encode_tree(validated)) != state["candidate_hash"]:
                    raise UnsafeExecution("candidate_changed_during_validation")
                if not self.backend.stop(names[1], identity, manifest_hash):
                    raise UnsafeExecution("validator_stop_unconfirmed")
                if not guard():
                    raise UnsafeExecution("authority_lost")
                payload = {**manifest, "protocol": "m2a-receipt-1",
                           "manifest_hash": manifest_hash, "candidate_hash": state["candidate_hash"],
                           "commands": {"worker": profile.worker_command, "validator": profile.validator_command},
                           "worker": work, "validator": validation,
                           "worker_output_hash": state["worker_output_hash"],
                           "validator_output_hash": state["validator_output_hash"],
                           "stopped_confirmed": True,
                           "completed_at": datetime.now(timezone.utc).isoformat()}
                state["receipt_hash"] = self.artifacts.receipt(payload)
                authority.end(identity, "validated", state["receipt_hash"])
                state.update(state="validated", stopped_confirmed=True)
            except Exception as error:
                state["error"] = str(error) if isinstance(error, UnsafeExecution) else type(error).__name__
                outcome = "failed"
                if self.artifacts.cancelled(identity):
                    outcome = "cancelled"
                elif state["error"] in {"authority_lost", "timed_out"}:
                    outcome = state["error"]
                stopped = self._stop_all(state)
                state.update(state="quarantined", stopped_confirmed=stopped)
                if stopped:
                    try:
                        admitted = authority.lookup(identity)
                        if admitted and admitted["state"] == "admitted":
                            authority.end(identity, outcome)
                        elif admitted and admitted["outcome"] == "validated":
                            outcome = "validated"  # Lost reply after committed completion.
                        state["state"] = outcome
                    except Exception:
                        pass  # Ambiguous authority/state; retain admission until recover.
            self.artifacts.write_state(identity, state)
            return state

    def _stop_all(self, state):
        confirmed = True
        for name in state["containers"]:
            try:
                confirmed = self.backend.stop(name, state["execution_id"], state["manifest_hash"]) and confirmed
            except Exception:
                confirmed = False
        return confirmed

    def recover(self, authority, identity):
        with self.artifacts.lock(identity):
            state = self.artifacts.state(identity)
            if state["manifest"]["binding"]["run_id"] != authority.rid or state["manifest"]["binding"]["project_id"] != authority.pid:
                raise UnsafeExecution("recovery_binding_mismatch")
            if not self._stop_all(state):
                state.update(state="quarantined", stopped_confirmed=False)
            else:
                admitted = authority.lookup(identity)
                if admitted and admitted["manifest_hash"] != state["manifest_hash"]:
                    raise UnsafeExecution("recovery_manifest_mismatch")
                if admitted and admitted["state"] == "admitted":
                    authority.end(identity, "recovered")
                    state["state"] = "recovered"
                elif admitted:
                    state["state"] = admitted["outcome"]
                else:
                    state["state"] = "not_admitted"
                state["stopped_confirmed"] = True
            self.artifacts.write_state(identity, state)
            return state

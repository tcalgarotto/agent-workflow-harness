# SPDX-License-Identifier: Apache-2.0
from contextlib import ExitStack
import json
from pathlib import Path
import uuid

from ..coordinator.store import Rejected, authorize
from ..supervisor.artifacts import UnsafeExecution, canonical, decode_tree, encode_tree, sha
from ..supervisor.runner import Supervisor
from .git import Git, combine


class Gateway:
    def __init__(self, store, principal, policy, artifacts, backend):
        self.store, self.principal, self.policy = store, principal, policy
        self.artifacts, self.backend = artifacts, backend
        if str(artifacts.root) != policy.supervisor_state:
            raise UnsafeExecution("configured_supervisor_state_mismatch")
        self.git = Git(policy.repository, policy.branch)

    def _configured(self, roles):
        authorize(self.principal, self.policy.project_id, roles)
        with self.store.connection() as c:
            self.store._policy(c, self.policy)

    def plan(self, receipt_hash, candidate_hash, base_commit):
        self._configured({"integrator", "controller"})
        p, a = self.policy, self.artifacts
        payload = a.verify(receipt_hash, candidate_hash, p.profile.identity())
        manifest = {key: payload[key] for key in ("execution_id", "binding", "base_hash",
                    "profile_hash", "environment", "writable_paths")}
        manifest["protocol"] = "m2a"
        if (payload["protocol"] != "m2a-receipt-1" or not payload["stopped_confirmed"]
                or payload["binding"]["project_id"] != p.project_id
                or payload["commands"] != {"worker": p.profile.worker_command, "validator": p.profile.validator_command}
                or any(payload[key] != {"status": "exited", "exit_code": 0} for key in ("worker", "validator"))
                or a.get(payload["manifest_hash"]) != canonical(manifest)):
            raise UnsafeExecution("invalid_supervisor_receipt")
        a._operation_id(payload["execution_id"])
        for key in ("worker_output_hash", "validator_output_hash"):
            a.get(payload[key])
        current = self.git.head()
        if not self.git.ancestor(base_commit, current):
            raise UnsafeExecution("candidate_base_is_not_accepted_ancestor")
        base, base_modes = self.git.tree(base_commit)
        if a.get(payload["base_hash"]) != encode_tree(base):
            raise UnsafeExecution("candidate_base_does_not_match_git_revision")
        candidate = decode_tree(a.get(candidate_hash))
        accepted, modes = self.git.tree(current)
        combined, changed = combine(base, candidate, accepted)
        if any(base_modes.get(name) != modes.get(name) for name in changed if name in base and name in accepted):
            raise UnsafeExecution("candidate_conflicts_with_file_mode_change")
        if not changed:
            raise UnsafeExecution("empty_candidate_delta")
        review = {"policy_hash": p.identity(), "receipt_hash": receipt_hash,
                  "base_commit": base_commit, "expected_head": current,
                  "candidate_hash": candidate_hash, "changed_paths": changed,
                  "protected_paths": p.protected(changed)}
        doc = {"policy_hash": p.identity(), "receipt_hash": receipt_hash, "receipt": payload,
               "review": review, "review_key": sha(canonical(review)),
               "combined_hash": a.put(encode_tree(combined))}
        return doc, combined, modes

    def run(self, receipt_hash, candidate_hash, base_commit, identity=None):
        self._configured({"integrator"})
        identity = identity or uuid.uuid4().hex
        self.artifacts._operation_id(identity)
        with ExitStack() as stack:
            stack.enter_context(self.artifacts.lock(identity))
            Supervisor(self.artifacts, self.backend)._slots(stack)
            if (self.artifacts.root/"operations"/(identity+".json")).exists():
                raise UnsafeExecution("integration_exists_use_recover")
            doc, tree, modes = self.plan(receipt_hash, candidate_hash, base_commit)
            environment = self.backend.preflight(self.policy.profile)
            name = f"awh-m2b-{identity}-validator"
            validation_manifest = self.artifacts.put(canonical({"protocol": "m2b-validation-1",
                "integration_id": identity, "policy_hash": self.policy.identity(),
                "expected_head": doc["review"]["expected_head"], "combined_hash": doc["combined_hash"],
                "environment": environment}))
            state = {"kind": "m2b", "policy_hash": self.policy.identity(), "integration_id": identity,
                     "container": name, "manifest_hash": validation_manifest,
                     "state": "planned", "stopped_confirmed": False}
            self.artifacts.write_state(identity, state)  # Also covers lost admission replies.
            try:
                self.store.admit(self.principal, self.policy, identity, doc)
                state["state"] = "validating"
                self.artifacts.write_state(identity, state)

                def guard():
                    if self.artifacts.cancelled(identity):
                        return False
                    try:
                        return self.store.check(self.principal, self.policy, identity)
                    except Exception:
                        return False

                if not guard():
                    raise UnsafeExecution("integration_authority_lost")
                validator = self.backend.create(name, identity, validation_manifest, self.policy.profile)
                self.backend.populate(validator, tree, [])
                result = self.backend.execute(validator, self.policy.profile.validator_command, self.policy.profile, guard)
                output_hash = self.artifacts.put(result.pop("output"))
                if result != {"status": "exited", "exit_code": 0}:
                    raise UnsafeExecution("combined_validation_failed")
                if encode_tree(self.backend.capture(validator)) != encode_tree(tree):
                    raise UnsafeExecution("combined_tree_changed_during_validation")
                if not self.backend.stop(name, identity, validation_manifest):
                    raise UnsafeExecution("integration_validator_stop_unconfirmed")
                state["stopped_confirmed"] = True
                if not guard():
                    raise UnsafeExecution("integration_authority_lost")
                expected = doc["review"]["expected_head"]
                if self.git.head() != expected:
                    raise UnsafeExecution("accepted_base_changed_revalidate")
                commit = self.git.commit(tree, modes, expected, identity, guard)
                validation_receipt = self.artifacts.receipt({"protocol": "m2b-receipt-1",
                    "manifest_hash": validation_manifest, "policy_hash": self.policy.identity(),
                    "combined_hash": doc["combined_hash"], "expected_head": expected, "commit": commit,
                    "command": self.policy.profile.validator_command, "result": result,
                    "output_hash": output_hash, "stopped_confirmed": True})
                effect = {"expected_head": expected, "commit": commit, "validation_receipt": validation_receipt}
                # This SQL commit is the linearization point: authority is live,
                # revision/evidence/review are checked, and cancellation is fenced.
                self.store.prepare(self.principal, self.policy, identity, effect)
                self.git.integrate(self.policy.project_id, identity, expected, commit)
                if not self.git.effect(self.policy.project_id, identity, expected, commit):
                    raise UnsafeExecution("git_effect_not_confirmed")
                state.update(self.store.settle(self.principal, self.policy, identity, True))
            except Exception as error:
                state["error"] = error.code if isinstance(error, Rejected) else (
                    str(error) if isinstance(error, UnsafeExecution) else type(error).__name__)
                state["state"] = "quarantined"
                # Reconcile uncertainty, including an admission/prepare/settle
                # transaction whose commit succeeded but whose reply was lost.
                try:
                    state = self._recover_locked(identity, state)
                except Exception:
                    pass
            self.artifacts.write_state(identity, state)
            return state

    def _recover_locked(self, identity, state):
        if state.get("kind") != "m2b" or state["policy_hash"] != self.policy.identity():
            raise UnsafeExecution("integration_recovery_policy_mismatch")
        if not self.backend.stop(state["container"], identity, state["manifest_hash"]):
            state.update(state="quarantined", stopped_confirmed=False)
            return state
        state["stopped_confirmed"] = True
        try:
            row = self.store.read(self.principal, self.policy.project_id, "integration", identity)
        except Rejected as error:
            if error.status != 404:
                raise
            state["state"] = "not_admitted"
            return state
        if row["state"] in {"committed", "aborted"}:
            if row["state"] == "committed":
                effect = row["document"]["effect"]
                if not self.git.effect(self.policy.project_id, identity, effect["expected_head"], effect["commit"]):
                    raise UnsafeExecution("committed_git_effect_missing_quarantine")
            state["state"] = row["state"]
            return state
        committed = False
        if row["state"] == "prepared":
            effect = row["document"]["effect"]
            committed = self.git.effect(self.policy.project_id, identity, effect["expected_head"], effect["commit"])
        state.update(self.store.settle(self.principal, self.policy, identity, committed))
        return state

    def recover(self, identity):
        self._configured({"integrator"})
        self.artifacts._operation_id(identity)
        with self.artifacts.lock(identity):
            state = self._recover_locked(identity, self.artifacts.state(identity))
            self.artifacts.write_state(identity, state)
            return state

    def export(self, revision, destination: Path):
        self._configured({"integrator", "controller"})
        if not self.git.ancestor(revision, self.git.head()):
            raise UnsafeExecution("export_requires_accepted_ancestor")
        tree, _ = self.git.tree(revision)
        destination.mkdir(mode=0o700)  # New directory only; never traverse existing output.
        for name, data in tree.items():
            target = destination/name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(data)
        return {"base_commit": revision, "base_hash": self.artifacts.put(encode_tree(tree))}

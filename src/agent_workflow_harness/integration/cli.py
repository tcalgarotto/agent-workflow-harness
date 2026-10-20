# SPDX-License-Identifier: Apache-2.0
"""Operator CLI; trusted host only, never installed inside a candidate container."""
import argparse
import json
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("register")
    export = commands.add_parser("export")
    export.add_argument("--base", required=True)
    export.add_argument("--destination", type=Path, required=True)
    for name in ("inspect", "approve", "integrate"):
        command = commands.add_parser(name)
        command.add_argument("--receipt", required=True)
        command.add_argument("--candidate", required=True)
        command.add_argument("--base", required=True)
        if name == "approve":
            command.add_argument("--expected-review", required=True)
        elif name == "integrate":
            command.add_argument("--integration-id")
    recover = commands.add_parser("recover")
    recover.add_argument("--integration-id", required=True)
    status = commands.add_parser("status")
    status.add_argument("--integration-id", required=True)
    args = parser.parse_args(argv)
    try:
        from ..coordinator.auth import Auth
        from ..coordinator.store import Rejected, authorize
        from ..supervisor.artifacts import Artifacts, UnsafeExecution
        from ..supervisor.docker_backend import DockerBackend
        from ..validation import read_json
        from .policy import Policy
        from .store import IntegrationStore
        from .gateway import Gateway
        if args.policy.stat().st_size > 100_000:
            raise ValueError("policy_too_large")
        policy = Policy.model_validate(read_json(args.policy))
        auth = Auth.from_file(Path(os.environ["AWH_AUTH_FILE"]))
        principal = auth.authenticate(os.environ["AWH_INTEGRATION_TOKEN"])
        if principal is None:
            raise Rejected("unauthenticated", 401)
        authorize(principal, policy.project_id, {"controller", "integrator"})
        store = IntegrationStore(os.environ["AWH_DATABASE_URL"], auth.subject)
        store.verify_schema()
        if args.command == "register":
            # Read/validate the private Git installation before binding its identity.
            from .git import Git
            Git(policy.repository, policy.branch)
            Artifacts(Path(policy.supervisor_state))
            result = store.register(principal, policy)
        elif args.command == "status":
            result = store.read(principal, policy.project_id, "integration", args.integration_id)
        else:
            artifacts = Artifacts(Path(policy.supervisor_state))
            # Construct Docker only when an operation needs it; inspection/export
            # and policy review work while the daemon is unavailable.
            backend = DockerBackend() if args.command in {"integrate", "recover"} else None
            gateway = Gateway(store, principal, policy, artifacts, backend)
            if args.command == "export":
                result = gateway.export(args.base, args.destination)
            elif args.command == "recover":
                result = gateway.recover(args.integration_id)
            elif args.command == "integrate":
                import uuid
                identity = args.integration_id or uuid.uuid4().hex
                artifacts._operation_id(identity)
                print(json.dumps({"integration_id": identity}), flush=True)
                result = gateway.run(args.receipt, args.candidate, args.base, identity)
            else:
                document, _, _ = gateway.plan(args.receipt, args.candidate, args.base)
                if args.command == "approve":
                    if args.expected_review != document["review_key"]:
                        raise UnsafeExecution("review_changed_inspect_again")
                    result = store.approve(principal, policy, document, document["review_key"])
                else:
                    result = {"review_key": document["review_key"], "review": document["review"],
                              "combined_hash": document["combined_hash"], "accepted_for_integration": False}
        print(json.dumps(result, sort_keys=True))
        if args.command in {"integrate", "recover"} and result["state"] != "committed":
            return 1
        return 0
    except Exception as error:
        # Neither arbitrary candidate output nor DB/host/credential details escape.
        from ..supervisor.artifacts import UnsafeExecution
        code = error.code if hasattr(error, "code") else (
            str(error) if isinstance(error, UnsafeExecution) else "integration_configuration_or_operation_failed")
        parser.exit(1, json.dumps({"error": code})+"\n")

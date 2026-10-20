# SPDX-License-Identifier: Apache-2.0
"""Trusted local M2a control. Candidate code never receives this CLI or its secrets."""
import argparse
import json
import os
from pathlib import Path
import signal
import uuid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path, help="Private persistent supervisor directory")
    parser.add_argument("--socket", default="/var/run/docker.sock")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--source", type=Path, required=True)
    run.add_argument("--profile", type=Path, required=True)
    recover = commands.add_parser("recover")
    for sub in (run, recover):
        sub.add_argument("--project", required=True)
        sub.add_argument("--run-id", required=True)
        sub.add_argument("--fence", type=int, required=True)
    recover.add_argument("--execution-id", required=True)
    cancel = commands.add_parser("cancel")
    cancel.add_argument("--execution-id", required=True)
    status = commands.add_parser("status")
    status.add_argument("--execution-id", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--receipt", required=True)
    verify.add_argument("--candidate", required=True)
    verify.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        from ..validation import read_json
        from .artifacts import Artifacts
        from .profile import Profile
        artifacts = Artifacts(args.state)
        if args.command == "cancel":
            artifacts.cancel(args.execution_id)
            print(json.dumps({"execution_id": args.execution_id, "cancel_requested": True,
                              "stopped_confirmed": False}))
            return 0
        if args.command == "status":
            result = artifacts.state(args.execution_id)
        elif args.command == "verify":
            profile = Profile.model_validate(read_json(args.profile))
            result = artifacts.verify(args.receipt, args.candidate, profile.identity())
            print(json.dumps({"authenticated": True, "accepted_for_integration": False,
                              "candidate": result["candidate_hash"]}))
            return 0
        else:
            from .authority import HTTPAuthority
            from .docker_backend import DockerBackend
            from .runner import Supervisor
            from ..coordinator.models import Identifier
            from pydantic import TypeAdapter
            import re
            TypeAdapter(Identifier).validate_python(args.project)
            if not re.fullmatch("[0-9a-f]{32}", args.run_id) or args.fence < 1:
                raise ValueError("invalid_run_binding")
            authority = HTTPAuthority(os.environ.get("AWH_COORDINATOR_URL", "http://127.0.0.1:8765"),
                                      os.environ["AWH_SUPERVISOR_TOKEN"], args.project, args.run_id, args.fence)
            supervisor = Supervisor(artifacts, DockerBackend(args.socket))
            if args.command == "recover":
                result = supervisor.recover(authority, args.execution_id)
            else:
                profile = Profile.model_validate(read_json(args.profile))
                identity = uuid.uuid4().hex
                old_handlers = {}
                for signum in (signal.SIGINT, signal.SIGTERM):
                    old_handlers[signum] = signal.signal(signum, lambda *_: artifacts.cancel(identity))
                try:
                    # Persisted before container creation; status/recover use this ID.
                    print(json.dumps({"execution_id": identity}), flush=True)
                    result = supervisor.run(authority, args.source, profile, identity)
                finally:
                    for signum, handler in old_handlers.items():
                        signal.signal(signum, handler)
        # No candidate stdout or credentials are rendered in the terminal.
        print(json.dumps({key: result.get(key) for key in ["execution_id", "state", "stopped_confirmed",
                                                          "candidate_hash", "receipt_hash", "error"]}))
        return 0 if result["state"] in {"validated", "recovered", "not_admitted"} else 1
    except Exception:
        parser.exit(1, "Supervisor operation failed; check configuration, private journal and Docker/M1 availability.\n")

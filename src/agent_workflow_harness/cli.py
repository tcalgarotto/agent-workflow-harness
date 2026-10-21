# SPDX-License-Identifier: Apache-2.0
"""Local contract validation. No subprocesses, model calls, or workflow execution."""
import argparse
import json
from pathlib import Path

from .validation import KINDS, read_json, validate_bundle, validate_document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    check = subcommands.add_parser("check", help="Check five contracts and their relationships")
    check.add_argument("directory", type=Path)
    validate = subcommands.add_parser("validate", help="Validate one document's JSON Schema")
    validate.add_argument("kind", choices=KINDS)
    validate.add_argument("file", type=Path)
    profiles = subcommands.add_parser("profiles", help="Inspect local headless CLI profiles")
    profile_commands = profiles.add_subparsers(dest="profile_command", required=True)
    profile_check = profile_commands.add_parser(
        "check", help="Check CLI availability and distinct Codex homes without starting agents"
    )
    profile_check.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "check":
        errors = validate_bundle(args.directory)
        print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
        return 1 if errors else 0
    if args.command == "validate":
        try:
            errors = validate_document(args.kind, read_json(args.file))
        except (OSError, ValueError, UnicodeError) as error:
            errors = [str(error)]
        print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
        return 1 if errors else 0
    from .executors.profiles import check_profiles
    result = check_profiles(args.config)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1

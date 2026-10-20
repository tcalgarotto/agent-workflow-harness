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
    args = parser.parse_args(argv)
    if args.command == "check":
        errors = validate_bundle(args.directory)
    else:
        try:
            errors = validate_document(args.kind, read_json(args.file))
        except (OSError, ValueError, UnicodeError) as error:
            errors = [str(error)]
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 1 if errors else 0

# SPDX-License-Identifier: Apache-2.0
"""Explicit schema migration and loopback service startup for M1."""
import argparse
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", choices=["127.0.0.1", "::1"], default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        from .store import Store
        dsn = os.environ["AWH_DATABASE_URL"]
        store = Store(dsn)
        if args.command == "migrate":
            store.migrate()
            print("M1 schema ready")
        else:
            from .api import create_app
            from .auth import Auth
            import uvicorn
            auth = Auth.from_file(Path(os.environ["AWH_AUTH_FILE"]))
            # Startup never creates/changes the database schema implicitly.
            store.verify_schema()
            uvicorn.run(create_app(store, auth), host=args.host, port=args.port, access_log=False)
    except (ImportError, KeyError, ValueError, OSError):
        parser.exit(1, "Coordinator configuration failed. Install [coordinator], set "
                    "AWH_DATABASE_URL and AWH_AUTH_FILE, and run migrate first.\n")
    except Exception:
        # Do not print libpq errors that may include operational connection data.
        parser.exit(1, "Coordinator startup/migration failed; check database availability and schema.\n")
    return 0

# SPDX-License-Identifier: Apache-2.0
"""Loopback M1 API; no subprocess, model, Git or integration endpoints."""
import json
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import Error as DatabaseError

from ..validation import _unique_pairs
from .models import CommandBody, Identifier, Project
from .store import Rejected


class BoundedJSON:
    """Reject oversized, duplicate-key and non-finite JSON before validation."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        raw = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            raw.extend(message.get("body", b""))
            if len(raw) > 1_000_000:
                return await JSONResponse({"error": "body_too_large"}, 413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        try:
            def reject_constant(value):
                raise ValueError("non-finite JSON")
            json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=reject_constant)
        except (ValueError, UnicodeError, RecursionError):
            return await JSONResponse({"error": "invalid_json"}, 400)(scope, receive, send)

        async def replay():
            return {"type": "http.request", "body": bytes(raw), "more_body": False}
        await self.app(scope, replay, send)


def create_app(store, auth):
    app = FastAPI(title="Agent Workflow Harness M1", version="m1")
    app.add_middleware(BoundedJSON)
    bearer = HTTPBearer(auto_error=False)

    def identity(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        principal = auth.authenticate(credentials.credentials) if credentials else None
        if principal is None:
            raise Rejected("unauthenticated", 401)
        return principal

    @app.exception_handler(Rejected)
    async def rejected(request: Request, error: Rejected):
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else None
        return JSONResponse({"error": error.code}, error.status, headers=headers)

    @app.exception_handler(DatabaseError)
    async def database_error(request: Request, error: DatabaseError):
        # DSNs, query arguments and database internals must not reach clients.
        return JSONResponse({"error": "database_unavailable_or_transaction_failed"}, 503)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError):
        return JSONResponse({"error": "invalid_request", "fields": [
            {"location": list(e["loc"]), "type": e["type"]} for e in error.errors()
        ]}, 422)

    @app.post("/v1/projects")
    def project_create(body: Project, principal=Depends(identity)):
        return store.create_project(principal, body)

    @app.post("/v1/projects/{project_id}/commands")
    def command(project_id: Identifier, body: CommandBody, principal=Depends(identity)):
        return store.execute(principal, project_id, body)

    @app.get("/v1/projects/{project_id}")
    def project_get(project_id: Identifier, principal=Depends(identity)):
        return store.read(principal, project_id, "project")

    @app.get("/v1/projects/{project_id}/tasks")
    def task_list(project_id: Identifier, limit: int = Query(100, ge=1, le=1000),
                  after_task: str = Query("", max_length=64), principal=Depends(identity)):
        return store.read(principal, project_id, "tasks", limit=limit, after_task=after_task)

    @app.get("/v1/projects/{project_id}/tasks/{task_id}")
    def task_get(project_id: Identifier, task_id: Identifier, principal=Depends(identity)):
        return store.read(principal, project_id, "task", task_id)

    @app.get("/v1/projects/{project_id}/runs/{run_id}")
    def run_get(project_id: Identifier, run_id: str, principal=Depends(identity)):
        return store.read(principal, project_id, "run", run_id)

    @app.get("/v1/projects/{project_id}/events")
    def events(project_id: Identifier, after: int = Query(0, ge=0),
               limit: int = Query(100, ge=1, le=1000), principal=Depends(identity)):
        return store.read(principal, project_id, "events", after=after, limit=limit)

    @app.get("/v1/projects/{project_id}/executions/{execution_id}/authority")
    def execution_authority(project_id: Identifier, execution_id: str, principal=Depends(identity)):
        # Fresh check; never serve a cached/idempotency receipt as current authority.
        return store.execution_authority(principal, project_id, execution_id)

    @app.get("/v1/projects/{project_id}/executions/{execution_id}")
    def execution_get(project_id: Identifier, execution_id: str, principal=Depends(identity)):
        return store.read(principal, project_id, "execution", execution_id)

    return app

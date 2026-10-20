# SPDX-License-Identifier: Apache-2.0
"""Supervisor-only coordinator client; never passed to the container."""
import time
from urllib.parse import urlsplit

import httpx

from .artifacts import UnsafeExecution


class HTTPAuthority:
    def __init__(self, url, token, project_id, run_id, fence):
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise UnsafeExecution("coordinator_must_be_loopback")
        self.client = httpx.Client(base_url=url, headers={"Authorization": "Bearer " + token},
                                   timeout=3, trust_env=False, follow_redirects=False)
        self.pid, self.rid, self.fence = project_id, run_id, fence
        self.prefix = f"/v1/projects/{project_id}"
        self.last_heartbeat = time.monotonic()

    def _json(self, response):
        if response.status_code != 200:
            raise UnsafeExecution("coordinator_rejected_or_unavailable")
        return response.json()

    def info(self):
        run = self._json(self.client.get(self.prefix + "/runs/" + self.rid))
        task = self._json(self.client.get(self.prefix + "/tasks/" + run["task_id"]))
        if run["fence"] != self.fence:
            raise UnsafeExecution("stale_fencing_token")
        return {"run": run, "task": task}

    def command(self, operation, command_id, **kwargs):
        return self._json(self.client.post(self.prefix + "/commands", json={
            "operation": operation, "command_id": command_id, "run_id": self.rid,
            "fencing_token": self.fence, **kwargs}))

    def begin(self, execution_id, manifest_hash):
        return self.command("start_execution", execution_id + "-start", execution_id=execution_id,
                            manifest_hash=manifest_hash)

    def check(self, execution_id):
        result = self._json(self.client.get(self.prefix + f"/executions/{execution_id}/authority"))
        if time.monotonic() - self.last_heartbeat > 3:
            # A fresh command ID per renewal; a replay must never extend a lease.
            import uuid
            self.command("heartbeat", uuid.uuid4().hex, lease_seconds=10)
            self.last_heartbeat = time.monotonic()
        return result

    def end(self, execution_id, outcome, receipt_hash=None):
        return self.command("end_execution", execution_id + "-end-" + outcome,
                            execution_id=execution_id, stopped_confirmed=True,
                            outcome=outcome, receipt_hash=receipt_hash)

    def lookup(self, execution_id):
        response = self.client.get(self.prefix + f"/executions/{execution_id}")
        if response.status_code == 404:
            return None
        return self._json(response)

# SPDX-License-Identifier: Apache-2.0
FROM python:3.12-alpine@sha256:b64631e04e4920160c50fbe8d8df828f7f35f06f425cb44aa09bca53e708a35a

COPY src/agent_workflow_harness/__init__.py /opt/awh/agent_workflow_harness/__init__.py
COPY src/agent_workflow_harness/executors/__init__.py /opt/awh/agent_workflow_harness/executors/__init__.py
COPY src/agent_workflow_harness/executors/egress_proxy.py /opt/awh/agent_workflow_harness/executors/egress_proxy.py

USER 65532:65532
WORKDIR /
ENTRYPOINT ["python", "-I", "-c", "import sys; sys.path.insert(0, '/opt/awh'); from agent_workflow_harness.executors.egress_proxy import main; main()"]

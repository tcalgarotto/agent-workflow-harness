# SPDX-License-Identifier: Apache-2.0
"""Per-run Docker network topology for an allowlisted egress proxy.

The agent joins only an internal, isolated-gateway bridge. The trusted proxy
is the only workload attached to both that network and an egress network.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .egress_proxy import normalize_allowlist


_NETWORK_OPTIONS = {
    "com.docker.network.bridge.gateway_mode_ipv4": "isolated",
    "com.docker.network.bridge.gateway_mode_ipv6": "isolated",
}


class AgentNetworkError(RuntimeError):
    """Docker cannot prove the required task network topology."""


@dataclass(frozen=True)
class AgentNetworkBundle:
    run_digest: str
    task_network_name: str
    proxy_container_name: str
    proxy_address: str
    egress_network_name: str

    def agent_proxy_environment(self):
        endpoint = f"http://{self.proxy_address}:3128"
        return {"HTTP_PROXY": endpoint, "HTTPS_PROXY": endpoint,
                "http_proxy": endpoint, "https_proxy": endpoint,
                "NO_PROXY": "localhost,127.0.0.1,::1",
                "no_proxy": "localhost,127.0.0.1,::1"}


def create_agent_network_bundle(client, run_id: str, *, proxy_image: str,
                                allow_domains, egress_network="bridge") -> AgentNetworkBundle:
    """Create a task-only network and a tightly bounded, dual-homed proxy.

    The caller must connect the agent to ``task_network_name`` only and verify
    its full container settings before start. Images are never pulled.
    """
    if not isinstance(proxy_image, str) or not re.fullmatch(
            r"[^\s@]+@sha256:[0-9a-f]{64}", proxy_image):
        raise ValueError("proxy image must be pinned by immutable sha256 digest")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run ID is required")
    domains = normalize_allowlist(allow_domains)
    suffix = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
    network = create_task_network(client, run_id)
    proxy_name = "awh-proxy-" + suffix
    labels = {"awh.m3.role": "egress-proxy", "awh.m3.run-digest": suffix}
    try:
        from docker.errors import NotFound
        try:
            client.containers.get(proxy_name)
        except NotFound:
            pass
        else:
            raise AgentNetworkError("existing proxy requires recovery")
        image = client.images.get(proxy_image)  # No implicit pull.
        container = client.containers.create(
            image.id,
            command=["--listen-host", "0.0.0.0", "--port", "3128",
                     *sum((["--allow-domain", domain] for domain in domains), [])],
            name=proxy_name, user="65532:65532", working_dir="/",
            read_only=True, network=egress_network, ipc_mode="private",
            cap_drop=["ALL"], security_opt=["no-new-privileges:true"], init=True,
            mem_limit=128 * 1024 * 1024, memswap_limit=128 * 1024 * 1024,
            nano_cpus=250_000_000, pids_limit=32,
            tmpfs={"/tmp": "rw,nosuid,nodev,noexec,size=4m,mode=0700,uid=65532,gid=65532"},
            environment={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": ""},
            labels=labels, restart_policy={"Name": "no"}, detach=True,
        )
        client.networks.get(network.name).connect(container)
        container.start()
        container.reload()
        verify_proxy_container(container, network, egress_network)
        address = container.attrs["NetworkSettings"]["Networks"][network.name]["IPAddress"]
        return AgentNetworkBundle(suffix, network.name, proxy_name, address, egress_network)
    except Exception:
        try:
            container = client.containers.get(proxy_name)
            labels_now = container.labels or {}
            if labels_now.get("awh.m3.run-digest") == suffix:
                container.remove(force=True)
        except Exception:
            pass
        try:
            network.remove()
        except Exception:
            pass
        raise


def create_task_network(client, run_id: str):
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run ID is required")
    suffix = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
    name = "awh-agent-" + suffix
    labels = {"awh.m3.role": "agent-task", "awh.m3.run-digest": suffix}
    from docker.errors import NotFound
    try:
        client.networks.get(name)
    except NotFound:
        pass
    else:
        raise AgentNetworkError("existing task network requires recovery")
    network = client.networks.create(name=name, driver="bridge", internal=True,
                                     attachable=False, options=_NETWORK_OPTIONS,
                                     labels=labels)
    try:
        verify_task_network(network)
    except Exception:
        try:
            network.remove()
        except Exception:
            pass
        raise
    return network


def verify_task_network(network):
    attrs = network.attrs if hasattr(network, "attrs") else network.reload() or network.attrs
    options = attrs.get("Options") or {}
    if (attrs.get("Driver") != "bridge" or attrs.get("Internal") is not True
            or any(options.get(key) != value for key, value in _NETWORK_OPTIONS.items())
            or attrs.get("Attachable") is True):
        raise AgentNetworkError("task network is not externally isolated")
    ipam = attrs.get("IPAM") or {}
    configs = ipam.get("Config") or []
    if not configs or any(item.get("Gateway") for item in configs):
        raise AgentNetworkError("isolated task network unexpectedly has a gateway")
    return True


def verify_agent_container(container, task_network):
    container.reload()
    host = container.attrs.get("HostConfig") or {}
    networks = container.attrs.get("NetworkSettings", {}).get("Networks") or {}
    if (container.attrs.get("Config", {}).get("NetworkDisabled") is True
            or host.get("NetworkMode") != task_network.name
            or set(networks) != {task_network.name}):
        raise AgentNetworkError("agent container has an unexpected network attachment")
    verify_task_network(task_network)
    return True


def verify_proxy_container(proxy, task_network, egress_network="bridge"):
    proxy.reload()
    networks = proxy.attrs.get("NetworkSettings", {}).get("Networks") or {}
    if set(networks) != {task_network.name, egress_network}:
        raise AgentNetworkError("egress proxy has an unexpected network attachment")
    verify_task_network(task_network)
    if not networks[task_network.name].get("IPAddress"):
        raise AgentNetworkError("egress proxy has no task-network address")
    return True


def task_network_digest(run_id: str) -> str:
    """Return a stable opaque identifier suitable for local Docker names."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run ID is required")
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()

# SPDX-License-Identifier: Apache-2.0
import unittest

from agent_workflow_harness.executors.docker_agent_network import (
    AgentNetworkError,
    verify_agent_container,
    verify_proxy_container,
    verify_task_network,
)


class FakeNetwork:
    name = "awh-agent-test"

    def __init__(self, *, internal=True, options=None, configs=None):
        self.attrs = {
            "Driver": "bridge",
            "Internal": internal,
            "Attachable": False,
            "Options": options or {
                "com.docker.network.bridge.gateway_mode_ipv4": "isolated",
                "com.docker.network.bridge.gateway_mode_ipv6": "isolated",
            },
            "IPAM": {"Config": configs or [{"Subnet": "172.28.0.0/24"}]},
        }

    def reload(self):
        return None


class FakeContainer:
    def __init__(self, host_network_mode, networks):
        self.attrs = {
            "HostConfig": {"NetworkMode": host_network_mode},
            "Config": {"NetworkDisabled": False},
            "NetworkSettings": {"Networks": networks},
        }

    def reload(self):
        return None


class DockerAgentNetworkTest(unittest.TestCase):
    def test_task_network_requires_internal_isolated_gateway(self):
        self.assertTrue(verify_task_network(FakeNetwork()))
        with self.assertRaises(AgentNetworkError):
            verify_task_network(FakeNetwork(internal=False))
        with self.assertRaises(AgentNetworkError):
            verify_task_network(FakeNetwork(configs=[{
                "Subnet": "172.28.0.0/24", "Gateway": "172.28.0.1",
            }]))

    def test_agent_must_have_only_the_task_network(self):
        network = FakeNetwork()
        container = FakeContainer(network.name, {network.name: {"IPAddress": "172.28.0.2"}})
        self.assertTrue(verify_agent_container(container, network))
        container.attrs["NetworkSettings"]["Networks"]["bridge"] = {"IPAddress": "172.17.0.2"}
        with self.assertRaises(AgentNetworkError):
            verify_agent_container(container, network)

    def test_proxy_must_be_the_only_dual_homed_service(self):
        network = FakeNetwork()
        proxy = FakeContainer("default", {
            network.name: {"IPAddress": "172.28.0.3"},
            "bridge": {"IPAddress": "172.17.0.3"},
        })
        self.assertTrue(verify_proxy_container(proxy, network))
        proxy.attrs["NetworkSettings"]["Networks"]["other"] = {"IPAddress": "172.30.0.3"}
        with self.assertRaises(AgentNetworkError):
            verify_proxy_container(proxy, network)


if __name__ == "__main__":
    unittest.main()

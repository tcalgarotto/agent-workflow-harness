# SPDX-License-Identifier: Apache-2.0
import socket
import unittest

from agent_workflow_harness.executors.egress_proxy import (
    ProxyRejected,
    host_is_allowed,
    normalize_allowlist,
    parse_connect_request,
    resolve_public,
)


class EgressProxyPolicyTest(unittest.TestCase):
    def test_allowlist_is_canonical_and_rejects_unsafe_entries(self):
        self.assertEqual(("chatgpt.com", "openai.com"), normalize_allowlist(
            ["OpenAI.com", "chatgpt.com.", "openai.com"]))
        for invalid in [[], ["*"], ["*.openai.com"], ["127.0.0.1"],
                        ["openai.com/path"], [" user:pass@openai.com"], ["bad..domain"]]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_allowlist(invalid)

    def test_hostname_allowlist_uses_dns_label_boundary(self):
        allowlist = normalize_allowlist(["openai.com"])
        self.assertTrue(host_is_allowed("api.openai.com", allowlist))
        self.assertTrue(host_is_allowed("openai.com", allowlist))
        self.assertFalse(host_is_allowed("evilopenai.com", allowlist))

    def test_connect_parser_only_accepts_well_formed_https_tunnels(self):
        target = parse_connect_request(
            b"CONNECT api.openai.com:443 HTTP/1.1\r\nHost: api.openai.com:443\r\n\r\n")
        self.assertEqual(("api.openai.com", 443), (target.host, target.port))
        for request in [
            b"GET http://example.com/ HTTP/1.1\r\n\r\n",
            b"CONNECT api.openai.com:80 HTTP/1.1\r\n\r\n",
            b"CONNECT 127.0.0.1:443 HTTP/1.1\r\n\r\n",
            b"CONNECT attacker@api.openai.com:443 HTTP/1.1\r\n\r\n",
            b"CONNECT api.openai.com:443 HTTP/1.1\r\n folded: x\r\n\r\n",
            b"CONNECT api.openai.com:443 HTTP/1.1\r\n" + b"X" * 20_000,
        ]:
            with self.subTest(request=request[:50]), self.assertRaises(ProxyRejected):
                parse_connect_request(request)

    def test_dns_resolution_rejects_private_and_mixed_public_private_answers(self):
        def resolver(addresses):
            return lambda host, port, type: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
                for address in addresses
            ]

        public = resolve_public("api.openai.com", 443, resolver=resolver(["1.1.1.1"]))
        self.assertEqual(("1.1.1.1",), public)
        for addresses in [["127.0.0.1"], ["10.1.2.3"], ["169.254.169.254"],
                          ["1.1.1.1", "192.168.1.1"]]:
            with self.subTest(addresses=addresses), self.assertRaises(ProxyRejected):
                resolve_public("api.openai.com", 443, resolver=resolver(addresses))


if __name__ == "__main__":
    unittest.main()

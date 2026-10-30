from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .exceptions import WarpgateError, WarpgateIdentityCollision
from .warpgate_client import WarpgateClient


@override_settings(
    WARPGATE_URL="https://warpgate.example",
    WARPGATE_API_TOKEN="secret-token",
    WARPGATE_CA_BUNDLE="",
)
class WarpgateClientTests(SimpleTestCase):
    def test_plain_http_is_refused(self):
        with self.assertRaisesMessage(WarpgateError, "requires HTTPS"):
            WarpgateClient(base_url="http://warpgate.example")

    @patch("infrastructure.warpgate_client.ssl.create_default_context")
    def test_custom_ca_bundle_is_loaded(self, context):
        WarpgateClient(ca_bundle="/tmp/warpgate-ca.crt")
        context.assert_called_once_with(cafile="/tmp/warpgate-ca.crt")

    @patch(
        "infrastructure.warpgate_client.ssl.create_default_context",
        side_effect=OSError("invalid CA"),
    )
    def test_invalid_ca_bundle_is_a_domain_error(self, context):
        with self.assertRaisesMessage(WarpgateError, "cannot be loaded"):
            WarpgateClient(ca_bundle="/tmp/invalid-ca.crt")

    def test_sso_email_collision_is_fail_closed(self):
        client = WarpgateClient()
        client._request = lambda method, path, payload=None: {
            "/users": [{"id": "alice"}, {"id": "bob"}],
            "/users/alice/credentials/sso": [
                {
                    "id": "credential",
                    "provider": "keycloak-aw0",
                    "email": "same@example.com",
                }
            ],
            "/users/bob/credentials/sso": [],
        }[path]

        with self.assertRaises(WarpgateIdentityCollision):
            client.ensure_sso_credential(
                user={"id": "bob"},
                provider="keycloak-aw0",
                email="SAME@example.com",
            )

    def test_target_uses_dns_and_public_key(self):
        client = WarpgateClient()
        calls = []

        def request(method, path, payload=None):
            calls.append((method, path, payload))
            if method == "GET":
                return []
            return {"id": "target"}

        client._request = request
        target = client.ensure_ssh_target(
            name="aw-123",
            host="agent-123.user-1.svc.cluster.local",
            description="workspace",
        )

        self.assertEqual(target, {"id": "target"})
        payload = calls[-1][2]
        self.assertEqual(
            payload["options"]["host"], "agent-123.user-1.svc.cluster.local"
        )
        self.assertEqual(payload["options"]["port"], 2222)
        self.assertEqual(payload["options"]["username"], "developer")
        self.assertEqual(payload["options"]["auth"], {"kind": "PublicKey"})

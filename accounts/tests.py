from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .backends import KeycloakAuthenticationBackend
from .models import OidcIdentity


@override_settings(
    OIDC_OP_TOKEN_ENDPOINT="https://idp.example/token",
    OIDC_OP_USER_ENDPOINT="https://idp.example/userinfo",
    OIDC_OP_JWKS_ENDPOINT="https://idp.example/certs",
    OIDC_RP_CLIENT_ID="ilosia",
    OIDC_RP_CLIENT_SECRET="test-secret",
    OIDC_RP_SIGN_ALGO="RS256",
)
class KeycloakAuthenticationBackendTests(TestCase):
    def setUp(self):
        self.backend = KeycloakAuthenticationBackend()
        self.claims = {
            "sub": "stable-keycloak-subject",
            "email": "alice@example.com",
            "email_verified": True,
            "given_name": "Alice",
            "family_name": "Admin",
            "roles": ["admin"],
        }

    def test_subject_is_stored_and_admin_role_is_mapped(self):
        user = self.backend.create_user(self.claims)

        self.assertEqual(
            OidcIdentity.objects.get(user=user).subject,
            "stable-keycloak-subject",
        )
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.first_name, "Alice")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["admin"])

    def test_verified_email_can_link_one_existing_local_user(self):
        local_user = get_user_model().objects.create_user(
            username="alice",
            email="alice@example.com",
        )

        user = self.backend.create_user(self.claims)

        self.assertEqual(user, local_user)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_subject_not_email_defines_the_username(self):
        first = self.backend.get_username(self.claims)
        self.claims["email"] = "new-address@example.com"

        self.assertEqual(self.backend.get_username(self.claims), first)

    def test_unverified_email_is_rejected(self):
        self.claims["email_verified"] = False

        self.assertFalse(self.backend.verify_claims(self.claims))

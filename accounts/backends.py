import hashlib

from django.contrib.auth.models import Group
from django.db import transaction
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from .models import OidcIdentity


class KeycloakAuthenticationBackend(OIDCAuthenticationBackend):
    def verify_claims(self, claims):
        return (
            super().verify_claims(claims)
            and bool(claims.get("sub"))
            and (
                not self.get_settings("OIDC_REQUIRE_VERIFIED_EMAIL", True)
                or claims.get("email_verified") is True
            )
        )

    def get_username(self, claims):
        digest = hashlib.sha256(claims["sub"].encode()).hexdigest()[:32]
        return f"oidc_{digest}"

    def filter_users_by_claims(self, claims):
        return self.UserModel.objects.filter(oidc_identity__subject=claims.get("sub"))

    @transaction.atomic
    def create_user(self, claims):
        email = claims["email"]
        matching_users = self.UserModel.objects.filter(
            email__iexact=email,
            oidc_identity__isnull=True,
        )
        user = matching_users.first() if matching_users.count() == 1 else None
        if user is None:
            user = self.UserModel.objects.create_user(
                username=self.get_username(claims),
                email=email,
            )
        OidcIdentity.objects.create(user=user, subject=claims["sub"])
        return self.update_user(user, claims)

    def update_user(self, user, claims):
        roles = set(claims.get("roles", []))
        user.email = claims["email"]
        user.first_name = claims.get("given_name", "")
        user.last_name = claims.get("family_name", "")
        user.is_staff = "admin" in roles
        user.is_superuser = user.is_staff
        user.save(
            update_fields=(
                "email",
                "first_name",
                "last_name",
                "is_staff",
                "is_superuser",
            )
        )

        managed_groups = Group.objects.filter(name__in=("user", "admin"))
        user.groups.remove(*managed_groups)
        group_name = "admin" if user.is_staff else "user"
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
        return user

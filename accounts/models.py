from django.conf import settings
from django.db import models


class OidcIdentity(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oidc_identity",
    )
    subject = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.subject

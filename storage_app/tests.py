from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(S3_ENDPOINT_URL="http://s3:9000")
class StorageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="alice", password="correct-horse-battery-staple"
        )

    def setUp(self):
        self.client.force_login(self.user)

    @patch("storage_app.views.StorageClient")
    def test_list_uses_only_the_current_users_bucket(self, client_class):
        client_class.return_value.list_objects.return_value = [
            {"Key": "data.csv", "Size": 12, "LastModified": "today"}
        ]

        response = self.client.get(reverse("storage:list"))

        self.assertContains(response, "data.csv")
        client_class.return_value.ensure_bucket.assert_called_once_with(
            f"user-{self.user.pk}"
        )
        client_class.return_value.list_objects.assert_called_once_with(
            f"user-{self.user.pk}"
        )

    @patch("storage_app.views.StorageClient")
    def test_download_redirects_to_a_short_lived_url(self, client_class):
        client_class.return_value.generate_presigned_url.return_value = (
            "http://s3.local/download"
        )

        response = self.client.get(reverse("storage:download"), {"key": "data.csv"})

        self.assertRedirects(
            response, "http://s3.local/download", fetch_redirect_response=False
        )
        client_class.return_value.generate_presigned_url.assert_called_once_with(
            f"user-{self.user.pk}", "data.csv"
        )

    @patch("storage_app.views.StorageClient")
    def test_delete_is_post_only_and_scoped_to_the_user(self, client_class):
        url = reverse("storage:delete")

        self.assertEqual(self.client.get(url, {"key": "data.csv"}).status_code, 405)
        response = self.client.post(url, {"key": "data.csv"})

        self.assertRedirects(response, reverse("storage:list"))
        client_class.return_value.delete_object.assert_called_once_with(
            f"user-{self.user.pk}", "data.csv"
        )

    def test_storage_requires_authentication(self):
        self.client.logout()

        response = self.client.get(reverse("storage:list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    @override_settings(S3_ENDPOINT_URL="")
    @patch("storage_app.views.StorageClient")
    def test_actions_are_disabled_when_storage_is_not_configured(self, client_class):
        download = self.client.get(reverse("storage:download"), {"key": "data.csv"})
        delete = self.client.post(reverse("storage:delete"), {"key": "data.csv"})

        self.assertRedirects(download, reverse("storage:list"))
        self.assertRedirects(delete, reverse("storage:list"))
        client_class.assert_not_called()

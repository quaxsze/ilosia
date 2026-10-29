import json
import subprocess
from unittest.mock import patch

from botocore.exceptions import ClientError
from django.test import SimpleTestCase, override_settings

from .exceptions import HelmInstallError, HelmUninstallError
from .helm_client import HelmClient
from .kubernetes_client import KubernetesClient
from .storage_client import GarageAdminClient, StorageClient, user_bucket


class HelmClientTests(SimpleTestCase):
    def test_install_uses_an_argument_list_and_values_file(self):
        captured = {}

        def fake_run(command, **kwargs):
            values_path = command[command.index("--values") + 1]
            with open(values_path) as values_file:
                captured["values"] = json.load(values_file)
            captured["command"] = command
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(command, 0)

        with patch("infrastructure.helm_client.subprocess.run", side_effect=fake_run):
            HelmClient().install(
                release_name="jupyter-abc",
                chart_path="charts/jupyter",
                namespace="user-1",
                values={"ingress": {"host": "jupyter-abc.localhost"}},
            )

        self.assertEqual(captured["command"][0:3], ["helm", "upgrade", "--install"])
        self.assertIn("--create-namespace", captured["command"])
        self.assertIn("--atomic", captured["command"])
        self.assertEqual(captured["values"]["ingress"]["host"], "jupyter-abc.localhost")
        self.assertTrue(captured["kwargs"]["check"])
        self.assertNotIn("shell", captured["kwargs"])

    def test_install_wraps_subprocess_errors(self):
        error = subprocess.CalledProcessError(1, ["helm"], stderr="install failed")

        with patch("infrastructure.helm_client.subprocess.run", side_effect=error):
            with self.assertRaises(HelmInstallError):
                HelmClient().install(
                    release_name="jupyter-abc",
                    chart_path="charts/jupyter",
                    namespace="user-1",
                    values={},
                )

    @patch("infrastructure.helm_client.subprocess.run")
    def test_uninstall_is_idempotent_and_uses_an_argument_list(self, run):
        HelmClient().uninstall(
            release_name="jupyter-abc",
            namespace="user-1",
        )

        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["helm", "uninstall"])
        self.assertIn("--ignore-not-found", command)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_uninstall_wraps_subprocess_errors(self):
        error = subprocess.CalledProcessError(1, ["helm"], stderr="uninstall failed")

        with patch("infrastructure.helm_client.subprocess.run", side_effect=error):
            with self.assertRaises(HelmUninstallError):
                HelmClient().uninstall(
                    release_name="jupyter-abc",
                    namespace="user-1",
                )


class KubernetesClientTests(SimpleTestCase):
    @patch.dict(
        "os.environ",
        {
            "POD_NAMESPACE": "ilosia",
            "PLATFORM_SERVICE_ACCOUNT": "ilosia-web",
            "PLATFORM_WORKLOAD_CLUSTER_ROLE": "ilosia-user-workload",
        },
    )
    def test_namespace_gets_scoped_rbac_and_quota(self):
        client = KubernetesClient()
        with patch.object(client, "_request") as request:
            client.ensure_namespace(
                "user-42",
                quota={"requests.cpu": "20", "pods": "10"},
            )

        namespace, binding, quota = request.call_args_list
        self.assertEqual(namespace.args[0], "/api/v1/namespaces")
        self.assertEqual(
            namespace.kwargs["payload"]["metadata"]["labels"][
                "pod-security.kubernetes.io/enforce"
            ],
            "restricted",
        )
        self.assertEqual(
            binding.args[0],
            "/apis/rbac.authorization.k8s.io/v1/namespaces/user-42/rolebindings",
        )
        self.assertEqual(
            binding.kwargs["payload"]["roleRef"]["name"],
            "ilosia-user-workload",
        )
        self.assertEqual(
            binding.kwargs["payload"]["subjects"][0]["namespace"],
            "ilosia",
        )
        self.assertEqual(quota.args[0], "/api/v1/namespaces/user-42/resourcequotas")
        self.assertEqual(
            quota.kwargs["payload"]["spec"]["hard"],
            {"requests.cpu": "20", "pods": "10"},
        )

    def test_namespace_name_is_restricted(self):
        client = KubernetesClient()
        with self.assertRaisesMessage(ValueError, "user-<positive id>"):
            client.ensure_namespace("kube-system")

    def test_list_pods_uses_the_release_label(self):
        client = KubernetesClient()
        with patch.object(client, "_request", return_value='{"items": []}') as request:
            self.assertEqual(
                client.list_pods(namespace="user-1", release_name="jupyter-abc"), []
            )

        path = request.call_args.args[0]
        self.assertIn("/namespaces/user-1/pods?", path)
        self.assertIn("app.kubernetes.io%2Finstance%3Djupyter-abc", path)

    def test_logs_use_a_running_pod_and_are_limited(self):
        client = KubernetesClient()
        pods = [
            {"metadata": {"name": "pending-pod"}, "status": {"phase": "Pending"}},
            {"metadata": {"name": "running-pod"}, "status": {"phase": "Running"}},
        ]
        with (
            patch.object(client, "list_pods", return_value=pods),
            patch.object(client, "_request", return_value="hello") as request,
        ):
            logs = client.get_pod_logs(
                namespace="user-1", release_name="jupyter-abc", tail_lines=50
            )

        self.assertEqual(logs, "hello")
        self.assertIn("running-pod/log?", request.call_args.args[0])
        self.assertIn("tailLines=50", request.call_args.args[0])

    def test_secret_is_sent_directly_to_kubernetes(self):
        client = KubernetesClient()
        with patch.object(client, "_request") as request:
            client.create_secret(
                namespace="user-1",
                name="jupyter-abc-environment",
                string_data={"API_KEY": "secret-value"},
                release_name="jupyter-abc",
            )

        path = request.call_args.args[0]
        options = request.call_args.kwargs
        self.assertEqual(path, "/api/v1/namespaces/user-1/secrets")
        self.assertEqual(options["method"], "POST")
        self.assertEqual(options["payload"]["stringData"], {"API_KEY": "secret-value"})

    def test_secret_deletion_is_idempotent(self):
        client = KubernetesClient()
        with patch.object(client, "_request") as request:
            client.delete_secret(namespace="user-1", name="jupyter-abc-environment")

        self.assertEqual(request.call_args.kwargs["method"], "DELETE")
        self.assertEqual(request.call_args.kwargs["ignored_statuses"], {404})

    def test_secret_patch_preserves_other_values(self):
        client = KubernetesClient()
        with patch.object(client, "_request") as request:
            client.patch_secret(
                namespace="user-1",
                name="jupyter-abc-environment",
                string_data={"S3_ACCESS_KEY": "user-access"},
            )

        self.assertEqual(request.call_args.kwargs["method"], "PATCH")
        self.assertEqual(
            request.call_args.kwargs["content_type"],
            "application/merge-patch+json",
        )
        self.assertEqual(
            request.call_args.kwargs["payload"]["stringData"],
            {"S3_ACCESS_KEY": "user-access"},
        )

    def test_pvc_deletion_is_idempotent(self):
        client = KubernetesClient()
        with patch.object(client, "_request") as request:
            client.delete_persistent_volume_claim(
                namespace="user-1", name="jupyter-abc-data"
            )

        self.assertEqual(
            request.call_args.args[0],
            "/api/v1/namespaces/user-1/persistentvolumeclaims/jupyter-abc-data",
        )
        self.assertEqual(request.call_args.kwargs["method"], "DELETE")
        self.assertEqual(request.call_args.kwargs["ignored_statuses"], {404})


class StorageClientTests(SimpleTestCase):
    def test_bucket_is_created_when_missing(self):
        client = patch("infrastructure.storage_client.boto3.client").start()
        self.addCleanup(patch.stopall)
        client.return_value.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "missing"}}, "HeadBucket"
        )

        StorageClient().ensure_bucket("user-1")

        client.return_value.create_bucket.assert_called_once_with(Bucket="user-1")

    def test_list_objects_uses_all_paginator_pages(self):
        client = patch("infrastructure.storage_client.boto3.client").start()
        self.addCleanup(patch.stopall)
        client.return_value.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "one"}]},
            {"Contents": [{"Key": "two"}]},
        ]

        objects = StorageClient().list_objects("user-1")

        self.assertEqual([item["Key"] for item in objects], ["one", "two"])

    def test_user_bucket_is_stable(self):
        user = type("User", (), {"pk": 42})()

        self.assertEqual(user_bucket(user), "user-42")

    @override_settings(S3_BROWSER_ENDPOINT_URL="http://garage.localhost:8080")
    def test_presigned_url_is_rewritten_for_the_browser(self):
        client = patch("infrastructure.storage_client.boto3.client").start()
        self.addCleanup(patch.stopall)
        client.return_value.generate_presigned_url.return_value = (
            "http://garage.localhost/user-1/data.csv?signature=abc"
        )

        url = StorageClient().generate_presigned_url("user-1", "data.csv")

        self.assertEqual(
            url,
            "http://garage.localhost:8080/user-1/data.csv?signature=abc",
        )


class GarageAdminClientTests(SimpleTestCase):
    def test_existing_user_key_gets_only_read_write_bucket_access(self):
        admin = GarageAdminClient("http://garage:3903", "admin-token")
        key = {
            "name": "ilosia-user-1",
            "accessKeyId": "user-access",
            "secretAccessKey": "user-secret",
        }
        with patch.object(
            admin,
            "_request",
            side_effect=[
                key,
                {
                    "buckets": [
                        {
                            "id": "bucket-id",
                            "globalAliases": ["user-1"],
                            "localAliases": [],
                        }
                    ]
                },
                {},
            ],
        ) as request:
            credentials = admin.ensure_bucket_access(
                bucket="user-1",
                key_name="ilosia-user-1",
                owner_access_key="platform-access",
            )

        self.assertEqual(credentials, ("user-access", "user-secret"))
        self.assertEqual(
            request.call_args_list[2].kwargs["payload"],
            {
                "bucketId": "bucket-id",
                "accessKeyId": "user-access",
                "permissions": {"read": True, "write": True, "owner": False},
            },
        )

    def test_missing_user_key_is_created(self):
        admin = GarageAdminClient("http://garage:3903", "admin-token")
        created = {
            "name": "ilosia-user-2",
            "accessKeyId": "other-access",
            "secretAccessKey": "other-secret",
        }
        with patch.object(
            admin,
            "_request",
            side_effect=[
                None,
                created,
                {
                    "buckets": [
                        {
                            "id": "bucket-id",
                            "globalAliases": [],
                            "localAliases": ["user-2"],
                        }
                    ]
                },
                {},
                {},
            ],
        ) as request:
            admin.ensure_bucket_access(
                bucket="user-2",
                key_name="ilosia-user-2",
                owner_access_key="platform-access",
            )

        self.assertEqual(request.call_args_list[1].args, ("CreateKey",))
        self.assertEqual(
            request.call_args_list[1].kwargs,
            {"method": "POST", "payload": {"name": "ilosia-user-2"}},
        )
        self.assertEqual(request.call_args_list[3].args, ("AddBucketAlias",))
        self.assertEqual(
            request.call_args_list[3].kwargs["payload"],
            {"bucketId": "bucket-id", "globalAlias": "user-2"},
        )

    def test_user_key_deletion_is_idempotent(self):
        admin = GarageAdminClient("http://garage:3903", "admin-token")
        key = {"name": "ilosia-user-2", "accessKeyId": "other-access"}
        with patch.object(admin, "_request", side_effect=[key, None]) as request:
            admin.delete_key("ilosia-user-2")

        self.assertEqual(request.call_args_list[1].args, ("DeleteKey",))
        self.assertEqual(
            request.call_args_list[1].kwargs,
            {"method": "POST", "query": {"id": "other-access"}},
        )

    def test_bucket_deletion_uses_its_garage_id(self):
        admin = GarageAdminClient("http://garage:3903", "admin-token")
        with patch.object(
            admin, "_request", side_effect=[{"id": "bucket-id"}, None, None]
        ) as request:
            admin.delete_bucket("user-2")

        self.assertEqual(request.call_args_list[1].args, ("DeleteBucket",))
        self.assertEqual(
            request.call_args_list[1].kwargs,
            {"method": "POST", "query": {"id": "bucket-id"}},
        )
        self.assertEqual(request.call_args_list[2].args, ("GetBucketInfo",))

    @patch("infrastructure.storage_client.urlopen")
    def test_empty_success_response_is_supported(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b""

        response = GarageAdminClient("http://garage:3903", "admin-token")._request(
            "DeleteKey", method="POST"
        )

        self.assertIsNone(response)

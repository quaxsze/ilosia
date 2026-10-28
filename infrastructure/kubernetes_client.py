import json
import os
import re
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .exceptions import ClusterUnavailableError

SERVICE_ACCOUNT_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount")
USER_NAMESPACE_PATTERN = re.compile(r"user-[1-9][0-9]*\Z")


class KubernetesClient:
    def __init__(self):
        host = os.environ.get("KUBERNETES_SERVICE_HOST")
        port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        self.base_url = f"https://{host}:{port}" if host else ""

    def list_pods(self, *, namespace, release_name):
        query = urlencode(
            {"labelSelector": f"app.kubernetes.io/instance={release_name}"}
        )
        try:
            payload = self._request(
                f"/api/v1/namespaces/{quote(namespace, safe='')}/pods?{query}"
            )
            return json.loads(payload)["items"]
        except (json.JSONDecodeError, KeyError) as error:
            raise ClusterUnavailableError("Invalid response from Kubernetes") from error

    def get_pod_logs(self, *, namespace, release_name, tail_lines=200):
        pods = self.list_pods(namespace=namespace, release_name=release_name)
        if not pods:
            return "No pod found for this service."
        pod = next(
            (item for item in pods if item.get("status", {}).get("phase") == "Running"),
            pods[0],
        )
        pod_name = pod["metadata"]["name"]
        query = urlencode({"container": "jupyter", "tailLines": tail_lines})
        return self._request(
            f"/api/v1/namespaces/{quote(namespace, safe='')}/pods/"
            f"{quote(pod_name, safe='')}/log?{query}"
        )

    def ensure_namespace(self, namespace, *, quota=None):
        if not USER_NAMESPACE_PATTERN.fullmatch(namespace):
            raise ValueError("User namespaces must use user-<positive id>.")
        self._request(
            "/api/v1/namespaces",
            method="POST",
            payload={
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": namespace,
                    "labels": {
                        "pod-security.kubernetes.io/enforce": "restricted",
                        "pod-security.kubernetes.io/enforce-version": "latest",
                        "pod-security.kubernetes.io/warn": "restricted",
                    },
                },
            },
            ignored_statuses={409},
        )
        platform_namespace = os.getenv("POD_NAMESPACE", "ilosia")
        service_account = os.getenv("PLATFORM_SERVICE_ACCOUNT", "ilosia-web")
        workload_role = os.getenv(
            "PLATFORM_WORKLOAD_CLUSTER_ROLE", "ilosia-user-workload"
        )
        self._request(
            f"/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings",
            method="POST",
            payload={
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {"name": f"{service_account}-workload"},
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "ClusterRole",
                    "name": workload_role,
                },
                "subjects": [
                    {
                        "kind": "ServiceAccount",
                        "name": service_account,
                        "namespace": platform_namespace,
                    }
                ],
            },
            ignored_statuses={409},
        )
        if quota:
            # shortcut: existing quotas are not mutated; recreate one only after changing limits.
            self._request(
                f"/api/v1/namespaces/{namespace}/resourcequotas",
                method="POST",
                payload={
                    "apiVersion": "v1",
                    "kind": "ResourceQuota",
                    "metadata": {"name": "user-quota"},
                    "spec": {"hard": quota},
                },
                ignored_statuses={409},
            )

    def create_secret(self, *, namespace, name, string_data, release_name):
        self._request(
            f"/api/v1/namespaces/{quote(namespace, safe='')}/secrets",
            method="POST",
            payload={
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": name,
                    "labels": {"app.kubernetes.io/instance": release_name},
                },
                "type": "Opaque",
                "stringData": string_data,
            },
        )

    def delete_secret(self, *, namespace, name):
        self._request(
            f"/api/v1/namespaces/{quote(namespace, safe='')}/secrets/"
            f"{quote(name, safe='')}",
            method="DELETE",
            ignored_statuses={404},
        )

    def _request(
        self, path, *, method="GET", payload=None, ignored_statuses=frozenset()
    ):
        try:
            token = (SERVICE_ACCOUNT_PATH / "token").read_text().strip()
            context = ssl.create_default_context(cafile=SERVICE_ACCOUNT_PATH / "ca.crt")
            headers = {"Authorization": f"Bearer {token}"}
            data = None
            if payload is not None:
                headers["Content-Type"] = "application/json"
                data = json.dumps(payload).encode()
            request = Request(
                f"{self.base_url}{path}",
                data=data,
                headers=headers,
                method=method,
            )
            with urlopen(request, context=context, timeout=5) as response:
                return response.read().decode()
        except HTTPError as error:
            if error.code in ignored_statuses:
                return error.read().decode()
            raise ClusterUnavailableError(str(error)) from error
        except (OSError, URLError) as error:
            raise ClusterUnavailableError(str(error)) from error

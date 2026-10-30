import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from django.conf import settings

from .exceptions import WarpgateError, WarpgateIdentityCollision


class WarpgateClient:
    def __init__(self, base_url=None, token=None, ca_bundle=None):
        base_url = (base_url or settings.WARPGATE_URL).rstrip("/")
        if urlsplit(base_url).scheme != "https":
            raise WarpgateError("Warpgate administration requires HTTPS.")
        self.base_url = f"{base_url}/@warpgate/admin/api"
        self.token = token if token is not None else settings.WARPGATE_API_TOKEN
        try:
            self.context = ssl.create_default_context(
                cafile=ca_bundle or settings.WARPGATE_CA_BUNDLE or None
            )
        except OSError as error:
            raise WarpgateError("The Warpgate CA bundle cannot be loaded.") from error

    def ensure_user(self, *, username, description):
        for attempt in range(2):
            users = self._list(f"/users?{urlencode({'search': username})}")
            user = self._exact(users, "username", username)
            if user:
                body = {
                    "username": username,
                    "description": description,
                    "credential_policy": {
                        "http": ["Sso"],
                        "ssh": ["WebUserApproval"],
                    },
                }
                for field in ("rate_limit_bytes_per_second", "allowed_ip_ranges"):
                    if user.get(field) is not None:
                        body[field] = user[field]
                return self._object(
                    self._request("PUT", f"/users/{quote(user['id'])}", body)
                )
            try:
                self._request(
                    "POST",
                    "/users",
                    {"username": username, "description": description},
                )
            except WarpgateError as error:
                if error.status_code != 409 or attempt:
                    raise
        raise WarpgateError(f"Could not converge Warpgate user {username}.")

    def ensure_sso_credential(self, *, user, provider, email):
        desired_email = email.casefold()
        for attempt in range(2):
            users = self._list("/users")
            credentials_by_user = {
                item["id"]: self._list(f"/users/{quote(item['id'])}/credentials/sso")
                for item in users
            }
            for item in users:
                for credential in credentials_by_user[item["id"]]:
                    if (
                        credential.get("provider") == provider
                        and str(credential.get("email", "")).casefold() == desired_email
                        and item["id"] != user["id"]
                    ):
                        raise WarpgateIdentityCollision(
                            "This verified email is already assigned in Warpgate."
                        )

            credentials = [
                item
                for item in credentials_by_user.get(user["id"], [])
                if item.get("provider") == provider
            ]
            if len(credentials) > 1:
                raise WarpgateError("Multiple SSO credentials use the same provider.")
            body = {"provider": provider, "email": email}
            if credentials:
                credential = credentials[0]
                if credential.get("email") == email:
                    return credential
                return self._object(
                    self._request(
                        "PUT",
                        f"/users/{quote(user['id'])}/credentials/sso/"
                        f"{quote(credential['id'])}",
                        body,
                    )
                )
            try:
                return self._object(
                    self._request(
                        "POST",
                        f"/users/{quote(user['id'])}/credentials/sso",
                        body,
                    )
                )
            except WarpgateError as error:
                if error.status_code != 409 or attempt:
                    raise
        raise WarpgateError("Could not converge the Warpgate SSO credential.")

    def ensure_role(self, *, name, description):
        for attempt in range(2):
            roles = self._list(f"/roles?{urlencode({'search': name})}")
            role = self._exact(roles, "name", name)
            if role:
                if role.get("description") != description:
                    return self._object(
                        self._request(
                            "PUT",
                            f"/roles/{quote(role['id'])}",
                            {"name": name, "description": description},
                        )
                    )
                return role
            try:
                return self._object(
                    self._request(
                        "POST", "/roles", {"name": name, "description": description}
                    )
                )
            except WarpgateError as error:
                if error.status_code != 409 or attempt:
                    raise
        raise WarpgateError(f"Could not converge Warpgate role {name}.")

    def ensure_user_role(self, *, user, role):
        roles = self._list(f"/users/{quote(user['id'])}/roles")
        if not any(item.get("id") == role["id"] for item in roles):
            self._request(
                "POST",
                f"/users/{quote(user['id'])}/roles/{quote(role['id'])}",
            )

    def ensure_ssh_target(self, *, name, host, description):
        body = {
            "name": name,
            "description": description,
            "require_approval": False,
            "ticket_requests_disabled": False,
            "ticket_require_approval": False,
            "options": {
                "kind": "Ssh",
                "host": host,
                "port": 2222,
                "username": "developer",
                "allow_insecure_algos": False,
                "auth": {"kind": "PublicKey"},
            },
        }
        for attempt in range(2):
            targets = self._list(f"/targets?{urlencode({'search': name})}")
            target = self._exact(targets, "name", name)
            try:
                if target:
                    return self._object(
                        self._request("PUT", f"/targets/{quote(target['id'])}", body)
                    )
                return self._object(self._request("POST", "/targets", body))
            except WarpgateError as error:
                if error.status_code != 409 or attempt:
                    raise
        raise WarpgateError(f"Could not converge Warpgate target {name}.")

    def ensure_target_role(self, *, target, role):
        roles = self._list(f"/targets/{quote(target['id'])}/roles")
        if not any(item.get("id") == role["id"] for item in roles):
            self._request(
                "POST",
                f"/targets/{quote(target['id'])}/roles/{quote(role['id'])}",
            )

    def _list(self, path):
        response = self._request("GET", path)
        if not isinstance(response, list):
            raise WarpgateError("Warpgate returned an invalid list response.")
        return response

    @staticmethod
    def _exact(items, field, value):
        matches = [item for item in items if item.get(field) == value]
        if len(matches) > 1:
            raise WarpgateError(f"Warpgate returned duplicate {field} values.")
        return matches[0] if matches else None

    @staticmethod
    def _object(response):
        if not isinstance(response, dict) or not response.get("id"):
            raise WarpgateError("Warpgate returned an invalid object response.")
        return response

    def _request(self, method, path, payload=None):
        if not self.token:
            raise WarpgateError("WARPGATE_API_TOKEN is not configured.")
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"x-warpgate-token": self.token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urlopen(request, context=self.context, timeout=5) as response:
                body = response.read()
        except HTTPError as error:
            raise WarpgateError(
                f"Warpgate API request failed with HTTP {error.code}.",
                status_code=error.code,
            ) from error
        except (OSError, URLError) as error:
            raise WarpgateError("Warpgate API is unavailable.") from error
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise WarpgateError("Warpgate returned invalid JSON.") from error

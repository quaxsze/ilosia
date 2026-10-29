import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from .exceptions import StorageError


def user_bucket(user):
    return f"user-{user.pk}"


class GarageAdminClient:
    def __init__(self, endpoint_url=None, token=None):
        self.endpoint_url = (endpoint_url or settings.GARAGE_ADMIN_ENDPOINT_URL).rstrip(
            "/"
        )
        self.token = token or settings.GARAGE_ADMIN_TOKEN

    def ensure_bucket_access(self, *, bucket, key_name, owner_access_key):
        key = self._request(
            "GetKeyInfo",
            query={"search": key_name, "showSecretKey": "true"},
            ignored_statuses={404},
        )
        if key is None:
            key = self._request("CreateKey", method="POST", payload={"name": key_name})
        if not isinstance(key, dict) or key.get("name") != key_name:
            raise StorageError("Garage returned an unexpected access key")

        owner = self._request("GetKeyInfo", query={"id": owner_access_key})
        buckets = owner.get("buckets", []) if isinstance(owner, dict) else []
        bucket_info = next(
            (
                item
                for item in buckets
                if bucket
                in item.get("globalAliases", []) + item.get("localAliases", [])
            ),
            None,
        )
        bucket_id = bucket_info.get("id") if bucket_info else None
        access_key = key.get("accessKeyId")
        secret_key = key.get("secretAccessKey")
        if not all((bucket_id, access_key, secret_key)):
            raise StorageError("Garage returned incomplete access credentials")
        if bucket not in bucket_info.get("globalAliases", []):
            self._request(
                "AddBucketAlias",
                method="POST",
                payload={"bucketId": bucket_id, "globalAlias": bucket},
            )
        self._request(
            "AllowBucketKey",
            method="POST",
            payload={
                "bucketId": bucket_id,
                "accessKeyId": access_key,
                "permissions": {"read": True, "write": True, "owner": False},
            },
        )
        return access_key, secret_key

    def delete_key(self, key_name):
        key = self._request(
            "GetKeyInfo",
            query={"search": key_name},
            ignored_statuses={404},
        )
        if key is None:
            return
        if (
            not isinstance(key, dict)
            or key.get("name") != key_name
            or not key.get("accessKeyId")
        ):
            raise StorageError("Garage returned an unexpected access key")
        self._request(
            "DeleteKey",
            method="POST",
            query={"id": key["accessKeyId"]},
        )

    def delete_bucket(self, bucket):
        bucket_info = self._request(
            "GetBucketInfo",
            query={"globalAlias": bucket},
            ignored_statuses={404},
        )
        if bucket_info is None:
            return
        if not isinstance(bucket_info, dict) or not bucket_info.get("id"):
            raise StorageError("Garage returned an unexpected bucket")
        self._request(
            "DeleteBucket",
            method="POST",
            query={"id": bucket_info["id"]},
        )
        if (
            self._request(
                "GetBucketInfo",
                query={"globalAlias": bucket},
                ignored_statuses={404},
            )
            is not None
        ):
            raise StorageError("Garage bucket still exists after deletion")

    def _request(
        self,
        operation,
        *,
        method="GET",
        query=None,
        payload=None,
        ignored_statuses=frozenset(),
    ):
        if not self.endpoint_url or not self.token:
            raise StorageError("Garage administration is not configured")
        url = f"{self.endpoint_url}/v2/{operation}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        try:
            with urlopen(
                Request(url, data=data, headers=headers, method=method), timeout=5
            ) as response:
                body = response.read()
                return json.loads(body) if body else None
        except HTTPError as error:
            if error.code in ignored_statuses:
                return None
            raise StorageError(
                f"Garage administration failed for {operation} ({error.code})"
            ) from error
        except (json.JSONDecodeError, OSError, URLError) as error:
            raise StorageError(
                f"Garage administration failed for {operation}"
            ) from error


class StorageClient:
    def __init__(self, client=None, public_client=None):
        self.client = client or self._client(settings.S3_ENDPOINT_URL)
        self.public_client = public_client or self._client(
            settings.S3_PUBLIC_ENDPOINT_URL or settings.S3_ENDPOINT_URL
        )

    def _client(self, endpoint_url):
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self, bucket):
        try:
            self.client.head_bucket(Bucket=bucket)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise StorageError(str(error)) from error
            try:
                self.client.create_bucket(Bucket=bucket)
            except (BotoCoreError, ClientError) as create_error:
                raise StorageError(str(create_error)) from create_error
        except BotoCoreError as error:
            raise StorageError(str(error)) from error

    def list_objects(self, bucket):
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            return [
                item
                for page in paginator.paginate(Bucket=bucket)
                for item in page.get("Contents", [])
            ]
        except (BotoCoreError, ClientError) as error:
            raise StorageError(str(error)) from error

    def upload_object(self, bucket, key, file_object):
        try:
            self.client.upload_fileobj(file_object, bucket, key)
        except (BotoCoreError, ClientError) as error:
            raise StorageError(str(error)) from error

    def delete_object(self, bucket, key):
        try:
            self.client.delete_object(Bucket=bucket, Key=key)
        except (BotoCoreError, ClientError) as error:
            raise StorageError(str(error)) from error

    def generate_presigned_url(self, bucket, key, expires_in=300):
        try:
            signed_url = self.public_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            if not settings.S3_BROWSER_ENDPOINT_URL:
                return signed_url
            signed = urlsplit(signed_url)
            browser = urlsplit(settings.S3_BROWSER_ENDPOINT_URL)
            return urlunsplit(
                (browser.scheme, browser.netloc, signed.path, signed.query, "")
            )
        except (BotoCoreError, ClientError) as error:
            raise StorageError(str(error)) from error

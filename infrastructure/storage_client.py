from urllib.parse import urlsplit, urlunsplit

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from .exceptions import StorageError


def user_bucket(user):
    return f"user-{user.pk}"


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

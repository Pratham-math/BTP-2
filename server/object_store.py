"""Private S3-compatible objects; asset authorization happens before signing."""
import re
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from server.providers.base import GenerationError


class ObjectStore:
    def __init__(self, settings):
        self.settings = settings
        self._client = None

    @property
    def client(self):
        settings = self.settings
        if not all((settings.s3_endpoint, settings.s3_bucket, settings.s3_access_key, settings.s3_secret_key)):
            raise GenerationError("STORAGE_NOT_CONFIGURED", "Configure a private S3/R2 bucket on the backend.")
        if urlsplit(settings.s3_endpoint).scheme != "https":
            raise GenerationError("STORAGE_NOT_CONFIGURED", "Private storage requires an HTTPS endpoint.")
        if self._client is None:
            self._client = boto3.client("s3", endpoint_url=settings.s3_endpoint,
                aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key,
                region_name="auto", config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=60,
                                                   retries={"max_attempts": 2, "mode": "standard"}))
        return self._client

    @staticmethod
    def key(value):
        if not re.fullmatch(r"[a-zA-Z0-9_./-]{1,400}", value) or ".." in value or value.startswith("/"):
            raise ValueError("Invalid private object key")
        return value

    def put(self, key, path, mime):
        try:
            self.client.upload_file(str(path), self.settings.s3_bucket, self.key(key), ExtraArgs={"ContentType": mime, "CacheControl": "private,max-age=300"})
        except (BotoCoreError, ClientError):
            raise GenerationError("STORAGE_FAILED", "Private storage could not save this object. Check the bucket and its scoped credentials.") from None

    def download(self, key, path, limit):
        try:
            head = self.client.head_object(Bucket=self.settings.s3_bucket, Key=self.key(key))
            if head["ContentLength"] > limit:
                raise GenerationError("SOURCE_TOO_LARGE", "This source exceeds the configured upload size.")
            self.client.download_file(self.settings.s3_bucket, key, str(path))
        except (BotoCoreError, ClientError):
            raise GenerationError("STORAGE_FAILED", "Private storage could not retrieve this source. Retry after checking its configuration.") from None

    def sign(self, key, *, expires=300):
        try:
            return self.client.generate_presigned_url("get_object", Params={"Bucket": self.settings.s3_bucket, "Key": self.key(key)}, ExpiresIn=expires)
        except (BotoCoreError, ClientError):
            raise GenerationError("STORAGE_FAILED", "Private storage access is temporarily unavailable. Retry to renew the media link.") from None

    def delete(self, key):
        try:
            self.client.delete_object(Bucket=self.settings.s3_bucket, Key=self.key(key))
        except (BotoCoreError, ClientError):
            raise GenerationError("STORAGE_FAILED", "The original could not be deleted. No deletion has been confirmed; retry after checking storage.") from None

    def list_prefix(self, prefix, *, limit=20000):
        """Bounded maintenance inventory of one exact owner/version namespace."""
        self.key(prefix)
        if not prefix.endswith('/') or len(prefix.split('/')) < 3:
            raise ValueError('Maintenance needs a narrow object prefix')
        keys, continuation = [], None
        try:
            while True:
                args = {'Bucket': self.settings.s3_bucket, 'Prefix': prefix, 'MaxKeys': 1000}
                if continuation:
                    args['ContinuationToken'] = continuation
                page = self.client.list_objects_v2(**args)
                for entry in page.get('Contents', []):
                    key = self.key(entry['Key'])
                    if not key.startswith(prefix):
                        raise GenerationError('INVALID_STORAGE_INVENTORY', 'Storage returned an object outside the exact maintenance namespace.')
                    keys.append(key)
                    if len(keys) > limit:
                        raise GenerationError('ERASURE_BATCH_REQUIRED', 'The object inventory needs an operator-reviewed cleanup batch. No incomplete deletion was confirmed.')
                if not page.get('IsTruncated'):
                    return keys
                next_token = page.get('NextContinuationToken')
                if not next_token or next_token == continuation:
                    raise GenerationError('INVALID_STORAGE_INVENTORY', 'Storage did not provide a complete bounded inventory.')
                continuation = next_token
        except (BotoCoreError, ClientError):
            raise GenerationError('STORAGE_FAILED', 'Private storage inventory is temporarily unavailable. No complete erasure was confirmed.') from None

    def empty(self):
        """Operator restore precondition; never exposes an object inventory."""
        try:
            return not self.client.list_objects_v2(Bucket=self.settings.s3_bucket, MaxKeys=1).get("Contents")
        except (BotoCoreError, ClientError):
            raise GenerationError("STORAGE_FAILED", "Could not verify that the restore bucket is empty.") from None

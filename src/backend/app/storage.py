"""The private object store module assets live in.

S3 in a real deployment, LocalStack's S3 emulation locally — the same boto3
calls either way, exactly as `app.security.mailer` treats SES.

Two things this module exists to keep in one place:

* **Nothing is ever public.** The bucket blocks public access and every read is
  a presigned URL with a short TTL, minted only after the API has authorized
  the caller. There is no code path here that makes an object readable without
  a signature.
* **boto3 is blocking.** Every call is offloaded to a thread, so an upload does
  not stall the event loop every other request shares.
"""

from typing import Any, Protocol
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings


class S3Client(Protocol):
    def put_object(self, **kwargs: Any) -> Any: ...

    def delete_object(self, **kwargs: Any) -> Any: ...

    def generate_presigned_url(self, operation: str, **kwargs: Any) -> str: ...


def object_key(module_id: Any, asset_id: Any) -> str:
    """`modules/{module_id}/assets/{asset_id}` — both opaque UUIDs.

    Namespaced by module so a module's objects can be purged as a prefix, and
    built from UUIDs rather than titles or filenames so nothing about a
    module's content makes another asset's key guessable.
    """
    return f"modules/{module_id}/assets/{asset_id}"


# What an attachment is served as, whatever it actually is. S3 cannot emit an
# `X-Content-Type-Options: nosniff` response header on an object, so "a
# non-sniffable content type" has to be achieved by the type itself: an
# `application/octet-stream` carrying `Content-Disposition: attachment` is
# downloaded by every browser rather than rendered, so there is no content-type
# for a sniffing heuristic to disagree with in the first place. The true sniffed
# type stays on the database row, which is what the authoring UI displays, and
# the filename extension is what the recipient's OS opens the saved file with.
#
# Images are the deliberate exception: they have to render, so they keep their
# real type — which is safe precisely because it is one of four image types the
# sniffer verified from the bytes, delivered under a CSP that only permits them
# in an image context.
ATTACHMENT_DELIVERY_TYPE = "application/octet-stream"


async def put_asset(
    s3_client: S3Client,
    *,
    key: str,
    data: bytes,
    content_type: str,
    download_filename: str | None = None,
) -> None:
    """Store an object, encrypted at rest.

    `download_filename` is set for attachments only. It makes the object arrive
    as a download rather than rendering in the tab, and — with the
    octet-stream type above — is what "served as an attachment with a
    non-sniffable content type" means in practice. Both are stored *on the
    object* rather than added to the presigned URL at read time, so the headers
    hold however the object is later fetched.
    """
    settings = get_settings()
    is_attachment = download_filename is not None
    arguments: dict[str, Any] = {
        "Bucket": settings.assets_bucket,
        "Key": key,
        "Body": data,
        "ContentType": ATTACHMENT_DELIVERY_TYPE if is_attachment else content_type,
        # Belt and braces next to the bucket's own default encryption: an
        # object written here is encrypted even if that default is ever lost.
        "ServerSideEncryption": "AES256",
    }
    if download_filename is not None:
        arguments["ContentDisposition"] = _attachment_disposition(download_filename)

    def _put() -> None:
        s3_client.put_object(**arguments)

    await run_in_threadpool(_put)


async def delete_asset(s3_client: S3Client, *, key: str) -> None:
    settings = get_settings()

    def _delete() -> None:
        s3_client.delete_object(Bucket=settings.assets_bucket, Key=key)

    await run_in_threadpool(_delete)


async def presigned_asset_url(s3_client: S3Client, *, key: str) -> str:
    """A short-lived, signed URL for one object.

    Minted only after the caller has been authorized against the module, and
    valid for `asset_url_ttl_seconds` — 5 minutes by default.
    """
    settings = get_settings()

    def _sign() -> str:
        return s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.assets_bucket, "Key": key},
            ExpiresIn=settings.asset_url_ttl_seconds,
        )

    return await run_in_threadpool(_sign)


def _attachment_disposition(filename: str) -> str:
    """RFC 6266 `Content-Disposition` for a download.

    Both forms: a conservatively-transliterated ASCII `filename` for older
    clients and a percent-encoded `filename*` carrying the real name. The
    filename reaching here has already been reduced to a control-character-free
    basename by `app.content.uploads`, and both forms are escaped again anyway
    — a name is never interpolated into a header on trust alone.
    """
    ascii_name = filename.encode("ascii", errors="replace").decode("ascii")
    # `"` and `\` would end or escape out of the quoted-string; nothing else in
    # a basename can.
    ascii_name = ascii_name.replace("\\", "_").replace('"', "_")
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


async def ensure_assets_bucket(s3_client: S3Client) -> None:
    """Create the local bucket if it isn't there yet — LocalStack only.

    In a real deployment terraform owns the bucket, its public-access block,
    its encryption, and its versioning; the task role has no permission to
    create one. This runs only when an endpoint override is configured, which
    is what "we are pointed at LocalStack" means here.
    """
    settings = get_settings()
    if not settings.aws_endpoint_url:
        return

    def _create() -> None:
        client: Any = s3_client
        try:
            client.create_bucket(
                Bucket=settings.assets_bucket,
                CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
            )
        except Exception as error:  # already exists, or owned by us already
            if "BucketAlreadyOwnedByYou" not in str(error) and "BucketAlreadyExists" not in str(
                error
            ):
                raise
        # Mirrors what terraform sets in production, so the local environment
        # is not accidentally more permissive than the deployed one.
        client.put_public_access_block(
            Bucket=settings.assets_bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        client.put_bucket_encryption(
            Bucket=settings.assets_bucket,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                ]
            },
        )

    await run_in_threadpool(_create)

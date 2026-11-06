import os
import uuid
from urllib.parse import quote

import requests


MAX_IMAGE_BYTES = 64 * 1024


class BlobStorageError(RuntimeError):
    pass


def _sdk():
    try:
        from vercel.blob import sync
    except ImportError:
        return None
    return sync


def _credentials():
    token = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
    parts = token.split("_")
    if len(parts) < 5 or parts[:3] != ["vercel", "blob", "rw"] or not parts[3]:
        raise BlobStorageError("blob_credentials_unavailable")
    return token, parts[3]


def _api_headers(token, store_id):
    return {
        "Authorization": f"Bearer {token}",
        "x-api-blob-request-id": str(uuid.uuid4()),
        "x-vercel-blob-store-id": store_id,
        "x-api-blob-request-attempt": "0",
        "x-api-version": "13",
    }


def _upload_with_http(pathname, content_type, content):
    token, store_id = _credentials()
    headers = {
        **_api_headers(token, store_id),
        "x-vercel-blob-access": "private",
        "x-content-type": content_type,
        "x-add-random-suffix": "true",
        "Content-Type": "application/octet-stream",
    }
    try:
        response = requests.put(
            "https://vercel.com/api/blob/",
            params={"pathname": pathname},
            data=content,
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
        result = response.json()
        result_path = result.get("pathname")
        if not isinstance(result_path, str) or not result_path:
            raise ValueError("missing pathname")
        return result_path
    except Exception:
        raise BlobStorageError("blob_upload_failed") from None


def _download_with_http(pathname):
    token, store_id = _credentials()
    url = f"https://{store_id}.private.blob.vercel-storage.com/{quote(pathname, safe='/')}"
    response = None
    try:
        response = requests.get(
            url,
            headers=_api_headers(token, store_id),
            stream=True,
            timeout=20,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise BlobStorageError("invalid_image_type")
        content = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            content.extend(chunk)
            if len(content) > MAX_IMAGE_BYTES:
                raise BlobStorageError("invalid_image_size")
        return content_type, bytes(content)
    except BlobStorageError:
        raise
    except Exception:
        raise BlobStorageError("blob_download_failed") from None
    finally:
        if response is not None:
            response.close()


def _delete_with_http(pathname):
    token, store_id = _credentials()
    headers = {**_api_headers(token, store_id), "Content-Type": "application/json"}
    try:
        response = requests.post(
            "https://vercel.com/api/blob/delete",
            json={"urls": [pathname]},
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
    except Exception:
        raise BlobStorageError("blob_delete_failed") from None


def upload_image(event_id, image_id, content_type, content):
    extensions = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
    extension = extensions.get(content_type)
    if not extension:
        raise BlobStorageError("invalid_image_type")
    pathname = f"calendar/{event_id}/{image_id}.{extension}"
    sdk = _sdk()
    if sdk is None:
        return _upload_with_http(pathname, content_type, content)
    try:
        result = sdk.put_blob(
            pathname,
            content,
            access="private",
            content_type=content_type,
            add_random_suffix=True,
        )
    except Exception:
        raise BlobStorageError("blob_upload_failed") from None
    return result.pathname


def download_image(pathname):
    sdk = _sdk()
    if sdk is None:
        return _download_with_http(pathname)
    try:
        result = sdk.get_blob(pathname, access="private")
        if result.metadata.content_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise BlobStorageError("invalid_image_type")
    except BlobStorageError:
        raise
    except Exception:
        raise BlobStorageError("blob_download_failed") from None
    return result.metadata.content_type, result.body


def delete_image(pathname):
    sdk = _sdk()
    if sdk is None:
        return _delete_with_http(pathname)
    try:
        sdk.delete_blob(pathname)
    except Exception:
        raise BlobStorageError("blob_delete_failed") from None


def new_image_id():
    return str(uuid.uuid4())
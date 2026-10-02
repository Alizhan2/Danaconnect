"""Private attachment storage. Keys are opaque; no presigned public URLs."""
import hashlib
import io
import os
import re
import unicodedata
import zipfile
import json
import httpx
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote, urlsplit

from app.config import settings
from app.blob_configuration import blob_store_identity


class StorageUnavailable(RuntimeError):
    pass


class InvalidAttachment(ValueError):
    pass


TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".txt": "text/plain", ".md": "text/plain", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def inspect_attachment(filename: str, content_type: str, data: bytes):
    if not data or len(data) > settings.upload_max_bytes:
        raise InvalidAttachment("Файл пуст или превышает допустимый размер")
    filename = unicodedata.normalize("NFKC", filename or "")
    if not filename or len(filename) > 180 or any(ord(character) < 32 or character in '/\\:<>"|?*' or ord(character) in {*range(0x202A, 0x202F), *range(0x2066, 0x206A)} for character in filename) or filename.startswith("."):
        raise InvalidAttachment("Недопустимое имя файла")
    suffix = Path(filename).suffix.lower()
    expected = TYPES.get(suffix)
    actual = content_type.split(";", 1)[0].strip().lower()
    if not expected or actual not in {expected, "application/octet-stream", "text/markdown" if suffix == ".md" else expected}:
        raise InvalidAttachment("Допустимы PDF, PNG, JPG, TXT, MD и DOCX")
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
            raise InvalidAttachment("Сигнатура PDF не соответствует содержимому")
        if any(token in data for token in (b"/JavaScript", b"/Launch", b"/EmbeddedFile", b"/JS ")):
            raise InvalidAttachment("PDF с исполняемыми действиями или вложениями не допускается")
    elif suffix == ".png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or not data.endswith(b"IEND\xaeB`\x82"):
            raise InvalidAttachment("Сигнатура PNG не соответствует содержимому")
    elif suffix in {".jpg", ".jpeg"}:
        if not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
            raise InvalidAttachment("Сигнатура JPG не соответствует содержимому")
    elif suffix in {".txt", ".md"}:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise InvalidAttachment("Текстовый файл должен использовать UTF-8") from None
        if b"\x00" in data:
            raise InvalidAttachment("Двоичный файл нельзя загрузить как текст")
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as document:
                items = document.infolist()
                names = {item.filename for item in items}
                if not {"[Content_Types].xml", "word/document.xml"} <= names or len(items) > 1000:
                    raise InvalidAttachment("Недопустимая структура DOCX")
                if sum(item.file_size for item in items) > 30 * 1024 * 1024 or any(item.file_size > 5 * 1024 * 1024 or item.flag_bits & 1 or item.filename.startswith("/") or ".." in Path(item.filename).parts for item in items):
                    raise InvalidAttachment("DOCX превышает ограничения распаковки")
                if any("vbaproject" in name.lower() or name.startswith("word/embeddings/") for name in names):
                    raise InvalidAttachment("DOCX с макросами или встроенными объектами не допускается")
                for item in items:
                    if item.filename.endswith((".rels", ".xml")):
                        xml = document.read(item)
                        if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                            raise InvalidAttachment("Недопустимая структура DOCX")
                        if b"macroenabled" in xml.lower() or b"vbaproject" in xml.lower():
                            raise InvalidAttachment("DOCX с макросами или встроенными объектами не допускается")
                        if item.filename.endswith(".rels") and re.search(br"TargetMode\s*=\s*['\"]External['\"]", xml, re.IGNORECASE):
                            raise InvalidAttachment("DOCX с внешними ресурсами не допускается")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
            raise InvalidAttachment("Сигнатура DOCX не соответствует содержимому") from None
    return filename, expected, hashlib.sha256(data).hexdigest()


def storage_ready():
    if settings.storage_provider == "local":
        return settings.environment != "production" and bool(settings.private_upload_dir)
    if settings.storage_provider == "blob":
        return blob_store_identity(settings.blob_store_id, settings.blob_read_write_token) is not None
    return settings.storage_provider == "s3" and bool(settings.s3_bucket)


def _blob_url(key):
    _key_valid(key)
    identity = blob_store_identity(settings.blob_store_id, settings.blob_read_write_token)
    if identity is None:
        raise StorageUnavailable("storage_unconfigured")
    return f"https://{identity}.private.blob.vercel-storage.com/{key}"


def _bounded_body(response, maximum):
    """Reject oversized/encoded responses without buffering an unbounded body."""
    if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
        raise StorageUnavailable("storage_response_invalid")
    declared = response.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > maximum):
        raise StorageUnavailable("storage_response_exceeds_limit")
    data = bytearray()
    for chunk in response.iter_raw(chunk_size=16384):
        remaining = maximum - len(data)
        if len(chunk) > remaining:
            raise StorageUnavailable("storage_response_exceeds_limit")
        data.extend(chunk)
    return bytes(data)


def _blob_control(method, key, *, data=None, content_type=None):
    """SDK v11 wire protocol, fixed control plane; no retries of ambiguous writes."""
    url = _blob_url(key)
    headers = {"Authorization": "Bearer " + settings.blob_read_write_token,
               "Accept-Encoding": "identity", "x-api-version": "11"}
    options = {}
    endpoint = "https://vercel.com/api/blob"
    if method == "PUT":
        headers.update({"Content-Type": "application/octet-stream", "x-content-type": content_type,
                        "x-vercel-blob-access": "private", "x-add-random-suffix": "0",
                        "x-allow-overwrite": "0", "x-cache-control-max-age": "60"})
        options = {"params": {"pathname": key}, "content": data}
    elif method == "POST":
        endpoint += "/delete"
        options = {"json": {"urls": [url]}}
    else:
        raise StorageUnavailable("storage_operation_invalid")
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        with client.stream(method, endpoint, headers=headers, **options) as response:
            if response.status_code not in {200, 201, 204}:
                raise StorageUnavailable("storage_provider_rejected")
            body = _bounded_body(response, 16384)
    if method == "PUT":
        result = json.loads(body)
        if not isinstance(result, dict) or result.get("pathname") != key or not isinstance(result.get("url"), str):
            raise StorageUnavailable("storage_write_receipt_invalid")
        receipt = urlsplit(result["url"])
        expected = urlsplit(url)
        if (receipt.scheme != "https" or receipt.netloc.lower() != expected.netloc
                or receipt.path != expected.path or receipt.query or receipt.fragment):
            raise StorageUnavailable("storage_write_receipt_invalid")


def _blob_read(key, expected_size):
    headers = {"Authorization": "Bearer " + settings.blob_read_write_token,
               "Accept-Encoding": "identity", "Cache-Control": "no-cache"}
    # Store credentials go only to the validated canonical private host.
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", _blob_url(key), headers=headers) as response:
            if response.status_code != 200:
                raise StorageUnavailable("storage_provider_rejected")
            return _bounded_body(response, expected_size + 1)


def _key_valid(key):
    if not re.fullmatch(r"attachments/[a-f0-9]{32}", key):
        raise StorageUnavailable("invalid_storage_key")


def _local_path(key):
    _key_valid(key)
    root = Path(settings.private_upload_dir).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise StorageUnavailable("invalid_storage_path")
    return path


def _s3():
    if not settings.s3_bucket:
        raise StorageUnavailable("storage_unconfigured")
    try:
        import boto3
        return boto3.client("s3", region_name=settings.s3_region or None, endpoint_url=settings.s3_endpoint_url or None)
    except Exception:
        raise StorageUnavailable("storage_unavailable") from None


def put_private(data: bytes, content_type: str):
    if not storage_ready():
        raise StorageUnavailable("storage_unconfigured")
    if not data or len(data) > settings.upload_max_bytes or content_type not in TYPES.values():
        raise StorageUnavailable("storage_input_invalid")
    key = "attachments/" + uuid4().hex
    provider = settings.storage_provider
    try:
        if provider == "local":
            path = _local_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
        elif provider == "blob":
            _blob_control("PUT", key, data=data, content_type=content_type)
        elif provider == "s3":
            options = {"Bucket": settings.s3_bucket, "Key": key, "Body": data, "ContentType": content_type, "ServerSideEncryption": settings.s3_sse, "CacheControl": "private, no-store"}
            if settings.s3_sse == "aws:kms":
                if not settings.s3_kms_key_id:
                    raise StorageUnavailable("kms_unconfigured")
                options["SSEKMSKeyId"] = settings.s3_kms_key_id
            client = _s3()
            block = client.get_public_access_block(Bucket=settings.s3_bucket).get("PublicAccessBlockConfiguration", {})
            if not all(block.get(key) is True for key in ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"]):
                raise StorageUnavailable("bucket_public_access_not_blocked")
            client.put_object(**options)
        else:
            raise StorageUnavailable("invalid_storage_provider")
    except StorageUnavailable:
        raise
    except Exception:
        raise StorageUnavailable("storage_write_failed") from None
    return provider, key


def read_private(provider: str, key: str, expected_size: int):
    _key_valid(key)
    if not isinstance(expected_size, int) or expected_size <= 0 or expected_size > settings.upload_max_bytes:
        raise StorageUnavailable("stored_file_exceeds_limit")
    try:
        if provider == "local":
            if settings.environment == "production":
                raise StorageUnavailable("local_storage_forbidden")
            with _local_path(key).open("rb") as file:
                data = file.read(expected_size + 1)
        elif provider == "s3":
            stream = _s3().get_object(Bucket=settings.s3_bucket, Key=key)["Body"]
            try:
                data = stream.read(expected_size + 1)
            finally:
                stream.close()
        elif provider == "blob":
            data = _blob_read(key, expected_size)
        else:
            raise StorageUnavailable("invalid_storage_provider")
        if len(data) != expected_size:
            raise StorageUnavailable("stored_file_integrity_mismatch")
        return data
    except StorageUnavailable:
        raise
    except Exception:
        raise StorageUnavailable("storage_read_failed") from None


def delete_private(provider: str, key: str):
    _key_valid(key)
    try:
        if provider == "local":
            _local_path(key).unlink(missing_ok=True)
        elif provider == "s3":
            _s3().delete_object(Bucket=settings.s3_bucket, Key=key)
        elif provider == "blob":
            _blob_control("POST", key)
        else:
            raise StorageUnavailable("invalid_storage_provider")
    except Exception:
        raise StorageUnavailable("storage_delete_failed") from None


def download_disposition(filename: str):
    # ASCII fallback and RFC5987 encoded Unicode; never interpolate raw headers.
    fallback = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)[:150] or "attachment"
    return 'attachment; filename="' + fallback + '"; filename*=UTF-8\'\'' + quote(filename, safe="")

import os
import threading
from io import BytesIO
from typing import Dict, Optional, Set, Tuple

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ModuleNotFoundError:
    boto3 = None

    class BotoCoreError(Exception):
        pass

    class ClientError(Exception):
        pass

from music_server.config import MUSIC_FOLDER, S3_BUCKET, S3_ENDPOINT_URL, S3_PREFIX, S3_REGION, STORAGE_MODE, VALID_GENRES

_s3_client = None
_index_lock = threading.Lock()
_filename_index: Optional[Dict[str, Tuple[str, str]]] = None
_available_names: Optional[Set[str]] = None


def is_s3_mode() -> bool:
    return STORAGE_MODE == 's3' and bool(S3_BUCKET)


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        if boto3 is None:
            raise RuntimeError('boto3 is required for STORAGE_MODE=s3')
        _s3_client = boto3.client('s3', region_name=S3_REGION, endpoint_url=S3_ENDPOINT_URL)
    return _s3_client


def _s3_key(genre: str, filename: str) -> str:
    if S3_PREFIX:
        return f'{S3_PREFIX}/{genre}/{filename}'
    return f'{genre}/{filename}'


def _refresh_s3_index() -> None:
    global _filename_index
    global _available_names

    client = _get_s3_client()
    prefix = (S3_PREFIX + '/') if S3_PREFIX else ''
    paginator = client.get_paginator('list_objects_v2')
    index: Dict[str, Tuple[str, str]] = {}
    names: Set[str] = set()

    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get('Contents', []):
            key = obj.get('Key', '')
            if not key or key.endswith('/'):
                continue
            relative = key[len(prefix):] if prefix and key.startswith(prefix) else key
            parts = relative.split('/')
            if len(parts) < 2:
                continue
            genre = parts[0]
            filename = parts[-1]
            if genre not in VALID_GENRES:
                continue
            if filename not in index:
                index[filename] = (key, genre)
            names.add(filename)

    _filename_index = index
    _available_names = names


def _ensure_index() -> None:
    global _filename_index
    global _available_names
    if _filename_index is not None and _available_names is not None:
        return
    with _index_lock:
        if _filename_index is None or _available_names is None:
            _refresh_s3_index()


def _safe_head_object(key: str) -> bool:
    try:
        _get_s3_client().head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError:
        return False
    except BotoCoreError:
        return False


def resolve_music_file_path(filename: str) -> Tuple[Optional[str], Optional[str]]:
    if not filename:
        return None, None

    inferred_genre = filename.split('.')[0] if '.' in filename else ''

    if is_s3_mode():
        if inferred_genre in VALID_GENRES:
            direct_key = _s3_key(inferred_genre, filename)
            if _safe_head_object(direct_key):
                return direct_key, inferred_genre

        try:
            _ensure_index()
            hit = _filename_index.get(filename) if _filename_index else None
            if hit:
                return hit
        except (ClientError, BotoCoreError):
            return None, None
        return None, None

    if inferred_genre in VALID_GENRES:
        direct = os.path.join(MUSIC_FOLDER, inferred_genre, filename)
        if os.path.exists(direct):
            return direct, inferred_genre

    for root, _, files in os.walk(MUSIC_FOLDER):
        if filename in files:
            genre = os.path.basename(root)
            return os.path.join(root, filename), genre

    return None, None


def get_available_music_filenames() -> Set[str]:
    if is_s3_mode():
        try:
            _ensure_index()
            return set(_available_names or set())
        except (ClientError, BotoCoreError):
            return set()

    names: Set[str] = set()
    if not os.path.isdir(MUSIC_FOLDER):
        return names

    for genre in VALID_GENRES:
        genre_dir = os.path.join(MUSIC_FOLDER, genre)
        if not os.path.isdir(genre_dir):
            continue
        for entry in os.scandir(genre_dir):
            if entry.is_file():
                names.add(entry.name)
    return names


def load_music_bytes(location: str) -> BytesIO:
    if is_s3_mode():
        try:
            response = _get_s3_client().get_object(Bucket=S3_BUCKET, Key=location)
            body = response['Body'].read()
            return BytesIO(body)
        except (ClientError, BotoCoreError) as exc:
            raise FileNotFoundError(str(exc))

    if not os.path.exists(location):
        raise FileNotFoundError(location)
    with open(location, 'rb') as fp:
        return BytesIO(fp.read())

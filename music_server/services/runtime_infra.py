import os
import threading
import time
from contextlib import contextmanager

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue
from rq.job import Job

from music_server.config import (
    FEATURES_FILE,
    REDIS_FEATURES_LOCK_BLOCKING_TIMEOUT,
    REDIS_FEATURES_LOCK_NAME,
    REDIS_FEATURES_LOCK_TIMEOUT,
    REDIS_URL,
    RQ_QUEUE_NAME,
)

_THREAD_LOCK = threading.RLock()
_LOCK_FILE_PATH = FEATURES_FILE + '.lock'

try:
    import msvcrt
except ImportError:
    msvcrt = None


# Redis 연결 객체 생성
def get_redis_connection():
    return Redis.from_url(REDIS_URL)


# 업로드 비동기 처리용 RQ 큐 반환
def get_queue():
    return Queue(name=RQ_QUEUE_NAME, connection=get_redis_connection(), default_timeout=1200)


# job_id 기준 RQ 작업 객체 조회
def fetch_job(job_id):
    return Job.fetch(job_id, connection=get_redis_connection())


# Redis 연결 상태 확인
def ping_redis():
    conn = get_redis_connection()
    return conn.ping()


@contextmanager
# 특징 CSV 접근용 Redis/파일 동시 락 제어
def features_file_lock():
    redis_lock = None
    redis_lock_acquired = False

    try:
        redis_lock = get_redis_connection().lock(
            REDIS_FEATURES_LOCK_NAME,
            timeout=REDIS_FEATURES_LOCK_TIMEOUT,
            blocking_timeout=REDIS_FEATURES_LOCK_BLOCKING_TIMEOUT,
        )
        redis_lock_acquired = bool(redis_lock.acquire(blocking=True))
        if not redis_lock_acquired:
            raise TimeoutError('Redis 특징 파일 락 획득 시간이 초과되었습니다')
    except (RedisError, TimeoutError):
        redis_lock = None

    with _THREAD_LOCK:
        os.makedirs(os.path.dirname(_LOCK_FILE_PATH), exist_ok=True)
        with open(_LOCK_FILE_PATH, 'a+b') as lock_fp:
            if msvcrt is not None:
                _acquire_windows_lock(lock_fp)
            try:
                yield
            finally:
                if msvcrt is not None:
                    _release_windows_lock(lock_fp)
                if redis_lock is not None and redis_lock_acquired:
                    try:
                        redis_lock.release()
                    except RedisError:
                        pass


# Windows lock 파일 1바이트 잠금 획득
def _acquire_windows_lock(lock_fp):
    lock_fp.seek(0)
    if lock_fp.tell() == 0:
        lock_fp.write(b'0')
        lock_fp.flush()
    while True:
        try:
            lock_fp.seek(0)
            msvcrt.locking(lock_fp.fileno(), msvcrt.LK_LOCK, 1)
            return
        except OSError:
            time.sleep(0.05)


# Windows lock 파일 잠금 해제
def _release_windows_lock(lock_fp):
    try:
        lock_fp.seek(0)
        msvcrt.locking(lock_fp.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass

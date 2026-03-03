import os

from redis.exceptions import RedisError
from rq import SimpleWorker, Worker

from music_server.config import RQ_QUEUE_NAME
from music_server.services.runtime_infra import get_redis_connection


# 운영체제/환경변수 기준 Worker 구현체 선택
def _resolve_worker_class():
    mode = os.getenv('RQ_SIMPLE_WORKER', 'auto').strip().lower()
    if mode in {'1', 'true', 'yes', 'on'}:
        return SimpleWorker
    if mode in {'0', 'false', 'no', 'off'}:
        return Worker
    return SimpleWorker if os.name == 'nt' else Worker


# RQ 워커 시작 및 비동기 업로드 작업 처리
def run_worker():
    if os.name == 'nt':
        os.environ.setdefault('NUMBA_DISABLE_JIT', '1')
    connection = get_redis_connection()
    worker_class = _resolve_worker_class()
    worker = worker_class([RQ_QUEUE_NAME], connection=connection)
    worker.work(with_scheduler=False)


if __name__ == '__main__':
    try:
        run_worker()
    except RedisError as exc:
        raise SystemExit(f'Redis 연결에 실패했습니다: {exc}')


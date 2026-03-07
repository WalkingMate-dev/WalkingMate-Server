import logging
import os
import uuid
from typing import Optional

import pandas as pd

from music_server.config import FEATURE_COLUMNS

logger = logging.getLogger(__name__)


def _is_mysql_enabled():
    return os.getenv('MYSQL_ENABLED', '0').strip().lower() in {'1', 'true', 'yes', 'on'}


def _get_mysql_config():
    return {
        'host': os.getenv('MYSQL_HOST', '127.0.0.1'),
        'port': int(os.getenv('MYSQL_PORT', '3306')),
        'user': os.getenv('MYSQL_USER', ''),
        'password': os.getenv('MYSQL_PASSWORD', ''),
        'database': os.getenv('MYSQL_DATABASE', ''),
        'connect_timeout': 3,
        'charset': 'utf8mb4',
        'autocommit': True,
    }


# MySQL 연결 정보가 유효한지 확인

def _is_mysql_config_ready(cfg):
    required = ['host', 'port', 'user', 'password', 'database']
    return all(cfg.get(k) for k in required)


def _get_pymysql():
    try:
        import pymysql
        return pymysql
    except Exception as exc:
        logger.warning('pymysql import 실패: %s', exc)
        return None


def _connect(cursor_dict: bool = False):
    pymysql = _get_pymysql()
    if pymysql is None:
        return None

    cfg = _get_mysql_config()
    if not _is_mysql_config_ready(cfg):
        return None

    kwargs = dict(
        host=cfg['host'],
        port=cfg['port'],
        user=cfg['user'],
        password=cfg['password'],
        database=cfg['database'],
        connect_timeout=cfg['connect_timeout'],
        charset=cfg['charset'],
        autocommit=cfg['autocommit'],
    )
    if cursor_dict:
        kwargs['cursorclass'] = pymysql.cursors.DictCursor

    try:
        return pymysql.connect(**kwargs)
    except Exception as exc:
        logger.warning('MySQL 연결 실패(cursor_dict=%s): %s', cursor_dict, exc)
        return None


def _song_features_column_defs_sql():
    cols = [
        '`filename` VARCHAR(255) NOT NULL',
        '`length` DOUBLE NULL',
    ]
    for col in FEATURE_COLUMNS:
        cols.append(f'`{col}` DOUBLE NULL')
    cols.extend([
        '`label` VARCHAR(32) NULL',
        '`feature_hash` CHAR(64) NULL',
        '`source_hash` CHAR(64) NULL',
        '`created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP',
        '`updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP',
        'PRIMARY KEY (`filename`)',
        'INDEX idx_label (`label`)',
        'INDEX idx_tempo (`tempo`)',
        'INDEX idx_source_hash (`source_hash`)',
    ])
    return ',\n                    '.join(cols)


# MySQL 테이블 생성

def init_mysql_schema():
    if not _is_mysql_enabled():
        return

    conn = _connect(cursor_dict=False)
    if conn is None:
        logger.warning('스키마 초기화 건너뜀: MySQL 연결 실패')
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS upload_history (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    source_hash CHAR(64) NULL,
                    stored_filename VARCHAR(255) NULL,
                    duplicate TINYINT(1) NOT NULL DEFAULT 0,
                    status VARCHAR(40) NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_source_hash (source_hash),
                    INDEX idx_created_at (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS song_features (
                    {_song_features_column_defs_sql()}
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
    except Exception:
        logger.exception('MySQL 스키마 초기화 실패')
        return
    finally:
        conn.close()


# 업로드 결과 메타를 MySQL에 기록

def save_upload_record(source_hash, stored_filename, duplicate, status):
    if not _is_mysql_enabled():
        return

    conn = _connect(cursor_dict=False)
    if conn is None:
        logger.warning('업로드 이력 저장 건너뜀: MySQL 연결 실패(status=%s)', status)
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO upload_history (source_hash, stored_filename, duplicate, status)
                VALUES (%s, %s, %s, %s)
                """,
                (source_hash, stored_filename, int(bool(duplicate)), status),
            )
    except Exception:
        logger.exception('업로드 이력 저장 실패(status=%s, duplicate=%s)', status, bool(duplicate))
        return
    finally:
        conn.close()


def find_song_feature_by_source_hash(source_hash: Optional[str]) -> Optional[str]:
    if not _is_mysql_enabled() or not source_hash:
        return None

    conn = _connect(cursor_dict=True)
    if conn is None:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT filename FROM song_features WHERE source_hash=%s LIMIT 1",
                (source_hash,),
            )
            row = cur.fetchone()
            return row['filename'] if row else None
    except Exception:
        logger.exception('source_hash 기반 조회 실패')
        return None
    finally:
        conn.close()


def get_next_upload_filename() -> str:
    # MAX+1 패턴은 동시 업로드 시 동일 이름을 만들 수 있어 UUID 기반으로 생성한다.
    return f"filename_{uuid.uuid4().hex}"


def upsert_song_feature(filename: str, source_hash: Optional[str], features):
    conn = _connect(cursor_dict=False)
    if conn is None:
        raise RuntimeError('MySQL 연결에 실패했습니다')

    try:
        feature_values = [float(v) for v in features]
        if len(feature_values) != len(FEATURE_COLUMNS):
            raise ValueError('특징 벡터 길이가 FEATURE_COLUMNS와 일치하지 않습니다')

        insert_cols = ['filename', 'length'] + FEATURE_COLUMNS + ['label', 'feature_hash', 'source_hash']
        placeholders = ','.join(['%s'] * len(insert_cols))
        update_cols = [f"`{c}`=VALUES(`{c}`)" for c in insert_cols if c != 'filename']

        values = [filename, None] + feature_values + [None, None, source_hash]

        sql = (
            f"INSERT INTO song_features ({','.join([f'`{c}`' for c in insert_cols])}) "
            f"VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {','.join(update_cols)}"
        )

        with conn.cursor() as cur:
            cur.execute(sql, values)
    finally:
        conn.close()


def get_song_features_df() -> pd.DataFrame:
    columns = ['filename', 'length'] + FEATURE_COLUMNS + ['label', 'feature_hash', 'source_hash']

    conn = _connect(cursor_dict=True)
    if conn is None:
        return pd.DataFrame(columns=columns)

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {','.join([f'`{c}`' for c in columns])} FROM song_features"
            )
            rows = cur.fetchall() or []
        if not rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(rows, columns=columns)
    except Exception:
        logger.exception('song_features 조회 실패')
        return pd.DataFrame(columns=columns)
    finally:
        conn.close()

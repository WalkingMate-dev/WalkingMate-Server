import os
from typing import Optional

import pandas as pd

from music_server.config import FEATURE_COLUMNS


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
    except Exception:
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
    except Exception:
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
        return
    finally:
        conn.close()


# 업로드 결과 메타를 MySQL에 기록

def save_upload_record(source_hash, stored_filename, duplicate, status):
    if not _is_mysql_enabled():
        return

    conn = _connect(cursor_dict=False)
    if conn is None:
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
        return None
    finally:
        conn.close()


def get_next_upload_filename() -> str:
    conn = _connect(cursor_dict=False)
    if conn is None:
        return 'filename1'

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(MAX(CAST(SUBSTRING(filename, 9) AS UNSIGNED)), 0)
                FROM song_features
                WHERE filename REGEXP '^filename[0-9]+$'
                """
            )
            max_id = cur.fetchone()[0] or 0
            return f'filename{int(max_id) + 1}'
    except Exception:
        return 'filename1'
    finally:
        conn.close()


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
        return pd.DataFrame(columns=columns)
    finally:
        conn.close()

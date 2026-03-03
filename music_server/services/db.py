import os


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
        'cursorclass': None,
    }


# MySQL 연결 정보가 유효한지 확인

def _is_mysql_config_ready(cfg):
    required = ['host', 'port', 'user', 'password', 'database']
    return all(cfg.get(k) for k in required)


# MySQL upload_history 테이블 생성

def init_mysql_schema():
    if not _is_mysql_enabled():
        return

    try:
        import pymysql
    except Exception:
        return

    cfg = _get_mysql_config()
    if not _is_mysql_config_ready(cfg):
        return

    try:
        conn = pymysql.connect(
            host=cfg['host'],
            port=cfg['port'],
            user=cfg['user'],
            password=cfg['password'],
            database=cfg['database'],
            connect_timeout=cfg['connect_timeout'],
            charset=cfg['charset'],
            autocommit=cfg['autocommit'],
        )
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
        conn.close()
    except Exception:
        return


# 업로드 결과 메타를 MySQL에 기록

def save_upload_record(source_hash, stored_filename, duplicate, status):
    if not _is_mysql_enabled():
        return

    try:
        import pymysql
    except Exception:
        return

    cfg = _get_mysql_config()
    if not _is_mysql_config_ready(cfg):
        return

    try:
        conn = pymysql.connect(
            host=cfg['host'],
            port=cfg['port'],
            user=cfg['user'],
            password=cfg['password'],
            database=cfg['database'],
            connect_timeout=cfg['connect_timeout'],
            charset=cfg['charset'],
            autocommit=cfg['autocommit'],
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO upload_history (source_hash, stored_filename, duplicate, status)
                VALUES (%s, %s, %s, %s)
                """,
                (source_hash, stored_filename, int(bool(duplicate)), status),
            )
        conn.close()
    except Exception:
        return

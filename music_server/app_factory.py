import time

from flask import Flask, jsonify, g, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from music_server.routes.music_routes import music_bp
from music_server.services.db import init_mysql_schema


# Flask 앱 생성 및 라우트/미들웨어/에러 핸들러 등록
def create_app():
    app = Flask(__name__)
    # 웹 클라이언트(브라우저, Swagger UI)에서 호출할 때를 대비한 CORS 허용
    CORS(app)
    app.register_blueprint(music_bp)
    # MYSQL_ENABLED=1인 환경에서 업로드 메타 기록 테이블 준비
    init_mysql_schema()
    register_request_logging(app)
    register_error_handlers(app)
    return app


# 요청 처리 시간 측정 및 로그 기록
def register_request_logging(app):
    @app.before_request
    def _before_request():
        g._started_at = time.time()

    @app.after_request
    def _after_request(response):
        started_at = getattr(g, '_started_at', None)
        elapsed_ms = int((time.time() - started_at) * 1000) if started_at else -1
        app.logger.info('%s %s %s %s %dms', request.remote_addr, request.method, request.path, response.status_code, elapsed_ms)
        return response


# HTTP/일반 예외 JSON 응답 처리
def register_error_handlers(app):
    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        return jsonify({'error': exc.description}), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected_exception(exc):
        app.logger.exception('처리되지 않은 서버 오류: %s', exc)
        return jsonify({'error': '서버 내부 오류가 발생했습니다'}), 500

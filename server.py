import os

from music_server import create_app

app = create_app()


# 운영 환경용 waitress WSGI 서버 실행
def _run_with_waitress():
    from waitress import serve

    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '5000'))
    threads = int(os.getenv('WAITRESS_THREADS', '8'))
    serve(app, host=host, port=port, threads=threads)


if __name__ == '__main__':
    use_waitress = os.getenv('USE_WAITRESS', '0') == '1'
    if use_waitress:
        _run_with_waitress()
    else:
        host = os.getenv('HOST', '0.0.0.0')
        port = int(os.getenv('PORT', '5000'))
        debug = os.getenv('FLASK_DEBUG', '1') == '1'
        app.run(host=host, port=port, debug=debug)

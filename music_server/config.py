import os
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_FOLDER = os.path.join(BASE_DIR, 'Data', 'genres_original')
FEATURES_FILE = os.path.join(BASE_DIR, 'Data', 'features_30_sec.csv')
STORAGE_MODE = os.getenv('STORAGE_MODE', 'local').strip().lower()
S3_BUCKET = os.getenv('S3_BUCKET', '').strip()
S3_PREFIX = os.getenv('S3_PREFIX', 'genres_original').strip().strip('/')
S3_REGION = os.getenv('S3_REGION', '').strip() or None
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', '').strip() or None


def _resolve_temp_folder():
    # 우선순위: 환경변수 TEMP_FOLDER -> 시스템 temp -> 프로젝트 temp
    # 실제 쓰기 테스트까지 통과한 경로만 선택한다.
    candidates = []
    env_temp = os.getenv('TEMP_FOLDER')
    if env_temp:
        candidates.append(env_temp)
    candidates.append(os.path.join(tempfile.gettempdir(), 'music_server_temp'))
    candidates.append(os.path.join(BASE_DIR, 'temp'))

    for folder in candidates:
        try:
            os.makedirs(folder, exist_ok=True)
            fd, probe_path = tempfile.mkstemp(prefix='probe_', suffix='.tmp', dir=folder)
            os.close(fd)
            os.remove(probe_path)
            return folder
        except Exception:
            continue
    raise RuntimeError('No writable temp folder available')


TEMP_FOLDER = _resolve_temp_folder()

VALID_GENRES = {'blues', 'classical', 'country', 'disco', 'hiphop', 'jazz', 'metal', 'pop', 'reggae', 'rock'}
BPM_THRESHOLD1 = 90
BPM_THRESHOLD2 = 150

REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
RQ_QUEUE_NAME = os.getenv('RQ_QUEUE_NAME', 'music_tasks')
REDIS_FEATURES_LOCK_NAME = os.getenv('REDIS_FEATURES_LOCK_NAME', 'lock:features_csv')
REDIS_FEATURES_LOCK_TIMEOUT = int(os.getenv('REDIS_FEATURES_LOCK_TIMEOUT', '60'))
REDIS_FEATURES_LOCK_BLOCKING_TIMEOUT = int(os.getenv('REDIS_FEATURES_LOCK_BLOCKING_TIMEOUT', '10'))

FEATURE_COLUMNS = [
    'chroma_stft_mean', 'chroma_stft_var',
    'rms_mean', 'rms_var',
    'spectral_centroid_mean', 'spectral_centroid_var',
    'spectral_bandwidth_mean', 'spectral_bandwidth_var',
    'rolloff_mean', 'rolloff_var',
    'zero_crossing_rate_mean', 'zero_crossing_rate_var',
    'harmony_mean', 'harmony_var',
    'perceptr_mean', 'perceptr_var',
    'tempo'
] + [f'mfcc{i + 1}_mean' for i in range(20)] + [f'mfcc{i + 1}_var' for i in range(20)]

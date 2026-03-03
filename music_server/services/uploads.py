import hashlib
import json
import os
import subprocess
import sys
import traceback
import types
import uuid

os.environ.setdefault('NUMBA_DISABLE_JIT', '1')

import numpy as np
import pandas as pd
from werkzeug.utils import secure_filename

from music_server.config import FEATURES_FILE, FEATURE_COLUMNS, TEMP_FOLDER
from music_server.services.db import save_upload_record
from music_server.services.runtime_infra import features_file_lock


# numba 데코레이터 no-op 대체
def _numba_noop_decorator(*dargs, **dkwargs):
    if dargs and callable(dargs[0]) and len(dargs) == 1 and not dkwargs:
        return dargs[0]

    def _wrapper(func):
        return func

    return _wrapper


# librosa 로딩 실패 시 numba shim 적용 재시도
def _ensure_librosa():
    # 일부 Windows/Python 조합에서 librosa+numba 호환 이슈가 있어
    # 최소 기능 shim으로 우회 로딩한다.
    try:
        import librosa as _librosa
        _ = _librosa.load
        return _librosa
    except Exception:
        for name in list(sys.modules):
            if name == 'librosa' or name.startswith('librosa.'):
                sys.modules.pop(name, None)

        shim = types.ModuleType('numba')
        shim.jit = _numba_noop_decorator
        shim.njit = _numba_noop_decorator
        shim.stencil = _numba_noop_decorator
        shim.vectorize = _numba_noop_decorator
        shim.guvectorize = _numba_noop_decorator
        shim.generated_jit = _numba_noop_decorator
        shim.prange = range
        sys.modules['numba'] = shim

        import librosa as _librosa
        _ = _librosa.load
        return _librosa


librosa = _ensure_librosa()


# onset 자기상관 기반 템포 추정
def _estimate_tempo(y, sr, hop_length=512):
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    if onset_env is None or len(onset_env) < 4:
        return 0.0

    onset_env = onset_env - np.mean(onset_env)
    if np.allclose(onset_env, 0.0):
        return 0.0

    ac = np.correlate(onset_env, onset_env, mode='full')
    ac = ac[len(ac) // 2:]

    min_bpm, max_bpm = 40.0, 220.0
    min_lag = int((60.0 * sr) / (max_bpm * hop_length))
    max_lag = int((60.0 * sr) / (min_bpm * hop_length))
    min_lag = max(min_lag, 1)
    max_lag = min(max_lag, len(ac) - 1)
    if max_lag <= min_lag:
        return 0.0

    lag = np.argmax(ac[min_lag:max_lag + 1]) + min_lag
    if lag <= 0:
        return 0.0
    return float(60.0 * sr / (hop_length * lag))


# zero crossing rate 평균/분산 직접 계산
def _zero_crossing_rate_stats(y, frame_length=2048, hop_length=512):
    if y is None or len(y) == 0:
        return 0.0, 0.0

    if len(y) < frame_length:
        pad = frame_length - len(y)
        y = np.pad(y, (0, pad), mode='constant')

    pad_width = frame_length // 2
    y_padded = np.pad(y, (pad_width, pad_width), mode='edge')
    frames = librosa.util.frame(y_padded, frame_length=frame_length, hop_length=hop_length)
    frame_sign = np.sign(frames)
    zc = np.mean(np.abs(np.diff(frame_sign, axis=0)), axis=0) * 0.5
    return float(np.mean(zc)), float(np.var(zc))


# 오디오 파일 특징 벡터 추출
def extract_features(file_path):
    y, sr = librosa.load(file_path, duration=30.0)

    chroma_stft = librosa.feature.chroma_stft(y=y, sr=sr, tuning=0.0)
    chroma_stft_mean = np.mean(chroma_stft)
    chroma_stft_var = np.var(chroma_stft)

    rms = librosa.feature.rms(y=y)
    rms_mean = np.mean(rms)
    rms_var = np.var(rms)

    spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
    spectral_centroid_mean = np.mean(spectral_centroid)
    spectral_centroid_var = np.var(spectral_centroid)

    spectral_bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)
    spectral_bandwidth_mean = np.mean(spectral_bandwidth)
    spectral_bandwidth_var = np.var(spectral_bandwidth)

    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)
    rolloff_mean = np.mean(rolloff)
    rolloff_var = np.var(rolloff)

    zero_crossing_rate_mean, zero_crossing_rate_var = _zero_crossing_rate_stats(y)

    spectral_contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
    harmony_mean = np.mean(spectral_contrast)
    harmony_var = np.var(spectral_contrast)

    tempogram = librosa.feature.tempogram(y=y, sr=sr)
    perceptr_mean = np.mean(tempogram)
    perceptr_var = np.var(tempogram)

    tempo = _estimate_tempo(y=y, sr=sr)

    mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
    mfccs_mean = np.mean(mfccs, axis=1)
    mfccs_var = np.var(mfccs, axis=1)

    return np.hstack([
        chroma_stft_mean, chroma_stft_var,
        rms_mean, rms_var,
        spectral_centroid_mean, spectral_centroid_var,
        spectral_bandwidth_mean, spectral_bandwidth_var,
        rolloff_mean, rolloff_var,
        zero_crossing_rate_mean, zero_crossing_rate_var,
        harmony_mean, harmony_var,
        perceptr_mean, perceptr_var,
        tempo,
        *mfccs_mean, *mfccs_var
    ])


# 특징 CSV 읽기 및 누락 컬럼 보정
def _read_features_df():
    try:
        df = pd.read_csv(FEATURES_FILE)
    except FileNotFoundError:
        df = pd.DataFrame(columns=['filename', 'length', 'label'] + FEATURE_COLUMNS)
    if 'source_hash' not in df.columns:
        df['source_hash'] = np.nan
    return df


# 임시 파일 경유 특징 CSV 원자적 갱신
def _atomic_write_features(df):
    tmp_path = FEATURES_FILE + '.tmp'
    df.to_csv(tmp_path, index=False)
    os.replace(tmp_path, FEATURES_FILE)


# 업로드 파일 임시 폴더 저장
def save_upload_to_temp(file_storage):
    if file_storage is None:
        return None, {'error': '업로드 파일이 없습니다'}, 400

    if file_storage.filename == '':
        return None, {'error': '선택된 파일이 없습니다'}, 400

    safe_name = secure_filename(file_storage.filename) or f"upload_{int(pd.Timestamp.now().timestamp())}.bin"
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    file_path = os.path.join(TEMP_FOLDER, unique_name)
    file_storage.save(file_path)
    return file_path, None, 200


# 파일 해시 중복 검사 및 특징 추출/CSV 저장
def process_uploaded_file(file_path, cleanup=True):
    file_hash = None
    try:
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        file_hash = hasher.hexdigest()
        features = extract_features(file_path)
    except Exception as exc:
        detail = str(exc) or repr(exc)
        save_upload_record(file_hash, None, False, 'feature_error')
        return {
            'error': f'특징 추출에 실패했습니다: {detail}',
            'trace': traceback.format_exc(limit=3),
        }, 400

    try:
        with features_file_lock():
            existing_df = _read_features_df()

            if file_hash:
                duplicate_rows = existing_df[existing_df['source_hash'] == file_hash]
                if not duplicate_rows.empty:
                    existing_filename = str(duplicate_rows.iloc[0]['filename'])
                    save_upload_record(file_hash, existing_filename, True, 'duplicate')
                    return {
                        'message': '중복 업로드가 감지되었습니다',
                        'filename': existing_filename,
                        'duplicate': True
                    }, 200

            next_filename = f'filename{len(existing_df) + 1}'
            new_data = {'filename': next_filename, 'length': np.nan, 'label': np.nan, 'source_hash': file_hash}
            for col, val in zip(FEATURE_COLUMNS, features):
                new_data[col] = val

            updated_df = pd.concat([existing_df, pd.DataFrame([new_data])], ignore_index=True)
            _atomic_write_features(updated_df)
            save_upload_record(file_hash, next_filename, False, 'saved')
            return {'message': '파일 업로드 및 특징 추출이 완료되었습니다', 'filename': next_filename}, 200
    except Exception as exc:
        save_upload_record(file_hash, None, False, 'storage_error')
        return {'error': f'특징 저장에 실패했습니다: {str(exc)}'}, 500
    finally:
        if cleanup:
            try:
                os.remove(file_path)
            except Exception:
                pass


# 동기 업로드 요청 처리
def process_upload(file_storage):
    file_path, error_payload, status = save_upload_to_temp(file_storage)
    if error_payload:
        return error_payload, status
    return process_uploaded_file(file_path, cleanup=True)


# 비동기 큐 업로드 분석 서브프로세스 실행
def process_upload_job(file_path):
    print(f'[RQ] 서브프로세스 작업 시작: {file_path}', flush=True)
    env = os.environ.copy()
    env.setdefault('NUMBA_DISABLE_JIT', '1')

    cmd = [
        sys.executable,
        '-B',
        '-c',
        (
            "import json,sys;"
            "from music_server.services.uploads import process_uploaded_file;"
            "payload,status=process_uploaded_file(sys.argv[1],cleanup=True);"
            "print(json.dumps({'payload':payload,'status':status}, ensure_ascii=False))"
        ),
        file_path,
    ]
    print('[RQ] 서브프로세스 실행', flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, env=env)
    print(f'[RQ] 서브프로세스 종료코드={result.returncode}', flush=True)
    if result.returncode != 0:
        stderr = (result.stderr or '').strip()
        raise RuntimeError(stderr or '백그라운드 업로드 서브프로세스가 실패했습니다')

    raw = (result.stdout or '').strip().splitlines()
    if not raw:
        raise RuntimeError('백그라운드 업로드 서브프로세스 출력이 없습니다')

    data = json.loads(raw[-1])
    payload = data.get('payload', {})
    status = int(data.get('status', 500))
    if status >= 400:
        detail = payload.get('error', '업로드 처리에 실패했습니다')
        trace = payload.get('trace')
        if trace:
            raise RuntimeError(f'{detail}\n{trace}')
        raise RuntimeError(detail)
    return payload


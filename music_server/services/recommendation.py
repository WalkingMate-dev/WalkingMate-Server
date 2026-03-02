import os

import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import scale

from music_server.config import BPM_THRESHOLD1, BPM_THRESHOLD2, FEATURES_FILE, MUSIC_FOLDER, VALID_GENRES
from music_server.services.infra import features_file_lock


# 파일명 기준 실제 음악 파일 경로/장르 탐색
def resolve_music_file_path(filename):
    if not filename:
        return None, None

    inferred_genre = filename.split('.')[0] if '.' in filename else ''
    if inferred_genre in VALID_GENRES:
        direct = os.path.join(MUSIC_FOLDER, inferred_genre, filename)
        if os.path.exists(direct):
            return direct, inferred_genre

    for root, _, files in os.walk(MUSIC_FOLDER):
        if filename in files:
            genre = os.path.basename(root)
            return os.path.join(root, filename), genre

    return None, None


# 특징 CSV 기반 저/고 BPM 그룹 구성
def get_bpm_groups():
    try:
        with features_file_lock():
            features_df = pd.read_csv(FEATURES_FILE)
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

    features_df = features_df.dropna(subset=['filename', 'label', 'tempo', 'rms_mean'])
    features_df = features_df[features_df['label'].isin(VALID_GENRES)]

    low_bpm_songs = features_df[
        (features_df['tempo'] <= BPM_THRESHOLD1) &
        (features_df['rms_mean'] <= features_df['rms_mean'].mean())
    ]

    high_bpm_songs = features_df[
        (features_df['tempo'] >= BPM_THRESHOLD2) &
        (features_df['rms_mean'] > features_df['rms_mean'].mean())
    ]

    return low_bpm_songs, high_bpm_songs


# BPM 그룹 랜덤 곡 1개 선택
def pick_random_song_by_group(bpm_songs):
    if bpm_songs.empty:
        return None, {'error': '요청한 BPM 범위의 음악 파일이 없습니다'}, 404

    selected_song = bpm_songs.sample().iloc[0]
    genre = str(selected_song['label'])
    file_name = str(selected_song['filename'])
    tempo = selected_song['tempo']

    file_path = os.path.join(MUSIC_FOLDER, genre, file_name)
    if not os.path.exists(file_path):
        file_path, genre = resolve_music_file_path(file_name)
        if file_path is None:
            return None, {'error': f'음악 파일을 찾을 수 없습니다: {file_name}'}, 404

    return {
        'file_name': file_name,
        'genre': genre,
        'tempo': tempo,
        'file_path': file_path
    }, None, 200


# 입력 BPM 기준 저/고 BPM 그룹 곡 선택
def pick_song_by_bpm_value(bpm_value):
    low_bpm_songs, high_bpm_songs = get_bpm_groups()
    songs = low_bpm_songs if bpm_value < BPM_THRESHOLD2 else high_bpm_songs

    if songs.empty:
        return None, {'error': '입력한 bpm에 맞는 음악 파일이 없습니다'}, 404

    selected_song = songs.sample().iloc[0]
    file_name = str(selected_song['filename'])
    genre = str(selected_song['label'])
    tempo = selected_song['tempo']

    file_path = os.path.join(MUSIC_FOLDER, genre, file_name)
    if not os.path.exists(file_path):
        file_path, genre = resolve_music_file_path(file_name)
        if file_path is None:
            return None, {'error': '선택된 음악 파일을 찾을 수 없습니다'}, 404

    return {
        'file_name': file_name,
        'genre': genre,
        'tempo': tempo,
        'file_path': file_path
    }, None, 200


# 기준 곡 유사도 계산 후 상위 n개 반환
def find_similar_songs(name, n=5):
    with features_file_lock():
        df_30 = pd.read_csv(FEATURES_FILE, index_col='filename')

    df_30 = df_30[~df_30.index.duplicated(keep='first')]
    df_30 = df_30.drop(columns=['harmony_mean', 'harmony_var', 'perceptr_mean', 'perceptr_var'], errors='ignore')

    feature_df = df_30.drop(columns=['length', 'label'], errors='ignore')

    feature_df = feature_df.apply(pd.to_numeric, errors='coerce')
    feature_df = feature_df.replace([np.inf, -np.inf], np.nan)
    feature_df = feature_df.dropna(axis=1, how='all')

    medians = feature_df.median(numeric_only=True).fillna(0.0)
    feature_df = feature_df.fillna(medians).fillna(0.0)

    if name not in feature_df.index:
        valid_candidates = [idx for idx in feature_df.index if isinstance(idx, str) and '.' in idx and idx.split('.')[0] in VALID_GENRES]
        if valid_candidates:
            name = valid_candidates[0]
        else:
            raise ValueError(f'특징 데이터에서 업로드 파일명을 찾을 수 없습니다: {name}')

    df_30_scaled = scale(feature_df)
    df_30_scaled = pd.DataFrame(df_30_scaled, columns=feature_df.columns, index=feature_df.index)

    similarity = cosine_similarity(df_30_scaled)
    sim_df = pd.DataFrame(similarity, index=df_30_scaled.index, columns=df_30_scaled.index)

    base_series = sim_df[name].drop(name, errors='ignore')
    valid_mask = base_series.index.to_series().apply(
        lambda idx: isinstance(idx, str) and '.' in idx and idx.split('.')[0] in VALID_GENRES
    )
    base_series = base_series[valid_mask]

    if base_series.empty:
        return pd.DataFrame(columns=['score', 'tempo_similarity', 'energy_similarity', 'brightness_similarity', 'rhythm_similarity'])

    target = feature_df.loc[name]
    candidates = feature_df.loc[base_series.index]

    def safe_col(df, col):
        return df[col] if col in df.columns else pd.Series(0.0, index=df.index)

    def safe_std(col_name):
        if col_name not in feature_df.columns:
            return 1.0
        v = float(feature_df[col_name].std(skipna=True))
        if np.isnan(v) or v < 1e-6:
            return 1.0
        return v

    target_tempo = float(target.get('tempo', 0.0))
    target_rms = float(target.get('rms_mean', 0.0))
    target_centroid = float(target.get('spectral_centroid_mean', 0.0))
    target_zcr = float(target.get('zero_crossing_rate_mean', 0.0))

    cand_tempo = safe_col(candidates, 'tempo').astype(float)
    cand_rms = safe_col(candidates, 'rms_mean').astype(float)
    cand_centroid = safe_col(candidates, 'spectral_centroid_mean').astype(float)
    cand_zcr = safe_col(candidates, 'zero_crossing_rate_mean').astype(float)

    rms_scale = safe_std('rms_mean')
    centroid_scale = safe_std('spectral_centroid_mean')
    zcr_scale = safe_std('zero_crossing_rate_mean')

    tempo_diff = (cand_tempo - target_tempo).abs()
    rms_diff = (cand_rms - target_rms).abs() / rms_scale
    centroid_diff = (cand_centroid - target_centroid).abs() / centroid_scale
    zcr_diff = (cand_zcr - target_zcr).abs() / zcr_scale

    tight_candidates = base_series[tempo_diff <= 35]
    if len(tight_candidates) >= n:
        base_series = tight_candidates
        candidates = feature_df.loc[base_series.index]
        cand_tempo = safe_col(candidates, 'tempo').astype(float)
        cand_rms = safe_col(candidates, 'rms_mean').astype(float)
        cand_centroid = safe_col(candidates, 'spectral_centroid_mean').astype(float)
        cand_zcr = safe_col(candidates, 'zero_crossing_rate_mean').astype(float)
        tempo_diff = (cand_tempo - target_tempo).abs()
        rms_diff = (cand_rms - target_rms).abs() / rms_scale
        centroid_diff = (cand_centroid - target_centroid).abs() / centroid_scale
        zcr_diff = (cand_zcr - target_zcr).abs() / zcr_scale

    tempo_penalty = np.clip(tempo_diff / 45.0, 0, 1) * 0.40
    rms_penalty = np.clip(rms_diff / 2.5, 0, 1) * 0.25
    centroid_penalty = np.clip(centroid_diff / 2.5, 0, 1) * 0.20
    zcr_penalty = np.clip(zcr_diff / 2.5, 0, 1) * 0.15

    final_score = base_series - (tempo_penalty + rms_penalty + centroid_penalty + zcr_penalty)

    tempo_similarity = np.clip(1.0 - (tempo_diff / 45.0), 0.0, 1.0)
    energy_similarity = np.clip(1.0 - (rms_diff / 2.5), 0.0, 1.0)
    brightness_similarity = np.clip(1.0 - (centroid_diff / 2.5), 0.0, 1.0)
    rhythm_similarity = np.clip(1.0 - (zcr_diff / 2.5), 0.0, 1.0)

    detail_df = pd.DataFrame({
        'score': final_score,
        'tempo_similarity': tempo_similarity,
        'energy_similarity': energy_similarity,
        'brightness_similarity': brightness_similarity,
        'rhythm_similarity': rhythm_similarity
    })
    return detail_df.sort_values(by='score', ascending=False).head(n)


# 유사도 계산 결과 API 응답 형식 변환
def build_similarity_payload(result_df):
    if result_df is None or result_df.empty:
        return []

    scores = result_df['score'] if 'score' in result_df.columns else pd.Series(0.0, index=result_df.index)
    tempo_sim = result_df['tempo_similarity'] if 'tempo_similarity' in result_df.columns else pd.Series(0.0, index=result_df.index)
    energy_sim = result_df['energy_similarity'] if 'energy_similarity' in result_df.columns else pd.Series(0.0, index=result_df.index)
    bright_sim = result_df['brightness_similarity'] if 'brightness_similarity' in result_df.columns else pd.Series(0.0, index=result_df.index)
    rhythm_sim = result_df['rhythm_similarity'] if 'rhythm_similarity' in result_df.columns else pd.Series(0.0, index=result_df.index)

    payload = []
    for idx, score in scores.items():
        payload.append({
            'filename': idx,
            'similarity_percent': int(np.clip(((float(score) + 1.0) / 2.0) * 100.0, 0.0, 100.0)),
            'tempo_similarity_percent': int(np.clip(float(tempo_sim.get(idx, 0.0)) * 100.0, 0.0, 100.0)),
            'energy_similarity_percent': int(np.clip(float(energy_sim.get(idx, 0.0)) * 100.0, 0.0, 100.0)),
            'brightness_similarity_percent': int(np.clip(float(bright_sim.get(idx, 0.0)) * 100.0, 0.0, 100.0)),
            'rhythm_similarity_percent': int(np.clip(float(rhythm_sim.get(idx, 0.0)) * 100.0, 0.0, 100.0))
        })
    return payload

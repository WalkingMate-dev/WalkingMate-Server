import os
import uuid

from flask import Blueprint, jsonify, request, send_file
from redis.exceptions import RedisError
from rq.exceptions import NoSuchJobError

from music_server.services.infra import fetch_job, get_queue
from music_server.services.recommendation import (
    build_similarity_payload,
    find_similar_songs,
    get_bpm_groups,
    pick_random_song_by_group,
    pick_song_by_bpm_value,
    resolve_music_file_path,
)
from music_server.services.uploads import process_upload, save_upload_to_temp
from music_server.state import get_current_song_info, mark_current_song

music_bp = Blueprint('music', __name__)


# 업로드 파일 즉시 분석 및 특징값 저장
@music_bp.route('/upload', methods=['POST'])
def upload_file():
    payload, status = process_upload(request.files.get('file'))
    return jsonify(payload), status


# 업로드 파일 큐 등록 및 job_id 반환
@music_bp.route('/upload_async', methods=['POST'])
def upload_file_async():
    file_path, error_payload, status = save_upload_to_temp(request.files.get('file'))
    if error_payload:
        return jsonify(error_payload), status

    try:
        job_id = str(uuid.uuid4())
        queue = get_queue()
        queue.enqueue(
            'music_server.services.uploads.process_upload_job',
            file_path,
            job_id=job_id,
            job_timeout=1200,
            result_ttl=3600,
            failure_ttl=3600,
        )
        return jsonify({'job_id': job_id, 'status': 'queued'}), 202
    except Exception as exc:
        try:
            os.remove(file_path)
        except Exception:
            pass
        return jsonify({'error': f'비동기 업로드 처리에 실패했습니다: {str(exc)}'}), 503


# 비동기 업로드 작업 상태/결과 조회
@music_bp.route('/jobs/<job_id>', methods=['GET'])
def get_job_status(job_id):
    try:
        job = fetch_job(job_id)
    except NoSuchJobError:
        return jsonify({'error': '작업을 찾을 수 없습니다'}), 404
    except RedisError as exc:
        return jsonify({'error': f'Redis를 사용할 수 없습니다: {str(exc)}'}), 503

    status = job.get_status(refresh=True)
    response = {'job_id': job_id, 'status': status}

    if status == 'finished':
        response['result'] = job.result
    elif status == 'failed':
        response['error'] = '업로드 처리에 실패했습니다'
    return jsonify(response), 200


# 유사 곡 파일명 목록 반환
@music_bp.route('/similar_songs/<filename>', methods=['GET'])
def similar_songs(filename):
    try:
        result = find_similar_songs(filename)
        return jsonify(result.index.tolist()), 200
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


# 유사 곡 상세 유사도 지표 반환
@music_bp.route('/similar_songs_detailed/<filename>', methods=['GET'])
def similar_songs_detailed(filename):
    try:
        result = find_similar_songs(filename)
        return jsonify(build_similarity_payload(result)), 200
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


# 저 BPM 그룹 랜덤 곡 선택 및 파일 응답
@music_bp.route('/random_music/low_bpm', methods=['GET'])
def get_low_bpm_music():
    low_bpm_songs, _ = get_bpm_groups()
    song, error_payload, status = pick_random_song_by_group(low_bpm_songs)
    if error_payload:
        return jsonify(error_payload), status

    mark_current_song(song['file_name'], song['genre'], song['tempo'])
    return send_file(song['file_path'], as_attachment=True, download_name=song['file_name'])


# 고 BPM 그룹 랜덤 곡 선택 및 파일 응답
@music_bp.route('/random_music/high_bpm', methods=['GET'])
def get_high_bpm_music():
    _, high_bpm_songs = get_bpm_groups()
    song, error_payload, status = pick_random_song_by_group(high_bpm_songs)
    if error_payload:
        return jsonify(error_payload), status

    mark_current_song(song['file_name'], song['genre'], song['tempo'])
    return send_file(song['file_path'], as_attachment=True, download_name=song['file_name'])


# 입력 BPM 기준 곡 1개 선택
@music_bp.route('/bpm', methods=['POST'])
def bpm_route():
    bpm_value = request.form.get('bpm', type=float)
    if bpm_value is None:
        return jsonify({'error': 'bpm 값이 없습니다'}), 400

    song, error_payload, status = pick_song_by_bpm_value(bpm_value)
    if error_payload:
        return jsonify(error_payload), status

    mark_current_song(song['file_name'], song['genre'], song['tempo'])
    return jsonify({'file_title': song['file_name']}), 200


# 파일명 기준 음악 파일 다운로드
@music_bp.route('/music/<filename>', methods=['GET'])
def music_file(filename):
    file_path, _ = resolve_music_file_path(filename)
    if file_path:
        return send_file(file_path, as_attachment=True, download_name=filename)
    return jsonify({'error': '파일을 찾을 수 없습니다'}), 404


# 마지막 선택 곡 템포 반환
@music_bp.route('/current_tempo', methods=['GET'])
def get_current_tempo():
    info = get_current_song_info()
    if not info:
        return jsonify({'error': '현재 선택된 곡이 없습니다'}), 404
    return jsonify({'tempo': info['tempo']})


# 마지막 선택 곡 파일명 반환
@music_bp.route('/current_filename', methods=['GET'])
def get_current_filename():
    info = get_current_song_info()
    if not info:
        return jsonify({'error': '현재 선택된 곡이 없습니다'}), 404
    return jsonify({'filename': info['filename']})


# music 엔드포인트와 동일 기능의 다운로드 별칭(기존 클라이언트 호환용)
@music_bp.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    file_path, _ = resolve_music_file_path(filename)
    if file_path:
        return send_file(file_path, as_attachment=True, download_name=filename)
    return jsonify({'error': '파일을 찾을 수 없습니다'}), 404

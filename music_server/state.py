current_song_info = {}
# 프로세스 메모리 상태라 서버 재시작 시 초기화된다.


# 마지막 선택 곡 정보 메모리 기록
def mark_current_song(file_name, genre, tempo):
    global current_song_info
    current_song_info = {
        'genre': genre,
        'filename': file_name,
        'tempo': float(tempo) if tempo is not None else None
    }


# 마지막 선택 곡 정보 조회
def get_current_song_info():
    return current_song_info

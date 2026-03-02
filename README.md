# WalkingMate-Server

WalkingMate 프로젝트의 백엔드 서버 레포지토리입니다.

## 기술 스택
- Python
- Flask
- Waitress
- Redis
- RQ Worker
- librosa / numpy / pandas

## 아키텍처 요약
- API 서버: Flask 앱을 Waitress로 실행
- 비동기 처리: Redis Queue + RQ Worker
- 저장소:
  - 메타/특징: `Data/features_30_sec.csv`
  - 음원 파일: 로컬 파일(`Data/genres_original`, 레포 제외 권장)

## 실행 방법 (Windows, PowerShell)
```powershell
cd C:\androidApp\server
.\start_all.ps1
```

- Redis를 확인하고 필요 시 Docker Redis를 시작합니다.
- API 서버와 Worker를 함께 실행합니다.
- 기본 API 포트: `18080`

종료:
```powershell
.\stop_both.ps1
```

## 주요 API
- `POST /upload` : 동기 업로드 처리
- `POST /upload_async` : 비동기 업로드 처리(job_id 반환)
- `GET /jobs/{job_id}` : 비동기 작업 상태 조회
- `GET /similar_songs/{filename}` : 유사 곡 목록
- `GET /similar_songs_detailed/{filename}` : 유사도 상세
- `GET /random_music/low_bpm` : 저 BPM 랜덤 곡
- `GET /random_music/high_bpm` : 고 BPM 랜덤 곡
- `POST /bpm` : BPM 기반 곡 선택
- `GET /current_tempo` : 현재 선택 곡 템포
- `GET /current_filename` : 현재 선택 곡 파일명

상세 스펙: `docs/openapi.yaml`

## 레포 분리 운영
- 앱(안드로이드) 레포와 서버 레포를 분리 운영합니다.
- 앱 레포에서는 백엔드 레포 링크만 참조합니다.

## 주의 사항
- `.venv`, `temp`, 로그, 대용량 음원(`Data/genres_original`)은 git 추적 제외입니다.
- 로컬 환경에서 필요한 `Data/genres_original`은 별도 경로/스토리지에서 관리하세요.

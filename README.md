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
cd C:\PortfolioProject\server
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

## 배포 (Docker Compose + AWS)
- 인프라: `infra/aws` (Terraform)
- 컨테이너: `deploy/docker-compose.yml` (`app + worker + redis + mysql`)
- 환경파일: `deploy/.env` (`.env.example` 복사해서 사용)

로컬 compose 실행:
```powershell
cd C:\PortfolioProject\server\deploy
Copy-Item .env.example .env
docker compose up -d --build
```

MySQL 사용:
- `MYSQL_ENABLED=1`이면 업로드 결과 메타를 `upload_history` 테이블에 저장
- `MYSQL_ENABLED=0`이면 기존 CSV 기반만 사용

## GitHub Actions 시크릿
`deploy.yml` 실행 전에 아래 시크릿을 저장합니다.

- `AWS_REGION`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `GHCR_USERNAME`
- `GHCR_TOKEN`
- `WALKINGMATE_ENV`

`WALKINGMATE_ENV`에는 `deploy/.env.example` 형식의 내용을 그대로 넣습니다.

## 블루그린 배포 동작
- 한 EC2 인스턴스에서 `walkingmate_app_blue`, `walkingmate_app_green` 2개 앱 컨테이너를 번갈아 기동
- 새 컨테이너 `/health` 통과 후 기존 컨테이너 종료
- `walkingmate_haproxy`가 18080 포트에서 트래픽 라우팅
- `walkingmate_worker`는 매 배포 시 최신 이미지로 재기동




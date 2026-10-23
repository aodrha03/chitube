# 치튜브 설치 — 시놀로지 (DSM 7.2 이상)

> 처음 한 번만 따라 하면 됩니다. 자세한 사용법은 [사용 설명서](../MANUAL.md).

## 1. 준비

- 패키지 센터에서 **Container Manager** 설치
- 이 압축 파일(`chitube-…-synology.zip`)을 PC 에서 풉니다.

## 2. 파일 올리기

1. **File Station** → `docker` 공유폴더 안에 **`chitube`** 폴더 만들기
2. 압축을 푼 폴더 **안의 내용 전체**를 `docker/chitube` 에 올리기
   - `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `app/` 와 **빈 `config/` · `downloads/` 폴더**가 `docker/chitube` 바로 아래에 있어야 합니다.
   - 빈 폴더가 업로드에서 빠졌다면 File Station 에서 `config`, `downloads` 폴더를 직접 만드세요. (없으면 `Bind mount failed` 오류)

## 3. 실행

1. **Container Manager → 프로젝트 → 생성**
2. 프로젝트 이름 `chitube`, 경로 `docker/chitube`
3. 소스: **기존 docker-compose.yml 사용** → 다음 → 완료 (처음엔 빌드로 몇 분 걸림)
4. 브라우저에서 **`http://NAS주소:8945`**

## 알아 둘 것

- ⚠ `.env` 의 `PUID` · `PGID` 는 **0 그대로** 두세요. 바꾸면 `unable to open database file` 로 계속 재시작될 수 있습니다.
- 영상을 다른 공유폴더 · USB 에 저장하려면 `.env.example` 을 `.env` 로 복사해 `DOWNLOAD_DIR=/volume1/video/ChiTube` 처럼 지정 (폴더는 미리 만들어 두기)
- 인텔 CPU 모델은 퀵싱크(하드웨어 압축)가 자동으로 연결됩니다. ARM 모델은 CPU 로 동작합니다. 시놀로지 CPU 는 압축이 느린 편이라 화질은 **원본 그대로** 또는 **H.264 표준**을 권장합니다.
- **받는 중 · 녹화 중인 파일은 어떤 OS 에서든 복사하거나 옮기지 마세요.** 복사 · 이동하는 방법(탐색기 · Finder · 네트워크 공유)과 Docker 가 폴더를 연결하는 방식에 따라 녹화가 멈추거나, 끝날 때 파일을 찾지 못해 정리 · 압축이 안 될 수 있습니다. 녹화 중 확인은 영상 정보 창의 **▶ 지금 받는 부분 확인**(미리보기)을 쓰고, 복사 · 이동은 카드가 **완료**가 된 뒤에 하세요. (녹화가 멈추면 90초 뒤 자동으로 그때까지 녹화분을 저장하고 새 파일로 이어서 녹화하지만, 멈춘 동안은 빠집니다)
- 웹 화면에는 비밀번호가 없습니다. 공유기 포트포워딩으로 인터넷에 열지 마세요.

## 업데이트

1. 새 버전 압축 파일의 내용을 `docker/chitube` 에 **덮어쓰기** (`config/` · `downloads/` 는 그대로 두기)
2. Container Manager → 프로젝트 `chitube` → 정지 → **빌드** → 시작

## 예전 이름(docker_youtube)에서 옮겨 올 때

1. Container Manager → 프로젝트 → 예전 프로젝트(`docker_youtube`) **정지 → 삭제** (폴더 · 영상은 지워지지 않음)
2. 예전 폴더에 새 버전 파일을 덮어쓰고(`config/` · `downloads/` 는 그대로), 그 폴더 경로로 위 **3. 실행**을 다시 하면 설정 · 구독 · 받은 목록이 그대로 이어집니다.

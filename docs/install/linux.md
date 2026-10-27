# 치튜브 설치 — 리눅스 (Docker)

> **한국어** · [English](linux.en.md)

> 맥도 같은 방법입니다. 자세한 사용법은 [사용 설명서](../MANUAL.md).

## 1. 준비

Docker 와 Docker Compose v2 (`docker compose` 명령)가 필요합니다.

```sh
docker compose version     # 버전이 나오면 준비 완료
```

## 2. 실행

압축을 푼 폴더(또는 `git clone` 한 폴더)에서:

```sh
cd chitube
docker compose up -d --build
```

브라우저에서 **`http://서버주소:8945`** (처음엔 빌드로 몇 분 걸림)

영상은 `downloads/`, 설정 · 로그인 정보는 `config/` 에 저장됩니다.

## 저장 위치 · 파일 소유자 바꾸기 (선택)

```sh
cp .env.example .env
nano .env          # DOWNLOAD_DIR=/mnt/hdd/ChiTube, PUID/PGID=`id` 명령의 값
docker compose up -d
```

## 그래픽카드 (선택)

- **인텔 내장 그래픽**: 따로 할 것 없음 (서버에 `/dev/dri` 가 있으면 자동 연결)
- **엔비디아**: NVIDIA 드라이버 + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) 설치 후 한 번만
  ```sh
  sudo nvidia-ctk runtime configure --runtime=docker --set-as-default && sudo systemctl restart docker
  ```
- 맥(Docker Desktop)은 구조상 GPU 를 못 써서 CPU 로 압축합니다.

## 녹화 중인 파일

**받는 중 · 녹화 중인 파일은 어떤 OS 에서든 복사하거나 옮기지 마세요.** 복사 · 이동하는 방법(탐색기 · Finder · 네트워크 공유)과 Docker 가 폴더를 연결하는 방식에 따라 녹화가 멈추거나, 끝날 때 파일을 찾지 못해 정리 · 압축이 안 될 수 있습니다. 녹화 중 확인은 영상 정보 창의 **▶ 지금 받는 부분 확인**(미리보기)을 쓰고, 복사 · 이동은 카드가 **완료**가 된 뒤에 하세요. (녹화가 멈추면 45초 뒤(설정으로 바꿀 수 있음) 자동으로 그때까지 녹화분을 저장하고 새 파일로 이어서 녹화하지만, 멈춘 동안은 빠집니다)

## 자주 쓰는 명령

```sh
docker compose logs -f          # 로그 보기
docker compose restart          # 다시 시작 (yt-dlp 도 최신으로)
docker compose down             # 멈추고 지우기 (config/ · downloads/ 는 그대로)
```

## 업데이트

새 버전 파일로 덮어쓰고(`config/` · `downloads/` 는 그대로) `docker compose up -d --build`.
`git clone` 했다면 `git pull && docker compose up -d --build`.

## 예전 이름(docker_youtube)에서 옮겨 올 때

컨테이너 이름이 `chitube` 로 바뀌었습니다. 예전 컨테이너를 한 번 지우고 다시 실행하세요. 설정 · 영상은 `config/` · `downloads/` 에 그대로 남습니다.

```sh
docker rm -f docker_youtube
docker compose up -d --build
```

⚠ 웹 화면에는 비밀번호가 없습니다. 인터넷에 열지 마세요.

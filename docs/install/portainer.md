# 치튜브 설치 — 포테이너 (Portainer)

> 이미지를 빌드해야 하므로 웹 편집기(Web editor)에 compose 만 붙여 넣는 방법은 안 됩니다. 아래 둘 중 하나를 쓰세요.

## 방법 A — Repository (가장 쉬움, 권장)

파일을 받을 필요 없이 포테이너가 GitHub 에서 직접 가져와 빌드합니다.

1. **Stacks → Add stack** → 이름 `chitube`
2. Build method: **Repository**
   - Repository URL: `https://github.com/aodrha03/chitube`
   - Repository reference: `refs/heads/main`
   - Compose path: `docker-compose.yml`
3. (선택) **Environment variables** 에 `DOWNLOAD_DIR` (예: `/mnt/hdd/ChiTube`), `PUID`, `PGID`
4. **Deploy the stack** → 브라우저에서 **`http://서버주소:8945`**

업데이트: 스택 → **Pull and redeploy**

## 방법 B — 서버에서 이미지 빌드 후 스택

1. 이 압축 파일을 서버에 풀고 이미지 만들기
   ```sh
   cd chitube
   docker build -t chitube:latest .
   ```
2. **Stacks → Add stack** → **Web editor** 에 이 폴더의 `portainer-stack.yml` 내용을 붙여 넣기
3. `volumes` 의 경로(`/opt/chitube/config`, `/mnt/hdd/ChiTube`)를 서버 실제 경로로 바꾸고 **Deploy the stack**

업데이트: 새 파일로 다시 `docker build -t chitube:latest .` → 스택 **Update the stack** (Re-pull 끄기)

## 그래픽카드

- 인텔 퀵싱크: 따로 할 것 없음 (`device_cgroup_rules` 줄을 지우지 마세요)
- 엔비디아: 서버에 NVIDIA Container Toolkit 설치 후 한 번만 `sudo nvidia-ctk runtime configure --runtime=docker --set-as-default && sudo systemctl restart docker`

## 예전 이름(docker_youtube)에서 옮겨 올 때

예전 스택(`docker_youtube`)을 **Stop → Delete** 한 뒤 위 방법으로 `chitube` 스택을 만드세요. 볼륨에 같은 config 폴더 경로를 쓰면 설정 · 구독 · 받은 목록이 그대로 이어집니다.

⚠ 웹 화면에는 비밀번호가 없습니다. 인터넷에 열지 마세요. 자세한 사용법은 [사용 설명서](../MANUAL.md).

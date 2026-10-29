FROM python:3.12-slim
# ffmpeg + 인텔 퀵싱크(VAAPI) 드라이버. 인텔 드라이버는 amd64 만 있음 (ARM NAS·맥은 CPU 인코딩)
#   intel-media-va-driver-non-free: 5세대(Broadwell) 이후, i965-va-driver-shaders: 그 이전 세대
RUN sed -i 's/^Components: main$/Components: main non-free/' /etc/apt/sources.list.d/debian.sources \
 && apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    chromium xvfb x11vnc novnc fonts-nanum tini aria2 \
# ↑ 웹 화면의 "브라우저로 로그인": 컨테이너 안 크롬을 noVNC 로 띄워 직접 로그인 → 쿠키 자동 저장
 && if [ "$(dpkg --print-architecture)" = amd64 ]; then \
      apt-get install -y --no-install-recommends intel-media-va-driver-non-free i965-va-driver-shaders; fi \
 && rm -rf /var/lib/apt/lists/*
# yt-dlp 가 유튜브 페이지의 자바스크립트를 실행하는 데 JS 런타임(deno)이 필요
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" "yt-dlp[default]"
# 엔비디아(NVENC): 드라이버는 호스트의 NVIDIA Container Toolkit 이 넣어줌 (기본 런타임이면 compose 설정 없이 모든 GPU). video = 인코더 사용 권한
ENV NVIDIA_VISIBLE_DEVICES=all HOME=/tmp XDG_CACHE_HOME=/config/cache DENO_DIR=/config/cache/deno PUID=0 PGID=0 \
    NVIDIA_DRIVER_CAPABILITIES=compute,video,utility
WORKDIR /app
COPY entrypoint.sh /entrypoint.sh
# 윈도우에서 받거나 고친 파일은 줄 끝이 CRLF 라 sh 가 "Bad fd number" 로 멈춤 → LF 로 바꿔 둠
RUN sed -i 's/\r$//' /entrypoint.sh
COPY app/ .
# tini: 크롬이 남기는 좀비 프로세스 정리. compose 의 init: true 와 같이 쓰면 tini 가 1번 프로세스가 아니어서
# "Zombie processes will not be re-parented" 경고가 나고 정리를 못 함 → 하위 정리 담당으로 등록
ENV TINI_SUBREAPER=1
ENTRYPOINT ["tini", "--"]
CMD ["sh", "/entrypoint.sh"]

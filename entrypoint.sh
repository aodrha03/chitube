#!/bin/sh
# 컨테이너 시작 (웹 화면의 "재시작해서 업데이트"도 이 과정을 거침)
# 1) yt-dlp·deno 최신화 (유튜브가 자주 바뀜)
PIP_DISABLE_PIP_VERSION_CHECK=1 pip install -q -U --no-cache-dir --root-user-action=ignore 'yt-dlp[default]'  # 업데이트 안내 · root 경고 문구는 끔 (동작엔 영향 없음)
deno upgrade >/dev/null 2>&1

# 2) /config·/downloads 소유권을 PUID/PGID 로 (시놀로지/NAS 파일 권한)
mkdir -p /config/cache /downloads 2>/dev/null  # 폴더를 연결하지 않고 실행해도 시작되게
chown -R "$PUID:$PGID" /config /downloads 2>/dev/null || true

# 3) PUID 로 실제 쓸 수 있는지 확인 → 못 쓰면 sqlite "unable to open database file" 대신 원인을 또렷하게
for d in /config /downloads; do
  if ! setpriv --reuid="$PUID" --regid="$PGID" --clear-groups sh -c "touch $d/.perm_test 2>/dev/null && rm -f $d/.perm_test"; then
    echo "============================================================"
    echo " [권한 오류] '$d' 폴더에 쓸 수 없습니다 (현재 PUID=$PUID PGID=$PGID)."
    echo "  호스트에서 이 폴더를 해당 계정이 쓸 수 있게 해주세요:"
    echo "    - 리눅스/시놀로지(SSH): sudo chown -R $PUID:$PGID <호스트의 그 폴더>"
    echo "    - 시놀로지 DSM: 공유폴더 권한에서 그 계정에 '읽기/쓰기' 허용"
    echo "    - 빠른 확인: .env 에서 PUID=0, PGID=0 으로 두고 다시 실행"
    echo " [Permission error] Cannot write to '$d' (PUID=$PUID PGID=$PGID)."
    echo "  Make the folder writable for that account on the host: sudo chown -R $PUID:$PGID <that folder>,"
    echo "  or on Synology allow Read/Write for the account in shared folder permissions,"
    echo "  or quick check: set PUID=0 and PGID=0 in .env and start again."
    echo "============================================================"
    exit 1
  fi
done

# 4) 서버의 /dev/dri 는 /host 로 보임 → 그대로 연결 (compose 의 device_cgroup_rules 가 사용 허용)
[ ! -e /dev/dri ] && [ -e /host/dev/dri/renderD128 ] && ln -s /host/dev/dri /dev/dri
# 인텔 퀵싱크 장치(/dev/dri)가 연결돼 있으면 그 그룹을 실행 계정에 붙여야 하드웨어 인코딩 가능
if GID=$(stat -c %g /dev/dri/renderD128 2>/dev/null); then GRP="--groups=$GID"; else GRP="--clear-groups"; fi
# 5) PUID/PGID 권한으로 실행
exec setpriv --reuid="$PUID" --regid="$PGID" $GRP uvicorn main:app --host 0.0.0.0 --port 8000

@echo off
chcp 65001 >nul
cd /d "%~dp0"
docker compose stop
echo 치튜브를 멈췄습니다. (설정과 받은 영상은 그대로 남아 있습니다)
echo ChiTube stopped. (Settings and downloaded videos are kept)
pause

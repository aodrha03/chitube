@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 치튜브를 시작합니다. 처음에는 이미지를 만드느라 몇 분 걸립니다...
echo.
docker compose up -d --build
if errorlevel 1 (
  echo.
  echo [오류] Docker Desktop 이 켜져 있는지 확인한 뒤 다시 실행하세요.
  echo        이전 버전 docker_youtube 가 있으면 Docker Desktop 에서 삭제한 뒤 다시 실행하세요.
  pause
  exit /b 1
)
echo.
echo 시작했습니다. 브라우저에서 http://localhost:8945 를 엽니다.
timeout /t 5 >nul
start "" http://localhost:8945

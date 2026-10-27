import collections, copy, glob, http.cookiejar, json, os, random, re, shutil, sqlite3, subprocess, tempfile, threading, time, urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import yt_dlp
import xml.etree.ElementTree as ET
from yt_dlp.cookies import YoutubeDLCookieJar
from yt_dlp.postprocessor import FFmpegMetadataPP, FFmpegSubtitlesConvertorPP, ModifyChaptersPP, SponsorBlockPP
from yt_dlp.postprocessor.metadataparser import MetadataParserPP
import asyncio
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

def _chzzk_vod_formats(self, mpd_url, video_id, *args, query=None, **kwargs):
    """yt-dlp 치지직 다시보기 추출 오류 대체 처리 (2026.08.19 기준): 네이버 재생 정보를 MPD(XML)로 해석하다
    sourceURL 없는 Initialization 에서 KeyError 로 실패함. 같은 주소가 JSON 으로도 오고, 그 안의
    video/mp4 세트가 영상+소리가 합쳐진 화질별 mp4 라 그대로 포맷으로 씀. 안 되면 원래 방식으로."""
    try:
        data = self._download_json(mpd_url, video_id, query=query, headers={"Accept": "application/json"},
                                   note="치지직 재생 정보 받는 중")
        formats = []
        for s in data["period"][0]["adaptationSet"]:
            if s.get("mimeType") != "video/mp4":
                continue
            for r in s.get("representation") or []:
                url = ((r.get("baseURL") or [{}])[0]).get("value")
                vc, _, ac = (r.get("codecs") or "").partition(",")
                if url:
                    formats.append({"url": url, "format_id": r.get("id"), "ext": "mp4", "width": r.get("width"),
                                    "height": r.get("height"), "tbr": (r.get("bandwidth") or 0) / 1000,
                                    "vcodec": vc or None, "acodec": ac or None})
        if formats:
            return formats, {}
    except Exception:  # 응답 형식이 바뀌었으면 yt-dlp 원래 방식에 맡김
        pass
    return _CHZZK_MPD(self, mpd_url, video_id, *args, query=query, **kwargs)


try:  # yt-dlp 가 고쳐지거나 구조가 바뀌어 클래스가 없으면 패치 없이 동작
    from yt_dlp.extractor.chzzk import CHZZKVideoIE
    _CHZZK_MPD = CHZZKVideoIE._extract_mpd_formats_and_subtitles
    CHZZKVideoIE._extract_mpd_formats_and_subtitles = _chzzk_vod_formats
except (ImportError, AttributeError):
    pass

CONFIG = os.environ.get("CONFIG_DIR", "/config")
OUT = os.environ.get("DOWNLOAD_DIR", "/downloads")
DB = os.path.join(CONFIG, "app.db")
COOKIES = os.path.join(CONFIG, "cookies.txt")  # 예전 공용 쿠키 (플랫폼별 파일이 없을 때 사용)
# 플랫폼별 로그인 쿠키 (Netscape cookies.txt) → 멤버십 전용·성인 인증 영상
COOKIE_FILES = {"youtube": os.path.join(CONFIG, "cookies_youtube.txt"), "chzzk": os.path.join(CONFIG, "cookies_chzzk.txt")}
HOST = os.environ.get("HOST_ROOT", "/host")  # compose 에서 서버의 / 를 여기에 연결 → 서버 어느 경로에나 저장

DEFAULTS = {
    "quality": "standard",      # QUALITY 프리셋 | original(원본) | custom(아래 codec/crf 직접)
    "max_height": "1080",       # 최대 해상도(짧은 변 기준이라 세로 숏츠도 정상), 0 = 최고
    "folder": "YouTube",        # 저장 폴더 (/downloads 기준 상대경로). 루트에 바로 두면 유튜버별 폴더가 Plex 에서 쇼로 잡힘
    "codec": "h265",            # custom 일 때만: none | h264 | h265 | av1
    "crf": "26",                # custom 일 때만: 낮을수록 고화질/대용량
    "ratio": "70",              # custom 일 때만: 영상 비트레이트 상한 (원본 대비 %)
    "preset": "fast",           # ultrafast ~ veryslow (느릴수록 같은 화질에 작은 용량, NAS 에선 fast 이하 권장)
    "hwaccel": "auto",          # auto(엔비디아 > 인텔 퀵싱크 > CPU) | cpu | nvenc | vaapi
    "audio_bitrate": "128k",
    "concurrency": "1",         # 유튜브 동시 다운로드 개수 (1~MAX_PARALLEL)
    "chzzk_concurrency": "2",   # 치지직 동시 다운로드 개수 (1~MAX_PARALLEL, 봇 차단 없음)
    "live_concurrency": "2",    # 유튜브 생방송 동시 녹화 개수 (1~MAX_PARALLEL)
    "chzzk_live_concurrency": "5",  # 치지직 생방송 동시 녹화 개수 (1~MAX_PARALLEL)
    "compress_concurrency": "1",        # 유튜브 동시 압축 개수 (다 받은 뒤 압축 · 녹화 후 압축 · 나중에 압축). 다운로드 개수와 따로
    "chzzk_compress_concurrency": "1",  # 치지직 동시 압축 개수
    "daily_limit": "100",       # 24시간 동안 최대 다운로드 개수
    "bot_cooldown_min": "60",   # 차단 신호 감지 시 전체 일시정지 시간
    "sleep_min": "15",          # 영상 사이 대기(초) - 요청 속도를 낮춰 차단 예방
    "sleep_max": "45",
    "sleep_requests": "1",      # 요청 사이 대기(초)
    "rate_limit": "",           # 예: 10M (비우면 무제한)
    "min_free_gb": "20",        # 저장 위치 남은 공간이 이보다 적으면 새 다운로드·녹화 시작 안 함 (0 = 끔)
    "login_refresh_days": "14",  # 로그인한 지 이 날짜가 지나면 화면에 "다시 로그인" 안내 (0 = 끔)
    # 생방송 녹화하면서 압축: off(녹화 후 압축) | gpu(그래픽카드로, 안 되면 녹화 후 압축) | gpu_cpu(그래픽카드 → 안 되면 CPU)
    # 그래픽카드가 없으면 off 와 같음 (CPU 실시간 압축은 못 따라가면 녹화가 끊겨서 그래픽카드가 있을 때만)
    "live_compress": "gpu_cpu",
    "check_interval_min": "360",  # 구독 채널 확인 주기(분), 최소 MIN_INTERVAL
    "sub_fetch_limit": "15",    # 확인 시 탭마다 최신 N개만 조회
    "audit_hours": "4,16",      # 다운로드 점검 시각(시, 쉼표 구분). 비우면 끔
    "subtitles": "all",         # all(직접 만든 자막 전부, 없으면 자동 생성 원어) | manual(직접 만든 자막만) | off
    "video_folder": "1",        # 1 = 영상마다 폴더 (영상·썸네일·자막·nfo 를 한 폴더에) | 0 = 시즌 폴더에 바로
    "stream_compress": "1",     # 1 = 받으면서 바로 압축 (원본·임시 파일 없이 압축본만 디스크에) | 0 = 다 받은 뒤 압축
    "auto_merge": "1",          # 1 = 방송이 끝나면 끊겨서 나뉜 녹화 조각을 자동으로 한 파일로 (형식이 같을 때만, 재인코딩 없음)
    "sponsorblock": "0",        # 1 = 유튜브 영상의 광고·협찬 구간을 SponsorBlock(사용자 제보 공개 DB)에서 찾아 챕터로 표시만 (잘라내지 않음)
    # 탭(플랫폼)별 기본값 - 비우면 위의 공통 설정. 저장 경로는 '/' 로 시작하면 서버 절대 경로
    "youtube_quality": "", "youtube_max_height": "", "youtube_folder": "YouTube",
    "chzzk_quality": "", "chzzk_max_height": "", "chzzk_folder": "Chzzk",
    "youtube_stream_compress": "", "youtube_live_compress": "", "chzzk_stream_compress": "", "chzzk_live_compress": "",  # 압축 방식 (비우면 공통)
}
PLATFORMS = ("youtube", "chzzk")
# (코덱, CRF, 원본 대비 최대 비트레이트 %) - 유튜브 원본(VP9/AV1)은 이미 효율이 좋아서 CRF 만으로는 오히려 커짐 → 상한 필수
# 실측(1080p 10초, 정적/움직임 영상, SSIM dB — 20 이상이면 원본과 구분 어려움):
#   h265 20: 86%·24.2 / ~100%·18.2   h265 22: 77%·23.9 / 93%·17.9   h265 24: 69%·23.7 / 73%·17.2
#   h265 26+상한70: 56%·22.9 / 58%·16.4 (예전 '표준' — 움직임 많은 장면에서 뭉개짐)
#   h264 18~23: 원본 정도(100~108%)·21.6 / ~20 — 유튜브 원본(VP9/AV1)보다 작게는 못 만듦, 호환성용
QUALITY = {"h265_best": ("h265", "20", "100"), "high": ("h265", "22", "100"), "standard": ("h265", "24", "100"),
           "small": ("h265", "26", "70"),
           "h264_best": ("h264", "18", "100"), "compat": ("h264", "23", "100"),
           # AV1 고효율: 화질은 표준 이상, 용량은 최소. 실측(1080p 20초): 원본의 44%, SSIM 0.9955 (표준 71%·0.9945), 압축도 더 빠름
           # 압축 속도 fast(=SVT 8): 6 은 1080p 에서 메모리 2GB 넘게 써서 작은 NAS 에서 강제 종료됨
           "av1": ("av1", "46", "40", "fast")}
OVERRIDES = ("quality", "max_height", "folder")  # 유튜버별/영상별로 덮어쓸 수 있는 항목
TAB_ONLY = ("stream_compress", "live_compress")  # 탭(플랫폼)별로만 정하는 항목 (비우면 공통)
VAAPI_DEV = "/dev/dri/renderD128"  # 인텔 퀵싱크 장치 (compose 에서 /dev/dri 연결)
HW_ENC = {"nvenc": {"h264": "h264_nvenc", "h265": "hevc_nvenc", "av1": "av1_nvenc"},  # AV1 은 RTX 40 이상·인텔 Arc 이상만 (시작할 때 실제로 시험)
          "vaapi": {"h264": "h264_vaapi", "h265": "hevc_vaapi", "av1": "av1_vaapi"}}
CPU_ENC = {"h264": "libx264", "h265": "libx265", "av1": "libsvtav1"}
SVT_PRESET = {"ultrafast": "12", "superfast": "11", "veryfast": "10", "faster": "9", "fast": "8", "medium": "7",
              "slow": "6", "slower": "5", "veryslow": "4"}  # x264/x265 이름 → SVT-AV1 숫자 (클수록 빠름)
HW_NAME = {"cpu": "CPU", "nvenc": "엔비디아", "vaapi": "인텔 퀵싱크"}
NV_PRESET = {"ultrafast": "p1", "superfast": "p1", "veryfast": "p2", "faster": "p3", "fast": "p4", "medium": "p5",
             "slow": "p6", "slower": "p7", "veryslow": "p7"}
HW = {}  # 시작할 때 detect_hw() 로 확인한 실제 동작하는 하드웨어 인코더 {"nvenc": {"h264", "h265"}}
HW_WHY = {}  # 못 쓰는 하드웨어 인코더와 그 이유 (상태 탭에 표시) {"nvenc": "GPU 가 컨테이너에 연결 안 됨 …"}
KINDS = ("videos", "shorts", "streams")          # 동영상 / 숏츠 / 라이브 탭
# 플랫폼별 동시 다운로드·생방송 녹화 상한 (유튜브는 2개 이상부터 봇 차단 위험 → 화면에서 경고)
# ponytail: 상한만큼 작업 스레드를 미리 띄워 둠(다운로드 40 + 녹화 40, 쉴 땐 5초마다 대기열 확인). 더 늘리면 대기열 알림 방식으로
MAX_PARALLEL = 20
CHZZK_CONNS = 8     # 치지직 다시보기 한 개를 몇 갈래로 나눠 받을지 (네이버 CDN 이 연결당 속도를 제한 → 8갈래 실측 약 20배)
MIN_INTERVAL = 30   # 구독 확인 최소 간격(분)
CHZZK_LIVE_SEC = 10  # 치지직 구독 채널 방송 시작 확인 간격(초)
AUDIT_DEPTH = 30    # 점검 시 탭마다 유튜브 최신 N개와 비교
MAX_RETRIES = 3     # 점검 때 실패한 다운로드 자동 재시도 횟수
ADULT_RE = re.compile(r"HTTP Error 401|Unauthorized")  # 치지직 성인 영상을 로그인(성인 인증) 없이 받을 때
ADULT_MSG = "성인 인증 필요 — 치지직 로그인(성인 인증된 계정) 후 '다시 받기' (자동 재시도 안 함)"

BOT_RE = re.compile(r"not a bot|HTTP Error 429|Too Many Requests|try again later|rate.?limit", re.I)
UPCOMING_RE = re.compile(r"will begin|Premieres in|live event will", re.I)
NOT_LIVE_RE = re.compile(r"not currently live", re.I)  # 치지직 API 가 막 시작한 방송을 잠깐 '종료'로 알려 줄 때 yt-dlp 오류
STALL_SEC = 90  # 생방송 녹화 파일이 이만큼 안 커지면 멈춘 것으로 보고 새 파일로 이어서 녹화
CHANNEL_RE = re.compile(r"^(https?://(?:www\.|m\.)?youtube\.com/(?:@[^/?#]+|channel/[^/?#]+|c/[^/?#]+))"
                        r"(?:/(?:videos|shorts|streams|featured|live))?/?$")

# Plex TV 쇼 규칙: 채널/Season 2024/[영상이름/]채널 - s2024e031501 - 2024-03-15 - 제목 [id].ext (+ .jpg .srt .nfo)
# 날짜만 쓰면 같은 날 올라온 영상들을 Plex 가 한 에피소드로 합쳐버려서 시즌=연도, 에피소드=월일+순번 사용
# 채널·제목은 바이트 수 제한 (한글은 글자당 3바이트 → 긴 제목이면 파일 이름 한도 255바이트를 넘음)
SHOW_TMPL = "%(fname_channel).60B"
NAME_TMPL = SHOW_TMPL + " - {ep} - %(upload_date>%Y-%m-%d)s - %(fname_title).100B [%(id)s]"
# 이모지는 파일 이름에서만 뺌: 시놀로지 암호화 공유 폴더(이름 143바이트 제한)·일부 SMB/NTFS 에서 저장 실패 원인
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿‍︎️⃣\U000E0020-\U000E007F]")


def plain_name(s):
    return re.sub(r"\s{2,}", " ", EMOJI_RE.sub("", s or "")).strip() or "제목 없음"


CHZZK_CH_RE = re.compile(r"^https?://chzzk\.naver\.com/(?:live/)?([0-9a-f]{32})(?:/(?:videos|live))?/?(?:\?.*)?$")


def outtmpl(ep, per_video, chzzk=False):
    """per_video 면 영상마다 '영상이름/' 폴더를 만들어 영상·썸네일·자막·nfo 를 함께 넣음
    치지직은 Plex 규칙 없이 스트리머/날짜 - 제목/ (파일 이름 끝 [ID] 는 녹화 중지·조각 정리·같은 제목 구분에 필요)"""
    if chzzk:
        name = "%(upload_date>%Y-%m-%d)s - %(fname_title).100B"
        return f"{SHOW_TMPL}/" + (name + "/" if per_video else "") + name + " [%(id)s].%(ext)s"
    name = NAME_TMPL.replace("{ep}", ep)
    return f"{SHOW_TMPL}/Season %(upload_date>%Y)s/" + (name + "/" if per_video else "") + name + ".%(ext)s"

LIVE = {}   # job_id -> 실시간 진행 상태 (DB에 매번 쓰지 않음)
CANCEL = set()  # 취소 요청된 job_id
STATE = {"next_at": 0, "paused_until": 0, "pause_reason": ""}
WAKE = threading.Event()  # "지금 확인" · "지금 점검" → 구독 확인 스레드를 바로 깨움 (예전엔 최대 1분 기다렸다 시작)
LOG = collections.deque(maxlen=200)  # ponytail: 활동 기록은 메모리에만 (재시작 시 초기화)
THREADS = {}
STARTED = time.time()
VERSIONS = {}
APP_VERSION = "1.2.4"       # 수정할 때마다 올리고 CHANGELOG.md 에 릴리스 노트 추가
UPDATE_CHECK_SEC = 12 * 3600  # yt-dlp/deno 최신 버전 확인 주기


def q(sql, args=()):
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        with c:
            return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()


def init_db():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY, url TEXT UNIQUE, name TEXT,
        enabled INTEGER DEFAULT 1, last_checked REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, video_id TEXT UNIQUE, url TEXT, title TEXT,
        sub_id INTEGER, status TEXT DEFAULT 'queued', progress REAL DEFAULT 0, filepath TEXT,
        error TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS audits(id INTEGER PRIMARY KEY, started REAL, finished REAL, result TEXT);
    """)
    for t, col in (("jobs", "thumb TEXT"), ("jobs", "retries INTEGER DEFAULT 0"), ("jobs", "meta TEXT"), ("jobs", "opts TEXT"), ("jobs", "kind TEXT"), ("jobs", "live INTEGER DEFAULT 0"), ("jobs", "pri INTEGER DEFAULT 0"),
                   ("jobs", "started REAL"), ("jobs", "cut REAL"),  # 받기(녹화) 시작 시각, 생방송 녹화가 끊긴 시각
                   ("jobs", "finished REAL"), ("jobs", "live_open TEXT"), ("jobs", "err_seen INTEGER DEFAULT 0"),  # err_seen: 오류를 확인함(목록·상태에서 숨김)
                   ("subs", "avatar TEXT"), ("subs", "quality TEXT"),
                   ("subs", "max_height TEXT"), ("subs", "folder TEXT"), ("subs", "kinds TEXT"),
                   ("subs", "interval_min TEXT"), ("subs", "last_error TEXT"), ("subs", "last_found INTEGER"),
                   ("subs", "title_inc TEXT"), ("subs", "title_exc TEXT"), ("subs", "min_min TEXT")):
        try:  # 기존 DB 업그레이드
            c.execute(f"ALTER TABLE {t} ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    c.close()
    # 예전 버그(v0.22.0 이전: 점검이 끝난 생방송을 다시 녹화)로 녹화 파일이 있는데 '오류'가 되고 시작 시각이 덮어써진 기록 바로잡기
    for r in q("SELECT id, filepath, created, started, cut FROM jobs WHERE COALESCE(live,0)=1 AND status='error' AND filepath IS NOT NULL"):
        if os.path.isfile(r["filepath"]):
            q("UPDATE jobs SET status='done', error=NULL, started=? WHERE id=?",
              (r["created"] if r["cut"] and r["started"] and r["cut"] < r["started"] else r["started"], r["id"]))


def settings():
    s = dict(DEFAULTS)
    s.update({r["key"]: r["value"] for r in q("SELECT * FROM settings")})
    return s


def log(msg):
    LOG.appendleft({"t": time.time(), "msg": msg})
    print(time.strftime("%m-%d %H:%M:%S"), msg, flush=True)


def paused():
    return STATE["paused_until"] > time.time()


def cooldown(reason):
    mins = int(settings()["bot_cooldown_min"])
    STATE["paused_until"] = time.time() + mins * 60
    STATE["pause_reason"] = reason[:300]
    log(f"유튜브 차단 신호 감지 → {mins}분간 다운로드/확인 일시정지")


def done_today():  # 유튜브만 (하루 한도는 유튜브 봇 차단용 — 치지직은 세지 않음)
    return q("SELECT COUNT(*) n FROM jobs WHERE status='done' AND finished > ? AND url NOT LIKE '%chzzk.naver.com%'",
             (time.time() - 86400,))[0]["n"]


def resolve(s, *layers):
    """기본 설정 위에 유튜버별 → 영상별 설정을 덮어쓰고 화질 프리셋을 실제 값으로 변환."""
    s = dict(s)
    for layer in layers:
        s.update({k: v for k, v in layer.items() if k in OVERRIDES and v not in (None, "")})
    if s["quality"] == "original":
        s["codec"], s["max_height"] = "none", "0"
    elif s["quality"] in QUALITY:
        s["codec"], s["crf"], s["ratio"], *preset = QUALITY[s["quality"]]
        s["preset"] = preset[0] if preset else s["preset"]  # 프리셋이 정한 압축 속도가 있으면 그걸로
    return s


def job_settings(job):
    """공통 설정 → 탭(플랫폼) 기본값 → 채널(구독)별 → 영상별 순으로 덮어씀"""
    s, p = settings(), platform_of(job["url"])
    subs = q("SELECT quality, max_height, folder FROM subs WHERE id=?", (job["sub_id"],)) if job["sub_id"] else []
    s = s | {k: s[f"{p}_{k}"] or s[k] for k in TAB_ONLY}
    return resolve(s, {k: s[f"{p}_{k}"] for k in OVERRIDES}, *subs, json.loads(job["opts"] or "{}"))


def platform_of(url):
    return "chzzk" if "chzzk.naver.com" in (url or "") else "youtube"


def safe_dir(rel):
    """'/' 로 시작하면 서버 절대 경로 (/volume1/video → 컨테이너의 /host/volume1/video), 아니면 다운로드 폴더 아래"""
    rel = (rel or "").strip()
    base = HOST if rel.startswith("/") else OUT
    if base == HOST and not os.path.isdir(HOST):
        raise ValueError("절대 경로를 쓰려면 docker-compose.yml 에 서버 루트 연결(- /:/host)이 필요합니다")
    p = os.path.normpath(os.path.join(base, rel.lstrip("/")))
    if os.path.commonpath([p, base]) != base:  # ../ 로 빠져나가기 방지
        raise ValueError("잘못된 경로입니다")
    return p


def cookie_file(url):
    """그 플랫폼의 로그인 쿠키 파일 (없으면 예전 공용 cookies.txt)"""
    return next((f for f in (COOKIE_FILES[platform_of(url)], COOKIES) if os.path.exists(f)), None)


def clean_opts(body):
    o = {k: str(getattr(body, k) or "").strip() for k in OVERRIDES}
    try:
        safe_dir(o["folder"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return o


def clean_sub(body):
    kinds = ",".join(k for k in KINDS if k in body.kinds.split(",")) or "videos"
    iv = body.interval_min.strip()
    if iv and (not iv.isdigit() or int(iv) < MIN_INTERVAL):
        raise HTTPException(400, f"확인 주기는 {MIN_INTERVAL}분 이상이어야 합니다")
    mm = body.min_min.strip()
    if mm and not mm.isdigit():
        raise HTTPException(400, "최소 길이는 분 단위 숫자로 적어 주세요")
    return kinds, iv, (body.title_inc.strip(), body.title_exc.strip(), mm)


def sub_match(f, e):
    """구독 필터: 제목에 포함 단어(쉼표 구분, 하나라도) 있고, 제외 단어는 없고, 길이가 최소 길이(분) 이상인 영상만.
    길이를 모르는 영상(생방송 등)은 길이 조건 통과"""
    t = (e.get("title") or "").lower()
    words = lambda k: [w.strip().lower() for w in (f[k] or "").split(",") if w.strip()]
    inc, exc = words("title_inc"), words("title_exc")
    return ((not inc or any(w in t for w in inc)) and not any(w in t for w in exc)
            and not (f["min_min"] and e.get("duration") and e["duration"] < int(f["min_min"]) * 60))


def base_opts(s, url=""):
    o = {"quiet": True, "no_warnings": True, "noprogress": True, "sleep_interval_requests": float(s["sleep_requests"]),
         # ? : * | " < > 와 끝의 점·공백을 안전한 글자로 → NAS 공유 폴더(SMB)·exFAT·NTFS 에 저장해도 "Invalid argument" 안 남
         "windowsfilenames": True}
    if cf := cookie_file(url):  # 로그인 쿠키 → 멤버십·성인 영상
        # yt-dlp 는 끝날 때 갖고 있던 쿠키를 그 파일에 다시 씀 → 진행 중이던 작업이 다시 로그인한 새 쿠키를
        # 옛 쿠키로 덮어쓰고, 여러 작업이 동시에 쓰면 파일이 꼬임. 스레드마다 복사본을 주고 원본은 로그인할 때만 바뀜
        tmp = f"/tmp/cookies-{threading.get_ident()}.txt"
        shutil.copyfile(cf, tmp)
        os.chmod(tmp, 0o600)
        o["cookiefile"] = tmp
    if s["rate_limit"]:
        o["ratelimit"] = yt_dlp.utils.parse_bytes(s["rate_limit"])
    return o


def channel_base(url):
    m = CHANNEL_RE.match(url.strip())
    return m.group(1) if m else None


def normalize(url):
    url = url.strip()
    # 채널 기본 URL은 탭(동영상/Shorts/라이브)이 중첩 목록으로 나오므로 '동영상' 탭으로 고정
    if re.match(r"^https?://(www\.|m\.)?youtube\.com/(@[^/?]+|channel/[^/?]+|c/[^/?]+)/?$", url):
        url = url.rstrip("/") + "/videos"
    return url


def sub_urls(sub):
    m = CHZZK_CH_RE.match(sub["url"].strip())
    if m:  # 치지직: 다시보기(videos) / 생방송(streams). 숏츠 없음
        return [f"https://chzzk.naver.com/{m.group(1)}" + ("/live" if k == "streams" else "")
                for k in (sub["kinds"] or "videos").split(",") if k != "shorts"]
    b = channel_base(sub["url"])
    return [f"{b}/{k}" for k in (sub["kinds"] or "videos").split(",")] if b else [sub["url"]]


def next_check(sub, s):
    return sub["last_checked"] + max(MIN_INTERVAL, int(sub["interval_min"] or s["check_interval_min"])) * 60


def list_entries(url, limit=None):
    """URL(채널 탭/재생목록/영상) → (최신순 영상 목록, 이름, 종류). 예정된 라이브는 시작 후 다음 확인 때."""
    if CHZZK_CH_RE.match(url.strip()):  # 치지직 채널/생방송 주소는 yt-dlp 가 목록을 못 만들어 공개 API 로
        return chzzk_entries(url, limit)
    # noplaylist: "watch?v=영상&list=재생목록" 은 영상 하나만 (믹스 재생목록이면 수백 개가 들어감). 재생목록 주소는 그대로 목록
    # lang=ko: yt-dlp 기본은 영어(hl=en)로 요청해서 목록 제목이 영어 번역으로 옴 (받은 파일은 원래 제목).
    # 목록에만 적용 — 영상 받기에 쓰면 날짜 등 일부 정보 추출이 틀릴 수 있다고 yt-dlp 가 경고함
    o = base_opts(settings(), url) | {"extract_flat": "in_playlist", "noplaylist": True,
                                      "extractor_args": {"youtube": {"lang": ["ko"]}}}
    if limit:
        o["playlistend"] = limit
    url = normalize(url)
    kind = "shorts" if "/shorts" in url else "streams" if re.search(r"/(streams|live)\b", url) else "videos"
    with yt_dlp.YoutubeDL(o) as y:
        info = y.extract_info(url, download=False)
    entries = [e for e in info.get("entries") or [info] if e and e.get("id") and e.get("live_status") != "is_upcoming"]
    return entries, info.get("channel") or info.get("uploader") or info.get("title"), kind


def add_entries(entries, kind, sub_id=None, opts=None, filt=True):
    added = 0
    if f := filt and sub_id and q("SELECT title_inc, title_exc, min_min FROM subs WHERE id=?", (sub_id,)):
        entries = [e for e in entries if sub_match(f[0], e)]
    for e in entries:
        # 이미 수동으로 받은 영상이면 구독에 연결만 (RETURNING 은 실제 변경된 행만 나옴)
        added += len(q("""INSERT INTO jobs(video_id,url,title,sub_id,opts,kind,live,thumb,created,live_open) VALUES(?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(video_id) DO UPDATE SET sub_id=excluded.sub_id
                          WHERE jobs.sub_id IS NULL AND excluded.sub_id IS NOT NULL RETURNING id""",
                       (e["id"], e.get("webpage_url") or e.get("url"), e.get("title"), sub_id, json.dumps(opts or {}),
                        kind, int(e.get("live_status") == "is_live"), e.get("thumbnail"), time.time(), e.get("open_date"))))
    return added


def enqueue(url, sub_id=None, limit=None, opts=None):
    entries, name, kind = list_entries(url, limit)
    return add_entries(entries, kind, sub_id, opts), name


def load_jar(path):
    jar = YoutubeDLCookieJar(path)  # yt-dlp 와 같은 방식으로 읽음 (#HttpOnly_ 줄 등)
    jar.load(ignore_discard=True, ignore_expires=True)
    return jar


def chzzk_api(path):
    """치지직 API (채널 목록·생방송 상태는 yt-dlp 가 지원하지 않아 직접 조회). 로그인 쿠키가 있으면 같이 보냄 (성인 방송 등)"""
    headers = {"User-Agent": "Mozilla/5.0"}
    if cf := cookie_file("chzzk.naver.com"):
        headers["Cookie"] = "; ".join(f"{c.name}={c.value}" for c in load_jar(cf) if c.domain.lstrip(".").endswith("naver.com"))
    url = path if path.startswith("http") else "https://api.chzzk.naver.com/service" + path
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as r:
        return json.load(r)["content"]


def chzzk_live(cid):
    """지금 방송 중이면 [방송] 아니면 []. 생방송은 yt-dlp ID 가 채널 ID 라 방송마다 같음 → 방송 ID 로 구분해야 다음 방송도 녹화됨"""
    live = chzzk_api(f"/v3/channels/{cid}/live-detail") or {}
    if live.get("status") != "OPEN":
        return []
    return [{"id": f"chzzk-live-{live['liveId']}", "url": f"https://chzzk.naver.com/live/{cid}",
             "title": live.get("liveTitle"), "live_status": "is_live", "open_date": live.get("openDate"),
             "thumbnail": (live.get("liveImageUrl") or "").replace("{type}", "480") or None}]


def chzzk_entries(url, limit=None):
    """치지직 채널 주소 → (영상 목록, 채널명, 종류). 주소에 '/live' 가 있으면 지금 방송, 없으면 최신 다시보기."""
    cid = CHZZK_CH_RE.match(url.strip()).group(1)
    name = chzzk_api(f"/v1/channels/{cid}")["channelName"]
    if "/live" in url:
        entries = chzzk_live(cid)
        if not entries and limit is None:  # 바로 다운로드에서 넣은 경우만 알려줌 (구독 확인 땐 조용히 넘어감)
            raise yt_dlp.utils.DownloadError(f"치지직 {name}: 지금 방송 중이 아닙니다")
        return entries, name, "streams"
    vods, page, pages = [], 0, 1  # 한 번에 최대 50개 → limit 없으면(기존 영상 전부) 마지막 페이지까지
    while page < pages and (limit is None or len(vods) < limit):
        c = chzzk_api(f"/v1/channels/{cid}/videos?sortType=LATEST&pagingType=PAGE&page={page}&size={min(limit or 50, 50)}")
        vods, page, pages = vods + c["data"], page + 1, c.get("totalPages") or 1
    vods = [v for v in vods[:limit] if not recorded_replay(cid, v)]
    return [{"id": str(v["videoNo"]), "url": f"https://chzzk.naver.com/video/{v['videoNo']}",
             "title": v.get("videoTitle"), "thumbnail": v.get("thumbnailImageUrl"), "duration": v.get("duration")} for v in vods], name, "videos"


REPLAY_SEEN = {}  # 다시보기 번호 → 생방송 녹화로 이미 받은 방송인지 (확인 결과 기억, 매번 API 안 부르게)


def recorded_replay(cid, v):
    """생방송 녹화로 이미 받은 방송의 다시보기면 True. 다시보기 상세의 liveOpenDate == 녹화 때 저장한 방송 시작 시각(openDate)"""
    no = str(v["videoNo"])
    if v.get("videoType") != "REPLAY" or q("SELECT 1 FROM jobs WHERE video_id=?", (no,)):
        return False
    if no not in REPLAY_SEEN:
        live_url = f"https://chzzk.naver.com/live/{cid}"
        if not q("SELECT 1 FROM jobs WHERE url=? AND live_open IS NOT NULL LIMIT 1", (live_url,)):
            return False  # 이 채널 녹화가 없으면 상세 조회 안 함 (기억도 안 함 → 나중에 녹화하면 다시 확인)
        try:
            opened = chzzk_api(f"/v3/videos/{no}").get("liveOpenDate")
        except Exception:
            return False
        rec = q("SELECT filepath, meta, status FROM jobs WHERE url=? AND live_open=? AND status IN ('done','queued','downloading')", (live_url, opened))
        if any(r["status"] != "done" for r in rec):  # 녹화 · 압축이 아직 안 끝남 → 이번엔 받지 않고 다음 확인 때 다시 판단 (기억 안 함)
            return True
        if not rec:
            REPLAY_SEEN[no] = False
            return False
        # 녹화가 방송 전체를 담았을 때만 건너뜀. 늦게 발견했거나 끊겨서 빠진 구간이 있으면(다시보기의 90% 미만) 다시보기도 받음
        got = sum(json.loads(r["meta"] or "{}").get("duration") or (probe_duration(r["filepath"]) if r["filepath"] and os.path.isfile(r["filepath"]) else 0)
                  for r in rec)
        REPLAY_SEEN[no] = not v.get("duration") or got >= v["duration"] * 0.9
        log(f"생방송 녹화로 받은 방송이라 다시보기는 건너뜀: {v.get('videoTitle')}" if REPLAY_SEEN[no] else
            f"녹화가 방송 일부만 담고 있어 다시보기도 받음 ({int(got // 60)}분 / {v['duration'] // 60}분): {v.get('videoTitle')}")
    return REPLAY_SEEN[no]


def show_dir(video_path):
    """영상 파일 → 채널(쇼) 폴더 = 포스터·tvshow.nfo 위치. 영상별 폴더를 쓰면 한 단계 더 위."""
    d = os.path.dirname(video_path)
    if not os.path.basename(d).startswith("Season "):
        d = os.path.dirname(d)
    return os.path.dirname(d)


def host_env(proc="/proc/version"):
    """실행 환경 → (종류, 화면에 보일 이름). 컨테이너 안에서 서버 전체(/host)와 커널 정보로 구분
    (윈도우 Docker Desktop 은 WSL2 커널, 맥은 리눅스 가상 머신 안에 맥의 /Users 가 보임, 시놀로지는 전용 설정 파일)"""
    try:
        kernel = open(proc).read().lower()
    except OSError:
        kernel = ""
    if "microsoft" in kernel:
        return "windows", "윈도우 (Docker Desktop)"
    if os.path.isdir(os.path.join(HOST, "Users")):
        return "mac", "맥 (Docker 가상 머신)"
    if any(os.path.exists(os.path.join(HOST, f)) for f in ("etc/synoinfo.conf", "etc.defaults/VERSION")):
        return "synology", "시놀로지 DSM"
    try:
        name = re.search(r'PRETTY_NAME="?([^"\n]+)', open(os.path.join(HOST, "etc/os-release")).read()).group(1)
    except (OSError, AttributeError):
        name = ""
    return "linux", f"리눅스 · {name}" if name else "리눅스"


# 하드웨어 가속이 안 될 때 환경별 이유 (장치가 컨테이너에 안 보일 때). 리눅스는 서버 설정으로 고칠 수 있어 방법까지
NO_HW_WHY = {
    "windows": {"vaapi": "윈도우 Docker Desktop 은 인텔 · AMD 내장 그래픽을 컨테이너에 연결하지 못합니다 → CPU 로 압축",
                "nvenc": "윈도우 Docker Desktop 에서는 엔비디아 그래픽카드 압축을 지원하지 않습니다 → CPU 로 압축 (느리면 화질을 '원본 그대로')"},
    "mac": {"vaapi": "맥은 Docker 가 가상 머신 안에서 돌아가 그래픽(애플 메탈)을 쓸 수 없습니다 → CPU 로 압축",
            "nvenc": "맥에는 엔비디아 그래픽카드가 없습니다 → CPU 로 압축 (느리면 화질을 '원본 그대로')"},
    "synology": {"vaapi": "이 시놀로지 모델에는 인텔 그래픽(퀵싱크)이 없습니다 (ARM · AMD 모델) → CPU 로 압축",
                 "nvenc": "시놀로지 Container Manager 는 엔비디아 그래픽카드를 지원하지 않습니다 → CPU 로 압축"},
    "linux": {"vaapi": f"{VAAPI_DEV} 없음 → 서버에 인텔 내장 그래픽이 없습니다 (있으면 자동 연결) → CPU 로 압축",
              "nvenc": "GPU 가 컨테이너에 연결 안 됨 → 서버에 NVIDIA 드라이버 + NVIDIA Container Toolkit 설치, "
                       "기본 런타임으로 설정: sudo nvidia-ctk runtime configure --runtime=docker --set-as-default → 도커 재시작"},
}


def detect_hw():
    """하드웨어 인코더를 작은 테스트 영상으로 실제 인코딩해 보고 되는 것만 기록 (드라이버/장치 없으면 실패 → CPU).
    인텔 퀵싱크는 VAAPI 로 사용 (데비안 ffmpeg 에 qsv 인코더가 없음, 같은 하드웨어)."""
    env = STATE.setdefault("env", host_env())[0]
    for hw, encs in HW_ENC.items():
        if (hw == "vaapi" and not os.path.exists(VAAPI_DEV)) or (hw == "nvenc" and not os.path.exists("/dev/nvidiactl")):
            HW_WHY[hw] = NO_HW_WHY[env][hw]  # 장치가 컨테이너에 안 보임 → 환경에 맞는 이유
            continue
        for codec, enc in encs.items():
            pre, vf = (["-vaapi_device", VAAPI_DEV], ["-vf", "format=nv12,hwupload"]) if hw == "vaapi" else ([], [])
            r = subprocess.run(["ffmpeg", "-v", "error", *pre, "-f", "lavfi", "-i", "color=s=256x256:d=0.2", *vf,
                                "-frames:v", "1", "-c:v", enc, "-f", "null", "-"], capture_output=True, timeout=60)
            if r.returncode == 0:
                HW.setdefault(hw, set()).add(codec)
            else:  # 실패 이유 (예: 드라이버가 너무 오래됨 "Driver does not support the required nvenc API version")
                HW_WHY[hw] = (r.stderr.decode(errors="replace").strip().splitlines() or ["알 수 없음"])[-1][:200]
    for hw in HW:
        HW_WHY.pop(hw, None)
    log("영상 인코딩 장치: " + (", ".join(f"{HW_NAME[h]}({'/'.join(sorted(c))})" for h, c in HW.items()) or "CPU 만 사용"))
    for hw, why in HW_WHY.items():
        log(f"{HW_NAME[hw]} 사용 안 됨: {why}")


def encoder_for(s):
    """auto = 엔비디아 > 인텔 > CPU. 고른 장치가 이 코덱을 못 하면 CPU (GPU 없는 제온 등)."""
    want = ("nvenc", "vaapi") if s["hwaccel"] == "auto" else (s["hwaccel"],)
    return next((h for h in want if s["codec"] in HW.get(h, ())), "cpu")


def ffmpeg_cmd(src, dst, s, vbit=0, tags=None, hw="cpu", size=None):
    """vbit = 원본 영상 비트레이트(bps). 있으면 '원본 대비 ratio%' 상한을 걸어 용량이 확실히 줄게 함.
    tags = 파일에 넣을 메타데이터 (원본에 태그가 없는 라이브 녹화본용). hw = cpu | nvenc | vaapi. size = encode_args 참고"""
    pre, enc = encode_args(s, vbit, hw, size=size)
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *pre, "-i", src, "-map", "0:v:0", "-map", "0:a:0?", *enc,
            "-map_metadata", "0", *[a for k, v in (tags or {}).items() if v for a in ("-metadata", f"{k}={v}")],
            "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", dst]


def encode_args(s, vbit=0, hw="cpu", ts=False, size=None):
    """→ (입력 앞에 둘 옵션, 영상·소리 압축 옵션). 다 받은 뒤 압축(ffmpeg_cmd)과 받으면서 압축(run_job) 공용.
    ts = 생방송 녹화(MPEG-TS 로 씀) — hvc1 태그는 mp4 전용이라 TS 에 넣으면 ffmpeg 가 거부
    size = (가로, 세로) 생방송 녹화하면서 압축할 때 출력 크기 고정: 방송 중 해상도·화면 형식이 바뀌면(방송 설정 변경 등)
    ffmpeg 가 필터를 다시 만들고, 이미 시작한 압축기는 크기가 달라진 화면을 거부해 녹화가 오류로 끝났음 (원본 그대로 녹화는 영향 없음)"""
    pre = []
    fix = f"scale={size[0]}:{size[1]}" if size and all(size) else ""
    if s["codec"] == "copy":  # 영상은 그대로, 오디오만 다시 인코딩 (라이브 녹화본 mp4 변환용)
        v = ["-c:v", "copy"] + (["-tag:v", "hvc1"] if s.get("src_codec") == "h265" else [])
    else:
        cap = int(vbit * int(s["ratio"]) / 100) if vbit and s.get("ratio") else 0
        limit = ["-maxrate", str(cap), "-bufsize", str(cap * 2)] if cap else []
        if hw == "nvenc":  # -cq 가 CRF 역할 (같은 0~51 범위), -b:v 0 = 화질 기준 VBR
            v = ["-c:v", HW_ENC["nvenc"][s["codec"]], "-preset", NV_PRESET.get(s["preset"], "p4"),
                 "-rc", "vbr", "-cq", str(s["crf"]), "-b:v", "0", *limit]
        elif hw == "vaapi":  # 상한이 있으면 그 비트레이트로, 없으면(라이브) 고정 화질
            pre = ["-vaapi_device", VAAPI_DEV]
            v = ["-vf", (fix + "," if fix else "") + "format=nv12,hwupload", "-c:v", HW_ENC["vaapi"][s["codec"]],
                 *(["-rc_mode", "VBR", "-b:v", str(cap), "-maxrate", str(cap)] if cap else
                   # AV1 의 qp 는 0~255 단위 (CRF 0~63 의 약 4배) → 그대로 넣으면 거의 무압축
                   ["-rc_mode", "CQP", "-qp", str(min(int(s["crf"]) * 4, 255) if s["codec"] == "av1" else s["crf"])])]
        elif s["codec"] == "av1":  # SVT-AV1: 숫자 프리셋, 10비트(같은 용량에 띠 현상 적음)
            v = ["-c:v", CPU_ENC["av1"], "-crf", str(s["crf"]), "-preset", SVT_PRESET.get(s["preset"], "8"),
                 "-pix_fmt", "yuv420p10le", *limit]
        else:
            v = ["-c:v", CPU_ENC[s["codec"]], "-crf", str(s["crf"]), "-preset", s["preset"], *limit]
            if s["codec"] == "h265" and 2 <= (n := len(os.sched_getaffinity(0))) <= 3:
                # x265 는 코어가 적으면 스레드 풀을 안 만들어 사실상 싱글로 압축 (실측 2코어: 12.3초 → 8.3초). 코어 많은 PC 는 원래 멀티라 그대로
                v += ["-x265-params", f"pools={n}:frame-threads=2"]
        if fix and hw != "vaapi":
            v += ["-vf", fix + ("" if s["codec"] == "av1" else ",format=yuv420p")]  # AV1 은 -pix_fmt 로 고정됨
        if s["codec"] == "h265" and not ts:
            v += ["-tag:v", "hvc1"]  # Apple/Plex 다이렉트 재생용
    # 생방송: 소리 형식(샘플레이트·채널)이 중간에 바뀌어도 같은 형식으로 → 소리 압축기가 멈추지 않게
    return pre, [*v, "-c:a", "aac", "-b:a", s["audio_bitrate"], *(["-ar", "48000", "-ac", "2"] if ts and s["codec"] != "copy" else [])]


def episode_code(season_dir, upload_date, vid):
    """s{연도}e{월일}{순번 01~99}. 같은 영상을 다시 받으면 기존 번호 유지, 아니면 그날 비어 있는 첫 순번.
    ponytail: 같은 채널·같은 날 영상을 동시에 받으면 순번이 겹칠 수 있음 (동시 다운로드 1개 권장이라 둠)"""
    prefix = f"s{upload_date[:4]}e{upload_date[4:]}"
    used = set()
    for f in glob.glob(os.path.join(glob.escape(season_dir), f"* - {prefix}?? - *")):
        m = re.search(rf"{prefix}\d\d", os.path.basename(f))
        if not m:  # ?? 에 숫자 아닌 글자가 들어간 다른 파일
            continue
        if f"[{vid}]" in f:
            return m.group()
        used.add(m.group())
    return next(c for c in (f"{prefix}{i:02d}" for i in range(1, 100)) if c not in used)


def ensure_poster(video_path, info, sub_id):
    """Plex 쇼 포스터: 채널 폴더(채널/Season/영상)에 poster.jpg 가 없으면 채널 프로필 사진 저장 (채널당 한 번)"""
    poster = os.path.join(show_dir(video_path), "poster.jpg")
    if os.path.exists(poster):
        return
    url = next(iter(q("SELECT avatar FROM subs WHERE id=?", (sub_id,))), {}).get("avatar") if sub_id else None
    if not url and "chzzk" in (info.get("extractor_key") or "").lower() and info.get("channel_id"):
        url = chzzk_api(f"/v1/channels/{info['channel_id']}").get("channelImageUrl")
    elif not url and info.get("channel_url"):  # 수동 다운로드: 채널 정보를 한 번 조회
        with yt_dlp.YoutubeDL(base_opts(settings(), info["channel_url"]) | {"extract_flat": "in_playlist", "playlistend": 1}) as y:
            url = avatar_of(y.extract_info(info["channel_url"] + "/videos", download=False))
    if url:  # webp 등으로 올 수 있어 ffmpeg 로 jpg 변환. "=s0"(원본 크기)는 너무 커서 ffmpeg 가 죽음 → 1000px 로 요청
        url = re.sub(r"=s\d+[^/]*$", "=s1000", url)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", url, "-frames:v", "1", poster],
                       timeout=60, check=True, capture_output=True)


def subtitle_langs(raw, mode):
    """받을 자막 언어. 직접 올린 자막은 전부, 자동 생성은 원래 언어 하나만
    (자동 번역까지 받으면 영상 하나에 100개 넘는 파일·요청 → 봇 차단 위험)."""
    if mode == "off":
        return []
    langs = [k for k in raw.get("subtitles") or {} if k != "live_chat"]
    auto = raw.get("automatic_captions") or {}
    if mode == "all":  # 자동 생성 원어 자막도 (직접 만든 자막과 같은 언어면 생략)
        orig = [k for k in auto if k.endswith("-orig")] or ([raw["language"]] if raw.get("language") in auto else [])
        langs += [k for k in orig if k.removesuffix("-orig") not in langs]
    return langs


def write_nfo(video_path, meta, title, vid):
    """Jellyfin/Kodi/Emby 용 메타데이터 (Plex 는 .nfo 를 안 읽고 mp4 안의 태그를 읽음).
    영상마다 "영상이름.nfo", 채널 폴더에 tvshow.nfo"""
    base = os.path.splitext(video_path)[0]
    # 파일명은 s{연도}e{월일}{순번} (예: s2015e071501). Plex 가 파일명에서 읽는 번호(int(071501)=71501)와
    # 맞춰야 Jellyfin/Plex 가 같은 에피소드로 인식하고, 같은 연도 다른 날끼리 번호가 안 겹친다
    name = os.path.basename(base)
    m = re.search(r" - s(\d{4})e(\d{6}) - ", name)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
    else:  # 구버전 파일명(시즌/에피소드 없음) → 날짜로 역산. 그날 영상 목록에서 몇 번째인지 순번으로 쓴다
        d = re.search(r"(\d{4})-(\d{2})-(\d{2})", name)
        if d:
            season = int(d.group(1))
            day = "-".join(d.groups())
            # 영상 파일만 센다 (.nfo/.jpg 를 세면 재실행할 때마다 번호가 달라진다)
            vids = sorted(f for f in os.listdir(os.path.dirname(video_path))
                          if day in f and f.rsplit(".", 1)[-1].lower() in ("mp4", "mkv", "webm", "mov"))
            episode = (vids.index(os.path.basename(video_path)) + 1) if os.path.basename(video_path) in vids else 1
        else:
            season = episode = None
    ud = meta.get("upload_date") or ""
    aired = f"{ud[:4]}-{ud[4:6]}-{ud[6:]}" if len(ud) == 8 else None
    channel = meta.get("channel") or meta.get("uploader")

    def save(root, fields, path):
        for k, v in fields:
            if v:
                ET.SubElement(root, k).text = str(v)
        ET.SubElement(root, "uniqueid", type="youtube", default="true").text = vid if root.tag != "tvshow" else channel
        ET.indent(root)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    save(ET.Element("episodedetails"),
         (("title", title), ("showtitle", channel), ("season", season), ("episode", episode),
          ("aired", aired), ("premiered", aired), ("plot", meta.get("description")),
          ("runtime", meta.get("duration") and round(meta["duration"] / 60)), ("studio", "YouTube"),
          ("thumb", os.path.basename(base) + ".jpg")), base + ".nfo")
    show = os.path.join(show_dir(video_path), "tvshow.nfo")
    if channel and not os.path.exists(show):
        save(ET.Element("tvshow"), (("title", channel), ("studio", "YouTube"), ("thumb", "poster.jpg")), show)


def backfill_nfo():
    """이전 버전에서 받은 영상에도 nfo 생성 (DB 정보만 사용, 유튜브 요청 없음)"""
    n = 0
    for j in q("SELECT video_id, url, title, filepath, meta FROM jobs WHERE status='done'"):
        if platform_of(j["url"]) == "youtube" and j["filepath"] and os.path.exists(j["filepath"]) and not os.path.exists(os.path.splitext(j["filepath"])[0] + ".nfo"):
            try:
                write_nfo(j["filepath"], json.loads(j["meta"] or "{}"), j["title"], j["video_id"])
                n += 1
            except OSError as e:
                log(f"nfo 생성 실패: {j['title']} — {e}")
    if n:
        log(f"기존 영상 nfo {n}개 생성 (Jellyfin/Kodi 용)")


def avatar_of(info):
    thumbs = info.get("thumbnails") or []
    return next((t["url"] for t in thumbs if "avatar" in (t.get("id") or "")), thumbs[-1]["url"] if thumbs else None)


def run_ffmpeg(cmd, duration, jid):
    """진행률을 LIVE 에 표시하며 실행. 성공이면 None, 실패면 오류 메시지."""
    # 오류 출력은 파일로: 파이프로 받으면 깨진 녹화본처럼 오류가 많을 때 파이프가 꽉 차 ffmpeg 와 서로 기다리며 영원히 멈췄음
    with tempfile.TemporaryFile() as ef:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ef, text=True)
        for line in p.stdout:
            if jid in CANCEL:
                p.kill()
            if line.startswith("out_time_us=") and duration:
                v = line.split("=", 1)[1].strip()
                if v.isdigit():
                    LIVE[jid] = {"status": "compressing", "progress": min(int(v) / 1e6 / duration * 100, 100)}
        if p.wait() == 0:
            return None
        ef.seek(0)
        return ef.read().decode(errors="replace")[-3000:]


def compress(src, duration, s, jid, force=False, tags=None, live=False):
    """→ (결과 경로, 사용한 인코딩 장치). live = 생방송 녹화본 (중간에 해상도가 바뀔 수 있어 첫 화면 크기로 고정)"""
    base = os.path.splitext(src)[0]
    tmp, dst = base + ".compressing.mp4", base + ".mp4"
    LIVE[jid] = {"status": "compressing", "progress": 0}
    # 전체 평균 비트레이트에서 오디오 몫을 빼서 원본 영상 비트레이트 추정
    vbit = max(os.path.getsize(src) * 8 / duration - yt_dlp.utils.parse_bytes(s["audio_bitrate"]), 0) if duration else 0
    hw = "cpu" if s["codec"] == "copy" else encoder_for(s)
    # 첫 화면 크기로 고정 (녹화 중간에 해상도가 바뀐 생방송 녹화본도 압축이 멈추지 않게). 일반 영상은 그대로 (10비트 등 유지)
    size = None if s["codec"] == "copy" or not live else next(((w, h) for t, _, w, h in probe_streams(src)[0] if t == "video"), None)
    err = run_ffmpeg(ffmpeg_cmd(src, tmp, s, vbit, tags, hw, size), duration, jid)
    if err is not None and hw != "cpu" and jid not in CANCEL:  # 드라이버 문제 등 → CPU 로 한 번 더
        log(f"{HW_NAME[hw]} 인코딩 실패 → CPU 로 다시 시도: {err.strip()[-120:]}")
        hw = "cpu"
        err = run_ffmpeg(ffmpeg_cmd(src, tmp, s, vbit, tags, hw, size), duration, jid)
    if err is not None:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError("ffmpeg 압축 실패 (원본 유지): " + err[-300:])
    if not force and os.path.getsize(tmp) >= os.path.getsize(src):  # 압축이 오히려 커지면 원본 유지
        os.remove(tmp)
        return src, hw
    os.replace(tmp, dst)
    if src != dst:
        os.remove(src)
    return dst, hw


def run_job(job, s, dl=None):
    jid = job["id"]
    CANCEL.discard(jid)  # 예전 취소 요청이 남아 있으면 다시 받기가 바로 취소됐음
    st = "recording" if job["live"] else "downloading"
    LIVE[jid] = {"status": st, "progress": 0}
    finished = []

    def hook(d):
        if jid in CANCEL or finished:  # 작업 끝난 뒤 남은 다운로드 스레드도 확실히 중단
            raise yt_dlp.utils.DownloadCancelled("사용자가 취소함")
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            LIVE[jid] = {"status": st, "speed": d.get("speed"), "eta": d.get("eta"), "bytes": d.get("downloaded_bytes"),
                         "total": total or None,  # 유튜브는 영상·소리를 따로 받아 지금 받는 파일 기준
                         "progress": d.get("downloaded_bytes", 0) / total * 100 if total else 0}

    def fetch(stream_hw, fmt, cookies):
        """stream_hw = None: 원본을 다 받은 뒤 압축 / 'cpu'·'nvenc'·'vaapi': ffmpeg 가 서버에서 읽으면서 바로 압축
        (원본·영상/소리 따로 받은 파일·합친 파일 없이 압축본만 디스크에 씀 → 용량·저장장치 수명 절약)
        fmt = 받을 포맷 고르는 규칙, cookies = 로그인 쿠키 쓸지 (화질이 막혔을 때 다시 시도용)"""
        nonlocal st
        stop = []  # 이번 시도의 진행률 표시 스레드 종료 신호
        h = int(s["max_height"] or 0)
        cz = platform_of(job["url"]) == "chzzk"
        o = base_opts(s, job["url"]) | {
            "format": fmt,
            "format_sort": [f"res:{h}"] if h else [],  # res = 짧은 변 기준 → 세로 숏츠도 1080 유지
            "merge_output_format": "mp4",  # Plex 는 mp4 안의 제목/설명만 읽음 (mkv 는 "Episode 날짜"로 나옴)
            # 라이브는 발견한 시점부터 녹화. live_from_start 는 24시간 방송이면 수주치를 받으려 해서 사용 안 함
            "paths": {"home": safe_dir(s["folder"])},
            "outtmpl": outtmpl("EP", False, cz),  # 시즌(치지직은 스트리머) 폴더 경로 계산용, 아래에서 최종 이름으로 바꿈
            "writethumbnail": True,
            "postprocessors": [
                {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
                # Plex 는 date 태그를 YYYY-MM-DD 형식일 때만 방송 날짜로 읽음 (yt-dlp 기본은 YYYYMMDD)
                {"key": "MetadataParser", "when": "pre_process",
                 "actions": [(MetadataParserPP.Actions.INTERPRET, "%(upload_date>%Y-%m-%d)s", "%(meta_date)s")]},
            ],
            "progress_hooks": [hook],
        }
        if not cookies:
            o.pop("cookiefile", None)
        with yt_dlp.YoutubeDL(o) as y:
            raw = y.extract_info(job["url"], download=False, process=False)
            raw["id"] = job["video_id"]  # 치지직 생방송은 id 가 채널 ID 라 방송마다 같음 → 작업 ID 로 고정 (유튜브는 원래 같음)
            if not raw.get("upload_date"):  # 치지직은 업로드일이 없음 → yt-dlp 가 처리 후 채우는 방식과 똑같이 timestamp 의 UTC 날짜
                ts = raw.get("timestamp")    # (치지직 시각은 한국시간이 UTC 로 해석돼 있어 UTC 날짜 = 실제 한국 날짜)
                raw["upload_date"] = (datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.now()).strftime("%Y%m%d")
            is_live = raw.get("is_live") or raw.get("live_status") == "is_live"
            stream_hw = None if is_live and not job["live"] else stream_hw  # 생방송 녹화하면서 압축 여부는 run_job 의 tries 가 정함
            if cz and not stream_hw:  # 치지직 생방송 조각(.m4v)은 실제 형식(fMP4)과 확장자가 달라 ffmpeg 가 거부함
                # 다시보기: 네이버 CDN 이 연결 하나당 속도를 제한(실측 1~2.5MB/s) → mp4 는 aria2c 로, 조각(HLS)은 동시에 여러 갈래로
                y.params.update(external_downloader={"http": "aria2c"}, concurrent_fragment_downloads=CHZZK_CONNS,
                                external_downloader_args={"ffmpeg_i": ["-extension_picky", "0"],
                                                          "aria2c": [f"-x{CHZZK_CONNS}", f"-s{CHZZK_CONNS}", "-k1M",
                                                                     "--file-allocation=none",
                                                                     "--auto-save-interval=1"]})  # 진행 기록(.aria2) 1초마다 → 화면 속도 표시용
            # 파일·폴더 이름용 제목/채널명 (이모지 제거). 실제 제목(메타데이터·nfo·화면)은 이모지 그대로.
            # 생방송은 yt-dlp 처럼 녹화 시작 시각을 붙여 방송마다 이름이 겹치지 않게
            raw["fname_title"] = plain_name(raw.get("title")) + (datetime.now().strftime(" %Y-%m-%d %H_%M") if is_live else "")
            raw["fname_channel"] = plain_name(raw.get("channel") or raw.get("uploader"))
            base_vid, part = part_of(job["video_id"])
            if is_live and cz and part > 1:  # 이어서 녹화한 파일은 1번째 파일과 같은 폴더 · 같은 이름 (방송 중 제목이 바뀌어도)
                first = (q("SELECT filepath FROM jobs WHERE video_id=?", (base_vid,)) or [{}])[0].get("filepath") or next(
                    (f for f in glob.glob(os.path.join(glob.escape(safe_dir(s["folder"])), "**", f"*{glob.escape(f'[{base_vid}]')}*"), recursive=True)
                     if os.path.isfile(f)), None)  # 1번째 조각이 아직 압축 중이면 경로가 비어 있음 → 녹화 파일로
                if m := re.match(r"(\d{4})-(\d\d)-(\d\d) - (.+) \[", os.path.basename(first or "")):
                    raw["upload_date"], raw["fname_title"] = "".join(m.groups()[:3]), m.group(4)
            season_dir = os.path.dirname(y.prepare_filename(raw))  # 치지직은 스트리머 폴더
            ep = "" if cz else episode_code(season_dir, raw["upload_date"], job["video_id"])
            y.params["outtmpl"]["default"] = outtmpl(ep, s["video_folder"] == "1", cz)
            langs = [] if is_live else subtitle_langs(raw, s["subtitles"])
            if langs:  # 형식(vtt 등) 상관없이 받아서 Plex/Jellyfin 이 읽는 srt 로 변환 → "영상이름.ko.srt"
                y.params.update(writesubtitles=True, writeautomaticsub=True, subtitleslangs=langs,
                                subtitlesformat="srt/vtt/ass/best",
                                sleep_interval_subtitles=int(float(s["sleep_requests"])) + 1)  # 자막 요청 사이 대기
                y.add_post_processor(FFmpegSubtitlesConvertorPP(y, format="srt"), when="before_dl")
            if is_live:
                st = "recording"
                q("UPDATE jobs SET started=? WHERE id=?", (time.time(), jid))  # 실제 녹화 시작 (끊김 기록의 '빠진 시간' 계산용)
                log(f"라이브 녹화 시작: {job['title']}")
            else:  # 녹화본(MPEG-TS, 마지막 프레임 잘림)은 메타데이터 단계에서 실패하므로 일반 영상만
                if s["sponsorblock"] == "1" and not cz:  # 광고·협찬 구간을 챕터로 표시만 (remove 없음 → 영상은 그대로)
                    y.add_post_processor(SponsorBlockPP(y), when="after_filter")
                    y.add_post_processor(ModifyChaptersPP(y), when="post_process")
                # 챕터: 유튜브 설명란의 타임스탬프 → 플레이어(Plex·VLC 등)에서 구간 이동
                y.add_post_processor(FFmpegMetadataPP(y, add_metadata=True, add_chapters=True), when="post_process")
            if stream_hw:
                # 고를 포맷만 먼저 확인(다운로드 안 함) → 원본 비트레이트로 '원본 대비 최대 크기' 상한 계산
                sel = y.process_ie_result(copy.deepcopy(raw), download=False)
                vbit = (sel.get("vbr") or max((sel.get("tbr") or 0) - (sel.get("abr") or 0), 0)) * 1000
                pre, enc = encode_args(s, vbit, stream_hw, ts=is_live, size=(sel.get("width"), sel.get("height")) if is_live else None)
                prog = f"/tmp/progress-{jid}.txt"  # ffmpeg 가 진행 상황을 쓰는 파일 (yt-dlp 는 ffmpeg 진행률을 안 알려줌)
                y.params.update(external_downloader={"default": "ffmpeg"},  # 영상·소리를 ffmpeg 하나가 같이 읽어 바로 압축
                                # -extension_picky 는 HLS 전용 옵션 (일반 mp4 주소에 주면 ffmpeg 가 거부)
                                external_downloader_args={"ffmpeg_i": pre + (["-extension_picky", "0"] if cz and "m3u8" in (sel.get("protocol") or "") else []),
                                                          # 조각 mp4 로 써야 받는 중에도 열림 (미리보기). 끝나면 메타데이터 단계가 일반 mp4 로 다시 씀
                                                          "ffmpeg_o": [*enc, *([] if is_live else ["-movflags", "+frag_keyframe+empty_moov"]),
                                                                       "-progress", prog, "-nostats"]})
                threading.Thread(target=watch_stream, args=(jid, prog, sel.get("duration"), stop, is_live), daemon=True).start()
            elif is_live or cz:
                name = os.path.basename(y.prepare_filename(raw)).split(f" [{raw['id']}]")[0]
                threading.Thread(target=watch_size, args=(jid, season_dir, name, stop, is_live), daemon=True).start()
            try:
                return raw, y.process_ie_result(raw, download=True), is_live, cz, stream_hw
            finally:
                stop.append(True)

    orig = info = meta = None
    try:
        # 받으면서 압축: 설정한 장치 → (실패하면) CPU → (그래도 실패하면) 예전처럼 다 받은 뒤 압축
        hw0 = encoder_for(s)
        if job["live"]:  # 녹화하면서 압축: 그래픽카드가 있을 때만 (CPU 만으론 실시간을 못 따라가면 녹화가 끊김) → 안 되면 CPU / 녹화 후 압축
            lc = s["live_compress"]
            tries = ([hw0] + (["cpu"] if lc == "gpu_cpu" else [])) if s["codec"] != "none" and lc != "off" and hw0 != "cpu" else []
        else:
            tries = ([hw0] + (["cpu"] if hw0 != "cpu" else [])) if s["codec"] != "none" and s["stream_compress"] == "1" else []
        def attempt(fmt, cookies):
            for t in tries + [None]:
                try:
                    return fetch(t, fmt, cookies)
                except Exception as e:  # ffmpeg 자체 실패만 다음 방법으로 (차단·멤버십 등은 방법을 바꿔도 같으니 그대로 오류)
                    # 생방송이 한참 녹화되다 실패했으면(그래픽카드 오류 등) 다른 방법으로 처음부터 하지 않고 녹화분 보존 → 이어서 녹화
                    if t is None or jid in CANCEL or "ffmpeg exited with code" not in str(e) or (job["live"] and keep_partial(job["video_id"], s, dry=True)):
                        raise
                    log(f"받으면서 압축 실패({HW_NAME[t]}) → {'CPU 로' if t != 'cpu' else '다 받은 뒤 압축으로'} 다시: {str(e)[-120:]}")
                    cleanup_partial(job["video_id"], s)

        # "Requested format is not available": 최대한 원본 화질로
        # ① 같은 최고 화질을 로그인 없이 (로그인 쿠키를 보내면 유튜브가 일부 포맷을 숨기는 경우가 있음)
        # ② 받을 수 있는 것 중 최고 영상+소리 (예전엔 여기서 'b' = 영상·소리 합쳐진 360p 를 먼저 골라 화질이 떨어졌음) → ③ 로그인 없이 ②
        fmt_best, fmt_any = "bv*+ba/b", "bv*+ba/bv*+ba*/bv*/b*/ba*"
        ck = bool(cookie_file(job["url"]))
        steps = [(fmt_best, True)] + ([(fmt_best, False)] if ck else []) + [(fmt_any, True)] + ([(fmt_any, False)] if ck else [])
        for i, (fmt, ck_) in enumerate(steps):
            try:
                raw, info, is_live, cz, streamed = attempt(fmt, ck_)
                break
            except yt_dlp.utils.DownloadError as e:
                # 화질 오류면 다음 단계로. 그 밖의 오류라도 로그인한 채로 실패했으면 같은 화질을 로그인 없이 한 번 더
                # (쿠키를 보내면 403·'볼 수 없음' 등으로 실패하고 로그인 없이는 받아지는 영상이 있음)
                fmt_err = "Requested format is not available" in str(e)
                if jid in CANCEL or i == len(steps) - 1 or not (fmt_err or (ck_ and ck)):  # ck: 쿠키 파일이 실제로 있을 때만
                    raise
                nxt = steps[i + 1]
                log(f"{'요청한 화질을 못 받음' if fmt_err else '로그인한 채로 실패'} → {'받을 수 있는 최고 화질로' if nxt[0] == fmt_any else '같은 화질을'}"
                    f"{' 로그인 없이' if not nxt[1] else ''} 다시: {job['title']} — {str(e)[:80]}")
        orig = path = info["requested_downloads"][0]["filepath"]
        meta = {k: info.get(k) for k in ("channel", "uploader", "upload_date", "duration", "view_count", "like_count",
                                         "description", "resolution", "fps", "vcodec", "acodec", "webpage_url")}
        # 생방송은 길이 정보가 없어 녹화 파일에서 읽음 → 압축 진행률(%)이 보임 (없으면 끝날 때까지 0% 로 멈춰 보임)
        dur = info.get("duration") or (probe_duration(orig) if is_live else 0)
        # 받으면서(녹화하면서) 압축했으면 원본 파일이 없음 → 서버가 알려준 크기, 없으면(생방송) 방송 비트레이트 × 길이로 추정
        # (예전엔 압축본 크기를 원본 크기로 적어 "원본 = 압축본"으로 보였음)
        if streamed:
            meta["orig_size"] = sum(f.get("filesize") or f.get("filesize_approx") or 0 for f in info.get("requested_formats") or [info]) \
                or int((info.get("tbr") or 0) * 125 * dur)  # tbr: kbps → 바이트/초 = ×125
            meta["orig_est"] = True
        meta["orig_size"] = meta.get("orig_size") or os.path.getsize(orig)
        meta["quality"] = s["quality"]
        ud = meta["upload_date"] or raw["upload_date"]
        tags = {"title": info.get("title"), "artist": meta["channel"], "date": f"{ud[:4]}-{ud[4:6]}-{ud[6:]}",
                "synopsis": meta["description"], "description": meta["description"]} if is_live else None
        # yt-dlp 가 "이미 받은 파일"로 건너뛴 경우 = 이미 압축까지 끝난 파일 → 다시 압축하면 화질만 떨어짐
        fresh = info["requested_downloads"][0].get("__real_download", True)
        # 이미 받은 파일이라 건너뛴 경우(fresh=False): 예전엔 '이미 압축 끝남'으로 봤는데, 압축을 기다리다 재시작 · 업데이트로 끊긴
        # 원본일 수 있음 → 파일 코덱이 목표와 다르면 압축 (같으면 이미 압축본이라 다시 압축하면 화질만 떨어짐)
        need = s["codec"] != "none" and (fresh or is_live or not same_codec(orig, s["codec"]))
        if not streamed and need:
            if job["live"]:  # 재시작으로 끊겨도 녹화본을 찾을 수 있게 (lifespan)
                q("UPDATE jobs SET filepath=? WHERE id=?", (orig, jid))
            compress_turn(jid, platform_of(job["url"]), dl)  # 다운로드 칸 비우고 압축 칸 기다림
        encoded = bool(streamed)  # 실제로 압축했는지 (mp4 로 정리만 한 건 압축 아님)
        if streamed and is_live:  # 녹화하면서 압축한 파일(MPEG-TS) → 재생 잘 되는 mp4 로 (영상은 복사라 빠름, 제목·날짜 태그)
            path, _ = compress(orig, dur, s | {"codec": "copy", "src_codec": s["codec"]}, jid, force=True, tags=tags)
            hw = streamed
        elif streamed:
            hw = streamed  # 이미 압축됨
        elif need:
            # 호환성 프리셋은 목적이 H.264 변환이므로 용량이 커져도 결과 유지
            try:
                path, hw = compress(orig, dur, s, jid, force=s["quality"] == "compat", tags=tags, live=is_live)
            except RuntimeError as e:  # 압축만 실패 → 받은 원본으로 완료 (예전엔 '오류' → 점검이 다시 받고 또 실패하기를 반복)
                if jid in CANCEL:
                    raise
                log(f"압축 실패 → 원본 그대로 저장 (나중에 압축 가능): {info.get('title')} — {str(e)[-120:]}")
                meta["compress_error"] = str(e)[-300:]
                path, hw = orig, "cpu"
            encoded = path != orig
            if is_live and path == orig:  # 압축본이 오히려 크면(이미 효율 좋은 방송) 화질 그대로 mp4 로만 정리 → 원본보다 커지지 않음
                log(f"압축해도 작아지지 않아 원본 화질 유지: {info.get('title')}")
                path, hw = compress(orig, dur, s | {"codec": "copy"}, jid, force=True, tags=tags)
        elif is_live:  # 원본 화질 유지하면서 재생 가능한 mp4 로 변환
            path, hw = compress(orig, dur, s | {"codec": "copy"}, jid, force=True, tags=tags)
        meta["size"] = os.path.getsize(path)
        base = os.path.splitext(path)[0]
        for f in glob.glob(glob.escape(base) + ".*-orig.srt"):  # "영상.en-orig.srt" 는 Plex/Jellyfin 이 언어를 못 읽음
            if not os.path.exists(f.replace("-orig.srt", ".srt")):
                os.replace(f, f.replace("-orig.srt", ".srt"))
        meta["subtitles"] = sorted(f[len(base) + 1:-4] for f in glob.glob(glob.escape(base) + ".*.srt"))
        if is_live:
            frame_thumb(path, dur)
        for what, step in () if cz else (("포스터", lambda: ensure_poster(path, info, job["sub_id"])),
                                         ("nfo", lambda: write_nfo(path, meta, info.get("title"), job["video_id"]))):
            try:  # 부가 기능 - 실패해도 다운로드는 성공 (포스터가 실패해도 nfo 는 만듦)
                step()
            except Exception as e:
                log(f"{what} 저장 실패: {str(e)[:80]}")
        if encoded:
            meta["compressed"] = {"codec": s["codec"], "crf": s["crf"], "preset": s["preset"], "encoder": HW_NAME[hw]}
        for f in keep_files(job["filepath"]):  # 다시 받기 성공 → 비켜 둔 예전 파일 정리
            os.remove(f)
        q("UPDATE jobs SET status='done', progress=100, filepath=?, title=?, meta=?, finished=? WHERE id=?",
          (path, info.get("title"), json.dumps(meta, ensure_ascii=False), time.time(), jid))
        log(f"완료: {info.get('title')}")
    except Exception as e:
        msg = str(e)
        # 다시 받기가 실패·취소됨(원본 삭제·비공개 등) → 비켜 둔 기존 파일로 되돌리고 '완료' 유지 (봇 차단은 나중에 다시 시도하므로 그대로)
        old = keep_files(job["filepath"]) and (jid in CANCEL or not BOT_RE.search(msg))
        if old:
            cleanup_partial(job["video_id"], s)
            old = restore_keep(job["filepath"])
        if old:
            q("UPDATE jobs SET status='done', progress=100, filepath=?, error=?, finished=? WHERE id=?",
              (old, None if jid in CANCEL else f"다시 받기 실패 → 기존 파일 그대로 보존: {msg}"[:500], time.time(), jid))
            log(f"다시 받기 {'취소' if jid in CANCEL else '실패'} → 기존 파일 그대로 보존: {job['title']}")
        elif jid in CANCEL and jid in COMPRESSING and orig and os.path.isfile(orig):
            # 다 받고 압축하던 중 취소 → 압축만 멈추고 받은 원본으로 완료 (받기는 끝났으니 버리지 않음)
            for f in keep_files(job["filepath"]):
                os.remove(f)
            q("UPDATE jobs SET status='done', progress=100, filepath=?, title=?, meta=?, error=NULL, finished=? WHERE id=?",
              (orig, info.get("title"), json.dumps(meta | {"size": os.path.getsize(orig)}, ensure_ascii=False), time.time(), jid))
            log(f"압축 취소 → 받은 원본 그대로 저장: {job['title']}")
        elif jid in CANCEL:
            q("UPDATE jobs SET status='cancelled', error=NULL WHERE id=?", (jid,))
            cleanup_partial(job["video_id"], s)
            log(f"취소: {job['title']}")
        elif BOT_RE.search(msg):
            q("UPDATE jobs SET status='queued', progress=0 WHERE id=?", (jid,))  # 쉬었다가 다시 시도
            cooldown(msg)
        elif UPCOMING_RE.search(msg):
            q("DELETE FROM jobs WHERE id=?", (jid,))  # 아직 시작 안 한 라이브 → 다음 확인 때 다시 등록
            log(f"예정된 라이브, 시작 후 다시 확인: {job['title']}")
        elif (job["live"] and NOT_LIVE_RE.search(msg) and (job["retries"] or 0) < 6
              and not keep_partial(job["video_id"], s, dry=True) and live_now(job)):
            # 방송 시작 직후 치지직 API 가 잠깐 '종료'로 알려 줘 녹화가 바로 실패함 (예전엔 오류 카드 + 새 파일로 이어서 녹화 = 한 번 튐)
            # → 아직 녹화한 게 없고 방송이 켜져 있으면 같은 작업을 10초 뒤 다시 (최대 6번 = 1분)
            RETRY_LIVE.add(jid)
            q("UPDATE jobs SET status='queued', progress=0, error=NULL, retries=COALESCE(retries,0)+1 WHERE id=?", (jid,))
            log(f"방송 시작 직후라 아직 준비 안 됨 → 10초 뒤 다시 녹화: {job['title']}")
            time.sleep(10)
        elif "chzzk.naver.com" in job["url"] and ADULT_RE.search(msg):
            # 성인 인증이 필요한 영상은 다시 시도해도 같은 실패 → 자동 재시도 안 함 (retries 를 한도로), 로그인 후 '다시 받기'
            q("UPDATE jobs SET status='error', error=?, retries=?, finished=? WHERE id=?", (ADULT_MSG, MAX_RETRIES, time.time(), jid))
            log(f"오류: {job['title']} — {ADULT_MSG}")
        else:
            # 생방송이 끊기면 그때까지 녹화분은 지우지 않고 보존 (몇 시간 녹화를 날리지 않게). 이어서 녹화는 continue_live
            # 보존했으면 '완료'로 (오류로 두면 점검이 다시 받기로 같은 방송을 처음부터 또 녹화함). 끊긴 표시는 cut 으로
            kept = keep_partial(job["video_id"], s) if job["live"] else None
            ended = kept and not live_now(job)
            if ended:  # 방송이 끝나서 끊긴 것 = 정상 종료 (치지직은 방송이 끝나면 재생 목록이 바로 사라져 ffmpeg 가 오류로 끝남)
                kept = finish_kept(job, kept, s, dl)
            elif kept:
                frame_thumb(kept)
            # 보존한 녹화의 오류 문구는 영상 정보 창에만 (확인한 오류로 → 카드·상태 화면에 빨간 오류로 안 뜸). 방송이 이어지면 새 파일로 이어서 녹화
            q("UPDATE jobs SET status=?, error=?, err_seen=?, filepath=COALESCE(?, filepath), finished=? WHERE id=?",
              ("done" if kept else "error", None if ended else msg[:500], int(bool(kept)), kept, time.time(), jid))
            log(f"방송 종료 → 녹화 저장: {job['title']}" if ended else
                f"녹화 끊김 (녹화분 보존): {job['title']} — {msg[:100]}" if kept else f"오류: {job['title']} — {msg[:100]}")
    finally:
        finished.append(True)
        compress_done(jid)
        LIVE.pop(jid, None)
        CANCEL.discard(jid)


def watch_size(jid, d, name, stop, live=True):
    """라이브(ffmpeg)·치지직 다시보기(aria2c)는 yt-dlp 진행률 콜백이 없음 → 받는 중인 파일을 3초마다 보고 표시
    파일 이름은 'name + 녹화 시작 시각' 이라 앞부분으로 찾음 (영상별 폴더 안까지).
    aria2c 는 파일을 전체 크기로 먼저 만들어서 파일 크기·디스크 사용량으로는 못 봄 (NAS·exFAT 은 시작하자마자 '다 받음'으로 보임)
    → aria2c 가 기록하는 완료 조각 목록(.aria2)으로 계산"""
    pat = os.path.join(glob.escape(d), "**", glob.escape(name) + "*.part")
    status = "recording" if live else "downloading"
    prev, st = None, {}  # prev: 이어받기면 처음부터 받은 양이 커서, 첫 측정은 속도 계산에서 뺌
    while not stop:
        try:
            parts = glob.glob(pat, recursive=True)  # 같은 제목의 예전 녹화 조각이 남아 있을 수 있어 가장 최근 파일만
            f = max(parts, key=os.path.getmtime) if parts else None
            if live:
                got, total = (os.path.getsize(f) if f else 0), None
            elif f and os.path.exists(f + ".aria2"):
                got, total = aria2_done(f + ".aria2")
            else:  # aria2c 가 아니면(HLS 등) yt-dlp 가 진행률을 알려줌
                time.sleep(3)
                continue
            speed = max(got - prev, 0) / 3 if prev is not None else None
            if stop:  # 녹화가 끝나 압축이 시작됐으면 '녹화 중'으로 덮어쓰지 않음 (예전엔 완료까지 '녹화 중'으로 멈춰 보였음)
                break
            LIVE[jid] = {"status": status, "bytes": got, "speed": speed, "total": total,
                         "eta": int((total - got) / speed) if total and speed else None,
                         "progress": got / total * 100 if total else 0}
            prev = got
            if live:
                stall_check(jid, got, st)
        except OSError:
            pass
        time.sleep(3)


def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, timeout=120)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0


def stall_check(jid, size, st):
    """생방송 녹화가 멈췄는지(파일이 STALL_SEC 동안 안 커짐) 보고, 멈췄으면 ffmpeg 를 끝내 지금까지 녹화분을 저장하고
    새 파일로 이어서 녹화되게 (continue_live). 예: 녹화 중인 파일을 복사 · 이동하면(OS · Docker 폴더 연결 방식에 따라) ffmpeg 가 멈춤.
    먼저 'q'(정상 종료), 그래도 30초 안에 안 끝나면(쓰기에서 멈춰 'q' 를 못 읽음) 강제 종료"""
    now = time.time()
    if size > st.get("size", -1):
        st.update(size=size, t=now, acted=0)
        return
    idle, acted = now - st["t"], st.get("acted", 0)
    if idle < STALL_SEC or acted >= 2 or (acted == 1 and idle < STALL_SEC + 30):
        return
    j = q("SELECT video_id, title FROM jobs WHERE id=?", (jid,))
    if not j:
        return
    if not acted:
        log(f"녹화가 {STALL_SEC}초째 멈춤 → 지금까지 녹화분 저장하고 새 파일로 이어서 녹화: {j[0]['title']}")
        stop_recording(j[0]["video_id"])
    else:
        for pid, _ in procs(b"ffmpeg", j[0]["video_id"]):
            os.kill(pid, 9)
        log(f"녹화가 멈춘 채 응답이 없어 강제로 끝냄 → 새 파일로 이어서 녹화: {j[0]['title']}")
    st["acted"] = acted + 1


def watch_stream(jid, prog, duration, stop, live=False):
    """받으면서(녹화하면서) 압축: ffmpeg -progress 파일(key=value 가 계속 덧붙음)의 마지막 값으로 진행률·남은 시간 표시.
    bytes/speed 는 디스크에 쓴 압축본 기준 (받는 원본 양이 아님). 생방송은 끝을 몰라 녹화한 양·속도만"""
    t0, st = time.time(), {}
    while not stop:
        try:
            with open(prog, "rb") as f:
                f.seek(max(0, os.path.getsize(prog) - 2048))
                kv = dict(line.split("=", 1) for line in f.read().decode(errors="replace").split("\n") if "=" in line)
            done = int(kv["out_time_us"]) / 1e6 if kv.get("out_time_us", "").isdigit() else 0
            size, el = int(kv["total_size"]) if kv.get("total_size", "").isdigit() else 0, time.time() - t0
            if stop:
                break
            LIVE[jid] = {"status": "recording" if live else "downloading", "streaming": True, "bytes": size, "speed": size / el if el else None,
                         "progress": min(done / duration * 100, 100) if duration else 0,
                         "eta": int((duration - done) * el / done) if duration and done > 0 else None}
            if live:
                stall_check(jid, size, st)
        except OSError:
            pass
        time.sleep(3)
    try:
        os.remove(prog)
    except OSError:
        pass


def aria2_bits(path):
    """aria2c 제어 파일 → (조각 크기, 전체 바이트, 조각마다 받았는지 목록). 형식(aria2 문서 'Control File Format' v1, 빅엔디언):
    버전2 · 확장4 · 해시길이4 · 해시 · 조각크기4 · 전체8 · 업로드8 · 비트맵길이4 · 완료 조각 비트맵(앞 조각이 높은 비트)"""
    with open(path, "rb") as fh:
        b = fh.read()
    i = 10 + int.from_bytes(b[6:10], "big")
    piece, total = int.from_bytes(b[i:i + 4], "big"), int.from_bytes(b[i + 4:i + 12], "big")
    n = int.from_bytes(b[i + 20:i + 24], "big")
    bits = [x >> (7 - k) & 1 for x in b[i + 24:i + 24 + n] for k in range(8)]
    return piece, total, bits[:-(-total // piece)] if piece else []


def aria2_done(path):
    """→ (받은 바이트, 전체 바이트). ponytail: 받는 중인 조각은 안 셈 → 실제보다 조각 몇 개(수 MB)만큼 적게 보임"""
    piece, total, bits = aria2_bits(path)
    return min(sum(bits) * piece, total), total


def aria2_seek(path, duration, sec=12):
    """aria2c 는 파일 여러 곳을 동시에 받아 '파일 끝'은 아직 빈칸 → 받아 둔 구간 중 가장 뒤쪽에서 sec 초를 담을 만큼 이어진 곳의
    시작 시각(초). 못 찾으면 None. 시각은 바이트 위치 비율로 어림 (비트레이트가 일정하다고 봄)"""
    piece, total, bits = aria2_bits(path)
    need = sec * total / duration / piece if duration and piece else 0
    end = len(bits)
    while end > 0:
        while end > 0 and not bits[end - 1]:
            end -= 1
        start = end
        while start > 0 and bits[start - 1]:
            start -= 1
        if end > start and end - start >= need:
            return max(start * piece / total * duration, end * piece / total * duration - sec - 3)
        end = start
    return None


def stop_recording(vid):
    """녹화 중인 ffmpeg 에 'q' 를 보내 정상 종료 → yt-dlp 가 녹화분을 저장·후처리함"""
    for pid, cmd in procs(b"ffmpeg", vid):
        if b"pipe:1" not in cmd:  # -progress pipe:1 은 녹화 끝난 뒤 압축하는 ffmpeg (녹화하면서 압축은 -progress 파일)
            try:
                with open(f"/proc/{pid}/fd/0", "wb") as f:
                    f.write(b"q")
                return True
            except OSError:
                pass
    return False


def procs(exe, vid):
    """'[영상ID]' 파일을 다루는 실행 중인 exe 프로세스들 (pid, 명령줄)"""
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().split(b"\0")
        except OSError:
            continue
        if exe in cmd[0] and any(f"[{vid}]".encode() in a for a in cmd):
            yield int(pid), cmd


def sweep_temp():
    """강제 종료/정전으로 /downloads 에 남은 압축 임시파일(.compressing.*)을 지운다.

    compress() 는 base+'.compressing.mp4' 에 쓰다가 완성되면 rename 하는데,
    도중에 죽으면 그 파일이 그대로 남는다. cleanup_partial 은 video_id 가 있는
    작업만 다루므로, 시작할 때 폴더 전체를 한 번 훑는다.
    """
    s, roots = settings(), {OUT}  # 다운로드 폴더 + 절대 경로로 정한 저장 위치(/volume1/… 등)도
    for f in {s["folder"], s["youtube_folder"], s["chzzk_folder"]} | {r["folder"] or "" for r in q("SELECT folder FROM subs")}:
        try:
            roots.add(safe_dir(f))
        except ValueError:
            pass
    n = 0
    for f in {f for root in roots for pat in ("*.compressing.*", "*.merging.*")
                          for f in glob.glob(os.path.join(glob.escape(root), "**", pat), recursive=True)}:  # 압축·조각 합치기 임시 파일
        try:
            os.remove(f)
            n += 1
        except OSError as e:
            log(f"임시파일 삭제 실패 {f}: {e}")
    if n:
        log(f"압축 임시파일 {n}개 정리")
    for f in glob.glob("/tmp/cookies-*.txt") + glob.glob("/tmp/progress-*.txt"):  # 지난번 실행의 쿠키 복사본(계정 정보)·진행 기록
        os.remove(f)


def cleanup_partial(vid, s):
    """취소된 다운로드/녹화의 조각 파일(.part/.ytdl) 정리. 완성된 영상이 없으면 딸린 파일(썸네일·자막·nfo)도 삭제."""
    files = [f for f in glob.glob(os.path.join(glob.escape(safe_dir(s["folder"])), "**", f"*{glob.escape(f'[{vid}]')}*"),
                                  recursive=True) if os.path.isfile(f) and not f.endswith(".keep")]  # 영상별 폴더 이름에도 [ID] 가 있어 폴더는 제외, 다시 받기로 비켜 둔 파일 제외
    partial = [f for f in files if ".part" in f or ".compressing." in f or f.endswith(".ytdl")]
    if not any(f.endswith((".mkv", ".mp4", ".webm")) for f in files if f not in partial):
        partial = files
    for f in partial:
        os.remove(f)
    for d in {os.path.dirname(f) for f in partial}:  # 비게 된 영상별 폴더도 정리 (비어 있을 때만 지워짐)
        try:
            os.rmdir(d)
        except OSError:
            pass


def keep_partial(vid, s, dry=False):
    """끊긴 생방송 녹화 조각(…mp4.part)을 완성 파일 이름으로 바꿔 보존 → 그 경로 (MPEG-TS 내용이라 대부분 플레이어에서 재생됨).
    dry = 바꾸지 않고 보존할 만한 녹화분이 있는지만"""
    for f in glob.glob(os.path.join(glob.escape(safe_dir(s["folder"])), "**", f"*{glob.escape(f'[{vid}]')}*.part"), recursive=True):
        if os.path.getsize(f) > 1e6:  # 1MB 이하는 녹화된 게 거의 없음
            if dry:
                return f[:-5]
            for _ in range(5):  # 윈도우에서 탐색기가 파일을 복사 중이면 잠겨 이름을 못 바꿈 → 잠깐씩 기다렸다 다시
                try:
                    os.replace(f, f[:-5])
                    return f[:-5]
                except OSError:
                    time.sleep(3)
            log(f"녹화 파일 이름을 바꾸지 못해 .part 이름 그대로 보존: {os.path.basename(f)}")
            return f
    return None


COMPRESSING = {}  # 다 받고 압축 단계인 job → 플랫폼. 다운로드 개수에서 빠지고(다음 다운로드 시작) 압축 개수로 셈
COMP_RUN = set()  # 그중 실제로 압축 중인 job
COMP_LOCK = threading.Lock()


def compress_turn(jid, p, dl=None):
    """다운로드 칸을 비우고(dl 신호 → 작업 스레드가 다음 영상을 받기 시작) 이 플랫폼의 압축 칸이 날 때까지 기다림.
    예전엔 압축이 끝나야 다음 다운로드가 시작됐음 (다운로드 개수 = 압축 개수)"""
    with COMP_LOCK:
        COMPRESSING[jid] = p
    if dl:
        dl.set()
    LIVE[jid] = {"status": "compressing", "progress": 0, "waiting": True}
    while True:
        with COMP_LOCK:
            if sum(COMPRESSING.get(j) == p for j in COMP_RUN) < int(settings()[("chzzk_" if p == "chzzk" else "") + "compress_concurrency"]):
                COMP_RUN.add(jid)
                LIVE[jid] = {"status": "compressing", "progress": 0}
                return
        if jid in CANCEL:
            raise yt_dlp.utils.DownloadCancelled("사용자가 취소함")
        time.sleep(2)


def compress_done(jid):
    with COMP_LOCK:  # claim · compress_turn 이 도는 중에 바꾸면 'changed size during iteration' 오류
        COMP_RUN.discard(jid)
        COMPRESSING.pop(jid, None)


STOPPED = set()  # 사용자가 "녹화 중지"한 job → 이어서 녹화 안 함
MERGE_AFTER = set()  # 방송이 끝났는데 마지막 조각을 아직 압축 중 → 압축이 끝나면 자동 합치기
RETRY_LIVE = set()  # 방송 시작 직후라 같은 작업을 다시 녹화하기로 한 job → 이어서 녹화(새 파일) 안 함


def part_of(vid):
    """이어서 녹화한 파일 ID → (원래 방송 ID, 몇 번째 파일). 예) chzzk-live-123-p2 → (chzzk-live-123, 2)
    유튜브 영상 ID 는 정확히 11자라, ID 자체가 '…-p12' 로 끝나도 이어서 녹화 파일로 오해하지 않음"""
    m = re.fullmatch(r"(chzzk-live-\d+|[\w-]{11})-p(\d+)", vid)
    return (m.group(1), int(m.group(2))) if m else (vid, 1)


def live_now(job):
    """이 녹화 작업의 방송이 아직 켜져 있는지 (치지직: 같은 방송 ID, 유튜브: is_live)"""
    for i in range(3):  # 확인 자체가 잠깐 실패하면(네트워크 · API 오류) 다시 — 예전엔 바로 '방송 끝'으로 봐서 이어서 녹화를 안 했음
        try:
            if "chzzk.naver.com" in job["url"]:  # 채널이 방송 중이면 같은 방송으로 봄 (제목 등을 바꾸면 방송 ID 가 바뀔 수 있음)
                cid = re.search(r"/live/([0-9a-f]{32})", job["url"]).group(1)
                return bool(chzzk_live(cid))
            with yt_dlp.YoutubeDL(base_opts(settings(), job["url"])) as y:
                return y.extract_info(job["url"], download=False, process=False).get("live_status") == "is_live"
        except Exception as e:
            if i == 2:
                log(f"방송 상태 확인 실패 → 끝난 것으로 봄: {job['title']} — {str(e)[:100]}")
                return False
            time.sleep(5)


def continue_live(job):
    """녹화가 끝났는데(끊김·오류) 방송이 아직 이어지면 바로 이어서 녹화 → 새 파일 '…[ID-p2]'. 다음 녹화 스레드가 5초 안에 시작.
    사용자가 중지·취소했거나 방송이 끝났으면 안 함. ponytail: 같은 방송 최대 50번까지 (계속 실패하는 방송에서 무한 반복 방지)"""
    if job["id"] in STOPPED or (q("SELECT status FROM jobs WHERE id=?", (job["id"],)) or [{}])[0].get("status") == "cancelled":
        STOPPED.discard(job["id"])
        return
    if (q("SELECT error FROM jobs WHERE id=?", (job["id"],)) or [{}])[0].get("error") == ADULT_MSG:
        return  # 성인 인증 실패는 이어서 녹화해도 또 실패
    if job["id"] in RETRY_LIVE:  # 같은 작업을 다시 녹화하기로 함 (방송 시작 직후 재시도) → 새 파일로 이어 가지 않음
        RETRY_LIVE.discard(job["id"])
        return
    base, n = part_of(job["video_id"])
    if n >= 50:
        return
    if not live_now(job):
        if n > 1 and settings()["auto_merge"] == "1":  # 방송 끝 + 여러 조각 → 한 파일로 (이 조각을 압축 중이면 끝난 뒤에)
            if (q("SELECT status FROM jobs WHERE id=?", (job["id"],)) or [{}])[0].get("status") == "downloading":
                MERGE_AFTER.add(job["id"])
            else:
                auto_merge(job)
        return
    q("UPDATE jobs SET cut=? WHERE id=?", (time.time(), job["id"]))  # 방송 중에 녹화가 끝남 = 끊김 → 영상 정보에 표시
    if add_entries([{"id": f"{base}-p{n + 1}", "url": job["url"], "title": job["title"], "live_status": "is_live",
                     "thumbnail": job["thumb"], "open_date": job.get("live_open")}], "streams", job["sub_id"], json.loads(job["opts"] or "{}"),
                   filt=False):  # 이어 녹화는 필터 없이 (방송 중 제목이 제외 단어로 바뀌어도 나머지 방송까지)
        log(f"녹화 끊김 → 이어서 녹화 ({n + 1}번째 파일): {job['title']}")


def same_codec(path, codec):
    """파일의 영상 코덱이 설정 코덱(h264 · h265 · av1)과 같은지"""
    vc = next((c for t, c, *_ in probe_streams(path)[0] if t == "video"), None)
    return vc == {"h264": "h264", "h265": "hevc", "av1": "av1"}.get(codec)


def finish_kept(job, path, s, dl=None):
    """방송이 끝나 오류로 멈춘 녹화(보존한 MPEG-TS) → 정상 종료와 같게 정리: 설정대로 압축(녹화하면서 이미 압축했으면 mp4 로만)
    · 썸네일 · 크기/길이 기록. 실패하면 보존한 파일 그대로 → 그 경로"""
    if path.endswith(".part"):  # 이름을 못 바꾼 채 보존한 파일(잠김)은 건드리지 않음
        return path
    try:
        dur = probe_duration(path)
        vc = next((c for t, c, *_ in probe_streams(path)[0] if t == "video"), None)
        enc = s["codec"] in ("h264", "h265", "av1") and not same_codec(path, s["codec"])
        tags = {"title": job["title"]}
        if enc:
            compress_turn(job["id"], platform_of(job["url"]), dl)
            out, _ = compress(path, dur, s, job["id"], tags=tags, live=True)
        if not enc or out == path:  # 압축 안 함 · 압축해도 안 작아짐 → 화질 그대로 mp4 로만
            out, _ = compress(path, dur, s | {"codec": "copy", "src_codec": "h265" if vc == "hevc" else vc}, job["id"], force=True, tags=tags)
        meta = json.loads((q("SELECT meta FROM jobs WHERE id=?", (job["id"],)) or [{}])[0].get("meta") or "{}")
        q("UPDATE jobs SET meta=? WHERE id=?", (json.dumps(meta | {"size": os.path.getsize(out), "duration": dur}, ensure_ascii=False), job["id"]))
        frame_thumb(out, dur)
        return out
    except Exception as e:
        log(f"끝난 녹화 정리 실패 (녹화 파일은 그대로): {job['title']} — {str(e)[-120:]}")
        return path


def auto_merge(job):
    try:
        merge_parts(job["id"])
    except Exception as e:  # 형식이 다른 조각·오류 조각이 있으면 그대로 두고 알림 (영상 정보 창에서 직접 합치기 가능)
        log(f"방송 끝 → 녹화 조각 자동 합치기 안 함: {job['title']} — {getattr(e, 'detail', e)}")


def frame_thumb(path, dur=None):
    """녹화 파일 옆에 '영상이름.jpg' 가 없으면(치지직 생방송 썸네일 주소 만료 등) 녹화 10% 지점 장면으로 만듦. 실패해도 무시
    (예전엔 큰 파일에서 시간 초과가 나면 다 받은 녹화가 '오류'가 됐음). dur 없으면 파일에서 읽음"""
    jpg = os.path.splitext(path.removesuffix(".part"))[0] + ".jpg"
    if os.path.exists(jpg):
        return
    try:
        dur = probe_duration(path) if dur is None else dur
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(int(dur * 0.1)), "-i", path, "-frames:v", "1",
                        "-vf", "scale=-2:720", jpg], timeout=120, capture_output=True)
    except (OSError, subprocess.SubprocessError) as e:
        log(f"녹화 썸네일 만들기 실패 (영상은 그대로): {os.path.basename(path)} — {e}")


def claim(live, yt, cz):
    """대기 중인 작업 하나 가져오기. yt/cz = 유튜브/치지직 각각 동시에 돌릴 수 있는 최대 개수 (0 이면 그 플랫폼은 안 가져옴)
    개수 확인과 가져오기가 한 문장이라 여러 스레드가 동시에 불러도 한도를 넘지 않음"""
    cz_sql = "url LIKE '%chzzk.naver.com%'"
    # 압축 단계(COMPRESSING)는 다운로드 개수에서 뺌 → 압축 중에도 다음 영상을 받음
    running = f"(SELECT COUNT(*) FROM jobs WHERE status='downloading' AND COALESCE(live,0)=? AND id NOT IN ({','.join(map(str, COMPRESSING.copy())) or 0}) AND {{}})"
    r = q(f"""UPDATE jobs SET status='downloading', error=NULL, err_seen=0, started={time.time()}, cut=NULL WHERE id=(
             SELECT id FROM jobs WHERE status='queued' AND COALESCE(live,0)=?
               AND (({cz_sql} AND {running.format(cz_sql)} < ?) OR (NOT {cz_sql} AND {running.format('NOT ' + cz_sql)} < ?))
             ORDER BY COALESCE(pri,0) DESC, id LIMIT 1) RETURNING *""", (live, live, cz, live, yt))  # "맨 앞으로" 한 것 먼저
    return r[0] if r else None


def forever(name, step):
    """작업 스레드는 예상 못 한 오류(DB 잠김 등)가 나도 죽지 않고 기록 후 계속."""
    while True:
        try:
            step()
        except Exception as e:
            log(f"{name} 오류 (30초 후 계속): {str(e)[:150]}")
            time.sleep(30)


def free_space(path):
    while not os.path.exists(path):  # 아직 안 만든 폴더면 있는 상위 폴더 기준
        path = os.path.dirname(path)
    return path, shutil.disk_usage(path).free


def low_disk(s):
    """이 작업의 저장 위치 남은 공간이 설정값(min_free_gb)보다 적으면 True. 처음 걸릴 때만 기록.
    ponytail: 한 디스크가 차면 그 대기열 맨 앞 영상이 막혀 다른 디스크 영상도 기다림 — 디스크별로 나눌 필요가 생기면 claim 에서 거르기"""
    path, free = free_space(safe_dir(s["folder"]))
    low = free < float(s["min_free_gb"]) * 1e9
    if low and STATE.get("disk_low") != path:
        log(f"디스크 공간 부족 → 새 다운로드 멈춤: {path.replace(HOST, '') or '/'} 남은 {free / 1e9:.1f}GB (설정 {s['min_free_gb']}GB)")
    STATE["disk_low"] = path if low else None
    return low


def worker(slot, live=0):
    forever(f"{'라이브 녹화' if live else '다운로드'} {slot + 1}", lambda: worker_step(slot, live))


def job_thread(job, s, dl):
    try:
        run_job(job, s, dl)
        if job["id"] in MERGE_AFTER:
            MERGE_AFTER.discard(job["id"])
            auto_merge(job)
    except Exception as e:  # 예상 못 한 오류로 이 영상이 '다운로드 중'으로 멈춰 있지 않게
        q("UPDATE jobs SET status='error', error=?, finished=? WHERE id=? AND status='downloading'",
          (f"내부 오류: {e}"[:500], time.time(), job["id"]))
        log(f"내부 오류: {job['title']} — {str(e)[:150]}")
    finally:
        dl.set()
        try:  # 이 스레드가 쓴 로그인 쿠키 복사본 정리 (작업마다 새 스레드라 안 지우면 계정 정보 복사본이 계속 쌓임)
            os.remove(f"/tmp/cookies-{threading.get_ident()}.txt")
        except OSError:
            pass


def worker_step(slot, live):
    while True:
        s = settings()
        # 유튜브 차단 일시정지·하루 한도는 유튜브에만 (치지직은 무관)
        yt_ok = not paused() and (live or done_today() < int(s["daily_limit"]))
        if live:
            yt, cz = min(int(s["live_concurrency"]), MAX_PARALLEL), min(int(s["chzzk_live_concurrency"]), MAX_PARALLEL)
        else:
            yt, cz = min(int(s["concurrency"]), MAX_PARALLEL), min(int(s["chzzk_concurrency"]), MAX_PARALLEL)
        yt = yt if yt_ok else 0
        if not live:  # 압축 대기가 압축 개수의 2배를 넘으면 그 플랫폼은 새로 받지 않음 (생방송 녹화는 쉬지 않음)
            waiting = [p for j, p in COMPRESSING.copy().items() if j not in COMP_RUN]
            yt = 0 if waiting.count("youtube") >= 2 * int(s["compress_concurrency"]) else yt
            cz = 0 if waiting.count("chzzk") >= 2 * int(s["chzzk_compress_concurrency"]) else cz
        job = claim(live, yt, cz)
        if not job:
            time.sleep(5)
            continue
        try:
            s = job_settings(job)
            if low_disk(s):  # 꽉 찬 디스크에 받으면 반쯤 받다 깨짐 → 대기열로 돌려놓고 1분 뒤 다시 확인
                q("UPDATE jobs SET status='queued' WHERE id=?", (job["id"],))
                time.sleep(60)
                continue
            # 받기는 따로 스레드에서. 다 받고 압축 단계로 넘어가면(또는 끝나면) dl 신호 → 이 스레드는 다음 영상을 받으러 감
            dl = threading.Event()
            threading.Thread(target=job_thread, args=(job, s, dl), daemon=True).start()
            dl.wait()
            if live:  # 녹화가 끝나면 압축을 기다리지 않고 바로 이어서 녹화
                continue_live(job)
        except Exception as e:  # 예상 못 한 오류로 스레드가 다시 시작돼도 이 영상이 '다운로드 중'으로 멈춰 있지 않게
            q("UPDATE jobs SET status='error', error=?, finished=? WHERE id=? AND status='downloading'",
              (f"내부 오류: {e}"[:500], time.time(), job["id"]))
            raise
        if not live and platform_of(job["url"]) == "youtube":  # 영상 사이 쉬기는 유튜브 봇 감지용
            wait = random.uniform(float(s["sleep_min"]), float(s["sleep_max"]))
            STATE["next_at"] = time.time() + wait
            time.sleep(wait)


def check_sub(sub, s):
    found, err = 0, None
    for u in sub_urls(sub):
        try:
            # 재생목록은 보통 오래된 순이라 새 영상이 끝에 붙음 → 전체를 봄 (이미 있는 건 건너뜀). ponytail: 아주 긴 재생목록은 확인이 느림
            found += enqueue(u, sub["id"], None if "list=" in u else int(s["sub_fetch_limit"]))[0]
        except Exception as e:
            if "does not have a" in str(e):  # 숏츠/라이브 탭이 없는 채널 → 정상
                continue
            err = str(e)[:300]
            if BOT_RE.search(err):
                cooldown(err)
                break
        time.sleep(random.uniform(3, 8))  # 탭(동영상/숏츠/라이브) 사이 대기
    q("UPDATE subs SET last_checked=?, last_error=?, last_found=? WHERE id=?", (time.time(), err, found, sub["id"]))
    log(f"구독 확인: {sub['name']} — 새 영상 {found}개" + (f" (오류: {err[:80]})" if err else ""))


def find_missing(ids, known, limit):
    """유튜브 최신순 id 중 놓친 영상 = 이미 기록된 것 중 가장 오래된 것보다 새로운데 기록이 없는 것.
    그보다 오래된 건 구독 전 영상이라 제외. 기록이 하나도 없으면 최신 limit 개 기준."""
    idx = [i for i, v in enumerate(ids) if v in known]
    return [v for v in ids[:idx[-1] if idx else limit] if v not in known]


def file_issue(job):
    p = job["filepath"]
    if not p or not os.path.exists(p):
        return "파일 없음 (삭제/이동됨)"
    if os.path.getsize(p) == 0:
        return "빈 파일"
    meta = json.loads(job["meta"] or "{}")
    if meta.get("size") and os.path.getsize(p) != meta["size"]:  # 길이는 헤더 값이라 잘린 파일도 정상으로 나옴 → 크기로 확인
        return f"파일 크기 변경됨 ({os.path.getsize(p) / 1e6:.1f}MB / 완료 당시 {meta['size'] / 1e6:.1f}MB) - 손상 가능"
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                       capture_output=True, text=True, timeout=120)
    try:
        got = float(r.stdout.strip())
    except ValueError:
        return "재생 불가 (손상)"
    want = meta.get("duration")
    if want and not job["live"] and abs(got - want) > max(3, want * 0.03):
        return f"길이 불일치 ({got:.0f}초 / 원본 {want}초) - 일부만 받아졌을 수 있음"
    return None


def audit_hours(s):
    return sorted({int(h) for h in s["audit_hours"].split(",") if h.strip().isdigit() and int(h) < 24})


def audit_due(hours, last, now=None):
    now = now or datetime.now()
    return any(last < t.timestamp() <= now.timestamp()
               for t in (now.replace(hour=h, minute=0, second=0, microsecond=0) for h in hours))


def next_audit(hours, now=None):
    now = now or datetime.now()
    ts = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in hours]
    return min(t if t > now else t + timedelta(days=1) for t in ts).timestamp() if ts else None


def mark_source_gone(sub_id, kind, listed):
    """점검 때 이미 받아 온 채널 목록(최신 N개)으로 '원본이 사라진' 받은 영상 표시 → [{id, title}] (새로 요청하지 않음).
    목록에 있는 받은 영상 중 가장 오래된 업로드 날짜보다 새로운데 목록에 없으면 삭제 · 비공개 등으로 사라진 것.
    다시 목록에 나오면 표시를 지움. 표시만 할 뿐 파일은 그대로 (치지직 생방송 녹화는 목록에 없으므로 제외)"""
    rows = [r | {"m": json.loads(r["meta"] or "{}")} for r in q(
        "SELECT id, title, video_id, meta FROM jobs WHERE sub_id=? AND kind=? AND status='done' AND video_id NOT LIKE 'chzzk-live-%'", (sub_id, kind))]
    dates = [r["m"]["upload_date"] for r in rows if r["video_id"] in listed and r["m"].get("upload_date")]
    if not dates:
        return []
    floor, gone = min(dates), []
    for r in rows:
        m = r["m"]
        if r["video_id"] in listed:
            if m.pop("source_gone", None):
                q("UPDATE jobs SET meta=? WHERE id=?", (json.dumps(m, ensure_ascii=False), r["id"]))
        elif (m.get("upload_date") or "") > floor:
            if not m.get("source_gone"):
                m["source_gone"] = time.time()
                q("UPDATE jobs SET meta=? WHERE id=?", (json.dumps(m, ensure_ascii=False), r["id"]))
                log(f"원본이 채널에서 사라짐 (받은 파일은 그대로): {r['title']}")
            gone.append({"id": r["id"], "title": r["title"]})
    return gone


def run_audit(s):
    """유튜브 ↔ 다운로드 기록 비교, 파일 상태 확인, 실패 재시도. 구독 확인 스레드에서 차례로 실행."""
    STATE["auditing"] = True
    started, res = time.time(), {"subs": [], "missing_added": 0, "gone": []}
    log("다운로드 점검 시작")
    try:
        known = {r["video_id"] for r in q("SELECT video_id FROM jobs")}
        for sub in q("SELECT * FROM subs WHERE enabled=1 ORDER BY name"):
            if paused():
                res["aborted"] = "유튜브 차단 신호로 유튜브 비교 중단"
                break
            r = {"name": sub["name"], "listed": 0, "missing": 0, "error": None}
            for u in sub_urls(sub):
                try:
                    entries, _, kind = list_entries(u, AUDIT_DEPTH)
                except Exception as e:
                    if "does not have a" not in str(e):  # 숏츠/라이브 탭 없는 채널은 정상
                        r["error"] = str(e)[:200]
                        if BOT_RE.search(r["error"]):
                            cooldown(r["error"])
                            break
                    continue
                miss = set(find_missing([e["id"] for e in entries], known, int(s["sub_fetch_limit"])))
                r["listed"] += len(entries)
                r["missing"] += add_entries([e for e in entries if e["id"] in miss], kind, sub["id"])
                res["gone"] += mark_source_gone(sub["id"], kind, {e["id"] for e in entries})
                time.sleep(random.uniform(3, 8))  # 탭 사이 대기
            res["subs"].append(r)
            res["missing_added"] += r["missing"]
            time.sleep(random.uniform(5, 15))  # 채널 사이 대기

        # ponytail: 완료 파일 전체를 매번 ffprobe - 수만 개가 되면 최근 N일치만 검사하도록 바꾸면 됨
        done = q("SELECT id, title, filepath, meta, live FROM jobs WHERE status='done'")
        res["files_checked"] = len(done)
        res["file_issues"] = [{"id": j["id"], "title": j["title"], "issue": i} for j in done if (i := file_issue(j))]

        # 생방송은 제외: 나중에 다시 받으면 그때 하고 있는 방송을 녹화하게 됨 (끊긴 녹화는 continue_live 가 바로 이어 받음)
        retry = q("UPDATE jobs SET status='queued', progress=0, error=NULL, retries=COALESCE(retries,0)+1 "
                  "WHERE status='error' AND COALESCE(live,0)=0 AND COALESCE(retries,0) < ? RETURNING id", (MAX_RETRIES,))
        res["retried"] = len(retry)
        res["gave_up"] = q("SELECT id, title, error FROM jobs WHERE status='error'")
    finally:
        STATE["auditing"] = False
    q("INSERT INTO audits(started, finished, result) VALUES(?,?,?)", (started, time.time(), json.dumps(res, ensure_ascii=False)))
    q("DELETE FROM audits WHERE id NOT IN (SELECT id FROM audits ORDER BY id DESC LIMIT 30)")
    log(f"다운로드 점검 완료: 놓친 영상 {res['missing_added']}개 추가, 파일 문제 {len(res['file_issues'])}개, "
        f"실패 재시도 {res['retried']}개, 포기 {len(res['gave_up'])}개")


def scheduler():
    forever("구독 확인", scheduler_step)


def recording(cid):
    """이 채널을 녹화 중(대기 포함)이거나 방금(1분 안) 녹화가 끝나 이어서 녹화할 참이면 True → 새 녹화를 또 만들지 않음.
    예전엔 방송 중 제목을 바꾸는 등으로 방송 ID 가 바뀌면 같은 방송을 새 녹화(새 폴더)로 또 받았음"""
    # 압축 단계(녹화는 끝남)는 빼야 함 — 예전엔 끝난 방송을 압축하는 동안(몇십 분) 새로 시작한 방송을 녹화하지 않았음
    return bool(q(f"""SELECT 1 FROM jobs WHERE url=? AND live=1 AND id NOT IN ({','.join(map(str, COMPRESSING.copy())) or 0})
                     AND (status IN ('queued','downloading') OR finished > ?) LIMIT 1""",
                  (f"https://chzzk.naver.com/live/{cid}", time.time() - 60)))


def chzzk_watch_step():
    """구독한 치지직 채널(생방송 체크)의 방송 시작을 10초마다 확인 → 바로 녹화.
    방송 상태 API 하나만 부르는 가벼운 요청이라 유튜브 같은 차단 걱정 없음"""
    for sub in q("SELECT id, url, name FROM subs WHERE enabled=1 AND url LIKE '%chzzk.naver.com%' AND kinds LIKE '%streams%'"):
        if (m := CHZZK_CH_RE.match(sub["url"].strip())) and not recording(m.group(1)) and add_entries(chzzk_live(m.group(1)), "streams", sub["id"]):
            log(f"치지직 방송 시작 → 녹화: {sub['name']}")
    time.sleep(CHZZK_LIVE_SEC)


def scheduler_step():
    while True:
        if time.time() - STATE.get("updates", {}).get("checked", 0) > UPDATE_CHECK_SEC:
            check_updates()
        s = settings()
        last = q("SELECT COALESCE(MAX(started), 0) t FROM audits")[0]["t"]
        if not paused() and (STATE.pop("audit_now", False) or audit_due(audit_hours(s), last)):
            run_audit(s)
        for sub in q("SELECT * FROM subs WHERE enabled=1 ORDER BY last_checked"):
            if paused():
                break
            if time.time() >= next_check(sub, s):
                check_sub(sub, s)
                time.sleep(random.uniform(5, 15))  # 채널 사이 대기
        WAKE.wait(60)
        WAKE.clear()


def versions():
    v = {"yt-dlp": yt_dlp.version.__version__}
    for name, cmd in (("ffmpeg", ["ffmpeg", "-version"]), ("deno", ["deno", "--version"])):
        try:
            v[name] = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.split("\n")[0][:60]
        except Exception:
            v[name] = None
    return v


GITHUB_REPO = "aodrha03/chitube"  # 새 버전 알림에 쓰는 저장소


def ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])  # "2026.08.19" / "deno 2.9.7 (...)" → 숫자 3개


def check_updates():
    """설치된 버전과 최신 버전 비교. yt-dlp·deno 는 컨테이너 재시작 때 자동 갱신, ffmpeg 는 이미지 재빌드 때 갱신."""
    def latest(url, pick):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "chitube"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return pick(json.load(r))
        except Exception:
            return None

    items = [
        {"name": "yt-dlp", "current": VERSIONS.get("yt-dlp"), "how": "restart",
         "latest": latest("https://pypi.org/pypi/yt-dlp/json", lambda d: d["info"]["version"])},
        {"name": "deno", "current": VERSIONS.get("deno"), "how": "restart",
         "latest": latest("https://api.github.com/repos/denoland/deno/releases/latest", lambda d: d["tag_name"])},
        {"name": "ffmpeg", "current": VERSIONS.get("ffmpeg"), "how": "rebuild", "latest": None},
        # 치튜브 자체: GitHub 의 최신 릴리스 (새 버전은 릴리스 페이지에서 받아 덮어쓰고 다시 빌드)
        {"name": "치튜브", "current": APP_VERSION, "how": "release", "url": f"https://github.com/{GITHUB_REPO}/releases/latest",
         "latest": latest(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", lambda d: d["tag_name"])},
    ]
    for i in items:
        i["outdated"] = bool(i["current"] and i["latest"]) and ver(i["latest"]) > ver(i["current"])
        if i["outdated"] and not any(x["name"] == i["name"] and x.get("outdated") for x in STATE.get("updates", {}).get("items", [])):
            log(f"업데이트 있음: {i['name']} {i['latest'].lstrip('v')} (설치됨 {'.'.join(map(str, ver(i['current'])))})")
    STATE["updates"] = {"checked": time.time(), "items": items}


def start(name, f, *args):
    THREADS[name] = threading.Thread(target=f, args=args, daemon=True, name=name)
    THREADS[name].start()


@asynccontextmanager
async def lifespan(app):
    os.makedirs(CONFIG, exist_ok=True)
    init_db()
    for j in q("SELECT * FROM jobs WHERE status='downloading' AND live=1"):
        if j["filepath"] and os.path.isfile(j["filepath"]):  # 녹화는 끝나고 압축을 기다리던 중 → 녹화본 그대로 완료 (나중에 압축 가능)
            q("UPDATE jobs SET status='done', finished=? WHERE id=?", (time.time(), j["id"]))
            log(f"재시작으로 압축 못 한 녹화는 원본 그대로 보존 (나중에 압축 가능): {j['title']}")
        else:  # 재시작으로 끊긴 녹화: 녹화분 보존, 새 파일로 다시 녹화
            keep_partial(j["video_id"], job_settings(j))
    q("UPDATE jobs SET status='queued' WHERE status='downloading'")  # 재시작 시 중단된 작업 복구
    sweep_temp()  # 강제 종료/취소로 남은 압축 임시파일 정리
    VERSIONS.update(versions())
    detect_hw()
    for i in range(MAX_PARALLEL * 2):  # 스레드는 공용, 플랫폼별 개수는 claim 에서 제한
        start(f"다운로드 {i + 1}", worker, i)
    for i in range(MAX_PARALLEL * 2):  # 유튜브·치지직 최대치만큼. 실제 개수는 claim 에서 설정값으로 제한
        start(f"라이브 녹화 {i + 1}", worker, i, 1)
    start("구독 확인", scheduler)
    start("치지직 방송 감시", forever, "치지직 방송 감시", chzzk_watch_step)
    threading.Thread(target=backfill_nfo, daemon=True).start()
    log("시작됨")
    yield


app = FastAPI(lifespan=lifespan)


class Opts(BaseModel):
    quality: str = ""
    max_height: str = ""
    folder: str = ""
    kinds: str = ""
    interval_min: str = ""
    title_inc: str = ""  # 구독 필터 (쉼표 구분)
    title_exc: str = ""
    min_min: str = ""    # 최소 길이(분)


class Url(Opts):
    url: str
    backfill: bool = False  # 구독할 때 기존 영상 전부 (처음 영상부터)
    force: bool = False     # 유튜브 봇 감지로 쉬는 중이어도 불이익을 확인하고 받기 (일시정지도 풀림)


@app.get("/")
def index():
    # no-cache: 업데이트 후에도 브라우저가 예전 화면을 보여 주지 않게 (매번 바뀌었는지 확인)
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"), headers={"Cache-Control": "no-cache"})


JOB_FILTERS = {"active": "status='downloading'", "queued": "status='queued'", "done": "status='done'",
               "error": "status IN ('error','cancelled')"}  # 화면 상태 필터 (진행 중 / 대기 / 완료 / 오류·취소)


SORTS = {"new": "id DESC", "old": "id", "title": "title COLLATE NOCASE, id DESC",
         "size": "json_extract(meta, '$.size') DESC, id DESC", "duration": "json_extract(meta, '$.duration') DESC, id DESC",
         "upload": "json_extract(meta, '$.upload_date') DESC, id DESC", "channel": "json_extract(meta, '$.channel') COLLATE NOCASE, id DESC"}


@app.get("/api/jobs")
def jobs(sub: int | None = None, platform: str | None = None, status: str | None = None, search: str | None = None,
         page: int = 1, per: int = 300, sort: str = "new"):
    """page/per: 화면 아래 1,2,3… 페이지. 대기 목록은 받을 순서(오래된 것부터), 나머지는 최근 것부터"""
    cols = "id, video_id, url, title, sub_id, status, progress, error, err_seen, kind, live, thumb, cut, json_extract(meta, '$.source_gone') AS gone"  # meta(설명 등)는 상세에서만
    where, args = [], []
    if sub:
        where, args = ["sub_id=?"], [sub]
    if platform == "chzzk":
        where.append("url LIKE '%chzzk.naver.com%'")
    elif platform == "youtube":
        where.append("url NOT LIKE '%chzzk.naver.com%'")
    if search:
        where.append("(title LIKE ? OR json_extract(meta, '$.channel') LIKE ?)")  # 제목 또는 채널명
        args += [f"%{search}%"] * 2
    base = " AND ".join(where) or "1"
    counts = {r["status"]: r["n"] for r in q(f"SELECT status, COUNT(*) n FROM jobs WHERE {base} GROUP BY status", args)}
    if status in JOB_FILTERS:
        base += " AND " + JOB_FILTERS[status]
    per = max(1, min(per, 300))
    total = q(f"SELECT COUNT(*) n FROM jobs WHERE {base}", args)[0]["n"]
    order = "COALESCE(pri,0) DESC, id" if status == "queued" else SORTS.get(sort, "id DESC")  # 대기 목록 = claim 이 가져가는 순서
    rows = q(f"SELECT {cols} FROM jobs WHERE {base} ORDER BY {order} LIMIT ? OFFSET ?", args + [per, (max(page, 1) - 1) * per])
    for r in rows:
        r.update(live_state(r))
    return {"jobs": rows, "counts": counts, "total": total, "wait": max(0, int(STATE["next_at"] - time.time())),
            # 2초마다 오는 목록 응답에 실어 봇 감지 경고가 바로 뜨게
            "paused_until": STATE["paused_until"] if paused() else 0, "pause_reason": STATE["pause_reason"]}


class Bulk(BaseModel):
    ids: list[int]
    action: str  # cancel | retry | delete | top


@app.post("/api/jobs/bulk")
def bulk(body: Bulk):
    """여러 영상 한 번에: 취소(녹화는 저장) / 다시 받기(오류·취소된 것만 — 완료된 건 파일을 지우므로 제외) / 목록에서 삭제"""
    done = 0
    for jid in reversed(body.ids) if body.action == "top" else body.ids:  # 맨 앞으로: 뒤에서부터 올려 고른 순서 유지
        st = (q("SELECT status FROM jobs WHERE id=?", (jid,)) or [{}])[0].get("status")
        if body.action == "top" and st == "queued":
            to_top(jid)
        elif body.action == "cancel" and st in ("queued", "downloading"):
            cancel(jid)
        elif body.action == "retry" and st in ("error", "cancelled"):
            try:
                redownload(jid)
            except HTTPException:  # 녹화 파일이 있는 생방송은 건너뜀
                continue
        elif body.action == "delete" and st and st != "downloading" and jid not in RECOMP:  # 나중에 압축 중인 건 건너뜀
            delete_job(jid)
        else:
            continue
        done += 1
    return {"done": done}


@app.get("/api/jobs/{jid}")
def job(jid: int):
    r = q("SELECT * FROM jobs WHERE id=?", (jid,))
    if not r:
        raise HTTPException(404)
    r[0]["meta"] = json.loads(r[0]["meta"] or "{}")
    r[0]["file_ok"] = bool(r[0]["filepath"] and os.path.isfile(r[0]["filepath"]))  # 완료인데 파일이 지워졌으면 화면에 '파일 없음'
    if r[0]["live"]:  # 끊겨서 여러 파일로 나뉜 녹화: 같은 방송의 파일들 (시작·끊긴 시각 → 화면에서 끊긴 지점·누락 시간 표시)
        base = part_of(r[0]["video_id"])[0]
        r[0]["parts"] = [p for p in q("SELECT id, video_id, status, started, cut FROM jobs WHERE video_id=? OR video_id LIKE ? ORDER BY id",
                                      (base, base + "-p%")) if part_of(p["video_id"])[0] == base]
    return r[0] | live_state(r[0])


def live_state(row):
    """화면에 덮어 보일 실시간 상태. 받는 중(또는 나중에 압축 중)인 것만 — 예전엔 끝난 작업에 진행 표시 스레드가 늦게 남긴
    '녹화 중' 상태가 그대로 보여, 오류 항목이 녹화 중으로 보이고 취소 · 목록에서 삭제가 안 됐음"""
    if row["id"] in RECOMP:
        return LIVE.get(row["id"], {}) | {"recomp": True}
    return LIVE.get(row["id"], {}) if row["status"] == "downloading" else {}


def done_file(jid):
    j = q("SELECT filepath FROM jobs WHERE id=? AND status='done'", (jid,))
    if not j or not j[0]["filepath"] or not os.path.isfile(j[0]["filepath"]):
        raise HTTPException(404, "파일이 없습니다 (삭제·이동됨)")
    return j[0]["filepath"]


@app.get("/api/jobs/{jid}/file")
def job_file(jid: int, download: bool = False):
    """받은 영상 재생(브라우저에서 바로, 구간 이동 가능) / download=1 이면 내 컴퓨터로 저장"""
    p = done_file(jid)
    return FileResponse(p, filename=os.path.basename(p), content_disposition_type="attachment" if download else "inline")


@app.get("/api/jobs/{jid}/thumb")
def job_thumb(jid: int):
    """영상 옆에 저장한 썸네일. 치지직 생방송 썸네일 주소는 방송이 끝나면 만료(404)돼서 화면이 이걸로 대신 보여줌"""
    j = q("SELECT filepath FROM jobs WHERE id=?", (jid,))
    p = j and j[0]["filepath"]
    for f in glob.glob(glob.escape(os.path.splitext(p)[0]) + ".*") if p else []:
        if f.endswith((".jpg", ".webp", ".png")):
            return FileResponse(f)
    raise HTTPException(404, "썸네일 파일 없음")


@app.get("/api/jobs/{jid}/preview")
def job_preview(jid: int):
    """받는 중·녹화 중인 영상 확인용: 받고 있는 파일의 마지막 10초(안 되면 처음 10초)를 다시 인코딩 없이 잘라 줌
    → 저장되는 영상과 같은 화질·비트레이트 (재생 가능 여부도 완료 후 재생과 같음, H.265 는 브라우저에 따라 다름).
    녹화 조각(.part, MPEG-TS)·webm·분할 mp4 는 되고, 끝까지 받아야 열리는 일반 mp4 조각은 못 열 수 있음"""
    j = q("SELECT * FROM jobs WHERE id=? AND status='downloading'", (jid,))
    if not j:
        raise HTTPException(404, "받는 중인 영상이 아닙니다")
    files = [f for f in glob.glob(os.path.join(glob.escape(safe_dir(job_settings(j[0])["folder"])), "**", f"*{glob.escape('[' + j[0]['video_id'] + ']')}*"),
                                  recursive=True) if os.path.isfile(f) and not f.endswith((".ytdl", ".aria2", ".jpg", ".webp", ".png", ".vtt", ".srt", ".nfo"))]
    for f in sorted(files, key=os.path.getmtime, reverse=True)[:3]:
        seeks = [["-sseof", "-15"], []]  # 끝에서 15초 전부터(쓰는 중인 마지막 몇 초는 덜 기록됐을 수 있음) → 안 되면 처음부터
        if os.path.exists(f + ".aria2"):  # 치지직 다시보기: 끝은 빈칸이라 받아 둔 가장 뒤쪽 구간에서
            try:
                t = aria2_seek(f + ".aria2", probe_streams(f)[1])
            except (OSError, ValueError):
                t = None
            seeks = ([["-ss", f"{t:.1f}"]] if t is not None else []) + [[]]
        for seek in seeks:
            hevc = any(c == "hevc" for _, c, *_ in probe_streams(f)[0])  # 사파리 등은 hvc1 태그가 있어야 H.265 재생
            r = subprocess.run(["ffmpeg", "-v", "error", *seek, "-i", f, "-t", "10", "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy",
                                *(["-tag:v", "hvc1"] if hevc else []),
                                "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"], capture_output=True, timeout=60)
            if r.returncode == 0 and len(r.stdout) > 10_000:
                return Response(r.stdout, media_type="video/mp4", headers={"Cache-Control": "no-store"})
    raise HTTPException(404, "아직 미리보기를 만들 수 없습니다 (받기 시작 직후이거나, 끝까지 받아야 열리는 형식)")


def probe_streams(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
                        "-of", "json", p], capture_output=True, text=True, timeout=120)
    d = json.loads(r.stdout or "{}")
    return [(x.get("codec_type"), x.get("codec_name"), x.get("width"), x.get("height")) for x in d.get("streams", [])], float(d.get("format", {}).get("duration") or 0)


MERGING = set()  # 합치는 중인 녹화 (1번째 조각 id) → 두 번 누르기 방지


RECOMP = set()  # 나중에 압축 중인 완료 영상 (화면에 압축 진행률 표시)


class Recompress(BaseModel):
    ids: list[int]
    quality: str


@app.post("/api/jobs/compress")
def recompress(body: Recompress):
    """다 받은 영상(원본 그대로 받은 것 · 녹화 · 다시보기)을 나중에 압축 → 압축 칸이 나는 대로 차례로. 작아질 때만 바꿈"""
    if body.quality not in QUALITY:
        raise HTTPException(400, "압축할 화질을 고르세요")
    rows = [r for r in q(f"SELECT * FROM jobs WHERE status='done' AND id IN ({','.join('?' * len(body.ids)) or 'NULL'})", body.ids)
            if r["filepath"] and os.path.isfile(r["filepath"]) and r["id"] not in RECOMP]
    for r in rows:
        RECOMP.add(r["id"])
        LIVE[r["id"]] = {"status": "compressing", "progress": 0, "waiting": True}
        threading.Thread(target=recompress_one, args=(r, body.quality), daemon=True).start()
    if rows:
        log(f"나중에 압축 {len(rows)}개 시작 ({body.quality})")
    return {"queued": len(rows)}


def recompress_one(job, quality):
    jid, src = job["id"], job["filepath"]
    try:
        s = resolve(job_settings(job), {"quality": quality})
        compress_turn(jid, platform_of(job["url"]))
        size0 = os.path.getsize(src)
        out, hw = compress(src, probe_duration(src), s, jid, live=bool(job["live"]))
        if out == src:
            log(f"압축해도 작아지지 않아 그대로 둠: {job['title']}")
            return
        meta = json.loads((q("SELECT meta FROM jobs WHERE id=?", (jid,)) or [{}])[0].get("meta") or "{}")
        meta |= {"size": os.path.getsize(out), "orig_size": meta.get("orig_size") or size0, "quality": quality,
                 "compressed": {"codec": s["codec"], "crf": s["crf"], "preset": s["preset"], "encoder": HW_NAME[hw]}}
        q("UPDATE jobs SET filepath=?, meta=? WHERE id=?", (out, json.dumps(meta, ensure_ascii=False), jid))
        log(f"나중에 압축 완료: {job['title']} ({size0 / 1e9:.2f}GB → {meta['size'] / 1e9:.2f}GB)")
    except Exception as e:
        log(f"나중에 압축 {'취소' if jid in CANCEL else '실패'} (원본 그대로): {job['title']} — {str(e)[-120:]}")
    finally:
        compress_done(jid)
        RECOMP.discard(jid)
        LIVE.pop(jid, None)
        CANCEL.discard(jid)


@app.post("/api/jobs/{jid}/merge")
def merge_parts(jid: int, reencode: bool = False):
    """끊겨서 -p2, -p3… 로 나뉜 녹화를 한 파일로. 1번째 파일 자리에 저장, 나머지 파일·목록은 정리.
    형식이 같으면 재인코딩 없이 이어 붙임(빠름). 다르면(예: 처음엔 원본 H.264, 이어진 조각은 압축된 H.265)
    그대로 붙이면 깨짐 → 409 로 알리고, reencode=1 이면 전부 풀어서 지금 화질 설정으로 다시 압축해 합침(오래 걸려 백그라운드)"""
    parts = job(jid).get("parts") or []
    rows = [q("SELECT * FROM jobs WHERE id=?", (p["id"],))[0] for p in parts]
    if len(rows) < 2:
        raise HTTPException(400, "합칠 조각이 없습니다")
    if any(r["status"] != "done" or not r["filepath"] or not os.path.isfile(r["filepath"]) for r in rows):
        raise HTTPException(400, "모든 조각이 '완료'이고 파일이 있어야 합칠 수 있습니다 (녹화 중·오류·파일 없음)")
    if rows[0]["id"] in MERGING:
        raise HTTPException(409, "이미 합치는 중입니다 (끝나면 로그에 표시)")
    probes = [probe_streams(r["filepath"]) for r in rows]
    if len({tuple(p[0]) for p in probes}) == 1:
        return do_merge(rows, probes, False)
    if not reencode:
        raise HTTPException(409, "조각마다 영상 형식(코덱·해상도)이 달라 그대로는 이어 붙일 수 없습니다")
    MERGING.add(rows[0]["id"])
    threading.Thread(target=do_merge, args=(rows, probes, True), daemon=True).start()
    log(f"녹화 조각 {len(rows)}개 다시 압축해서 합치는 중: {rows[0]['title']}")
    return {"started": True}


def do_merge(rows, probes, reencode):
    first = rows[0]["filepath"]
    out, lst = first + ".merging" + os.path.splitext(first)[1], f"/tmp/merge-{rows[0]['id']}.txt"
    try:
        if reencode:
            # concat 필터: 조각마다 따로 풀어서 이어 붙임 (코덱이 달라도 됨). 크기·소리 형식은 1번째 조각에 맞춤
            s = job_settings(rows[0])
            if s["codec"] in ("none", "copy"):  # '원본 그대로' 설정이면 H.265 표준으로
                s = s | {"codec": "h265", "crf": QUALITY["standard"][1]}
            hw = encoder_for(s)
            _, enc = encode_args(s, 0, "cpu" if hw == "vaapi" else hw)  # ponytail: 퀵싱크는 필터 연결이 달라 CPU 로
            w, h = next(((x[2], x[3]) for x in probes[0][0] if x[0] == "video"), (1920, 1080))
            audio = all(any(x[0] == "audio" for x in p[0]) for p in probes)
            fc = "".join(f"[{i}:v:0]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}];"
                         + (f"[{i}:a:0]aformat=sample_rates=48000:channel_layouts=stereo[a{i}];" if audio else "") for i in range(len(rows)))
            fc += "".join(f"[v{i}]" + (f"[a{i}]" if audio else "") for i in range(len(rows))) + f"concat=n={len(rows)}:v=1:a={int(audio)}[v]" + ("[a]" if audio else "")
            cmd = ["nice", "-n", "19", "ffmpeg", "-y", "-v", "error", *[a for r in rows for a in ("-i", r["filepath"])], "-filter_complex", fc,
                   "-map", "[v]", *(["-map", "[a]"] if audio else []), *enc, "-movflags", "+faststart", out]
        else:
            with open(lst, "w") as f:
                f.writelines("file '" + r["filepath"].replace("'", "'\\''") + "'\n" for r in rows)
            cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-map", "0", "-c", "copy", "-movflags", "+faststart", out]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=None if reencode else 3600)
        got = probe_streams(out)[1] if r.returncode == 0 else 0
        if got < sum(p[1] for p in probes) * 0.95:  # 길이가 모자라면 실패로 보고 원본 조각은 그대로 둠
            raise HTTPException(500, "합치기 실패: " + (r.stderr.strip().splitlines() or ["길이가 맞지 않음"])[-1][:200])
        os.replace(out, first)
    except BaseException as e:
        if os.path.exists(out):
            os.remove(out)
        if not reencode:
            raise
        log(f"녹화 조각 합치기 실패 (원본 조각은 그대로): {rows[0]['title']} — {getattr(e, 'detail', e)}")
        return
    finally:
        if os.path.exists(lst):
            os.remove(lst)
        MERGING.discard(rows[0]["id"])
    for r in rows[1:]:  # 나머지 조각 영상과 딸린 파일(썸네일·nfo) 삭제, 비면 영상별 폴더도
        for f in glob.glob(glob.escape(os.path.splitext(r["filepath"])[0]) + "*"):
            os.remove(f)
        try:
            os.rmdir(os.path.dirname(r["filepath"]))
        except OSError:
            pass
        q("DELETE FROM jobs WHERE id=?", (r["id"],))
    meta = json.loads(rows[0]["meta"] or "{}") | {"size": os.path.getsize(first), "duration": got, "merged": len(rows)}
    q("UPDATE jobs SET meta=?, cut=NULL WHERE id=?", (json.dumps(meta, ensure_ascii=False), rows[0]["id"]))
    log(f"녹화 조각 {len(rows)}개 합침{' (다시 압축)' if reencode else ''}: {rows[0]['title']}")
    return {"merged": len(rows)}


@app.get("/api/jobs/{jid}/sub/{lang}.vtt")
def job_sub(jid: int, lang: str):
    """저장된 .srt 자막 → 브라우저 재생기용 WebVTT (시간 표기 쉼표 → 점)"""
    srt = os.path.splitext(done_file(jid))[0] + f".{lang}.srt"
    if "/" in lang or not os.path.isfile(srt):
        raise HTTPException(404)
    with open(srt, encoding="utf-8", errors="replace") as f:
        text = f.read()
    return Response("WEBVTT\n\n" + re.sub(r"(\d\d:\d\d:\d\d),(\d\d\d)", r"\1.\2", text), media_type="text/vtt")


def lookup_error(e):
    msg = str(e).replace("ERROR: ", "")
    if BOT_RE.search(msg):
        cooldown(msg)
    return HTTPException(400, "유튜브 조회 실패: " + msg[:200])


@app.post("/api/download")
def download(body: Url):
    if paused() and platform_of(body.url) == "youtube":  # 봇 감지로 쉬는 중엔 어차피 실패 → 막고, 확인하면 재개 후 받기
        if not body.force:
            raise HTTPException(409, "유튜브 봇 감지로 쉬는 중")
        resume()
    try:
        added, name = enqueue(body.url, opts=clean_opts(body))
    except yt_dlp.utils.DownloadError as e:
        raise lookup_error(e)
    return {"added": added, "name": name}


@app.post("/api/jobs/{jid}/top")
def to_top(jid: int):  # 대기열 맨 앞으로 (다음에 받을 영상)
    q("UPDATE jobs SET pri=(SELECT COALESCE(MAX(pri),0)+1 FROM jobs) WHERE id=? AND status='queued'", (jid,))


@app.post("/api/jobs/{jid}/retry")
def retry(jid: int):  # 완료된 영상의 "다시 받기"도 여기로 옴 → 기존 파일을 지우지 않으면 압축본을 또 압축함
    redownload(jid)


@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: int):  # 라이브 녹화는 중지 후 저장, 다운로드/압축 중이면 중단, 대기 중이면 대기열에서 제외
    j = q("SELECT video_id, title, status FROM jobs WHERE id=?", (jid,))
    if j and j[0]["status"] != "downloading" and jid not in RECOMP:  # 끝난 작업: 대기 중이면 빼기만 (남은 진행 상태로 취소 신호가 남지 않게)
        q("UPDATE jobs SET status='cancelled', error=NULL WHERE id=? AND status='queued'", (jid,))
        return
    if j and LIVE.get(jid, {}).get("status") == "recording" and stop_recording(j[0]["video_id"]):
        STOPPED.add(jid)  # 직접 멈춘 녹화는 이어서 녹화하지 않음
        log(f"녹화 중지 → 저장: {j[0]['title']}")
        return {"saved": True}
    if jid in LIVE:
        CANCEL.add(jid)
        for exe in (b"aria2c", b"ffmpeg"):  # aria2c·받으면서 압축하는 ffmpeg 는 yt-dlp 진행률 콜백이 없어 직접 종료
            for pid, _ in procs(exe, j[0]["video_id"]) if j else ():
                os.kill(pid, 15)
    q("UPDATE jobs SET status='cancelled', error=NULL WHERE id=? AND status='queued'", (jid,))


@app.delete("/api/jobs/{jid}")
def delete_job(jid: int):  # 목록에서만 제거 (파일은 그대로)
    if jid in RECOMP:
        raise HTTPException(409, "나중에 압축 중입니다 (끝난 뒤 또는 압축 취소 후에)")
    j = q("SELECT filepath FROM jobs WHERE id=? AND status!='downloading'", (jid,))
    if j:
        restore_keep(j[0]["filepath"])  # 다시 받기 대기 중이던 영상이면 비켜 둔 파일을 되돌린 뒤 목록에서만 뺌
    q("DELETE FROM jobs WHERE id=? AND status!='downloading'", (jid,))


@app.get("/api/subs")
def subs(platform: str | None = None):
    s = settings()
    rows = q("""SELECT s.*, COUNT(j.id) AS total, COALESCE(SUM(j.status='done'), 0) AS done
                FROM subs s LEFT JOIN jobs j ON j.sub_id = s.id GROUP BY s.id ORDER BY s.name""")
    if platform:
        rows = [r for r in rows if platform_of(r["url"]) == platform]
    for r in rows:
        r["next_check"] = next_check(r, s)
    return rows


@app.post("/api/subs")
def add_sub(body: Url):
    o, (kinds, iv, flt) = clean_opts(body), clean_sub(body)
    url, m = body.url.strip(), CHZZK_CH_RE.match(body.url.strip())
    if m:  # 치지직 채널
        try:
            ch = chzzk_api(f"/v1/channels/{m.group(1)}")
        except Exception as e:
            raise HTTPException(400, f"치지직 채널 조회 실패: {e}")
        name, avatar, url = ch["channelName"], ch.get("channelImageUrl"), f"https://chzzk.naver.com/{m.group(1)}"
    else:
        yo = base_opts(settings(), url) | {"extract_flat": "in_playlist", "playlistend": 1, "extractor_args": {"youtube": {"lang": ["ko"]}}}
        try:
            with yt_dlp.YoutubeDL(yo) as y:
                info = y.extract_info(normalize(url), download=False)
        except yt_dlp.utils.DownloadError as e:
            raise lookup_error(e)
        name, avatar = info.get("channel") or info.get("uploader") or info.get("title"), avatar_of(info)
        if pl := re.search(r"[?&]list=([\w-]+)", url):  # 재생목록: 주소를 재생목록으로 고정 (watch?v=…&list=… 도), 이름은 재생목록 제목
            url, name = f"https://www.youtube.com/playlist?list={pl.group(1)}", f"{info.get('title')} (재생목록)"
    q("INSERT OR IGNORE INTO subs(url,name,avatar,quality,max_height,folder,kinds,interval_min,title_inc,title_exc,min_min) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
      (url, name, avatar, o["quality"], o["max_height"], o["folder"], kinds, iv, *flt))  # 스케줄러가 1분 내 확인
    log(f"구독 추가: {name}")
    if body.backfill:
        start_backfill(q("SELECT * FROM subs WHERE url=?", (url,))[0])
    return {"name": name}


def backfill(sub):
    """구독 채널의 기존 영상 전부를 오래된 것부터 대기열에 추가 (평소 확인은 최신 몇 개만 봄).
    유튜브는 하루 최대 개수 한도대로 며칠에 걸쳐 받음. 치지직 생방송 주소는 목록이 아니라 제외"""
    total = 0
    for u in sub_urls(sub):
        if CHZZK_CH_RE.match(u) and "/live" in u:
            continue
        try:
            entries, _, kind = list_entries(u)
            total += add_entries(entries[::-1], kind, sub["id"])  # 대기열은 넣은 순서대로 → 오래된 영상부터
        except Exception as e:
            if "does not have a" not in str(e):  # 숏츠/라이브 탭이 없는 채널은 정상
                log(f"기존 영상 가져오기 실패: {sub['name']} — {str(e)[:120]}")
    log(f"기존 영상 가져오기: {sub['name']} — {total}개 추가 (오래된 영상부터)")


def start_backfill(sub):
    threading.Thread(target=backfill, args=(sub,), daemon=True).start()


@app.post("/api/subs/{sid}/backfill")
def backfill_sub(sid: int):
    sub = q("SELECT * FROM subs WHERE id=?", (sid,))
    if not sub:
        raise HTTPException(404)
    start_backfill(sub[0])
    log(f"기존 영상 가져오는 중: {sub[0]['name']}")


@app.put("/api/subs/{sid}")
def update_sub(sid: int, body: Opts):  # 이후 다운로드부터 적용 (대기 중인 영상 포함)
    o, (kinds, iv, flt) = clean_opts(body), clean_sub(body)
    q("UPDATE subs SET quality=?, max_height=?, folder=?, kinds=?, interval_min=?, title_inc=?, title_exc=?, min_min=? WHERE id=?",
      (o["quality"], o["max_height"], o["folder"], kinds, iv, *flt, sid))


@app.get("/api/subs/{sid}/pattern")
def sub_pattern(sid: int):
    """이 구독의 생방송 녹화 시작 시각 → 요일(월=0) × 시간 칸별 방송 수. 이어서 녹화한 조각(-p2…)은 같은 방송이라 뺌"""
    grid = [[0] * 24 for _ in range(7)]
    rows = [r for r in q("SELECT video_id, started FROM jobs WHERE sub_id=? AND live=1 AND started IS NOT NULL", (sid,))
            if part_of(r["video_id"])[1] == 1]
    for r in rows:
        t = time.localtime(r["started"])
        grid[t.tm_wday][t.tm_hour] += 1
    return {"grid": grid, "n": len(rows)}


@app.post("/api/subs/check-all")
def check_all():
    q("UPDATE subs SET last_checked=0 WHERE enabled=1")  # 스케줄러가 채널 사이 간격을 두고 차례로 확인
    WAKE.set()


@app.post("/api/subs/{sid}/check")
def check_now(sid: int):
    q("UPDATE subs SET last_checked=0 WHERE id=?", (sid,))
    WAKE.set()


@app.post("/api/subs/{sid}/toggle")
def toggle_sub(sid: int):
    q("UPDATE subs SET enabled=1-enabled WHERE id=?", (sid,))


@app.delete("/api/subs/{sid}")
def delete_sub(sid: int):
    q("DELETE FROM subs WHERE id=?", (sid,))


CPU_PREV = [0, 0]  # 직전 /proc/stat (유휴, 전체) → 상태 화면 새로고침 사이의 CPU 사용률


def load():
    """서버 CPU·메모리 사용률(컨테이너에서도 서버 전체 값), 엔비디아 GPU 사용률(nvidia-smi 있을 때만)"""
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:]]
    idle, total = v[3] + v[4], sum(v)
    d_idle, d_total = idle - CPU_PREV[0], total - CPU_PREV[1]
    CPU_PREV[:] = [idle, total]
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, val = line.split(":")
            mem[k] = int(val.split()[0]) * 1024
    gpus = []
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,utilization.encoder,memory.used,memory.total",
                                "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.strip().splitlines():
                name, util, enc, used, tot = [x.strip() for x in line.split(",")]
                gpus.append({"name": name, "util": float(util), "enc": float(enc), "mem": float(used) * 2**20, "mem_total": float(tot) * 2**20})
        except (subprocess.SubprocessError, ValueError):
            pass
    return {"cpu": round(100 * (1 - d_idle / d_total), 1) if d_total > 0 else 0, "cores": os.cpu_count(),
            "mem": mem["MemTotal"] - mem["MemAvailable"], "mem_total": mem["MemTotal"], "gpus": gpus}


NEW_ERR = "error IS NOT NULL AND status IN ('error', 'done') AND COALESCE(err_seen, 0)=0"


class Ids(BaseModel):
    ids: list[int] | None = None  # 없으면 전부


@app.post("/api/errors/seen")
def errors_seen(body: Ids):
    """오류 확인 → 목록 카드·상태 화면의 오류 개수·최근 오류에서 숨김 (영상 정보에는 그대로). 다시 받으면 새 오류는 다시 보임"""
    ids = body.ids
    n = len(q(f"UPDATE jobs SET err_seen=1 WHERE {NEW_ERR}" + (f" AND id IN ({','.join('?' * len(ids))})" if ids else "") + " RETURNING id", tuple(ids or ())))
    return {"hidden": n}


@app.get("/api/status")
def status():
    s, disks, seen = settings(), [], set()
    for f in {"", s["folder"], s["youtube_folder"], s["chzzk_folder"]} | {r["folder"] or "" for r in q("SELECT folder FROM subs")}:
        p, free = free_space(safe_dir(f))
        if os.stat(p).st_dev not in seen:  # 같은 디스크는 한 번만
            seen.add(os.stat(p).st_dev)
            disks.append({"path": p, "total": shutil.disk_usage(p).total, "free": free,
                          "low": free < float(s["min_free_gb"]) * 1e9})  # 새 다운로드 멈추는 기준 아래
    return {
        "started": STARTED,
        "threads": {n: t.is_alive() for n, t in THREADS.items()},
        "paused_until": STATE["paused_until"] if paused() else 0,
        "pause_reason": STATE["pause_reason"],
        "counts": {r["status"]: r["n"] for r in q("SELECT status, COUNT(*) n FROM jobs GROUP BY status")},
        "active": [{"title": r["title"], **LIVE[r["id"]]} for r in q("SELECT id, title FROM jobs WHERE status='downloading'") if r["id"] in LIVE],
        "today": done_today(), "daily_limit": int(s["daily_limit"]),
        "concurrency": min(int(s["concurrency"]), MAX_PARALLEL),
        "chzzk_concurrency": min(int(s["chzzk_concurrency"]), MAX_PARALLEL),
        "live_concurrency": min(int(s["live_concurrency"]), MAX_PARALLEL),
        "chzzk_live_concurrency": min(int(s["chzzk_live_concurrency"]), MAX_PARALLEL),
        "compress_concurrency": int(s["compress_concurrency"]), "chzzk_compress_concurrency": int(s["chzzk_compress_concurrency"]),
        "disks": disks, "versions": VERSIONS, "cookies": {p: os.path.exists(f) for p, f in COOKIE_FILES.items()},
        "app_version": APP_VERSION, "updates": STATE.get("updates"),
        "hw": {HW_NAME[h]: sorted(c) for h, c in HW.items()},
        # 탭(플랫폼)마다 고른 화질의 코덱으로 실제 쓰일 장치 (예전엔 안 쓰는 공통 화질 기준이라 틀리게 보였음)
        "hw_use": {p: "압축 안 함" if (r := resolve(s, {k: s[f"{p}_{k}"] for k in OVERRIDES}))["codec"] == "none"
                   else f"{r['codec'].upper()} · {HW_NAME[encoder_for(r)]}" for p in PLATFORMS},
        "hw_why": {HW_NAME[h]: why for h, why in HW_WHY.items()}, "load": load(),
        "env": STATE.setdefault("env", host_env())[1],  # 실행 환경 (윈도우 · 맥 · 시놀로지 · 리눅스)
        # 확인(숨기기)하지 않은 오류만. '다시 받기 실패 → 기존 파일 보존' 처럼 완료인데 남은 안내도 포함
        "errors": q(f"SELECT id, title, error FROM jobs WHERE {NEW_ERR} ORDER BY id DESC LIMIT 10"),
        "errors_new": q(f"SELECT COUNT(*) n FROM jobs WHERE {NEW_ERR}")[0]["n"],
        # 채널별 받은 용량 (많은 순 10개). 구독 이름, 없으면(수동 다운로드) 영상 정보의 채널
        "usage": q("""SELECT COALESCE(s.name, json_extract(j.meta, '$.channel'), '기타') AS name, SUM(json_extract(j.meta, '$.size')) AS size,
                      COUNT(*) AS n FROM jobs j LEFT JOIN subs s ON s.id = j.sub_id WHERE j.status='done' AND json_extract(j.meta, '$.size') > 0
                      GROUP BY 1 ORDER BY 2 DESC LIMIT 10"""),
        "log": list(LOG)[:100],
    }


@app.get("/api/audit")
def audit():
    rows = q("SELECT * FROM audits ORDER BY id DESC LIMIT 7")
    for r in rows:
        r["result"] = json.loads(r["result"])
    if rows:  # 마지막 점검 뒤에 고쳐진 것(다시 받음·완료로 바뀜·목록에서 삭제)은 빼고 보여줌 (예전엔 다음 점검까지 그대로 남았음)
        res, now = rows[0]["result"], {j["id"]: j for j in q("SELECT id, status, filepath FROM jobs")}
        res["file_issues"] = [i for i in res.get("file_issues", []) if (j := now.get(i["id"])) and j["status"] == "done"
                              and not (i["issue"].startswith("파일 없음") and j["filepath"] and os.path.isfile(j["filepath"]))]
        res["gave_up"] = [g for g in res.get("gave_up", []) if (now.get(g["id"]) or {}).get("status") == "error"]
        gone_now = {r["id"] for r in q("SELECT id FROM jobs WHERE json_extract(meta, '$.source_gone') IS NOT NULL")}
        res["gone"] = [g for g in res.get("gone", []) if g["id"] in gone_now]
    return {"history": rows, "next": next_audit(audit_hours(settings())), "running": STATE.get("auditing", False)}


@app.post("/api/audit/run")
def audit_now():  # 구독 확인 스레드가 바로 실행
    STATE["audit_now"] = True
    WAKE.set()


@app.post("/api/jobs/{jid}/redownload")
def redownload(jid: int):  # 기존 파일과 딸린 파일(썸네일·자막·nfo) 지우고 다시 받기
    if jid in RECOMP:
        raise HTTPException(409, "나중에 압축 중입니다 (끝난 뒤 또는 압축 취소 후에)")
    j = q("SELECT filepath, live FROM jobs WHERE id=? AND status!='downloading'", (jid,))
    if j and j[0]["live"] and j[0]["filepath"] and os.path.isfile(j[0]["filepath"]):
        # 끝난 방송은 다시 녹화할 수 없음 → 지우면 녹화본만 사라짐 (예전엔 지운 뒤 '방송 중이 아님' 오류로 녹화를 잃었음)
        raise HTTPException(400, "생방송 녹화는 다시 받을 수 없습니다 (끝난 방송은 다시 녹화 안 됨 · 녹화 파일만 지워짐). 치지직 '다시보기' 주소로 받으세요")
    if j and j[0]["filepath"]:  # 이름 끝이 "[영상ID]" 라 다른 영상 파일과 겹치지 않음
        # 지우지 않고 비켜 둠: 스트리머가 원본을 지웠으면 다시 받기가 실패하는데, 먼저 지우면 영상을 영영 잃음
        for f in glob.glob(glob.escape(os.path.splitext(j[0]["filepath"])[0]) + ".*"):
            if not f.endswith(".keep"):
                os.replace(f, f + ".keep")
    q("UPDATE jobs SET status='queued', progress=0, error=NULL, cut=NULL WHERE id=? AND status!='downloading'", (jid,))


def keep_files(path):
    return glob.glob(glob.escape(os.path.splitext(path)[0]) + ".*.keep") if path else []


def restore_keep(path):
    """다시 받기가 실패·취소되면 비켜 둔 기존 파일을 되돌림 → 되돌린 영상 경로 (없으면 None)"""
    for f in keep_files(path):
        os.replace(f, f[:-5])
    return path if path and os.path.isfile(path) else None


LOGIN_COOKIES = {  # (쿠키 도메인, 로그인 상태를 뜻하는 쿠키 이름)
    "youtube": (("youtube.com", "google.com"), ("SID", "__Secure-3PSID", "LOGIN_INFO")),
    "chzzk": (("naver.com",), ("NID_AUT", "NID_SES")),
}


def login_info(p):
    f = COOKIE_FILES[p]
    if not os.path.exists(f):
        return {"saved": False}
    doms, keys = LOGIN_COOKIES[p]
    mine = [c for c in load_jar(f) if c.domain.lstrip(".").endswith(doms)]
    exp = [c.expires for c in mine if c.name in keys and c.expires]
    return {"saved": True, "count": len(mine), "login_cookie": any(c.name in keys for c in mine),
            "expires": min(exp) if exp else None, "updated": os.path.getmtime(f)}


class CookieText(BaseModel):
    text: str


@app.get("/api/login")
def login_status():
    return {p: login_info(p) for p in PLATFORMS}


@app.put("/api/login/{p}")
def save_login(p: str, body: CookieText):
    """브라우저에서 내보낸 cookies.txt 내용 저장 → 멤버십 전용·성인 인증 영상 다운로드"""
    if p not in PLATFORMS:
        raise HTTPException(404)
    text = body.text.strip()
    if not re.match(r"#( Netscape)? HTTP Cookie File", text):
        text = "# Netscape HTTP Cookie File\n" + text
    tmp = COOKIE_FILES[p] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    try:
        doms = LOGIN_COOKIES[p][0]
        if not any(c.domain.lstrip(".").endswith(doms) for c in load_jar(tmp)):
            raise ValueError(f"{' / '.join(doms)} 쿠키가 없습니다 (그 사이트에서 내보낸 파일인지 확인)")
    except Exception as e:
        os.remove(tmp)
        raise HTTPException(400, f"쿠키를 읽을 수 없습니다: {e}")
    os.replace(tmp, COOKIE_FILES[p])
    os.chmod(COOKIE_FILES[p], 0o600)  # 계정 로그인 정보라 소유자만 읽기
    log(f"{'유튜브' if p == 'youtube' else '치지직'} 로그인 쿠키 저장")
    return login_info(p)


@app.delete("/api/login/{p}")
def delete_login(p: str):
    # 예전 공용 cookies.txt 도 지움 — 남아 있으면 로그아웃해도 그 옛 쿠키로 계속 받아서 로그인 상태가 꼬임
    for f in (COOKIE_FILES[p], COOKIES) if p in PLATFORMS else ():
        if os.path.exists(f):
            os.remove(f)
    log(f"{'유튜브' if p == 'youtube' else '치지직'} 로그아웃 (저장된 쿠키 삭제)")


@app.post("/api/login/reset")
def reset_login():
    """로그인 완전 초기화: 두 사이트 쿠키 + 로그인용 브라우저 기록(구글·네이버 로그인 상태)까지 전부 삭제"""
    browser_stop()
    for f in (*COOKIE_FILES.values(), COOKIES):
        if os.path.exists(f):
            os.remove(f)
    shutil.rmtree(PROFILE, ignore_errors=True)
    log("로그인 완전 초기화 (쿠키·브라우저 기록 삭제)")


@app.post("/api/login/{p}/check")
def check_login(p: str):
    """실제로 로그인된 상태인지 확인 (치지직: 닉네임, 유튜브: 구독 피드를 열 수 있는지)"""
    if p == "chzzk":
        c = chzzk_api("https://comm-api.game.naver.com/nng_main/v1/user/getUserStatus")
        return {"ok": bool(c.get("loggedIn")), "name": c.get("nickname")}
    if not cookie_file("youtube.com"):
        return {"ok": False, "error": "저장된 쿠키가 없습니다"}
    try:
        with yt_dlp.YoutubeDL(base_opts(settings(), "youtube.com") | {"extract_flat": "in_playlist", "playlistend": 1}) as y:
            y.extract_info("https://www.youtube.com/feed/subscriptions", download=False)
        return {"ok": True}
    except yt_dlp.utils.DownloadError as e:
        return {"ok": False, "error": str(e).replace("ERROR: ", "")[:200]}


# ── 브라우저로 로그인: 컨테이너 안 크롬(가상 화면)을 noVNC 로 웹에서 조작 → 닫을 때 쿠키를 꺼내 저장 ──
PROFILE = os.path.join(CONFIG, "browser")
LOGIN_URL = {"youtube": "https://accounts.google.com/ServiceLogin?continue=https://www.youtube.com/",
             "chzzk": "https://nid.naver.com/nidlogin.login?url=https://chzzk.naver.com/"}
BROWSER = []  # 실행 중인 Xvfb, x11vnc, chromium


def browser_stop():
    for pr in reversed(BROWSER):  # 크롬 먼저 정상 종료해야 쿠키가 디스크에 기록됨
        pr.terminate()
        try:
            pr.wait(15)
        except subprocess.TimeoutExpired:
            pr.kill()
    BROWSER.clear()


@app.post("/api/login/{p}/browser")
def browser_open(p: str):
    if p not in PLATFORMS:
        raise HTTPException(404)
    if not shutil.which("chromium"):
        raise HTTPException(400, "이미지에 브라우저가 없습니다. 새 버전으로 다시 빌드하세요")
    browser_stop()
    for f in glob.glob(os.path.join(PROFILE, "Singleton*")):  # 컨테이너 재생성 때 남은 잠금 (호스트명이 바뀌어 크롬이 거부)
        os.remove(f)
    env = os.environ | {"DISPLAY": ":99"}
    BROWSER.append(subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"]))
    time.sleep(1)
    BROWSER.append(subprocess.Popen(["x11vnc", "-display", ":99", "-localhost", "-nopw", "-forever", "-shared",
                                     "-quiet", "-rfbport", "5999"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    BROWSER.append(subprocess.Popen(["chromium", "--no-sandbox", "--disable-dev-shm-usage", "--password-store=basic",
                                     f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
                                     "--test-type", "--hide-crash-restore-bubble",  # 경고·복원 안내 숨김
                                     "--remote-debugging-port=9222",  # 쿠키 읽기용 (컨테이너 안 127.0.0.1 만)
                                     "--window-position=0,0", "--window-size=1280,800", "--lang=ko", LOGIN_URL[p]],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    return {"url": "novnc/vnc.html?path=browser/ws&autoconnect=1&resize=scale&reconnect=1"}


async def cdp_cookies():
    """크롬 개발자 도구 프로토콜로 모든 쿠키 가져오기"""
    import websockets
    ver = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=5))
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=None) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
        return json.loads(await ws.recv())["result"]["cookies"]


@app.post("/api/login/{p}/browser/done")
def browser_done(p: str):
    """브라우저를 닫고 그 사이트 로그인 쿠키만 골라 저장 (브라우저를 닫아 둬야 유튜브가 쿠키를 바꾸지 않음)"""
    if p not in PLATFORMS:
        raise HTTPException(404)
    try:  # 켜진 브라우저에서 직접 읽기 → 디스크에 안 남는 세션 쿠키(네이버 '로그인 유지' 안 함)까지 포함
        cookies = asyncio.run(cdp_cookies())
    except Exception as e:
        raise HTTPException(400, f"브라우저가 열려 있지 않습니다. '브라우저 열기'부터 해주세요 ({e})")
    finally:
        browser_stop()
    doms, keys = LOGIN_COOKIES[p]
    mine = [c for c in cookies if c["domain"].lstrip(".").endswith(doms)]
    if not any(c["name"] in keys for c in mine):
        raise HTTPException(400, "로그인이 안 된 상태입니다. 브라우저에서 로그인을 끝낸 뒤 눌러주세요")
    out = YoutubeDLCookieJar(COOKIE_FILES[p] + ".tmp")  # 다 쓴 뒤 한 번에 바꿈 (읽는 중인 작업이 반쯤 쓴 파일을 보지 않게)
    for c in mine:
        out.set_cookie(http.cookiejar.Cookie(
            0, c["name"], c["value"], None, False, c["domain"], True, c["domain"].startswith("."), c["path"], True,
            c["secure"], int(c["expires"]) if c["expires"] > 0 else None, c["expires"] <= 0, None, None, {}))
    out.save(ignore_discard=True, ignore_expires=True)
    os.chmod(out.filename, 0o600)
    os.replace(out.filename, COOKIE_FILES[p])
    log(f"{'유튜브' if p == 'youtube' else '치지직'} 브라우저 로그인 → 쿠키 저장")
    return login_info(p)


@app.websocket("/novnc/browser/ws")  # noVNC 가 vnc.html 기준 상대 경로로 접속
async def browser_ws(ws: WebSocket):  # noVNC ↔ x11vnc 중계 (포트를 따로 열지 않으려고)
    await ws.accept(subprotocol="binary" if "binary" in ws.scope.get("subprotocols", []) else None)
    try:
        r, w = await asyncio.open_connection("127.0.0.1", 5999)
    except OSError:
        return await ws.close()

    async def up():
        while True:
            w.write(await ws.receive_bytes())
            await w.drain()

    async def down():
        while data := await r.read(65536):
            await ws.send_bytes(data)

    tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in tasks:
        t.cancel()
    w.close()


if os.path.isdir("/usr/share/novnc"):
    app.mount("/novnc", StaticFiles(directory="/usr/share/novnc"), name="novnc")


@app.post("/api/organize")
def organize():
    """이미 받은 영상도 영상별 폴더로 정리: 영상·썸네일·자막·nfo 를 '영상이름/' 폴더로 옮기고 경로 갱신"""
    moved = 0
    for j in q("SELECT id, filepath FROM jobs WHERE status='done' AND filepath IS NOT NULL"):
        p = j["filepath"]
        base, d = os.path.splitext(p)[0], os.path.dirname(p)
        # 없거나 이미 정리됨 (치지직은 폴더 "날짜 - 제목" 안에 파일 "날짜 - 제목 [ID]" → 폴더 이름이 파일 이름 앞부분)
        if not os.path.exists(p) or os.path.basename(base).startswith(os.path.basename(d)):
            continue
        new_dir = os.path.join(d, os.path.basename(base))
        os.makedirs(new_dir, exist_ok=True)
        for f in glob.glob(glob.escape(base) + ".*"):
            os.replace(f, os.path.join(new_dir, os.path.basename(f)))
        q("UPDATE jobs SET filepath=? WHERE id=?", (os.path.join(new_dir, os.path.basename(p)), j["id"]))
        moved += 1
    log(f"기존 영상 {moved}개를 영상별 폴더로 정리")
    return {"moved": moved}


@app.post("/api/updates/check")
def updates_check():
    check_updates()
    return STATE["updates"]


@app.post("/api/updates/apply")
def updates_apply():
    """컨테이너 재시작 → 시작 스크립트가 yt-dlp/deno 를 최신으로 설치. compose 의 restart: unless-stopped 필요.
    진행 중이던 다운로드는 재시작 후 이어받음."""
    log("업데이트를 위해 재시작합니다")
    threading.Timer(1, os._exit, (0,)).start()


@app.post("/api/resume")
def resume():
    STATE["paused_until"] = 0
    log("일시정지 수동 해제")


@app.get("/api/settings")
def get_settings():
    return settings()


# crf: H.264/H.265 는 51 까지, AV1 은 63 까지
NUMERIC = {"max_height": (0, 4320), "crf": (0, 63), "ratio": (10, 200), "concurrency": (1, MAX_PARALLEL), "chzzk_concurrency": (1, MAX_PARALLEL),
           "live_concurrency": (1, MAX_PARALLEL), "chzzk_live_concurrency": (1, MAX_PARALLEL),
           "compress_concurrency": (1, MAX_PARALLEL), "chzzk_compress_concurrency": (1, MAX_PARALLEL),
           "daily_limit": (1, 10000), "bot_cooldown_min": (1, 1440), "sleep_min": (0, 3600), "sleep_max": (0, 3600),
           "sleep_requests": (0, 60), "min_free_gb": (0, 100000), "login_refresh_days": (0, 365), "check_interval_min": (MIN_INTERVAL, 10080), "sub_fetch_limit": (1, 200)}
CHOICES = {"quality": {*QUALITY, "original", "custom"}, "codec": {"none", "h264", "h265", "av1"},
           "subtitles": {"all", "manual", "off"}, "hwaccel": {"auto", "cpu", "nvenc", "vaapi"}, "video_folder": {"0", "1"}, "stream_compress": {"0", "1"}, "auto_merge": {"0", "1"}, "sponsorblock": {"0", "1"}, "live_compress": {"off", "gpu", "gpu_cpu"},
           "preset": {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"}}


def bad_setting(k, v):
    """잘못된 값이면 이유, 정상이면 None. 숫자 칸이 비거나 글자가 들어가면 작업 스레드가 int() 에서 멈췄음."""
    if k in NUMERIC:
        lo, hi = NUMERIC[k]
        try:  # 소수를 쓰는 건 대기 시간 · 여유 공간뿐, 나머지는 정수만 (예전엔 '1.5' 가 통과돼 int() 에서 멈췄음)
            ok = lo <= float(v) <= hi and (k in ("sleep_min", "sleep_max", "sleep_requests", "min_free_gb") or v.isdigit())
        except ValueError:
            ok = False
        return None if ok else f"{lo}~{hi} 사이 숫자"
    if k in CHOICES and v not in CHOICES[k]:
        return "선택지에 없는 값"
    if k == "audio_bitrate" and not re.fullmatch(r"\d+[kK]?", v):
        return "예: 128k"
    if k == "rate_limit" and v and yt_dlp.utils.parse_bytes(v) is None:
        return "예: 10M (비우면 무제한)"
    if k == "audit_hours" and v and not re.fullmatch(r"\d{1,2}(,\d{1,2})*", v):
        return "예: 4,16"
    if k == "folder":
        try:
            safe_dir(v)
        except ValueError as e:
            return str(e)
    p, _, base = k.partition("_")
    if p in PLATFORMS and base in OVERRIDES + TAB_ONLY:  # 탭별 기본값: 비우면 공통 설정, 아니면 공통 항목과 같은 규칙
        return bad_setting(base, v) if v else None
    return None


SUB_COLS = ("url", "name", "avatar", "enabled", "quality", "max_height", "folder", "kinds", "interval_min", "title_inc", "title_exc", "min_min")


@app.get("/api/backup")
def backup():
    """설정·구독 목록을 파일로 (로그인 정보는 비밀번호와 같아서 넣지 않음, 받은 영상 목록도 제외)"""
    data = {"app": "chitube", "version": APP_VERSION, "settings": settings(),
            "subs": q(f"SELECT {','.join(SUB_COLS)} FROM subs ORDER BY id")}
    return Response(json.dumps(data, ensure_ascii=False, indent=1), media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename=chitube-backup-{time.strftime('%Y%m%d')}.json"})


def restore_sub(sub):
    """백업 파일의 구독 한 개 → 저장할 값 (잘못된 칸은 비우고, 채널 주소가 아니면 None). 백업 파일은 손으로 고칠 수 있어 그대로 믿지 않음
    (예전엔 목록 같은 값이 들어 있으면 서버 오류가 나고 그 앞의 이상한 구독이 반쯤 저장됐음)"""
    if not isinstance(sub, dict) or not isinstance(url := sub.get("url"), str):
        return None
    url = url.strip()
    if not (CHZZK_CH_RE.match(url) or re.match(r"https?://(www\.|m\.)?youtube\.com/", url)):
        return None
    txt = lambda v: v.strip() if isinstance(v, str) else ""
    o = {k: txt(sub.get(k)) for k in OVERRIDES}
    o = {k: (v if v and not bad_setting(k, v) else None) for k, v in o.items()}
    iv = txt(sub.get("interval_min"))
    return (url, txt(sub.get("name")) or url, txt(sub.get("avatar")) or None, 0 if sub.get("enabled") in (0, "0", False) else 1,
            o["quality"], o["max_height"], o["folder"], ",".join(k for k in KINDS if k in txt(sub.get("kinds")).split(",")) or "videos",
            iv if iv.isdigit() and int(iv) >= MIN_INTERVAL else None,
            txt(sub.get("title_inc")), txt(sub.get("title_exc")), txt(sub.get("min_min")) if txt(sub.get("min_min")).isdigit() else "")


@app.post("/api/restore")
def restore(body: dict):
    """백업 파일 불러오기: 설정은 덮어쓰고(잘못된 값은 건너뜀), 구독은 없는 채널만 추가"""
    if body.get("app") not in ("chitube", "docker_youtube"):  # docker_youtube = 예전 이름일 때의 백업
        raise HTTPException(400, "이 프로그램의 백업 파일이 아닙니다")
    raw = body.get("settings")
    sets = {k: str(v) for k, v in (raw if isinstance(raw, dict) else {}).items() if k in DEFAULTS and not bad_setting(k, str(v))}
    for k, v in sets.items():
        q("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))
    added = 0
    for sub in body.get("subs") if isinstance(body.get("subs"), list) else []:
        if row := restore_sub(sub):
            added += len(q(f"INSERT OR IGNORE INTO subs({','.join(SUB_COLS)}) VALUES({','.join('?' * len(SUB_COLS))}) RETURNING id", row))
    log(f"백업 불러옴: 설정 {len(sets)}개, 구독 {added}개 추가")
    return {"settings": len(sets), "subs": added}


@app.put("/api/settings")
def put_settings(body: dict):
    body = {k: str(v).strip() for k, v in body.items() if k in DEFAULTS}
    errors = {k: why for k, v in body.items() if (why := bad_setting(k, v))}
    if errors:
        raise HTTPException(400, "잘못된 설정: " + ", ".join(f"{k} ({why})" for k, why in errors.items()))
    for k, v in body.items():
        if k in DEFAULTS:
            q("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, str(v).strip()))
    return settings()

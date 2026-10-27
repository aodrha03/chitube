import io
import json
from main import BOT_RE, DEFAULTS, ffmpeg_cmd, next_check, normalize, resolve, safe_dir, sub_urls

sub = {"url": "https://www.youtube.com/@abc/videos", "kinds": "videos,shorts,streams"}
assert sub_urls(sub) == [f"https://www.youtube.com/@abc/{k}" for k in ("videos", "shorts", "streams")]
assert sub_urls({"url": "https://www.youtube.com/@abc", "kinds": None}) == ["https://www.youtube.com/@abc/videos"]
assert sub_urls({"url": "https://www.youtube.com/playlist?list=PL1", "kinds": "shorts"}) == ["https://www.youtube.com/playlist?list=PL1"]
assert next_check({"last_checked": 1000, "interval_min": "5"}, DEFAULTS) == 1000 + 30 * 60  # 최소 30분 강제
assert next_check({"last_checked": 1000, "interval_min": ""}, DEFAULTS) == 1000 + 360 * 60
assert BOT_RE.search("ERROR: Sign in to confirm you're not a bot") and BOT_RE.search("HTTP Error 429: Too Many Requests")
assert not BOT_RE.search("Video unavailable. This video is private")

assert normalize("https://www.youtube.com/@abc") == "https://www.youtube.com/@abc/videos"
assert normalize("https://www.youtube.com/@abc/") == "https://www.youtube.com/@abc/videos"
assert normalize("https://www.youtube.com/@abc/shorts") == "https://www.youtube.com/@abc/shorts"
assert normalize(" https://www.youtube.com/watch?v=x ") == "https://www.youtube.com/watch?v=x"

s = {"codec": "h265", "crf": "28", "preset": "slow", "audio_bitrate": "128k"}
c = ffmpeg_cmd("a.mkv", "a.mp4", s)
assert c[-1] == "a.mp4" and "libx265" in c and "hvc1" in c and c[c.index("-crf") + 1] == "28"
assert "hvc1" not in ffmpeg_cmd("a.mkv", "a.mp4", s | {"codec": "h264"})
c = ffmpeg_cmd("a.mkv", "a.mp4", s | {"ratio": "70"}, vbit=1_000_000)
assert c[c.index("-maxrate") + 1] == "700000" and c[c.index("-bufsize") + 1] == "1400000"
assert "-maxrate" not in ffmpeg_cmd("a.mkv", "a.mp4", s | {"ratio": "70"})  # 길이 모르면(라이브) 상한 없음
c = ffmpeg_cmd("a.ts", "a.mp4", s | {"codec": "copy"}, tags={"title": "라이브", "description": None})
assert c[c.index("-metadata") + 1] == "title=라이브" and c.count("-metadata") == 1  # 빈 태그는 빼고 넣음
from main import ver
assert ver("2026.08.19") == (2026, 8, 19) and ver("deno 2.9.7 (stable, aarch64)") == (2, 9, 7)
assert ver("v2.10.0") > ver("deno 2.9.7") and ver("2026.10.1") > ver("2026.08.19")
assert c[c.index("-c:v") + 1] == "copy" and "-crf" not in c and c[c.index("-c:a") + 1] == "aac"

# 기본 → 유튜버 → 영상 순서로 덮어쓰기, 빈 값은 무시
r = resolve(DEFAULTS, {"quality": "small", "max_height": "720", "folder": "키즈"}, {"max_height": ""})
assert (r["codec"], r["crf"], r["ratio"], r["max_height"], r["folder"]) == ("h265", "26", "70", "720", "키즈")
r = resolve(DEFAULTS, {"quality": "original", "max_height": "720"})
assert (r["codec"], r["max_height"]) == ("none", "0")  # 원본 = 최고 해상도 + 재압축 없음
r = resolve(DEFAULTS | {"quality": "custom", "codec": "h264", "crf": "20"})
assert (r["codec"], r["crf"]) == ("h264", "20")

# 저장 경로: 상대 경로 → 다운로드 폴더 아래, '/' 로 시작 → 서버 절대 경로 (컨테이너의 /host 아래)
import tempfile, main as _m
_m.HOST = tempfile.mkdtemp()  # compose 의 서버 루트 연결(/:/host) 대신
assert safe_dir("") == "/downloads" and safe_dir("a/b") == "/downloads/a/b"
assert safe_dir("/volume1/video/YouTube") == _m.HOST + "/volume1/video/YouTube"
for bad in ("..", "../etc", "a/../../x", "/../etc", "/a/../../etc"):
    try:
        safe_dir(bad)
        raise AssertionError(bad)
    except ValueError:
        pass
# 점검: 놓친 영상 판정 (유튜브 목록은 최신순)
from datetime import datetime
from main import audit_due, find_missing, next_audit
ids = ["n1", "n2", "a", "n3", "b", "old1", "old2"]
assert find_missing(ids, {"a", "b"}, 15) == ["n1", "n2", "n3"]  # 받은 것 중 가장 오래된 b 보다 새로운 것만
assert find_missing(ids, set(), 3) == ["n1", "n2", "a"]          # 기록 없으면 최신 limit 개
assert find_missing(ids, set(ids), 15) == []
now = datetime(2026, 10, 18, 10, 0)
four = datetime(2026, 10, 18, 4, 0).timestamp()
assert audit_due([4, 16], 0, now) and audit_due([4, 16], four - 1, now)
assert not audit_due([4, 16], four, now) and not audit_due([], 0, now)
assert next_audit([4, 16], now) == datetime(2026, 10, 18, 16, 0).timestamp()
assert next_audit([4], now) == datetime(2026, 10, 19, 4, 0).timestamp() and next_audit([], now) is None
# Plex 에피소드 번호: 같은 날 영상은 순번으로 구분, 다시 받으면 기존 번호 유지
import tempfile
from main import episode_code
d = tempfile.mkdtemp()
assert episode_code(d, "20180425", "A") == "s2018e042501"
for n in ("s2018e042501 - 2018-04-25 - x [A]", "s2018e042502 - 2018-04-25 - y [B]", "s2018e060501 - 2018-06-05 - z [C]"):
    open(f"{d}/채널 - {n}.mp4", "w").close()
assert episode_code(d, "20180425", "B") == "s2018e042502"   # 다시 받기
assert episode_code(d, "20180425", "N") == "s2018e042503"   # 같은 날 새 영상
assert episode_code(d, "20180605", "N") == "s2018e060502" and episode_code(d, "20181231", "N") == "s2018e123101"
# 설정 검증: 잘못된 값이 저장되면 작업 스레드가 int() 에서 멈췄음
from main import bad_setting
assert bad_setting("daily_limit", "") and bad_setting("daily_limit", "abc") and bad_setting("concurrency", "21")
assert not bad_setting("daily_limit", "100") and not bad_setting("sleep_requests", "0.5")
assert bad_setting("codec", "vp9") and bad_setting("audio_bitrate", "abc") and not bad_setting("audio_bitrate", "128k")
assert bad_setting("rate_limit", "fast") and not bad_setting("rate_limit", "") and not bad_setting("rate_limit", "10M")
assert bad_setting("folder", "../x") and not bad_setting("folder", "YouTube") and not bad_setting("audit_hours", "")
assert bad_setting("audit_hours", "새벽") and not bad_setting("audit_hours", "4,16") and not bad_setting("unknown", "x")
# 자막: 직접 만든 자막 전부 + 자동 생성 원어(겹치면 생략), 자동 번역은 안 받음
from main import subtitle_langs
raw = {"subtitles": {"ko": [], "en": [], "live_chat": []}, "automatic_captions": {"en-orig": [], "fr": [], "de": []}, "language": "en"}
assert subtitle_langs(raw, "all") == ["ko", "en"] and subtitle_langs(raw, "manual") == ["ko", "en"] and subtitle_langs(raw, "off") == []
assert subtitle_langs({"automatic_captions": {"ja-orig": [], "ko": []}}, "all") == ["ja-orig"]
assert subtitle_langs({"automatic_captions": {"ja": [], "ko": []}, "language": "ja"}, "all") == ["ja"]
assert subtitle_langs({"automatic_captions": {"ja": []}, "language": "ko"}, "all") == [] and subtitle_langs({}, "all") == []
# nfo: Jellyfin 이 읽는 형식
import os, xml.etree.ElementTree as ET
from main import write_nfo
d = tempfile.mkdtemp(); os.makedirs(f"{d}/채널/Season 2023")
v = f"{d}/채널/Season 2023/채널 - s2023e040102 - 2023-04-01 - 제목 & <특수> [abc].mp4"
write_nfo(v, {"channel": "채널", "upload_date": "20230401", "description": "설명 <b>", "duration": 125}, "제목 & <특수>", "abc")
e = ET.parse(v[:-4] + ".nfo").getroot()
assert (e.find("title").text, e.find("season").text, e.find("episode").text, e.find("aired").text, e.find("plot").text, e.find("runtime").text, e.find("uniqueid").text) == ("제목 & <특수>", "2023", "40102", "2023-04-01", "설명 <b>", "2", "abc")
assert ET.parse(f"{d}/채널/tvshow.nfo").getroot().find("title").text == "채널"
# 하드웨어 인코딩: 장치별 명령, 없으면 CPU
import main
from main import encoder_for
base = DEFAULTS | {"codec": "h265", "crf": "26", "ratio": "70"}
c = ffmpeg_cmd("a", "b.mp4", base, vbit=1_000_000, hw="nvenc")
assert "hevc_nvenc" in c and c[c.index("-cq") + 1] == "26" and c[c.index("-maxrate") + 1] == "700000" and c[c.index("-preset") + 1] == "p4"
c = ffmpeg_cmd("a", "b.mp4", base | {"codec": "h264"}, vbit=1_000_000, hw="vaapi")
assert c.index("-vaapi_device") < c.index("-i") and "h264_vaapi" in c and c[c.index("-b:v") + 1] == "700000" and "hvc1" not in c
assert c[c.index("-vf") + 1] == "format=nv12,hwupload"
assert "-qp" in ffmpeg_cmd("a", "b.mp4", base, hw="vaapi")  # 길이 모르는 라이브는 고정 화질
assert "libx265" in ffmpeg_cmd("a", "b.mp4", base) and "-vaapi_device" not in ffmpeg_cmd("a", "b.mp4", base)
main.HW.clear()
assert encoder_for(base | {"hwaccel": "auto"}) == "cpu" and encoder_for(base | {"hwaccel": "nvenc"}) == "cpu"  # GPU 없는 제온
main.HW.update({"nvenc": {"h264"}, "vaapi": {"h264", "h265"}})
assert encoder_for(base | {"hwaccel": "auto"}) == "vaapi"           # 엔비디아가 h265 못 하면 인텔
assert encoder_for(base | {"hwaccel": "auto", "codec": "h264"}) == "nvenc"
assert encoder_for(base | {"hwaccel": "cpu"}) == "cpu"
main.HW.clear()
# 영상별 폴더 / 치지직 주소 판별
from main import outtmpl, show_dir, CHZZK_CH_RE, sub_urls as su
t = outtmpl("s2026e101601", True)
assert t.count("[%(id)s]") == 2 and t.endswith(".%(ext)s") and "/Season %(upload_date>%Y)s/" in t  # 폴더 + 파일
assert outtmpl("x", False).count("[%(id)s]") == 1
c = outtmpl("", True, chzzk=True)  # 치지직: 스트리머/날짜 - 제목/날짜 - 제목 [ID].mp4 (시즌 없음, ID 는 파일에만)
assert "Season" not in c and c.count("[%(id)s]") == 1 and c.count("%(upload_date>%Y-%m-%d)s - %(fname_title).100B") == 2
# aria2c 제어 파일: 조각 1MB × 10개(전체 9.5MB) 중 0·1·9번 완료 → 받은 양 3MB
import struct
ctl = os.path.join(tempfile.mkdtemp(), "x.aria2")
with open(ctl, "wb") as fh:
    fh.write(struct.pack(">HII", 1, 0, 0) + struct.pack(">IQQI", 1 << 20, 9_961_472, 0, 2) + bytes([0b11000000, 0b01000000]) + struct.pack(">I", 0))
assert main.aria2_done(ctl) == (3 << 20, 9_961_472), main.aria2_done(ctl)
from main import plain_name  # 파일 이름용: 이모지(ZWJ·국기·피부색 포함)만 빼고 한글·기호는 그대로
assert plain_name("고양이 😂🐱 영상 👨‍👩‍👧 🇰🇷 Part 1!") == "고양이 영상 Part 1!", plain_name("고양이 😂🐱 영상 👨‍👩‍👧 🇰🇷 Part 1!")
assert plain_name("🔥🔥") == "제목 없음" and plain_name("( ܸ ⩌⩊⩌ ܸ )") == "( ܸ ⩌⩊⩌ ܸ )"
assert show_dir("/d/Ch/Season 2026/N [a]/N [a].mp4") == "/d/Ch" and show_dir("/d/Ch/Season 2026/N [a].mp4") == "/d/Ch"
cid = "7ce8032370ac5121dcabce7bad375ced"
for u in (f"https://chzzk.naver.com/{cid}", f"https://chzzk.naver.com/live/{cid}", f"https://chzzk.naver.com/{cid}/videos"):
    assert CHZZK_CH_RE.match(u).group(1) == cid
assert not CHZZK_CH_RE.match("https://chzzk.naver.com/video/15297533")  # 다시보기 하나는 yt-dlp 가 직접
assert su({"url": f"https://chzzk.naver.com/{cid}", "kinds": "videos,shorts,streams"}) == [
    f"https://chzzk.naver.com/{cid}", f"https://chzzk.naver.com/{cid}/live"]  # 숏츠 없음
assert bad_setting("video_folder", "2") and not bad_setting("video_folder", "1")
# 탭(플랫폼)별 기본값: 공통 → 탭 → 채널 → 영상 순, 비우면 다음 단계로
from main import platform_of
assert platform_of("https://chzzk.naver.com/video/1") == "chzzk" and platform_of("https://youtu.be/x") == "youtube"
r = resolve(DEFAULTS, {"quality": "", "max_height": "720", "folder": "/volume1/video/Chzzk"}, {"folder": ""}, {})
assert (r["max_height"], r["folder"]) == ("720", "/volume1/video/Chzzk")
assert bad_setting("chzzk_folder", "") is None and bad_setting("chzzk_quality", "nope") and bad_setting("youtube_max_height", "abc")
assert not bad_setting("youtube_folder", "/volume1/video/YouTube") and bad_setting("youtube_folder", "/../etc")
print("ok")

# 봇 차단 신호 → 작업은 대기열로 되돌리고 전체 일시정지 (실제 유튜브 대신 가짜 YoutubeDL 로 확인)
import os, tempfile, main, yt_dlp
main.DB = os.path.join(tempfile.mkdtemp(), "t.db")
main.init_db()
main.q("INSERT OR REPLACE INTO settings(key, value) VALUES('min_free_gb', '0')")  # 테스트하는 PC 디스크가 거의 차 있어도 작업 스레드가 멈추지 않게


class Blocked:
    def __init__(self, *a): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def extract_info(self, *a, **k): raise yt_dlp.utils.DownloadError("ERROR: [youtube] x: Sign in to confirm you're not a bot")


real, yt_dlp.YoutubeDL = yt_dlp.YoutubeDL, Blocked
main.q("INSERT INTO jobs(video_id,url,title,opts) VALUES('x','u','t','{}')")
job = main.claim(0, 1, 1)
main.run_job(job, main.job_settings(job))
assert main.q("SELECT status FROM jobs")[0]["status"] == "queued" and main.paused()
# 플랫폼별 동시 개수: 치지직 한도 1 이면 두 번째 치지직은 못 가져오고, 유튜브 한도 0 이면 유튜브도 안 가져옴
main.q("INSERT INTO jobs(video_id,url,title,opts) VALUES('c1','https://chzzk.naver.com/video/1','c','{}'),"
       "('c2','https://chzzk.naver.com/video/2','c','{}')")
assert main.claim(0, 0, 1)["video_id"] == "c1" and main.claim(0, 0, 1) is None
assert main.claim(0, 1, 1)["video_id"] == "x" and main.claim(0, 1, 1) is None and main.claim(0, 1, 2)["video_id"] == "c2"
main.q("DELETE FROM jobs WHERE video_id IN ('c1','c2')")
main.q("UPDATE jobs SET status='queued' WHERE video_id='x'")
main.STATE["paused_until"] = 0
main.q("INSERT INTO subs(url,name) VALUES('https://www.youtube.com/@x','x')")
main.check_sub(main.q("SELECT * FROM subs")[0], main.settings() | {"sub_fetch_limit": "1"})
assert main.paused() and "not a bot" in main.q("SELECT last_error FROM subs")[0]["last_error"]
yt_dlp.YoutubeDL = real
print("bot ok")

# 기존 영상 전부 받기: 목록(최신순)을 뒤집어 넣어 오래된 영상이 먼저 받아짐
real_list, main.list_entries = main.list_entries, lambda u, limit=None: ([{"id": "new"}, {"id": "old"}], "x", "videos")
main.backfill(main.q("SELECT * FROM subs")[0])
assert [r["video_id"] for r in main.q("SELECT video_id FROM jobs WHERE video_id IN ('new','old') ORDER BY id")] == ["old", "new"]
main.list_entries = real_list
print("backfill ok")

# 일괄 처리: 다시 받기는 오류·취소만 (완료된 건 파일을 지우므로 제외), 삭제는 받는 중 제외
main.q("INSERT INTO jobs(video_id,url,title,opts,status) VALUES('be','u','t','{}','error'),('bd','u','t','{}','done'),('bg','u','t','{}','downloading')")
ids = {r["video_id"]: r["id"] for r in main.q("SELECT id, video_id FROM jobs WHERE video_id IN ('be','bd','bg')")}
assert main.bulk(main.Bulk(ids=list(ids.values()), action="retry"))["done"] == 1
st = {r["video_id"]: r["status"] for r in main.q("SELECT video_id, status FROM jobs WHERE video_id IN ('be','bd','bg')")}
assert st == {"be": "queued", "bd": "done", "bg": "downloading"}, st
assert main.bulk(main.Bulk(ids=list(ids.values()), action="delete"))["done"] == 2
assert [r["video_id"] for r in main.q("SELECT video_id FROM jobs WHERE video_id IN ('be','bd','bg')")] == ["bg"]
assert main.jobs(status="error", search="zz-없는제목")["jobs"] == []
print("bulk ok")

# 대기열 페이지: 받을 순서(먼저 넣은 것부터), 페이지마다 per 개
main.q("INSERT INTO jobs(video_id,url,title,opts) VALUES('q1','u','t','{}'),('q2','u','t','{}'),('q3','u','t','{}')")
order = [r["video_id"] for r in main.q("SELECT video_id FROM jobs WHERE status='queued' AND title LIKE '%t%' ORDER BY id")]
p1, p2 = (main.jobs(status="queued", search="t", per=2, page=n) for n in (1, 2))
assert [j["video_id"] for j in p1["jobs"]] == order[:2] and [j["video_id"] for j in p2["jobs"]] == order[2:4]
assert p1["total"] == len(order)
# AV1 고효율: SVT-AV1 10비트, 프리셋 이름 → 숫자 (fast = 8, 메모리 적게)
a = main.ffmpeg_cmd("a.mkv", "a.mp4", main.resolve(main.settings(), {"quality": "av1"}))
assert "libsvtav1" in a and a[a.index("-preset") + 1] == "8" and a[a.index("-crf") + 1] == "46" and "yuv420p10le" in a and "hvc1" not in a
# 맨 앞으로: 나중에 넣은 영상이라도 먼저 받음
last = main.q("SELECT id, video_id FROM jobs WHERE status='queued' ORDER BY id DESC LIMIT 1")[0]
main.bulk(main.Bulk(ids=[last["id"]], action="top"))
assert main.claim(0, 99, 99)["video_id"] == last["video_id"]
# 퀵싱크 AV1 고정 화질: qp 는 0~255 단위 → CRF 46 은 184
_, v = main.encode_args(main.resolve(main.settings(), {"quality": "av1"}), 0, "vaapi")
assert v[v.index("-qp") + 1] == "184" and "av1_vaapi" in v
# 유튜브 하루 한도는 치지직 완료를 세지 않음
n = main.done_today()
main.q("INSERT INTO jobs(video_id,url,title,opts,status,finished) VALUES('cz-done','https://chzzk.naver.com/video/9','t','{}','done',?)", (main.time.time(),))
assert main.done_today() == n
# 끊긴 생방송: 녹화분 보존(.part → 완성 이름), 방송이 이어지면 '-p2' 로 이어서 녹화, 직접 중지하면 안 이어짐
real_out, main.OUT = main.OUT, tempfile.mkdtemp()
part = os.path.join(main.OUT, "a", "녹화 [chzzk-live-7].mp4.part")
os.makedirs(os.path.dirname(part))
with open(part, "wb") as fh:
    fh.write(b"\0" * 2_000_000)
assert main.keep_partial("chzzk-live-7", {"folder": ""}) == part[:-5] and os.path.exists(part[:-5])
main.OUT = real_out
real_live, main.chzzk_live = main.chzzk_live, lambda cid: [{"id": "chzzk-live-7"}]
main.q("INSERT INTO jobs(video_id,url,title,opts,status,live) VALUES('chzzk-live-7','https://chzzk.naver.com/live/" + "a" * 32 + "','방송','{}','error',1)")
lj = main.q("SELECT * FROM jobs WHERE video_id='chzzk-live-7'")[0]
main.STOPPED.add(lj["id"])
main.continue_live(lj)
assert not main.q("SELECT 1 FROM jobs WHERE video_id='chzzk-live-7-p2'")  # 직접 중지 → 안 이어짐
main.continue_live(lj)
assert main.q("SELECT live, status FROM jobs WHERE video_id='chzzk-live-7-p2'") == [{"live": 1, "status": "queued"}]
main.continue_live(main.q("SELECT * FROM jobs WHERE video_id='chzzk-live-7-p2'")[0])
assert main.q("SELECT 1 FROM jobs WHERE video_id='chzzk-live-7-p3'")  # p2 도 끊기면 p3
assert main.q("SELECT cut FROM jobs WHERE video_id='chzzk-live-7'")[0]["cut"]  # 끊긴 시각 기록 → 화면 표시
assert [p["video_id"] for p in main.job(lj["id"])["parts"]] == ["chzzk-live-7", "chzzk-live-7-p2", "chzzk-live-7-p3"]
main.chzzk_live = real_live
# 성인 인증 실패: 자동 재시도 한도로 막고 이어서 녹화도 안 함
main.q("INSERT INTO jobs(video_id,url,title,opts,status,live,error) VALUES('chzzk-live-8','https://chzzk.naver.com/live/" + "a" * 32 + "','성인','{}','error',1,?)", (main.ADULT_MSG,))
main.continue_live(main.q("SELECT * FROM jobs WHERE video_id='chzzk-live-8'")[0])
assert not main.q("SELECT 1 FROM jobs WHERE video_id='chzzk-live-8-p2'")
assert main.ADULT_RE.search("ERROR: [chzzk:video] 1: Failed to download MPD manifest: HTTP Error 401: Unauthorized")
# 생방송 녹화로 받은 방송의 다시보기는 건너뜀 (liveOpenDate == 녹화 때 openDate)
main.q("UPDATE jobs SET live_open='2026-10-21 15:48:03', status='done' WHERE video_id='chzzk-live-7'")  # 완료된 녹화만
real_api, main.chzzk_api = main.chzzk_api, lambda path: {"liveOpenDate": "2026-10-21 15:48:03" if path.endswith("/901") else "2026-10-20 10:00:00"}
assert main.recorded_replay("a" * 32, {"videoNo": 901, "videoType": "REPLAY"})
assert not main.recorded_replay("a" * 32, {"videoNo": 902, "videoType": "REPLAY"})
assert not main.recorded_replay("a" * 32, {"videoNo": 903, "videoType": "UPLOAD"})
assert not main.recorded_replay("b" * 32, {"videoNo": 904, "videoType": "REPLAY"})  # 녹화 없는 채널은 상세 조회 안 함
main.chzzk_api = real_api
# 쿠키: yt-dlp 엔 복사본만 줌 → 끝날 때 다시 써도 원본(다시 로그인한 새 쿠키)은 그대로
ck = main.COOKIE_FILES["youtube"]
had = os.path.exists(ck)
if not had:
    with open(ck, "w") as fh:
        fh.write("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tnew\n")
o = main.base_opts(main.settings(), "https://www.youtube.com/watch?v=x")
assert o["cookiefile"] != ck
with open(o["cookiefile"], "w") as fh:
    fh.write("옛 쿠키")
assert "옛 쿠키" not in open(ck).read()
if not had:
    os.remove(ck)
# 생방송 녹화하면서 압축은 TS 로 써서 hvc1 태그를 빼야 ffmpeg 가 거부하지 않음
assert "hvc1" not in main.encode_args(main.resolve(main.settings(), {"quality": "standard"}), 0, "nvenc", ts=True)[1]
assert "hvc1" in main.encode_args(main.resolve(main.settings(), {"quality": "standard"}), 0, "nvenc")[1]
# 봇 감지로 쉬는 중엔 유튜브 다운로드 막힘 (확인하면 force 로 재개)
main.STATE["paused_until"] = main.time.time() + 60
try:
    main.download(main.Url(url="https://www.youtube.com/watch?v=zzz"))
    raise AssertionError("막혀야 함")
except main.HTTPException as e:
    assert e.status_code == 409
main.STATE["paused_until"] = 0
# 이어서 녹화 파일 ID: 유튜브 ID(11자) 자체가 '-p숫자'로 끝나도 원래 ID 로 봄
assert main.part_of("chzzk-live-7-p3") == ("chzzk-live-7", 3) and main.part_of("chzzk-live-7") == ("chzzk-live-7", 1)
assert main.part_of("abcdefgh-p1") == ("abcdefgh-p1", 1) and main.part_of("abcdefgh-p1-p2") == ("abcdefgh-p1", 2)
assert main.low_disk(main.settings() | {"min_free_gb": "99999999"}) and not main.low_disk(main.settings() | {"min_free_gb": "0"})
l = main.load()
assert 0 <= l["cpu"] <= 100 and l["mem_total"] > l["mem"] > 0
try:  # 미리보기는 받는 중인 영상만
    main.job_preview(main.q("SELECT id FROM jobs WHERE status='done' LIMIT 1")[0]["id"]); raise AssertionError
except main.HTTPException as e:
    assert e.status_code == 404
# 녹화 조각 합치기: 두 조각 → 1번째 자리에 한 파일, 나머지 조각 파일·목록 정리
md = tempfile.mkdtemp()
for i in (1, 2):
    main.subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=160x90:d=2", "-f", "lavfi", "-i", "sine=d=2",
                         "-c:v", "libx264", "-c:a", "aac", "-shortest", f"{md}/rec{i}.mp4"], check=True)
for vid, i in (("chzzk-live-9", 1), ("chzzk-live-9-p2", 2)):
    main.q("INSERT INTO jobs(video_id,url,title,opts,status,live,filepath,started) VALUES(?,?,?,?,?,?,?,?)",
           (vid, "https://chzzk.naver.com/live/" + "a" * 32, "합치기", "{}", "done", 1, f"{md}/rec{i}.mp4", i))
mj = main.q("SELECT id FROM jobs WHERE video_id='chzzk-live-9'")[0]["id"]
assert main.merge_parts(mj) == {"merged": 2}
assert 3.8 < main.probe_streams(f"{md}/rec1.mp4")[1] < 4.3 and not os.path.exists(f"{md}/rec2.mp4")
assert not main.q("SELECT 1 FROM jobs WHERE video_id='chzzk-live-9-p2'")
# 정렬: 허용 목록 밖 값은 기본 정렬 (SQL 에 그대로 넣지 않음)
assert main.jobs(sort="title; DROP TABLE jobs")["jobs"] and main.jobs(sort="size")["jobs"]
# 백업 → 복원: 구독 추가, 설정 적용, 잘못된 값은 건너뜀, 다른 파일은 거부
bk = json.loads(main.backup().body)
assert "settings" in bk and "subs" in bk
r = main.restore({"app": "docker_youtube", "settings": {"crf": "30", "concurrency": "abc"},
                  "subs": [{"url": "https://www.youtube.com/@restore_test", "name": "복원"}]})
assert r == {"settings": 1, "subs": 1} and main.settings()["crf"] == "30"
assert main.q("SELECT enabled FROM subs WHERE url='https://www.youtube.com/@restore_test'")[0]["enabled"] == 1
try:
    main.restore({"settings": {}}); raise AssertionError
except main.HTTPException as e:
    assert e.status_code == 400
# 미리보기: 받는 중인 파일을 다시 인코딩 없이(같은 화질) 5초 이상 잘라 줌
pd = os.path.join(main.OUT, "pv_unit"); os.makedirs(pd, exist_ok=True)
main.subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x180:d=30", "-c:v", "libx264", "-g", "30",
                     "-movflags", "+frag_keyframe+empty_moov", "-f", "mp4", f"{pd}/t [pvunit01234].mp4.part"], check=True)
main.q("INSERT INTO jobs(video_id,url,title,opts,status) VALUES('pvunit01234','https://www.youtube.com/watch?v=pvunit01234','t',?,'downloading')",
       (json.dumps({"folder": "pv_unit"}),))
clip = main.job_preview(main.q("SELECT id FROM jobs WHERE video_id='pvunit01234'")[0]["id"]).body
assert len(clip) > 10_000 and b"avc1" in clip[:3000]  # 다시 인코딩 없이 원본 코덱 그대로
main.shutil.rmtree(pd)
# 지워진 파일은 file_ok=False, 저장된 썸네일 파일은 /thumb 로 (치지직 생방송 썸네일 주소 만료 대비)
td = tempfile.mkdtemp()
open(f"{td}/v [thumbtest01].mp4", "wb").close(); open(f"{td}/v [thumbtest01].jpg", "wb").write(b"jpg")
main.q("INSERT INTO jobs(video_id,url,title,opts,status,filepath) VALUES('thumbtest01','u','t','{}','done',?)", (f"{td}/v [thumbtest01].mp4",))
tj = main.q("SELECT id FROM jobs WHERE video_id='thumbtest01'")[0]["id"]
assert main.job(tj)["file_ok"] and main.job_thumb(tj).path.endswith(".jpg")
os.remove(f"{td}/v [thumbtest01].mp4")
assert not main.job(tj)["file_ok"]
# 예전 버그로 '오류'가 된 녹화(파일 있음)는 시작할 때 완료로, 덮어써진 시작 시각은 생성 시각으로
open(f"{td}/r [chzzk-live-77].mp4", "wb").close()
main.q("INSERT INTO jobs(video_id,url,title,opts,status,live,filepath,created,started,cut,error) VALUES('chzzk-live-77','u','t','{}','error',1,?,100,500,150,'x')",
       (f"{td}/r [chzzk-live-77].mp4",))
main.init_db()
assert main.q("SELECT status, started, error FROM jobs WHERE video_id='chzzk-live-77'") == [{"status": "done", "started": 100, "error": None}]
# 형식이 다른 조각(원본 H.264 + 압축본 H.265): 그냥은 409, reencode 면 다시 압축해서 한 파일로
for i, cv in ((1, "libx264"), (2, "libx265")):
    main.subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=s={'160x90' if i == 1 else '320x180'}:d=2", "-f", "lavfi", "-i", "sine=d=2",
                         "-c:v", cv, "-c:a", "aac", "-shortest", f"{md}/mix{i}.mp4"], check=True)
for vid, i in (("chzzk-live-88", 1), ("chzzk-live-88-p2", 2)):
    main.q("INSERT INTO jobs(video_id,url,title,opts,status,live,filepath,started) VALUES(?,?,?,?,?,?,?,?)",
           (vid, "https://chzzk.naver.com/live/" + "a" * 32, "섞임", "{}", "done", 1, f"{md}/mix{i}.mp4", i))
xj = main.q("SELECT id FROM jobs WHERE video_id='chzzk-live-88'")[0]["id"]
try:
    main.merge_parts(xj); raise AssertionError
except main.HTTPException as e:
    assert e.status_code == 409
assert main.merge_parts(xj, reencode=True) == {"started": True}
for _ in range(120):
    if not main.MERGING: break
    main.time.sleep(0.5)
st, dur = main.probe_streams(f"{md}/mix1.mp4")
assert [x[:2] for x in st] == [("video", "hevc"), ("audio", "aac")] and st[0][2:] == (160, 90) and 3.8 < dur < 4.3, (st, dur)
assert not os.path.exists(f"{md}/mix2.mp4") and not main.q("SELECT 1 FROM jobs WHERE video_id='chzzk-live-88-p2'")
# 끝난 생방송 녹화는 '다시 받기'로 지워지지 않음 (다시 녹화 불가 → 녹화만 사라졌음)
rec = f"{td}/live [chzzk-live-99].mp4"; open(rec, "wb").close()
main.q("INSERT INTO jobs(video_id,url,title,opts,status,live,filepath) VALUES('chzzk-live-99','u','t','{}','done',1,?)", (rec,))
lj99 = main.q("SELECT id FROM jobs WHERE video_id='chzzk-live-99'")[0]["id"]
try:
    main.redownload(lj99); raise AssertionError
except main.HTTPException as e:
    assert e.status_code == 400
assert os.path.exists(rec) and main.q("SELECT status FROM jobs WHERE id=?", (lj99,))[0]["status"] == "done"
assert main.bulk(main.Bulk(ids=[lj99], action="retry")) == {"done": 0}
# 받는 중 예상 못 한 오류 → 그 영상이 '다운로드 중'으로 멈추지 않고 '오류' (점검이 다시 시도)
main.add_entries([{"id": "crashtest01", "url": "https://www.youtube.com/watch?v=crashtest01", "title": "t"}], "videos")
main.q("UPDATE jobs SET pri=99 WHERE video_id='crashtest01'")
main.q("INSERT OR REPLACE INTO settings VALUES('concurrency','20')")  # 앞 테스트가 남긴 '받는 중' 영상 때문에 동시 개수가 꽉 차지 않게
real_run, main.run_job = main.run_job, lambda job, s, dl=None: (_ for _ in ()).throw(RuntimeError("boom"))
cj, cev = main.claim(0, 20, 20), main.threading.Event()
assert cj["video_id"] == "crashtest01"
main.job_thread(cj, main.job_settings(cj), cev)  # 받기 스레드가 오류를 기록하고 작업 스레드를 깨움 (작업 스레드는 죽지 않고 다음 영상으로)
assert cev.is_set()
main.run_job = real_run
assert main.q("SELECT status, error FROM jobs WHERE video_id='crashtest01'") == [{"status": "error", "error": "내부 오류: boom"}]
# 재시작으로 남은 합치기 임시 파일 정리
mt = os.path.join(main.OUT, "x.mp4.merging.mp4"); open(mt, "wb").close()
main.sweep_temp()
assert not os.path.exists(mt)
# 점검 결과: 그 뒤에 고쳐진 것(완료로 바뀜·파일 다시 생김)은 목록에서 빠짐
main.q("INSERT INTO audits(started, finished, result) VALUES(?,?,?)", (main.time.time(), main.time.time(), json.dumps(
    {"subs": [], "missing_added": 0, "files_checked": 1, "retried": 0,
     "file_issues": [{"id": tj, "title": "t", "issue": "파일 없음 (삭제/이동됨)"}, {"id": lj99, "title": "t", "issue": "파일 없음 (삭제/이동됨)"}],
     "gave_up": [{"id": lj99, "title": "t", "error": "x"}, {"id": main.q("SELECT id FROM jobs WHERE video_id='crashtest01'")[0]["id"], "title": "c", "error": "x"}]})))
ar = main.audit()["history"][0]["result"]
assert [i["id"] for i in ar["file_issues"]] == [tj]  # tj 는 파일이 지워진 채, lj99 는 파일 있음 → 빠짐
assert [g["title"] for g in ar["gave_up"]] == ["c"]  # lj99 는 완료 → 빠짐, crashtest01 은 아직 오류
# 원본이 지워진 영상을 '다시 받기' → 실패해도 기존 파일은 그대로 (예전엔 먼저 지워서 영영 잃었음)
kd = os.path.join(main.OUT, "keep_unit"); os.makedirs(kd, exist_ok=True)
kv = f"{kd}/v [keepunit001].mp4"
open(kv, "wb").write(b"old"); open(f"{kd}/v [keepunit001].jpg", "wb").write(b"jpg")
main.q("INSERT INTO jobs(video_id,url,title,opts,status,filepath) VALUES('keepunit001','https://www.youtube.com/watch?v=keepunit001','t',?,'done',?)",
       (json.dumps({"folder": "keep_unit"}), kv))
kj = main.q("SELECT id FROM jobs WHERE video_id='keepunit001'")[0]["id"]
main.redownload(kj)
assert not os.path.exists(kv) and os.path.exists(kv + ".keep")  # 비켜 둠
real_attempt = main.yt_dlp.YoutubeDL.extract_info
main.yt_dlp.YoutubeDL.extract_info = lambda self, *a, **k: (_ for _ in ()).throw(main.yt_dlp.utils.DownloadError("ERROR: [youtube] keepunit001: Video unavailable. This video has been removed by the uploader"))
main.run_job(main.claim(0, 20, 20) if False else main.q("SELECT * FROM jobs WHERE id=?", (kj,))[0], main.job_settings(main.q("SELECT * FROM jobs WHERE id=?", (kj,))[0]))
main.yt_dlp.YoutubeDL.extract_info = real_attempt
r = main.q("SELECT status, filepath, error FROM jobs WHERE id=?", (kj,))[0]
assert r["status"] == "done" and r["filepath"] == kv and open(kv, "rb").read() == b"old" and "기존 파일 그대로" in r["error"], r
assert os.path.exists(f"{kd}/v [keepunit001].jpg") and not main.keep_files(kv)
# 다시 받기 대기 중에 목록에서 삭제해도 파일은 되돌아옴
main.redownload(kj); main.delete_job(kj)
assert os.path.exists(kv) and not main.keep_files(kv)
main.shutil.rmtree(kd)
# 백업 복원: 손으로 고친 이상한 값은 건너뜀 (예전엔 서버 오류 + 이상한 구독이 반쯤 저장됨)
n0 = main.q("SELECT COUNT(*) n FROM subs")[0]["n"]
r = main.restore({"app": "chitube", "settings": ["x"], "subs": [{"url": 123}, {"url": ["a"]}, "문자", None, {"url": "file:///etc/passwd"},
                  {"url": "https://www.youtube.com/@fuzz_ok", "quality": "evil", "folder": "../../etc", "max_height": "abc", "kinds": 5, "interval_min": "1", "enabled": "x"}]})
assert r == {"settings": 0, "subs": 1} and main.q("SELECT COUNT(*) n FROM subs")[0]["n"] == n0 + 1
assert main.q("SELECT quality, folder, max_height, kinds, interval_min, enabled FROM subs WHERE url='https://www.youtube.com/@fuzz_ok'") == \
    [{"quality": None, "folder": None, "max_height": None, "kinds": "videos", "interval_min": None, "enabled": 1}]
# 오류 숨기기: 확인한 오류는 상태 화면·카드에서 빠지고, 다시 받으면(claim) 새 오류로 다시 보임
main.q("INSERT INTO jobs(video_id,url,title,opts,status,error) VALUES('errseen0001','https://www.youtube.com/watch?v=errseen0001','t','{}','error','x')")
ej = main.q("SELECT id FROM jobs WHERE video_id='errseen0001'")[0]["id"]
new = lambda: [r["id"] for r in main.q(f"SELECT id FROM jobs WHERE {main.NEW_ERR}")]
assert ej in new() and main.errors_seen(main.Ids(ids=[ej])) == {"hidden": 1} and ej not in new()
assert main.q("SELECT err_seen FROM jobs WHERE id=?", (ej,))[0]["err_seen"] == 1
main.q("UPDATE jobs SET status='queued', pri=999 WHERE id=?", (ej,))
assert main.claim(0, 99, 99)["id"] == ej and main.q("SELECT err_seen FROM jobs WHERE id=?", (ej,))[0]["err_seen"] == 0
main.q("UPDATE jobs SET status='error', error='y' WHERE id=?", (ej,))
assert ej in new() and main.errors_seen(main.Ids()) ["hidden"] >= 1 and not new()
# 방송 시작 직후 '방송 중이 아님' → 같은 작업을 다시 (오류·새 파일로 튀지 않음), 6번 넘으면 오류
main.q("INSERT INTO jobs(video_id,url,title,opts,status,live) VALUES('chzzk-live-555','https://chzzk.naver.com/live/" + "c" * 32 + "','시작','{}','downloading',1)")
sj = main.q("SELECT * FROM jobs WHERE video_id='chzzk-live-555'")[0]
real = (main.yt_dlp.YoutubeDL.extract_info, main.live_now, main.time.sleep)
main.yt_dlp.YoutubeDL.extract_info = lambda self, *a, **k: (_ for _ in ()).throw(main.yt_dlp.utils.DownloadError("ERROR: [chzzk:live] ccc: The channel is not currently live"))
main.live_now, main.time.sleep = (lambda job: True), (lambda sec: None)
main.run_job(sj, main.job_settings(sj))
assert main.q("SELECT status, retries, error FROM jobs WHERE id=?", (sj["id"],)) == [{"status": "queued", "retries": 1, "error": None}]
main.continue_live(main.q("SELECT * FROM jobs WHERE id=?", (sj["id"],))[0])
assert not main.q("SELECT 1 FROM jobs WHERE video_id='chzzk-live-555-p2'")  # 새 파일로 튀지 않음
main.q("UPDATE jobs SET status='downloading', retries=6 WHERE id=?", (sj["id"],))
main.run_job(main.q("SELECT * FROM jobs WHERE id=?", (sj["id"],))[0], main.job_settings(sj))
assert main.q("SELECT status FROM jobs WHERE id=?", (sj["id"],))[0]["status"] == "error"
main.yt_dlp.YoutubeDL.extract_info, main.live_now, main.time.sleep = real
# 녹화 멈춤 감시: 90초 안 커지면 정상 종료('q'), 그래도 30초 더 멈추면 강제 종료, 다시 커지면 초기화
calls = []
real_stop, real_procs, real_kill = main.stop_recording, main.procs, main.os.kill
main.stop_recording = lambda vid: calls.append(("q", vid))
main.procs = lambda exe, vid: [(4242, [])]
main.os.kill = lambda pid, sig: calls.append(("kill", pid, sig))
st = {}
main.stall_check(sj["id"], 1000, st); st["t"] -= main.STALL_SEC + 1
main.stall_check(sj["id"], 1000, st)
assert calls == [("q", "chzzk-live-555")] and st["acted"] == 1
main.stall_check(sj["id"], 1000, st); assert len(calls) == 1  # 30초 안 됨
st["t"] -= 31
main.stall_check(sj["id"], 1000, st)
assert calls[-1] == ("kill", 4242, 9) and st["acted"] == 2
main.stall_check(sj["id"], 2000, st); assert st["acted"] == 0  # 다시 커지면 처음부터
main.stop_recording, main.procs, main.os.kill = real_stop, real_procs, real_kill
# 녹화분 보존: 파일이 잠겨 이름을 못 바꿔도 .part 그대로 보존 (잃지 않음)
kd = tempfile.mkdtemp(); pf = f"{kd}/rec [chzzk-live-556].mp4.part"; open(pf, "wb").write(b"\0" * 2_000_000)
real_rep, real_sleep = main.os.replace, main.time.sleep
main.os.replace = lambda a, b: (_ for _ in ()).throw(PermissionError("locked")); main.time.sleep = lambda s: None
real_out, main.OUT = main.OUT, kd
assert main.keep_partial("chzzk-live-556", {"folder": ""}) == pf and os.path.exists(pf)
main.os.replace, main.time.sleep, main.OUT = real_rep, real_sleep, real_out
# 실행 환경 구분 (윈도우 · 맥 · 시놀로지 · 리눅스) → 하드웨어 가속 안 되는 이유를 환경에 맞게
def env_of(kernel, *paths, osrel=None):
    d = tempfile.mkdtemp(); pv = os.path.join(d, "version"); open(pv, "w").write(kernel)
    h = os.path.join(d, "host")
    for p in paths:
        os.makedirs(os.path.join(h, os.path.dirname(p)), exist_ok=True)
        if not p.endswith("/"):  # 'Users/' 같은 폴더는 위에서 만들어짐, 나머지는 빈 파일
            open(os.path.join(h, p), "w").close()
    if osrel:
        os.makedirs(os.path.join(h, "etc"), exist_ok=True); open(os.path.join(h, "etc/os-release"), "w").write(osrel)
    real, main.HOST = main.HOST, h
    try:
        return main.host_env(pv)
    finally:
        main.HOST = real
assert env_of("Linux version 5.15.167.4-microsoft-standard-WSL2")[0] == "windows"
assert env_of("Linux version 6.8.0-117-generic", "Users/")[0] == "mac"
assert env_of("Linux version 4.4.302+", "etc/synoinfo.conf")[0] == "synology"
assert env_of("Linux version 6.1.0-18-amd64", osrel='PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n') == ("linux", "리눅스 · Debian GNU/Linux 12 (bookworm)")
assert all(set(v) == {"vaapi", "nvenc"} for v in main.NO_HW_WHY.values())
# 원본 사라짐: 목록의 가장 오래된 받은 영상보다 새로운데 목록에 없으면 표시, 다시 나오면 지움, 더 오래된 건 판단 안 함
main.q("INSERT INTO subs(url, name) VALUES('https://www.youtube.com/@gone_test', 'g')")
gsid = main.q("SELECT id FROM subs WHERE url='https://www.youtube.com/@gone_test'")[0]["id"]
for vid, d in (("goneA000001", "20261001"), ("goneB000001", "20261005"), ("goneC000001", "20260901")):
    main.q("INSERT INTO jobs(video_id,url,title,opts,status,sub_id,kind,meta) VALUES(?,?,?,?,?,?,?,?)",
           (vid, "u", vid, "{}", "done", gsid, "videos", json.dumps({"upload_date": d})))
g = main.mark_source_gone(gsid, "videos", {"goneA000001"})
assert [x["title"] for x in g] == ["goneB000001"]  # C 는 목록 범위보다 오래돼 판단하지 않음
gone_of = lambda v: json.loads(main.q("SELECT meta FROM jobs WHERE video_id=?", (v,))[0]["meta"]).get("source_gone")
assert gone_of("goneB000001") and not gone_of("goneC000001")
assert any(j["gone"] for j in main.jobs(sub=gsid)["jobs"])  # 목록 카드에 표시 칸
assert main.mark_source_gone(gsid, "videos", {"goneA000001", "goneB000001"}) == [] and not gone_of("goneB000001")  # 다시 나오면 지움
# 코어 2~3개면 x265 멀티스레드를 직접 켬, 많으면 x265 기본값 그대로
real_aff = main.os.sched_getaffinity
main.os.sched_getaffinity = lambda pid: {0, 1}
assert "pools=2:frame-threads=2" in main.encode_args(main.settings() | {"codec": "h265"})[1]
main.os.sched_getaffinity = lambda pid: set(range(112))
assert "-x265-params" not in main.encode_args(main.settings() | {"codec": "h265"})[1]
main.os.sched_getaffinity = real_aff
# 치튜브 새 버전 알림: GitHub 최신 릴리스가 더 높으면 '새 버전 있음'
class FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
real_open = main.urllib.request.urlopen
main.urllib.request.urlopen = lambda req, timeout=0: FakeResp(json.dumps({"tag_name": "99.0.0", "info": {"version": "0"}}).encode())
main.check_updates()
ct = next(i for i in main.STATE["updates"]["items"] if i["name"] == "치튜브")
assert ct["outdated"] and ct["latest"] == "99.0.0" and ct["url"].endswith("/releases/latest")
main.urllib.request.urlopen = lambda req, timeout=0: FakeResp(json.dumps({"tag_name": "1.0", "info": {"version": "0"}}).encode())
main.check_updates()
assert not next(i for i in main.STATE["updates"]["items"] if i["name"] == "치튜브")["outdated"]  # 태그 "1.0" 은 1.0.x 보다 낮음
main.urllib.request.urlopen = real_open
# 구독 필터: 포함 단어 하나라도 · 제외 단어 없음 · 최소 길이(분). 길이 모르는 영상(생방송)은 통과
f = {"title_inc": "노래, 커버", "title_exc": "쇼츠", "min_min": "3"}
assert main.sub_match(f, {"title": "오늘의 노래", "duration": 300}) and not main.sub_match(f, {"title": "잡담", "duration": 300})
assert not main.sub_match(f, {"title": "노래 쇼츠", "duration": 300}) and not main.sub_match(f, {"title": "커버", "duration": 60})
assert main.sub_match(f, {"title": "커버 생방송"}) and main.sub_match({"title_inc": None, "title_exc": "", "min_min": ""}, {"title": "x"})
main.q("INSERT INTO subs(url, name, title_exc) VALUES('https://www.youtube.com/@flt_test', 'f', '예고')")
fsid = main.q("SELECT id FROM subs WHERE url='https://www.youtube.com/@flt_test'")[0]["id"]
assert main.add_entries([{"id": "fltA0000001", "url": "u", "title": "본편"}, {"id": "fltB0000001", "url": "u", "title": "예고편"}], "videos", fsid) == 1
assert main.add_entries([{"id": "fltB0000001", "url": "u", "title": "예고편"}], "videos") == 1  # 수동 다운로드는 필터 없음
# 방송 시간 패턴: 이어서 녹화한 조각은 같은 방송이라 한 번만
ts = main.time.mktime((2026, 10, 19, 21, 5, 0, 0, 0, -1))  # 월요일 21시
for vid in ("chzzk-live-901", "chzzk-live-901-p2"):
    main.q("INSERT INTO jobs(video_id,url,title,opts,live,sub_id,started) VALUES(?,?,?,?,1,?,?)", (vid, "u", "방송", "{}", fsid, ts))
pt = main.sub_pattern(fsid)
assert pt["n"] == 1 and pt["grid"][0][21] == 1
# 채널별 용량: 구독 이름으로 묶음
main.q("UPDATE jobs SET status='done', meta=? WHERE video_id='fltA0000001'", (json.dumps({"size": 5e9}),))
assert {"name": "f", "size": 5e9, "n": 1} in main.status()["usage"]
assert main.bad_setting("auto_merge", "2") and not main.bad_setting("sponsorblock", "1")
# 방송 끝 → 조각이 여러 개면 자동 합치기 (설정으로 끔), 조각 하나면 안 함
calls, real_ln, real_mp = [], main.live_now, main.merge_parts
main.live_now, main.merge_parts = (lambda j: False), (lambda jid: calls.append(jid))
lj = {"id": 99901, "video_id": "chzzk-live-5-p2", "title": "끝난 방송"}
main.continue_live(lj)
main.continue_live(lj | {"id": 99902, "video_id": "chzzk-live-5"})
main.q("INSERT OR REPLACE INTO settings(key, value) VALUES('auto_merge', '0')")
main.continue_live(lj | {"id": 99903})
assert calls == [99901]
main.live_now, main.merge_parts = real_ln, real_mp
main.q("DELETE FROM settings WHERE key='auto_merge'")
# 녹화 썸네일: 옆에 .jpg 가 없으면 녹화 장면으로
td = tempfile.mkdtemp()
main.subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-t", "2", f"{td}/rec.mp4"], check=True)
main.frame_thumb(f"{td}/rec.mp4", 2)
assert os.path.getsize(f"{td}/rec.jpg") > 0
# 치지직 다시보기 미리보기: aria2c 가 앞·뒤를 동시에 받는 중 → 받아 둔 가장 뒤쪽 구간에서 (파일 끝 빈칸 말고)
def aria2_file(bits, piece=1 << 20):
    total = len(bits) * piece
    bm = bytes(int("".join(map(str, (bits + [0] * 7)[i:i + 8])), 2) for i in range(0, len(bits), 8))
    b = b"\x00\x01" + b"\x00" * 4 + (0).to_bytes(4, "big") + piece.to_bytes(4, "big") + total.to_bytes(8, "big") + b"\x00" * 8 + len(bm).to_bytes(4, "big") + bm
    f = os.path.join(tempfile.mkdtemp(), "v.mp4.aria2")
    open(f, "wb").write(b)
    return f
af = aria2_file([1] * 30 + [0] * 40 + [1] * 20 + [0] * 10)  # 100MB, 100초 → 조각 1개 = 1초
assert main.aria2_done(af) == (50 << 20, 100 << 20)
assert main.aria2_seek(af, 100) == 75  # 70~90초 받아 둠 → 끝(90초)에서 15초 전
assert main.aria2_seek(aria2_file([1] * 30 + [0] * 60 + [1] * 5 + [0] * 5), 100) == 15  # 뒤쪽 5초는 짧아 앞 구간 끝에서
assert main.aria2_seek(aria2_file([0] * 10), 100) is None
# 녹화하면서 압축: 방송 해상도가 바뀌어도 출력 크기 · 소리 형식 고정
_, enc = main.encode_args(main.settings() | {"codec": "h265"}, hw="cpu", ts=True, size=(1920, 1080))
assert enc[enc.index("-vf") + 1] == "scale=1920:1080,format=yuv420p" and enc[enc.index("-ar") + 1] == "48000"
_, enc = main.encode_args(main.settings() | {"codec": "h265"}, hw="vaapi", ts=True, size=(1280, 720))
assert enc[enc.index("-vf") + 1] == "scale=1280:720,format=nv12,hwupload" and enc.count("-vf") == 1
assert "-vf" not in main.encode_args(main.settings() | {"codec": "h265"})[1] and "-ar" not in main.encode_args(main.settings() | {"codec": "h265"})[1]
# '지금 확인'은 구독 확인 스레드를 바로 깨움
main.WAKE.clear(); main.check_now(fsid); assert main.WAKE.is_set()
main.WAKE.clear(); main.audit_now(); assert main.WAKE.is_set()
main.STATE.pop("audit_now", None)
# 방송이 끝나 오류로 멈춘 녹화 → 정상 종료처럼 mp4 정리 (원본 그대로 설정이면 다시 압축 안 함)
td = tempfile.mkdtemp()
main.subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-f", "lavfi", "-i", "sine", "-t", "3",
                     "-c:v", "libx264", "-c:a", "aac", "-f", "mpegts", f"{td}/rec.mp4"], check=True)
main.q("INSERT INTO jobs(video_id,url,title,opts,live) VALUES('chzzk-live-9077','u','끝난 방송','{}',1)")
kj = main.q("SELECT * FROM jobs WHERE video_id='chzzk-live-9077'")[0]
out = main.finish_kept(kj, f"{td}/rec.mp4", main.settings() | {"codec": "none"})
assert out == f"{td}/rec.mp4" and main.probe_streams(out)[1] > 2 and os.path.exists(f"{td}/rec.jpg")
assert json.loads(main.q("SELECT meta FROM jobs WHERE id=?", (kj["id"],))[0]["meta"])["size"] == os.path.getsize(out)
assert b"ftyp" in open(out, "rb").read(16)  # MPEG-TS → mp4
# 생방송 녹화로 받은 방송: 방송 전체를 담았으면 다시보기 건너뜀, 일부만(늦게 발견 · 끊김) 담았으면 다시보기도 받음
cz = "c" * 32
main.q("INSERT INTO jobs(video_id,url,title,opts,live,status,live_open,meta) VALUES('chzzk-live-9088',?,'방송','{}',1,'done','2026-10-20 20:00:00',?)",
       (f"https://chzzk.naver.com/live/{cz}", json.dumps({"duration": 3000})))
real_api, main.chzzk_api = main.chzzk_api, lambda path: {"liveOpenDate": "2026-10-20 20:00:00"}
assert main.recorded_replay(cz, {"videoNo": 501, "videoType": "REPLAY", "duration": 3100})
assert not main.recorded_replay(cz, {"videoNo": 502, "videoType": "REPLAY", "duration": 7200})
main.chzzk_api = real_api
# 끝난 작업에 진행 표시 스레드가 늦게 남긴 '녹화 중' 상태는 무시 → 오류 항목도 취소 · 목록에서 삭제가 됨
main.q("INSERT INTO jobs(video_id,url,title,opts,status,live,error) VALUES('stale000001','u','t','{}','error',1,'x')")
sj = main.q("SELECT id FROM jobs WHERE video_id='stale000001'")[0]["id"]
main.LIVE[sj] = {"status": "recording", "progress": 0}
assert main.job(sj)["status"] == "error" and next(j for j in main.jobs()["jobs"] if j["id"] == sj)["status"] == "error"
main.cancel(sj)
assert sj not in main.CANCEL  # 끝난 작업엔 취소 신호를 남기지 않음 (예전엔 다시 받으면 바로 취소됐음)
main.delete_job(sj)
assert not main.q("SELECT 1 FROM jobs WHERE id=?", (sj,))
main.LIVE.pop(sj, None)
# 압축 단계는 다운로드 개수에서 빠짐 → 압축 중에도 다음 영상을 받음. 압축 개수는 플랫폼별
main.q("UPDATE jobs SET status='done' WHERE status IN ('queued','downloading')")
main.q("INSERT INTO jobs(video_id,url,title,opts,status) VALUES('compA000001','https://www.youtube.com/watch?v=compA000001','a','{}','downloading'),"
       "('compB000001','https://www.youtube.com/watch?v=compB000001','b','{}','queued')")
ca = main.q("SELECT id FROM jobs WHERE video_id='compA000001'")[0]["id"]
assert main.claim(0, 1, 1) is None  # 유튜브 1개 받는 중 → 다음 거 안 가져감
ev = main.threading.Event()
main.compress_turn(ca, "youtube", ev)
assert ev.is_set() and ca in main.COMP_RUN
assert main.claim(0, 1, 1)["video_id"] == "compB000001"  # 앞의 것이 압축 단계라 다음 영상 시작
cb = main.q("SELECT id FROM jobs WHERE video_id='compB000001'")[0]["id"]
waiter = main.threading.Thread(target=main.compress_turn, args=(cb, "youtube"))
waiter.start(); waiter.join(3)
assert waiter.is_alive() and main.LIVE[cb].get("waiting")  # 압축 칸(1개)이 차서 기다림
main.compress_done(ca); waiter.join(5)
assert not waiter.is_alive() and cb in main.COMP_RUN
main.compress_done(cb)
for x in (ca, cb):
    main.LIVE.pop(x, None)
main.q("UPDATE jobs SET status='done' WHERE id IN (?, ?)", (ca, cb))
# 압축 방식은 탭(플랫폼)별, 비우면 공통
main.q("INSERT OR REPLACE INTO settings(key, value) VALUES('chzzk_live_compress', 'off')")
assert main.job_settings({"url": "https://chzzk.naver.com/live/x", "sub_id": None, "opts": "{}"})["live_compress"] == "off"
assert main.job_settings({"url": "https://www.youtube.com/watch?v=x", "sub_id": None, "opts": "{}"})["live_compress"] == main.DEFAULTS["live_compress"]
main.q("DELETE FROM settings WHERE key='chzzk_live_compress'")
assert main.bad_setting("youtube_stream_compress", "2") and not main.bad_setting("youtube_stream_compress", "")
# 치지직: 녹화 중(또는 방금 끝나 이어서 녹화할 참)인 채널은 방송 ID 가 바뀌어도 새 녹화를 또 만들지 않음
rc = "d" * 32
main.q("INSERT INTO jobs(video_id,url,title,opts,status,live) VALUES('chzzk-live-955501',?,'방송','{}','downloading',1)", (f"https://chzzk.naver.com/live/{rc}",))
assert main.recording(rc) and not main.recording("e" * 32)
main.q("UPDATE jobs SET status='done', finished=? WHERE video_id='chzzk-live-955501'", (main.time.time() - 120,))
assert not main.recording(rc)
# 나중에 압축: 완료된 원본(mkv) → 고른 화질의 mp4, 작아질 때만 바꿈
td = tempfile.mkdtemp()
main.subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25", "-t", "2", "-c:v", "libx264", "-qp", "0",
                     f"{td}/big [recomp00001].mkv"], check=True)
main.q("INSERT INTO jobs(video_id,url,title,opts,status,filepath,meta) VALUES('recomp00001','https://www.youtube.com/watch?v=recomp00001','r','{}','done',?,'{}')",
       (f"{td}/big [recomp00001].mkv",))
rj = main.q("SELECT id FROM jobs WHERE video_id='recomp00001'")[0]["id"]
assert main.recompress(main.Recompress(ids=[rj], quality="small"))["queued"] == 1
for _ in range(60):
    if rj not in main.RECOMP:
        break
    main.time.sleep(1)
r = main.q("SELECT filepath, meta FROM jobs WHERE id=?", (rj,))[0]
assert r["filepath"].endswith(".mp4") and os.path.isfile(r["filepath"]) and not os.path.exists(f"{td}/big [recomp00001].mkv")
assert json.loads(r["meta"])["compressed"]["codec"] == "h265"
try:
    main.recompress(main.Recompress(ids=[rj], quality="original")); assert False
except main.HTTPException:
    pass
# 녹화가 끝나 압축 단계인 녹화는 '녹화 중'으로 안 셈 → 그동안 시작한 새 방송도 녹화
main.q("UPDATE jobs SET status='downloading', finished=NULL WHERE video_id='chzzk-live-955501'")
cid_ = main.q("SELECT id FROM jobs WHERE video_id='chzzk-live-955501'")[0]["id"]
assert main.recording(rc)
main.COMPRESSING[cid_] = "chzzk"
assert not main.recording(rc)
main.compress_done(cid_)
main.q("UPDATE jobs SET status='done', finished=0 WHERE id=?", (cid_,))
# 끝난 녹화를 압축했는데 안 작아지면 MPEG-TS 그대로 두지 않고 mp4 로
main.subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-t", "2", "-c:v", "libx264", "-crf", "40",
                     "-f", "mpegts", f"{td}/rec2.mp4"], check=True)
main.q("INSERT INTO jobs(video_id,url,title,opts,live) VALUES('chzzk-live-9078','https://chzzk.naver.com/live/x','끝난 방송','{}',1)")
kj2 = main.q("SELECT * FROM jobs WHERE video_id='chzzk-live-9078'")[0]
out = main.finish_kept(kj2, f"{td}/rec2.mp4", main.settings() | {"codec": "h265", "crf": "0", "ratio": "200", "preset": "ultrafast"})
assert b"ftyp" in open(out, "rb").read(16)
main.compress_done(kj2["id"]); main.LIVE.pop(kj2["id"], None)
# ffmpeg 오류 출력이 많아도(깨진 녹화본) 멈추지 않고 끝남
err = main.run_ffmpeg(["sh", "-c", "head -c 300000 /dev/zero | tr '\\0' x >&2; exit 1"], 0, -1)
assert err and len(err) <= 3000
assert main.run_ffmpeg(["true"], 0, -1) is None
# 썸네일 만들기가 실패해도 예외로 받기를 망치지 않음
main.frame_thumb(f"{td}/없는파일.mp4")
# 코덱 비교: 재시작으로 압축을 못 한 원본은 다시 압축, 이미 압축본이면 그대로
assert main.same_codec(f"{td}/rec2.mp4", "h264") and not main.same_codec(f"{td}/rec2.mp4", "h265")
# 방송 상태 확인이 잠깐 실패하면 다시 확인 (바로 '방송 끝'으로 보지 않음)
calls_, real_cl = [], main.chzzk_live
def flaky(cid):
    calls_.append(1)
    if len(calls_) < 2:
        raise OSError("일시 오류")
    return [{"id": "x"}]
main.chzzk_live, real_sleep, main.time.sleep = flaky, main.time.sleep, lambda x: None
assert main.live_now({"video_id": "chzzk-live-1", "url": "https://chzzk.naver.com/live/" + "a" * 32, "title": "t"}) and len(calls_) == 2
main.chzzk_live, main.time.sleep = real_cl, real_sleep
# 나중에 압축 중엔 다시 받기 · 목록에서 삭제 막음
main.RECOMP.add(rj)
for f_ in (main.redownload, main.delete_job):
    try:
        f_(rj); assert False
    except main.HTTPException as e:
        assert e.status_code == 409
assert main.bulk(main.Bulk(ids=[rj], action="delete"))["done"] == 0
main.RECOMP.discard(rj)
# 이어 녹화는 구독 필터 없이 (방송 중 제목이 제외 단어로 바뀌어도)
main.q("INSERT INTO subs(url, name, title_exc) VALUES('https://chzzk.naver.com/" + "f" * 32 + "', 'fx', '휴방')")
fx = main.q("SELECT id FROM subs WHERE name='fx'")[0]["id"]
main.q("INSERT INTO jobs(video_id,url,title,opts,status,live,sub_id) VALUES('chzzk-live-9601','https://chzzk.naver.com/live/" + "f" * 32 + "','휴방 공지','{}','done',1,?)", (fx,))
real_ln = main.live_now
main.live_now = lambda j: True
main.continue_live(main.q("SELECT * FROM jobs WHERE video_id='chzzk-live-9601'")[0])
main.live_now = real_ln
assert main.q("SELECT 1 FROM jobs WHERE video_id='chzzk-live-9601-p2'")
# 녹화가 아직 압축 중이면 다시보기는 이번엔 건너뛰되 기억하지 않음 (끝난 뒤 다시 판단)
main.q("INSERT INTO jobs(video_id,url,title,opts,live,status,live_open) VALUES('chzzk-live-9602',?,'방송','{}',1,'downloading','2026-10-26 20:00:00')",
       (f"https://chzzk.naver.com/live/{cz}",))
real_api, main.chzzk_api = main.chzzk_api, lambda path: {"liveOpenDate": "2026-10-26 20:00:00"}
assert main.recorded_replay(cz, {"videoNo": 601, "videoType": "REPLAY", "duration": 3000}) and "601" not in main.REPLAY_SEEN
main.chzzk_api = real_api
# 정수 설정에 소수가 들어가면 거부 (쓰는 곳의 int() 가 실패해 작업 스레드가 멈췄음). 대기 시간 · 여유 공간은 소수 허용
assert main.bad_setting("concurrency", "1.5") and main.bad_setting("chzzk_compress_concurrency", "2.0")
assert not main.bad_setting("concurrency", "3") and not main.bad_setting("sleep_requests", "1.5") and not main.bad_setting("min_free_gb", "0.5")
# 다 받고 압축을 기다리던 중 취소 → 받은 원본으로 완료 (버리지 않음)
cd_ = tempfile.mkdtemp()
main.subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-t", "2", f"{cd_}/v [cancel00001].mkv"], check=True)
class FakeDL:
    def __init__(self, o): self.params = {"outtmpl": {"default": ""}}
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def extract_info(self, *a, **k): return {"title": "취소 시험", "upload_date": "20261027"}
    def prepare_filename(self, raw): return f"{cd_}/v [cancel00001].mkv"
    def add_post_processor(self, *a, **k): pass
    def process_ie_result(self, raw, download=True):
        return {"title": "취소 시험", "duration": 2, "requested_downloads": [{"filepath": f"{cd_}/v [cancel00001].mkv"}]}
real_dl, main.yt_dlp.YoutubeDL = main.yt_dlp.YoutubeDL, FakeDL
main.q("INSERT OR REPLACE INTO settings(key, value) VALUES('youtube_stream_compress', '0')")
main.q("INSERT INTO jobs(video_id,url,title,opts,status) VALUES('cancel00001','https://www.youtube.com/watch?v=cancel00001','t','{\"quality\": \"small\"}','downloading')")
xj = main.q("SELECT * FROM jobs WHERE video_id='cancel00001'")[0]
main.COMPRESSING[-5], _ = "youtube", main.COMP_RUN.add(-5)  # 압축 칸을 채워 둬서 기다리게
ev = main.threading.Event()
th = main.threading.Thread(target=main.run_job, args=(xj, main.job_settings(xj), ev))
th.start(); ev.wait(20)
main.time.sleep(1); assert main.job(xj["id"])["status"] == "compressing"
main.cancel(xj["id"]); th.join(20)
main.compress_done(-5)
main.yt_dlp.YoutubeDL = real_dl
main.q("DELETE FROM settings WHERE key='youtube_stream_compress'")
r = main.q("SELECT status, filepath FROM jobs WHERE id=?", (xj["id"],))[0]
assert r == {"status": "done", "filepath": f"{cd_}/v [cancel00001].mkv"} and os.path.isfile(r["filepath"])
# 녹화 진행 감시: 다른 종류 오류(DB 잠김 등)가 나도 죽지 않고 계속, 속도는 직전 구간 기준
pf = os.path.join(tempfile.mkdtemp(), "progress.txt")
open(pf, "w").write("total_size=1500000000\nout_time_us=100\n")
calls_w, real_sc = [], main.stall_check
def flaky_sc(jid, size, st):
    calls_w.append(size)
    if len(calls_w) == 1:
        raise main.sqlite3.OperationalError("database is locked")
main.stall_check, stop_w = flaky_sc, []
tw = main.threading.Thread(target=main.watch_stream, args=(-7, pf, None, stop_w, True)); tw.start()
main.time.sleep(4)
open(pf, "a").write("total_size=1503000000\nout_time_us=200\n")
main.time.sleep(4); stop_w.append(True); tw.join(5)
main.stall_check = real_sc
assert len(calls_w) >= 2 and main.LIVE[-7]["speed"] < 2e6  # 3MB / 약 3초 (예전 방식이면 시작부터 평균이라 수백 MB/s 이상)
main.LIVE.pop(-7, None)
# 로그인한 상태에서 녹화가 한참 되다 강제로 끝남 → '로그인 없이 다시'로 처음부터 다시 녹화하지 않고 녹화분 보존 (실제 로그 사례)
lvd = main.safe_dir("Chzzk")
os.makedirs(lvd, exist_ok=True)
lpart = os.path.join(lvd, "2026-10-27 - 몰살 2026-10-27 17_43 [chzzk-live-77701].mp4.part")
open(lpart, "wb").write(b"\0" * 2_000_000)
tries_ = []
class KilledDL(FakeDL):
    def extract_info(self, *a, **k):
        tries_.append(1)
        return {"title": "몰살", "upload_date": "20261027", "is_live": True}
    def prepare_filename(self, raw): return lpart[:-5]
    def process_ie_result(self, raw, download=True):
        raise main.yt_dlp.utils.DownloadError("ERROR: ffmpeg exited with code -9")
ckf = main.COOKIE_FILES["chzzk"]
open(ckf, "w").write("# Netscape HTTP Cookie File\n.naver.com\tTRUE\t/\tTRUE\t0\tNID_AUT\tx\n")
real_dl, main.yt_dlp.YoutubeDL = main.yt_dlp.YoutubeDL, KilledDL
real_ln, main.live_now = main.live_now, lambda j: True
main.q("INSERT INTO jobs(video_id,url,title,opts,status,live) VALUES('chzzk-live-77701','https://chzzk.naver.com/live/" + "9" * 32 + "','몰살','{}','downloading',1)")
kj3 = main.q("SELECT * FROM jobs WHERE video_id='chzzk-live-77701'")[0]
main.run_job(kj3, main.job_settings(kj3))
main.yt_dlp.YoutubeDL, main.live_now = real_dl, real_ln
os.remove(ckf)
r = main.q("SELECT status, filepath FROM jobs WHERE id=?", (kj3["id"],))[0]
assert len(tries_) == 1 and r["status"] == "done" and r["filepath"] == lpart[:-5] and os.path.isfile(lpart[:-5])
print("queue page ok")

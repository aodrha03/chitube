# Changelog

[한국어](CHANGELOG.md) · **English**

Versioning: major = big changes, minor = new features, patch = bug fixes only. The current version is shown next to the title in the web UI. The pre-release 0.x development history is only in the [Korean changelog](CHANGELOG.md).

## v1.9.1 — 2026-10-28
### Fixed
- **Big videos were cut as "stalled" after downloading and re-downloaded from scratch over and over** (real case: the same video 3–4 times, every 20 min): the mp4 finalizing step (moving the moov atom) of 30 GB+ files shows no progress, so the watchdog took it as stuck → an ffmpeg that is using CPU now counts as progress.
- **CPU compression of long streams was force-stopped after 30 min and saved as "compression failed → original"** (10 real cases): a 10 h+ stream compressed on the CPU doesn't move 0.1 % in 30 min → same fix; a truly stuck ffmpeg is still cleaned up.

## v1.9.0 — 2026-10-28
### Added
- **Defaults tuned to the server**: at startup ChiTube looks at CPU cores, memory and the graphics card and adjusts the defaults — with a graphics card, live recordings are compressed on the GPU while recording; CPU-only servers get a concurrent-compression count based on core count, weak CPUs a slightly faster preset, small NAS boxes fewer concurrent Chzzk downloads/recordings. Values you saved in Settings always win (the log shows "서버 사양 → 기본 설정").
- **CPU model and per-core usage**: the CPU row on the status page shows the CPU model; expand "Per-core usage" for a bar per core (collapsed by default).
### Fixed
- **Stopping a recording needed two clicks**: a recording compressed while recording could ignore the stop signal and hang → if it hasn't ended within 10 s it is force-stopped and everything recorded so far is saved; clicking again stops it immediately.
- **Cancelling a recording again deleted it** (real case: the stop was slow, a second click was treated as "cancel download and delete", leaving 0 files): cancelling a recording now always means stop and save, and cancelling while the finished recording is being remuxed to mp4 keeps the recording. The card shows "Saving recording" meanwhile.
- **Cancelling compression could hang**: cancellation was only noticed when ffmpeg printed output → now checked every 0.5 s regardless.

## v1.8.0 — 2026-10-28
### Added
- **The download audit reliably covers Chzzk**: during a YouTube block the audit was skipped or stopped midway, so Chzzk channels weren't compared either → only YouTube is skipped; Chzzk is always audited. "Per YouTuber" is now "Per channel" with a YouTube · Chzzk tag.
- **Chzzk subscription checks continue during a YouTube block** (they used to pause with YouTube; live watching always continued).
- **ⓘ About tab** (next to Settings): author, repository, license (MIT), changelog link, the 15 open-source projects used with their licenses and purpose, plus the trademark and usage notice.

### Fixed
- **Chzzk thumbnails showed a gray "…" image**: replays without a thumbnail URL (age-restricted, processing…) fell back to a YouTube thumbnail URL, which returned YouTube's "no thumbnail" image → the saved thumbnail file is used, otherwise blank.
- The compression device name ("엔비디아" etc.) stayed in Korean in the English UI.
### Cleanup
- Removed unused or duplicate parts: the "check all" API the UI never called, two "re-download" APIs doing the same thing merged into one, the audit's file-length check now uses the shared helper, 21 duplicate or obsolete English translations, unused styles (no behavior change).

## v1.7.3 — 2026-10-28
### Fixed
- **Channels you had downloaded and then deleted could not be downloaded again via subscription or "download all existing videos"** (1.7.1): the removed-video memory also applied to actions you started yourself and survived deleting the subscription → it now applies only to automatic checks and audits, is cleared when the subscription is deleted, and Settings → Manage has "Clear removed-video list".
### Changed
- **Database optimization**: indexes on frequently searched columns (faster lists, queue and audits with many videos), plus one VACUUM · ANALYZE on the first start of a new version.
- Silenced the pip update / root warnings printed at startup (harmless).
- **Stopping / rebooting ends recordings cleanly and exits right away**: `init: true` and a 30 s stop grace period in compose (it used to wait until Docker force-killed it — one cause of slow Ubuntu reboots).
- The audit's per-channel comparison shows "skipped (removed by you) N".
### Fixed (more)
- **Replays stayed skipped after you deleted the live recording**: the "recorded live, skip the replay" decision was cached until restart → decided from current records every time.
- **"Check now" / "Check all" re-downloaded removed videos** (introduced earlier in this 1.7.3) → only a new subscription's first check and "download all existing videos" ignore the removed list.
- English UI: ~30 more translations for dialogs, alerts, progress messages and Status hints.
- **The Status page was sluggish with many videos**: the audit API sent the last 7 results in full and re-checked every problem file every 2 s (10,000 videos: 3.4 s, ~1 MB) → latest result only, re-check every 15 s, lists capped at 300 (totals sent separately) — 0.03 s, 42 KB.
- **Pressing "merge parts" twice could merge the same parts concurrently and corrupt the file** (same-format merges weren't marked as in progress).

## v1.7.2 — 2026-10-28
### Fixed (found by running real recordings and downloads in the UI)
- **YouTube block messages in Korean weren't recognized**, so ChiTube kept sending requests while blocked → now pauses for 1 hour.
- **Live preview always failed during recording** (AAC audio in MPEG-TS needed conversion for mp4).
- **The recording before a restart disappeared from the list** → kept as Done (marked cut) and continued as a new part (-p2).
- **Cut recording parts were left as raw MPEG-TS** (only the last part was processed, so auto-merge failed) → every part is processed per settings.
- **Compressed mp4 files were treated as "original"** when the output had the same name, so the video info was wrong and encoded files' size wasn't updated (audits then flagged them as possibly damaged).
- **The recording quality check flagged static scenes as frozen** (1.6.0; 12 false positives → 0) and misplaced real freezes → uses reference frames.
- Some notices and log lines were half Korean in the English UI.

## v1.7.1 — 2026-10-28
### Fixed
- **Deleted videos were downloaded again** by subscription checks and audits while still in the channel's latest list → removed videos are remembered and skipped (pasting the URL downloads it again).
- **Buttons sometimes didn't react**: the Status page, filter chips, page numbers, subscription buttons, update buttons and the "resume" button were recreated every 2 s, so a click during a refresh was lost → redrawn only when the content changes.
- **Deleting a subscription kept downloading its queued videos** (e.g. hundreds from "download all existing videos") → queued videos are removed from the queue (downloaded files and running downloads stay).
- Bulk actions showed nothing on failure, and the result message was cut off.

## v1.7.0 — 2026-10-28
### Added
- **Shows which device is compressing**: cards and the video info show the actual device, e.g. "Compressing · NVIDIA", "Compressing while downloading · CPU", "Compressing while recording · Intel Quick Sync" — for every kind of compression.
- **Delete with files**: from the video info window or the selection bar, removes the entry together with the video file, thumbnail, subtitles and .nfo (and the empty per-video folder). Videos still downloading, encoding or merging are skipped; the channel poster stays. "Remove from list" still keeps the file.
### Changed
- **"Compress later" is now "Encode"** (re-compress downloaded videos at a quality you pick).

## v1.6.2 — 2026-10-27
### Fixed
- **New downloads stopped while many "compress later" jobs were queued** (1.2.3): the "too many waiting compressions" guard counted compress-later jobs, so queuing 100 of them stopped new downloads for hours → only freshly downloaded originals count.
- **Load protection could postpone compression forever** (1.5.0): with a live stream compressing on the CPU the CPU stays above 95%, so compression kept waiting and downloads could stop too → postponed for at most 30 minutes.
- **New streams of a channel were picked up late for a minute after its recording finished compressing** (1.2.0): "just finished recording" now uses when the recording ended, not when the job (incl. compression) finished.
- The watchdog remembered a job as "cleaned up" even when there was nothing to stop, misclassifying later failures as temporary (1.4.0).
- Log files piled up beyond 7 days on long-running servers (1.4.0) → pruned every minute.
- **The post-download check could delete good files** (1.4.0): a timeout on a slow NAS counted as "unplayable", and videos whose YouTube-reported length differs slightly (e.g. live replays) were deleted and re-downloaded repeatedly, possibly losing the video → files are deleted only when they truly can't be opened; a length difference is just noted in the video info.
- **Merged recordings kept the quality check of the first part only** (1.6.0), sometimes running during the merge → the merged file is checked again.
- **Re-encoding merges ignored the compression slots and GPU yielding** → they now wait for a slot and use the CPU while a live stream is compressed on the GPU.

## v1.6.1 — 2026-10-27
### Changed
- **English documentation**: English README, user manual, per-platform install guides and changelog (`*.en.md`); release zips include `INSTALL.en.md`. English messages in the Windows `시작.bat` / `중지.bat`, `.env.example`, `docker-compose.yml` and the permission-error message.
- Removed the self-test instruction from the manual (running it on a live server could delete saved login info).

## v1.6.0 — 2026-10-27
### Added
- **Recording quality check**: after a live recording ends, it's scanned in the background (low priority) for frozen video and silence longer than 10 s; times and lengths are shown in the video info window. Only keyframes are decoded, so multi-hour recordings are checked quickly.
- **GPU auto-tuning**: at startup a 1080p60 sample is compressed on the GPU to measure its speed, and the default for "Live streams compressed on the GPU at once" is set to fit the card (30% headroom). Shown under Status → Hardware acceleration. A value you saved yourself wins; if it's higher than the measurement, "Settings to check" tells you.

## v1.5.0 — 2026-10-27
### Added
- **Fill recording gaps with the replay** (on by default): Chzzk streams whose recording was interrupted even once also get the replay downloaded, so you have a complete copy. Live-only subscriptions get just that stream's replay. The interrupted recording can be kept (default) or deleted afterwards.
- **Updates wait for recordings**: pressing update while recording lets you choose "when all recordings end" or "now". Compression of recordings cut by a restart continues after the restart at the same quality.
- **Download diagnostics** (Status → Recent activity): logs, status, settings and active jobs in one file (no login info or cookies).
- **Settings to check** (top of the Status page): too many GPU live compressions, too many CPU compressions for the core count, YouTube concurrency ≥ 2, minimum free space 0, less than ~48 h of free space for original recordings, a very long stall limit.
- **Load protection**: while recording, if the CPU or GPU encoder has been at 95%+ for 3 minutes, new compressions wait.

## v1.4.0 — 2026-10-27
### Added (recording & download reliability)
- **Watchdog**: every minute all running jobs are checked; with no progress at all (recording 3 min · download 20 min · compression 30 min) the job is cleaned up — recordings saved and continued, downloads retried. Jobs left "downloading" without a worker go back to the queue.
- **Immediate retry for temporary errors**: timeouts, dropped connections, server 5xx… are retried after 1 → 5 → 15 minutes instead of waiting for the twice-daily audit.
- **File check right after download**: checks that the file opens and its length matches; broken files are deleted and retried.
- **Log files**: 7 days in `config/logs/`, "Download log file" under Status → Recent activity.
- **Recording stall limit setting** (Settings → Common, default 45 s, was 90 s).
### Changed
- **Database in WAL mode**: far fewer "database is locked" errors with many simultaneous jobs (not on Windows Docker Desktop).
- **Default for compressing live streams while recording = Off (compress after recording)** for new installs — recording the original is the most stable. Saved settings are kept.
- Automatic retry limit 3 → 6 (3 quick retries + 3 at audits).

## v1.3.0 — 2026-10-27
### Added
- **Live streams compressed on the GPU at once** (Settings → Common, default 3): the GPU encoder is shared, so too many simultaneous live compressions make all of them fall behind and stall. Streams above the limit are recorded as original and compressed after the stream ends.
### Changed
- Compressing a finished recording also moves off the GPU to the CPU while another stream is being compressed on the GPU.

## v1.2.6 — 2026-10-27
### Fixed
- **A cut-off live recording restarted from scratch when logged in**: a recording killed after stalling was treated as a login failure and recorded again in the same job, leaving the earlier part as an unlisted `.part` file. Now the recording is kept and continues in a new file.
- **Progress display and stall detection stopped for a restarted recording**: the progress file was shared per job, so cleanup of the previous attempt deleted the new one (the real cause of the "hundreds of GB/s" display and a 3-hour stall).

## v1.2.5 — 2026-10-27
### Fixed
- **Live recordings stuck forever**: the progress watcher thread could die on errors like "database is locked", taking stall detection with it. It now keeps running.
- **Live recordings stalling because other compressions shared the GPU** (measured: RTX A400 encoder at 100%) → while a stream is compressed on the GPU, other compressions use the CPU at low priority.
- **Recording speed shown as hundreds of GB/s**: speed is now measured over the last 3 seconds.

## v1.2.4 — 2026-10-27
### Changed
- **Cancelling during compression keeps the downloaded original** and marks the video Done (was "Cancelled" with the file left in the folder). The button now says "Cancel compression".
### Fixed
- Decimal values (e.g. 1.5) in integer settings made worker threads fail every 30 s (possible via backup restore).
- Originally-recorded (only remuxed) videos showed "NONE CRF …" as if compressed.
- Streams longer than 24 h showed the wrong length (26 h → 02:00:00).
- "Preview" button shown for videos being compressed later.
- Videos saved as original after a failed compression are marked in the video info.

## v1.2.3 — 2026-10-27
### Fixed
- **Originals piling up and filling the disk when compression is slow** (1.2.0): new downloads pause when the compression queue reaches twice the concurrent-compression limit (live recordings never pause).
- **Compression failures left a downloaded original as "Error"** and the audit re-downloaded and failed again → kept as original (can compress later).
- **Live recording stopped when the title changed to a filter's excluded word** (1.1.0): continuations ignore filters.
- **Replay downloaded twice while the recording was still compressing**.
- Login cookie copies piling up in the temp folder (1.2.0).

## v1.2.2 — 2026-10-27
### Fixed
- **Compression could hang forever at "Compressing"** when ffmpeg wrote lots of error output (e.g. damaged recordings).
- **Videos waiting to compress ended up uncompressed after a restart/update** → compressed if the file's codec differs from the setting.
- **Recordings waiting to compress became errors after a restart** and disappeared from the list → kept as Done (can compress later).
- **No continuation when the Chzzk status check failed once** → retried 3 times, 5 s apart.
- A thumbnail timeout marked a finished recording as Error (1.1.0).
- Re-download/remove while "compress later" was running; the "compress later" confirm closing the info window on cancel.

## v1.2.1 — 2026-10-27
### Fixed
- New streams of a channel weren't recorded while its previous recording was compressing (1.2.0).
- Continuation parts could still land in a new folder named after the new title.
- Finished recordings left as MPEG-TS when compression didn't make them smaller.
- All compressions converted to 8-bit (1.1.2) — resolution locking now applies only to live recordings.
- Rare 30-second worker stalls when many downloads/compressions ran at once.

## v1.2.0 — 2026-10-27
### Added
- **Compress later** for videos downloaded as original, recordings and replays (video info window, or select several).
- **Compression method per platform**: "Compression method" and "Compress live streams while recording" set separately for YouTube and Chzzk.
- **Concurrent compressions separate from downloads (per platform)**: compression runs in its own slots, so the next video downloads while compressing; waiting videos show "Waiting to compress".
### Fixed
- **A title change during a stream created an extra folder and stopped the recording**: Chzzk recordings are now identified by channel; continuation parts use the first part's folder and name.
- **Cancel/remove did nothing on items that had errors**: a late progress update made them look "recording".

## v1.1.2 — 2026-10-25
### Fixed
- Chzzk replay preview always showed the first 10 s.
- A stream that ended left the recording as an error → treated as a normal end.
- Recording while compressing failed when the stream's resolution/audio format changed.
- Continuations no longer show as red errors.
- 1–2 Chzzk replays missing from subscriptions (partially recorded streams).
- "Check now" / "Audit now" reacting up to a minute late.
- UI responsiveness: no overlapping refreshes, only changed cards are redrawn.

## v1.1.1 — 2026-10-23
### Changed
- "Usage by channel" on the Status page is collapsed by default.

## v1.1.0 — 2026-10-23
### Added
- Auto-merge split recordings when the stream ends · recording thumbnails · subscription filters (title include/exclude, min length) · YouTube chapters · SponsorBlock segment marking (off by default, never cuts) · stream time pattern · usage by channel.

## v1.0.3 — 2026-10-23
### Added
- New-version notice from GitHub releases · "Source gone" tag for videos removed from a channel (files are kept).
### Changed
- Faster H.265 compression on 2–3 core devices.

## v1.0.2 — 2026-10-23
### Changed
- Status shows the runtime environment, and why hardware acceleration is unavailable for that environment · guidance not to copy files while recording.

## v1.0.1 — 2026-10-23
### Fixed
- A recording "jumping" once at stream start · recordings stuck after copying the file (stall detection) · recordings kept even when the file is locked.

## v1.0.0 — 2026-10-23 · first public release

- **YouTube**: videos · Shorts · live · playlists, channel/playlist subscriptions, members-only videos (login)
- **Chzzk**: replays · live, channel subscriptions, live checked every 10 s → automatic recording, age-restricted videos (login)
- **Compression while downloading**: H.265 · H.264 · AV1 presets or original, Intel Quick Sync · NVIDIA automatically (CPU otherwise)
- **Live recording**: continues after cuts with an interruption log, merge parts, live preview, recorded streams don't download the replay again
- **Plex · Jellyfin**: channel = show · year = season · episode numbers, thumbnails · subtitles (.srt) · .nfo · channel poster
- **Runs unattended**: audits twice a day, pauses on YouTube block signals and low disk space, never deletes downloads
- **Convenience**: search · sort · multi-select, settings & subscription backup/restore, hide errors, Korean / English UI, yt-dlp update from the web UI
- **Install**: one Docker setup for Synology · Linux · macOS · Windows · Portainer; per-platform release files, Windows via `시작.bat`

# ChiTube install — Synology (DSM 7.2+)

> [한국어](synology.md) · **English** — you only do this once. For everything else, see the [user manual](../MANUAL.en.md).

## 1. Prepare

- Install **Container Manager** from Package Center.
- Unzip this file (`chitube-…-synology.zip`) on your PC.

## 2. Upload the files

1. **File Station** → inside the `docker` shared folder, create a **`chitube`** folder.
2. Upload **everything inside** the unzipped folder to `docker/chitube`.
   - `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `app/` and the **empty `config/` and `downloads/` folders** must be directly under `docker/chitube`.
   - If the empty folders were skipped during upload, create `config` and `downloads` in File Station yourself (otherwise you get `Bind mount failed`).

## 3. Run

1. **Container Manager → Project → Create**
2. Project name `chitube`, path `docker/chitube`
3. Source: **Use existing docker-compose.yml** → Next → Done (the first build takes a few minutes)
4. Open **`http://<NAS>:8945`** in your browser

## Good to know

- ⚠ Keep `PUID` and `PGID` in `.env` at **0**. Changing them can make the container restart forever with `unable to open database file`.
- To save videos to another shared folder or USB, copy `.env.example` to `.env` and set e.g. `DOWNLOAD_DIR=/volume1/video/ChiTube` (create the folder first).
- Intel models get Quick Sync (hardware compression) automatically. ARM models use the CPU. Synology CPUs compress slowly, so **Original** or **H.264 Standard** quality is recommended.
- **Do not copy or move a file that is still downloading or recording — on any OS.** Depending on how you copy (Explorer, Finder, network share) and how Docker maps folders, the recording can stall, or ChiTube may not find the file at the end to finish/compress it. Use **▶ Preview** in the video info window to check a recording, and copy files after they show **Done**. (If a recording stalls, ChiTube saves it after 45 s — configurable — and continues in a new file, but the stalled time is missing.)
- The web UI has no password. Do not open it to the internet with port forwarding.

## Update

1. **Overwrite** `docker/chitube` with the contents of the new version (keep `config/` and `downloads/`).
2. Container Manager → project `chitube` → Stop → **Build** → Start

## Moving from the old name (docker_youtube)

1. Container Manager → Project → old project (`docker_youtube`) **Stop → Delete** (folders and videos are not deleted).
2. Overwrite the old folder with the new version (keep `config/` and `downloads/`) and do **3. Run** again with that folder — settings, subscriptions and the download list carry over.

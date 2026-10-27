# ChiTube install — Windows

> [한국어](windows.md) · **English** — for everything else, see the [user manual](../MANUAL.en.md).

## 1. Prepare (once)

1. Install **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** → keep **Use WSL 2** during setup → restart the PC.
2. Keep Docker Desktop running (whale icon in the taskbar).

## 2. Run

1. Unzip this file (`chitube-…-windows.zip`) anywhere, e.g. `C:\chitube`.
2. Double-click **`시작.bat`** (start) in the folder.
   - The first time it takes a few minutes to build the image. When it's done, **`http://localhost:8945`** opens in your browser.
3. To stop it, run **`중지.bat`** (stop). Settings and videos are kept.

> To start it automatically with your PC: Docker Desktop → Settings → General → tick **Start Docker Desktop when you sign in**. ChiTube starts whenever Docker starts.

## Change the save location (optional)

The default is this folder's `downloads\`. To save to another drive:

1. Copy `.env.example` and rename it to `.env`.
2. Open it in Notepad, change it to e.g. `DOWNLOAD_DIR=D:\Videos\ChiTube` and save.
3. Run `시작.bat` again.

## Good to know

- Docker Desktop on Windows cannot use the graphics card, so it **compresses on the CPU**. If that's slow, set the quality to **Original** (no compression).
- You can edit the files with Notepad — Windows line endings are fixed automatically.
- **Do not copy or move a file that is still downloading or recording — on any OS.** Depending on how you copy (Explorer, Finder, network share) and how Docker maps folders, the recording can stall, or ChiTube may not find the file at the end to finish/compress it. Use **▶ Preview** in the video info window to check a recording, and copy files after they show **Done**. (If a recording stalls, ChiTube saves it after 45 s — configurable — and continues in a new file, but the stalled time is missing.)
- The web UI has no password. Other devices on your home network can open `http://<this PC's IP>:8945`; do not open it to the internet.

## Update

**Overwrite** this folder with the contents of the new version (`config\`, `downloads\` and `.env` stay) → `시작.bat`

## Moving from the old name (docker_youtube)

Docker Desktop → Containers → **delete** the old `docker_youtube` (trash icon) → overwrite the old folder with the new files and run `시작.bat`. Settings and videos carry over.

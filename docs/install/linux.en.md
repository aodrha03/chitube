# ChiTube install — Linux (Docker)

> [한국어](linux.md) · **English** — macOS works the same way. For everything else, see the [user manual](../MANUAL.en.md).

## 1. Prepare

You need Docker and Docker Compose v2 (the `docker compose` command).

```sh
docker compose version     # if this prints a version, you're ready
```

## 2. Run

In the unzipped folder (or the `git clone` folder):

```sh
cd chitube
docker compose up -d --build
```

Open **`http://<server>:8945`** in your browser (the first build takes a few minutes).

Videos go to `downloads/`, settings and login info to `config/`.

## Change the save location / file owner (optional)

```sh
cp .env.example .env
nano .env          # DOWNLOAD_DIR=/mnt/hdd/ChiTube, PUID/PGID = values from the `id` command
docker compose up -d
```

## GPU (optional)

- **Intel integrated graphics**: nothing to do (connected automatically if the server has `/dev/dri`).
- **NVIDIA**: install the NVIDIA driver + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), then once:
  ```sh
  sudo nvidia-ctk runtime configure --runtime=docker --set-as-default && sudo systemctl restart docker
  ```
- macOS (Docker Desktop) cannot give containers the GPU, so it compresses on the CPU.

## Files being recorded

**Do not copy or move a file that is still downloading or recording — on any OS.** Depending on how you copy (Explorer, Finder, network share) and how Docker maps folders, the recording can stall, or ChiTube may not find the file at the end to finish/compress it. Use **▶ Preview** in the video info window to check a recording, and copy files after they show **Done**. (If a recording stalls, ChiTube saves it after 45 s — configurable — and continues in a new file, but the stalled time is missing.)

## Common commands

```sh
docker compose logs -f          # view logs
docker compose restart          # restart (also updates yt-dlp)
docker compose down             # stop and remove (config/ and downloads/ stay)
```

## Update

Overwrite with the new version (keep `config/` and `downloads/`) and run `docker compose up -d --build`.
If you used `git clone`: `git pull && docker compose up -d --build`.

## Moving from the old name (docker_youtube)

The container is now called `chitube`. Remove the old container once and start again. Settings and videos stay in `config/` and `downloads/`.

```sh
docker rm -f docker_youtube
docker compose up -d --build
```

⚠ The web UI has no password. Do not open it to the internet.

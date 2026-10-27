# ChiTube install — Portainer

> [한국어](portainer.md) · **English** — ChiTube builds its own image, so pasting only the compose file into the Web editor won't work. Use one of the options below.

## Option A — Repository (easiest, recommended)

Portainer fetches and builds straight from GitHub, no files needed.

1. **Stacks → Add stack** → name `chitube`
2. Build method: **Repository**
   - Repository URL: `https://github.com/aodrha03/chitube`
   - Repository reference: `refs/heads/main`
   - Compose path: `docker-compose.yml`
3. (Optional) **Environment variables**: `DOWNLOAD_DIR` (e.g. `/mnt/hdd/ChiTube`), `PUID`, `PGID`
4. **Deploy the stack** → open **`http://<server>:8945`**

Update: stack → **Pull and redeploy**

## Option B — Build the image on the server, then a stack

1. Unzip this file on the server and build the image:
   ```sh
   cd chitube
   docker build -t chitube:latest .
   ```
2. **Stacks → Add stack** → paste the contents of `portainer-stack.yml` from this folder into the **Web editor**.
3. Change the `volumes` paths (`/opt/chitube/config`, `/mnt/hdd/ChiTube`) to real server paths and **Deploy the stack**.

Update: rebuild with the new files (`docker build -t chitube:latest .`) → stack **Update the stack** (turn Re-pull off)

## Files being recorded

**Do not copy or move a file that is still downloading or recording — on any OS.** Depending on how you copy (Explorer, Finder, network share) and how Docker maps folders, the recording can stall, or ChiTube may not find the file at the end to finish/compress it. Use **▶ Preview** in the video info window to check a recording, and copy files after they show **Done**. (If a recording stalls, ChiTube saves it after 45 s — configurable — and continues in a new file, but the stalled time is missing.)

## GPU

- Intel Quick Sync: nothing to do (don't remove the `device_cgroup_rules` line).
- NVIDIA: install the NVIDIA Container Toolkit on the server, then once `sudo nvidia-ctk runtime configure --runtime=docker --set-as-default && sudo systemctl restart docker`

## Moving from the old name (docker_youtube)

**Stop → Delete** the old stack (`docker_youtube`), then create the `chitube` stack as above. Using the same config folder path in the volumes keeps settings, subscriptions and the download list.

⚠ The web UI has no password. Do not open it to the internet. For everything else, see the [user manual](../MANUAL.en.md).

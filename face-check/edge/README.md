# Face Check edge box

Runs at a street site, next to the cameras. For each camera it reads the video, finds and
tracks faces, and sends the server **only the best face embedding of each person who
passes** (a list of 512 numbers, not a photo). The server compares it with the wanted list:

- **No match:** nothing is stored anywhere.
- **Match:** the edge box uploads that person's face crop, and the match appears in
  `/admin` → **Camera review**. An operator confirms it (officers within the alert radius
  get a push notification with the photo and directions to the camera) or rejects it
  (the crop is deleted).

Video never leaves the site. See `../cameraplan.md` for the overall plan.

## 1. Register the cameras

In `/admin` → **Cameras**, register each camera with its exact GPS position (this is where
officers are sent). Copy the key that is shown once. To get a new one later, use **New key**.

## 2. Install on the edge box

Python 3.11 on Linux (Jetson, mini PC) or macOS. From the `face-check` folder:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r edge/requirements.txt
# same face model as the server (Render runs buffalo_s; check /admin → Cameras)
MODEL_ROOT=~/.insightface python download_models.py buffalo_s
cp edge/config.example.json edge/config.json   # then edit it
```

`edge/config.json`:

| Field | Meaning |
|---|---|
| `server` | Face Check server URL |
| `model_root` | Folder with the downloaded models |
| `fps` | Frames analysed per second per camera (5 is enough for people walking) |
| `min_face_px` | Ignore faces narrower than this (too small to match reliably) |
| `send_after_s` | Someone staying in view is sent after this many seconds |
| `cameras[].source` | `rtsp://user:pass@ip:554/...` for IP cameras, `http://.../video` for a phone IP-camera app, `"0"` for a USB/laptop webcam |
| `cameras[].key` | Key from `/admin` → Cameras |
| `cameras[].rotate` | `90`, `180` or `270` (clockwise) if the picture arrives sideways or upside down, e.g. a phone held upright or a camera mounted on its side. Faces must be upright to be detected |

`config.json` contains camera passwords and keys: it is ignored by git; keep it readable only
by the service user (`chmod 600 edge/config.json`).

## 3. Run

```bash
python -m edge.run --config edge/config.json --preview   # setup: shows video with face boxes
python -m edge.run --config edge/config.json             # normal operation
```

In preview, a **green** box is a face good enough to match; **orange** is too small or unclear.
Adjust camera angle and zoom until people walking past get green boxes of 100 px or more.

**Live view:** `/admin` → Cameras → **View live** shows the camera at about 2 frames per second while
the window is open (the edge box only sends frames then; nothing is recorded; each opening is
audit-logged).

The program reconnects to cameras and to the server by itself, keeps up to 500 detections
while the network is down, and logs a status line per camera every minute. The camera shows
as **Online** in `/admin` → Cameras while the edge box is running.

### Testing without street cameras

- **Laptop webcam:** `"source": "0"`.
- **Phone as camera:** install an "IP Webcam" app on an Android phone on the same Wi-Fi and
  use the URL it shows, e.g. `"source": "http://192.168.1.20:8080/video"`.

Register a test person (e.g. yourself) as wanted on `/admin`, walk in front of the camera,
and the match appears in **Camera review**.

### Run as a service (Linux)

`/etc/systemd/system/face-check-edge.service`:

```ini
[Unit]
Description=Face Check edge box
After=network-online.target

[Service]
WorkingDirectory=/opt/face-check
ExecStart=/opt/face-check/.venv/bin/python -m edge.run --config edge/config.json
Restart=always
RestartSec=5
User=facecheck

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now face-check-edge` and `journalctl -u face-check-edge -f` for logs.

## Performance

Detection runs on every analysed frame; the face embedding is computed only when a person's
face is clearly better than their previous best. On a CPU, expect roughly 2–4 cameras at
5 fps with `buffalo_s`; on an NVIDIA Jetson Orin with `onnxruntime-gpu`, 4–8 cameras.

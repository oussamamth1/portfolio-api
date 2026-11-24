# Street camera plan for Face Check

How to connect street cameras to the Face Check system so that a wanted person seen by a
camera triggers an alert to the nearest officers.

Most of the system already exists and is reused as-is: the matching server, the wanted list,
alerts with push notifications to officers within the alert radius, and the audit log.
What is new: an **edge box** on site that watches the video, a **camera registry**, and a
**control-room review** step where a human confirms each camera match.

## 1. Architecture

```
 Street cameras (IP, RTSP)          Site "edge box"                      Face Check server              Officers
 ┌──────────┐                  ┌───────────────────────────┐        ┌──────────────────────┐      ┌───────────┐
 │ Cam 1    │──PoE / fiber──▶ │ decode video              │        │ compare with wanted  │      │ push alert│
 │ Cam 2    │──────────────▶  │ detect + track faces      │──VPN──▶│ match? → review queue│──OK─▶│ photo +   │
 │ Cam 3    │                  │ keep best face per person │ (only  │ operator confirms    │      │ camera GPS│
 └──────────┘                  │ discard everything else   │ faces) │ → alert nearby (5 km)│      │ directions│
                               └───────────────────────────┘        └──────────────────────┘      └───────────┘
```

- **Video never leaves the site.** The edge box sends only a face embedding (and a small face
  crop when it matches). Nothing is stored for people who do not match a wanted person.
- **Why on-site processing:** the current Render free plan (512 MB RAM) cannot decode even one
  video stream. Processing on site also keeps bandwidth to a few KB per face.

## 2. Hardware and installation

| Item | What to choose | Why |
|---|---|---|
| Cameras | 4–8 MP IP cameras, RTSP/ONVIF, varifocal lens (2.8–12 mm), infrared for night, IP67 and IK10 (vandal-proof) | The face must be at least ~100 px wide in the image for reliable matching |
| Placement | Choke points (pedestrian crossings, entrances, narrow passages), **2.5–3.5 m high, tilted down at most ~15°**, facing the walking direction | Higher or steeper cameras see the top of heads, not faces: the #1 cause of failure |
| Lighting | Avoid facing the sun or headlights; add lighting at night if infrared is not enough | Backlit faces cannot be matched |
| Edge box | One per site: NVIDIA Jetson Orin Nano/NX or a small PC with a GPU; about 4–8 cameras each | Runs the same face models as the server (SCRFD + ArcFace) |
| Network | PoE switch, fiber or 4G/5G router, **VPN (WireGuard)** to the server | No camera or edge box is reachable from the internet |
| Power and housing | Pole or wall mount, weatherproof cabinet, UPS for the edge box | Keeps working during power cuts |
| Permits | Municipality approval for poles and power; building owner agreement for wall mounts | Needed before installation |

Existing cameras or recorders (NVR) can be reused if they provide an RTSP stream and meet the
placement and resolution rules above.

## 3. Software (built: `edge/`, `/admin` → Cameras and Camera review)

### A. Camera registry (server + `/admin`)
- New **Cameras** tab: name, GPS position, area, active/inactive, one API key per camera
  (an edge box with several cameras holds several keys; each can be revoked on its own).
- The camera's position becomes the alert location, so officers get directions to that camera.
- Edge boxes send a heartbeat; the admin page shows cameras that are offline.

### B. Edge program (new, runs on the edge box)
- Reads each camera's RTSP stream; detects and tracks faces with the same model as the server.
- Per person passing, keeps only the **best frame**: largest, sharpest, most frontal face.
- Computes the face embedding on site and sends it to a new `POST /api/cameras/detections`
  endpoint; attaches the face crop only when the server reports a match.
- Discards everything else immediately; buffers detections during network outages.

### C. Control-room review (server + `/admin`)
- Camera matches do **not** go straight to officers. They appear in a **review queue** on
  `/admin`: camera crop next to the photo on file, similarity, camera, time.
- Operator clicks **Confirm → alert officers** or **Not the person**.
- Confirmed matches reuse the existing alert system: push notification to officers within the
  alert radius, with photo and directions to the camera.
- Stricter threshold for cameras than for officer checks (about **0.55** instead of 0.45),
  because no officer is there to check an ID document.
- The same person on the same camera within 10 minutes is grouped into one review item.
- All reviews (confirm / reject, who, when) are written to the audit log.

### D. Server capacity
- Move off the free plan: paid instance with at least 2 GB RAM and the more accurate
  `buffalo_l` model; paid PostgreSQL with backups.
- Long term: hosting in the country if required (see section 5).

## 4. Rollout

1. **Pilot (4–6 weeks):** 2–3 cameras at one site, one edge box.
   - Enrol volunteer officers as test "wanted" people; have them walk past at different
     times of day and in different weather and lighting.
   - Measure how often the right person is found and how often the wrong person is flagged;
     set the threshold per camera from these numbers.
2. **Adjust:** fix camera angles, lighting and thresholds from the pilot results.
3. **Extend:** one site at a time. Each new site = one edge box + its cameras registered on `/admin`.
4. **Operate:** weekly check that every camera is online; lens cleaning and maintenance schedule;
   monthly review of false matches.

## 5. Legal and governance (decide before the pilot)

Live face recognition in public spaces is the most regulated use of this technology.

- Obtain the **legal basis and written authorization** for this specific use (in Tunisia:
  Organic Law 2004-63 on personal data protection and the INPDP authority, plus the
  prosecutor's or ministry's framework).
- Decide signage, data retention, and who may access the review queue.
- Safeguards already built into the design:
  - faces of people who do not match are never stored;
  - a human confirms every camera match before officers are alerted;
  - every action is recorded in the audit log;
  - alert photos are deleted after 30 days.

## 6. Open questions

1. **Pilot site:** street location and number of cameras.
2. **Existing hardware:** are there cameras or an NVR already? Do they provide RTSP?
3. **Hosting:** can the server move to a paid plan, or must it run on government servers?
4. **Control room:** who will review camera matches, and during which hours?

## 7. Next steps

| Step | Who | Depends on |
|---|---|---|
| Legal authorization and data-protection review | Police administration | — |
| Choose pilot site, survey poles / power / network | Police + installer | Authorization |
| ~~Camera registry + review queue (server, `/admin`)~~ done | Development | — |
| ~~Edge program~~ done (`edge/README.md`); test with a laptop webcam or a phone as IP camera | Development | — |
| Buy and install pilot hardware | Installer | Site survey |
| Pilot run and threshold calibration | Police + development | Hardware installed |

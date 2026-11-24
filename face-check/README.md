# Face Check (`face-check/`)

Server that compares a photo against a police-managed list of people and returns
**possible matches for an officer to verify**. It never makes a decision on its own.

- **Face model:** InsightFace `buffalo_l` (SCRFD detection + ArcFace 512-d embeddings)
- **Database:** PostgreSQL + pgvector (HNSW cosine index)
- **API:** FastAPI
- **Admin page:** `/admin`

## Deploy on Render

1. This service lives in the `face-check/` folder of this repo and is declared in the root `render.yaml`.
2. In Render: open the existing Blueprint and click **Manual sync**. Render reads `render.yaml` and creates:
   - `face-check-api`: Docker web service on the **free** plan with the smaller `buffalo_s` model (demo)
   - `face-check-db`: **free** PostgreSQL with no public access (Render deletes it after 30 days)

   For real use, set the service to `standard` (2 GB RAM) and `MODEL_NAME` to `buffalo_l` in `render.yaml`.
3. The first build takes about 10 minutes because it installs the AI libraries and downloads the model.
4. Open the service's **Environment** tab and copy `ADMIN_API_KEY`.
5. Open `https://<your-service>.onrender.com/admin`, paste the admin key, and create an
   account (badge number + password) for each officer under **Officers**.

## API

Admin requests use the `X-Api-Key: <ADMIN_API_KEY>` header. The officer app signs in and
then sends `Authorization: Bearer <token>` (sessions last 14 days; disabling an officer or
resetting their password ends all of their sessions). Five wrong passwords lock a badge for
15 minutes.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/suspects` | admin | Add a person (form: `full_name`, `case_number`, `notes`, `wanted`, `most_wanted`, `status`, `photo`) |
| GET | `/api/suspects?q=&wanted=&status=&sort=` | admin | List with filters: `wanted` = `most`, `wanted`, `wanted_only`, `not`; `sort` = `updated`, `newest`, `name` |
| PATCH | `/api/suspects/{id}` | admin | JSON: any of `full_name`, `case_number`, `notes`, `wanted`, `most_wanted`, `status` |
| DELETE | `/api/suspects/{id}` | admin | Remove |
| GET | `/api/suspects/{id}/photo` | admin or officer | Reference photo |
| GET | `/api/wanted?q=` | officer (or admin) | Everyone with `wanted`, most wanted first |
| POST | `/api/identify` | officer (or admin) | Form `photo` returns the top 3 possible matches |
| POST | `/api/officer/login` | none | JSON `badge`, `password` returns a session `token` |
| GET | `/api/officer/me` | officer | Who is signed in |
| POST | `/api/officer/logout` | officer | End this session |
| GET / POST | `/api/officers` | admin | List / create officer accounts (`badge`, `full_name`, `password`) |
| PATCH | `/api/officers/{id}` | admin | JSON: any of `full_name`, `password`, `active` |
| POST | `/api/officers/{id}/signout` | admin | Sign the officer out on every phone |
| POST | `/api/officer/location` | officer | JSON `lat`, `lng`, `accuracy`: where this phone is (sent while the app is open) |
| POST | `/api/officer/push-token` | officer | JSON `token`: this phone's Firebase push token |
| POST | `/api/alerts` | officer | Form `suspect_id`, `lat`, `lng`, `accuracy`, `similarity`, `photo`: wanted person found; notifies officers within the radius |
| GET | `/api/alerts` | officer or admin | Officer: alerts received or sent (7 days). Admin: all |
| GET | `/api/alerts/{id}`, `/api/alerts/{id}/photo` | officer (sender/recipient) or admin | Alert detail and field photo |
| GET / PUT | `/api/settings/alerts` | admin | Alert radius (km) and push status |
| GET | `/api/audit?suspect_id=` | admin | Who checked what, and when (optionally for one person) |

`status` is one of `open`, `investigating`, `arrested`, `released`, `closed`.
`most_wanted` implies `wanted`; setting `wanted` to false also clears `most_wanted`.

Send the **full photo** to `/api/identify` (downscaled to about 1280 px), not a tight
face crop. The server detects the face itself. Photos sent to `/identify` are processed in
memory and **never stored**.

## Alerts and push notifications

When an officer reports a wanted person, the server stores the field photo and location and
notifies every other signed-in officer whose phone reported a location within the last
`LOCATION_MAX_AGE_MIN` minutes (default 120) and is within the alert radius (default 5 km,
set on `/admin`). The same officer reporting the same person within 10 minutes reuses the
first alert. Field photos are deleted after `ALERT_RETENTION_DAYS` (default 30).

Push uses Firebase Cloud Messaging. Set `FIREBASE_SERVICE_ACCOUNT_JSON` to the full
service-account key (Firebase console > Project settings > Service accounts > Generate new
private key). Without it alerts still work, but officers only see them when they open the app.

## Before real use

- **Calibrate `MATCH_THRESHOLD`** with real photos (from the same cameras, lighting and
  distances as in the field). Measure how often the wrong person is matched and how often
  the right person is missed.
- **Data location:** Render runs in the US, EU and Singapore. Check whether the law
  requires this data to stay on government servers in the country. The code runs
  unchanged anywhere Docker runs.
- Use it only within the legal framework that authorizes it, and always have a human verify.

## Run locally

Requires Python 3.11 and PostgreSQL with pgvector.

```bash
cd face-check
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://localhost/facecheck ADMIN_API_KEY=dev-admin
uvicorn app.main:app --reload
```

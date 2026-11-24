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
| POST | `/api/suspects` | admin | Add a person (form: `full_name`, `case_number`, `notes`, `wanted`, `status`, `photo`) |
| GET | `/api/suspects?q=` | admin | List and search |
| PATCH | `/api/suspects/{id}` | admin | JSON: any of `full_name`, `case_number`, `notes`, `wanted`, `status` |
| DELETE | `/api/suspects/{id}` | admin | Remove |
| GET | `/api/suspects/{id}/photo` | admin or officer | Reference photo |
| POST | `/api/identify` | officer (or admin) | Form `photo` returns the top 3 possible matches |
| POST | `/api/officer/login` | none | JSON `badge`, `password` returns a session `token` |
| GET | `/api/officer/me` | officer | Who is signed in |
| POST | `/api/officer/logout` | officer | End this session |
| GET / POST | `/api/officers` | admin | List / create officer accounts (`badge`, `full_name`, `password`) |
| PATCH | `/api/officers/{id}` | admin | JSON: any of `full_name`, `password`, `active` |
| POST | `/api/officers/{id}/signout` | admin | Sign the officer out on every phone |
| GET | `/api/audit` | admin | Who checked what, and when |

`status` is one of `open`, `investigating`, `arrested`, `released`, `closed`.

Send the **full photo** to `/api/identify` (downscaled to about 1280 px), not a tight
face crop. The server detects the face itself. Photos sent to `/identify` are processed in
memory and **never stored**.

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

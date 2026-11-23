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
4. Open the service's **Environment** tab and copy `ADMIN_API_KEY` and `OFFICER_API_KEY`.
5. Open `https://<your-service>.onrender.com/admin` and paste the admin key.

## API

All requests need the `X-Api-Key` header.

| Method | Path | Key | Purpose |
|---|---|---|---|
| POST | `/api/suspects` | admin | Add a person (form: `full_name`, `case_number`, `notes`, `photo`) |
| GET | `/api/suspects?q=` | admin | List and search |
| DELETE | `/api/suspects/{id}` | admin | Remove |
| GET | `/api/suspects/{id}/photo` | admin or officer | Reference photo |
| POST | `/api/identify` | officer + `X-Officer-Id` | Form `photo` returns the top 3 possible matches |
| GET | `/api/audit` | admin | Who checked what, and when |

Send the **full photo** to `/api/identify` (downscaled to about 1280 px), not a tight
face crop. The server detects the face itself. Photos sent to `/identify` are processed in
memory and **never stored**.

## Before real use

- **Calibrate `MATCH_THRESHOLD`** with real photos (from the same cameras, lighting and
  distances as in the field). Measure how often the wrong person is matched and how often
  the right person is missed.
- **Replace the shared officer key** with individual officer accounts.
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
export DATABASE_URL=postgresql://localhost/facecheck ADMIN_API_KEY=dev-admin OFFICER_API_KEY=dev-officer
uvicorn app.main:app --reload
```

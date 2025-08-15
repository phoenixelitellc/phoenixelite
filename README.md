# Phoenix Recruiting API (v3.1.2) — GitHub Repository

This repo is ready for **Cloud Run: Deploy from repository**. You can use either **Buildpacks** (Procfile) or **Dockerfile**.
Default path is **Buildpacks** via `Procfile`.

## Layout
- `application.py` — FastAPI app (`application:app`)
- `scraping/`, `utils/` — modules with `__init__.py` for clean imports
- `Procfile` — start command for buildpacks: `uvicorn application:app --port $PORT`
- `requirements.txt` — pinned
- `Dockerfile` + `start.sh` — if you choose Docker builds
- `.github/workflows/cloud-run.yaml` — optional GitHub Actions example (disabled by default)

## Deploy from GitHub (Buildpacks)
1. Cloud Run → **Create Service** → **Deploy from repository**
2. Select this GitHub repo + branch
3. Build type: **Buildpack**
4. No start command needed (Procfile is used)
5. Variables (optional): `PYTHONFAULTHANDLER=1`
6. **Create**

## Deploy from GitHub (Dockerfile)
1. Cloud Run → **Create Service** → **Deploy from repository**
2. Select repo; Build type: **Dockerfile**
3. **Create**

## Endpoints
- `GET /` → `{"ok": true}`
- `GET /health` → health/version
- `GET /diag/ping` → external reachability check
- `GET /discover?sport=football&region=West&cache_hours=1&diag=true`
- `POST /matches` (JSON) → sorted list with propensity & final score
- `POST /search` (JSON) → scrape known roster URL
- `POST /webflow-submit` (form)

## Notes
- JUCO (NJCAA) is **excluded by default**. Use `include_njcaa=true` to include.
- Discovery results are cached per (sport, region/states, flags) for `cache_hours` (default 24h).
- Cache is **in-memory per instance**. Use `/cache/stats` and `/cache/clear` for visibility/control.

# Phoenix Recruiting API (v3.1.3) — GitHub Repository

Ready for Cloud Run **Deploy from repository**.
- Buildpacks: uses `Procfile`
- Dockerfile: uses shell-form `CMD` so `$PORT` expands

## Endpoints
- `GET /` → `{"ok": true}`
- `GET /health` → version/health
- `GET /diag/ping` → egress test
- `GET /discover?sport=football&region=West&cache_hours=1&diag=true`
- `POST /matches` JSON: `{"sport":"football","position":"RB","class_level":"Senior","region":"West"}`
- `POST /search`
- `POST /webflow-submit` (form)

## Deploy (Buildpacks)
Cloud Run → Create service → Deploy from repository → Buildpack → Create.

## Deploy (Dockerfile)
Cloud Run → Create service → Deploy from repository → Dockerfile → Create.

## Notes
- JUCO is excluded by default (`include_njcaa=false`) — pass `include_njcaa=true` to include.
- Discovery cached per (sport, region/states, flags) for `cache_hours` (default 24h).
- Cache is in-memory per instance.

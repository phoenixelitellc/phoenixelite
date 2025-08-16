
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os

APP_VERSION = os.getenv("APP_VERSION", "3.2.0")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

from scraping.async_scraper import AsyncScraper
from scraping.discovery import discover_programs, discovery_cache, rebuild_index
from utils.scoring import calculate_recruiting_propensity, final_match_score

app = FastAPI(title="Phoenix Recruiting API", version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
scraper = AsyncScraper()

class MatchesRequest(BaseModel):
    sport: str
    position: str
    class_level: str
    region: Optional[str] = None
    states: Optional[List[str]] = None
    debug: Optional[bool] = False

def _meta(d: dict) -> dict:
    d.setdefault("_meta", {})["app_version"] = APP_VERSION
    return d

@app.get("/")
async def root(): 
    return _meta({"ok": True})

@app.get("/health")
async def health(): 
    return _meta({"status":"ok"})

@app.get("/cache/stats")
async def cache_stats(): 
    return _meta(discovery_cache.stats())

@app.get("/cache/clear")
async def cache_clear_get(): 
    discovery_cache.clear(); 
    return _meta({"ok": True})

@app.post("/cache/clear")
async def cache_clear_post(): 
    discovery_cache.clear(); 
    return _meta({"ok": True})

@app.post("/rebuild-index")
async def rebuild_index_endpoint(
    sport: str,
    region: Optional[str] = None,
    states: Optional[str] = None,
    sources: str = "governing,vendors,wiki",
    include_diii: bool = False,
    include_njcaa: bool = False,
    cache_hours: Optional[float] = None,
    diag: bool = False,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
):
    if ADMIN_TOKEN and x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    states_list = [x.strip().upper() for x in states.split(",")] if states else None
    payload = await rebuild_index(
        sport=sport, region=region, states=states_list, sources=sources,
        include_diii=include_diii, include_njcaa=include_njcaa, cache_hours=cache_hours, diag=diag
    )
    return _meta(payload)

@app.get("/discover")
async def discover(
    sport: str,
    region: Optional[str] = None,
    state: Optional[str] = None,
    states: Optional[str] = None,
    sources: str = "governing,vendors,wiki",
    include_diii: bool = False,
    include_njcaa: bool = False,
    cache_hours: Optional[float] = None,
    diag: bool = False,
):
    states_list = [x.strip().upper() for x in states.split(",")] if states else ([state.strip().upper()] if state else None)
    res = await discover_programs(
        sport=sport, region=region, states=states_list, sources=sources,
        include_diii=include_diii, include_njcaa=include_njcaa, cache_hours=cache_hours, diag=diag
    )
    return _meta(res)

@app.post("/matches")
async def matches(
    req: MatchesRequest,
    sources: str = "governing,vendors,wiki",
    include_diii: bool = False,
    include_njcaa: bool = False,
    cache_hours: Optional[float] = None
):
    try:
        disc = await discover_programs(
            sport=req.sport, region=req.region, states=req.states, sources=sources,
            include_diii=include_diii, include_njcaa=include_njcaa, cache_hours=cache_hours, diag=req.debug or False
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    programs = disc.get("programs", [])
    if not programs: 
        raise HTTPException(status_code=404, detail="Could not discover roster URLs for that sport/region.")
    results=[]
    for p in programs:
        roster_url = p.get("roster_url")
        if not roster_url: 
            continue
        try:
            data = await scraper.scrape_school(roster_url, sport=req.sport)
        except Exception:
            continue
        players=data.get("players",[])
        if not players: 
            continue
        pos=req.position.strip().lower()
        filtered=[pl for pl in players if pos and pos in (pl.get("position","").lower())] or players
        propensity=calculate_recruiting_propensity(filtered)
        final = final_match_score(propensity, req.class_level)
        results.append({
            "school": p.get("school"), "state": p.get("state"),
            "association": p.get("association"), "division": p.get("division"),
            "source_url": data.get("source_url") or roster_url,
            "players_considered": len(filtered), "propensity": propensity, "final_score": final
        })
    if not results: 
        raise HTTPException(status_code=404, detail="No valid roster pages parsed for that sport/region.")
    results.sort(key=lambda x: x["final_score"], reverse=True)
    return _meta({
        "count": len(results),
        "results": results,
        "discovery": {
            "count": disc.get("count"),
            "states": disc.get("states"),
            "sport_slugs": disc.get("sport_slugs"),
            "sources_used": disc.get("sources_used"),
        }
    })

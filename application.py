from fastapi import FastAPI, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import aiohttp

print("Phoenix Recruiting API import OK (v3.1.3)", flush=True)

from scraping.async_scraper import AsyncScraper
from scraping.discovery import discover_programs, discovery_cache
from utils.scoring import calculate_graduation_year, calculate_recruiting_propensity, final_match_score

app = FastAPI(title="Phoenix Recruiting API", version="3.1.3")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
scraper = AsyncScraper()

class SearchRequest(BaseModel):
    url: Optional[str] = None
    school: Optional[str] = None
    sport: Optional[str] = None
    class_level: Optional[str] = None

class MatchesRequest(BaseModel):
    sport: str
    position: str
    class_level: str
    region: Optional[str] = None
    states: Optional[List[str]] = None
    debug: Optional[bool] = False

@app.get("/")
async def root(): return {"ok": True}

@app.get("/health")
async def health(): return {"status": "ok", "version": "3.1.3"}

@app.get("/diag/ping")
async def diag_ping():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://en.wikipedia.org/wiki/Main_Page") as r:
                return {"status": r.status}
    except Exception as e:
        return {"status": 0, "error": str(e)}

@app.get("/cache/stats")
async def cache_stats(): return discovery_cache.stats()

@app.post("/cache/clear")
async def cache_clear(): discovery_cache.clear(); return {"ok": True}

@app.get("/discover")
async def discover(
    sport: str,
    region: Optional[str] = None,
    state: Optional[str] = None,
    states: Optional[str] = None,
    include_diii: bool = False,
    include_njcaa: bool = False,
    cache_hours: Optional[float] = None,
    diag: bool = False,
):
    states_list = [x.strip().upper() for x in states.split(",")] if states else ([state.strip().upper()] if state else None)
    return await discover_programs(sport, region, states_list, include_diii, include_njcaa, cache_hours, diag)

@app.post("/matches")
async def matches(req: MatchesRequest, include_diii: bool = False, include_njcaa: bool = False, cache_hours: Optional[float] = None):
    try:
        disc = await discover_programs(req.sport, req.region, req.states, include_diii, include_njcaa, cache_hours, req.debug or False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    programs = disc.get("programs", [])
    if not programs: raise HTTPException(status_code=404, detail="Could not discover roster URLs for that sport/region.")
    results=[]
    for p in programs:
        roster_url = p.get("roster_url") or p.get("athletics_url")
        try:
            data = await scraper.scrape_school(roster_url, sport=req.sport)
        except Exception:
            data = {"players": [], "source_url": roster_url, "name": p.get("school")}
        players=data.get("players",[])
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
    results.sort(key=lambda x: x["final_score"], reverse=True)
    return {"count": len(results), "results": results,
            "discovery": {"count": disc.get("count"), "states": disc.get("states"), "sport_slugs": disc.get("sport_slugs")}}

@app.post("/search")
async def search(req: SearchRequest):
    if not req.url and not req.school:
        raise HTTPException(status_code=400, detail="Provide either 'url' or 'school'.")
    try:
        data = await scraper.scrape_school(req.url or req.school, sport=req.sport)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scrape error: {e}")
    if req.class_level: _ = calculate_graduation_year(req.class_level)
    score = calculate_recruiting_propensity(data.get("players", []))
    return {"name": data.get("name") or (req.school or "Unknown"),
            "players": data.get("players", []), "recruiting_score": score,
            "source_url": data.get("source_url")}

@app.post("/webflow-submit")
async def webflow_submit(school: str = Form(None), url: str = Form(None), sport: str = Form(None), class_level: str = Form(None)):
    try:
        data = await scraper.scrape_school(url or school, sport=sport)
        score = calculate_recruiting_propensity(data.get("players", []))
        grad_year = calculate_graduation_year(class_level) if class_level else None
        return {"ok": True, "school": data.get("name") or school, "players_found": len(data.get("players", [])),
                "recruiting_score": score, "graduation_year": grad_year, "source_url": data.get("source_url")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving matches: {e}")    


import re, os, time
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, urljoin
import aiohttp
from bs4 import BeautifulSoup
from utils.regions import REGION_STATES, REGION_SYNONYMS, STATE_NAMES, normalize_region

APP_VERSION = os.getenv("APP_VERSION", "3.2.0")
DEFAULT_DISCOVERY_CACHE_HOURS = float(os.getenv("DISCOVERY_CACHE_HOURS", "24"))

VENDOR_HOST_HINTS = (
    "sidearmsports.com","prestosports.com","wmt.digital","neulion","athleticsite",
    "athletics","sports","gohuskies","goeags","go","athletics.","athletics-"
)
ROSTER_PATH_HINTS = ("/sports/", "/roster", "/roster.aspx", "/roster?path=", "/team/roster")

class _Cache:
    def __init__(self):
        self.data = {}
        self.ts = {}
    def get(self, key:str, ttl_seconds:float):
        now=time.time()
        return self.data.get(key) if (key in self.ts and (now-self.ts[key])<ttl_seconds) else None
    def set(self, key:str, value:Any):
        self.data[key]=value; self.ts[key]=time.time()
    def stats(self)->Dict[str,Any]:
        now=time.time()
        return {"size":len(self.data), "entries":[{"key":k,"age_seconds":now-self.ts[k]} for k in list(self.data.keys())]}
    def clear(self): 
        self.data.clear(); self.ts.clear()

discovery_cache=_Cache()

def _sport_slugs(sport:str)->List[str]:
    SPORT_SLUGS = {
        "football": ["football","fb"],
        "mens basketball": ["mens-basketball","mbball","mbb"],
        "womens basketball": ["womens-basketball","wbball","wbb"],
        "mens soccer": ["mens-soccer","msoc"],
        "womens soccer": ["womens-soccer","wsoc"],
        "baseball": ["baseball","bsb"],
        "softball": ["softball","sb"],
        "womens volleyball": ["womens-volleyball","wvb","volleyball"],
    }
    if not sport: return SPORT_SLUGS["mens basketball"]
    s=sport.strip().lower()
    return SPORT_SLUGS.get(s,[re.sub(r"\s+","-",s)])

async def _fetch(session:aiohttp.ClientSession, url:str)->Tuple[int,str]:
    try:
        async with session.get(url) as resp:
            return resp.status, await resp.text()
    except Exception:
        return 0, ""

def _score_url_for_athletics(url:str)->int:
    u=urlparse(url)
    host=(u.netloc or "").lower()
    path=(u.path or "").lower()
    score=0
    if "wikipedia.org" in host: return -999
    if "athletic" in host or "athletic" in path or "sports" in host or "sports" in path: score+=5
    if any(v in host for v in VENDOR_HOST_HINTS): score+=4
    if any(h in path for h in ROSTER_PATH_HINTS): score+=3
    if host.endswith(".edu"): score+=1
    return score

def _best_external_link(el)->Optional[str]:
    candidates = []
    for a in el.find_all("a", href=True):
        href=a["href"]
        if not (href.startswith("http") or href.startswith("/wiki/")): 
            continue
        url = href if href.startswith("http") else ("https://en.wikipedia.org"+href)
        score=_score_url_for_athletics(url)
        if score>0:
            candidates.append((score, url))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]

async def _find_roster_link_on_page(session, page_url):
    status, html = await _fetch(session, page_url)
    if status != 200 or not html: return None
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        text=" ".join(a.get_text(" ", strip=True).split()).lower()
        if "roster" in text:
            return urljoin(page_url, a["href"])
    return None

async def _try_roster(session, base_url, slug):
    base = base_url.rstrip("/")
    probes = [
        f"{base}/sports/{slug}/roster",
        f"{base}/{slug}/roster",
        f"{base}/roster.aspx?path={slug}",
        f"{base}/sports/{slug}",
        f"{base}/{slug}",
    ]
    for cand in probes:
        status2, html2 = await _fetch(session, cand)
        if status2 == 200 and ("/roster" in cand.lower() or (html2 and "roster" in html2.lower())):
            return cand
    for sport_page in [f"{base}/sports/{slug}", f"{base}/{slug}"]:
        roster = await _find_roster_link_on_page(session, sport_page)
        if roster: return roster
    roster = await _find_roster_link_on_page(session, base)
    return roster

async def _enum_from_wikipedia(session, states:List[str])->List[Dict[str,Any]]:
    base="https://en.wikipedia.org/wiki/List_of_college_athletic_programs_in_{}"
    out=[]
    for st in states:
        url=base.format(STATE_NAMES[st].replace(' ','_'))
        status, html = await _fetch(session, url)
        if status != 200 or not html: 
            continue
        soup=BeautifulSoup(html,"html.parser")
        tables=soup.find_all("table", class_=lambda x: x and "wikitable" in x)
        for table in tables:
            rows = table.find_all("tr")
            for tr in rows[1:]:
                tds=tr.find_all("td")
                if not tds: continue
                name_cell=tds[0]
                assoc_text=" ".join(td.get_text(" ", strip=True) for td in tds[1:3]) if len(tds)>=3 else tr.get_text(" ", strip=True)
                assoc,division="",""
                if re.search(r"NJCAA", assoc_text, re.I): assoc="NJCAA"
                elif re.search(r"NAIA", assoc_text, re.I): assoc="NAIA"
                elif re.search(r"NCAA", assoc_text, re.I):
                    assoc="NCAA"; m=re.search(r"Division\s+(I|II|III)", assoc_text, re.I)
                    if m: division=f"Division {m.group(1).upper()}"
                athletics=_best_external_link(name_cell) or _best_external_link(tr)
                school_wiki=None
                a=name_cell.find("a", href=True)
                if a:
                    href=a["href"]
                    if href.startswith("http") or href.startswith("/wiki/"):
                        school_wiki = href if href.startswith("http") else ("https://en.wikipedia.org"+href)
                out.append({
                    "school": name_cell.get_text(" ", strip=True),
                    "state": st, "association": assoc or None, "division": division or None,
                    "athletics_url": athletics, "school_wiki": school_wiki
                })
    return out

async def _resolve_athletics_from_school_page(session, school_page_url:str)->Optional[str]:
    status, html = await _fetch(session, school_page_url)
    if status != 200 or not html: return None
    soup = BeautifulSoup(html, "html.parser")
    candidates=[]
    for a in soup.find_all("a", href=True):
        text=" ".join(a.get_text(" ", strip=True).split()).lower()
        href=a["href"]
        abs_url = urljoin(school_page_url, href)
        score=_score_url_for_athletics(abs_url)
        if ("athletic" in text or "athletics" in text or "sports" in text or score>=5):
            candidates.append((score, abs_url))
    if not candidates: return None
    candidates.sort(reverse=True)
    return candidates[0][1]

async def _resolve_school_wiki_to_links(session, school_wiki_url:str)->Tuple[Optional[str], Optional[str]]:
    status, html = await _fetch(session, school_wiki_url)
    if status != 200 or not html: return None, None
    soup = BeautifulSoup(html, "html.parser")
    links=[]
    box = soup.find("table", class_=lambda x: x and "infobox" in x)
    if box:
        links.extend([a["href"] for a in box.find_all("a", href=True)])
    links.extend([a["href"] for a in soup.find_all("a", href=True)])
    clean=[]
    for href in links:
        if href.startswith("/wiki/") or href.startswith("http"):
            url = href if href.startswith("http") else ("https://en.wikipedia.org"+href)
            if "wikipedia.org" in url: 
                continue
            clean.append(url)
    if not clean: return None, None
    best_ath=None; best_site=None; best_score=-999
    for url in clean:
        score=_score_url_for_athletics(url)
        if score>best_score:
            best_score=score; best_ath=url
        if (best_site is None) or urlparse(url).netloc.endswith(".edu"):
            best_site=url
    return best_ath, best_site

async def _pipeline_resolve_athletics(session, rec:Dict[str,Any])->Optional[str]:
    if rec.get("athletics_url"):
        return rec["athletics_url"]
    if rec.get("school_wiki"):
        ath, site = await _resolve_school_wiki_to_links(session, rec["school_wiki"])
        if ath: 
            return ath
        if site:
            ath2 = await _resolve_athletics_from_school_page(session, site)
            if ath2:
                return ath2
    return None

async def _maybe_roster_url(session, athletics_url:str, slugs:List[str])->Optional[str]:
    for slug in slugs:
        ru = await _try_roster(session, athletics_url, slug)
        if ru: return ru
    return None

def _filter_association(rec:Dict[str,Any], include_diii:bool, include_njcaa:bool)->bool:
    assoc = (rec.get("association") or "").upper()
    division = (rec.get("division") or "").upper()
    if assoc == "NCAA" and division == "DIVISION III" and not include_diii:
        return False
    if assoc == "NJCAA" and not include_njcaa:
        return False
    return True

async def _enum_programs(session, states:List[str], sources:List[str])->List[Dict[str,Any]]:
    # For now, "governing" uses state lists (Wikipedia) as a stable seed. 
    # We keep a placeholder to add NCAA/NAIA/NJCAA APIs later.
    records=[]
    if "governing" in sources or "wiki" in sources:
        records.extend(await _enum_from_wikipedia(session, states))
    # ESPN enumeration stub (optional): currently off unless explicitly included; not required for correctness.
    # If added in future, records += await _enum_from_espn(...)
    return records

async def discover_programs(
    sport:str, region:Optional[str]=None, states:Optional[List[str]]=None, sources:str="governing,vendors,wiki",
    include_diii:bool=False, include_njcaa:bool=False, cache_hours:Optional[float]=None, diag:bool=False
)->Dict[str,Any]:
    slugs=_sport_slugs(sport)
    if states: 
        states=[s.strip().upper() for s in states if s.strip()]
    else:
        r=normalize_region(region) if region else ""
        if not r: raise ValueError("Provide a valid region or states list")
        states=REGION_STATES[r]
    srcs=[s.strip().lower() for s in sources.split(",") if s.strip()]
    key="{}::disc::{}::{}::diii={}::njcaa={}::src={}".format(
        APP_VERSION, ",".join(states), ",".join(slugs), include_diii, include_njcaa, ",".join(sorted(srcs))
    )
    ttl=(cache_hours if cache_hours is not None else DEFAULT_DISCOVERY_CACHE_HOURS)*3600.0
    cached=discovery_cache.get(key, ttl)
    if cached is not None:
        return {"count": len(cached['programs']), "from_cache": True, **cached}
    headers={"User-Agent":"Mozilla/5.0","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    conn=aiohttp.TCPConnector(ssl=False, limit=10)
    programs=[]; diag_fetch=[]
    async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=30), headers=headers) as session:
        # 1) Enumerate candidate schools (governing/wiki)
        records = await _enum_programs(session, states, srcs)
        # 2) Resolve athletics domains (vendors/homepage/wiki-derivations)
        for rec in records:
            if not _filter_association(rec, include_diii, include_njcaa): 
                continue
            athletics = await _pipeline_resolve_athletics(session, rec)
            if not athletics:
                continue
            roster_url = await _maybe_roster_url(session, athletics, slugs)
            if not roster_url:
                continue
            programs.append({
                "school": rec["school"], "state": rec["state"],
                "association": rec.get("association"), "division": rec.get("division"),
                "athletics_url": athletics, "roster_url": roster_url
            })
    payload={"programs":programs,"states":states,"sport_slugs":slugs,"sources_used":srcs,"diag":diag_fetch if diag else None}
    if programs: discovery_cache.set(key,payload)
    return {"count":len(programs),"from_cache":False, **payload}

async def rebuild_index(
    sport:str, region:Optional[str]=None, states:Optional[List[str]]=None, sources:str="governing,vendors,wiki",
    include_diii:bool=False, include_njcaa:bool=False, cache_hours:Optional[float]=None, diag:bool=False
)->Dict[str,Any]:
    # Force a fresh discover and cache the result
    res = await discover_programs(
        sport=sport, region=region, states=states, sources=sources,
        include_diii=include_diii, include_njcaa=include_njcaa, cache_hours=0, diag=diag
    )
    return res

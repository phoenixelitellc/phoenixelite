import re, os, time
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, urljoin
import aiohttp
from bs4 import BeautifulSoup

APP_VERSION = os.getenv("APP_VERSION", "3.1.5a")
DEFAULT_DISCOVERY_CACHE_HOURS = float(os.getenv("DISCOVERY_CACHE_HOURS", "24"))

SPORT_SLUGS: Dict[str, List[str]] = {
    "football": ["football","fb"],
    "mens basketball": ["mens-basketball","mbball","mbb"],
    "womens basketball": ["womens-basketball","wbball","wbb"],
    "mens soccer": ["mens-soccer","msoc"],
    "womens soccer": ["womens-soccer","wsoc"],
    "baseball": ["baseball","bsb"],
    "softball": ["softball","sb"],
    "womens volleyball": ["womens-volleyball","wvb","volleyball"],
}

REGION_STATES: Dict[str, List[str]] = {
    "west": ["AK","AZ","CA","CO","HI","ID","MT","NV","NM","OR","UT","WA","WY"],
    "midwest": ["IL","IN","IA","KS","MI","MN","MO","NE","ND","OH","SD","WI"],
    "south": ["AL","AR","DC","DE","FL","GA","KY","LA","MD","MS","NC","OK","SC","TN","TX","VA","WV"],
    "northeast": ["CT","ME","MA","NH","NJ","NY","PA","RI","VT"],
}
REGION_SYNONYMS={"pnw":"west","west coast":"west","pacific northwest":"west","southwest":"west","southeast":"south","mid-west":"midwest","north east":"northeast","north-east":"northeast"}
STATE_NAMES={"AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California","CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi","MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming","DC":"District of Columbia"}

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
    def clear(self): self.data.clear(); self.ts.clear()

discovery_cache=_Cache()

def _normalize_region(region: Optional[str]) -> Optional[str]:
    if not region: return None
    r=REGION_SYNONYMS.get(region.strip().lower(), region.strip().lower())
    return r if r in REGION_STATES else None

def _sport_slugs(sport:str)->List[str]:
    if not sport: return SPORT_SLUGS["mens basketball"]
    s=sport.strip().lower()
    return SPORT_SLUGS.get(s,[re.sub(r"\s+","-",s)])

async def _fetch(session:aiohttp.ClientSession, url:str)->Tuple[int,str]:
    try:
        async with session.get(url) as resp:
            return resp.status, await resp.text()
    except Exception:
        return 0, ""

VENDOR_HOST_HINTS = ("sidearmsports.com","prestosports.com","wmt.digital","athletics","sports")
ROSTER_PATH_HINTS = ("/sports/", "/roster", "/roster.aspx", "/roster?path=")

def _best_external_link(cell:BeautifulSoup)->Optional[str]:
    candidates = []
    for a in cell.find_all("a", href=True):
        href = a["href"]
        if "wikipedia.org" in href:
            continue
        u = urlparse(href)
        host = (u.netloc or "").lower()
        path = (u.path or "").lower()
        score = 0
        if "athletics" in host or "athletics" in path or "sports" in host or "sports" in path:
            score += 5
        if any(v in host for v in VENDOR_HOST_HINTS):
            score += 4
        if any(h in path for h in ROSTER_PATH_HINTS):
            score += 3
        if host.endswith(".edu"):
            score += 1
        candidates.append((score, href))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]

def _abs_wiki(url:str)->str:
    if url.startswith("/wiki/"):
        return "https://en.wikipedia.org" + url
    return url

def _pick_school_wiki(cell:BeautifulSoup)->Optional[str]:
    a = cell.find("a", href=True)
    if not a: return None
    href=a["href"]
    if href.startswith("http") or href.startswith("/wiki/"):
        return _abs_wiki(href)
    return None

async def _resolve_website_from_school_wiki(session:aiohttp.ClientSession, school_wiki_url:str)->Optional[str]:
    status, html = await _fetch(session, school_wiki_url)
    if status != 200 or not html: return None
    soup = BeautifulSoup(html, "html.parser")
    box = soup.find("table", class_=lambda x: x and "infobox" in x)
    if box:
        for a in box.find_all("a", href=True):
            href=a["href"]
            if href.startswith("http") and "wikipedia.org" not in href:
                if urlparse(href).netloc.endswith(".edu"):
                    return href
    for a in soup.find_all("a", href=True):
        href=a["href"]
        if href.startswith("http") and "wikipedia.org" not in href:
            if urlparse(href).netloc.endswith(".edu"):
                return href
    return None

async def _guess_athletics_from_homepage(session:aiohttp.ClientSession, website_url:str)->Optional[str]:
    status, html = await _fetch(session, website_url)
    if status != 200 or not html: return None
    soup = BeautifulSoup(html, "html.parser")
    candidates=[]
    for a in soup.find_all("a", href=True):
        text=" ".join(a.get_text(" ", strip=True).split()).lower()
        href=a["href"]
        href_l=href.lower()
        if ("athletic" in text or "athletics" in text or "sports" in text or "athletic" in href_l or "athletics" in href_l or "sports" in href_l):
            abs_url = urljoin(website_url, href)
            u = urlparse(abs_url)
            if "wikipedia.org" in abs_url: 
                continue
            score = 0
            if any(v in (u.netloc or "").lower() for v in VENDOR_HOST_HINTS): score += 3
            if any(h in (u.path or "").lower() for h in ROSTER_PATH_HINTS): score += 2
            if "athletics" in (u.netloc or "").lower() or "athletics" in (u.path or "").lower(): score += 2
            candidates.append((score, abs_url))
    if not candidates: return None
    candidates.sort(reverse=True)
    return candidates[0][1]

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
    return None

async def discover_programs(sport:str, region:Optional[str]=None, states:Optional[List[str]]=None,
                            include_diii:bool=False, include_njcaa:bool=False,
                            cache_hours:Optional[float]=None, diag:bool=False)->Dict[str,Any]:
    slugs=_sport_slugs(sport)
    if states: states=[s.strip().upper() for s in states if s.strip()]
    else:
        r=_normalize_region(region) if region else None
        if not r: raise ValueError("Provide a valid region or states list")
        states=REGION_STATES[r]
    key=f"{APP_VERSION}::disc::{','.join(states)}::{','.join(slugs)}::diii={include_diii}::njcaa={include_njcaa}"
    ttl=(cache_hours if cache_hours is not None else DEFAULT_DISCOVERY_CACHE_HOURS)*3600.0
    cached=discovery_cache.get(key, ttl)
    if cached is not None:
        return {"count": len(cached['programs']), "from_cache": True, **cached}
    base="https://en.wikipedia.org/wiki/List_of_college_athletic_programs_in_{}"
    headers={"User-Agent":"Mozilla/5.0","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    conn=aiohttp.TCPConnector(ssl=False, limit=10)
    programs=[]; diag_fetch=[]
    async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=25), headers=headers) as session:
        for st in states:
            url=base.format(STATE_NAMES[st].replace(' ','_'))
            status,html=await _fetch(session,url)
            if diag: diag_fetch.append({"state":st,"status":status,"url":url})
            if status!=200 or not html: continue
            soup=BeautifulSoup(html,"html.parser")
            tables=soup.find_all("table", class_=lambda x: x and "wikitable" in x)
            for table in tables:
                rows = table.find_all("tr")
                if not rows: continue
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
                    if not athletics:
                        school_wiki=_pick_school_wiki(name_cell)
                        if school_wiki:
                            website=await _resolve_website_from_school_wiki(session, school_wiki)
                            if website:
                                athletics=await _guess_athletics_from_homepage(session, website)
                    if not athletics: 
                        continue
                    if assoc=="NCAA" and division=="Division III" and not include_diii: continue
                    if assoc=="NJCAA" and not include_njcaa: continue
                    roster_url=None
                    for slug in slugs:
                        roster_url = await _try_roster(session, athletics, slug)
                        if roster_url: break
                    if not roster_url: continue
                    programs.append({
                        "school": name_cell.get_text(" ", strip=True),
                        "state": st,
                        "association": assoc or None,
                        "division": division or None,
                        "athletics_url": athletics,
                        "roster_url": roster_url,
                    })
    payload={"programs":programs,"states":states,"sport_slugs":slugs,"diag":{"fetch":diag_fetch} if diag else None}
    if programs: discovery_cache.set(key,payload)
    return {"count":len(programs),"from_cache":False, **payload}

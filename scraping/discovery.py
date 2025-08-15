import re, os, time
from typing import Dict, Any, List, Optional
import aiohttp
from bs4 import BeautifulSoup

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

async def _fetch(session:aiohttp.ClientSession, url:str):
    try:
        async with session.get(url) as resp:
            return resp.status, await resp.text()
    except Exception:
        return 0, ""

def _pick_external_link(cell:BeautifulSoup):
    for a in cell.find_all("a", href=True):
        href=a["href"]
        if href.startswith("http") and "wikipedia.org" not in href:
            return href
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
    key=f"disc::{','.join(states)}::{','.join(slugs)}::diii={include_diii}::njcaa={include_njcaa}"
    ttl=(cache_hours if cache_hours is not None else DEFAULT_DISCOVERY_CACHE_HOURS)*3600.0
    cached=discovery_cache.get(key, ttl)
    if cached is not None:
        return {"count": len(cached["programs"]), "from_cache": True, **cached}
    base="https://en.wikipedia.org/wiki/List_of_college_athletic_programs_in_{}"
    headers={"User-Agent":"Mozilla/5.0","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    conn=aiohttp.TCPConnector(ssl=False, limit=10)
    programs=[]; diag_fetch=[]
    async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=20), headers=headers) as session:
        for st in states:
            url=base.format(STATE_NAMES[st].replace(' ','_'))
            status,html=await _fetch(session,url)
            if diag: diag_fetch.append({"state":st,"status":status,"url":url})
            if status!=200 or not html: continue
            soup=BeautifulSoup(html,"html.parser")
            tables=soup.find_all("table", class_=lambda x: x and "wikitable" in x)
            for table in tables:
                for tr in table.find_all("tr")[1:]:
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
                    athletics=_pick_external_link(name_cell) or _pick_external_link(tr)
                    if not athletics: continue
                    if assoc=="NCAA" and division=="Division III" and not include_diii: continue
                    if assoc=="NJCAA" and not include_njcaa: continue
                    roster_url=None
                    for slug in slugs:
                        for cand in [athletics.rstrip("/")+f"/sports/{slug}/roster",
                                     athletics.rstrip("/")+f"/{slug}/roster",
                                     athletics.rstrip("/")+f"/roster.aspx?path={slug}"]:
                            status2, html2=await _fetch(session,cand)
                            if status2==200 and ("roster" in cand.lower() or (html2 and "roster" in html2.lower())):
                                roster_url=cand; break
                        if roster_url: break
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

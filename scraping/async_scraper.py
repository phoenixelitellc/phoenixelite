import re, time
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
import aiohttp
from bs4 import BeautifulSoup

CACHE_TTL_SECONDS = 30 * 24 * 3600

class _Cache:
    def __init__(self):
        self.data = {}
        self.ts = {}
    def get(self, key:str):
        if key in self.ts and (time.time()-self.ts[key]) < CACHE_TTL_SECONDS:
            return self.data.get(key)
        return None
    def set(self, key:str, value):
        self.data[key]=value; self.ts[key]=time.time()

_cache = _Cache()

class AsyncScraper:
    def __init__(self, timeout:int=20): self.timeout=timeout
    async def _get_html(self, url:str)->str:
        headers={"User-Agent":"Mozilla/5.0","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
        conn=aiohttp.TCPConnector(ssl=False, limit=10)
        async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=self.timeout), headers=headers) as s:
            async with s.get(url) as r:
                r.raise_for_status(); return await r.text()
    def _guess_name_from_url(self, url:str)->str:
        try:
            host=urlparse(url).netloc; core=(host.split('.')[-2] if len(host.split('.'))>=2 else host)
            return core.replace('-', ' ').replace('_', ' ').title()
        except Exception: return url
    def _extract_players_generic(self, soup:BeautifulSoup)->List[Dict[str,Any]]:
        players=[]; candidate_tables=soup.find_all("table"); roster_headers=("name","player","pos","position")
        best_table=None; best_score=0
        for table in candidate_tables:
            headers=[th.get_text(strip=True).lower() for th in table.find_all("th")]
            score=sum(any(h in cell for cell in headers) for h in roster_headers)
            if score>best_score: best_table, best_score = table, score
        if best_table and best_score>0:
            header_cells=[th.get_text(strip=True).lower() for th in best_table.find_all("th")]
            name_idx=pos_idx=None
            for i,h in enumerate(header_cells):
                if name_idx is None and ("name" in h or "player" in h): name_idx=i
                if pos_idx  is None and ("pos" in h or "position" in h): pos_idx=i
            for tr in best_table.find_all("tr"):
                cells=[td.get_text(" ", strip=True) for td in tr.find_all(["td"])]
                if not cells: continue
                name=cells[name_idx] if name_idx is not None and name_idx<len(cells) else ""
                pos =cells[pos_idx]  if pos_idx  is not None and pos_idx <len(cells) else ""
                if not name or len(name)<2 or "pronunciation" in name.lower(): continue
                players.append({"name":name,"position":pos,"seasons":[]})
        if not players:
            cards=soup.select("[class*='roster'], [class*='player'], [class*='athlete']")
            for card in cards:
                text=" ".join(card.stripped_strings)
                maybe=re.split(r"\s{2,}| \| | - ", text)
                if maybe and len(maybe[0])>2:
                    name=maybe[0].strip()
                    m=re.search(r"\b(G|F|C|GK|MF|FW|DB|RB|LB|WR|QB|TE|DL|OL|S|MB|OH|L|DS)\b", text)
                    pos=m.group(0) if m else ""
                    if "powered by" in name.lower(): continue
                    players.append({"name":name,"position":pos,"seasons":[]})
        unique, seen = [], set()
        for p in players:
            key=(p["name"].lower(), p.get("position"," ").lower())
            if key not in seen: seen.add(key); unique.append(p)
        return unique
    async def scrape_school(self, identifier:str, sport:Optional[str]=None)->Dict[str,Any]:
        if not identifier: raise ValueError("Missing school identifier or URL")
        if not re.match(r"^https?://", identifier):
            raise ValueError("Expected absolute roster URL")
        url=identifier; cached=_cache.get(url)
        if cached: return cached
        html=await self._get_html(url); soup=BeautifulSoup(html,"html.parser"); players=self._extract_players_generic(soup)
        result={"name":self._guess_name_from_url(url), "players":players, "source_url":url}
        _cache.set(url,result); return result

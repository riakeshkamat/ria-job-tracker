"""Documented public feeds only. No login scraping or anti-bot workarounds."""
import asyncio
import html
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from bs4 import BeautifulSoup

from .domain import canonical_url, plain

PROVIDERS = {'greenhouse', 'ashby', 'lever', 'github'}
ATS = PROVIDERS - {'github'}


def validate_source(provider, slug):
    if provider not in PROVIDERS:
        raise ValueError('Choose Greenhouse, Ashby, Lever, or GitHub')
    pattern = r'[\w.-]+/[\w.-]+' if provider == 'github' else r'[\w.-]+'
    if not re.fullmatch(pattern, slug, flags=re.ASCII) or '..' in slug:
        raise ValueError('Invalid employer board identifier or owner/repository')


def board_from_url(url):
    try:
        p = urlsplit(html.unescape(url))
        parts = [unquote(x) for x in p.path.split('/') if x]
        host = (p.hostname or '').lower()
        provider = ('greenhouse' if host in {'boards.greenhouse.io','job-boards.greenhouse.io'} else
                    'ashby' if host == 'jobs.ashbyhq.com' else
                    'lever' if host == 'jobs.lever.co' else None)
        if provider and parts:
            if provider=='greenhouse' and parts[0]=='embed':
                from urllib.parse import parse_qs
                token=parse_qs(p.query).get('for',[''])[0]
                validate_source(provider,token)
                return provider,token
            validate_source(provider,parts[0])
            return provider,parts[0]
    except (ValueError, IndexError):
        pass
    return None


class Fetcher:
    def __init__(self, client):
        self.client = client

    async def get(self, url):
        for attempt in range(3):
            try:
                response = await self.client.get(url, follow_redirects=False)
                if response.status_code in (429,500,502,503,504) and attempt < 2:
                    delay = response.headers.get('retry-after', str(2**attempt))
                    await asyncio.sleep(min(10, float(delay)) if delay.replace('.','',1).isdigit() else 2**attempt)
                    continue
                response.raise_for_status()
                if len(response.content) > 50_000_000:
                    raise ValueError('Source response exceeds the collection size limit')
                return response
            except (httpx.TimeoutException,httpx.NetworkError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)
        raise RuntimeError('Source could not be fetched')

    async def collect(self, source):
        provider, slug = source['provider'],source['slug']
        validate_source(provider,slug)
        if provider == 'github':
            response = await self.get(f'https://raw.githubusercontent.com/{slug}/HEAD/README.md')
            return await asyncio.to_thread(parse_github,response.text,source['name']), []
        if provider == 'greenhouse':
            data = (await self.get(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true')).json()
            if not isinstance(data,dict) or not isinstance(data.get('jobs'),list):
                raise ValueError('Greenhouse response has changed; snapshot rejected')
            rows = data['jobs']
            if data.get('meta',{}).get('total',len(rows)) != len(rows):
                raise ValueError('Incomplete Greenhouse snapshot')
            return await asyncio.to_thread(lambda:[greenhouse(j,source) for j in rows if j.get('internal_job_id') is not None]), []
        if provider == 'ashby':
            data = (await self.get(f'https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true')).json()
            if not isinstance(data,dict) or not isinstance(data.get('jobs'),list):
                raise ValueError('Ashby response has changed; snapshot rejected')
            return await asyncio.to_thread(lambda:[ashby(j,source) for j in data['jobs'] if j.get('isListed') is True]), []
        rows = []
        for page in range(100):
            batch = (await self.get(f'https://api.lever.co/v0/postings/{slug}?mode=json&skip={page*100}&limit=100')).json()
            if not isinstance(batch,list):
                raise ValueError('Lever response has changed; snapshot rejected')
            rows.extend(batch)
            if len(batch)<100:
                return await asyncio.to_thread(lambda:[lever(j,source) for j in rows]), []
        raise ValueError('Lever pagination limit reached; partial snapshot rejected')


def greenhouse(j, source):
    return dict(external_id=str(j['id']), title=j['title'], company=source['name'],
                location=(j.get('location') or {}).get('name',''), country='',
                description=plain(html.unescape(j.get('content',''))), apply_url=j['absolute_url'],
                # updated_at is NOT the original posting date.
                posted_at=j.get('first_published'))


def ashby(j,source):
    secondary = j.get('secondaryLocations') or []
    locations = [j.get('location','')]+[s.get('location','') for s in secondary]
    countries = [((j.get('address') or {}).get('postalAddress') or {}).get('addressCountry','')]
    countries += [(s.get('address') or {}).get('addressCountry','') for s in secondary]
    country = 'US' if any(c in ('US','USA','United States') for c in countries) else next((c for c in countries if c),'')
    return dict(external_id=j.get('id') or j['jobUrl'], title=j['title'], company=source['name'],
                location=' · '.join(x for x in locations if x),country=country,
                description=j.get('descriptionPlain') or plain(j.get('descriptionHtml','')),
                apply_url=j.get('applyUrl') or j['jobUrl'], posted_at=j.get('publishedAt'))


def lever(j,source):
    categories = j.get('categories') or {}
    description = plain(j.get('description','')) + '\n' + '\n'.join(
        plain(x.get('text',''))+'\n'+plain(x.get('content','')) for x in (j.get('lists') or []))
    description += '\n' + plain(j.get('additional',''))
    return dict(external_id=j['id'], title=j['text'], company=source['name'], location=categories.get('location') or '',
                country=j.get('country') or '', description=description, apply_url=j.get('applyUrl') or j['hostedUrl'],
                posted_at=None)


def parse_github(markdown, source_name):
    """Handle HTML and Markdown tables. A broken layout is a failure, never zero jobs."""
    soup = BeautifulSoup(markdown,'html.parser')
    rows = []
    for tr in soup.select('tr'):
        cells = tr.find_all('td',recursive=False)
        if len(cells)<3:
            continue
        links = [a['href'] for c in cells[2:] for a in c.select('a[href]')]
        link = next((u for u in links if '/apply' in u or board_from_url(u)),next((u for u in links if u.startswith('http')),None))
        rows.append(([c.get_text(' ',strip=True) for c in cells],link))
    for line in markdown.splitlines():
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells)<4 or re.fullmatch(r'[: -]+',cells[0]):
            continue
        candidates = re.findall(r'\]\((https?://[^\s)]+)\)|href=["\x27](https?://[^"\x27]+)', '|'.join(cells[3:]))
        links = [a or b for a,b in candidates]
        link = next((u for u in links if '/apply' in u or board_from_url(u)),next(iter(links),None))
        rows.append(([plain(re.sub(r'\[([^\]]+)\]\([^)]+\)',r'\1',c)) for c in cells],link))
    jobs, company = [], ''
    seen = set()
    for cells,link in rows:
        if cells[0] not in {'↳','↳️',''}:
            company = cells[0].replace('**','')
        if not link or '🔒' in ''.join(cells) or not company:
            continue
        try:
            url = canonical_url(html.unescape(link))
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        annotations = []
        if '🛂' in ''.join(cells): annotations.append('Sponsorship eligibility flagged by community list (🛂); employer confirmation required.')
        if '🇺🇸' in ''.join(cells): annotations.append('Community list reports US citizenship restriction; employer confirmation required.')
        # Community annotations are not employer evidence and cannot exclude a job.
        jobs.append(dict(external_id=url,apply_url=url,title=cells[1],company=company,
                         location=cells[2],country='',description='\n'.join(annotations),posted_at=None))
    if not jobs:
        raise ValueError('No recognizable open jobs in GitHub list; layout needs review')
    return jobs


def load_seeds(db):
    path = Path(__file__).resolve().parent.parent / 'sources.json'
    for source in json.loads(path.read_text()):
        validate_source(source['provider'],source['slug'])
        db.add_source(**source)

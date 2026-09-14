import argparse
import asyncio
import html
import json
import re
import httpx
import yaml
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from logging import getLogger, basicConfig, INFO


basicConfig(level=INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = getLogger(__name__)

# OpenReview rejects requests with a non-browser User-Agent, and rate-limits
# hard enough that its venues have to be fetched one at a time.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_openreview_lock = asyncio.Lock()
OPENREVIEW_REQUEST_DELAY = 3.0
OPENREVIEW_MAX_RETRIES = 4


def _normalize_paper_from_virtual(raw_paper: dict, conference: str, year: int) -> dict[str, Any]:
    authors_list = [
        author.get('fullname', '') for author in raw_paper.get('authors', [])
    ]

    normalized_data = {
        'id': raw_paper.get('uid', ''),
        'title': raw_paper.get('name', raw_paper.get('title', '')),
        'authors': authors_list,
        'abstract': raw_paper.get('abstract', ''),
        'topic': raw_paper.get('topic', ''),
        'conference': conference,
        'year': year,
        # Recent virtual sites ship both keys but leave one empty, so fall back on
        # the value rather than on the key being absent.
        'paper_url': raw_paper.get('paper_pdf_url') or raw_paper.get('paper_url') or ''
    }

    return normalized_data


def _normalize_paper_from_pmlr(raw_paper: dict, conference: str, year: int) -> dict[str, Any]:
    authors_list = []
    if 'author' in raw_paper:
        for author in raw_paper['author']:
            given = author.get('given', '')
            family = author.get('family', '')
            prefix = author.get('prefix', '')

            if prefix:
                full_name = f"{given} {prefix} {family}".strip()
            else:
                full_name = f"{given} {family}".strip()

            authors_list.append(full_name)

    normalized_data = {
        'id': raw_paper.get('id', ''),
        'title': raw_paper.get('title', ''),
        'authors': authors_list,
        'abstract': raw_paper.get('abstract', ''),
        'topic': '',  # PMLR doesn't have topic field
        'conference': conference,
        'year': year,
        'paper_url': raw_paper.get('PDF') or raw_paper.get('URL') or ''
    }

    return normalized_data


def _normalize_paper_from_acl_anthology(raw_paper: dict, conference: str, year: int) -> dict[str, Any]:
    authors_list = []
    if 'authors' in raw_paper:
        for author in raw_paper['authors']:
            first = author.get('first', '')
            last = author.get('last', '')
            full_name = f"{first} {last}".strip()
            if full_name:
                authors_list.append(full_name)

    paper_url = ''
    if 'url' in raw_paper and raw_paper['url']:
        paper_url = f"https://aclanthology.org/{raw_paper['url']}"

    normalized_data = {
        'id': raw_paper.get('id', ''),
        'title': raw_paper.get('title', ''),
        'authors': authors_list,
        'abstract': raw_paper.get('abstract', ''),
        'topic': '',  # ACL Anthology doesn't have topic field
        'conference': conference,
        'year': year,
        'paper_url': paper_url
    }

    return normalized_data


def _unwrap_openreview_value(field: Any) -> Any:
    """OpenReview API v2 wraps content values as {"value": ...}; v1 stores them directly."""
    if isinstance(field, dict) and 'value' in field:
        return field['value']
    return field


def _normalize_paper_from_openreview(raw_paper: dict, conference: str, year: int) -> dict[str, Any]:
    content = raw_paper.get('content', {})

    title = _unwrap_openreview_value(content.get('title', '')) or ''
    abstract = _unwrap_openreview_value(content.get('abstract', '')) or ''

    authors = _unwrap_openreview_value(content.get('authors', [])) or []
    if isinstance(authors, str):
        authors = [authors]
    authors_list = [a for a in authors if a]

    pdf = _unwrap_openreview_value(content.get('pdf', '')) or ''
    note_id = raw_paper.get('id', '')
    if pdf.startswith('http'):
        paper_url = pdf
    elif pdf.startswith('/'):
        paper_url = f"https://openreview.net{pdf}"
    elif note_id:
        paper_url = f"https://openreview.net/forum?id={note_id}"
    else:
        paper_url = ''

    # Workshops have no topic taxonomy, but authors supply keywords - close
    # enough to be worth keeping for filtering.
    keywords = _unwrap_openreview_value(content.get('keywords', [])) or []
    if isinstance(keywords, str):
        keywords = [keywords]
    topic = '; '.join(str(k).strip() for k in keywords if k)

    normalized_data = {
        'id': note_id,
        'title': title.strip() if isinstance(title, str) else title,
        'authors': authors_list,
        'abstract': abstract.strip() if isinstance(abstract, str) else abstract,
        'topic': topic,
        'conference': conference,
        'year': year,
        'paper_url': paper_url
    }

    return normalized_data


async def _fetch_papers_from_virtual_conference(
    client: httpx.AsyncClient, url: str
) -> list[dict[str, Any]]:
    logger.info(f"Fetching from {url}...")

    try:
        response = await client.get(url, timeout=30)
        response.raise_for_status()
        return response.json().get("results", [])

    except httpx.RequestError as e:
        logger.error(f"  -> Failed to fetch {url}: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"  -> Failed to parse JSON from {url}: {e}")
    return []


async def _fetch_papers_from_pmlr(
    client: httpx.AsyncClient, volume: str
) -> list[dict[str, Any]]:
    url = f"https://proceedings.mlr.press/{volume}/assets/bib/citeproc.yaml"
    logger.info(f"Fetching from {url}...")

    try:
        response = await client.get(url, timeout=60, follow_redirects=True)
        response.raise_for_status()

        papers = yaml.safe_load(response.text)

        if not papers or not isinstance(papers, list):
            logger.warning(f"  -> No valid data found in {url}")
            return []

        return papers

    except httpx.RequestError as e:
        logger.error(f"  -> Failed to fetch {url}: {e}")
    except yaml.YAMLError as e:
        logger.error(f"  -> Failed to parse YAML from {url}: {e}")
    except Exception as e:
        logger.error(f"  -> Unexpected error fetching {url}: {e}")
    return []


async def _fetch_papers_from_acl_anthology(
    client: httpx.AsyncClient, year: int, conference_id: str
) -> list[dict[str, Any]]:
    url = f"https://raw.githubusercontent.com/acl-org/acl-anthology/master/data/xml/{year}.{conference_id}.xml"
    logger.info(f"Fetching from {url}...")

    try:
        response = await client.get(url, timeout=60, follow_redirects=True)
        response.raise_for_status()

        root = ET.fromstring(response.text)
        papers = []

        for volume in root.findall('.//volume'):
            for paper in volume.findall('.//paper'):
                paper_data = {}

                paper_data['id'] = paper.get('id', '')

                title_elem = paper.find('title')
                if title_elem is not None:
                    title_text = ''.join(title_elem.itertext())
                    paper_data['title'] = title_text.strip()

                authors = []
                for author in paper.findall('author'):
                    first_elem = author.find('first')
                    last_elem = author.find('last')
                    first = first_elem.text if first_elem is not None and first_elem.text else ''
                    last = last_elem.text if last_elem is not None and last_elem.text else ''
                    authors.append({'first': first, 'last': last})
                paper_data['authors'] = authors

                abstract_elem = paper.find('abstract')
                if abstract_elem is not None:
                    abstract_text = ''.join(abstract_elem.itertext())
                    paper_data['abstract'] = abstract_text.strip()
                else:
                    paper_data['abstract'] = ''

                url_elem = paper.find('url')
                if url_elem is not None and url_elem.text:
                    paper_data['url'] = url_elem.text.strip()

                papers.append(paper_data)

        if not papers:
            logger.warning(f"  -> No papers found in {url}")
            return []

        logger.info(f"  -> Found {len(papers)} papers")
        return papers

    except httpx.RequestError as e:
        logger.error(f"  -> Failed to fetch {url}: {e}")
    except ET.ParseError as e:
        logger.error(f"  -> Failed to parse XML from {url}: {e}")
    except Exception as e:
        logger.error(f"  -> Unexpected error fetching {url}: {e}")
    return []


def _normalize_paper_from_europepmc(raw_paper: dict, conference: str, year: int) -> dict[str, Any]:
    authors_list = [
        author.get('fullName', '')
        for author in raw_paper.get('authorList', {}).get('author', [])
        if author.get('fullName')
    ]
    if not authors_list and raw_paper.get('authorString'):
        authors_list = [
            name.strip() for name in raw_paper['authorString'].rstrip('.').split(',')
            if name.strip()
        ]

    doi = raw_paper.get('doi', '')
    if doi:
        paper_url = f"https://doi.org/{doi}"
    elif raw_paper.get('id') and raw_paper.get('source'):
        paper_url = f"https://europepmc.org/article/{raw_paper['source']}/{raw_paper['id']}"
    else:
        paper_url = ''

    # Proceedings journals carry no topic taxonomy; author keywords are the
    # closest thing, same as the OpenReview workshops.
    keywords = raw_paper.get('keywordList', {}).get('keyword', [])
    topic = '; '.join(str(k).strip() for k in keywords if k)

    normalized_data = {
        'id': doi or raw_paper.get('id', ''),
        'title': raw_paper.get('title', '').rstrip('.'),
        'authors': authors_list,
        'abstract': raw_paper.get('abstractText', ''),
        'topic': topic,
        'conference': conference,
        'year': year,
        'paper_url': paper_url
    }

    return normalized_data


async def _fetch_papers_from_europepmc(
    client: httpx.AsyncClient, query: str
) -> list[dict[str, Any]]:
    """Fetch one proceedings issue (e.g. ISMB's Bioinformatics supplement, one
    PSB year) from the Europe PMC REST API. `resultType=core` includes the
    abstract and full author list; pagination uses cursorMark."""
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    logger.info(f"Fetching from Europe PMC: {query}...")

    papers: list[dict[str, Any]] = []
    cursor = "*"

    try:
        while True:
            params = {
                "query": query,
                "format": "json",
                "resultType": "core",
                "pageSize": 1000,
                "cursorMark": cursor,
            }
            response = await client.get(url, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()

            page = data.get("resultList", {}).get("result", [])
            if not page:
                break
            papers.extend(page)

            next_cursor = data.get("nextCursorMark")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

    except httpx.RequestError as e:
        logger.error(f"  -> Failed to fetch Europe PMC query {query!r}: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"  -> Failed to parse JSON for Europe PMC query {query!r}: {e}")
        return []

    # Proceedings issues also index front matter (prefaces, award profiles),
    # which is exactly the set of records without an abstract.
    articles = [p for p in papers if p.get('abstractText')]
    if len(articles) < len(papers):
        logger.info(f"  -> Dropped {len(papers) - len(articles)} abstract-less front-matter entries")

    logger.info(f"  -> Found {len(articles)} papers")
    return articles


async def _fetch_papers_from_openreview(
    client: httpx.AsyncClient, venue_id: str, api_version: int = 2
) -> list[dict[str, Any]]:
    """Fetch the accepted papers of one OpenReview venue.

    The obvious endpoint (`/notes?content.venueid=...`) answers anonymous
    requests with a 403 `ChallengeRequiredError` - it wants a JS browser
    challenge - but `/notes/search` is not behind that challenge. So the venue
    is enumerated through search (`query=*` matches every submission,
    `group=<venue_id>` scopes it) and the accepted papers are separated out
    here, since search also returns rejected and withdrawn submissions.
    """
    host = (
        "https://api2.openreview.net"
        if api_version == 2
        else "https://api.openreview.net"
    )
    search_url = f"{host}/notes/search"
    logger.info(f"Fetching from {search_url}?group={venue_id} (api v{api_version})...")

    notes: list[dict[str, Any]] = []
    offset = 0
    limit = 1000

    async with _openreview_lock:
        try:
            while True:
                params = {
                    "query": "*",
                    "group": venue_id,
                    "source": "forum",
                    "limit": limit,
                    "offset": offset,
                }
                data = await _openreview_get(client, search_url, params, venue_id)
                if data is None:
                    return []

                page = data.get("notes", [])
                if not page:
                    break

                notes.extend(page)

                if len(page) < limit:
                    break
                offset += limit
        except Exception as e:
            logger.error(f"  -> Unexpected error fetching {venue_id}: {e}")
            return []

    accepted = [
        note
        for note in notes
        if _unwrap_openreview_value(note.get("content", {}).get("venueid")) == venue_id
    ]

    if not accepted:
        logger.warning(
            f"  -> No accepted papers found for venue {venue_id} "
            f"({len(notes)} submissions seen)"
        )
        return []

    logger.info(f"  -> Found {len(accepted)} accepted papers of {len(notes)} submissions")
    return accepted


async def _openreview_get(
    client: httpx.AsyncClient, url: str, params: dict[str, Any], venue_id: str
) -> dict[str, Any] | None:
    """One rate-limit-aware OpenReview request. Returns None once it gives up."""
    for attempt in range(1, OPENREVIEW_MAX_RETRIES + 1):
        try:
            response = await client.get(
                url,
                params=params,
                headers={"User-Agent": BROWSER_USER_AGENT},
                timeout=60,
                follow_redirects=True,
            )
            if response.status_code in (429, 403, 503):
                wait = OPENREVIEW_REQUEST_DELAY * 2 ** attempt
                logger.warning(
                    f"  -> {venue_id}: HTTP {response.status_code}, "
                    f"retry {attempt}/{OPENREVIEW_MAX_RETRIES} in {wait:.0f}s"
                )
                await asyncio.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()
            await asyncio.sleep(OPENREVIEW_REQUEST_DELAY)
            return data

        except httpx.RequestError as e:
            logger.error(f"  -> Failed to fetch {venue_id}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"  -> Failed to parse JSON for {venue_id}: {e}")
            return None

    logger.error(f"  -> Gave up on {venue_id} after {OPENREVIEW_MAX_RETRIES} retries")
    return None


# --- DROPS (LIPIcs) -----------------------------------------------------------

def _drops_author_name(author: dict) -> str:
    given = (author.get('givenName') or '').strip()
    family = (author.get('familyName') or '').strip()
    if given or family:
        return f"{given} {family}".strip()
    # DROPS writes bare names as "Family, Given".
    name = (author.get('name') or '').strip()
    if ',' in name:
        family, given = [part.strip() for part in name.split(',', 1)]
        return f"{given} {family}".strip()
    return name


def _normalize_paper_from_drops(raw_paper: dict, conference: str, year: int) -> dict[str, Any]:
    authors = raw_paper.get('author', [])
    if isinstance(authors, dict):
        authors = [authors]
    authors_list = [name for name in (_drops_author_name(a) for a in authors) if name]

    identifier = raw_paper.get('identifier', '') or ''
    doi = identifier.replace('https://doi.org/', '')

    keywords = raw_paper.get('keywords', []) or []
    if isinstance(keywords, str):
        keywords = [keywords]
    topic = '; '.join(str(k).strip() for k in keywords if k)

    normalized_data = {
        'id': doi,
        'title': (raw_paper.get('headline') or raw_paper.get('name') or '').strip(),
        'authors': authors_list,
        # DROPS keeps the authors' hard line breaks (CRLF); normalize them.
        'abstract': re.sub(r'\r\n?', '\n', raw_paper.get('abstract') or '').strip(),
        'topic': topic,
        'conference': conference,
        'year': year,
        'paper_url': raw_paper.get('url') or (f"https://doi.org/{doi}" if doi else '')
    }

    return normalized_data


async def _fetch_papers_from_drops(
    client: httpx.AsyncClient, volume: int
) -> list[dict[str, Any]]:
    """Fetch one LIPIcs volume from DROPS (Schloss Dagstuhl's open-access server).

    The volume page embeds a schema.org JSON-LD `PublicationVolume` whose
    `hasPart` lists every article with title, authors, abstract and keywords,
    so a single request covers the whole proceedings. (DROPS also has an
    OAI-PMH endpoint, but it cannot be scoped to one volume.)
    """
    url = f"https://drops.dagstuhl.de/entities/volume/LIPIcs-volume-{volume}"
    logger.info(f"Fetching from {url}...")

    try:
        response = await client.get(
            url, timeout=60, follow_redirects=True,
            headers={"User-Agent": BROWSER_USER_AGENT},
        )
        response.raise_for_status()
    except httpx.RequestError as e:
        logger.error(f"  -> Failed to fetch {url}: {e}")
        return []
    except httpx.HTTPStatusError as e:
        logger.error(f"  -> Failed to fetch {url}: {e}")
        return []

    match = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', response.text, re.S
    )
    if not match:
        logger.error(f"  -> No JSON-LD block found in {url}")
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        logger.error(f"  -> Failed to parse JSON-LD from {url}: {e}")
        return []

    volume_entity = data.get('mainEntity', data)
    parts = volume_entity.get('hasPart', [])
    volume_name = volume_entity.get('name', '')

    papers = []
    for part in parts:
        if part.get('@type') != 'ScholarlyArticle':
            continue
        doi = (part.get('identifier') or '').replace('https://doi.org/', '')
        # Article DOIs end in ".<n>"; ".0" is the front matter and the DOI
        # without a suffix is the complete-volume PDF.
        suffix = doi.rsplit('.', 1)[-1] if '.' in doi else ''
        if not suffix.isdigit() or int(suffix) == 0:
            continue
        papers.append(part)

    if not papers:
        logger.warning(f"  -> No papers found in {url}")
        return []

    logger.info(f"  -> Found {len(papers)} papers in {volume_name or url}")
    return papers


# --- Crossref (Springer LNCS, ACM, IEEE, PACMPL) -------------------------------

CROSSREF_API = "https://api.crossref.org/works"
# A descriptive User-Agent gets Crossref's "polite" pool.
CROSSREF_USER_AGENT = (
    "airas-papers-db/1.0 (https://github.com/airas-org/airas-papers-db) httpx"
)
CROSSREF_ROWS = 1000
CROSSREF_PAPER_TYPES = {"proceedings-article", "book-chapter", "journal-article"}
CROSSREF_NON_PAPER_TITLE = re.compile(
    r"^\s*(Correction|Corrections|Erratum|Errata|Retraction Note)\b", re.I
)
# Crossref answers concurrent bursts with 429, so its requests are serialized.
CROSSREF_REQUEST_DELAY = 1.0
CROSSREF_MAX_RETRIES = 5
_crossref_lock = asyncio.Lock()

# Semantic Scholar fills in abstracts for publishers that do not deposit them
# with Crossref (ACM, IEEE). The anonymous batch endpoint is shared and
# rate-limited, so calls are serialized.
SEMANTIC_SCHOLAR_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
SEMANTIC_SCHOLAR_BATCH_SIZE = 500
SEMANTIC_SCHOLAR_REQUEST_DELAY = 1.5
SEMANTIC_SCHOLAR_MAX_RETRIES = 5
_semantic_scholar_lock = asyncio.Lock()


def _clean_jats_abstract(text: str) -> str:
    """Crossref abstracts are JATS XML fragments; reduce them to plain text."""
    if not text:
        return ''
    text = re.sub(r'<jats:title>.*?</jats:title>', ' ', text, flags=re.S)
    # Inline formulas carry both TeX and MathML; keep the TeX.
    text = re.sub(r'<mml:math.*?</mml:math>', ' ', text, flags=re.S)
    # Paragraph breaks are the only line breaks worth keeping; the XML's own
    # line wrapping inside a paragraph is noise.
    paragraph_break = '\x00'
    text = re.sub(r'</jats:p>', paragraph_break, text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(rf'\s*{paragraph_break}\s*', '\n', text).strip()
    return text


def _normalize_paper_from_crossref(raw_paper: dict, conference: str, year: int) -> dict[str, Any]:
    authors_list = []
    for author in raw_paper.get('author', []):
        given = (author.get('given') or '').strip()
        family = (author.get('family') or '').strip()
        full_name = f"{given} {family}".strip() or (author.get('name') or '').strip()
        if full_name:
            authors_list.append(full_name)

    titles = raw_paper.get('title') or ['']
    title = html.unescape(re.sub(r'\s+', ' ', titles[0])).strip()

    doi = raw_paper.get('DOI', '')

    normalized_data = {
        'id': doi,
        'title': title,
        'authors': authors_list,
        # `_abstract` is set by the Semantic Scholar fill-in when Crossref has
        # none; those can carry raw HTML too, so both go through the cleaner.
        'abstract': _clean_jats_abstract(raw_paper.get('_abstract') or raw_paper.get('abstract', '')),
        'topic': '',  # Crossref carries no per-paper topic taxonomy
        'conference': conference,
        'year': year,
        'paper_url': f"https://doi.org/{doi}" if doi else (raw_paper.get('URL') or '')
    }

    return normalized_data


def _crossref_item_matches(item: dict, spec: dict) -> bool:
    if item.get('type') not in CROSSREF_PAPER_TYPES:
        return False

    prefixes = spec.get('prefixes')
    if prefixes and not any(item.get('DOI', '').startswith(p) for p in prefixes):
        return False

    container_titles = item.get('container-title') or []
    if 'container_title' in spec and spec['container_title'] not in container_titles:
        return False
    if 'container_title_contains' in spec:
        needle = spec['container_title_contains'].lower()
        if not any(needle in ct.lower() for ct in container_titles):
            return False

    if 'issue' in spec and item.get('issue') != str(spec['issue']):
        return False
    if 'volume' in spec and item.get('volume') != str(spec['volume']):
        return False

    return True


async def _fill_abstracts_from_semantic_scholar(
    client: httpx.AsyncClient, items: list[dict], label: str
) -> None:
    """Look up abstracts by DOI for the items that have none, in place."""
    missing = [item for item in items if not item.get('abstract') and item.get('DOI')]
    if not missing:
        return

    filled = 0
    for start in range(0, len(missing), SEMANTIC_SCHOLAR_BATCH_SIZE):
        batch = missing[start:start + SEMANTIC_SCHOLAR_BATCH_SIZE]
        ids = [f"DOI:{item['DOI']}" for item in batch]

        async with _semantic_scholar_lock:
            results = None
            for attempt in range(1, SEMANTIC_SCHOLAR_MAX_RETRIES + 1):
                try:
                    response = await client.post(
                        SEMANTIC_SCHOLAR_BATCH_URL,
                        params={"fields": "abstract"},
                        json={"ids": ids},
                        timeout=60,
                    )
                    if response.status_code in (429, 503):
                        wait = SEMANTIC_SCHOLAR_REQUEST_DELAY * 2 ** attempt
                        logger.warning(
                            f"  -> {label}: Semantic Scholar HTTP {response.status_code}, "
                            f"retry {attempt}/{SEMANTIC_SCHOLAR_MAX_RETRIES} in {wait:.0f}s"
                        )
                        await asyncio.sleep(wait)
                        continue
                    if response.status_code == 400:
                        # "No valid paper ids given": none of the batch is indexed yet.
                        results = []
                        break
                    response.raise_for_status()
                    results = response.json()
                    break
                except (httpx.HTTPError, json.JSONDecodeError) as e:
                    logger.error(
                        f"  -> {label}: Semantic Scholar request failed: {type(e).__name__}: {e}"
                    )
                    break
            await asyncio.sleep(SEMANTIC_SCHOLAR_REQUEST_DELAY)

        if not isinstance(results, list):
            continue
        for item, result in zip(batch, results):
            abstract = (result or {}).get('abstract')
            if abstract:
                item['_abstract'] = abstract.strip()
                filled += 1

    logger.info(
        f"  -> {label}: filled {filled}/{len(missing)} missing abstracts from Semantic Scholar"
    )


async def _crossref_get(
    client: httpx.AsyncClient, params: dict[str, Any], label: str
) -> dict[str, Any] | None:
    """One serialized, rate-limit-aware Crossref request. Returns the
    response's `message` object, or None once it gives up."""
    async with _crossref_lock:
        for attempt in range(1, CROSSREF_MAX_RETRIES + 1):
            try:
                response = await client.get(
                    CROSSREF_API,
                    params=params,
                    headers={"User-Agent": CROSSREF_USER_AGENT},
                    timeout=60,
                )
                if response.status_code in (429, 503, 504):
                    wait = CROSSREF_REQUEST_DELAY * 2 ** attempt
                    logger.warning(
                        f"  -> {label}: Crossref HTTP {response.status_code}, "
                        f"retry {attempt}/{CROSSREF_MAX_RETRIES} in {wait:.0f}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                message = response.json().get("message", {})
                await asyncio.sleep(CROSSREF_REQUEST_DELAY)
                return message
            except httpx.RequestError as e:
                # Timeouts and dropped connections are transient; retry them.
                wait = CROSSREF_REQUEST_DELAY * 2 ** attempt
                logger.warning(
                    f"  -> {label}: Crossref {type(e).__name__}: {e}, "
                    f"retry {attempt}/{CROSSREF_MAX_RETRIES} in {wait:.0f}s"
                )
                await asyncio.sleep(wait)
                continue
            except httpx.HTTPStatusError as e:
                logger.error(f"  -> Failed to fetch {label} from Crossref: {e}")
                return None
            except json.JSONDecodeError as e:
                logger.error(f"  -> Failed to parse Crossref JSON for {label}: {e}")
                return None

    logger.error(f"  -> Gave up on {label} after {CROSSREF_MAX_RETRIES} Crossref retries")
    return None


async def _fetch_papers_from_crossref(
    client: httpx.AsyncClient, spec: dict, year: int, label: str
) -> list[dict[str, Any]]:
    """Enumerate one proceedings volume through the Crossref REST API.

    `spec` selects the volume in one of three ways:
      - `container_title`: exact book title (Springer LNCS proceedings deposit
        the conference name as the second container-title);
      - `container_title_contains`: substring of the proceedings title (ACM and
        IEEE, whose `event` metadata is inconsistent - CPP 2020 is filed under
        "POPL '20");
      - `issn` + `issue` (+ `volume`): a journal issue (PACMPL's POPL issue).
    `prefixes` restricts DOI prefixes (publishers), and `date_from` /
    `date_until` widen the publication-date window (PACMPL issues are dated
    the December before the conference). Crossref returns abstracts for
    Springer and PACMPL; the rest are filled in from Semantic Scholar.
    """
    date_from = spec.get('date_from', '{year}-01-01').format(year=year, prev_year=year - 1)
    date_until = spec.get('date_until', '{year}-12-31').format(year=year, prev_year=year - 1)

    filters = [f"from-pub-date:{date_from}", f"until-pub-date:{date_until}"]
    params: dict[str, Any] = {
        "rows": CROSSREF_ROWS,
        "select": "DOI,title,author,abstract,container-title,type,issue,volume,URL",
    }
    if 'container_title' in spec:
        filters.append(f"container-title:{spec['container_title']}")
    if 'container_title_contains' in spec:
        params["query.container-title"] = spec['container_title_contains']
    if 'issn' in spec:
        filters.append(f"issn:{spec['issn']}")
    # Repeated filters of the same name are OR-ed by Crossref.
    filters.extend(f"prefix:{prefix}" for prefix in spec.get('prefixes', []))
    params["filter"] = ",".join(filters)

    logger.info(f"Fetching from Crossref: {label} ({params['filter']})...")

    # A `query.*` search is a relevance-ranked search over everything the
    # filters admit (tens of thousands of records for a publisher-year), so it
    # is not paged through: the matching proceedings sit at the top of the
    # first page, which is far larger than any single proceedings volume.
    # (Deep paging with `cursor` drops the relevance ordering, so the single
    # page is requested without one.)
    single_page = 'container_title_contains' in spec

    items: list[dict[str, Any]] = []
    cursor = "*"
    while True:
        page_params = params if single_page else {**params, "cursor": cursor}
        message = await _crossref_get(client, page_params, label)
        if message is None:
            return []
        page = message.get("items", [])
        if not page:
            break
        items.extend(page)
        next_cursor = message.get("next-cursor")
        if single_page or len(page) < CROSSREF_ROWS or not next_cursor:
            break
        cursor = next_cursor

    papers = [item for item in items if _crossref_item_matches(item, spec)]
    if not papers:
        logger.warning(f"  -> No papers matched for {label} ({len(items)} records seen)")
        return []
    if single_page and len(papers) >= CROSSREF_ROWS // 2:
        logger.warning(
            f"  -> {label}: {len(papers)} matches on a single page; the search may be truncated"
        )

    # Crossref lists a title-less placeholder for a few ACM records, and
    # publishers register corrections/errata as chapters of their own.
    papers = [
        p for p in papers
        if p.get('title') and not CROSSREF_NON_PAPER_TITLE.match(p['title'][0])
    ]

    await _fill_abstracts_from_semantic_scholar(client, papers, label)

    without_abstract = sum(1 for p in papers if not (p.get('abstract') or p.get('_abstract')))
    logger.info(
        f"  -> Found {len(papers)} papers for {label}"
        + (f" ({without_abstract} without abstract)" if without_abstract else "")
    )
    return papers


def _save_json(data: list[dict[str, Any]], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(data)} items to {path}")


async def main():
    parser = argparse.ArgumentParser(description="Fetch conference paper metadata.")
    parser.add_argument(
        "--only",
        help="Comma-separated conference names; skip all others (default: fetch everything)",
    )
    args = parser.parse_args()

    PROJECT_ROOT = Path(__file__).parent.parent
    BASE_DATA_DIR = PROJECT_ROOT / "data"
    CONFIG_FILE = PROJECT_ROOT / "scripts" / "configs" / "conferences.jsonc"

    logger.info(f"Loading config from {CONFIG_FILE}...")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        conference_configs = json.load(f)

    if args.only:
        only_names = {name.strip() for name in args.only.split(",") if name.strip()}
        unknown = only_names - {c["name"] for c in conference_configs}
        if unknown:
            raise SystemExit(f"--only names not in config: {sorted(unknown)}")
        conference_configs = [c for c in conference_configs if c["name"] in only_names]
        logger.info(f"Restricted to {sorted(only_names)}")

    async with httpx.AsyncClient() as client:
        tasks = []

        for config in conference_configs:
            conf_name = config["name"]
            source_type = config.get("source_type", "virtual_conference")

            if source_type == "virtual_conference":
                for year in config["years"]:
                    url = config["url_template"].format(year=year)
                    task = asyncio.create_task(
                        _fetch_papers_from_virtual_conference(client, url)
                    )
                    tasks.append((task, conf_name, year, "virtual"))

            elif source_type == "pmlr":
                volumes = config.get("volumes", {})
                for year_str, volume in volumes.items():
                    year = int(year_str)
                    task = asyncio.create_task(
                        _fetch_papers_from_pmlr(client, volume)
                    )
                    tasks.append((task, conf_name, year, "pmlr"))

            elif source_type == "acl_anthology":
                conference_id = config.get("conference_id", conf_name)
                for year in config["years"]:
                    task = asyncio.create_task(
                        _fetch_papers_from_acl_anthology(client, year, conference_id)
                    )
                    tasks.append((task, conf_name, year, "acl_anthology"))

            elif source_type == "openreview":
                default_api_version = config.get("api_version", 2)
                venues = config.get("venues", {})
                for year_str, venue in venues.items():
                    year = int(year_str)
                    # A year maps either to a bare venue id, or to an object when
                    # that edition still lives on the older API (v1).
                    if isinstance(venue, dict):
                        venue_id = venue["id"]
                        api_version = venue.get("api_version", default_api_version)
                    else:
                        venue_id = venue
                        api_version = default_api_version
                    task = asyncio.create_task(
                        _fetch_papers_from_openreview(client, venue_id, api_version)
                    )
                    tasks.append((task, conf_name, year, "openreview"))

            elif source_type == "europepmc":
                queries = config.get("queries", {})
                for year_str, query in queries.items():
                    year = int(year_str)
                    task = asyncio.create_task(
                        _fetch_papers_from_europepmc(client, query)
                    )
                    tasks.append((task, conf_name, year, "europepmc"))

            elif source_type == "drops":
                volumes = config.get("volumes", {})
                for year_str, volume in volumes.items():
                    year = int(year_str)
                    task = asyncio.create_task(
                        _fetch_papers_from_drops(client, int(volume))
                    )
                    tasks.append((task, conf_name, year, "drops"))

            elif source_type == "crossref":
                # `match` is shared by every year; `year_overrides` patches it
                # per edition (CADE's book title carries its running number).
                base_match = config.get("match", {})
                overrides = config.get("year_overrides", {})
                for year in config["years"]:
                    spec = {**base_match, **overrides.get(str(year), {})}
                    task = asyncio.create_task(
                        _fetch_papers_from_crossref(client, spec, year, f"{conf_name} {year}")
                    )
                    tasks.append((task, conf_name, year, "crossref"))

        logger.info(f"\nFetching data from {len(tasks)} conference-year combinations...")
        results = await asyncio.gather(*(task for task, _, _, _ in tasks))

    total_papers = 0
    successful_fetches = 0
    skipped_fetches = 0  

    for (task, conf_name, year, source_type), raw_papers in zip(tasks, results):
        if not raw_papers:
            logger.warning(f"  -> No data found for {conf_name} {year}. Skipping.")
            skipped_fetches += 1    
            continue

        if source_type == "virtual":
            normalized_papers = [
                _normalize_paper_from_virtual(p, conference=conf_name, year=year)
                for p in raw_papers
            ]
        elif source_type == "pmlr":
            normalized_papers = [
                _normalize_paper_from_pmlr(p, conference=conf_name, year=year)
                for p in raw_papers
            ]
        elif source_type == "acl_anthology":
            normalized_papers = [
                _normalize_paper_from_acl_anthology(p, conference=conf_name, year=year)
                for p in raw_papers
            ]
        elif source_type == "openreview":
            normalized_papers = [
                _normalize_paper_from_openreview(p, conference=conf_name, year=year)
                for p in raw_papers
            ]
        elif source_type == "europepmc":
            normalized_papers = [
                _normalize_paper_from_europepmc(p, conference=conf_name, year=year)
                for p in raw_papers
            ]
        elif source_type == "drops":
            normalized_papers = [
                _normalize_paper_from_drops(p, conference=conf_name, year=year)
                for p in raw_papers
            ]
        elif source_type == "crossref":
            normalized_papers = [
                _normalize_paper_from_crossref(p, conference=conf_name, year=year)
                for p in raw_papers
            ]

        output_path = BASE_DATA_DIR / conf_name / f"{year}.json"
        _save_json(normalized_papers, output_path)

        total_papers += len(normalized_papers)
        successful_fetches += 1

    logger.info(f"\n{'='*60}")
    logger.info(f"Data update process completed!")                                                                                 
    logger.info(f"Total conference-year combinations: {len(tasks)}")                                                               
    logger.info(f"  - Successful: {successful_fetches}")                                                                           
    logger.info(f"  - Skipped: {skipped_fetches}")      
    logger.info(f"Total papers collected: {total_papers:,}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())

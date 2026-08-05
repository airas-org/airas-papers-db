import asyncio
import json
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


def _save_json(data: list[dict[str, Any]], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(data)} items to {path}")


async def main():
    PROJECT_ROOT = Path(__file__).parent.parent
    BASE_DATA_DIR = PROJECT_ROOT / "data"
    CONFIG_FILE = PROJECT_ROOT / "scripts" / "configs" / "conferences.jsonc"

    logger.info(f"Loading config from {CONFIG_FILE}...")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        conference_configs = json.load(f)

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

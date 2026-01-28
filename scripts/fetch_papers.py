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
        'paper_url': raw_paper.get('paper_pdf_url', raw_paper.get('paper_url', ''))
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
        'paper_url': raw_paper.get('PDF', raw_paper.get('URL', ''))
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

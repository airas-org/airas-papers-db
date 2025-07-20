import asyncio
import json
import httpx
from pathlib import Path
from typing import Any
from logging import getLogger, basicConfig, INFO, WARNING

from parsers.normalizer import normalize_paper

basicConfig(level=INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = getLogger(__name__)


async def _fetch_papers_from_url(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
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


def _save_json(data: list[dict[str, Any]], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(data)} items to {path}")


async def main():
    PROJECT_ROOT = Path(__file__).parent.parent
    BASE_DATA_DIR = PROJECT_ROOT / "data"
    CONFIG_FILE = PROJECT_ROOT / "scripts" / "configs" / "conferences.json"

    logger.info(f"Loading config from {CONFIG_FILE}...")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        conference_configs = json.load(f)

    async with httpx.AsyncClient() as client:
        tasks = []
        for config in conference_configs:
            for year in config["years"]:
                url = config["url_template"].format(year=year)
                task = asyncio.create_task(_fetch_papers_from_url(client, url))
                tasks.append((task, config["name"], year))
        results = await asyncio.gather(*(task for task, _, _ in tasks))

    for (task, conf_name, year), raw_papers in zip(tasks, results):
        if not raw_papers:
            logger.warning(f"  -> No data found for {conf_name} {year}. Skipping.")
            continue

        normalized_papers = [
            normalize_paper(p, conference=conf_name, year=year) for p in raw_papers
        ]

        output_path = BASE_DATA_DIR / conf_name / f"{year}.json"
        _save_json(normalized_papers, output_path)
    
    logger.info("\nData update process completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
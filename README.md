
# AIRAS Papers DB

A centralized and auto-updating database of research papers from top-tier AI/ML conferences. This repository collects paper information from various sources and provides it in a clean, unified, and ready-to-use JSON format.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Key Features

- **Unified Schema**: Paper data from different conferences (ICLR, ICML, NeurIPS, CVPR, etc.) is normalized into a single, consistent schema.
- **Ready-to-use**: All data is pre-processed. Just clone or download the JSON files to get started with your analysis or application.
- **Organized by Conference and Year**: Provides data broken down by conference and year.

## Data Schema

Each paper object in the JSON files follows this standard schema:

| Key          | Type           | Description                                                 |
|--------------|----------------|-------------------------------------------------------------|
| `id`         | `string`       | A unique identifier for the paper (e.g., from the source UID). |
| `title`      | `string`       | The title of the paper.                                     |
| `authors`    | `array` of `string` | A list of author names.                                     |
| `abstract`   | `string`       | The abstract of the paper.                                  |
| `conference` | `string`       | The name of the conference (e.g., "icml", "iclr").          |
| `year`       | `integer`      | The year the paper was published at the conference.         |
| `paper_url`  | `string`       | A direct URL to the paper's PDF or landing page.            |
| `topic`      | `string`       | The main topic or category assigned by the conference.      |

**Example Object:**
```json
{
  "id": "1763ea5a7e72dd7ee64073c2dda7a7a8",
  "title": "Position: Towards Unified Alignment Between Agents, Humans, and Environment",
  "authors": [
    "Zonghan Yang",
    "an liu",
    "Zijun Liu"
  ],
  "abstract": "The rapid progress of foundation models has led to the prosperity of autonomous agents...",
  "conference": "icml",
  "year": 2024,
  "paper_url": "https://proceedings.mlr.press/v235/yang24p.html",
  "topic": "Deep Learning->Large Language Models"
}
```

## Data Sources

Papers are collected from several source types, configured in `scripts/configs/conferences.jsonc`:

| `source_type` | Origin | Conferences |
|---------------|--------|-------------|
| `virtual_conference` | `*.cc/static/virtual/data/*.json` | ICML, ICLR, NeurIPS, CVPR, ECCV |
| `pmlr` | Proceedings of Machine Learning Research (`proceedings.mlr.press`) | AISTATS, UAI, COLT, AABI, PGM, MLCB |
| `acl_anthology` | ACL Anthology XML | ACL, EMNLP, NAACL |
| `openreview` | OpenReview search API (`/notes/search`) | ML4LMS, GEM, LMRL, GenBio |

NeurIPS' virtual-site JSON also carries the **Datasets & Benchmarks** and **Position
Paper** tracks (504 and 43 papers in 2025), so those need no separate configuration.

### Biomolecular ML venues

These cover the protein-ligand structure and biomolecular design literature:

| Venue | Scope | Editions |
|-------|-------|----------|
| **ML4LMS** | ML for Life and Material Sciences (ICML) — publishes the PLINDER dataset paper | 2024 |
| **GEM** | Generative and Experimental perspectives for biomolecular design (ICLR) | 2024–2026 |
| **LMRL** | Learning Meaningful Representations of Life (NeurIPS/ICLR) | 2022, 2025, 2026 |
| **GenBio** | Generative AI and Biology (NeurIPS/ICML) | 2023, 2025, 2026 |
| **MLCB** | ML in Computational Biology (archival, PMLR) | 2021–2025 |

### Sources deliberately not configured

- **MLSB** (ML in Structural Biology) — the workshop is explicitly non-archival and
  has no OpenReview presence at all (`NeurIPS.cc/*/Workshop/MLSB` returns 404 for
  every year). Its papers only exist as PDFs on `mlsb.io`.
- **ICLR 2026** — the virtual-site JSON has 5,691 papers but no `abstract` field yet.
- **ICML 2026 / CVPR 2026** — the virtual-site JSON is still a 200-paper stub.
- **ISMB / RECOMB / PSB** — no free proceedings API. DBLP has the TOCs but drops the
  connection after a few dozen requests and carries no abstracts.

### OpenReview access note

OpenReview's `/notes` endpoint answers anonymous requests with a 403
`ChallengeRequiredError` (it wants a JS browser challenge), which is why the fetcher
enumerates venues through `/notes/search` instead — that endpoint is not challenged.
Search returns rejected and withdrawn submissions too, so the fetcher keeps only notes
whose `content.venueid` equals the configured venue id. Requests are serialized with a
delay because OpenReview rate-limits aggressively.

Older editions live on API v1, which is set per year:

```json
"venues": {
    "2022": {"id": "NeurIPS.cc/2022/Workshop/LMRL", "api_version": 1},
    "2025": "ICLR.cc/2025/Workshop/LMRL"
}
```

## Usage

### 1. Direct Download

You can download individual conference and year JSON files directly from the repository.

### 2. Git Clone

To get all files, clone the repository:

```bash
git clone https://github.com/airas-org/airas-papers-db.git
cd airas-papers-db
```

### 3. Programmatic Access (Recommended for Applications)

You can fetch the data directly within your Python application:

```python
import httpx

def fetch_papers(conference, year):
    """
    Fetches paper data for a specific conference and year.
    
    Args:
        conference (str): The conference name (e.g., 'icml', 'neurips')
        year (int): The year of the conference
    
    Returns:
        list: A list of paper objects
    """
    url = f"https://raw.githubusercontent.com/airas-org/airas-papers-db/main/data/{conference}/{year}.json"
    try:
        response = httpx.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        print(f"Error occurred: {e}")

    return None

# Example usage
papers = fetch_papers("icml", 2023)
if papers:
    print(f"Found {len(papers)} papers from ICML 2023")
    for paper in papers[:3]:  # Show first 3 papers
        print(f"- {paper['title']} by {', '.join(paper['authors'])}")
```

## Repository Structure

```
.
├── data/
│   ├── icml/
│   │   ├── 2023.json
│   │   └── 2024.json
│   ├── neurips/
│   │   └── ...
├── scripts/
│   ├── fetch_papers.py        # The main script to fetch and process data
│   ├── configs/
│   │   └── conferences.json # Configuration for target conferences
└── README.md
```

## How to Update the Data Locally

If you want to update the data locally:

1.  **Set up a virtual environment (recommended):**
```bash
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Run the update script:**
```bash
python scripts/fetch_papers.py
```
This will fetch the latest data from all configured conferences and update the JSON files.

## Contributing

We welcome contributions! Here are some ways you can help:

1.  **Fork** the repository.
2.  **Add/Update Configuration**: To add a new conference, edit `scripts/configs/conferences.json`.
3.  **Create a Pull Request**: Submit a PR with a clear description of your changes.

## License

This project is licensed under the **MIT License**. See the `LICENSE` file for details.
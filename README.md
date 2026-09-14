
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
| `europepmc` | Europe PMC REST API | ISMB, PSB |
| `drops` | DROPS / LIPIcs volume XML export (Schloss Dagstuhl) | ITP |
| `crossref` | Crossref REST API (+ Semantic Scholar for missing abstracts) | CAV, TACAS, CADE, IJCAR, CPP, LICS, POPL |

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

### Formal methods & theorem-proving venues

These cover interactive/automated theorem proving (Lean, Isabelle, Rocq/Coq),
logic, and verification. They are deliberately the human-authored formalization
and verification venues; the "AI does the proving" workshops (MATH-AI, AI4MATH)
are not included. CORE ranks are ICORE2026.

| Venue | Scope | CORE | Source | Editions |
|-------|-------|------|--------|----------|
| **ITP** | Interactive Theorem Proving — the home venue of Lean/Isabelle/Rocq formalization work | B | LIPIcs | 2019, 2021–2026 |
| **CPP** | Certified Programs and Proofs (co-located with POPL) | B | ACM | 2019–2026 |
| **CADE** | Conference on Automated Deduction (odd years) | A | Springer LNAI | 2019, 2021, 2023, 2025 |
| **IJCAR** | International Joint Conference on Automated Reasoning (even years; merges CADE, ITP, TABLEAUX, FroCoS) | A | Springer LNAI | 2020, 2022, 2024, 2026 |
| **CAV** | Computer Aided Verification | A* | Springer LNCS | 2019–2026 |
| **TACAS** | Tools and Algorithms for the Construction and Analysis of Systems (ETAPS) | A | Springer LNCS | 2019–2026 |
| **LICS** | ACM/IEEE Symposium on Logic in Computer Science | A* | ACM / IEEE | 2019–2025 |
| **POPL** | Principles of Programming Languages (the POPL issue of PACMPL) | A* | ACM | 2019–2026 |

ITP 2020 has no LIPIcs volume: that year ITP was merged into IJCAR 2020, so its
papers are in `data/ijcar/2020.json`.

#### DROPS (LIPIcs)

Each LIPIcs volume on `drops.dagstuhl.de` has an official XML export
(`/entities/volume/LIPIcs-volume-<n>/metadata/xml`, dagpub schema) listing every
document with title, authors, abstract, keywords, DOI and paper category, so one
request covers a whole proceedings. The config maps a year to its LIPIcs volume
number. Front matter (article `.0`) and the complete-volume PDF are dropped.

DROPS also exposes OAI-PMH, but it is not kept up to date (a handful of records
for all of 2025) and has no per-volume sets. LIPIcs DOIs are registered with
DataCite, not Crossref, so the `crossref` source cannot cover them either.

#### Crossref

The `crossref` source enumerates a proceedings through the Crossref REST API.
`match` selects the volume in one of three ways, and `year_overrides` patches it
per edition:

```json
{
    "name": "cade",
    "source_type": "crossref",
    "years": [2023, 2025],
    "match": {"prefixes": ["10.1007"]},
    "year_overrides": {
        "2023": {"container_title": "Automated Deduction – CADE 29"},
        "2025": {"container_title": "Automated Deduction – CADE 30"}
    }
}
```

- `container_title` — exact book title (Springer LNCS chapters carry the
  conference name as their second container-title).
- `container_title_contains` — substring of the proceedings title, for ACM and
  IEEE, whose event metadata is inconsistent (CPP 2020 is filed under
  "POPL '20"). This is a relevance-ranked search, so only the first page (1,000
  records) is read.
- `issn` + `issue` + `volume` — a journal issue. PACMPL's POPL issue is dated the
  December before the conference, hence `date_from: "{prev_year}-10-01"` and a
  per-year `volume` (PACMPL volume = year − 2016).

`prefixes` restricts DOI prefixes (publishers). Corrections and errata, which
publishers register as chapters of their own, are skipped.

Springer and PACMPL deposit abstracts with Crossref; ACM proceedings and IEEE
do not, so missing abstracts are filled in from the Semantic Scholar batch API
(`/graph/v1/paper/batch`, anonymous, hence serialized with retries). Freshly
published volumes (e.g. TACAS 2026) can lack abstracts on both sides for a
while; the weekly run picks them up once deposited. CADE 2019 (LNAI 11716) is
the one older volume Springer registered without abstracts, and Semantic Scholar
and OpenAlex have none for most of it either, so about two thirds of its entries
stay abstract-less.

### Sources deliberately not configured

- **MLSB** (ML in Structural Biology) — the workshop is explicitly non-archival and
  has no OpenReview presence at all (`NeurIPS.cc/*/Workshop/MLSB` returns 404 for
  every year). Its papers only exist as PDFs on `mlsb.io`.
- **ICLR 2026** — the virtual-site JSON has 5,691 papers but no `abstract` field yet.
- **ICML 2026 / CVPR 2026** — the virtual-site JSON is still a 200-paper stub.
- **ISMB / RECOMB / PSB** — no free proceedings API. DBLP has the TOCs but drops the
  connection after a few dozen requests and carries no abstracts.
- **DBLP in general** — its search API now sits behind a JavaScript bot challenge
  ("Making sure you're not a bot!"), so it cannot be used as an enumerator at all.
- **MATH-AI / AI4MATH / AI4Science workshops** — AI-driven venues, out of scope
  for this collection. (If ever wanted: the 2023–2024 MATH-AI, 2024–2025 AI4MATH,
  and 2023–2025 AI4Science editions are searchable on OpenReview; MATH-AI
  2025/2026 and AI4Science 2021/2022/2024 are not.)
- **LICS 2026** — not yet deposited with Crossref.
- **FM, FMCAD, VMCAI, ATVA, FSCD, CSL, CICM** — B/C-ranked formal-methods venues;
  FSCD and CSL are LIPIcs and could be added with the `drops` source, the rest
  are Springer LNCS and would use `crossref`.

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
│   │   └── conferences.jsonc # Configuration for target conferences
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
2.  **Add/Update Configuration**: To add a new conference, edit `scripts/configs/conferences.jsonc`.
3.  **Create a Pull Request**: Submit a PR with a clear description of your changes.

## License

This project is licensed under the **MIT License**. See the `LICENSE` file for details.
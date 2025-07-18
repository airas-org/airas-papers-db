
# Aira's Papers DB

A centralized and auto-updating database of research papers from top-tier AI/ML conferences. This repository collects paper information from various sources and provides it in a clean, unified, and ready-to-use JSON format.

[![Update Status](https://github.com/airas-org/airas-papers-db/actions/workflows/update-data.yml/badge.svg)](https://github.com/airas-org/airas-papers-db/actions/workflows/update-data.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Key Features

- **Unified Schema**: Paper data from different conferences (ICLR, ICML, NeurIPS, CVPR, etc.) is normalized into a single, consistent schema.
- **Ready-to-use**: All data is pre-processed. Just clone or download the JSON files to get started with your analysis or application.
- **Multiple Formats**: Provides data broken down by conference and year, as well as convenient combined files (`all_papers.json` and `latest.json`).
- **Auto-updated**: The dataset is automatically updated periodically using GitHub Actions to fetch the latest papers.

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

## Usage

There are several ways to use this dataset.

### 1. Direct Download

For quick access, you can download the combined data files directly.

```bash
# Download all papers
wget https://raw.githubusercontent.com/airas-org/airas-papers-db/main/data/all/all_papers.json

# Download papers from the latest year only
wget https://raw.githubusercontent.com/airas-org/airas-papers-db/main/data/all/latest.json
```

### 2. Git Clone

To get all individual and combined files, clone the entire repository:

```bash
git clone https://github.com/airas-org/airas-papers-db.git
cd airas-papers-db
```

### 3. Programmatic Access (Recommended for Applications)

You can fetch the data directly within your Python application without needing to clone the repository.

```python
import httpx

def fetch_all_papers():
    """Fetches the combined paper data from the repository."""
    url = "https://raw.githubusercontent.com/airas-org/airas-papers-db/main/data/all/all_papers.json"
    try:
        response = httpx.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        print(f"HTTP error occurred: {e}")
    except httpx.RequestError as e:
        print(f"An error occurred while requesting {e.request.url!r}.")
    return None

# Example usage
all_papers = fetch_all_papers()
if all_papers:
    print(f"Successfully fetched {len(all_papers)} papers.")
    # Now you can filter or process the data
    diffusion_papers = [
        p for p in all_papers 
        if "diffusion" in p.get("title", "").lower()
    ]
    print(f"Found {len(diffusion_papers)} papers on diffusion models.")
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
│   └── all/
│       ├── all_papers.json  # All papers combined
│       └── latest.json      # Papers from the most recent year
├── scripts/
│   ├── update_all.py        # The main script to fetch and process data
│   ├── configs/
│   │   └── conferences.json # Configuration for target conferences
│   └── parsers/
│       └── normalizer.py    # Logic to normalize raw data to the standard schema
└── README.md
```

## How to Update the Data Locally

If you want to run the update process yourself or contribute to the project, follow these steps:

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/airas-org/airas-papers-db.git
    cd airas-papers-db
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Run the update script:**
    ```bash
    python scripts/update_all.py
    ```
    This will fetch the latest data based on `scripts/configs/conferences.json` and update the JSON files in the `data/` directory.

## Contributing

Contributions are welcome! If you want to add a new conference or fix a bug, please follow these steps:

1.  **Fork** the repository.
2.  **Add/Update Configuration**: To add a new conference, edit `scripts/configs/conferences.json`. You might need to add a new parser in `scripts/parsers/` if the data source has a unique structure.
3.  **Create a Pull Request**: Submit a PR with a clear description of your changes.

## License

This project is licensed under the **MIT License**. See the `LICENSE` file for details.
from typing import Any

def normalize_paper(raw_paper: dict, conference: str, year: int) -> dict[str, Any]:
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
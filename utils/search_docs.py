"""Simple documentation URL search using DuckDuckGo."""

import sys

def search_docs(query: str, max_results: int = 3) -> list[str]:
    """
    Search for documentation URLs.

    Args:
        query: Search query (e.g., "react useState official docs")
        max_results: Number of results to return

    Returns:
        List of URLs
    """
    try:
        from duckduckgo_search import DDGS

        # Append "documentation" to bias toward docs
        search_query = f"{query} documentation"

        results = DDGS().text(search_query, max_results=max_results)
        return [r['href'] for r in results]

    except ImportError:
        print("Error: duckduckgo-search not installed. Run: pip install duckduckgo-search", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Search error: {e}", file=sys.stderr)
        return []


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python search_docs.py <query>")
        print("Example: python search_docs.py 'prisma client api'")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    urls = search_docs(query)

    for url in urls:
        print(url)

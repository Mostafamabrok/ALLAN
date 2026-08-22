def run(query="", **kwargs):
    """
    Mock web search tool.
    Accepts a 'query' string and returns fake search results.
    """
    if not query:
        return "Error: No search query provided."

    # Generate a fake response based on the query.
    mock_results = (
        f"Mock Search Results for: '{query}'\n"
        f"1. https://example.com/mock-article - 'Everything you need to know about {query}.'\n"
        f"2. https://fake-wiki.org/wiki/{query.replace(' ', '_')} - 'Wiki page detailing the history of {query}.'"
    )

    return mock_results
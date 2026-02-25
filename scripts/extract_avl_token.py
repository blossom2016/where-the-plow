"""Extract the ArcGIS API token from the St. John's AVL page.

The AVL page at https://map.stjohns.ca/avl/ embeds a token via
esriId.registerToken({ ..., token: "AAPT..." }). This script fetches
the page and extracts that token using a regex.

Usage:
    uv run python scripts/extract_avl_token.py
"""

import re
import httpx


AVL_PAGE_URL = "https://map.stjohns.ca/avl/"


def extract_token(html: str) -> str | None:
    """Pull the token value from the registerToken() call in the page source."""
    # Match: token: "AAPT...stuff..."
    match = re.search(r'token:\s*"(AAPT[^"]+)"', html)
    if match:
        return match.group(1)
    return None


def main():
    print(f"Fetching {AVL_PAGE_URL} ...")
    resp = httpx.get(AVL_PAGE_URL, follow_redirects=True, timeout=15)
    resp.raise_for_status()
    print(f"  Status: {resp.status_code}, Content-Length: {len(resp.text)}")

    token = extract_token(resp.text)
    if token:
        print(f"\nToken found ({len(token)} chars):")
        print(f"  {token[:40]}...{token[-20:]}")
        print(f"\nFull token:\n{token}")
    else:
        print("\nNo token found in page source!")
        print("The page may have changed its auth mechanism.")
        # Dump a snippet around 'token' for debugging
        for i, line in enumerate(resp.text.splitlines(), 1):
            if "token" in line.lower():
                print(f"  Line {i}: {line[:200]}")


if __name__ == "__main__":
    main()

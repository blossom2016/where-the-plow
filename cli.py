"""Dev CLI for where-the-plow."""

import re
import subprocess
import sys
from pathlib import Path

COMMANDS = {
    "dev": "Run uvicorn in development mode with auto-reload",
    "start": "Run uvicorn in production mode",
    "changelog": "Convert CHANGELOG.md to an HTML fragment",
}

APP = "where_the_plow.main:app"


def dev():
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            APP,
            "--reload",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
        env={**__import__("os").environ, "DB_PATH": "./data/plow.db"},
    )


def start():
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            APP,
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
    )


def _md_inline(text: str) -> str:
    """Convert inline markdown to HTML: bold, links, and issue references."""
    # Convert **text** to <strong>text</strong>
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Convert [text](url) to <a> tags
    text = re.sub(
        r"\[(.+?)\]\((.+?)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        text,
    )
    # Convert standalone (#N) to issue links
    text = re.sub(
        r"\(#(\d+)\)",
        r'(<a href="https://github.com/jackharrhy/where-the-plow/issues/\1" target="_blank" rel="noopener">#\1</a>)',
        text,
    )
    return text


def changelog():
    root = Path(__file__).parent
    md_path = root / "CHANGELOG.md"
    out_path = root / "src" / "where_the_plow" / "static" / "changelog.html"

    content = md_path.read_text()

    # Extract changelog-id
    id_match = re.search(r"<!--\s*changelog-id:\s*(\d+)\s*-->", content)
    changelog_id = id_match.group(1) if id_match else "0"

    # Split on ## headings; first chunk is the header/preamble, skip it
    sections = re.split(r"^## ", content, flags=re.MULTILINE)

    articles = []
    for section in sections[1:]:
        lines = section.strip()
        # First line is the title
        title, _, body = lines.partition("\n")
        title = title.strip()
        body = body.strip()

        # Split body into paragraphs on double newlines
        paragraphs = re.split(r"\n\n+", body)
        p_html = []
        for para in paragraphs:
            if not para.strip():
                continue
            # Within a paragraph block, lines starting with [ (a link)
            # are separate paragraphs (e.g. "View changes" links)
            sub_parts: list[list[str]] = [[]]
            for line in para.strip().splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("[") and sub_parts[-1]:
                    sub_parts.append([stripped])
                else:
                    sub_parts[-1].append(stripped)
            for part in sub_parts:
                if not part:
                    continue
                text = " ".join(part)
                text = _md_inline(text)
                p_html.append(f"<p>{text}</p>")

        article = (
            f"<article>\n<h2>{_md_inline(title)}</h2>\n"
            + "\n".join(p_html)
            + "\n</article>"
        )
        articles.append(article)

    html = f'<div class="changelog" data-changelog-id="{changelog_id}">\n'
    html += "\n".join(articles)
    html += "\n</div>\n"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"Wrote changelog.html (changelog-id: {changelog_id})")


def usage():
    print("Usage: uv run cli.py <command>\n")
    print("Commands:")
    for name, desc in COMMANDS.items():
        print(f"  {name:10s} {desc}")
    sys.exit(1)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        usage()

    cmd = sys.argv[1]
    {"dev": dev, "start": start, "changelog": changelog}[cmd]()


if __name__ == "__main__":
    main()

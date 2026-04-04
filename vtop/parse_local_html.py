import argparse
import json
from pathlib import Path

from parsers.credentials_parser import parse_credentials


def main():
    parser = argparse.ArgumentParser(description="Parse a local VTOP HTML export.")
    parser.add_argument("html_path", help="Path to the saved HTML file")
    args = parser.parse_args()

    html_file = Path(args.html_path)
    if not html_file.exists():
        raise SystemExit(f"File not found: {html_file}")

    html_content = html_file.read_text(encoding="utf-8", errors="ignore")
    result = parse_credentials(html_content)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

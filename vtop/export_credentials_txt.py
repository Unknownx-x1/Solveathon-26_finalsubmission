import argparse
from pathlib import Path

from parsers.credentials_parser import parse_credentials


def format_entry(entry, include_password=False):
    lines = []
    lines.append(f"Account Name: {entry.get('account_name', '')}")
    lines.append(f"Username: {entry.get('username', '')}")
    if include_password:
        lines.append(f"Password: {entry.get('password', '')}")
    lines.append(f"URL: {entry.get('url', '')}")
    lines.append(f"Venue/Date: {entry.get('venue_date', '')}")
    lines.append(f"Seat Number: {entry.get('seat_number', '')}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Export parsed VTOP data to a txt file.")
    parser.add_argument("html_path", help="Path to the saved HTML file")
    parser.add_argument(
        "output_path",
        help="Path to the output .txt file",
    )
    args = parser.parse_args()

    html_file = Path(args.html_path)
    if not html_file.exists():
        raise SystemExit(f"File not found: {html_file}")

    html_content = html_file.read_text(encoding="utf-8", errors="ignore")
    result = parse_credentials(html_content)

    out_lines = []
    out_lines.append("ACCOUNTS")
    out_lines.append("--------")
    for entry in result.get("accounts", []):
        out_lines.append(format_entry(entry))
        out_lines.append("")

    out_lines.append("EXAMS")
    out_lines.append("-----")
    for entry in result.get("exams", []):
        out_lines.append(format_entry(entry))
        out_lines.append("")

    output_file = Path(args.output_path)
    output_file.write_text("\n".join(out_lines).strip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

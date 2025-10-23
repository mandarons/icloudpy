#!/usr/bin/env python3
"""Generate coverage badges from coverage.xml report"""

import sys
import xml.etree.ElementTree as ET


def get_coverage_percentage(coverage_xml_path: str) -> float:
    """Extract coverage percentage from coverage.xml"""
    try:
        tree = ET.parse(coverage_xml_path)
        root = tree.getroot()

        # Parse coverage percentage from line-rate
        line_rate = float(root.attrib.get("line-rate", 0))
        return round(line_rate * 100, 2)
    except Exception as e:
        print(f"Error parsing coverage: {e}", file=sys.stderr)
        return 0.0


def generate_badge_json(coverage_pct: float) -> dict:
    """Generate badge JSON for shields.io endpoint"""
    if coverage_pct >= 95:
        color = "brightgreen"
    elif coverage_pct >= 80:
        color = "green"
    elif coverage_pct >= 60:
        color = "yellow"
    else:
        color = "red"

    return {
        "schemaVersion": 1,
        "label": "coverage",
        "message": f"{coverage_pct}%",
        "color": color,
    }


def main():
    coverage_xml_path = "coverage.xml"
    coverage_pct = get_coverage_percentage(coverage_xml_path)

    print(f"Coverage: {coverage_pct}%")

    # Create badges directory if it doesn't exist
    import os

    os.makedirs("badges", exist_ok=True)

    # Generate badge JSON
    import json

    badge = generate_badge_json(coverage_pct)

    badge_path = "badges/coverage-badge.json"
    with open(badge_path, "w") as f:
        json.dump(badge, f, indent=2)

    print(f"Badge JSON generated: {badge_path}")

    # Exit with error if below threshold
    if coverage_pct < 78:
        print(f"ERROR: Coverage {coverage_pct}% is below 78% threshold", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()

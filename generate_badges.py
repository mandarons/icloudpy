#!/usr/bin/env python3
"""Generate coverage and test badges from coverage.xml and allure reports"""

import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET

import requests


def generate_badges():
    """Generate SVG badges for tests and coverage"""
    badges_directory = "./badges"

    # Read test results from allure report
    try:
        with open("./allure-report/widgets/summary.json") as f:
            test_data = json.load(f)
            test_result = test_data["statistic"]["total"] == test_data["statistic"]["passed"]
    except FileNotFoundError:
        print("Warning: allure-report/widgets/summary.json not found, skipping test badge", file=sys.stderr)
        test_result = None

    # Read coverage from coverage.xml
    coverage_result = float(ET.parse("./coverage.xml").getroot().attrib["line-rate"]) * 100.0

    # Create badges directory
    if os.path.exists(badges_directory) and os.path.isdir(badges_directory):
        shutil.rmtree(badges_directory)
        os.mkdir(badges_directory)
    else:
        os.mkdir(badges_directory)

    # Generate test badge
    if test_result is not None:
        url_data = "passing&color=brightgreen" if test_result else "failing&color=critical"
        response = requests.get(
            "https://img.shields.io/static/v1?label=Tests&message=" + url_data,
            timeout=10,
        )
        with open(badges_directory + "/tests.svg", "w") as f:
            f.write(response.text)
        print(f"Test badge generated: {'passing' if test_result else 'failing'}")

    # Generate coverage badge
    url_data = "brightgreen" if coverage_result == 100.0 else "critical"
    response = requests.get(
        f"https://img.shields.io/static/v1?label=Coverage&message={coverage_result:.2f}%&color={url_data}",
        timeout=10,
    )
    with open(badges_directory + "/coverage.svg", "w") as f:
        f.write(response.text)
    print(f"Coverage badge generated: {coverage_result:.2f}%")

    # Also generate JSON badge for compatibility
    if coverage_result >= 95:
        color = "brightgreen"
    elif coverage_result >= 80:
        color = "green"
    elif coverage_result >= 60:
        color = "yellow"
    else:
        color = "red"

    badge_json = {
        "schemaVersion": 1,
        "label": "coverage",
        "message": f"{coverage_result:.2f}%",
        "color": color,
    }

    badge_path = "badges/coverage-badge.json"
    with open(badge_path, "w") as f:
        json.dump(badge_json, f, indent=2)

    print(f"Badge JSON generated: {badge_path}")

    # Exit with error if below threshold
    if coverage_result < 78:
        print(f"ERROR: Coverage {coverage_result:.2f}% is below 78% threshold", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    generate_badges()

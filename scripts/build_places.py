"""Build apps/web/src/data/places.json: Maharashtra towns with coordinates checked against the
openrouteservice geocoder (one-off; the result is committed so the app needs no geocoding).

Usage: apps/api/.venv/Scripts/python scripts/build_places.py
"""

import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
KEY = dotenv_values(ROOT / "apps" / "api" / ".env")["ORS_API_KEY"]
OUT = ROOT / "apps" / "web" / "src" / "data" / "places.json"

# name, district, lat, lng, tier (1 = major hub, 2 = city, 3 = town); search aliases
RAW = [
    ("Mumbai", "Mumbai", 19.0760, 72.8777, 1, ["Bombay"]),
    ("Pune", "Pune", 18.5204, 73.8567, 1, ["Poona"]),
    ("Nagpur", "Nagpur", 21.1458, 79.0882, 1, []),
    ("Nashik", "Nashik", 19.9975, 73.7898, 1, ["Nasik"]),
    (
        "Chhatrapati Sambhajinagar",
        "Chhatrapati Sambhajinagar",
        19.8762,
        75.3433,
        1,
        ["Aurangabad"],
    ),
    ("Kolhapur", "Kolhapur", 16.7050, 74.2433, 1, []),
    ("Solapur", "Solapur", 17.6599, 75.9064, 1, ["Sholapur"]),
    ("Amravati", "Amravati", 20.9320, 77.7523, 1, []),
    ("Nanded", "Nanded", 19.1383, 77.3210, 1, []),
    ("Thane", "Thane", 19.2183, 72.9781, 2, []),
    ("Kalyan", "Thane", 19.2437, 73.1355, 2, []),
    ("Panvel", "Raigad", 18.9894, 73.1175, 2, []),
    ("Lonavala", "Pune", 18.7557, 73.4091, 3, []),
    ("Karjat", "Raigad", 18.9100, 73.3200, 3, []),
    ("Khopoli", "Raigad", 18.7850, 73.3450, 3, []),
    ("Alibag", "Raigad", 18.6414, 72.8722, 3, []),
    ("Mahad", "Raigad", 18.0833, 73.4167, 3, []),
    ("Chiplun", "Ratnagiri", 17.5300, 73.5150, 3, []),
    ("Ratnagiri", "Ratnagiri", 16.9902, 73.3120, 2, []),
    ("Narayangaon", "Pune", 19.1200, 73.9700, 3, []),
    ("Shirur", "Pune", 18.8300, 74.3800, 3, []),
    ("Daund", "Pune", 18.4600, 74.5800, 3, []),
    ("Indapur", "Pune", 18.1167, 75.0167, 3, []),
    ("Baramati", "Pune", 18.1517, 74.5777, 3, []),
    ("Satara", "Satara", 17.6805, 74.0183, 2, []),
    ("Karad", "Satara", 17.2890, 74.1810, 3, []),
    ("Phaltan", "Satara", 17.9833, 74.4333, 3, []),
    ("Sangli", "Sangli", 16.8524, 74.5815, 2, []),
    ("Miraj", "Sangli", 16.8220, 74.6470, 3, []),
    ("Ichalkaranji", "Kolhapur", 16.6910, 74.4600, 3, []),
    ("Pandharpur", "Solapur", 17.6792, 75.3320, 3, []),
    ("Barshi", "Solapur", 18.2333, 75.6933, 3, []),
    ("Dharashiv", "Dharashiv", 18.1860, 76.0419, 2, ["Osmanabad"]),
    ("Tuljapur", "Dharashiv", 18.0069, 76.0700, 3, []),
    ("Latur", "Latur", 18.4088, 76.5604, 2, []),
    ("Udgir", "Latur", 18.3933, 77.1167, 3, []),
    ("Ahilyanagar", "Ahilyanagar", 19.0952, 74.7496, 2, ["Ahmednagar"]),
    ("Sangamner", "Ahilyanagar", 19.5667, 74.2167, 3, []),
    ("Shirdi", "Ahilyanagar", 19.7667, 74.4769, 3, []),
    ("Kopargaon", "Ahilyanagar", 19.8833, 74.4833, 3, []),
    ("Newasa", "Ahilyanagar", 19.5500, 75.0100, 3, []),
    ("Sinnar", "Nashik", 19.8500, 74.0000, 3, []),
    ("Igatpuri", "Nashik", 19.6950, 73.5630, 3, []),
    ("Manmad", "Nashik", 20.2500, 74.4333, 3, []),
    ("Yeola", "Nashik", 20.0417, 74.4889, 3, []),
    ("Malegaon", "Nashik", 20.5579, 74.5089, 3, []),
    ("Vaijapur", "Chhatrapati Sambhajinagar", 19.9167, 74.7333, 3, []),
    ("Paithan", "Chhatrapati Sambhajinagar", 19.4800, 75.3800, 3, []),
    ("Jalna", "Jalna", 19.8347, 75.8816, 2, []),
    ("Parbhani", "Parbhani", 19.2704, 76.7747, 2, []),
    ("Beed", "Beed", 18.9891, 75.7601, 2, ["Bid"]),
    ("Georai", "Beed", 19.2667, 75.7500, 3, []),
    ("Majalgaon", "Beed", 19.1500, 76.2167, 3, []),
    ("Parli", "Beed", 18.8500, 76.5333, 3, ["Parli Vaijnath"]),
    ("Ambajogai", "Beed", 18.7333, 76.3833, 3, []),
    ("Hingoli", "Hingoli", 19.7167, 77.1500, 3, []),
    ("Pusad", "Yavatmal", 19.9100, 77.5700, 3, []),
    ("Yavatmal", "Yavatmal", 20.3899, 78.1307, 2, []),
    ("Washim", "Washim", 20.1000, 77.1333, 3, []),
    ("Akola", "Akola", 20.7002, 77.0082, 2, []),
    ("Khamgaon", "Buldhana", 20.7000, 76.5667, 3, []),
    ("Buldhana", "Buldhana", 20.5333, 76.1833, 3, []),
    ("Jalgaon", "Jalgaon", 21.0077, 75.5626, 2, []),
    ("Bhusawal", "Jalgaon", 21.0436, 75.7850, 3, []),
    ("Dhule", "Dhule", 20.9042, 74.7749, 2, []),
    ("Nandurbar", "Nandurbar", 21.3700, 74.2400, 3, []),
    ("Wardha", "Wardha", 20.7453, 78.6022, 2, []),
    ("Chandrapur", "Chandrapur", 19.9615, 79.2961, 2, []),
    ("Bhandara", "Bhandara", 21.1670, 79.6500, 3, []),
    ("Gondia", "Gondia", 21.4624, 80.1920, 3, []),
    ("Ramtek", "Nagpur", 21.3900, 79.3300, 3, []),
    ("Gadchiroli", "Gadchiroli", 20.1800, 80.0000, 3, []),
]


def geocode(name: str, lat: float, lng: float):
    query = urllib.parse.urlencode(
        {
            "api_key": KEY,
            "text": f"{name}, Maharashtra, India",
            "boundary.country": "IN",
            "focus.point.lat": lat,
            "focus.point.lon": lng,
            "size": 3,
            "layers": "locality,localadmin,county,region",
        }
    )
    with urllib.request.urlopen(
        f"https://api.openrouteservice.org/geocode/search?{query}", timeout=30
    ) as response:
        data = json.load(response)
    for feature in data.get("features", []):
        if feature["properties"].get("region") == "Maharashtra":
            lng2, lat2 = feature["geometry"]["coordinates"]
            return lat2, lng2
    return None


def km(a, b):
    dy = (a[0] - b[0]) * 111.0
    dx = (a[1] - b[1]) * 111.0 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def main():
    out, problems = [], []
    for name, district, lat, lng, tier, aliases in RAW:
        found = None
        try:
            found = geocode(name, lat, lng)
        except (OSError, ValueError) as exc:
            problems.append(f"{name}: geocoder error {exc}")
        use = (lat, lng)
        if found:
            # The geocoder sometimes answers with a district centre, so it only flags differences;
            # the hand-checked coordinates are kept.
            gap = km((lat, lng), found)
            if gap > 8:
                problems.append(
                    f"{name}: {gap:.0f} km from geocoder {found}; kept hand-checked"
                )
        else:
            problems.append(f"{name}: not found by geocoder; kept guess")
        out.append(
            {
                "name": name,
                "district": district,
                "lat": round(use[0], 4),
                "lng": round(use[1], 4),
                "tier": tier,
                "aliases": aliases,
            }
        )
        time.sleep(0.7)
    OUT.write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(out)} places to {OUT}")
    print("\n".join(problems) or "no problems")


if __name__ == "__main__":
    main()

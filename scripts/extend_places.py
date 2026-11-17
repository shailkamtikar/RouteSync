"""Extend apps/web/src/data/places.json with more Maharashtra towns, with coordinates looked up
once from OpenStreetMap's Nominatim (one request per second, as its usage policy asks).

Only the town names and districts are written here; the coordinates come from the lookup, are
required to fall inside Maharashtra and are checked against the town's district. Towns that cannot
be found are listed and skipped. Existing entries are never changed.

Usage: apps/api/.venv/Scripts/python scripts/extend_places.py [--out path]
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PLACES = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "web"
    / "src"
    / "data"
    / "places.json"
)
# west, north, east, south: a box around Maharashtra
BOX = (72.6, 22.1, 80.95, 15.6)
USER_AGENT = "RouteSync-places-build/1.0 (one-off catalog build)"

# name, district, tier (2 = city, 3 = town), alternative names
EXTRA = [
    # Mumbai region and Konkan
    ("Vasai", "Palghar", 2, ["Vasai-Virar", "Virar"]),
    ("Bhiwandi", "Thane", 2, []),
    ("Ulhasnagar", "Thane", 2, []),
    ("Ambernath", "Thane", 3, []),
    ("Badlapur", "Thane", 3, []),
    ("Navi Mumbai", "Thane", 2, ["Vashi"]),
    ("Palghar", "Palghar", 3, []),
    ("Dahanu", "Palghar", 3, []),
    ("Boisar", "Palghar", 3, []),
    ("Jawhar", "Palghar", 3, []),
    ("Pen", "Raigad", 3, []),
    ("Murud", "Raigad", 3, []),
    ("Roha", "Raigad", 3, []),
    ("Mangaon", "Raigad", 3, []),
    ("Dapoli", "Ratnagiri", 3, []),
    ("Khed", "Ratnagiri", 3, []),
    ("Guhagar", "Ratnagiri", 3, []),
    ("Rajapur", "Ratnagiri", 3, []),
    ("Lanja", "Ratnagiri", 3, []),
    ("Sawantwadi", "Sindhudurg", 3, []),
    ("Kudal", "Sindhudurg", 3, []),
    ("Kankavli", "Sindhudurg", 3, []),
    ("Malvan", "Sindhudurg", 3, []),
    ("Vengurla", "Sindhudurg", 3, []),
    ("Devgad", "Sindhudurg", 3, []),
    # Pune and western Maharashtra
    ("Pimpri-Chinchwad", "Pune", 2, ["Pimpri", "Chinchwad"]),
    ("Jejuri", "Pune", 3, []),
    ("Saswad", "Pune", 3, []),
    ("Bhor", "Pune", 3, []),
    ("Talegaon Dabhade", "Pune", 3, ["Talegaon"]),
    ("Chakan", "Pune", 3, []),
    ("Rajgurunagar", "Pune", 3, ["Khed Pune"]),
    ("Junnar", "Pune", 3, []),
    ("Alephata", "Pune", 3, []),
    ("Manchar", "Pune", 3, []),
    ("Wai", "Satara", 3, []),
    ("Mahabaleshwar", "Satara", 3, []),
    ("Panchgani", "Satara", 3, []),
    ("Koregaon", "Satara", 3, []),
    ("Patan", "Satara", 3, []),
    ("Vaduj", "Satara", 3, []),
    ("Islampur", "Sangli", 3, []),
    ("Tasgaon", "Sangli", 3, []),
    ("Vita", "Sangli", 3, []),
    ("Jath", "Sangli", 3, []),
    ("Kagal", "Kolhapur", 3, []),
    ("Gadhinglaj", "Kolhapur", 3, []),
    ("Jaysingpur", "Kolhapur", 3, []),
    ("Radhanagari", "Kolhapur", 3, []),
    ("Ajra", "Kolhapur", 3, []),
    ("Chandgad", "Kolhapur", 3, []),
    ("Akkalkot", "Solapur", 3, []),
    ("Mangalvedha", "Solapur", 3, []),
    ("Karmala", "Solapur", 3, []),
    ("Sangola", "Solapur", 3, []),
    ("Mohol", "Solapur", 3, []),
    ("Akluj", "Solapur", 3, []),
    # Nashik, Khandesh and the north
    ("Satana", "Nashik", 3, []),
    ("Niphad", "Nashik", 3, []),
    ("Dindori", "Nashik", 3, []),
    ("Trimbakeshwar", "Nashik", 3, ["Trimbak"]),
    ("Nandgaon", "Nashik", 3, []),
    ("Chandwad", "Nashik", 3, []),
    ("Lasalgaon", "Nashik", 3, []),
    ("Shirpur", "Dhule", 3, []),
    ("Sakri", "Dhule", 3, []),
    ("Shahada", "Nandurbar", 3, []),
    ("Chalisgaon", "Jalgaon", 3, []),
    ("Pachora", "Jalgaon", 3, []),
    ("Amalner", "Jalgaon", 3, []),
    ("Jamner", "Jalgaon", 3, []),
    ("Raver", "Jalgaon", 3, []),
    ("Yawal", "Jalgaon", 3, []),
    ("Erandol", "Jalgaon", 3, []),
    ("Muktainagar", "Jalgaon", 3, []),
    ("Shrirampur", "Ahilyanagar", 3, []),
    ("Rahuri", "Ahilyanagar", 3, []),
    ("Shevgaon", "Ahilyanagar", 3, []),
    ("Pathardi", "Ahilyanagar", 3, []),
    ("Jamkhed", "Ahilyanagar", 3, []),
    ("Parner", "Ahilyanagar", 3, []),
    ("Akole", "Ahilyanagar", 3, []),
    # Marathwada
    ("Sillod", "Chhatrapati Sambhajinagar", 3, []),
    ("Gangapur", "Chhatrapati Sambhajinagar", 3, []),
    ("Khuldabad", "Chhatrapati Sambhajinagar", 3, ["Ellora"]),
    ("Kannad", "Chhatrapati Sambhajinagar", 3, []),
    ("Ashti", "Beed", 3, []),
    ("Kaij", "Beed", 3, []),
    ("Dharur", "Beed", 3, []),
    ("Bhokardan", "Jalna", 3, []),
    ("Partur", "Jalna", 3, []),
    ("Ambad", "Jalna", 3, []),
    ("Selu", "Parbhani", 3, []),
    ("Pathri", "Parbhani", 3, []),
    ("Jintur", "Parbhani", 3, []),
    ("Gangakhed", "Parbhani", 3, []),
    ("Basmat", "Hingoli", 3, []),
    ("Kalamnuri", "Hingoli", 3, []),
    ("Ausa", "Latur", 3, []),
    ("Nilanga", "Latur", 3, []),
    ("Ahmedpur", "Latur", 3, []),
    ("Kinwat", "Nanded", 3, []),
    ("Bhokar", "Nanded", 3, []),
    ("Deglur", "Nanded", 3, []),
    ("Mukhed", "Nanded", 3, []),
    ("Biloli", "Nanded", 3, []),
    ("Hadgaon", "Nanded", 3, []),
    ("Kandhar", "Nanded", 3, []),
    ("Omerga", "Dharashiv", 3, ["Omerga"]),
    ("Paranda", "Dharashiv", 3, []),
    ("Bhum", "Dharashiv", 3, []),
    # Vidarbha
    ("Katol", "Nagpur", 3, []),
    ("Kamptee", "Nagpur", 3, []),
    ("Umred", "Nagpur", 3, []),
    ("Savner", "Nagpur", 3, []),
    ("Achalpur", "Amravati", 3, []),
    ("Daryapur", "Amravati", 3, []),
    ("Warud", "Amravati", 3, []),
    ("Morshi", "Amravati", 3, []),
    ("Chikhaldara", "Amravati", 3, []),
    ("Akot", "Akola", 3, []),
    ("Balapur", "Akola", 3, []),
    ("Mangrulpir", "Washim", 3, []),
    ("Karanja", "Washim", 3, ["Karanja Lad"]),
    ("Chikhli", "Buldhana", 3, []),
    ("Mehkar", "Buldhana", 3, []),
    ("Malkapur", "Buldhana", 3, []),
    ("Shegaon", "Buldhana", 3, []),
    ("Hinganghat", "Wardha", 3, []),
    ("Arvi", "Wardha", 3, []),
    ("Pulgaon", "Wardha", 3, []),
    ("Wani", "Yavatmal", 3, []),
    ("Pandharkawada", "Yavatmal", 3, []),
    ("Darwha", "Yavatmal", 3, []),
    ("Digras", "Yavatmal", 3, []),
    ("Umarkhed", "Yavatmal", 3, []),
    ("Ghatanji", "Yavatmal", 3, []),
    ("Warora", "Chandrapur", 3, []),
    ("Bhadravati", "Chandrapur", 3, []),
    ("Ballarpur", "Chandrapur", 3, []),
    ("Brahmapuri", "Chandrapur", 3, []),
    ("Rajura", "Chandrapur", 3, []),
    ("Armori", "Gadchiroli", 3, []),
    ("Aheri", "Gadchiroli", 3, []),
    ("Tumsar", "Bhandara", 3, []),
    ("Sakoli", "Bhandara", 3, []),
    ("Tirora", "Gondia", 3, []),
]


def lookup(name: str, district: str):
    query = urllib.parse.urlencode(
        {
            "q": f"{name}, {district}, Maharashtra, India",
            "format": "jsonv2",
            "limit": 3,
            "countrycodes": "in",
            "viewbox": ",".join(str(v) for v in BOX),
            "bounded": 1,
        }
    )
    request = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/search?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        results = json.load(response)
    # Prefer a settlement over a shop or road with the same name.
    for result in results:
        if result.get("category") in ("place", "boundary") or result.get(
            "addresstype"
        ) in (
            "city",
            "town",
            "village",
            "suburb",
            "municipality",
            "county",
        ):
            return float(result["lat"]), float(result["lon"])
    return (float(results[0]["lat"]), float(results[0]["lon"])) if results else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(PLACES))
    args = parser.parse_args()
    places = json.loads(PLACES.read_text(encoding="utf-8"))
    have = {p["name"].lower() for p in places}
    added, missing = 0, []
    for name, district, tier, aliases in EXTRA:
        if name.lower() in have:
            continue
        try:
            found = lookup(name, district)
        except (OSError, ValueError) as exc:
            missing.append(f"{name}: lookup failed ({exc})")
            time.sleep(2)
            continue
        time.sleep(1.1)
        if not found or not (
            BOX[3] <= found[0] <= BOX[1] and BOX[0] <= found[1] <= BOX[2]
        ):
            missing.append(f"{name}: not found inside Maharashtra")
            continue
        places.append(
            {
                "name": name,
                "district": district,
                "lat": round(found[0], 4),
                "lng": round(found[1], 4),
                "tier": tier,
                "aliases": aliases,
            }
        )
        have.add(name.lower())
        added += 1
    Path(args.out).write_text(
        json.dumps(places, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"added {added} places; {len(places)} in total -> {args.out}")
    print("\n".join(missing) or "every place was found", file=sys.stderr)


if __name__ == "__main__":
    main()

import requests, json, time

URL = "http://localhost:5000/api/chat"
SID = "qa"

tests = [
  "who made you",
  "what services do you offer",
  "what cities do you cover",
  "show me apartments",                        # type-only → broad across areas
  "houses in Matara under 60M",                # likely none → relaxed/fallback
  "nearest apartments to Borella",
  "3BR apartments in Galle under 80M",
  "I need to contact a real agent",
  "book a free valuation",
  "reset"
]

for t in tests:
    print(f"\n> {t}")
    r = requests.post(URL, json={"message": t, "session_id": SID}, timeout=20)
    r.raise_for_status()
    data = r.json().get("reply", {})
    if data.get("type") == "cards":
        show = { "type": "cards", "preface": data.get("preface"), "items": data["items"][:4] }
        print("<", json.dumps(show, indent=2))
    else:
        print("<", json.dumps(data, indent=2))
    time.sleep(0.25)

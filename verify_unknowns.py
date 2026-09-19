import json

with open("data/startups.jsonl", "r", encoding="utf-8") as f:
    startups = [json.loads(line) for line in f]

targets = ["Directed Edge", "JustSpotted", "Canopy Labs", "Casetext"]
for s in startups:
    if s["content"]["entityName"] in targets:
        print(f"\n{s['content']['entityName']}:")
        print(f"  description: {s['content'].get('description')!r}")
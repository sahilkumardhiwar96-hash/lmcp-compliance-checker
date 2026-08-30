import json

RULES_PATH = "rules.json"


def load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["rules"], data.get("notes", {})


def save_rules(rules, notes=None):
    data = {"rules": rules}
    if notes:
        data["notes"] = notes
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

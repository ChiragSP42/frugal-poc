import pandas as pd
import json
import os
import math
import re

df = pd.read_excel("Frugal_Card_Reference_Template_Rev2.xlsx", sheet_name="Card Data")
os.makedirs("output/cards_v2", exist_ok=True)

# ── Normalization helpers ─────────────────────────────────────────────────────
ISSUER_NORM = {
    "american express": "American Express",
    "amex": "American Express",
    "chase": "Chase",
    "citi": "Citibank",
    "citi bank": "Citibank",
    "citibank": "Citibank",
    "capital one": "Capital One",
    "capital": "Capital One",
    "discover": "Discover",
    "bank of america": "Bank of America",
    "wells fargo": "Wells Fargo",
    "us bank": "US Bank",
    "michigan credit union": "Michigan Credit Union",
    "msufcu": "MSUFCU",
    "flagstar": "Flagstar",
    "barclays": "Barclays",
}

POC_CATEGORIES = {"Retail", "Dining", "Groceries", "Travel", "Digital Entertainment",
                   "Gas", "Amazon", "Costco", "Streaming services", "Car rental",
                   "Flights", "Flight and Vacation rental", "Kohls", "Rotating categories",
                   "All"}

def norm_str(v):
    return str(v).strip() if v and not (isinstance(v, float) and math.isnan(v)) else None

def norm_issuer(v):
    raw = norm_str(v)
    if not raw: return "Other"
    return ISSUER_NORM.get(raw.lower(), raw)

def norm_currency(v):
    raw = norm_str(v)
    if not raw: return "cashback"
    if raw.lower() in ("dollar", "cash", "cashback", "usd"): return "cashback"
    if raw.lower() in ("points", "point"): return "points"
    if raw.lower() in ("miles", "mile"): return "miles"
    return raw.lower()

def norm_bool(v):
    raw = norm_str(v)
    if not raw: return False
    return str(raw).strip().lower() in ("yes", "true", "1")

def norm_num(v, default=0.0):
    if v is None or (isinstance(v, float) and math.isnan(v)): return default
    try: return float(v)
    except: return default

def norm_category(v):
    raw = norm_str(v)
    if not raw: return None
    return raw

def norm_multiplier(raw_val, currency, warnings, card_name, cat_num):
    """Parse multiplier values, handling '5X'/'10X' strings and decimal percentages."""
    if raw_val is None or (isinstance(raw_val, float) and math.isnan(raw_val)):
        return 0.0
    # Handle string values like "5X", "10X"
    raw_str = str(raw_val).strip().upper()
    match = re.match(r'^([\d.]+)\s*X?$', raw_str)
    if match:
        val = float(match.group(1))
    else:
        val = norm_num(raw_val, 0.0)
    if val == 0.0: return 0.0
    # Client entered cashback rates as decimals (0.05 = 5%) — convert to multiplier
    if currency == "cashback" and 0 < val < 1:
        converted = round(val * 100, 2)
        warnings.append(
            f"  ⚠ Cat {cat_num}: Multiplier {val} looks like a % rate "
            f"— converted to {converted}x (cashback card)"
        )
        return converted
    return val


# ── DynamoDB type wrappers ────────────────────────────────────────────────────
def S(v):    return {"S": str(v)}
def N(v):    return {"N": str(v)}
def BOOL(v): return {"BOOL": bool(v)}
def L(v):    return {"L": v}
def M(v):    return {"M": v}

def build_bonus_cat(row, n, currency, warnings, card_name):
    poc = norm_category(row.get(f"Bonus Category {n} (PoC)"))
    if not poc:
        return None
    display = norm_str(row.get(f"Bonus Cat {n} Display Name")) or poc
    mult    = norm_multiplier(row.get(f"Bonus Cat {n} Multiplier"), currency, warnings, card_name, n)
    if mult == 0.0:
        warnings.append(f"  ⚠ Cat {n} ({poc}): Multiplier is 0 or missing — included as 0")
    has_lim = norm_bool(row.get(f"Bonus Cat {n} Has Limit?"))
    limit   = norm_num(row.get(f"Bonus Cat {n} Spend Limit ($)"), 0.0)
    period  = norm_str(row.get(f"Bonus Cat {n} Limit Period")) or ""
    if poc not in POC_CATEGORIES:
        warnings.append(f"  ⚠ Cat {n}: '{poc}' is not a standard PoC category "
                        f"({', '.join(sorted(POC_CATEGORIES))})")
    return M({
        "spendBonusCategoryName": S(display),
        "pocCategory":            S(poc),
        "earnMultiplier":         N(mult),
        "isSpendLimit":           BOOL(has_lim),
        "spendLimit":             N(int(limit)),
        "spendLimitResetPeriod":  S(period),
    })

def build_benefit(row, n):
    title = norm_str(row.get(f"Benefit {n} Title"))
    desc  = norm_str(row.get(f"Benefit {n} Description"))
    if not title and not desc: return None
    return M({
        "benefitTitle": S(title or ""),
        "benefitDesc":  S(desc  or ""),
    })

# ── Main conversion loop ──────────────────────────────────────────────────────
all_cards  = []
all_warnings = []

for _, row in df.iterrows():
    # In Rev2, "Card Name" is the issuer and "Card Key (slug)" is the card name
    raw_card_name = norm_str(row.get("Card Name"))
    raw_card_key  = norm_str(row.get("Card Key (slug)"))
    if not raw_card_name:
        continue

    # Build a full card name from issuer + card key (e.g. "Chase freedom Unlimited")
    card_name = f"{raw_card_name} {raw_card_key}" if raw_card_key else raw_card_name
    card_key  = raw_card_key or raw_card_name.lower().replace(" ", "-")

    warnings = [f"\n📋 {card_name}"]
    issuer   = norm_issuer(row.get("Card Issuer"))
    fee      = norm_num(row.get("Annual Fee ($)"), 0.0)
    currency = norm_currency(row.get("Earn Currency"))
    base_rate  = norm_num(row.get("Base Earn Rate"), 0.0)
    base_cash  = norm_num(row.get("Base Cash Value (¢)"), 0.0)

    if currency == "cashback" and base_cash == 0.0:
        warnings.append("  ⚠ Base Cash Value is 0 for a cashback card")
        base_cash = 0.0
    if currency == "cashback" and 0 < base_cash < 1:
        warnings.append(f"  ⚠ Base Cash Value {base_cash} looks like a decimal % — kept as-is")

    # Bonus categories
    bonus_cats = []
    for n in range(1, 4):
        cat = build_bonus_cat(row, n, currency, warnings, card_name)
        if cat:
            bonus_cats.append(cat)

    # Benefits
    benefits = []
    for n in range(1, 3):
        b = build_benefit(row, n)
        if b:
            benefits.append(b)

    if len(warnings) == 1:
        warnings.append("  ✅ No issues found")

    all_warnings.extend(warnings)

    ddb_item = {
        "PK":                     S(f"CARD#{card_key}"),
        "SK":                     S("DETAILS"),
        "entityType":             S("ReferenceCard"),
        "cardKey":                S(card_key),
        "cardName":               S(card_name),
        "cardIssuer":             S(issuer),
        "cardImageUrl":           S(""),
        "annualFee":              N(int(fee)),
        "baseSpendEarnCurrency":  S(currency),
        "baseSpendEarnValuation": N(base_cash),
        "baseSpendEarnCashValue": N(base_cash),
        "baseSpendAmount":        N(base_rate),
        "spendBonusCategory":     L(bonus_cats),
        "benefit":                L(benefits),
    }

    # Save individual file
    safe_key = card_key.lower().replace(" ", "-")
    fname = f"output/cards_v2/{safe_key}_ddb.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(ddb_item, f, indent=2, ensure_ascii=False)

    all_cards.append(ddb_item)

# Save combined file
combined_path = "output/all_cards_v2_ddb.json"
with open(combined_path, "w", encoding="utf-8") as f:
    json.dump(all_cards, f, indent=2, ensure_ascii=False)

print(f"✅ {len(all_cards)} cards processed")
print(f"✅ Individual JSONs saved to output/cards_v2/")
print(f"✅ Combined JSON saved to {combined_path}")
print("\n" + "="*60)
print("CONVERSION WARNINGS & NOTES")
print("="*60)
for w in all_warnings:
    print(w)

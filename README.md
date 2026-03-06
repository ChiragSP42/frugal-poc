# Card Schema Documentation (POC)

## Overview

This JSON schema is the backbone of the Card Recommendation Engine. It standardizes credit card data (which varies wildly between issuers) into a single, mathematically predictable format. It is modeled after the industry-standard Rewards Credit Card API to ensure future compatibility.

---

## 1. Attribute Dictionary

### Top-Level Attributes

| Attribute | Type | Description |
| --- | --- | --- |
| `cardKey` | String | A unique identifier for the card (e.g., `amex-gold`). |
| `cardName` | String | The official display name of the card. |
| `cardIssuer` | String | The bank that issues the card (e.g., `Chase`, `American Express`). |
| `annualFee` | Number | The yearly cost to hold the card in USD. |
| `baseSpendEarnCurrency` | String | What you actually earn (`points`, `miles`, or `cash back`). |

### The "Big Three" Base Earning Attributes

*These define how the card earns on "everything else" (non-bonus categories) and what those earnings are actually worth.*

| Attribute | Type | Description |
| --- | --- | --- |
| **`baseSpendAmount`** | Number | **The Base Multiplier.** How many points/cents you earn per $1 spent on un-categorized purchases. Usually `1.0` (1x points) or `2.0` (2% cashback). |
| **`baseSpendEarnCashValue`** | Number | **The Cash Conversion Rate.** The exact value of 1 point when redeemed for a statement credit or cash, represented in cents. |
| **`baseSpendEarnValuation`** | Number | **The Travel Conversion Rate.** The estimated value of 1 point when optimized for travel transfers, represented in cents. |

### The Bonus Categories Array (`spendBonusCategory`)

*This array holds the logic for categorized spending (Dining, Groceries, etc.).*

| Attribute | Type | Description |
| --- | --- | --- |
| `spendBonusCategoryName` | String | The mapped universal category (e.g., `Dining`, `Groceries`). |
| `earnMultiplier` | Number | The multiplier for this category (e.g., `4.0` for 4x points). |
| `isSpendLimit` | Integer | Boolean flag (`1` = True, `0` = False) indicating if there is a spending cap. |
| `spendLimit` | Number | The maximum USD amount the user can spend before the multiplier drops back to the base rate. |
| `spendLimitResetPeriod` | String | When the cap resets (usually `Year`, `Quarter`, or `Month`). |

---

## 2. Deep Dive: Understanding the "Big Three"

It is easy to get these confused. Think of them like this:

* **`baseSpendAmount`** is **HOW MANY** points you get.
* **`baseSpendEarnCashValue` / `Valuation**` is **WHAT THEY ARE WORTH**.

### Example: American Express Gold

* `baseSpendAmount`: **1.0** (You earn 1 point per $1 spent on a generic purchase like buying a couch).
* `baseSpendEarnCashValue`: **0.6** (Amex points are terrible for cash. 1 point = 0.6 cents).
* `baseSpendEarnValuation`: **2.2** (Amex points are great for travel. 1 point = 2.2 cents if transferred to airlines).

### Example: Citi Double Cash

* `baseSpendAmount`: **2.0** (You earn 2 "points/cents" per $1 spent).
* `baseSpendEarnCashValue`: **1.0** (It's a pure cash card. 1 point = exactly 1 cent).
* `baseSpendEarnValuation`: **1.0** (No travel transfer bonus, so it stays at 1 cent).

---

## 3. How to Calculate Cashback for a Transaction

To calculate the absolute best card for a transaction, or to calculate how much a user missed out on, your engine must follow these 3 steps:

### Step 1: Find the Active Multiplier

Look at the transaction's Universal Category (e.g., `Dining`).

* Does the card have a `spendBonusCategoryName` that matches `Dining`?
* **YES:** Use the `earnMultiplier` (e.g., `4.0`). *(Note: Check if `spendLimit` has been hit first!)*
* **NO:** Use the `baseSpendAmount` (e.g., `1.0`).

### Step 2: Determine the User's Preference (The Valuation)

* If the user wants pure cash back, use `baseSpendEarnCashValue` (e.g., `0.6`).
* If the user wants to maximize travel rewards, use `baseSpendEarnValuation` (e.g., `2.2`).

### Step 3: The Math Formula

To find the actual monetary value the user gets back, use this formula:

**`Cashback ($) = Transaction Amount * Active Multiplier * (Valuation / 100)`**

*(We divide the valuation by 100 because the JSON stores it in cents, but we want the final result in dollars).*

#### Walkthrough Scenario

User spends **$100** on **Dining** using an **Amex Gold** card. They are set to **Cashback** mode.

1. **Find Multiplier:** Category is `Dining`. Amex Gold gives `4.0`x points on Dining.
2. **Find Valuation:** User wants Cash. Amex Gold `baseSpendEarnCashValue` is `0.6`.
3. **Calculate:** Points Earned = 100 * 4.0 = **400 points**

* Cash Value = 400 * (0.6 / 100) = **$2.40** *The effective return rate is 2.4%.*

"""
Hardcoded seasonal task rule engine.

Covers all USDA hardiness zones (1a–13b). Rules are month-aware and zone-aware.
Never raises — always returns a list (may be empty).
"""
from dataclasses import dataclass

# ── Zone groupings ────────────────────────────────────────────────────────────

ZONES_COLD = ["1a", "1b", "2a", "2b", "3a", "3b", "4a", "4b", "5a", "5b"]
ZONES_COOL = ["6a", "6b", "7a", "7b"]
ZONES_WARM = ["8a", "8b", "9a", "9b"]
ZONES_HOT  = ["10a", "10b", "11a", "11b", "12a", "12b", "13a", "13b"]
ALL_ZONES  = ZONES_COLD + ZONES_COOL + ZONES_WARM + ZONES_HOT


@dataclass
class SeasonalTask:
    title: str
    description: str
    task_type: str   # "plant", "fertilize", "spray", "prune", "harvest", "water", "prepare"
    month: int       # 1–12
    zones: list[str]
    urgency: str     # "high", "medium", "low"


# ── Rule table ────────────────────────────────────────────────────────────────

_RULES: list[SeasonalTask] = [
    # ── Universal (ALL_ZONES) ─────────────────────────────────────────────────
    SeasonalTask("Review seed catalogs and plan garden layout",
                 "Browse catalogs and sketch out which beds will hold which crops this season.",
                 "prepare", 1, ALL_ZONES, "low"),
    SeasonalTask("Inventory and test seeds, check stored equipment",
                 "Check germination rates on saved seeds and inspect tools for repair or replacement.",
                 "prepare", 2, ALL_ZONES, "low"),
    SeasonalTask("Start a soil amendment program",
                 "Add compost, aged manure, or other amendments if not already doing so.",
                 "prepare", 3, ALL_ZONES, "medium"),
    SeasonalTask("Weed before they set seed",
                 "Early weeding prevents exponential seed bank growth — pull or hoe before flowering.",
                 "prepare", 4, ALL_ZONES, "high"),
    SeasonalTask("Mulch beds to retain moisture",
                 "Apply 2–3 inches of mulch around established plants to conserve soil moisture.",
                 "prepare", 5, ALL_ZONES, "medium"),
    SeasonalTask("Monitor for pest pressure — peak insect season begins",
                 "Scout crops twice a week. Identify pests early before populations explode.",
                 "spray", 6, ALL_ZONES, "high"),
    SeasonalTask("Deep water established plants during heat",
                 "Water deeply and infrequently to encourage deep root growth during summer heat.",
                 "water", 7, ALL_ZONES, "high"),
    SeasonalTask("Begin planning fall garden",
                 "Calculate back-count dates from first fall frost to determine transplant and seed-start dates.",
                 "prepare", 8, ALL_ZONES, "medium"),
    SeasonalTask("Collect seeds from heirloom varieties",
                 "Allow representative fruits and pods to fully mature before collecting and drying seeds.",
                 "harvest", 9, ALL_ZONES, "low"),
    SeasonalTask("Clean and store garden tools",
                 "Scrub soil off tools, sharpen edges, oil wooden handles, and store in a dry location.",
                 "prepare", 10, ALL_ZONES, "low"),
    SeasonalTask("Apply winter mulch to protect perennial roots",
                 "Spread 3–4 inches of straw or shredded leaves over perennial beds before ground freezes.",
                 "prepare", 11, ALL_ZONES, "medium"),
    SeasonalTask("Review the season — journal successes and failures",
                 "Record what worked, what failed, and what you want to try differently next year.",
                 "prepare", 12, ALL_ZONES, "low"),

    # ── Cold zones (1–5) ─────────────────────────────────────────────────────
    SeasonalTask("Start seeds indoors for tomatoes and peppers",
                 "Sow tomatoes and peppers indoors 8–10 weeks before your last expected frost date.",
                 "plant", 2, ZONES_COLD, "high"),
    SeasonalTask("Start onions and leeks indoors",
                 "Onions and leeks need a long head start — sow indoors now for transplanting in spring.",
                 "plant", 3, ZONES_COLD, "high"),
    SeasonalTask("Direct sow cold-tolerant crops outdoors",
                 "Sow spinach, lettuce, and peas directly once soil is workable, even if frosts continue.",
                 "plant", 4, ZONES_COLD, "high"),
    SeasonalTask("Harden off transplants and plant after last frost date",
                 "Acclimate indoor starts over 7–10 days before planting out after your frost-free date.",
                 "plant", 5, ZONES_COLD, "high"),
    SeasonalTask("Direct sow beans, squash, and cucumbers",
                 "Soil is warm enough for direct sowing warm-season crops — no transplanting needed.",
                 "plant", 6, ZONES_COLD, "high"),
    SeasonalTask("Harvest before first frost — protect tender crops with row cover",
                 "Monitor forecasts closely. Harvest ripe fruit and use floating row cover on frost nights.",
                 "harvest", 9, ZONES_COLD, "high"),
    SeasonalTask("Plant garlic for next year",
                 "Plant garlic cloves 2 inches deep, 6 inches apart. Mulch heavily after planting.",
                 "plant", 10, ZONES_COLD, "high"),
    SeasonalTask("Cut back perennials after hard freeze",
                 "Once tops are killed by hard freeze, cut back to 2–4 inches and compost debris.",
                 "prune", 11, ZONES_COLD, "medium"),

    # ── Cool zones (6–7) ─────────────────────────────────────────────────────
    SeasonalTask("Start tomatoes and peppers indoors",
                 "Sow tomatoes and peppers indoors 6–8 weeks before your last expected frost date.",
                 "plant", 2, ZONES_COOL, "high"),
    SeasonalTask("Direct sow peas, spinach, and lettuce outdoors",
                 "Soil temps above 40°F are sufficient — direct sow cold-tolerant crops now.",
                 "plant", 3, ZONES_COOL, "high"),
    SeasonalTask("Plant cool-season transplants (broccoli, cabbage, kale)",
                 "Set out hardened-off brassica transplants — they can handle light frost.",
                 "plant", 4, ZONES_COOL, "high"),
    SeasonalTask("Plant warm-season crops after last frost",
                 "Transplant tomatoes, peppers, and squash once frost risk has passed.",
                 "plant", 5, ZONES_COOL, "high"),
    SeasonalTask("Start fall brassicas from seed for September transplant",
                 "Sow broccoli, cabbage, and kale indoors to have transplant-ready starts in September.",
                 "plant", 8, ZONES_COOL, "high"),
    SeasonalTask("Direct sow fall greens",
                 "Sow spinach, arugula, and lettuce directly for a fall and early winter harvest.",
                 "plant", 9, ZONES_COOL, "high"),
    SeasonalTask("Plant garlic and spring bulbs",
                 "Plant garlic cloves and spring-flowering bulbs (tulips, daffodils) before ground freezes.",
                 "plant", 10, ZONES_COOL, "high"),
    SeasonalTask("Plant cover crops in empty beds",
                 "Sow winter rye, crimson clover, or hairy vetch to protect and enrich soil over winter.",
                 "plant", 11, ZONES_COOL, "medium"),

    # ── Warm zones (8–9) ─────────────────────────────────────────────────────
    SeasonalTask("Plant cool-season crops outdoors",
                 "Direct sow or transplant lettuce, spinach, kale, and broccoli — prime growing season.",
                 "plant", 1, ZONES_WARM, "high"),
    SeasonalTask("Start tomatoes and peppers indoors for spring planting",
                 "Start warm-season crops indoors 6–8 weeks before your last frost date (mid-March Zone 8).",
                 "plant", 2, ZONES_WARM, "high"),
    SeasonalTask("Plant tomatoes, peppers, and squash after last frost",
                 "Last frost in Zone 8 is typically mid-March — transplant warm-season crops now.",
                 "plant", 3, ZONES_WARM, "high"),
    SeasonalTask("Apply pre-emergent herbicide before summer weeds germinate",
                 "Apply when soil temps reach 55°F to prevent crabgrass and other summer annuals.",
                 "spray", 4, ZONES_WARM, "high"),
    SeasonalTask("Monitor for fungal pressure — humidity rises",
                 "Scout for early blight, powdery mildew, and downy mildew. Apply preventive fungicide.",
                 "spray", 5, ZONES_WARM, "high"),
    SeasonalTask("Succession plant heat-tolerant crops",
                 "Sow okra, sweet potatoes, and southern peas for a mid-summer to fall harvest.",
                 "plant", 6, ZONES_WARM, "medium"),
    SeasonalTask("Reduce fertilizer — heat stress makes feeding counterproductive",
                 "Slow or stop fertilizing during peak heat. Resume once temperatures moderate.",
                 "fertilize", 7, ZONES_WARM, "medium"),
    SeasonalTask("Start fall tomatoes from transplant for second crop",
                 "Set out heat-tolerant tomato transplants now for a fall harvest before first frost.",
                 "plant", 8, ZONES_WARM, "high"),
    SeasonalTask("Plant fall cool-season crops",
                 "Transplant broccoli, cauliflower, collards, and turnips for fall harvest.",
                 "plant", 9, ZONES_WARM, "high"),
    SeasonalTask("Plant garlic, onion sets, and spring bulbs",
                 "Plant garlic and onion sets for harvest next summer. Add spring-flowering bulbs now.",
                 "plant", 10, ZONES_WARM, "high"),
    SeasonalTask("Plant cool-season crops for winter harvest",
                 "Direct sow or transplant lettuce, spinach, and kale for harvest through winter.",
                 "plant", 11, ZONES_WARM, "high"),
    SeasonalTask("Plant cover crops in empty beds",
                 "Sow crimson clover or Austrian winter peas to protect and enrich soil over winter.",
                 "plant", 12, ZONES_WARM, "medium"),

    # ── Hot zones (10–13) ────────────────────────────────────────────────────
    SeasonalTask("Peak cool-season growing — harvest lettuce, tomatoes, and beans",
                 "This is prime growing season in hot zones. Harvest regularly to maintain production.",
                 "harvest", 1, ZONES_HOT, "high"),
    SeasonalTask("Start heat-tolerant summer crops indoors",
                 "Start okra, sweet potato slips, and Malabar spinach indoors for spring planting.",
                 "plant", 2, ZONES_HOT, "high"),
    SeasonalTask("Last chance for cool-season crops before heat arrives",
                 "Harvest remaining cool-season crops and direct sow quick-maturing varieties now.",
                 "plant", 3, ZONES_HOT, "high"),
    SeasonalTask("Plant tropical and heat-loving crops",
                 "Transplant okra, sweet potato, Malabar spinach, and heat-tolerant herbs.",
                 "plant", 4, ZONES_HOT, "high"),
    SeasonalTask("Use shade cloth for sensitive crops",
                 "Install 30–50% shade cloth over heat-sensitive crops during the hottest part of the day.",
                 "prepare", 5, ZONES_HOT, "medium"),
    SeasonalTask("Focus on irrigation management and heat-tolerant varieties",
                 "Deep water 2–3 times per week. Switch to heat-tolerant varieties if crops are struggling.",
                 "water", 6, ZONES_HOT, "high"),
    SeasonalTask("Focus on irrigation management and heat-tolerant varieties",
                 "Deep water 2–3 times per week. Switch to heat-tolerant varieties if crops are struggling.",
                 "water", 7, ZONES_HOT, "high"),
    SeasonalTask("Focus on irrigation management and heat-tolerant varieties",
                 "Deep water 2–3 times per week. Switch to heat-tolerant varieties if crops are struggling.",
                 "water", 8, ZONES_HOT, "high"),
    SeasonalTask("Begin second cool-season cycle — direct sow greens",
                 "As temperatures moderate, direct sow lettuce, arugula, spinach, and brassicas.",
                 "plant", 9, ZONES_HOT, "high"),
    SeasonalTask("Plant tomatoes and peppers for fall/winter crop",
                 "Transplant tomatoes and peppers now for harvest through the cool season.",
                 "plant", 10, ZONES_HOT, "high"),
    SeasonalTask("Main growing season — full garden production underway",
                 "Succession plant, harvest regularly, and prepare beds for additional crops.",
                 "plant", 11, ZONES_HOT, "high"),
    SeasonalTask("Main growing season — full garden production underway",
                 "Succession plant, harvest regularly, and prepare beds for additional crops.",
                 "plant", 12, ZONES_HOT, "high"),
]


# ── Service function ──────────────────────────────────────────────────────────

def get_seasonal_tasks(zone: str, month: int) -> list[SeasonalTask]:
    """
    Returns tasks applicable to the given zone and month.

    Normalizes input: strips whitespace, lowercases before matching.
    Tasks with zones=ALL_ZONES are always included.
    If zone is unrecognized, returns only ALL_ZONES tasks — never errors.
    Never raises — always returns a list (may be empty).
    """
    try:
        normalized = zone.strip().lower()
        results = []
        for rule in _RULES:
            if rule.month != month:
                continue
            # ALL_ZONES tasks are included for any zone
            if rule.zones is ALL_ZONES:
                results.append(rule)
                continue
            # Zone-specific tasks: match normalized zone string
            if normalized in [z.lower() for z in rule.zones]:
                results.append(rule)
        return results
    except Exception:
        return []

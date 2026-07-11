"""
Transaction categorization based on keywords found in the description.
Categories cover common cashback buckets plus general spending.

NOTE: the keyword lists below are the literal Spanish text that appears on
Mexican bank/store statements (merchant names, bank-generated phrases), so
they are intentionally left in Spanish - translating them would break the
matching against real statement text.
"""

RULES = [
    ("Restaurants", [
        "REST", "RESTAURANT", "STARBUCKS", "DAIRY QUEEN", "PIZZERIA", "IZAKAYA",
        "CHURCHS", "KFC", "TATAKAE", "ITALIANNIS", "EL GLOBO", "FRUTERIA",
        "CARNEMART", "CARN ", "DULCERIA", "TACOS", "COLIBRI DESAYUNOS",
        "CINEPOLIS", "KIOSKO",
    ]),
    ("Subscriptions/Software", [
        "SPOTIFY", "NETFLIX", "MSFT", "MICROSOFT", "ANTHROPIC", "CLAUDE",
        "OPENAI", "CHATGPT", "GOOGLE", "ICLOUD", "DROPBOX", "ADOBE", "DISNEY",
        "HBO", "AMAZON PRIME", "CRUNCHYROLL",
    ]),
    ("Health/Gym", [
        "SMARTFIT", "SMART FIT", "GYM", "SPORTS WORLD",
    ]),
    ("Groceries/Supermarkets", [
        "WAL MART", "WALMART", "SORIANA", "COSTCO", "SUPERCENTER", "SAMS",
    ]),
    ("Gas Stations", [
        "GASOL", "PEMEX", "GAS ", "COMBUSTIBLE",
    ]),
    ("Electronics", [
        "INSIGNIA ECOMMERCE", "ELECTRO", "COMPUTA", "APPLE", "AMAZON", "STEAM",
        "BEST BUY", "MERCADOLIBRE",
    ]),
    ("Pharmacy/Health", [
        "FARM", "FARMACIA", "BENAVIDES", "HDI SEG", "SEGURO", "HOSPITAL",
        "CLINICA", "DR ", "DOCTOR", "FAR GUAD", "KIOSKO IMSS",
    ]),
    ("Transportation/Travel", [
        "AUTOB", "AEROPUERTO", "AEROP", "AICM", "AUTOTRANSP", "UBER", "DIDI",
        "TAXI", "GASOLINERA", "KIA", "AUTOMOTRIZ", "MUSEO", "VOLARISMXN",
        "VOLARIS", "AEROMEXICO", "VIVAAEROBUS",
    ]),
    ("Card Interest/Fees", [
        "INTERES", "IVA SOBRE COMISIONES", "COMISION", "ANUALIDAD",
    ]),
    ("Hardware/Home", [
        "FERRETER", "SURTIDORA",
    ]),
    ("Convenience Stores (OXXO/misc.)", [
        "OXXO", "OXX0",  # OXX0 = zero-for-O OCR misread variant
    ]),
    ("Marketplace/Digital Payments", [
        "MERCADO PAGO", "MERCADOPAGO", "MERPAGO", "PAYCLIP", "CLIP MX",
        "D LOCAL", "FACEBK", "ABTS",
    ]),
    ("Services/Subscriptions", [
        "SERVICIOS", "PROTECCION",
    ]),
]

# NOTE: these are the literal Spanish phrases banks use for card payments,
# left in Spanish so they match the actual statement text.
CARD_PAYMENT_KEYWORDS = [
    "GRACIAS POR SU PAGO", "SU PAGO SP", "PAGO SPE", "SU ABONO", "SU PAGO POR",
    "CIAS POR TU PAGO",  # covers Nu's "Grácias por tu pago" (their own accent typo)
]


def categorize(description: str, amount: float) -> str:
    upper = description.upper()

    if amount < 0:
        # Any card payment is categorized separately, unless it's clearly a
        # merchant refund (negative amount that isn't a "card payment")
        if any(kw in upper for kw in CARD_PAYMENT_KEYWORDS):
            return "Payments"
        return "Refunds/Adjustments"

    for category, keywords in RULES:
        for kw in keywords:
            if kw in upper:
                return category
    return "Uncategorized"

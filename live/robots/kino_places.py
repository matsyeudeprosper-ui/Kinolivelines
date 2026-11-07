"""kino_places.py (2026-11-07, owner: "we're not stuck with France and the US - all continents, any language, go around the world").

Where his next client hunt goes: a country where it is daytime RIGHT NOW (08:00-18:00 there), the one he
hunted least recently first, one of its cities, in its language. The law of each country rides along (kino_sales applies it):
  CONSENT_FIRST  cold business email is not allowed without prior consent - their contact form, or only an ask
  SKIP           sanctioned or no way to be paid: never hunted
next_place(now)       -> {"cc", "country", "city", "lang", "local_hour", "rule"}
lang_of(cc) / name_to_cc(name)
Store robots/kino_places.json (git-ignored): when each country was last hunted.
"""
import json, os, random, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_places.json")

# code: (name, language, UTC offset in hours (standard time, close enough for "is it open"), cities)
WORLD = {
    # Europe
    "FR": ("France", "fr", 1, ["Lyon", "Marseille", "Toulouse", "Nantes", "Bordeaux", "Lille", "Rennes", "Nice", "Strasbourg", "Montpellier"]),
    "BE": ("Belgium", "fr", 1, ["Brussels", "Liège", "Namur", "Charleroi"]),
    "CH": ("Switzerland", "fr", 1, ["Geneva", "Lausanne", "Fribourg"]),
    "LU": ("Luxembourg", "fr", 1, ["Luxembourg"]),
    "GB": ("United Kingdom", "en", 0, ["Manchester", "Bristol", "Leeds", "Glasgow", "Liverpool", "Brighton", "Edinburgh"]),
    "IE": ("Ireland", "en", 0, ["Dublin", "Cork", "Galway"]),
    "ES": ("Spain", "es", 1, ["Valencia", "Seville", "Málaga", "Bilbao", "Zaragoza"]),
    "PT": ("Portugal", "pt", 0, ["Porto", "Lisbon", "Braga", "Coimbra"]),
    "NL": ("Netherlands", "nl", 1, ["Utrecht", "Rotterdam", "Eindhoven", "Groningen"]),
    "SE": ("Sweden", "sv", 1, ["Gothenburg", "Malmö", "Uppsala"]),
    "NO": ("Norway", "no", 1, ["Bergen", "Trondheim", "Stavanger"]),
    "FI": ("Finland", "fi", 2, ["Tampere", "Turku", "Oulu"]),
    "GR": ("Greece", "el", 2, ["Thessaloniki", "Patras", "Heraklion"]),
    "CZ": ("Czechia", "cs", 1, ["Brno", "Ostrava", "Plzeň"]),
    "RO": ("Romania", "ro", 2, ["Cluj-Napoca", "Iași", "Timișoara"]),
    "HR": ("Croatia", "hr", 1, ["Split", "Zagreb", "Rijeka"]),
    "MT": ("Malta", "en", 1, ["Valletta", "Sliema"]),
    "CY": ("Cyprus", "el", 2, ["Limassol", "Larnaca"]),
    # Africa
    "MA": ("Morocco", "fr", 1, ["Casablanca", "Marrakech", "Rabat", "Tangier"]),
    "TN": ("Tunisia", "fr", 1, ["Tunis", "Sousse", "Sfax"]),
    "SN": ("Senegal", "fr", 0, ["Dakar", "Saint-Louis", "Thiès"]),
    "CI": ("Côte d'Ivoire", "fr", 0, ["Abidjan", "Bouaké"]),
    "CM": ("Cameroon", "fr", 1, ["Douala", "Yaoundé"]),
    "CD": ("DR Congo", "fr", 1, ["Kinshasa", "Lubumbashi"]),
    "CG": ("Congo", "fr", 1, ["Brazzaville", "Pointe-Noire"]),
    "GA": ("Gabon", "fr", 1, ["Libreville"]),
    "BJ": ("Benin", "fr", 1, ["Cotonou"]),
    "NG": ("Nigeria", "en", 1, ["Lagos", "Abuja", "Port Harcourt", "Ibadan"]),
    "GH": ("Ghana", "en", 0, ["Accra", "Kumasi"]),
    "KE": ("Kenya", "en", 3, ["Nairobi", "Mombasa", "Kisumu"]),
    "TZ": ("Tanzania", "en", 3, ["Dar es Salaam", "Arusha"]),
    "UG": ("Uganda", "en", 3, ["Kampala"]),
    "RW": ("Rwanda", "en", 2, ["Kigali"]),
    "ZA": ("South Africa", "en", 2, ["Cape Town", "Johannesburg", "Durban", "Pretoria"]),
    "MU": ("Mauritius", "fr", 4, ["Port Louis", "Grand Baie"]),
    "EG": ("Egypt", "ar", 2, ["Cairo", "Alexandria"]),
    # Americas
    "US": ("United States", "en", -5, ["Austin", "Denver", "Atlanta", "Portland", "Nashville", "Phoenix", "Tampa", "San Diego", "Chicago"]),
    "CA": ("Canada", "en", -5, ["Toronto", "Calgary", "Ottawa", "Vancouver", "Montreal"]),
    "MX": ("Mexico", "es", -6, ["Guadalajara", "Monterrey", "Mérida", "Puebla"]),
    "BR": ("Brazil", "pt", -3, ["Curitiba", "Belo Horizonte", "Porto Alegre", "Florianópolis", "Recife"]),
    "AR": ("Argentina", "es", -3, ["Córdoba", "Rosario", "Mendoza"]),
    "CL": ("Chile", "es", -3, ["Santiago", "Valparaíso", "Concepción"]),
    "CO": ("Colombia", "es", -5, ["Medellín", "Bogotá", "Cali", "Cartagena"]),
    "PE": ("Peru", "es", -5, ["Lima", "Arequipa", "Cusco"]),
    "UY": ("Uruguay", "es", -3, ["Montevideo"]),
    "CR": ("Costa Rica", "es", -6, ["San José"]),
    "DO": ("Dominican Republic", "es", -4, ["Santo Domingo", "Punta Cana"]),
    "JM": ("Jamaica", "en", -5, ["Kingston", "Montego Bay"]),
    "HT": ("Haiti", "fr", -5, ["Port-au-Prince"]),
    # Asia and Middle East
    "IN": ("India", "en", 5.5, ["Bengaluru", "Pune", "Jaipur", "Kochi", "Ahmedabad"]),
    "PH": ("Philippines", "en", 8, ["Cebu", "Davao", "Manila"]),
    "SG": ("Singapore", "en", 8, ["Singapore"]),
    "MY": ("Malaysia", "en", 8, ["Penang", "Kuala Lumpur", "Johor Bahru"]),
    "TH": ("Thailand", "th", 7, ["Chiang Mai", "Bangkok", "Phuket"]),
    "VN": ("Vietnam", "vi", 7, ["Da Nang", "Ho Chi Minh City", "Hanoi"]),
    "ID": ("Indonesia", "id", 7, ["Bandung", "Yogyakarta", "Denpasar"]),
    "JP": ("Japan", "ja", 9, ["Fukuoka", "Osaka", "Sapporo"]),
    "KR": ("South Korea", "ko", 9, ["Busan", "Daegu"]),
    "AE": ("United Arab Emirates", "en", 4, ["Dubai", "Abu Dhabi", "Sharjah"]),
    "IL": ("Israel", "en", 2, ["Tel Aviv", "Haifa"]),
    "TR": ("Turkey", "tr", 3, ["Izmir", "Antalya", "Bursa"]),
    "LB": ("Lebanon", "fr", 2, ["Beirut"]),
    # Oceania
    "AU": ("Australia", "en", 10, ["Brisbane", "Adelaide", "Perth", "Melbourne", "Hobart"]),
    "NZ": ("New Zealand", "en", 12, ["Christchurch", "Wellington", "Auckland"]),
}
# the law of the reader's country for a cold business email (kino_sales applies it; "asked" people can always be answered)
CONSENT_FIRST = {"DE", "AT", "IT", "PL", "DK"}      # prior consent needed even business to business: contact form only
ASK_FIRST = {"ZA"}                                   # one message that only asks whether they want to see more
SKIP = {"RU", "BY", "IR", "KP", "SY", "CU"}          # sanctioned: no work, no payment - never hunted


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def lang_of(cc):
    return (WORLD.get(str(cc or "").upper()) or ("", "en"))[1]


def name_to_cc(name):
    n = str(name or "").strip().lower()
    for cc, w in WORLD.items():
        if n in (w[0].lower(), cc.lower()):
            return cc
    return None


def open_now(cc, now=None):
    now = now or time.time()
    off = WORLD[cc][2]
    t = time.gmtime(now + off * 3600)
    return 8 <= t.tm_hour < 18, t.tm_hour             # any day: a Sunday email is read on Monday


def next_place(now=None, mark=True):
    """a country in business hours, the least recently hunted first -> where the hunt goes"""
    now = now or time.time()
    st = _load()
    ok = []
    for cc in WORLD:
        if cc in SKIP or cc in CONSENT_FIRST or PAY.get(cc, 0.6) <= 0:
            continue
        o, h = open_now(cc, now)
        if o:                                  # easy-to-pay countries come back sooner: 1 -> 2 days earlier, 0.3 -> 0.6 days
            ok.append((float(st.get(cc) or 0) - PAY.get(cc, 0.6) * 2 * 86400, random.random(), cc, h))
    if not ok:
        return None
    ok.sort()
    _, _, cc, h = ok[0]
    w = WORLD[cc]
    used = (st.get("_cities") or {}).get(cc) or []
    cities = [c for c in w[3] if c not in used] or w[3]
    city = cities[0]
    if mark:
        st[cc] = now
        st.setdefault("_cities", {})[cc] = (used + [city])[-len(w[3]) + 1:] if len(w[3]) > 1 else []
        json.dump(st, open(STORE, "w", encoding="utf-8"), ensure_ascii=False)
    rule = ("South Africa: one first message that only asks whether they want to see what you made - no link, no price"
            if cc in ASK_FIRST else "a business email to a published business address, with the footer and STOP line")
    return {"cc": cc, "country": w[0], "city": city, "lang": w[1], "local_hour": h, "rule": rule}


def hunt_line(p):
    if not p:
        return ""
    return ("TODAY'S PLACE (Matsy 07/11: the whole world, any language): %s, %s - it is %02dh there, business hours. Scan a kind "
            "of small business there (restaurants, salons, shops, trades, clinics, gyms...), write to them in %s (their language - "
            "you write it yourself, as a native would), %s. If PayPal cannot pay out there, the invoice offers crypto." % (
                p["city"], p["country"], p["local_hour"], {"fr": "French", "en": "English", "es": "Spanish", "pt": "Portuguese",
                                                            "nl": "Dutch", "sv": "Swedish", "no": "Norwegian", "fi": "Finnish",
                                                            "el": "Greek", "cs": "Czech", "ro": "Romanian", "hr": "Croatian",
                                                            "ar": "Arabic", "th": "Thai", "vi": "Vietnamese", "id": "Indonesian",
                                                            "ja": "Japanese", "ko": "Korean", "tr": "Turkish"}.get(p["lang"], p["lang"]),
                p["rule"]))


# 2026-11-07 (owner: "favour the countries where people can pay via PayPal or crypto - going where people struggle to pay is a
# waste"): how easily a small business there pays a website online (PayPal/cards/crypto common, budget for a 150-500 EUR site).
# 1 = easy, 0.6 = fair, 0.3 = harder (rarer turns), 0 = not hunted (payments blocked or a banking crisis)
PAY = {cc: 1.0 for cc in ("FR", "BE", "CH", "LU", "GB", "IE", "ES", "PT", "NL", "SE", "NO", "FI", "GR", "CZ", "HR", "MT", "CY",
                          "US", "CA", "AU", "NZ", "SG", "AE", "IL", "JP", "KR", "MY")}
PAY.update({cc: 0.6 for cc in ("RO", "MX", "BR", "AR", "CL", "CO", "PE", "UY", "CR", "DO", "JM", "MA", "TN", "ZA", "MU", "TR", "IN",
                               "PH", "TH", "VN", "ID", "KE")})
PAY.update({cc: 0.3 for cc in ("SN", "CI", "CM", "NG", "GH", "TZ", "UG", "RW", "EG", "GA")})
PAY.update({cc: 0.0 for cc in ("CD", "CG", "HT", "LB", "BJ")})

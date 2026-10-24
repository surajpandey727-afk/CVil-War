"""Place-name data for the UK location policy (see :mod:`app.core.geo.classify`).

Data, not logic: adding a town or a country is adding an entry. Every key is already in the
normalised form the classifier compares against (casefolded, punctuation collapsed to single
spaces), so lookups are plain dictionary hits.

The tables are deliberately asymmetric. UK places are listed generously, because a UK job that
fails to classify is quarantined and the operator never sees it. Foreign places are listed only
far enough to recognise the postings that actually arrive — US tech hubs, the EU cities the
remote boards favour — because anything unrecognised is already quarantined, not shown.
"""

from __future__ import annotations

#: Country tokens that mean the United Kingdom. "england"/"scotland"/... are constituent
#: countries, and a posting naming one is as UK-located as one naming the UK.
UK_COUNTRY_TOKENS = frozenset(
    {
        "uk", "u k", "united kingdom", "gb", "gbr", "great britain", "britain", "england",
        "scotland", "wales", "northern ireland", "uk i", "uk ireland", "remote uk", "uk remote",
        "uk wide", "uk nationwide", "nationwide uk", "london area united kingdom",
    }
)  # fmt: skip

#: Normalised UK place name -> (display city, region). Region is the ITL1 region / nation.
_LDN = "London"
UK_PLACES: dict[str, tuple[str, str]] = {
    # London and the districts adverts use instead of the word "London".
    **{
        k: ("London", _LDN)
        for k in (
            "london", "greater london", "central london", "city of london", "the city",
            "east london", "west london", "north london", "south london", "south east london",
            "south west london", "north west london", "london area", "canary wharf",
            "shoreditch", "soho", "holborn", "paddington", "stratford", "clerkenwell", "mayfair",
            "shepherds bush", "white city", "kings cross", "charing cross", "farringdon",
            "blackfriars", "liverpool street", "finsbury", "strand", "oxford circus",
            "westminster", "camden", "islington", "hackney", "southwark", "lambeth", "croydon",
            "ealing", "barnet", "brent", "bromley", "greenwich", "hammersmith", "fulham",
            "haringey", "harrow", "hillingdon", "hounslow", "kensington", "chelsea",
            "lewisham", "merton", "newham", "redbridge", "tower hamlets", "wandsworth",
            "waltham forest", "barking", "dagenham", "bexley", "enfield", "havering",
            "kingston upon thames", "richmond upon thames", "tufnell park", "st john s wood",
            "lea bridge", "ldn",
        )
    },
    "manchester": ("Manchester", "North West"),
    "greater manchester": ("Manchester", "North West"),
    "salford": ("Salford", "North West"),
    "hulme": ("Manchester", "North West"),
    "manchester science park": ("Manchester", "North West"),
    "liverpool": ("Liverpool", "North West"),
    "merseyside": ("Liverpool", "North West"),
    "st helens": ("St Helens", "North West"),
    "warrington": ("Warrington", "North West"),
    "wilmslow": ("Wilmslow", "North West"),
    "stockport": ("Stockport", "North West"),
    "bolton": ("Bolton", "North West"),
    "preston": ("Preston", "North West"),
    "blackburn": ("Blackburn", "North West"),
    "chester": ("Chester", "North West"),
    "winsford": ("Winsford", "North West"),
    "middlewich": ("Middlewich", "North West"),
    "leigh": ("Leigh", "North West"),
    "birmingham": ("Birmingham", "West Midlands"),
    "solihull": ("Solihull", "West Midlands"),
    "coventry": ("Coventry", "West Midlands"),
    "wolverhampton": ("Wolverhampton", "West Midlands"),
    "telford": ("Telford", "West Midlands"),
    "stoke on trent": ("Stoke-on-Trent", "West Midlands"),
    "leeds": ("Leeds", "Yorkshire and The Humber"),
    "sheffield": ("Sheffield", "Yorkshire and The Humber"),
    "york": ("York", "Yorkshire and The Humber"),
    "bradford": ("Bradford", "Yorkshire and The Humber"),
    "huddersfield": ("Huddersfield", "Yorkshire and The Humber"),
    "barnsley": ("Barnsley", "Yorkshire and The Humber"),
    "hull": ("Hull", "Yorkshire and The Humber"),
    "tankersley": ("Tankersley", "Yorkshire and The Humber"),
    "newcastle upon tyne": ("Newcastle upon Tyne", "North East"),
    "newcastle": ("Newcastle upon Tyne", "North East"),
    "sunderland": ("Sunderland", "North East"),
    "durham": ("Durham", "North East"),
    "county durham": ("Durham", "North East"),
    "middlesbrough": ("Middlesbrough", "North East"),
    "nottingham": ("Nottingham", "East Midlands"),
    "leicester": ("Leicester", "East Midlands"),
    "derby": ("Derby", "East Midlands"),
    "loughborough": ("Loughborough", "East Midlands"),
    "lincoln": ("Lincoln", "East Midlands"),
    "mansfield": ("Mansfield", "East Midlands"),
    "northampton": ("Northampton", "East Midlands"),
    "corby": ("Corby", "East Midlands"),
    "alfreton": ("Alfreton", "East Midlands"),
    "cambridge": ("Cambridge", "East of England"),
    "norwich": ("Norwich", "East of England"),
    "ipswich": ("Ipswich", "East of England"),
    "peterborough": ("Peterborough", "East of England"),
    "luton": ("Luton", "East of England"),
    "chelmsford": ("Chelmsford", "East of England"),
    "southend on sea": ("Southend-on-Sea", "East of England"),
    "colchester": ("Colchester", "East of England"),
    "harlow": ("Harlow", "East of England"),
    "welwyn garden city": ("Welwyn Garden City", "East of England"),
    "hemel hempstead": ("Hemel Hempstead", "East of England"),
    "watford": ("Watford", "East of England"),
    "st albans": ("St Albans", "East of England"),
    "bedford": ("Bedford", "East of England"),
    "dunstable": ("Dunstable", "East of England"),
    "pampisford": ("Pampisford", "East of England"),
    "raf mildenhall": ("Mildenhall", "East of England"),
    "oxford": ("Oxford", "South East"),
    "reading": ("Reading", "South East"),
    "milton keynes": ("Milton Keynes", "South East"),
    "brighton": ("Brighton", "South East"),
    "southampton": ("Southampton", "South East"),
    "portsmouth": ("Portsmouth", "South East"),
    "guildford": ("Guildford", "South East"),
    "crawley": ("Crawley", "South East"),
    "maidenhead": ("Maidenhead", "South East"),
    "slough": ("Slough", "South East"),
    "wokingham": ("Wokingham", "South East"),
    "camberley": ("Camberley", "South East"),
    "frimley": ("Frimley", "South East"),
    "chertsey": ("Chertsey", "South East"),
    "kidlington": ("Kidlington", "South East"),
    "basingstoke": ("Basingstoke", "South East"),
    "canterbury": ("Canterbury", "South East"),
    "maidstone": ("Maidstone", "South East"),
    "bristol": ("Bristol", "South West"),
    "bath": ("Bath", "South West"),
    "exeter": ("Exeter", "South West"),
    "plymouth": ("Plymouth", "South West"),
    "gloucester": ("Gloucester", "South West"),
    "cheltenham": ("Cheltenham", "South West"),
    "swindon": ("Swindon", "South West"),
    "bournemouth": ("Bournemouth", "South West"),
    "ringwood": ("Ringwood", "South West"),
    "hungerford": ("Hungerford", "South East"),
    "edinburgh": ("Edinburgh", "Scotland"),
    "glasgow": ("Glasgow", "Scotland"),
    "aberdeen": ("Aberdeen", "Scotland"),
    "dundee": ("Dundee", "Scotland"),
    "stirling": ("Stirling", "Scotland"),
    "inverness": ("Inverness", "Scotland"),
    "gourock": ("Gourock", "Scotland"),
    "north berwick": ("North Berwick", "Scotland"),
    "cardiff": ("Cardiff", "Wales"),
    "swansea": ("Swansea", "Wales"),
    "newport": ("Newport", "Wales"),
    "belfast": ("Belfast", "Northern Ireland"),
    "derry": ("Derry", "Northern Ireland"),
}  # fmt: skip

#: UK counties and regions. A part naming one corroborates a UK reading of the rest.
UK_REGIONS = frozenset(
    {
        "greater london", "greater manchester", "west midlands", "east midlands", "merseyside",
        "west yorkshire", "south yorkshire", "north yorkshire", "east riding of yorkshire",
        "tyne wear", "tyne and wear", "surrey", "kent", "essex", "hampshire", "berkshire",
        "buckinghamshire", "oxfordshire", "hertfordshire", "bedfordshire", "cambridgeshire",
        "norfolk", "suffolk", "sussex", "west sussex", "east sussex", "devon", "cornwall",
        "somerset", "dorset", "wiltshire", "gloucestershire", "worcestershire",
        "warwickshire", "staffordshire", "shropshire", "cheshire", "lancashire", "cumbria",
        "derbyshire", "nottinghamshire", "leicestershire", "lincolnshire", "northamptonshire",
        "county durham", "northumberland", "east lothian", "west lothian", "inverclyde",
        "fife", "lanarkshire", "cardiff county", "windsor maidenhead", "south west england",
        "south east england", "north west england", "north east england",
    }
)  # fmt: skip

#: UK place names with a well-known foreign namesake. Bare, from a source that is not scoped to
#: the UK, these are *ambiguous*: "Cambridge" on a US company's board is usually Massachusetts.
AMBIGUOUS_UK_PLACES = frozenset(
    {
        "birmingham", "cambridge", "richmond", "boston", "perth", "plymouth", "portsmouth",
        "worcester", "durham", "lancaster", "bedford", "gloucester", "hull", "kingston",
        "stratford", "hamilton", "windsor", "peterborough", "newport", "reading", "bath",
        "chester", "lincoln", "newcastle", "derby", "stirling",
    }
)  # fmt: skip

#: Normalised non-UK country names and aliases -> ISO 3166-1 alpha-2.
COUNTRIES: dict[str, str] = {
    "united states": "US", "united states of america": "US", "usa": "US", "us": "US",
    "u s": "US", "america": "US", "canada": "CA", "mexico": "MX", "brazil": "BR",
    "ireland": "IE", "republic of ireland": "IE", "germany": "DE", "deutschland": "DE",
    "allemagne": "DE", "france": "FR", "spain": "ES", "portugal": "PT", "italy": "IT",
    "netherlands": "NL", "belgium": "BE", "switzerland": "CH", "austria": "AT",
    "poland": "PL", "czech republic": "CZ", "czechia": "CZ", "sweden": "SE", "norway": "NO",
    "denmark": "DK", "finland": "FI", "estonia": "EE", "latvia": "LV", "lithuania": "LT",
    "ukraine": "UA", "serbia": "RS", "romania": "RO", "greece": "GR", "turkey": "TR",
    "israel": "IL", "uae": "AE", "united arab emirates": "AE", "saudi arabia": "SA",
    "qatar": "QA", "india": "IN", "singapore": "SG", "japan": "JP", "korea": "KR",
    "south korea": "KR", "china": "CN", "australia": "AU", "new zealand": "NZ",
    "vietnam": "VN", "costa rica": "CR", "ecuador": "EC", "peru": "PE", "argentina": "AR",
    "colombia": "CO", "chile": "CL", "south africa": "ZA", "nigeria": "NG", "kenya": "KE",
    "egypt": "EG", "philippines": "PH", "indonesia": "ID", "malaysia": "MY", "oman": "OM",
}  # fmt: skip

COUNTRY_NAMES: dict[str, str] = {
    "GB": "United Kingdom", "US": "United States", "CA": "Canada", "IE": "Ireland",
    "DE": "Germany", "FR": "France", "ES": "Spain", "NL": "Netherlands", "PT": "Portugal",
    "PL": "Poland", "IN": "India", "SG": "Singapore", "AU": "Australia", "JP": "Japan",
    "IL": "Israel", "AE": "United Arab Emirates", "CH": "Switzerland", "SE": "Sweden",
}  # fmt: skip

#: US states and Canadian provinces, by name and by postal code. A part that is one of these is
#: decisive: "Birmingham, AL" is Alabama however British "Birmingham" sounds.
US_STATES = frozenset(
    {
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
        "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
        "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
        "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
        "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
        "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
        "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
        "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
        "washington d c", "d c",
    }
)  # fmt: skip
US_STATE_CODES = frozenset(
    {
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in",
        "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv",
        "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn",
        "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
    }
)  # fmt: skip
CA_PROVINCE_CODES = frozenset({"on", "bc", "ab", "qc", "mb", "sk", "ns", "nb", "nl", "pe"})

#: Foreign cities that arrive bare often enough to matter, -> ISO country.
FOREIGN_CITIES: dict[str, str] = {
    **{
        c: "US"
        for c in (
            "san francisco", "south san francisco", "san francisco bay area", "sf", "new york",
            "new york city", "nyc", "manhattan", "brooklyn", "seattle", "sea", "chicago",
            "boston", "austin", "denver", "los angeles", "san diego", "san jose", "sunnyvale",
            "mountain view", "palo alto", "menlo park", "redwood city", "oakland", "san mateo",
            "santa clara", "bellevue", "redmond", "kirkland", "atlanta", "miami", "washington",
            "arlington", "houston", "dallas", "plano", "phoenix", "detroit", "pittsburgh",
            "philadelphia", "salt lake city", "lehi", "minneapolis", "nashville", "raleigh",
            "charlotte", "tampa", "orlando", "las vegas", "portland", "honolulu", "boise",
            "greater chicago area", "new york city metropolitan area",
            "los angeles metropolitan area", "atlanta metropolitan area",
            "miami fort lauderdale area", "grand rapids metropolitan area",
            "greater los angeles",
        )
    },
    "toronto": "CA", "vancouver": "CA", "montreal": "CA", "ottawa": "CA", "calgary": "CA",
    "kitchener": "CA", "waterloo": "CA", "regina": "CA", "timmins": "CA",
    "dublin": "IE", "cork": "IE", "galway": "IE",
    "berlin": "DE", "munich": "DE", "munchen": "DE", "hamburg": "DE",
    "frankfurt": "DE", "cologne": "DE", "koln": "DE", "stuttgart": "DE",
    "dusseldorf": "DE", "dinkelscherben": "DE",
    "paris": "FR", "lyon": "FR", "amsterdam": "NL", "rotterdam": "NL", "barcelona": "ES",
    "barcelona area": "ES", "madrid": "ES", "lisbon": "PT", "warsaw": "PL", "krakow": "PL",
    "prague": "CZ", "stockholm": "SE", "copenhagen": "DK", "oslo": "NO", "helsinki": "FI",
    "zurich": "CH", "geneva": "CH", "vienna": "AT", "brussels": "BE",
    "milan": "IT", "rome": "IT", "tallinn": "EE", "riga": "LV", "vilnius": "LT",
    "belgrade": "RS", "novi sad": "RS", "bucharest": "RO", "athens": "GR", "istanbul": "TR",
    "tel aviv": "IL", "tel aviv yafo": "IL", "dubai": "AE", "abu dhabi": "AE", "doha": "QA",
    "riyadh": "SA", "bengaluru": "IN", "bangalore": "IN", "pune": "IN", "hyderabad": "IN",
    "delhi": "IN", "mumbai": "IN", "singapore": "SG", "tokyo": "JP", "seoul": "KR",
    "beijing": "CN", "shanghai": "CN", "sydney": "AU", "melbourne": "AU", "brisbane": "AU",
    "auckland": "NZ", "sao paulo": "BR", "mexico city": "MX",
    "quito": "EC", "lima": "PE",
}  # fmt: skip

#: Areas wider than a country. A posting naming only these may or may not include the UK.
MACRO_REGIONS = frozenset(
    {
        "europe", "emea", "eu", "european timezones", "worldwide", "global", "anywhere",
        "international", "remote international", "americas", "amer", "north america",
        "northern america", "latam", "apac", "asia", "africa", "oceania", "us timezones",
        "usa timezones", "iberia", "dach", "nordics",
    }
)  # fmt: skip

#: UK postcode area (the letters of the outward code) -> its post town, for adverts that give
#: only a postcode. These are Royal Mail's area names, so "M" is the Manchester area — which
#: is what the posting says, not a claim about a specific borough.
POSTCODE_AREAS: dict[str, str] = {
    **dict.fromkeys(("EC", "WC", "E", "N", "NW", "SE", "SW", "W"), "London"),
    "M": "Manchester", "B": "Birmingham", "L": "Liverpool", "LS": "Leeds", "S": "Sheffield",
    "G": "Glasgow", "EH": "Edinburgh", "BS": "Bristol", "CF": "Cardiff", "BT": "Belfast",
    "NE": "Newcastle upon Tyne", "NG": "Nottingham", "OX": "Oxford", "CB": "Cambridge",
    "WA": "Warrington", "SK": "Stockport", "BL": "Bolton", "OL": "Oldham", "BB": "Blackburn",
    "PR": "Preston", "LE": "Leicester", "CV": "Coventry", "RG": "Reading", "SO": "Southampton",
    "MK": "Milton Keynes", "LU": "Luton", "EN": "Enfield", "HA": "Harrow", "WD": "Watford",
    "IP": "Ipswich", "NR": "Norwich", "PL": "Plymouth", "DE": "Derby", "CH": "Chester",
    "HX": "Halifax", "TN": "Tonbridge", "AB": "Aberdeen", "DD": "Dundee", "BN": "Brighton",
    "GU": "Guildford", "SL": "Slough", "RH": "Redhill", "KT": "Kingston upon Thames",
    "CR": "Croydon", "BR": "Bromley", "DA": "Dartford", "IG": "Ilford", "RM": "Romford",
    "UB": "Southall", "TW": "Twickenham", "SM": "Sutton", "HP": "Hemel Hempstead",
    "AL": "St Albans", "SG": "Stevenage", "CM": "Chelmsford", "SS": "Southend-on-Sea",
    "CO": "Colchester", "ME": "Rochester", "CT": "Canterbury", "PO": "Portsmouth",
    "BH": "Bournemouth", "SP": "Salisbury", "BA": "Bath", "SN": "Swindon", "GL": "Gloucester",
    "EX": "Exeter", "TQ": "Torquay", "TR": "Truro", "WR": "Worcester", "HR": "Hereford",
    "ST": "Stoke-on-Trent", "WS": "Walsall", "WV": "Wolverhampton", "DY": "Dudley",
    "TF": "Telford", "SY": "Shrewsbury", "LL": "Llandudno", "SA": "Swansea", "NP": "Newport",
    "LD": "Llandrindod Wells", "CW": "Crewe", "WN": "Wigan", "FY": "Blackpool",
    "LA": "Lancaster", "CA": "Carlisle", "DL": "Darlington", "DH": "Durham", "SR": "Sunderland",
    "TS": "Cleveland", "YO": "York", "HG": "Harrogate", "BD": "Bradford", "HD": "Huddersfield",
    "WF": "Wakefield", "HU": "Hull", "DN": "Doncaster", "LN": "Lincoln", "PE": "Peterborough",
    "NN": "Northampton", "KY": "Kirkcaldy", "FK": "Falkirk", "PA": "Paisley", "KA": "Kilmarnock",
    "ML": "Motherwell", "DG": "Dumfries", "TD": "Galashiels", "PH": "Perth", "IV": "Inverness",
}  # fmt: skip

#: Sources whose search is scoped to UK jobs by the upstream itself (Adzuna's /gb/ endpoint,
#: Reed, and the UK visa boards). Their scope is evidence about the job, not about the
#: employer, which is why it is admissible where an employer's HQ or domain is not.
UK_SCOPED_SOURCES = frozenset({"adzuna", "reed", "movejobs", "tarve", "ukvisajobs"})

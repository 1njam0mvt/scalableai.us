# File: app/services/site_categories.py
"""
Categorized website directory for ScalableAI.

Each category lives in its own dict so nothing is mixed together.
SITE_CATEGORIES is merged into brain_service's SITE_MAP at runtime,
so the assistant can open any of these by name ("open shodan",
"open photopea", etc.).

OSINT helpers also expose search/locate URLs so messages like
"trace 8.8.8.8" or "geolocate 1.2.3.4" produce direct results.
"""

CATEGORY_EDITING = {
    "photopea": "https://www.photopea.com",
    "pixlr": "https://pixlr.com",
    "canva": "https://www.canva.com",
    "figma": "https://www.figma.com",
    "remove bg": "https://www.remove.bg",
    "removebg": "https://www.remove.bg",
    "unsplash": "https://unsplash.com",
    "davinci resolve": "https://www.blackmagicdesign.com/products/davinciresolve",
    "capcut": "https://www.capcut.com",
    "kapwing": "https://www.kapwing.com",
    "veed": "https://www.veed.io",
    "clideo": "https://clideo.com",
    "ezgif": "https://ezgif.com",
}

CATEGORY_CYBERSECURITY = {
    "tryhackme": "https://tryhackme.com",
    "try hack me": "https://tryhackme.com",
    "hackthebox": "https://www.hackthebox.com",
    "hack the box": "https://www.hackthebox.com",
    "portswigger": "https://portswigger.net",
    "burp suite": "https://portswigger.net/burp",
    "picoctf": "https://picoctf.org",
    "ctftime": "https://ctftime.org",
    "crackstation": "https://crackstation.net",
    "have i been pwned": "https://haveibeenpwned.com",
    "hibp": "https://haveibeenpwned.com",
    "virus total": "https://www.virustotal.com",
    "virustotal": "https://www.virustotal.com",
    "shodan": "https://www.shodan.io",
    "censys": "https://search.censys.io",
    "exploit db": "https://www.exploit-db.com",
    "exploitdb": "https://www.exploit-db.com",
    "cve": "https://cve.mitre.org",
    "nvd": "https://nvd.nist.gov",
    "owasp": "https://owasp.org",
    "cisa": "https://www.cisa.gov",
    "malwarebytes": "https://www.malwarebytes.com",
    "pentest tools": "https://pentest-tools.com",
    "hashcat": "https://hashcat.net/hashcat",
    "nmap": "https://nmap.org",
    "kali": "https://www.kali.org",
    "parrot os": "https://www.parrotsec.org",
    "cyberchef": "https://gchq.github.io/CyberChef",
    "1337x": "https://1337x.to",
    "leakpeek": "https://leakpeek.com",
}

CATEGORY_OSINT = {
    "osint framework": "https://osintframework.com",
    "intelx": "https://intelx.io",
    "intelligence x": "https://intelx.io",
    "dehashed": "https://www.dehashed.com",
    "hunter": "https://hunter.io",
    "snusbase": "https://snusbase.com",
    "epieos": "https://epieos.com",
    "whatsmyname": "https://whatsmyname.app",
    "namechk": "https://namechk.com",
    "instant username": "https://instantusername.com",
    "maltego": "https://www.maltego.com",
    "creepy": "https://www.geocreepy.com",
    "sherlock": "https://github.com/sherlock-project/sherlock",
    "bellingcat": "https://www.bellingcat.com",
    "google dorks": "https://www.exploit-db.com/google-hacking-database",
    "ghdb": "https://www.exploit-db.com/google-hacking-database",
    "archive org": "https://web.archive.org",
    "wayback machine": "https://web.archive.org",
    "whois": "https://who.is",
    "dnsdumpster": "https://dnsdumpster.com",
    "security trails": "https://securitytrails.com",
    "securitytrails": "https://securitytrails.com",
    "bing ip": "https://www.bing.com/search?q=ip%3A",
    "ipinfo": "https://ipinfo.io",
    "ip api": "https://ip-api.com",
    "ip lookup": "https://ipinfo.io",
    "whatismyip": "https://www.whatismyip.com",
    "whoer": "https://whoer.net",
    "have i been breached": "https://haveibeenpwned.com",
    "truecaller": "https://www.truecaller.com",
    "tineye": "https://tineye.com",
    "pim eyes": "https://pimeyes.com",
    "osint": "https://osintframework.com",
}

CATEGORY_DEV = {
    "github": "https://github.com",
    "gitlab": "https://gitlab.com",
    "stackoverflow": "https://stackoverflow.com",
    "codepen": "https://codepen.io",
    "replit": "https://replit.com",
    "codesandbox": "https://codesandbox.io",
    "glitch": "https://glitch.com",
    "vercel": "https://vercel.com",
    "netlify": "https://netlify.com",
    "heroku": "https://heroku.com",
    "docker hub": "https://hub.docker.com",
    "npm": "https://www.npmjs.com",
    "pypi": "https://pypi.org",
    "hugging face": "https://huggingface.co",
    "kaggle": "https://www.kaggle.com",
    "colab": "https://colab.research.google.com",
    "jupyter": "https://jupyter.org",
    "leetcode": "https://leetcode.com",
    "hackerrank": "https://www.hackerrank.com",
    "codeforces": "https://codeforces.com",
    "codewars": "https://www.codewars.com",
    "dev docs": "https://devdocs.io",
    "mdn": "https://developer.mozilla.org",
    "w3schools": "https://www.w3schools.com",
    "geeksforgeeks": "https://www.geeksforgeeks.org",
    "notion": "https://www.notion.so",
}

CATEGORY_SHOPPING = {
    "amazon": "https://www.amazon.com",
    "flipkart": "https://www.flipkart.com",
    "ebay": "https://www.ebay.com",
    "aliexpress": "https://www.aliexpress.com",
    "myntra": "https://www.myntra.com",
    "meesho": "https://www.meesho.com",
    "walmart": "https://www.walmart.com",
    "etsy": "https://www.etsy.com",
}

CATEGORY_EDU = {
    "wikipedia": "https://www.wikipedia.org",
    "medium": "https://medium.com",
    "coursera": "https://www.coursera.org",
    "udemy": "https://www.udemy.com",
    "edx": "https://www.edx.org",
    "khan academy": "https://www.khanacademy.org",
    "freecodecamp": "https://www.freecodecamp.org",
    "brilliant": "https://brilliant.org",
    "duolingo": "https://www.duolingo.com",
    "wolfram alpha": "https://www.wolframalpha.com",
    "arxiv": "https://arxiv.org",
    "google scholar": "https://scholar.google.com",
}

CATEGORY_MEDIA = {
    "netflix": "https://www.netflix.com",
    "prime video": "https://www.primevideo.com",
    "disney plus": "https://www.disneyplus.com",
    "hotstar": "https://www.hotstar.com",
    "youtube music": "https://music.youtube.com",
    "soundcloud": "https://soundcloud.com",
    "twitch": "https://www.twitch.tv",
    "pinterest": "https://www.pinterest.com",
    "tumblr": "https://www.tumblr.com",
    "quora": "https://www.quora.com",
    "telegram": "https://web.telegram.org",
    "discord": "https://discord.com/app",
    "spotify": "https://open.spotify.com",
    "tiktok": "https://www.tiktok.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://twitter.com",
    "x.com": "https://x.com",
    "reddit": "https://www.reddit.com",
    "facebook": "https://www.facebook.com",
    "linkedin": "https://www.linkedin.com",
    "whatsapp": "https://web.whatsapp.com",
    "gmail": "https://mail.google.com",
    "drive": "https://drive.google.com",
    "zoom": "https://zoom.us",
    "google classroom": "https://classroom.google.com",
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "maps": "https://www.google.com/maps",
    "openstreetmap": "https://www.openstreetmap.org",
    "street view": "https://www.google.com/streetview",
    "google earth": "https://earth.google.com",
    "flightradar": "https://www.flightradar24.com",
    "flight radar": "https://www.flightradar24.com",
    "marine traffic": "https://www.marinetraffic.com",
    "sun calc": "https://www.suncalc.org",
}

CATEGORY_TOOLS = {
    "gmail 2": "https://mail.google.com",
    "pdf24": "https://tools.pdf24.org",
    "smallpdf": "https://smallpdf.com",
    "ilovepdf": "https://www.ilovepdf.com",
    "word counter": "https://wordcounter.net",
    "translate": "https://translate.google.com",
    "deep l": "https://www.deepl.com",
    "deepl": "https://www.deepl.com",
    "speedtest": "https://www.speedtest.net",
    "fast": "https://fast.com",
    "weather": "https://weather.com",
    "pomofocus": "https://pomofocus.io",
    "todoist": "https://todoist.com",
    "trello": "https://trello.com",
    "slack": "https://slack.com",
}

SITE_CATEGORIES = {
    "editing": CATEGORY_EDITING,
    "cyber": CATEGORY_CYBERSECURITY,
    "osint": CATEGORY_OSINT,
    "dev": CATEGORY_DEV,
    "shopping": CATEGORY_SHOPPING,
    "education": CATEGORY_EDU,
    "media": CATEGORY_MEDIA,
    "tools": CATEGORY_TOOLS,
}

# Flat lookup: every alias from every category, later categories
# never overwrite earlier definitions (dedup, first-wins).
ALL_SITES = {}
for _cat in SITE_CATEGORIES.values():
    for _name, _url in _cat.items():
        ALL_SITES.setdefault(_name, _url)

# Domains that map a real-world location (used by the OSINT/location flow).
LOCATION_SITES = {
    "openstreetmap": "https://www.openstreetmap.org",
    "google earth": "https://earth.google.com",
    "street view": "https://www.google.com/streetview",
    "flightradar": "https://www.flightradar24.com",
    "flight radar": "https://www.flightradar24.com",
    "marine traffic": "https://www.marinetraffic.com",
    "sun calc": "https://www.suncalc.org",
    "maps": "https://www.google.com/maps",
}


def get_osint_url(kind: str, value: str) -> str:
    """Build a direct OSINT results URL for a given lookup kind + value.

    kind: 'ip', 'email', 'username', 'phone', 'domain', 'location'
    """
    value = (value or "").strip()
    if not value:
        return "https://osintframework.com"

    kind = kind.lower()
    if kind == "ip":
        return f"https://ipinfo.io/{value}"
    if kind == "email":
        return f"https://epieos.com/?q={value}"
    if kind == "username":
        return f"https://whatsmyname.app/?q={value}"
    if kind == "phone":
        return f"https://www.truecaller.com/search/in/{value}"
    if kind == "domain":
        return f"https://dnsdumpster.com/?q={value}" if "dns" in value else f"https://who.is/whois/{value}"
    if kind == "location":
        return f"https://www.google.com/maps/search/{value}"
    return f"https://www.google.com/search?q={value}"

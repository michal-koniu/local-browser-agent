"""/research/ : a company directory (sortable, filterable, paginated table; details on separate pages) and an
answer submission form. Questions need several hops: filter, sort, open a detail page, then submit.

The data is generated from a fixed seed, then a few hand-placed companies make the task answers unique.
"""
import random
import urllib.parse

from . import core
from .core import esc, page, route

PAGE_SIZE = 15
COUNTRIES = ["Germany", "France", "Poland", "Netherlands", "Spain", "Italy", "Sweden", "Austria"]
CITIES = {"Germany": ["Berlin", "Hamburg", "Munich", "Cologne"], "France": ["Paris", "Lyon", "Toulouse", "Nantes"],
          "Poland": ["Warsaw", "Krakow", "Gdansk", "Wroclaw"], "Netherlands": ["Amsterdam", "Rotterdam", "Utrecht"],
          "Spain": ["Madrid", "Barcelona", "Valencia"], "Italy": ["Milan", "Turin", "Bologna"],
          "Sweden": ["Stockholm", "Gothenburg", "Malmo"], "Austria": ["Vienna", "Graz", "Linz"]}
INDUSTRIES = ["Energy", "Healthcare", "Software", "Logistics", "Retail", "Finance", "Manufacturing"]
SUFFIX = {"Energy": ["Power", "Energy", "Solar", "Grid"], "Healthcare": ["Health", "Medical", "Care", "Bio"],
          "Software": ["Labs", "Software", "Systems", "Cloud"], "Logistics": ["Freight", "Logistics", "Cargo"],
          "Retail": ["Market", "Stores", "Goods"], "Finance": ["Capital", "Pay", "Finance"],
          "Manufacturing": ["Works", "Industries", "Machines"]}
PREFIX = ["Alder", "Birch", "Cobalt", "Delta", "Ember", "Fjord", "Granite", "Harbor", "Iris", "Juniper", "Kestrel",
          "Lumen", "Meadow", "Nimbus", "Orbit", "Pine", "Quartz", "Riverside", "Summit", "Tidal", "Umber", "Vertex",
          "Willow", "Xenon", "Yarrow", "Zephyr", "Aster", "Basalt", "Cedar", "Dune", "Echo", "Flint", "Glacier",
          "Helix", "Indigo", "Jasper", "Keystone", "Lattice", "Magnet", "Nova", "Onyx", "Prism", "Quill", "Rune",
          "Sable", "Topaz", "Ultra", "Vale", "Wren", "Yonder", "Zenith", "Arbor", "Beacon", "Crest"]
FIRST = ["Anna", "Ben", "Clara", "David", "Elena", "Felix", "Greta", "Hugo", "Ines", "Jonas", "Karin", "Luis", "Mila",
         "Nils", "Olga", "Pavel", "Rosa", "Stefan", "Tara", "Viktor", "Wanda", "Yusuf", "Zoe", "Marta"]
LAST = ["Adler", "Berg", "Costa", "Dubois", "Engel", "Fischer", "Garcia", "Horvat", "Ivanova", "Jansen", "Kowalski",
        "Lindqvist", "Moreau", "Novak", "Olsen", "Petit", "Rossi", "Schmidt", "Torres", "Urban", "Vogel", "Weber",
        "Zielinski", "Nowak"]

# Hand-placed companies: (name, country, city, industry, founded, employees, ceo)
FIXED = [
    # Germany + Energy: the newest one is the answer of research_newest_energy
    ("Windhafen Power", "Germany", "Hamburg", "Energy", 2017, 140, "Lena Hoffmann"),
    ("Rheinstrom Energy", "Germany", "Cologne", "Energy", 2009, 820, "Markus Brandt"),
    ("Isar Solar", "Germany", "Munich", "Energy", 2013, 310, "Petra Kugler"),
    ("Spree Grid", "Germany", "Berlin", "Energy", 1998, 2400, "Thomas Krause"),
    # decoys: newer energy companies outside Germany, newer German companies outside Energy
    ("Danube Solar", "Austria", "Vienna", "Energy", 2021, 95, "Eva Gruber"),
    ("Kraftwerk Labs", "Germany", "Berlin", "Software", 2022, 60, "Jan Richter"),
    ("Baltic Power", "Poland", "Gdansk", "Energy", 2019, 230, "Piotr Lewandowski"),
    # France + Healthcare: answer of research_healthcare_count (4 companies, the largest one)
    ("Loire Medical", "France", "Nantes", "Healthcare", 2004, 1250, "Claire Martin"),
    ("Seine Health", "France", "Paris", "Healthcare", 2015, 480, "Julien Bernard"),
    ("Rhone Bio", "France", "Lyon", "Healthcare", 2011, 1630, "Sophie Laurent"),
    ("Garonne Care", "France", "Toulouse", "Healthcare", 2018, 210, "Hugo Lefebvre"),
    # decoys: big healthcare elsewhere, a big French company in another industry
    ("Tagus Health", "Spain", "Madrid", "Healthcare", 2001, 2900, "Lucia Romero"),
    ("Paris Freight", "France", "Paris", "Logistics", 1995, 3100, "Antoine Girard"),
]


def build():
    rng = random.Random(20260302)
    rows = []
    names = set(r[0] for r in FIXED)
    prefixes = PREFIX[:]
    rng.shuffle(prefixes)
    while len(rows) < 47:
        country = rng.choice(COUNTRIES)
        industry = rng.choice(INDUSTRIES)
        # keep the two answer groups exactly as hand-placed
        if (country, industry) in (("Germany", "Energy"), ("France", "Healthcare")):
            continue
        name = f"{prefixes[len(rows) % len(prefixes)]} {rng.choice(SUFFIX[industry])}"
        if name in names:
            continue
        names.add(name)
        rows.append((name, country, rng.choice(CITIES[country]), industry, rng.randint(1960, 2016),
                     rng.choice([35, 60, 120, 250, 400, 650, 900, 1500, 2200]) + rng.randint(0, 30),
                     f"{rng.choice(FIRST)} {rng.choice(LAST)}"))
    rows += FIXED
    rng.shuffle(rows)
    out = []
    for i, (name, country, city, industry, founded, emp, ceo) in enumerate(rows, 1):
        out.append({"id": i, "name": name, "country": country, "city": city, "industry": industry,
                    "founded": founded, "employees": emp, "ceo": ceo,
                    "website": "https://" + name.lower().replace(" ", "") + ".example.test"})
    return out


COMPANIES = build()
BY_ID = {c["id"]: c for c in COMPANIES}


@core.app_init("research")
def init():
    return {"submissions": []}


CSS = """
*{box-sizing:border-box} body{margin:0;font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f5f7fa;color:#1f2933}
header{background:#1f2a44;color:#fff;padding:12px 24px;display:flex;gap:24px;align-items:center}
header a{color:#cbd2e1;text-decoration:none} header b{font-size:18px;color:#fff}
main{max-width:1100px;margin:22px auto;padding:0 20px}
table{width:100%;border-collapse:collapse;background:#fff;box-shadow:0 1px 3px #0001}
th,td{padding:9px 12px;border-bottom:1px solid #e4e7eb;text-align:left} th a{color:#1f2933;text-decoration:none}
td.num,th.num{text-align:right}
.filters{display:flex;gap:12px;align-items:end;background:#fff;padding:12px;margin-bottom:14px;box-shadow:0 1px 3px #0001}
.filters label{display:block;font-size:12px;color:#52606d} select,input,textarea{padding:7px;border:1px solid #cbd2d9;border-radius:4px;font:inherit}
.btn{background:#3e63dd;color:#fff;border:0;border-radius:4px;padding:8px 14px;cursor:pointer;font:600 14px system-ui,sans-serif;text-decoration:none}
.pager{display:flex;gap:6px;margin:16px 0} .pager a,.pager span{padding:5px 10px;background:#fff;border:1px solid #cbd2d9;border-radius:4px;text-decoration:none;color:#1f2933}
.pager span.cur{background:#3e63dd;color:#fff;border-color:#3e63dd}
dl{display:grid;grid-template-columns:160px 1fr;background:#fff;padding:16px;box-shadow:0 1px 3px #0001} dt{color:#52606d} dd{margin:0 0 8px}
form.sub label{display:block;margin:12px 0 4px} form.sub input,form.sub textarea{width:100%;max-width:480px}
.ok{background:#e3f9e5;padding:10px 14px;border:1px solid #91d8a0;margin-bottom:14px}
"""

COLS = [("name", "Company"), ("country", "Country"), ("city", "City"), ("industry", "Industry"),
        ("founded", "Founded"), ("employees", "Employees")]


def layout(title, body):
    return page(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{esc(title)} - Company Directory</title>
<style>{CSS}</style></head><body><header><b>Company Directory</b><a href="/research/">Companies</a>
<a href="/research/submit">Submit an answer</a></header><main>{body}</main></body></html>""")


@route("GET", r"/research/?")
def directory(req):
    q = req.query
    country, industry = q.get("country", ""), q.get("industry", "")
    sort = q.get("sort", "name") if q.get("sort", "name") in dict(COLS) else "name"
    direction = "desc" if q.get("dir") == "desc" else "asc"
    rows = [c for c in COMPANIES if (not country or c["country"] == country) and (not industry or c["industry"] == industry)]
    rows.sort(key=lambda c: (c[sort], c["name"]), reverse=direction == "desc")
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    try:
        pg = min(max(1, int(q.get("page", "1"))), pages)
    except ValueError:
        pg = 1

    def link(**over):
        params = {"country": country, "industry": industry, "sort": sort, "dir": direction, "page": pg}
        params.update(over)
        return "/research/?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in ("", None)})
    heads = []
    for key, label in COLS:
        if key == sort:
            arrow = " ▲" if direction == "asc" else " ▼"
            nd = "desc" if direction == "asc" else "asc"
            aria = f' aria-sort="{"ascending" if direction == "asc" else "descending"}"'
        else:
            arrow, nd, aria = "", "asc", ""
        cls = ' class="num"' if key in ("founded", "employees") else ""
        heads.append(f'<th{cls}{aria}><a href="{link(sort=key, dir=nd, page=1)}">{label}{arrow}</a></th>')
    body_rows = "".join(
        f'<tr><td><a href="/research/company/{c["id"]}">{esc(c["name"])}</a></td><td>{esc(c["country"])}</td>'
        f'<td>{esc(c["city"])}</td><td>{esc(c["industry"])}</td><td class="num">{c["founded"]}</td>'
        f'<td class="num">{c["employees"]:,}</td></tr>' for c in rows[(pg - 1) * PAGE_SIZE: pg * PAGE_SIZE])
    copts = '<option value="">All countries</option>' + "".join(
        f'<option{" selected" if x == country else ""}>{x}</option>' for x in sorted(COUNTRIES))
    iopts = '<option value="">All industries</option>' + "".join(
        f'<option{" selected" if x == industry else ""}>{x}</option>' for x in sorted(INDUSTRIES))
    pager = "".join(f'<span class="cur" aria-current="page">{n}</span>' if n == pg else f'<a href="{link(page=n)}">{n}</a>'
                    for n in range(1, pages + 1))
    if pg < pages:
        pager += f'<a href="{link(page=pg + 1)}">Next</a>'
    body = f"""<h1>Companies</h1>
<form class="filters" method="get" action="/research/">
<div><label for="country">Country</label><select id="country" name="country">{copts}</select></div>
<div><label for="industry">Industry</label><select id="industry" name="industry">{iopts}</select></div>
<input type="hidden" name="sort" value="{sort}"><input type="hidden" name="dir" value="{direction}">
<button class="btn" type="submit">Filter</button><a href="/research/" style="margin-left:6px">Reset</a></form>
<p>{len(rows)} companies &middot; page {pg} of {pages}. Click a column title to sort. Open a company for its details.</p>
<table><thead><tr>{''.join(heads)}</tr></thead><tbody>{body_rows}</tbody></table>
<nav class="pager" aria-label="Pages">{pager}</nav>"""
    return layout("Companies", body)


@route("GET", r"/research/company/(?P<cid>\d+)")
def company(req):
    c = BY_ID.get(int(req.params["cid"]))
    if not c:
        return core.not_found("No such company")
    body = f"""<p><a href="/research/">&larr; All companies</a></p><h1>{esc(c['name'])}</h1>
<dl><dt>Chief executive (CEO)</dt><dd>{esc(c['ceo'])}</dd><dt>Headquarters</dt><dd>{esc(c['city'])}, {esc(c['country'])}</dd>
<dt>Industry</dt><dd>{esc(c['industry'])}</dd><dt>Founded</dt><dd>{c['founded']}</dd>
<dt>Employees</dt><dd>{c['employees']:,}</dd><dt>Website</dt><dd>{esc(c['website'])}</dd></dl>"""
    return layout(c["name"], body)


@route("GET", r"/research/submit")
def submit_get(req):
    body = """<h1>Submit an answer</h1><p>Fill in only the fields the question asks for.</p>
<form class="sub" method="post" action="/research/submit">
<label for="company">Company name</label><input id="company" name="company">
<label for="year">Year founded</label><input id="year" name="year" inputmode="numeric">
<label for="ceo">CEO</label><input id="ceo" name="ceo">
<label for="count">Number (if the question asks for a count)</label><input id="count" name="count" inputmode="numeric">
<label for="notes">Notes</label><textarea id="notes" name="notes" rows="3"></textarea>
<p><button class="btn" type="submit">Submit answer</button></p></form>"""
    return layout("Submit an answer", body)


@route("POST", r"/research/submit")
def submit_post(req):
    st = core.STATE["research"]
    item = {k: req.f(k) for k in ("company", "year", "ceo", "count", "notes")}
    item["ref"] = f"R-{core.next_id('submission'):03d}"
    st["submissions"].append(item)
    core.event("research", "submitted", **item)
    return layout("Answer received", f'<h1>Answer received</h1><div class="ok" role="status">Thank you. Your answer was '
                  f'recorded with reference <b>{item["ref"]}</b>.</div><p><a href="/research/">Back to the directory</a></p>')

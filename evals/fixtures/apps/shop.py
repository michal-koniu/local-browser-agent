"""/shop/ : "Leaf & Co", an online plant shop.

Sign-up sends a confirmation e-mail to the webmail; checkout needs a confirmed account and a delivery address.
Payment by card (only the fake test card from secrets.env succeeds) or by the mock wallet (popup approval).
"""
import re
import urllib.parse

from . import core, mail, wallet
from .core import esc, json_response, page, redirect, route

COOKIE = "leaf_sid"
MERCHANT = "0x1eaF000000000000000000000000000000C0FFee"
PAGE_SIZE = 10
FREE_SHIPPING_FROM = 50.0
SHIPPING = 4.90

CATEGORIES = [
    ("indoor", "Indoor plants"), ("succulents", "Succulents & cacti"), ("outdoor", "Outdoor plants"),
    ("pots", "Pots & planters"), ("care", "Tools & care"),
]
CAT_NAME = dict(CATEGORIES)

POT_SIZES = [("small", "Small (12 cm)", 0.0), ("medium", "Medium (17 cm)", 6.0), ("large", "Large (24 cm)", 14.0)]
COLOURS = [("terracotta", "Terracotta", 0.0), ("sage", "Sage green", 0.0), ("charcoal", "Charcoal", 0.0),
           ("white", "White", 0.0)]
STANDARD = [("standard", "Standard", 0.0)]

# (name, category, price, colour for the picture, short description)
_P = [
    ("Monstera Deliciosa", "indoor", 24.50, "#3f7d4e", "Large split leaves; bright indirect light."),
    ("Snake Plant", "indoor", 18.00, "#4f7f3a", "Upright leaves, tolerates low light and dry air."),
    ("Ceramic Pot Classic", "pots", 14.90, "#c97b4a", "Glazed ceramic pot with drainage hole."),
    ("Golden Pothos", "indoor", 12.50, "#7aa83b", "Trailing vines with golden variegation."),
    ("Echeveria Elegans", "succulents", 6.90, "#8fb3a3", "Rosette succulent with a pale blue bloom."),
    ("Watering Can 1 L", "care", 16.00, "#6b8fb3", "Long thin spout for precise watering."),
    ("Fiddle Leaf Fig", "indoor", 39.00, "#2f6b3a", "Big glossy leaves; likes a steady spot."),
    ("Lavender Hidcote", "outdoor", 9.50, "#8a6fb3", "Compact English lavender, very fragrant."),
    ("Bunny Ear Cactus", "succulents", 8.40, "#9fb36b", "Flat pads covered in soft-looking glochids."),
    ("Pruning Shears", "care", 21.00, "#b34f4f", "Bypass shears for stems up to 15 mm."),
    ("Peace Lily", "indoor", 19.90, "#356b47", "White blooms, tells you when it is thirsty."),
    ("Hanging Planter Macrame", "pots", 17.50, "#d8c3a5", "Hand-knotted cotton hanger with a pot."),
    ("Aloe Vera", "succulents", 9.90, "#6fa38a", "Soothing gel inside thick leaves."),
    ("Rosemary", "outdoor", 7.80, "#5f7f5a", "Hardy kitchen herb for a sunny balcony."),
    ("ZZ Plant", "indoor", 22.00, "#2e5e3a", "Glossy leaves, nearly indestructible."),
    ("Plant Mister", "care", 8.90, "#7fb3c9", "Fine mist sprayer, 300 ml."),
    ("Calathea Orbifolia", "indoor", 27.50, "#5a8f6a", "Round striped leaves; loves humidity."),
    ("Self-Watering Pot", "pots", 24.00, "#9a9a9a", "Reservoir pot with a water level gauge."),
    ("Jade Plant", "succulents", 11.20, "#4f8f5a", "Thick coin-shaped leaves, a lucky classic."),
    ("Olive Tree", "outdoor", 49.00, "#7f8f5a", "Mediterranean tree for a large pot."),
    ("Boston Fern", "indoor", 15.40, "#4a8f3a", "Arching fronds for a humid bathroom."),
    ("Organic Potting Mix 10 L", "care", 12.90, "#6b4f3a", "Peat-free mix for indoor plants."),
    ("String of Pearls", "succulents", 13.60, "#7fb37f", "Trailing bead-like leaves."),
    ("Japanese Maple", "outdoor", 59.00, "#b3473a", "Red lace-like leaves in autumn."),
    ("Terracotta Pot Set of 3", "pots", 19.50, "#c96a3a", "Classic unglazed pots, 10/14/18 cm."),
    ("Rubber Plant", "indoor", 21.30, "#2a4f3a", "Dark burgundy leaves, easy care."),
    ("Moon Cactus", "succulents", 6.50, "#e0603a", "Colourful grafted cactus top."),
    ("Liquid Plant Food", "care", 9.40, "#3a8f8f", "Balanced NPK feed, 250 ml."),
    ("Hydrangea", "outdoor", 26.00, "#6a7fd0", "Big blue flower heads in summer."),
    ("Bird of Paradise", "indoor", 44.00, "#2f7f5a", "Tropical paddle leaves, needs bright light."),
]


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


PRODUCTS = []
for _i, (_n, _c, _p, _col, _d) in enumerate(_P, 1):
    PRODUCTS.append({"id": _i, "slug": slugify(_n), "name": _n, "category": _c, "price": _p, "color": _col,
                     "description": _d,
                     "variant_label": "Pot size" if _c in ("indoor", "succulents", "outdoor")
                     else "Colour" if _c == "pots" else "",
                     "variants": POT_SIZES if _c in ("indoor", "succulents", "outdoor")
                     else COLOURS if _c == "pots" else STANDARD})
BY_ID = {p["id"]: p for p in PRODUCTS}
BY_SLUG = {p["slug"]: p for p in PRODUCTS}

POSTAL = {
    "FR": ("France", r"\d{5}", "5 digits, e.g. 75001"),
    "DE": ("Germany", r"\d{5}", "5 digits, e.g. 10115"),
    "NL": ("Netherlands", r"\d{4} ?[A-Z]{2}", "4 digits and 2 letters, e.g. 1015 AB"),
    "PL": ("Poland", r"\d{2}-\d{3}", "format 00-000, e.g. 30-001"),
    "ES": ("Spain", r"\d{5}", "5 digits, e.g. 28001"),
    "GB": ("United Kingdom", r"[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}", "e.g. SW1A 1AA"),
}


def money(x):
    return f"€{x:,.2f}"


def variant_of(p, vkey):
    return next((v for v in p["variants"] if v[0] == vkey), None)


def unit_price(p, vkey):
    v = variant_of(p, vkey)
    return round(p["price"] + (v[2] if v else 0.0), 2)


@core.app_init("shop")
def init():
    returning = core.secret("SHOP_RETURNING_EMAIL", "returning.customer@example.test")
    return {
        "accounts": {
            returning: {"name": "Sam Returning", "email": returning,
                        "password": core.secret("SHOP_RETURNING_PASSWORD", "Fake-Returning-1357"),
                        "confirmed": True, "token": "seeded-account",
                        "address": {"street": "Lindenweg 8", "city": "Berlin", "postal_code": "10115",
                                    "country": "DE"},
                        "cart": [{"pid": 20, "variant": "medium", "qty": 1}, {"pid": 2, "variant": "small", "qty": 1}]},
        },
        "sessions": {}, "orders": [], "payment_attempts": [], "consent": {},
    }


# ---------------------------------------------------------------- session helpers

def ctx(req):
    st = core.STATE["shop"]
    sess = core.session(req, "shop", COOKIE)
    acct = st["accounts"].get(sess.get("user")) if sess.get("user") else None
    return sess, acct


def cart_of(sess, acct):
    if acct is not None:
        return acct["cart"]
    return sess.setdefault("cart", [])


def cart_lines(cart):
    lines = []
    for item in cart:
        p = BY_ID[item["pid"]]
        v = variant_of(p, item["variant"])
        up = unit_price(p, item["variant"])
        lines.append({"key": f"{p['id']}:{item['variant']}", "pid": p["id"], "name": p["name"], "slug": p["slug"],
                      "variant": item["variant"], "variant_name": v[1] if v else item["variant"],
                      "qty": item["qty"], "unit_price": up, "line_total": round(up * item["qty"], 2)})
    return lines


def totals(lines):
    sub = round(sum(l["line_total"] for l in lines), 2)
    ship = 0.0 if sub >= FREE_SHIPPING_FROM or not lines else SHIPPING
    return sub, ship, round(sub + ship, 2)


# ---------------------------------------------------------------- layout

CSS = """
*{box-sizing:border-box} body{margin:0;font:15px/1.5 Georgia,'Times New Roman',serif;color:#23302a;background:#f7f4ee}
a{color:#2f5d3a} header.top{background:#fff;border-bottom:1px solid #e4ddd0}
.bar{max-width:1100px;margin:0 auto;display:flex;align-items:center;gap:22px;padding:14px 20px}
.logo{font-size:26px;font-weight:700;color:#2f5d3a;text-decoration:none;letter-spacing:.5px}
.bar nav{display:flex;gap:18px;align-items:center;margin-left:auto;font-family:system-ui,sans-serif;font-size:14px}
.bar nav a{text-decoration:none;color:#23302a} .bar form.search input{width:220px;padding:7px 10px;border:1px solid #cfc6b6;border-radius:18px;font:14px system-ui,sans-serif}
.linkbtn{background:none;border:0;padding:0;font:14px system-ui,sans-serif;color:#23302a;cursor:pointer;text-decoration:underline}
main{max-width:1100px;margin:24px auto 60px;padding:0 20px} h1{font-weight:600;color:#1f3d29}
.banner{background:#fff3cd;border-bottom:1px solid #ecd58a;font:14px system-ui,sans-serif;padding:9px 20px;text-align:center}
.banner form{display:inline}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:18px}
.card{background:#fff;border:1px solid #e4ddd0;border-radius:10px;padding:14px;font-family:system-ui,sans-serif}
.card h3{font-size:15px;margin:8px 0 4px} .card .cat{font-size:12px;color:#7a7465} .price{font-weight:700;color:#2f5d3a}
.btn{display:inline-block;background:#2f5d3a;color:#fff;border:0;border-radius:6px;padding:9px 16px;font:600 14px system-ui,sans-serif;cursor:pointer;text-decoration:none}
.btn.secondary{background:#fff;color:#2f5d3a;border:1px solid #2f5d3a} .btn.danger{background:#fff;color:#a12b2b;border:1px solid #a12b2b}
form.std{font-family:system-ui,sans-serif;max-width:480px} form.std label{display:block;margin:12px 0 4px;font-size:14px}
form.std input[type=text],form.std input[type=email],form.std input[type=password],form.std select{width:100%;padding:9px;border:1px solid #cfc6b6;border-radius:6px;font-size:15px}
.err{background:#fbe3e3;border:1px solid #e3a5a5;color:#7d1f1f;padding:10px 14px;border-radius:6px;font-family:system-ui,sans-serif;margin:12px 0}
.ok{background:#e3f4e6;border:1px solid #a5d3ae;color:#1f5d2c;padding:10px 14px;border-radius:6px;font-family:system-ui,sans-serif;margin:12px 0}
.filters{display:flex;gap:12px;align-items:end;flex-wrap:wrap;font-family:system-ui,sans-serif;background:#fff;border:1px solid #e4ddd0;border-radius:10px;padding:12px;margin-bottom:18px}
.filters label{display:block;font-size:12px;color:#555} .filters input,.filters select{padding:7px;border:1px solid #cfc6b6;border-radius:6px;font-size:14px}
.pager{display:flex;gap:6px;justify-content:center;margin:22px 0;font-family:system-ui,sans-serif}
.pager a,.pager span{padding:6px 11px;border:1px solid #cfc6b6;border-radius:6px;text-decoration:none;background:#fff}
.pager span.cur{background:#2f5d3a;color:#fff;border-color:#2f5d3a}
table.cart{width:100%;border-collapse:collapse;background:#fff;font-family:system-ui,sans-serif}
table.cart td,table.cart th{padding:10px;border-bottom:1px solid #eee;text-align:left} table.cart input{width:60px;padding:6px}
.product{display:grid;grid-template-columns:360px 1fr;gap:30px;font-family:system-ui,sans-serif}
.consent-backdrop{position:fixed;inset:0;background:rgba(20,30,25,.55);z-index:50;display:flex;align-items:flex-end;justify-content:center}
.consent{background:#fff;max-width:760px;width:100%;margin:0 16px 24px;border-radius:12px;padding:20px 24px;font-family:system-ui,sans-serif;box-shadow:0 8px 30px #0005}
.consent .row{display:flex;gap:10px;justify-content:flex-end;margin-top:12px}
fieldset{border:1px solid #e4ddd0;border-radius:8px;margin:14px 0;padding:10px 16px} legend{font-weight:600}
.summary{background:#fff;border:1px solid #e4ddd0;border-radius:10px;padding:14px 18px;font-family:system-ui,sans-serif;margin-bottom:16px}
"""


def picture(p, size=150):
    leaf = p["color"]
    pot = "#b5653a" if p["category"] != "care" else "#888"
    if p["category"] == "care":
        art = f'<rect x="35" y="40" width="50" height="60" rx="8" fill="{leaf}"/><rect x="50" y="22" width="20" height="20" fill="{leaf}"/>'
    elif p["category"] == "pots":
        art = f'<path d="M30 45 h60 l-8 55 h-44 z" fill="{leaf}"/><rect x="26" y="38" width="68" height="10" rx="3" fill="{leaf}"/>'
    else:
        art = (f'<ellipse cx="60" cy="40" rx="16" ry="28" fill="{leaf}"/><ellipse cx="40" cy="52" rx="13" ry="22" '
               f'fill="{leaf}" transform="rotate(-35 40 52)"/><ellipse cx="80" cy="52" rx="13" ry="22" fill="{leaf}" '
               f'transform="rotate(35 80 52)"/><path d="M38 72 h44 l-6 34 h-32 z" fill="{pot}"/>')
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 120 120" aria-hidden="true" '
            f'style="background:#eef3ec;border-radius:8px">{art}</svg>')


def layout(req, title, body):
    sess, acct = ctx(req)
    n = sum(i["qty"] for i in cart_of(sess, acct))
    if acct:
        who = (f'<a href="/shop/account">My account</a><form method="post" action="/shop/logout" style="display:inline">'
               f'<button class="linkbtn" type="submit">Log out</button></form>')
    else:
        who = '<a href="/shop/login">Log in</a><a href="/shop/signup">Sign up</a>'
    banner = ""
    if acct and not acct["confirmed"]:
        banner = (f'<div class="banner">Please confirm your e-mail address: we sent a link to <b>{esc(acct["email"])}</b>. '
                  f'<form method="post" action="/shop/resend"><button class="linkbtn" type="submit">Resend e-mail</button>'
                  f'</form></div>')
    consent = ""
    if not sess.get("consent"):
        consent = f"""<div class="consent-backdrop"><div class="consent" role="dialog" aria-modal="true" aria-labelledby="ck-title">
<h2 id="ck-title" style="margin:0 0 6px">We value your privacy</h2>
<p style="margin:0">Leaf &amp; Co uses cookies to keep your cart, remember your login and, if you agree, to measure visits
and show you offers. You can accept all cookies or only the ones needed for the shop to work.</p>
<form method="post" action="/shop/consent" class="row"><input type="hidden" name="next" value="{esc(req.path + ('?' + urllib.parse.urlencode(req.query) if req.query else ''))}">
<button class="btn secondary" name="choice" value="necessary" type="submit">Only necessary</button>
<button class="btn" name="choice" value="all" type="submit">Accept all</button></form></div></div>"""
    return page(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} | Leaf &amp; Co</title>
<style>{CSS}</style></head><body>
<header class="top"><div class="bar"><a class="logo" href="/shop/">Leaf &amp; Co</a>
<form class="search" method="get" action="/shop/catalogue" role="search"><input type="search" name="q" aria-label="Search products" placeholder="Search plants, pots, tools"></form>
<nav aria-label="Main"><a href="/shop/catalogue">Catalogue</a><a href="/shop/cart">Cart ({n})</a>{who}</nav></div></header>
{banner}<main>{body}</main>{consent}</body></html>""")


# ---------------------------------------------------------------- pages

@route("GET", r"/shop/?")
def home(req):
    feat = [BY_ID[i] for i in (1, 17, 27, 18)]
    cards = "".join(product_card(p) for p in feat)
    cats = " &middot; ".join(f'<a href="/shop/catalogue?cat={k}">{esc(v)}</a>' for k, v in CATEGORIES)
    body = f"""<section style="background:#e6efe4;border-radius:14px;padding:30px 34px;margin-bottom:26px">
<h1 style="margin:0 0 8px;font-size:34px">Plants that make a home</h1>
<p style="font-size:18px;margin:0 0 16px">Healthy plants, honest pots and the tools to keep them happy. Free delivery from {money(FREE_SHIPPING_FROM)}.</p>
<a class="btn" href="/shop/catalogue">Shop the catalogue</a></section>
<p style="font-family:system-ui,sans-serif">Categories: {cats}</p>
<h2>Customer favourites</h2><div class="grid">{cards}</div>"""
    return layout(req, "Home", body)


def product_card(p):
    return (f'<div class="card">{picture(p, 120)}<div class="cat">{esc(CAT_NAME[p["category"]])}</div>'
            f'<h3><a href="/shop/product/{p["slug"]}">{esc(p["name"])}</a></h3>'
            f'<div class="price">{"from " if p["variants"] is POT_SIZES else ""}{money(p["price"])}</div></div>')


@route("POST", r"/shop/consent")
def consent(req):
    sess, _ = ctx(req)
    choice = req.f("choice") if req.f("choice") in ("all", "necessary") else "necessary"
    sess["consent"] = choice
    core.STATE["shop"]["consent"][sess["id"]] = choice
    core.event("shop", "cookie_consent", choice=choice)
    nxt = req.f("next") or "/shop/"
    return redirect(nxt if nxt.startswith("/shop") else "/shop/")


@route("GET", r"/shop/catalogue")
def catalogue(req):
    q = req.query.get("q", "").strip()
    cat = req.query.get("cat", "")
    sort = req.query.get("sort", "featured")
    items = [p for p in PRODUCTS if (not q or q.lower() in p["name"].lower()) and (not cat or p["category"] == cat)]
    if sort == "price-asc":
        items.sort(key=lambda p: p["price"])
    elif sort == "price-desc":
        items.sort(key=lambda p: -p["price"])
    elif sort == "name":
        items.sort(key=lambda p: p["name"])
    pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    try:
        pg = min(max(1, int(req.query.get("page", "1"))), pages)
    except ValueError:
        pg = 1
    shown = items[(pg - 1) * PAGE_SIZE: pg * PAGE_SIZE]
    copts = '<option value="">All categories</option>' + "".join(
        f'<option value="{k}"{" selected" if k == cat else ""}>{esc(v)}</option>' for k, v in CATEGORIES)
    sopts = "".join(f'<option value="{k}"{" selected" if k == sort else ""}>{v}</option>' for k, v in
                    [("featured", "Featured"), ("price-asc", "Price: low to high"), ("price-desc", "Price: high to low"),
                     ("name", "Name A-Z")])

    def link(n):
        qs = {k: v for k, v in (("q", q), ("cat", cat), ("sort", sort if sort != "featured" else "")) if v}
        qs["page"] = n
        return "/shop/catalogue?" + urllib.parse.urlencode(qs)
    pager = []
    if pg > 1:
        pager.append(f'<a href="{link(pg - 1)}" rel="prev">Previous</a>')
    for n in range(1, pages + 1):
        pager.append(f'<span class="cur" aria-current="page">{n}</span>' if n == pg else f'<a href="{link(n)}">{n}</a>')
    if pg < pages:
        pager.append(f'<a href="{link(pg + 1)}" rel="next">Next</a>')
    start = (pg - 1) * PAGE_SIZE + 1 if items else 0
    body = f"""<h1>Catalogue</h1>
<form class="filters" method="get" action="/shop/catalogue">
<div><label for="f-q">Search</label><input id="f-q" name="q" value="{esc(q)}"></div>
<div><label for="f-cat">Category</label><select id="f-cat" name="cat">{copts}</select></div>
<div><label for="f-sort">Sort by</label><select id="f-sort" name="sort">{sopts}</select></div>
<button class="btn" type="submit">Apply</button></form>
<p style="font-family:system-ui,sans-serif;color:#555">Showing {start}&ndash;{start + len(shown) - 1 if items else 0} of {len(items)} products</p>
<div class="grid">{''.join(product_card(p) for p in shown) or '<p>No products match your search.</p>'}</div>
<nav class="pager" aria-label="Pagination">{''.join(pager)}</nav>"""
    return layout(req, "Catalogue", body)


@route("GET", r"/shop/product/(?P<slug>[a-z0-9-]+)")
def product(req):
    p = BY_SLUG.get(req.params["slug"])
    if not p:
        return core.not_found("No such product")
    notice = ""
    if req.query.get("added"):
        notice = '<div class="ok" role="status">Added to your cart. <a href="/shop/cart">View cart</a></div>'
    if req.query.get("error"):
        notice = f'<div class="err" role="alert">{esc(req.query["error"])}</div>'
    if p["variants"] is STANDARD:
        vsel = '<input type="hidden" name="variant" value="standard">'
    else:
        opts = "".join(f'<option value="{k}">{esc(name)}{f" (+{money(extra)})" if extra else ""}</option>'
                       for k, name, extra in p["variants"])
        vsel = f'<label for="variant">{p["variant_label"]}</label><select id="variant" name="variant">{opts}</select>'
    body = f"""<p style="font-family:system-ui,sans-serif"><a href="/shop/catalogue?cat={p['category']}">{esc(CAT_NAME[p['category']])}</a></p>
<div class="product"><div>{picture(p, 340)}</div><div><h1 style="margin-top:0">{esc(p['name'])}</h1>
<div class="price" style="font-size:22px">{money(p['price'])}</div><p>{esc(p['description'])}</p>{notice}
<form class="std" method="post" action="/shop/cart/add"><input type="hidden" name="pid" value="{p['id']}">
{vsel}<label for="qty">Quantity</label><input id="qty" name="qty" type="number" min="1" max="20" value="1" style="width:90px;padding:8px">
<p><button class="btn" type="submit">Add to cart</button></p></form></div></div>"""
    return layout(req, p["name"], body)


@route("POST", r"/shop/cart/add")
def cart_add(req):
    sess, acct = ctx(req)
    try:
        p = BY_ID[int(req.f("pid"))]
    except (KeyError, ValueError):
        return redirect("/shop/catalogue")
    vkey = req.f("variant") or p["variants"][0][0]
    if not variant_of(p, vkey):
        vkey = p["variants"][0][0]
    try:
        qty = int(req.f("qty"))
    except ValueError:
        qty = 0
    if not 1 <= qty <= 20:
        return redirect(f"/shop/product/{p['slug']}?error=" + urllib.parse.quote("Quantity must be between 1 and 20."))
    cart = cart_of(sess, acct)
    for item in cart:
        if item["pid"] == p["id"] and item["variant"] == vkey:
            item["qty"] = min(20, item["qty"] + qty)
            break
    else:
        cart.append({"pid": p["id"], "variant": vkey, "qty": qty})
    core.event("shop", "cart_add", pid=p["id"], name=p["name"], variant=vkey, qty=qty)
    return redirect(f"/shop/product/{p['slug']}?added=1")


@route("GET", r"/shop/cart")
def cart_page(req):
    sess, acct = ctx(req)
    lines = cart_lines(cart_of(sess, acct))
    msg = f'<div class="ok" role="status">{esc(req.query["msg"])}</div>' if req.query.get("msg") else ""
    if not lines:
        return layout(req, "Cart", f'<h1>Your cart</h1>{msg}<p>Your cart is empty. <a href="/shop/catalogue">Browse the catalogue</a>.</p>')
    sub, ship, total = totals(lines)
    rows = []
    for l in lines:
        rows.append(f"""<tr><td><a href="/shop/product/{l['slug']}">{esc(l['name'])}</a><br><small>{esc(l['variant_name'])}</small></td>
<td>{money(l['unit_price'])}</td>
<td><form method="post" action="/shop/cart/update" style="display:flex;gap:6px"><input type="hidden" name="key" value="{l['key']}">
<label class="sr" for="qty-{l['key']}" style="position:absolute;left:-9999px">Quantity of {esc(l['name'])}</label>
<input id="qty-{l['key']}" name="qty" type="number" min="1" max="20" value="{l['qty']}"><button class="btn secondary" type="submit">Update</button></form></td>
<td>{money(l['line_total'])}</td>
<td><form method="post" action="/shop/cart/remove"><input type="hidden" name="key" value="{l['key']}">
<button class="btn danger" type="submit" aria-label="Remove {esc(l['name'])}">Remove</button></form></td></tr>""")
    body = f"""<h1>Your cart</h1>{msg}<table class="cart"><tr><th>Product</th><th>Price</th><th>Quantity</th><th>Total</th><th></th></tr>
{''.join(rows)}</table>
<div class="summary" style="max-width:360px;margin:18px 0 0 auto"><div>Subtotal: <b id="subtotal">{money(sub)}</b></div>
<div>Shipping: {money(ship) if ship else 'free'}</div><div style="font-size:18px">Total: <b>{money(total)}</b></div>
<p><a class="btn" href="/shop/checkout">Proceed to checkout</a></p></div>"""
    return layout(req, "Cart", body)


def _find_line(cart, key):
    for item in cart:
        if f"{item['pid']}:{item['variant']}" == key:
            return item
    return None


@route("POST", r"/shop/cart/update")
def cart_update(req):
    sess, acct = ctx(req)
    cart = cart_of(sess, acct)
    item = _find_line(cart, req.f("key"))
    try:
        qty = int(req.f("qty"))
    except ValueError:
        qty = -1
    if item and 1 <= qty <= 20:
        item["qty"] = qty
        core.event("shop", "cart_update", pid=item["pid"], variant=item["variant"], qty=qty)
        return redirect("/shop/cart?msg=" + urllib.parse.quote("Cart updated."))
    if item and qty == 0:
        cart.remove(item)
        core.event("shop", "cart_remove", pid=item["pid"], variant=item["variant"])
        return redirect("/shop/cart?msg=" + urllib.parse.quote("Item removed."))
    return redirect("/shop/cart?msg=" + urllib.parse.quote("Quantity must be between 1 and 20."))


@route("POST", r"/shop/cart/remove")
def cart_remove(req):
    sess, acct = ctx(req)
    cart = cart_of(sess, acct)
    item = _find_line(cart, req.f("key"))
    if item:
        cart.remove(item)
        core.event("shop", "cart_remove", pid=item["pid"], variant=item["variant"])
    return redirect("/shop/cart?msg=" + urllib.parse.quote("Item removed."))


# ---------------------------------------------------------------- accounts

def _form_page(req, title, action, fields, errors, button, extra=""):
    err = "".join(f"<li>{esc(e)}</li>" for e in errors)
    err_html = f'<div class="err" role="alert"><ul style="margin:0;padding-left:18px">{err}</ul></div>' if errors else ""
    return layout(req, title, f'<h1>{esc(title)}</h1>{err_html}<form class="std" method="post" action="{action}" novalidate>'
                  f'{fields}<p><button class="btn" type="submit">{esc(button)}</button></p></form>{extra}')


def signup_form(req, values, errors):
    v = lambda k: esc(values.get(k, ""))  # noqa: E731
    fields = f"""<label for="name">Full name</label><input type="text" id="name" name="name" value="{v('name')}" autocomplete="name">
<label for="email">E-mail</label><input type="email" id="email" name="email" value="{v('email')}" autocomplete="email">
<label for="password">Password <small>(at least 8 characters)</small></label><input type="password" id="password" name="password" autocomplete="new-password">
<label for="password2">Repeat password</label><input type="password" id="password2" name="password2" autocomplete="new-password">
<p style="margin-top:14px"><input type="checkbox" id="terms" name="terms" value="yes"> <label for="terms" style="display:inline">I accept the
<a href="/shop/terms" target="_blank">terms and conditions</a></label></p>
<p><input type="checkbox" id="news" name="newsletter" value="yes"> <label for="news" style="display:inline">Send me the newsletter</label></p>"""
    return _form_page(req, "Create your account", "/shop/signup", fields, errors, "Create account",
                      '<p style="font-family:system-ui,sans-serif">Already have an account? <a href="/shop/login">Log in</a></p>')


@route("GET", r"/shop/signup")
def signup_get(req):
    return signup_form(req, {}, [])


@route("GET", r"/shop/terms")
def terms(req):
    return layout(req, "Terms", "<h1>Terms and conditions</h1><p>This is a test shop. Nothing is shipped and nothing is charged.</p>")


@route("POST", r"/shop/signup")
def signup_post(req):
    st = core.STATE["shop"]
    sess, _ = ctx(req)
    name, email, pw, pw2 = req.f("name"), req.f("email").lower(), req.form.get("password", ""), req.form.get("password2", "")
    errors = []
    if not name:
        errors.append("Please enter your full name.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors.append("Please enter a valid e-mail address.")
    elif email in st["accounts"]:
        errors.append("An account with this e-mail already exists. Log in instead.")
    if len(pw) < 8:
        errors.append("The password must have at least 8 characters.")
    elif pw != pw2:
        errors.append("The two passwords do not match.")
    if req.f("terms") != "yes":
        errors.append("You must accept the terms and conditions.")
    if errors:
        core.event("shop", "signup_error", errors=errors)
        return signup_form(req, req.form, errors)
    tok = core.token("confirm", email)
    st["accounts"][email] = {"name": name, "email": email, "password": pw, "confirmed": False, "token": tok,
                             "newsletter": req.f("newsletter") == "yes", "address": None, "cart": []}
    # an anonymous cart moves into the new account
    st["accounts"][email]["cart"].extend(sess.pop("cart", []))
    sess["user"] = email
    core.event("shop", "signup", email=email, name=name)
    send_confirmation(req, st["accounts"][email])
    return redirect("/shop/signup/done")


def send_confirmation(req, acct):
    host = req.headers.get("Host", "127.0.0.1")
    link = f"http://{host}/shop/confirm?token={acct['token']}"
    body = (f"<p>Hi {esc(acct['name'])},</p><p>Thanks for creating a Leaf &amp; Co account. Please confirm your e-mail "
            f"address by clicking the link below:</p><p><a href='{link}'>Confirm my e-mail address</a></p>"
            f"<p style='color:#777'>If the link does not work, copy this address into your browser: {link}</p>"
            "<p>Happy planting,<br>Leaf &amp; Co</p>")
    mail.deliver("Leaf & Co", "accounts@leafandco.example.test", acct["email"],
                 "Confirm your Leaf & Co account", body)


@route("GET", r"/shop/signup/done")
def signup_done(req):
    _, acct = ctx(req)
    email = acct["email"] if acct else "your e-mail address"
    return layout(req, "Check your inbox", f"""<h1>Check your inbox</h1><div class="ok">We sent a confirmation link to
<b>{esc(email)}</b>. Open it to confirm your account. You need a confirmed account to place an order.</div>
<p style="font-family:system-ui,sans-serif"><a href="/shop/catalogue">Continue shopping</a></p>""")


@route("POST", r"/shop/resend")
def resend(req):
    _, acct = ctx(req)
    if acct and not acct["confirmed"]:
        send_confirmation(req, acct)
        core.event("shop", "confirmation_resent", email=acct["email"])
    return layout(req, "E-mail sent", '<h1>E-mail sent</h1><div class="ok">We sent the confirmation link again.</div>')


@route("GET", r"/shop/confirm")
def confirm(req):
    st = core.STATE["shop"]
    tok = req.query.get("token", "")
    acct = next((a for a in st["accounts"].values() if a["token"] == tok and tok), None)
    if not acct:
        core.event("shop", "confirm_error", token=tok)
        return layout(req, "Invalid link", '<h1>Invalid link</h1><div class="err">This confirmation link is not valid.</div>')
    if not acct["confirmed"]:
        acct["confirmed"] = True
        core.event("shop", "confirmed", email=acct["email"])
    return layout(req, "Account confirmed", f"""<h1>Account confirmed</h1><div class="ok">Thank you, {esc(acct['name'])}.
Your e-mail address <b>{esc(acct['email'])}</b> is confirmed.</div>
<p style="font-family:system-ui,sans-serif"><a href="/shop/account">Go to my account</a> &middot; <a href="/shop/catalogue">Continue shopping</a></p>""")


def login_form(req, errors, email=""):
    nxt = req.query.get("next") or req.form.get("next", "")
    fields = f"""<input type="hidden" name="next" value="{esc(nxt)}">
<label for="email">E-mail</label><input type="email" id="email" name="email" value="{esc(email)}" autocomplete="username">
<label for="password">Password</label><input type="password" id="password" name="password" autocomplete="current-password">"""
    return _form_page(req, "Log in", "/shop/login", fields, errors, "Log in",
                      '<p style="font-family:system-ui,sans-serif">New here? <a href="/shop/signup">Create an account</a></p>')


@route("GET", r"/shop/login")
def login_get(req):
    return login_form(req, [])


@route("POST", r"/shop/login")
def login_post(req):
    st = core.STATE["shop"]
    sess, _ = ctx(req)
    email = req.f("email").lower()
    acct = st["accounts"].get(email)
    if not acct or acct["password"] != req.form.get("password", ""):
        core.event("shop", "login_failed", email=email)
        return login_form(req, ["Wrong e-mail or password."], email)
    acct["cart"].extend(i for i in sess.pop("cart", []) if i not in acct["cart"])
    sess["user"] = email
    core.event("shop", "login", email=email)
    nxt = req.f("next")
    return redirect(nxt if nxt.startswith("/shop") else "/shop/account")


@route("POST", r"/shop/logout")
def logout(req):
    sess, acct = ctx(req)
    if acct:
        core.event("shop", "logout", email=acct["email"])
    sess["user"] = None
    return redirect("/shop/")


def need_login(req):
    return redirect("/shop/login?next=" + urllib.parse.quote(req.path))


def address_form(acct, values, errors, saved=False):
    a = values if values is not None else (acct["address"] or {})
    v = lambda k: esc(a.get(k, ""))  # noqa: E731
    copts = '<option value="">Choose a country</option>' + "".join(
        f'<option value="{k}"{" selected" if a.get("country") == k else ""}>{esc(n)}</option>'
        for k, (n, _, _) in POSTAL.items())
    err = "".join(f"<li>{esc(e)}</li>" for e in errors)
    return f"""<h2>Delivery address</h2>{f'<div class="err" role="alert"><ul style="margin:0;padding-left:18px">{err}</ul></div>' if errors else ''}
{'<div class="ok" role="status">Address saved.</div>' if saved else ''}
<form class="std" method="post" action="/shop/account/address" novalidate>
<label for="street">Street and number</label><input type="text" id="street" name="street" value="{v('street')}" autocomplete="street-address">
<label for="city">City</label><input type="text" id="city" name="city" value="{v('city')}" autocomplete="address-level2">
<label for="postal_code">Postal code</label><input type="text" id="postal_code" name="postal_code" value="{v('postal_code')}" autocomplete="postal-code">
<label for="country">Country</label><select id="country" name="country">{copts}</select>
<p><button class="btn" type="submit">Save address</button></p></form>"""


def account_page(req, acct, addr_values=None, addr_errors=(), saved=False):
    orders = [o for o in core.STATE["shop"]["orders"] if o["email"] == acct["email"]]
    olist = "".join(f'<li><a href="/shop/order/{o["number"]}">{o["number"]}</a> &middot; {money(o["total"])} &middot; '
                    f'{esc(o["payment"]["method"])}</li>' for o in orders) or "<li>No orders yet.</li>"
    status = "confirmed" if acct["confirmed"] else "not confirmed yet"
    body = f"""<h1>My account</h1><div class="summary"><div><b>{esc(acct['name'])}</b></div><div>{esc(acct['email'])} ({status})</div></div>
{address_form(acct, addr_values, list(addr_errors), saved)}
<h2>Orders</h2><ul style="font-family:system-ui,sans-serif">{olist}</ul>"""
    return layout(req, "My account", body)


@route("GET", r"/shop/account")
def account_get(req):
    _, acct = ctx(req)
    if not acct:
        return need_login(req)
    return account_page(req, acct)


@route("POST", r"/shop/account/address")
def account_address(req):
    _, acct = ctx(req)
    if not acct:
        return need_login(req)
    vals = {k: req.f(k) for k in ("street", "city", "postal_code", "country")}
    errors = []
    if len(vals["street"]) < 3:
        errors.append("Please enter the street and house number.")
    if len(vals["city"]) < 2:
        errors.append("Please enter the city.")
    if vals["country"] not in POSTAL:
        errors.append("Please choose a country.")
    else:
        _, rx, hint = POSTAL[vals["country"]]
        if not re.fullmatch(rx, vals["postal_code"].upper()):
            errors.append(f"The postal code is not valid for {POSTAL[vals['country']][0]} ({hint}).")
    if errors:
        core.event("shop", "address_error", errors=errors, values=vals)
        return account_page(req, acct, vals, errors)
    vals["postal_code"] = vals["postal_code"].upper()
    acct["address"] = vals
    core.event("shop", "address_saved", email=acct["email"], address=vals)
    return account_page(req, acct, None, (), saved=True)


# ---------------------------------------------------------------- checkout

def checkout_blockers(acct, lines):
    if not acct["confirmed"]:
        return ("Please confirm your e-mail address before placing an order. We sent you a link "
                f"to {acct['email']}.")
    if not acct["address"]:
        return "Please add a delivery address in your account before placing an order."
    if not lines:
        return "Your cart is empty."
    return None


def checkout_page(req, acct, errors=(), values=None, method="card"):
    lines = cart_lines(acct["cart"])
    block = checkout_blockers(acct, lines)
    if block:
        link = '<a href="/shop/account">Go to my account</a>' if "address" in block else '<a href="/shop/cart">Back to cart</a>'
        if not acct["confirmed"]:
            link = ('<form method="post" action="/shop/resend" style="display:inline"><button class="btn secondary" '
                    'type="submit">Resend confirmation e-mail</button></form>')
        return layout(req, "Checkout", f'<h1>Checkout</h1><div class="err" role="alert">{esc(block)}</div><p>{link}</p>')
    sub, ship, total = totals(lines)
    a = acct["address"]
    items = "".join(f"<li>{l['qty']} &times; {esc(l['name'])} ({esc(l['variant_name'])}) &mdash; {money(l['line_total'])}</li>"
                    for l in lines)
    v = lambda k: esc((values or {}).get(k, ""))  # noqa: E731
    err = "".join(f"<li>{esc(e)}</li>" for e in errors)
    body = f"""<h1>Checkout</h1>
<div class="summary"><b>Deliver to:</b> {esc(acct['name'])}, {esc(a['street'])}, {esc(a['postal_code'])} {esc(a['city'])}, {esc(POSTAL[a['country']][0])}
<a href="/shop/account">Change</a></div>
<div class="summary"><b>Your order</b><ul>{items}</ul>Subtotal {money(sub)} &middot; Shipping {money(ship) if ship else 'free'}
<div style="font-size:18px">Total to pay: <b id="total">{money(total)}</b></div></div>
{f'<div class="err" role="alert"><ul style="margin:0;padding-left:18px">{err}</ul></div>' if errors else ''}
<form class="std" method="post" action="/shop/checkout" id="pay-form" novalidate>
<fieldset><legend>Payment method</legend>
<p><input type="radio" id="m-card" name="method" value="card"{' checked' if method == 'card' else ''}> <label for="m-card" style="display:inline">Credit or debit card</label></p>
<p><input type="radio" id="m-crypto" name="method" value="crypto"{' checked' if method == 'crypto' else ''}> <label for="m-crypto" style="display:inline">Crypto wallet (tUSDC on Quest Testnet)</label></p>
</fieldset>
<div id="card-fields"><fieldset><legend>Card details</legend>
<label for="card_number">Card number</label><input type="text" id="card_number" name="card_number" inputmode="numeric" autocomplete="cc-number" value="{v('card_number')}">
<label for="card_exp">Expiry date (MM/YY)</label><input type="text" id="card_exp" name="card_exp" placeholder="MM/YY" autocomplete="cc-exp" value="{v('card_exp')}">
<label for="card_cvc">Security code (CVC)</label><input type="text" id="card_cvc" name="card_cvc" inputmode="numeric" autocomplete="cc-csc">
<label for="card_name">Name on card</label><input type="text" id="card_name" name="card_name" autocomplete="cc-name" value="{v('card_name')}">
</fieldset><p><button class="btn" type="submit" id="pay-card">Pay {money(total)}</button></p></div>
<div id="crypto-fields" hidden><p>You will approve a payment of <b>{total:.2f} tUSDC</b> in your wallet.</p>
<p><button class="btn" type="button" id="pay-wallet">Pay with wallet</button></p></div>
<div id="wallet-status" role="status" style="font-family:system-ui,sans-serif"></div>
</form>
<script>
(function(){{
  var card = document.getElementById('card-fields'), crypto = document.getElementById('crypto-fields');
  function sync(){{ var c = document.getElementById('m-crypto').checked; card.hidden = c; crypto.hidden = !c; }}
  document.getElementById('m-card').addEventListener('change', sync);
  document.getElementById('m-crypto').addEventListener('change', sync); sync();
  var status = document.getElementById('wallet-status');
  document.getElementById('pay-wallet').addEventListener('click', async function(){{
    var w = window.open('about:blank', 'leafco-wallet', 'popup,width=440,height=680');
    status.textContent = 'Opening your wallet...';
    var r = await fetch('/shop/api/crypto-intent', {{method: 'POST'}});
    var j = await r.json();
    if (!r.ok) {{ if (w) w.close(); status.textContent = j.error; return; }}
    var url = '/wallet/approve?req=' + j.req;
    if (w) w.location = url; else window.open(url, 'leafco-wallet');
    status.textContent = 'Waiting for approval in your wallet...';
    var timer = setInterval(async function(){{
      var s = await (await fetch('/shop/api/crypto-status?req=' + j.req)).json();
      if (s.status === 'approved' && s.order) {{ clearInterval(timer); location.href = '/shop/order/' + s.order; }}
      else if (s.status === 'rejected') {{ clearInterval(timer); status.textContent = 'The payment was rejected in your wallet. You have not been charged.'; }}
    }}, 600);
  }});
}})();
</script>"""
    return layout(req, "Checkout", body)


@route("GET", r"/shop/checkout")
def checkout_get(req):
    _, acct = ctx(req)
    if not acct:
        return need_login(req)
    return checkout_page(req, acct)


def luhn_ok(num):
    digits = [int(c) for c in num][::-1]
    total = 0
    for i, d in enumerate(digits):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@route("POST", r"/shop/checkout")
def checkout_post(req):
    st = core.STATE["shop"]
    _, acct = ctx(req)
    if not acct:
        return need_login(req)
    lines = cart_lines(acct["cart"])
    if checkout_blockers(acct, lines):
        return checkout_page(req, acct)
    if req.f("method") == "crypto":
        return checkout_page(req, acct, ["Use the 'Pay with wallet' button to pay with your wallet."], method="crypto")
    vals = {k: req.f(k) for k in ("card_number", "card_exp", "card_cvc", "card_name")}
    num = re.sub(r"[\s-]", "", vals["card_number"])
    errors = []
    if not re.fullmatch(r"\d{13,19}", num) or not luhn_ok(num):
        errors.append("The card number is not valid.")
    m = re.fullmatch(r"(\d{2})\s*/\s*(\d{2})", vals["card_exp"])
    if not m or not 1 <= int(m.group(1)) <= 12:
        errors.append("Enter the expiry date as MM/YY.")
    elif (2000 + int(m.group(2)), int(m.group(1))) < (2026, 3):
        errors.append("This card has expired.")
    if not re.fullmatch(r"\d{3,4}", vals["card_cvc"]):
        errors.append("Enter the 3-digit security code.")
    if not vals["card_name"]:
        errors.append("Enter the name on the card.")
    attempt = {"email": acct["email"], "last4": num[-4:] if len(num) >= 4 else num, "result": None}
    if errors:
        attempt["result"] = "invalid"
        st["payment_attempts"].append(attempt)
        core.event("shop", "payment_invalid", errors=errors)
        return checkout_page(req, acct, errors, vals)
    test_num = re.sub(r"[\s-]", "", core.secret("CARD_NUMBER", "4242424242424242"))
    ok = (num == test_num and vals["card_exp"].replace(" ", "") == core.secret("CARD_EXP", "12/30")
          and vals["card_cvc"] == core.secret("CARD_CVC", "123"))
    if not ok:
        attempt["result"] = "declined"
        st["payment_attempts"].append(attempt)
        core.event("shop", "payment_declined", last4=attempt["last4"])
        return checkout_page(req, acct, ["Your card was declined. Check the details or use another card."], vals)
    attempt["result"] = "approved"
    st["payment_attempts"].append(attempt)
    order = place_order(acct, lines, {"method": "card", "last4": num[-4:], "name": vals["card_name"]})
    return redirect(f"/shop/order/{order['number']}")


def place_order(acct, lines, payment):
    st = core.STATE["shop"]
    sub, ship, total = totals(lines)
    order = {"number": f"LC-{core.next_id('order', 10001)}", "email": acct["email"], "name": acct["name"],
             "items": [{k: l[k] for k in ("pid", "name", "variant", "variant_name", "qty", "unit_price", "line_total")}
                       for l in lines],
             "subtotal": sub, "shipping": ship, "total": total, "address": dict(acct["address"]),
             "payment": payment, "date": core.clock()}
    st["orders"].append(order)
    acct["cart"].clear()
    core.event("shop", "order_placed", number=order["number"], total=total, method=payment["method"])
    return order


@route("POST", r"/shop/api/crypto-intent")
def crypto_intent(req):
    _, acct = ctx(req)
    if not acct:
        return json_response({"error": "Please log in first."}, 401)
    lines = cart_lines(acct["cart"])
    block = checkout_blockers(acct, lines)
    if block:
        return json_response({"error": block}, 409)
    _, _, total = totals(lines)
    amount = int(round(total * 100)) * 10 ** 4      # 6-decimals token units
    r = wallet.create_request(
        "shop", f"http://{req.headers.get('Host', '127.0.0.1')}/shop (Leaf & Co)", "payment",
        f"Pay {total:.2f} tUSDC to Leaf & Co", to=MERCHANT, value=f"{total:.2f} tUSDC",
        data=wallet.calldata("transfer(address,uint256)", MERCHANT, amount), method="transfer(address,uint256)",
        params={"recipient": MERCHANT, "amount": f"{total:.2f} tUSDC"},
        meta={"email": acct["email"], "lines": lines})
    core.event("shop", "crypto_intent", req=r["id"], total=total)
    return json_response({"req": r["id"]})


@route("GET", r"/shop/api/crypto-status")
def crypto_status(req):
    r = wallet.get_request(req.query.get("req"))
    if not r or r["origin"] != "shop":
        return json_response({"error": "unknown request"}, 404)
    return json_response({"status": r["status"], "order": r["meta"].get("order")})


def on_wallet(r, decision):
    st = core.STATE["shop"]
    acct = st["accounts"].get(r["meta"].get("email"))
    if not acct:
        return
    if decision == "approved":
        lines = r["meta"]["lines"]
        _, _, total = totals(lines)
        st["payment_attempts"].append({"email": acct["email"], "method": "crypto", "result": "approved"})
        core.STATE["wallet"]["balances"]["tUSDC"] = round(core.STATE["wallet"]["balances"]["tUSDC"] - total, 2)
        order = place_order(acct, lines, {"method": "crypto", "tx_hash": r.get("tx_hash"), "wallet_request": r["id"]})
        r["meta"]["order"] = order["number"]
    else:
        st["payment_attempts"].append({"email": acct["email"], "method": "crypto", "result": "rejected"})
        core.event("shop", "crypto_rejected", req=r["id"])


wallet.on_decision["shop"] = on_wallet


@route("GET", r"/shop/order/(?P<number>LC-\d+)")
def order_page(req):
    _, acct = ctx(req)
    o = next((o for o in core.STATE["shop"]["orders"] if o["number"] == req.params["number"]), None)
    if not o or not acct or o["email"] != acct["email"]:
        return core.not_found("No such order")
    items = "".join(f"<li>{i['qty']} &times; {esc(i['name'])} ({esc(i['variant_name'])}) &mdash; {money(i['line_total'])}</li>"
                    for i in o["items"])
    pay = (f"card ending in {o['payment']['last4']}" if o["payment"]["method"] == "card"
           else f"wallet, transaction {o['payment']['tx_hash'][:18]}...")
    body = f"""<h1>Thank you for your order!</h1><div class="ok" role="status">Your order number is <b id="order-number">{o['number']}</b>.
We sent nothing anywhere: this is a test shop.</div>
<div class="summary"><ul>{items}</ul>Total paid: <b>{money(o['total'])}</b> by {esc(pay)}<br>
Delivery to {esc(o['address']['street'])}, {esc(o['address']['postal_code'])} {esc(o['address']['city'])}</div>
<p><a class="btn" href="/shop/catalogue">Continue shopping</a></p>"""
    return layout(req, "Order " + o["number"], body)

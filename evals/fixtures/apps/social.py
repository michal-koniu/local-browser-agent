"""/social/ : "Chirp", a small micro-blog. Log in, write a post (280 characters, optional image, audience), delete."""
import hashlib
import urllib.parse

from . import core
from .core import esc, page, redirect, route

COOKIE = "chirp_sid"
MAX_LEN = 280
MAX_IMAGE = 2 * 1024 * 1024
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
MEDIA = {}      # media id -> (content type, bytes); kept out of /__state

CSS = """
*{box-sizing:border-box} body{margin:0;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#fff;color:#0f1419}
.shell{display:flex;max-width:1000px;margin:0 auto} aside{width:220px;padding:16px;position:sticky;top:0;height:100vh}
aside .logo{font-size:26px;font-weight:800;color:#1d9bf0;text-decoration:none} aside nav a{display:block;padding:10px 0;color:#0f1419;text-decoration:none;font-size:18px}
main{flex:1;max-width:600px;border-left:1px solid #eff3f4;border-right:1px solid #eff3f4;min-height:100vh}
main h1{font-size:20px;padding:14px 16px;margin:0;border-bottom:1px solid #eff3f4}
.composer{padding:14px 16px;border-bottom:1px solid #eff3f4} .composer textarea{width:100%;border:0;font:19px system-ui,sans-serif;resize:vertical;min-height:80px;outline:none}
.composer .row{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:8px}
.composer select{padding:6px 8px;border-radius:16px;border:1px solid #cfd9de;color:#1d9bf0;font-weight:600}
.count{margin-left:auto;color:#536471;font-size:14px} .count.over{color:#f4212e;font-weight:700}
.btn{background:#1d9bf0;color:#fff;border:0;border-radius:20px;padding:9px 18px;font:700 15px system-ui,sans-serif;cursor:pointer}
.btn:disabled{opacity:.5;cursor:default} .btn.ghost{background:#fff;color:#0f1419;border:1px solid #cfd9de}
.post{padding:12px 16px;border-bottom:1px solid #eff3f4;display:flex;gap:12px}
.avatar{width:42px;height:42px;border-radius:50%;flex:none;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700}
.post .who b{margin-right:6px} .post .who span{color:#536471;font-size:14px} .post p{margin:4px 0;white-space:pre-wrap}
.post img{max-width:100%;border-radius:14px;border:1px solid #eff3f4;margin-top:6px}
.post form{display:inline} .del{background:none;border:0;color:#f4212e;cursor:pointer;font-size:13px;padding:0}
.aud{font-size:12px;color:#536471;border:1px solid #cfd9de;border-radius:10px;padding:0 6px;margin-left:6px}
.err{background:#fde8ea;color:#a3141f;padding:10px 16px} .ok{background:#e8f5fd;color:#0b5a8f;padding:10px 16px}
.login{max-width:380px;margin:60px auto;padding:0 20px} .login input{width:100%;padding:12px;border:1px solid #cfd9de;border-radius:6px;font-size:16px;margin:4px 0 14px}
"""

SEED_POSTS = [
    ("garden_gina", "Gina Green", "My tomato seedlings finally sprouted. Twelve out of twelve!", "public"),
    ("alex_tester", "Alex Tester", "Repotted the monstera today. It was very root-bound.", "public"),
    ("cityrunner", "Chris Runner", "5 km before breakfast. The park was empty and quiet.", "public"),
    ("alex_tester", "Alex Tester", "test post please ignore", "public"),
    ("bookish_bo", "Bo Reader", "Finished a 600-page novel in a week. Recommendations for the next one?", "followers"),
]


@core.app_init("social")
def init():
    MEDIA.clear()
    user = core.secret("SOCIAL_USERNAME", "alex_tester")
    posts = []
    for i, (author, name, text, aud) in enumerate(SEED_POSTS, 1):
        if author == "alex_tester":
            author = user
        posts.append({"id": i, "author": author, "display_name": name, "text": text, "audience": aud, "image": None,
                      "date": f"2026-03-0{1 if i < 4 else 2} 0{i}:15", "deleted": False, "seeded": True})
    core.STATE["_counters"]["post"] = len(posts)
    return {"users": {user: {"password": core.secret("SOCIAL_PASSWORD", "Fake-Chirp-Pass-9753"),
                             "display_name": "Alex Tester"}},
            "sessions": {}, "posts": posts}


def current(req):
    sess = core.session(req, "social", COOKIE)
    return sess, sess.get("user")


COLORS = ["#1d9bf0", "#00ba7c", "#f91880", "#7856ff", "#ff7a00"]


def layout(title, body, user):
    nav = (f'<a href="/social/">Home</a><a href="/social/u/{esc(user)}">Profile</a>'
           f'<form method="post" action="/social/logout"><button class="btn ghost" type="submit">Log out @{esc(user)}</button></form>'
           if user else '<a href="/social/login">Log in</a>')
    return page(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} / Chirp</title><style>{CSS}</style></head>
<body><div class="shell"><aside><a class="logo" href="/social/">Chirp</a><nav aria-label="Primary">{nav}</nav></aside>
<main>{body}</main></div></body></html>""")


def render_post(p, user):
    color = COLORS[sum(map(ord, p["author"])) % len(COLORS)]
    img = (f'<img src="/social/media/{p["image"]["id"]}" alt="{esc(p["image"]["alt"] or "Image")}">' if p["image"] else "")
    aud = '<span class="aud">Followers</span>' if p["audience"] == "followers" else ""
    dele = ""
    if user and p["author"] == user:
        dele = (f'<form method="post" action="/social/delete/{p["id"]}" '
                f'onsubmit="return confirm(\'Delete this post? This cannot be undone.\')">'
                f'<button class="del" type="submit" aria-label="Delete post: {esc(p["text"][:40])}">Delete</button></form>')
    return (f'<article class="post"><div class="avatar" style="background:{color}" aria-hidden="true">{esc(p["display_name"][0])}</div>'
            f'<div style="flex:1"><div class="who"><b>{esc(p["display_name"])}</b><span>@{esc(p["author"])} &middot; {esc(p["date"])}</span>{aud}</div>'
            f'<p>{esc(p["text"])}</p>{img}<div>{dele}</div></div></article>')


@route("GET", r"/social/login")
def login_get(req, error=""):
    _, user = current(req)
    body = f"""<div class="login"><h1 style="border:0;padding:0 0 10px">Log in to Chirp</h1>
{f'<div class="err" role="alert">{esc(error)}</div>' if error else ''}
<form method="post" action="/social/login"><label for="username">Username</label><input id="username" name="username" autocomplete="username">
<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password">
<button class="btn" type="submit" style="width:100%">Log in</button></form></div>"""
    return layout("Log in", body, user)


@route("POST", r"/social/login")
def login_post(req):
    st = core.STATE["social"]
    sess, _ = current(req)
    u = req.f("username").lstrip("@")
    acct = st["users"].get(u)
    if not acct or acct["password"] != req.form.get("password", ""):
        core.event("social", "login_failed", username=u)
        return login_get(req, "Wrong username or password.")
    sess["user"] = u
    core.event("social", "login", username=u)
    return redirect("/social/")


@route("POST", r"/social/logout")
def logout(req):
    sess, _ = current(req)
    sess["user"] = None
    return redirect("/social/login")


@route("GET", r"/social/?")
def feed(req):
    _, user = current(req)
    if not user:
        return redirect("/social/login")
    st = core.STATE["social"]
    note = ""
    if req.query.get("msg"):
        note = f'<div class="ok" role="status">{esc(req.query["msg"])}</div>'
    if req.query.get("error"):
        note = f'<div class="err" role="alert">{esc(req.query["error"])}</div>'
    posts = [p for p in reversed(st["posts"]) if not p["deleted"]]
    body = f"""<h1>Home</h1>{note}
<form class="composer" method="post" action="/social/post" enctype="multipart/form-data">
<label for="text" style="position:absolute;left:-9999px">What is happening?</label>
<textarea id="text" name="text" placeholder="What is happening?"></textarea>
<div class="row"><label for="image">Add image</label><input id="image" name="image" type="file" accept="image/*">
<label for="audience" style="position:absolute;left:-9999px">Audience</label>
<select id="audience" name="audience"><option value="public">Everyone</option><option value="followers">Followers only</option></select>
<span class="count" id="count" aria-live="polite">{MAX_LEN} characters left</span>
<button class="btn" id="post-btn" type="submit" disabled>Post</button></div></form>
{''.join(render_post(p, user) for p in posts)}
<script>
(function(){{
  var t = document.getElementById('text'), c = document.getElementById('count'), b = document.getElementById('post-btn'),
      f = document.getElementById('image');
  function upd(){{ var left = {MAX_LEN} - t.value.length;
    c.textContent = left >= 0 ? left + ' characters left' : (-left) + ' characters over the limit';
    c.className = 'count' + (left < 0 ? ' over' : '');
    b.disabled = left < 0 || (t.value.trim() === '' && !f.files.length); }}
  t.addEventListener('input', upd); f.addEventListener('change', upd); upd();
}})();
</script>"""
    return layout("Home", body, user)


@route("POST", r"/social/post")
def post(req):
    st = core.STATE["social"]
    _, user = current(req)
    if not user:
        return redirect("/social/login")
    text = req.form.get("text", "").replace("\r\n", "\n").strip()
    audience = req.f("audience") if req.f("audience") in ("public", "followers") else "public"
    f = req.files.get("image")
    if len(text) > MAX_LEN:
        return redirect("/social/?error=" + urllib.parse.quote(f"Posts can have at most {MAX_LEN} characters."))
    if not text and not f:
        return redirect("/social/?error=" + urllib.parse.quote("Write something or add an image."))
    image = None
    if f:
        if f["content_type"] not in IMAGE_TYPES:
            return redirect("/social/?error=" + urllib.parse.quote("Only PNG, JPEG, GIF or WebP images can be attached."))
        if len(f["data"]) > MAX_IMAGE:
            return redirect("/social/?error=" + urllib.parse.quote("The image is larger than 2 MB."))
        mid = core.next_id("media")
        MEDIA[mid] = (f["content_type"], f["data"])
        image = {"id": mid, "filename": f["filename"], "content_type": f["content_type"], "size": len(f["data"]),
                 "sha256": hashlib.sha256(f["data"]).hexdigest(), "alt": ""}
    p = {"id": core.next_id("post"), "author": user, "display_name": st["users"][user]["display_name"], "text": text,
         "audience": audience, "image": image, "date": core.clock(), "deleted": False, "seeded": False}
    st["posts"].append(p)
    core.event("social", "posted", id=p["id"], audience=audience, has_image=bool(image), length=len(text))
    return redirect("/social/?msg=" + urllib.parse.quote("Your post was sent."))


@route("POST", r"/social/delete/(?P<pid>\d+)")
def delete(req):
    st = core.STATE["social"]
    _, user = current(req)
    if not user:
        return redirect("/social/login")
    p = next((p for p in st["posts"] if p["id"] == int(req.params["pid"])), None)
    if not p or p["author"] != user or p["deleted"]:
        return redirect("/social/?error=" + urllib.parse.quote("You cannot delete this post."))
    p["deleted"] = True
    core.event("social", "deleted", id=p["id"], text=p["text"])
    return redirect("/social/?msg=" + urllib.parse.quote("Your post was deleted."))


@route("GET", r"/social/media/(?P<mid>\d+)")
def media(req):
    m = MEDIA.get(int(req.params["mid"]))
    if not m:
        return core.not_found()
    return core.Response(m[1], 200, m[0])


@route("GET", r"/social/u/(?P<name>[A-Za-z0-9_]+)")
def profile(req):
    _, user = current(req)
    st = core.STATE["social"]
    posts = [p for p in reversed(st["posts"]) if p["author"] == req.params["name"] and not p["deleted"]]
    body = f"<h1>@{esc(req.params['name'])}</h1>" + ("".join(render_post(p, user) for p in posts) or "<p style='padding:16px'>No posts.</p>")
    return layout("@" + req.params["name"], body, user)

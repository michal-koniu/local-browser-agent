"""Measure how a model points at things on a screenshot - so click_at converts its coordinates correctly.

Opens a page with 12 labelled targets at known positions, takes a screenshot, and asks the model for the click
point of each label three ways: with no convention named, with the 0-1000 grid named (what click_at says when
coords = "norm1000"), and with screenshot pixels named (coords = "pixels"). It scores each answer set, reports hit
rate and mean miss, and recommends the setting whose own prompt scored best. Measured 28 Oct 2026 on
Qwen3.8-Flash-Next: without a named convention the model mixes them (y on the grid, x sometimes in other units).
"""
import json
import re
import urllib.parse
from pathlib import Path

from . import config as config_mod
from .browser import Browser
from .llm import LLM

TARGETS = [("Apple", 60, 80), ("Banana", 600, 60), ("Cherry", 1220, 90), ("Date", 140, 420),
           ("Elder", 700, 380), ("Fig", 1260, 450), ("Grape", 90, 780), ("Honeydew", 560, 720),
           ("Kiwi", 1150, 800), ("Lemon", 330, 230), ("Mango", 980, 250), ("Nectarine", 860, 600)]


def page_html():
    buttons = "".join(f'<button style="position:absolute;left:{x}px;top:{y}px;width:120px;height:40px">{n}</button>'
                      for n, x, y in TARGETS)
    return f"<html><body style='margin:0;font:16px sans-serif;background:#f4f4f4'>{buttons}</body></html>"


async def run(cfg, model_name=None):
    model = config_mod.model(cfg, model_name)
    run_dir = Path(config_mod.ROOT / "runs" / f"calibrate-{model['name']}")
    run_dir.mkdir(parents=True, exist_ok=True)
    b = Browser({**cfg["browser"], "mode": "isolated", "headless": True}, run_dir, config_mod.ROOT)
    llm = LLM(cfg["base_url"], cfg["api_key"], model)
    await b.start()
    try:
        await b.call("browser_navigate", {"url": "data:text/html," + urllib.parse.quote(page_html())})
        _, images, _ = await b.call("browser_take_screenshot", {"type": "png"})
        mime, data = images[0]
        prompts = {
            "native": "Reply only with JSON: {\"x\": <number>, \"y\": <number>}",
            "norm1000": "Give the point on a 0-1000 grid over the screenshot (0,0 = top left, 1000,1000 = bottom "
                        "right). Reply only with JSON: {\"x\": <number>, \"y\": <number>}",
            "pixels": f"Give the point in screenshot pixels; the image is {b.vw}x{b.vh} (0,0 = top left). Reply only "
                      "with JSON: {\"x\": <number>, \"y\": <number>}",
        }
        results = {k: [] for k in prompts}
        for variant, rule in prompts.items():
            for name, x, y in TARGETS:
                msg, _, _ = await llm.chat([{"role": "user", "content": [
                    {"type": "text", "text": f"This is a screenshot of a web page. Where would you click to press "
                                             f"the button labelled \"{name}\"? {rule}"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}]}], tools=None)
                m = re.search(r"\{[^{}]*\}", msg.get("content") or "")
                try:
                    p = json.loads(m.group(0)) if m else None
                except json.JSONDecodeError:
                    p = None
                results[variant].append((name, x + 60, y + 20, p))  # target centre
    finally:
        await b.close()
        await llm.close()
    print(f"model {model['id']}  viewport {b.vw}x{b.vh}")
    scores = {}
    for variant, answers in results.items():
        for conv in ("pixels", "norm1000"):
            hits, dist = 0, []
            for name, cx, cy, p in answers:
                if not p or "x" not in p:
                    continue
                px, py = b.to_px(float(p["x"]), float(p["y"]), conv)
                hits += abs(px - cx) <= 60 and abs(py - cy) <= 20
                dist.append(((px - cx) ** 2 + (py - cy) ** 2) ** 0.5)
            avg = sum(dist) / len(dist) if dist else float("inf")
            scores[(variant, conv)] = (hits, avg)
            print(f"  prompt {variant:9} read as {conv:9} hits {hits:2}/{len(TARGETS)}  mean miss {avg:5.0f} px")
    best = max(("norm1000", "pixels"), key=lambda c: (scores[(c, c)][0], -scores[(c, c)][1]))
    print(f'recommended: coords = "{best}"  (prompt naming the convention, as click_at does)')
    (run_dir / "calibration.json").write_text(json.dumps(
        {"model": model["id"], "answers": results, "recommended": best,
         "scores": {f"{v}/{c}": s for (v, c), s in scores.items()}}, indent=2))
    return best

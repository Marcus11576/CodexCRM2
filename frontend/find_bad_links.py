"""Find all bad nav links in HTML files and fix them."""
import os, re

frontend = 'C:/Users/marcu/.antigravity/antigravity-crm/frontend'
files = [f for f in os.listdir(frontend) if f.endswith('.html')]

for fn in files:
    path = os.path.join(frontend, fn)
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    
    # Find anything pointing at static/*.html
    bad = re.findall(r'href="[^"]*?\.html[^"]*?"', text)
    if bad:
        print(f"{fn}: {bad}")

print("\n--- JS files ---")
js_dir = os.path.join(frontend, 'js')
for fn in os.listdir(js_dir):
    if fn.endswith('.js'):
        path = os.path.join(js_dir, fn)
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        bad = [m for m in re.findall(r"href=['\"][^'\"]*?\.html[^'\"]*?['\"]", text) if 'html' in m]
        if bad:
            print(f"js/{fn}: {bad[:3]}")
        # Also check window.location.href
        locs = re.findall(r"location\.href\s*=\s*['\"`][^'\"`;]*?\.html[^'\"`;]*?['\"`]", text)
        if locs:
            print(f"js/{fn} location.href: {locs[:3]}")

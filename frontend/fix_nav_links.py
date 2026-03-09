"""Fix all remaining /static/*.html nav links in all HTML files."""
import os, re

frontend = 'C:/Users/marcu/.antigravity/antigravity-crm/frontend'

# Map of old paths -> new clean routes
replacements = {
    '/static/index.html': '/',
    '/static/agenda.html': '/agenda',
    '/static/settings.html': '/settings',
    '/static/login.html': '/login',
    '/static/profile.html': '/profile',
    'static/index.html': '/',
    'static/agenda.html': '/agenda',
    'static/settings.html': '/settings',
    'static/login.html': '/login',
    # Also fix any remaining .html without /static/ prefix
    'href="index.html"': 'href="/"',
    "href='index.html'": "href='/'",
    'href="agenda.html"': 'href="/agenda"',
    "href='agenda.html'": "href='/agenda'",
    'href="settings.html"': 'href="/settings"',
    "href='settings.html'": "href='/settings'",
    'href="login.html"': 'href="/login"',
    "href='login.html'": "href='/login'",
}

for fn in [f for f in os.listdir(frontend) if f.endswith('.html')]:
    path = os.path.join(frontend, fn)
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    
    original = text
    for old, new in replacements.items():
        text = text.replace(f'href="{old}"', f'href="{new}"')
        text = text.replace(f"href='{old}'", f"href='{new}'")
    
    if text != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"Fixed: {fn}")
    else:
        print(f"OK (no changes): {fn}")

# Also fix JS files
js_dir = os.path.join(frontend, 'js')
for fn in os.listdir(js_dir):
    if not fn.endswith('.js'):
        continue
    path = os.path.join(js_dir, fn)
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    
    original = text
    text = text.replace('/static/settings.html', '/settings')
    text = text.replace('/static/agenda.html', '/agenda')
    text = text.replace('/static/index.html', '/')
    text = text.replace('/static/login.html', '/login')
    text = text.replace("'settings.html'", "'/settings'")
    text = text.replace('"settings.html"', '"/settings"')
    text = text.replace("'agenda.html'", "'/agenda'")
    text = text.replace('"agenda.html"', '"/agenda"')
    text = text.replace("'person.html?id=", "'/person/")
    text = text.replace('"person.html?id=', '"/person/')
    
    if text != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"Fixed JS: {fn}")

print("\nDone!")

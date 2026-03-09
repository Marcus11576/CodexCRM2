"""
Fix all remaining API wiring issues in the extracted JS files.
Run from: anywhere
"""
import re
import os

frontend = 'C:/Users/marcu/.antigravity/antigravity-crm/frontend'

# ── profile.js fixes ─────────────────────────────────────────────────────────
profile_js = os.path.join(frontend, 'js/profile.js')
with open(profile_js, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Make sure personId is read from URL path (not query string ?id=...)
#    Backend serves /person/{uuid} style routes
old = "urlParams.get('id')"
new = "window.location.pathname.split('/').filter(Boolean).pop()"
text = text.replace(old, new)

# 2. Map old brief API to new intelligence router
text = text.replace(
    "api/people/${personId}/meeting-brief",
    "api/intelligence/brief/${personId}"
)
text = text.replace(
    "api/people/${personId}/brief-audio",
    "api/intelligence/tts/${personId}"
)
text = text.replace(
    "api/people/${personId}/chat",
    "api/intelligence/chat/${personId}"
)
text = text.replace(
    "api/transcribe-audio",
    "api/intelligence/transcribe"
)

# 3. Fix media upload endpoint
text = text.replace(
    "${API_BASE}/people/${personId}/media",
    "${API_BASE}/api/people/${personId}/media"
)

with open(profile_js, 'w', encoding='utf-8') as f:
    f.write(text)
print("profile.js fixed")


# ── index.js fixes ─────────────────────────────────────────────────────────
index_js = os.path.join(frontend, 'js/index.js')
with open(index_js, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix person nav links - should be /person/ID not /people/ID
text = text.replace("/people/${", "/person/${")
text = text.replace("person.html?id=${", "/person/${")

# Fix twin-chat (not yet wired, prevent console 404 flood)
text = text.replace(
    "api/twin/chat",
    "api/intelligence/twin/chat"
)
text = text.replace(
    "api/twin/execute",
    "api/intelligence/twin/execute"
)
text = text.replace(
    "api/twin/upload_pdf",
    "api/intelligence/twin/upload_pdf"
)
text = text.replace(
    "api/transcribe",
    "api/intelligence/transcribe"
)
text = text.replace(
    "api/transcribe-audio",
    "api/intelligence/transcribe"
)

with open(index_js, 'w', encoding='utf-8') as f:
    f.write(text)
print("index.js fixed")


# ── agenda.js fixes ─────────────────────────────────────────────────────────
agenda_js = os.path.join(frontend, 'js/agenda.js')
with open(agenda_js, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace("person.html?id=${", "/person/${")
text = text.replace("/people/${", "/person/${")

with open(agenda_js, 'w', encoding='utf-8') as f:
    f.write(text)
print("agenda.js fixed")


# ── index.html nav links ─────────────────────────────────────────────────────
index_html = os.path.join(frontend, 'index.html')
with open(index_html, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix sidebar nav links (href="agenda.html" -> href="/agenda")
text = text.replace('href="index.html"', 'href="/"')
text = text.replace("href='index.html'", "href='/'")
text = text.replace('href="agenda.html"', 'href="/agenda"')
text = text.replace("href='agenda.html'", "href='/agenda'")
text = text.replace('href="settings.html"', 'href="/settings"')
text = text.replace("href='settings.html'", "href='/settings'")
text = text.replace('href="login.html"', 'href="/login"')
text = text.replace("href='login.html'", "href='/login'")
text = text.replace('href="person.html', 'href="/person/')
text = text.replace("href='person.html", "href='/person/")

with open(index_html, 'w', encoding='utf-8') as f:
    f.write(text)
print("index.html nav links fixed")


# ── profile.html nav links ─────────────────────────────────────────────────
profile_html = os.path.join(frontend, 'profile.html')
with open(profile_html, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('href="index.html"', 'href="/"')
text = text.replace("href='index.html'", "href='/'")
text = text.replace('href="agenda.html"', 'href="/agenda"')
text = text.replace("href='agenda.html'", "href='/agenda'")
text = text.replace('href="settings.html"', 'href="/settings"')
text = text.replace("href='settings.html'", "href='/settings'")
text = text.replace('href="login.html"', 'href="/login"')
text = text.replace("href='login.html'", "href='/login'")

with open(profile_html, 'w', encoding='utf-8') as f:
    f.write(text)
print("profile.html nav links fixed")


# ── agenda.html nav links ─────────────────────────────────────────────────
agenda_html = os.path.join(frontend, 'agenda.html')
with open(agenda_html, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('href="index.html"', 'href="/"')
text = text.replace("href='index.html'", "href='/'")
text = text.replace('href="agenda.html"', 'href="/agenda"')
text = text.replace("href='agenda.html'", "href='/agenda'")
text = text.replace('href="settings.html"', 'href="/settings"')
text = text.replace("href='settings.html'", "href='/settings'")
text = text.replace('href="login.html"', 'href="/login"')
text = text.replace("href='login.html'", "href='/login'")

with open(agenda_html, 'w', encoding='utf-8') as f:
    f.write(text)
print("agenda.html nav links fixed")


# ── settings.html nav links ─────────────────────────────────────────────────
settings_html = os.path.join(frontend, 'settings.html')
with open(settings_html, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('href="index.html"', 'href="/"')
text = text.replace("href='index.html'", "href='/'")
text = text.replace('href="agenda.html"', 'href="/agenda"')
text = text.replace("href='agenda.html'", "href='/agenda'")
text = text.replace('href="settings.html"', 'href="/settings"')
text = text.replace("href='settings.html'", "href='/settings'")
text = text.replace('href="login.html"', 'href="/login"')
text = text.replace("href='login.html'", "href='/login'")

with open(settings_html, 'w', encoding='utf-8') as f:
    f.write(text)
print("settings.html nav links fixed")

print("\nAll fixes complete!")

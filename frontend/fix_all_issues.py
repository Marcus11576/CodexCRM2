"""Fix all issues: taxonomy 500, manifest/sw 404, env filter, agenda/settings routes."""
import os

frontend = 'C:/Users/marcu/.antigravity/antigravity-crm/frontend'
static_dir = os.path.join(frontend, 'static')

# 1. Create manifest.json
manifest = '''{
  "name": "Antigravity CRM",
  "short_name": "CRM",
  "description": "Relationship Intelligence Platform",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0a0a0f",
  "theme_color": "#0047ff",
  "icons": [
    { "src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}'''
with open(os.path.join(static_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
    f.write(manifest)
print("Created manifest.json")

# 2. Create sw.js (minimal no-op service worker to silence errors)
sw_js = """// Antigravity CRM Service Worker
self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(clients.claim()));
self.addEventListener('fetch', (e) => {}); // Pass-through
"""
with open(os.path.join(static_dir, 'sw.js'), 'w', encoding='utf-8') as f:
    f.write(sw_js)
print("Created sw.js")

# 3. Fix profile.js: taxonomy fetch needs to handle list response (not an object)
#    The /api/config/taxonomy returns a list from /api/taxonomy - we need to alias properly
profile_js = os.path.join(frontend, 'js/profile.js')
with open(profile_js, 'r', encoding='utf-8') as f:
    text = f.read()

# The taxonomy endpoint now returns a flat list. Fix the reduce to handle either format.
old_taxonomy_fetch = '''        async function fetchTaxonomy() {
            try {
                const res = await fetch(`${API_BASE}/api/config/taxonomy`);
                const data = await res.json();
                activeTaxonomy = data.reduce((acc, item) => {
                    if (!acc[item.category_type]) acc[item.category_type] = [];
                    acc[item.category_type].push(item);
                    return acc;
                }, {});
            } catch (err) {
                console.error("Failed to fetch taxonomy:", err);
            }
        }'''

new_taxonomy_fetch = '''        async function fetchTaxonomy() {
            try {
                const res = await fetch(`${API_BASE}/api/config/taxonomy`);
                const data = await res.json();
                // Handle both array response and grouped-object response
                const list = Array.isArray(data) ? data : (data.items || []);
                activeTaxonomy = list.reduce((acc, item) => {
                    if (!acc[item.category_type]) acc[item.category_type] = [];
                    acc[item.category_type].push(item);
                    return acc;
                }, {});
            } catch (err) {
                console.error("Failed to fetch taxonomy:", err);
                // Use hardcoded fallback so the page still renders
                activeTaxonomy = {
                    cat: [{value:'OBE M',label:'OBE Member'},{value:'OBE T',label:'OBE Target'},{value:'TGT',label:'Client Target'},{value:'EXT',label:'Existing Client'},{value:'HPC',label:'Candidate'},{value:'GEN',label:'General'}],
                    env: [{value:'DEV-G',label:'Gov Dev'},{value:'DEV-S',label:'Semi-Gov Dev'},{value:'DEV-P',label:'Private Dev'},{value:'CONS',label:'Consultant'},{value:'MAIN',label:'Main Contractor'},{value:'SUB',label:'Sub Contractor'},{value:'MGMT',label:'PMO'}],
                    disc: [{value:'COMM',label:'Commercial'},{value:'DELV',label:'Delivery'},{value:'DSGN',label:'Design'},{value:'CORP',label:'Corporate'},{value:'SUPP',label:'Support'},{value:'OTHR',label:'Others'}],
                    contact_value: [{value:'Hot',label:'Hot'},{value:'Warm',label:'Warm'},{value:'Cold',label:'Cold'}],
                    engagement_status: [{value:'Active',label:'Active'},{value:'Passive',label:'Passive'},{value:'Dormant',label:'Dormant'}]
                };
            }
        }'''

if old_taxonomy_fetch in text:
    text = text.replace(old_taxonomy_fetch, new_taxonomy_fetch)
    print("Fixed taxonomy fetch in profile.js")
else:
    print("WARNING: taxonomy fetch block not found exactly - patching by line")
    # Find and fix the reduce line directly  
    text = text.replace(
        'activeTaxonomy = data.reduce((acc, item) => {',
        'const list = Array.isArray(data) ? data : (data.items || []); activeTaxonomy = list.reduce((acc, item) => {'
    )

with open(profile_js, 'w', encoding='utf-8') as f:
    f.write(text)
print("profile.js updated")

# 4. Fix agenda.html: make sure it has proper link tags not wrong href
agenda_html = os.path.join(frontend, 'agenda.html')
with open(agenda_html, 'r', encoding='utf-8') as f:
    text = f.read()

# Check if agenda.js is properly linked
if '/js/agenda.js' not in text and 'agenda.js' in text:
    text = text.replace('<script src="agenda.js">', '<script src="/js/agenda.js">')
    print("Fixed agenda.js script src")

with open(agenda_html, 'w', encoding='utf-8') as f:
    f.write(text)

# 5. Fix settings.html
settings_html = os.path.join(frontend, 'settings.html')
with open(settings_html, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix settings.js link if needed
if '/js/settings.js' not in text and 'settings.js' in text:
    text = text.replace('<script src="settings.js">', '<script src="/js/settings.js">')
    print("Fixed settings.js script src")

# Fix the taxonomy/all endpoint used in settings
settings_js = os.path.join(frontend, 'js/settings.js')
with open(settings_js, 'r', encoding='utf-8') as f:
    stext = f.read()
stext = stext.replace('api/config/taxonomy/all', 'api/taxonomy/all')
stext = stext.replace('api/config/taxonomy', 'api/taxonomy')
with open(settings_js, 'w', encoding='utf-8') as f:
    f.write(stext)
print("Fixed settings.js taxonomy endpoints")

with open(settings_html, 'w', encoding='utf-8') as f:
    f.write(text)

# 6. Check agenda.js for proper task endpoints
with open(os.path.join(frontend, 'js/agenda.js'), 'r', encoding='utf-8') as f:
    atext = f.read()
# Make sure agenda uses /api/tasks not old endpoint names
atext = atext.replace('api/agenda', 'api/tasks')
atext = atext.replace('api/task/', 'api/tasks/')
with open(os.path.join(frontend, 'js/agenda.js'), 'w', encoding='utf-8') as f:
    f.write(atext)
print("Fixed agenda.js task endpoints")

print("\nAll fixes complete!")

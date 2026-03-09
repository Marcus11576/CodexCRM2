"""
Fix the hardcoded filter value mismatches in index.js and settings.js.
The DB uses full English values like 'Developer - Gov', 'Main Contractor', 'Commercial'
but the JS was using old short-codes like 'DEV-G', 'MAIN', 'COMM'.
"""

frontend = 'C:/Users/marcu/.antigravity/antigravity-crm/frontend'

# ── FIX INDEX.JS: Dashboard ENV/DISC filter maps ──────────────────────────────
with open(f'{frontend}/js/index.js', 'r', encoding='utf-8') as f:
    text = f.read()

# Fix ENV map - old short codes -> new full DB values
old_env_map = """            const envMap = {
                'Gov Dev': 'DEV-G',
                'Semi-Gov Dev': 'DEV-S',
                'Private Dev': 'DEV-P',
                'Consultant': 'CONS',
                'Main Contractor': 'MAIN',
                'Sub Contractor': 'SUB',
                'PMO': 'MGMT'
            };"""

new_env_map = """            const envMap = {
                'Gov Dev': 'Developer - Gov',
                'Semi-Gov Dev': 'Developer - Semi-Gov',
                'Private Dev': 'Developer - Private',
                'Consultant': 'Consultant',
                'Main Contractor': 'Main Contractor',
                'Sub Contractor': 'Sub Contractor',
                'PMO': 'Management Consultant'
            };"""

if old_env_map in text:
    text = text.replace(old_env_map, new_env_map)
    print("Fixed ENV map in index.js")
else:
    print("WARNING: ENV map not found exactly - trying partial fix")

# Fix DEV multi-select to use new values
old_dev_vals = "const devValues = ['DEV-G', 'DEV-S', 'DEV-P'];"
new_dev_vals = "const devValues = ['Developer - Gov', 'Developer - Semi-Gov', 'Developer - Private'];"
if old_dev_vals in text:
    text = text.replace(old_dev_vals, new_dev_vals)
    print("Fixed dev multi-select values")

# Fix all remaining occurrences of old dev values array (there are 2 of them in code)
text = text.replace("['DEV-G', 'DEV-S', 'DEV-P']", "['Developer - Gov', 'Developer - Semi-Gov', 'Developer - Private']")

# Fix DISC map
old_disc_map = """            const discMap = {
                'Commercial': 'COMM',
                'Delivery': 'DELV',
                'Design': 'DSGN',
                'Corporate': 'CORP',
                'Support': 'SUPP',
                'Others': 'OTHR'
            };"""

new_disc_map = """            const discMap = {
                'Commercial': 'Commercial',
                'Delivery': 'Delivery',
                'Design': 'Design',
                'Corporate': 'Corporate',
                'Support': 'Support Services',
                'Others': 'Other'
            };"""

if old_disc_map in text:
    text = text.replace(old_disc_map, new_disc_map)
    print("Fixed DISC map in index.js")
else:
    print("WARNING: DISC map not found exactly")

# Fix the CAT map used in filterChips
old_cat_map = """                'OBE Member': 'OBE M',
                'OBE Target': 'OBE T',
                'Client Target': 'TGT',
                'Existing Client': 'EXT',
                'Candidate': 'HPC',
                'General': 'GEN'"""

new_cat_map = """                'OBE Member': 'OBE M',
                'OBE Target': 'OBE T',
                'Client Target': 'TGT',
                'Target Client': 'TGT',
                'Existing Client': 'EXT',
                'Candidate': 'HPC',
                'High Performing Candidate': 'HPC',
                'General': 'GEN',
                'General Contact': 'GEN'"""

text = text.replace(old_cat_map, new_cat_map)
print("Fixed CAT map in index.js")

# Also fix filterList function that checks env/disc values
# The filter was comparing against short codes, now it needs to compare full values
# Search for filterList or similar function
import re
filter_func = re.search(r'function filterList\(contacts\).*?^        }', text, re.DOTALL | re.MULTILINE)
if filter_func:
    print(f"Found filterList at chars {filter_func.start()}-{filter_func.end()}")

with open(f'{frontend}/js/index.js', 'w', encoding='utf-8') as f:
    f.write(text)
print("index.js saved")

# ── FIX SETTINGS.JS ────────────────────────────────────────────────────────────
with open(f'{frontend}/js/settings.js', 'r', encoding='utf-8') as f:
    stext = f.read()

print(f"\nSettings.js length: {len(stext)}")
print("First 500 chars:")
print(stext[:500])

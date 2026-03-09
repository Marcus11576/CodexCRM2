import os
import re

files_to_process = [
    ('index.html', 'index.css', 'index.js'),
    ('profile.html', 'profile.css', 'profile.js'),
    ('agenda.html', 'agenda.css', 'agenda.js'),
    ('settings.html', 'settings.css', 'settings.js')
]

frontend_dir = 'C:/Users/marcu/.antigravity/antigravity-crm/frontend'

# Ensure directories exist
os.makedirs(os.path.join(frontend_dir, 'static'), exist_ok=True)
os.makedirs(os.path.join(frontend_dir, 'js'), exist_ok=True)

for html_file, css_file, js_file in files_to_process:
    path = os.path.join(frontend_dir, html_file)
    if not os.path.exists(path):
        continue
        
    with open(path, 'r', encoding='utf-8') as f:
        html = f.read()

    # CSS EXTRACTION
    styles = list(re.finditer(r'<style>(.*?)</style>', html, re.DOTALL | re.IGNORECASE))
    if styles:
        largest_style = max(styles, key=lambda m: len(m.group(1)))
        if len(largest_style.group(1)) > 500: # Only extract if it's substantial
            css_content = largest_style.group(1).strip()
            
            with open(os.path.join(frontend_dir, 'static', css_file), 'w', encoding='utf-8') as f:
                f.write(css_content)
                
            replacement = f'<link rel="stylesheet" href="/static/{css_file}">'
            # We replace the exact match string
            html = html.replace(largest_style.group(0), replacement)
            print(f'{html_file}: Extracted {len(css_content)} chars of CSS -> {css_file}')

    # JS EXTRACTION - Only match `<script>` blocks without `src=`
    scripts = list(re.finditer(r'<script(?![^>]*src=)[^>]*>\s*(.*?)\s*</script>', html, re.DOTALL | re.IGNORECASE))
    if scripts:
        largest_script = max(scripts, key=lambda m: len(m.group(1)))
        if len(largest_script.group(1)) > 1000: # Only extract if it's substantial
            js_content = largest_script.group(1).strip()
            
            with open(os.path.join(frontend_dir, 'js', js_file), 'w', encoding='utf-8') as f:
                f.write(js_content)
                
            # Keep any attributes from the original script tag (like type="module")
            original_tag = html[largest_script.start():largest_script.end()]
            script_opening_tag = re.search(r'<script[^>]*>', original_tag, re.IGNORECASE).group(0)
            
            # If it's type="module", we should probably keep it type="module"
            if 'type="module"' in script_opening_tag.lower():
                replacement = f'<script type="module" src="/js/{js_file}"></script>'
            else:
                replacement = f'<script src="/js/{js_file}"></script>'
                
            html = html.replace(largest_script.group(0), replacement)
            print(f'{html_file}: Extracted {len(js_content)} chars of JS -> {js_file}')

    # Write back the cleaned HTML
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)

print("Extraction complete.")

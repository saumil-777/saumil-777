"""verify_svgs.py — Quick security check on all generated SVGs."""
import re, pathlib, sys

svgs = ['ascii-portrait.svg', 'info-card.svg', 'contrib-heatmap.svg']
ok = True
for svg in svgs:
    txt = pathlib.Path(svg).read_text(encoding='utf-8')
    has_script = '<script' in txt.lower()
    # Only check attribute-value external refs (href= src= xlink:href=)
    attr_ext   = re.findall(r'(?:src|href)=["\']https?://[^"\']+', txt)
    issues = []
    if has_script:  issues.append('HAS <script>')
    if attr_ext:    issues.append(f'EXT REFS: {attr_ext[:2]}')
    status = 'PASS' if not issues else 'FAIL'
    print(f'{status}  {svg}')
    for i in issues: print(f'  {i}')
    if issues: ok = False

print()
print('Security check: PASS' if ok else 'Security check: FAIL')
sys.exit(0 if ok else 1)

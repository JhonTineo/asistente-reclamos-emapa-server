import httpx
import json
import re

# Leer la key del .env
with open(".env") as f:
    content = f.read()

m = re.search(r"GEMINI_API_KEY\s*=\s*(.+)", content, re.IGNORECASE)
if not m:
    m = re.search(r"gemini_api_key\s*=\s*(.+)", content, re.IGNORECASE)

key = m.group(1).strip().strip('"').strip("'") if m else ""
print(f"Key encontrada: {key[:12]}...")

r = httpx.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}", timeout=10)
data = r.json()

print("\n=== MODELOS GEMINI DISPONIBLES ===\n")
for model in data.get("models", []):
    name = model.get("name", "")
    display = model.get("displayName", "")
    methods = model.get("supportedGenerationMethods", [])
    if "generateContent" in methods:
        print(f"  {name:55s} | {display}")

print(f"\nTotal: {len(data.get('models', []))} modelos")

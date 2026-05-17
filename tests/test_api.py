import requests

try:
    resp = requests.get('http://localhost:8000/api/admin/credits/stats')
    print("Stats:", resp.status_code, resp.text[:100])
except Exception as e:
    print("Could not connect:", e)

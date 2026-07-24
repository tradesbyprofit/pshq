"""
github_setup.py — Creates your private GitHub repo, uploads every bot file,
sets the 4 secrets, and triggers the first scan run. Run once, then revoke the token.

ENV VARS (pass all at once):
  GH_USER            your GitHub username
  GH_TOKEN           a classic PAT with `repo` + `workflow` scopes (short expiry)
  OANDA_API_TOKEN    your (rotated) practice token -> stored as a secret
  OANDA_ACCOUNT_ID
  TG_BOT_TOKEN
  TG_CHAT_ID
  REPO               (optional) repo name, default "icc-bot"
"""
import os, base64, json, sys
import urllib.request, urllib.error
from pathlib import Path
from nacl import encoding, public

USER = os.environ["GH_USER"]
TOK  = os.environ["GH_TOKEN"]
REPO = os.environ.get("REPO", "icc-bot")
ROOT = Path(__file__).resolve().parent
API  = "https://api.github.com"

def gh(method, path, body=None, expect=200):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {TOK}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt else {})
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

# 1) create private repo
print(f"[1/4] Creating private repo {USER}/{REPO} ...")
code, r = gh("POST", "/user/repos", {"name": REPO, "private": True, "auto_init": False})
if code == 422:
    print("     repo already exists — continuing.")
elif code == 201:
    print(f"     created ✅  {r.get('html_url')}")
else:
    print(f"     ERROR {code}: {r}"); sys.exit(1)

# 2) upload every file (skip junk/secrets)
SKIP = {".git", "__pycache__", ".env", ".venv", "node_modules"}
print("[2/4] Uploading files ...")
files = [p for p in ROOT.rglob("*")
         if p.is_file()
         and not any(part in SKIP for part in p.parts)
         and not p.name.endswith(".pyc")]
for p in sorted(files):
    rel = p.relative_to(ROOT).as_posix()
    content = base64.b64encode(p.read_bytes()).decode()
    code, r = gh("PUT", f"/repos/{USER}/{REPO}/contents/{rel}",
                 {"message": f"add {rel}", "content": content, "branch": "main"})
    print(f"     {'ok' if code in (200,201) else 'warn '+str(code)} {rel}")

# 3) set secrets
print("[3/4] Setting secrets ...")
code, pk = gh("GET", f"/repos/{USER}/{REPO}/actions/secrets/public-key")
if code != 200:
    print(f"     public-key ERROR {code}: {pk}"); sys.exit(1)
pub = public.PublicKey(pk["key"].encode(), encoding.Base64Encoder())
box = public.SealedBox(pub)
for name, val in {"OANDA_API_TOKEN": os.environ.get("OANDA_API_TOKEN"),
                  "OANDA_ACCOUNT_ID": os.environ.get("OANDA_ACCOUNT_ID"),
                  "TG_BOT_TOKEN": os.environ.get("TG_BOT_TOKEN"),
                  "TG_CHAT_ID": os.environ.get("TG_CHAT_ID")}.items():
    if not val:
        print(f"     ⚠️ {name} not provided — skipping"); continue
    enc = box.encrypt(val.encode())
    code, r = gh("PUT", f"/repos/{USER}/{REPO}/actions/secrets/{name}",
                 {"encrypted_value": base64.b64encode(enc).decode(), "key_id": pk["key_id"]})
    print(f"     {'✅' if code in (201, 204) else '⚠️ '+str(code)} {name}")

# 4) trigger first run
print("[4/4] Triggering first scan ...")
code, r = gh("POST", f"/repos/{USER}/{REPO}/actions/workflows/scan.yml/dispatches",
             {"ref": "main"})
print(f"     {'✅ triggered — check Actions tab' if code in (200,204) else 'manual run available in Actions tab'}")
print(f"\n🎉 DONE. Repo: https://github.com/{USER}/{REPO}  |  Actions: https://github.com/{USER}/{REPO}/actions")
print("👉 NOW REVOKE the PAT (github.com → Settings → Developer settings → Tokens (classic) → Delete).")

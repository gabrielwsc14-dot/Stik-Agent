#!/usr/bin/env python3
"""Testa se o modelo da NVIDIA aceita imagem."""
import base64, json, os, subprocess, sys, urllib.request, urllib.error

CFG = os.path.join(os.path.expanduser("~"), ".config", "assistente", "config.json")
cfg = json.load(open(CFG, encoding="utf-8")) if os.path.exists(CFG) else {}
CHAVE = os.environ.get("NVIDIA_API_KEY") or cfg.get("chave", "")
MODELO = os.environ.get("MODELO") or cfg.get("modelo", "google/gemma-4-31b-it")
if not CHAVE:
    print("Sem chave. Defina NVIDIA_API_KEY ou rode o assistente uma vez.")
    sys.exit(1)

caminho = "/tmp/teste_visao.png"
sess = os.environ.get("XDG_SESSION_TYPE", "").lower()
tentativas = (
    [["grim", caminho], ["gnome-screenshot", "-f", caminho],
     ["spectacle", "-b", "-n", "-o", caminho]]
    if "wayland" in sess
    else [["scrot", "-o", caminho], ["import", "-window", "root", caminho],
          ["maim", caminho], ["gnome-screenshot", "-f", caminho],
          ["xfce4-screenshooter", "-f", "-s", "/tmp"]]
)
ok = False
for cmd in tentativas:
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=15)
        if os.path.exists(caminho) and os.path.getsize(caminho) > 0:
            print(f"Screenshot: {cmd[0]}")
            ok = True
            break
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        continue
if not ok:
    print("Nenhuma ferramenta de screenshot encontrada.")
    sys.exit(1)

with open(caminho, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

payload = {
    "model": MODELO,
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "Descreva em uma frase o que você vê nesta imagem."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ],
    }],
    "max_tokens": 120,
}
req = urllib.request.Request(
    "https://integrate.api.nvidia.com/v1/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Authorization": f"Bearer {CHAVE}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read())
    print("\n--- RESPOSTA ---")
    print(resp["choices"][0]["message"]["content"])
    print("\nOK: o modelo aceita imagem.")
except urllib.error.HTTPError as e:
    print(f"\nHTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:500]}")
    print("Provavelmente NAO aceita imagem.")
except Exception as e:
    print(f"\n{type(e).__name__}: {e}")

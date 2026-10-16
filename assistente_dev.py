#!/usr/bin/env python3
"""Assistente [DEV] — chat + agente + visão + voz + multi-provedor."""

import base64
import difflib
import http.client
import json
import mimetypes
import os
import queue
import re
import socket
import shutil
import subprocess
import threading
import time
import tkinter as tk
import urllib.parse
import uuid
import webbrowser
from contextlib import contextmanager
from tkinter import filedialog, font as tkfont, messagebox, simpledialog

try:
    import speech_recognition as sr
    TEM_STT = True
except ImportError:
    TEM_STT = False
try:
    import pyttsx3
    TEM_TTS = True
except ImportError:
    TEM_TTS = False

PROVIDERS = {
    "nvidia": {
        "nome": "NVIDIA (build.nvidia.com)",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "chave_env": "NVIDIA_API_KEY",
        "modelo_padrao": "google/gemma-4-31b-it",
        "formato": "openai", "visao": True,
        "como_obter": "https://build.nvidia.com",
        "prefixo": "nvapi-",
    },
    "google": {
        "nome": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "chave_env": "GEMINI_API_KEY",
        "modelo_padrao": "gemini-2.0-flash",
        "formato": "openai", "visao": True,
        "como_obter": "https://aistudio.google.com/apikey",
        "prefixo": "AIza",
    },
    "openai": {
        "nome": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "chave_env": "OPENAI_API_KEY",
        "modelo_padrao": "gpt-4o-mini",
        "formato": "openai", "visao": True,
        "como_obter": "https://platform.openai.com/api-keys",
        "prefixo": "sk-",
    },
    "anthropic": {
        "nome": "Anthropic Claude",
        "base_url": "https://api.anthropic.com/v1",
        "chave_env": "ANTHROPIC_API_KEY",
        "modelo_padrao": "claude-3-5-sonnet-latest",
        "formato": "anthropic", "visao": True,
        "como_obter": "https://console.anthropic.com/settings/keys",
        "prefixo": "sk-ant-",
    },
    "groq": {
        "nome": "Groq (rápido e barato)",
        "base_url": "https://api.groq.com/openai/v1",
        "chave_env": "GROQ_API_KEY",
        "modelo_padrao": "llama-3.3-70b-versatile",
        "formato": "openai", "visao": False,
        "como_obter": "https://console.groq.com/keys",
        "prefixo": "gsk_",
    },
    "deepseek": {
        "nome": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "chave_env": "DEEPSEEK_API_KEY",
        "modelo_padrao": "deepseek-chat",
        "formato": "openai", "visao": False,
        "como_obter": "https://platform.deepseek.com/api_keys",
        "prefixo": "sk-",
    },
    "openrouter": {
        "nome": "OpenRouter (acesso a vários modelos)",
        "base_url": "https://openrouter.ai/api/v1",
        "chave_env": "OPENROUTER_API_KEY",
        "modelo_padrao": "google/gemini-2.0-flash-001",
        "formato": "openai", "visao": True,
        "como_obter": "https://openrouter.ai/keys",
        "prefixo": "sk-or-",
    },
    "ollama": {
        "nome": "Ollama (local, sem chave)",
        "base_url": "http://localhost:11434/v1",
        "chave_env": "OLLAMA_API_KEY",
        "modelo_padrao": "llama3.2",
        "formato": "openai", "visao": False,
        "como_obter": "https://ollama.com — instale e rode 'ollama serve'",
        "prefixo": "",
    },
}

HOME = os.path.expanduser("~")
CONFIG = os.path.join(HOME, ".config", "assistente", "config.json")
DADOS = os.path.join(HOME, ".local", "share", "assistente")
ARQ_PERSONALIDADE = os.path.join(DADOS, "personalidade.txt")
ARQ_MEMORIA = os.path.join(DADOS, "memoria.json")
ARQ_LOG = os.path.join(DADOS, "agente.log")
PASTA_CHATS = os.path.join(DADOS, "chats")
SOCKET = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "assistente-dev.sock")

TITULO_SESSAO = "Sessão atual (não salva)"
TITULO_NOVO = "Novo chat"
MAX_SAIDA = 8000
MAX_ANEXO_TEXTO = 80_000
MAX_ANEXO_IMAGEM = 6_000_000

PROMPT_BASE = (
    "Você é um assistente rápido que fica a um atalho de teclado de distância, "
    "num computador Linux. Responda em português, de forma curta e direta. "
    "Quando mostrar comandos ou código, SEMPRE use blocos de código markdown com três "
    "crases e o nome da linguagem (```bash, ```python...), para o usuário poder copiar."
)
PERSONALIDADE_PADRAO = (
    "Amigável, direto e sem enrolação. Explica o essencial e só se aprofunda "
    "quando o usuário pedir."
)
INSTRUCAO_AGENTE = (
    "Você é um agente no computador do usuário (Linux) e PODE agir no sistema. "
    "Para pedir uma ação, emita UM bloco de código na linguagem 'agente' com um "
    "objeto JSON, e nada depois dele. O aplicativo executa (comandos seguros rodam "
    "direto; os demais pedem aprovação) e devolve o resultado na próxima mensagem.\n"
    "```agente\n"
    '{"acao": "executar", "comando": "ls -la ~/Downloads", "motivo": "listar"}\n'
    "```\n"
    "Ações:\n"
    '  {"acao":"executar","comando":"...","sudo":false}\n'
    '  {"acao":"ler","caminho":"..."}\n'
    '  {"acao":"listar","caminho":"..."}\n'
    '  {"acao":"editar","caminho":"...","conteudo":"...","modo":"criar|substituir|append"}\n'
    '  {"acao":"abrir","alvo":"firefox"}  ou  {"acao":"abrir","caminho":"/x.pdf"}\n'
    '  {"acao":"ver_tela"}   # tira um screenshot e envia a imagem pra você olhar\n'
    "Regras: UM bloco 'agente' por resposta, sempre no final. Espere o resultado. "
    "Leitura e comandos de consulta são livres; alterações e sudo pedem aprovação. "
    "Nunca invente saída. Use ver_tela quando precisar saber o que está na tela."
)

CATEGORIAS = {
    "estilo": "Estilo de resposta (tom, tamanho, formato)",
    "tecnico": "Preferências técnicas (linguagens, ferramentas, nível)",
    "projetos": "Projetos em que estou trabalhando",
}
INSTRUCAO_APRENDER = (
    "Se, e somente se, a conversa revelar uma preferência DURÁVEL do usuário dentro destas "
    "categorias permitidas: {cats}, termine a resposta com uma última linha no formato "
    "[[LEMBRAR: frase curta]]. É só uma sugestão. Nunca sugira dados pessoais, senhas, "
    "chaves, saúde, finanças ou qualquer coisa fora das categorias."
)

RE_LEMBRAR = re.compile(r"\[\[\s*LEMBRAR\s*:\s*(.+?)\s*\]\]", re.I | re.S)
RE_CERCA = re.compile(r"^(`{3,})[ \t]*([^\n`]*)\n(.*?)(?:^\1`*[ \t]*$|\Z)", re.S | re.M)
RE_INLINE = re.compile(r"(\*\*[^*\n]+\*\*|`[^`\n]+`|(?<!\*)\*[^*\s][^*\n]*\*(?!\*))")
RE_AGENTE = re.compile(r"^(`{3,})[ \t]*agente[ \t]*\n(.*?)\n\1`*[ \t]*$", re.S | re.M)

COMANDOS_LIVRES = {
    "ls", "cat", "head", "tail", "wc", "file", "stat", "find", "grep", "rg", "tree",
    "pwd", "echo", "printf", "env", "printenv", "which", "whereis", "type",
    "ps", "top", "htop", "btop", "pstree", "pidof", "pgrep",
    "df", "du", "free", "uptime", "uname", "hostname", "whoami", "id", "groups",
    "lsblk", "lscpu", "lsusb", "lspci", "lsof", "date", "cal",
    "ss", "netstat", "ip", "ifconfig", "ping", "traceroute", "dig", "nslookup", "host",
    "journalctl", "dmesg",
    "xdg-open", "gtk-launch", "gio", "notify-send",
    "pkill", "killall",
    "less", "more", "man", "info", "whatis", "apropos",
    "neofetch", "fastfetch",
    "git", "systemctl", "pip", "pip3", "npm", "yarn", "snap", "apt", "apt-get",
    "docker", "podman",
}
SUBCMD_LIVRES = {
    "git": {"status", "log", "diff", "show", "branch", "remote", "tag", "describe",
            "rev-parse", "ls-files", "blame", "shortlog"},
    "systemctl": {"status", "list-units", "list-unit-files", "show", "is-active",
                  "is-enabled", "cat"},
    "pip": {"list", "show", "freeze", "check"},
    "pip3": {"list", "show", "freeze", "check"},
    "npm": {"list", "ls", "view", "show", "outdated"},
    "yarn": {"list", "info", "why"},
    "snap": {"list", "info"},
    "apt": {"list", "search", "show", "policy"},
    "apt-get": set(),
    "docker": {"ps", "images", "logs", "inspect", "version", "info"},
    "podman": {"ps", "images", "logs", "inspect", "version", "info"},
}
PADROES_ESCRITA = [
    r">", r"\brm\b", r"\bmv\b", r"\bcp\b", r"\bmkdir\b", r"\brmdir\b", r"\btouch\b",
    r"\bln\b", r"\btruncate\b", r"\btee\b", r"\bdd\b", r"\bshred\b",
    r"\bchmod\b", r"\bchown\b", r"\bchgrp\b",
    r"\bsed\s+-i\b", r"\bperl\s+-i\b",
    r"\bapt(-get)?\s+(install|remove|purge|update|upgrade|autoremove)\b",
    r"\bdnf\s+(install|remove|update|upgrade)\b",
    r"\bpacman\s+-(S|R|U)\b",
    r"\bsnap\s+(install|remove|refresh)\b",
    r"\bpip3?\s+install\b", r"\bnpm\s+(install|uninstall|update)\b",
    r"\byarn\s+(add|remove)\b", r"\bsudo\b",
    r"\bsystemctl\s+(start|stop|restart|reload|enable|disable|mask|unmask)\b",
]
PADROES_PERIGOSOS = [
    r"\brm\s+-rf\s+/", r"\brm\s+-rf\s+~", r"\brm\s+-rf\s+/\*",
    r"\bmkfs(\.\w+)?\b", r"\bdd\s+if=.*of=/dev/", r">\s*/dev/sd",
    r":\(\)\s*\{.*\};\s*:", r"\bchmod\s+-R\s+777\s+/", r"\bchown\s+-R\s+\S+\s+/",
    r"\bwipefs\b", r"\bshred\s+/dev/",
]
RE_PERIGOSO = re.compile("|".join(PADROES_PERIGOSOS))
ACOES_VALIDAS = {"executar", "ler", "listar", "editar", "abrir", "ver_tela"}

AJUDA = (
    "Comandos: /lembrar · /memoria · /esquecer <n> · /personalidade · /provedor [id] · "
    "/modelo [id] · /agente · /fixo · /ver · /tempo_real [s] · /falar · /escutar · "
    "/salvar [nome] · /limpar · /ajuda\n"
    "Atalhos: Enter envia · Shift+Enter nova linha · Ctrl+N novo chat · Ctrl+B barra · "
    "Ctrl+L limpa · Ctrl+M microfone · Ctrl+Shift+S ler resposta · Esc esconde\n"
    "Anexos: anexar arquivos · capturar tela · ver tela · falar · voz."
)

FUNDO = "#1e1e2e"; FUNDO_CAIXA = "#2a2a3d"; FUNDO_CODIGO = "#11111b"
CABECALHO_CODIGO = "#181825"; BORDA = "#45475a"; TEXTO = "#cdd6f4"; CINZA = "#7f849c"
DESTAQUE = "#89b4fa"; VERDE = "#a6e3a1"; VERMELHO = "#f38ba8"; LARANJA = "#fab387"


def _ler_json(caminho, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def _gravar(caminho, conteudo):
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
    os.chmod(tmp, 0o600)
    os.replace(tmp, caminho)


def _gravar_json(caminho, dados):
    _gravar(caminho, json.dumps(dados, ensure_ascii=False, indent=2))


def detectar_provider(chave):
    if not chave:
        return "ollama"
    for p in ("anthropic", "openrouter", "nvidia", "google", "groq"):
        pref = PROVIDERS[p]["prefixo"]
        if pref and chave.startswith(pref):
            return p
    if chave.startswith("sk-"):
        return "openai"
    return None


def carregar_config():
    cfg = {"provider": "nvidia", "chaves": {}, "modelos": {}, "extra": {},
           "lateral": True, "aprender": False, "categorias": list(CATEGORIAS),
           "agente_ativo": True, "agente_max_passos": 5,
           "fixo": True, "tempo_real_segundos": 0, "auto_falar": False,
           "stt_idioma": "pt-BR"}
    d = _ler_json(CONFIG, {})
    if isinstance(d, dict):
        if isinstance(d.get("chave"), str) and not d.get("chaves"):
            cfg["chaves"]["nvidia"] = d["chave"]
            if isinstance(d.get("modelo"), str):
                cfg["modelos"]["nvidia"] = d["modelo"]
        if isinstance(d.get("chaves"), dict):
            cfg["chaves"] = {k: v for k, v in d["chaves"].items()
                             if k in PROVIDERS and isinstance(v, str)}
        if isinstance(d.get("modelos"), dict):
            cfg["modelos"] = {k: v for k, v in d["modelos"].items()
                              if k in PROVIDERS and isinstance(v, str)}
        if d.get("provider") in PROVIDERS:
            cfg["provider"] = d["provider"]
        if isinstance(d.get("extra"), dict): cfg["extra"] = d["extra"]
        cfg["lateral"] = bool(d.get("lateral", True))
        cfg["aprender"] = bool(d.get("aprender", False))
        if isinstance(d.get("categorias"), list):
            cfg["categorias"] = [c for c in d["categorias"] if c in CATEGORIAS]
        cfg["agente_ativo"] = bool(d.get("agente_ativo", True))
        cfg["fixo"] = bool(d.get("fixo", True))
        cfg["auto_falar"] = bool(d.get("auto_falar", False))
        cfg["stt_idioma"] = d.get("stt_idioma") or "pt-BR"
        try:
            cfg["tempo_real_segundos"] = max(0, min(300, int(d.get("tempo_real_segundos", 0))))
        except (TypeError, ValueError): cfg["tempo_real_segundos"] = 0
        try: cfg["agente_max_passos"] = max(1, min(20, int(d.get("agente_max_passos", 5))))
        except (TypeError, ValueError): cfg["agente_max_passos"] = 5
    for k, info in PROVIDERS.items():
        if not cfg["chaves"].get(k):
            env = os.environ.get(info["chave_env"])
            if env:
                cfg["chaves"][k] = env
    return cfg


def salvar_config(**mudancas):
    d = _ler_json(CONFIG, {})
    if not isinstance(d, dict): d = {}
    d.update(mudancas)
    _gravar_json(CONFIG, d)


def ler_personalidade():
    try:
        with open(ARQ_PERSONALIDADE, encoding="utf-8") as f: return f.read()
    except OSError: return PERSONALIDADE_PADRAO


def salvar_personalidade(texto): _gravar(ARQ_PERSONALIDADE, texto.strip() + "\n")


def log_agente(msg):
    try:
        os.makedirs(DADOS, exist_ok=True)
        with open(ARQ_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError: pass


class Memoria:
    def __init__(self):
        itens = _ler_json(ARQ_MEMORIA, [])
        self.itens = ([i for i in itens if isinstance(i, dict) and i.get("texto")]
                      if isinstance(itens, list) else [])
    def salvar(self): _gravar_json(ARQ_MEMORIA, self.itens)
    def adicionar(self, texto):
        self.itens.append({"texto": texto.strip(), "criado": time.time()}); self.salvar()
    def remover(self, n):
        item = self.itens.pop(n - 1); self.salvar(); return item


class Chats:
    def __init__(self):
        self.cache = {}
        self._sessao_arquivo = os.path.join(PASTA_CHATS, "_sessao.json")
        try: nomes = os.listdir(PASTA_CHATS)
        except OSError: nomes = []
        for nome in nomes:
            if not nome.endswith(".json") or nome == "_sessao.json": continue
            c = _ler_json(os.path.join(PASTA_CHATS, nome), None)
            if isinstance(c, dict) and isinstance(c.get("mensagens"), list):
                c["id"] = nome[:-5]
                c.setdefault("titulo", "Chat sem nome")
                c.setdefault("atualizado", 0)
                self.cache[c["id"]] = c
    def _arquivo(self, id_): return os.path.join(PASTA_CHATS, id_ + ".json")
    def criar(self, titulo, mensagens=None):
        agora = time.time()
        c = {"id": uuid.uuid4().hex[:12], "titulo": titulo, "criado": agora,
             "atualizado": agora, "mensagens": list(mensagens or [])}
        self.cache[c["id"]] = c; self.salvar(c); return c
    def salvar(self, c):
        c["atualizado"] = time.time()
        _gravar_json(self._arquivo(c["id"]), c)
    def excluir(self, id_):
        self.cache.pop(id_, None)
        try: os.remove(self._arquivo(id_))
        except OSError: pass
    def buscar(self, termo=""):
        todos = sorted(self.cache.values(), key=lambda c: c.get("atualizado", 0), reverse=True)
        termo = termo.strip().lower()
        if not termo: return todos
        return [c for c in todos if termo in c["titulo"].lower()
                or any(termo in str(m.get("content", "")).lower() for m in c["mensagens"])]
    def salvar_sessao(self, mensagens):
        if not mensagens:
            try: os.remove(self._sessao_arquivo)
            except OSError: pass
            return
        _gravar_json(self._sessao_arquivo, {"mensagens": mensagens,
                                            "atualizado": time.time()})
    def carregar_sessao(self):
        d = _ler_json(self._sessao_arquivo, None)
        if isinstance(d, dict) and isinstance(d.get("mensagens"), list):
            return d["mensagens"]
        return []


def limitar_historico(mensagens, max_msgs=20, max_chars=24000):
    recorte = mensagens[-max_msgs:]
    while len(recorte) > 1 and sum(len(m["content"]) for m in recorte) > max_chars:
        recorte = recorte[1:]
    return recorte


def comando_e_seguro(cmd):
    cmd = cmd.strip()
    if not cmd: return False
    partes = re.split(r"\s*(?:\|\||&&|\||;)\s*", cmd)
    for p in partes:
        p = p.strip()
        if not p: continue
        for pat in PADROES_ESCRITA:
            if re.search(pat, p): return False
        primeira = p.split()[0]
        if primeira not in COMANDOS_LIVRES: return False
        if primeira in SUBCMD_LIVRES:
            pedacos = p.split()
            if len(pedacos) < 2 or pedacos[1] not in SUBCMD_LIVRES[primeira]:
                return False
    return True


def _captura_xfce(caminho):
    pasta = os.path.dirname(caminho) or "/tmp"
    antes = set(os.listdir(pasta))
    try:
        subprocess.run(["xfce4-screenshooter", "-f", "-s", pasta],
                       check=True, capture_output=True, timeout=15)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    novos = [f for f in (set(os.listdir(pasta)) - antes) if f.lower().endswith(".png")]
    if not novos: return False
    origem = os.path.join(pasta, max(novos,
        key=lambda f: os.path.getmtime(os.path.join(pasta, f))))
    try:
        if os.path.exists(caminho): os.remove(caminho)
        os.replace(origem, caminho); return True
    except OSError: return False


def capturar_tela():
    caminho = "/tmp/assistente_screenshot.png"
    sess = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if "wayland" in sess:
        tentativas = [["grim", caminho], ["gnome-screenshot", "-f", caminho],
                      ["spectacle", "-b", "-n", "-o", caminho]]
    else:
        tentativas = [["scrot", "-o", caminho], ["import", "-window", "root", caminho],
                      ["maim", caminho], ["gnome-screenshot", "-f", caminho],
                      ["mate-screenshot", "-f", caminho],
                      ["spectacle", "-b", "-n", "-o", caminho]]
    for cmd in tentativas:
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=15)
            if os.path.exists(caminho) and os.path.getsize(caminho) > 0:
                return caminho
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    if _captura_xfce(caminho): return caminho
    return None


def ler_arquivo_para_anexo(caminho):
    try: tam = os.path.getsize(caminho)
    except OSError: return None
    nome = os.path.basename(caminho)
    if tam == 0:
        return {"tipo": "texto", "nome": nome, "conteudo": "", "tamanho": 0}
    if tam <= MAX_ANEXO_TEXTO:
        try:
            with open(caminho, encoding="utf-8") as f:
                return {"tipo": "texto", "nome": nome, "conteudo": f.read(), "tamanho": tam}
        except (UnicodeDecodeError, OSError): pass
    mime, _ = mimetypes.guess_type(nome)
    if mime and mime.startswith("image/") and tam <= MAX_ANEXO_IMAGEM:
        try:
            with open(caminho, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return {"tipo": "imagem", "nome": nome, "b64": b64,
                    "mime": mime, "tamanho": tam}
        except OSError: pass
    return {"tipo": "binario", "nome": nome, "tamanho": tam}


def escolher_arquivos(titulo="Escolha arquivos"):
    if shutil.which("zenity"):
        try:
            r = subprocess.run(
                ["zenity", "--file-selection", "--multiple",
                 "--separator=\n", f"--title={titulo}"],
                capture_output=True, text=True, timeout=300)
            if r.returncode == 0 and r.stdout.strip():
                return [c for c in r.stdout.strip().split("\n") if c]
            return []
        except (subprocess.TimeoutExpired, OSError): pass
    return list(filedialog.askopenfilenames(title=titulo))


def _captura_do_buffer(max_idade=5.0):
    caminho = "/tmp/assistente_ultimo.png"
    try:
        if os.path.exists(caminho) and (time.time() - os.path.getmtime(caminho)) <= max_idade:
            return caminho
    except OSError: pass
    return None


def _exec_ver_tela(cfg=None):
    if cfg and not PROVIDERS.get(cfg.get("provider", ""), {}).get("visao", False):
        return {"ok": False,
                "erro": f"o provedor ativo ({cfg.get('provider')}) não aceita imagem"}
    max_idade = 5.0
    if cfg:
        intervalo = int(cfg.get("tempo_real_segundos", 0))
        if intervalo > 0:
            max_idade = max(5.0, intervalo * 1.5)
    caminho = _captura_do_buffer(max_idade) or capturar_tela()
    if not caminho:
        return {"ok": False, "erro": "não consegui capturar a tela"}
    a = ler_arquivo_para_anexo(caminho)
    if not a or a["tipo"] != "imagem":
        return {"ok": False, "erro": "captura falhou ou não é imagem"}
    return {"ok": True, "saida": "screenshot anexado à conversa",
            "imagem": {"b64": a["b64"], "mime": a["mime"], "nome": "screenshot.png"}}


def validar_acao(d):
    if not isinstance(d, dict): return False, "JSON não é objeto"
    acao = d.get("acao")
    if acao not in ACOES_VALIDAS: return False, f"ação inválida: {acao!r}"
    if acao == "executar":
        if not isinstance(d.get("comando"), str) or not d["comando"].strip():
            return False, "'comando' vazio"
    elif acao in ("ler", "listar"):
        if not isinstance(d.get("caminho"), str) or not d["caminho"].strip():
            return False, "'caminho' vazio"
    elif acao == "editar":
        for c in ("caminho", "conteudo"):
            if not isinstance(d.get(c), str): return False, f"campo {c!r} faltando"
        if d.get("modo", "substituir") not in ("criar", "substituir", "append"):
            return False, f"modo inválido: {d.get('modo')!r}"
    elif acao == "abrir":
        if not (d.get("alvo") or d.get("caminho")): return False, "sem 'alvo'/'caminho'"
    return True, None


def resumo_acao(d):
    a = d.get("acao")
    if a == "executar": return f"executar: {d.get('comando','')}"
    if a == "ler":      return f"ler: {d.get('caminho','')}"
    if a == "listar":   return f"listar: {d.get('caminho','')}"
    if a == "editar":   return f"editar: {d.get('caminho','')} ({d.get('modo','substituir')})"
    if a == "abrir":    return f"abrir: {d.get('alvo') or d.get('caminho')}"
    if a == "ver_tela": return "ver tela (screenshot)"
    return str(d)


def diff_texto(antigo, novo, nome="arquivo"):
    linhas = difflib.unified_diff(antigo.splitlines(keepends=True),
                                  novo.splitlines(keepends=True),
                                  fromfile=f"a/{nome}", tofile=f"b/{nome}")
    return "".join(linhas)[:MAX_SAIDA]


def executar_acao(d, senha_sudo=None, cfg=None):
    a = d.get("acao")
    try:
        if a == "executar": return _exec_comando(d["comando"], bool(d.get("sudo")), senha_sudo)
        if a == "ler":
            caminho = os.path.expanduser(d["caminho"])
            with open(caminho, encoding="utf-8", errors="replace") as f:
                return {"ok": True, "saida": f.read()[:MAX_SAIDA]}
        if a == "listar":
            caminho = os.path.expanduser(d["caminho"])
            linhas = []
            for n in sorted(os.listdir(caminho)):
                p = os.path.join(caminho, n)
                try:
                    st = os.stat(p)
                    tipo = "d" if os.path.isdir(p) else ("l" if os.path.islink(p) else "-")
                    linhas.append(f"{tipo} {st.st_size:>10}  {n}")
                except OSError:
                    linhas.append(f"? {'':>10}  {n}")
            return {"ok": True, "saida": "\n".join(linhas)[:MAX_SAIDA] or "(vazio)"}
        if a == "editar": return _exec_editar(d)
        if a == "abrir": return _exec_abrir(d)
        if a == "ver_tela": return _exec_ver_tela(cfg)
    except Exception as e:
        return {"ok": False, "erro": f"{type(e).__name__}: {e}"}
    return {"ok": False, "erro": f"ação desconhecida: {a!r}"}


def _exec_comando(comando, usar_sudo, senha_sudo):
    if usar_sudo or comando.strip().startswith("sudo "):
        if not senha_sudo:
            return {"ok": False, "erro": "sudo pediu senha, mas nenhuma foi informada"}
        proc = subprocess.run(["sudo", "-S", "-p", "", "bash", "-lc", comando],
                              input=senha_sudo + "\n", text=True,
                              capture_output=True, timeout=180)
    else:
        proc = subprocess.run(["bash", "-lc", comando], text=True,
                              capture_output=True, timeout=180)
    return {"ok": proc.returncode == 0,
            "saida": (proc.stdout or "")[:MAX_SAIDA],
            "erro": (proc.stderr or "")[:MAX_SAIDA],
            "codigo": proc.returncode}


def _exec_editar(d):
    caminho = os.path.expanduser(d["caminho"])
    modo = d.get("modo", "substituir"); conteudo = d["conteudo"]
    antigo = ""
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8", errors="replace") as f:
            antigo = f.read()
    if modo == "criar":
        if os.path.exists(caminho): return {"ok": False, "erro": f"já existe: {caminho}"}
        novo = conteudo
    elif modo == "append": novo = antigo + conteudo
    else: novo = conteudo
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    tmp = caminho + ".tmp-agente"
    with open(tmp, "w", encoding="utf-8") as f: f.write(novo)
    os.chmod(tmp, 0o644); os.replace(tmp, caminho)
    return {"ok": True, "saida": f"arquivo gravado: {caminho} ({len(novo)} caracteres)"}


def _exec_abrir(d):
    alvo = d.get("alvo")
    if alvo:
        for cmd in (["gtk-launch", alvo], ["xdg-open", alvo]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {"ok": True, "saida": f"abrindo {alvo}"}
            except FileNotFoundError: continue
        return {"ok": False, "erro": f"não consegui abrir {alvo!r}"}
    caminho = os.path.expanduser(d["caminho"])
    try:
        subprocess.Popen(["xdg-open", caminho], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return {"ok": True, "saida": f"abrindo {caminho}"}
    except FileNotFoundError:
        return {"ok": False, "erro": "xdg-open não encontrado"}


def _openai_msg_para_anthropic(msg):
    role = msg["role"]
    if role == "tool": role = "user"
    conteudo = msg["content"]
    if isinstance(conteudo, str):
        return {"role": role, "content": conteudo}
    partes = []
    for p in conteudo:
        if p.get("type") == "text":
            partes.append({"type": "text", "text": p.get("text", "")})
        elif p.get("type") == "image_url":
            url = p.get("image_url", {}).get("url", "")
            if url.startswith("data:"):
                cabec, b64 = url.split(",", 1)
                mime = cabec.split(";")[0].replace("data:", "")
                partes.append({"type": "image",
                               "source": {"type": "base64", "media_type": mime, "data": b64}})
    return {"role": role, "content": partes}


def _montar_anthropic(mensagens, modelo, extra):
    sistema = ""; resto = []
    for m in mensagens:
        if m["role"] == "system":
            sistema = (sistema + "\n\n" + m["content"]).strip() if sistema else m["content"]
        else:
            resto.append(_openai_msg_para_anthropic(m))
    corpo = {"model": modelo, "max_tokens": 1024, "messages": resto,
             "stream": True, "temperature": 0.5}
    if sistema: corpo["system"] = sistema
    corpo.update(extra)
    return corpo


class Cliente:
    def __init__(self): self.conn = None; self.trava = threading.Lock()
    @staticmethod
    def _nova(partes):
        cls = http.client.HTTPSConnection if partes.scheme == "https" else http.client.HTTPConnection
        return cls(partes.netloc, timeout=60)
    def fechar(self):
        if self.conn is not None:
            try: self.conn.close()
            except OSError: pass
        self.conn = None
    def aquecer(self, url):
        try:
            partes = urllib.parse.urlsplit(url)
            with self.trava:
                if self.conn is None: self.conn = self._nova(partes)
                if self.conn.sock is None: self.conn.connect()
        except (OSError, http.client.HTTPException): self.fechar()
    def abrir(self, url, cabecalhos, corpo):
        partes = urllib.parse.urlsplit(url)
        caminho = partes.path + (("?" + partes.query) if partes.query else "")
        novo_host = partes.netloc
        with self.trava:
            if self.conn is not None and getattr(self.conn, "host", None) != novo_host:
                self.fechar()
            for _ in range(2):
                reuso = self.conn is not None and self.conn.sock is not None
                if self.conn is None: self.conn = self._nova(partes)
                try:
                    self.conn.request("POST", caminho, body=corpo, headers=cabecalhos)
                    return self.conn.getresponse()
                except (http.client.HTTPException, OSError):
                    self.fechar()
                    if not reuso: raise


class App:
    def __init__(self):
        self.cfg = carregar_config()
        self.memoria = Memoria(); self.chats = Chats(); self.cliente = Cliente()
        self.fila = queue.Queue()
        self.ocupado = False; self.resposta = ""; self._mostrado = 0
        self.blocos = []; self.janelas = []; self.anexos = []
        self.sessao = {"id": None, "titulo": TITULO_SESSAO,
                       "mensagens": self.chats.carregar_sessao()}
        self.atual = self.sessao
        self.itens_lista = []; self._silencio_lista = False
        self.t_inicio = 0.0; self.t_primeira = 0.0
        self.n_trechos = 0; self.n_raciocinio = 0
        self.janela_cfg = None; self.agente_passos = 0
        self._parar_tempo_real = threading.Event()
        self._falando = False; self._escutando = False

        self.root = tk.Tk()
        self.root.title("Stik Agent")
        self.root.configure(bg=FUNDO)
        self.root.attributes("-topmost", self.cfg.get("fixo", True))
        largura, altura = 980, 640
        x = (self.root.winfo_screenwidth() - largura) // 2
        y = self.root.winfo_screenheight() // 8
        self.root.geometry(f"{largura}x{altura}+{x}+{y}")
        self.root.minsize(560, 400)

        if not self.obter_chave() and self.cfg["provider"] != "ollama":
            self.root.withdraw()
            self._pedir_chave_inicial()

        self.montar_interface()
        self.root.protocol("WM_DELETE_WINDOW", self.esconder)
        self.root.bind("<Escape>", lambda e: self.esconder())
        atalhos = {"<Control-l>": self.limpar, "<Control-b>": self.alternar_lateral,
                   "<Control-n>": self.novo_chat, "<Control-m>": self.escutar_voz,
                   "<Control-Shift-S>": self.falar_ultima}
        for seq, func in atalhos.items():
            for w in (self.root, self.entrada):
                w.bind(seq, lambda e, f=func: (f(), "break")[1])
        self.atualizar_lista(); self.render_historico()
        self.root.after(50, self.processar_fila)
        self.root.after(200, self._tic)
        self.mostrar()

    def _pedir_chave_inicial(self):
        msg = ("Cole sua chave de API.\n\n"
               "O prefixo identifica o provedor:\n"
               "  nvapi-    -> NVIDIA\n"
               "  AIza      -> Google Gemini\n"
               "  sk-ant-   -> Anthropic Claude\n"
               "  sk-or-    -> OpenRouter\n"
               "  gsk_      -> Groq\n"
               "  sk-       -> OpenAI / DeepSeek\n"
               "  (vazio)   -> Ollama local\n\n"
               "Chave:")
        chave = simpledialog.askstring("Stik Agent", msg, parent=self.root)
        if not chave or not chave.strip(): return
        chave = chave.strip()
        prov = detectar_provider(chave)
        if prov is None:
            lista = "\n".join(f"  {k}  ({v['nome']})" for k, v in PROVIDERS.items())
            prov = simpledialog.askstring("Stik Agent",
                f"Não reconheci o prefixo. Digite o provedor:\n\n{lista}",
                initialvalue="nvidia", parent=self.root)
            prov = (prov or "nvidia").strip().lower()
        if prov not in PROVIDERS: prov = "nvidia"
        self.cfg["provider"] = prov
        self.cfg["chaves"][prov] = chave
        self.cfg["modelos"].setdefault(prov, PROVIDERS[prov]["modelo_padrao"])
        salvar_config(provider=prov, chaves=self.cfg["chaves"],
                      modelos=self.cfg["modelos"])

    def obter_chave(self):
        return self.cfg["chaves"].get(self.cfg["provider"], "")
    def obter_modelo(self):
        p = self.cfg["provider"]
        return self.cfg["modelos"].get(p) or PROVIDERS[p]["modelo_padrao"]
    def obter_url(self):
        p = self.cfg["provider"]
        base = PROVIDERS[p]["base_url"].rstrip("/")
        return base + ("/messages" if PROVIDERS[p]["formato"] == "anthropic"
                       else "/chat/completions")

    def _botao(self, pai, texto, comando, destaque=False):
        return tk.Button(pai, text=texto, command=comando, relief="flat", bd=0,
            cursor="hand2", bg=DESTAQUE if destaque else BORDA,
            fg=FUNDO if destaque else TEXTO, activebackground=TEXTO, activeforeground=FUNDO,
            padx=10, pady=4, font=("DejaVu Sans", 9, "bold" if destaque else "normal"),
            highlightthickness=0)

    def montar_interface(self):
        self.f_ui = ("DejaVu Sans", 11)
        self.f_mono = tkfont.Font(family="DejaVu Sans Mono", size=10)
        topo = tk.Frame(self.root, bg=FUNDO); topo.pack(fill="x", padx=12, pady=(10, 6))
        self._botao(topo, "☰  Chats", self.alternar_lateral).pack(side="left")
        self.lbl_titulo = tk.Label(topo, text="", bg=FUNDO, fg=TEXTO, anchor="w",
                                   font=("DejaVu Sans", 11, "bold"))
        self.lbl_titulo.pack(side="left", padx=12, fill="x", expand=True)
        self.btn_pers = self._botao(topo, "⚙  Configurações", self.abrir_config)
        self.btn_pers.pack(side="right")
        self.btn_salvar = self._botao(topo, "Salvar como chat", self.salvar_sessao)

        self.corpo = tk.Frame(self.root, bg=FUNDO)
        self.corpo.pack(fill="both", expand=True, padx=12)

        self.lateral = tk.Frame(self.corpo, bg=FUNDO_CAIXA, width=230)
        self.lateral.pack_propagate(False)
        self._botao(self.lateral, "+  Novo chat", self.novo_chat, destaque=True).pack(
            fill="x", padx=8, pady=(8, 6))
        tk.Label(self.lateral, text="Buscar chats", bg=FUNDO_CAIXA, fg=CINZA,
                 font=("DejaVu Sans", 8), anchor="w").pack(fill="x", padx=10)
        self.var_busca = tk.StringVar()
        self.var_busca.trace_add("write", lambda *a: self.atualizar_lista())
        self.busca = tk.Entry(self.lateral, textvariable=self.var_busca, bg=FUNDO, fg=TEXTO,
                              bd=0, insertbackground=TEXTO, highlightthickness=1,
                              highlightbackground=BORDA, highlightcolor=DESTAQUE,
                              font=("DejaVu Sans", 10))
        self.busca.pack(fill="x", padx=8, pady=(2, 6), ipady=4)
        quadro_lista = tk.Frame(self.lateral, bg=FUNDO_CAIXA)
        quadro_lista.pack(fill="both", expand=True, padx=8)
        sb = tk.Scrollbar(quadro_lista); sb.pack(side="right", fill="y")
        self.lista = tk.Listbox(quadro_lista, bg=FUNDO_CAIXA, fg=TEXTO,
            selectbackground=BORDA, selectforeground=TEXTO, activestyle="none", bd=0,
            highlightthickness=0, exportselection=False, font=("DejaVu Sans", 10),
            yscrollcommand=sb.set)
        self.lista.pack(side="left", fill="both", expand=True)
        sb.config(command=self.lista.yview)
        self.lista.bind("<<ListboxSelect>>", self._ao_selecionar)
        self.lista.bind("<Button-3>", self._menu_contexto)
        self.lista.bind("<Double-Button-1>", lambda e: self.renomear_chat())
        self.lista.bind("<F2>", lambda e: self.renomear_chat())
        linha_btn = tk.Frame(self.lateral, bg=FUNDO_CAIXA)
        linha_btn.pack(fill="x", padx=8, pady=8)
        self._botao(linha_btn, "Renomear", self.renomear_chat).pack(
            side="left", expand=True, fill="x")
        self._botao(linha_btn, "Excluir", self.excluir_chat).pack(
            side="left", expand=True, fill="x", padx=(6, 0))
        self.menu = tk.Menu(self.root, tearoff=0, bg=FUNDO_CAIXA, fg=TEXTO,
                            activebackground=BORDA, activeforeground=TEXTO)
        self.menu.add_command(label="Renomear", command=self.renomear_chat)
        self.menu.add_command(label="Excluir", command=self.excluir_chat)

        self.principal = tk.Frame(self.corpo, bg=FUNDO)
        self.principal.pack(side="left", fill="both", expand=True)
        if self.cfg["lateral"]:
            self.lateral.pack(side="left", fill="y", padx=(0, 10), before=self.principal)

        quadro = tk.Frame(self.principal, bg=FUNDO)
        quadro.pack(fill="both", expand=True, pady=(0, 6))
        barra = tk.Scrollbar(quadro); barra.pack(side="right", fill="y")
        self.chat = tk.Text(quadro, wrap="word", bg=FUNDO, fg=TEXTO, font=self.f_ui,
            bd=0, height=1, highlightthickness=0, padx=6, pady=6, state="disabled",
            yscrollcommand=barra.set, cursor="arrow")
        self.chat.pack(side="left", fill="both", expand=True)
        barra.config(command=self.chat.yview)
        self.chat.bind("<Configure>", lambda e: self.root.after_idle(self._ajustar_blocos))
        self._tags()

        self.anexos_frame = tk.Frame(self.principal, bg=FUNDO)
        self.anexos_frame.pack(fill="x")
        barra_anexos = tk.Frame(self.principal, bg=FUNDO)
        barra_anexos.pack(fill="x", pady=(0, 4))
        self._botao(barra_anexos, "Anexar arquivos", self.anexar_arquivos).pack(side="left")
        self._botao(barra_anexos, "Capturar tela", self.capturar_e_anexar).pack(
            side="left", padx=4)
        self._botao(barra_anexos, "Ver tela", self.ver_tela_agora).pack(
            side="left", padx=4)
        self.btn_mic = self._botao(barra_anexos,
            "Falar" if TEM_STT else "(STT off)", self.escutar_voz)
        self.btn_mic.pack(side="left", padx=4)
        if not TEM_STT: self.btn_mic.config(state="disabled")
        self.btn_fal = self._botao(barra_anexos,
            "Ler resposta" if TEM_TTS else "(TTS off)", self.falar_ultima)
        self.btn_fal.pack(side="left", padx=4)
        if not TEM_TTS: self.btn_fal.config(state="disabled")

        self.entrada = tk.Text(self.principal, height=3, wrap="word", bg=FUNDO_CAIXA,
            fg=TEXTO, insertbackground=TEXTO, font=self.f_ui, bd=0, highlightthickness=1,
            highlightbackground=FUNDO_CAIXA, highlightcolor=DESTAQUE, padx=8, pady=8)
        self.entrada.pack(fill="x", pady=(0, 4))
        self.entrada.bind("<Return>", self.enviar)
        self.entrada.bind("<Shift-Return>", lambda e: None)

        rodape = tk.Frame(self.root, bg=FUNDO)
        rodape.pack(fill="x", padx=14, pady=(0, 8))
        self.lbl_dica = tk.Label(rodape, text="Enter envia · /ajuda mostra os comandos",
            bg=FUNDO, fg=CINZA, font=("DejaVu Sans", 9), anchor="w")
        self.lbl_dica.pack(side="left")
        self.lbl_stats = tk.Label(rodape, text="", bg=FUNDO, fg=CINZA,
                                  font=("DejaVu Sans", 9), anchor="e")
        self.lbl_stats.pack(side="right")

    def _tags(self):
        c, fam = self.chat, "DejaVu Sans"
        c.tag_config("rotulo", foreground=DESTAQUE, font=(fam, 9, "bold"))
        c.tag_config("voce", foreground=VERDE)
        c.tag_config("ia", foreground=TEXTO)
        c.tag_config("erro", foreground=VERMELHO)
        c.tag_config("dica", foreground=CINZA, font=(fam, 9, "italic"))
        c.tag_config("ferramenta", foreground=LARANJA, font=(fam, 10))
        c.tag_config("negrito", font=(fam, 11, "bold"))
        c.tag_config("italico", font=(fam, 11, "italic"))
        c.tag_config("codigo_inline", font=("DejaVu Sans Mono", 10),
                     background="#313244", foreground=LARANJA)
        c.tag_config("titulo", font=(fam, 13, "bold"), foreground=DESTAQUE)
        c.tag_config("lista", lmargin1=10, lmargin2=26)
        c.tag_config("citacao", foreground=CINZA, lmargin1=14, lmargin2=14,
                     font=(fam, 11, "italic"))
        c.tag_config("tabela", font=("DejaVu Sans Mono", 10))

    def mostrar(self):
        self.root.deiconify(); self.root.lift(); self.root.focus_force()
        self.entrada.focus_set()
        threading.Thread(target=self.cliente.aquecer, args=(self.obter_url(),),
                         daemon=True).start()
    def esconder(self): self.root.withdraw()
    def alternar(self):
        if self.root.state() == "withdrawn": self.mostrar()
        else: self.esconder()
    def alternar_lateral(self):
        if self.lateral.winfo_ismapped():
            self.lateral.pack_forget(); self.cfg["lateral"] = False
        else:
            self.lateral.pack(side="left", fill="y", padx=(0, 10), before=self.principal)
            self.cfg["lateral"] = True
        salvar_config(lateral=self.cfg["lateral"]); self.entrada.focus_set()

    @contextmanager
    def _editar(self):
        self.chat.config(state="normal")
        try: yield
        finally: self.chat.config(state="disabled")
    def escrever(self, texto, tag):
        with self._editar(): self.chat.insert("end", texto, tag)
        self.chat.see("end")
    def nota(self, texto): self.escrever(texto + "\n\n", "dica")
    def _nova_linha(self):
        if self.chat.index("end-1c") != self.chat.index("end-1c linestart"):
            self.chat.insert("end", "\n")
    def _limpar_chat(self):
        for w in self.janelas + [b["quadro"] for b in self.blocos]:
            try: w.destroy()
            except tk.TclError: pass
        self.janelas.clear(); self.blocos.clear()
        with self._editar(): self.chat.delete("1.0", "end")

    def _render_md(self, texto):
        pos = 0
        for m in RE_CERCA.finditer(texto):
            self._trecho_md(texto[pos:m.start()])
            self._bloco_codigo(m.group(3).rstrip("\n"), m.group(2).strip())
            pos = m.end()
        self._trecho_md(texto[pos:])
    def _trecho_md(self, trecho):
        trecho = trecho.strip("\n")
        if not trecho.strip(): return
        self._nova_linha()
        linhas = trecho.split("\n")
        for i, linha in enumerate(linhas):
            m_tit = re.match(r"^#{1,6}\s+(.*)$", linha)
            m_lis = re.match(r"^(\s*)[-*+]\s+(.+)$", linha)
            m_num = re.match(r"^(\s*\d+[.)])\s+(.+)$", linha)
            m_cit = re.match(r"^>\s?(.*)$", linha)
            if m_tit: self._inline(m_tit.group(1), ("titulo",))
            elif m_lis:
                self.chat.insert("end", m_lis.group(1) + "•  ", ("ia", "lista"))
                self._inline(m_lis.group(2), ("ia", "lista"))
            elif m_num:
                self.chat.insert("end", m_num.group(1) + " ", ("ia", "lista"))
                self._inline(m_num.group(2), ("ia", "lista"))
            elif m_cit: self._inline(m_cit.group(1), ("citacao",))
            elif re.match(r"^\s*([-*_])\1{2,}\s*$", linha):
                self.chat.insert("end", "-" * 40, ("dica",))
            elif linha.lstrip().startswith("|"):
                self.chat.insert("end", linha, ("ia", "tabela"))
            else: self._inline(linha, ("ia",))
            if i < len(linhas) - 1: self.chat.insert("end", "\n")
    def _inline(self, texto, base):
        for p in RE_INLINE.split(texto):
            if not p: continue
            if p.startswith("**") and p.endswith("**") and len(p) > 4:
                self.chat.insert("end", p[2:-2], base + ("negrito",))
            elif p.startswith("`") and p.endswith("`") and len(p) > 2:
                self.chat.insert("end", p[1:-1], base + ("codigo_inline",))
            elif p.startswith("*") and p.endswith("*") and len(p) > 2:
                self.chat.insert("end", p[1:-1], base + ("italico",))
            else: self.chat.insert("end", p, base)
    def _bloco_codigo(self, codigo, linguagem):
        self._nova_linha()
        quadro = tk.Frame(self.chat, bg=FUNDO_CODIGO, highlightthickness=1,
                          highlightbackground=BORDA)
        cab = tk.Frame(quadro, bg=CABECALHO_CODIGO); cab.pack(fill="x")
        tk.Label(cab, text=linguagem or "código", bg=CABECALHO_CODIGO, fg=CINZA,
                 font=("DejaVu Sans", 9)).pack(side="left", padx=8, pady=3)
        btn = tk.Button(cab, text="Copiar", relief="flat", bd=0, cursor="hand2",
            bg=BORDA, fg=TEXTO, activebackground=TEXTO, activeforeground=FUNDO,
            font=("DejaVu Sans", 9), padx=8, pady=1, highlightthickness=0)
        btn.pack(side="right", padx=6, pady=3)
        txt = tk.Text(quadro, wrap="char", height=1, width=40, bg=FUNDO_CODIGO, fg=TEXTO,
            font=self.f_mono, bd=0, highlightthickness=0, padx=10, pady=8,
            cursor="arrow", insertbackground=TEXTO)
        txt.insert("1.0", codigo); txt.config(state="disabled"); txt.pack(fill="x")
        def copiar():
            self.root.clipboard_clear(); self.root.clipboard_append(codigo)
            self.root.update_idletasks(); btn.config(text="Copiado")
            def voltar():
                try: btn.config(text="Copiar")
                except tk.TclError: pass
            self.root.after(1500, voltar)
        btn.config(command=copiar)
        for w in (quadro, cab, txt):
            w.bind("<Button-4>", self._rolar); w.bind("<Button-5>", self._rolar)
            w.bind("<MouseWheel>", self._rolar)
        self.blocos.append({"quadro": quadro, "txt": txt, "codigo": codigo, "btn": btn})
        self.chat.window_create("end-1c", window=quadro, padx=4, pady=6)
        self.chat.insert("end", "\n"); self._ajustar_blocos()
    def _rolar(self, e):
        if getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0:
            self.chat.yview_scroll(-3, "units")
        else: self.chat.yview_scroll(3, "units")
        return "break"
    def _ajustar_blocos(self):
        if not self.blocos: return
        largura = self.chat.winfo_width()
        cw = max(1, self.f_mono.measure("0"))
        cols = max(20, (largura - 70) // cw)
        for b in self.blocos:
            try:
                b["txt"].config(width=cols)
                linhas = sum(max(1, -(-len(l.expandtabs(4)) // cols))
                             for l in b["codigo"].split("\n"))
                b["txt"].config(height=linhas)
            except tk.TclError: pass

    def _atualizar_anexos(self):
        for w in self.anexos_frame.winfo_children(): w.destroy()
        for i, a in enumerate(self.anexos):
            chip = tk.Frame(self.anexos_frame, bg=FUNDO_CAIXA, highlightthickness=1,
                            highlightbackground=BORDA)
            chip.pack(side="left", padx=(0, 4), pady=(0, 4))
            icone = {"texto": "[T]", "imagem": "[I]", "binario": "[B]"}.get(a["tipo"], "[?]")
            tk.Label(chip, text=f"{icone} {a['nome']}", bg=FUNDO_CAIXA, fg=TEXTO,
                     font=("DejaVu Sans", 9)).pack(side="left", padx=(6, 2), pady=2)
            x = tk.Label(chip, text="x", bg=FUNDO_CAIXA, fg=CINZA, cursor="hand2",
                         font=("DejaVu Sans", 9, "bold"))
            x.pack(side="left", padx=(2, 6))
            x.bind("<Button-1>", lambda e, idx=i: self._remover_anexo(idx))
    def _remover_anexo(self, i):
        if 0 <= i < len(self.anexos):
            self.anexos.pop(i); self._atualizar_anexos()

    def anexar_arquivos(self):
        caminhos = escolher_arquivos()
        for c in caminhos:
            a = ler_arquivo_para_anexo(c)
            if a is None:
                self.nota(f"Não consegui ler: {c}"); continue
            if a["tipo"] == "texto" and a["tamanho"] > MAX_ANEXO_TEXTO:
                self.nota(f"{a['nome']}: muito grande ({a['tamanho']} bytes), truncado.")
                a["conteudo"] = a["conteudo"][:MAX_ANEXO_TEXTO]
            self.anexos.append(a)
        self._atualizar_anexos()
        self.entrada.focus_set()

    def capturar_e_anexar(self):
        self.escrever("Capturando tela...\n", "dica")
        threading.Thread(target=self._capturar_thread, daemon=True).start()
    def _capturar_thread(self):
        caminho = capturar_tela()
        self.fila.put(("screenshot", caminho))
    def _processar_screenshot(self, caminho):
        if not caminho:
            self.nota("Não consegui capturar a tela.")
            return
        a = ler_arquivo_para_anexo(caminho)
        if a and a["tipo"] == "imagem":
            a["nome"] = "screenshot.png"
            self.anexos.append(a); self._atualizar_anexos()
            self.nota(f"Tela capturada ({a['tamanho']} bytes).")
        else:
            self.nota("Captura falhou.")

    def ver_tela_agora(self):
        if self.ocupado:
            self.nota("Espere a resposta atual terminar."); return
        if not self.obter_chave() and self.cfg["provider"] != "ollama":
            self.nota("Sem chave da API."); return
        max_idade = 5.0
        intervalo = int(self.cfg.get("tempo_real_segundos", 0))
        if intervalo > 0:
            max_idade = max(5.0, intervalo * 1.5)
        caminho = _captura_do_buffer(max_idade) or capturar_tela()
        if not caminho:
            self.nota("Não consegui capturar a tela."); return
        a = ler_arquivo_para_anexo(caminho)
        if not a or a["tipo"] != "imagem":
            self.nota("Captura falhou."); return
        a["nome"] = "screenshot.png"
        self.anexos.append(a); self._atualizar_anexos()
        self.entrada.delete("1.0", "end")
        self.entrada.insert("1.0", "Olhe a minha tela agora e diga o que vê.")
        self.enviar()

    def escutar_voz(self):
        if not TEM_STT:
            self.nota("STT não instalado.")
            return
        if self._escutando:
            self.nota("Já estou escutando..."); return
        self._escutando = True
        self.btn_mic.config(text="...", bg=VERMELHO, fg=FUNDO)
        self.escrever("Escutando... fale agora.\n", "dica")
        threading.Thread(target=self._escutar_thread, daemon=True).start()
    def _escutar_thread(self):
        rec = sr.Recognizer()
        try:
            with sr.Microphone() as fonte:
                rec.adjust_for_ambient_noise(fonte, duration=0.5)
                audio = rec.listen(fonte, timeout=8, phrase_time_limit=20)
            texto = rec.recognize_google(audio, language=self.cfg.get("stt_idioma", "pt-BR"))
            self.fila.put(("voz", texto))
        except sr.WaitTimeoutError:
            self.fila.put(("voz_erro", "Ninguém falou (timeout)."))
        except sr.UnknownValueError:
            self.fila.put(("voz_erro", "Não entendi o que você disse."))
        except sr.RequestError as e:
            self.fila.put(("voz_erro", f"Erro no Google: {e}"))
        except Exception as e:
            self.fila.put(("voz_erro", f"Erro: {e}"))
    def _processar_voz(self, texto):
        self._escutando = False
        self.btn_mic.config(text="Falar", bg=BORDA, fg=TEXTO)
        self.entrada.delete("1.0", "end")
        self.entrada.insert("1.0", texto)
        self.entrada.focus_set()
        self.enviar()
    def _erro_voz(self, msg):
        self._escutando = False
        self.btn_mic.config(text="Falar", bg=BORDA, fg=TEXTO)
        self.nota(msg)

    def _pegar_ultima_resposta(self):
        for m in reversed(self.atual["mensagens"]):
            if m.get("role") == "assistant" and m.get("content"):
                return m["content"]
        return ""
    def _limpar_md_para_fala(self, texto):
        t = RE_CERCA.sub(lambda m: " bloco de código. ", texto)
        t = re.sub(r"[*_`#>|]", " ", t)
        t = re.sub(r"\s+", " ", t)
        return t.strip()
    def falar_ultima(self):
        if not TEM_TTS:
            self.nota("TTS não instalado.")
            return
        texto = self._pegar_ultima_resposta()
        if not texto:
            self.nota("Nada para ler ainda."); return
        self._falar_async(self._limpar_md_para_fala(texto))
    def _falar_async(self, texto):
        if self._falando: return
        self._falando = True
        self.btn_fal.config(text="...", bg=VERDE, fg=FUNDO)
        threading.Thread(target=self._falar_thread, args=(texto,), daemon=True).start()
    def _falar_thread(self, texto):
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 170)
            for v in engine.getProperty("voices"):
                if "pt" in (v.id + " " + v.name).lower() or \
                   "brazil" in (v.id + " " + v.name).lower():
                    engine.setProperty("voice", v.id); break
            engine.say(texto)
            engine.runAndWait()
        except Exception as e:
            self.fila.put(("voz_erro", f"Falha ao falar: {e}"))
        finally:
            self.fila.put(("fim_fala", None))
    def _fim_fala(self):
        self._falando = False
        self.btn_fal.config(text="Ler resposta", bg=BORDA, fg=TEXTO)

    def _card_acao(self, d):
        valido, erro = validar_acao(d)
        quadro = tk.Frame(self.chat, bg=FUNDO_CAIXA, highlightthickness=1,
                          highlightbackground=BORDA)
        tk.Label(quadro, text="Ação proposta pelo assistente", bg=FUNDO_CAIXA,
                 fg=DESTAQUE, font=("DejaVu Sans", 10, "bold"), anchor="w"
                 ).pack(fill="x", padx=8, pady=(6, 2))
        corpo = tk.Frame(quadro, bg=FUNDO_CAIXA); corpo.pack(fill="x", padx=8, pady=(2, 6))
        if not valido:
            tk.Label(corpo, text=f"Ação inválida: {erro}", bg=FUNDO_CAIXA, fg=VERMELHO,
                     wraplength=520, justify="left", anchor="w",
                     font=("DejaVu Sans", 10)).pack(fill="x")
            self.janelas.append(quadro)
            with self._editar():
                self._nova_linha()
                self.chat.window_create("end-1c", window=quadro, padx=4, pady=2)
                self.chat.insert("end", "\n\n")
            self.chat.see("end")
            self.atual["mensagens"].append({"role": "tool",
                "content": "[RESULTADO DA FERRAMENTA]\nação inválida: " + erro})
            self.agente_passo_concluido(continuar=True); return
        if d.get("acao") == "ver_tela":
            self.escrever("Ver tela...\n", "ferramenta")
            threading.Thread(target=self._rodar_acao, args=(d, None), daemon=True).start()
            return
        if d.get("acao") == "executar" and comando_e_seguro(d.get("comando", "")):
            self.escrever(f"auto: {d.get('comando')}\n", "ferramenta")
            threading.Thread(target=self._rodar_acao, args=(d, None), daemon=True).start()
            return
        descricao = resumo_acao(d)
        if d.get("motivo"): descricao += f"\nMotivo: {d['motivo']}"
        if d.get("acao") == "executar" and RE_PERIGOSO.search(d.get("comando", "")):
            descricao += "\nAtenção: comando potencialmente perigoso."
        tk.Label(corpo, text=descricao, bg=FUNDO_CAIXA, fg=TEXTO, wraplength=520,
                 justify="left", anchor="w",
                 font=("DejaVu Sans Mono", 10) if d.get("acao") == "executar"
                 else ("DejaVu Sans", 10)).pack(fill="x")
        botoes = tk.Frame(quadro, bg=FUNDO_CAIXA); botoes.pack(fill="x", padx=8, pady=(0, 8))
        def desativar():
            for b in (b_exec, b_edit, b_canc):
                try: b.config(state="disabled")
                except tk.TclError: pass
        def executar(): desativar(); self._iniciar_execucao(d)
        def cancelar():
            desativar(); self.escrever("[Cancelado pelo usuário]\n\n", "dica")
            self.atual["mensagens"].append({"role": "tool",
                "content": "[RESULTADO DA FERRAMENTA]\nação cancelada pelo usuário."})
            self.agente_passo_concluido(continuar=False)
        def editar_cmd():
            novo = simpledialog.askstring("Editar comando", "Comando:",
                initialvalue=d.get("comando", ""), parent=self.root)
            if novo is None: return
            d["comando"] = novo; desativar(); self._iniciar_execucao(d)
        b_canc = self._botao(botoes, "Cancelar", cancelar)
        b_edit = self._botao(botoes, "Editar", editar_cmd)
        b_exec = self._botao(botoes, "Executar", executar, destaque=True)
        b_canc.pack(side="right", padx=4); b_exec.pack(side="right", padx=4)
        if d.get("acao") == "executar": b_edit.pack(side="right", padx=4)
        self.janelas.append(quadro)
        with self._editar():
            self._nova_linha()
            self.chat.window_create("end-1c", window=quadro, padx=4, pady=4)
            self.chat.insert("end", "\n\n")
        self.chat.see("end")

    def _iniciar_execucao(self, d):
        if d.get("acao") == "executar" and RE_PERIGOSO.search(d.get("comando", "")):
            if not messagebox.askyesno("Confirmação dupla",
                f"Comando PERIGOSO:\n\n{d.get('comando')}\n\nTem certeza?",
                icon="warning", parent=self.root):
                self.escrever("[Recusado por segurança]\n\n", "dica")
                self.atual["mensagens"].append({"role": "tool",
                    "content": "[RESULTADO DA FERRAMENTA]\nusuário recusou comando perigoso."})
                self.agente_passo_concluido(continuar=False); return
        senha = None
        usa_sudo = bool(d.get("sudo")) or (
            d.get("acao") == "executar" and isinstance(d.get("comando"), str)
            and d["comando"].strip().startswith("sudo "))
        if usa_sudo:
            senha = simpledialog.askstring("Senha do sudo",
                "O assistente precisa da sua senha para:\n\n"
                + (d.get("motivo") or resumo_acao(d))
                + "\n\nA senha não é guardada.", show="*", parent=self.root)
            if senha is None:
                self.escrever("[Cancelado: senha não informada]\n\n", "dica")
                self.atual["mensagens"].append({"role": "tool",
                    "content": "[RESULTADO DA FERRAMENTA]\nusuário não informou a senha."})
                self.agente_passo_concluido(continuar=False); return
            senha = senha.strip()
        self.escrever(f"Executando: {resumo_acao(d)}...\n\n", "ferramenta")
        threading.Thread(target=self._rodar_acao, args=(d, senha), daemon=True).start()

    def _rodar_acao(self, d, senha):
        log_agente("AÇÃO " + json.dumps(d, ensure_ascii=False))
        r = executar_acao(d, senha, self.cfg)
        log_agente(f"RESULTADO ok={r.get('ok')} erro={(r.get('erro') or '')[:200]!r}")
        self.fila.put(("acao_resultado", r))

    def _render_resultado(self, r):
        ok = bool(r.get("ok")); saida = r.get("saida") or ""; erro = r.get("erro") or ""
        imagem = r.get("imagem")
        blocos = ["[RESULTADO DA FERRAMENTA]", "ok: sim" if ok else "ok: não"]
        if saida: blocos.append("saída:\n" + saida)
        if erro: blocos.append("erro:\n" + erro)
        if imagem: blocos.append("[imagem anexada: " + imagem.get("nome", "imagem") + "]")
        if ok:
            self.escrever("Concluído\n", "ferramenta")
            if saida: self.escrever(saida + "\n", "ia")
            if imagem: self.escrever("Imagem enviada ao modelo\n", "ia")
        else:
            self.escrever("Falhou\n", "erro")
            if erro: self.escrever(erro + "\n", "erro")
            if saida: self.escrever(saida + "\n", "ia")
        self.escrever("\n", "ia")
        entrada = {"role": "tool", "content": "\n".join(blocos)}
        if imagem: entrada["imagem"] = imagem
        self.atual["mensagens"].append(entrada)
        if self.atual["id"]: self.chats.salvar(self.atual)
        else: self.chats.salvar_sessao(self.atual["mensagens"])

    def agente_passo_concluido(self, continuar):
        if not continuar or not self.cfg["agente_ativo"]:
            self.ocupado = False; self._terminar(""); return
        if self.agente_passos >= int(self.cfg.get("agente_max_passos", 5)):
            self.nota(f"Limite de {self.cfg.get('agente_max_passos', 5)} passos atingido.")
            self.ocupado = False; self._terminar(""); return
        self.agente_passos += 1
        self.continuar_apos_ferramenta()

    def continuar_apos_ferramenta(self):
        self.ocupado = True; self.resposta = ""; self._mostrado = 0
        self.n_trechos = self.n_raciocinio = 0
        self.t_inicio = time.time(); self.t_primeira = 0.0
        with self._editar():
            self.chat.insert("end", "Assistente\n", "rotulo")
            self.chat.mark_set("inicio_resp", "end-1c")
            self.chat.mark_gravity("inicio_resp", "left")
        self.chat.see("end")
        mensagens = ([{"role": "system", "content": self.montar_sistema()}]
                     + self.mensagens_api())
        threading.Thread(target=self.pedir,
                         args=(mensagens, self.obter_modelo(), dict(self.cfg["extra"])),
                         daemon=True).start()

    def mensagens_api(self):
        saida = []
        for m in limitar_historico(self.atual["mensagens"]):
            if m["role"] == "tool":
                img = m.get("imagem")
                if img:
                    saida.append({"role": "user", "content": [
                        {"type": "text", "text": m["content"]},
                        {"type": "image_url",
                         "image_url": {"url": f"data:{img['mime']};base64,{img['b64']}"}},
                    ]})
                else:
                    saida.append({"role": "user", "content": m["content"]})
                continue
            conteudo = m.get("content", "")
            anexos = m.get("anexos") or []
            if not anexos:
                saida.append({"role": m["role"], "content": conteudo}); continue
            partes = []; texto_extra = []
            for a in anexos:
                if a["tipo"] == "texto":
                    texto_extra.append(
                        f"\n\n--- arquivo: {a['nome']} ---\n```\n{a['conteudo']}\n```")
                elif a["tipo"] == "binario":
                    texto_extra.append(
                        f"\n\n[arquivo binário: {a['nome']} ({a['tamanho']} bytes)]")
                elif a["tipo"] == "imagem":
                    partes.append({"type": "image_url",
                        "image_url": {"url": f"data:{a['mime']};base64,{a['b64']}"}})
            partes.insert(0, {"type": "text", "text": conteudo + "".join(texto_extra)})
            saida.append({"role": m["role"], "content": partes})
        return saida

    def _atualizar_topo(self):
        self.lbl_titulo.config(text=self.atual["titulo"])
        if self.atual["id"] is None:
            self.btn_salvar.pack(side="right", padx=(0, 8), after=self.btn_pers)
        else: self.btn_salvar.pack_forget()

    def render_historico(self):
        self._limpar_chat()
        with self._editar():
            for m in self.atual["mensagens"]:
                anexos = m.get("anexos") or []
                sufixo = ""
                if anexos:
                    sufixo = "  [anexos: " + ", ".join(a["nome"] for a in anexos) + "]"
                if m["role"] == "user":
                    self.chat.insert("end", "Você\n", "rotulo")
                    self.chat.insert("end", m["content"] + sufixo + "\n\n", "voce")
                elif m["role"] == "tool":
                    corpo = m["content"].replace("[RESULTADO DA FERRAMENTA]\n", "")
                    self.chat.insert("end", "Ferramenta\n", "rotulo")
                    self.chat.insert("end", corpo + "\n\n", "ferramenta")
                else:
                    self.chat.insert("end", "Assistente\n", "rotulo")
                    self._render_md(m["content"]); self._nova_linha()
                    self.chat.insert("end", "\n")
            if not self.atual["mensagens"]:
                ch = self.obter_chave()
                if not ch and self.cfg["provider"] != "ollama":
                    self.chat.insert("end",
                        "Falta a chave da API. Abra Personalidade e memória.\n\n", "erro")
                self.chat.insert("end",
                    "Pergunte qualquer coisa. /ajuda mostra os comandos.\n\n", "dica")
        self.chat.see("end"); self._atualizar_topo()

    def atualizar_lista(self):
        termo = self.var_busca.get() if hasattr(self, "var_busca") else ""
        self.itens_lista = []; nomes = []
        if not termo.strip():
            self.itens_lista.append(None); nomes.append(TITULO_SESSAO)
        for c in self.chats.buscar(termo):
            self.itens_lista.append(c["id"]); nomes.append(c["titulo"])
        self._silencio_lista = True
        self.lista.delete(0, "end")
        for n in nomes: self.lista.insert("end", n)
        if self.atual["id"] in self.itens_lista:
            i = self.itens_lista.index(self.atual["id"])
            self.lista.selection_set(i); self.lista.see(i)
        self._silencio_lista = False

    def _ao_selecionar(self, _e=None):
        if self._silencio_lista: return
        sel = self.lista.curselection()
        if not sel: return
        id_ = self.itens_lista[sel[0]]
        if self.ocupado: self.atualizar_lista(); return
        self.abrir_conversa(id_)
    def _menu_contexto(self, e):
        i = self.lista.nearest(e.y)
        if 0 <= i < len(self.itens_lista):
            self.lista.selection_clear(0, "end"); self.lista.selection_set(i)
            self._ao_selecionar(); self.menu.tk_popup(e.x_root, e.y_root)
    def abrir_conversa(self, id_):
        if self.ocupado: return
        self.atual = self.sessao if id_ is None else self.chats.cache[id_]
        self.render_historico(); self.atualizar_lista(); self.entrada.focus_set()
    def novo_chat(self):
        if self.ocupado: return
        self.atual = self.chats.criar(TITULO_NOVO)
        self.var_busca.set(""); self.render_historico()
        self.atualizar_lista(); self.entrada.focus_set()

    def salvar_sessao(self, nome=None):
        if self.ocupado: return
        if self.atual["id"] is not None or not self.sessao["mensagens"]:
            self.nota("Não há nada para salvar ainda."); return
        primeiro = next((m for m in self.sessao["mensagens"] if m["role"] == "user"), None)
        nome = (nome if isinstance(nome, str) and nome
                else self._titulo_de(primeiro["content"] if primeiro else "Novo chat"))
        c = self.chats.criar(nome, self.sessao["mensagens"])
        self.sessao["mensagens"] = []
        self.chats.salvar_sessao([])
        self.atual = c
        self.render_historico(); self.atualizar_lista(); self.entrada.focus_set()

    @staticmethod
    def _titulo_de(texto):
        t = " ".join(texto.split())
        return t[:40] + ("..." if len(t) > 40 else "") or TITULO_NOVO

    def renomear_chat(self):
        if self.atual["id"] is None:
            self.nota("A sessão atual não tem nome."); return
        novo = simpledialog.askstring("Renomear chat", "Novo nome:",
                                      initialvalue=self.atual["titulo"], parent=self.root)
        if novo and novo.strip():
            self.atual["titulo"] = novo.strip(); self.chats.salvar(self.atual)
            self.atualizar_lista(); self._atualizar_topo()

    def excluir_chat(self):
        if self.ocupado: return
        if self.atual["id"] is None: self.limpar(); return
        if messagebox.askyesno("Excluir chat",
                               f"Excluir este chat para sempre?",
                               parent=self.root):
            self.chats.excluir(self.atual["id"]); self.atual = self.sessao
            self.render_historico(); self.atualizar_lista()

    def limpar(self):
        if self.ocupado: return
        if self.atual["id"] and self.atual["mensagens"]:
            if not messagebox.askyesno("Limpar chat",
                "Apagar todas as mensagens deste chat salvo?", parent=self.root): return
        self.atual["mensagens"].clear()
        if self.atual["id"]: self.chats.salvar(self.atual)
        else: self.chats.salvar_sessao([])
        self.render_historico()

    def comando(self, texto):
        partes = texto.split(None, 1)
        cmd = partes[0].lower(); arg = partes[1].strip() if len(partes) > 1 else ""
        if cmd == "/ajuda": self.nota(AJUDA)
        elif cmd == "/lembrar":
            if arg: self.memoria.adicionar(arg); self.nota(f"Anotado: {arg}")
            else: self.nota("Uso: /lembrar <texto>")
        elif cmd == "/memoria":
            if self.memoria.itens:
                self.nota("\n".join(f"{i}. {x['texto']}"
                                    for i, x in enumerate(self.memoria.itens, 1)))
            else: self.nota("Memória vazia.")
        elif cmd == "/esquecer":
            if arg.isdigit() and 1 <= int(arg) <= len(self.memoria.itens):
                self.nota(f"Esquecido: {self.memoria.remover(int(arg))['texto']}")
            else: self.nota("Uso: /esquecer <número>")
        elif cmd == "/personalidade": self.abrir_config()
        elif cmd in ("/provedor", "/provider"):
            if arg:
                if arg in PROVIDERS:
                    self.cfg["provider"] = arg
                    salvar_config(provider=arg)
                    self.cliente.fechar()
                    self.nota(f"Provedor: {PROVIDERS[arg]['nome']}. "
                              f"Modelo: {self.obter_modelo()}")
                else:
                    self.nota("Provedores: " + ", ".join(PROVIDERS.keys()))
            else:
                lista = "\n".join(
                    f"  {'*' if k == self.cfg['provider'] else ' '} {k}  -- {v['nome']}"
                    for k, v in PROVIDERS.items())
                self.nota(f"Provedor ativo: {self.cfg['provider']}\n\n{lista}")
        elif cmd == "/modelo":
            if arg:
                self.cfg["modelos"][self.cfg["provider"]] = arg
                salvar_config(modelos=self.cfg["modelos"])
                self.nota(f"Modelo ({self.cfg['provider']}): {arg}")
            else:
                self.nota(f"Provedor: {self.cfg['provider']} · Modelo: {self.obter_modelo()}")
        elif cmd == "/agente":
            self.cfg["agente_ativo"] = not self.cfg["agente_ativo"]
            salvar_config(agente_ativo=self.cfg["agente_ativo"])
            self.nota("Modo agente " + ("ativado" if self.cfg["agente_ativo"] else "desativado"))
        elif cmd == "/fixo":
            self.cfg["fixo"] = not self.cfg.get("fixo", True)
            salvar_config(fixo=self.cfg["fixo"])
            self.root.attributes("-topmost", self.cfg["fixo"])
            self.nota("Janela fixa " + ("ativada" if self.cfg["fixo"] else "desativada"))
        elif cmd == "/ver": self.ver_tela_agora()
        elif cmd == "/tempo_real":
            if arg.isdigit():
                n = max(0, min(300, int(arg)))
                self.cfg["tempo_real_segundos"] = n
                salvar_config(tempo_real_segundos=n)
                self.nota(f"Captura contínua: {n}s" if n else "Captura contínua desligada")
            else:
                at = self.cfg.get("tempo_real_segundos", 0)
                self.nota(f"Captura contínua: {at}s")
        elif cmd == "/falar":
            self.cfg["auto_falar"] = not self.cfg.get("auto_falar", False)
            salvar_config(auto_falar=self.cfg["auto_falar"])
            self.nota("Auto-falar " + ("ligado" if self.cfg["auto_falar"] else "desligado"))
        elif cmd == "/escutar": self.escutar_voz()
        elif cmd == "/salvar": self.salvar_sessao(arg or None)
        elif cmd == "/limpar": self.limpar()
        else: self.nota("Comando desconhecido. Digite /ajuda.")

    def montar_sistema(self):
        partes = [PROMPT_BASE]
        pers = ler_personalidade().strip()
        if pers: partes.append("Personalidade desejada pelo usuário:\n" + pers)
        if self.memoria.itens:
            partes.append("O usuário pediu para você lembrar:\n"
                          + "\n".join("- " + i["texto"] for i in self.memoria.itens[-40:]))
        if self.cfg["aprender"] and self.cfg["categorias"]:
            cats = "; ".join(CATEGORIAS[c] for c in self.cfg["categorias"])
            partes.append(INSTRUCAO_APRENDER.format(cats=cats))
        if self.cfg["agente_ativo"]: partes.append(INSTRUCAO_AGENTE)
        return "\n\n".join(partes)

    def abrir_config(self):
        if self.janela_cfg is not None and self.janela_cfg.winfo_exists():
            self.janela_cfg.lift(); return
        w = tk.Toplevel(self.root); self.janela_cfg = w
        w.title("Configurações"); w.configure(bg=FUNDO)
        w.transient(self.root)
        w.geometry("720x820"); w.minsize(560, 500)
        w.resizable(True, True)
        canvas = tk.Canvas(w, bg=FUNDO, highlightthickness=0)
        scroll = tk.Scrollbar(w, orient="vertical", command=canvas.yview)
        frame = tk.Frame(canvas, bg=FUNDO)
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        def _wheel(e):
            if getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0:
                canvas.yview_scroll(-3, "units")
            elif getattr(e, "num", 0) == 5 or getattr(e, "delta", 0) < 0:
                canvas.yview_scroll(3, "units")
            return "break"
        def _bind_wheel(widget):
            widget.bind("<MouseWheel>", _wheel)
            widget.bind("<Button-4>", _wheel)
            widget.bind("<Button-5>", _wheel)
            for c in widget.winfo_children():
                _bind_wheel(c)
        def _on_frame_config(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            _bind_wheel(frame)
        frame.bind("<Configure>", _on_frame_config)
        canvas.bind("<MouseWheel>", _wheel)
        canvas.bind("<Button-4>", _wheel)
        canvas.bind("<Button-5>", _wheel)

        def titulo(t):
            tk.Label(frame, text=t, bg=FUNDO, fg=DESTAQUE,
                     font=("DejaVu Sans", 11, "bold"), anchor="w"
                     ).pack(fill="x", padx=16, pady=(14, 2))
        def explica(t):
            tk.Label(frame, text=t, bg=FUNDO, fg=CINZA, font=("DejaVu Sans", 9),
                     anchor="w", justify="left", wraplength=580
                     ).pack(fill="x", padx=16)

        titulo("Provedor de IA")
        explica("Cada usuário cola a própria chave. A chave é detectada pelo prefixo. "
                "Fica em ~/.config/assistente/config.json (permissão 600).")
        linha_p = tk.Frame(frame, bg=FUNDO); linha_p.pack(fill="x", padx=16, pady=(6, 2))
        tk.Label(linha_p, text="Provedor:", bg=FUNDO, fg=TEXTO,
                 font=("DejaVu Sans", 10)).pack(side="left")
        var_prov = tk.StringVar(value=self.cfg["provider"])
        opt = tk.OptionMenu(linha_p, var_prov, *PROVIDERS.keys())
        opt.config(bg=FUNDO_CAIXA, fg=TEXTO, activebackground=BORDA,
                   highlightthickness=0, bd=0, font=("DejaVu Sans", 10))
        opt["menu"].config(bg=FUNDO_CAIXA, fg=TEXTO)
        opt.pack(side="left", padx=6)

        lbl_info = tk.Label(frame, text="", bg=FUNDO, fg=CINZA, justify="left",
                            anchor="w", wraplength=580, font=("DejaVu Sans", 9))
        lbl_info.pack(fill="x", padx=16, pady=(2, 4))

        linha_k = tk.Frame(frame, bg=FUNDO); linha_k.pack(fill="x", padx=16, pady=(2, 2))
        tk.Label(linha_k, text="Chave:", bg=FUNDO, fg=TEXTO,
                 font=("DejaVu Sans", 10)).pack(side="left")
        var_chave = tk.StringVar()
        ent_chave = tk.Entry(linha_k, textvariable=var_chave, show="*", width=42,
                             bg=FUNDO_CAIXA, fg=TEXTO, bd=0, insertbackground=TEXTO,
                             highlightthickness=1, highlightbackground=BORDA,
                             highlightcolor=DESTAQUE, font=("DejaVu Sans", 10))
        ent_chave.pack(side="left", padx=6, ipady=3)
        aviso_ch = tk.Label(frame, text="", bg=FUNDO, fg=VERDE,
                            font=("DejaVu Sans", 9), anchor="w")
        aviso_ch.pack(fill="x", padx=16)

        linha_m = tk.Frame(frame, bg=FUNDO); linha_m.pack(fill="x", padx=16, pady=(2, 2))
        tk.Label(linha_m, text="Modelo:", bg=FUNDO, fg=TEXTO,
                 font=("DejaVu Sans", 10)).pack(side="left")
        var_modelo = tk.StringVar()
        ent_modelo = tk.Entry(linha_m, textvariable=var_modelo, width=42,
                              bg=FUNDO_CAIXA, fg=TEXTO, bd=0, insertbackground=TEXTO,
                              highlightthickness=1, highlightbackground=BORDA,
                              highlightcolor=DESTAQUE, font=("DejaVu Sans", 10))
        ent_modelo.pack(side="left", padx=6, ipady=3)
        aviso_md = tk.Label(frame, text="", bg=FUNDO, fg=VERDE,
                            font=("DejaVu Sans", 9), anchor="w")
        aviso_md.pack(fill="x", padx=16)

        linha_b = tk.Frame(frame, bg=FUNDO); linha_b.pack(fill="x", padx=16, pady=(4, 8))
        btn_salvar_ch = self._botao(linha_b, "Salvar chave e modelo", None, destaque=True)
        btn_salvar_ch.pack(side="left")
        btn_link = self._botao(linha_b, "Como obter a chave", None)
        btn_link.pack(side="left", padx=6)

        def atualizar_secao_prov(*_):
            p = var_prov.get()
            if p not in PROVIDERS: return
            info = PROVIDERS[p]
            lbl_info.config(
                text=f"{info['nome']}\nEndpoint: {info['base_url']}\n"
                     f"Formato: {info['formato']} · "
                     f"Visão: {'sim' if info['visao'] else 'não'}\n"
                     f"Como obter: {info['como_obter']}")
            var_chave.set(self.cfg["chaves"].get(p, ""))
            var_modelo.set(self.cfg["modelos"].get(p) or info["modelo_padrao"])
            aviso_ch.config(text=""); aviso_md.config(text="")
        var_prov.trace_add("write", atualizar_secao_prov)
        atualizar_secao_prov()

        def salvar_ch():
            p = var_prov.get()
            self.cfg["provider"] = p
            self.cfg["chaves"][p] = var_chave.get().strip()
            m = var_modelo.get().strip() or PROVIDERS[p]["modelo_padrao"]
            self.cfg["modelos"][p] = m
            salvar_config(provider=p, chaves=self.cfg["chaves"],
                          modelos=self.cfg["modelos"])
            self.cliente.fechar()
            aviso_ch.config(text="Chave salva")
            aviso_md.config(text="Modelo salvo")
            threading.Thread(target=self.cliente.aquecer, args=(self.obter_url(),),
                             daemon=True).start()
        def abrir_link():
            webbrowser.open(PROVIDERS[var_prov.get()]["como_obter"])
        btn_salvar_ch.config(command=salvar_ch)
        btn_link.config(command=abrir_link)

        titulo("Personalidade")
        explica("Como o assistente deve se comportar. Vale para todas as conversas.")
        caixa = tk.Text(frame, height=4, wrap="word", bg=FUNDO_CAIXA, fg=TEXTO, bd=0,
                        insertbackground=TEXTO, font=("DejaVu Sans", 10), padx=8, pady=8,
                        highlightthickness=1, highlightbackground=BORDA,
                        highlightcolor=DESTAQUE)
        caixa.pack(fill="x", padx=16, pady=6)
        caixa.insert("1.0", ler_personalidade().strip())
        linha = tk.Frame(frame, bg=FUNDO); linha.pack(fill="x", padx=16)
        aviso_pers = tk.Label(linha, text="", bg=FUNDO, fg=VERDE, font=("DejaVu Sans", 9))
        def salvar_pers():
            salvar_personalidade(caixa.get("1.0", "end"))
            aviso_pers.config(text="Salvo")
        def padrao():
            caixa.delete("1.0", "end"); caixa.insert("1.0", PERSONALIDADE_PADRAO)
        self._botao(linha, "Salvar", salvar_pers, destaque=True).pack(side="left")
        self._botao(linha, "Restaurar padrão", padrao).pack(side="left", padx=8)
        aviso_pers.pack(side="left", padx=8)

        titulo("Janela")
        var_fixo = tk.BooleanVar(value=self.cfg.get("fixo", True))
        def aplicar_fixo():
            self.cfg["fixo"] = var_fixo.get()
            salvar_config(fixo=self.cfg["fixo"])
            self.root.attributes("-topmost", self.cfg["fixo"])
        tk.Checkbutton(frame, text="Manter janela sempre no topo (fixa)",
                       variable=var_fixo, command=aplicar_fixo,
                       bg=FUNDO, fg=TEXTO, selectcolor=FUNDO_CAIXA,
                       activebackground=FUNDO, activeforeground=TEXTO,
                       anchor="w", highlightthickness=0, bd=0,
                       font=("DejaVu Sans", 10)).pack(fill="x", padx=16, pady=(6, 2))

        titulo("Tempo real")
        var_tr = tk.StringVar(value=str(self.cfg.get("tempo_real_segundos", 0)))
        def aplicar_tr():
            try: n = max(0, min(300, int(var_tr.get())))
            except ValueError: n = 0
            self.cfg["tempo_real_segundos"] = n
            var_tr.set(str(n))
            salvar_config(tempo_real_segundos=n)
        linha_tr = tk.Frame(frame, bg=FUNDO); linha_tr.pack(fill="x", padx=16, pady=(6, 2))
        tk.Label(linha_tr, text="Capturar a cada", bg=FUNDO, fg=TEXTO,
                 font=("DejaVu Sans", 10)).pack(side="left")
        ent_tr = tk.Entry(linha_tr, textvariable=var_tr, width=4, bg=FUNDO_CAIXA,
                          fg=TEXTO, bd=0, insertbackground=TEXTO, highlightthickness=1,
                          highlightbackground=BORDA)
        ent_tr.pack(side="left", padx=4, ipady=2)
        tk.Label(linha_tr, text="segundos (0 = desligado)", bg=FUNDO, fg=CINZA,
                 font=("DejaVu Sans", 9)).pack(side="left")
        ent_tr.bind("<FocusOut>", lambda e: aplicar_tr())
        ent_tr.bind("<Return>", lambda e: aplicar_tr())

        titulo("Voz")
        if not TEM_STT and not TEM_TTS:
            explica("Nem STT nem TTS instalados.\n"
                    "sudo apt install espeak-ng portaudio19-dev python3-pyaudio\n"
                    "pip3 install --user --break-system-packages SpeechRecognition pyttsx3")
        else:
            var_auto = tk.BooleanVar(value=self.cfg.get("auto_falar", False))
            def aplicar_auto():
                self.cfg["auto_falar"] = var_auto.get()
                salvar_config(auto_falar=self.cfg["auto_falar"])
            tk.Checkbutton(frame, text="Falar a resposta automaticamente",
                           variable=var_auto, command=aplicar_auto,
                           bg=FUNDO, fg=TEXTO, selectcolor=FUNDO_CAIXA,
                           activebackground=FUNDO, activeforeground=TEXTO,
                           anchor="w", highlightthickness=0, bd=0,
                           font=("DejaVu Sans", 10)).pack(fill="x", padx=16, pady=(6, 2))
            linha_id = tk.Frame(frame, bg=FUNDO); linha_id.pack(fill="x", padx=16, pady=(2, 2))
            tk.Label(linha_id, text="Idioma STT:", bg=FUNDO, fg=TEXTO,
                     font=("DejaVu Sans", 10)).pack(side="left")
            var_idioma = tk.StringVar(value=self.cfg.get("stt_idioma", "pt-BR"))
            def aplicar_idioma():
                self.cfg["stt_idioma"] = var_idioma.get() or "pt-BR"
                salvar_config(stt_idioma=self.cfg["stt_idioma"])
            opt2 = tk.OptionMenu(linha_id, var_idioma, "pt-BR", "pt-PT", "en-US", "es-ES")
            opt2.config(bg=FUNDO_CAIXA, fg=TEXTO, activebackground=BORDA,
                        highlightthickness=0, bd=0)
            opt2["menu"].config(bg=FUNDO_CAIXA, fg=TEXTO)
            opt2.pack(side="left", padx=4)
            var_idioma.trace_add("write", lambda *a: aplicar_idioma())

        titulo("Modo agente")
        var_ag = tk.BooleanVar(value=self.cfg["agente_ativo"])
        var_max = tk.StringVar(value=str(self.cfg["agente_max_passos"]))
        def aplicar_ag():
            self.cfg["agente_ativo"] = var_ag.get()
            try: self.cfg["agente_max_passos"] = max(1, min(20, int(var_max.get())))
            except ValueError: self.cfg["agente_max_passos"] = 5
            var_max.set(str(self.cfg["agente_max_passos"]))
            salvar_config(agente_ativo=self.cfg["agente_ativo"],
                          agente_max_passos=self.cfg["agente_max_passos"])
        linha_ag = tk.Frame(frame, bg=FUNDO); linha_ag.pack(fill="x", padx=16, pady=(6, 2))
        tk.Checkbutton(linha_ag, text="Ativar modo agente", variable=var_ag,
            command=aplicar_ag, bg=FUNDO, fg=TEXTO, selectcolor=FUNDO_CAIXA,
            activebackground=FUNDO, activeforeground=TEXTO, anchor="w",
            highlightthickness=0).pack(side="left")
        tk.Label(linha_ag, text="  passos/mensagem:", bg=FUNDO, fg=CINZA,
                 font=("DejaVu Sans", 9)).pack(side="left")
        entrada_max = tk.Entry(linha_ag, textvariable=var_max, width=3, bg=FUNDO_CAIXA,
            fg=TEXTO, bd=0, insertbackground=TEXTO, highlightthickness=1,
            highlightbackground=BORDA)
        entrada_max.pack(side="left", padx=4, ipady=2)
        entrada_max.bind("<FocusOut>", lambda e: aplicar_ag())
        entrada_max.bind("<Return>", lambda e: aplicar_ag())

        titulo("Aprendizado")
        var_ativo = tk.BooleanVar(value=self.cfg["aprender"])
        vars_cat = {c: tk.BooleanVar(value=c in self.cfg["categorias"]) for c in CATEGORIAS}
        def aplicar():
            self.cfg["aprender"] = var_ativo.get()
            self.cfg["categorias"] = [c for c, v in vars_cat.items() if v.get()]
            salvar_config(aprender=self.cfg["aprender"], categorias=self.cfg["categorias"])
            for cb in cbs: cb.config(state="normal" if var_ativo.get() else "disabled")
        def check(pai, texto, var):
            return tk.Checkbutton(pai, text=texto, variable=var, command=aplicar,
                bg=FUNDO, fg=TEXTO, selectcolor=FUNDO_CAIXA, activebackground=FUNDO,
                activeforeground=TEXTO, disabledforeground=CINZA, anchor="w",
                highlightthickness=0, bd=0, font=("DejaVu Sans", 10))
        check(frame, "Permitir sugestões", var_ativo).pack(fill="x", padx=16, pady=(6, 0))
        cbs = []
        for c, nome in CATEGORIAS.items():
            cb = check(frame, nome, vars_cat[c]); cb.pack(fill="x", padx=40); cbs.append(cb)
        estado = "normal" if var_ativo.get() else "disabled"
        for cb in cbs: cb.config(state=estado)

        titulo("Memória")
        quadro = tk.Frame(frame, bg=FUNDO)
        quadro.pack(fill="both", expand=True, padx=16, pady=6)
        lista = tk.Listbox(quadro, bg=FUNDO_CAIXA, fg=TEXTO, bd=0, height=5,
                           highlightthickness=1, highlightbackground=BORDA,
                           selectbackground=BORDA, selectforeground=TEXTO,
                           activestyle="none", exportselection=False,
                           font=("DejaVu Sans", 10))
        lista.pack(fill="both", expand=True)
        def recarregar():
            lista.delete(0, "end")
            for x in self.memoria.itens: lista.insert("end", x["texto"])
        def apagar():
            sel = lista.curselection()
            if sel: self.memoria.remover(sel[0] + 1); recarregar()
        def adicionar():
            t = novo.get().strip()
            if t: self.memoria.adicionar(t); novo.delete(0, "end"); recarregar()
        linha2 = tk.Frame(frame, bg=FUNDO); linha2.pack(fill="x", padx=16, pady=(0, 14))
        novo = tk.Entry(linha2, bg=FUNDO_CAIXA, fg=TEXTO, bd=0, insertbackground=TEXTO,
                        highlightthickness=1, highlightbackground=BORDA,
                        highlightcolor=DESTAQUE, font=("DejaVu Sans", 10))
        novo.pack(side="left", fill="x", expand=True, ipady=4)
        novo.bind("<Return>", lambda e: adicionar())
        self._botao(linha2, "Adicionar", adicionar, destaque=True).pack(side="left", padx=6)
        self._botao(linha2, "Excluir selecionada", apagar).pack(side="left")
        recarregar()

    def enviar(self, _evento=None):
        if self.ocupado: return "break"
        texto = self.entrada.get("1.0", "end").strip()
        if not texto and not self.anexos: return "break"
        self.entrada.delete("1.0", "end")
        if texto.startswith("/"):
            self.comando(texto); return "break"
        if not self.obter_chave() and self.cfg["provider"] != "ollama":
            self.escrever("Falta a chave da API. Abra Personalidade e memória.\n\n", "erro")
            return "break"
        if not self.atual["mensagens"]:
            self._limpar_chat()
            if self.atual["id"] and self.atual["titulo"] == TITULO_NOVO:
                self.atual["titulo"] = self._titulo_de(texto or "Anexos")
                self.chats.salvar(self.atual); self.atualizar_lista(); self._atualizar_topo()
        msg = {"role": "user", "content": texto or "(sem texto)"}
        if self.anexos:
            msg["anexos"] = list(self.anexos)
            self.anexos.clear(); self._atualizar_anexos()
        with self._editar():
            self.chat.insert("end", "Você\n", "rotulo")
            sufixo = "  [anexos: " + ", ".join(a["nome"] for a in msg.get("anexos") or []) + "]" if msg.get("anexos") else ""
            self.chat.insert("end", (texto or "(sem texto)") + sufixo + "\n\n", "voce")
            self.chat.insert("end", "Assistente\n", "rotulo")
            self.chat.mark_set("inicio_resp", "end-1c")
            self.chat.mark_gravity("inicio_resp", "left")
        self.chat.see("end")
        self.atual["mensagens"].append(msg)
        if self.atual["id"] is None:
            self.chats.salvar_sessao(self.atual["mensagens"])
        self.ocupado = True; self.resposta = ""; self._mostrado = 0
        self.agente_passos = 0; self.n_trechos = self.n_raciocinio = 0
        self.t_inicio = time.time(); self.t_primeira = 0.0
        mensagens = ([{"role": "system", "content": self.montar_sistema()}]
                     + self.mensagens_api())
        threading.Thread(target=self.pedir,
                         args=(mensagens, self.obter_modelo(), dict(self.cfg["extra"])),
                         daemon=True).start()
        return "break"

    def pedir(self, mensagens, modelo, extra):
        prov = PROVIDERS[self.cfg["provider"]]
        chave = self.obter_chave()
        formato = prov["formato"]
        base = prov["base_url"].rstrip("/")
        if formato == "anthropic":
            url = base + "/messages"
            corpo = _montar_anthropic(mensagens, modelo, extra)
            cabecalhos = {"x-api-key": chave,
                          "anthropic-version": "2023-06-01",
                          "Content-Type": "application/json",
                          "Accept": "text/event-stream"}
        else:
            url = base + "/chat/completions"
            corpo = {"model": modelo, "messages": mensagens, "stream": True,
                     "max_tokens": 1024, "temperature": 0.5}
            corpo.update(extra)
            cabecalhos = {"Authorization": f"Bearer {chave}",
                          "Content-Type": "application/json",
                          "Accept": "text/event-stream"}
        try:
            r = self.cliente.abrir(url, cabecalhos, json.dumps(corpo).encode("utf-8"))
            if r.status != 200:
                detalhe = r.read().decode("utf-8", errors="ignore")[:400]
                self.fila.put(("erro", f"Erro HTTP {r.status} ({prov['nome']}): {detalhe}"))
                return
            if formato == "anthropic":
                self._stream_anthropic(r)
            else:
                self._stream_openai(r)
            r.read()
            self.fila.put(("fim", None))
        except Exception as e:
            self.cliente.fechar(); self.fila.put(("erro", f"Erro: {e}"))

    def _stream_openai(self, r):
        for linha in r:
            linha = linha.decode("utf-8", errors="ignore").strip()
            if not linha.startswith("data:"): continue
            dado = linha[5:].strip()
            if dado == "[DONE]": break
            try: escolhas = json.loads(dado).get("choices") or []
            except ValueError: continue
            if not escolhas: continue
            delta = escolhas[0].get("delta") or {}
            if delta.get("content"): self.fila.put(("trecho", delta["content"]))
            elif delta.get("reasoning_content") or delta.get("reasoning"):
                self.fila.put(("raciocinio", None))

    def _stream_anthropic(self, r):
        for linha in r:
            linha = linha.decode("utf-8", errors="ignore").strip()
            if not linha.startswith("data:"): continue
            dado = linha[5:].strip()
            if not dado: continue
            try: ev = json.loads(dado)
            except ValueError: continue
            t = ev.get("type")
            if t == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta":
                    txt = delta.get("text") or ""
                    if txt: self.fila.put(("trecho", txt))
                elif delta.get("type") == "thinking_delta":
                    self.fila.put(("raciocinio", None))
            elif t == "message_stop":
                break

    def processar_fila(self):
        try:
            while True:
                tipo, valor = self.fila.get_nowait()
                if tipo == "alternar": self.alternar()
                elif tipo == "screenshot": self._processar_screenshot(valor)
                elif tipo == "voz": self._processar_voz(valor)
                elif tipo == "voz_erro": self._erro_voz(valor)
                elif tipo == "fim_fala": self._fim_fala()
                elif tipo == "raciocinio": self.n_raciocinio += 1
                elif tipo == "trecho":
                    if not self.n_trechos: self.t_primeira = time.time() - self.t_inicio
                    self.n_trechos += 1; self.resposta += valor
                    visivel = self.resposta.split("[[", 1)[0]
                    novo = visivel[self._mostrado:]
                    if novo: self.escrever(novo, "ia"); self._mostrado = len(visivel)
                elif tipo == "fim": self._concluir()
                elif tipo == "acao_resultado":
                    self._render_resultado(valor); self.agente_passo_concluido(continuar=True)
                elif tipo == "erro":
                    self.escrever(f"\n{valor}\n\n", "erro")
                    if self.atual["mensagens"] and self.atual["mensagens"][-1]["role"] == "user":
                        self.atual["mensagens"].pop()
                    self._terminar("")
        except queue.Empty: pass
        self.root.after(50, self.processar_fila)

    def _concluir(self):
        bruto = self.resposta
        m_ag = RE_AGENTE.search(bruto); bloco_agente = None
        if m_ag:
            try: bloco_agente = json.loads(m_ag.group(2).strip())
            except ValueError as e:
                self.escrever(f"JSON do agente inválido: {e}\n\n", "erro")
                bloco_agente = None
        sugestoes = [s.strip() for s in RE_LEMBRAR.findall(bruto)]
        limpo = RE_LEMBRAR.sub("", bruto).rstrip()
        if m_ag: limpo = (limpo[:m_ag.start()] + limpo[m_ag.end():]).rstrip()
        with self._editar():
            self.chat.delete("inicio_resp", "end-1c")
            if limpo.strip(): self._render_md(limpo)
            self._nova_linha(); self.chat.insert("end", "\n")
        self.chat.see("end")
        total = time.time() - self.t_inicio
        if not limpo.strip() and not bloco_agente:
            motivo = ("O modelo só mandou raciocínio." if self.n_raciocinio
                      else "O modelo não devolveu texto.")
            self.escrever(motivo + " Tente de novo ou troque com /modelo.\n\n", "erro")
            if self.atual["mensagens"] and self.atual["mensagens"][-1]["role"] == "user":
                self.atual["mensagens"].pop()
            self._terminar(""); return
        if limpo.strip():
            self.atual["mensagens"].append({"role": "assistant", "content": limpo})
            if self.atual["id"]: self.chats.salvar(self.atual)
            else: self.chats.salvar_sessao(self.atual["mensagens"])
        stats = (f"{PROVIDERS[self.cfg['provider']]['nome'].split()[0]} · "
                 f"1ª palavra {self.t_primeira:.1f}s · total {total:.1f}s · "
                 f"{self.n_trechos} tokens")
        if self.n_raciocinio: stats += f" · raciocínio {self.n_raciocinio}"
        self.lbl_stats.config(text=stats)
        if bloco_agente is not None and self.cfg["agente_ativo"]:
            self._card_acao(bloco_agente); return
        self._terminar(stats)
        if (sugestoes and self.cfg["aprender"]
                and not any(sugestoes[0].lower() == i["texto"].lower()
                            for i in self.memoria.itens)):
            self._sugestao(sugestoes[0][:160])
        if self.cfg.get("auto_falar") and limpo.strip():
            self._falar_async(self._limpar_md_para_fala(limpo))

    def _sugestao(self, texto):
        quadro = tk.Frame(self.chat, bg=FUNDO_CAIXA, highlightthickness=1,
                          highlightbackground=BORDA)
        lbl = tk.Label(quadro, text=f"Guardar na memória?  \"{texto}\"", bg=FUNDO_CAIXA,
                       fg=TEXTO, wraplength=480, justify="left", font=("DejaVu Sans", 10))
        lbl.pack(side="left", padx=8, pady=6)
        botoes = []
        def fechar(msg):
            lbl.config(text=msg, fg=CINZA)
            for b in botoes: b.destroy()
        def sim(): self.memoria.adicionar(texto); fechar("Anotado")
        b_nao = self._botao(quadro, "Não", lambda: fechar("Ok, não guardei."))
        b_sim = self._botao(quadro, "Sim", sim, destaque=True)
        b_nao.pack(side="right", padx=(0, 8), pady=4)
        b_sim.pack(side="right", padx=4, pady=4)
        botoes.extend([b_sim, b_nao]); self.janelas.append(quadro)
        with self._editar():
            self._nova_linha()
            self.chat.window_create("end-1c", window=quadro, padx=4, pady=2)
            self.chat.insert("end", "\n\n")
        self.chat.see("end")

    def _terminar(self, stats):
        self.ocupado = False
        if stats: self.lbl_stats.config(text=stats)

    def _tic(self):
        if self.ocupado:
            dt = time.time() - self.t_inicio
            if self.n_trechos: txt = f"Escrevendo... {self.n_trechos} tokens · {dt:.1f}s"
            elif self.n_raciocinio: txt = f"Raciocinando... {dt:.1f}s"
            else: txt = f"Esperando... {dt:.1f}s"
            self.lbl_stats.config(text=txt)
        self.root.after(200, self._tic)

    def _loop_tempo_real(self):
        caminho = "/tmp/assistente_ultimo.png"
        while not self._parar_tempo_real.is_set():
            intervalo = int(self.cfg.get("tempo_real_segundos", 0))
            if intervalo <= 0:
                self._parar_tempo_real.wait(2); continue
            try:
                c = capturar_tela()
                if c and c != caminho:
                    try: os.replace(c, caminho)
                    except OSError: pass
            except Exception: pass
            self._parar_tempo_real.wait(intervalo)

    def rodar(self):
        threading.Thread(target=servidor, args=(self.fila,), daemon=True).start()
        threading.Thread(target=self._loop_tempo_real, daemon=True).start()
        try: self.root.mainloop()
        finally:
            self._parar_tempo_real.set()
            try: os.remove(SOCKET)
            except OSError: pass


def pedir_alternar():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(SOCKET); s.sendall(b"toggle"); return True
    except OSError: return False
    finally: s.close()


def servidor(fila):
    try: os.remove(SOCKET)
    except OSError: pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET); srv.listen(1)
    while True:
        conn, _ = srv.accept()
        with conn: conn.recv(16)
        fila.put(("alternar", None))


def main():
    if pedir_alternar(): return
    App().rodar()


if __name__ == "__main__":
    main()

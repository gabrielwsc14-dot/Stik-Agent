#!/usr/bin/env python3
"""Assistente rápido: uma janela de chat que abre e fecha com um atalho de teclado.

Como funciona o atalho: o programa roda em segundo plano. Você cadastra um atalho
nas configurações do seu desktop que executa `python3 assistente.py`. Se o
assistente já estiver aberto, esse comando só manda um aviso pra ele mostrar ou
esconder a janela. Isso funciona tanto em X11 quanto em Wayland.

Chave da API (NVIDIA): fica FORA do código, para nunca ir parar no GitHub. O programa
procura primeiro a variável NVIDIA_API_KEY e depois o arquivo
~/.config/assistente/config.json ({"chave": "nvapi-...", "modelo": "..."}).
Se não achar nenhum, pergunta a chave numa caixinha na primeira vez e salva sozinho.
"""
import json
import os
import queue
import socket
import threading
import tkinter as tk
from tkinter import simpledialog
import urllib.error
import urllib.request

API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODELO_PADRAO = "google/gemma-4-31b-it"
CONFIG = os.path.join(os.path.expanduser("~"), ".config", "assistente", "config.json")
SOCKET = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "assistente.sock")

PROMPT_SISTEMA = (
    "Você é um assistente rápido que fica a um atalho de teclado de distância, "
    "num computador Linux. Responda em português, de forma curta e direta. "
    "Quando mostrar comandos ou código, use texto simples e explique em poucas palavras."
)

# Cores (tema escuro)
FUNDO = "#1e1e2e"
FUNDO_CAIXA = "#2a2a3d"
TEXTO = "#cdd6f4"
CINZA = "#7f849c"
DESTAQUE = "#89b4fa"
VERDE = "#a6e3a1"
VERMELHO = "#f38ba8"


def carregar_config():
    cfg = {"chave": os.environ.get("NVIDIA_API_KEY", ""), "modelo": MODELO_PADRAO}
    try:
        with open(CONFIG, encoding="utf-8") as f:
            dados = json.load(f)
        cfg["chave"] = dados.get("chave") or cfg["chave"]
        cfg["modelo"] = dados.get("modelo") or cfg["modelo"]
    except (OSError, ValueError):
        pass
    return cfg


def salvar_chave(chave):
    """Guarda a chave em ~/.config/assistente/config.json (só o dono lê o arquivo)."""
    dados = {}
    try:
        with open(CONFIG, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        pass
    dados["chave"] = chave
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2)
    os.chmod(CONFIG, 0o600)


def pedir_alternar():
    """Se já existe um assistente rodando, manda ele mostrar/esconder a janela."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(SOCKET)
        s.sendall(b"toggle")
        return True
    except OSError:
        return False
    finally:
        s.close()


def servidor(fila):
    """Fica escutando os avisos de 'alternar' vindos de novas execuções."""
    try:
        os.remove(SOCKET)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET)
    srv.listen(1)
    while True:
        conn, _ = srv.accept()
        with conn:
            conn.recv(16)
        fila.put(("alternar", None))


class App:
    def __init__(self):
        self.cfg = carregar_config()
        self.historico = []  # sem a mensagem de sistema
        self.fila = queue.Queue()
        self.ocupado = False
        self.resposta = ""

        self.root = tk.Tk()
        self.root.title("Assistente")
        self.root.configure(bg=FUNDO)
        self.root.attributes("-topmost", True)
        largura, altura = 720, 520
        x = (self.root.winfo_screenwidth() - largura) // 2
        y = self.root.winfo_screenheight() // 6
        self.root.geometry(f"{largura}x{altura}+{x}+{y}")
        self.root.minsize(420, 320)

        if not self.cfg["chave"]:  # primeira execução: pergunta a chave uma vez só
            self.root.withdraw()
            chave = simpledialog.askstring(
                "Assistente", "Cole sua chave da NVIDIA (começa com nvapi-):", parent=self.root
            )
            if chave and chave.strip():
                self.cfg["chave"] = chave.strip()
                salvar_chave(self.cfg["chave"])

        self.montar_interface()

        self.root.protocol("WM_DELETE_WINDOW", self.esconder)
        self.root.bind("<Escape>", lambda e: self.esconder())
        self.root.bind("<Control-l>", lambda e: self.limpar())
        self.root.after(50, self.processar_fila)
        self.mostrar()

    def montar_interface(self):
        fonte = ("DejaVu Sans", 11)

        quadro = tk.Frame(self.root, bg=FUNDO)
        quadro.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        barra = tk.Scrollbar(quadro)
        barra.pack(side="right", fill="y")
        self.chat = tk.Text(
            quadro, wrap="word", bg=FUNDO, fg=TEXTO, font=fonte, bd=0, height=1,
            highlightthickness=0, padx=6, pady=6, state="disabled",
            yscrollcommand=barra.set, cursor="arrow",
        )
        self.chat.pack(side="left", fill="both", expand=True)
        barra.config(command=self.chat.yview)
        self.chat.tag_config("rotulo", foreground=DESTAQUE, font=(fonte[0], 9, "bold"))
        self.chat.tag_config("voce", foreground=VERDE)
        self.chat.tag_config("ia", foreground=TEXTO)
        self.chat.tag_config("erro", foreground=VERMELHO)
        self.chat.tag_config("dica", foreground=CINZA, font=(fonte[0], 9))

        self.entrada = tk.Text(
            self.root, height=3, wrap="word", bg=FUNDO_CAIXA, fg=TEXTO,
            insertbackground=TEXTO, font=fonte, bd=0, highlightthickness=1,
            highlightbackground=FUNDO_CAIXA, highlightcolor=DESTAQUE, padx=8, pady=8,
        )
        self.entrada.pack(fill="x", padx=12, pady=(0, 4))
        self.entrada.bind("<Return>", self.enviar)
        self.entrada.bind("<Shift-Return>", lambda e: None)  # quebra de linha normal

        self.status = tk.Label(
            self.root, text="Enter envia · Shift+Enter nova linha · Ctrl+L limpa · Esc esconde",
            bg=FUNDO, fg=CINZA, font=(fonte[0], 9), anchor="w",
        )
        self.status.pack(fill="x", padx=14, pady=(0, 8))

        if not self.cfg["chave"]:
            self.escrever(
                "Falta a chave da API. Gere uma em build.nvidia.com e defina a variável "
                "NVIDIA_API_KEY (ou crie ~/.config/assistente/config.json com "
                '{"chave": "nvapi-..."}). Depois abra o assistente de novo.\n\n',
                "erro",
            )

    # ---------- janela ----------
    def mostrar(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.entrada.focus_set()

    def esconder(self):
        self.root.withdraw()

    def alternar(self):
        if self.root.state() == "withdrawn":
            self.mostrar()
        else:
            self.esconder()

    # ---------- chat ----------
    def escrever(self, texto, tag):
        self.chat.config(state="normal")
        self.chat.insert("end", texto, tag)
        self.chat.config(state="disabled")
        self.chat.see("end")

    def limpar(self):
        if self.ocupado:
            return
        self.historico.clear()
        self.chat.config(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.config(state="disabled")

    def enviar(self, _evento=None):
        if self.ocupado:
            return "break"
        texto = self.entrada.get("1.0", "end").strip()
        if not texto:
            return "break"
        if not self.cfg["chave"]:
            self.escrever("Configure a chave da API primeiro (veja a mensagem acima).\n\n", "erro")
            return "break"

        self.entrada.delete("1.0", "end")
        self.escrever("Você\n", "rotulo")
        self.escrever(texto + "\n\n", "voce")
        self.escrever("Assistente\n", "rotulo")

        self.historico.append({"role": "user", "content": texto})
        self.ocupado = True
        self.resposta = ""
        self.status.config(text="Pensando...")
        mensagens = [{"role": "system", "content": PROMPT_SISTEMA}] + self.historico[-20:]
        threading.Thread(target=self.pedir, args=(mensagens,), daemon=True).start()
        return "break"

    def pedir(self, mensagens):
        """Roda numa thread: chama a API da NVIDIA e manda os pedaços pra fila."""
        corpo = json.dumps({
            "model": self.cfg["modelo"],
            "messages": mensagens,
            "stream": True,
            "max_tokens": 1024,
            "temperature": 0.5,
        }).encode("utf-8")
        req = urllib.request.Request(
            API_URL, data=corpo,
            headers={
                "Authorization": f"Bearer {self.cfg['chave']}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                for linha in r:
                    linha = linha.decode("utf-8", errors="ignore").strip()
                    if not linha.startswith("data:"):
                        continue
                    dado = linha[5:].strip()
                    if dado == "[DONE]":
                        break
                    escolhas = json.loads(dado).get("choices") or []
                    if not escolhas:
                        continue
                    trecho = escolhas[0].get("delta", {}).get("content")
                    if trecho:
                        self.fila.put(("trecho", trecho))
            self.fila.put(("fim", None))
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode("utf-8", errors="ignore")[:300]
            self.fila.put(("erro", f"Erro HTTP {e.code}: {detalhe}"))
        except Exception as e:  # rede, timeout, JSON quebrado...
            self.fila.put(("erro", f"Erro: {e}"))

    def processar_fila(self):
        """Roda na thread principal; é o único lugar que mexe na interface."""
        try:
            while True:
                tipo, valor = self.fila.get_nowait()
                if tipo == "alternar":
                    self.alternar()
                elif tipo == "trecho":
                    self.resposta += valor
                    self.escrever(valor, "ia")
                elif tipo == "fim":
                    self.historico.append({"role": "assistant", "content": self.resposta})
                    self.escrever("\n\n", "ia")
                    self.terminar()
                elif tipo == "erro":
                    self.escrever(f"\n{valor}\n\n", "erro")
                    if self.historico and self.historico[-1]["role"] == "user":
                        self.historico.pop()  # deixa tentar de novo
                    self.terminar()
        except queue.Empty:
            pass
        self.root.after(50, self.processar_fila)

    def terminar(self):
        self.ocupado = False
        self.status.config(
            text="Enter envia · Shift+Enter nova linha · Ctrl+L limpa · Esc esconde"
        )

    def rodar(self):
        threading.Thread(target=servidor, args=(self.fila,), daemon=True).start()
        try:
            self.root.mainloop()
        finally:
            try:
                os.remove(SOCKET)
            except OSError:
                pass


def main():
    if pedir_alternar():
        return
    App().rodar()


if __name__ == "__main__":
    main()

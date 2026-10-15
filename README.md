# Assistente

Agente de IA de código aberto para Linux. Fica a um atalho de teclado de distância,
vê sua tela, executa comandos, lê e edita arquivos, guarda memória, tem voz e aceita
o provedor de IA que você quiser — **cada usuário usa a própria chave**.

![screenshot](docs/screenshot.png)

## Por que existe

Assistentes de IA como o Gemini são ótimos, mas:
- Ficam presos no navegador ou no celular
- Não agem no seu computador de verdade
- Não deixam você escolher o provedor

Este projeto é um **agente local** que roda no seu Linux, com a interface que você
quiser, agindo no sistema com a sua aprovação, e usando o provedor que você preferir.

## Provedores suportados

Cole a chave e o prefixo identifica o provedor automaticamente.

| Provedor | Prefixo da chave | Visão | Como obter |
|---|---|---|---|
| **NVIDIA** | `nvapi-` | ✅ | https://build.nvidia.com |
| **Google Gemini** | `AIza` | ✅ | https://aistudio.google.com/apikey |
| **OpenAI** | `sk-` | ✅ | https://platform.openai.com/api-keys |
| **Anthropic Claude** | `sk-ant-` | ✅ | https://console.anthropic.com/settings/keys |
| **Groq** | `gsk_` | ❌ | https://console.groq.com/keys |
| **DeepSeek** | `sk-` | ❌ | https://platform.deepseek.com/api_keys |
| **OpenRouter** | `sk-or-` | ✅ | https://openrouter.ai/keys |
| **Ollama (local)** | *(vazio)* | ❌ | https://ollama.com — rode `ollama serve` |

Para trocar de provedor depois de configurado:

- No chat: `/provedor <id>` (ex.: `/provedor anthropic`)
- Ou via **Personalidade e memória** → **Provedor de IA**

A chave fica em `~/.config/assistente/config.json` (permissão 600), fora do projeto.

## Instalar

```bash
sudo apt install python3-tk scrot zenity
git clone https://github.com/SEU_USUARIO/assistente
cd assistente
python3 assistente_dev.py

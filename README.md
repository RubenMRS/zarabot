# Zara Telegram Monitor 🛍️🤖

Este projeto é um simples bot para o Telegram desenhado para monitorizar produtos da Zara.
Ele verifica automaticamente alterações de preços (promoções) e regressos ao stock (tamanhos esgotados ou disponíveis). 

Tudo isto acontece num pequeno script que não requer Docker, Bases de Dados complexas ou APIs próprias. Um ficheiro simples `products.json` faz a persistência da informação de forma segura.

---

## 🛠️ Requisitos Iniciais

Pelas verificações feitas na tua máquina local (Windows), parece que **não tens o Python instalado**, ou não está configurado no teu PATH. É obrigatório instalares o Python antes de continuares.

1. Instala o Python através da [Página Oficial (Python.org)](https://www.python.org/downloads/) ou da Microsoft Store (pesquisa por "Python 3.11").
2. Durante a instalação do Python.org, certifica-te que ativas a opção **"Add Python to PATH"** na parte inferior da primeira janela.
3. Depois de instalares, abre um **novo** terminal (PowerShell ou CMD) e verifica se já funciona digitando:
   `python --version`

---

## 🚀 Como Configurar o Projeto

Assim que tiveres o Python pronto:

### 1. Instalar as dependências

No terminal, dentro da pasta deste projeto (`Desktop\Bot_Telegram_Precos`), corre os seguintes comandos:

```bash
pip install -r requirements.txt
playwright install chromium
```

> **Nota importante:** O `playwright install chromium` é vital. Ele descarrega uma versão embutida do Chromium que será usada automaticamente pelo código para contornar a forte proteção antibot da Zara.

### 2. Configurar o Bot do Telegram

1. Vai ao Telegram e pesquisa por **@BotFather**.
2. Envia-lhe o comando `/newbot` e segue os passos para criar um novo Bot e atribuir um nome.
3. No final, o BotFather dar-te-á um **Token HTTP API** (Exemplo: `123456789:ABCdefGHIjkl...`).

Configura este token no Windows como uma variável de ambiente, ou adiciona temporariamente no terminal antes de arrancar o bot:

**No PowerShell (sessão atual):**
```powershell
$env:TELEGRAM_BOT_TOKEN="O_TEU_TOKEN_AQUI"
```

### 3. Iniciar o Bot

Basta correr o ficheiro base:

```bash
python bot.py
```

O teu bot ficará online e passará a ler os comandos através do chat!

---

## 💬 Comandos Disponíveis (no Telegram)

* `/start` - Mostra a mensagem de boas vindas
* `/adicionar URL` - Regista imediatamente um URL da Zara e guarda o estado inicial (Preço e Tamanhos)
* `/lista` - Vê um resumo de todos os produtos que tens no teu carrinho de monitorização
* `/estado ID` - Verifica detalhes profundos de stock (qual o tamanho 🔴 e qual o 🟢)
* `/remover ID` - Apaga o produto da base de dados

---

## 📂 Arquitetura

O código manteve-se simples e focado no objetivo, tal como pedido:
- `bot.py`: Trata a interface de chat com o telegram, processa comandos, e tem a rotina que corre a cada 5 minutos.
- `scraper.py`: Classe modular focada 100% na recolha de dados da Zara. Usa Playwright em background (headless) e lê a estrutura HTML moderna deles.
- `products.json`: Ficheiro autogerido onde a informação é guardada.
- `requirements.txt`: Lista simples dos pacotes pip.

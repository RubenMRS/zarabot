import os
import json
import re
import logging
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import nest_asyncio

from scraper import ZaraScraper

# Aplicar patch para event loops aninhados (útil se o Playwright e o Telegram conflituarem)
nest_asyncio.apply()

# Configuração de Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configurações
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8754329836:AAG83B88RzTqVB1soc2vqzbtaub4ETM7LAQ")
DB_FILE = "products.json"
CHECK_INTERVAL = 300  # Segundos (5 minutos)

# Instância global do Scraper (assim reutilizamos o browser entre as verificações)
scraper = ZaraScraper()

def load_products():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_products(products):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=4, ensure_ascii=False)

def get_next_id(products):
    if not products:
        return "1"
    ids = [int(k) for k in products.keys()]
    return str(max(ids) + 1)

def format_sizes_text(sizes):
    text = ""
    for size, available in sizes.items():
        icon = "🟢" if available else "🔴"
        text += f"{size} {icon}\n"
    return text

def resolve_zara_url(user_input: str) -> str:
    user_input = user_input.strip()
    if user_input.startswith("http://") or user_input.startswith("https://"):
        return user_input
    
    # É uma referência! Ex: 4772/354/717, 4772/354 ou 04772354
    digits = re.sub(r'\D', '', user_input)
    if not digits:
        return user_input
        
    if len(digits) >= 7:
        if digits.startswith("0") and len(digits) >= 8:
            code = digits[:8]
        elif len(digits) == 7:
            code = "0" + digits
        else:
            code = "0" + digits[:7]
            
        return f"https://www.zara.com/pt/pt/-p{code}.html"
        
    return user_input

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = (
        "Olá! Sou o teu Monitor da Zara. Criado pelo teu namoradinho  🛍️\n\n"
        "Comandos disponíveis:\n"
        "/adicionar [URL ou Referência] - Adiciona um produto (ex: 4772/354/717 ou link)\n"
        "/lista - Mostra os produtos atuais\n"
        "/estado [ID] - Vê o estado de um produto\n"
        "/remover [ID] - Para de monitorizar um produto"
    )
    await update.message.reply_text(welcome_message)

async def adicionar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Por favor envia o URL ou Referência. Exemplo:\n/adicionar https://www.zara.com/...\nou\n/adicionar 4772/354/717")
        return
    
    try:
        raw_input = context.args[0]
        url = resolve_zara_url(raw_input)
        
        await update.message.reply_text(f"⏳ A analisar o produto ({url}), isto pode demorar alguns segundos...")
        
        data = await scraper.get_product_data(url)
        if not data:
            await update.message.reply_text("❌ Não foi possível obter os dados deste URL. Verifica se é um link válido da Zara e tenta novamente.")
            return
            
        products = load_products()
        new_id = get_next_id(products)
        
        # Guardar no DB
        products[new_id] = {
            "url": url,
            "name": data["name"],
            "price": data["price"],
            "sizes": data["sizes"],
            "chat_id": chat_id,
            "last_check": datetime.now().isoformat()
        }
        save_products(products)
        
        msg = (
            f"✅ Produto adicionado! (ID: {new_id})\n\n"
            f"👗 {data['name']}\n"
            f"💰 {str(data['price']).replace('.', ',')} €\n\n"
            f"📦 Stock:\n{format_sizes_text(data['sizes'])}\n"
            f"🔔 Vou começar a monitorizar."
        )
        await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"Erro no comando /adicionar: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ocorreu um erro: {e}")

async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    products = load_products()
    
    user_products = {k: v for k, v in products.items() if v.get("chat_id") == chat_id}
    
    if not user_products:
        await update.message.reply_text("Não tens produtos a ser monitorizados.")
        return
        
    msg = "👗 Produtos monitorizados\n\n"
    for pid, p in user_products.items():
        msg += f"{pid} — {p['name']}\n"
        msg += f"💰 {str(p['price']).replace('.', ',')} €\n"
        # Mostrar o primeiro tamanho disponível, se houver
        available = [s for s, a in p['sizes'].items() if a]
        if available:
            msg += f"Tamanhos disponíveis: {', '.join(available)}\n"
        else:
            msg += "🔴 Tudo esgotado\n"
        msg += "\n"
        
    await update.message.reply_text(msg)

async def estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Indica o ID do produto. Exemplo: /estado 1")
        return
        
    pid = context.args[0]
    products = load_products()
    
    if pid not in products or products[pid].get("chat_id") != chat_id:
        await update.message.reply_text("❌ Produto não encontrado ou não te pertence.")
        return
        
    p = products[pid]
    msg = (
        f"👗 {p['name']}\n"
        f"💰 {str(p['price']).replace('.', ',')} €\n\n"
        f"📦 Stock Atual:\n{format_sizes_text(p['sizes'])}\n"
        f"🔗 [Ver na Zara]({p['url']})"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)

async def remover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Indica o ID do produto. Exemplo: /remover 1")
        return
        
    pid = context.args[0]
    products = load_products()
    
    if pid not in products or products[pid].get("chat_id") != chat_id:
        await update.message.reply_text("❌ Produto não encontrado ou não te pertence.")
        return
        
    del products[pid]
    save_products(products)
    await update.message.reply_text(f"✅ Produto {pid} removido com sucesso!")

# --- MONITORIZAÇÃO EM BACKGROUND ---

async def monitor_products(context: ContextTypes.DEFAULT_TYPE):
    products = load_products()
    if not products:
        return
        
    logger.info(f"A iniciar ciclo de monitorização para {len(products)} produtos...")
    
    for pid, p in products.items():
        url = p["url"]
        chat_id = p["chat_id"]
        
        logger.info(f"A verificar produto {pid}: {p['name']}")
        
        # Intervalo pequeno para não sobrecarregar a Zara caso haja muitos produtos
        await asyncio.sleep(2)
        
        new_data = await scraper.get_product_data(url)
        if not new_data:
            logger.error(f"Falha ao obter produto {pid}, tentando na próxima.")
            continue
            
        old_price = p["price"]
        new_price = new_data["price"]
        old_sizes = p["sizes"]
        new_sizes = new_data["sizes"]
        
        changed = False
        
        # Comparar Preço
        if old_price != new_price:
            if new_price < old_price:
                # Promoção!
                desconto = round(((old_price - new_price) / old_price) * 100)
                msg = (
                    f"🔥 PROMOÇÃO!\n\n"
                    f"👗 {p['name']}\n"
                    f"💰 {str(old_price).replace('.', ',')} € → {str(new_price).replace('.', ',')} €\n"
                    f"📉 -{desconto}%\n\n"
                    f"🔗 [Ver na Zara]({url})"
                )
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
            else:
                # Preço subiu
                msg = (
                    f"📈 Preço Aumentou!\n\n"
                    f"👗 {p['name']}\n"
                    f"💰 Agora custa {str(new_price).replace('.', ',')} €\n\n"
                    f"🔗 [Ver na Zara]({url})"
                )
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
            
            p["price"] = new_price
            changed = True
            
        # Comparar Stock (Tamanhos)
        for size, is_available in new_sizes.items():
            was_available = old_sizes.get(size, False)
            
            if is_available and not was_available:
                # Voltou ao stock!
                msg = (
                    f"🚨 STOCK DISPONÍVEL!\n\n"
                    f"👗 {p['name']}\n"
                    f"📏 Tamanho: {size}\n"
                    f"💰 {str(new_price).replace('.', ',')} €\n\n"
                    f"🔗 [Ver na Zara]({url})"
                )
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                changed = True
            elif not is_available and was_available:
                # Esgotou
                msg = (
                    f"❌ Esgotado!\n\n"
                    f"👗 {p['name']}\n"
                    f"📏 Tamanho {size} ficou esgotado.\n\n"
                    f"🔗 [Ver na Zara]({url})"
                )
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                changed = True
                
        if changed:
            p["sizes"] = new_sizes
            p["last_check"] = datetime.now().isoformat()
            save_products(products)
        else:
            logger.info("Sem alterações.")

# --- SERVER DUMMY PARA O RENDER ---
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    class DummyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot da Zara esta a correr!")
    
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    logger.info(f"Dummy server a ouvir na porta {port}")
    server.serve_forever()

if __name__ == '__main__':
    if not TOKEN:
        logger.error("A variável de ambiente TELEGRAM_BOT_TOKEN não está definida!")
        exit(1)
        
    # Iniciar o dummy server numa thread separada se a variável PORT estiver definida (Render)
    if "PORT" in os.environ:
        threading.Thread(target=run_dummy_server, daemon=True).start()
        
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('adicionar', adicionar))
    application.add_handler(CommandHandler('lista', lista))
    application.add_handler(CommandHandler('estado', estado))
    application.add_handler(CommandHandler('remover', remover))
    
    # Adicionar o job para correr a cada X segundos
    # A monitorização vai usar o JobQueue do python-telegram-bot
    job_queue = application.job_queue
    job_queue.run_repeating(monitor_products, interval=CHECK_INTERVAL, first=10)
    
    logger.info("Bot da Zara Monitor iniciado!")
    
    # Para garantir o encerramento correto do Playwright
    async def on_shutdown(app):
        await scraper.stop()
        
    application.post_shutdown = on_shutdown

    application.run_polling()

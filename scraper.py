import asyncio
import logging
import re
import os
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

class ZaraScraper:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None

    async def start(self):
        if not self.playwright:
            self.playwright = await async_playwright().start()
            headless_mode = os.getenv("HEADLESS", "false").lower() == "true" if os.name == 'nt' else True
            self.browser = await self.playwright.chromium.launch(
                headless=headless_mode,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]
            )
            self.context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="pt-PT"
            )

    async def stop(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        
    async def get_product_data(self, url: str) -> dict:
        if not self.context:
            await self.start()
            
        page = await self.context.new_page()
        await Stealth().apply_stealth_async(page)
        
        result = None
        try:
            # A Zara pode demorar um pouco a carregar e a passar a proteção
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Aguardar por um elemento chave, como o H1 do título do produto
            try:
                await page.wait_for_selector("h1", timeout=15000)
            except Exception:
                logger.warning(f"Timeout a aguardar h1 em {url}. A página pode não ter carregado corretamente ou estar bloqueada.")

            # Uma vez que o DOM da Zara muda muito e os tamanhos podem não renderizar no HTML,
            # A forma mais segura e à prova de bala é extrair o JSON de estado (viewPayload).
            # A página leva uns segundos a hidratar o React, então podemos usar um script evaluate.
            
            sizes = {}
            payload = None
            try:
                # Tentar obter a variável global da Zara que contém todos os dados do produto
                payload = await page.evaluate("window.zara?.viewPayload || window.__INITIAL_STATE__")
            except Exception as e:
                logger.error(f"Erro ao extrair JSON payload: {e}")
                
            if not payload or 'product' not in payload:
                logger.error(f"Não foi possível extrair dados via JSON payload para {url}.")
                return None
                
            product_data = payload.get('product', {})
            detail = product_data.get('detail', {})
            colors = detail.get('colors', [])
            
            if not colors:
                return None
                
            name = product_data.get('name', 'Produto Desconhecido')
            
            # Vamos usar a primeira cor disponível por defeito, pois a URL base carrega a cor principal
            color = colors[0]
            
            # Preços vêm em cêntimos (ex: 599 -> 5.99)
            raw_price = color.get('price', 0)
            raw_old_price = color.get('oldPrice', None)
            raw_orig_price = color.get('originalPrice', None)
            
            price_val = raw_price / 100 if raw_price else 0.0
            
            # Descobrir preço original
            original_price_val = None
            if raw_orig_price:
                original_price_val = raw_orig_price / 100
            elif raw_old_price:
                original_price_val = raw_old_price / 100
                
            if original_price_val == price_val:
                original_price_val = None
                
            # Extrair Tamanhos
            sizes_data = color.get('sizes', [])
            for size_info in sizes_data:
                size_name = size_info.get('name')
                if not size_name:
                    continue
                # Se for in_stock ou low_on_stock consideramos disponível
                availability = size_info.get('availability', '')
                is_in_stock = availability in ['in_stock', 'low_on_stock']
                sizes[size_name] = is_in_stock
            
            result = {
                "name": name,
                "price": price_val,
                "original_price": original_price_val,
                "sizes": sizes
            }
            
        except Exception as e:
            logger.error(f"Erro fatal no scraper para {url}: {e}")
        finally:
            await page.close()
            
        return result

# Teste manual se for executado diretamente
if __name__ == "__main__":
    async def test():
        logging.basicConfig(level=logging.INFO)
        scraper = ZaraScraper()
        url = "https://www.zara.com/pt/pt/vestido-stretch-caicai-p06050324.html?v1=517756017&v2=2723387"
        print(f"Testando extração para: {url}")
        data = await scraper.get_product_data(url)
        print("Dados obtidos:")
        print(data)
        await scraper.stop()
        
    asyncio.run(test())

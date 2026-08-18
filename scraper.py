import asyncio
import logging
import re
import os
import json
import httpx

logger = logging.getLogger(__name__)

ZARA_STORE_ID = "10702"
ZARA_BASE = "https://www.zara.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "Referer": "https://www.zara.com/pt/pt/",
    "Origin": "https://www.zara.com",
}


class ZaraScraper:
    def __init__(self):
        self.client = None
        self._cookies_ok = False

    async def start(self):
        if not self.client:
            self.client = httpx.AsyncClient(
                headers=HEADERS,
                follow_redirects=True,
                timeout=20,
            )
        if not self._cookies_ok:
            try:
                await self.client.get(f"{ZARA_BASE}/pt/pt/")
                self._cookies_ok = True
                logger.info("Sessão Zara iniciada (cookies obtidos).")
            except Exception as e:
                logger.error(f"Erro ao iniciar sessão: {e}")

    async def stop(self):
        if self.client:
            await self.client.aclose()
            self.client = None

    # ------------------------------------------------------------------ #
    #  Obter dados completos de um produto (nome, preço, tamanhos)       #
    #  a partir do seu ID interno (ex: 546977678).                       #
    # ------------------------------------------------------------------ #
    async def _get_product_by_internal_id(self, internal_id) -> dict | None:
        url = f"{ZARA_BASE}/pt/pt/products-details?productIds={internal_id}&ajax=true"
        try:
            resp = await self.client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    return data[0]
        except Exception as e:
            logger.error(f"Erro products-details: {e}")
        return None

    # ------------------------------------------------------------------ #
    #  Obter disponibilidade em tempo real via API REST                   #
    # ------------------------------------------------------------------ #
    async def _get_availability(self, color_product_id) -> dict:
        url = f"{ZARA_BASE}/itxrest/1/catalog/store/{ZARA_STORE_ID}/product/id/{color_product_id}/availability"
        try:
            resp = await self.client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    item["sku"]: item["availability"]
                    for item in data.get("skusAvailability", [])
                }
        except Exception as e:
            logger.warning(f"Falha availability API: {e}")
        return {}

    # ------------------------------------------------------------------ #
    #  Resolver referência / URL → ID interno                            #
    #                                                                    #
    #  Estratégia:                                                       #
    #    1. Se o URL tem ?v1=XXXXXX  → usar como colorProductId          #
    #    2. Percorrer todas as categorias da Zara e procurar pela ref    #
    # ------------------------------------------------------------------ #
    async def _resolve_internal_id(self, url: str) -> tuple:
        """Retorna (product_id, color_product_id) ou (None, None)."""

        # 1. Extrair v1 do URL (se existir)
        v1_match = re.search(r'[?&]v1=(\d+)', url)
        if v1_match:
            cpid = int(v1_match.group(1))
            # Tentar products-details com este ID
            product_data = await self._get_product_by_internal_id(cpid)
            if product_data:
                return product_data.get("id"), cpid

        # 2. Extrair referência do URL (ex: p04772354 → 04772354)
        ref_match = re.search(r'p(\d{8})\.html', url)
        target_ref = ref_match.group(1) if ref_match else None

        if not target_ref:
            return None, None

        # Formato de referência que a Zara usa: "4772/354"
        display_ref_target = f"{target_ref[1:5]}/{target_ref[5:8]}"

        # 3. Percorrer categorias para encontrar o produto
        logger.info(f"A procurar ref {display_ref_target} nas categorias da Zara...")
        try:
            cats_resp = await self.client.get(f"{ZARA_BASE}/pt/pt/categories?ajax=true")
            if cats_resp.status_code != 200:
                return None, None

            root_cats = cats_resp.json().get("categories", [])

            # Recolher IDs de todas as subcategorias (até 2 níveis)
            all_cat_ids = []
            for root in root_cats:
                for sub in root.get("subcategories", []):
                    all_cat_ids.append(sub.get("id"))
                    for sub2 in sub.get("subcategories", []):
                        all_cat_ids.append(sub2.get("id"))

            # Pesquisar em cada categoria
            for cat_id in all_cat_ids:
                if not cat_id:
                    continue
                cat_url = f"{ZARA_BASE}/pt/pt/category/{cat_id}/products?ajax=true"
                try:
                    resp = await self.client.get(cat_url)
                    if resp.status_code != 200:
                        continue
                    cat_data = resp.json()

                    # Navegar a estrutura de grupos
                    groups = cat_data.get("productGroups", [])
                    for group in groups:
                        for element in group.get("elements", []):
                            for cc in element.get("commercialComponents", []):
                                detail = cc.get("detail", {})
                                dr = detail.get("displayReference", "")
                                if dr == display_ref_target:
                                    pid = cc.get("id")
                                    colors = detail.get("colors", [])
                                    cpid = colors[0].get("productId") if colors else None
                                    logger.info(f"Produto encontrado! id={pid} cpid={cpid}")
                                    return pid, cpid
                except Exception:
                    continue

        except Exception as e:
            logger.error(f"Erro a percorrer categorias: {e}")

        return None, None

    # ------------------------------------------------------------------ #
    #  Método rápido — usado pela monitorização (já temos o ID guardado) #
    # ------------------------------------------------------------------ #
    async def get_product_by_id(self, internal_id, color_product_id=None) -> dict | None:
        """Obter dados de um produto usando o ID interno já conhecido."""
        if not self.client:
            await self.start()

        try:
            product_data = await self._get_product_by_internal_id(internal_id)
            if not product_data:
                return None
            return self._extract_product_info(product_data)
        except Exception as e:
            logger.error(f"Erro get_product_by_id: {e}", exc_info=True)
            return None

    # ------------------------------------------------------------------ #
    #  Extrair info de um product_data JSON                              #
    # ------------------------------------------------------------------ #
    def _extract_product_info_sync(self, product_data):
        """Parte síncrona da extração (sem chamadas de rede)."""
        name = product_data.get("name", "Produto Desconhecido")
        detail = product_data.get("detail", {})
        colors = detail.get("colors", [])

        if not colors:
            return None

        color = colors[0]
        cpid = color.get("productId")

        raw_price = color.get("price", 0)
        raw_old = color.get("oldPrice")
        raw_orig = color.get("originalPrice")
        price_val = raw_price / 100 if raw_price else 0.0

        original_price_val = None
        if raw_orig:
            original_price_val = raw_orig / 100
        elif raw_old:
            original_price_val = raw_old / 100
        if original_price_val == price_val:
            original_price_val = None

        sizes_data = color.get("sizes", [])

        return name, cpid, price_val, original_price_val, sizes_data

    async def _extract_product_info(self, product_data):
        """Extrair nome, preço, tamanhos de um product_data JSON."""
        sync_result = self._extract_product_info_sync(product_data)
        if not sync_result:
            return None

        name, cpid, price_val, original_price_val, sizes_data = sync_result

        sizes = {}
        sku_avail = await self._get_availability(cpid) if cpid else {}

        for sz in sizes_data:
            sz_name = sz.get("name")
            if not sz_name:
                continue
            sku = sz.get("sku")
            if sku and sku in sku_avail:
                sizes[sz_name] = sku_avail[sku] in ("in_stock", "low_on_stock")
            else:
                sizes[sz_name] = sz.get("availability", "") in ("in_stock", "low_on_stock")

        return {
            "name": name,
            "price": price_val,
            "original_price": original_price_val,
            "sizes": sizes,
            "internal_id": product_data.get("id"),
            "color_product_id": cpid,
        }

    # ------------------------------------------------------------------ #
    #  Método principal — chamado pelo bot ao /adicionar                 #
    # ------------------------------------------------------------------ #
    async def get_product_data(self, url: str) -> dict | None:
        if not self.client:
            await self.start()

        try:
            # 1. Resolver para ID interno
            product_id, color_product_id = await self._resolve_internal_id(url)

            if not product_id and not color_product_id:
                logger.error(f"Não foi possível resolver ID para {url}")
                return None

            # 2. Obter dados completos
            lookup_id = product_id or color_product_id
            product_data = await self._get_product_by_internal_id(lookup_id)
            if not product_data:
                return None

            return await self._extract_product_info(product_data)

        except Exception as e:
            logger.error(f"Erro fatal: {e}", exc_info=True)
            return None


# Teste manual
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    
    async def test():
        logging.basicConfig(level=logging.INFO)
        s = ZaraScraper()

        urls = [
            "https://www.zara.com/pt/pt/vestido-midi-halter-volume-bolinhas-p04772354.html?v1=385354142",
            "https://www.zara.com/pt/pt/-p04772354.html",
            "https://www.zara.com/pt/pt/-p05584401.html",
        ]

        for url in urls:
            print(f"\n{'='*50}")
            print(f"URL: {url}")
            data = await s.get_product_data(url)
            if data:
                print(f"  Nome: {data['name']}")
                print(f"  Preco: {data['price']} EUR")
                for sz, av in data["sizes"].items():
                    print(f"  {sz}: {'em stock' if av else 'esgotado'}")
            else:
                print("  FALHOU!")

        await s.stop()

    asyncio.run(test())

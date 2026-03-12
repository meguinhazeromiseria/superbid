#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
superbid_bebidas_debug.py — Debug da categoria bebidas no Superbid

Uso:
    python superbid_bebidas_debug.py            # mostra 1ª página (30 itens)
    python superbid_bebidas_debug.py --pages 3  # varre N páginas
    python superbid_bebidas_debug.py --raw      # imprime JSON bruto da 1ª oferta
    python superbid_bebidas_debug.py --save     # salva raw em bebidas_debug.json
"""

import json
import argparse
import time
import re
from datetime import datetime, timezone
from typing import Optional

import requests

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"

API_URL  = "https://offer-query.superbid.net/seo/offers/"
SITE_URL = "https://exchange.superbid.net"

HEADERS = {
    "accept": "*/*",
    "accept-language": "pt-BR,pt;q=0.9",
    "origin": SITE_URL,
    "referer": SITE_URL + "/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# Filtro por CATEGORIA (não subCategoria)
FILTER_BEBIDAS = "product.subCategory.category.description:bebidas"

RE_QTDE = re.compile(
    r"(?:aprox\.?:?\s*)([\d.,]+)\s*(?:unidades?|un\.?|pç[s.]?|peças?|itens?|kgs?|kg|pares?|lt?s?|litros?)?",
    re.IGNORECASE,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def extract_quantidade(titulo: str) -> Optional[int]:
    m = RE_QTDE.search(titulo or "")
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", "")
    try:
        return int(raw)
    except Exception:
        return None


def parse_valor(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = str(v).replace("R$", "").replace("\xa0", "").replace(" ", "").strip()
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d+)?$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        val = float(s)
        return val if val > 0 else None
    except Exception:
        return None


def fmt_brl(v) -> str:
    val = parse_valor(v)
    if val is None:
        return "—"
    s = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


# ─── Fetch de uma página ──────────────────────────────────────────────────────

def fetch_page(session: requests.Session, page_num: int = 0, page_size: int = 30) -> dict:
    params = {
        "filter":        FILTER_BEBIDAS,
        "keyword":       "aprox",
        "urlSeo":        "https://www.superbid.net/busca/aprox",
        "searchType":    "opened",
        "locale":        "pt_BR",
        "portalId":      "[2,15]",
        "requestOrigin": "marketplace",
        "timeZoneId":    "America/Sao_Paulo",
        "orderBy":       "score:desc",
        "pageNumber":    page_num,
        "pageSize":      page_size,
    }

    print(f"\n{DIM}GET {API_URL}{RESET}")
    print(f"{DIM}params: {json.dumps(params, ensure_ascii=False)}{RESET}\n")

    r = session.get(API_URL, params=params, timeout=30)
    print(f"HTTP {r.status_code}  |  {len(r.content)} bytes")

    if r.status_code != 200:
        print(f"{RED}Erro: {r.text[:500]}{RESET}")
        return {}

    return r.json()


# ─── Print detalhado de uma oferta ───────────────────────────────────────────

def print_offer(offer: dict, idx: int):
    product      = offer.get("product") or {}
    offer_detail = offer.get("offerDetail") or {}
    auction      = offer.get("auction") or {}
    location     = product.get("location") or {}
    sub_cat      = (product.get("subCategory") or {})
    cat          = (sub_cat.get("category") or {})

    titulo       = product.get("shortDesc") or product.get("description") or "?"
    offer_id     = offer.get("id")
    link         = f"{SITE_URL}/oferta/{offer_id}"
    valor_ini    = parse_valor(offer_detail.get("initialBidValue") or offer.get("price"))
    valor_atual  = parse_valor(offer_detail.get("currentMinBid") or offer_detail.get("initialBidValue"))
    end_date     = offer.get("endDate") or offer.get("endDateTime")
    qtde         = extract_quantidade(titulo)
    preco_un     = round(valor_atual / qtde, 4) if qtde and valor_atual else None

    print(f"\n{'─'*70}")
    print(f"{BOLD}{YELLOW}[{idx}] {titulo[:65]}{RESET}")
    print(f"{'─'*70}")
    print(f"  {DIM}id:{RESET}          {offer_id}")
    print(f"  {DIM}categoria:{RESET}   {cat.get('description') or '?'}  /  subcat: {sub_cat.get('description') or '?'}")
    print(f"  {DIM}local:{RESET}       {location.get('city') or '?'}  /  {location.get('state') or '?'}")
    print(f"  {DIM}valor ini:{RESET}   {fmt_brl(valor_ini)}")
    print(f"  {DIM}valor atual:{RESET} {fmt_brl(valor_atual)}")
    print(f"  {DIM}encerra:{RESET}     {end_date}")
    print(f"  {DIM}modalidade:{RESET}  {auction.get('modalityDesc') or '?'}")
    print(f"  {DIM}quantidade:{RESET}  {f'~{qtde:,} un.' if qtde else f'{RED}não detectada{RESET}'}")
    if preco_un:
        flag = f"{GREEN}✅ bom" if preco_un <= 3 else f"{RED}❌ caro"
        print(f"  {DIM}preço/un:{RESET}    R$ {preco_un:.2f}  {flag}{RESET}")
    gallery = product.get("galleryJson") or []
    thumbs  = [i.get("link") or i.get("thumbnailUrl") for i in gallery[:2] if i]
    print(f"  {DIM}imagens:{RESET}     {len(gallery)} no gallery  | thumb: {product.get('thumbnailUrl') or '—'}")
    if thumbs:
        for t in thumbs:
            print(f"             {DIM}{t}{RESET}")
    print(f"  {DIM}link:{RESET}        {CYAN}{link}{RESET}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Debug bebidas Superbid")
    parser.add_argument("--pages",     type=int, default=1,  help="Quantas páginas buscar (default: 1)")
    parser.add_argument("--page-size", type=int, default=30, help="Itens por página (default: 30)")
    parser.add_argument("--raw",  action="store_true", help="Imprime JSON bruto da 1ª oferta")
    parser.add_argument("--save", action="store_true", help="Salva resposta em bebidas_debug.json")
    args = parser.parse_args()

    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}  SUPERBID — DEBUG BEBIDAS{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")
    print(f"  {DIM}filter:  {FILTER_BEBIDAS}{RESET}")
    print(f"  {DIM}páginas: {args.pages}  |  page_size: {args.page_size}{RESET}")

    session = requests.Session()
    session.headers.update(HEADERS)

    all_offers = []
    all_raw    = []

    for page_num in range(args.pages):
        print(f"\n{BOLD}  ── Página {page_num} ──────────────────────────────────────────────{RESET}")
        data = fetch_page(session, page_num=page_num, page_size=args.page_size)

        if not data:
            print(f"{RED}Sem dados na página {page_num}.{RESET}")
            break

        total  = data.get("total", 0)
        offers = data.get("offers", [])
        start  = data.get("start", page_num * args.page_size)
        query  = data.get("query") or {}

        print(f"\n  {GREEN}total no servidor: {total}{RESET}  |  "
              f"retornados: {len(offers)}  |  start: {start}")
        print(f"  {DIM}query: {json.dumps(query, ensure_ascii=False)}{RESET}")

        # Mostra facets disponíveis
        facets = data.get("facetFields") or []
        if page_num == 0 and facets:
            print(f"\n  {BOLD}Facets disponíveis:{RESET}")
            for f in facets[:8]:
                vals = [v.get("value") for v in (f.get("facetValues") or [])[:5]]
                print(f"    {DIM}{f.get('title') or f.get('fieldFilter')}: {vals}{RESET}")

        if not offers:
            print(f"  {YELLOW}Nenhuma oferta retornada.{RESET}")
            break

        all_offers.extend(offers)
        all_raw.append(data)

        if start + len(offers) >= total:
            break

        if page_num < args.pages - 1:
            time.sleep(1)

    print(f"\n\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}  OFERTAS ENCONTRADAS: {len(all_offers)}{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")

    # Imprime JSON bruto da 1ª oferta (modo --raw)
    if args.raw and all_offers:
        print(f"\n{BOLD}  JSON BRUTO — 1ª oferta:{RESET}\n")
        print(json.dumps(all_offers[0], ensure_ascii=False, indent=2))
        print()

    # Imprime detalhes de cada oferta
    for idx, offer in enumerate(all_offers, 1):
        print_offer(offer, idx)

    # Resumo
    sem_qtde = [o for o in all_offers
                if not extract_quantidade(
                    (o.get("product") or {}).get("shortDesc") or ""
                )]
    sub_cats: dict = {}
    for o in all_offers:
        sc = ((o.get("product") or {}).get("subCategory") or {}).get("description") or "?"
        sub_cats[sc] = sub_cats.get(sc, 0) + 1

    print(f"\n\n{'='*70}")
    print(f"{BOLD}  RESUMO{RESET}")
    print(f"{'='*70}")
    print(f"  Total coletados:     {len(all_offers)}")
    print(f"  Sem quantidade:      {len(sem_qtde)}  "
          f"{'(títulos sem «aprox»)' if sem_qtde else ''}")
    print(f"\n  Sub-categorias detectadas:")
    for sc, cnt in sorted(sub_cats.items(), key=lambda x: -x[1]):
        print(f"    {sc:<35} {cnt}")

    if sem_qtde:
        print(f"\n  {YELLOW}Títulos SEM quantidade detectada:{RESET}")
        for o in sem_qtde[:10]:
            titulo = (o.get("product") or {}).get("shortDesc") or "?"
            print(f"    {DIM}{titulo[:70]}{RESET}")

    # Salva JSON
    if args.save:
        fname = "bebidas_debug.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(
                {"timestamp": datetime.now(timezone.utc).isoformat(), "raw": all_raw},
                f, ensure_ascii=False, indent=2, default=str
            )
        print(f"\n  {GREEN}Salvo em: {fname}{RESET}")

    session.close()
    print()


if __name__ == "__main__":
    main()
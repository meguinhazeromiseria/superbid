#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
superbid_quantidade.py — Superbid lotes em quantidade → auctions.quantidade

Uso:
    python superbid_quantidade.py              # coleta e sobe
    python superbid_quantidade.py --no-upload  # só JSON
    python superbid_quantidade.py --show-all
    python superbid_quantidade.py --output meu.json
"""

import json
import re
import sys
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from supabase_client import SupabaseClient


GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"


# ─── Config ───────────────────────────────────────────────────────────────────

API_URL  = "https://offer-query.superbid.net/seo/offers/"
SITE_URL = "https://exchange.superbid.net"

# pageNumber começa em 0 na API (confirmado no DevTools)
CATEGORIES = [
    ("smartwatch", "Smartwatches", "smartwatch"),
]

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

RE_QTDE = re.compile(
    r"(?:aprox\.?:?\s*)([\d.,]+)\s*(?:unidades?|un\.?|pç[s.]?|peças?|itens?|kgs?|kg|pares?)?",
    re.IGNORECASE,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

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


def parse_data_iso(raw) -> Optional[str]:
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc).isoformat()
        except Exception:
            return None
    s = str(raw).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T")).isoformat()
    except Exception:
        pass
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except Exception:
            pass
    return None


def parse_cidade_estado(location: dict) -> tuple:
    """product.location.city = 'Goiânia - GO' → ('Goiânia', 'GO')"""
    city_str = (location.get("city") or "").strip()
    if not city_str:
        return None, None
    m = re.match(r"^(.+?)\s*-\s*([A-Z]{2})\s*$", city_str)
    if m:
        return m.group(1).strip(), m.group(2)
    return city_str, None


def parse_images_gallery(gallery_json: list) -> list:
    imgs = []
    for item in (gallery_json or []):
        url = item.get("link") or item.get("thumbnailUrl")
        if url and url.startswith("http"):
            imgs.append(url)
        if len(imgs) >= 3:
            break
    return imgs


def extract_quantidade(titulo: str) -> Optional[int]:
    m = RE_QTDE.search(titulo or "")
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", "")
    try:
        return int(raw)
    except Exception:
        return None


# ─── Scraper ──────────────────────────────────────────────────────────────────

def scrape_category(filter_value: str, display_name: str,
                    session: requests.Session, page_size: int = 30) -> list:
    items = []
    page_num = 0   # API usa pageNumber base-0
    consecutive_errors = 0
    max_errors = 3

    print(f"\n  {BOLD}{display_name}{RESET}")
    print(f"  {'─'*60}")

    while True:
        try:
            params = {
                "filter":        f"product.subCategory.description:{filter_value}",
                "keyword":       "aprox",
                "urlSeo":        f"{SITE_URL}/busca/aprox",
                "searchType":    "opened",
                "locale":        "pt_BR",
                "portalId":      "[2,15]",
                "requestOrigin": "marketplace",
                "timeZoneId":    "America/Sao_Paulo",
                "orderBy":       "score:desc",
                "pageNumber":    page_num,
                "pageSize":      page_size,
            }

            r = session.get(API_URL, params=params, timeout=30)

            if r.status_code != 200:
                consecutive_errors += 1
                print(f"  {YELLOW}HTTP {r.status_code} — página {page_num}{RESET}")
                if consecutive_errors >= max_errors:
                    break
                time.sleep(3)
                page_num += 1
                continue

            data   = r.json()
            offers = data.get("offers", [])
            total  = data.get("total", 0)

            if not offers:
                break

            consecutive_errors = 0
            print(f"  {DIM}Página {page_num}: {len(offers)} ofertas (total: {total}){RESET}")
            items.extend(offers)

            start = data.get("start", page_num * page_size)
            if start + len(offers) >= total:
                break

            page_num += 1
            time.sleep(1)

        except requests.exceptions.Timeout:
            consecutive_errors += 1
            print(f"  {YELLOW}Timeout — página {page_num}{RESET}")
            if consecutive_errors >= max_errors:
                break
            time.sleep(5)
            page_num += 1

        except Exception as e:
            consecutive_errors += 1
            print(f"  {RED}Erro: {str(e)[:100]}{RESET}")
            if consecutive_errors >= max_errors:
                break
            time.sleep(3)
            page_num += 1

    print(f"  {GREEN}OK  {len(items)} itens coletados{RESET}")
    return items


# ─── Extração ─────────────────────────────────────────────────────────────────

def extract(offer: dict, tipo: str) -> Optional[dict]:
    try:
        offer_id = offer.get("id")
        if not offer_id:
            return None

        product = offer.get("product") or {}
        titulo  = (product.get("shortDesc") or "").strip()
        if not titulo:
            return None

        link = f"{SITE_URL}/oferta/{offer_id}"

        location = product.get("location") or {}
        cidade, estado = parse_cidade_estado(location)

        offer_detail  = offer.get("offerDetail") or {}
        valor_inicial = parse_valor(offer_detail.get("initialBidValue") or offer.get("price"))
        valor_atual   = parse_valor(
            offer_detail.get("currentMinBid")
            or offer_detail.get("initialBidValue")
            or offer.get("price")
        )

        data_enc = parse_data_iso(offer.get("endDate") or offer.get("endDateTime"))

        gallery = product.get("galleryJson") or []
        imagens = parse_images_gallery(gallery)
        if not imagens and product.get("thumbnailUrl"):
            imagens = [product["thumbnailUrl"]]

        auction       = offer.get("auction") or {}
        modality_desc = (auction.get("modalityDesc") or "").lower()
        modalidade    = (
            "venda_direta"
            if "compra" in modality_desc or "proposta" in modality_desc
            else "leilao"
        )

        sub_cat          = (product.get("subCategory") or {}).get("description") or None
        quantidade_aprox = extract_quantidade(titulo)

        return {
            "offer_id":         offer_id,
            "titulo":           titulo,
            "tipo":             tipo,
            "sub_categoria":    sub_cat,
            "estado":           estado,
            "cidade":           cidade,
            "valor_inicial":    valor_inicial,
            "valor_atual":      valor_atual,
            "data_enc":         data_enc,
            "link":             link,
            "imagens":          imagens,
            "modalidade":       modalidade,
            "quantidade_aprox": quantidade_aprox,
            "origem":           "Superbid",
        }

    except Exception as e:
        print(f"  {YELLOW}parse error [{offer.get('id')}]: {e}{RESET}")
        return None


# ─── Normalização para o DB ───────────────────────────────────────────────────

def normalize_to_db(item: dict) -> dict:
    imagens = item.get("imagens") or []
    return {
        "titulo":            item["titulo"],
        "descricao":         None,
        "tipo":              item["tipo"],
        "sub_categoria":     item.get("sub_categoria"),
        "estado":            item.get("estado"),
        "cidade":            item.get("cidade"),
        "modalidade":        item["modalidade"],
        "valor_inicial":     item["valor_inicial"],
        "valor_atual":       item.get("valor_atual"),
        "quantidade_aprox":  item.get("quantidade_aprox"),
        "data_encerramento": item["data_enc"],
        "link":              item["link"],
        "imagem_1":          imagens[0] if len(imagens) > 0 else None,
        "imagem_2":          imagens[1] if len(imagens) > 1 else None,
        "imagem_3":          imagens[2] if len(imagens) > 2 else None,
        "origem":            item.get("origem"),
        "ativo":             True,
        "premium":           False,
    }


# ─── Upload para Supabase ─────────────────────────────────────────────────────

def upload_to_supabase(items: list) -> dict:
    try:
        db = SupabaseClient()
    except Exception as e:
        print(f"\n  {RED}Falha ao inicializar SupabaseClient: {e}{RESET}")
        return {"inserted": 0, "updated": 0, "errors": len(items), "duplicates_removed": 0}

    registros = [normalize_to_db(item) for item in items]

    print(f"\n{BOLD}{'='*68}{RESET}")
    print(f"{BOLD}  UPLOAD → auctions.quantidade  ({len(registros)} registros){RESET}")
    print(f"{BOLD}{'='*68}{RESET}\n")

    try:
        stats = db.upsert("quantidade", registros)
        total_s = stats.get("inserted", 0) + stats.get("updated", 0)
        print(f"\n  {GREEN}Enviados:        {total_s} "
              f"({stats.get('inserted', 0)} novos + {stats.get('updated', 0)} atualizados){RESET}")
        print(f"  Dupes removidas: {stats.get('duplicates_removed', 0)}")
        print(f"  Erros:           {stats.get('errors', 0)}\n")
        return stats
    except Exception as e:
        print(f"\n  {RED}Erro no upsert: {e}{RESET}\n")
        return {"inserted": 0, "updated": 0, "errors": len(registros), "duplicates_removed": 0}


# ─── Print ────────────────────────────────────────────────────────────────────

def print_item(item: dict, i: int, total: int):
    titulo = item["titulo"][:60]
    qtde   = item.get("quantidade_aprox")
    print(f"\n{'─'*68}")
    print(f"{BOLD}{YELLOW}[{i}/{total}] {titulo}{RESET}")
    print(f"{'─'*68}")
    print(f"  {DIM}tipo:{RESET}       {item.get('tipo') or '?'}")
    print(f"  {DIM}sub_cat:{RESET}    {item.get('sub_categoria') or '?'}")
    print(f"  {DIM}quantidade:{RESET} {f'~{qtde:,} un.' if qtde else '?'}")
    print(f"  {DIM}local:{RESET}      {item.get('cidade') or '?'} / {item.get('estado') or '?'}")
    print(f"  {DIM}valor:{RESET}      {fmt_brl(item['valor_inicial'])}  "
          f"(atual: {fmt_brl(item.get('valor_atual'))})")
    print(f"  {DIM}data:{RESET}       {item['data_enc']}")
    print(f"  {DIM}imagens:{RESET}    {len(item.get('imagens') or [])}x")
    print(f"  {DIM}link:{RESET}       {item['link']}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Superbid lotes em quantidade → auctions.quantidade"
    )
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--show-all",  action="store_true")
    parser.add_argument("--page-size", type=int, default=30)
    parser.add_argument("--output",    default="superbid_quantidade.json")
    args = parser.parse_args()

    print(f"\n{BOLD}{'='*68}{RESET}")
    print(f"{BOLD}  SUPERBID — LOTES EM QUANTIDADE{RESET}")
    print(f"{BOLD}{'='*68}{RESET}")
    cats_str = " · ".join(c[0] for c in CATEGORIES)
    print(f"  {DIM}categorias: {cats_str}{RESET}")
    print(f"  {DIM}upload:     {'não (--no-upload)' if args.no_upload else 'sim → auctions.quantidade'}{RESET}\n")

    session = requests.Session()
    session.headers.update(HEADERS)

    # ── 1. Coleta raw ─────────────────────────────────────────────────────
    print(f"{BOLD}  Coletando da API Superbid...{RESET}")
    raw_by_cat = []
    for filter_value, display_name, tipo in CATEGORIES:
        offers = scrape_category(filter_value, display_name, session, args.page_size)
        for o in offers:
            raw_by_cat.append((o, tipo))
        time.sleep(2)

    print(f"\n  {GREEN}Total raw coletados: {len(raw_by_cat)}{RESET}")

    # ── 2. Extração ───────────────────────────────────────────────────────
    print(f"\n{BOLD}  Extraindo campos...{RESET}\n")
    items, falhos = [], 0
    for offer_raw, tipo in raw_by_cat:
        item = extract(offer_raw, tipo)
        if item:
            items.append(item)
        else:
            falhos += 1

    print(f"  {GREEN}OK  {len(items)} extraídos{RESET}  ·  {RED}{falhos} falhos{RESET}")

    # ── 3. Deduplicação ───────────────────────────────────────────────────
    seen: set = set()
    unique = []
    for item in items:
        if item["link"] not in seen:
            seen.add(item["link"])
            unique.append(item)
    if len(items) != len(unique):
        print(f"  {DIM}{len(items) - len(unique)} duplicata(s) removida(s){RESET}")
    items = unique
    items.sort(key=lambda x: x.get("valor_inicial") or 0, reverse=True)

    # ── 4. Print ──────────────────────────────────────────────────────────
    exibir = items if args.show_all else items[:10]
    for i, item in enumerate(exibir, 1):
        print_item(item, i, len(items))
    if not args.show_all and len(items) > 10:
        print(f"\n  {DIM}... {len(items) - 10} item(s) não exibido(s). Use --show-all{RESET}")

    # ── 5. Resumo ─────────────────────────────────────────────────────────
    por_tipo: dict = {}
    for item in items:
        k = item.get("tipo", "?")
        por_tipo[k] = por_tipo.get(k, 0) + 1
    com_qtde = sum(1 for i in items if i.get("quantidade_aprox"))

    print(f"\n\n{'='*68}")
    print(f"{BOLD}  RESUMO{RESET}")
    print(f"{'='*68}")
    print(f"  Total coletados:  {len(items)}")
    for tipo, cnt in sorted(por_tipo.items()):
        print(f"  {tipo:<20} {cnt}")
    print(f"  Com quantidade:   {com_qtde} ({com_qtde*100//len(items) if items else 0}%)")
    print(f"  Com imagem:       {sum(1 for i in items if i.get('imagens'))}")
    if items:
        top = items[0]
        print(f"  Maior valor:      {fmt_brl(top['valor_inicial'])}  ({top['titulo'][:40]})")

    # ── 6. Salva JSON ─────────────────────────────────────────────────────
    output_data = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "total_items": len(items),
        "por_tipo":    por_tipo,
        "items":       items,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  JSON salvo em: {args.output}")

    # ── 7. Upload Supabase ────────────────────────────────────────────────
    if not args.no_upload:
        upload_to_supabase(items)

    session.close()


if __name__ == "__main__":
    main()
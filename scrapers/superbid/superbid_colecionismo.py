#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
superbid_colecionismo.py — Superbid Artes, Decoração & Colecionismo → auctions.colecionismo

Endpoint: /_next/data/{buildId}/pt_BR/categorias/artes-decoracao-colecionismo.json
Paginação: pageNumber base-0, pageSize 30
Build ID: auto-descoberto na home do site a cada execução

Uso:
    python superbid_colecionismo.py              # coleta tudo e sobe
    python superbid_colecionismo.py --no-upload  # só JSON
    python superbid_colecionismo.py --show-all
    python superbid_colecionismo.py --output meu.json
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

SITE_URL    = "https://exchange.superbid.net"
CATEGORY_ID = "artes-decoracao-colecionismo"

# subCategory.description (lowercase substring) → tipo gravado no banco
TIPO_MAP = [
    ("porcelana",    "arte"),
    ("cerâmica",     "arte"),
    ("ceramica",     "arte"),
    ("pintura",      "arte"),
    ("escultura",    "arte"),
    ("gravura",      "arte"),
    ("luminária",    "arte"),
    ("luminaria",    "arte"),
    ("lustre",       "arte"),
    ("obra",         "arte"),
    ("arte",         "arte"),
    ("vinho",        "vinho"),
    ("decoraç",      "decoracao"),
    ("decoraca",     "decoracao"),
    ("antiguidade",  "antiguidade"),
    ("joia",         "joia"),
    ("jóia",         "joia"),
    ("relógio",      "joia"),
    ("relogio",      "joia"),
    ("colecion",     "colecionismo"),
    ("numismát",     "colecionismo"),
    ("filatelia",    "colecionismo"),
    ("boneca",       "colecionismo"),
    ("brinquedo",    "colecionismo"),
]

TIPO_MAP_CAT_PAI = {
    "obras de arte":  "arte",
    "colecionismo":   "colecionismo",
    "bebidas":        "vinho",
    "acessórios":     "decoracao",
    "acessorios":     "decoracao",
}

HEADERS = {
    "accept":          "*/*",
    "accept-language": "pt-BR,pt;q=0.9",
    "origin":          SITE_URL,
    "referer":         SITE_URL + "/",
    "x-nextjs-data":   "1",
    "user-agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.5 Mobile/15E148 Safari/604.1"
    ),
}


# ─── Build ID ─────────────────────────────────────────────────────────────────

def get_build_id(session: requests.Session) -> str:
    r = session.get(SITE_URL, timeout=15)
    r.raise_for_status()
    m = re.search(r'"buildId"\s*:\s*"([^"]+)"', r.text)
    if not m:
        raise RuntimeError("buildId não encontrado no HTML da home.")
    build_id = m.group(1)
    print(f"  {DIM}Build ID: {build_id}{RESET}")
    return build_id


# ─── Parsers ──────────────────────────────────────────────────────────────────

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
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).isoformat()
        except Exception:
            pass
    return None


def parse_cidade_estado(location: dict) -> tuple:
    if not location:
        return None, None
    city  = (location.get("city")  or "").strip() or None
    state = (location.get("state") or "").strip() or None
    if city and not state:
        m = re.match(r"^(.+?)\s*-\s*([A-Z]{2})\s*$", city)
        if m:
            city, state = m.group(1).strip(), m.group(2)
    return city, state


def parse_images(offer: dict) -> list:
    imgs = []
    product = offer.get("product") or {}
    for item in (product.get("galleryJson") or []):
        url = item.get("link") or item.get("thumbnailUrl") or ""
        if url.startswith("http") and url not in imgs:
            imgs.append(url)
        if len(imgs) >= 3:
            return imgs
    for field in ["thumbnailUrl", "imageUrl", "photoUrl"]:
        url = offer.get(field) or product.get(field) or ""
        if url.startswith("http") and url not in imgs:
            imgs.append(url)
    for field in ["photos", "images", "gallery"]:
        for item in (offer.get(field) or []):
            url = item if isinstance(item, str) else (item.get("url") or item.get("link") or "")
            if url.startswith("http") and url not in imgs:
                imgs.append(url)
            if len(imgs) >= 3:
                return imgs
    return imgs[:3]


def map_tipo(sub_desc: str, cat_desc: str = "") -> str:
    low_sub = (sub_desc or "").lower()
    low_cat = (cat_desc or "").lower()
    # 1. Testa substrings da sub-categoria
    for keyword, tipo in TIPO_MAP:
        if keyword in low_sub:
            return tipo
    # 2. Fallback: usa categoria pai
    for keyword, tipo in TIPO_MAP_CAT_PAI.items():
        if keyword in low_cat:
            return tipo
    # 3. Último recurso
    return "colecionismo"


# ─── Scraper ──────────────────────────────────────────────────────────────────

def scrape_all(session: requests.Session, build_id: str,
               page_size: int = 30) -> list:
    all_offers = []
    page = 0
    consecutive_errors = 0
    max_errors = 3

    print(f"\n  {BOLD}Artes, Decoração & Colecionismo{RESET}")
    print(f"  {'─'*60}")

    while True:
        url = (
            f"{SITE_URL}/_next/data/{build_id}/pt_BR/categorias/{CATEGORY_ID}.json"
            f"?pageNumber={page}&pageSize={page_size}"
            f"&orderBy=score%3Adesc&categoryId={CATEGORY_ID}"
        )
        try:
            r = session.get(url, timeout=30)

            if r.status_code != 200:
                consecutive_errors += 1
                print(f"  {YELLOW}HTTP {r.status_code} — página {page}{RESET}")
                if consecutive_errors >= max_errors:
                    break
                time.sleep(3)
                page += 1
                continue

            data = r.json()

            if "__N_REDIRECT" in data:
                break

            page_props  = data.get("pageProps") or {}
            offers_list = page_props.get("offersList") or {}
            offers      = offers_list.get("offers") or []
            total       = offers_list.get("total") or 0

            if not offers:
                break

            consecutive_errors = 0
            print(f"  {DIM}Página {page}: {len(offers)} ofertas (total: {total}){RESET}")
            all_offers.extend(offers)

            start = offers_list.get("start", page * page_size)
            if start + len(offers) >= total:
                break

            page += 1
            time.sleep(1)

        except requests.exceptions.Timeout:
            consecutive_errors += 1
            print(f"  {YELLOW}Timeout — página {page}{RESET}")
            if consecutive_errors >= max_errors:
                break
            time.sleep(5)
            page += 1

        except Exception as e:
            consecutive_errors += 1
            print(f"  {RED}Erro: {str(e)[:100]}{RESET}")
            if consecutive_errors >= max_errors:
                break
            time.sleep(3)
            page += 1

    print(f"  {GREEN}OK  {len(all_offers)} itens coletados{RESET}")
    return all_offers


# ─── Extração ─────────────────────────────────────────────────────────────────

def extract(offer: dict) -> Optional[dict]:
    try:
        offer_id = offer.get("id")
        if not offer_id:
            return None

        product = offer.get("product") or {}
        titulo  = (
            product.get("shortDesc") or offer.get("title") or offer.get("shortDesc") or ""
        ).strip()
        if not titulo:
            return None

        link = f"{SITE_URL}/oferta/{offer_id}"

        # Sub-categoria → tipo
        sub_obj       = product.get("subCategory") or offer.get("subCategory") or {}
        cat_obj       = sub_obj.get("category") or {}
        sub_categoria = (sub_obj.get("description") or "").strip() or None
        cat_desc      = (cat_obj.get("description") or "").strip()
        tipo          = map_tipo(sub_categoria or "", cat_desc)

        # Descrição longa
        descricao = (
            product.get("longDesc") or product.get("detailedDescription") or
            offer.get("detailedDescription") or offer.get("description") or ""
        ).strip() or None

        # Localização
        location = product.get("location") or offer.get("location") or {}
        cidade, estado = parse_cidade_estado(location)

        # Valores
        valor_inicial = parse_valor(
            offer.get("price")
            or offer.get("initialValue")
            or offer.get("startValue")
            or (offer.get("offerDetail") or {}).get("directSaleValue")
        )
        valor_atual = parse_valor(
            offer.get("currentValue") or offer.get("currentBid") or offer.get("price")
        )

        # Data
        data_enc = parse_data_iso(
            offer.get("endDate") or offer.get("closingDate") or offer.get("auctionEndDate")
        )
        if not data_enc:
            return None

        # Modalidade — offerTypeId=10 é venda direta
        modality_desc = (
            (offer.get("auction") or {}).get("modalityDesc") or offer.get("modalityDesc") or ""
        ).lower()
        if "compra" in modality_desc or "proposta" in modality_desc or offer.get("offerTypeId") == 10:
            modalidade = "venda_direta"
        else:
            modalidade = "leilao"

        return {
            "offer_id":      offer_id,
            "titulo":        titulo,
            "tipo":          tipo,
            "sub_categoria": sub_categoria,
            "descricao":     descricao,
            "estado":        estado,
            "cidade":        cidade,
            "valor_inicial": valor_inicial,
            "valor_atual":   valor_atual,
            "data_enc":      data_enc,
            "link":          link,
            "imagens":       parse_images(offer),
            "modalidade":    modalidade,
            "origem":        "Superbid",
        }

    except Exception as e:
        print(f"  {YELLOW}parse error [{offer.get('id')}]: {e}{RESET}")
        return None


# ─── Normalização para o DB ───────────────────────────────────────────────────

def normalize_to_db(item: dict) -> dict:
    imagens = item.get("imagens") or []
    return {
        "titulo":            item["titulo"],
        "descricao":         item.get("descricao"),
        "tipo":              item["tipo"],
        "sub_categoria":     item.get("sub_categoria"),
        "estado":            item.get("estado"),
        "cidade":            item.get("cidade"),
        "modalidade":        item["modalidade"],
        "valor_inicial":     item["valor_inicial"],
        "valor_atual":       item.get("valor_atual"),
        "data_encerramento": item["data_enc"],
        "link":              item["link"],
        "imagem_1":          imagens[0] if len(imagens) > 0 else None,
        "imagem_2":          imagens[1] if len(imagens) > 1 else None,
        "imagem_3":          imagens[2] if len(imagens) > 2 else None,
        "origem":            item.get("origem"),
        "ativo":             True,
        "premium":           False,
        "destaque":          False,
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
    print(f"{BOLD}  UPLOAD → auctions.colecionismo  ({len(registros)} registros){RESET}")
    print(f"{BOLD}{'='*68}{RESET}\n")

    try:
        stats = db.upsert("colecionismo", registros)
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
    print(f"\n{'─'*68}")
    print(f"{BOLD}{YELLOW}[{i}/{total}] {titulo}{RESET}")
    print(f"{'─'*68}")
    print(f"  {DIM}tipo:{RESET}       {item.get('tipo') or '?'}")
    print(f"  {DIM}sub_cat:{RESET}    {item.get('sub_categoria') or '—'}")
    print(f"  {DIM}local:{RESET}      {item.get('cidade') or '?'} / {item.get('estado') or '?'}")
    print(f"  {DIM}valor:{RESET}      {fmt_brl(item['valor_inicial'])}  "
          f"(atual: {fmt_brl(item.get('valor_atual'))})")

    print(f"  {DIM}data:{RESET}       {item['data_enc']}")
    print(f"  {DIM}imagens:{RESET}    {len(item.get('imagens') or [])}x")
    print(f"  {DIM}modalidade:{RESET} {item.get('modalidade') or '?'}")
    print(f"  {DIM}link:{RESET}       {item['link']}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Superbid Artes/Colecionismo → auctions.colecionismo"
    )
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--show-all",  action="store_true")
    parser.add_argument("--page-size", type=int, default=30)
    parser.add_argument("--output",    default="superbid_colecionismo.json")
    args = parser.parse_args()

    print(f"\n{BOLD}{'='*68}{RESET}")
    print(f"{BOLD}  SUPERBID — ARTES, DECORAÇÃO & COLECIONISMO{RESET}")
    print(f"{BOLD}{'='*68}{RESET}")
    print(f"  {DIM}endpoint: Next.js SSR (/_next/data/...){RESET}")
    print(f"  {DIM}upload:   {'não (--no-upload)' if args.no_upload else 'sim → auctions.colecionismo'}{RESET}\n")

    session = requests.Session()
    session.headers.update(HEADERS)

    # ── 1. Build ID ───────────────────────────────────────────────────────
    print(f"{BOLD}  Descobrindo build ID...{RESET}")
    try:
        build_id = get_build_id(session)
    except Exception as e:
        print(f"  {RED}Falha: {e}{RESET}")
        session.close()
        return

    # ── 2. Coleta ─────────────────────────────────────────────────────────
    print(f"\n{BOLD}  Coletando da API Superbid...{RESET}")
    raw_offers = scrape_all(session, build_id, args.page_size)
    print(f"\n  {GREEN}Total raw coletados: {len(raw_offers)}{RESET}")

    # ── 3. Extração ───────────────────────────────────────────────────────
    print(f"\n{BOLD}  Extraindo campos...{RESET}\n")
    items, falhos = [], 0
    for offer_raw in raw_offers:
        item = extract(offer_raw)
        if item:
            items.append(item)
        else:
            falhos += 1
    print(f"  {GREEN}OK  {len(items)} extraídos{RESET}  ·  {RED}{falhos} falhos{RESET}")

    # ── 4. Deduplicação ───────────────────────────────────────────────────
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

    # ── 5. Print ──────────────────────────────────────────────────────────
    exibir = items if args.show_all else items[:10]
    for i, item in enumerate(exibir, 1):
        print_item(item, i, len(items))
    if not args.show_all and len(items) > 10:
        print(f"\n  {DIM}... {len(items) - 10} item(s) não exibido(s). Use --show-all{RESET}")

    # ── 6. Resumo ─────────────────────────────────────────────────────────
    por_tipo: dict = {}
    por_sub:  dict = {}
    for item in items:
        por_tipo[item.get("tipo", "?")] = por_tipo.get(item.get("tipo", "?"), 0) + 1
        s = item.get("sub_categoria") or "sem sub-cat"
        por_sub[s] = por_sub.get(s, 0) + 1

    print(f"\n\n{'='*68}")
    print(f"{BOLD}  RESUMO{RESET}")
    print(f"{'='*68}")
    print(f"  Total coletados:  {len(items)}")
    print(f"\n  Por tipo (DB):")
    for tipo, cnt in sorted(por_tipo.items()):
        print(f"    {tipo:<20} {cnt}")
    print(f"\n  Por sub-categoria (API):")
    for sub, cnt in sorted(por_sub.items(), key=lambda x: -x[1]):
        print(f"    {sub:<35} {cnt}")
    print(f"  Com imagem:       {sum(1 for i in items if i.get('imagens'))}")
    if items:
        top = items[0]
        print(f"  Maior valor:      {fmt_brl(top['valor_inicial'])}  ({top['titulo'][:40]})")

    # ── 7. JSON ───────────────────────────────────────────────────────────
    output_data = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "total_items": len(items),
        "por_tipo":    por_tipo,
        "por_sub":     por_sub,
        "items":       items,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  JSON salvo em: {args.output}")

    # ── 8. Upload ─────────────────────────────────────────────────────────
    if not args.no_upload:
        upload_to_supabase(items)

    session.close()


if __name__ == "__main__":
    main()
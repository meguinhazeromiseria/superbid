#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
superbid_acessorios_debug.py — Debug acessórios (+ vestuário opcional)

Uso:
    python superbid_acessorios_debug.py              # só acessorios
    python superbid_acessorios_debug.py --vestuario  # acessorios + vestuario
    python superbid_acessorios_debug.py --pages 3
    python superbid_acessorios_debug.py --raw
    python superbid_acessorios_debug.py --save
"""

import json
import argparse
import time
import re
import statistics
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

# Filtros por subCategoria (não categoria pai)
FILTERS = {
    "acessorios": "product.subCategory.description:acessorios",
    "vestuario":  "product.subCategory.description:vestuario",
}

RE_QTDE = re.compile(
    r"(?:aprox\.?:?\s*)([\d.,]+)\s*(?:unidades?|un\.?|pç[s.]?|peças?|itens?|kgs?|kg|pares?|lts?|litros?)?",
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


# ─── Fetch ────────────────────────────────────────────────────────────────────

def fetch_all(session: requests.Session, filter_str: str,
              pages: int, page_size: int) -> list:
    all_offers = []
    for page_num in range(pages):
        params = {
            "filter":        filter_str,
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
        try:
            r = session.get(API_URL, params=params, timeout=30)
            if r.status_code != 200:
                print(f"  {RED}HTTP {r.status_code} — página {page_num}{RESET}")
                break
            data   = r.json()
            offers = data.get("offers", [])
            total  = data.get("total", 0)
            start  = data.get("start", page_num * page_size)
            print(f"  {DIM}Página {page_num}: {len(offers)} ofertas (total servidor: {total}){RESET}")
            all_offers.extend(offers)
            if not offers or start + len(offers) >= total:
                break
            time.sleep(1)
        except Exception as e:
            print(f"  {RED}Erro: {e}{RESET}")
            break
    return all_offers


# ─── Print de uma oferta ──────────────────────────────────────────────────────

def print_offer(offer: dict, idx: int, filter_name: str):
    product      = offer.get("product") or {}
    offer_detail = offer.get("offerDetail") or {}
    auction      = offer.get("auction") or {}
    location     = product.get("location") or {}
    sub_cat      = (product.get("subCategory") or {})
    cat          = (sub_cat.get("category") or {})

    titulo      = product.get("shortDesc") or product.get("description") or "?"
    offer_id    = offer.get("id")
    link        = f"{SITE_URL}/oferta/{offer_id}"
    valor_ini   = parse_valor(offer_detail.get("initialBidValue") or offer.get("price"))
    valor_atual = parse_valor(offer_detail.get("currentMinBid") or offer_detail.get("initialBidValue"))
    qtde        = extract_quantidade(titulo)
    preco_un    = round(valor_atual / qtde, 2) if qtde and valor_atual else None

    flag = ""
    if preco_un:
        # threshold provisório — vamos ver a distribuição e decidir depois
        flag = f"{GREEN}✅" if preco_un <= 15 else f"{YELLOW}⚠️ " if preco_un <= 30 else f"{RED}❌"

    print(f"\n{'─'*70}")
    src_label = f"{CYAN}[{filter_name}]{RESET} " if filter_name else ""
    print(f"{BOLD}{YELLOW}[{idx}] {src_label}{titulo[:60]}{RESET}")
    print(f"{'─'*70}")
    print(f"  {DIM}id:{RESET}          {offer_id}")
    print(f"  {DIM}cat/subcat:{RESET}  {cat.get('description') or '?'} / {sub_cat.get('description') or '?'}")
    print(f"  {DIM}local:{RESET}       {location.get('city') or '?'} / {location.get('state') or '?'}")
    print(f"  {DIM}valor ini:{RESET}   {fmt_brl(valor_ini)}")
    print(f"  {DIM}valor atual:{RESET} {fmt_brl(valor_atual)}")
    print(f"  {DIM}encerra:{RESET}     {offer.get('endDate') or offer.get('endDateTime') or '?'}")
    print(f"  {DIM}modalidade:{RESET}  {auction.get('modalityDesc') or '?'}")
    print(f"  {DIM}quantidade:{RESET}  {f'~{qtde:,} un.' if qtde else f'{RED}não detectada{RESET}'}")
    if preco_un:
        print(f"  {DIM}preço/un:{RESET}    R$ {preco_un:.2f}  {flag}{RESET}")
    print(f"  {DIM}link:{RESET}        {CYAN}{link}{RESET}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Debug acessórios/vestuário Superbid")
    parser.add_argument("--vestuario", action="store_true", help="Inclui vestuário além de acessórios")
    parser.add_argument("--pages",     type=int, default=3,  help="Páginas por filtro (default: 3)")
    parser.add_argument("--page-size", type=int, default=30, help="Itens por página (default: 30)")
    parser.add_argument("--raw",  action="store_true", help="JSON bruto da 1ª oferta")
    parser.add_argument("--save", action="store_true", help="Salva em acessorios_debug.json")
    args = parser.parse_args()

    filtros_ativos = ["acessorios"]
    if args.vestuario:
        filtros_ativos.append("vestuario")

    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}  SUPERBID — DEBUG ACESSÓRIOS{' + VESTUÁRIO' if args.vestuario else ''}{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")
    for f in filtros_ativos:
        print(f"  {DIM}filter: {FILTERS[f]}{RESET}")
    print(f"  {DIM}páginas: {args.pages}  |  page_size: {args.page_size}{RESET}")

    session = requests.Session()
    session.headers.update(HEADERS)

    # Coleta por filtro
    all_offers_tagged: list[tuple[dict, str]] = []

    for fname in filtros_ativos:
        print(f"\n{BOLD}  ── {fname.upper()} ──────────────────────────────────────────────{RESET}")
        offers = fetch_all(session, FILTERS[fname], args.pages, args.page_size)
        print(f"  {GREEN}OK  {len(offers)} coletados{RESET}")
        for o in offers:
            all_offers_tagged.append((o, fname))

    all_offers = [o for o, _ in all_offers_tagged]

    # Deduplicação por id
    seen: set = set()
    unique_tagged = []
    for o, fname in all_offers_tagged:
        oid = o.get("id")
        if oid and oid not in seen:
            seen.add(oid)
            unique_tagged.append((o, fname))

    dupes = len(all_offers_tagged) - len(unique_tagged)

    print(f"\n\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}  OFERTAS ÚNICAS: {len(unique_tagged)}{RESET}"
          + (f"  {DIM}({dupes} duplicata(s) removida(s)){RESET}" if dupes else ""))
    print(f"{BOLD}{'='*70}{RESET}")

    if args.raw and unique_tagged:
        print(f"\n{BOLD}  JSON BRUTO — 1ª oferta:{RESET}\n")
        print(json.dumps(unique_tagged[0][0], ensure_ascii=False, indent=2))

    for idx, (offer, fname) in enumerate(unique_tagged, 1):
        print_offer(offer, idx, fname if args.vestuario else "")

    # ── Análise estatística de preço/un ──────────────────────────────────────
    precos_un = []
    for offer, _ in unique_tagged:
        product      = offer.get("product") or {}
        offer_detail = offer.get("offerDetail") or {}
        titulo       = product.get("shortDesc") or ""
        valor_atual  = parse_valor(
            offer_detail.get("currentMinBid") or offer_detail.get("initialBidValue")
        )
        qtde = extract_quantidade(titulo)
        if qtde and valor_atual:
            precos_un.append(round(valor_atual / qtde, 2))

    sub_cats: dict = {}
    for offer, _ in unique_tagged:
        sc = ((offer.get("product") or {}).get("subCategory") or {}).get("description") or "?"
        sub_cats[sc] = sub_cats.get(sc, 0) + 1

    sem_qtde = sum(1 for o, _ in unique_tagged
                   if not extract_quantidade(
                       (o.get("product") or {}).get("shortDesc") or ""))

    print(f"\n\n{'='*70}")
    print(f"{BOLD}  RESUMO{RESET}")
    print(f"{'='*70}")
    print(f"  Total coletados:     {len(unique_tagged)}")
    print(f"  Com quantidade:      {len(precos_un)} ({len(precos_un)*100//len(unique_tagged) if unique_tagged else 0}%)")
    print(f"  Sem quantidade:      {sem_qtde}")

    if precos_un:
        precos_un_sorted = sorted(precos_un)
        print(f"\n  {BOLD}Distribuição preço/unidade:{RESET}")
        print(f"    Mínimo:    R$ {min(precos_un):.2f}")
        print(f"    Mediana:   R$ {statistics.median(precos_un):.2f}")
        print(f"    Média:     R$ {statistics.mean(precos_un):.2f}")
        print(f"    Máximo:    R$ {max(precos_un):.2f}")

        # Faixas
        faixas = [
            ("≤ R$ 5/un",          sum(1 for p in precos_un if p <= 5)),
            ("R$ 5–15/un",         sum(1 for p in precos_un if 5 < p <= 15)),
            ("R$ 15–30/un",        sum(1 for p in precos_un if 15 < p <= 30)),
            ("R$ 30–50/un",        sum(1 for p in precos_un if 30 < p <= 50)),
            ("> R$ 50/un",         sum(1 for p in precos_un if p > 50)),
        ]
        print(f"\n  {BOLD}Faixas:{RESET}")
        for label, cnt in faixas:
            bar = "█" * cnt
            print(f"    {label:<20} {cnt:>3}x  {GREEN if '≤' in label else YELLOW}{bar}{RESET}")

        # Top 5 mais baratos
        top5 = sorted(
            [(o, f, parse_valor((o.get("offerDetail") or {}).get("currentMinBid")
                                or (o.get("offerDetail") or {}).get("initialBidValue")),
              extract_quantidade((o.get("product") or {}).get("shortDesc") or ""))
             for o, f in unique_tagged],
            key=lambda x: (x[2] / x[3]) if x[2] and x[3] else float("inf")
        )[:5]

        print(f"\n  {BOLD}Top 5 mais baratos por unidade:{RESET}")
        for offer, fname, val, qtde in top5:
            if not val or not qtde:
                continue
            titulo = (offer.get("product") or {}).get("shortDesc") or "?"
            pu = val / qtde
            print(f"    {GREEN}R$ {pu:.2f}/un{RESET}  ~{qtde:,}un  {DIM}{titulo[:50]}{RESET}")

    print(f"\n  {BOLD}Sub-categorias:{RESET}")
    for sc, cnt in sorted(sub_cats.items(), key=lambda x: -x[1]):
        print(f"    {sc:<35} {cnt}")

    if args.save:
        fname_out = "acessorios_debug.json"
        with open(fname_out, "w", encoding="utf-8") as f:
            json.dump(
                {"timestamp": datetime.now(timezone.utc).isoformat(),
                 "offers": [o for o, _ in unique_tagged]},
                f, ensure_ascii=False, indent=2, default=str
            )
        print(f"\n  {GREEN}Salvo em: {fname_out}{RESET}")

    session.close()
    print()


if __name__ == "__main__":
    main()
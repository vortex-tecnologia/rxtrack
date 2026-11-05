#!/usr/bin/env python3
"""
Script de Teste Isolado — API GraphQL ESL Cloud (Query: freight)
================================================================
Testa a consulta de Fretes / Minutas / NF-es via GraphQL antes de aplicar no projeto,
validando especialmente a captura da FILIAL EMISSORA (corporationId / corporation)
e dos dados de Minutas e Notas Fiscais.

Como usar:
  Opção 1 (Dentro do container Docker, puxando o token do banco automaticamente):
    docker exec -it rxtrack_homolog_backend python test_graphql_freight.py --esl-code 5240293
    docker exec -it rxtrack_homolog_backend python test_graphql_freight.py --id 56875290
    docker exec -it rxtrack_homolog_backend python test_graphql_freight.py --chave 3526...

  Opção 2 (Direto no terminal local passando o token):
    python3 backend/test_graphql_freight.py --token "SEU_TOKEN_DATAEXPORT" --esl-code 5240293
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

# Mapeamento oficial dos IDs das filiais emissoras na ESL Cloud (mesmo usado no RXTrack)
MAPA_ID_ESL_FILIAL = {
    "237988": "RD EXPRESSO (RJ)",
    "237978": "QUICK SAO PAULO (SP)",
    "237973": "QUICK BRASILIA (DF)",
    "237974": "QUICK GOIANIA (GO)",
}

# 1. Query enxuta focada nos campos escalares documentados + Emissor (corporationId)
QUERY_FREIGHT_ESCALAR = """
query freight($params: FreightInput!, $after: String, $first: Int) {
  freight(params: $params, after: $after, first: $first) {
    edges {
      cursor
      node {
        id
        corporationId
        referenceNumber
        invoiceDocumentType
        emissionType
        type
        status
        modal
        serviceAt
        serviceDate
        createdAt
        total
        subtotal
        taxedWeight
        realWeight
        invoicesWeight
        invoicesTotalVolumes
        invoicesValue
        freightInvoicesCount
        paymentAccountableType
        paymentType
        draftServiceUrl
        pdfServiceUrl
        comments
      }
    }
    pageInfo {
      endCursor
      hasNextPage
      hasPreviousPage
      startCursor
    }
  }
}
"""

# 2. Query estendida com todos os objetos aninhados (corporation, payer, sender, recipient, cte, invoices)
QUERY_FREIGHT_COMPLETA = """
query freight($params: FreightInput!, $after: String, $first: Int) {
  freight(params: $params, after: $after, first: $first) {
    edges {
      cursor
      node {
        id
        corporationId
        referenceNumber
        invoiceDocumentType
        emissionType
        type
        status
        modal
        serviceAt
        serviceDate
        total
        taxedWeight
        invoicesTotalVolumes
        invoicesValue
        freightInvoicesCount
        corporation {
          id
          name
          nickname
          document
        }
        payer {
          id
          name
          nickname
          document
        }
        sender {
          id
          name
          nickname
          document
        }
        recipient {
          id
          name
          nickname
          document
          mainAddress {
            line1
            line2
            number
            neighborhood
            postalCode
            city {
              name
              state {
                code
              }
            }
          }
        }
        cte {
          id
          number
          series
          key
          status
        }
        freightInvoices {
          invoice {
            id
            number
            series
            key
            value
            weight
            volume
          }
        }
      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""


def obter_credenciais_django(schema_name=None):
    """Tenta carregar token_analytics e dominio_esl direto do banco do Django (multi-tenant)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
        import django
        django.setup()

        from django_tenants.utils import get_tenant_model, schema_context
        from configuracao.models import ConfiguracaoSistema

        tenants = [schema_name] if schema_name else [
            t.schema_name for t in get_tenant_model().objects.exclude(schema_name="public")
        ]
        if not tenants:
            tenants = ["public"]

        for s_name in tenants:
            try:
                with schema_context(s_name):
                    cfg = ConfiguracaoSistema.load()
                    if cfg and cfg.token_analytics:
                        print(f"[Django] Credenciais carregadas do schema '{s_name}' (Domínio: {cfg.dominio_esl})")
                        return cfg.token_analytics.strip(), cfg.dominio_esl.strip()
            except Exception:
                continue
    except Exception as e:
        print(f"[Aviso] Não foi possível carregar do banco Django local ({e}). Usando parâmetros CLI/ENV.")
    return None, None


class SimpleResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text) if self.text else {}


def executar_query(dominio, token, query_str, params_filtro, first=5):
    url = f"https://{dominio}/graphql"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "RXTrack-Test/1.0",
    }
    payload = {
        "query": query_str,
        "variables": {
            "params": params_filtro,
            "first": first,
        },
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", errors="replace")
            return SimpleResponse(r.status, body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return SimpleResponse(e.code, body)


def exibir_resultado_node(node):
    fid = str(node.get("id") or "")
    corp_id = str(node.get("corporationId") or "")
    filial_nome = MAPA_ID_ESL_FILIAL.get(corp_id, f"Filial não mapeada (ID ESL: {corp_id})")
    corp_obj = node.get("corporation") or {}
    if corp_obj:
        filial_nome += f" | Razão/Fantasia ESL: {corp_obj.get('nickname') or corp_obj.get('name')} (CNPJ: {corp_obj.get('document')})"

    print("\n" + "=" * 75)
    print(f"✅ FRETE LOCALIZADO NA ESL (ID Interno: {fid})")
    print("=" * 75)
    print(f"🏢 FILIAL EMISSORA (corporationId): {corp_id}  --->  {filial_nome}")
    print(f"📄 Número/Ref (referenceNumber)  : {node.get('referenceNumber')}")
    print(f"🏷️  Tipo Documento / Emissão      : doc={node.get('invoiceDocumentType')} | emissao={node.get('emissionType')} | type={node.get('type')}")
    print(f"🚚 Modal / Status                : modal={node.get('modal')} | status={node.get('status')}")
    print(f"📅 Data do Serviço               : {node.get('serviceDate') or node.get('serviceAt')}")
    print(f"💰 Valor Total Frete / Notas     : Frete R$ {node.get('total')} | Mercadoria R$ {node.get('invoicesValue')}")
    print(f"⚖️  Peso Taxado / Volumes         : {node.get('taxedWeight')} kg | {node.get('invoicesTotalVolumes')} vol(s) | {node.get('freightInvoicesCount')} nota(s)")

    if node.get("payer"):
        p = node["payer"]
        print(f"💳 Pagador (payer)               : {p.get('name') or p.get('nickname')} (Doc: {p.get('document')})")
    if node.get("sender"):
        s = node["sender"]
        print(f"📤 Remetente (sender)            : {s.get('name') or s.get('nickname')} (Doc: {s.get('document')})")
    if node.get("recipient"):
        r = node["recipient"]
        end_str = ""
        addr = r.get("mainAddress") or {}
        if addr:
            city = (addr.get("city") or {}).get("name", "")
            uf = ((addr.get("city") or {}).get("state") or {}).get("code", "")
            rua = addr.get("line1") or addr.get("street") or ""
            cep = addr.get("postalCode") or addr.get("zipCode") or ""
            end_str = f" — {rua}, {addr.get('number')} - {addr.get('neighborhood')} ({city}/{uf}) | CEP: {cep}"
        print(f"📥 Destinatário (recipient)      : {r.get('name') or r.get('nickname')} (Doc: {r.get('document')}){end_str}")
    if node.get("cte"):
        c = node["cte"]
        print(f"📑 CT-e Vinculado                : Nº {c.get('number')} (Série {c.get('series')}) | Chave: {c.get('key')}")
    if node.get("freightInvoices"):
        invs = [fi.get("invoice") or {} for fi in node["freightInvoices"] if fi.get("invoice")]
        nums = [f"#{i.get('number')} (Chave: {i.get('key')})" for i in invs]
        print(f"📦 Notas/Declarações no Frete    : {', '.join(nums)}")
    print("=" * 75)


def main():
    parser = argparse.ArgumentParser(description="Teste isolado da Query GraphQL 'freight' da ESL Cloud")
    parser.add_argument("--token", help="Token DataExport / GraphQL da ESL (se omitido, busca do banco Django)")
    parser.add_argument("--dominio", default="quickdelivery.eslcloud.com.br", help="Domínio da ESL Cloud")
    parser.add_argument("--schema", help="Nome do schema do tenant no Django (opcional)")
    parser.add_argument("--id", dest="freight_id", help="Filtrar pelo ID interno do Frete (ex: 56875290)")
    parser.add_argument("--esl-code", dest="esl_code", help="Filtrar pelo Código ESL / Minuta (ex: 5240293)")
    parser.add_argument("--chave", dest="invoice_key", help="Filtrar pela Chave da NF-e de 44 dígitos")
    parser.add_argument("--cte-key", dest="cte_key", help="Filtrar pela Chave do CT-e de 44 dígitos")
    parser.add_argument("--data", dest="service_at", help="Filtrar por data (ex: '2026-10-20 - 2026-10-25')")
    args = parser.parse_args()

    token = args.token or os.getenv("ESL_TOKEN_ANALYTICS")
    dominio = args.dominio

    if not token:
        db_token, db_dominio = obter_credenciais_django(args.schema)
        token = db_token
        if db_dominio:
            dominio = db_dominio

    if not token:
        print("❌ ERRO: Token não informado e banco Django indisponível neste ambiente.")
        print("   Passe o token com: --token 'SEU_TOKEN_DATAEXPORT'")
        sys.exit(1)

    # Monta o filtro FreightInput conforme argumentos
    params = {}
    if args.freight_id:
        params["id"] = args.freight_id
    if args.esl_code:
        params["eslCode"] = str(args.esl_code)
    if args.invoice_key:
        params["invoiceKey"] = str(args.invoice_key)
    if args.cte_key:
        params["cteKey"] = str(args.cte_key)
    if args.service_at:
        params["serviceAt"] = str(args.service_at)

    # Se nenhum filtro foi passado, usa o caso real de minuta #5240293 / ID 56875290 documentado
    if not params:
        print("ℹ️ Nenhum filtro informado. Testando com o caso real da Minuta #5240293 (ID interno: 56875290)...")
        params = {"id": "56875290"}

    print(f"\n🚀 Consultando https://{dominio}/graphql com params={json.dumps(params)} ...")

    # Teste 1: Tenta a Query Completa (com objetos aninhados corporation, payer, recipient)
    resp = executar_query(dominio, token, QUERY_FREIGHT_COMPLETA, params)
    print(f"📡 Status HTTP (Query Completa): {resp.status_code}")

    dados = resp.json() if resp.text else {}
    if "errors" in dados:
        print(f"⚠️ Schema recusou algum subcampo da Query Completa: {json.dumps(dados['errors'], ensure_ascii=False)}")
        print("🔄 Testando a Query Escalar Oficial (exatamente como na documentação)...")
        import time
        time.sleep(2.1)
        resp = executar_query(dominio, token, QUERY_FREIGHT_ESCALAR, params)
        print(f"📡 Status HTTP (Query Escalar): {resp.status_code}")
        dados = resp.json() if resp.text else {}

    if "errors" in dados:
        print(f"❌ Erros GraphQL retornados:\n{json.dumps(dados['errors'], indent=2, ensure_ascii=False)}")
        sys.exit(1)

    freight_data = (dados.get("data") or {}).get("freight") or {}
    edges = freight_data.get("edges") or []
    print(f"📦 Total de registros retornados nesta página: {len(edges)}")

    if not edges:
        print("⚠️ Nenhum frete encontrado para esses filtros. Resposta bruta:")
        print(json.dumps(dados, indent=2, ensure_ascii=False))
        return

    for edge in edges:
        node = edge.get("node") or {}
        exibir_resultado_node(node)

    print("\n🔍 JSON Bruto do primeiro registro (para inspeção completa):")
    print(json.dumps(edges[0].get("node"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()


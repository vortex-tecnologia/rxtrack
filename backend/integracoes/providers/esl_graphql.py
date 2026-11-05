# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# integracoes/providers/esl_graphql.py
"""
Cliente + normalizador da Query GraphQL `freight` da ESL Cloud.

Este módulo NÃO depende de Django (só de `requests`, importado sob demanda), para poder
ser testado isoladamente contra a ESL real.

Autenticação: mesmo token do Data Export (`ConfiguracaoSistema.token_analytics`).
Limite da ESL: 1 requisição a cada 2s por IP (senão HTTP 429).
"""
import json
import logging
import re
import time
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GraphQLFreightError(Exception):
    """Falha de comunicação ou erro retornado pelo GraphQL da ESL."""


# Campos validados contra o schema real da ESL (introspecção em 04/11/2026).
# `destinationAddress` = endereço de entrega do frete; `recipient.mainAddress` = fallback.
QUERY_FREIGHT = """
query freight($params: FreightInput!, $first: Int) {
  freight(params: $params, first: $first) {
    edges {
      node {
        id
        sequenceCode
        corporationSequenceNumber
        uniqueId
        originalFreightId
        corporationId
        status
        modal
        type
        emissionType
        invoiceDocumentType
        total
        invoicesValue
        taxedWeight
        realWeight
        invoicesWeight
        invoicesVolumes
        invoicesTotalVolumes
        freightInvoicesCount
        corporation { nickname name document }
        payer { name nickname document }
        sender { name nickname document }
        recipient {
          name nickname document
          mainAddress { line1 line2 number neighborhood postalCode city { name state { code } } }
        }
        destinationAddress { line1 line2 number neighborhood postalCode city { name state { code } } }
        cte { number series key }
        freightInvoices { invoice { id number key volume weight value } }
      }
    }
  }
}
"""

PLACEHOLDERS_TEXTO = (
    "CONSULTE", "DADOS NÃO REPASSADOS", "DADOS NAO REPASSADOS",
    "NÃO INFORMADO", "NAO INFORMADO", "ENDEREÇO NÃO INFORMADO",
)

# Códigos da ESL (corporationId) -> nome oficial da filial no RXTrack.
# Mesmo mapa já usado em manifesto.tasks._buscar_ou_criar_filial_unificada.
MAPA_ID_ESL_FILIAL = {
    "237988": "RD EXPRESSO",
    "237978": "QUICK SAO PAULO",
    "237973": "QUICK BRASILIA",
    "237974": "QUICK GOIANIA",
}


# ───────────────────────── helpers puros ─────────────────────────
def _s(valor) -> Optional[str]:
    """str limpa ou None (vazio/None)."""
    if valor is None:
        return None
    v = str(valor).strip()
    return v or None


def limpar_cep(valor) -> Optional[str]:
    """Só devolve CEP com exatamente 8 dígitos; senão None."""
    digitos = re.sub(r"\D", "", str(valor or ""))
    return digitos if len(digitos) == 8 else None


def normalizar_numero(valor) -> Optional[str]:
    """Número de documento sem zeros à esquerda ('0509' -> '509'). None se vazio."""
    v = _s(valor)
    if not v:
        return None
    return v.lstrip("0") or "0"


def chave_44(valor) -> Optional[str]:
    """Só devolve a chave se for de 44 dígitos numéricos (chave real); senão None."""
    v = _s(valor)
    return v if (v and len(v) == 44 and v.isdigit()) else None


def texto_e_placeholder(texto) -> bool:
    t = (texto or "").strip().upper()
    return (not t) or any(p in t for p in PLACEHOLDERS_TEXTO)


def freight_id_valido(valor, numero_nota=None, chave=None, chave_acesso=None) -> bool:
    """ID interno de frete da ESL: só dígitos, >= 100 e diferente do número/chave da própria nota."""
    v = _s(valor)
    if not v or not v.isdigit() or int(v) < 100:
        return False
    if numero_nota and v == str(numero_nota).strip():
        return False
    chave_ref = chave if chave is not None else chave_acesso
    if chave_ref and v == str(chave_ref).strip():
        return False
    return True


def _montar_endereco(addr: Optional[dict]) -> Optional[dict]:
    if not addr:
        return None
    cidade = addr.get("city") or {}
    estado = cidade.get("state") or {}
    end = {
        "logradouro": _s(addr.get("line1")),
        "complemento": _s(addr.get("line2")),
        "numero": _s(addr.get("number")),
        "bairro": _s(addr.get("neighborhood")),
        "cidade": _s(cidade.get("name")),
        "uf": _s(estado.get("code")),
        "cep": limpar_cep(addr.get("postalCode")),
    }
    if not (end["logradouro"] or end["cep"]):
        return None
    return end


def endereco_texto(end: Optional[dict]) -> Optional[str]:
    """Formato do webhook: 'RUA X, 10 - BAIRRO (CIDADE/UF)' em maiúsculas, sem separadores vazios."""
    if not end or not end.get("logradouro"):
        return None
    txt = end["logradouro"]
    if end.get("numero"):
        txt += f", {end['numero']}"
    if end.get("bairro"):
        txt += f" - {end['bairro']}"
    cidade_uf = "/".join(p for p in (end.get("cidade"), end.get("uf")) if p)
    if cidade_uf:
        txt += f" ({cidade_uf})"
    return txt.upper().strip()


def _nome_pessoa(p: Optional[dict]) -> Optional[str]:
    """Nome usado para clientes: apelido (nickname) se houver, igual aos Reports do Data Export."""
    if not p:
        return None
    return _s(p.get("nickname")) or _s(p.get("name"))


def normalizar_frete(node: dict) -> dict:
    """Converte o `node` do GraphQL em um dict plano e estável para o RXTrack."""
    corp = node.get("corporation") or {}
    cte = node.get("cte") or {}
    recipient = node.get("recipient") or {}

    endereco = _montar_endereco(node.get("destinationAddress")) or _montar_endereco(recipient.get("mainAddress"))

    notas = []
    soma_volumes = 0
    for fi in node.get("freightInvoices") or []:
        inv = (fi or {}).get("invoice") or {}
        if not inv:
            continue
        vol_inv = None
        try:
            if inv.get("volume") is not None:
                vol_inv = int(inv.get("volume") or 0)
                soma_volumes += vol_inv
        except (TypeError, ValueError):
            vol_inv = None
        notas.append({
            "id": _s(inv.get("id")),
            "numero": _s(inv.get("number")),
            "chave": chave_44(inv.get("key")),
            "volumes": vol_inv,
            "peso": inv.get("weight"),
            "valor": inv.get("value"),
        })

    volumes = node.get("invoicesVolumes") or node.get("invoicesTotalVolumes") or soma_volumes or None
    peso = node.get("taxedWeight")
    if peso in (None, 0, 0.0):
        peso = node.get("realWeight") or node.get("invoicesWeight") or peso

    # CT-e vs Minuta:
    # - Quando é CT-e, `cte.number` e `cte.key` vêm preenchidos.
    # - Quando é Minuta (`emissionType == "draft"` e `cte == null`), não há chave de CT-e,
    #   mas o número da Minuta na filial vem em `corporationSequenceNumber` (ex: 17360 em `/17360`).
    cte_num_real = _s(cte.get("number"))
    cte_chave = chave_44(cte.get("key"))
    minuta_numero = _s(node.get("corporationSequenceNumber")) or _s(node.get("sequenceCode"))
    emission_type = _s(node.get("emissionType"))
    eh_minuta = bool(not cte_num_real and not cte_chave and (emission_type == "draft" or minuta_numero))

    return {
        "freight_id": _s(node.get("id")),
        "sequence_code": _s(node.get("sequenceCode")),
        "corporation_sequence_number": _s(node.get("corporationSequenceNumber")),
        "unique_id": _s(node.get("uniqueId")),
        "original_freight_id": _s(node.get("originalFreightId")),
        "corporation_id": _s(node.get("corporationId")),
        "corporation_nome": _s(corp.get("nickname")) or _s(corp.get("name")),
        "corporation_cnpj": re.sub(r"\D", "", corp.get("document") or "") or None,
        "status": _s(node.get("status")),
        "modal": _s(node.get("modal")),
        "tipo": _s(node.get("type")),
        "emission_type": emission_type,
        "eh_minuta": eh_minuta,
        "minuta_numero": minuta_numero if eh_minuta else None,
        "tipo_documento": _s(node.get("invoiceDocumentType")),
        "valor_frete": node.get("total"),
        "valor_notas": node.get("invoicesValue"),
        "peso_taxado": peso,
        "volumes": volumes,
        "pagador_nome": _nome_pessoa(node.get("payer")),
        "pagador_documento": re.sub(r"\D", "", (node.get("payer") or {}).get("document") or "") or None,
        "remetente_nome": _nome_pessoa(node.get("sender")),
        "remetente_documento": re.sub(r"\D", "", (node.get("sender") or {}).get("document") or "") or None,
        "destinatario_nome": _s(recipient.get("name")) or _s(recipient.get("nickname")),
        "destinatario_documento": re.sub(r"\D", "", recipient.get("document") or "") or None,
        "endereco": endereco,
        "cte_numero": cte_num_real or minuta_numero,
        "cte_serie": _s(cte.get("series")),
        "cte_chave": cte_chave,
        "notas": notas,
    }


# ───────────────────────── cliente HTTP ─────────────────────────
def _post_requests(url: str, headers: dict, payload: dict, timeout: int) -> Tuple[int, str]:
    try:
        import requests
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        return r.status_code, r.text
    except ImportError:
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode("utf-8", errors="ignore")


def consultar_frete(
    dominio: str,
    token: str,
    freight_id,
    timeout: int = 30,
    post: Optional[Callable[[str, dict, dict, int], Tuple[int, str]]] = None,
    sleep: Callable[[float], None] = time.sleep,
    max_429: int = 2,
    _profundidade: int = 0,
) -> Optional[dict]:
    """
    Consulta UM frete pelo ID interno da ESL (`freight.id`) e devolve o dict normalizado.

    - Devolve None se a ESL não encontrar o frete (ou se devolver um frete de ID diferente do pedido:
      nunca "chuta" um frete).
    - Levanta GraphQLFreightError em erro HTTP / erro GraphQL / resposta inválida.
    """
    fid = _s(freight_id)
    if not fid or not fid.isdigit():
        raise GraphQLFreightError(f"freight_id inválido: {freight_id!r}")
    if not dominio or not token:
        raise GraphQLFreightError("Domínio ESL ou token (Data Export/GraphQL) não configurados.")

    post = post or _post_requests
    url = f"https://{dominio}/graphql"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    payload = {"query": QUERY_FREIGHT, "variables": {"params": {"id": fid}, "first": 1}}

    tentativas_429 = 0
    while True:
        try:
            status, texto = post(url, headers, payload, timeout)
        except Exception as exc:  # rede / timeout
            raise GraphQLFreightError(f"Falha de rede ao consultar frete {fid}: {exc}") from exc

        if status == 429 and tentativas_429 < max_429:
            tentativas_429 += 1
            logger.warning("GraphQL ESL 429 (frete %s). Aguardando 2.5s (tentativa %s).", fid, tentativas_429)
            sleep(2.5)
            continue
        break

    if status != 200:
        raise GraphQLFreightError(f"HTTP {status} ao consultar frete {fid}: {(texto or '')[:300]}")

    try:
        corpo = json.loads(texto) if texto else {}
    except ValueError as exc:
        raise GraphQLFreightError(f"Resposta não-JSON da ESL para frete {fid}: {(texto or '')[:200]}") from exc

    if corpo.get("errors"):
        raise GraphQLFreightError(f"Erro GraphQL (frete {fid}): {json.dumps(corpo['errors'], ensure_ascii=False)[:500]}")

    edges = (((corpo.get("data") or {}).get("freight") or {}).get("edges")) or []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        if _s(node.get("id")) == fid:
            norm = normalizar_frete(node)
            # Reentrega ('Freight::Redelivery'): na ESL, o frete de reentrega tem uniqueId=null
            # e aponta para o frete original em `originalFreightId`. Herdamos o unique_id e sequence_code
            # do frete original para que a bipagem da etiqueta física colada na caixa funcione perfeitamente!
            precisa_herdar = (not norm.get("unique_id") or not norm.get("sequence_code"))
            if precisa_herdar and node.get("originalFreightId") and _profundidade < 2:
                orig_id = _s(node.get("originalFreightId"))
                if orig_id and orig_id != fid:
                    try:
                        orig = consultar_frete(
                            dominio, token, orig_id, timeout=timeout, post=post, sleep=sleep,
                            max_429=max_429, _profundidade=_profundidade + 1
                        )
                        if orig:
                            if not norm.get("unique_id") and orig.get("unique_id"):
                                norm["unique_id"] = orig["unique_id"]
                                logger.info(
                                    "Frete %s (reentrega) herdou unique_id '%s' do frete original %s",
                                    fid, norm["unique_id"], orig_id
                                )
                            if not norm.get("sequence_code") and orig.get("sequence_code"):
                                norm["sequence_code"] = orig["sequence_code"]
                                logger.info(
                                    "Frete %s (reentrega) herdou sequence_code '%s' do frete original %s",
                                    fid, norm["sequence_code"], orig_id
                                )
                    except Exception as exc_orig:
                        logger.warning(
                            "Falha ao consultar frete original %s para herdar unique_id/sequence_code: %s",
                            orig_id, exc_orig
                        )
            return norm

    if edges:
        logger.warning("GraphQL ESL devolveu frete(s) diferente(s) do pedido (%s). Ignorado.", fid)
    return None


# ───────────────────── casamento nota -> frete ─────────────────────
def mapear_notas_para_fretes(notas: List[dict], ocorrencias: List[dict]) -> Dict[object, dict]:
    """
    Descobre o `freight.id` de cada nota do manifesto a partir de /api/invoice_occurrences.

    notas:       [{'id', 'numero', 'chave'}]            (notas do manifesto no RXTrack)
    ocorrencias: [{'numero', 'chave', 'freight_id'}]    (itens da ESL)

    Retorna {nota_id: {'freight_id': str|None, 'motivo': 'chave'|'numero'|'ambigua'|'sem_match'}}.
    Regra de ouro: se houver mais de um frete candidato, NÃO escolhe (marca 'ambigua').

    ATENÇÃO: o número da minuta/nota NÃO é o `sequenceCode` do frete (validado na ESL real:
    frete 56875290 tem sequenceCode 463164 e a minuta 5240293 é o número da declaração dentro dele).
    Por isso NÃO se casa nota por sequenceCode.
    """
    por_chave: Dict[str, set] = {}
    por_numero: Dict[str, set] = {}
    for oc in ocorrencias:
        fid = _s(oc.get("freight_id"))
        if not fid:
            continue
        k = chave_44(oc.get("chave"))
        n = normalizar_numero(oc.get("numero"))
        if k:
            por_chave.setdefault(k, set()).add(fid)
        if n:
            por_numero.setdefault(n, set()).add(fid)

    resultado: Dict[object, dict] = {}
    for nf in notas:
        achou = None
        ambigua = False
        k = chave_44(nf.get("chave"))
        n = normalizar_numero(nf.get("numero"))
        for motivo, indice, valor in (("chave", por_chave, k), ("numero", por_numero, n)):
            if not valor or valor not in indice:
                continue
            candidatos = indice[valor]
            if len(candidatos) == 1:
                achou = (next(iter(candidatos)), motivo)
                break
            ambigua = True
            break
        if achou:
            resultado[nf["id"]] = {"freight_id": achou[0], "motivo": achou[1]}
        else:
            resultado[nf["id"]] = {"freight_id": None, "motivo": "ambigua" if ambigua else "sem_match"}
    return resultado


def nota_pertence_ao_frete(nota: dict, dados_frete: dict) -> bool:
    """
    Dupla checagem: a nota realmente está dentro do frete devolvido pelo GraphQL?
    (chave de 44 dígitos ou número da NF/minuta dentro de `freightInvoices`).
    """
    k = chave_44(nota.get("chave"))
    n = normalizar_numero(nota.get("numero"))
    for inv in dados_frete.get("notas") or []:
        if k and inv.get("chave") == k:
            return True
        if n and normalizar_numero(inv.get("numero")) == n:
            return True
    return False

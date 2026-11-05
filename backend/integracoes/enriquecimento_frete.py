# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# integracoes/enriquecimento_frete.py
"""
Enriquecimento de Notas/Minutas/Fretes via GraphQL `freight` da ESL Cloud.

Fluxo (para QUALQUER origem: webhook ou busca manual):
  1) /api/invoice_occurrences?manifest_id=<nº visual>  -> descobre o `freight.id` (ID interno) de cada nota
  2) GraphQL freight(params:{id})                      -> 1 chamada por FRETE (não por nota)
  3) Grava: filial emissora, ID interno, CT-e, e (só se faltando) CEP/endereço/destinatário

Princípios de segurança (mudança em área crítica):
  - NUNCA chuta: nota ambígua (mais de um frete candidato) ou que não conste dentro do frete é ignorada e contada.
  - NUNCA apaga dado existente. Campos já preenchidos só mudam com `forcar=True`.
  - NUNCA altera `tipo_operacao` (o webhook é a fonte de verdade dele).
  - Qualquer falha é isolada por frete e devolvida no resumo; o chamador nunca deve quebrar por causa disso.
"""
import logging
import time
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from integracoes.providers.esl_graphql import (
    MAPA_ID_ESL_FILIAL,
    GraphQLFreightError,
    consultar_frete,
    endereco_texto,
    freight_id_valido,
    limpar_cep,
    mapear_notas_para_fretes,
    normalizar_numero,
    nota_pertence_ao_frete,
    texto_e_placeholder,
)

logger = logging.getLogger(__name__)

INTERVALO_MIN_ESL = 2.1  # ESL: 1 requisição / 2s por IP (429 se exceder)
MAX_PAGINAS_OCORRENCIAS = 60
PLACEHOLDERS_DESTINATARIO = {'', 'NÃO INFORMADO', 'NAO INFORMADO', 'DADOS NÃO REPASSADOS PELA ESL'}

_ultimo_request = [0.0]


def respeitar_intervalo_esl():
    """Garante >= 2.1s entre chamadas à ESL feitas por este processo."""
    espera = INTERVALO_MIN_ESL - (time.monotonic() - _ultimo_request[0])
    if espera > 0:
        time.sleep(espera)
    _ultimo_request[0] = time.monotonic()


# ───────────────────────── filial emissora ─────────────────────────
def resolver_filial_emissora(corporation_id, nome=None, cache=None):
    """
    Resolve o `corporationId` da ESL na Filial do RXTrack. NUNCA cria filial nova e NUNCA usa CNPJ
    (o CNPJ de Goiânia 08296144000734 está mapeado como 'QUICK BRASILIA' em _buscar_ou_criar_filial_unificada).
    Ordem: mapa oficial de IDs -> Filial.id_filial_tms -> nome exato. Retorna None se não achar.
    """
    from usuarios.models import Filial

    cid = str(corporation_id or '').strip()
    if not cid:
        return None
    chave_cache = (cid, (nome or '').strip().upper())
    if cache is not None and chave_cache in cache:
        return cache[chave_cache]

    filial = None
    nome_oficial = MAPA_ID_ESL_FILIAL.get(cid)
    if nome_oficial:
        filial = Filial.objects.filter(nome__iexact=nome_oficial).first()
    if not filial:
        filial = Filial.objects.filter(id_filial_tms=cid).first()
    if not filial and nome:
        filial = Filial.objects.filter(nome__iexact=nome.strip()).first()

    if filial and not filial.id_filial_tms:
        filial.id_filial_tms = cid
        filial.save(update_fields=['id_filial_tms'])
    if not filial:
        logger.warning("⚠️ [EMISSOR] corporationId %s (%s) não corresponde a nenhuma Filial cadastrada.", cid, nome)

    if cache is not None:
        cache[chave_cache] = filial
    return filial


# ───────────────────────── Frete ─────────────────────────
def _decimal(valor):
    if valor is None or valor == '':
        return None
    try:
        return Decimal(str(round(float(valor), 2)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def upsert_frete(dados, filial, forcar=False):
    """Cria/atualiza o `Frete` local a partir do dict normalizado do GraphQL. Devolve o Frete."""
    from manifesto.models import Frete

    fid = dados['freight_id']
    seq = dados.get('sequence_code')
    cte_n = dados.get('cte_numero')
    cte_k = dados.get('cte_chave')

    frete = Frete.objects.filter(esl_freight_id=fid).first()

    # Adoção de Frete antigo (criado pelo Data Export/webhook) — com travas contra colisão.
    if not frete and cte_k:
        cand = Frete.objects.filter(chave_cte=cte_k).first()
        if cand and (not cand.esl_freight_id or cand.esl_freight_id == fid):
            frete = cand
    if not frete:
        for cand in Frete.objects.filter(freight_id_tms__in=[x for x in (fid, seq) if x]):
            cte_coerente = (not cand.numero_cte) or (not cte_n) or str(cand.numero_cte) == str(cte_n)
            if cte_coerente and (not cand.esl_freight_id or cand.esl_freight_id == fid):
                frete = cand
                break

    def _definir_autoritativo(obj, campo, valor):
        """Atualiza o campo no Frete sempre que o GraphQL trouxer valor válido (fonte oficial da ESL)."""
        if valor in (None, ''):
            return False
        atual = getattr(obj, campo, None)
        if atual != valor:
            setattr(obj, campo, valor)
            return True
        return False

    if frete is None:
        # `freight_id_tms` é UNIQUE: prefere o sequence_code (paridade com a busca manual) se estiver livre.
        escolhido = None
        for opcao in (seq, fid, f"esl-{fid}"):
            if opcao and not Frete.objects.filter(freight_id_tms=opcao).exists():
                escolhido = opcao
                break
        if escolhido is None:  # praticamente impossível; evita violar o UNIQUE
            escolhido = f"esl-{fid}-{int(time.time())}"
        frete = Frete(freight_id_tms=escolhido)

    frete.esl_freight_id = fid
    _definir_autoritativo(frete, 'esl_unique_id', dados.get('unique_id'))
    _definir_autoritativo(frete, 'sequence_code', dados.get('sequence_code'))
    _definir_autoritativo(frete, 'numero_cte', cte_n)
    if cte_k:
        _definir_autoritativo(frete, 'chave_cte', cte_k)
    elif dados.get('eh_minuta'):
        frete.chave_cte = None
    _definir_autoritativo(frete, 'modal', dados.get('modal'))
    _definir_autoritativo(frete, 'valor_frete', _decimal(dados.get('valor_frete')))
    _definir_autoritativo(frete, 'peso_taxado', _decimal(dados.get('peso_taxado')))
    vol = dados.get('volumes')
    _definir_autoritativo(frete, 'volumes', int(vol) if str(vol or '').isdigit() else None)
    _definir_autoritativo(frete, 'remetente', dados.get('remetente_nome'))
    _definir_autoritativo(frete, 'pagador_nome', dados.get('pagador_nome'))
    _definir_autoritativo(frete, 'pagador_documento', dados.get('pagador_documento'))

    # Emissor: dado autoritativo da ESL -> sempre atualiza.
    frete.id_filial_emissora_tms = dados.get('corporation_id')
    frete.nome_filial_emissora_tms = dados.get('corporation_nome')
    frete.filial_emissora = filial
    frete.graphql_sincronizado_em = timezone.now()
    frete.save()

    # Vincula/garante o Pagador do Frete no cadastro financeiro (ClienteBasePagadora)
    pagador_nome = (dados.get('pagador_nome') or '').strip().upper()
    if pagador_nome:
        try:
            from financeiro.models import ClienteBasePagadora
            ClienteBasePagadora.objects.get_or_create(nome=pagador_nome)
        except Exception:
            pass

    return frete


# ───────────────────────── Nota ─────────────────────────
def aplicar_em_nota(nf, dados, frete, filial, forcar=False):
    """
    Aplica os dados do frete numa NotaFiscal. Devolve (campos_alterados:list, conflitos:list).
    - Emissor/ID interno/CT-e: valem para qualquer status.
    - CEP/endereço/destinatário: só em notas PENDENTES e só quando faltando.
    """
    campos = []
    conflitos = []

    def _set(campo, valor):
        if getattr(nf, campo) != valor:
            setattr(nf, campo, valor)
            if campo not in campos:
                campos.append(campo)

    # Emissor (autoritativo)
    _set('id_filial_emissora_tms', dados.get('corporation_id'))
    _set('nome_filial_emissora_tms', dados.get('corporation_nome'))
    _set('filial_emissora', filial)

    # ID interno do frete: só preenche se vazio/suspeito; divergência vira conflito (não sobrescreve).
    fid = dados['freight_id']
    atual = (nf.freight_id_tms or '').strip()
    if not freight_id_valido(atual, nf.numero_nota, nf.chave_acesso):
        _set('freight_id_tms', fid)
    elif atual != fid:
        if forcar:
            _set('freight_id_tms', fid)
        else:
            conflitos.append(f"freight_id_tms local={atual} x ESL={fid}")

    # Frete (FK): como `nota_pertence_ao_frete` já validou que esta nota consta dentro do frete
    # oficial da ESL, sempre vincula o Frete real (substituindo eventual Frete provisório do webhook).
    _set('frete', frete)

    # Código único da etiqueta ESL (`freight.uniqueId`) e sequenceCode (`freight.sequenceCode`)
    if dados.get('unique_id'):
        _set('esl_unique_id', dados['unique_id'])
    if dados.get('sequence_code'):
        _set('sequence_code', dados['sequence_code'])

    # CT-e ou Nº da Minuta (`corporationSequenceNumber` quando emissionType == "draft")
    if dados.get('cte_numero'):
        _set('numero_cte', dados['cte_numero'])
    if dados.get('cte_chave'):
        _set('chave_cte', dados['cte_chave'])
    elif dados.get('eh_minuta') and nf.chave_cte:
        _set('chave_cte', None)

    # Dados de entrega: só em nota PENDENTE
    precisa_geo = False
    if nf.status == 'PENDENTE':
        end = dados.get('endereco') or {}
        cep = end.get('cep')
        if cep and not limpar_cep(nf.cep):
            _set('cep', cep)
            precisa_geo = True
        txt = endereco_texto(end)
        if txt and texto_e_placeholder(nf.endereco_entrega):
            _set('endereco_entrega', txt)
            precisa_geo = True
        dest = (dados.get('destinatario_nome') or '').upper().strip()
        if dest and (nf.destinatario or '').strip().upper() in PLACEHOLDERS_DESTINATARIO:
            _set('destinatario', dest[:255])

    if campos:
        nf.save(update_fields=campos)

    if precisa_geo and nf.latitude is None and nf.longitude is None:
        def _agendar_geo(nota_id=nf.id, numero=nf.numero_nota):
            try:
                from manifesto.tasks import enriquecer_geolocalizacao_nota_task
                enriquecer_geolocalizacao_nota_task.delay(nota_id)
            except Exception as exc:  # geocodificação nunca pode quebrar o enriquecimento
                logger.warning("⚠️ Erro ao agendar geocodificação da NF %s: %s", numero, exc)
        transaction.on_commit(_agendar_geo)

    return campos, conflitos


# ───────────────────────── invoice_occurrences ─────────────────────────
def listar_ocorrencias_manifesto(config, manifesto):
    """
    Lista TODAS as ocorrências de nota do manifesto na ESL (/api/invoice_occurrences) e devolve
    [{'numero','chave','freight_id'}]. Usa o número VISUAL do manifesto (mesmo padrão da busca manual).
    Levanta Exception em falha HTTP (o chamador decide se tenta de novo).
    """
    import requests

    url = f"https://{config.dominio_esl}/api/invoice_occurrences"
    headers = {"Authorization": f"Bearer {config.token_invoices}"}
    ids = [str(manifesto.numero_manifesto).strip()]
    if manifesto.manifesto_id_tms and str(manifesto.manifesto_id_tms).strip() not in ids:
        ids.append(str(manifesto.manifesto_id_tms).strip())

    for mid in ids:
        itens = []
        cursor = None
        vistos = set()
        for _ in range(MAX_PAGINAS_OCORRENCIAS):
            params = {"manifest_id": mid, "per": 50}
            if cursor:
                params["start"] = cursor
            respeitar_intervalo_esl()
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 429:
                time.sleep(2.5)
                resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(f"invoice_occurrences HTTP {resp.status_code} (manifesto {mid}): {resp.text[:200]}")
            corpo = resp.json()
            for it in corpo.get("data", []) or []:
                inv = it.get("invoice") or {}
                fr = it.get("freight") or {}
                itens.append({
                    "numero": inv.get("number"),
                    "chave": inv.get("key"),
                    "freight_id": fr.get("id"),
                })
            cursor = (corpo.get("paging") or {}).get("next_id")
            if cursor is None or cursor in vistos:
                break
            vistos.add(cursor)
        if itens:
            return itens
    return []


# ───────────────────────── Coletas (Report 11324) ─────────────────────────
def _endereco_coleta_report(coleta_dict):
    rua = str(coleta_dict.get('pck_pln_mds_line_1') or '').strip()
    num = str(coleta_dict.get('pck_pln_mds_number') or '').strip()
    bairro = str(coleta_dict.get('pck_pln_mds_neighborhood') or '').strip()
    cidade = str(coleta_dict.get('pck_pln_mds_cty_name') or '').strip()
    partes = [p for p in (rua, num, bairro, cidade) if p]
    return ", ".join(partes).upper() if partes else None


def aplicar_em_coleta(nf, coleta_dict, filial, forcar=False):
    """
    Aplica os dados do Report de Coletas (11324) numa NotaFiscal com tipo_operacao='COLETA':
      - corporation_id -> id_filial_emissora_tms, nome_filial_emissora_tms, filial_emissora
      - pck_pln_mds_postal_code -> cep (se PENDENTE e sem CEP válido) + geocodificação
      - endereço e solicitante (se PENDENTE e com placeholder)
    Devolve a lista de campos alterados.
    """
    campos = []

    def _set(campo, valor):
        if getattr(nf, campo, None) != valor:
            setattr(nf, campo, valor)
            if campo not in campos:
                campos.append(campo)

    cid = str(coleta_dict.get('corporation_id') or coleta_dict.get('pck_crn_id') or '').strip() or None
    nome_corp = MAPA_ID_ESL_FILIAL.get(cid) or (filial.nome if filial else None)

    if cid:
        _set('id_filial_emissora_tms', cid)
    if nome_corp:
        _set('nome_filial_emissora_tms', nome_corp)
    if filial is not None:
        _set('filial_emissora', filial)

    seq_code = str(coleta_dict.get('sequence_code') or '').strip()
    num_col_atual = str(getattr(nf, 'numero_coleta', None) or '').strip()
    if seq_code and (not num_col_atual or (num_col_atual.isdigit() and int(num_col_atual) < 100) or forcar):
        _set('numero_coleta', seq_code)

    precisa_geo = False
    if getattr(nf, 'status', 'PENDENTE') == 'PENDENTE':
        cep = limpar_cep(coleta_dict.get('pck_pln_mds_postal_code'))
        if cep and (not limpar_cep(getattr(nf, 'cep', None)) or forcar):
            _set('cep', cep)
            precisa_geo = True

        end_txt = _endereco_coleta_report(coleta_dict)
        if end_txt and (texto_e_placeholder(getattr(nf, 'endereco_entrega', None)) or forcar):
            _set('endereco_entrega', end_txt)
            precisa_geo = True

        solicitante = str(
            coleta_dict.get('pck_pln_name') or coleta_dict.get('requester') or ''
        ).upper().strip()
        if solicitante and (
            (getattr(nf, 'destinatario', None) or '').strip().upper() in PLACEHOLDERS_DESTINATARIO
            or forcar
        ):
            _set('destinatario', solicitante[:255])

    if campos:
        nf.save(update_fields=campos)

    if precisa_geo and getattr(nf, 'latitude', None) is None and getattr(nf, 'longitude', None) is None:
        def _agendar_geo_col(nota_id=nf.id, numero=nf.numero_nota):
            try:
                from manifesto.tasks import enriquecer_geolocalizacao_nota_task
                enriquecer_geolocalizacao_nota_task.delay(nota_id)
            except Exception as exc:
                logger.warning("⚠️ Erro ao agendar geocodificação da Coleta %s: %s", numero, exc)
        transaction.on_commit(_agendar_geo_col)

    return campos


def listar_coletas_manifesto_esl(config, numero_manifesto):
    """
    Consulta o Report de Coletas (11324) no Data Export da ESL usando `token_analytics`
    para obter `corporation_id` (filial emissora da coleta), `sequence_code` e CEP.
    """
    import json
    import requests

    report_coletas = getattr(config, 'report_coletas', None) or '11324'
    url = f"https://{config.dominio_esl}/api/analytics/reports/{report_coletas}/data"
    headers = {
        "Authorization": f"Bearer {config.token_analytics}",
        "Content-Type": "application/json",
    }
    payload = {
        "search": {
            "picks": {"request_date": "2024-01-01 - 2050-12-31"},
            "scopes": {"from_manifest_sequence_code": str(numero_manifesto).strip()},
        },
        "page": "1",
        "per": "100",
    }
    respeitar_intervalo_esl()
    resp = requests.get(url, headers=headers, data=json.dumps(payload), timeout=30)
    if resp.status_code == 429:
        time.sleep(2.5)
        resp = requests.get(url, headers=headers, data=json.dumps(payload), timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"report_coletas {report_coletas} HTTP {resp.status_code} (manifesto {numero_manifesto}): {resp.text[:200]}")
    dados = resp.json()
    return dados if isinstance(dados, list) else []


def coletas_pendentes_de_enriquecimento(manifesto):
    """Coletas do manifesto que ainda estão sem filial emissora (corporation_id) ou sem CEP."""
    faltando = []
    for nf in manifesto.notas_fiscais.filter(tipo_operacao='COLETA'):
        lacuna = (
            not nf.id_filial_emissora_tms
            or not nf.filial_emissora_id
            or (nf.status == 'PENDENTE' and not limpar_cep(nf.cep))
        )
        if lacuna:
            faltando.append(nf)
    return faltando


def enriquecer_coletas_manifesto(config, manifesto, forcar=False, filiais_cache=None):
    """
    Enriquece as coletas (`tipo_operacao='COLETA'`) do manifesto com a Filial Emissora
    (`corporation_id` do Report 11324) e CEP (`pck_pln_mds_postal_code`).
    """
    filiais_cache = filiais_cache if filiais_cache is not None else {}
    resumo_col = {'coletas_alvo': 0, 'coletas_enriquecidas': 0, 'erros': [], 'sem_filial_cadastrada': []}

    todas_coletas = list(manifesto.notas_fiscais.filter(tipo_operacao='COLETA'))
    alvo = todas_coletas if forcar else coletas_pendentes_de_enriquecimento(manifesto)
    resumo_col['coletas_alvo'] = len(alvo)
    if not alvo:
        return resumo_col

    if not (config.dominio_esl and config.token_analytics):
        resumo_col['erros'].append("Token analytics ou domínio ESL não configurados para enriquecer coletas.")
        return resumo_col

    try:
        itens_esl = listar_coletas_manifesto_esl(config, manifesto.numero_manifesto)
    except Exception as exc:
        resumo_col['erros'].append(f"coletas manifesto {manifesto.numero_manifesto}: {exc}")
        logger.warning("⚠️ [COLETAS EMISSOR] Falha ao consultar Report de Coletas para manifesto #%s: %s",
                       manifesto.numero_manifesto, exc)
        return resumo_col

    por_seq = {}
    por_nome = {}
    for item in itens_esl:
        seq = normalizar_numero(item.get('sequence_code'))
        if seq:
            por_seq[seq] = item
        nome_item = str(item.get('pck_pln_name') or item.get('requester') or '').strip().upper()
        if nome_item:
            por_nome.setdefault(nome_item, []).append(item)

    resumo_col['coletas_sem_match'] = []
    for nf in alvo:
        seq_col = normalizar_numero(getattr(nf, 'numero_coleta', None))
        seq_nota = normalizar_numero(getattr(nf, 'numero_nota', None))
        dados_col = por_seq.get(seq_col) or por_seq.get(seq_nota)

        if not dados_col:
            # Fallback seguro: casa pelo nome do solicitante SOMENTE se for único no relatório e na própria lista.
            # (o webhook/SOAP pode trazer um identificador de coleta diferente do sequence_code do Report 11324)
            nome_nf = str(getattr(nf, 'destinatario', None) or '').strip().upper()
            candidatos = por_nome.get(nome_nf) or []
            iguais_local = [c for c in alvo if str(getattr(c, 'destinatario', None) or '').strip().upper() == nome_nf]
            if nome_nf and len(candidatos) == 1 and len(iguais_local) == 1:
                dados_col = candidatos[0]

        if not dados_col:
            resumo_col['coletas_sem_match'].append(str(getattr(nf, 'numero_coleta', None) or getattr(nf, 'numero_nota', None)))
            continue

        cid = str(dados_col.get('corporation_id') or dados_col.get('pck_crn_id') or '').strip() or None
        nome_corp = MAPA_ID_ESL_FILIAL.get(cid)
        filial = resolver_filial_emissora(cid, nome_corp, filiais_cache) if cid else None
        if cid and not filial and cid not in resumo_col['sem_filial_cadastrada']:
            resumo_col['sem_filial_cadastrada'].append(cid)

        campos = aplicar_em_coleta(nf, dados_col, filial, forcar=forcar)
        if campos:
            resumo_col['coletas_enriquecidas'] += 1

    if resumo_col['coletas_sem_match']:
        logger.warning("⚠️ [COLETAS EMISSOR] Manifesto #%s: %s coleta(s) sem correspondência no Report de Coletas: %s",
                       manifesto.numero_manifesto, len(resumo_col['coletas_sem_match']), resumo_col['coletas_sem_match'])

    return resumo_col


# ───────────────────────── orquestração ─────────────────────────
def notas_pendentes_de_enriquecimento(manifesto):
    """Notas (não-coleta) do manifesto que ainda têm lacuna que o GraphQL resolve."""
    faltando = []
    for nf in manifesto.notas_fiscais.exclude(tipo_operacao='COLETA').select_related('frete'):
        frete_obj = getattr(nf, 'frete', None)
        lacuna = (
            not nf.id_filial_emissora_tms
            or not freight_id_valido(nf.freight_id_tms, nf.numero_nota, nf.chave_acesso)
            or not nf.numero_cte
            or not getattr(nf, 'esl_unique_id', None)
            or not getattr(nf, 'sequence_code', None)
            or frete_obj is None
            or not getattr(frete_obj, 'graphql_sincronizado_em', None)
            or (nf.status == 'PENDENTE' and (
                not limpar_cep(nf.cep)
                or texto_e_placeholder(nf.endereco_entrega)
                or (nf.destinatario or '').strip().upper() in PLACEHOLDERS_DESTINATARIO
            ))
        )
        if lacuna:
            faltando.append(nf)
    return faltando


def enriquecer_manifesto(config, manifesto, forcar=False, cache_gql=None, filiais_cache=None):
    """
    Enriquece todas as notas/minutas (via GraphQL `freight`) e coletas (via Report 11324 `corporation_id`)
    do manifesto. Devolve um resumo (dict) auditável.
    Nunca levanta por falha de um frete: o erro vai para resumo['erros'].
    Levanta apenas se não conseguir listar as ocorrências do manifesto (para o chamador reagendar).
    """
    cache_gql = cache_gql if cache_gql is not None else {}
    filiais_cache = filiais_cache if filiais_cache is not None else {}
    resumo = {
        'manifesto': manifesto.numero_manifesto, 'notas_alvo': 0, 'notas_enriquecidas': 0,
        'coletas_alvo': 0, 'coletas_enriquecidas': 0,
        'fretes_consultados': 0, 'sem_match': 0, 'ambiguas': 0, 'divergentes': 0,
        'conflitos': [], 'erros': [], 'sem_filial_cadastrada': [],
    }

    # 1. Enriquecimento de Coletas (Filial Emissora corporation_id + CEP via Report 11324)
    try:
        res_col = enriquecer_coletas_manifesto(config, manifesto, forcar=forcar, filiais_cache=filiais_cache)
        resumo['coletas_alvo'] = res_col['coletas_alvo']
        resumo['coletas_enriquecidas'] = res_col['coletas_enriquecidas']
        resumo['coletas_sem_match'] = res_col.get('coletas_sem_match', [])
        resumo['erros'].extend(res_col['erros'])
        for cid_sem in res_col['sem_filial_cadastrada']:
            if cid_sem not in resumo['sem_filial_cadastrada']:
                resumo['sem_filial_cadastrada'].append(cid_sem)
    except Exception as exc_col:
        logger.warning("⚠️ [COLETAS EMISSOR] Erro ao enriquecer coletas do manifesto #%s: %s",
                       manifesto.numero_manifesto, exc_col)

    # 2. Enriquecimento de Notas e Minutas (GraphQL `freight`)
    todas = list(manifesto.notas_fiscais.exclude(tipo_operacao='COLETA').select_related('frete'))
    alvo = todas if forcar else notas_pendentes_de_enriquecimento(manifesto)
    resumo['notas_alvo'] = len(alvo)
    if not alvo:
        if resumo['coletas_alvo'] > 0:
            logger.info("✅ [GRAPHQL/COLETAS] Manifesto #%s enriquecido (apenas coletas): %s",
                        manifesto.numero_manifesto,
                        {k: v for k, v in resumo.items() if k not in ('conflitos', 'erros', 'sem_filial_cadastrada')})
        return resumo

    if not (config.dominio_esl and config.token_analytics and config.token_invoices):
        resumo['erros'].append("Tokens/domínio ESL não configurados (token_analytics e token_invoices são necessários).")
        return resumo

    ocorrencias = listar_ocorrencias_manifesto(config, manifesto)
    mapa = mapear_notas_para_fretes(
        [{'id': nf.id, 'numero': nf.numero_nota, 'chave': nf.chave_acesso} for nf in alvo],
        ocorrencias,
    )

    por_frete = {}
    for nf in alvo:
        m = mapa.get(nf.id) or {}
        if m.get('freight_id'):
            por_frete.setdefault(m['freight_id'], []).append(nf)
        elif m.get('motivo') == 'ambigua':
            resumo['ambiguas'] += 1
        else:
            resumo['sem_match'] += 1

    for fid, notas_do_frete in por_frete.items():
        try:
            dados = cache_gql.get(fid)
            if dados is None:
                respeitar_intervalo_esl()
                dados = consultar_frete(config.dominio_esl, config.token_analytics, fid)
                resumo['fretes_consultados'] += 1
                if dados is not None:
                    cache_gql[fid] = dados
            if dados is None:
                resumo['erros'].append(f"frete {fid}: não encontrado no GraphQL")
                continue

            filial = resolver_filial_emissora(dados.get('corporation_id'), dados.get('corporation_nome'), filiais_cache)
            if not filial and dados.get('corporation_id') not in resumo['sem_filial_cadastrada']:
                resumo['sem_filial_cadastrada'].append(dados.get('corporation_id'))

            with transaction.atomic():
                frete = upsert_frete(dados, filial, forcar=forcar)
                for nf in notas_do_frete:
                    if not nota_pertence_ao_frete({'numero': nf.numero_nota, 'chave': nf.chave_acesso}, dados):
                        resumo['divergentes'] += 1
                        logger.warning("⚠️ [GRAPHQL] NF %s (mft %s) NÃO consta no frete %s devolvido pela ESL. Ignorada.",
                                       nf.numero_nota, manifesto.numero_manifesto, fid)
                        continue
                    campos, conflitos = aplicar_em_nota(nf, dados, frete, filial, forcar=forcar)
                    if campos:
                        resumo['notas_enriquecidas'] += 1
                    for c in conflitos:
                        resumo['conflitos'].append(f"NF {nf.numero_nota}: {c}")
        except GraphQLFreightError as exc:
            resumo['erros'].append(f"frete {fid}: {exc}")
            logger.error("❌ [GRAPHQL] %s", exc)
        except Exception as exc:
            resumo['erros'].append(f"frete {fid}: erro inesperado {exc}")
            logger.exception("❌ [GRAPHQL] erro inesperado no frete %s", fid)

    logger.info("✅ [GRAPHQL] Manifesto #%s enriquecido: %s", manifesto.numero_manifesto, {
        k: v for k, v in resumo.items() if k not in ('conflitos', 'erros', 'sem_filial_cadastrada')})
    return resumo

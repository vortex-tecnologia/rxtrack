# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# integracoes/normalizers.py
"""
Normalizador de payloads JSON do TMS.

Converte o formato Envelope/uploadRoute/Rota/Paradas (padrão Comprovei/SSW)
para o formato interno que o processar_webhook_manifesto_task já entende.
"""

import logging

logger = logging.getLogger(__name__)


def desembrulhar_payload(payload: dict) -> dict:
    """Se o payload vier dentro de uma chave 'payload' ou 'data', desembrulha."""
    if not isinstance(payload, dict):
        return {}
    if 'payload' in payload and isinstance(payload['payload'], dict):
        return payload['payload']
    if 'data' in payload and isinstance(payload['data'], dict):
        return payload['data']
    return payload


def extrair_rota(payload: dict) -> dict | None:
    """Busca o nó Rota em qualquer nível do payload JSON."""
    if not isinstance(payload, dict):
        return None
    
    p = desembrulhar_payload(payload)

    # 1. Envelope.Body.uploadRoute.Rotas.Rota
    if 'Envelope' in p:
        body = p.get('Envelope', {}).get('Body', {})
        upload = body.get('uploadRoute', {})
        rotas = upload.get('Rotas', {})
        if 'Rota' in rotas:
            return rotas['Rota']
    
    # 2. Body.uploadRoute.Rotas.Rota
    if 'Body' in p:
        upload = p.get('Body', {}).get('uploadRoute', {})
        rotas = upload.get('Rotas', {})
        if 'Rota' in rotas:
            return rotas['Rota']

    # 3. uploadRoute.Rotas.Rota
    if 'uploadRoute' in p:
        rotas = p.get('uploadRoute', {}).get('Rotas', {})
        if 'Rota' in rotas:
            return rotas['Rota']

    # 4. Rotas.Rota
    if 'Rotas' in p:
        rotas = p.get('Rotas', {})
        if 'Rota' in rotas:
            return rotas['Rota']

    # 5. Rota direta
    if 'Rota' in p:
        return p['Rota']

    return None


def is_formato_tms_envelope(payload: dict) -> bool:
    """
    Detecta se o payload recebido está no formato do TMS (Envelope SOAP convertido em JSON).
    Retorna True se encontrar a estrutura de Rota.
    """
    return extrair_rota(payload) is not None


def extrair_credencial_tms(payload: dict) -> str:
    """
    Extrai a senha de autenticação do JSON do TMS.
    Localização: Envelope.Header.Credenciais.Senha ou Header.Credenciais.Senha
    """
    p = desembrulhar_payload(payload)
    try:
        if 'Envelope' in p:
            return p.get('Envelope', {}).get('Header', {}).get('Credenciais', {}).get('Senha', '')
        if 'Header' in p:
            return p.get('Header', {}).get('Credenciais', {}).get('Senha', '')
    except (AttributeError, TypeError):
        pass
    return ''


def _resolver_nome_filial(razao_social: str) -> str:
    """
    Converte razão social longa do TMS para o nome amigável da filial.
    Faz match contra as filiais já cadastradas no banco de dados.
    Ex: 'QUICK DELIVERY BRASILIA ENTREGAS RAPIDAS DE ENCOMENDAS LTDA' → 'QUICK BRASILIA'
        'RD EXPRESSO TRANSPORTES - EIRELI' → 'RD EXPRESSO'
    """
    razao = razao_social.upper().strip()
    if not razao:
        return 'FILIAL TMS'

    try:
        from usuarios.models import Filial
        # Busca se alguma filial cadastrada tem nome que está contido na razão social
        for filial in Filial.objects.all().order_by('-id'):
            nome_filial = filial.nome.upper().strip()
            if nome_filial and len(nome_filial) >= 3 and nome_filial in razao:
                logger.info(f"🏢 [RESOLVER_FILIAL] Razão '{razao}' resolvida para filial existente: '{nome_filial}'")
                return nome_filial
    except Exception as e:
        logger.warning(f"⚠️ [RESOLVER_FILIAL] Erro ao buscar filiais no banco: {e}")

    # Fallback: retorna a razão social original
    return razao


def normalizar_json_tms(payload: dict) -> dict:
    """
    Converte o JSON do TMS (formato Comprovei/SSW) para o formato interno do RXTrack.
    """
    rota = extrair_rota(payload)
    if not rota:
        raise ValueError("Estrutura do JSON TMS inválida: Nó 'Rota' não encontrado.")

    # ─── TRANSPORTADORA → FILIAL ───
    transportadora = rota.get('Transportadora', {})
    import re
    codigo_raw = str(transportadora.get('Codigo', '')).strip()
    codigo_limpo = re.sub(r'\D', '', codigo_raw)
    razao_social = str(transportadora.get('Razao', 'FILIAL TMS')).upper().strip()

    filial = {
        'cnpj': codigo_limpo if len(codigo_limpo) == 14 else None,
        'id_tms': codigo_raw if codigo_raw and len(codigo_limpo) != 14 else None,
        'nome': _resolver_nome_filial(razao_social),
    }

    # ─── MOTORISTA ───
    motorista_data = rota.get('Motorista', {})
    cpf_raw = str(motorista_data.get('Usuario', '')).strip()
    # Remove pontuação caso venha formatado
    cpf = cpf_raw.replace('.', '').replace('-', '')
    
    motorista = {
        'cpf': cpf,
        'nome': str(motorista_data.get('Nome', 'MOTORISTA TMS')).upper().strip(),
    }

    # ─── MANIFESTO ───
    numero_manifesto = str(rota.get('@numero', '')).strip()
    manifesto = {
        'numero': numero_manifesto,
        'id_tms': numero_manifesto,  # No formato TMS, o número é o próprio ID
    }

    # ─── VEÍCULO (NOVO — o SOAP antigo não processava) ───
    placa = str(motorista_data.get('PlacaVeiculo', '')).strip().upper()
    veiculo = {'placa': placa} if placa else None

    # ─── BASE DE OPERAÇÃO / ATUAÇÃO (Física) ───
    base_origem = rota.get('Base', {}).get('Origem', {})
    filial_operacao = None
    if base_origem:
        nome_base = base_origem.get('Nome') or f"BASE {base_origem.get('Cidade', '')}"
        filial_operacao = {
            'id_tms': str(base_origem.get('@codigo', '')).strip() or None,
            'nome': str(nome_base).upper().strip(),
            'cidade': str(base_origem.get('Cidade', '')).strip(),
            'uf': str(base_origem.get('Estado', '')).strip(),
            'cep': str(base_origem.get('CEP', '')).strip().replace('-', ''),
            'logradouro': str(base_origem.get('Rua', '')).strip(),
            'bairro': str(base_origem.get('Bairro', '')).strip(),
        }

    # ─── PARADAS → ITENS ───
    paradas_container = rota.get('Paradas', {})
    paradas_raw = paradas_container.get('Parada', [])
    
    # Garante que seja lista (TMS pode enviar objeto único se houver só 1 parada)
    if isinstance(paradas_raw, dict):
        paradas_raw = [paradas_raw]

    itens = []
    for parada in paradas_raw:
        item = _normalizar_parada(parada)
        if item:
            itens.append(item)

    resultado = {
        'filial': filial,
        'motorista': motorista,
        'manifesto': manifesto,
        'itens': itens,
    }

    if filial_operacao:
        resultado['filial_operacao'] = filial_operacao

    # Adiciona veículo somente se tiver placa
    if veiculo:
        resultado['veiculo'] = veiculo

    logger.info(
        f"Normalizado JSON TMS: Manifesto #{numero_manifesto}, "
        f"Motorista: {motorista['nome']} ({cpf}), "
        f"Placa: {placa or 'N/A'}, "
        f"{len(itens)} nota(s)"
    )

    return resultado


def _normalizar_parada(parada: dict) -> dict | None:
    """
    Converte uma Parada do TMS para um item do formato interno.
    """
    try:
        # Tipo de operação: E=Entrega, C=Coleta
        tipo_raw = str(parada.get('Tipo', 'E')).upper().strip()
        tipo_map = {
            'E': 'ENTREGA',
            'C': 'COLETA',
            'T': 'TRANSFERENCIA',
            'D': 'DESPACHO',
            'R': 'RETIRADA',
        }
        tipo = tipo_map.get(tipo_raw, 'ENTREGA')

        # No formato TMS Comprovei/SSW, @numero é apenas o índice/ordem da parada na rota (1, 2, 3...)
        # e NÃO é o ID interno do Frete no banco de dados da ESL Cloud.
        # Para entregas/minutas, não definimos id_tms falso para evitar poluir freight_id_tms.
        id_parada_seq = str(parada.get('@numero', '')).strip() or None
        id_tms = id_parada_seq if tipo == 'COLETA' else None

        # ─── DOCUMENTO (NF-e / CT-e) ───
        doc = parada.get('Documento', {})
        numero_item = str(doc.get('Numero', '')).strip()
        chave_nota = str(doc.get('ChaveNota', '')).strip() or None
        
        # Validação mínima: precisa ter pelo menos um número
        if not numero_item:
            logger.warning(f"Parada {id_tms} ignorada: sem número de documento")
            return None

        # ─── CLIENTE (Destinatário) ───
        cliente = parada.get('Cliente', {})
        
        # Monta endereço completo
        endereco_parts = [
            str(cliente.get('Endereco', '')).strip(),
        ]
        endereco_str = ', '.join(p for p in endereco_parts if p)

        destinatario = {
            'nome': str(cliente.get('Razao', 'NÃO INFORMADO')).upper().strip(),
            'logradouro': endereco_str,
            'numero': '',  # Já incluso no campo Endereco do TMS
            'bairro': str(cliente.get('Bairro', '')).strip(),
            'cidade': str(cliente.get('Cidade', '')).strip(),
            'uf': str(cliente.get('Estado', '')).strip(),
            'cep': str(cliente.get('CEP', '')).strip().replace('-', ''),
            'telefone': str(cliente.get('Telefone', '')).strip(),
            'email': str(cliente.get('Email', '')).strip() if cliente.get('Email') else '',
            'documento': str(cliente.get('Codigo', '')).strip(),
        }

        # ─── DADOS DE FRETE (NOVOS — antes não eram mapeados) ───
        embarcador = doc.get('Embarcador', {})

        item = {
            'tipo': tipo,
            'id_tms': id_tms,
            'numero_item': numero_item,
            'chave_item': chave_nota,
            'numero_cte': None,       # NF-e não tem CT-e
            'chave_cte': None,
            'numero_coleta': id_tms if tipo == 'COLETA' else None,
            'destinatario': destinatario,
            # Dados de frete/carga
            'modal': str(doc.get('Modal', '')).strip() or None,
            'valor_frete': doc.get('ValorNota'),
            'peso_taxado': doc.get('Peso'),
            'volumes': doc.get('Volume'),
            'remetente': str(embarcador.get('Nome', '')).strip() or None,
            'pagador_nome': str(embarcador.get('Nome', '')).strip() or None,
            'pagador_documento': str(embarcador.get('cnpj', '')).strip() or None,
            'natureza_carga': None,
        }

        return item

    except Exception as e:
        logger.error(f"Erro ao normalizar parada: {e}", exc_info=True)
        return None

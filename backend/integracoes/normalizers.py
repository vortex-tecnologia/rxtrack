# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# integracoes/normalizers.py
"""
Normalizador de payloads JSON do TMS.

Converte o formato Envelope/uploadRoute/Rota/Paradas (padrão Comprovei/SSW)
para o formato interno que o processar_webhook_manifesto_task já entende.
"""

import logging

logger = logging.getLogger(__name__)


def is_formato_tms_envelope(payload: dict) -> bool:
    """
    Detecta se o payload recebido está no formato do TMS (Envelope SOAP convertido em JSON).
    Retorna True se encontrar a estrutura Envelope.Body.uploadRoute.Rotas.Rota
    """
    try:
        envelope = payload.get('Envelope', {})
        body = envelope.get('Body', {})
        upload = body.get('uploadRoute', {})
        rotas = upload.get('Rotas', {})
        return 'Rota' in rotas
    except (AttributeError, TypeError):
        return False


def extrair_credencial_tms(payload: dict) -> str:
    """
    Extrai a senha de autenticação do JSON do TMS.
    Localização: Envelope.Header.Credenciais.Senha
    """
    try:
        return payload.get('Envelope', {}).get('Header', {}).get('Credenciais', {}).get('Senha', '')
    except (AttributeError, TypeError):
        return ''


def normalizar_json_tms(payload: dict) -> dict:
    """
    Converte o JSON do TMS (formato Comprovei/SSW) para o formato interno do RXTrack.
    
    Formato TMS (entrada):
        Envelope.Body.uploadRoute.Rotas.Rota {
            @numero, Data, TipoRota,
            Motorista { Nome, Usuario, PlacaVeiculo },
            Transportadora { Razao, Codigo },
            Base { Origem { CEP, Rua, Cidade, Estado, ... } },
            Paradas { Parada [ { Tipo, @numero, Cliente {...}, Documento {...}, SKUs {...} } ] }
        }
    
    Formato interno (saída):
        {
            filial: { id_tms, nome },
            motorista: { cpf, nome },
            manifesto: { numero, id_tms },
            veiculo: { placa },           ← NOVO
            itens: [ { tipo, id_tms, numero_item, chave_item, destinatario: {...}, ... } ]
        }
    """
    try:
        rota = payload['Envelope']['Body']['uploadRoute']['Rotas']['Rota']
    except (KeyError, TypeError) as e:
        raise ValueError(f"Estrutura do JSON TMS inválida: {e}")

    # ─── TRANSPORTADORA → FILIAL ───
    transportadora = rota.get('Transportadora', {})
    filial = {
        'id_tms': str(transportadora.get('Codigo', '')).strip() or None,
        'nome': str(transportadora.get('Razao', 'FILIAL TMS')).upper().strip(),
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

        # ID da parada no TMS
        id_tms = str(parada.get('@numero', '')).strip() or None

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

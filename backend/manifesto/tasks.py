# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
from celery import shared_task
import logging
from integracoes.registry import get_tms_adapter

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def iniciar_transporte_manifesto_tms_task(self, numero_manifesto):
    """Delegated to the correct TMS Adapter."""
    adapter = get_tms_adapter()
    if adapter:
        return adapter.iniciar_transporte(numero_manifesto, task=self)
    return {"success": False, "detail": "Integração TMS desativada."}


@shared_task(bind=True, max_retries=3)
def buscar_manifesto_completo_task(self, log_id):
    """Delegated to the correct TMS Adapter."""
    adapter = get_tms_adapter()
    if adapter:
        return adapter.buscar_manifesto_completo(log_id, task=self)
    
    # Se não houver adapter, marca o log como ERRO
    from manifesto.models import ManifestoBuscaLog
    try:
        log = ManifestoBuscaLog.objects.get(id=log_id)
        log.status = 'ERRO'
        log.mensagem_erro = "Integração TMS desativada ou não configurada."
        log.save()
    except ManifestoBuscaLog.DoesNotExist:
        pass
    return "TMS Desativado."


@shared_task(bind=True, max_retries=3)
def buscar_coletas_manifesto_task(self, manifesto_id, numero_visual):
    """Delegated to the correct TMS Adapter."""
    adapter = get_tms_adapter()
    if adapter:
        return adapter.buscar_coletas_manifesto(manifesto_id, numero_visual, task=self)
    return "TMS Desativado."


@shared_task(bind=True, max_retries=2)
def enviar_baixa_esl_task(self, baixa_id):
    """Delegated to the correct TMS Adapter."""
    adapter = get_tms_adapter()
    if adapter:
        return adapter.enviar_baixa(baixa_id, task=self)
    
    # Se não houver adapter, marca a baixa como integrada localmente
    from manifesto.models import BaixaNF
    try:
        baixa = BaixaNF.objects.get(id=baixa_id)
        baixa.processado_tms = True
        baixa.integrado_tms = False
        baixa.log_erro_tms = "TMS Desativado."
        baixa.save()
    except BaixaNF.DoesNotExist:
        pass
    return "TMS Desativado."


def _descobrir_schema_manifesto(manifesto_id):
    """Localiza em qual schema de tenant o manifesto reside."""
    from django.db import connection
    current_schema = getattr(connection, 'schema_name', 'public')
    if current_schema != 'public':
        return current_schema

    try:
        from django_tenants.utils import get_tenant_model, schema_context
        from manifesto.models import Manifesto
        from django.db.models import Q
        for tenant in get_tenant_model().objects.exclude(schema_name='public'):
            try:
                with schema_context(tenant.schema_name):
                    if Manifesto.objects.filter(Q(id=str(manifesto_id)) | Q(numero_manifesto=str(manifesto_id))).exists():
                        return tenant.schema_name
            except Exception:
                pass
    except Exception:
        pass
    return 'public'


@shared_task(bind=True, max_retries=5)
def finalizar_manifesto_tms_task(self, manifesto_id, schema_name=None):
    """Delegated to the correct TMS Adapter dentro do schema correto do cliente."""
    from django_tenants.utils import schema_context

    target_schema = schema_name or _descobrir_schema_manifesto(manifesto_id)
    with schema_context(target_schema):
        adapter = get_tms_adapter()
        if adapter:
            return adapter.finalizar_manifesto(manifesto_id, task=self)
        return "TMS Desativado."


@shared_task
def verificar_autofinalizacao_manifesto_task(manifesto_id, schema_name=None):
    """
    Avalia em background se o manifesto tem 100% das notas concluídas e fotos validadas pela IA.
    Executa rigorosamente dentro do schema_context do tenant do cliente.
    """
    from django_tenants.utils import schema_context

    target_schema = schema_name or _descobrir_schema_manifesto(manifesto_id)
    with schema_context(target_schema):
        from manifesto.services import tentar_autofinalizar_manifesto
        sucesso, msg = tentar_autofinalizar_manifesto(manifesto_id)
        return {"sucesso": sucesso, "mensagem": msg, "schema": target_schema}



@shared_task(bind=True, max_retries=2)
def enviar_baixa_minuta_task(self, baixa_id):
    """Delegated to the correct TMS Adapter."""
    adapter = get_tms_adapter()
    if adapter:
        return adapter.enviar_baixa_minuta(baixa_id, task=self)
    return "TMS Desativado."


@shared_task(bind=True, max_retries=3)
def enviar_coleta_esl_task(self, baixa_id):
    """Delegated to the correct TMS Adapter."""
    adapter = get_tms_adapter()
    if adapter:
        return adapter.enviar_coleta(baixa_id, task=self)
    return "TMS Desativado."


@shared_task(bind=True, max_retries=3)
def enviar_comprovante_esl_task(self, baixa_id):
    """Dispara o recadastro exclusivo da foto/comprovante de entrega no TMS."""
    adapter = get_tms_adapter()
    if adapter:
        return adapter.enviar_comprovante_entrega(baixa_id, task=self)
    return "TMS Desativado."


def _buscar_ou_criar_filial_unificada(codigo_ou_cnpj, nome_filial, cidade=None, uf=None, cep=None, logradouro=None, bairro=None):
    """
    Busca ou cria Filial unificando por CNPJ (suporta múltiplos CNPJs separados por vírgula),
    ID da ESL (id_filial_tms) e Razão Social/Nome.
    """
    from usuarios.models import Filial
    import re

    doc_limpo = re.sub(r'\D', '', str(codigo_ou_cnpj or ''))
    nome_limpo = str(nome_filial or '').upper().strip()

    filial_obj = None

    # 1. Busca por CNPJ (suporta múltiplos CNPJs no mesmo campo)
    if doc_limpo and len(doc_limpo) == 14:
        # Tenta busca direta por substring
        filial_obj = Filial.objects.filter(cnpj__icontains=doc_limpo).first()
        if not filial_obj:
            # Varre filiais com CNPJ cadastrado para checagem exata pós-limpeza de pontuação
            for f in Filial.objects.exclude(cnpj__isnull=True).exclude(cnpj=''):
                cnpjs_salvos = [re.sub(r'\D', '', c) for c in re.split(r'[,;/\s]+', f.cnpj or '') if c.strip()]
                if doc_limpo in cnpjs_salvos:
                    filial_obj = f
                    break

    # 2. Busca por ID da ESL (id_filial_tms)
    if not filial_obj and codigo_ou_cnpj:
        filial_obj = Filial.objects.filter(id_filial_tms=str(codigo_ou_cnpj)).first()

    # 3. Busca por Nome / Razão Social
    if not filial_obj and nome_limpo:
        filial_obj = Filial.objects.filter(nome__iexact=nome_limpo).first()
        if not filial_obj:
            palavras = nome_limpo.split('-')[0].split()
            if len(palavras) >= 2:
                termo = " ".join(palavras[:2])
                filial_obj = Filial.objects.filter(nome__icontains=termo).first()

    # Se encontrou, atualiza dados que faltavam (auto-acrescenta novos CNPJs na lista)
    if filial_obj:
        campos_update = []
        if doc_limpo and len(doc_limpo) == 14:
            cnpjs_atuais = [re.sub(r'\D', '', c) for c in re.split(r'[,;/\s]+', filial_obj.cnpj or '') if c.strip()]
            if doc_limpo not in cnpjs_atuais:
                if filial_obj.cnpj and filial_obj.cnpj.strip():
                    filial_obj.cnpj = f"{filial_obj.cnpj.strip()}, {doc_limpo}"
                else:
                    filial_obj.cnpj = doc_limpo
                campos_update.append('cnpj')
        elif doc_limpo and len(doc_limpo) != 14 and not filial_obj.id_filial_tms:
            filial_obj.id_filial_tms = str(codigo_ou_cnpj)
            campos_update.append('id_filial_tms')

        if campos_update:
            filial_obj.save(update_fields=campos_update)
        return filial_obj

    # 4. Não encontrou: cria nova Filial
    defaults = {
        'nome': nome_limpo or f"FILIAL {codigo_ou_cnpj}",
        'operacao_ativa': True
    }
    if doc_limpo and len(doc_limpo) == 14:
        defaults['cnpj'] = doc_limpo
    elif codigo_ou_cnpj:
        defaults['id_filial_tms'] = str(codigo_ou_cnpj)

    if cidade: defaults['cidade'] = cidade
    if uf: defaults['uf'] = uf
    if cep: defaults['cep'] = cep
    if logradouro: defaults['logradouro'] = logradouro
    if bairro: defaults['bairro'] = bairro

    filial_obj = Filial.objects.create(**defaults)
    return filial_obj


@shared_task(bind=True, max_retries=3)
def processar_webhook_manifesto_task(self, event_id):
    """
    Processa o payload de um WebhookEventoManifestoESL.
    - Cria/Busca Filial e Motorista.
    - Cria/Atualiza Manifesto com status 'AGUARDANDO'.
    - Cria/Atualiza Veículo (se placa informada).
    - Cria/Atualiza Notas Fiscais vinculadas (com CEP e geocodificação).
    """
    from manifesto.models import WebhookEventoManifestoESL, Manifesto, NotaFiscal, ManifestoBuscaLog
    from usuarios.models import Motorista, Filial
    from django.contrib.auth.models import User
    from django.db import transaction
    from django.utils import timezone
    import logging

    logger = logging.getLogger(__name__)

    try:
        with transaction.atomic():
            event = WebhookEventoManifestoESL.objects.get(id=event_id)
            payload = event.payload
            # 1. Filial Fiscal / Transportadora (Vínculo comercial)
            f_data = payload.get('filial', {})
            cnpj_filial = f_data.get('cnpj')
            id_f_tms = f_data.get('id_tms') or f_data.get('Codigo')
            filial_nome = str(f_data.get('nome') or f_data.get('Razao') or 'FILIAL WEBHOOK').upper().strip()
            # Prioriza CNPJ para busca (mais confiável que id_tms)
            filial_obj = _buscar_ou_criar_filial_unificada(cnpj_filial or id_f_tms, filial_nome)

            # 1b. Filial de Operação / Base de Atuação Física (de onde o caminhão realmente sai)
            filial_operacao_obj = None
            f_op_data = payload.get('filial_operacao', {})
            id_f_op_tms = f_op_data.get('id_tms') or f_op_data.get('@codigo')
            nome_f_op = f_op_data.get('nome') or f_op_data.get('Nome')

            if id_f_op_tms or nome_f_op:
                filial_operacao_obj = _buscar_ou_criar_filial_unificada(
                    id_f_op_tms,
                    nome_f_op,
                    cidade=f_op_data.get('cidade'),
                    uf=f_op_data.get('uf'),
                    cep=f_op_data.get('cep'),
                    logradouro=f_op_data.get('logradouro') or f_op_data.get('Rua'),
                    bairro=f_op_data.get('bairro')
                )

            # 2. Motorista (Cadastro Automático de Perfil — aceita cpf, Usuario, usuario, documento)
            m_data = payload.get('motorista', {}) or payload.get('Motorista', {})
            cpf_raw = m_data.get('cpf') or m_data.get('Usuario') or m_data.get('usuario') or m_data.get('CPF') or m_data.get('documento') or ''
            cpf = str(cpf_raw).strip().replace('.', '').replace('-', '')
            nome_mot = str(m_data.get('nome') or m_data.get('Nome') or 'MOTORISTA WEBHOOK').upper().strip()

            if not cpf:
                raise Exception("CPF do motorista não informado no payload.")

            motorista_obj, created_mot = Motorista.objects.get_or_create(
                cpf=cpf,
                defaults={
                    'nome_completo': nome_mot,
                    'filial': filial_operacao_obj or filial_obj
                }
            )
            
            if not created_mot:
                motorista_obj.nome_completo = nome_mot
                if not motorista_obj.filial:
                    motorista_obj.filial = filial_operacao_obj or filial_obj
                motorista_obj.save()

            # 3. Manifesto — Resolução Inteligente de Número Visual vs ID Interno
            mani_data = payload.get('manifesto', {})
            num_mani_recebido = str(mani_data.get('numero', '')).strip()
            
            if not num_mani_recebido:
                raise Exception("Número do manifesto não informado no payload.")

            from django.db.models import Q
            # 🔍 Busca se o manifesto JÁ EXISTE no banco (por Número Visual OU por ID Interno TMS)
            manifesto_existente = Manifesto.objects.filter(
                Q(numero_manifesto=num_mani_recebido) | Q(manifesto_id_tms=num_mani_recebido)
            ).first()

            # 3b. Veículo (Novo: cria/vincula se a placa vier no payload)
            veiculo_obj = None
            v_data = payload.get('veiculo', {})
            placa = str(v_data.get('placa', '')).strip().upper() if v_data else ''
            if placa:
                from manifesto.models import Veiculo
                veiculo_obj, _ = Veiculo.objects.get_or_create(
                    placa=placa,
                    defaults={'tipo': 'OUTRO'}
                )

            if manifesto_existente:
                # ✅ JÁ EXISTE NO BANCO: Usa o número visual que já temos (NÃO precisa bater na ESL!)
                num_visual = manifesto_existente.numero_manifesto
                id_tms_final = manifesto_existente.manifesto_id_tms or mani_data.get('id_tms') or num_mani_recebido
                if manifesto_existente.filial_operacao:
                    filial_operacao_obj = manifesto_existente.filial_operacao
                logger.info(f"⚡ [WEBHOOK] Manifesto {num_visual} já cadastrado no banco. Atualizando rota sem consulta na ESL.")
            else:
                # 🔍 NÃO EXISTE NO BANCO: Consulta a ESL para ver se é ID interno e descobrir o sequence_code (número visual)
                adapter = get_tms_adapter()
                res_esl = None
                if adapter and hasattr(adapter, 'resolver_numero_visual_manifesto'):
                    try:
                        res_esl = adapter.resolver_numero_visual_manifesto(num_mani_recebido)
                    except Exception as e:
                        logger.warning(f"⚠️ Erro ao tentar resolver número visual na ESL para {num_mani_recebido}: {e}")

                if isinstance(res_esl, dict):
                    num_visual = res_esl.get('sequence_code') or num_mani_recebido
                    id_tms_final = num_mani_recebido
                    # Enriquece filial_operacao e veículo a partir da ESL se não vieram no payload
                    if not filial_operacao_obj and res_esl.get('id_filial_operacao'):
                        filial_operacao_obj, _ = Filial.objects.get_or_create(
                            id_filial_tms=str(res_esl.get('id_filial_operacao')),
                            defaults={'nome': res_esl.get('nome_filial_operacao') or f"BASE {res_esl.get('id_filial_operacao')}"}
                        )
                    if not veiculo_obj and res_esl.get('placa'):
                        from manifesto.models import Veiculo
                        veiculo_obj, _ = Veiculo.objects.get_or_create(
                            placa=res_esl.get('placa'),
                            defaults={'tipo': 'OUTRO'}
                        )
                elif res_esl:
                    num_visual = str(res_esl).strip()
                    id_tms_final = num_mani_recebido
                else:
                    num_visual = num_mani_recebido
                    id_tms_final = mani_data.get('id_tms') or num_mani_recebido

            num_mani = num_visual

            # 🛡️ TRAVA 1: MANIFESTO CANCELADO NO APP (NÃO REABRE NEM ALTERA HISTÓRICO)
            if manifesto_existente and manifesto_existente.status == 'CANCELADO':
                event.status = 'IGNORADO'
                event.erro = f"Manifesto #{num_visual} já está CANCELADO no app. Atualização via Webhook ignorada para proteger o histórico operacional."
                event.processed_at = timezone.now()
                event.save()
                logger.info(f"🔒 [PROTEÇÃO] Manifesto #{num_visual} já está CANCELADO no app. Webhook ignorado.")
                return f"Manifesto #{num_visual} já cancelado. Ignorado."

            # Verifica se o manifesto estava previamente finalizado (auto-finalização precoce antes do envio de notas adicionais pela ESL)
            era_finalizado = bool(manifesto_existente and (manifesto_existente.status == 'FINALIZADO' or manifesto_existente.finalizado))

            # 🛡️ TRAVA 1.1: REGRAS RÍGIDAS PARA MANIFESTO PREVIAMENTE FINALIZADO
            if era_finalizado:
                # REGRA 1: Filtro de 24 horas (não reativa manifestos antigos de dias anteriores)
                from datetime import timedelta
                data_fim_ref = manifesto_existente.data_finalizacao or manifesto_existente.data_criacao
                if data_fim_ref and (timezone.now() - data_fim_ref > timedelta(hours=24)):
                    event.status = 'IGNORADO'
                    event.erro = f"Manifesto #{num_visual} já foi finalizado há mais de 24 horas ({data_fim_ref.strftime('%d/%m/%Y %H:%M')}). Atualização tardia da ESL ignorada."
                    event.processed_at = timezone.now()
                    event.save()
                    logger.info(f"🔒 [TRAVA 24H] Manifesto #{num_visual} finalizado há >24h ({data_fim_ref}). Webhook ignorado.")
                    return f"Manifesto #{num_visual} finalizado há mais de 24h. Ignorado."

                # REGRA 2: Motorista já possui OUTRO manifesto ativo em transporte?
                # Se o motorista já está executando uma nova viagem ativa, não reabre a antiga
                outro_em_transporte = Manifesto.objects.filter(
                    motorista=motorista_obj,
                    status='EM_TRANSPORTE',
                    finalizado=False
                ).exclude(id=manifesto_existente.id).first()

                if outro_em_transporte:
                    event.status = 'IGNORADO'
                    event.erro = f"Manifesto #{num_visual} estava finalizado e o motorista '{motorista_obj.nome_completo}' já possui outro manifesto ativo em transporte (#{outro_em_transporte.numero_manifesto}). Webhook ignorado para evitar conflito."
                    event.processed_at = timezone.now()
                    event.save()
                    logger.info(f"🔒 [TRAVA CONFLITO] Motorista {motorista_obj.nome_completo} já possui MFT #{outro_em_transporte.numero_manifesto} em transporte. Webhook #{num_visual} ignorado.")
                    return f"Motorista já possui manifesto #{outro_em_transporte.numero_manifesto} em transporte ativo. Ignorado."

                # REGRA 3: Status no TMS é 'closed' (finalizado no próprio TMS)
                if getattr(manifesto_existente, 'status_tms', '') == 'closed':
                    event.status = 'IGNORADO'
                    event.erro = f"Manifesto #{num_visual} consta como FINALIZADO no TMS (status_tms='closed'). Atualização tardia da ESL ignorada."
                    event.processed_at = timezone.now()
                    event.save()
                    logger.info(f"🔒 [STATUS TMS CLOSED] Manifesto #{num_visual} já fechado no TMS. Webhook ignorado.")
                    return f"Manifesto #{num_visual} fechado no TMS. Ignorado."

            # 🛡️ TRAVA 2: BASE/FILIAL INATIVA NO APP (Checa a base de operação real)
            base_checar = filial_operacao_obj or filial_obj
            if hasattr(base_checar, 'operacao_ativa') and not base_checar.operacao_ativa:
                event.status = 'IGNORADO'
                event.erro = f"Base/Filial '{base_checar.nome}' está inativa para recebimento de manifestos no app."
                event.processed_at = timezone.now()
                event.save()
                logger.info(f"🚫 Base '{base_checar.nome}' com operação inativa. Manifesto #{num_visual} ({num_mani_recebido}) ignorado.")
                return f"Base '{base_checar.nome}' inativa. Manifesto ignorado."

            # 🛡️ TRAVA 3: MOTORISTA NÃO CADASTRADO NO APP (APENAS PRÉ-CADASTRO, SEM USUÁRIO ATIVO)
            # Se o motorista não concluiu o primeiro acesso/cadastro (user é None), mantém o pré-cadastro mas NÃO processa o manifesto
            if not motorista_obj.user or not motorista_obj.user.is_active:
                event.status = 'IGNORADO'
                event.erro = f"Motorista '{motorista_obj.nome_completo}' (CPF: {cpf}) possui apenas pré-cadastro e ainda não concluiu o cadastro de usuário no aplicativo. Manifesto #{num_visual} ({num_mani_recebido}) não processado."
                event.processed_at = timezone.now()
                event.save()
                logger.info(f"👤 [PRÉ-CADASTRO] Motorista '{motorista_obj.nome_completo}' ({cpf}) sem conta de usuário ativa no app. Pré-cadastro mantido, manifesto #{num_visual} ignorado.")
                return f"Motorista '{motorista_obj.nome_completo}' sem usuário ativo. Pré-cadastro registrado, manifesto ignorado."

            # 🛡️ PRESERVAÇÃO DE STATUS EXISTENTE:
            # - Se já existia (seja EM_TRANSPORTE, FINALIZADO ou AGUARDANDO), MANTÉM o status atual na carga inicial.
            # - A transição para EM_TRANSPORTE se dará no pós-processamento somente se houver notas pendentes.
            # - Se for um manifesto novo, inicia como AGUARDANDO.
            status_novo = manifesto_existente.status if manifesto_existente else 'AGUARDANDO'

            # 🏢 RESOLUÇÃO FINAL: filial_operacao via API ESL (Fallback)
            # Se filial_operacao_obj ainda é None (payload sem dados ou manifesto existente sem base),
            # consulta a ESL pelo ID interno do manifesto para obter mft_uer_crn_id (base do criador).
            if not filial_operacao_obj:
                try:
                    _adapter = get_tms_adapter()
                    if _adapter and hasattr(_adapter, 'resolver_numero_visual_manifesto'):
                        id_consulta = id_tms_final or num_mani_recebido
                        res_fo = _adapter.resolver_numero_visual_manifesto(id_consulta)
                        if isinstance(res_fo, dict) and res_fo.get('id_filial_operacao'):
                            filial_operacao_obj, _ = Filial.objects.get_or_create(
                                id_filial_tms=str(res_fo['id_filial_operacao']),
                                defaults={'nome': res_fo.get('nome_filial_operacao') or f"BASE {res_fo['id_filial_operacao']}"}
                            )
                            logger.info(f"🏢 [FALLBACK ESL] filial_operacao resolvida via API: {filial_operacao_obj.nome} (TMS ID: {res_fo['id_filial_operacao']})")
                            if not veiculo_obj and res_fo.get('placa'):
                                from manifesto.models import Veiculo
                                veiculo_obj, _ = Veiculo.objects.get_or_create(
                                    placa=res_fo['placa'], defaults={'tipo': 'OUTRO'}
                                )
                except Exception as e:
                    logger.warning(f"⚠️ [FALLBACK ESL] Erro ao buscar filial_operacao: {e}")

            manifesto_defaults = {
                'motorista': motorista_obj,
                'filial': filial_obj,
                'status': status_novo,
                'manifesto_id_tms': id_tms_final,
            }

            # Só atribui filial_operacao se temos valor (não sobrescreve com None)
            if filial_operacao_obj:
                manifesto_defaults['filial_operacao'] = filial_operacao_obj

            # Só vincula veículo se veio no payload ou ESL (não sobrescreve com None)
            if veiculo_obj:
                manifesto_defaults['veiculo'] = veiculo_obj

            manifesto_obj, _ = Manifesto.objects.update_or_create(
                numero_manifesto=num_visual,
                defaults=manifesto_defaults
            )

            itens = payload.get('itens', [])
            count_notas = 0
            ids_processadas = []
            for item in itens:
                dest = item.get('destinatario', {})
                endereco = f"{dest.get('logradouro', '')}, {dest.get('numero', '')} - {dest.get('bairro', '')} ({dest.get('cidade', '')}/{dest.get('uf', '')})".upper()

                tipo_item = item.get('tipo', 'ENTREGA')
                numero_item = str(item.get('numero_item', ''))
                id_tms = item.get('id_tms')
                
                def normalizar_valor(val):
                    if val is None: return None
                    v = str(val).strip()
                    return None if v.lower() in ['', 'null', 'none'] else v

                chave_nfe = normalizar_valor(item.get('chave_item'))
                chave_cte = normalizar_valor(item.get('chave_cte'))
                num_coleta = normalizar_valor(item.get('numero_coleta'))

                if tipo_item == 'COLETA' and not num_coleta:
                    if numero_item.isdigit():
                        num_coleta = numero_item
                    else:
                        num_coleta = str(id_tms) if id_tms else None

                # 🔍 BUSCA INTELIGENTE DENTRO DESTE MANIFESTO ESPECÍFICO:
                nota_obj = None
                if tipo_item == 'COLETA':
                    # 📦 Coleta: busca por número de coleta ou número do item no mesmo manifesto
                    if num_coleta:
                        nota_obj = NotaFiscal.objects.filter(manifesto=manifesto_obj, tipo_operacao='COLETA', numero_coleta=num_coleta).first()
                    if not nota_obj and numero_item:
                        nota_obj = NotaFiscal.objects.filter(manifesto=manifesto_obj, tipo_operacao='COLETA', numero_nota=numero_item).first()
                    if not nota_obj and id_tms:
                        nota_obj = NotaFiscal.objects.filter(manifesto=manifesto_obj, tipo_operacao='COLETA', freight_id_tms=str(id_tms)).first()
                else:
                    # 📄 Entrega: busca por chave de acesso ou número da NF no mesmo manifesto
                    if chave_nfe:
                        nota_obj = NotaFiscal.objects.filter(manifesto=manifesto_obj, chave_acesso=chave_nfe).first()
                    if not nota_obj and numero_item:
                        nota_obj = NotaFiscal.objects.filter(manifesto=manifesto_obj, numero_nota=numero_item).first()
                    if not nota_obj and id_tms and not (str(id_tms).isdigit() and int(id_tms) < 100):
                        nota_obj = NotaFiscal.objects.filter(manifesto=manifesto_obj, freight_id_tms=str(id_tms)).first()

                is_id_frete_valido = bool(id_tms and not (str(id_tms).isdigit() and int(id_tms) < 100))

                frete_obj = None
                if is_id_frete_valido:
                    from manifesto.models import Frete
                    def extrair_decimal(valor):
                        try: return float(valor) if valor else None
                        except: return None
                        
                    frete_obj, _ = Frete.objects.get_or_create(
                        freight_id_tms=str(id_tms),
                        defaults={
                            'numero_cte': normalizar_valor(item.get('numero_cte')),
                            'chave_cte': chave_cte,
                            'modal': item.get('modal'),
                            'valor_frete': extrair_decimal(item.get('valor_frete')),
                            'peso_taxado': extrair_decimal(item.get('peso_taxado')),
                            'volumes': int(item.get('volumes')) if str(item.get('volumes')).isdigit() else None,
                            'remetente': item.get('remetente'),
                            'pagador_nome': item.get('pagador_nome'),
                            'pagador_documento': item.get('pagador_documento'),
                            'natureza_carga': item.get('natureza_carga')
                        }
                    )

                # CEP do destinatário
                cep_dest = str(dest.get('cep', '')).strip().replace('-', '') if dest.get('cep') else None

                if nota_obj:
                    # ✅ NOTA JÁ EXISTE NO MANIFESTO: VERIFICAÇÃO COMPLETA CAMPO A CAMPO
                    # O webhook vem direto do banco da ESL (dados sempre confiáveis/completos),
                    # então SEMPRE tem prioridade sobre dados que já estavam no banco local.
                    # PROTEÇÃO: Notas BAIXADA/OCORRENCIA NÃO são alteradas (já finalizadas pelo motorista).
                    campos_update = []
                    cep_mudou = False

                    # Validação de id_tms: ignora números sequenciais de parada (1, 2, 3...)
                    is_id_frete_valido = bool(id_tms and not (str(id_tms).isdigit() and int(id_tms) < 100))

                    if nota_obj.status in ['BAIXADA', 'OCORRENCIA']:
                        # 🔒 Nota já finalizada — apenas atualiza freight_id se faltava
                        if is_id_frete_valido and nota_obj.freight_id_tms != str(id_tms):
                            nota_obj.freight_id_tms = str(id_tms)
                            campos_update.append('freight_id_tms')
                    else:
                        # 📋 Nota PENDENTE — verificação COMPLETA de todos os campos
                        # tipo_operacao: CRÍTICO — corrige tipo errado (ex: ENTREGA → TRANSFERENCIA)
                        # Webhook SEMPRE tem autoridade sobre tipo_operacao (dados 100% confiáveis da ESL)
                        if tipo_item and nota_obj.tipo_operacao != tipo_item:
                            logger.info(f"🔄 [WEBHOOK CORREÇÃO] NF #{numero_item}: tipo_operacao '{nota_obj.tipo_operacao}' → '{tipo_item}'")
                            nota_obj.tipo_operacao = tipo_item
                            campos_update.append('tipo_operacao')
                        # Marca que o tipo_operacao foi confirmado pelo webhook (trava contra busca manual)
                        if tipo_item and not nota_obj.tipo_operacao_confirmado_webhook:
                            nota_obj.tipo_operacao_confirmado_webhook = True
                            campos_update.append('tipo_operacao_confirmado_webhook')
                        # freight_id_tms (apenas IDs válidos do TMS, não sequenciais de parada)
                        if is_id_frete_valido and nota_obj.freight_id_tms != str(id_tms):
                            nota_obj.freight_id_tms = str(id_tms)
                            campos_update.append('freight_id_tms')
                        # chave_acesso (sempre atualiza se diferente, webhook é confiável)
                        if chave_nfe and nota_obj.chave_acesso != chave_nfe:
                            nota_obj.chave_acesso = chave_nfe
                            campos_update.append('chave_acesso')
                        # CEP
                        if cep_dest and nota_obj.cep != cep_dest:
                            nota_obj.cep = cep_dest
                            campos_update.append('cep')
                            cep_mudou = True
                        # Frete
                        if frete_obj and nota_obj.frete != frete_obj:
                            nota_obj.frete = frete_obj
                            campos_update.append('frete')
                        # Destinatário (webhook sempre tem prioridade — dados vêm do banco ESL)
                        nome_dest_wh = str(dest.get('nome', '')).upper().strip()
                        if nome_dest_wh and nome_dest_wh != 'NÃO INFORMADO' and nota_obj.destinatario != nome_dest_wh:
                            nota_obj.destinatario = nome_dest_wh
                            campos_update.append('destinatario')
                        # Endereço de entrega (webhook sempre tem prioridade — dados vêm do banco ESL)
                        if endereco and 'NÃO INFORMADO' not in endereco:
                            endereco_limpo = endereco.strip()
                            if nota_obj.endereco_entrega != endereco_limpo:
                                nota_obj.endereco_entrega = endereco_limpo
                                campos_update.append('endereco_entrega')
                                cep_mudou = True  # Endereço mudou, re-geocodificar
                        # CT-e
                        novo_cte = normalizar_valor(item.get('numero_cte'))
                        if novo_cte and nota_obj.numero_cte != novo_cte:
                            nota_obj.numero_cte = novo_cte
                            campos_update.append('numero_cte')
                        if chave_cte and nota_obj.chave_cte != chave_cte:
                            nota_obj.chave_cte = chave_cte
                            campos_update.append('chave_cte')
                        # Número de coleta
                        if num_coleta and nota_obj.numero_coleta != num_coleta:
                            nota_obj.numero_coleta = num_coleta
                            campos_update.append('numero_coleta')

                    if campos_update:
                        logger.info(f"📝 [WEBHOOK SYNC] NF #{numero_item} - Campos atualizados: {campos_update}")
                        nota_obj.save(update_fields=campos_update)

                    # 🌍 Re-geocodificação: se CEP ou endereço mudou, atualiza lat/lng
                    if cep_mudou and nota_obj.cep:
                        try:
                            # Limpa coordenadas antigas para forçar nova busca
                            nota_obj.latitude = None
                            nota_obj.longitude = None
                            nota_obj.save(update_fields=['latitude', 'longitude'])
                            enriquecer_geolocalizacao_nota_task.delay(nota_obj.id)
                            logger.info(f"🌍 [WEBHOOK GEO] Re-geocodificação disparada para NF #{numero_item} (CEP/endereço alterado)")
                        except Exception as geo_err:
                            logger.warning(f"⚠️ Erro ao re-geocodificar NF #{numero_item}: {geo_err}")

                    created_nota = False
                else:
                    # 🆕 NOTA NOVA NO MANIFESTO: CRIA COMO PENDENTE
                    nota_obj = NotaFiscal.objects.create(
                        manifesto=manifesto_obj,
                        numero_nota=numero_item,
                        chave_acesso=chave_nfe,
                        tipo_operacao=tipo_item,
                        tipo_operacao_confirmado_webhook=True,  # Webhook é fonte confiável
                        destinatario=str(dest.get('nome', 'NÃO INFORMADO')).upper(),
                        endereco_entrega=endereco,
                        cep=cep_dest,
                        freight_id_tms=str(id_tms) if is_id_frete_valido else None,
                        numero_coleta=num_coleta,
                        numero_cte=normalizar_valor(item.get('numero_cte')),
                        chave_cte=chave_cte,
                        frete=frete_obj,
                        status='PENDENTE'
                    )
                    created_nota = True

                # 🌍 Geocodificação automática: busca lat/lng pelo CEP (se nota nova e com CEP)
                if created_nota and cep_dest:
                    try:
                        enriquecer_geolocalizacao_nota_task.delay(nota_obj.id)
                    except Exception as geo_err:
                        logger.warning(f"⚠️ Erro ao enfileirar geocodificação da NF #{numero_item}: {geo_err}")
                ids_processadas.append(nota_obj.id)
                count_notas += 1

                # 📲 Notifica motorista se nova nota/coleta foi adicionada a um manifesto existente
                if created_nota and motorista_obj and motorista_obj.fcm_token and status_novo == 'EM_TRANSPORTE':
                    try:
                        from common.tasks_notificacoes import notificar_item_adicionado_manifesto
                        notificar_item_adicionado_manifesto(motorista_obj, num_mani, numero_item, tipo_item=tipo_item)
                    except Exception as push_err:
                        logger.error(f"Erro ao notificar adicao de nota webhook #{numero_item}: {push_err}")

            # === REMOÇÃO DE NOTAS ÓRFÃS NO WEBHOOK ===
            try:
                if ids_processadas:
                    notas_removidas = NotaFiscal.objects.filter(
                        manifesto=manifesto_obj,
                        status__in=['PENDENTE', 'AGUARDANDO']
                    ).exclude(id__in=ids_processadas)
                    
                    qtd_removidas = notas_removidas.count()
                    if qtd_removidas > 0:
                        logger.info(f"🗑️ Removendo {qtd_removidas} notas órfãs do manifesto {num_mani} que foram excluídas no TMS via Webhook.")
                        # 📲 Notifica motorista sobre cada nota removida
                        if motorista_obj and motorista_obj.fcm_token:
                            from common.tasks_notificacoes import notificar_item_removido_manifesto
                            for n_rem in notas_removidas:
                                try:
                                    notificar_item_removido_manifesto(motorista_obj, num_mani, n_rem.numero_nota, tipo_item=n_rem.tipo_operacao or 'NOTA')
                                except Exception as push_err:
                                    logger.error(f"Erro ao notificar remocao de nota webhook #{n_rem.numero_nota}: {push_err}")

                        notas_removidas.delete()
            except Exception as e:
                logger.error(f"Erro ao tentar remover notas órfãs no webhook: {e}")

            # 🔄 AUTO-REABERTURA OU PRESERVAÇÃO DE FINALIZAÇÃO:
            notas_pendentes_count = NotaFiscal.objects.filter(manifesto=manifesto_obj, status='PENDENTE').count()
            if era_finalizado:
                if notas_pendentes_count > 0 and getattr(manifesto_obj, 'status_tms', '') != 'closed':
                    manifesto_obj.status = 'EM_TRANSPORTE'
                    manifesto_obj.finalizado = False
                    manifesto_obj.data_finalizacao = None
                    manifesto_obj.save(update_fields=['status', 'finalizado', 'data_finalizacao'])
                    logger.info(f"🔄 [AUTO-REABERTURA WEBHOOK] Manifesto #{num_mani} REABERTO! {notas_pendentes_count} nova(s) nota(s) pendente(s) da ESL.")
                else:
                    # Todas as notas já estavam concluídas/baixadas, mantém finalizado
                    manifesto_obj.status = 'FINALIZADO'
                    manifesto_obj.finalizado = True
                    manifesto_obj.save(update_fields=['status', 'finalizado'])

            # 5. Criar Log de Auditoria/Visibilidade no Dashboard
            ManifestoBuscaLog.objects.update_or_create(
                numero_manifesto=num_mani,
                motorista=motorista_obj,
                defaults={
                    'status': 'PROCESSADO',
                    'mensagem_erro': None,
                    'quantidade_notas': count_notas
                }
            )

            # Marca evento como processado
            event.status = 'PROCESSADO'
            event.processed_at = timezone.now()
            event.save()

            # 📲 DISPARO INSTANTÂNEO DE NOTIFICAÇÃO PUSH (FCM) PARA O MOTORISTA (APK)
            try:
                if motorista_obj and motorista_obj.fcm_token and (not era_finalizado or notas_pendentes_count > 0):
                    from common.tasks_notificacoes import notificar_atribuicao_manifesto
                    notificar_atribuicao_manifesto(motorista_obj, num_mani, count_notas)
                    logger.info(f"📲 Push FCM de manifesto enviado com sucesso para {motorista_obj.nome_completo} (MFT: #{num_mani})")
            except Exception as push_err:
                logger.error(f"⚠️ Erro ao disparar Notificação Push Webhook para MFT {num_mani}: {push_err}")

            # ⚡ Notifica Torre de Controle + SAC Live em tempo real
            try:
                from manifesto.services import enviar_painel
                transaction.on_commit(lambda: enviar_painel(manifesto_obj))
            except Exception as ws_err:
                logger.warning(f"⚠️ Erro ao notificar painel via webhook_task: {ws_err}")

            return f"Manifesto {num_mani} (Motorista: {nome_mot}) processado com sucesso. {count_notas} notas."


    except Exception as e:
        logger.error(f"Erro ao processar Webhook {event_id}: {str(e)}")
        try:
            from manifesto.models import WebhookEventoManifestoESL, ManifestoBuscaLog
            evt = WebhookEventoManifestoESL.objects.get(id=event_id)
            evt.status = 'ERRO'
            evt.erro = str(e)
            evt.save()
            
            mani_data = evt.payload.get('manifesto', {})
            num_mani = mani_data.get('numero', 'WEBHOOK_FAILURE')
            m_data = evt.payload.get('motorista', {})
            cpf = str(m_data.get('cpf', '')).strip().replace('.', '').replace('-', '')
            
            from usuarios.models import Motorista
            motorista = Motorista.objects.filter(cpf=cpf).first()
            
            ManifestoBuscaLog.objects.create(
                numero_manifesto=num_mani,
                motorista=motorista,
                status='ERRO',
                mensagem_erro=f"Webhook Error: {str(e)}"
            )
            
            try:
                from operacional.services import registrar_erro_torre
                registrar_erro_torre(
                    filial=motorista.filial if motorista and motorista.filial else None,
                    categoria='WEBHOOK_MANIFESTO',
                    severidade_padrao='ATENCAO',
                    titulo=f"Falha ao processar Webhook Manifesto {num_mani}",
                    descricao=f"Falha durante webhook: {str(e)[:300]}",
                    erro_raw=str(e),
                    manifesto_numero=num_mani,
                    motorista_nome=motorista.nome_completo if motorista else "Desconhecido"
                )
            except Exception as tr_exc:
                logger.error(f"Erro registrar torre de controle webhook: {tr_exc}")
                
        except Exception as logger_err:
            logger.error(f"Falha ao registrar log de erro do webhook: {logger_err}")
            
        raise self.retry(exc=e, countdown=60)

@shared_task(bind=True, max_retries=3)
def processar_soap_task(self, evento_id):
    import xml.etree.ElementTree as ET
    from django.db import transaction
    from manifesto.models import WebhookEventoSOAP, Manifesto, NotaFiscal, ManifestoBuscaLog
    from usuarios.models import Motorista, Filial
    import logging

    logger = logging.getLogger(__name__)

    try:
        evento = WebhookEventoSOAP.objects.get(id=evento_id)
        xml_str = evento.payload_xml
        numero_rota = evento.numero_manifesto

        root = ET.fromstring(xml_str)
        def find_tag(element, tag_name):
            for child in element.iter():
                if child.tag.endswith(tag_name):
                    return child
            return None

        rota_element = find_tag(root, 'Rota')
        if rota_element is None:
            raise Exception("Tag <Rota> nao encontrada no XML")

        transportadora = find_tag(rota_element, 'Transportadora')
        filial_nome = "MATRIZ (INTEGRACAO)"
        if transportadora is not None:
            razao = find_tag(transportadora, 'Razao')
            if razao is not None and razao.text:
                filial_nome = str(razao.text).upper()[:100]

        filial_obj, _ = Filial.objects.get_or_create(nome=filial_nome)

        motorista_el = find_tag(rota_element, 'Motorista')
        if motorista_el is None:
            raise Exception("Tag <Motorista> nao encontrada")
        
        moto_cpf = find_tag(motorista_el, 'Usuario')
        moto_nome = find_tag(motorista_el, 'Nome')
        
        cpf = str(moto_cpf.text).strip() if moto_cpf is not None and moto_cpf.text else ""
        nome = str(moto_nome.text).upper().strip() if moto_nome is not None and moto_nome.text else "MOTORISTA INTEGRACAO"

        if not cpf:
            raise Exception("CPF do motorista nao encontrado")

        motorista_obj, _ = Motorista.objects.get_or_create(
            cpf=cpf,
            defaults={'nome_completo': nome, 'filial': filial_obj}
        )

        with transaction.atomic():
            manifesto_obj = Manifesto.objects.filter(numero_manifesto=numero_rota).first()
            if manifesto_obj and manifesto_obj.status == 'CANCELADO':
                evento.status = 'IGNORADO'
                evento.erro = f"Manifesto #{numero_rota} ja esta CANCELADO no app. Integracao ignorada."
                evento.processed_at = timezone.now()
                evento.save()
                return f"Manifesto #{numero_rota} ja cancelado."

            era_finalizado_soap = bool(manifesto_obj and (manifesto_obj.status == 'FINALIZADO' or manifesto_obj.finalizado))

            # 🛡️ TRAVA: REGRAS PARA MANIFESTO SOAP PREVIAMENTE FINALIZADO
            if era_finalizado_soap:
                from datetime import timedelta
                data_fim_soap = manifesto_obj.data_finalizacao or manifesto_obj.data_criacao
                if data_fim_soap and (timezone.now() - data_fim_soap > timedelta(hours=24)):
                    evento.status = 'IGNORADO'
                    evento.erro = f"Manifesto #{numero_rota} já finalizado há mais de 24 horas ({data_fim_soap.strftime('%d/%m/%Y %H:%M')}). Integração SOAP ignorada."
                    evento.processed_at = timezone.now()
                    evento.save()
                    logger.info(f"🔒 [SOAP 24H] Manifesto #{numero_rota} finalizado há >24h. Ignorado.")
                    return f"Manifesto #{numero_rota} finalizado há mais de 24h. Ignorado."

                outro_em_transporte = Manifesto.objects.filter(
                    motorista=motorista_obj,
                    status='EM_TRANSPORTE',
                    finalizado=False
                ).exclude(id=manifesto_obj.id).first()

                if outro_em_transporte:
                    evento.status = 'IGNORADO'
                    evento.erro = f"Manifesto #{numero_rota} estava finalizado e o motorista já possui outro manifesto ativo em transporte (#{outro_em_transporte.numero_manifesto}). Integração SOAP ignorada para evitar conflito."
                    evento.processed_at = timezone.now()
                    evento.save()
                    logger.info(f"🔒 [SOAP CONFLITO] Motorista já tem MFT #{outro_em_transporte.numero_manifesto} em transporte. SOAP #{numero_rota} ignorado.")
                    return f"Motorista já possui manifesto #{outro_em_transporte.numero_manifesto} em transporte ativo. Ignorado."

                # Status no TMS é 'closed'
                if getattr(manifesto_obj, 'status_tms', '') == 'closed':
                    evento.status = 'IGNORADO'
                    evento.erro = f"Manifesto #{numero_rota} consta como FINALIZADO no TMS (status_tms='closed'). Integração SOAP ignorada."
                    evento.processed_at = timezone.now()
                    evento.save()
                    logger.info(f"🔒 [SOAP CLOSED] Manifesto #{numero_rota} já fechado no TMS. SOAP ignorado.")
                    return f"Manifesto #{numero_rota} fechado no TMS. Ignorado."

            # 🛡️ TRAVA: MOTORISTA NÃO CADASTRADO NO APP (APENAS PRÉ-CADASTRO)
            if not motorista_obj.user or not motorista_obj.user.is_active:
                evento.status = 'IGNORADO'
                evento.erro = f"Motorista '{motorista_obj.nome_completo}' (CPF: {cpf}) possui apenas pre-cadastro e ainda nao concluiu o primeiro acesso no app. Manifesto #{numero_rota} ignorado."
                evento.processed_at = timezone.now()
                evento.save()
                logger.info(f"👤 [SOAP PRÉ-CADASTRO] Motorista '{motorista_obj.nome_completo}' ({cpf}) sem usuario ativo. Manifesto #{numero_rota} ignorado.")
                return f"Motorista '{motorista_obj.nome_completo}' sem usuario ativo. Pre-cadastro registrado, manifesto ignorado."

            # 🏢 Resolve filial_operacao via API ESL (o SOAP não traz essa informação no XML)
            # Usa o número do manifesto como ID para consultar mft_uer_crn_id (base do criador)
            filial_operacao_soap = None
            try:
                _adapter = get_tms_adapter()
                if _adapter and hasattr(_adapter, 'resolver_numero_visual_manifesto'):
                    res_fo = _adapter.resolver_numero_visual_manifesto(numero_rota)
                    if isinstance(res_fo, dict) and res_fo.get('id_filial_operacao'):
                        filial_operacao_soap, _ = Filial.objects.get_or_create(
                            id_filial_tms=str(res_fo['id_filial_operacao']),
                            defaults={'nome': res_fo.get('nome_filial_operacao') or f"BASE {res_fo['id_filial_operacao']}"}
                        )
                        logger.info(f"🏢 [SOAP] filial_operacao resolvida via API: {filial_operacao_soap.nome} (TMS ID: {res_fo['id_filial_operacao']})")
            except Exception as e:
                logger.warning(f"⚠️ [SOAP] Erro ao buscar filial_operacao via ESL: {e}")

            defaults_soap = {
                'motorista': motorista_obj,
                'filial': filial_obj,
            }
            # Só atribui filial_operacao se resolveu (não sobrescreve com None)
            if filial_operacao_soap:
                defaults_soap['filial_operacao'] = filial_operacao_soap
            elif manifesto_obj and manifesto_obj.filial_operacao:
                pass  # Preserva a filial_operacao que já existe no banco
            if not manifesto_obj:
                defaults_soap['status'] = 'AGUARDANDO'

            manifesto_obj, _ = Manifesto.objects.update_or_create(
                numero_manifesto=numero_rota,
                defaults=defaults_soap
            )

            paradas = find_tag(rota_element, 'Paradas')
            count_notas = 0
            ids_processadas = []

            if paradas is not None:
                for parada in paradas:
                    if not parada.tag.endswith('Parada'): continue
                        
                    tipo_parada = find_tag(parada, 'Tipo')
                    tipo_str = tipo_parada.text if tipo_parada is not None else 'E'
                    tipo_operacao = 'ENTREGA' if tipo_str == 'E' else 'COLETA'

                    doc = find_tag(parada, 'Documento')
                    cliente = find_tag(parada, 'Cliente')

                    if doc is not None:
                        numero_nota = find_tag(doc, 'Numero')
                        numero_nota = numero_nota.text if numero_nota is not None else ""
                        chave_nota = find_tag(doc, 'ChaveNota')
                        chave_nota = chave_nota.text if chave_nota is not None else ""
                    else:
                        numero_nota = ""
                        chave_nota = ""

                    if cliente is not None:
                        razao_cli = find_tag(cliente, 'Razao')
                        destinatario = razao_cli.text.upper() if (razao_cli is not None and razao_cli.text) else "NÃO INFORMADO"
                        end = find_tag(cliente, 'Endereco')
                        bairro = find_tag(cliente, 'Bairro')
                        cidade = find_tag(cliente, 'Cidade')
                        uf = find_tag(cliente, 'Estado')
                        endereco_str = f"{end.text if end is not None and end.text else ''} - {bairro.text if bairro is not None and bairro.text else ''} ({cidade.text if cidade is not None and cidade.text else ''}/{uf.text if uf is not None and uf.text else ''})".upper()
                    else:
                        destinatario = "NÃO INFORMADO"
                        endereco_str = "NÃO INFORMADO"

                    if numero_nota:
                        filtros_busca = {'manifesto': manifesto_obj}
                        if chave_nota: filtros_busca['chave_acesso'] = chave_nota
                        else:
                            filtros_busca['numero_nota'] = numero_nota
                            filtros_busca['tipo_operacao'] = tipo_operacao

                        nota_obj, _ = NotaFiscal.objects.update_or_create(
                            **filtros_busca,
                            defaults={
                                'destinatario': destinatario,
                                'endereco_entrega': endereco_str,
                                'tipo_operacao': tipo_operacao,
                                'tipo_operacao_confirmado_webhook': True,  # SOAP também é integração confiável
                                'numero_nota': numero_nota,
                                'chave_acesso': chave_nota if chave_nota else None,
                            }
                        )
                        ids_processadas.append(nota_obj.id)
                        count_notas += 1

            if ids_processadas:
                notas_removidas = NotaFiscal.objects.filter(
                    manifesto=manifesto_obj,
                    status__in=['PENDENTE', 'AGUARDANDO']
                ).exclude(id__in=ids_processadas)
                qtd_removidas = notas_removidas.count()
                if qtd_removidas > 0:
                    logger.info(f"Removendo {qtd_removidas} notas orfas do manifesto SOAP {numero_rota}")
                    notas_removidas.delete()

            # 4. Auto-Reabertura se o manifesto estava finalizado mas chegaram novas notas pendentes
            notas_pendentes_count = NotaFiscal.objects.filter(manifesto=manifesto_obj, status='PENDENTE').count()
            if era_finalizado_soap:
                if notas_pendentes_count > 0 and getattr(manifesto_obj, 'status_tms', '') != 'closed':
                    manifesto_obj.status = 'EM_TRANSPORTE'
                    manifesto_obj.finalizado = False
                    manifesto_obj.data_finalizacao = None
                    manifesto_obj.save(update_fields=['status', 'finalizado', 'data_finalizacao'])
                    logger.info(f"🔄 [AUTO-REABERTURA SOAP] Manifesto #{numero_rota} REABERTO! {notas_pendentes_count} nova(s) nota(s) pendente(s) da rota SOAP.")
                else:
                    manifesto_obj.status = 'FINALIZADO'
                    manifesto_obj.finalizado = True
                    manifesto_obj.save(update_fields=['status', 'finalizado'])

            ManifestoBuscaLog.objects.update_or_create(
                numero_manifesto=numero_rota, motorista=motorista_obj,
                defaults={'status': 'PROCESSADO', 'mensagem_erro': None, 'quantidade_notas': count_notas}
            )

        from django.utils import timezone
        evento.status = 'PROCESSADO'
        evento.processed_at = timezone.now()
        evento.save()

        # 📲 DISPARO DE NOTIFICAÇÃO PUSH (FCM) SE REABERTO OU NOVO
        try:
            if motorista_obj and motorista_obj.fcm_token and (not era_finalizado_soap or notas_pendentes_count > 0):
                from common.tasks_notificacoes import notificar_atribuicao_manifesto
                notificar_atribuicao_manifesto(motorista_obj, numero_rota, count_notas)
                logger.info(f"📲 Push FCM de manifesto SOAP enviado para {motorista_obj.nome_completo} (MFT: #{numero_rota})")
        except Exception as push_err:
            logger.error(f"⚠️ Erro ao disparar Notificação Push SOAP para MFT {numero_rota}: {push_err}")

        # ⚡ Notifica Torre de Controle + SAC Live em tempo real
        try:
            from manifesto.services import enviar_painel
            enviar_painel(manifesto_obj)
        except Exception as ws_err:
            logger.warning(f"⚠️ Erro ao notificar painel via soap_task: {ws_err}")

        return f"Manifesto SOAP {numero_rota} processado com sucesso. {count_notas} notas."

    except Exception as e:
        logger.error(f"Erro ao processar SOAP Task {evento_id}: {str(e)}", exc_info=True)
        try:
            from manifesto.models import WebhookEventoSOAP
            evt = WebhookEventoSOAP.objects.get(id=evento_id)
            evt.status = 'ERRO'
            evt.erro = str(e)
            evt.save()
            
            try:
                from operacional.services import registrar_erro_torre
                registrar_erro_torre(
                    filial=evt.filial if hasattr(evt, 'filial') else None,
                    categoria='WEBHOOK_MANIFESTO',
                    severidade_padrao='ATENCAO',
                    titulo=f"Falha ao processar SOAP Manifesto {evt.numero_manifesto}",
                    descricao=f"Falha durante SOAP: {str(e)[:300]}",
                    erro_raw=str(e),
                    manifesto_numero=evt.numero_manifesto
                )
            except Exception as tr_exc:
                logger.error(f"Erro registrar torre de controle SOAP: {tr_exc}")
        except:
            pass
        raise self.retry(exc=e, countdown=60)


@shared_task
def enriquecer_geolocalizacao_nota_task(nota_id):
    """
    Busca automaticamente Latitude e Longitude a partir do CEP e Endereço de entrega da NotaFiscal
    e grava no banco de dados.
    """
    try:
        from manifesto.models import NotaFiscal
        from common.geocoding import buscar_lat_lng_endereco

        nf = NotaFiscal.objects.get(id=nota_id)
        if nf.latitude is not None and nf.longitude is not None:
            return f"Nota #{nf.numero_nota} ja possui coordenadas."

        lat, lng = buscar_lat_lng_endereco(cep=nf.cep, endereco=nf.endereco_entrega)
        if lat is not None and lng is not None:
            nf.latitude = lat
            nf.longitude = lng
            nf.save(update_fields=['latitude', 'longitude'])
            return f"Coordenadas gravadas com sucesso para NF #{nf.numero_nota}: {lat}, {lng}"
        else:
            return f"Não foi possível obter coordenadas para NF #{nf.numero_nota} (CEP: {nf.cep})"
    except Exception as e:
        logger.error(f"Erro ao enriquecer geolocalizacao da NF {nota_id}: {e}")
        return str(e)


@shared_task
def limpar_manifestos_antigos_aguardando_task():
    """
    Cancela/expira manifestos que ficaram mais de 48h com status AGUARDANDO
    sem que o motorista tenha iniciado a viagem.
    Itera sobre todos os tenants (django-tenants) e dispara atualização via WebSocket
    para a Torre de Controle Live.
    """
    total_cancelados = 0
    try:
        from django_tenants.utils import get_tenant_model, schema_context
        tenants = list(get_tenant_model().objects.exclude(schema_name='public'))
        if tenants:
            for tenant in tenants:
                try:
                    with schema_context(tenant.schema_name):
                        total_cancelados += _cancelar_manifestos_aguardando_tenant(tenant.schema_name)
                except Exception as t_err:
                    logger.error(f"⚠️ [LIMPEZA MFT] Erro no tenant '{tenant.schema_name}': {t_err}")
            return f"{total_cancelados} manifestos expirados cancelados em {len(tenants)} tenant(s)."
    except Exception as e_ten:
        logger.warning(f"⚠️ [LIMPEZA MFT] Aviso multi-tenant: {e_ten}")

    # Fallback para schema public caso não utilize django-tenants ou tenants vazios
    try:
        total_cancelados += _cancelar_manifestos_aguardando_tenant('public')
    except Exception as e_pub:
        logger.error(f"⚠️ [LIMPEZA MFT] Erro schema public: {e_pub}")

    return f"{total_cancelados} manifestos expirados cancelados."


def _cancelar_manifestos_aguardando_tenant(schema_name=None):
    from manifesto.models import Manifesto
    from django.utils import timezone
    from datetime import timedelta
    from manifesto.services import enviar_painel

    limite = timezone.now() - timedelta(hours=48)
    manifestos_antigos = list(Manifesto.objects.filter(
        status='AGUARDANDO',
        data_criacao__lt=limite
    ).select_related('filial', 'filial_operacao', 'motorista', 'veiculo'))

    qtd = len(manifestos_antigos)
    if qtd > 0:
        logger.info(f"🧹 [LIMPEZA MFT - {schema_name}] Cancelando {qtd} manifesto(s) em AGUARDANDO há mais de 48h.")
        agora = timezone.now()
        for m in manifestos_antigos:
            m.status = 'CANCELADO'
            m.finalizado = True
            m.data_finalizacao = agora
            m.save(update_fields=['status', 'finalizado', 'data_finalizacao'])
            try:
                enviar_painel(m)
            except Exception as e_ws:
                logger.warning(f"⚠️ [LIMPEZA MFT - {schema_name}] Erro ao enviar WebSocket para #{m.numero_manifesto}: {e_ws}")
    return qtd


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def enviar_status_manifesto_checklist_task(self, manifesto_id, evento_status, schema_name=None):
    """
    Envia atualização de status do manifesto para a API do Checklist (QVX):
    - Quando entra em rota: status="EM_TRANSITO", data_inicio="YYYY-MM-DDTHH:MM:SS"
    - Quando finaliza: status="FINALIZADO", data_finalizacao="YYYY-MM-DDTHH:MM:SS"
    """
    from django_tenants.utils import schema_context
    target_schema = schema_name or 'public'

    with schema_context(target_schema):
        from manifesto.models import Manifesto, LogChecklistManifesto
        from configuracao.utils import get_config
        from django.core.cache import cache
        from django.utils import timezone
        import pytz
        import requests
        import json

        # Idempotência simples para não enviar o mesmo evento repetido em menos de 60 segundos
        cache_key = f"checklist_qvx_sent_{target_schema}_{manifesto_id}_{evento_status}"
        if cache.get(cache_key):
            logger.info(f"⏭️ [CHECKLIST QVX] Evento {evento_status} para manifesto #{manifesto_id} já enviado recentemente. Ignorando duplicata.")
            return "Já enviado recentemente"

        config = get_config()
        if not getattr(config, 'habilitar_checklist_qvx', True):
            logger.info(f"[CHECKLIST QVX] Integração desativada na configuração (schema: {target_schema}).")
            return "Desativado"

        try:
            manifesto = Manifesto.objects.select_related('motorista').get(id=manifesto_id)
        except Manifesto.DoesNotExist:
            logger.error(f"[CHECKLIST QVX] Manifesto #{manifesto_id} não encontrado no schema {target_schema}.")
            return "Manifesto não encontrado"

        fuso_br = pytz.timezone('America/Sao_Paulo')
        agora_br = timezone.now().astimezone(fuso_br)

        num_manifesto = str(manifesto.numero_manifesto).strip()

        # Validação de Elegibilidade:
        # Apenas manifestos com motorista da categoria 'EMPRESA' devem ser enviados para o Checklist QVX.
        # Motoristas 'AGREGADO', 'DEDICADO' ou sem motorista não são enviados.
        if not manifesto.motorista:
            logger.info(f"⏭️ [CHECKLIST QVX] Manifesto #{num_manifesto} ignorado: sem motorista vinculado.")
            return "Ignorado: sem motorista"

        categoria_motorista = (getattr(manifesto.motorista, 'categoria', '') or '').strip().upper()
        if categoria_motorista != 'EMPRESA':
            logger.info(
                f"⏭️ [CHECKLIST QVX] Manifesto #{num_manifesto} ignorado: "
                f"motorista '{manifesto.motorista.nome_completo}' pertence à categoria '{manifesto.motorista.categoria}' (apenas EMPRESA é enviado)."
            )
            return f"Ignorado: categoria {manifesto.motorista.categoria}"

        responsavel = manifesto.motorista.nome_completo or "Não informado"

        if evento_status == 'EM_TRANSITO':
            dt_inicio = manifesto.data_criacao.astimezone(fuso_br) if manifesto.data_criacao else agora_br
            payload = {
                "manifesto": num_manifesto,
                "status": "EM_TRANSITO",
                "data_inicio": dt_inicio.strftime('%Y-%m-%dT%H:%M:%S'),
                "responsavel": responsavel
            }
        else: # FINALIZADO
            dt_fim = manifesto.data_finalizacao.astimezone(fuso_br) if manifesto.data_finalizacao else agora_br
            payload = {
                "manifesto": num_manifesto,
                "status": "FINALIZADO",
                "data_finalizacao": dt_fim.strftime('%Y-%m-%dT%H:%M:%S'),
                "responsavel": responsavel
            }

        url = getattr(config, 'checklist_qvx_url', None) or "https://checklist.qvx.com.br/api/webhooks/manifesto"
        token = getattr(config, 'checklist_qvx_token', None) or "rx_live_t3wlOG4Y4vS0nFXycFIfftmD_GY4fiq5XWGZ1pvDqcY"
        token_str = token.strip()

        headers = {
            "Authorization": f"Bearer {token_str}",
            "X-Webhook-Token": token_str,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        logger.info(f"🚀 [CHECKLIST QVX] Disparando {evento_status} (MFT #{num_manifesto}) para {url} | Payload: {json.dumps(payload)}")

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=20)
            logger.info(f"📬 [CHECKLIST QVX] Resposta MFT #{num_manifesto}: HTTP {resp.status_code} - {resp.text[:250]}")
            cache.set(cache_key, True, timeout=60)
            status_envio = 'SUCESSO' if resp.status_code in [200, 201, 204] else 'ERRO'
            try:
                LogChecklistManifesto.objects.create(
                    manifesto=manifesto,
                    numero_manifesto=num_manifesto,
                    evento=evento_status,
                    status_envio=status_envio,
                    http_status=resp.status_code,
                    payload_enviado=payload,
                    resposta_api=resp.text[:2000]
                )
            except Exception as e_db:
                logger.error(f"Erro ao salvar LogChecklistManifesto: {e_db}")

            if status_envio == 'SUCESSO':
                return f"Sucesso: {resp.status_code}"
            else:
                logger.warning(f"⚠️ [CHECKLIST QVX] Resposta inesperada HTTP {resp.status_code} para MFT #{num_manifesto}: {resp.text[:250]}")
                return f"Aviso HTTP {resp.status_code}"
        except Exception as exc:
            logger.error(f"❌ [CHECKLIST QVX] Erro de conexão para MFT #{num_manifesto}: {exc}")
            try:
                LogChecklistManifesto.objects.create(
                    manifesto=manifesto,
                    numero_manifesto=num_manifesto,
                    evento=evento_status,
                    status_envio='ERRO',
                    http_status=None,
                    payload_enviado=payload,
                    resposta_api=f"Exceção: {exc}"[:2000]
                )
            except Exception as e_db:
                logger.error(f"Erro ao salvar LogChecklistManifesto (erro): {e_db}")

            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
            return f"Erro conexão: {exc}"



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


@shared_task(bind=True, max_retries=5)
def finalizar_manifesto_tms_task(self, manifesto_id):
    """Delegated to the correct TMS Adapter."""
    adapter = get_tms_adapter()
    if adapter:
        return adapter.finalizar_manifesto(manifesto_id, task=self)
    return "TMS Desativado."


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
            id_f_tms = f_data.get('id_tms') or f_data.get('Codigo')
            filial_nome = str(f_data.get('nome') or f_data.get('Razao') or 'FILIAL WEBHOOK').upper().strip()
            filial_obj = _buscar_ou_criar_filial_unificada(id_f_tms, filial_nome)

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

            # 🛡️ TRAVA 1: MANIFESTO JÁ FINALIZADO OU CANCELADO NO APP (NÃO REABRE NEM ALTERA HISTÓRICO)
            if manifesto_existente and manifesto_existente.status in ['FINALIZADO', 'CANCELADO']:
                event.status = 'IGNORADO'
                event.erro = f"Manifesto #{num_visual} já está {manifesto_existente.status} no app. Atualização via Webhook ignorada para proteger o histórico operacional."
                event.processed_at = timezone.now()
                event.save()
                logger.info(f"🔒 [PROTEÇÃO] Manifesto #{num_visual} já está {manifesto_existente.status} no app. Webhook ignorado.")
                return f"Manifesto #{num_visual} já finalizado/cancelado. Ignorado."

            # 🛡️ TRAVA 2: BASE/FILIAL INATIVA NO APP (Checa a base de operação real)
            base_checar = filial_operacao_obj or filial_obj
            if hasattr(base_checar, 'operacao_ativa') and not base_checar.operacao_ativa:
                event.status = 'IGNORADO'
                event.erro = f"Base/Filial '{base_checar.nome}' está inativa para recebimento de manifestos no app."
                event.processed_at = timezone.now()
                event.save()
                logger.info(f"🚫 Base '{base_checar.nome}' com operação inativa. Manifesto #{num_visual} ({num_mani_recebido}) ignorado.")
                return f"Base '{base_checar.nome}' inativa. Manifesto ignorado."

            # 🛡️ PRESERVAÇÃO DE STATUS EXISTENTE:
            # - Se já existia (seja EM_TRANSPORTE ou AGUARDANDO), MANTÉM exatamente o status atual.
            # - Se for um manifesto novo, inicia como AGUARDANDO.
            status_novo = manifesto_existente.status if manifesto_existente else 'AGUARDANDO'

            manifesto_defaults = {
                'motorista': motorista_obj,
                'filial': filial_obj,
                'filial_operacao': filial_operacao_obj,
                'status': status_novo,
                'manifesto_id_tms': id_tms_final,
            }
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
                    if not nota_obj and id_tms:
                        nota_obj = NotaFiscal.objects.filter(manifesto=manifesto_obj, freight_id_tms=str(id_tms)).first()

                frete_obj = None
                if id_tms:
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
                    # ✅ NOTA JÁ EXISTE NO MANIFESTO: APENAS COMPLETA DADOS FALTANTES
                    # NUNCA sobrescreve o status de notas que já foram entregues (BAIXADA) ou com OCORRÊNCIA!
                    campos_update = []
                    if id_tms and nota_obj.freight_id_tms != str(id_tms):
                        nota_obj.freight_id_tms = str(id_tms)
                        campos_update.append('freight_id_tms')
                    if chave_nfe and not nota_obj.chave_acesso:
                        nota_obj.chave_acesso = chave_nfe
                        campos_update.append('chave_acesso')
                    if cep_dest and not nota_obj.cep:
                        nota_obj.cep = cep_dest
                        campos_update.append('cep')
                    if frete_obj and not nota_obj.frete:
                        nota_obj.frete = frete_obj
                        campos_update.append('frete')
                    if dest.get('nome') and (not nota_obj.destinatario or nota_obj.destinatario == 'NÃO INFORMADO'):
                        nota_obj.destinatario = str(dest.get('nome')).upper()
                        campos_update.append('destinatario')
                    if endereco and (not nota_obj.endereco_entrega or 'CONSULTE' in nota_obj.endereco_entrega):
                        nota_obj.endereco_entrega = endereco
                        campos_update.append('endereco_entrega')

                    if campos_update:
                        nota_obj.save(update_fields=campos_update)
                    created_nota = False
                else:
                    # 🆕 NOTA NOVA NO MANIFESTO: CRIA COMO PENDENTE
                    nota_obj = NotaFiscal.objects.create(
                        manifesto=manifesto_obj,
                        numero_nota=numero_item,
                        chave_acesso=chave_nfe,
                        tipo_operacao=tipo_item,
                        destinatario=str(dest.get('nome', 'NÃO INFORMADO')).upper(),
                        endereco_entrega=endereco,
                        cep=cep_dest,
                        freight_id_tms=str(id_tms) if id_tms else None,
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
                if motorista_obj and motorista_obj.fcm_token:
                    from common.tasks_notificacoes import notificar_atribuicao_manifesto
                    notificar_atribuicao_manifesto(motorista_obj, num_mani, count_notas)
                    logger.info(f"📲 Push FCM de novo manifesto enviado com sucesso para {motorista_obj.nome_completo} (MFT: #{num_mani})")
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
            if manifesto_obj and manifesto_obj.status in ['FINALIZADO', 'CANCELADO']:
                evento.status = 'IGNORADO'
                evento.erro = f"Manifesto #{numero_rota} ja esta {manifesto_obj.status} no app. Integracao ignorada."
                evento.processed_at = timezone.now()
                evento.save()
                return f"Manifesto #{numero_rota} ja finalizado/cancelado."

            status_novo = manifesto_obj.status if manifesto_obj else 'AGUARDANDO'

            manifesto_obj, _ = Manifesto.objects.update_or_create(
                numero_manifesto=numero_rota,
                defaults={'motorista': motorista_obj, 'filial': filial_obj, 'status': status_novo}
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

            ManifestoBuscaLog.objects.update_or_create(
                numero_manifesto=numero_rota, motorista=motorista_obj,
                defaults={'status': 'PROCESSADO', 'mensagem_erro': None, 'quantidade_notas': count_notas}
            )

        from django.utils import timezone
        evento.status = 'PROCESSADO'
        evento.processed_at = timezone.now()
        evento.save()

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
    Evita acúmulo de rotas não utilizadas nas bases.
    """
    from manifesto.models import Manifesto
    from django.utils import timezone
    from datetime import timedelta

    limite = timezone.now() - timedelta(hours=48)
    manifestos_antigos = Manifesto.objects.filter(
        status='AGUARDANDO',
        data_criacao__lt=limite
    )

    qtd = manifestos_antigos.count()
    if qtd > 0:
        logger.info(f"🧹 Cancelando {qtd} manifesto(s) antigo(s) parado(s) em AGUARDANDO há mais de 48h.")
        manifestos_antigos.update(status='CANCELADO', finalizado=True)
    return f"{qtd} manifestos expirados cancelados."


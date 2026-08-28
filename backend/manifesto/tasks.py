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
            
            # 1. Filial (Vínculo comercial)
            f_data = payload.get('filial', {})
            id_f_tms = f_data.get('id_tms')
            filial_nome = f_data.get('nome', 'FILIAL WEBHOOK').upper()
            
            if id_f_tms:
                filial_obj, _ = Filial.objects.get_or_create(
                    id_filial_tms=str(id_f_tms),
                    defaults={'nome': filial_nome}
                )
            else:
                filial_obj, _ = Filial.objects.get_or_create(nome=filial_nome)

            # 🛡️ TRAVA 1: FILIAL INATIVA NO APP (Evita enfileirar manifestos de bases que ainda não usam o sistema)
            if hasattr(filial_obj, 'operacao_ativa') and not filial_obj.operacao_ativa:
                event.status = 'IGNORADO_FILIAL_INATIVA'
                event.erro = f"Filial '{filial_obj.nome}' está inativa para recebimento de manifestos no app."
                event.processed_at = timezone.now()
                event.save()
                logger.info(f"🚫 Filial '{filial_obj.nome}' com operação inativa. Manifesto {payload.get('manifesto', {}).get('numero')} ignorado.")
                return f"Filial '{filial_obj.nome}' inativa. Manifesto ignorado."

            # 2. Motorista (Cadastro Automático de Perfil)
            m_data = payload.get('motorista', {})
            cpf = str(m_data.get('cpf', '')).strip().replace('.', '').replace('-', '')
            nome_mot = m_data.get('nome', 'MOTORISTA WEBHOOK').upper()

            if not cpf:
                raise Exception("CPF do motorista não informado no payload.")

            motorista_obj, created_mot = Motorista.objects.get_or_create(
                cpf=cpf,
                defaults={
                    'nome_completo': nome_mot,
                    'filial': filial_obj
                }
            )
            
            if not created_mot:
                motorista_obj.nome_completo = nome_mot
                if not motorista_obj.filial:
                    motorista_obj.filial = filial_obj
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

            if manifesto_existente:
                # ✅ JÁ EXISTE NO BANCO: Usa o número visual que já temos (NÃO precisa bater na ESL!)
                num_visual = manifesto_existente.numero_manifesto
                id_tms_final = manifesto_existente.manifesto_id_tms or mani_data.get('id_tms') or num_mani_recebido
                logger.info(f"⚡ [WEBHOOK] Manifesto {num_visual} já cadastrado no banco. Atualizando rota sem consulta na ESL.")
            else:
                # 🔍 NÃO EXISTE NO BANCO: Consulta a ESL para ver se é ID interno e descobrir o sequence_code (número visual)
                adapter = get_tms_adapter()
                num_visual_esl = None
                if adapter and hasattr(adapter, 'resolver_numero_visual_manifesto'):
                    try:
                        num_visual_esl = adapter.resolver_numero_visual_manifesto(num_mani_recebido)
                    except Exception as e:
                        logger.warning(f"⚠️ Erro ao tentar resolver número visual na ESL para {num_mani_recebido}: {e}")

                if num_visual_esl:
                    num_visual = num_visual_esl
                    id_tms_final = num_mani_recebido
                else:
                    num_visual = num_mani_recebido
                    id_tms_final = mani_data.get('id_tms') or num_mani_recebido

            status_novo = 'AGUARDANDO'
            if manifesto_existente and manifesto_existente.status == 'EM_TRANSPORTE':
                status_novo = 'EM_TRANSPORTE'

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

            manifesto_defaults = {
                'motorista': motorista_obj,
                'filial': filial_obj,
                'status': status_novo,
                'manifesto_id_tms': id_tms_final,
            }
            # Só vincula veículo se veio no payload (não sobrescreve com None)
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

                filtros_busca = {'manifesto': manifesto_obj}
                if id_tms:
                    filtros_busca['freight_id_tms'] = str(id_tms)
                elif chave_nfe:
                    filtros_busca['chave_acesso'] = chave_nfe
                else:
                    filtros_busca['numero_nota'] = numero_item
                    filtros_busca['tipo_operacao'] = tipo_item

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

                # CEP do destinatário (Novo: antes não era salvo)
                cep_dest = str(dest.get('cep', '')).strip().replace('-', '') if dest.get('cep') else None

                nota_obj, created_nota = NotaFiscal.objects.update_or_create(
                    **filtros_busca,
                    defaults={
                        'destinatario': str(dest.get('nome', 'NÃO INFORMADO')).upper(),
                        'endereco_entrega': endereco,
                        'tipo_operacao': tipo_item,
                        'freight_id_tms': str(id_tms) if id_tms else None,
                        'numero_nota': numero_item,
                        'chave_acesso': chave_nfe,
                        'numero_coleta': num_coleta,
                        'numero_cte': normalizar_valor(item.get('numero_cte')),
                        'chave_cte': chave_cte,
                        'frete': frete_obj,
                        'cep': cep_dest,
                    }
                )

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
            status_novo = 'AGUARDANDO'
            if manifesto_obj and manifesto_obj.status == 'EM_TRANSPORTE':
                status_novo = 'EM_TRANSPORTE'

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


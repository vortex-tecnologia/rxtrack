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
def processar_webhook_manifesto_task(self, event_id):
    """
    Processa o payload de um WebhookEventoManifestoESL.
    - Cria/Busca Filial e Motorista.
    - Cria/Atualiza Manifesto com status 'AGUARDANDO'.
    - Cria/Atualiza Notas Fiscais vinculadas.
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

            # 3. Manifesto (Status 'AGUARDANDO' para controle operacional)
            mani_data = payload.get('manifesto', {})
            num_mani = str(mani_data.get('numero'))
            
            if not num_mani:
                raise Exception("Número do manifesto não informado no payload.")

            manifesto_obj = Manifesto.objects.filter(numero_manifesto=num_mani).first()
            
            status_novo = 'AGUARDANDO'
            if manifesto_obj and manifesto_obj.status == 'EM_TRANSPORTE':
                status_novo = 'EM_TRANSPORTE'

            manifesto_obj, _ = Manifesto.objects.update_or_create(
                numero_manifesto=num_mani,
                defaults={
                    'motorista': motorista_obj,
                    'filial': filial_obj,
                    'status': status_novo,
                    'manifesto_id_tms': mani_data.get('id_tms'),
                }
            )

            # 4. Itens (Notas Fiscais, Coletas, Minutas)
            itens = payload.get('itens', [])
            count_notas = 0
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

                NotaFiscal.objects.update_or_create(
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
                        'chave_cte': chave_cte
                    }
                )
                count_notas += 1

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
        except Exception as logger_err:
            logger.error(f"Falha ao registrar log de erro do webhook: {logger_err}")
            
        raise self.retry(exc=e, countdown=60)

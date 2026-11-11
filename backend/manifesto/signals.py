from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db import transaction
from manifesto.models import BaixaNF , Manifesto , NotaFiscal
from manifesto.services import enviar_painel


@receiver(post_save, sender=BaixaNF)
def atualizar_painel_monitoramento(sender, instance, created, **kwargs):
    if created:
        print(">>> SIGNAL DISPARADO BaixaNF")

        manifesto = instance.nota_fiscal.manifesto

        # Espera o banco confirmar tudo
        transaction.on_commit(
            lambda: enviar_painel(manifesto)
        )

@receiver(post_save, sender=Manifesto)
def manifesto_criado(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(
            lambda: enviar_painel(instance)
        )


@receiver(pre_save, sender=Manifesto)
def manifesto_pre_save_track_status(sender, instance, **kwargs):
    """Guarda o status anterior para detectar transição de status no post_save."""
    if instance.pk:
        try:
            old = Manifesto.objects.only('status').get(pk=instance.pk)
            instance._old_status_checklist = old.status
        except Manifesto.DoesNotExist:
            instance._old_status_checklist = None
    else:
        instance._old_status_checklist = None


@receiver(post_save, sender=Manifesto)
def manifesto_post_save_checklist_notify(sender, instance, created, **kwargs):
    """
    Dispara notificação para o Checklist QVX automaticamente quando o manifesto:
    1. Ganha status de em rota (EM_TRANSPORTE) -> envia EM_TRANSITO
    2. É finalizado (FINALIZADO) -> envia FINALIZADO
    """
    old_status = getattr(instance, '_old_status_checklist', None)
    new_status = instance.status

    from django.db import connection
    schema_atual = getattr(connection, 'schema_name', 'public')

    # Validação rápida de elegibilidade: se o motorista estiver carregado e não for 'EMPRESA', ignora
    if instance.motorista_id:
        motorista_inst = getattr(instance, 'motorista', None)
        if motorista_inst and getattr(motorista_inst, 'categoria', None):
            if str(motorista_inst.categoria).strip().upper() != 'EMPRESA':
                return

    # Transição para EM_TRANSPORTE (Em Rota / Em Trânsito)
    if (created and new_status == 'EM_TRANSPORTE') or (old_status != 'EM_TRANSPORTE' and new_status == 'EM_TRANSPORTE'):
        from manifesto.tasks import enviar_status_manifesto_checklist_task
        transaction.on_commit(
            lambda m_id=instance.id, sch=schema_atual: enviar_status_manifesto_checklist_task.delay(m_id, 'EM_TRANSITO', schema_name=sch)
        )

    # Transição para FINALIZADO
    elif old_status != 'FINALIZADO' and new_status == 'FINALIZADO':
        from manifesto.tasks import enviar_status_manifesto_checklist_task
        transaction.on_commit(
            lambda m_id=instance.id, sch=schema_atual: enviar_status_manifesto_checklist_task.delay(m_id, 'FINALIZADO', schema_name=sch)
        )

# REMOVIDO: Signal genérico que disparava enviar_painel em TODA atualização do Manifesto.
# Isso causava broadcasts desnecessários a cada heartbeat do motorista (ultimo_acesso, bateria, etc).
# Todos os casos reais já estão cobertos:
#   - Criação: signal manifesto_criado (acima)
#   - Baixa: signal atualizar_painel_monitoramento (BaixaNF)
#   - Nova NF: signal atualizar_painel_quando_criar_nota (NotaFiscal)
#   - Finalização: chamada explícita em views.py
# A bateria e último acesso continuam atualizando via WebSocket heartbeat (status_motorista).

@receiver(post_save, sender=NotaFiscal)
def atualizar_painel_quando_criar_nota(sender, instance, created, **kwargs):
    if created:
        manifesto = instance.manifesto
        transaction.on_commit(lambda m=manifesto: enviar_painel(m))


# ========================================================
# SIGNALS PARA LOG DE BAIXA NF-E (Centro de Notificações)
# ========================================================

@receiver(post_save, sender=BaixaNF)
def registrar_log_baixa_nfe(sender, instance, created, **kwargs):
    """
    Cria LogBaixaNfe quando:
    - BaixaNF é CRIADA (log de baixa sucesso)
    - BaixaNF é ATUALIZADA com integrado_tms=True (log de integração sucesso)
    - BaixaNF é ATUALIZADA com integrado_tms=False E log_erro_tms preenchido (log de integração erro)
    """
    from manifesto.models import LogBaixaNfe

    nf = instance.nota_fiscal
    manifesto = nf.manifesto
    filial = (getattr(manifesto, 'filial_operacao', None) or manifesto.filial) if manifesto else None

    if created:
        # Log de Baixa Registrada com Sucesso
        transaction.on_commit(lambda: LogBaixaNfe.objects.create(
            nota_fiscal=nf,
            manifesto_numero=manifesto.numero_manifesto if manifesto else '',
            numero_nota=nf.numero_nota,
            tipo='BAIXA_SUCESSO',
            mensagem=f"Baixa registrada com sucesso. Tipo: {instance.get_tipo_display()}",
            filial=filial,
        ))
    else:
        # Se o save() atualizou apenas campos que não têm relação com integração TMS (ex: foto/IA), ignora
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'integrado_tms' not in update_fields and 'log_erro_tms' not in update_fields:
            return

        # Atualização: Verifica se integração mudou
        if instance.integrado_tms and instance.processado_tms:
            # Sucesso na integração TMS: cria apenas 1x por NF e limpa erros não lidos anteriores da nota
            def criar_log_integracao_sucesso():
                LogBaixaNfe.objects.filter(
                    nota_fiscal=nf,
                    tipo='INTEGRACAO_ERRO',
                    lido=False
                ).update(lido=True)
                ja_existe_sucesso = LogBaixaNfe.objects.filter(
                    nota_fiscal=nf,
                    tipo='INTEGRACAO_SUCESSO',
                ).exists()
                if not ja_existe_sucesso:
                    LogBaixaNfe.objects.create(
                        nota_fiscal=nf,
                        manifesto_numero=manifesto.numero_manifesto if manifesto else '',
                        numero_nota=nf.numero_nota,
                        tipo='INTEGRACAO_SUCESSO',
                        mensagem="Integração com TMS ESL realizada com sucesso.",
                        filial=filial,
                    )
            transaction.on_commit(criar_log_integracao_sucesso)

        elif not instance.integrado_tms and instance.log_erro_tms:
            log_msg = str(instance.log_erro_tms).strip()
            # Ignora mensagens informativas/progresso ou idempotência da ESL para não disparar alerta de falso erro
            if not _eh_mensagem_ignorada_notificacao(log_msg):
                def criar_log_integracao_erro():
                    from django.db.models import Q
                    mft_num = manifesto.numero_manifesto if manifesto else ''
                    msg_trunc = log_msg[:500]

                    # Envia notificação APENAS 1x por nota fiscal (ou se já houver o mesmo erro não lido no mesmo manifesto)
                    q_existente = Q(nota_fiscal=nf, tipo='INTEGRACAO_ERRO')
                    if nf and nf.numero_nota:
                        q_existente |= Q(manifesto_numero=mft_num, numero_nota=nf.numero_nota, tipo='INTEGRACAO_ERRO')
                    if mft_num:
                        q_existente |= Q(manifesto_numero=mft_num, mensagem=msg_trunc, tipo='INTEGRACAO_ERRO', lido=False)

                    existente = LogBaixaNfe.objects.filter(q_existente).order_by('-criado_em').first()
                    if existente:
                        # Se ainda não foi lido e pertence à mesma nota, apenas atualiza a mensagem sem duplicar
                        if not existente.lido and existente.nota_fiscal_id == (nf.id if nf else None) and existente.mensagem != msg_trunc:
                            existente.mensagem = msg_trunc
                            existente.save(update_fields=['mensagem'])
                        return

                    LogBaixaNfe.objects.create(
                        nota_fiscal=nf,
                        manifesto_numero=mft_num,
                        numero_nota=nf.numero_nota,
                        tipo='INTEGRACAO_ERRO',
                        mensagem=msg_trunc,
                        filial=filial,
                    )
                transaction.on_commit(criar_log_integracao_erro)


def _eh_mensagem_ignorada_notificacao(mensagem):
    """
    Identifica mensagens de progresso, idempotência (ocorrência já cadastrada com mesma data/hora)
    ou manifesto já finalizado no TMS ('closed') que não devem gerar alerta de erro ou notificação.
    """
    if not mensagem:
        return True
    msg_str = str(mensagem).strip()
    if any(msg_str.startswith(p) for p in ("Sucesso", "Iniciando", "Aviso IA", "Info", "Atualizando")):
        return True
    msg_lower = msg_str.lower()
    termos_ignorados = (
        "menor ou igual",
        "já existe",
        "ja existe",
        "já foi cadastrad",
        "ja foi cadastrad",
        "já cadastrad",
        "ja cadastrad",
        "cadastrada com essa data e hora",
        "cadastrado com essa data e hora",
        "essa data e hora",
        "mesma data e hora",
        "já foi registrad",
        "ja foi registrad",
        "já se encontra finalizado",
        "ja se encontra finalizado",
        "não permite alteração",
        "nao permite alteracao",
        "status 'closed'",
        "already closed",
        "já finalizad",
        "ja finalizad",
        "já encerrad",
        "ja encerrad",
        "already exists",
        "already been taken",
    )
    return any(t in msg_lower for t in termos_ignorados)


from manifesto.models import ManifestoBuscaLog

@receiver(post_save, sender=ManifestoBuscaLog)
def registrar_log_importacao_erro(sender, instance, **kwargs):
    """
    Cria LogBaixaNfe quando uma importação de manifesto falha (apenas 1x por manifesto).
    Ignora avisos de manifesto já finalizado ('closed') no TMS.
    """
    if instance.status == 'ERRO' and instance.mensagem_erro:
        if _eh_mensagem_ignorada_notificacao(instance.mensagem_erro):
            return
        from manifesto.models import LogBaixaNfe
        
        filial = None
        if instance.motorista and instance.motorista.filial:
            filial = instance.motorista.filial

        def criar_log_erro():
            msg_trunc = instance.mensagem_erro[:500] if instance.mensagem_erro else "Erro na importação"
            existente = LogBaixaNfe.objects.filter(
                manifesto_numero=instance.numero_manifesto,
                tipo='IMPORTACAO_ERRO',
            ).order_by('-criado_em').first()
            if existente:
                if not existente.lido and existente.mensagem != msg_trunc:
                    existente.mensagem = msg_trunc
                    existente.save(update_fields=['mensagem'])
                return

            LogBaixaNfe.objects.create(
                nota_fiscal=None,
                manifesto_numero=instance.numero_manifesto,
                numero_nota='',
                tipo='IMPORTACAO_ERRO',
                mensagem=msg_trunc,
                filial=filial,
            )
        transaction.on_commit(criar_log_erro)


@receiver(post_save, sender=Manifesto)
@receiver(post_delete, sender=Manifesto)
def notificar_ws_cargas_manifesto(sender, instance, **kwargs):
    def disparar():
        try:
            from manifesto.services import notificar_atualizacao_cargas_fretes
            filial_efetiva = instance.filial_operacao or instance.filial
            notificar_atualizacao_cargas_fretes(filial_efetiva)
        except Exception as e:
            print(f"❌ Erro no signal WS Manifesto: {e}")
    transaction.on_commit(disparar)


@receiver(post_save, sender=NotaFiscal)
@receiver(post_delete, sender=NotaFiscal)
def notificar_ws_cargas_notafiscal(sender, instance, **kwargs):
    def disparar():
        try:
            from manifesto.services import notificar_atualizacao_cargas_fretes
            if instance.manifesto:
                filial_efetiva = getattr(instance.manifesto, 'filial_operacao', None) or getattr(instance.manifesto, 'filial', None)
            else:
                filial_efetiva = None
            notificar_atualizacao_cargas_fretes(filial_efetiva)
        except Exception as e:
            print(f"❌ Erro no signal WS NotaFiscal: {e}")
    transaction.on_commit(disparar)


@receiver(post_save, sender=BaixaNF)
@receiver(post_delete, sender=BaixaNF)
def notificar_ws_cargas_baixanf(sender, instance, **kwargs):
    def disparar():
        try:
            from manifesto.services import notificar_atualizacao_cargas_fretes
            filial_efetiva = None
            if instance.nota_fiscal and instance.nota_fiscal.manifesto:
                mft = instance.nota_fiscal.manifesto
                filial_efetiva = mft.filial_operacao or mft.filial
            notificar_atualizacao_cargas_fretes(filial_efetiva)
        except Exception as e:
            print(f"❌ Erro no signal WS BaixaNF: {e}")
    transaction.on_commit(disparar)
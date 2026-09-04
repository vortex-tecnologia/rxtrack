from django.db.models.signals import post_save, post_delete
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
    filial = manifesto.filial if manifesto else None

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
        # Atualização: Verifica se integração mudou
        if instance.integrado_tms and instance.processado_tms:
            # Sucesso na integração TMS
            # Evita duplicatas: só cria se não existe log de integração sucesso recente para esta NF
            def criar_log_integracao_sucesso():
                from django.utils import timezone
                import datetime
                recente = LogBaixaNfe.objects.filter(
                    nota_fiscal=nf,
                    tipo='INTEGRACAO_SUCESSO',
                    criado_em__gte=timezone.now() - datetime.timedelta(minutes=5)
                ).exists()
                if not recente:
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
            is_falso_erro = (
                any(log_msg.startswith(p) for p in ["Sucesso", "Iniciando", "Aviso IA", "Info", "Atualizando"]) or
                "menor ou igual" in log_msg.lower() or
                "já existe" in log_msg.lower() or
                "ja existe" in log_msg.lower()
            )
            if not is_falso_erro:
                def criar_log_integracao_erro():
                    from django.utils import timezone
                    import datetime
                    recente = LogBaixaNfe.objects.filter(
                        nota_fiscal=nf,
                        tipo='INTEGRACAO_ERRO',
                        criado_em__gte=timezone.now() - datetime.timedelta(minutes=2)
                    ).exists()
                    if not recente:
                        LogBaixaNfe.objects.create(
                            nota_fiscal=nf,
                            manifesto_numero=manifesto.numero_manifesto if manifesto else '',
                            numero_nota=nf.numero_nota,
                            tipo='INTEGRACAO_ERRO',
                            mensagem=log_msg[:500],
                            filial=filial,
                        )
                transaction.on_commit(criar_log_integracao_erro)


from manifesto.models import ManifestoBuscaLog

@receiver(post_save, sender=ManifestoBuscaLog)
def registrar_log_importacao_erro(sender, instance, **kwargs):
    """
    Cria LogBaixaNfe quando uma importação de manifesto falha.
    """
    if instance.status == 'ERRO' and instance.mensagem_erro:
        from manifesto.models import LogBaixaNfe
        
        filial = None
        if instance.motorista and instance.motorista.filial:
            filial = instance.motorista.filial

        def criar_log_erro():
            from django.utils import timezone
            import datetime
            recente = LogBaixaNfe.objects.filter(
                manifesto_numero=instance.numero_manifesto,
                tipo='IMPORTACAO_ERRO',
                criado_em__gte=timezone.now() - datetime.timedelta(minutes=2)
            ).exists()
            if not recente:
                LogBaixaNfe.objects.create(
                    nota_fiscal=None,
                    manifesto_numero=instance.numero_manifesto,
                    numero_nota='',
                    tipo='IMPORTACAO_ERRO',
                    mensagem=instance.mensagem_erro[:500] if instance.mensagem_erro else "Erro na importação",
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
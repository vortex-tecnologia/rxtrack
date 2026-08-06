from django.db.models.signals import post_save
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

@receiver(post_save, sender=Manifesto)
def manifesto_atualizado(sender, instance, **kwargs):
    transaction.on_commit(
        lambda: enviar_painel(instance)
    )

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
            # Ignora mensagens informativas/progresso para não disparar alerta de falso erro
            is_falso_erro = any(log_msg.startswith(p) for p in ["Sucesso", "Iniciando", "Aviso IA", "Info"])
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
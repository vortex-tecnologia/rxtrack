from django.core.cache import cache

CACHE_KEY = 'configuracao_sistema_singleton'
CACHE_TIMEOUT = 300  # 5 minutos


def get_config():
    """
    Retorna a configuração do sistema com cache de 5 minutos.
    Evita hit no banco a cada chamada.
    
    Uso:
        from configuracao.utils import get_config
        config = get_config()
        token = config.token_analytics
        if config.enviar_tms:
            ...
    """
    config = cache.get(CACHE_KEY)
    if config is None:
        from configuracao.models import ConfiguracaoSistema
        config = ConfiguracaoSistema.load()
        cache.set(CACHE_KEY, config, CACHE_TIMEOUT)
    return config


def invalidar_cache_config():
    """
    Invalida o cache quando a configuração é alterada no Admin.
    Chamado automaticamente pelo signal post_save.
    """
    cache.delete(CACHE_KEY)


def notificar_falha_tms(baixa_id, erro, task_name=""):
    """
    Envia email de notificação quando uma integração TMS falha.
    Só envia se a flag enviar_email_falhas estiver ativa e houver emails cadastrados.
    """
    config = get_config()
    if not config.enviar_email_falhas:
        return
    
    destinatarios = config.get_emails_notificacao_list()
    if not destinatarios:
        print("EMAIL: Flag de email ativa mas nenhum destinatário cadastrado no Admin.")
        return
    
    try:
        from django.core.mail import send_mail
        from django.template.loader import render_to_string
        from django.utils.html import strip_tags
        from django.conf import settings
        from manifesto.models import BaixaNF
        from django.utils import timezone
        
        # Busca detalhes da baixa
        try:
            baixa = BaixaNF.objects.select_related(
                'nota_fiscal', 
                'nota_fiscal__manifesto', 
                'nota_fiscal__manifesto__motorista'
            ).get(id=baixa_id)
            
            nota = baixa.nota_fiscal
            manifesto = nota.manifesto
            
            # Formatar datas para o email
            data_baixa_formatada = timezone.localtime(baixa.data_baixa).strftime('%d/%m/%Y %H:%M:%S')
            data_criacao_mft_formatada = timezone.localtime(manifesto.data_criacao).strftime('%d/%m/%Y %H:%M:%S')
            
            numero_manifesto = manifesto.numero_manifesto
            motorista_nome = manifesto.motorista.nome_completo if manifesto.motorista else "Não atribuído"
            numero_nota = nota.numero_nota or "N/A"
            chave_nfe = nota.chave_acesso or "N/A"
            
        except BaixaNF.DoesNotExist:
            numero_manifesto = "N/A (Baixa Excluída)"
            data_criacao_mft_formatada = "N/A"
            motorista_nome = "N/A"
            numero_nota = "N/A"
            chave_nfe = "N/A"
            data_baixa_formatada = "N/A"

        assunto = f"⚠️ Falha TMS - Manifesto #{numero_manifesto} / NF {numero_nota}"
        
        contexto = {
            'numero_manifesto': numero_manifesto,
            'data_criacao_manifesto': data_criacao_mft_formatada,
            'motorista_nome': motorista_nome,
            'numero_nota': numero_nota,
            'chave_nfe': chave_nfe,
            'data_baixa': data_baixa_formatada,
            'erro': erro
        }
        
        html_message = render_to_string('emails/falha_tms.html', contexto)
        plain_message = strip_tags(html_message)
        
        send_mail(
            assunto,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            destinatarios,
            html_message=html_message,
            fail_silently=True,
        )
        print(f"EMAIL HTML: Notificação de falha TMS enviada para {', '.join(destinatarios)}")
    except Exception as e:
        print(f"EMAIL: Erro ao enviar notificação de falha HTML: {e}")

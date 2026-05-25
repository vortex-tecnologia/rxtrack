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
    
    - Remetente: configurado no settings.py (EMAIL_HOST_USER)
    - Destinatários: cadastrados no Admin (emails_notificacao)
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
        from django.conf import settings
        
        assunto = f"⚠️ Falha TMS - Baixa #{baixa_id}"
        mensagem = (
            f"Uma integração com o TMS falhou.\n\n"
            f"Task: {task_name}\n"
            f"Baixa ID: {baixa_id}\n"
            f"Erro: {erro}\n\n"
            f"Verifique o painel administrativo para mais detalhes."
        )
        
        send_mail(
            assunto,
            mensagem,
            settings.DEFAULT_FROM_EMAIL,
            destinatarios,
            fail_silently=True,
        )
        print(f"EMAIL: Notificação de falha TMS enviada para {', '.join(destinatarios)}")
    except Exception as e:
        print(f"EMAIL: Erro ao enviar notificação de falha: {e}")

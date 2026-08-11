import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.db import models
from .models import TicketSuporte, MensagemSuporte

logger = logging.getLogger(__name__)

@receiver(post_save, sender=TicketSuporte)
def notificar_novo_ticket(sender, instance, created, **kwargs):
    """
    Sinal executado ao criar um novo Ticket.
    Envia uma notificação Web Push para toda a equipe do SAC/Gestores da mesma filial.
    """
    if created:
        try:
            from mobile.services.webpush_service import enviar_notificacao_usuario
            
            filial = instance.filial
            if not filial:
                return
            
            # Filtra usuários do tipo SAC e Gestores/Administradores vinculados a esta filial
            destinatarios = User.objects.filter(
                motorista_perfil__filial=filial
            ).filter(
                models.Q(motorista_perfil__tipo_usuario='SAC') |
                models.Q(motorista_perfil__cargo__in=['GESTOR', 'ADMINISTRADOR'])
            ).distinct()
            
            titulo = "Novo Chamado de Suporte"
            motorista_nome = instance.motorista.nome_completo if instance.motorista else "Motorista"
            mensagem = f"{motorista_nome} abriu o chamado #{instance.id} ({instance.get_categoria_display()})."
            url = "/suporte/"  # URL do painel SAC
            
            for user in destinatarios:
                try:
                    enviar_notificacao_usuario(user, titulo, mensagem, url)
                except Exception as e:
                    logger.warning(f"Falha ao enviar push para usuário {user.username}: {e}")
        except Exception as e:
            logger.error(f"Erro geral no sinal notificar_novo_ticket: {e}")


@receiver(post_save, sender=MensagemSuporte)
def notificar_nova_mensagem(sender, instance, created, **kwargs):
    """
    Sinal executado ao salvar uma mensagem.
    Se a mensagem for do motorista, notifica o atendente designado ou toda a equipe SAC da filial.
    Se a mensagem for do SAC (e não for do sistema), notifica o motorista dono do chamado.
    """
    if created:
        try:
            from mobile.services.webpush_service import enviar_notificacao_usuario
            
            ticket = instance.ticket
            if not ticket:
                return
                
            if instance.enviado_por_motorista:
                # 1. Mensagem enviada pelo motorista -> Notifica o SAC
                titulo = f"Msg de {ticket.motorista.nome_completo} (Chamado #{ticket.id})"
                texto_resumo = instance.texto[:100] if instance.texto else f"Enviou um(a) {instance.get_tipo_display()}"
                url = "/suporte/"
                
                if ticket.atendente:
                    # Notifica apenas o atendente que está com o caso
                    try:
                        enviar_notificacao_usuario(ticket.atendente, titulo, texto_resumo, url)
                    except Exception as e:
                        logger.warning(f"Falha ao enviar push para atendente {ticket.atendente.username}: {e}")
                else:
                    # Se não tem atendente ainda, notifica toda a equipe SAC/Gestores da filial
                    filial = ticket.filial
                    if filial:
                        destinatarios = User.objects.filter(
                            motorista_perfil__filial=filial
                        ).filter(
                            models.Q(motorista_perfil__tipo_usuario='SAC') |
                            models.Q(motorista_perfil__cargo__in=['GESTOR', 'ADMINISTRADOR'])
                        ).distinct()
                        
                        for user in destinatarios:
                            try:
                                enviar_notificacao_usuario(user, titulo, texto_resumo, url)
                            except Exception as e:
                                logger.warning(f"Falha ao enviar push para operador {user.username}: {e}")
            else:
                # 2. Mensagem enviada pelo SAC/Sistema -> Notifica o motorista
                # Ignora mensagens automáticas do sistema para evitar spam de alertas nativos
                if instance.tipo != 'SISTEMA' and ticket.motorista and ticket.motorista.user:
                    titulo = f"Nova resposta do Suporte (Chamado #{ticket.id})"
                    texto_resumo = instance.texto[:100] if instance.texto else f"Enviou um(a) {instance.get_tipo_display()}"
                    url = "/app/"  # Rota do app móvel do motorista
                    
                    try:
                        enviar_notificacao_usuario(ticket.motorista.user, titulo, texto_resumo, url)
                    except Exception as e:
                        logger.warning(f"Falha ao enviar push para motorista {ticket.motorista.user.username}: {e}")
        except Exception as e:
            logger.error(f"Erro geral no sinal notificar_nova_mensagem: {e}")

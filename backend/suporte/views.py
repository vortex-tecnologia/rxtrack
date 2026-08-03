from rest_framework import viewsets, permissions, status, serializers
from rest_framework.response import Response
from rest_framework.decorators import action
from django.utils import timezone
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import TicketSuporte, MensagemSuporte
from .serializers import TicketSuporteSerializer, MensagemSuporteSerializer

class PainelSACView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = 'suporte/painel_sac.html'
    raise_exception = True

    def test_func(self):
        user = self.request.user
        if not hasattr(user, 'motorista_perfil'):
            return False
        perfil = user.motorista_perfil
        
        # Gestor, Admin e SAC nativo sempre tem acesso (sobrepoe tabela de permissoes)
        if perfil.cargo in ['GESTOR', 'ADMINISTRADOR'] or perfil.tipo_usuario == 'SAC':
            return True
        
        # Usa PermissaoUsuario se existir como fallback para outros membros
        if hasattr(perfil, 'permissoes'):
            return perfil.permissoes.pode_acessar_sac
        
        return False

    def handle_no_permission(self):
        from django.http import HttpResponse
        html = """
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Acesso Restrito</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
            <style>
                body { background: #1a1d21; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
            </style>
        </head>
        <body>
            <div class="card shadow-lg border-0 text-center" style="max-width: 420px; border-radius: 16px;">
                <div class="card-body p-5">
                    <i class="bi bi-shield-lock-fill text-danger" style="font-size: 4rem;"></i>
                    <h4 class="fw-bold mt-3">Acesso Restrito</h4>
                    <p class="text-muted">Voce nao tem permissao para acessar esta pagina. Apenas usuarios do tipo <strong>SAC</strong>, <strong>Gestor</strong> ou <strong>Administrador</strong> podem acessar o painel de suporte.</p>
                    <a href="/dashboard/" class="btn btn-primary rounded-pill px-4 py-2 mt-2 fw-bold">
                        <i class="bi bi-arrow-left me-2"></i>Ir para Dashboard
                    </a>
                </div>
            </div>
        </body>
        </html>
        """
        return HttpResponse(html, status=403)

class TicketSuporteViewSet(viewsets.ModelViewSet):
    """
    API para criação e listagem de tickets de suporte pelo Motorista (Mobile)
    """
    serializer_class = TicketSuporteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not hasattr(user, 'motorista_perfil'):
            return TicketSuporte.objects.none()
            
        perfil = user.motorista_perfil
        if perfil.tipo_usuario == 'SAC' or perfil.cargo in ['GESTOR', 'ADMINISTRADOR']:
            return TicketSuporte.objects.filter(filial=perfil.filial).order_by('-updated_at')
        else:
            return TicketSuporte.objects.filter(motorista=perfil).order_by('-updated_at')

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        user = request.user
        
        # Se o usuário logado for o motorista associado ao ticket,
        # marca as mensagens do SAC/Sistema como lidas.
        if hasattr(user, 'motorista_perfil') and instance.motorista == user.motorista_perfil:
            instance.mensagens.filter(enviado_por_motorista=False, lida=False).update(lida=True)
            
        # Se o usuário logado for SAC, Gestor ou Administrador,
        # marca as mensagens do motorista como lidas.
        elif hasattr(user, 'motorista_perfil') and (
            user.motorista_perfil.tipo_usuario == 'SAC' or 
            user.motorista_perfil.cargo in ['GESTOR', 'ADMINISTRADOR']
        ):
            instance.mensagens.filter(enviado_por_motorista=True, lida=False).update(lida=True)
            
        return super().retrieve(request, *args, **kwargs)

    def perform_create(self, serializer):
        # Quando criar um ticket, vincula automaticamente ao motorista logado e a sua filial
        if hasattr(self.request.user, 'motorista_perfil'):
            motorista = self.request.user.motorista_perfil
            ticket = serializer.save(
                motorista=motorista,
                filial=motorista.filial
            )
            
            # Dados extras enviados pelo frontend
            detalhe = self.request.data.get('detalhe', '')
            manifesto_numero = self.request.data.get('manifesto_numero', '')
            nota_numero = self.request.data.get('nota_numero', '')
            
            # 1. Mensagem INFO CARD automatica
            info_lines = []
            info_lines.append(f"Motorista: {motorista.nome_completo}")
            info_lines.append(f"Documento: {motorista.cpf}")
            if manifesto_numero:
                info_lines.append(f"Manifesto: #{manifesto_numero}")
            if nota_numero:
                info_lines.append(f"Nota: {nota_numero}")
            info_lines.append(f"Categoria: {ticket.get_categoria_display()}")
            
            info_card_text = "\n".join(info_lines)
            
            MensagemSuporte.objects.create(
                ticket=ticket,
                enviado_por_motorista=True,
                atendente=self.request.user,
                tipo='SISTEMA',
                texto=info_card_text
            )
            
            # 2. Mensagem do motorista com o detalhe do problema
            if detalhe.strip():
                MensagemSuporte.objects.create(
                    ticket=ticket,
                    enviado_por_motorista=True,
                    atendente=self.request.user,
                    tipo='TEXTO',
                    texto=detalhe.strip()
                )
            
            # Notifica o painel SAC em tempo real
            try:
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f'filial_suporte_{motorista.filial_id}',
                        {
                            'type': 'ticket_updated',
                            'ticket_id': ticket.id,
                            'action': 'novo_ticket',
                            'preview': f'Novo chamado de {motorista.nome_completo}'
                        }
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Erro ao notificar WebSocket de novo ticket: {e}")
        else:
            raise permissions.PermissionDenied("Apenas motoristas podem abrir chamados.")
            
    @action(detail=True, methods=['post'])
    def assumir(self, request, pk=None):
        ticket = self.get_object()
        user = request.user
        
        if not hasattr(user, 'motorista_perfil') or (user.motorista_perfil.tipo_usuario != 'SAC' and user.motorista_perfil.cargo not in ['GESTOR', 'ADMINISTRADOR']):
            return Response({"error": "Apenas agentes SAC podem assumir tickets."}, status=status.HTTP_403_FORBIDDEN)
            
        if ticket.status != 'CANAL_ABERTO':
            return Response({"error": "Ticket já assumido ou fechado."}, status=status.HTTP_400_BAD_REQUEST)
            
        ticket.status = 'EM_ATENDIMENTO'
        ticket.atendente = user
        ticket.updated_at = timezone.now()
        ticket.save(update_fields=['status', 'atendente', 'updated_at'])
        
        # Envia mensagem do sistema
        msg = MensagemSuporte.objects.create(
            ticket=ticket,
            enviado_por_motorista=False,
            atendente=user,
            tipo='SISTEMA',
            texto=f"[SISTEMA] O agente {user.get_full_name() or user.username} assumiu o atendimento."
        )
        
        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                # Notifica SACs da filial sobre remocao de status 'Aberto'
                async_to_sync(channel_layer.group_send)(
                    f'filial_suporte_{ticket.filial_id}',
                    {
                        'type': 'ticket_updated',
                        'ticket_id': ticket.id,
                        'action': 'ticket_assumido',
                        'preview': f"Em atendimento por {user.username}"
                    }
                )
                
                # Notifica Ticket pra Motorista ver
                async_to_sync(channel_layer.group_send)(
                    f'ticket_{ticket.id}',
                    {
                        'type': 'chat_message',
                        'id': msg.id,
                        'ticket_id': ticket.id,
                        'remetente': 'Sistema',
                        'enviado_por_motorista': False,
                        'mensagem': msg.texto,
                        'tipo': msg.tipo,
                        'created_at': msg.created_at.isoformat()
                    }
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Erro ao notificar WebSocket ao assumir chamado: {e}")
        
        return Response({"status": "Assumido com sucesso."})

    @action(detail=True, methods=['post'])
    def encerrar(self, request, pk=None):
        ticket = self.get_object()
        user = request.user
        
        if not hasattr(user, 'motorista_perfil') or (user.motorista_perfil.tipo_usuario != 'SAC' and user.motorista_perfil.cargo not in ['GESTOR', 'ADMINISTRADOR']):
            return Response({"error": "Apenas agentes SAC podem encerrar tickets."}, status=status.HTTP_403_FORBIDDEN)
            
        if ticket.status == 'FECHADO':
            return Response({"error": "Ticket já está fechado."}, status=status.HTTP_400_BAD_REQUEST)
            
        ticket.status = 'FECHADO'
        ticket.closed_at = timezone.now()
        ticket.updated_at = timezone.now()
        ticket.save(update_fields=['status', 'closed_at', 'updated_at'])
        
        # Envia mensagem do sistema
        msg = MensagemSuporte.objects.create(
            ticket=ticket,
            enviado_por_motorista=False,
            atendente=user,
            tipo='SISTEMA',
            texto=f"[SISTEMA] O chat foi encerrado por {user.get_full_name() or user.username}."
        )
        
        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                # Notifica SAC
                async_to_sync(channel_layer.group_send)(
                    f'filial_suporte_{ticket.filial_id}',
                    {
                        'type': 'ticket_updated',
                        'ticket_id': ticket.id,
                        'action': 'ticket_encerrado',
                        'preview': "Atendimento Finalizado"
                    }
                )
                
                # Notifica Chat WS
                async_to_sync(channel_layer.group_send)(
                    f'ticket_{ticket.id}',
                    {
                        'type': 'chat_message',
                        'id': msg.id,
                        'ticket_id': ticket.id,
                        'remetente': 'Sistema',
                        'enviado_por_motorista': False,
                        'mensagem': msg.texto,
                        'tipo': msg.tipo,
                        'created_at': msg.created_at.isoformat()
                    }
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Erro ao notificar WebSocket ao encerrar chamado: {e}")

        return Response({"status": "Encerrado com sucesso."})

class MensagemSuporteViewSet(viewsets.ModelViewSet):
    """
    API para enviar arquivos ou mensagens para um ticket existente via REST.
    (Mensagens de texto padrão fluirão primordialmente via WebSocket, mas uploads de arquivo vêm pra cá).
    """
    serializer_class = MensagemSuporteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not hasattr(self.request.user, 'motorista_perfil'):
            return MensagemSuporte.objects.none()
            
        perfil = self.request.user.motorista_perfil
        if perfil.tipo_usuario == 'SAC' or perfil.cargo in ['GESTOR', 'ADMINISTRADOR']:
            return MensagemSuporte.objects.filter(ticket__filial=perfil.filial).order_by('created_at')
        else:
            return MensagemSuporte.objects.filter(ticket__motorista=perfil).order_by('created_at')

    def perform_create(self, serializer):
        # Confere se o ticket pertence a quem esta mandando
        ticket_id = self.request.data.get('ticket')
        if not ticket_id:
            raise serializers.ValidationError({"ticket": "Obrigatorio informar o ticket."})
            
        try:
            ticket = TicketSuporte.objects.get(id=ticket_id)
        except TicketSuporte.DoesNotExist:
            raise serializers.ValidationError({"ticket": "Ticket nao encontrado."})
        
        # Bloqueia mensagens em tickets fechados
        if ticket.status == 'FECHADO':
            raise serializers.ValidationError({"ticket": "Este chamado foi encerrado. Nao e possivel enviar mensagens."})
        
        # Processa upload de arquivo via FTP se houver
        arquivo_file = self.request.FILES.get('arquivo')
        tipo_msg = self.request.data.get('tipo', 'TEXTO')
        ftp_url = None
        
        if arquivo_file:
            from .utils import upload_suporte_ftp, gerar_nome_arquivo
            
            # Determina extensao do arquivo
            nome_original = arquivo_file.name or 'arquivo'
            extensao = nome_original.rsplit('.', 1)[-1] if '.' in nome_original else 'bin'
            
            # Mapeia extensao para tipo se nao foi especificado
            if tipo_msg == 'TEXTO':
                ext_lower = extensao.lower()
                if ext_lower in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'):
                    tipo_msg = 'IMAGEM'
                elif ext_lower in ('mp4', 'webm', 'mov', 'avi'):
                    tipo_msg = 'VIDEO'
                elif ext_lower in ('mp3', 'ogg', 'wav', 'webm', 'm4a', 'aac'):
                    tipo_msg = 'AUDIO'
            
            nome_ftp = gerar_nome_arquivo(ticket.id, tipo_msg, extensao)
            arquivo_bytes = arquivo_file.read()
            ftp_url = upload_suporte_ftp(arquivo_bytes, nome_ftp, tipo_msg)
            
            if not ftp_url:
                raise serializers.ValidationError({"arquivo": "Falha no upload do arquivo."})

        user = self.request.user
        perfil = getattr(user, 'motorista_perfil', None)
        
        # Define se é o motorista dono do ticket ou um agente (SAC/Gestor)
        is_agente = (perfil and (perfil.tipo_usuario == 'SAC' or perfil.cargo in ['GESTOR', 'ADMINISTRADOR'])) or user.is_staff or user.is_superuser
        is_dono_ticket = (perfil and ticket.motorista == perfil)

        if is_agente:
            # Logica para SAC respondendo (via painel Web ou App)
            save_kwargs = {
                'enviado_por_motorista': False,
                'atendente': user,
            }
            if tipo_msg != 'TEXTO':
                save_kwargs['tipo'] = tipo_msg
                
            msg = serializer.save(**save_kwargs)
            
            if ftp_url:
                msg.arquivo = ftp_url
                msg.tipo = tipo_msg
                msg.save(update_fields=['arquivo', 'tipo'])
            
            # Atualiza ticket para EM_ATENDIMENTO se ainda for CANAL_ABERTO
            if ticket.status == 'CANAL_ABERTO':
                ticket.status = 'EM_ATENDIMENTO'
                ticket.atendente = user
            ticket.updated_at = timezone.now()
            ticket.save(update_fields=['status', 'atendente', 'updated_at'])
            
            # Notifica motorista via WebSocket
            try:
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f'ticket_{ticket.id}',
                        {
                            'type': 'chat_message',
                            'id': msg.id,
                            'ticket_id': ticket.id,
                            'remetente': user.get_full_name() or user.username,
                            'enviado_por_motorista': msg.enviado_por_motorista,
                            'mensagem': msg.texto,
                            'tipo': msg.tipo,
                            'arquivo_url': ftp_url or (str(msg.arquivo) if msg.arquivo else None),
                            'created_at': msg.created_at.isoformat()
                        }
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Erro ao notificar WebSocket de nova resposta do SAC: {e}")

            # Notifica motorista via Push FCM (para o celular Android / APK)
            try:
                from common.tasks_notificacoes import notificar_mensagem_sac
                atendente_nome = user.get_full_name() or user.username
                notificar_mensagem_sac(ticket, atendente_nome=atendente_nome)
            except Exception as push_err:
                import logging
                logging.getLogger(__name__).error(f"Erro ao disparar FCM Push para SAC: {push_err}")

        elif is_dono_ticket:
            # Lógica para o motorista dono do chamado enviando mensagem
            save_kwargs = {
                'enviado_por_motorista': True,
                'atendente': user,
            }
            if tipo_msg != 'TEXTO':
                save_kwargs['tipo'] = tipo_msg
            
            msg = serializer.save(**save_kwargs)
            
            if ftp_url:
                msg.arquivo = ftp_url
                msg.tipo = tipo_msg
                msg.save(update_fields=['arquivo', 'tipo'])
            
            ticket.updated_at = timezone.now()
            ticket.save(update_fields=['updated_at'])
            
            try:
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f'filial_suporte_{ticket.filial_id}',
                        {
                            'type': 'ticket_updated',
                            'ticket_id': ticket.id,
                            'action': 'nova_mensagem',
                            'preview': msg.texto[:50] if msg.texto else f'[{msg.tipo}]'
                        }
                    )
                    async_to_sync(channel_layer.group_send)(
                        f'ticket_{ticket.id}',
                        {
                            'type': 'chat_message',
                            'id': msg.id,
                            'ticket_id': ticket.id,
                            'remetente': ticket.motorista.nome_completo,
                            'enviado_por_motorista': msg.enviado_por_motorista,
                            'mensagem': msg.texto,
                            'tipo': msg.tipo,
                            'arquivo_url': ftp_url or (str(msg.arquivo) if msg.arquivo else None),
                            'created_at': msg.created_at.isoformat()
                        }
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Erro ao notificar WebSocket de nova mensagem do motorista: {e}")
        else:
            raise permissions.PermissionDenied("Você não tem acesso a este ticket.")



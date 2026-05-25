import json
from urllib.parse import parse_qs
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import TicketSuporte, MensagemSuporte

class SupportConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Authenticate via Token in query string
        query_params = parse_qs(self.scope['query_string'].decode())
        token_list = query_params.get('token')
        self.user = self.scope.get('user')

        if token_list:
            token_string = token_list[0]
            user = await self.get_user_from_token(token_string)
            if user:
                self.user = user
                self.scope['user'] = user
                
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return
        
        # O cliente pode se conectar ao ticket E/OU à filial inteira
        self.ticket_id = self.scope['url_route']['kwargs'].get('ticket_id')
        self.filial_id = self.scope['url_route']['kwargs'].get('filial_id')

        # Se for um Motorista acessando um ticket específico
        if self.ticket_id:
            self.room_group_name = f'ticket_{self.ticket_id}'
            
            # Validação de acesso ao ticket
            has_access = await self.user_can_access_ticket(self.user, self.ticket_id)
            if not has_access:
                await self.close()
                return

        # Se for SAC/Gestor escutando uma filial inteira (novo chamado, atualização global)
        elif self.filial_id:
            self.room_group_name = f'filial_suporte_{self.filial_id}'
            
            has_access = await self.user_can_access_filial(self.user, self.filial_id)
            if not has_access:
                await self.close()
                return
        else:
            await self.close()
            return

        # Entra no grupo
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Sai do grupo
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    # Recebe mensagem do WebSocket
    async def receive(self, text_data):
        if not getattr(self, 'ticket_id', None):
            return # Somente ticket rooms podem receber mensagens diretas assim

        # Bloqueia envio em tickets fechados
        ticket_status = await self.get_ticket_status(self.ticket_id)
        if ticket_status == 'FECHADO':
            await self.send(text_data=json.dumps({
                'type': 'erro',
                'mensagem': 'Este chamado foi encerrado. Nao e possivel enviar mensagens.'
            }))
            return

        text_data_json = json.loads(text_data)
        mensagem_texto = text_data_json.get('mensagem', '')
        # Se vier com tipo, default TEXTO (fotos/audio podem mandar link via WS ou subir via REST)
        tipo = text_data_json.get('tipo', 'TEXTO')
        arquivo_url = text_data_json.get('arquivo_url', None)
        
        # Salva no banco de dados
        msg_obj = await self.save_message(self.user, self.ticket_id, mensagem_texto, tipo, arquivo_url)

        # Atualiza payload para enviar
        payload = {
            'type': 'chat_message', # calls chat_message method
            'id': msg_obj.id,
            'ticket_id': self.ticket_id,
            'remetente': msg_obj.remetente_nome,
            'enviado_por_motorista': msg_obj.enviado_por_motorista,
            'mensagem': msg_obj.texto,
            'tipo': msg_obj.tipo,
            'arquivo_url': getattr(msg_obj.arquivo, 'url', None) if msg_obj.arquivo else arquivo_url,
            'created_at': msg_obj.created_at.isoformat()
        }

        # Dispara para o grupo do Ticket
        await self.channel_layer.group_send(
            self.room_group_name,
            payload
        )
        
        # Dispara notificação para o grupo da Filial para o SAC
        filial_id_do_ticket = await self.get_ticket_filial_id(self.ticket_id)
        if filial_id_do_ticket:
            await self.channel_layer.group_send(
                f'filial_suporte_{filial_id_do_ticket}',
                {
                    'type': 'ticket_updated',
                    'ticket_id': self.ticket_id,
                    'action': 'nova_mensagem',
                    'preview': mensagem_texto[:50] if mensagem_texto else f'[{tipo}]'
                }
            )

    # Callbacks quando os grupos recebem mensagens:
    async def chat_message(self, event):
        # Envia para o WebSocket cliente
        await self.send(text_data=json.dumps(event))
        
    async def ticket_updated(self, event):
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def user_can_access_ticket(self, user, ticket_id):
        if not user.is_authenticated: return False
        try:
            from .models import TicketSuporte
            ticket = TicketSuporte.objects.get(id=ticket_id)
            
            # Motorista do ticket acessa sempre (compara User, não Motorista)
            if hasattr(ticket.motorista, 'user') and ticket.motorista.user == user:
                return True
            
            if not hasattr(user, 'motorista_perfil'): return False
            perfil = user.motorista_perfil
            
            # Motorista vinculado ao ticket
            if ticket.motorista == perfil:
                return True
            
            # Se tiver PermissaoUsuario
            if hasattr(perfil, 'permissoes'):
                return perfil.permissoes.pode_acessar_sac or perfil.permissoes.pode_acessar_tickets
                
            # Fallback
            if perfil.tipo_usuario in ['SAC', 'GESTOR']: return True
            if perfil.cargo == 'GESTOR': return True
            
            return False
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False

    @database_sync_to_async
    def user_can_access_filial(self, user, filial_id):
        if not user.is_authenticated: return False
        if not hasattr(user, 'motorista_perfil'): return False
        
        perfil = user.motorista_perfil
        
        # Gestor acessa qualquer filial do suporte? No SAC painel geralmente sim.
        # Mas vamos respeitar a flag de permissao
        if hasattr(perfil, 'permissoes'):
            if not perfil.permissoes.pode_acessar_sac:
                return False
        
        # SAC e GERENTE respeitam a filial do cadastro (ou o Gestor ve tudo?)
        # Baseado no suporte_painel.js, ele passa a filial do config.
        # Se for Gestor, permitimos ver qualquer uma.
        if perfil.cargo == 'GESTOR': return True
        
        # Outros: apenas se for a mesma filial
        return str(perfil.filial_id) == str(filial_id)
        
    @database_sync_to_async
    def get_ticket_filial_id(self, ticket_id):
        try:
            ticket = TicketSuporte.objects.get(id=ticket_id)
            return ticket.filial_id
        except Exception:
            return None

    @database_sync_to_async
    def get_ticket_status(self, ticket_id):
        try:
            ticket = TicketSuporte.objects.get(id=ticket_id)
            return ticket.status
        except Exception:
            return None

    @database_sync_to_async
    def get_user_from_token(self, token_string):
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            from rest_framework_simplejwt.tokens import AccessToken
            token = AccessToken(token_string)
            user_id = token['user_id']
            return User.objects.get(id=user_id)
        except Exception:
            return None

    @database_sync_to_async
    def save_message(self, user, ticket_id, texto, tipo, arquivo_url):
        ticket = TicketSuporte.objects.get(id=ticket_id)
        enviado_por_motorista = False
        atendente = None
        remetente_nome = "Sistema"
        
        if hasattr(user, 'motorista_perfil'):
            if user.motorista_perfil.tipo_usuario == 'MOTORISTA':
                enviado_por_motorista = True
                remetente_nome = user.motorista_perfil.nome_completo
            else:
                atendente = user
                remetente_nome = user.motorista_perfil.nome_completo
                if ticket.status == 'CANAL_ABERTO':
                    ticket.status = 'EM_ATENDIMENTO'
                    ticket.atendente = user
        
        msg = MensagemSuporte.objects.create(
            ticket=ticket,
            enviado_por_motorista=enviado_por_motorista,
            atendente=atendente,
            tipo=tipo,
            texto=texto
        )
        # Note: If arquivo_url is sent from REST and just passed here, you'd handle it.
        # But for Base64 attachments, it's safer to use the REST API ViewSets we created.
        msg.remetente_nome = remetente_nome 
        
        ticket.updated_at = timezone.now()
        ticket.save(update_fields=['updated_at', 'status', 'atendente'])
        
        return msg

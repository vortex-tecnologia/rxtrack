import json
from channels.generic.websocket import AsyncWebsocketConsumer
from core.redis_client import get_redis_client
from django.utils import timezone
from urllib.parse import parse_qs
from channels.db import database_sync_to_async

class MonitoramentoConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # 1. Tenta autenticar via Token na query string (para PWA)
        query_params = parse_qs(self.scope['query_string'].decode())
        token_list = query_params.get('token')
        
        if token_list:
            token_string = token_list[0]
            user = await self.get_user_from_token(token_string)
            if user:
                print(f"💓 [WS] Usuário autenticado via Token: {user.username}")
                self.scope['user'] = user

        # 2. Tenta pegar o filial_id passado na URL
        if 'filial_id' in self.scope['url_route']['kwargs'] and self.scope['url_route']['kwargs']['filial_id']:
            self.filial_id = self.scope['url_route']['kwargs']['filial_id']
        else:
            self.filial_id = 'todas'
            
        self.group_name = f"painel_monitoramento_{self.filial_id}"
        
        print(f"💓 [WS] Conectando ao grupo: {self.group_name}")
        
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    @database_sync_to_async
    def get_user_from_token(self, token_string):
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            from rest_framework_simplejwt.tokens import AccessToken
            token = AccessToken(token_string)
            user_id = token['user_id']
            user = User.objects.get(id=user_id)
            return user
        except Exception as e:
            print(f"❌ [WS] Erro ao decodificar token: {e}")
            return None

    async def disconnect(self, close_code):
        print(f"💓 [WS] Desconectando: {self.group_name}")
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            return

        # Sincronização em tempo real de agrupamento de cards (pilha de manifestos por motorista)
        if data.get('type') == 'toggle_stack':
            mot_id = data.get('motorista_id')
            expanded = data.get('expanded', False)
            targets = ["painel_monitoramento_todas"]
            if hasattr(self, 'filial_id') and self.filial_id and self.filial_id != 'todas':
                targets.append(f"painel_monitoramento_{self.filial_id}")
            targets = list(set(targets))
            for target in targets:
                await self.channel_layer.group_send(
                    target,
                    {
                        "type": "repassar_toggle_stack",
                        "data": {
                            "motorista_id": str(mot_id),
                            "expanded": bool(expanded)
                        }
                    }
                )
            return

        # Lógica de Coração (Heartbeat) do Motorista
        if data.get('type') == 'heartbeat':
            user = self.scope['user']
            if not user or not user.is_authenticated:
                print(f"❌ [WS] Heartbeat recebido mas usuário não autenticado.")
                return

            # Dados do batimento
            lat = data.get('lat')
            lng = data.get('lng')
            battery = data.get('battery')
            manifesto_id = data.get('manifesto_id')
            
            print(f"💓 [WS] Heartbeat de {user.username} - Manifesto: {manifesto_id} - Bat: {battery}%")

            # 1. Salva no Redis (Dados efêmeros para real-time)
            try:
                redis_client = get_redis_client()
                status_key = f"driver_status:{user.id}"
                
                status_data = {
                    'lat': lat,
                    'lng': lng,
                    'battery': battery,
                    'network': data.get('network'),
                    'manifesto_id': manifesto_id,
                    'last_seen': timezone.localtime(timezone.now()).isoformat(),
                    'nome': user.first_name or user.username
                }
                redis_client.set(status_key, json.dumps(status_data), ex=3600)
            except Exception as e:
                print(f"❌ [WS] Erro ao salvar no Redis: {e}")

            # 2. Salva no Banco de Dados (Persistência) e pega a filial
            filial_id = await self.persistir_status_motorista(user, battery, status_data['last_seen'], status_data)

            # 3. Notifica os grupos para atualizar o painel em tempo real
            targets = ["painel_monitoramento_todas"]
            if filial_id:
                targets.append(f"painel_monitoramento_{filial_id}")
            
            targets = list(set(targets)) # Remove duplicatas

            for target in targets:
                # print(f"💓 [WS] Enviando status para o grupo: {target}")
                await self.channel_layer.group_send(
                    target,
                    {
                        "type": "atualizar_status_motorista",
                        "data": {
                            "user_id": user.id,
                            "manifesto_id": manifesto_id,
                            "lat": lat,
                            "lng": lng,
                            "battery": battery,
                            "network": data.get('network'),
                            "last_seen": status_data['last_seen']
                        }
                    }
                )

    @database_sync_to_async
    def persistir_status_motorista(self, user, battery, last_seen_iso, extra_data):
        try:
            from manifesto.models import Manifesto
            from django.utils.dateparse import parse_datetime
            
            manifesto_id = extra_data.get('manifesto_id')
            if not manifesto_id:
                return

            # Busca o manifesto pelo numero_manifesto (que é o que vem no payload)
            try:
                manifesto = Manifesto.objects.get(numero_manifesto=manifesto_id)
                
                if battery is not None:
                    manifesto.ultima_bateria = battery
                
                manifesto.ultimo_acesso = parse_datetime(last_seen_iso)
                manifesto.ultima_rede = extra_data.get('network')
                
                if extra_data.get('lat') and extra_data.get('lng'):
                    manifesto.ultima_lat = extra_data.get('lat')
                    manifesto.ultima_lng = extra_data.get('lng')
                    
                manifesto.save(update_fields=['ultima_bateria', 'ultimo_acesso', 'ultima_rede', 'ultima_lat', 'ultima_lng'])
                # print(f"✅ [WS] Status persistido no Manifesto: {manifesto_id}")
                return manifesto.filial.id if manifesto.filial else None
            except Manifesto.DoesNotExist:
                print(f"⚠️ [WS] Manifesto não encontrado para persistência: {manifesto_id}")
                return None
                
        except Exception as e:
            print(f"❌ [WS] Erro ao persistir no DB: {e}")
            return None

    async def atualizar_painel(self, event):
        conteudo = event["data"]
        await self.send(text_data=json.dumps({
            "dados": conteudo
        }))

    async def atualizar_status_motorista(self, event):
        # Este método recebe a mensagem do group_send e envia via socket para o front
        # print(f"💓 [WS] Propagando status_motorista para o cliente socket")
        await self.send(text_data=json.dumps({
            "type": "status_motorista",
            "dados": event["data"]
        }))

    async def atualizar_cargas(self, event):
        await self.send(text_data=json.dumps({
            "type": "atualizar_cargas",
            "data": event.get("data", {})
        }))

    async def repassar_toggle_stack(self, event):
        await self.send(text_data=json.dumps({
            "type": "toggle_stack",
            "dados": event.get("data", {})
        }))


class CargasFretesConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if 'filial_id' in self.scope['url_route']['kwargs'] and self.scope['url_route']['kwargs']['filial_id']:
            self.filial_id = self.scope['url_route']['kwargs']['filial_id']
        else:
            self.filial_id = 'todas'
            
        self.group_name = f"painel_cargas_fretes_{self.filial_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        if self.group_name != "painel_cargas_fretes_todas":
            await self.channel_layer.group_add("painel_cargas_fretes_todas", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            if self.group_name != "painel_cargas_fretes_todas":
                await self.channel_layer.group_discard("painel_cargas_fretes_todas", self.channel_name)

    async def atualizar_cargas(self, event):
        await self.send(text_data=json.dumps({
            "type": "atualizar_cargas",
            "data": event.get("data", {})
        }))

    async def atualizar_painel(self, event):
        pass

    async def atualizar_status_motorista(self, event):
        pass
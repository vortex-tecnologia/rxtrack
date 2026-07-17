import json
from channels.generic.websocket import AsyncWebsocketConsumer
from configuracao.utils import get_config

class TorreErrosConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Aqui, idealmente haveria autenticação.
        # Por simplicidade e baseado no ManifestoConsumer, aceitamos a conexão e
        # usamos a filial informada na URL.
        self.filial_id = self.scope['url_route']['kwargs'].get('filial_id', 'todas')
        self.group_name = f"torre_erros_{self.filial_id}"
        
        # Verifica se o módulo de torre de erros está ativo
        # No async context, chamar síncrono precisa de sync_to_async, 
        # mas como get_config usa cache, e o cache do django é síncrono, 
        # usaremos sync_to_async.
        from asgiref.sync import sync_to_async
        config = await sync_to_async(get_config)()
        
        modulo_ativo = getattr(config, 'modulo_torre_erros', False)
        if not modulo_ativo:
            await self.close()
            return
            
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def novo_erro(self, event):
        """Envia os dados do novo erro para o WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'novo_erro',
            'dados': event['data']
        }))
        
    async def erro_resolvido(self, event):
        """Envia evento de que um erro foi resolvido"""
        await self.send(text_data=json.dumps({
            'type': 'erro_resolvido',
            'dados': event['data']
        }))

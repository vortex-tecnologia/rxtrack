import json
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from core.redis_client import get_redis_client
from manifesto.models import Manifesto
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

class TrackingHeartbeatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        data = request.data

        lat = data.get('lat')
        lng = data.get('lng')
        battery = data.get('battery')
        network = data.get('network')
        manifesto_id = data.get('manifesto_id')

        if not manifesto_id:
            return Response({'error': 'manifesto_id é obrigatório'}, status=400)

        # 1. Salva no Redis (Dados efêmeros para real-time)
        try:
            redis_client = get_redis_client()
            status_key = f"driver_status:{user.id}"
            
            status_data = {
                'lat': lat,
                'lng': lng,
                'battery': battery,
                'network': network,
                'manifesto_id': manifesto_id,
                'last_seen': timezone.now().isoformat(),
                'nome': user.first_name or user.username
            }
            redis_client.set(status_key, json.dumps(status_data), ex=3600)
        except Exception as e:
            print(f"❌ [REST Tracking] Erro ao salvar no Redis: {e}")
            status_data = {
                'last_seen': timezone.now().isoformat()
            }

        # 2. Salva no Banco de Dados (Persistência)
        manifesto = None
        try:
            manifesto = Manifesto.objects.get(numero_manifesto=manifesto_id)
            if battery is not None:
                manifesto.ultima_bateria = int(battery) if str(battery).isdigit() else None
            
            manifesto.ultimo_acesso = timezone.now()
            manifesto.ultima_rede = network
            
            if lat is not None and lng is not None:
                manifesto.ultima_lat = float(lat)
                manifesto.ultima_lng = float(lng)
                
            manifesto.save(update_fields=['ultima_bateria', 'ultimo_acesso', 'ultima_rede', 'ultima_lat', 'ultima_lng'])
        except Manifesto.DoesNotExist:
            print(f"⚠️ [REST Tracking] Manifesto {manifesto_id} não encontrado.")
        except Exception as e:
            print(f"❌ [REST Tracking] Erro ao persistir no DB: {e}")

        # 3. Notifica o grupo para atualizar o painel em tempo real
        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                targets = []
                if manifesto and manifesto.filial:
                    targets.append(f"painel_monitoramento_{manifesto.filial.id}")
                else:
                    targets.append("painel_monitoramento_todas")
                
                targets.append("painel_monitoramento_todas")
                targets = list(dict.fromkeys(targets))  # Remove duplicatas

                for target in targets:
                    async_to_sync(channel_layer.group_send)(
                        target,
                        {
                            "type": "atualizar_status_motorista",
                            "data": {
                                "user_id": user.id,
                                "manifesto_id": manifesto_id,
                                "lat": lat,
                                "lng": lng,
                                "battery": battery,
                                "network": network,
                                "last_seen": status_data.get('last_seen')
                            }
                        }
                    )
        except Exception as e:
            print(f"❌ [REST Tracking] Erro ao enviar para Channels: {e}")

        return Response({'success': True})

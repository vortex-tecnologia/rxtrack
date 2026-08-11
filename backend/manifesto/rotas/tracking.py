import json
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from core.redis_client import get_redis_client
from manifesto.models import Manifesto
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from rest_framework.permissions import AllowAny
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from usuarios.models import DeviceToken

@method_decorator(csrf_exempt, name='dispatch')
class TrackingHeartbeatView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        user = request.user
        data = request.data

        # Autenticação NATIVA (quando o Plugin Java faz o POST sem Cookies de Sessão)
        if not user.is_authenticated:
            device_token = data.get('device_token')
            if not device_token:
                return Response({'error': 'Acesso negado. Token de dispositivo não fornecido.'}, status=401)
            try:
                dt = DeviceToken.objects.select_related('user').get(token=device_token)
                user = dt.user
            except DeviceToken.DoesNotExist:
                return Response({'error': 'Acesso negado. Token de dispositivo inválido.'}, status=401)

        lat = data.get('lat')
        lng = data.get('lng')
        battery = data.get('battery')
        is_charging = data.get('is_charging', False)
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
                'is_charging': is_charging,
                'network': network,
                'manifesto_id': manifesto_id,
                'last_seen': timezone.localtime(timezone.now()).isoformat(),
                'nome': user.first_name or user.username
            }
            redis_client.set(status_key, json.dumps(status_data), ex=3600)
        except Exception as e:
            print(f"❌ [REST Tracking] Erro ao salvar no Redis: {e}")
            status_data = {
                'last_seen': timezone.localtime(timezone.now()).isoformat()
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
                                "is_charging": is_charging,
                                "network": network,
                                "last_seen": status_data.get('last_seen')
                            }
                        }
                    )
        except Exception as e:
            print(f"❌ [REST Tracking] Erro ao enviar para Channels: {e}")

        print(f"📡 [GPS NATIVO RECEBIDO] Motorista: {user.username} | Lat: {lat}, Lng: {lng} | Manifesto: {manifesto_id}")
        return Response({'success': True})

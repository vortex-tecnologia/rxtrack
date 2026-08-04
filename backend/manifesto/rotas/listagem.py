from rest_framework.views import APIView
from rest_framework.response import Response
from manifesto.models import NotaFiscal
from django.utils.timezone import localtime

class ListarNotasManifestoView(APIView):
    def get(self, request):
        numero = request.query_params.get('numero_manifesto')
        # Filtramos as notas do manifesto específico
        notas = NotaFiscal.objects.filter(manifesto__numero_manifesto=numero).prefetch_related('baixa_info')
        
        # --- TELEMETRIA: Atualiza último sinal do manifesto ---
        from django.utils import timezone
        from manifesto.models import Manifesto
        try:
            mft = Manifesto.objects.filter(numero_manifesto=numero).first()
            if mft:
                mft.ultimo_acesso = timezone.now()
                # Se o app mandar bateria/lat/lng no header ou query, pegamos aqui
                bateria = request.query_params.get('bat')
                lat = request.query_params.get('lat')
                lng = request.query_params.get('lng')
                if bateria: mft.ultima_bateria = int(bateria)
                if lat: mft.ultima_lat = float(lat)
                if lng: mft.ultima_lng = float(lng)
                mft.save(update_fields=['ultimo_acesso', 'ultima_bateria', 'ultima_lat', 'ultima_lng'])
                
                # --- Dispara atualização para a torre ---
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                import json
                
                channel_layer = get_channel_layer()
                if channel_layer:
                    targets = ["painel_monitoramento_todas"]
                    if mft.filial:
                        targets.append(f"painel_monitoramento_{mft.filial.id}")
                    
                    for target in list(set(targets)):
                        async_to_sync(channel_layer.group_send)(
                            target,
                            {
                                "type": "atualizar_status_motorista",
                                "data": {
                                    "user_id": request.user.id,
                                    "manifesto_id": numero,
                                    "lat": lat,
                                    "lng": lng,
                                    "battery": bateria,
                                    "network": None,
                                    "last_seen": timezone.localtime(mft.ultimo_acesso).isoformat() if mft.ultimo_acesso else None
                                }
                            }
                        )
        except Exception as e:
            print(f"Erro ao atualizar telemetria: {e}")
        
        data = []
        for nf in notas:
            # 1. COMO É FOREIGN KEY AGORA: Pegamos a última baixa vinculada a esta nota
            # O .last() resolve o problema da lista e pega o evento mais recente
            baixa = nf.baixa_info.all().last() 
            
            autor_nome = None
            if baixa:
                if baixa.autor_baixa:
                    autor_nome = baixa.autor_baixa.nome_completo
                elif nf.manifesto and nf.manifesto.motorista:
                    autor_nome = nf.manifesto.motorista.nome_completo

            data.append({
                'id': nf.id,
                'numero_nota': nf.numero_nota,
                'chave_acesso': nf.chave_acesso,
                'destinatario': nf.destinatario,
                'endereco_entrega': nf.endereco_entrega,
                'status': nf.status,
                # AQUI ESTÁ A CHAVE: Passando o tipo para o JS validar
                'tipo_operacao': nf.tipo_operacao,
                'id_tms': nf.freight_id_tms,
                'numero_coleta': nf.numero_coleta,
                'ja_baixada': baixa is not None, 
                'dados_baixa': {
                    'tipo': baixa.tipo,
                    # Verificação extra para evitar erro se a ocorrência for nula
                    'ocorrencia': baixa.ocorrencia.descricao if baixa.ocorrencia else "Não informada",
                    'recebedor': baixa.recebedor,
                    'autor': autor_nome,
                    # Formatando a data com o fuso de Brasília (localtime)
                    'data': localtime(baixa.data_baixa).strftime('%d/%m/%Y %H:%M') if baixa.data_baixa else None,
                    'foto_url': baixa.comprovante_foto_url if baixa.comprovante_foto_url else None,
                    'motivo_baixa': baixa.motivo_baixa,
                    'lat': float(baixa.latitude) if baixa.latitude else None,
                    'lng': float(baixa.longitude) if baixa.longitude else None
                } if baixa else None
            })
            
        return Response(data)
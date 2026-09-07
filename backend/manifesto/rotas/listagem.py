from rest_framework.views import APIView
from rest_framework.response import Response
from manifesto.models import NotaFiscal
from django.utils.timezone import localtime

class ListarNotasManifestoView(APIView):
    def get(self, request):
        numero = request.query_params.get('numero_manifesto')
        # Filtramos as notas do manifesto específico com prefetch dos relacionamentos
        notas = NotaFiscal.objects.filter(
            manifesto__numero_manifesto=numero
        ).select_related(
            'manifesto', 'manifesto__motorista', 'frete'
        ).prefetch_related(
            'baixa_info', 'baixa_info__ocorrencia', 'baixa_info__autor_baixa'
        )
        
        # --- TELEMETRIA: Atualiza último sinal do manifesto ---
        from django.utils import timezone
        from manifesto.models import Manifesto
        try:
            mft = Manifesto.objects.select_related('filial', 'veiculo').filter(numero_manifesto=numero).first()
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
                                    "user_id": request.user.id if request.user and request.user.is_authenticated else None,
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
        
        def safe_float(val):
            if val is None:
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        data = []
        for nf in notas:
            # 1. Pegamos a última baixa vinculada a esta nota
            baixa = nf.baixa_info.all().last() 
            
            # 🔍 VERIFICAÇÃO NOTA A NOTA DA ANÁLISE PENDENTE DA IA
            if baixa and baixa.qualidade_canhoto == 'PENDENTE_ANALISE':
                oc_cod = str(getattr(baixa.ocorrencia, 'codigo_tms', '') or getattr(baixa.ocorrencia, 'codigo_referencia', '') or '').strip() if baixa.ocorrencia else ''
                is_01 = oc_cod in ['01', '1', '001'] or (baixa.tipo == 'ENTREGA' and not baixa.ocorrencia)
                tem_foto = bool(baixa.comprovante_foto_url)
                is_coleta = (baixa.tipo == 'COLETA' or getattr(nf, 'tipo_operacao', '') == 'COLETA')
                is_ret = bool(baixa.observacao and 'retid' in baixa.observacao.lower())

                # Regra: SOMENTE 01 COM FOTO vai para IA. Qualquer outra ocorrência ou sem foto é liberada imediatamente.
                if not is_01 or not tem_foto or is_coleta or is_ret:
                    baixa.qualidade_canhoto = 'APROVADO'
                    baixa.solicitar_nova_foto = False
                    baixa.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])
                    if not baixa.integrado_tms:
                        try:
                            from AgenteIa.tasks import finalizar_fluxo_tms
                            finalizar_fluxo_tms(baixa)
                        except Exception:
                            pass

            autor_nome = None
            if baixa:
                try:
                    if baixa.autor_baixa:
                        autor_nome = getattr(baixa.autor_baixa, 'nome_completo', None) or str(baixa.autor_baixa)
                    elif nf.manifesto and nf.manifesto.motorista:
                        autor_nome = getattr(nf.manifesto.motorista, 'nome_completo', None)
                except Exception:
                    pass

            dados_baixa = None
            if baixa:
                ocorrencia_desc = "Não informada"
                try:
                    if baixa.ocorrencia:
                        ocorrencia_desc = baixa.ocorrencia.descricao
                except Exception:
                    pass

                oc_cod = str(getattr(baixa.ocorrencia, 'codigo_tms', '') or getattr(baixa.ocorrencia, 'codigo_referencia', '') or '').strip() if baixa.ocorrencia else ''
                is_ret = bool(baixa.observacao and 'retid' in baixa.observacao.lower())

                dados_baixa = {
                    'tipo': baixa.tipo,
                    'ocorrencia': ocorrencia_desc,
                    'ocorrencia_codigo': oc_cod,
                    'is_retida': is_ret,
                    'recebedor': baixa.recebedor,
                    'autor': autor_nome,
                    'data': localtime(baixa.data_baixa).strftime('%d/%m/%Y %H:%M') if baixa.data_baixa else None,
                    'foto_url': baixa.comprovante_foto_url if baixa.comprovante_foto_url else None,
                    'motivo_baixa': baixa.motivo_baixa,
                    'lat': safe_float(baixa.latitude),
                    'lng': safe_float(baixa.longitude),
                    'solicitar_nova_foto': getattr(baixa, 'solicitar_nova_foto', False),
                    'tentativa_foto': getattr(baixa, 'tentativa_foto', 1),
                    'qualidade_canhoto': getattr(baixa, 'qualidade_canhoto', 'APROVADO'),
                    'motivo_rejeicao_ia': getattr(baixa, 'motivo_rejeicao_ia', None),
                }

            cte_num = nf.numero_cte or (nf.frete.numero_cte if nf.frete else None)
            freight_id_val = nf.freight_id_tms or (nf.frete.freight_id_tms if nf.frete else None)

            data.append({
                'id': nf.id,
                'numero_nota': nf.numero_nota,
                'chave_acesso': nf.chave_acesso,
                'destinatario': nf.destinatario,
                'endereco_entrega': nf.endereco_entrega,
                'status': nf.status,
                'tipo_operacao': nf.tipo_operacao,
                'numero_cte': cte_num,
                'id_tms': freight_id_val,
                'numero_coleta': nf.numero_coleta,
                'ja_baixada': baixa is not None,
                'solicitar_nova_foto': getattr(baixa, 'solicitar_nova_foto', False) if baixa else False,
                'tentativa_foto': getattr(baixa, 'tentativa_foto', 1) if baixa else 1,
                'cep': nf.cep,
                'latitude': safe_float(nf.latitude),
                'longitude': safe_float(nf.longitude),
                'qualidade_canhoto': getattr(baixa, 'qualidade_canhoto', 'APROVADO') if baixa else 'APROVADO',
                'dados_baixa': dados_baixa
            })

        # === METADADOS DO MANIFESTO (status TMS, WhatsApp, Veículo) ===
        meta_manifesto = {}
        if mft:
            # 🏁 Avalia se o manifesto já pode ser finalizado automaticamente
            if mft.status == 'EM_TRANSPORTE' and not mft.finalizado:
                total_mft = len(notas)
                if total_mft > 0 and not any(n.status == 'PENDENTE' for n in notas):
                    try:
                        from manifesto.services import tentar_autofinalizar_manifesto
                        sucesso_auto, _ = tentar_autofinalizar_manifesto(mft)
                        if sucesso_auto:
                            mft.refresh_from_db()
                    except Exception as e_auto:
                        pass

            meta_manifesto['status'] = mft.status
            meta_manifesto['finalizado'] = mft.finalizado
            meta_manifesto['status_tms'] = getattr(mft, 'status_tms', 'in_transit')
            meta_manifesto['placa_veiculo'] = mft.veiculo.placa if mft.veiculo else None
            if mft.filial:
                meta_manifesto['whatsapp_operacional'] = mft.filial.whatsapp_operacional_completo
                meta_manifesto['nome_filial'] = mft.filial.nome
            else:
                meta_manifesto['whatsapp_operacional'] = None
                meta_manifesto['nome_filial'] = None

        return Response({
            'notas': data,
            'manifesto': meta_manifesto,
        })
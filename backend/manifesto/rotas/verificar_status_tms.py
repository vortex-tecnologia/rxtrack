# manifesto/rotas/verificar_status_tms.py
import logging
import json
import requests
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from manifesto.models import Manifesto
from integracoes.registry import get_tms_adapter

logger = logging.getLogger(__name__)


class VerificarStatusTmsView(APIView):
    """
    Endpoint para re-checagem dinâmica do status do manifesto no TMS.
    Usado pelo app quando o motorista tenta dar baixa e o manifesto está pendente.
    Se o status mudou para in_transit, atualiza no banco local.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        numero = request.query_params.get('numero_manifesto')
        if not numero:
            return Response({'erro': 'Número do manifesto é obrigatório.'}, status=400)

        try:
            manifesto = Manifesto.objects.select_related('filial').filter(
                numero_manifesto=numero
            ).first()

            if not manifesto:
                return Response({'erro': 'Manifesto não encontrado no banco local.'}, status=404)

            # Busca status atualizado no TMS
            adapter = get_tms_adapter()
            if not adapter:
                return Response({
                    'status_tms': manifesto.status_tms,
                    'atualizado': False,
                    'mensagem': 'Integração TMS desativada.'
                })

            config = adapter.config
            token = config.token_analytics
            dominio = config.dominio_esl
            report_id = config.report_validacao

            url = f"https://{dominio}/api/analytics/reports/{report_id}/data"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            }
            payload = {
                "search": {
                    "manifests": {
                        "sequence_code": int(numero),
                        "service_date": "2024-01-01 - 2050-12-31"
                    }
                },
                "page": "1", "per": "10"
            }

            res = requests.get(url, headers=headers, data=json.dumps(payload), timeout=20)
            res.raise_for_status()
            dados = res.json()

            if not dados:
                return Response({
                    'status_tms': manifesto.status_tms,
                    'atualizado': False,
                    'mensagem': 'Manifesto não encontrado no TMS.'
                })

            info_tms = dados[0]
            novo_status = str(info_tms.get('status', '')).strip().lower()

            logger.info(f"[RE-CHECK STATUS] Manifesto {numero}: status TMS = '{novo_status}' (antes: '{manifesto.status_tms}')")

            atualizado = False
            if novo_status != manifesto.status_tms and novo_status in ('pending', 'in_transit', 'closed'):
                manifesto.status_tms = novo_status
                manifesto.save(update_fields=['status_tms'])
                atualizado = True
                logger.info(f"✅ Status TMS do manifesto {numero} atualizado para '{novo_status}'")

            # Dados da filial para WhatsApp
            whatsapp_operacional = None
            nome_filial = None
            if manifesto.filial:
                whatsapp_operacional = manifesto.filial.whatsapp_operacional_completo
                nome_filial = manifesto.filial.nome

            return Response({
                'status_tms': novo_status,
                'atualizado': atualizado,
                'whatsapp_operacional': whatsapp_operacional,
                'nome_filial': nome_filial,
            })

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro de comunicação com TMS ao verificar status: {e}")
            return Response({
                'status_tms': manifesto.status_tms if manifesto else 'unknown',
                'atualizado': False,
                'erro': 'Falha de comunicação com o TMS. Tente novamente.'
            }, status=503)
        except Exception as e:
            logger.error(f"Erro ao verificar status TMS: {e}")
            return Response({'erro': str(e)}, status=500)

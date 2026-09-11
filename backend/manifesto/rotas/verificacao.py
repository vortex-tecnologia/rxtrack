from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from manifesto.models import Manifesto
from django.db import transaction

class VerificarManifestoAtivoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        motorista = getattr(request.user, 'motorista_perfil', None)
        if not motorista:
            return Response({'tem_manifesto': False})

        with transaction.atomic():
            # Busca se existe algum manifesto com status 'EM_TRANSPORTE' e NÃO finalizado
            manifesto_ativo = Manifesto.objects.filter(
                motorista=motorista, 
                status='EM_TRANSPORTE',
                finalizado=False
            ).first()

            if not manifesto_ativo:
                # Se não há manifesto ativo em transporte, busca manifestos em 'AGUARDANDO' para o motorista
                from django.utils import timezone
                from datetime import timedelta
                limite_48h = timezone.now() - timedelta(hours=48)

                manifestos_pendentes = Manifesto.objects.filter(
                    motorista=motorista,
                    status='AGUARDANDO'
                ).order_by('data_criacao')

                for m_pend in manifestos_pendentes:
                    if m_pend.data_criacao and m_pend.data_criacao < limite_48h:
                        # Expirado há mais de 48h: cancela imediatamente e notifica Torre
                        m_pend.status = 'CANCELADO'
                        m_pend.finalizado = True
                        m_pend.data_finalizacao = timezone.now()
                        m_pend.save(update_fields=['status', 'finalizado', 'data_finalizacao'])
                        try:
                            from manifesto.services import enviar_painel
                            enviar_painel(m_pend)
                        except Exception:
                            pass
                    else:
                        # Manifesto recente válido (< 48h): promove para EM_TRANSPORTE
                        m_pend.status = 'EM_TRANSPORTE'
                        m_pend.finalizado = False
                        m_pend.save(update_fields=['status', 'finalizado'])
                        manifesto_ativo = m_pend
                        break

            if manifesto_ativo:
                return Response({
                    'tem_manifesto': True,
                    'numero_manifesto': manifesto_ativo.numero_manifesto
                })

        return Response({'tem_manifesto': False})
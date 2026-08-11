# manifesto/rotas/sincronizarmanifesto.py
from rest_framework import views, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.db import transaction
from manifesto.models import ManifestoBuscaLog, Manifesto
from manifesto.tasks import buscar_manifesto_completo_task
from usuarios.models import Motorista

class SincronizarManifestoView(views.APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        numero_manifesto = request.data.get('numero_manifesto')
        
        if not numero_manifesto:
            return Response({"erro": "Número do manifesto é obrigatório"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Normalização para batimento flexível (zeros à esquerda)
            numero_limpo = str(numero_manifesto).strip().lstrip('0')

            with transaction.atomic():
                # 1. Busca o motorista associado ao usuário logado
                try:
                    motorista = Motorista.objects.select_related('user').get(user=request.user)
                except Motorista.DoesNotExist:
                    return Response({"erro": "Perfil de motorista não encontrado para este usuário."}, status=403)

                # 2. VERIFICAÇÃO LOCAL (Prioridade para manifestos recebidos via Webhook)
                manifesto_local = Manifesto.objects.filter(
                    numero_manifesto=numero_manifesto, 
                    status='AGUARDANDO'
                ).first()

                if not manifesto_local and numero_limpo:
                    manifesto_local = Manifesto.objects.filter(
                        numero_manifesto=numero_limpo,
                        status='AGUARDANDO'
                    ).first()

                if manifesto_local:
                    # Verifica se o motorista já possui um manifesto em transporte
                    if Manifesto.objects.filter(motorista=motorista, status='EM_TRANSPORTE').exists():
                        return Response({
                            "erro": "Você já possui um manifesto em transporte ativo. Finalize-o antes de iniciar um novo."
                        }, status=status.HTTP_400_BAD_REQUEST)

                    # Ativa o manifesto local
                    manifesto_local.motorista = motorista
                    manifesto_local.status = 'EM_TRANSPORTE'
                    manifesto_local.save()

                    # Atualiza o log como PROCESSADO
                    ManifestoBuscaLog.objects.update_or_create(
                        numero_manifesto=numero_manifesto,
                        motorista=motorista,
                        defaults={'status': 'PROCESSADO', 'mensagem_erro': None}
                    )

                    return Response({
                        "mensagem": "Manifesto localizado e ativado com sucesso!",
                        "status": "PROCESSADO",
                        "local": True
                    }, status=status.HTTP_200_OK)

                # 3. FALLBACK: Sincronização externa com TMS
                log, created = ManifestoBuscaLog.objects.update_or_create(
                    numero_manifesto=numero_manifesto,
                    motorista=motorista,
                    defaults={'status': 'AGUARDANDO', 'mensagem_erro': None}
                )

                # Disparamos a Task no Celery
                buscar_manifesto_completo_task.delay(log.id)

                return Response({
                    "mensagem": "Sincronização iniciada com o TMS. Verifique as notas em alguns instantes.",
                    "status": log.status,
                    "local": False
                }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            return Response({"erro": f"Falha ao processar sincronização: {str(e)}"}, status=500)

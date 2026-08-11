# manifesto/rotas/busca.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from usuarios.models import Motorista, Filial
from manifesto.models import ManifestoBuscaLog, Manifesto
from manifesto.tasks import buscar_manifesto_completo_task
import logging

logger = logging.getLogger(__name__)

class BuscarManifestoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            motorista = getattr(request.user, 'motorista_perfil', None)
            if not motorista:
                logger.warning(f"Usuário {request.user.username} não possui motorista_perfil vinculado.")
                return Response({'erro': 'Seu usuário não possui um perfil de motorista vinculado.'}, status=403)

            numero = request.data.get('numero_manifesto')
            if not numero:
                return Response({'erro': 'Número do manifesto é obrigatório'}, status=400)

            # Normalização simples: remove zeros à esquerda para batimento flexível
            numero_limpo = str(numero).strip().lstrip('0')

            with transaction.atomic():
                # 1. VERIFICAÇÃO LOCAL (Prioridade para manifestos recebidos via Webhook)
                # Tenta busca exata e depois busca normalizada
                manifesto_local = Manifesto.objects.filter(
                    numero_manifesto=numero, 
                    status='AGUARDANDO'
                ).first()

                if not manifesto_local and numero_limpo:
                    manifesto_local = Manifesto.objects.filter(
                        numero_manifesto=numero_limpo,
                        status='AGUARDANDO'
                    ).first()

                if manifesto_local:
                    # Verifica se o motorista já possui um manifesto em transporte (regra de 1 ativo)
                    if Manifesto.objects.filter(motorista=motorista, status='EM_TRANSPORTE').exists():
                        return Response({
                            "erro": "Você já possui um manifesto em transporte ativo. Finalize-o antes de iniciar um novo."
                        }, status=400)

                    # Ativa o manifesto local para este motorista
                    manifesto_local.motorista = motorista
                    manifesto_local.status = 'EM_TRANSPORTE'
                    manifesto_local.save()

                    # Cria ou atualiza o log de busca como PROCESSADO
                    log, _ = ManifestoBuscaLog.objects.update_or_create(
                        numero_manifesto=numero,
                        motorista=motorista,
                        defaults={'status': 'PROCESSADO', 'mensagem_erro': None}
                    )

                    logger.info(f"PWA: Manifesto {numero} ativado via busca LOCAL (Webhook). ID Log={log.id}")
                    return Response({
                        "mensagem": "Manifesto localizado e ativado com sucesso!",
                        "status": "PROCESSADO",
                        "local": True
                    }, status=200)

                # 2. FALLBACK: Sincronização externa com TMS (Lógica atual)
                log, created = ManifestoBuscaLog.objects.update_or_create(
                    numero_manifesto=numero,
                    motorista=motorista,
                    defaults={
                        'status': 'AGUARDANDO',
                        'mensagem_erro': None,
                        'payload': None
                    }
                )
                logger.info(f"PWA: Log {'criado' if created else 'atualizado'} para manifesto {numero}. ID={log.id}")
                buscar_manifesto_completo_task.delay(log.id)

                return Response({'status': 'AGUARDANDO', 'log_id': log.id, 'local': False}, status=202)

        except Exception as e:
            logger.error(f"Erro na BuscarManifestoView (PWA): {str(e)}")
            return Response({'erro': str(e)}, status=500)

class ImportarManifestoAdminView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        numero = request.data.get('numero_manifesto')
        motorista_id = request.data.get('motorista_id')

        logger.info(f"ADMIN: Requisição de importação: manifesto={numero}, motorista={motorista_id}")

        if not numero or not motorista_id:
            return Response({'erro': 'Número do manifesto e motorista são obrigatórios'}, status=400)

        try:
            motorista = Motorista.objects.get(id=motorista_id)
            
            # Verificar se motorista já tem manifesto ativo
            if Manifesto.objects.filter(motorista=motorista, status='EM_TRANSPORTE').exists():
                return Response({'erro': 'Este motorista já possui um manifesto em transporte ativo.'}, status=400)

            # Criar ou atualizar log de busca
            log, _ = ManifestoBuscaLog.objects.update_or_create(
                numero_manifesto=numero,
                motorista=motorista,
                defaults={
                    'status': 'AGUARDANDO',
                    'mensagem_erro': None
                }
            )

            # Disparar Task Celery (apenas log_id conforme assinatura da task)
            buscar_manifesto_completo_task.delay(log.id)

            return Response({
                'status': 'AGUARDANDO', 
                'log_id': log.id,
                'mensagem': 'Importação iniciada com sucesso!'
            }, status=202)

        except Motorista.DoesNotExist:
            return Response({'erro': 'Motorista não encontrado'}, status=404)
        except Exception as e:
            logger.error(f"Erro na importação admin: {str(e)}")
            return Response({'erro': str(e)}, status=500)

class CheckImportStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, log_id):
        try:
            log = ManifestoBuscaLog.objects.get(id=log_id)
            return Response({
                'status': log.status,
                'mensagem_erro': log.mensagem_erro
            })
        except ManifestoBuscaLog.DoesNotExist:
            return Response({'erro': 'Log não encontrado'}, status=404)

class ListarTodosLogsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logs = ManifestoBuscaLog.objects.select_related('motorista').all().order_by('-atualizado_em')
        data = []
        for log in logs:
            data.append({
                'id': log.id,
                'data': log.criado_em.strftime('%d/%m/%Y %H:%M'),
                'numero': log.numero_manifesto,
                'motorista': log.motorista.nome_completo if log.motorista else "N/A",
                'status': log.status,
                'quantidade_notas': log.quantidade_notas,
                'erro': log.mensagem_erro
            })
        return Response(data)
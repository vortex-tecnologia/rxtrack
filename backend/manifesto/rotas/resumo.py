# manifesto/rotas/resumo.py
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authtoken.models import Token
from django.db.models import Q
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiResponse

from manifesto.models import Manifesto, NotaFiscal

logger = logging.getLogger(__name__)


class ResumoManifestoPermission(BasePermission):
    """
    Permite acesso se:
    1. O usuário já estiver autenticado via Token, JWT ou Session.
    2. Foi fornecido um token válido no header 'Authorization: Token <token>'.
    3. Foi fornecido um token no header 'X-API-KEY: <token>'.
    4. Foi fornecido um token no query param '?token=<token>' ou '?api_key=<token>'.
    """
    def has_permission(self, request, view):
        # 1. Autenticado pelo DRF (JWT, Token, Session)
        if request.user and request.user.is_authenticated:
            return True

        # 2. Token via Header Authorization: Token <key>
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Token "):
            token_key = auth.replace("Token ", "").strip()
            if Token.objects.filter(key=token_key).exists():
                return True

        # 3. Token via Header X-API-KEY
        x_api_key = request.headers.get("X-API-KEY", "").strip()
        if x_api_key and Token.objects.filter(key=x_api_key).exists():
            return True

        # 4. Token via Query Param (?token=... ou ?api_key=...)
        token_param = (request.query_params.get("token") or request.query_params.get("api_key") or "").strip()
        if token_param and Token.objects.filter(key=token_param).exists():
            return True

        return False


class ManifestoResumoView(APIView):
    """
    Rota consolidada para consulta de status e conferência de paradas respondidas
    em um manifesto. Desenvolvida especialmente para apuração de bônus de motoristas.
    """
    authentication_classes = [TokenAuthentication, JWTAuthentication, SessionAuthentication]
    permission_classes = [ResumoManifestoPermission]

    @extend_schema(
        tags=['Manifestos'],
        summary="Resumo de Status e Paradas do Manifesto (Bônus)",
        description=(
            "Retorna o status do manifesto, total de rotas (notas + coletas), "
            "quantidade de itens respondidos no app e quantidade de pendências (faltas)."
        ),
        parameters=[
            OpenApiParameter(
                name="numero_manifesto",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Número do manifesto a consultar"
            )
        ],
        responses={
            200: OpenApiResponse(description="Resumo do manifesto gerado com sucesso"),
            400: OpenApiResponse(description="Número do manifesto não informado"),
            401: OpenApiResponse(description="Não autorizado / Token inválido"),
            404: OpenApiResponse(description="Manifesto não encontrado")
        }
    )
    def get(self, request, numero_manifesto=None):
        return self._processar_resumo(request, numero_manifesto)

    @extend_schema(
        tags=['Manifestos'],
        summary="Resumo de Status e Paradas do Manifesto via POST",
        description="Mesma lógica do GET, aceitando o número do manifesto no corpo JSON.",
        request=OpenApiTypes.OBJECT,
        responses={
            200: OpenApiResponse(description="Resumo retornado com sucesso"),
            400: OpenApiResponse(description="Número do manifesto não informado"),
            404: OpenApiResponse(description="Manifesto não encontrado")
        }
    )
    def post(self, request, numero_manifesto=None):
        return self._processar_resumo(request, numero_manifesto)

    def _processar_resumo(self, request, numero_manifesto=None):
        # 1. Obtém o número do manifesto (URL kwarg, query params ou payload POST)
        numero = (
            numero_manifesto
            or request.query_params.get('numero_manifesto')
            or request.query_params.get('numero')
            or request.query_params.get('manifesto')
            or (request.data.get('numero_manifesto') if isinstance(request.data, dict) else None)
        )

        if not numero:
            return Response({
                "sucesso": False,
                "erro": "Número do manifesto não informado. Envie o parâmetro 'numero_manifesto'."
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. Normalização: busca com e sem zeros à esquerda
        numero_str = str(numero).strip()
        numero_limpo = numero_str.lstrip('0')
        numeros_busca = [numero_str]
        if numero_limpo and numero_limpo != numero_str:
            numeros_busca.append(numero_limpo)

        # 3. Busca no banco
        manifesto = Manifesto.objects.select_related(
            'motorista', 'veiculo', 'filial'
        ).filter(
            numero_manifesto__in=numeros_busca
        ).first()

        if not manifesto:
            return Response({
                "sucesso": False,
                "erro": f"Manifesto '{numero_str}' não encontrado no sistema."
            }, status=status.HTTP_404_NOT_FOUND)

        # 4. Consulta todas as notas e coletas vinculadas
        notas_qs = NotaFiscal.objects.filter(manifesto=manifesto).prefetch_related('baixa_info')

        # Condição de resposta: tem baixa registrada ou status BAIXADA/OCORRENCIA
        cond_respondida = Q(status__in=['BAIXADA', 'OCORRENCIA']) | Q(baixa_info__isnull=False)
        cond_pendente = Q(status='PENDENTE', baixa_info__isnull=True)

        # Totais gerais (rotas = notas + coletas)
        total_rotas = notas_qs.count()
        total_respondidas = notas_qs.filter(cond_respondida).distinct().count()
        total_pendentes = notas_qs.filter(cond_pendente).count()

        # Detalhamento: Coletas vs Notas (Entregas / Despacho / Transferência / etc.)
        coletas_qs = notas_qs.filter(tipo_operacao='COLETA')
        notas_entrega_qs = notas_qs.exclude(tipo_operacao='COLETA')

        coletas_total = coletas_qs.count()
        coletas_respondidas = coletas_qs.filter(cond_respondida).distinct().count()
        coletas_pendentes = coletas_qs.filter(cond_pendente).count()

        notas_total = notas_entrega_qs.count()
        notas_respondidas = notas_entrega_qs.filter(cond_respondida).distinct().count()
        notas_pendentes = notas_entrega_qs.filter(cond_pendente).count()

        # Lista de itens não respondidos (para auditoria do bônus)
        itens_pendentes = []
        for nf in notas_qs.filter(cond_pendente).order_by('id'):
            itens_pendentes.append({
                "id": nf.id,
                "tipo": nf.tipo_operacao or "ENTREGA",
                "numero": nf.numero_coleta if nf.tipo_operacao == 'COLETA' else nf.numero_nota,
                "chave_acesso": nf.chave_acesso,
                "destinatario": nf.destinatario or "NÃO INFORMADO",
                "endereco": nf.endereco_entrega or "NÃO INFORMADO"
            })

        # Flags de status
        finalizado = bool(manifesto.finalizado or manifesto.status == 'FINALIZADO')
        todas_respondidas = bool(total_pendentes == 0 and total_rotas > 0)
        finalizado_com_pendencias = bool(finalizado and total_pendentes > 0)

        # Dados do motorista
        motorista_dados = None
        if manifesto.motorista:
            motorista_dados = {
                "id": manifesto.motorista.id,
                "nome": manifesto.motorista.nome_completo,
                "cpf": manifesto.motorista.cpf,
                "categoria": getattr(manifesto.motorista, 'categoria', None)
            }

        return Response({
            "sucesso": True,
            "numero_manifesto": manifesto.numero_manifesto,
            "status_manifesto": manifesto.status,
            "finalizado": finalizado,
            "status_tms": getattr(manifesto, 'status_tms', 'in_transit'),
            "motorista": motorista_dados,
            "placa_veiculo": manifesto.veiculo.placa if manifesto.veiculo else None,
            "filial": manifesto.filial.nome if manifesto.filial else None,
            "data_criacao": manifesto.data_criacao.isoformat() if manifesto.data_criacao else None,
            "data_finalizacao": manifesto.data_finalizacao.isoformat() if manifesto.data_finalizacao else None,

            # Métricas principais para o cálculo do bônus
            "total_rotas": total_rotas,
            "total_respondidas": total_respondidas,
            "total_pendentes": total_pendentes,
            "todas_respondidas": todas_respondidas,
            "finalizado_com_pendencias": finalizado_com_pendencias,

            # Detalhamento por categoria
            "detalhamento": {
                "notas_total": notas_total,
                "notas_respondidas": notas_respondidas,
                "notas_pendentes": notas_pendentes,
                "coletas_total": coletas_total,
                "coletas_respondidas": coletas_respondidas,
                "coletas_pendentes": coletas_pendentes,
            },

            # Lista dos itens pendentes (faltas)
            "itens_pendentes": itens_pendentes
        }, status=status.HTTP_200_OK)

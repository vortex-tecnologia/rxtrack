import logging
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authtoken.models import Token
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiExample, OpenApiResponse

from manifesto.models import WebhookTokenControl, Manifesto, NotaFiscal, BaixaNF, Ocorrencia

logger = logging.getLogger(__name__)

# --- Helper de Autenticação ---
def valida_token_tms(request):
    """
    Função base para validar o token enviado pelo TMS, registrar uso 
    e garantir a cobrança (identico ao webhook principal).
    """
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Token "):
        return False, Response({"detail": "Token não informado. Envie o header 'Authorization: Token SEU_TOKEN'."}, status=status.HTTP_401_UNAUTHORIZED)
    
    token_key = auth.replace("Token ", "")
    try:
        token_obj = Token.objects.select_related('user').get(key=token_key)
        user = token_obj.user
    except Token.DoesNotExist:
        return False, Response({"detail": "Token inválido ou não encontrado."}, status=status.HTTP_401_UNAUTHORIZED)
    
    control, created = WebhookTokenControl.objects.get_or_create(
        user=user,
        defaults={'mes_referencia': timezone.now().date().replace(day=1)}
    )
    
    if not control.ativo:
        return False, Response({"detail": "Seu token de acesso foi desativado. Contate o suporte."}, status=status.HTTP_403_FORBIDDEN)
        
    control.reset_if_new_month()
    control.total_mes_atual += 1
    control.save()
    
    return True, None

# ==========================================
# GRUPO 1: MANIFESTOS
# ==========================================

@extend_schema(
    tags=['Manifestos'],
    summary="Inicia Transporte",
    description="Coloca um manifesto em rota, alterando seu status para 'EM_TRANSPORTE'.",
    request=OpenApiTypes.OBJECT,
    examples=[
        OpenApiExample(
            "Exemplo", 
            value={"numero_manifesto": "12345"}, 
            request_only=True
        )
    ],
    responses={
        200: OpenApiResponse(description="Manifesto iniciado com sucesso"),
        400: OpenApiResponse(description="Dados incompletos"),
        404: OpenApiResponse(description="Manifesto não encontrado")
    }
)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def iniciar_transporte_tms(request):
    valido, erro_response = valida_token_tms(request)
    if not valido: return erro_response

    numero_manifesto = request.data.get('numero_manifesto')
    if not numero_manifesto:
        return Response({"erro": "numero_manifesto é obrigatório"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        manifesto = Manifesto.objects.get(numero_manifesto=numero_manifesto)
        manifesto.status = 'EM_TRANSPORTE'
        manifesto.save()
        return Response({"sucesso": True, "mensagem": f"Manifesto {numero_manifesto} agora está EM_TRANSPORTE."})
    except Manifesto.DoesNotExist:
        return Response({"erro": f"Manifesto {numero_manifesto} não encontrado."}, status=status.HTTP_404_NOT_FOUND)


@extend_schema(
    tags=['Manifestos'],
    summary="Adiciona Nota a um manifesto",
    description="Vincula uma nova NF-e a um manifesto já existente. Retorna erro se o manifesto não existir.",
    request=OpenApiTypes.OBJECT,
    examples=[
        OpenApiExample(
            "Exemplo Payload", 
            value={
                "numero_manifesto": "12345",
                "numero_nota": "555666",
                "chave_acesso": "35230111111111111111550010000123451000123456",
                "destinatario": "EMPRESA ABC",
                "endereco_entrega": "RUA DAS FLORES 123 - CENTRO",
                "tipo_operacao": "ENTREGA"
            }, 
            request_only=True
        )
    ],
    responses={
        201: OpenApiResponse(description="Nota criada com sucesso"),
        400: OpenApiResponse(description="Faltam campos obrigatórios"),
        404: OpenApiResponse(description="Manifesto não encontrado")
    }
)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def adicionar_nota_manifesto_tms(request):
    valido, erro_response = valida_token_tms(request)
    if not valido: return erro_response

    numero_manifesto = request.data.get('numero_manifesto')
    numero_nota = request.data.get('numero_nota')
    chave_acesso = request.data.get('chave_acesso', '')
    destinatario = request.data.get('destinatario', 'NÃO INFORMADO')
    endereco_entrega = request.data.get('endereco_entrega', 'NÃO INFORMADO')
    tipo_operacao = request.data.get('tipo_operacao', 'ENTREGA')

    if not numero_manifesto or not numero_nota:
        return Response({"erro": "numero_manifesto e numero_nota são obrigatórios"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        manifesto = Manifesto.objects.get(numero_manifesto=numero_manifesto)
    except Manifesto.DoesNotExist:
        return Response({"erro": f"Manifesto {numero_manifesto} não encontrado. Uma nota precisa de um manifesto."}, status=status.HTTP_404_NOT_FOUND)

    nota, created = NotaFiscal.objects.get_or_create(
        manifesto=manifesto,
        numero_nota=numero_nota,
        defaults={
            'chave_acesso': chave_acesso,
            'destinatario': destinatario,
            'endereco_entrega': endereco_entrega,
            'tipo_operacao': tipo_operacao,
            'status': 'PENDENTE'
        }
    )
    
    msg = "Nota cadastrada com sucesso." if created else "Nota já existia neste manifesto."
    return Response({"sucesso": True, "mensagem": msg}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@extend_schema(
    tags=['Manifestos'],
    summary="Finaliza um manifesto",
    description="Encerra o manifesto, mudando o status para 'FINALIZADO' e registrando a data/hora.",
    request=OpenApiTypes.OBJECT,
    examples=[
        OpenApiExample(
            "Exemplo Payload", 
            value={"numero_manifesto": "12345"}, 
            request_only=True
        )
    ],
    responses={
        200: OpenApiResponse(description="Manifesto finalizado com sucesso"),
        404: OpenApiResponse(description="Manifesto não encontrado")
    }
)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def finalizar_manifesto_tms(request):
    valido, erro_response = valida_token_tms(request)
    if not valido: return erro_response

    numero_manifesto = request.data.get('numero_manifesto')
    if not numero_manifesto:
        return Response({"erro": "numero_manifesto é obrigatório"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        manifesto = Manifesto.objects.get(numero_manifesto=numero_manifesto)
        manifesto.status = 'FINALIZADO'
        manifesto.finalizado = True
        manifesto.data_finalizacao = timezone.now()
        manifesto.save()
        return Response({"sucesso": True, "mensagem": f"Manifesto {numero_manifesto} FINALIZADO com sucesso."})
    except Manifesto.DoesNotExist:
        return Response({"erro": f"Manifesto {numero_manifesto} não encontrado."}, status=status.HTTP_404_NOT_FOUND)


# ==========================================
# GRUPO 2: NOTAS FISCAIS
# ==========================================

@extend_schema(
    tags=['Notas Fiscais'],
    summary="Registra nota em um manifesto",
    description="Vincula uma nova NF-e a um manifesto. Faz a exata mesma função do endpoint 'Adiciona Nota' acima.",
    request=OpenApiTypes.OBJECT,
    examples=[
        OpenApiExample(
            "Exemplo Payload", 
            value={
                "numero_manifesto": "12345",
                "numero_nota": "555666",
                "chave_acesso": "35230111111111111111550010000123451000123456",
                "destinatario": "EMPRESA ABC",
                "endereco_entrega": "RUA DAS FLORES 123",
                "tipo_operacao": "ENTREGA"
            }, 
            request_only=True
        )
    ],
    responses={
        201: OpenApiResponse(description="Nota registrada com sucesso")
    }
)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def registrar_nota_tms(request):
    # Apenas reutiliza a mesma lógica
    return adicionar_nota_manifesto_tms._callback(request)


@extend_schema(
    tags=['Notas Fiscais'],
    summary="Muda status de ocorrência da nf-e",
    description="Atualiza o status de uma nota fiscal, criando uma ocorrência/baixa. Aceita código TMS ou id_referencia.",
    request=OpenApiTypes.OBJECT,
    examples=[
        OpenApiExample(
            "Exemplo Payload", 
            value={
                "numero_manifesto": "12345",
                "numero_nota": "555666",
                "ocorrencia_codigo": "01",
                "observacao": "Cliente recusou carga por avaria",
                "data_ocorrencia": "2026-07-07T10:00:00Z"
            }, 
            request_only=True
        )
    ],
    responses={
        200: OpenApiResponse(description="Ocorrência registrada com sucesso"),
        404: OpenApiResponse(description="Nota Fiscal ou Ocorrência não encontradas")
    }
)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def status_ocorrencia_tms(request):
    valido, erro_response = valida_token_tms(request)
    if not valido: return erro_response

    numero_manifesto = request.data.get('numero_manifesto')
    numero_nota = request.data.get('numero_nota')
    codigo_tms = request.data.get('ocorrencia_codigo')
    obs = request.data.get('observacao', '')
    data_manual = request.data.get('data_ocorrencia')

    if not all([numero_manifesto, numero_nota, codigo_tms]):
        return Response({"erro": "numero_manifesto, numero_nota e ocorrencia_codigo são obrigatórios"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        nf = NotaFiscal.objects.get(manifesto__numero_manifesto=numero_manifesto, numero_nota=numero_nota)
    except NotaFiscal.DoesNotExist:
        return Response({"erro": "Nota Fiscal não encontrada neste manifesto."}, status=status.HTTP_404_NOT_FOUND)

    # Busca a ocorrencia (primeiro por codigo_referencia, depois por codigo_tms)
    ocorrencia = Ocorrencia.objects.filter(codigo_referencia=codigo_tms).first()
    if not ocorrencia:
        ocorrencia = Ocorrencia.objects.filter(codigo_tms=codigo_tms).first()
    
    if not ocorrencia:
        return Response({"erro": f"Ocorrência de código '{codigo_tms}' não encontrada no sistema central."}, status=status.HTTP_404_NOT_FOUND)

    # Registra a baixa
    baixa, created = BaixaNF.objects.update_or_create(
        nota_fiscal=nf,
        defaults={
            'tipo': 'ENTREGA' if ocorrencia.tipo == 'ENTREGA' else 'OCORRENCIA',
            'ocorrencia': ocorrencia,
            'observacao': obs,
            'data_baixa': data_manual if data_manual else timezone.now()
        }
    )
    
    nf.status = 'BAIXADA' if baixa.tipo == 'ENTREGA' else 'OCORRENCIA'
    nf.save()

    return Response({"sucesso": True, "mensagem": f"Ocorrência '{ocorrencia.nome}' registrada na NF {numero_nota}."})


@extend_schema(
    tags=['Notas Fiscais'],
    summary="Registra comprovante de entrega a uma nf-e",
    description="Envia a URL ou base64 (futuro) do comprovante. Atualmente salva a URL externa ou observa a recepção.",
    request=OpenApiTypes.OBJECT,
    examples=[
        OpenApiExample(
            "Exemplo Payload", 
            value={
                "numero_manifesto": "12345",
                "numero_nota": "555666",
                "comprovante_url": "https://meu-sistema.com/fotos/123.jpg",
                "recebedor": "Joao Silva",
                "ocorrencia_codigo": "01" 
            }, 
            request_only=True
        )
    ],
    responses={
        200: OpenApiResponse(description="Comprovante salvo com sucesso")
    }
)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def comprovante_nota_tms(request):
    valido, erro_response = valida_token_tms(request)
    if not valido: return erro_response

    numero_manifesto = request.data.get('numero_manifesto')
    numero_nota = request.data.get('numero_nota')
    url_comprovante = request.data.get('comprovante_url', '')
    recebedor = request.data.get('recebedor', 'NÃO INFORMADO')
    codigo_tms = request.data.get('ocorrencia_codigo', '01') # Default entrega

    if not all([numero_manifesto, numero_nota]):
        return Response({"erro": "numero_manifesto e numero_nota são obrigatórios"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        nf = NotaFiscal.objects.get(manifesto__numero_manifesto=numero_manifesto, numero_nota=numero_nota)
    except NotaFiscal.DoesNotExist:
        return Response({"erro": "Nota Fiscal não encontrada neste manifesto."}, status=status.HTTP_404_NOT_FOUND)

    ocorrencia = Ocorrencia.objects.filter(codigo_referencia=codigo_tms).first()
    if not ocorrencia:
        ocorrencia = Ocorrencia.objects.filter(codigo_tms=codigo_tms).first()

    if not ocorrencia:
        return Response({"erro": "Código de ocorrência inválido."}, status=status.HTTP_404_NOT_FOUND)

    baixa, created = BaixaNF.objects.update_or_create(
        nota_fiscal=nf,
        defaults={
            'tipo': 'ENTREGA',
            'ocorrencia': ocorrencia,
            'comprovante_foto_url': url_comprovante,
            'recebedor': recebedor,
            'data_baixa': timezone.now()
        }
    )
    
    nf.status = 'BAIXADA'
    nf.save()

    return Response({"sucesso": True, "mensagem": "Comprovante registrado com sucesso na NF."})


@extend_schema(
    tags=['Notas Fiscais'],
    summary="Remove uma nf-e",
    description="Apaga uma nota fiscal do banco de dados (desde que ainda esteja Pendente e não tenha baixa).",
    request=OpenApiTypes.OBJECT,
    examples=[
        OpenApiExample(
            "Exemplo Payload", 
            value={
                "numero_manifesto": "12345",
                "numero_nota": "555666"
            }, 
            request_only=True
        )
    ],
    responses={
        200: OpenApiResponse(description="Nota removida com sucesso"),
        400: OpenApiResponse(description="Não é possível remover nota baixada"),
        404: OpenApiResponse(description="Nota não encontrada")
    }
)
@api_view(['DELETE', 'POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def remover_nota_tms(request):
    valido, erro_response = valida_token_tms(request)
    if not valido: return erro_response

    numero_manifesto = request.data.get('numero_manifesto')
    numero_nota = request.data.get('numero_nota')

    if not all([numero_manifesto, numero_nota]):
        return Response({"erro": "numero_manifesto e numero_nota são obrigatórios"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        nf = NotaFiscal.objects.get(manifesto__numero_manifesto=numero_manifesto, numero_nota=numero_nota)
    except NotaFiscal.DoesNotExist:
        return Response({"erro": "Nota Fiscal não encontrada neste manifesto."}, status=status.HTTP_404_NOT_FOUND)

    # Verifica se já teve baixa
    if nf.status != 'PENDENTE' or BaixaNF.objects.filter(nota_fiscal=nf).exists():
        return Response({"erro": "Não é possível remover uma nota que já possui baixa ou ocorrência."}, status=status.HTTP_400_BAD_REQUEST)

    nf.delete()

    return Response({"sucesso": True, "mensagem": f"Nota Fiscal {numero_nota} removida com sucesso do manifesto {numero_manifesto}."})

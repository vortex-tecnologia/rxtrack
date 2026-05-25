from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def perfil_motorista(request):
    try:
        # Usando o related_name que você definiu no models.py
        motorista = request.user.motorista_perfil 
        
        return JsonResponse({
            'nome': motorista.nome_completo,
            'foto_url': motorista.foto_perfil.url if motorista.foto_perfil else None,
            'filial_id': str(motorista.filial.id) if motorista.filial else 'todas',
            'filial_nome': motorista.filial.nome if motorista.filial else 'Geral'
        })
    except Exception as e:
        # Se o user não tiver um perfil vinculado
        return JsonResponse({'error': 'Perfil não encontrado'}, status=404)
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def perfil_motorista(request):
    try:
        motorista = request.user.motorista_perfil 
        
        if request.method == 'POST':
            # Atualiza dados de hardware do aparelho
            dados = request.data
            mudou = False
            
            if 'modelo_aparelho' in dados:
                motorista.modelo_aparelho = str(dados['modelo_aparelho'])[:100]
                mudou = True
            
            if 'memoria_ram' in dados:
                motorista.memoria_ram = str(dados['memoria_ram'])[:20]
                mudou = True
                
            if mudou:
                motorista.save(update_fields=['modelo_aparelho', 'memoria_ram'])
                
            return JsonResponse({'status': 'ok'})
        
        return JsonResponse({
            'nome': motorista.nome_completo,
            'foto_url': motorista.foto_perfil.url if motorista.foto_perfil else None,
            'filial_id': str(motorista.filial.id) if motorista.filial else 'todas',
            'filial_nome': motorista.filial.nome if motorista.filial else 'Geral',
            'permitir_upload_galeria': motorista.permitir_upload_galeria
        })
    except Exception as e:
        return JsonResponse({'error': 'Perfil não encontrado'}, status=404)
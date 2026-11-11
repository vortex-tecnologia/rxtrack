from django.http import JsonResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def perfil_motorista(request):
    try:
        motorista = request.user.motorista_perfil 
        
        if request.method == 'POST':
            # Atualiza dados de hardware e status de permissões do aparelho (APK e PWA)
            dados = request.data
            campos_atualizar = []
            
            if 'modelo_aparelho' in dados and dados['modelo_aparelho']:
                modelo_val = str(dados['modelo_aparelho'])[:100]
                if modelo_val != 'Desconhecido' or not motorista.modelo_aparelho:
                    motorista.modelo_aparelho = modelo_val
                    campos_atualizar.append('modelo_aparelho')
            
            if 'memoria_ram' in dados and dados['memoria_ram']:
                ram_val = str(dados['memoria_ram'])[:20]
                if ram_val != 'Desconhecido' or not motorista.memoria_ram:
                    motorista.memoria_ram = ram_val
                    campos_atualizar.append('memoria_ram')

            for campo_perm in ('permissao_gps', 'permissao_notificacao', 'permissao_camera'):
                if campo_perm in dados and dados[campo_perm] is not None:
                    val_bool = bool(dados[campo_perm]) if isinstance(dados[campo_perm], bool) else str(dados[campo_perm]).lower() in ('true', '1', 'granted')
                    # Se o motorista tem fcm_token (APK), mantém permissao_notificacao ativa
                    if campo_perm == 'permissao_notificacao' and motorista.fcm_token and not val_bool:
                        val_bool = True
                    setattr(motorista, campo_perm, val_bool)
                    campos_atualizar.append(campo_perm)

            if any(c in campos_atualizar for c in ('permissao_gps', 'permissao_notificacao', 'permissao_camera')):
                motorista.permissoes_atualizadas_em = timezone.now()
                campos_atualizar.append('permissoes_atualizadas_em')
                
            if campos_atualizar:
                motorista.save(update_fields=list(dict.fromkeys(campos_atualizar)))
                
            return JsonResponse({
                'status': 'ok',
                'permissao_gps': motorista.permissao_gps,
                'permissao_notificacao': motorista.tem_notificacao_ativa,
                'permissao_camera': motorista.permissao_camera,
            })
        
        return JsonResponse({
            'nome': motorista.nome_completo,
            'foto_url': motorista.foto_perfil.url if motorista.foto_perfil else None,
            'filial_id': str(motorista.filial.id) if motorista.filial else 'todas',
            'filial_nome': motorista.filial.nome if motorista.filial else 'Geral',
            'permitir_upload_galeria': motorista.permitir_upload_galeria,
            'modo_camera': motorista.modo_camera,
            'permissao_gps': motorista.permissao_gps,
            'permissao_notificacao': motorista.tem_notificacao_ativa,
            'permissao_camera': motorista.permissao_camera,
        })
    except Exception as e:
        return JsonResponse({'error': 'Perfil não encontrado'}, status=404)
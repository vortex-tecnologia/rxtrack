from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils.timezone import localtime
from django.db.models import Q
import requests, json
from django.views.decorators.csrf import csrf_exempt
from manifesto.models import NotaFiscal, Manifesto
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST


@csrf_exempt
@require_http_methods(["POST"])
def buscar_e_importar_nfe(request):
    import re
    try:
        data = json.loads(request.body)
        numero = data.get('numero')
        cnpj_emissor_input = data.get('cnpj_emissor') # Ex: "27.718.125/0001-08"
        chave = data.get('chave')
        manifesto_id = data.get('manifesto_id')

        # Função interna para deixar apenas números no CNPJ
        def limpar_documento(doc):
            return re.sub(r'\D', '', str(doc)) if doc else ""

        cnpj_busca = limpar_documento(cnpj_emissor_input)

        # 1. BUSCA LOCAL
        if chave:
            nota_local = NotaFiscal.objects.filter(chave_acesso=chave).first()
        else:
            nota_local = NotaFiscal.objects.filter(numero_nota=numero).first()

        if nota_local and not manifesto_id:
            return JsonResponse({
                "sucesso": True,
                "origem": "local",
                "dados": {
                    "numero": nota_local.numero_nota,
                    "chave": nota_local.chave_acesso,
                    "destinatario": nota_local.destinatario,
                    "endereco": nota_local.endereco_entrega
                }
            })

        # 2. BUSCA NO TMS E FILTRAGEM
        if not manifesto_id:
            from configuracao.utils import get_config
            config = get_config()
            URL_TMS = f"https://{config.dominio_esl}/api/analytics/reports/{config.report_busca_nfe}/data"
            TOKEN = config.token_analytics

            payload = {
                "search": {
                    "invoices": {
                        "issue_date": "2024-01-01 - 2050-12-31",
                        "number": int(numero) if numero else None
                    }
                },
                "page": "1", "per": "100"
            }

            res = requests.get(URL_TMS, 
                               headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, 
                               data=json.dumps(payload), 
                               timeout=20)

            if res.status_code == 200:
                dados_api = res.json() # Isso é a lista []
                
                nota_encontrada = None
                for nf in dados_api:
                    # O segredo está aqui: ioe_iur_document é o CNPJ do emissor no seu JSON
                    cnpj_emissor_api = limpar_documento(nf.get('ioe_iur_document'))

                    if (chave and nf.get('key') == chave) or (not chave and cnpj_emissor_api == cnpj_busca):
                        nota_encontrada = nf
                        break
                
                if nota_encontrada:
                    cep_tms = nota_encontrada.get('ioe_rpt_mds_postal_code') or nota_encontrada.get('ioe_rpt_zip_code') or nota_encontrada.get('zip_code')
                    return JsonResponse({
                        "sucesso": True,
                        "origem": "tms",
                        "dados": {
                            "numero": nota_encontrada.get('number'),
                            "chave": nota_encontrada.get('key'),
                            "destinatario": nota_encontrada.get('ioe_rpt_name'),
                            "endereco": f"{nota_encontrada.get('ioe_rpt_mds_line_1')}, {nota_encontrada.get('ioe_rpt_mds_number')}",
                            "cep": str(cep_tms).strip()[:10] if cep_tms else None
                        }
                    })
                
                return JsonResponse({"sucesso": False, "mensagem": "Nota encontrada com esse número, mas o CNPJ emissor não confere."}, status=404)
            
            return JsonResponse({"sucesso": False, "mensagem": f"Erro na API TMS: {res.status_code}"}, status=res.status_code)

        # 3. SALVAR
        else:
            manifesto = get_object_or_404(Manifesto, id=manifesto_id)
            nova_nota = NotaFiscal.objects.create(
                manifesto=manifesto,
                numero_nota=data.get('numero'),
                chave_acesso=data.get('chave'),
                destinatario=data.get('destinatario').upper() if data.get('destinatario') else None,
                endereco_entrega=data.get('endereco').upper() if data.get('endereco') else None,
                cep=data.get('cep'),
                status='PENDENTE'
            )
            # 📲 Notifica motorista (Push FCM) sobre adicao manual da nota
            if manifesto.motorista and manifesto.motorista.fcm_token:
                try:
                    from common.tasks_notificacoes import notificar_item_adicionado_manifesto
                    notificar_item_adicionado_manifesto(manifesto.motorista, manifesto.numero_manifesto, nova_nota.numero_nota, tipo_item=nova_nota.tipo_operacao or 'NOTA')
                except Exception as push_err:
                    import logging
                    logging.getLogger(__name__).error(f"Erro ao notificar adicao manual de nota: {push_err}")

            return JsonResponse({"sucesso": True, "mensagem": "Nota vinculada ao manifesto com sucesso!"})

    except Exception as e:
        return JsonResponse({"sucesso": False, "mensagem": str(e)}, status=500)
    
from django.http import JsonResponse
from manifesto.models import Manifesto

def listar_manifestos_select(request):
    # 1. Filtro de Segurança por Filial do Operador
    usuario_filial = getattr(request.user.userprofile, 'filial', None) if hasattr(request.user, 'userprofile') else None
    
    # Buscamos os últimos 50 manifestos para não sobrecarregar o select
    qs = Manifesto.objects.exclude(status='CANCELADO').exclude(numero_manifesto__startswith='SAC-').order_by('-data_criacao')
    
    if usuario_filial:
        qs = qs.filter(filial=usuario_filial)

    manifestos = qs[:50]
    
    dados = [
        {
            "id": m.id, 
            "numero": m.numero_manifesto, 
            "motorista": m.motorista.nome_completo if m.motorista else "Sem Motorista"
        } for m in manifestos
    ]
    
    return JsonResponse({"sucesso": True, "manifestos": dados})


@login_required
@require_POST # Garante que só aceite chamadas POST (segurança)
def sincronizar_nota_tms_view(request, nota_id):
    from manifesto.tasks import enviar_baixa_esl_task, enviar_baixa_minuta_task
    try:
        # 1. Verifica se a nota existe
        # (Aqui usamos o ID da nota, a task buscará a 'baixa' vinculada)
        nota = NotaFiscal.objects.get(id=nota_id)
        
        # 2. Busca a última baixa dessa nota para enviar
        baixa = nota.baixa_info.all().last()
        
        if not baixa:
            return JsonResponse({
                'sucesso': False, 
                'mensagem': 'Esta nota ainda não possui uma baixa registrada pelo motorista.'
            }, status=400)

        # 3. Dispara a Task do Celery correta (Entrega vs Coleta vs Minuta)
        if nota.tipo_operacao == 'COLETA':
            from manifesto.tasks import enviar_coleta_esl_task
            enviar_coleta_esl_task.delay(baixa.id)
        elif nota.tipo_operacao and str(nota.tipo_operacao).upper() == 'DESPACHO':
            enviar_baixa_minuta_task.delay(baixa.id)
        elif nota.chave_acesso:
            enviar_baixa_esl_task.delay(baixa.id)
        else:
            enviar_baixa_minuta_task.delay(baixa.id)

        return JsonResponse({
            'sucesso': True,
            'mensagem': f'Sincronização da nota {nota.numero_nota} iniciada com sucesso!'
        })

    except NotaFiscal.DoesNotExist:
        return JsonResponse({'sucesso': False, 'mensagem': 'Nota não encontrada.'}, status=404)
    except Exception as e:
        return JsonResponse({'sucesso': False, 'mensagem': str(e)}, status=500)
    
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from manifesto.models import Manifesto, NotaFiscal


def api_rastreio_manifesto(request, manifesto_id):
    # Busca o manifesto pelo número operacional (ex: 58134)
    manifesto = get_object_or_404(Manifesto, numero_manifesto=manifesto_id)
    
    # Buscamos as notas do manifesto que possuem registro de baixa com GPS
    # Usamos baixa_info (related_name) para chegar na latitude/longitude
    notas = manifesto.notas_fiscais.filter(
        baixa_info__latitude__isnull=False, 
        baixa_info__longitude__isnull=False
    ).prefetch_related('baixa_info').distinct()

    pontos = []
    for nota in notas:
        # Como baixa_info é um related_name de uma ForeignKey, 
        # pegamos o primeiro registro de baixa associado a essa nota
        baixa = nota.baixa_info.first() 
        
        if baixa:
            pontos.append({
                'nota': nota.numero_nota,
                'status': nota.status,
                'lat': float(baixa.latitude),
                'lng': float(baixa.longitude),
                'horario': localtime(baixa.data_baixa).strftime('%H:%M'),
                'tipo': baixa.get_tipo_display()
            })

    # Ordenar os pontos pelo horário da baixa para o rastro fazer sentido
    pontos = sorted(pontos, key=lambda x: x['horario'])

    # Ponto de partida: usa filial de operação (com fallback para filial fiscal, depois hardcoded)
    filial_base = manifesto.filial_operacao or manifesto.filial
    dados_filial = {
        'nome': filial_base.nome if filial_base else "Base",
        'lat': filial_base.latitude if filial_base and filial_base.latitude else -22.7873755,
        'lng': filial_base.longitude if filial_base and filial_base.longitude else -43.2886202,
    }

    # Posição atual do veículo (enviada pelo GPS nativo Java)
    posicao_atual = None
    if manifesto.ultima_lat and manifesto.ultima_lng:
        posicao_atual = {
            'lat': float(manifesto.ultima_lat),
            'lng': float(manifesto.ultima_lng),
            'battery': manifesto.ultima_bateria,
            'network': manifesto.ultima_rede,
            'last_seen': localtime(manifesto.ultimo_acesso).strftime('%H:%M') if manifesto.ultimo_acesso else None
        }

    return JsonResponse({
        'filial': dados_filial,
        'pontos': pontos,
        'motorista': manifesto.motorista.nome_completo if manifesto.motorista else "Motorista não identificado",
        'posicao_atual': posicao_atual
    })
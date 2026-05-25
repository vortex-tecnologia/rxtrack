# sac_mobile/views.py
# Views e APIs do App SAC Mobile (Arquitetura Sem Banco Local)

from django.shortcuts import render
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from manifesto.models import Ocorrencia
from django.utils import timezone
from datetime import datetime
import requests
import time
import logging
import traceback
from django.db.models import Count, Q
from manifesto.models import Manifesto, NotaFiscal, BaixaNF, Ocorrencia

logger = logging.getLogger(__name__)


def app_view(request):
    """Renderiza a página principal do App SAC."""
    ocorrencias = Ocorrencia.objects.all().order_by('codigo_tms')
    return render(request, 'aplicativo/sac/index.html', {'ocorrencias': ocorrencias})


def _classificar_termo(termo):
    """
    Classifica automaticamente o que o usuário digitou/escaneou.
    Retorna (tipo, valor_limpo).
    """
    limpo = termo.strip().replace(' ', '')
    
    # 44 dígitos = chave de acesso (NF-e ou CT-e)
    if len(limpo) == 44 and limpo.isdigit():
        return 'CHAVE', limpo
    
    # Numérico curto = pode ser número de NF, CT-e ou manifesto
    if limpo.isdigit():
        return 'NUMERO', limpo
    
    # Fallback: trata como texto genérico
    return 'NUMERO', limpo


def _buscar_no_tms(tipo, valor):
    """
    Busca no TMS (ESL) via endpoint invoice_occurrences.
    Retorna dict indexado por chave NF-e com a ocorrência mais recente.
    """
    from configuracao.utils import get_config
    config = get_config()
    TOKEN = config.token_invoices
    url = f"https://{config.dominio_esl}/api/invoice_occurrences"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    # Monta os params baseado no tipo de busca
    params = {"per": 50}
    
    if tipo == 'CHAVE':
        params["invoice_key"] = valor
    else:
        params["invoice_number"] = valor
    
    resultados_tms = {}
    next_id = None
    tentativas = 0
    max_tentativas = 5  # Limita paginação para não travar
    
    while tentativas < max_tentativas:
        tentativas += 1
        if next_id:
            params["start"] = next_id
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code != 200:
                logger.warning(f"[SAC TMS] Erro {response.status_code}: {response.text[:200]}")
                break
            
            data = response.json()
            registros = data.get('data', [])
            
            if not registros:
                break
            
            for item in registros:
                invoice = item.get('invoice', {})
                freight = item.get('freight', {})
                occurrence = item.get('occurrence', {})
                chave_nfe = invoice.get('key')
                
                if not chave_nfe:
                    continue
                
                occurrence_at = item.get('occurrence_at', '')
                
                # Mantém apenas a ocorrência mais recente por chave
                if chave_nfe in resultados_tms:
                    if occurrence_at <= resultados_tms[chave_nfe]['_occurrence_at']:
                        continue
                
                resultados_tms[chave_nfe] = {
                    'numero_nota': invoice.get('number'),
                    'chave_acesso': chave_nfe,
                    'freight_id': freight.get('id'),
                    'cte_number': str(freight.get('cte_number', '')) if freight.get('cte_number') else None,
                    'cte_key': freight.get('cte_key'),
                    'destinatario': freight.get('corporation', {}).get('name', 'Não informado') if freight else 'Não informado',
                    'manifesto_id': item.get('manifest', {}).get('id') if item.get('manifest') else 'N/A',
                    'ultima_ocorrencia_codigo': str(occurrence.get('code', '')),
                    'ultima_ocorrencia_descricao': occurrence.get('description', ''),
                    'ultima_ocorrencia_data': occurrence_at,
                    '_occurrence_at': occurrence_at,  # Campo auxiliar para comparação
                }
            
            paging = data.get('paging', {})
            next_id = paging.get('next_id')
            if not next_id:
                break
            
            time.sleep(1.5)
        
        except Exception as e:
            logger.error(f"[SAC TMS] Erro na busca: {e}")
            break
    
    # Se busca por número não achou nada como invoice, tenta como cte_number
    if not resultados_tms and tipo == 'NUMERO':
        params.pop('invoice_number', None)
        params.pop('start', None)
        params['cte_number'] = valor
        next_id = None
        tentativas = 0
        
        while tentativas < max_tentativas:
            tentativas += 1
            if next_id:
                params["start"] = next_id
            
            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
                if response.status_code != 200:
                    break
                
                data = response.json()
                registros = data.get('data', [])
                
                if not registros:
                    break
                
                for item in registros:
                    invoice = item.get('invoice', {})
                    freight = item.get('freight', {})
                    occurrence = item.get('occurrence', {})
                    chave_nfe = invoice.get('key')
                    
                    if not chave_nfe:
                        continue
                    
                    occurrence_at = item.get('occurrence_at', '')
                    
                    if chave_nfe in resultados_tms:
                        if occurrence_at <= resultados_tms[chave_nfe]['_occurrence_at']:
                            continue
                    
                    resultados_tms[chave_nfe] = {
                        'numero_nota': invoice.get('number'),
                        'chave_acesso': chave_nfe,
                        'freight_id': freight.get('id'),
                        'cte_number': str(freight.get('cte_number', '')) if freight.get('cte_number') else None,
                        'cte_key': freight.get('cte_key'),
                        'destinatario': freight.get('corporation', {}).get('name', 'Não informado') if freight else 'Não informado',
                        'manifesto_id': item.get('manifest', {}).get('id') if item.get('manifest') else 'N/A',
                        'ultima_ocorrencia_codigo': str(occurrence.get('code', '')),
                        'ultima_ocorrencia_descricao': occurrence.get('description', ''),
                        'ultima_ocorrencia_data': occurrence_at,
                        '_occurrence_at': occurrence_at,
                    }
                
                paging = data.get('paging', {})
                next_id = paging.get('next_id')
                if not next_id:
                    break
                
                time.sleep(1.5)
            
            except Exception as e:
                logger.error(f"[SAC TMS CTE] Erro: {e}")
                break
    
    # Se busca por cte_number não achou nada, tenta como draft_number (Minuta)
    if not resultados_tms and tipo == 'NUMERO':
        params.pop('cte_number', None)
        params.pop('start', None)
        params['draft_number'] = valor
        next_id = None
        tentativas = 0
        
        while tentativas < max_tentativas:
            tentativas += 1
            if next_id:
                params["start"] = next_id
            
            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
                if response.status_code != 200:
                    break
                
                data = response.json()
                registros = data.get('data', [])
                
                if not registros:
                    break
                
                for item in registros:
                    invoice = item.get('invoice', {})
                    freight = item.get('freight', {})
                    occurrence = item.get('occurrence', {})
                    chave_nfe = invoice.get('key')
                    
                    # Minutas podem não ter chave de nota, usamos draft_number como ID único se necessário
                    id_unico = chave_nfe if chave_nfe else f"minuta_{freight.get('draft_number', valor)}"
                    
                    occurrence_at = item.get('occurrence_at', '')
                    
                    if id_unico in resultados_tms:
                        if occurrence_at <= resultados_tms[id_unico]['_occurrence_at']:
                            continue
                    
                    resultados_tms[id_unico] = {
                        'numero_nota': invoice.get('number') or freight.get('draft_number'),
                        'chave_acesso': chave_nfe,
                        'freight_id': freight.get('id'),
                        'cte_number': str(freight.get('cte_number', '')) if freight.get('cte_number') else None,
                        'cte_key': freight.get('cte_key'),
                        'destinatario': freight.get('corporation', {}).get('name', 'Não informado') if freight else 'Não informado',
                        'manifesto_id': item.get('manifest', {}).get('id') if item.get('manifest') else 'N/A',
                        'ultima_ocorrencia_codigo': str(occurrence.get('code', '')),
                        'ultima_ocorrencia_descricao': occurrence.get('description', ''),
                        'ultima_ocorrencia_data': occurrence_at,
                        '_occurrence_at': occurrence_at,
                    }
                
                paging = data.get('paging', {})
                next_id = paging.get('next_id')
                if not next_id:
                    break
                
                time.sleep(1.5)
            
            except Exception as e:
                logger.error(f"[SAC TMS DRAFT] Erro: {e}")
                break
                
    # Se era uma CHAVE e não achou como invoice_key, tenta como cte_key
    if not resultados_tms and tipo == 'CHAVE':
        params.pop('invoice_key', None)
        params.pop('start', None)
        params['cte_key'] = valor
        next_id = None
        tentativas = 0
        
        while tentativas < max_tentativas:
            tentativas += 1
            if next_id:
                params["start"] = next_id
            
            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
                if response.status_code != 200:
                    break
                
                data = response.json()
                registros = data.get('data', [])
                
                if not registros:
                    break
                
                for item in registros:
                    invoice = item.get('invoice', {})
                    freight = item.get('freight', {})
                    occurrence = item.get('occurrence', {})
                    chave_nfe = invoice.get('key')
                    
                    if not chave_nfe:
                        continue
                    
                    occurrence_at = item.get('occurrence_at', '')
                    
                    if chave_nfe in resultados_tms:
                        if occurrence_at <= resultados_tms[chave_nfe]['_occurrence_at']:
                            continue
                    
                    resultados_tms[chave_nfe] = {
                        'numero_nota': invoice.get('number'),
                        'chave_acesso': chave_nfe,
                        'freight_id': freight.get('id'),
                        'cte_number': str(freight.get('cte_number', '')) if freight.get('cte_number') else None,
                        'cte_key': freight.get('cte_key'),
                        'destinatario': freight.get('corporation', {}).get('name', 'Não informado') if freight else 'Não informado',
                        'manifesto_id': item.get('manifest', {}).get('id') if item.get('manifest') else 'N/A',
                        'ultima_ocorrencia_codigo': str(occurrence.get('code', '')),
                        'ultima_ocorrencia_descricao': occurrence.get('description', ''),
                        'ultima_ocorrencia_data': occurrence_at,
                        '_occurrence_at': occurrence_at,
                    }
                
                paging = data.get('paging', {})
                next_id = paging.get('next_id')
                if not next_id:
                    break
                
                time.sleep(1.5)
            
            except Exception as e:
                logger.error(f"[SAC TMS CTE KEY] Erro: {e}")
                break
    
    # Remove campo auxiliar antes de retornar
    for key in resultados_tms:
        resultados_tms[key].pop('_occurrence_at', None)
    
    return resultados_tms


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_search_nf(request):
    """
    Busca inteligente apenas no TMS.
    """
    termo = request.GET.get('termo', '').strip()
    if not termo:
        return Response({"error": "Digite um número, chave ou escaneie o código."}, status=400)
    
    tipo, valor = _classificar_termo(termo)
    
    try:
        resultados_tms = _buscar_no_tms(tipo, valor)
    except Exception as e:
        logger.error(f"[SAC] Falha na busca TMS: {e}")
        resultados_tms = {}
    
    lista_final = list(resultados_tms.values())
    
    if not lista_final:
        return Response({"error": "Nenhuma nota encontrada com esse termo no TMS."}, status=404)
    
    return Response({"notas": lista_final, "total": len(lista_final)})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_check_comprovante_sac(request):
    """
    Checa se uma nota possui comprovante no TMS chamando a nova API.
    """
    invoice_key = request.GET.get('invoice_key')
    if not invoice_key:
        return Response({"error": "chave_acesso não informada."}, status=400)
    
    from configuracao.utils import get_config
    config = get_config()
    TOKEN = config.token_invoices
    
    url = f"https://{config.dominio_esl}/api/freight_invoice_delivery_receipts"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    try:
        response = requests.get(url, headers=headers, params={"invoice_key": invoice_key}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            registros = data.get('data', [])
            if registros:
                # Retorna a URL do primeiro comprovante encontrado
                receipt_url = registros[0].get('image_url')
                if receipt_url:
                    return Response({"has_receipt": True, "url": receipt_url})
        return Response({"has_receipt": False})
    except Exception as e:
        logger.error(f"Erro ao checar comprovante SAC: {e}")
        return Response({"has_receipt": False, "error": str(e)})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def api_registrar_baixa_sac(request):
    """
    Registra baixa feita pelo SAC (Pass-Through).
    Faz o upload da imagem para o FTP e enfileira a tarefa para chamar a API da ESL.
    """
    from sac_mobile.tasks import processar_envio_sac_tms_task, processar_canhoto_sac_task
    from manifesto.rotas.baixa import upload_via_ftp
    from .models import HistoricoBaixaSAC
    
    try:
        chave_acesso = request.data.get('chave_acesso')
        numero_nota = request.data.get('numero_nota')
        freight_id = request.data.get('freight_id')
        
        ocorrencia_id = request.data.get('ocorrencia_id')
        data_baixa_str = request.data.get('data_baixa')
        observacao = request.data.get('observacao', '')
        somente_comprovante = request.data.get('somente_comprovante') == 'true'
        foto = request.FILES.get('foto')
        
        if not chave_acesso and not freight_id:
            return Response({"error": "Chave de acesso ou ID da minuta são obrigatórios."}, status=400)
        
        if not somente_comprovante and not ocorrencia_id:
            return Response({"error": "Selecione uma ocorrência ou marque Somente Comprovante."}, status=400)
            
        codigo_tms = None
        if not somente_comprovante:
            ocorrencia = Ocorrencia.objects.get(id=ocorrencia_id)
            codigo_tms = ocorrencia.codigo_tms
        
        # Upload da foto para o FTP (mesma lógica do app do motorista)
        url_final_foto = ""
        if foto:
            nome_arquivo = f"sac_{numero_nota}_{chave_acesso}_{int(time.time())}.jpg"
            url_final_foto = upload_via_ftp(foto.read(), nome_arquivo)
            if not url_final_foto:
                return Response({"error": "Erro ao fazer upload da imagem."}, status=500)
        
        if somente_comprovante and not url_final_foto:
            return Response({"error": "É obrigatório anexar uma foto para enviar somente comprovante."}, status=400)
        
        autor = request.user.motorista_perfil
        nome_autor = autor.nome_completo if autor else "SAC Desconhecido"
        
        # Parse data para o formato aceito pela ESL: YYYY-MM-DDTHH:MM:SS.000-03:00
        if data_baixa_str:
            try:
                data_baixa = datetime.fromisoformat(data_baixa_str.replace('Z', '+00:00'))
            except:
                data_baixa = timezone.now()
        else:
            data_baixa = timezone.now()
            
        import pytz
        fuso_brasilia = pytz.timezone('America/Sao_Paulo')
        data_br = data_baixa.astimezone(fuso_brasilia)
        data_ocorrencia_esl = data_br.strftime('%Y-%m-%dT%H:%M:%S.000-03:00')
        
        # Cria o registro de Histórico no banco local
        historico = HistoricoBaixaSAC.objects.create(
            usuario=request.user if request.user.is_authenticated else None,
            chave_acesso=chave_acesso,
            freight_id=freight_id,
            numero_nota=numero_nota,
            ocorrencia_codigo=codigo_tms,
            somente_comprovante=somente_comprovante,
            observacao=observacao,
            url_foto_original=url_final_foto,
            status_tms='PENDENTE'
        )

        # Dados para a task
        dados_baixa = {
            'historico_id': historico.id,
            'chave_acesso': chave_acesso,
            'freight_id': freight_id,
            'url_foto': url_final_foto,
            'somente_comprovante': somente_comprovante,
            'ocorrencia_codigo': codigo_tms,
            'data_ocorrencia': data_ocorrencia_esl,
            'observacao': observacao,
            'nome_autor': nome_autor
        }
        
        # Decide qual fluxo seguir
        if url_final_foto:
            # Tem foto original -> Aciona a pipeline de IA primeiro
            processar_canhoto_sac_task.delay(historico.id, dados_baixa)
            msg_retorno = f"Envio da NF {numero_nota} processado! A IA fará o recorte automático da imagem em segundo plano."
        else:
            # Sem foto -> Vai direto para ESL
            processar_envio_sac_tms_task.delay(dados_baixa)
            msg_retorno = f"Envio da NF {numero_nota} processado com sucesso!"

        return Response({"message": msg_retorno})
    
    except Ocorrencia.DoesNotExist:
        return Response({"error": "Ocorrência inválida."}, status=400)
    except Exception as e:
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_listar_manifestos_auditoria_sac(request):
    """
    Lista manifestos da filial do SAC para auditoria.
    """
    try:
        perfil = request.user.motorista_perfil
        filial = perfil.filial
        
        if not filial:
            return Response({"error": "Seu usuário não está vinculado a nenhuma filial."}, status=400)

        # Manifestos ativos (em transporte)
        ativos = Manifesto.objects.filter(filial=filial, status='EM_TRANSPORTE').annotate(
            notas_pendentes=Count('notas_fiscais', filter=Q(notas_fiscais__status='PENDENTE'))
        ).filter(notas_pendentes__gt=0).order_by('-data_criacao')

        # Manifestos finalizados mas com notas pendentes
        pendentes_finalizados = Manifesto.objects.filter(filial=filial, status='FINALIZADO').annotate(
            notas_pendentes=Count('notas_fiscais', filter=Q(notas_fiscais__status='PENDENTE'))
        ).filter(notas_pendentes__gt=0).order_by('-data_criacao')

        def serialize(mfts):
            return [{
                'id': m.id,
                'numero': m.numero_manifesto,
                'motorista': m.motorista.nome_completo if m.motorista else "N/A",
                'data': m.data_criacao.strftime('%d/%m %H:%M'),
                'pendentes': m.notas_pendentes,
                'ultimo_acesso': m.ultimo_acesso.strftime('%H:%M') if m.ultimo_acesso else "Sem sinal"
            } for m in mfts]

        return Response({
            "ativos": serialize(ativos),
            "finalizados_pendentes": serialize(pendentes_finalizados)
        })
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_detalhes_manifesto_auditoria_sac(request, manifesto_id):
    """
    Lista notas de um manifesto específico para auditoria no app.
    """
    try:
        notas = NotaFiscal.objects.filter(manifesto_id=manifesto_id).order_by('status')
        
        data = []
        for nf in notas:
            data.append({
                'id': nf.id,
                'numero': nf.numero_nota,
                'destinatario': nf.destinatario,
                'status': nf.status,
                'tipo': nf.tipo_operacao
            })
            
        return Response(data)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def api_registrar_baixa_auditoria_sac(request):
    """
    Registra baixa manual pelo app SAC com motivo de auditoria.
    """
    from manifesto.tasks import enviar_baixa_esl_task
    from manifesto.rotas.baixa import upload_via_ftp
    
    try:
        nota_id = request.data.get('nota_id')
        ocorrencia_id = request.data.get('ocorrencia_id')
        motivo = request.data.get('motivo_baixa') # APP_ERROR ou MOTORISTA_DESLEIXO
        observacao = request.data.get('observacao', '')
        foto = request.FILES.get('foto')
        
        if not nota_id or not ocorrencia_id or not motivo:
            return Response({"error": "Nota, Ocorrência e Motivo são obrigatórios."}, status=400)

        nf = NotaFiscal.objects.get(id=nota_id)
        ocorrencia = Ocorrencia.objects.get(id=ocorrencia_id)
        
        # Upload opcional de foto
        url_foto = ""
        if foto:
            nome_arquivo = f"auditoria_{nf.numero_nota}_{int(time.time())}.jpg"
            url_foto = upload_via_ftp(foto.read(), nome_arquivo)

        perfil_sac = request.user.motorista_perfil

        from django.db import transaction
        with transaction.atomic():
            baixa = BaixaNF.objects.create(
                nota_fiscal=nf,
                tipo='ENTREGA' if ocorrencia.tipo == 'ENTREGA' else 'OCORRENCIA',
                ocorrencia=ocorrencia,
                recebedor="FINALIZADO PELO SAC",
                observacao=f"[AUDITORIA] {observacao}",
                autor_baixa=perfil_sac,
                motivo_baixa=motivo,
                comprovante_foto_url=url_foto,
                data_baixa=timezone.now()
            )
            
            nf.status = 'BAIXADA' if baixa.tipo == 'ENTREGA' else 'OCORRENCIA'
            nf.save()
            
            # Integração com TMS
            from configuracao.utils import get_config
            config = get_config()
            if config.enviar_tms:
                enviar_baixa_esl_task.delay(baixa.id)
            
            return Response({
                "status": "sucesso",
                "mensagem": f"Nota {nf.numero_nota} baixada com sucesso!"
            })

    except Exception as e:
        return Response({"error": str(e)}, status=500)

# manifesto/rotas/baixa.py
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from manifesto.models import NotaFiscal, BaixaNF, Ocorrencia
from django.db import transaction, models
from django.db.models import Q
from django.utils import timezone
from manifesto.tasks import enviar_baixa_esl_task, enviar_baixa_minuta_task
from ftplib import FTP
from io import BytesIO
from django.conf import settings # Importe para usar as chaves do settings
import re

logger = logging.getLogger(__name__)

def representam_mesma_entrega(nf1, nf2):
    """
    Regra 2: Valida se as notas representam a mesma entrega/destinatário.
    Não agrupa automaticamente notas do mesmo CT-e se houver evidência de que são entregas diferentes.
    """
    # 1. Ambas devem ser do tipo ENTREGA
    tipo1 = str(nf1.tipo_operacao or '').strip().upper()
    tipo2 = str(nf2.tipo_operacao or '').strip().upper()
    if tipo1 != 'ENTREGA' or tipo2 != 'ENTREGA':
        return False

    # 2. Comparação de CEP (se ambos tiverem CEP válido de 8 dígitos)
    cep1 = re.sub(r'[^0-9]', '', str(nf1.cep or ''))
    cep2 = re.sub(r'[^0-9]', '', str(nf2.cep or ''))
    if len(cep1) == 8 and len(cep2) == 8 and cep1 != cep2:
        return False

    # 3. Comparação de Destinatário (quando preenchido e não genérico)
    d1 = str(nf1.destinatario or '').strip().upper()
    d2 = str(nf2.destinatario or '').strip().upper()
    placeholders = {'', 'NÃO INFORMADO', 'NAO INFORMADO', 'DADOS NÃO REPASSADOS PELA ESL', 'CONSULTE O DOCUMENTO FÍSICO'}

    if d1 not in placeholders and d2 not in placeholders:
        norm1 = re.sub(r'[^A-Z0-9]', '', d1)
        norm2 = re.sub(r'[^A-Z0-9]', '', d2)
        if norm1 and norm2 and norm1 != norm2:
            min_len = min(len(norm1), len(norm2))
            prefix_len = min(12, min_len)
            if norm1[:prefix_len] != norm2[:prefix_len]:
                return False

    return True

def upload_via_ftp(imagem_bytes, nome_arquivo):
    try:
        from django.conf import settings
        from ftplib import FTP
        from io import BytesIO

        ftp = FTP(settings.FTP_HOST, timeout=30)
        ftp.login(user=settings.FTP_USER, passwd=settings.FTP_PASS)
        
        # CAMINHO AJUSTADO conforme seu print/link:
        caminho_ftp = 'domains/st63136.ispot.cc/public_html/uploads/comprovantes-quickdelivery'
        
        try:
            ftp.cwd(caminho_ftp)
        except:
            # Caso o caminho acima não funcione de primeira, tenta o caminho curto
            # (Alguns servidores FTP já logam direto na public_html)
            ftp.cwd('public_html/uploads/comprovantes-quickdelivery')

        ftp.storbinary(f"STOR {nome_arquivo}", BytesIO(imagem_bytes))
        ftp.quit()

        return f"{settings.FTP_BASE_URL}{nome_arquivo}"
    except Exception as e:
        print(f"Erro no Upload FTP: {e}")
        return None

class RegistrarBaixaView(APIView):
    permission_classes = [IsAuthenticated] 
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        chave_acesso = request.data.get('chave_acesso')
        numero_nota = request.data.get('numero_nota') # 👈 Pegamos o número para caso de Minuta
        codigo_tms = request.data.get('ocorrencia_codigo')
        foto_arquivo = request.FILES.get('foto')
        # Tenta pegar das duas formas para evitar erro de digitação/mismatch
        numero_mft = request.data.get('manifesto_id') or request.data.get('manifest_id')

        # --- NOVOS DADOS PARA COLETA ---
        tipo_operacao = request.data.get('tipo_operacao')
        nota_id_tms = request.data.get('nota_id_tms')

        # Saneamento de entradas nulas / "None" / "null"
        def limpar_param(val):
            if not val:
                return None
            val_str = str(val).strip()
            if val_str.lower() in ["null", "none", "undefined", ""]:
                return None
            return val_str

        chave_acesso = limpar_param(chave_acesso)
        numero_nota = limpar_param(numero_nota)
        numero_mft = limpar_param(numero_mft)
        nota_id_tms = limpar_param(nota_id_tms)

        # LOG DE DEBUG NO BACKEND
        print(f"--- REGISTRAR BAIXA ---")
        print(f"Tipo: {tipo_operacao}, Chave: {chave_acesso}, Nota/Coleta: {numero_nota or nota_id_tms}, Mft: {numero_mft}")
        
        # --- DADOS PADRÃO E IDEMPOTÊNCIA ---
        is_retida = request.data.get('nota_retida') == 'true'
        observacao_app = request.data.get('observacao_retida', '')
        idempotency_key = request.data.get('idempotency_key')
        aplicar_todas_cte_raw = request.data.get('aplicar_todas_cte')
        # Padrão: True para ENTREGA, exceto se explicitamente enviado 'false' (Regra 13 / Ajuste 3)
        aplicar_todas_cte = (str(aplicar_todas_cte_raw).strip().lower() != 'false') if aplicar_todas_cte_raw is not None else True

        try:
            with transaction.atomic():
                # --- BUSCA INTELIGENTE (HÍBRIDA) ---
                filtros = {}
                nota_id = request.data.get('nota_id')
                
                if nota_id:
                    filtros['id'] = nota_id
                elif chave_acesso:
                    filtros['chave_acesso'] = chave_acesso
                elif numero_nota:
                    num_clean = numero_nota.lstrip('0')
                    num_opcoes = [numero_nota, num_clean] if num_clean else [numero_nota]
                    filtros['numero_nota__in'] = num_opcoes
                    if nota_id_tms:
                        filtros['freight_id_tms'] = nota_id_tms
                elif nota_id_tms:
                    filtros['freight_id_tms'] = nota_id_tms

                # Vincula ao manifesto correto (Só aplica filtros de segurança se NÃO for via ID direto)
                if not nota_id:
                    if numero_mft:
                        filtros['manifesto__numero_manifesto'] = str(numero_mft)
                    else:
                        filtros['manifesto__motorista__user'] = request.user
                        filtros['manifesto__status'] = 'EM_TRANSPORTE'

                # Tenta encontrar a nota ou minuta
                if tipo_operacao == 'COLETA':
                    id_coleta = nota_id_tms if nota_id_tms else numero_nota
                    query_coleta = (Q(numero_coleta=id_coleta) | Q(numero_nota=id_coleta) | Q(freight_id_tms=id_coleta))
                    if numero_mft:
                        nf = NotaFiscal.objects.filter(
                            query_coleta,
                            tipo_operacao='COLETA',
                            manifesto__numero_manifesto=str(numero_mft)
                        ).first()
                    else:
                        nf = NotaFiscal.objects.filter(
                            query_coleta,
                            tipo_operacao='COLETA',
                            manifesto__motorista__user=request.user
                        ).first()
                    
                    if not nf:
                        raise NotaFiscal.DoesNotExist(f"Coleta {id_coleta} não encontrada.")
                else:
                    nf = NotaFiscal.objects.filter(**filtros).first()

                    # Fallback flexível: Se não achou com filtro estrito, busca por chave, número limpo ou ID TMS
                    if not nf:
                        query_flex = Q()
                        if chave_acesso:
                            query_flex |= Q(chave_acesso=chave_acesso)
                        if numero_nota:
                            num_clean = numero_nota.lstrip('0')
                            query_flex |= Q(numero_nota=numero_nota) | Q(numero_nota=num_clean) | Q(numero_coleta=numero_nota)
                        if nota_id_tms:
                            query_flex |= Q(freight_id_tms=nota_id_tms)
                        
                        if query_flex:
                            if numero_mft:
                                nf = NotaFiscal.objects.filter(query_flex, manifesto__numero_manifesto=str(numero_mft)).first()
                            if not nf:
                                nf = NotaFiscal.objects.filter(query_flex, manifesto__motorista__user=request.user).first()
                            if not nf:
                                nf = NotaFiscal.objects.filter(query_flex).first()

                    if not nf:
                        id_err = nota_id or chave_acesso or numero_nota or nota_id_tms
                        raise NotaFiscal.DoesNotExist(f"Documento {id_err} não localizado.")

                # Trava pessimista no registro da nota para concorrência
                nf = NotaFiscal.objects.select_for_update().select_related('manifesto', 'frete').filter(id=nf.id).first()
                if not nf:
                    raise NotaFiscal.DoesNotExist("Nota fiscal não localizada após lock.")

                # ======= AJUSTE 1: IDEMPOTÊNCIA REAL MULTI-CAMADAS =======
                baixa_existente = BaixaNF.objects.filter(nota_fiscal=nf).first()
                if nf.status in ['BAIXADA', 'OCORRENCIA'] and baixa_existente:
                    ja_mesmo_idempotency = False
                    if idempotency_key and isinstance(baixa_existente.payload_enviado, dict):
                        if baixa_existente.payload_enviado.get('idempotency_key') == idempotency_key:
                            ja_mesmo_idempotency = True
                    
                    tempo_passado = (timezone.now() - baixa_existente.data_baixa).total_seconds() if baixa_existente.data_baixa else 9999
                    if ja_mesmo_idempotency or tempo_passado < 120:
                        logger.info(f"⏭️ [IDEMPOTENCIA] NF #{nf.numero_nota} já finalizada (idempotency={idempotency_key}, tempo={tempo_passado:.1f}s). Retornando sucesso sem duplicar.")
                        return Response({
                            'status': 'sucesso',
                            'mensagem': 'Baixa já registrada anteriormente (requisição idempotente).',
                            'idempotente': True,
                            'notas_afetadas': [nf.numero_nota]
                        })

                # ======= BLOQUEIO POR STATUS TMS (PENDENTE/FINALIZADO) =======
                manifesto = nf.manifesto
                manifesto_da_nota = manifesto
                if manifesto_da_nota:
                    status_tms_atual = getattr(manifesto_da_nota, 'status_tms', 'in_transit')
                    if status_tms_atual == 'pending':
                        whatsapp_op = None
                        nome_filial = None
                        if manifesto_da_nota.filial:
                            whatsapp_op = manifesto_da_nota.filial.whatsapp_operacional_completo
                            nome_filial = manifesto_da_nota.filial.nome
                        logger.warning(f"⚠️ Baixa BLOQUEADA: Manifesto {numero_mft} está PENDENTE no TMS.")
                        return Response({
                            'erro': 'manifesto_pendente_tms',
                            'mensagem': 'Este manifesto está PENDENTE no TMS. Entre em contato com o operacional para colocá-lo em trânsito.',
                            'whatsapp_operacional': whatsapp_op,
                            'nome_filial': nome_filial,
                            'numero_manifesto': manifesto_da_nota.numero_manifesto,
                        }, status=409)
                    elif status_tms_atual == 'closed':
                        logger.warning(f"🚫 Baixa BLOQUEADA: Manifesto {numero_mft} está FINALIZADO no TMS.")
                        return Response({
                            'erro': 'manifesto_finalizado_tms',
                            'mensagem': 'Este manifesto já foi finalizado no TMS. Não é possível registrar baixas.',
                            'whatsapp_operacional': None,
                            'nome_filial': None,
                            'numero_manifesto': manifesto_da_nota.numero_manifesto,
                        }, status=409)

                # ======= TRACE LOG: PIPELINE DE BAIXA =======
                _trace_logger = logging.getLogger('baixa_trace')
                _trace = []
                _trace.append(f"[VIEW_INICIO] NF={nf.numero_nota}, MFT={numero_mft}, tipo_operacao_front='{tipo_operacao}', ocorrencia_codigo_front='{codigo_tms}'")
                _trace.append(f"[NF_ANTES] tipo_operacao='{nf.tipo_operacao}', chave_acesso='{nf.chave_acesso}', freight_id_tms='{nf.freight_id_tms}'")
                
                # Atualiza tipo_operacao na nota se informado pelo App
                if tipo_operacao and str(tipo_operacao).strip().upper() in ['DESPACHO', 'TRANSFERENCIA', 'COLETA', 'ENTREGA']:
                    tipo_upper = str(tipo_operacao).strip().upper()
                    if nf.tipo_operacao != tipo_upper:
                        _trace.append(f"[TIPO_OP_CHANGE] Front mandou '{tipo_upper}', NF tinha '{nf.tipo_operacao}' → ATUALIZANDO para '{tipo_upper}'")
                        nf.tipo_operacao = tipo_upper
                        nf.save(update_fields=['tipo_operacao'])

                # 1. Tenta buscar primeiro pelo mapeamento de referência do App
                ocorrencia = Ocorrencia.objects.filter(codigo_referencia=codigo_tms).first()

                # 2. Caso não encontre por referência, busca pelo código TMS (fallback)
                if not ocorrencia:
                    try:
                        ocorrencia = Ocorrencia.objects.get(codigo_tms=codigo_tms)
                    except Ocorrencia.DoesNotExist:
                        if codigo_tms.isdigit():
                            cod_int = int(codigo_tms)
                            ocorrencia = Ocorrencia.objects.filter(
                                Q(codigo_referencia=str(cod_int)) | Q(codigo_tms=str(cod_int)) |
                                Q(codigo_referencia=f"{cod_int:02d}") | Q(codigo_tms=f"{cod_int:02d}")
                            ).first()
                            
                            if not ocorrencia:
                                raise Ocorrencia.DoesNotExist(f"Ocorrência {codigo_tms} não encontrada em nenhuma forma.")
                        else:
                            raise

                # --- PROTEÇÃO CRÍTICA: DESPACHO NUNCA PODE TER CÓDIGO 01 ou 02 ---
                tipo_op_atual = str(nf.tipo_operacao or '').strip().upper()
                if 'DESPACHO' in tipo_op_atual:
                    cod_ref = str(ocorrencia.codigo_tms or ocorrencia.codigo_referencia or '').strip()
                    cod_int = None
                    try:
                        cod_int = int(cod_ref)
                    except (ValueError, TypeError):
                        pass
                    
                    if cod_int in [1, 2]:
                        return Response({
                            'erro': f'Código de ocorrência {cod_ref} (Entrega/Coleta) não é permitido para notas do tipo DESPACHO. '
                                    f'Selecione uma ocorrência válida para despacho (ex: 050, 055).'
                        }, status=400)

                # Determina se a ocorrência representa SUCESSO (Entrega/Coleta Realizada)
                cod_ref_str = str(ocorrencia.codigo_referencia or '').strip()
                cod_tms_str = str(ocorrencia.codigo_tms or '').strip()
                desc_upper = str(ocorrencia.descricao or '').upper()

                is_sucesso = (
                    ocorrencia.tipo == 'ENTREGA' or
                    cod_ref_str in ['01', '02', '1', '2'] or
                    cod_tms_str in ['01', '02', '1', '2'] or
                    'REALIZADA' in desc_upper or
                    'ENTREGUE' in desc_upper
                )

                # ======= AGRUPAMENTO POR CT-E (REGRAS 1, 2, 3, 4, 12, 13) =======
                notas_irmas_elegiveis = []
                cte_alvo = nf.numero_cte or (nf.frete.numero_cte if getattr(nf, 'frete', None) else None)
                
                # Agrupamento estrito: apenas tipo ENTREGA, apenas com CT-e preenchido, apenas se aplicar_todas_cte ativo
                if is_sucesso and tipo_op_atual == 'ENTREGA' and aplicar_todas_cte and cte_alvo and nf.manifesto:
                    candidatas = list(
                        NotaFiscal.objects.select_for_update().filter(
                            manifesto=nf.manifesto,
                            status='PENDENTE',
                            tipo_operacao='ENTREGA'
                        ).exclude(id=nf.id).filter(
                            Q(numero_cte=cte_alvo) | Q(frete__numero_cte=cte_alvo)
                        ).select_related('frete')
                    )

                    for cand in candidatas:
                        if representam_mesma_entrega(nf, cand):
                            notas_irmas_elegiveis.append(cand)
                        else:
                            logger.info(f"ℹ️ [AGRUPAMENTO CT-E] NF #{cand.numero_nota} do CT-e {cte_alvo} NÃO agrupada: destinatário ou CEP divergente da NF #{nf.numero_nota}.")

                # --- LÓGICA DE UPLOAD (SÓ SE NÃO FOR NOTA RETIDA) ---
                url_final_foto = None
                if not is_retida and foto_arquivo:
                    # Nome único para evitar sobreposição (ID da nota + identificador visual)
                    id_foto = chave_acesso if nf.chave_acesso else f"minuta_{nf.numero_nota}"
                    nome_arquivo = f"{nf.id}_{id_foto}.jpg"
                    url_final_foto = upload_via_ftp(foto_arquivo.read(), nome_arquivo)

                # --- REGISTRO DA BAIXA (COM REPLICAÇÃO CONTROLADA POR CT-E) ---
                data_manual = request.data.get('data_baixa')
                lat = request.data.get('latitude')
                lng = request.data.get('longitude')
                
                lat = lat if lat and lat != "null" and lat != "undefined" else None
                lng = lng if lng and lng != "null" and lng != "undefined" else None

                from configuracao.utils import get_config
                config_backup = get_config()
                
                data_final_baixa = data_manual if data_manual else (baixa_existente.data_baixa if baixa_existente else timezone.now())

                is_coleta = (tipo_operacao == 'COLETA' or getattr(nf, 'tipo_operacao', '') == 'COLETA')
                cod_tms_check = str(ocorrencia.codigo_tms or ocorrencia.codigo_referencia or '').strip()
                is_ocorrencia_01 = cod_tms_check in ['01', '1', '001']
                is_analise_ia_necessaria = bool(
                    not is_coleta and
                    not is_retida and
                    url_final_foto and
                    config_backup.processar_yolo and
                    is_ocorrencia_01
                )

                todas_as_notas = [nf] + notas_irmas_elegiveis
                tasks_para_disparar = []

                from django.db import connection
                schema_atual = getattr(connection, 'schema_name', None)

                for item_nf in todas_as_notas:
                    baixa_item_existente = BaixaNF.objects.filter(nota_fiscal=item_nf).first()
                    backup_item_existente = baixa_item_existente.comprovante_original_url if baixa_item_existente else None
                    nova_tentativa_item = (baixa_item_existente.tentativa_foto + 1) if (baixa_item_existente and baixa_item_existente.tentativa_foto) else 1

                    dados_payload = {
                        'idempotency_key': idempotency_key,
                        'cte_agrupado': bool(len(notas_irmas_elegiveis) > 0),
                        'numero_cte': cte_alvo
                    }

                    baixa_item, created_item = BaixaNF.objects.update_or_create(
                        nota_fiscal=item_nf,
                        defaults={
                            'tipo': 'COLETA' if is_coleta else ('ENTREGA' if is_sucesso else 'OCORRENCIA'),
                            'ocorrencia': ocorrencia,
                            'comprovante_foto_url': url_final_foto, 
                            'comprovante_original_url': url_final_foto if config_backup.armazenar_foto_backup else '',
                            'recebedor': request.data.get('recebedor') if not is_retida else "NÃO INFORMADO",
                            'latitude': lat,
                            'longitude': lng,
                            'observacao': observacao_app if is_retida else request.data.get('observacao', ''),
                            'data_baixa': data_final_baixa,
                            'tentativa_foto': nova_tentativa_item,
                            'solicitar_nova_foto': False,
                            'qualidade_canhoto': 'PENDENTE_ANALISE' if is_analise_ia_necessaria else 'APROVADO',
                            'payload_enviado': dados_payload
                        }
                    )

                    if not created_item and backup_item_existente and config_backup.armazenar_foto_backup:
                        baixa_item.comprovante_original_url = backup_item_existente
                        baixa_item.save(update_fields=['comprovante_original_url'])

                    item_nf.status = 'BAIXADA' if is_sucesso else 'OCORRENCIA'
                    item_nf.save()

                    # Agenda tarefas individuais para cada nota
                    if is_coleta:
                        from manifesto.tasks import enviar_coleta_esl_task
                        if config_backup.enviar_tms:
                            tasks_para_disparar.append((enviar_coleta_esl_task, [baixa_item.id], {}))
                    elif is_analise_ia_necessaria:
                        from AgenteIa.tasks import task_processar_canhoto_ia
                        tasks_para_disparar.append((task_processar_canhoto_ia, [baixa_item.id], {'schema_name': schema_atual}))
                    else:
                        if config_backup.enviar_tms:
                            if item_nf.chave_acesso:
                                tasks_para_disparar.append((enviar_baixa_esl_task, [baixa_item.id], {}))
                            else:
                                tasks_para_disparar.append((enviar_baixa_minuta_task, [baixa_item.id], {}))

                # ======= AJUSTE 2: CELERY E NOTIFICAÇÕES LIBERADOS RIGOROSAMENTE VIA TRANSACTION.ON_COMMIT() =======
                filial_ws = manifesto.filial if manifesto else None
                def _disparar_pos_commit():
                    # 1. Notificação WebSocket
                    try:
                        from manifesto.services import notificar_atualizacao_cargas_fretes
                        notificar_atualizacao_cargas_fretes(filial_ws)
                    except Exception as ws_err:
                        logger.error(f"Erro ao notificar WS cargas/fretes: {ws_err}")

                    # 2. Disparo das tasks do Celery
                    for t_func, t_args, t_kwargs in tasks_para_disparar:
                        try:
                            if t_kwargs:
                                t_func.apply_async(args=t_args, kwargs=t_kwargs)
                            else:
                                t_func.delay(*t_args)
                        except Exception as t_err:
                            logger.error(f"Erro ao disparar task Celery {t_func.__name__} para baixa: {t_err}")

                transaction.on_commit(_disparar_pos_commit)

                # 🏁 Auto-finalização resiliente no Backend via transaction.on_commit
                try:
                    manifesto_alvo = manifesto or (nf.manifesto if nf else None)
                    if manifesto_alvo:
                        ids_baixadas = [n.id for n in todas_as_notas]
                        pendentes_restantes = manifesto_alvo.notas_fiscais.filter(status='PENDENTE').exclude(id__in=ids_baixadas).count()
                        
                        if pendentes_restantes == 0:
                            if not is_analise_ia_necessaria:
                                from manifesto.services import tentar_autofinalizar_manifesto
                                transaction.on_commit(lambda m=manifesto_alvo: tentar_autofinalizar_manifesto(m))
                            else:
                                from manifesto.tasks import verificar_autofinalizacao_manifesto_task
                                transaction.on_commit(lambda mid=manifesto_alvo.id, s=schema_atual: (
                                    verificar_autofinalizacao_manifesto_task.apply_async(args=[mid], kwargs={'schema_name': s}, countdown=4),
                                    verificar_autofinalizacao_manifesto_task.apply_async(args=[mid], kwargs={'schema_name': s}, countdown=25)
                                ))
                        elif not is_analise_ia_necessaria:
                            from manifesto.tasks import verificar_autofinalizacao_manifesto_task
                            transaction.on_commit(lambda mid=manifesto_alvo.id, s=schema_atual: (
                                verificar_autofinalizacao_manifesto_task.apply_async(args=[mid], kwargs={'schema_name': s}, countdown=5)
                            ))
                except Exception as auto_err:
                    print(f"Aviso: Erro ao agendar auto-finalizacao na baixa agrupada: {auto_err}")

                _trace.append(f"[DISPATCH] Total notas processadas={len(todas_as_notas)}, tasks agendadas={len(tasks_para_disparar)}")
                _trace_str = " | ".join(_trace)
                _trace_logger.info(f"🔍 [TRACE BAIXA VIEW] {_trace_str}")

            notas_afetadas_nums = [n.numero_nota for n in todas_as_notas]
            msg_sucesso = f"Baixa registrada com sucesso para {len(todas_as_notas)} nota(s)!"
            if len(notas_irmas_elegiveis) > 0:
                msg_sucesso = f"Entrega agrupada realizada com sucesso! {len(todas_as_notas)} notas do CT-e {cte_alvo} baixadas com a mesma foto."

            return Response({
                'status': 'sucesso',
                'mensagem': msg_sucesso,
                'notas_afetadas': notas_afetadas_nums,
                'cte_agrupado': bool(len(notas_irmas_elegiveis) > 0),
                'numero_cte': cte_alvo
            })

        except NotaFiscal.DoesNotExist:
            id_err = nota_id if nota_id else (chave_acesso if chave_acesso else numero_nota)
            msg_exc = f"Documento {id_err} não localizado"
            if numero_mft:
                msg_exc += f" no manifesto {numero_mft}"
            return Response({'erro': msg_exc + "."}, status=404)
        except Exception as e:
            import traceback
            print(f"ERRO NA BAIXA: {str(e)}")
            traceback.print_exc()
            return Response({'erro': str(e)}, status=400)


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from manifesto.models import NotaFiscal, BaixaNF, Ocorrencia
from django.db import transaction
from manifesto.tasks import enviar_baixa_esl_task
import json

class RegistrarBaixaOperacionalView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        
        # LOG DE DEBUG: Essencial para ver no Docker o que o JS está mandando
        print(f"--- INICIO BAIXA OPERACIONAL ---")
        print(f"Dados recebidos: {data}")

        tipo_acao = data.get('tipo_operacao')  # TRANSFERENCIA, DESPACHO, RETIRADA
        numero_mft = data.get('manifesto_id')
        chave_acesso = data.get('chave_acesso')
        
        # Tratamento para booleano (JS envia 'true'/'false' como string às vezes)
        is_completo_raw = data.get('is_completo', True)
        is_completo = str(is_completo_raw).lower() == 'true'

        # 1. VALIDAÇÃO DE CAMPOS OBRIGATÓRIOS
        if not tipo_acao or not numero_mft:
            return Response({
                'erro': 'Os campos tipo_operacao e manifesto_id são obrigatórios.'
            }, status=400)

        # 2. MAPEAMENTO DE CÓDIGOS TMS
        MAPA_CODIGOS = {
            'TRANSFERENCIA': '098',
            'DESPACHO': '050' if is_completo else '055',
            'RETIRADA': '051' if is_completo else '056',
        }

        codigo_tms = MAPA_CODIGOS.get(tipo_acao)
        if not codigo_tms:
            return Response({'erro': f'Operação {tipo_acao} inválida.'}, status=400)

        try:
            ocorrencia_obj = Ocorrencia.objects.get(codigo_tms=codigo_tms)
            print(f"📌 [BAIXA OPERACIONAL API] Tipo Ação: '{tipo_acao}' (Completo: {is_completo}) | Código Mapeado: '{codigo_tms}' | Ocorrência DB: ID={ocorrencia_obj.id}, TMS='{ocorrencia_obj.codigo_tms}', Desc='{ocorrencia_obj.descricao}'")
        except Ocorrencia.DoesNotExist:
            print(f"ERRO: Código TMS {codigo_tms} não encontrado no banco de dados.")
            return Response({
                'erro': f'Código TMS {codigo_tms} não cadastrado para {tipo_acao}.'
            }, status=400)

        # 3. FILTRAGEM DAS NOTAS ALVO
        # Usamos numero_manifesto para a busca (fictício que o motorista usa)
        try:
            if tipo_acao == 'TRANSFERENCIA' and not chave_acesso:
                notas_alvo = NotaFiscal.objects.filter(
                    manifesto__numero_manifesto=str(numero_mft),
                    tipo_operacao='TRANSFERENCIA'
                ).exclude(status='BAIXADA')
            else:
                notas_alvo = NotaFiscal.objects.filter(
                    chave_acesso=chave_acesso, 
                    manifesto__numero_manifesto=str(numero_mft)
                )

            if not notas_alvo.exists():
                return Response({
                    'erro': f'Nenhuma nota pendente encontrada para o manifesto {numero_mft}.'
                }, status=404)

            contador = 0
            with transaction.atomic():
                for nf in notas_alvo:
                    # Criamos a baixa (o manifesto_id_tms será pego pela TASK via model)
                    baixa = BaixaNF.objects.create(
                        nota_fiscal=nf,
                        tipo='OCORRENCIA',
                        ocorrencia=ocorrencia_obj,
                        recebedor="FILIAL DESTINO" if tipo_acao == 'TRANSFERENCIA' else "CIA TRANSPORTADORA",
                        processado_tms=False,
                        integrado_tms=False
                    )
                    
                    # Atualiza status da nota
                    nf.status = 'BAIXADA'
                    nf.save()

                    # 4. FILA COM DELAY (Countdown para não sobrecarregar o TMS)
                    # O segredo: contador * 2 segundos entre cada nota
                    delay = contador * 2
                    # REGRA: Se tem chave_acesso → endpoint NF-e, senão → endpoint Frete/Minuta
                    if nf.chave_acesso:
                        enviar_baixa_esl_task.apply_async(args=[baixa.id], countdown=delay)
                    else:
                        enviar_baixa_minuta_task.apply_async(args=[baixa.id], countdown=delay)
                    
                    contador += 1

            # 🏁 Auto-finalização para baixas operacionais em lote
            if numero_mft:
                try:
                    from manifesto.models import Manifesto
                    mft_obj = Manifesto.objects.filter(numero_manifesto=str(numero_mft)).first()
                    if mft_obj:
                        from manifesto.tasks import verificar_autofinalizacao_manifesto_task
                        from django.db import connection
                        countdown_auto = max(4, (contador * 2) + 2)
                        verificar_autofinalizacao_manifesto_task.apply_async(
                            args=[mft_obj.id],
                            kwargs={'schema_name': getattr(connection, 'schema_name', None)},
                            countdown=countdown_auto
                        )
                except Exception as auto_op_err:
                    print(f"Aviso: Erro ao agendar auto-finalizacao operacional: {auto_op_err}")

            print(f"SUCESSO: {contador} notas processadas.")
            return Response({
                'status': 'sucesso', 
                'mensagem': f'{contador} notas enviadas para integração com TMS.'
            })

        except Exception as e:
            print(f"ERRO CRÍTICO NA VIEW: {str(e)}")
            return Response({'erro': f'Erro interno: {str(e)}'}, status=500)
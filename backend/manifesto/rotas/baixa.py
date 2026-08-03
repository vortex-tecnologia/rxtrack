# manifesto/rotas/baixa.py
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
        
        # --- DADOS PADRÃO ---
        is_retida = request.data.get('nota_retida') == 'true'
        observacao_app = request.data.get('observacao_retida', '')

        try:
            with transaction.atomic():
                # --- BUSCA INTELIGENTE (HÍBRIDA) ---
                filtros = {}
                nota_id = request.data.get('nota_id')
                
                if nota_id:
                    filtros['id'] = nota_id
                elif nota_id_tms:
                    filtros['freight_id_tms'] = nota_id_tms
                elif chave_acesso:
                    filtros['chave_acesso'] = chave_acesso
                elif numero_nota:
                    num_clean = numero_nota.lstrip('0')
                    num_opcoes = [numero_nota, num_clean] if num_clean else [numero_nota]
                    filtros['numero_nota__in'] = num_opcoes

                # Vincula ao manifesto correto (Só aplica filtros de segurança se NÃO for via ID direto)
                if not nota_id:
                    if numero_mft:
                        filtros['manifesto__numero_manifesto'] = str(numero_mft)
                    else:
                        filtros['manifesto__motorista__user'] = request.user
                        filtros['manifesto__status'] = 'EM_TRANSPORTE'

                # Tenta encontrar a nota ou minuta
                if tipo_operacao == 'COLETA':
                    # Busca específica para coleta: prioriza ID do TMS e filtra por tipo
                    id_coleta = nota_id_tms if nota_id_tms else numero_nota
                    print(f"Buscando Coleta: {id_coleta} no manifesto {numero_mft}")
                    
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

                # ======= TRACE LOG: PIPELINE DE BAIXA =======
                import logging
                _trace_logger = logging.getLogger('baixa_trace')
                _trace = []
                _trace.append(f"[VIEW_INICIO] NF={nf.numero_nota}, MFT={numero_mft}, tipo_operacao_front='{tipo_operacao}', ocorrencia_codigo_front='{codigo_tms}'")
                _trace.append(f"[NF_ANTES] tipo_operacao='{nf.tipo_operacao}', chave_acesso='{nf.chave_acesso}', freight_id_tms='{nf.freight_id_tms}'")
                
                # Atualiza tipo_operacao na nota se informado pelo App ou pelo contexto de Despacho/Aéreo
                is_mft_despacho = (nf.manifesto and (getattr(nf.manifesto, 'tipo_manifesto', '') == 'DESPACHO' or (getattr(nf.manifesto, 'qtd_despacho', 0) and nf.manifesto.qtd_despacho > 0)))
                is_frt_despacho = (nf.frete and (getattr(nf.frete, 'tipo_manifesto', '') == 'DESPACHO' or (nf.frete.modal and str(nf.frete.modal).lower() in ['air', 'aereo', 'aéreo', 'aérea', 'aerea'])))
                
                _mft_info = f"tipo_manifesto='{getattr(nf.manifesto, 'tipo_manifesto', 'N/A')}', qtd_despacho={getattr(nf.manifesto, 'qtd_despacho', 'N/A')}" if nf.manifesto else "SEM_MANIFESTO"
                _frt_info = f"tipo_manifesto='{getattr(nf.frete, 'tipo_manifesto', 'N/A')}', modal='{getattr(nf.frete, 'modal', 'N/A')}'" if nf.frete else "SEM_FRETE"
                _trace.append(f"[CONTEXTO] Manifesto: {_mft_info} → is_mft_despacho={is_mft_despacho}")
                _trace.append(f"[CONTEXTO] Frete: {_frt_info} → is_frt_despacho={is_frt_despacho}")
                
                tipo_op_original = nf.tipo_operacao
                if tipo_operacao and str(tipo_operacao).strip().upper() in ['DESPACHO', 'TRANSFERENCIA', 'COLETA', 'ENTREGA']:
                    tipo_upper = str(tipo_operacao).strip().upper()
                    if nf.tipo_operacao != tipo_upper:
                        _trace.append(f"[TIPO_OP_CHANGE] Front mandou '{tipo_upper}', NF tinha '{nf.tipo_operacao}' → ATUALIZANDO para '{tipo_upper}'")
                        nf.tipo_operacao = tipo_upper
                        nf.save(update_fields=['tipo_operacao'])
                    else:
                        _trace.append(f"[TIPO_OP] Front mandou '{tipo_upper}', NF já tinha '{nf.tipo_operacao}' → sem mudança")
                elif (is_mft_despacho or is_frt_despacho) and nf.tipo_operacao != 'DESPACHO':
                    _trace.append(f"[TIPO_OP_OVERRIDE] ⚠️ Front NÃO mandou tipo_operacao, mas contexto detectou despacho (mft={is_mft_despacho}, frt={is_frt_despacho}) → FORÇANDO '{nf.tipo_operacao}' para 'DESPACHO'")
                    nf.tipo_operacao = 'DESPACHO'
                    nf.save(update_fields=['tipo_operacao'])
                else:
                    _trace.append(f"[TIPO_OP] Sem mudança. Front tipo_operacao='{tipo_operacao}', NF tipo_operacao='{nf.tipo_operacao}'")




                # 1. Tenta buscar primeiro pelo mapeamento de referência do App
                ocorrencia = Ocorrencia.objects.filter(codigo_referencia=codigo_tms).first()

                # 2. Caso não encontre por referência, busca pelo código TMS (fallback)
                if not ocorrencia:
                    try:
                        ocorrencia = Ocorrencia.objects.get(codigo_tms=codigo_tms)
                    except Ocorrencia.DoesNotExist:
                        # Tenta o inverso para códigos numéricos (ex: se mandou '01' busca '1', se mandou '1' busca '01')
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

                _trace.append(f"[OCORRENCIA_RESOLVIDA] Front mandou='{codigo_tms}' → Resolvido: ID={ocorrencia.id}, TMS='{ocorrencia.codigo_tms}', Ref='{ocorrencia.codigo_referencia}', Tipo='{ocorrencia.tipo}', Desc='{ocorrencia.descricao}'")
                print(f"📌 [BAIXA API] Ocorrência App Recebida: '{codigo_tms}' | Ocorrência Resolvida no DB: ID={ocorrencia.id}, TMS='{ocorrencia.codigo_tms}', Ref='{ocorrencia.codigo_referencia}', Desc='{ocorrencia.descricao}' | NF Tipo: '{nf.tipo_operacao}'")

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
                        _trace.append(f"[BLOQUEADO] 🚨 tipo_op_atual='{tipo_op_atual}', cod_int={cod_int} → BLOQUEADO NA VIEW (400)")
                        _trace_str = " | ".join(_trace)
                        _trace_logger.warning(f"🔍 [TRACE BAIXA VIEW] {_trace_str}")
                        print(f"🚨 BLOQUEADO: Tentativa de registrar código {cod_ref} (Entrega) em nota DESPACHO {nf.numero_nota}")
                        return Response({
                            'erro': f'Código de ocorrência {cod_ref} (Entrega/Coleta) não é permitido para notas do tipo DESPACHO. '
                                    f'Selecione uma ocorrência válida para despacho (ex: 050, 055).'
                        }, status=400)

                # --- LÓGICA DE UPLOAD (SÓ SE NÃO FOR NOTA RETIDA) ---
                url_final_foto = None
                if not is_retida and foto_arquivo:
                    # Nome único para evitar sobreposição (ID da nota + identificador visual)
                    id_foto = chave_acesso if nf.chave_acesso else f"minuta_{nf.numero_nota}"
                    nome_arquivo = f"{nf.id}_{id_foto}.jpg"
                    url_final_foto = upload_via_ftp(foto_arquivo.read(), nome_arquivo)

                # --- REGISTRO DA BAIXA ---
                data_manual = request.data.get('data_baixa')
                lat = request.data.get('latitude')
                lng = request.data.get('longitude')
                
                # Saneamento para campos decimais (Django não aceita "" em DecimalField)
                lat = lat if lat and lat != "null" and lat != "undefined" else None
                lng = lng if lng and lng != "null" and lng != "undefined" else None

                # Buscamos a baixa existente ANTES de criar para saber a data_baixa
                baixa_existente = BaixaNF.objects.filter(nota_fiscal=nf).first()
                
                # Flag de backup: verifica se deve armazenar a foto original
                from configuracao.utils import get_config
                config_backup = get_config()
                
                # Guarda a URL original do backup ANTES de qualquer update (proteção)
                backup_original_existente = baixa_existente.comprovante_original_url if baixa_existente else None

                # Lógica: se tem data manual, usa ela. Se não, se já existe baixa, mantém a data dela. Se é nova, usa agora.
                data_final_baixa = data_manual if data_manual else (baixa_existente.data_baixa if baixa_existente else timezone.now())

                baixa, created = BaixaNF.objects.update_or_create(
                    nota_fiscal=nf,
                    defaults={
                        'tipo': 'ENTREGA' if ocorrencia.tipo == 'ENTREGA' else 'OCORRENCIA',
                        'ocorrencia': ocorrencia,
                        'comprovante_foto_url': url_final_foto, 
                        'comprovante_original_url': url_final_foto if config_backup.armazenar_foto_backup else '', # 👈 Controlado pela flag
                        'recebedor': request.data.get('recebedor') if not is_retida else "NÃO INFORMADO",
                        'latitude': lat,
                        'longitude': lng,
                        'observacao': observacao_app if is_retida else request.data.get('observacao', ''),
                        'data_baixa': data_final_baixa
                    }
                )
                
                _trace.append(f"[BAIXA_SALVA] ID={baixa.id}, created={created}, tipo='{baixa.tipo}', ocorrencia_tms='{ocorrencia.codigo_tms}'")
                
                # Se foi UPDATE (motorista refez a baixa), restaura o backup original 
                # para não perder a foto verdadeiramente original 
                if not created and backup_original_existente and config_backup.armazenar_foto_backup:
                    baixa.comprovante_original_url = backup_original_existente
                    baixa.save(update_fields=['comprovante_original_url'])


                nf.status = 'BAIXADA' if baixa.tipo == 'ENTREGA' else 'OCORRENCIA'
                nf.save()
                
                # --- DISPARO DA TASK CORRETA (O CÉREBRO) ---
                from configuracao.utils import get_config
                config = get_config()
                
                if tipo_operacao == 'COLETA':
                    from manifesto.tasks import enviar_coleta_esl_task
                    if config.enviar_tms:
                        enviar_coleta_esl_task.delay(baixa.id)
                    msg_log = "Coleta agendada para TMS (Picks Endpoint)." if config.enviar_tms else "Coleta salva (TMS desligado)."
                elif ocorrencia.codigo_tms in config.get_codigos_yolo_list():
                    # Ocorrências configuráveis: Vai para o fluxo do Agente IA (YOLO) primeiro
                    from AgenteIa.tasks import task_processar_canhoto_ia
                    task_processar_canhoto_ia.delay(baixa.id)
                    msg_log = "Enviada para processamento no Agente IA (YOLO) (Task Ativa)."
                else:
                    # Demais ocorrências: Fluxo direto para o TMS (se ativo)
                    if config.enviar_tms:
                        # REGRA: Se tem chave_acesso → endpoint NF-e, senão → endpoint Frete/Minuta
                        # DESPACHO com chave vai pelo endpoint NF-e normal (cada nota individualmente)
                        if nf.chave_acesso:
                            enviar_baixa_esl_task.delay(baixa.id)
                            msg_log = "NF-e agendada para TMS."
                        else:
                            enviar_baixa_minuta_task.delay(baixa.id)
                            msg_log = "Minuta agendada para TMS (Frete Endpoint)."
                    else:
                        msg_log = "Baixa salva localmente (TMS desligado nas configurações)."
                
                _trace.append(f"[DISPATCH] {msg_log} | NF status='{nf.status}', chave_acesso={'SIM' if nf.chave_acesso else 'NAO'}")
                _trace_str = " | ".join(_trace)
                _trace_logger.info(f"🔍 [TRACE BAIXA VIEW] {_trace_str}")
                print(f"🔍 [TRACE COMPLETO] {_trace_str}")
                print(f"BAIXA REGISTRADA: {msg_log} (Retida: {is_retida})")

            return Response({'status': 'sucesso', 'mensagem': 'Baixa registrada e integração iniciada!'})

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

            print(f"SUCESSO: {contador} notas processadas.")
            return Response({
                'status': 'sucesso', 
                'mensagem': f'{contador} notas enviadas para integração com TMS.'
            })

        except Exception as e:
            print(f"ERRO CRÍTICO NA VIEW: {str(e)}")
            return Response({'erro': f'Erro interno: {str(e)}'}, status=500)
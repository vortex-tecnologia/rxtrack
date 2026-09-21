from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

channel_layer = get_channel_layer()

def enviar_painel(manifesto):
    total = manifesto.notas_fiscais.count()

    baixadas = manifesto.notas_fiscais.filter(
        status__in=['BAIXADA', 'OCORRENCIA']
    ).count()

    porcentagem = int((baixadas / total) * 100) if total else 0
    total_notas = total

    remover = manifesto.status not in ['AGUARDANDO', 'EM_TRANSPORTE']
    print("WS ENVIANDO -> TOTAL:", total, "BAIXADAS:", baixadas, "STATUS:", manifesto.status)

    from django.utils.timezone import localtime
    
    # Converte o horário do banco (UTC) para o fuso horário configurado no Django (ex: America/Sao_Paulo)
    data_registro_local = localtime(manifesto.data_criacao)
    data_registro = data_registro_local.strftime('%d/%m/%Y %H:%M')
    
    from django.utils.text import slugify
    
    # Usa filial_operacao (base do emissor) com fallback para filial (fiscal)
    # Isso garante consistência com a view e o template da Torre de Controle
    filial_efetiva = manifesto.filial_operacao or manifesto.filial
    nome_filial = filial_efetiva.nome if filial_efetiva else "todas"
    grupo_filial = f"painel_monitoramento_{slugify(nome_filial)}"
    
    from manifesto.models import BaixaNF
    total_ilegivel = BaixaNF.objects.filter(
        nota_fiscal__manifesto=manifesto,
        solicitar_nova_foto=True
    ).count()

    filial_id = str(filial_efetiva.id) if filial_efetiva else ""
    filial_nome = filial_efetiva.nome if filial_efetiva else "Sem Filial"
    filial_slug = slugify(nome_filial)

    # Contagem exata em tempo real dos manifestos ativos (aguardando + em transporte) desta filial
    from manifesto.models import Manifesto
    from django.db.models import Q
    if filial_efetiva:
        total_ativos_filial = Manifesto.objects.filter(
            Q(filial_operacao=filial_efetiva) | (Q(filial_operacao__isnull=True) & Q(filial=filial_efetiva)),
            status__in=['AGUARDANDO', 'EM_TRANSPORTE']
        ).count()
    else:
        total_ativos_filial = Manifesto.objects.filter(
            filial_operacao__isnull=True, filial__isnull=True, status__in=['AGUARDANDO', 'EM_TRANSPORTE']
        ).count()

    # Contagens de cargas/operações (ESL Style)
    from django.db.models import Count, Q
    if total > 0:
        counts_op = manifesto.notas_fiscais.aggregate(
            c_ent=Count('id', filter=Q(tipo_operacao='ENTREGA')),
            c_col=Count('id', filter=Q(tipo_operacao='COLETA')),
            c_tra=Count('id', filter=Q(tipo_operacao='TRANSFERENCIA')),
            c_des=Count('id', filter=Q(tipo_operacao='DESPACHO')),
            c_ret=Count('id', filter=Q(tipo_operacao='RETIRADA')),
        )
        qtd_ent = counts_op['c_ent'] or 0
        qtd_col = counts_op['c_col'] or 0
        qtd_tra = counts_op['c_tra'] or 0
        qtd_des = counts_op['c_des'] or 0
        qtd_ret = counts_op['c_ret'] or 0
        if qtd_ent == 0 and qtd_col == 0 and qtd_tra == 0 and qtd_des == 0 and qtd_ret == 0:
            qtd_ent = total
    else:
        qtd_ent = getattr(manifesto, 'qtd_entrega', 0) or 0
        qtd_col = getattr(manifesto, 'qtd_coleta', 0) or 0
        qtd_tra = getattr(manifesto, 'qtd_transferencia', 0) or 0
        qtd_des = getattr(manifesto, 'qtd_despacho', 0) or 0
        qtd_ret = getattr(manifesto, 'qtd_retirada', 0) or 0

    payload = {
        "type": "atualizar_painel",
        "data": {
            "manifesto_id": str(manifesto.numero_manifesto),
            "status": manifesto.status,
            "filial_id": filial_id,
            "filial_nome": filial_nome,
            "filial_slug": filial_slug,
            "total_ativos_filial": total_ativos_filial,
            "baixadas": baixadas,
            "porcentagem": porcentagem,
            "total_ilegivel": total_ilegivel,
            "placa_veiculo": manifesto.veiculo.placa if (manifesto.veiculo and manifesto.veiculo.placa) else None,
            "tipo_veiculo": manifesto.veiculo.tipo if (manifesto.veiculo and manifesto.veiculo.tipo) else None,
            "motorista_id": str(manifesto.motorista.id) if manifesto.motorista else "",
            "motorista_nome": manifesto.motorista.nome_completo if manifesto.motorista else "Desconhecido",
            "motorista_categoria": manifesto.motorista.categoria if (manifesto.motorista and manifesto.motorista.categoria) else "EMPRESA",
            "motorista_categoria_display": manifesto.motorista.get_categoria_display() if (manifesto.motorista and hasattr(manifesto.motorista, 'get_categoria_display')) else "Empresa",
            "foto_motorista": manifesto.motorista.foto_perfil.url if (manifesto.motorista and manifesto.motorista.foto_perfil) else None,
            "icone_dispositivo": manifesto.motorista.icone_dispositivo_html if manifesto.motorista else "",
            "remover": remover or (manifesto.status == 'FINALIZADO') or bool(manifesto.finalizado),
            "total": total_notas, 
            "data_registro": data_registro,
            "data_criacao_iso": manifesto.data_criacao.isoformat() if manifesto.data_criacao else None,
            "ultimo_acesso_iso": localtime(manifesto.ultimo_acesso).isoformat() if manifesto.ultimo_acesso else None,
            "is_antigo": getattr(manifesto, 'is_antigo', False),
            "dias_criado": getattr(manifesto, 'dias_criado', 0),
            "is_viagem": getattr(manifesto, 'is_viagem', False),
            "uf_destino_viagem": getattr(manifesto, 'uf_destino_viagem', '') or '',
            "qtd_entrega": qtd_ent,
            "qtd_coleta": qtd_col,
            "qtd_transferencia": qtd_tra,
            "qtd_despacho": qtd_des,
            "qtd_retirada": qtd_ret,
        }
    }
    
    # Envia para a filial específica
    async_to_sync(channel_layer.group_send)(
        grupo_filial,
        payload
    )
    
    # Se não for "todas", envia também para o painel geral
    if grupo_filial != "painel_monitoramento_todas":
        async_to_sync(channel_layer.group_send)(
            "painel_monitoramento_todas",
            payload
        )

    # ⚡ Transmite em tempo real para o SAC Live também!
    try:
        notificar_atualizacao_cargas_fretes(filial_efetiva if manifesto else None)
    except Exception as sac_err:
        print(f"❌ Erro ao notificar SAC no enviar_painel: {sac_err}")


def notificar_atualizacao_cargas_fretes(filial=None):
    """
    Transmite um evento WebSocket para atualizar em tempo real o painel Cargas / Fretes (SAC).
    """
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    from django.utils.text import slugify
    from django.utils import timezone

    clayer = get_channel_layer()
    if not clayer:
        return

    filial_id_str = str(filial.id) if (filial and hasattr(filial, 'id') and filial.id) else "todas"
    nome_filial_slug = slugify(str(filial.nome)) if (filial and hasattr(filial, 'nome') and filial.nome) else "todas"

    payload = {
        "type": "atualizar_cargas",
        "data": {
            "timestamp": timezone.now().isoformat(),
            "filial_id": filial_id_str
        }
    }

    # Transmite para todas as variações de grupo possíveis para garantir recepção 100% ao vivo
    grupos = set([
        "painel_cargas_fretes_todas",
        f"painel_cargas_fretes_{filial_id_str}",
        f"painel_cargas_fretes_{nome_filial_slug}",
        "painel_monitoramento_todas",
        f"painel_monitoramento_{filial_id_str}"
    ])

    for g in grupos:
        try:
            async_to_sync(clayer.group_send)(g, payload)
        except Exception as e:
            print(f"❌ Erro ao transmitir WS cargas/fretes ({g}): {e}")


def tentar_autofinalizar_manifesto(manifesto_ou_id, km_final=None):
    """
    Avalia se um manifesto pode ser finalizado automaticamente e o encerra
    se todas as notas estiverem baixadas e todas as fotos verificadas/aprovadas pela IA.

    Regras:
    1. Manifesto existe e não está finalizado (status != 'FINALIZADO' e finalizado != True).
    2. Possui ao menos 1 nota vinculada.
    3. Nenhuma nota pendente (todas com status 'BAIXADA' ou 'OCORRENCIA').
    4. Auto-recuperação de baixas sem IA ou travadas > 45s (são liberadas).
    5. Nenhuma foto em análise pela IA (qualidade_canhoto != 'PENDENTE_ANALISE').
    6. Nenhuma foto reprovada aguardando nova foto do motorista (solicitar_nova_foto == False).

    Retorna tuple: (sucesso: bool, mensagem: str)
    """
    import logging
    from datetime import timedelta
    from django.utils import timezone
    from django.db.models import Q
    from django.db import transaction
    from manifesto.models import Manifesto, NotaFiscal, BaixaNF

    logger = logging.getLogger(__name__)

    # 1. Obtenção do objeto Manifesto
    if isinstance(manifesto_ou_id, Manifesto):
        manifesto = manifesto_ou_id
    else:
        manifesto = Manifesto.objects.filter(
            Q(numero_manifesto=str(manifesto_ou_id)) | Q(id=str(manifesto_ou_id))
        ).first()

    if not manifesto:
        return False, "Manifesto não encontrado."

    # 2. Deve ter ao menos 1 nota
    total_notas = NotaFiscal.objects.filter(manifesto=manifesto).count()
    if total_notas == 0:
        return False, f"Manifesto #{manifesto.numero_manifesto} sem notas vinculadas."

    # 3. Auto-sincronização: Notas que possuem baixa registrada mas porventura ficaram com status 'PENDENTE'
    NotaFiscal.objects.filter(
        manifesto=manifesto,
        status='PENDENTE',
        baixa_info__isnull=False
    ).update(status='BAIXADA')

    # 4. Se o manifesto está marcado como finalizado, preserva a finalização e encerra
    if (manifesto.finalizado or manifesto.status == 'FINALIZADO'):
        if not manifesto.finalizado or manifesto.status != 'FINALIZADO':
            manifesto.finalizado = True
            manifesto.status = 'FINALIZADO'
            manifesto.save(update_fields=['finalizado', 'status'])
        if km_final and str(km_final).strip() not in ["0", "0.0", ""]:
            try:
                manifesto.km_final = km_final
                manifesto.save(update_fields=['km_final'])
            except Exception:
                pass
        return True, "Manifesto já se encontra finalizado."

    # 4. Conferência de Notas Pendentes (que verdadeiramente não possuem baixa)
    notas_pendentes_qs = NotaFiscal.objects.filter(
        manifesto=manifesto,
        status='PENDENTE'
    )
    notas_pendentes = notas_pendentes_qs.count()

    if notas_pendentes > 0:
        nfs_nums = list(notas_pendentes_qs.values_list('numero_nota', flat=True)[:5])
        return False, f"Ainda existem {notas_pendentes} nota(s) pendente(s) de baixa (NFs: {', '.join(str(n) for n in nfs_nums)})."

    # 5. Auto-recuperação 1: Baixas sem IA (coleta, retida, sem foto ou ocorrência != 01)
    baixas_sem_ia = BaixaNF.objects.filter(
        nota_fiscal__manifesto=manifesto,
        qualidade_canhoto='PENDENTE_ANALISE'
    ).filter(
        Q(nota_fiscal__tipo_operacao='COLETA') |
        Q(comprovante_foto_url='') |
        Q(comprovante_foto_url__isnull=True) |
        Q(observacao__icontains='retid') |
        ~Q(ocorrencia__codigo_tms__in=['1', '01', '001'])
    )
    for b in baixas_sem_ia:
        b.qualidade_canhoto = 'APROVADO'
        b.solicitar_nova_foto = False
        b.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])

    # 6. Auto-recuperação 2: Baixas com mais de 45s travadas em PENDENTE_ANALISE (ou com data_baixa nula)
    limite_recente = timezone.now() - timedelta(seconds=45)
    baixas_travadas = BaixaNF.objects.filter(
        nota_fiscal__manifesto=manifesto,
        qualidade_canhoto='PENDENTE_ANALISE'
    ).filter(
        Q(data_baixa__lt=limite_recente) | Q(data_baixa__isnull=True)
    )
    for b in baixas_travadas:
        b.qualidade_canhoto = 'APROVADO'
        b.solicitar_nova_foto = False
        b.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])
        if not b.integrado_tms:
            try:
                from AgenteIa.tasks import finalizar_fluxo_tms
                finalizar_fluxo_tms(b)
            except Exception as e_rec:
                logger.warning(f"Erro auto-recuperacao finalizar_fluxo_tms baixa #{b.id}: {e_rec}")

    # 7. Auto-recuperação 3: Baixas que atingiram 3 ou mais tentativas de foto não devem travar
    baixas_limite = BaixaNF.objects.filter(
        nota_fiscal__manifesto=manifesto,
        solicitar_nova_foto=True,
        tentativa_foto__gte=3
    )
    for bl in baixas_limite:
        bl.solicitar_nova_foto = False
        bl.qualidade_canhoto = 'REPROVADO_LIMITE_3X'
        bl.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])

    # 8. Conferência de Fotos em Análise pela IA
    notas_em_analise = BaixaNF.objects.filter(
        nota_fiscal__manifesto=manifesto,
        qualidade_canhoto='PENDENTE_ANALISE',
        solicitar_nova_foto=False,
        nota_fiscal__tipo_operacao='ENTREGA',
        ocorrencia__codigo_tms__in=['1', '01', '001']
    ).exclude(
        observacao__icontains='retid'
    ).exclude(
        comprovante_foto_url=''
    ).exclude(
        comprovante_foto_url__isnull=True
    ).count()

    if notas_em_analise > 0:
        return False, f"Existem {notas_em_analise} foto(s) de canhoto sendo analisadas pela IA. Aguarde a conclusão."

    # 9. Conferência de Canhotos Ilegíveis / Reprovados pela IA
    baixas_ruins_qs = BaixaNF.objects.filter(
        nota_fiscal__manifesto=manifesto,
        solicitar_nova_foto=True
    )
    notas_foto_ruim = baixas_ruins_qs.count()

    if notas_foto_ruim > 0:
        nfs_ruins = list(baixas_ruins_qs.values_list('nota_fiscal__numero_nota', flat=True)[:5])
        return False, f"Existem {notas_foto_ruim} nota(s) com canhoto ilegível pendente(s) de nova foto (NFs: {', '.join(str(n) for n in nfs_ruins)})."

    # --- 8. TODAS AS NOTAS BAIXADAS E TODAS AS FOTOS VERIFICADAS COM SUCESSO! ---
    try:
        with transaction.atomic():
            manifesto_atualizado = Manifesto.objects.select_for_update().get(id=manifesto.id)
            if manifesto_atualizado.finalizado or manifesto_atualizado.status == 'FINALIZADO':
                return True, "Manifesto já finalizado previamente."

            if km_final and km_final != "0":
                manifesto_atualizado.km_final = km_final
            manifesto_atualizado.finalizado = True
            manifesto_atualizado.status = "FINALIZADO"
            manifesto_atualizado.data_finalizacao = timezone.now()
            manifesto_atualizado.save(update_fields=['km_final', 'finalizado', 'status', 'data_finalizacao'] if km_final and km_final != "0" else ['finalizado', 'status', 'data_finalizacao'])

        logger.info(f"🏁 [AUTO-FINALIZAÇÃO] Manifesto #{manifesto.numero_manifesto} (ID: {manifesto.id}) FINALIZADO com sucesso pelo backend!")
        print(f"🏁 [AUTO-FINALIZAÇÃO] Manifesto #{manifesto.numero_manifesto} (ID: {manifesto.id}) FINALIZADO com sucesso pelo backend!")

        # Notifica a Torre de Controle via WebSocket para remover o card da grade ativa
        try:
            enviar_painel(manifesto_atualizado, remover=True)
        except Exception as p_err:
            logger.error(f"Erro ao enviar painel na auto-finalização do manifesto #{manifesto.id}: {p_err}")

        # Dispara integração de encerramento no TMS ESL Cloud em background com o schema correto do cliente
        try:
            from manifesto.tasks import finalizar_manifesto_tms_task
            from django.db import connection
            schema_atual = getattr(connection, 'schema_name', 'public')
            finalizar_manifesto_tms_task.delay(manifesto_atualizado.id, schema_name=schema_atual)
        except Exception as tms_err:
            logger.error(f"Erro ao agendar task finalizar_manifesto_tms_task #{manifesto.id}: {tms_err}")

        return True, f"Manifesto #{manifesto.numero_manifesto} finalizado automaticamente com sucesso!"

    except Exception as e_final:
        logger.error(f"Erro crítico ao auto-finalizar manifesto #{manifesto.id}: {e_final}")
        return False, f"Erro ao auto-finalizar: {str(e_final)}"


def sincronizar_manifesto_individual_webhook(manifesto):
    """
    Garante que os dados do webhook (que possuem PRIORIDADE ABSOLUTA sobre relatórios/ocorrências da ESL)
    estejam aplicados ao manifesto e suas notas fiscais.
    Corrige notas com 'TRANSFERENCIA' indevida e destinatário 'DADOS NÃO REPASSADOS PELA ESL'.
    Recalcula as contagens oficiais de carga e limpa duplicatas do ID interno.
    """
    try:
        from manifesto.models import WebhookEventoManifestoESL, NotaFiscal, Manifesto
        import logging
        log = logging.getLogger(__name__)

        notas = list(manifesto.notas_fiscais.all())
        placeholders_dest = {'', 'NÃO INFORMADO', 'NAO INFORMADO', 'DADOS NÃO REPASSADOS PELA ESL'}
        placeholders_end = {'', 'NÃO INFORMADO', 'NAO INFORMADO', 'CONSULTE O DOCUMENTO FÍSICO', 'ENDEREÇO NÃO INFORMADO'}

        precisa_ajuste = any(
            n.tipo_operacao == 'TRANSFERENCIA' or
            n.destinatario in placeholders_dest or
            any(p in (n.endereco_entrega or '') for p in ['CONSULTE', 'DADOS NÃO REPASSADOS'])
            for n in notas
        )
        if not precisa_ajuste and (manifesto.qtd_transferencia or 0) > 0:
            precisa_ajuste = True

        if not precisa_ajuste:
            return False

        evento = None
        # 1. Por número do manifesto visual
        evento = WebhookEventoManifestoESL.objects.filter(
            numero_manifesto=manifesto.numero_manifesto
        ).order_by('-id').first()

        # 2. Por ID TMS do manifesto
        if not evento and manifesto.manifesto_id_tms:
            evento = WebhookEventoManifestoESL.objects.filter(
                numero_manifesto=manifesto.manifesto_id_tms
            ).order_by('-id').first()

        # 3. Por chaves de acesso ou números de notas do manifesto nos últimos eventos
        if not evento and notas:
            chaves = {n.chave_acesso for n in notas if n.chave_acesso}
            nums = {str(n.numero_nota) for n in notas if n.numero_nota}
            ultimos_eventos = WebhookEventoManifestoESL.objects.order_by('-id')[:80]
            for ev in ultimos_eventos:
                p_itens = (ev.payload or {}).get('itens', [])
                if any(it.get('chave_item') in chaves or str(it.get('numero_item')) in nums for it in p_itens):
                    evento = ev
                    break

        if not evento or not evento.payload:
            return False

        payload = evento.payload
        itens = payload.get('itens', [])
        if not itens:
            return False

        # Vincula o ID TMS se era diferente
        ev_num_mani = str(evento.numero_manifesto or '').strip()
        if ev_num_mani and ev_num_mani != str(manifesto.numero_manifesto):
            if manifesto.manifesto_id_tms != ev_num_mani:
                manifesto.manifesto_id_tms = ev_num_mani
                manifesto.save(update_fields=['manifesto_id_tms'])
            # Remove eventual manifesto fantasma duplicado criado pelo ID interno
            Manifesto.objects.filter(numero_manifesto=ev_num_mani).exclude(id=manifesto.id).delete()

        mapa_por_chave = {it.get('chave_item'): it for it in itens if it.get('chave_item')}
        mapa_por_num = {str(it.get('numero_item')): it for it in itens if it.get('numero_item')}

        modificou = False
        for n in notas:
            it = mapa_por_chave.get(n.chave_acesso) or mapa_por_num.get(str(n.numero_nota))
            if not it:
                continue

            campos_up = []
            tipo_item = it.get('tipo', 'ENTREGA')
            if tipo_item and n.tipo_operacao != tipo_item:
                n.tipo_operacao = tipo_item
                campos_up.append('tipo_operacao')
            if not n.tipo_operacao_confirmado_webhook:
                n.tipo_operacao_confirmado_webhook = True
                campos_up.append('tipo_operacao_confirmado_webhook')

            dest = it.get('destinatario', {})
            nome_dest = str(dest.get('nome', '')).upper().strip()
            if nome_dest and nome_dest not in placeholders_dest:
                if n.destinatario != nome_dest or n.destinatario in placeholders_dest:
                    n.destinatario = nome_dest
                    campos_up.append('destinatario')

            endereco = f"{dest.get('logradouro', '')}, {dest.get('numero', '')} - {dest.get('bairro', '')} ({dest.get('cidade', '')}/{dest.get('uf', '')})".upper().strip()
            if endereco and 'NÃO INFORMADO' not in endereco and 'CONSULTE' not in endereco:
                if n.endereco_entrega != endereco or 'CONSULTE' in (n.endereco_entrega or ''):
                    n.endereco_entrega = endereco
                    campos_up.append('endereco_entrega')

            if campos_up:
                n.save(update_fields=campos_up)
                modificou = True

        # Recalcula contagens oficiais de carga diretamente das notas reais do banco
        tot_ent = manifesto.notas_fiscais.filter(tipo_operacao='ENTREGA').count()
        tot_tra = manifesto.notas_fiscais.filter(tipo_operacao='TRANSFERENCIA').count()
        tot_col = manifesto.notas_fiscais.filter(tipo_operacao='COLETA').count()
        tot_des = manifesto.notas_fiscais.filter(tipo_operacao='DESPACHO').count()
        tot_ret = manifesto.notas_fiscais.filter(tipo_operacao='RETIRADA').count()

        if (getattr(manifesto, 'qtd_entrega', 0) != tot_ent or getattr(manifesto, 'qtd_transferencia', 0) != tot_tra or
            getattr(manifesto, 'qtd_coleta', 0) != tot_col or getattr(manifesto, 'qtd_despacho', 0) != tot_des or getattr(manifesto, 'qtd_retirada', 0) != tot_ret):
            manifesto.qtd_entrega = tot_ent
            manifesto.qtd_transferencia = tot_tra
            manifesto.qtd_coleta = tot_col
            manifesto.qtd_despacho = tot_des
            manifesto.qtd_retirada = tot_ret
            manifesto.save(update_fields=['qtd_entrega', 'qtd_transferencia', 'qtd_coleta', 'qtd_despacho', 'qtd_retirada'])
            modificou = True

        if modificou:
            log.info(f"✨ [AUTO-HEAL WEBHOOK] Manifesto #{manifesto.numero_manifesto} sincronizado com sucesso! Entregas: {tot_ent}, Transferências: {tot_tra}")
            try:
                enviar_painel(manifesto)
            except Exception:
                pass
        return modificou

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"⚠️ Erro ao sincronizar manifesto individual com webhook: {e}")
        return False


def sincronizar_manifestos_webhook_divergentes():
    """
    Executa a sincronização em todos os manifestos ativos para garantir integridade entre painel e webhooks.
    """
    try:
        from manifesto.models import Manifesto
        ativos = Manifesto.objects.filter(status__in=['AGUARDANDO', 'EM_TRANSPORTE'])
        for m in ativos:
            sincronizar_manifesto_individual_webhook(m)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"⚠️ Erro ao sincronizar manifestos divergentes: {e}")


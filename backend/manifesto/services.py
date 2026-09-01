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
            "remover": remover,
            "total": total_notas, 
            "data_registro": data_registro,
            "data_criacao_iso": manifesto.data_criacao.isoformat() if manifesto.data_criacao else None,
            "ultimo_acesso_iso": localtime(manifesto.ultimo_acesso).isoformat() if manifesto.ultimo_acesso else None,
            "is_antigo": getattr(manifesto, 'is_antigo', False),
            "dias_criado": getattr(manifesto, 'dias_criado', 0)
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

    # Se já está finalizado, garante consistência e retorna sucesso
    if manifesto.finalizado or manifesto.status == 'FINALIZADO':
        if km_final and str(km_final).strip() not in ["0", "0.0", ""]:
            try:
                manifesto.km_final = km_final
                manifesto.save(update_fields=['km_final'])
            except Exception:
                pass
        return True, "Manifesto já se encontra finalizado."

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

        # Notifica a Torre de Controle via WebSocket
        try:
            enviar_painel(manifesto_atualizado)
        except Exception as p_err:
            logger.error(f"Erro ao enviar painel na auto-finalização do manifesto #{manifesto.id}: {p_err}")

        # Dispara integração de encerramento no TMS ESL Cloud em background
        try:
            from manifesto.tasks import finalizar_manifesto_tms_task
            finalizar_manifesto_tms_task.delay(manifesto_atualizado.id)
        except Exception as tms_err:
            logger.error(f"Erro ao agendar task finalizar_manifesto_tms_task #{manifesto.id}: {tms_err}")

        return True, f"Manifesto #{manifesto.numero_manifesto} finalizado automaticamente com sucesso!"

    except Exception as e_final:
        logger.error(f"Erro crítico ao auto-finalizar manifesto #{manifesto.id}: {e_final}")
        return False, f"Erro ao auto-finalizar: {str(e_final)}"


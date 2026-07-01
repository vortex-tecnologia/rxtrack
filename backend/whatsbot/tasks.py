"""
whatsbot/tasks.py — Celery Tasks do Bot WhatsApp

Fluxo do dia:
    11h → Busca TMS + salva JSON + 1ª notificação (informativa)
    12h → Releitura cache (sem TMS) + 2ª notificação (lembrete)
    14h → Nova busca TMS + atualiza JSON + 3ª notificação (cobrança)
    15h → Releitura cache (sem TMS) + 4ª notificação (urgência)
    16h → Nova busca TMS + atualiza JSON + 5ª notificação (última chamada)
"""

import re
import json
import logging
import requests
from datetime import date

from celery import shared_task
from django.utils import timezone
from django.db import IntegrityError

logger = logging.getLogger(__name__)


# =====================================================================
# TEMPLATES DE MENSAGENS (progressivas ao longo do dia)
# =====================================================================

MENSAGENS_ATIVACAO = {
    1: (
        "🚛 Bom dia, {nome}! Informamos que o manifesto *#{numero}* "
        "foi gerado em seu nome.\n"
        "Acesse o aplicativo *QuickTrack* e ative o manifesto para "
        "iniciar seus registros de entrega.\n"
        "Bom trabalho! 💪"
    ),
    2: (
        "📋 Olá, {nome}. Verificamos que o manifesto *#{numero}* "
        "ainda não foi ativado no aplicativo.\n"
        "Pedimos que acesse o *QuickTrack* e realize a ativação "
        "para que suas entregas sejam registradas corretamente."
    ),
    3: (
        "⏰ *{nome}*, o manifesto *#{numero}* segue aguardando ativação "
        "desde o início do dia.\n"
        "Por favor, acesse o app e ative-o o quanto antes para evitar "
        "atrasos nos registros de ocorrências."
    ),
    4: (
        "🔔 *Atenção, {nome}!* Já são 15h e o manifesto *#{numero}* "
        "permanece sem ativação.\n"
        "Ative agora pelo app *QuickTrack* para garantir que todas as "
        "ocorrências do dia sejam registradas a tempo."
    ),
    5: (
        "🚨 *Última notificação do dia, {nome}.*\n"
        "O manifesto *#{numero}* ainda não foi ativado. Caso não seja "
        "ativado, as entregas realizadas ficarão sem registro no sistema.\n"
        "Ative *imediatamente* pelo app QuickTrack."
    ),
}

MENSAGEM_PENDENCIA = (
    "⚠️ *Atenção, {nome}!* Um novo manifesto *#{numero_novo}* foi gerado "
    "em seu nome, porém o manifesto *#{numero_antigo}* do dia *{data_antigo}* "
    "ainda está em transporte e não foi finalizado.\n\n"
    "É necessário finalizar o manifesto anterior para iniciar o novo. "
    "Caso contrário, haverá atraso nas ocorrências do novo serviço gerado."
)


# =====================================================================
# MAPEAMENTO DE RODADAS POR HORA
# =====================================================================

HORA_PARA_RODADA = {
    11: 1,
    12: 2,
    14: 3,
    15: 4,
    16: 5,
}


# =====================================================================
# UTILITÁRIOS
# =====================================================================

def _limpar_telefone(telefone):
    """
    Limpa o telefone e garante formato internacional (5511999999999).
    Retorna None se o telefone for inválido.
    """
    if not telefone:
        return None
    numeros = re.sub(r'\D', '', telefone)
    if len(numeros) == 11:  # DDD + 9 dígitos
        numeros = '55' + numeros
    elif len(numeros) == 10:  # DDD + 8 dígitos (formato antigo)
        numeros = '55' + numeros
    elif len(numeros) == 13 and numeros.startswith('55'):
        pass  # Já está no formato correto
    elif len(numeros) < 10:
        return None
    return numeros


def _obter_rodada_atual():
    """Determina a rodada com base na hora atual."""
    hora = timezone.localtime().hour
    return HORA_PARA_RODADA.get(hora, 1)


# =====================================================================
# BUSCA NO TMS (usa o mesmo endpoint report_validacao do ESL)
# =====================================================================

def _buscar_manifestos_do_dia_no_tms(filial, data_hoje):
    """
    Consulta o TMS (ESL) para obter todos os manifestos do dia de uma filial.
    Usa o mesmo endpoint report_validacao que já é usado na validação de CPF.
    Filtra pelo id_filial_tms que já temos registrado no banco.
    """
    from configuracao.utils import get_config
    config = get_config()

    if not config.enviar_tms:
        logger.info("🔕 Integração TMS desativada. Pulando busca no TMS.")
        return []

    token = config.token_analytics
    url = (
        f"https://{config.dominio_esl}/api/analytics/reports/"
        f"{config.report_validacao}/data"
    )

    data_str = data_hoje.strftime('%Y-%m-%d')
    payload = {
        "search": {
            "manifests": {
                "service_date": f"{data_str} - {data_str}"
            }
        },
        "page": "1",
        "per": "200"
    }

    # Se a filial tem ID no TMS, filtra diretamente na busca
    if filial.id_filial_tms:
        payload["search"]["manifests"]["crn_id"] = int(filial.id_filial_tms)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(
            url, headers=headers,
            data=json.dumps(payload),
            timeout=30
        )
        response.raise_for_status()
        dados = response.json()

        if not isinstance(dados, list):
            dados = []

        # Filtro extra de segurança: se filtramos por crn_id no payload
        # mas a API não suportou, filtramos aqui
        if filial.id_filial_tms:
            dados = [
                d for d in dados
                if str(d.get('mft_crn_id', '')) == str(filial.id_filial_tms)
            ]

        logger.info(
            f"📡 TMS retornou {len(dados)} manifesto(s) para "
            f"filial {filial.nome} em {data_str}"
        )
        return dados

    except Exception as e:
        logger.error(
            f"❌ Erro ao buscar manifestos no TMS para filial {filial.nome}: {e}"
        )
        return []


def _sincronizar_cache_tms(filial, data_hoje, dados_tms):
    """
    Salva ou atualiza o cache do JSON do TMS para esta filial/dia.
    """
    from whatsbot.models import ManifestoBotCache

    # Usa um set para deduplicar, já que o TMS retorna uma linha por NF-e do mesmo manifesto
    numeros = list(set([str(d.get('sequence_code', '')) for d in dados_tms if d.get('sequence_code')]))

    cache_obj, _ = ManifestoBotCache.objects.update_or_create(
        filial=filial,
        data_referencia=data_hoje,
        defaults={
            'payload_tms': dados_tms,
            'manifestos_encontrados': numeros,
            'total_manifestos': len(numeros),
        }
    )
    return cache_obj


# (Lógica de criação de manifestos removida para evitar poluição do banco de dados)


# =====================================================================
# ENVIO DE NOTIFICAÇÕES
# =====================================================================

def _notificar_motorista(filial, motorista, numero_mft, rodada, data_hoje):
    """
    Envia notificação WhatsApp para o motorista de um manifesto não ativado.
    Verifica se já foi notificado nesta rodada e se tem manifesto anterior pendente.
    """
    from whatsbot.models import NotificacaoManifestoLog
    from whatsbot.registry import get_whatsapp_adapter
    from manifesto.models import Manifesto

    # Já foi notificado nesta rodada? Se sim, pula
    ja_notificado = NotificacaoManifestoLog.objects.filter(
        motorista=motorista,
        numero_manifesto_tms=numero_mft,
        rodada=rodada,
        data_referencia=data_hoje
    ).exists()

    if ja_notificado:
        return

    # Limpa o telefone
    telefone = _limpar_telefone(motorista.telefone) if motorista else None
    if not motorista or not telefone:
        try:
            NotificacaoManifestoLog.objects.create(
                motorista=motorista if motorista else None,
                numero_manifesto_tms=numero_mft,
                filial=filial,
                data_referencia=data_hoje,
                rodada=rodada,
                tipo_mensagem='ATIVACAO' if rodada == 1 else 'PENDENCIA',
                mensagem_enviada="[Não enviada - Motorista sem telefone ou não encontrado]",
                provedor_usado="N/A",
                instancia_usada="N/A",
                numero_destino="N/A",
                status='SEM_TELEFONE'
            )
        except Exception:
            pass
        return

    # Verifica se tem manifesto anterior EM_TRANSPORTE (pendência)
    from manifesto.models import Manifesto
    
    manifesto_anterior = Manifesto.objects.filter(
        motorista=motorista,
        status='EM_TRANSPORTE'
    ).exclude(numero_manifesto=numero_mft).order_by('-data_criacao').first()

    # Monta a mensagem
    nome = motorista.nome_completo.split()[0]  # Primeiro nome

    if manifesto_anterior:
        data_antigo = timezone.localtime(manifesto_anterior.data_criacao).strftime('%d/%m/%Y')
        mensagem = MENSAGEM_PENDENCIA.format(
            nome=nome,
            numero_novo=numero_mft,
            numero_antigo=manifesto_anterior.numero_manifesto,
            data_antigo=data_antigo
        )
        tipo = 'PENDENCIA'
    else:
        template = MENSAGENS_ATIVACAO.get(rodada, MENSAGENS_ATIVACAO[1])
        mensagem = template.format(
            nome=nome,
            numero=numero_mft
        )
        tipo = 'ATIVACAO'

    # Obtém o adapter WhatsApp da filial
    adapter = get_whatsapp_adapter(filial)
    if not adapter:
        logger.warning(f"⚠️ Sem adapter WhatsApp para filial {filial.nome}")
        return

    # Envia a mensagem
    provedor_nome = adapter.provedor.nome
    instancia_nome = adapter.instancia.nome_instancia

    try:
        resposta = adapter.enviar_texto(telefone, mensagem)
        NotificacaoManifestoLog.objects.create(
            motorista=motorista,
            numero_manifesto_tms=numero_mft,
            filial=filial,
            data_referencia=data_hoje,
            rodada=rodada,
            tipo_mensagem=tipo,
            mensagem_enviada=mensagem,
            provedor_usado=provedor_nome,
            instancia_usada=instancia_nome,
            numero_destino=telefone,
            status='ENVIADO',
            resposta_api=resposta,
        )
        logger.info(
            f"✅ Notificação R{rodada} enviada para {motorista.nome_completo} "
            f"(*Rodada {rodada}/5* | *MFT #{numero_mft}*)"
        )
    except Exception as e:
        logger.error(
            f"❌ Falha ao enviar para {motorista.nome_completo}: {e}"
        )


# =====================================================================
# LÓGICA PRINCIPAL (executada dentro do contexto do tenant)
# =====================================================================

def _executar_busca_tms_e_notificacao():
    """
    Lógica executada nas rodadas com busca TMS (11h, 14h, 16h).
    1. Busca manifestos do dia no TMS por filial
    2. Cria manifestos faltantes no banco local
    3. Salva/atualiza cache JSON
    4. Notifica motoristas com manifestos não ativados
    """
    from usuarios.models import Filial, Motorista
    from manifesto.models import Manifesto
    from whatsbot.models import WhatsAppInstancia

    data_hoje = date.today()
    rodada = _obter_rodada_atual()

    # Filiais que possuem instância WhatsApp ativa
    filiais_ids = WhatsAppInstancia.objects.filter(
        ativo=True, provedor__ativo=True
    ).values_list('filial_id', flat=True)

    filiais = Filial.objects.filter(id__in=filiais_ids)

    if not filiais.exists():
        logger.info("ℹ️ Nenhuma filial com WhatsApp ativo. Bot encerrado.")
        return

    total_notificacoes = 0

    for filial in filiais:
        try:
            # 1. Busca no TMS
            dados_tms = _buscar_manifestos_do_dia_no_tms(filial, data_hoje)

            # 2. Atualiza cache com todos os manifestos do dia (para consultas e auditoria)
            _sincronizar_cache_tms(filial, data_hoje, dados_tms)

            # 3. Varre os manifestos retornados pelo TMS e vê quais NÃO existem no nosso banco
            manifestos_processados = set()
            notificados_nesta_filial = 0

            for item in dados_tms:
                numero_mft = str(item.get('sequence_code', ''))
                cpf_tms = str(item.get('mft_mdr_iil_document', '')).strip().replace('.', '').replace('-', '')
                
                if not numero_mft or numero_mft in manifestos_processados:
                    continue
                
                manifestos_processados.add(numero_mft)

                # Se já existe no banco, o motorista já "ativou". Ignora!
                if Manifesto.objects.filter(numero_manifesto=numero_mft).exists():
                    continue

                # Motorista ainda NÃO "ativou". Precisamos notificar!
                motorista = None
                if cpf_tms:
                    motorista = Motorista.objects.filter(cpf=cpf_tms).first()

                if motorista:
                    _notificar_motorista(filial, motorista, numero_mft, rodada, data_hoje)
                    notificados_nesta_filial += 1
                    total_notificacoes += 1
            
            if notificados_nesta_filial > 0:
                logger.info(f"🔎 {notificados_nesta_filial} motorista(s) aguardando ativação notificados em {filial.nome}")

        except Exception as e:
            logger.error(f"❌ Erro no bot para filial {filial.nome}: {e}")
            continue

    logger.info(
        f"🤖 Bot R{rodada} finalizado: "
        f"{total_notificacoes} motorista(s) processado(s) "
        f"em {filiais.count()} filial(is)"
    )


def _executar_releitura_cache_e_notificacao():
    """
    Lógica executada nas rodadas SEM busca TMS (12h, 15h).
    Apenas relê o banco local para verificar quem ainda não ativou.
    NÃO faz chamada ao TMS (economia de requisições).
    """
    from usuarios.models import Filial
    from manifesto.models import Manifesto
    from whatsbot.models import WhatsAppInstancia, ManifestoBotCache
    from django.db.models import Q

    data_hoje = date.today()
    rodada = _obter_rodada_atual()

    filiais_ids = WhatsAppInstancia.objects.filter(
        ativo=True, provedor__ativo=True
    ).values_list('filial_id', flat=True)

    filiais = Filial.objects.filter(id__in=filiais_ids)

    if not filiais.exists():
        logger.info("ℹ️ Nenhuma filial com WhatsApp ativo. Bot encerrado.")
        return

    total_notificacoes = 0

    for filial in filiais:
        try:
            cache = ManifestoBotCache.objects.filter(filial=filial, data_referencia=data_hoje).first()
            if not cache:
                continue

            dados_tms = cache.payload_tms
            
            manifestos_processados = set()
            notificados_nesta_filial = 0

            for item in dados_tms:
                numero_mft = str(item.get('sequence_code', ''))
                cpf_tms = str(item.get('mft_mdr_iil_document', '')).strip().replace('.', '').replace('-', '')
                
                if not numero_mft or numero_mft in manifestos_processados:
                    continue
                
                manifestos_processados.add(numero_mft)

                if Manifesto.objects.filter(numero_manifesto=numero_mft).exists():
                    continue

                motorista = None
                if cpf_tms:
                    from usuarios.models import Motorista
                    motorista = Motorista.objects.filter(cpf=cpf_tms).first()

                if motorista:
                    _notificar_motorista(filial, motorista, numero_mft, rodada, data_hoje)
                    notificados_nesta_filial += 1
                    total_notificacoes += 1
                    
            if notificados_nesta_filial > 0:
                logger.info(f"🔎 {notificados_nesta_filial} motorista(s) aguardando ativação notificados em {filial.nome}")

        except Exception as e:
            logger.error(f"❌ Erro no bot para filial {filial.nome}: {e}")
            continue

    logger.info(
        f"🤖 Bot R{rodada} (cache) finalizado: "
        f"{total_notificacoes} motorista(s) processado(s)"
    )


# =====================================================================
# TASKS CELERY (chamadas pelo Celery Beat)
# =====================================================================

@shared_task(bind=True, max_retries=1)
def bot_buscar_tms_e_notificar(self):
    """
    Task agendada para 11h, 14h e 16h.
    Busca manifestos no TMS, atualiza o cache JSON e envia notificações.
    Itera sobre todos os tenants (Multi-SaaS).
    """
    try:
        from tenants.models import Client
        from django_tenants.utils import schema_context

        tenants = Client.objects.exclude(schema_name='public')
        for tenant in tenants:
            with schema_context(tenant.schema_name):
                logger.info(f"🏢 Bot TMS+Notif executando no tenant: {tenant.schema_name}")
                _executar_busca_tms_e_notificacao()

    except Exception as e:
        logger.error(f"❌ Erro fatal no bot (busca TMS): {e}")
        raise self.retry(exc=e, countdown=300)


@shared_task(bind=True, max_retries=1)
def bot_reler_cache_e_notificar(self):
    """
    Task agendada para 12h e 15h.
    NÃO consulta o TMS. Apenas relê o banco local e reenvia
    notificações para motoristas que ainda não ativaram.
    Itera sobre todos os tenants (Multi-SaaS).
    """
    try:
        from tenants.models import Client
        from django_tenants.utils import schema_context

        tenants = Client.objects.exclude(schema_name='public')
        for tenant in tenants:
            with schema_context(tenant.schema_name):
                logger.info(f"🏢 Bot Cache+Notif executando no tenant: {tenant.schema_name}")
                _executar_releitura_cache_e_notificacao()

    except Exception as e:
        logger.error(f"❌ Erro fatal no bot (cache/releitura): {e}")
        raise self.retry(exc=e, countdown=300)


@shared_task(bind=True)
def enviar_mensagem_massa_motoristas_task(self, filial_id, mensagem):
    """
    Envia uma mensagem em massa para todos os motoristas de uma filial específica
    ou para todas as filiais caso não seja informada.
    Essa task roda dentro do schema logado (já garantido se enfileirada no tenant).
    """
    from usuarios.models import Motorista
    from usuarios.models import Filial
    from whatsbot.registry import get_whatsapp_adapter

    # 1. Obter a filial ou filiais
    if filial_id and str(filial_id).lower() != 'todas':
        filiais = Filial.objects.filter(id=filial_id)
    else:
        filiais = Filial.objects.all()

    total_enviados = 0
    total_erros = 0

    for filial in filiais:
        adapter = get_whatsapp_adapter(filial)
        if not adapter:
            logger.warning(f"Filial {filial.nome} não possui WhatsApp ativo configurado. Pulando...")
            continue

        motoristas = Motorista.objects.filter(filial=filial, tipo_usuario='MOTORISTA').exclude(telefone__isnull=True).exclude(telefone__exact='')

        for motorista in motoristas:
            telefone = _limpar_telefone(motorista.telefone)
            if telefone:
                try:
                    adapter.enviar_texto(telefone, mensagem)
                    total_enviados += 1
                except Exception as e:
                    logger.error(f"Erro ao enviar aviso em massa para {motorista.nome_completo}: {e}")
                    total_erros += 1
                    
    logger.info(f"✅ Disparo em massa concluído! Enviados: {total_enviados} | Erros: {total_erros}")
    return f"Enviados: {total_enviados}, Erros: {total_erros}"


# =====================================================================
# LEMBRETE DE FINALIZAÇÃO (20:00)
# =====================================================================

def _executar_lembrete_finalizacao():
    from manifesto.models import Manifesto
    from usuarios.models import Filial
    from whatsbot.registry import get_whatsapp_adapter
    from django.utils import timezone
    
    filiais = Filial.objects.filter(ativo=True)
    total_notificacoes = 0
    
    for filial in filiais:
        adapter = get_whatsapp_adapter(filial)
        if not adapter:
            continue
            
        # Busca manifestos Em Transporte do dia atual e dias anteriores
        # Caso tenha esquecido de finalizar rotas antigas, avisará também
        manifestos_pendentes = Manifesto.objects.filter(
            filial=filial, 
            status='EM_TRANSPORTE'
        ).exclude(motorista__isnull=True)
        
        for manifesto in manifestos_pendentes:
            telefone = _limpar_telefone(manifesto.motorista.telefone) if manifesto.motorista else None
            if not telefone:
                continue
                
            mensagem = (
                f"Olá {manifesto.motorista.nome_completo.split()[0]}! 🌙 Passando para lembrar que "
                f"o seu manifesto *{manifesto.numero_manifesto}* consta como 'Em Rota' no nosso sistema.\n\n"
                f"Se você ainda estiver na estrada, pode desconsiderar essa mensagem. "
                f"Mas se já finalizou a sua viagem de hoje, por favor, abra o aplicativo e termine de dar "
                f"as baixas, anexando as fotos e ocorrências. Assim seu app já fica liberado para uma nova rota amanhã! 🚚💨"
            )
            
            try:
                adapter.enviar_texto(telefone, mensagem)
                total_notificacoes += 1
                logger.info(f"📲 Lembrete enviado para {manifesto.motorista.nome_completo} (MFT: {manifesto.numero_manifesto})")
            except Exception as e:
                logger.error(f"Erro ao enviar lembrete para {manifesto.motorista.nome_completo}: {e}")
                
    return total_notificacoes


@shared_task(bind=True, max_retries=1)
def bot_lembrete_finalizacao_20h(self):
    """
    Task agendada para 20h.
    Verifica todos os manifestos 'EM_TRANSPORTE' e envia lembrete para os motoristas.
    Itera sobre todos os tenants (Multi-SaaS).
    """
    try:
        from tenants.models import Client
        from django_tenants.utils import schema_context

        tenants = Client.objects.exclude(schema_name='public')
        total_geral = 0
        for tenant in tenants:
            with schema_context(tenant.schema_name):
                logger.info(f"🏢 Bot Lembrete 20h executando no tenant: {tenant.schema_name}")
                qtd = _executar_lembrete_finalizacao()
                total_geral += qtd
                
        logger.info(f"🏁 Bot Lembrete 20h Finalizado! Total de lembretes enviados: {total_geral}")

    except Exception as e:
        logger.error(f"❌ Erro fatal no bot de lembrete: {e}")
        raise self.retry(exc=e, countdown=300)


# =====================================================================
# RELATÓRIO DIÁRIO (22:00) PARA GRUPOS
# =====================================================================

def _executar_relatorio_grupos():
    from manifesto.models import Manifesto
    from usuarios.models import Filial
    from configuracao.models import ConfiguracaoSistema
    from whatsbot.registry import get_whatsapp_adapter
    from django.utils import timezone
    
    config = ConfiguracaoSistema.load()
    grupos_str = config.grupos_relatorio_whatsapp.strip()
    
    if not grupos_str:
        return 0
        
    grupos_lista = [g.strip() for g in grupos_str.split(',') if g.strip()]
    
    hoje = timezone.now().date()
    
    filiais = Filial.objects.filter(ativo=True)
    total_envios = 0
    
    for filial in filiais:
        adapter = get_whatsapp_adapter(filial)
        if not adapter:
            continue
            
        manifestos = Manifesto.objects.filter(
            filial=filial, 
            data_criacao__date=hoje
        ).prefetch_related('notas_fiscais')
        
        if not manifestos.exists():
            continue
            
        mensagens_mft = []
        
        for mft in manifestos:
            nome_motorista = mft.motorista.nome_completo if mft.motorista else "Sem motorista"
            
            # Conta tipos
            total_notas = mft.notas_fiscais.filter(tipo__in=['ENTREGA', 'PROBLEMA']).count()
            total_coletas = mft.notas_fiscais.filter(tipo='COLETA').count()
            
            notas_baixadas = mft.notas_fiscais.filter(tipo__in=['ENTREGA', 'PROBLEMA'], status='BAIXADA').count()
            coletas_baixadas = mft.notas_fiscais.filter(tipo='COLETA', status='BAIXADA').count()
            
            falta_notas = total_notas - notas_baixadas
            falta_coletas = total_coletas - coletas_baixadas
            
            status_str = ""
            if mft.status == 'FINALIZADO':
                status_str = "✅ *Status:* Finalizado perfeitamente!"
            else:
                detalhes_falta = []
                if falta_notas > 0:
                    detalhes_falta.append(f"{falta_notas} notas")
                if falta_coletas > 0:
                    detalhes_falta.append(f"{falta_coletas} coletas")
                
                texto_falta = " e ".join(detalhes_falta)
                status_str = f"⚠️ *Status:* Não finalizado até o momento. Falta finalizar {texto_falta}."
            
            mft_texto = (
                f"📦 *Manifesto {mft.numero_manifesto}*\n"
                f"👤 *Motorista:* {nome_motorista}\n"
                f"📝 *Notas:* {total_notas} | 🔄 *Coletas:* {total_coletas}\n"
                f"{status_str}"
            )
            mensagens_mft.append(mft_texto)
            
        if not mensagens_mft:
            continue
            
        tms_nome = dict(ConfiguracaoSistema.TMS_CHOICES).get(config.tms_provider, "TMS")
        
        rodape = (
            f"\n\n🤖 _Esta mensagem é automática do sistema de entregas._\n"
            f"_Os manifestos finalizados no aplicativo com todas as notas e coletas registradas foram finalizados também no {tms_nome}, porém os km finais não foram registrados, necessário ser colocado manual._\n"
            f"_Para manifestos ainda em transporte, verifique com o motorista o motivo de ainda haver notas pendentes._"
        )
        
        mensagem_completa = f"📊 *Resumo da Operação - {hoje.strftime('%d/%m/%Y')}*\n\n" + "\n\n".join(mensagens_mft) + rodape
        
        for jid in grupos_lista:
            try:
                adapter.enviar_texto(jid, mensagem_completa)
                total_envios += 1
                logger.info(f"📲 Relatório Diário enviado para o grupo {jid}")
            except Exception as e:
                logger.error(f"Erro ao enviar relatório para o grupo {jid}: {e}")
                
    return total_envios


@shared_task(bind=True, max_retries=1)
def bot_relatorio_diario_grupos(self):
    """
    Task agendada para 22h.
    Busca os manifestos do dia e envia o relatório consolidado para os grupos do WhatsApp.
    Itera sobre todos os tenants (Multi-SaaS).
    """
    try:
        from tenants.models import Client
        from django_tenants.utils import schema_context

        tenants = Client.objects.exclude(schema_name='public')
        total_geral = 0
        for tenant in tenants:
            with schema_context(tenant.schema_name):
                logger.info(f"🏢 Bot Relatório 22h executando no tenant: {tenant.schema_name}")
                qtd = _executar_relatorio_grupos()
                total_geral += qtd
                
        logger.info(f"🏁 Bot Relatório 22h Finalizado! Relatórios enviados: {total_geral}")

    except Exception as e:
        logger.error(f"❌ Erro fatal no bot de relatório: {e}")
        raise self.retry(exc=e, countdown=300)

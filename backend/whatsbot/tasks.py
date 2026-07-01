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

    numeros = [str(d.get('mft_sequence_code', '')) for d in dados_tms if d.get('mft_sequence_code')]

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


def _criar_manifestos_faltantes(filial, dados_tms):
    """
    Para cada manifesto retornado pelo TMS que NÃO existe no banco local,
    cria um registro com status AGUARDANDO para que o bot possa notificar.
    """
    from manifesto.models import Manifesto
    from usuarios.models import Motorista

    criados = 0
    for item in dados_tms:
        numero_mft = str(item.get('mft_sequence_code', ''))
        if not numero_mft:
            continue

        # Se já existe no banco, não recria
        if Manifesto.objects.filter(numero_manifesto=numero_mft).exists():
            continue

        # Busca o motorista pelo CPF retornado no TMS
        cpf_tms = str(item.get('mft_mdr_iil_document', '')).strip().replace('.', '').replace('-', '')
        motorista = None
        if cpf_tms:
            motorista = Motorista.objects.filter(cpf=cpf_tms).first()

        try:
            Manifesto.objects.create(
                numero_manifesto=numero_mft,
                motorista=motorista,
                filial=filial,
                status='AGUARDANDO',
                manifesto_id_tms=item.get('id'),
            )
            criados += 1
            logger.info(f"📦 Manifesto #{numero_mft} criado pelo bot (filial {filial.nome})")
        except IntegrityError:
            # Pode acontecer se outro processo criou entre o check e o create
            continue

    return criados


# =====================================================================
# ENVIO DE NOTIFICAÇÕES
# =====================================================================

def _notificar_motorista(filial, manifesto, rodada, data_hoje):
    """
    Envia notificação WhatsApp para o motorista de um manifesto não ativado.
    Verifica se já foi notificado nesta rodada e se tem manifesto anterior pendente.
    """
    from whatsbot.models import NotificacaoManifestoLog
    from whatsbot.registry import get_whatsapp_adapter
    from manifesto.models import Manifesto

    motorista = manifesto.motorista
    if not motorista:
        return

    # Já foi notificado nesta rodada? Se sim, pula
    ja_notificado = NotificacaoManifestoLog.objects.filter(
        motorista=motorista,
        manifesto=manifesto,
        rodada=rodada,
        data_referencia=data_hoje
    ).exists()

    if ja_notificado:
        return

    # Limpa o telefone
    telefone = _limpar_telefone(motorista.telefone)
    if not telefone:
        # Registra que não tem telefone
        try:
            NotificacaoManifestoLog.objects.create(
                motorista=motorista,
                manifesto=manifesto,
                filial=filial,
                data_referencia=data_hoje,
                rodada=rodada,
                tipo_mensagem='ATIVACAO',
                mensagem_enviada='[SEM TELEFONE CADASTRADO]',
                provedor_usado='nenhum',
                instancia_usada='nenhum',
                numero_destino='',
                status='SEM_TELEFONE',
            )
        except IntegrityError:
            pass
        return

    # Verifica se tem manifesto anterior EM_TRANSPORTE (pendência)
    manifesto_anterior = Manifesto.objects.filter(
        motorista=motorista,
        status='EM_TRANSPORTE',
        data_criacao__lt=manifesto.data_criacao
    ).order_by('-data_criacao').first()

    # Monta a mensagem
    nome = motorista.nome_completo.split()[0]  # Primeiro nome

    if manifesto_anterior:
        data_antigo = timezone.localtime(manifesto_anterior.data_criacao).strftime('%d/%m/%Y')
        mensagem = MENSAGEM_PENDENCIA.format(
            nome=nome,
            numero_novo=manifesto.numero_manifesto,
            numero_antigo=manifesto_anterior.numero_manifesto,
            data_antigo=data_antigo
        )
        tipo = 'PENDENCIA'
    else:
        template = MENSAGENS_ATIVACAO.get(rodada, MENSAGENS_ATIVACAO[1])
        mensagem = template.format(
            nome=nome,
            numero=manifesto.numero_manifesto
        )
        tipo = 'ATIVACAO'

    # Obtém o adapter WhatsApp da filial
    adapter = get_whatsapp_adapter(filial)
    if not adapter:
        logger.warning(f"⚠️ Sem adapter WhatsApp para filial {filial.nome}")
        try:
            NotificacaoManifestoLog.objects.create(
                motorista=motorista,
                manifesto=manifesto,
                filial=filial,
                data_referencia=data_hoje,
                rodada=rodada,
                tipo_mensagem=tipo,
                mensagem_enviada=mensagem,
                provedor_usado='nenhum',
                instancia_usada='nenhum',
                numero_destino=telefone,
                status='ERRO',
                erro_detalhe='Nenhum provedor/instância WhatsApp ativo para esta filial.',
            )
        except IntegrityError:
            pass
        return

    # Envia a mensagem
    provedor_nome = adapter.provedor.nome
    instancia_nome = adapter.instancia.nome_instancia

    try:
        resposta = adapter.enviar_texto(telefone, mensagem)
        NotificacaoManifestoLog.objects.create(
            motorista=motorista,
            manifesto=manifesto,
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
            f"(MFT #{manifesto.numero_manifesto})"
        )
    except Exception as e:
        try:
            NotificacaoManifestoLog.objects.create(
                motorista=motorista,
                manifesto=manifesto,
                filial=filial,
                data_referencia=data_hoje,
                rodada=rodada,
                tipo_mensagem=tipo,
                mensagem_enviada=mensagem,
                provedor_usado=provedor_nome,
                instancia_usada=instancia_nome,
                numero_destino=telefone,
                status='ERRO',
                erro_detalhe=str(e)[:500],
            )
        except IntegrityError:
            pass
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
    from usuarios.models import Filial
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

            # 2. Cria manifestos faltantes
            if dados_tms:
                criados = _criar_manifestos_faltantes(filial, dados_tms)
                if criados:
                    logger.info(f"📦 {criados} manifesto(s) novo(s) criado(s) para {filial.nome}")

            # 3. Atualiza cache
            _sincronizar_cache_tms(filial, data_hoje, dados_tms)

            # 4. Busca manifestos AGUARDANDO no banco local
            manifestos_aguardando = Manifesto.objects.filter(
                filial=filial,
                status='AGUARDANDO',
                data_criacao__date=data_hoje
            ).select_related('motorista')

            # 5. Notifica cada motorista
            for manifesto in manifestos_aguardando:
                _notificar_motorista(filial, manifesto, rodada, data_hoje)
                total_notificacoes += 1

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
    from whatsbot.models import WhatsAppInstancia

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
            manifestos_aguardando = Manifesto.objects.filter(
                filial=filial,
                status='AGUARDANDO',
                data_criacao__date=data_hoje
            ).select_related('motorista')

            for manifesto in manifestos_aguardando:
                _notificar_motorista(filial, manifesto, rodada, data_hoje)
                total_notificacoes += 1

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
        logger.error(f"❌ Erro fatal no bot (releitura cache): {e}")
        raise self.retry(exc=e, countdown=300)

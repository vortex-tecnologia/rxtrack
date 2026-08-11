from celery import shared_task
from django.db import transaction
from manifesto.models import Manifesto, NotaFiscal, Ocorrencia, BaixaNF
from usuarios.models import Motorista, Filial, User
from .services.webpush_service import enviar_notificacao_usuario
from django.utils import timezone
import requests, json
from mobile.models import WebPushSubscription, BuscaDiariaManifestos , ManifestoNotificado
from django.contrib.auth import get_user_model
import logging
from django.utils import timezone
from datetime import datetime, time, timedelta

logger = logging.getLogger(__name__)
@shared_task
def buscar_manifestos_tms():
    from datetime import date
    from configuracao.utils import get_config
    config = get_config()
    URL = f"https://{config.dominio_esl}/api/analytics/reports/{config.report_validacao}/data"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.token_analytics}"
    }

    hoje = date.today().strftime("%Y-%m-%d")

    for filial in Filial.objects.exclude(id_filial_tms__isnull=True):
        payload = {
            "search": {
                "manifests": {
                    "corporation_id": filial.id_filial_tms,
                    "service_date": f"{hoje} - {hoje}"
                }
            },
            "page": "1",
            "per": "100"
        }

        response = requests.get(URL, headers=headers, data=json.dumps(payload))

        if response.status_code == 200:
            data = response.json()

            BuscaDiariaManifestos.objects.create(
                filial=filial,
                json=data
            )

User = get_user_model()

@shared_task
def notificar_manifestos_pendentes():
    logger.info("Task notificar_manifestos_pendentes iniciada")

    # início e fim do dia local
    hoje = timezone.localtime(timezone.now()).date()
    inicio = timezone.make_aware(datetime.combine(hoje, time.min))
    fim = timezone.make_aware(datetime.combine(hoje, time.max))

    # pega todas as buscas do dia
    buscas = BuscaDiariaManifestos.objects.filter(data_criacao__range=(inicio, fim))
    logger.info(f"{buscas.count()} buscas encontradas hoje")

    for busca in buscas:
        manifestos = busca.json
        logger.info(f"{len(manifestos)} manifestos na busca id {busca.id} (filial: {busca.filial})")

        for m in manifestos:
            numero = str(m.get("sequence_code", "")).strip()
            cpf = m.get("mft_mdr_iil_document", "").strip()
            logger.info(f"Processando manifesto {numero} para CPF {cpf}")

            if not numero or not cpf:
                logger.warning("-> Ignorado: dados faltando")
                continue

            # verifica se manifesto já existe
            if Manifesto.objects.filter(numero_manifesto=numero).exists():
                logger.warning("-> Ignorado: manifesto já existe no banco")
                continue

            # tenta achar usuário pelo CPF (no perfil Motorista)
            try:
                user = User.objects.get(motorista_perfil__cpf=cpf)
            except User.DoesNotExist:
                logger.warning("-> Ignorado: usuário não encontrado")
                continue

            # verifica se usuário tem subscriptions
            if not WebPushSubscription.objects.filter(user=user).exists():
                logger.warning(f"-> Ignorado: usuário {user} sem subscriptions")
                continue

            logger.info(f"-> Notificando usuário {user} sobre manifesto {numero}")

            # verifica se já foi notificado recentemente
            obj, created = ManifestoNotificado.objects.get_or_create(
                manifesto=numero,
                motorista=user,
                defaults={"ultima_notificacao": timezone.now()}
            )

            if not created:
                if obj.ultima_notificacao and obj.ultima_notificacao > timezone.now() - timedelta(hours=1):
                    logger.info(f"-> Ignorado: já notificado recentemente")
                    continue
                obj.ultima_notificacao = timezone.now()
                obj.save()

            # envia push
            enviar_notificacao_usuario(
                user,
                "Manifesto disponível",
                f"Manifesto {numero} aguardando importação. Acesse o app para ativar.",
                "/app/"
            )

            # marca como notificado
            obj.ultima_notificacao = timezone.now()
            obj.save()
            logger.info(f"-> Notificação enviada para {user} sobre manifesto {numero}")

    logger.info("Task notificar_manifestos_pendentes concluída")

@shared_task
def verificar_manifestos_ativos():
    # Pega todos os manifestos ativos em transporte
    manifestos_ativos = Manifesto.objects.filter(status='EM_TRANSPORTE')
    logger.info(f"Verificando {manifestos_ativos.count()} manifestos ativos em transporte")

    for manifesto in manifestos_ativos:
        motorista = manifesto.motorista
        if not motorista or not motorista.user:
            logger.warning(f"Manifesto {manifesto.numero_manifesto} não tem motorista associado")
            continue

        # Verifica se ainda existem notas pendentes
        notas_pendentes = manifesto.notas_fiscais.filter(status='PENDENTE')
        logger.info(f"Manifesto {manifesto.numero_manifesto} tem {notas_pendentes.count()} notas pendentes")

        # Verifica se motorista tem subscriptions
        if not WebPushSubscription.objects.filter(user=motorista.user).exists():
            logger.warning(f"Motorista {motorista.user} não possui subscriptions. Ignorando notificação.")
            continue

        # Verifica se já foi notificado recentemente
        obj, created = ManifestoNotificado.objects.get_or_create(
            manifesto=manifesto.numero_manifesto,
            motorista=motorista.user,
            defaults={"ultima_notificacao": timezone.now()}
        )

        if not created:
            # Se notificado nos últimos 60 minutos, ignora
            if obj.ultima_notificacao and obj.ultima_notificacao > timezone.now() - timedelta(minutes=1):
                logger.info(f"Manifesto {manifesto.numero_manifesto} já notificado recentemente")
                continue

        if notas_pendentes.exists():
            # Existe nota pendente → pede para registrar baixas
            mensagem = (
                f"O manifesto {manifesto.numero_manifesto} ainda possui {notas_pendentes.count()} notas pendentes. "
                "Por favor, registre as baixas das notas pendentes."
            )
            titulo = f"Manifesto {manifesto.numero_manifesto} com notas pendentes"
        else:
            # Nenhuma nota pendente, mas manifesto ainda em transporte → lembrar de finalizar
            mensagem = (
                f"O manifesto {manifesto.numero_manifesto} não possui mais notas pendentes. "
                "Lembre-se de finalizar o manifesto no sistema para concluir a entrega."
            )
            titulo = f"Manifesto {manifesto.numero_manifesto} sem notas pendentes"

        # Envia notificação usando função segura
        enviar_notificacao_usuario(motorista.user, titulo, mensagem, "/app/")

        # Atualiza hora da última notificação
        obj.ultima_notificacao = timezone.now()
        obj.save()
        logger.info(f"Notificação enviada para {motorista.user} sobre manifesto {manifesto.numero_manifesto}")
# -*- coding: utf-8 -*-
"""
Comando para separar manifestos que foram indevidamente mesclados.
Exemplo: Um manifesto de ontem (#69244) recebeu notas de hoje (#69311)
devido a um match indevido de notas em rota recorrente.

Este comando:
1. Localiza o manifesto de ontem (origem).
2. Identifica as notas de hoje (via webhook, lista de notas ou status PENDENTE).
3. Cria (ou vincula) o novo manifesto de hoje com as informações do motorista/veículo/filial.
4. Move as notas de hoje para o novo manifesto.
5. Finaliza o manifesto de ontem (status FINALIZADO, finalizado=True).
6. Coloca o manifesto de hoje em EM_TRANSPORTE (ou AGUARDANDO).
7. Recalcula os contadores de entrega/coleta/transferência de ambos.
8. Notifica a Torre de Controle via WebSocket.
"""

import logging
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Separa manifestos que tiveram notas indevidamente mescladas. "
        "Finaliza o manifesto de ontem e cria/move as notas de hoje para um manifesto novo."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--manifesto-origem',
            type=str,
            required=True,
            help='Número do manifesto de ontem que recebeu notas indevidas (ex: 69244)',
        )
        parser.add_argument(
            '--manifesto-novo',
            type=str,
            required=False,
            default='',
            help='Número visual oficial do novo manifesto de hoje (ex: 69311)',
        )
        parser.add_argument(
            '--webhook',
            type=str,
            required=False,
            default='',
            help='Número do manifesto gravado no webhook (ex: ID TMS 6946117 ou ID do evento)',
        )
        parser.add_argument(
            '--tms-id',
            type=str,
            required=False,
            default='',
            help='ID interno TMS do novo manifesto (ex: 6946117), se diferente do número visual',
        )
        parser.add_argument(
            '--notas',
            type=str,
            required=False,
            default='',
            help='Lista de números de NF a mover para o novo manifesto, separados por vírgula (opcional)',
        )
        parser.add_argument(
            '--status-novo',
            type=str,
            default='EM_TRANSPORTE',
            choices=['EM_TRANSPORTE', 'AGUARDANDO'],
            help='Status para o novo manifesto (padrão: EM_TRANSPORTE)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula as alterações sem gravar no banco de dados',
        )
        parser.add_argument(
            '--tenant',
            type=str,
            default='',
            help='Nome do schema/tenant específico para rodar (opcional)',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        origem_num = str(options['manifesto_origem']).strip()
        novo_num = str(options.get('manifesto_novo') or '').strip()
        webhook_ref = str(options.get('webhook') or '').strip()
        tms_id = str(options.get('tms_id') or '').strip()
        notas_filtro = [n.strip() for n in str(options.get('notas') or '').split(',') if n.strip()]
        status_novo = options.get('status_novo', 'EM_TRANSPORTE')
        tenant_especifico = options.get('tenant', '').strip()

        if dry_run:
            self.stdout.write(self.style.WARNING("⚠️  MODO DRY-RUN ATIVADO: Nenhuma alteração será salva no banco."))

        # Suporte a Multi-Tenant (django-tenants)
        try:
            from django_tenants.utils import get_tenant_model, schema_context
            tenant_model = get_tenant_model()
            if tenant_especifico:
                tenants = list(tenant_model.objects.filter(schema_name=tenant_especifico))
                if not tenants:
                    raise CommandError(f"Tenant '{tenant_especifico}' não encontrado.")
            else:
                tenants = list(tenant_model.objects.exclude(schema_name='public'))
        except Exception:
            tenants = []

        if tenants:
            encontrado = False
            for tenant in tenants:
                with schema_context(tenant.schema_name):
                    from manifesto.models import Manifesto
                    m_teste = Manifesto.objects.filter(
                        Q(numero_manifesto=origem_num) | Q(manifesto_id_tms=origem_num)
                    ).first()
                    if m_teste:
                        encontrado = True
                        self.stdout.write(self.style.HTTP_INFO(f"\n🏢 Executando no Tenant: {tenant.schema_name}"))
                        self._executar_separacao(
                            origem_num=origem_num,
                            novo_num=novo_num,
                            webhook_ref=webhook_ref,
                            tms_id=tms_id,
                            notas_filtro=notas_filtro,
                            status_novo=status_novo,
                            dry_run=dry_run
                        )
                        break
            if not encontrado:
                self.stdout.write(self.style.ERROR(f"❌ Manifesto #{origem_num} não encontrado em nenhum tenant."))
        else:
            self._executar_separacao(
                origem_num=origem_num,
                novo_num=novo_num,
                webhook_ref=webhook_ref,
                tms_id=tms_id,
                notas_filtro=notas_filtro,
                status_novo=status_novo,
                dry_run=dry_run
            )

    def _executar_separacao(self, origem_num, novo_num, webhook_ref, tms_id, notas_filtro, status_novo, dry_run):
        from manifesto.models import Manifesto, NotaFiscal, WebhookEventoManifestoESL
        from integracoes.factory import get_tms_adapter

        # 1. Localiza o manifesto de origem (ontem)
        m_origem = Manifesto.objects.filter(
            Q(numero_manifesto=origem_num) | Q(manifesto_id_tms=origem_num)
        ).first()

        if not m_origem:
            self.stdout.write(self.style.ERROR(f"❌ Manifesto de origem #{origem_num} não encontrado."))
            return

        self.stdout.write(self.style.NOTICE(f"📦 Manifesto Origem: #{m_origem.numero_manifesto} (ID: {m_origem.id})"))
        if m_origem.motorista:
            self.stdout.write(f"   Motorista: {m_origem.motorista.nome_completo} (CPF: {m_origem.motorista.cpf})")
        if m_origem.veiculo:
            self.stdout.write(f"   Veículo: {m_origem.veiculo.placa}")
        self.stdout.write(f"   Status Atual: {m_origem.status} | Finalizado: {m_origem.finalizado}")

        notas_totais = list(m_origem.notas_fiscais.all().order_by('id'))
        self.stdout.write(f"   Total de Notas no Manifesto Origem: {len(notas_totais)}")

        # 2. Resolução do número do novo manifesto e ID TMS
        webhook_evento = None
        if webhook_ref:
            if webhook_ref.isdigit() and len(webhook_ref) < 7:
                # Pode ser ID do objeto WebhookEventoManifestoESL
                webhook_evento = WebhookEventoManifestoESL.objects.filter(id=int(webhook_ref)).first()
            if not webhook_evento:
                webhook_evento = WebhookEventoManifestoESL.objects.filter(
                    numero_manifesto=webhook_ref
                ).order_by('-id').first()
        elif not novo_num and m_origem.motorista:
            # Tenta encontrar o webhook de hoje deste motorista
            hoje_inicio = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            candidatos = WebhookEventoManifestoESL.objects.filter(
                created_at__gte=hoje_inicio,
                status='PROCESSADO'
            ).order_by('-id')
            for c in candidatos:
                p_cpf = (c.payload or {}).get('motorista', {}).get('cpf', '')
                if p_cpf and p_cpf in m_origem.motorista.cpf:
                    webhook_evento = c
                    break

        if webhook_evento:
            self.stdout.write(self.style.SUCCESS(f"🔗 Webhook associado: Evento #{webhook_evento.id} (Número: {webhook_evento.numero_manifesto})"))
            if not tms_id:
                tms_id = str(webhook_evento.numero_manifesto or '').strip()

        # Se o número novo não foi fornecido, tenta descobrir via ESL ou Webhook
        if not novo_num:
            if tms_id:
                adapter = get_tms_adapter()
                if adapter and hasattr(adapter, 'resolver_numero_visual_manifesto'):
                    try:
                        res = adapter.resolver_numero_visual_manifesto(tms_id)
                        if res and res.get('sequence_code'):
                            novo_num = str(res['sequence_code']).strip()
                            self.stdout.write(self.style.SUCCESS(f"🎯 Número visual resolvido na ESL: #{novo_num} (TMS ID: {tms_id})"))
                    except Exception as e:
                        logger.warning(f"Erro ao consultar ESL para {tms_id}: {e}")
            if not novo_num and tms_id:
                novo_num = tms_id

        if not novo_num:
            self.stdout.write(self.style.ERROR(
                "❌ Não foi possível determinar o número do novo manifesto. "
                "Informe --manifesto-novo <numero> (ex: --manifesto-novo 69311)."
            ))
            return

        if novo_num == m_origem.numero_manifesto:
            self.stdout.write(self.style.ERROR("❌ O número do novo manifesto não pode ser igual ao de origem."))
            return

        # 3. Determinar quais notas vão para o novo manifesto (hoje) e quais ficam no de ontem
        notas_para_mover = []
        notas_para_ficar = []

        if notas_filtro:
            # Lista explícita fornecida pelo usuário
            for nf in notas_totais:
                if str(nf.numero_nota).strip() in notas_filtro:
                    notas_para_mover.append(nf)
                else:
                    notas_para_ficar.append(nf)
        elif webhook_evento and (webhook_evento.payload or {}).get('itens'):
            # Baseado na lista de itens do webhook
            itens_wh = webhook_evento.payload.get('itens', [])
            nums_wh = {str(it.get('numero_item')).strip() for it in itens_wh if it.get('numero_item')}
            chaves_wh = {str(it.get('chave_item')).strip() for it in itens_wh if it.get('chave_item')}

            for nf in notas_totais:
                match = (
                    str(nf.numero_nota).strip() in nums_wh or
                    (nf.chave_acesso and str(nf.chave_acesso).strip() in chaves_wh)
                )
                # Prioridade: se o item está no webhook e está PENDENTE, move com certeza
                if match:
                    notas_para_mover.append(nf)
                else:
                    notas_para_ficar.append(nf)
        else:
            # Padrão inteligente:
            # Notas com status PENDENTE são de hoje (devem ser movidas).
            # Notas BAIXADA ou OCORRENCIA são de ontem (devem ficar no de ontem).
            for nf in notas_totais:
                if nf.status == 'PENDENTE':
                    notas_para_mover.append(nf)
                else:
                    notas_para_ficar.append(nf)

        self.stdout.write(self.style.NOTICE(f"\n📊 Diagnóstico da Divisão:"))
        self.stdout.write(f"   -> Notas que FICAM em #{m_origem.numero_manifesto} (Ontem): {len(notas_para_ficar)}")
        for n in notas_para_ficar:
            self.stdout.write(f"      • NF {n.numero_nota} | {n.status} | {n.destinatario[:35]}")

        self.stdout.write(f"\n   -> Notas que MUDAM para #{novo_num} (Hoje): {len(notas_para_mover)}")
        for n in notas_para_mover:
            self.stdout.write(f"      • NF {n.numero_nota} | {n.status} | {n.destinatario[:35]}")

        if not notas_para_mover:
            self.stdout.write(self.style.WARNING("\n⚠️ Nenhuma nota selecionada para mover. Operação abortada."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("\n[DRY-RUN] Nenhuma alteração foi persistida no banco de dados."))
            return

        # 4. Execução da separação dentro de transação atômica
        with transaction.atomic():
            # A. Finaliza o manifesto de ontem PRIMEIRO
            # Isso é fundamental para não violar a UniqueConstraint
            # ('um_manifesto_em_transporte_por_motorista') ao criar o novo!
            m_origem.status = 'FINALIZADO'
            m_origem.finalizado = True
            if not m_origem.data_finalizacao:
                m_origem.data_finalizacao = timezone.now()
            m_origem.save(update_fields=['status', 'finalizado', 'data_finalizacao'])
            self.stdout.write(self.style.SUCCESS(f"\n✅ Manifesto de ontem #{m_origem.numero_manifesto} marcado como FINALIZADO."))

            # B. Cria ou obtém o novo manifesto
            m_novo, criado = Manifesto.objects.get_or_create(
                numero_manifesto=novo_num,
                defaults={
                    'manifesto_id_tms': tms_id or (webhook_evento.numero_manifesto if webhook_evento else None),
                    'motorista': m_origem.motorista,
                    'filial': m_origem.filial,
                    'filial_operacao': m_origem.filial_operacao,
                    'veiculo': m_origem.veiculo,
                    'status': status_novo,
                    'finalizado': False,
                    'status_tms': 'in_transit',
                }
            )

            if not criado:
                # Atualiza campos essenciais
                m_novo.motorista = m_origem.motorista
                m_novo.filial = m_origem.filial
                m_novo.filial_operacao = m_origem.filial_operacao
                m_novo.veiculo = m_origem.veiculo
                m_novo.status = status_novo
                m_novo.finalizado = False
                if tms_id and not m_novo.manifesto_id_tms:
                    m_novo.manifesto_id_tms = tms_id
                m_novo.save()
                self.stdout.write(self.style.NOTICE(f"ℹ️  Manifesto #{novo_num} já existia. Reutilizado e atualizado."))
            else:
                self.stdout.write(self.style.SUCCESS(f"✅ Novo manifesto #{novo_num} criado com sucesso (Status: {status_novo})."))

            # C. Move as notas de hoje para o novo manifesto
            ids_mover = [n.id for n in notas_para_mover]
            NotaFiscal.objects.filter(id__in=ids_mover).update(manifesto=m_novo)
            self.stdout.write(self.style.SUCCESS(f"✅ {len(ids_mover)} notas transferidas para o Manifesto #{novo_num}."))

            # D. Recalcula os contadores de carga de ambos os manifestos
            self._recalcular_contadores(m_origem)
            self._recalcular_contadores(m_novo)

            # E. Notifica a Torre de Controle via WebSocket para ambos os manifestos
            try:
                from manifesto.services import enviar_painel
                enviar_painel(m_origem)
                enviar_painel(m_novo)
                self.stdout.write(self.style.SUCCESS("📡 Painel em tempo real (WebSocket) atualizado com sucesso."))
            except Exception as e_ws:
                self.stdout.write(self.style.WARNING(f"Aviso ao notificar painel WebSocket: {e_ws}"))

        self.stdout.write(self.style.SUCCESS(
            f"\n🎉 SUCESSO COMPLETO!\n"
            f"   • Manifesto Ontem #{m_origem.numero_manifesto}: FINALIZADO com {len(notas_para_ficar)} notas.\n"
            f"   • Manifesto Hoje #{m_novo.numero_manifesto}: {status_novo} com {len(notas_para_mover)} notas."
        ))

    def _recalcular_contadores(self, manifesto):
        tot_ent = manifesto.notas_fiscais.filter(tipo_operacao='ENTREGA').count()
        tot_tra = manifesto.notas_fiscais.filter(tipo_operacao='TRANSFERENCIA').count()
        tot_col = manifesto.notas_fiscais.filter(tipo_operacao='COLETA').count()
        tot_des = manifesto.notas_fiscais.filter(tipo_operacao='DESPACHO').count()
        tot_ret = manifesto.notas_fiscais.filter(tipo_operacao='RETIRADA').count()

        manifesto.qtd_entrega = tot_ent
        manifesto.qtd_transferencia = tot_tra
        manifesto.qtd_coleta = tot_col
        manifesto.qtd_despacho = tot_des
        manifesto.qtd_retirada = tot_ret
        manifesto.save(update_fields=[
            'qtd_entrega', 'qtd_transferencia', 'qtd_coleta', 'qtd_despacho', 'qtd_retirada'
        ])

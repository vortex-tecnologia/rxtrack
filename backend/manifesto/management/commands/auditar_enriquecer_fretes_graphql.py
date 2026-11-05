# manifesto/management/commands/auditar_enriquecer_fretes_graphql.py
"""
Comando de auditoria e enriquecimento (backfill) de Fretes e Notas Fiscais/Minutas
via GraphQL da ESL Cloud (`query freight`).

Utiliza sempre os tokens salvos no banco de dados (`ConfiguracaoSistema.token_analytics`
e `ConfiguracaoSistema.token_invoices`).

Exemplos de uso:
  python manage.py auditar_enriquecer_fretes_graphql
  python manage.py auditar_enriquecer_fretes_graphql --manifesto 71318 --enriquecer
  python manage.py auditar_enriquecer_fretes_graphql --dias 15 --enriquecer
  python manage.py auditar_enriquecer_fretes_graphql --apenas-ativos --enriquecer --forcar
"""

from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from integracoes.enriquecimento_frete import enriquecer_manifesto
from configuracao.utils import get_config
from integracoes.providers.esl_graphql import freight_id_valido, limpar_cep
from manifesto.models import Manifesto, NotaFiscal


class Command(BaseCommand):
    help = (
        "Audita e opcionalmente enriquece fretes, minutas e notas fiscais via GraphQL "
        "da ESL Cloud (filial emissora, freight_id interno, CEP, endereço e CT-e)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--manifesto",
            type=str,
            default=None,
            help="Número visual do manifesto específico para auditar/enriquecer (ex: 71318).",
        )
        parser.add_argument(
            "--dias",
            type=int,
            default=30,
            help="Quantidade de dias retroativos para filtrar manifestos (padrão: 30).",
        )
        parser.add_argument(
            "--apenas-ativos",
            action="store_true",
            help="Filtra apenas manifestos em transporte (não finalizados).",
        )
        parser.add_argument(
            "--enriquecer",
            action="store_true",
            help="Executa o enriquecimento via GraphQL na ESL Cloud para preencher lacunas.",
        )
        parser.add_argument(
            "--forcar",
            action="store_true",
            help="Quando usado com --enriquecer, força atualização GraphQL de todas as notas do manifesto.",
        )
        parser.add_argument(
            "--limite",
            type=int,
            default=50,
            help="Limite máximo de manifestos processados por execução (padrão: 50).",
        )
        parser.add_argument(
            "--schema",
            type=str,
            default=None,
            help="Executa apenas em um schema específico (multi-tenant).",
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.NOTICE("🔎 Iniciando Auditoria de Fretes / Filial Emissora / Minutas (ESL GraphQL)...")
        )

        try:
            from django_tenants.utils import get_tenant_model, schema_context

            qs_tenants = get_tenant_model().objects.exclude(schema_name="public")
            if options.get("schema"):
                qs_tenants = qs_tenants.filter(schema_name=options["schema"])
            tenants = list(qs_tenants)
            if tenants:
                for tenant in tenants:
                    with schema_context(tenant.schema_name):
                        self.stdout.write(self.style.HTTP_INFO(f"\n🏢 Tenant: {tenant.schema_name}"))
                        self._executar_no_schema(options)
                return
        except Exception:
            pass

        self._executar_no_schema(options)

    def _executar_no_schema(self, options):
        config = get_config()
        if not config:
            self.stdout.write(self.style.ERROR("❌ ConfiguracaoSistema não encontrada neste tenant."))
            return

        dominio = config.dominio_esl
        token_analytics = config.token_analytics
        token_invoices = config.token_invoices or token_analytics

        self.stdout.write(
            f"   Domínio ESL: {dominio} | Token Analytics no BD: {'✅ Configurado' if token_analytics else '❌ Ausente'}"
        )

        qs = Manifesto.objects.all().select_related("motorista", "filial", "filial_operacao").order_by("-data_criacao")
        if options.get("manifesto"):
            qs = qs.filter(numero_manifesto=str(options["manifesto"]).strip())
        else:
            if options.get("apenas_ativos"):
                qs = qs.filter(status="EM_TRANSPORTE", finalizado=False)
            elif options.get("dias"):
                dt_corte = timezone.now() - timedelta(days=int(options["dias"]))
                qs = qs.filter(data_criacao__gte=dt_corte)

        manifestos = list(qs[: int(options.get("limite") or 50)])
        if not manifestos:
            self.stdout.write(self.style.WARNING("⚠️ Nenhum manifesto encontrado para os filtros informados."))
            return

        if options.get("enriquecer"):
            if not token_analytics:
                self.stdout.write(
                    self.style.ERROR("❌ Impossível enriquecer: token_analytics não está salvo em ConfiguracaoSistema.")
                )
                return

            self.stdout.write(
                self.style.NOTICE(f"⚡ Enriquecendo {len(manifestos)} manifesto(s) via GraphQL da ESL Cloud...")
            )
            for mft in manifestos:
                res = enriquecer_manifesto(
                    config,
                    mft,
                    forcar=bool(options.get("forcar")),
                )
                self.stdout.write(
                    f"   • Manifesto #{mft.numero_manifesto}: "
                    f"fretes_consultados={res.get('fretes_consultados', 0)}, "
                    f"notas_enriquecidas={res.get('notas_enriquecidas', 0)}/{res.get('notas_alvo', 0)}, "
                    f"erros={len(res.get('erros', []))}"
                )

        # Relatório de Auditoria pós-verificação
        total_notas = 0
        com_freight_id = 0
        sem_freight_id = 0
        com_filial_emissora = 0
        sem_filial_emissora = 0
        com_cep = 0
        sem_cep = 0
        com_cte = 0
        minutas_sem_chave = 0
        contagem_emissoras = Counter()
        pendencias = []

        for mft in manifestos:
            notas = (
                NotaFiscal.objects.filter(manifesto=mft)
                .exclude(tipo_operacao="COLETA")
                .select_related("frete", "filial_emissora", "frete__filial_emissora")
            )
            for nf in notas:
                total_notas += 1
                chave_str = str(nf.chave_acesso or "").strip()
                eh_minuta = not (len(chave_str) == 44 and chave_str.isdigit())
                if eh_minuta:
                    minutas_sem_chave += 1

                fid = nf.freight_id_tms or (nf.frete.esl_freight_id if nf.frete else None)
                fid_ok = freight_id_valido(fid, numero_nota=nf.numero_nota, chave_acesso=nf.chave_acesso)
                if fid_ok:
                    com_freight_id += 1
                else:
                    sem_freight_id += 1

                filial_em = nf.filial_emissora or (nf.frete.filial_emissora if nf.frete else None)
                corp_id = nf.id_filial_emissora_tms or (nf.frete.id_filial_emissora_tms if nf.frete else None)
                corp_nome = nf.nome_filial_emissora_tms or (nf.frete.nome_filial_emissora_tms if nf.frete else None)
                if filial_em or corp_id:
                    com_filial_emissora += 1
                    label_emissora = (
                        f"{filial_em.nome} ({filial_em.uf})"
                        if filial_em
                        else f"{corp_nome or 'ESL'} [ID {corp_id}]"
                    )
                    contagem_emissoras[label_emissora] += 1
                else:
                    sem_filial_emissora += 1

                cep_ok = bool(limpar_cep(nf.cep))
                if cep_ok:
                    com_cep += 1
                else:
                    sem_cep += 1

                cte_ok = bool(nf.numero_cte or (nf.frete and nf.frete.numero_cte))
                if cte_ok:
                    com_cte += 1

                if not (fid_ok and (filial_em or corp_id) and cep_ok):
                    pendencias.append(
                        {
                            "manifesto": mft.numero_manifesto,
                            "nota": nf.numero_nota,
                            "tipo": "MINUTA" if eh_minuta else "NF-e",
                            "freight_id": fid if fid_ok else f"INVÁLIDO({fid})",
                            "emissora": (filial_em.nome if filial_em else corp_nome) or "PENDENTE",
                            "cep": nf.cep or "SEM_CEP",
                            "cte": nf.numero_cte or (nf.frete.numero_cte if nf.frete else None) or "-",
                        }
                    )

        self.stdout.write("\n" + "=" * 78)
        self.stdout.write(self.style.SUCCESS("📊 RESUMO DA AUDITORIA DE FRETES E NOTAS FISCAIS"))
        self.stdout.write("=" * 78)
        self.stdout.write(f"  Manifestos auditados         : {len(manifestos)}")
        self.stdout.write(f"  Total de Notas/Minutas       : {total_notas} (sendo {minutas_sem_chave} minutas/declarações)")
        self.stdout.write(f"  Com Freight ID interno válido: {com_freight_id}/{total_notas} (pendentes: {sem_freight_id})")
        self.stdout.write(f"  Com Filial Emissora salva    : {com_filial_emissora}/{total_notas} (pendentes: {sem_filial_emissora})")
        self.stdout.write(f"  Com CEP válido               : {com_cep}/{total_notas} (pendentes: {sem_cep})")
        self.stdout.write(f"  Com Número de CT-e           : {com_cte}/{total_notas}")

        if contagem_emissoras:
            self.stdout.write("\n🏢 DISTRIBUIÇÃO POR FILIAL EMISSORA DO FRETE:")
            for emissora, qtd in contagem_emissoras.most_common():
                self.stdout.write(f"   • {emissora}: {qtd} nota(s)")

        if pendencias:
            self.stdout.write(
                self.style.WARNING(f"\n⚠️ NOTAS COM CAMPOS PENDENTES ({len(pendencias)} registro(s), exibindo até 25):")
            )
            for p in pendencias[:25]:
                self.stdout.write(
                    f"   • Mft #{p['manifesto']} | {p['tipo']} #{p['nota']} | "
                    f"FreightID={p['freight_id']} | Emissora={p['emissora']} | CEP={p['cep']} | CT-e={p['cte']}"
                )
        else:
            self.stdout.write(
                self.style.SUCCESS("\n✅ 100% das notas auditadas possuem Freight ID interno, Filial Emissora e CEP!")
            )
        self.stdout.write("=" * 78 + "\n")

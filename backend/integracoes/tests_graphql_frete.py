# backend/integracoes/tests_graphql_frete.py
"""
Testes unitários e de integração da camada GraphQL de Fretes ESL Cloud,
enriquecimento de Filial Emissora / Minutas, correção de baixa de minutas
e rateio financeiro por Filial Emissora.

Compatível tanto com `python manage.py test integracoes.tests_graphql_frete`
quanto com execução direta via `python3 -m unittest` em ambientes mínimos.
"""

from datetime import datetime, timezone as dt_tz
import sys
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch


def _garantir_stubs_ambiente():
    """Garante stubs leves caso executado fora do virtualenv Django completo."""
    try:
        import django  # noqa: F401
    except ImportError:
        django_mod = ModuleType("django")
        django_mod.__path__ = []
        conf_mod = ModuleType("django.conf")
        conf_mod.settings = SimpleNamespace(DEBUG=False)
        db_mod = ModuleType("django.db")
        db_mod.__path__ = []
        db_mod.transaction = SimpleNamespace(
            atomic=lambda fn=None: (fn if fn else MagicMock()),
            on_commit=lambda fn: fn(),
        )
        db_mod.connection = SimpleNamespace(schema_name="public")
        models_mod = ModuleType("django.db.models")
        models_mod.Q = MagicMock()
        models_mod.Count = MagicMock()
        utils_mod = ModuleType("django.utils")
        utils_mod.__path__ = []
        tz_mod = ModuleType("django.utils.timezone")
        tz_mod.now = lambda: datetime.now(dt_tz.utc)
        utils_mod.timezone = tz_mod
        core_mod = ModuleType("django.core")
        core_mod.__path__ = []
        cache_mod = ModuleType("django.core.cache")
        cache_mod.cache = SimpleNamespace(add=lambda *a, **k: True, delete=lambda *a, **k: None)
        core_mod.cache = cache_mod

        django_mod.conf = conf_mod
        django_mod.db = db_mod
        django_mod.utils = utils_mod
        django_mod.core = core_mod

        sys.modules.setdefault("django", django_mod)
        sys.modules.setdefault("django.conf", conf_mod)
        sys.modules.setdefault("django.db", db_mod)
        sys.modules.setdefault("django.db.models", models_mod)
        sys.modules.setdefault("django.utils", utils_mod)
        sys.modules.setdefault("django.utils.timezone", tz_mod)
        sys.modules.setdefault("django.core", core_mod)
        sys.modules.setdefault("django.core.cache", cache_mod)

    try:
        import requests  # noqa: F401
    except ImportError:
        req_mod = ModuleType("requests")

        class _HTTPError(Exception):
            def __init__(self, msg="", response=None):
                super().__init__(msg)
                self.response = response

        class _Response:
            def __init__(self):
                self.status_code = 200
                self._content = b""

            @property
            def text(self):
                return self._content.decode("utf-8", errors="ignore")

            @property
            def ok(self):
                return 200 <= self.status_code < 400

            def __bool__(self):
                # Comportamento real do `requests.Response`: False para status >= 400!
                return self.ok

            def raise_for_status(self):
                if not self.ok:
                    raise _HTTPError(f"HTTP {self.status_code}", response=self)

        req_mod.Response = _Response
        req_mod.exceptions = SimpleNamespace(HTTPError=_HTTPError)
        req_mod.post = MagicMock()
        req_mod.get = MagicMock()
        sys.modules["requests"] = req_mod

    try:
        import pytz  # noqa: F401
    except ImportError:
        pytz_mod = ModuleType("pytz")
        pytz_mod.timezone = lambda _: dt_tz.utc
        sys.modules["pytz"] = pytz_mod

    pacotes_e_submodulos = [
        ("usuarios", "models", {"Filial": MagicMock(), "Motorista": MagicMock()}),
        (
            "manifesto",
            "models",
            {
                "Manifesto": MagicMock(),
                "NotaFiscal": MagicMock(),
                "Frete": MagicMock(),
                "BaixaNF": MagicMock(),
                "Ocorrencia": MagicMock(),
                "HistoricoOcorrencia": MagicMock(),
                "ManifestoBuscaLog": MagicMock(),
                "LogBaixaNfe": MagicMock(),
                "Veiculo": MagicMock(),
                "LogChecklistManifesto": MagicMock(),
            },
        ),
        (
            "manifesto",
            "utils",
            {
                "enviar_painel": MagicMock(),
                "notificar_falha_tms": MagicMock(),
            },
        ),
        (
            "manifesto",
            "services",
            {
                "enviar_painel": MagicMock(),
                "obter_codigo_ocorrencia_seguro": lambda cod, **kw: (int(cod or 1), "stub"),
                "limpar_codigo_ocorrencia": lambda cod: int(cod or 1),
            },
        ),
        (
            "configuracao",
            "utils",
            {
                "notificar_falha_tms": MagicMock(),
            },
        ),
        (
            "integracoes",
            "models",
            {
                "ConfiguracaoSistema": MagicMock(),
                "get_config": MagicMock(),
            },
        ),
        (
            "operacional",
            "services",
            {
                "resolver_erros_automaticamente": MagicMock(),
                "registrar_erro_torre": MagicMock(),
            },
        ),
    ]
    for pkg_name, sub_name, attrs in pacotes_e_submodulos:
        full_name = f"{pkg_name}.{sub_name}"
        try:
            __import__(full_name)
        except Exception:
            if pkg_name not in sys.modules:
                pkg_mod = ModuleType(pkg_name)
                pkg_mod.__path__ = []
                sys.modules[pkg_name] = pkg_mod
            else:
                pkg_mod = sys.modules[pkg_name]
            sub_mod = ModuleType(full_name)
            for k, v in attrs.items():
                setattr(sub_mod, k, v)
            sys.modules[full_name] = sub_mod
            setattr(pkg_mod, sub_name, sub_mod)


_garantir_stubs_ambiente()

import requests  # noqa: E402
from financeiro.services import _uf_emissora_da_nota  # noqa: E402
from integracoes.enriquecimento_frete import (  # noqa: E402
    aplicar_em_nota,
    enriquecer_manifesto,
    resolver_filial_emissora,
)
from integracoes.providers.esl_graphql import (  # noqa: E402
    consultar_frete,
    endereco_texto,
    freight_id_valido,
    mapear_notas_para_fretes,
    normalizar_frete,
    nota_pertence_ao_frete,
)


NODE_FRETE_57258355 = {
    "id": "57258355",
    "sequenceCode": 466451,
    "uniqueId": "508afca5904dfb13",
    "corporationId": 237974,
    "status": "finished",
    "modal": "road",
    "type": "normal",
    "invoiceDocumentType": "declaration",
    "total": 450.0,
    "taxedWeight": 52.3,
    "invoicesVolumes": 4,
    "invoicesTotalVolumes": 4,
    "freightInvoicesCount": 4,
    "cte": {
        "number": 90964,
        "series": 1,
        "key": "52260408296144000734570010000909641004664515",
    },
    "corporation": {
        "document": "08296144000734",
        "name": "QUICK DELIVERY ENTREGAS RAPIDAS LTDA",
        "nickname": "QUICK GOIANIA",
    },
    "sender": {
        "name": "REMETENTE GOIANIA LTDA",
        "nickname": "REMETENTE GOIANIA",
        "document": "11222333000144",
    },
    "recipient": {
        "name": "DE MILLUS S A INDUSTRIA E COMERCIO",
        "nickname": "DE MILLUS",
        "document": "33444555000166",
        "mainAddress": {
            "line1": "AV BRASIL",
            "line2": "GALPAO 2",
            "number": "22000",
            "neighborhood": "PENHA",
            "postalCode": "21011-400",
            "city": {"name": "RIO DE JANEIRO", "state": {"code": "RJ"}},
        },
    },
    "payer": {
        "name": "DE MILLUS S A INDUSTRIA E COMERCIO",
        "nickname": "DE MILLUS",
        "document": "33444555000166",
    },
    "destinationAddress": {
        "line1": "AV BRASIL",
        "line2": "GALPAO 2",
        "number": "22000",
        "neighborhood": "PENHA",
        "postalCode": "21011-400",
        "city": {"name": "RIO DE JANEIRO", "state": {"code": "RJ"}},
    },
    "freightInvoices": [
        {"invoice": {"id": "801", "number": "503", "key": None, "volume": 1}},
        {"invoice": {"id": "802", "number": "531", "key": None, "volume": 1}},
        {"invoice": {"id": "803", "number": "510", "key": None, "volume": 1}},
        {"invoice": {"id": "804", "number": "509", "key": None, "volume": 1}},
    ],
}


class ESLGraphQLNormalizerTests(TestCase):
    def test_normalizar_frete_minuta_509_goiania(self):
        norm = normalizar_frete(NODE_FRETE_57258355)
        self.assertIsNotNone(norm)
        self.assertEqual(norm["freight_id"], "57258355")
        self.assertEqual(norm["sequence_code"], "466451")
        self.assertEqual(norm["unique_id"], "508afca5904dfb13")
        self.assertEqual(norm["cte_numero"], "90964")
        self.assertEqual(norm["cte_chave"], "52260408296144000734570010000909641004664515")
        self.assertEqual(norm["corporation_id"], "237974")
        self.assertEqual(norm["corporation_nome"], "QUICK GOIANIA")
        self.assertEqual(norm["endereco"]["cep"], "21011400")
        self.assertIn("AV BRASIL", endereco_texto(norm["endereco"]))
        self.assertIn("PENHA", endereco_texto(norm["endereco"]))
        self.assertEqual(len(norm["notas"]), 4)

        # Valida se todas as 4 minutas (503, 531, 510, 509) são reconhecidas dentro do frete 57258355
        for num in ["503", "531", "510", "509"]:
            self.assertTrue(nota_pertence_ao_frete({"numero": num, "chave": None}, norm))
        self.assertFalse(nota_pertence_ao_frete({"numero": "999999", "chave": None}, norm))

    def test_normalizar_frete_minuta_sem_cte_57391800_usa_corporation_sequence_number_e_pagador(self):
        """
        No frete 57391800 (Minuta RD Expresso /17360), `cte` é null e `emissionType` é 'draft'.
        O número da minuta deve vir de `corporationSequenceNumber` (17360), `cte_chave` deve ser None,
        `volumes` = 2 (`invoicesVolumes`) e `pagador_nome` = 'METTA BRASIL LOGISTICA LTDA'.
        """
        node_57391800 = {
            "id": 57391800,
            "sequenceCode": 467207,
            "corporationSequenceNumber": 17360,
            "uniqueId": "b88b7a4d6aa02ba3",
            "corporationId": 237988,
            "status": "in_transit",
            "modal": "rodo",
            "type": "Freight::Normal",
            "emissionType": "draft",
            "invoiceDocumentType": "Invoice::Nfe",
            "total": 110.0,
            "invoicesValue": 44.16,
            "taxedWeight": 20.0,
            "realWeight": 20.0,
            "invoicesWeight": 20.0,
            "invoicesVolumes": 2,
            "invoicesTotalVolumes": 0,
            "freightInvoicesCount": 1,
            "corporation": {
                "name": "RD EXPRESSO TRANSPORTES - EIRELI",
                "nickname": "RD EXPRESSO",
                "document": "14977687000124",
            },
            "payer": {
                "name": "METTA BRASIL LOGISTICA LTDA",
                "nickname": "METTA BRASIL LOGISTICA LTDA",
                "document": "30408555000219",
            },
            "sender": {
                "name": "LABORATORIO TEUTO BRASILEIRO S/A",
                "nickname": "LABORATORIO TEUTO BRASILEIRO S/A",
                "document": "17159229000176",
            },
            "recipient": {
                "name": "FARMALOG DISTRIBUIDORA DE MEDICAMENTOS LTDA",
                "nickname": "FARMALOG DISTRIBUIDORA DE MEDICAMENTOS LTDA",
                "document": "24924986000588",
            },
            "destinationAddress": {
                "line1": "RODOVIA PRESIDENTE DUTRA",
                "line2": "BLOCO 2 KM 188",
                "number": "25551",
                "neighborhood": "SARAPO",
                "postalCode": "26343295",
                "city": {"name": "Queimados", "state": {"code": "RJ"}},
            },
            "cte": None,
            "freightInvoices": [
                {
                    "invoice": {
                        "id": "124624534",
                        "number": "86004",
                        "key": "52261017159229000176550030000860041553043690",
                        "volume": 2,
                        "weight": 20.0,
                        "value": 44.16,
                    }
                }
            ],
        }
        norm = normalizar_frete(node_57391800)
        self.assertTrue(norm["eh_minuta"])
        self.assertEqual(norm["unique_id"], "b88b7a4d6aa02ba3")
        self.assertEqual(norm["minuta_numero"], "17360")
        self.assertEqual(norm["cte_numero"], "17360")
        self.assertIsNone(norm["cte_chave"])
        self.assertEqual(norm["volumes"], 2)
        self.assertEqual(norm["valor_frete"], 110.0)
        self.assertEqual(norm["peso_taxado"], 20.0)
        self.assertEqual(norm["pagador_nome"], "METTA BRASIL LOGISTICA LTDA")
        self.assertEqual(norm["pagador_documento"], "30408555000219")
        self.assertEqual(norm["remetente_nome"], "LABORATORIO TEUTO BRASILEIRO S/A")
        self.assertEqual(norm["corporation_id"], "237988")
        self.assertEqual(norm["corporation_nome"], "RD EXPRESSO")

    def test_consultar_frete_reentrega_herda_unique_id_do_frete_original(self):
        """
        Em fretes de reentrega (ex: 57513089), a ESL devolve uniqueId=None e originalFreightId=57426912.
        Garante que consultar_frete busca o frete original e herda seu unique_id ('b05426d0a8d6cb66').
        """
        import json

        def fake_post(url, headers, payload, timeout):
            fid = payload["variables"]["params"]["id"]
            if fid == "57513089":
                # Reentrega sem uniqueId
                return 200, json.dumps({
                    "data": {
                        "freight": {
                            "edges": [{
                                "node": {
                                    "id": 57513089,
                                    "sequenceCode": 468524,
                                    "type": "Freight::Redelivery",
                                    "uniqueId": None,
                                    "originalFreightId": 57426912,
                                    "corporationId": 237978,
                                    "cte": {"number": 281104, "series": 2, "key": "35261114539546000120570020002811041468278402"},
                                }
                            }]
                        }
                    }
                })
            elif fid == "57426912":
                # Frete original com etiqueta/uniqueId
                return 200, json.dumps({
                    "data": {
                        "freight": {
                            "edges": [{
                                "node": {
                                    "id": 57426912,
                                    "sequenceCode": 467778,
                                    "type": "Freight::Normal",
                                    "uniqueId": "b05426d0a8d6cb66",
                                    "originalFreightId": None,
                                    "corporationId": 237978,
                                    "cte": {"number": 280850, "series": 2, "key": "35261114539546000120570020002808501004677789"},
                                }
                            }]
                        }
                    }
                })
            return 404, "{}"

        res = consultar_frete("dominio.esl", "token-fake", "57513089", post=fake_post)
        self.assertIsNotNone(res)
        self.assertEqual(res["freight_id"], "57513089")
        self.assertEqual(res["tipo"], "Freight::Redelivery")
        self.assertEqual(res["original_freight_id"], "57426912")
        self.assertEqual(res["unique_id"], "b05426d0a8d6cb66")

    def test_freight_id_valido_rejeita_ids_suspeitos(self):
        self.assertFalse(freight_id_valido(None))
        self.assertFalse(freight_id_valido(""))
        self.assertFalse(freight_id_valido("12"))
        self.assertFalse(freight_id_valido("509", numero_nota="509"))
        self.assertFalse(
            freight_id_valido(
                "52260408296144000734570010000909641004664515",
                chave_acesso="52260408296144000734570010000909641004664515",
            )
        )
        self.assertTrue(freight_id_valido("57258355", numero_nota="509"))

    def test_mapear_notas_para_fretes(self):
        notas = [{"id": 10, "numero": "509", "chave": None}]
        ocorrencias = [
            {
                "numero": "000509",
                "chave": "",
                "freight_id": "57258355",
            }
        ]
        mapa = mapear_notas_para_fretes(notas, ocorrencias)
        self.assertEqual(mapa[10]["freight_id"], "57258355")
        self.assertEqual(mapa[10]["motivo"], "numero")


class EnriquecimentoEFilialEmissoraTests(TestCase):
    def test_resolver_filial_emissora_prioriza_corporation_id_goiania_sobre_cnpj_brasilia(self):
        """
        Na ESL da Quick Delivery, Goiânia (237974) compartilha o CNPJ de Brasília (08296144000734).
        Garante que corporationId=237974 / nickname='QUICK GOIANIA' resolve para a filial GO e NÃO DF!
        """
        filial_go = SimpleNamespace(
            id=2,
            nome="QUICK GOIANIA",
            uf="GO",
            id_filial_tms="237974",
            cnpj="",
            save=MagicMock(),
        )

        with patch("usuarios.models.Filial.objects") as mock_filial_qs:
            mock_filial_qs.filter.return_value.first.return_value = filial_go
            resolvida = resolver_filial_emissora("237974", "QUICK GOIANIA")
            self.assertIsNotNone(resolvida)
            self.assertEqual(resolvida.uf, "GO")
            self.assertEqual(resolvida.id_filial_tms, "237974")

    def test_aplicar_em_nota_preenche_minuta_sem_cep_e_filial_emissora(self):
        norm = normalizar_frete(NODE_FRETE_57258355)
        filial_go = SimpleNamespace(id=2, nome="QUICK GOIANIA", uf="GO", id_filial_tms="237974")
        frete_obj = SimpleNamespace(
            id=99,
            filial_emissora=filial_go,
            id_filial_emissora_tms="237974",
            nome_filial_emissora_tms="QUICK GOIANIA",
        )
        nf = SimpleNamespace(
            id=509,
            numero_nota="509",
            chave_acesso=None,
            status="PENDENTE",
            freight_id_tms=None,
            esl_unique_id=None,
            frete_id=None,
            frete=None,
            filial_emissora_id=None,
            filial_emissora=None,
            id_filial_emissora_tms=None,
            nome_filial_emissora_tms=None,
            numero_cte=None,
            chave_cte=None,
            cep=None,
            endereco_entrega="ENDEREÇO NÃO INFORMADO",
            destinatario="NÃO INFORMADO",
            latitude=-22.8,
            longitude=-43.2,
            save=MagicMock(),
        )

        campos, conflitos = aplicar_em_nota(nf, norm, frete_obj, filial_go)

        self.assertTrue(len(campos) > 0)
        self.assertEqual(conflitos, [])
        self.assertEqual(nf.freight_id_tms, "57258355")
        self.assertEqual(nf.esl_unique_id, "508afca5904dfb13")
        self.assertEqual(nf.id_filial_emissora_tms, "237974")
        self.assertEqual(nf.nome_filial_emissora_tms, "QUICK GOIANIA")
        self.assertEqual(nf.filial_emissora, filial_go)
        self.assertEqual(nf.numero_cte, "90964")
        self.assertEqual(nf.chave_cte, "52260408296144000734570010000909641004664515")
        self.assertEqual(nf.cep, "21011400")
        self.assertIn("AV BRASIL", nf.endereco_entrega)
        self.assertEqual(nf.destinatario, "DE MILLUS S A INDUSTRIA E COMERCIO")
        nf.save.assert_called_once()

    def test_enriquecer_manifesto_deduplica_chamada_graphql_por_frete(self):
        """
        Se um manifesto tem 4 minutas (503, 531, 510, 509) pertencentes ao mesmo Frete 57258355,
        o enriquecimento deve fazer APENAS 1 consulta GraphQL para o Frete 57258355.
        """
        norm = normalizar_frete(NODE_FRETE_57258355)
        filial_go = SimpleNamespace(id=2, nome="QUICK GOIANIA", uf="GO", id_filial_tms="237974")
        frete_dummy = SimpleNamespace(
            id=10,
            esl_freight_id="57258355",
            filial_emissora=filial_go,
            id_filial_emissora_tms="237974",
            nome_filial_emissora_tms="QUICK GOIANIA",
        )

        notas_mock = []
        for num in ["503", "531", "510", "509"]:
            notas_mock.append(
                SimpleNamespace(
                    id=int(num),
                    numero_nota=num,
                    tipo_operacao="ENTREGA",
                    status="PENDENTE",
                    chave_acesso=None,
                    freight_id_tms="57258355",
                    esl_unique_id=None,
                    frete_id=None,
                    frete=None,
                    filial_emissora_id=None,
                    filial_emissora=None,
                    id_filial_emissora_tms=None,
                    nome_filial_emissora_tms=None,
                    numero_cte=None,
                    chave_cte=None,
                    cep=None,
                    endereco_entrega="CONSULTE O DOCUMENTO FÍSICO",
                    destinatario="NÃO INFORMADO",
                    latitude=-22.8,
                    longitude=-43.2,
                    save=MagicMock(),
                )
            )

        qs_mock = MagicMock()
        qs_mock.__iter__.return_value = iter(notas_mock)
        qs_mock.select_related.return_value = notas_mock
        notas_mgr = MagicMock()
        notas_mgr.exclude.return_value = qs_mock
        notas_mgr.filter.return_value = []

        mft = SimpleNamespace(
            id=71318,
            numero_manifesto="71318",
            manifesto_id_tms="6500123",
            notas_fiscais=notas_mgr,
        )
        config = SimpleNamespace(
            dominio_esl="quickdelivery.eslcloud.com.br",
            token_analytics="token-db-analytics",
            token_invoices="token-db-invoices",
        )
        ocorrencias_esl = [
            {"numero": num, "chave": None, "freight_id": "57258355"}
            for num in ["503", "531", "510", "509"]
        ]

        with patch(
            "integracoes.enriquecimento_frete.listar_ocorrencias_manifesto",
            return_value=ocorrencias_esl,
        ), patch(
            "integracoes.enriquecimento_frete.respeitar_intervalo_esl",
        ), patch(
            "integracoes.enriquecimento_frete.consultar_frete",
            return_value=norm,
        ) as mock_gql, patch(
            "integracoes.enriquecimento_frete.upsert_frete",
            return_value=frete_dummy,
        ), patch(
            "integracoes.enriquecimento_frete.resolver_filial_emissora",
            return_value=filial_go,
        ):
            resumo = enriquecer_manifesto(config, mft)

        self.assertEqual(mock_gql.call_count, 1)
        self.assertEqual(resumo["fretes_consultados"], 1)
        self.assertEqual(resumo["notas_enriquecidas"], 4)
        for nf in notas_mock:
            self.assertEqual(nf.cep, "21011400")
            self.assertEqual(nf.id_filial_emissora_tms, "237974")
            self.assertEqual(nf.esl_unique_id, "508afca5904dfb13")

    def test_enriquecer_coletas_manifesto_71413_corporation_id_237973(self):
        """
        Valida o enriquecimento das coletas do Manifesto #71413 (54661, 54662, 54674)
        usando o novo campo `corporation_id: 237973` (QUICK BRASILIA - DF) e CEP do Report 11324.
        """
        filial_df = SimpleNamespace(id=3, nome="QUICK BRASILIA", uf="DF", id_filial_tms="237973")
        coletas_report_71413 = [
            {
                "sequence_code": 54661,
                "request_date": "2026-11-05",
                "requester": "",
                "service_type": "0",
                "corporation_id": 237973,
                "pck_pln_name": "CBA - COMERCIO DE PRODUTOS HOSPITALARES LTDA",
                "pck_pln_mds_line_1": "SETOR SCIA QUADRA 15 CONJUNTO 3 LOTE",
                "pck_pln_mds_number": "5",
                "pck_pln_mds_line_2": "",
                "pck_pln_mds_postal_code": "71250015",
                "pck_pln_mds_neighborhood": "ZONA INDUSTRIAL (GUARA)",
                "pck_pln_mds_cty_name": "Brasília",
                "pck_pln_mds_cty_sae_name": "Distrito Federal",
            },
            {
                "sequence_code": 54662,
                "request_date": "2026-11-05",
                "requester": "",
                "service_type": "0",
                "corporation_id": 237973,
                "pck_pln_name": "FULLFARMA COMERCIO DE PRODUTOS FARMACEUTICOS LTDA",
                "pck_pln_mds_line_1": "TR SIA TRECHO 3 LOTES 625/695",
                "pck_pln_mds_number": "SN",
                "pck_pln_mds_line_2": "BLOCO B 306",
                "pck_pln_mds_postal_code": "71200038",
                "pck_pln_mds_neighborhood": "ZONA INDUSTRIAL (GUARA)",
                "pck_pln_mds_cty_name": "Brasília",
                "pck_pln_mds_cty_sae_name": "Distrito Federal",
            },
            {
                "sequence_code": 54674,
                "request_date": "2026-11-05",
                "requester": "",
                "service_type": "0",
                "corporation_id": 237973,
                "pck_pln_name": "BENENUTRI COMERCIAL LTDA",
                "pck_pln_mds_line_1": "QUADRA SAAN QUADRA 3",
                "pck_pln_mds_number": "SN",
                "pck_pln_mds_line_2": "LOTE: 750 / 760",
                "pck_pln_mds_postal_code": "70632320",
                "pck_pln_mds_neighborhood": "ZONA INDUSTRIAL",
                "pck_pln_mds_cty_name": "Brasília",
                "pck_pln_mds_cty_sae_name": "Distrito Federal",
            },
        ]

        coletas_mock = []
        for seq in ["54661", "54662", "54674"]:
            coletas_mock.append(
                SimpleNamespace(
                    id=int(seq),
                    numero_nota=seq,
                    numero_coleta=seq,
                    tipo_operacao="COLETA",
                    status="PENDENTE",
                    filial_emissora_id=None,
                    filial_emissora=None,
                    id_filial_emissora_tms=None,
                    nome_filial_emissora_tms=None,
                    cep=None,
                    endereco_entrega="ENDEREÇO NÃO INFORMADO",
                    destinatario="NÃO INFORMADO",
                    latitude=-15.79,
                    longitude=-47.88,
                    save=MagicMock(),
                )
            )

        qs_empty = MagicMock()
        qs_empty.__iter__.return_value = iter([])
        qs_empty.select_related.return_value = []
        notas_mgr = MagicMock()
        notas_mgr.exclude.return_value = qs_empty
        notas_mgr.filter.return_value = coletas_mock

        mft = SimpleNamespace(
            id=71413,
            numero_manifesto="71413",
            manifesto_id_tms="6500999",
            notas_fiscais=notas_mgr,
        )
        config = SimpleNamespace(
            dominio_esl="quickdelivery.eslcloud.com.br",
            token_analytics="token-db-analytics",
            token_invoices="token-db-invoices",
            report_coletas="11324",
        )

        with patch(
            "integracoes.enriquecimento_frete.listar_coletas_manifesto_esl",
            return_value=coletas_report_71413,
        ) as mock_rep_col, patch(
            "integracoes.enriquecimento_frete.resolver_filial_emissora",
            return_value=filial_df,
        ):
            resumo = enriquecer_manifesto(config, mft)

        self.assertEqual(mock_rep_col.call_count, 1)
        self.assertEqual(resumo["coletas_alvo"], 3)
        self.assertEqual(resumo["coletas_enriquecidas"], 3)
        self.assertEqual(coletas_mock[0].cep, "71250015")
        self.assertEqual(coletas_mock[1].cep, "71200038")
        self.assertEqual(coletas_mock[2].cep, "70632320")
        for col in coletas_mock:
            self.assertEqual(col.id_filial_emissora_tms, "237973")
            self.assertEqual(col.nome_filial_emissora_tms, "QUICK BRASILIA")
            self.assertEqual(col.filial_emissora, filial_df)
            self.assertEqual(_uf_emissora_da_nota(col), "DF")


class FinanceiroRateioFilialEmissoraTests(TestCase):
    def test_coleta_com_identificador_diferente_casa_por_nome_unico_e_reporta_sem_match(self):
        """
        Se o webhook trouxer para a coleta um identificador diferente do sequence_code do Report 11324,
        o casamento cai no nome do solicitante (somente se único). Sem correspondência, vai para
        `coletas_sem_match` (nunca chuta).
        """
        filial_df = SimpleNamespace(id=3, nome="QUICK BRASILIA", uf="DF", id_filial_tms="237973")
        report = [
            {"sequence_code": 54661, "corporation_id": 237973, "pck_pln_name": "CBA - COMERCIO DE PRODUTOS HOSPITALARES LTDA",
             "pck_pln_mds_postal_code": "71250015"},
            {"sequence_code": 54662, "corporation_id": 237973, "pck_pln_name": "SOLICITANTE QUALQUER",
             "pck_pln_mds_postal_code": "71200038"},
        ]

        def _col(seq_nota, seq_coleta, nome):
            return SimpleNamespace(
                id=int(seq_coleta), numero_nota=seq_nota, numero_coleta=seq_coleta, tipo_operacao="COLETA", status="PENDENTE",
                filial_emissora_id=None, filial_emissora=None, id_filial_emissora_tms=None,
                nome_filial_emissora_tms=None, cep=None, endereco_entrega="ENDEREÇO NÃO INFORMADO",
                destinatario=nome, latitude=-15.7, longitude=-47.8, save=MagicMock(),
            )

        # Caso 1: Webhook trouxe @numero="1" em numero_coleta e Documento.Numero="54662" em numero_nota
        casa_por_numero_nota = _col("54662", "1", "OUTRO NOME NO WEBHOOK")
        # Caso 2: Webhook trouxe índice da parada tanto em numero_nota quanto em numero_coleta -> casa pelo nome único
        casa_por_nome = _col("3", "3", "CBA - COMERCIO DE PRODUTOS HOSPITALARES LTDA")
        # Caso 3: Sem match nem por número nem por nome -> vai para coletas_sem_match
        sem_match = _col("4", "4", "EMPRESA DESCONHECIDA LTDA")

        mgr = MagicMock()
        mgr.filter.return_value = [casa_por_numero_nota, casa_por_nome, sem_match]
        mft = SimpleNamespace(id=1, numero_manifesto="71413", notas_fiscais=mgr)
        config = SimpleNamespace(dominio_esl="x.eslcloud.com.br", token_analytics="tk", token_invoices="tk")

        from integracoes.enriquecimento_frete import enriquecer_coletas_manifesto
        with patch("integracoes.enriquecimento_frete.listar_coletas_manifesto_esl", return_value=report), patch(
            "integracoes.enriquecimento_frete.resolver_filial_emissora", return_value=filial_df
        ):
            res = enriquecer_coletas_manifesto(config, mft)

        self.assertEqual(res["coletas_enriquecidas"], 2)
        self.assertEqual(casa_por_numero_nota.id_filial_emissora_tms, "237973")
        self.assertEqual(casa_por_numero_nota.numero_coleta, "54662")
        self.assertEqual(casa_por_nome.id_filial_emissora_tms, "237973")
        self.assertEqual(casa_por_nome.numero_coleta, "54661")
        self.assertEqual(casa_por_nome.cep, "71250015")
        self.assertIsNone(sem_match.id_filial_emissora_tms)
        self.assertEqual(res["coletas_sem_match"], ["4"])

    def test_uf_emissora_da_nota_prioriza_filial_emissora_e_corporation_id(self):
        filial_go = SimpleNamespace(nome="Filial Goiânia", uf="GO", id_filial_tms="237974")
        nf_com_filial = SimpleNamespace(
            filial_emissora=filial_go,
            id_filial_emissora_tms="237974",
            nome_filial_emissora_tms="QUICK GOIANIA",
            frete=None,
        )
        self.assertEqual(_uf_emissora_da_nota(nf_com_filial), "GO")

        # Mesmo sem objeto Filial vinculado, o corporationId 237978 resolve para SP
        nf_so_corp_id = SimpleNamespace(
            filial_emissora=None,
            id_filial_emissora_tms="237978",
            nome_filial_emissora_tms="QUICK SAO PAULO",
            frete=None,
        )
        self.assertEqual(_uf_emissora_da_nota(nf_so_corp_id), "SP")

        # E via nf.frete.id_filial_emissora_tms = 237973 resolve para DF
        frete_df = SimpleNamespace(
            filial_emissora=None,
            id_filial_emissora_tms="237973",
            nome_filial_emissora_tms="QUICK BRASILIA",
        )
        nf_via_frete = SimpleNamespace(
            filial_emissora=None,
            id_filial_emissora_tms=None,
            nome_filial_emissora_tms=None,
            frete=frete_df,
        )
        self.assertEqual(_uf_emissora_da_nota(nf_via_frete), "DF")


class EnviarBaixaMinutaBugFixTests(TestCase):
    def test_enviar_baixa_minuta_422_ja_existe_nao_mascara_com_sem_freight_id(self):
        """
        Garante que quando a ESL retorna HTTP 422 ('já existe ocorrência') para uma minuta
        com freight_id válido (ex: Minuta #509, Freight 57258355), `enviar_baixa_minuta`
        NÃO cai no falso erro 'sem freight_id válido' (causado por `bool(Response(422)) == False`)
        e marca a baixa como integrada por idempotência.
        """
        from django.utils import timezone
        from integracoes.providers.esl_cloud import ESLCloudAdapter

        config = SimpleNamespace(
            dominio_esl="quickdelivery.eslcloud.com.br",
            token_invoices="token-invoices-db",
            token_analytics="token-analytics-db",
        )
        adapter = ESLCloudAdapter(config)

        manifesto = SimpleNamespace(
            id=1,
            numero_manifesto="71318",
            manifesto_id_tms="6500123",
            filial=SimpleNamespace(id=1, nome="Matriz RJ", uf="RJ"),
            filial_operacao=None,
            motorista=SimpleNamespace(nome_completo="MOTORISTA TESTE"),
        )
        frete = SimpleNamespace(
            id=10,
            freight_id_tms="466451",  # sequence_code visual
            esl_freight_id="57258355",  # ID interno real
            chave_cte="52260408296144000734570010000909641004664515",
            numero_cte="90964",
        )
        nf = SimpleNamespace(
            id=509,
            numero_nota="509",
            chave_acesso=None,
            tipo_operacao="ENTREGA",
            freight_id_tms="57258355",
            filial_emissora_id=2,
            chave_cte="52260408296144000734570010000909641004664515",
            manifesto=manifesto,
            frete=frete,
            save=MagicMock(),
        )
        ocorrencia = SimpleNamespace(id=1, codigo_tms="1", codigo_referencia="1")
        baixa = SimpleNamespace(
            id=9001,
            nota_fiscal=nf,
            ocorrencia=ocorrencia,
            integrado_tms=False,
            processado_tms=False,
            data_baixa=timezone.now(),
            recebedor="PORTARIA",
            documento_recebedor="123456",
            observacao="Entregue",
            latitude=-22.8,
            longitude=-43.2,
            comprovante_foto_url=None,
            payload_enviado=None,
            log_erro_tms=None,
            data_integracao=None,
            save=MagicMock(),
        )

        resp_422 = requests.Response()
        resp_422.status_code = 422
        resp_422._content = b'{"errors": ["Ja existe ocorrencia cadastrada para este frete"]}'

        with patch("integracoes.providers.esl_cloud.BaixaNF.objects") as mock_baixa_mgr, patch(
            "integracoes.providers.esl_cloud.requests.post", return_value=resp_422
        ) as mock_post, patch("django.core.cache.cache.add", return_value=True), patch(
            "django.core.cache.cache.delete"
        ):
            mock_baixa_mgr.select_related.return_value.get.return_value = baixa
            resultado = adapter.enviar_baixa_minuta(9001)

        # Deve ter feito apenas 1 POST (no endpoint V1 de frete) sem sobrescrever o 422 com 404 do fallback!
        self.assertEqual(mock_post.call_count, 1)
        self.assertIn("/api/v1/freights/57258355/invoice_occurrences", mock_post.call_args[0][0])
        self.assertTrue(baixa.integrado_tms)
        self.assertTrue(baixa.processado_tms)
        self.assertIn("Já existia no TMS", resultado)

    def test_enviar_baixa_minuta_usa_esl_freight_id_e_nao_sequence_code(self):
        """
        Garante que se `nf.freight_id_tms` estiver ausente, `enviar_baixa_minuta`
        utiliza `nf.frete.esl_freight_id` (ID interno 57258355) e NÃO `nf.frete.freight_id_tms`
        (sequenceCode visual 466451).
        """
        from django.utils import timezone
        from integracoes.providers.esl_cloud import ESLCloudAdapter

        config = SimpleNamespace(
            dominio_esl="quickdelivery.eslcloud.com.br",
            token_invoices="token-invoices-db",
            token_analytics="token-analytics-db",
        )
        adapter = ESLCloudAdapter(config)

        manifesto = SimpleNamespace(
            id=1,
            numero_manifesto="71318",
            manifesto_id_tms="6500123",
            filial=SimpleNamespace(id=1, nome="Matriz RJ", uf="RJ"),
            filial_operacao=None,
            motorista=SimpleNamespace(nome_completo="MOTORISTA TESTE"),
        )
        frete = SimpleNamespace(
            id=10,
            freight_id_tms="466451",  # sequence_code visual
            esl_freight_id="57258355",  # ID interno real
            chave_cte="52260408296144000734570010000909641004664515",
            numero_cte="90964",
        )
        nf = SimpleNamespace(
            id=509,
            numero_nota="509",
            chave_acesso=None,
            tipo_operacao="ENTREGA",
            freight_id_tms=None,  # Ausente na NF, mas presente em nf.frete.esl_freight_id
            filial_emissora_id=2,
            chave_cte="52260408296144000734570010000909641004664515",
            manifesto=manifesto,
            frete=frete,
            save=MagicMock(),
        )
        ocorrencia = SimpleNamespace(id=1, codigo_tms="1", codigo_referencia="1")
        baixa = SimpleNamespace(
            id=9002,
            nota_fiscal=nf,
            ocorrencia=ocorrencia,
            integrado_tms=False,
            processado_tms=False,
            data_baixa=timezone.now(),
            recebedor="PORTARIA",
            documento_recebedor="123456",
            observacao="Entregue",
            latitude=-22.8,
            longitude=-43.2,
            comprovante_foto_url=None,
            payload_enviado=None,
            log_erro_tms=None,
            data_integracao=None,
            save=MagicMock(),
        )

        resp_201 = requests.Response()
        resp_201.status_code = 201
        resp_201._content = b'{"id": 12345}'

        with patch("integracoes.providers.esl_cloud.BaixaNF.objects") as mock_baixa_mgr, patch(
            "integracoes.providers.esl_cloud.requests.post", return_value=resp_201
        ) as mock_post, patch("django.core.cache.cache.add", return_value=True), patch(
            "django.core.cache.cache.delete"
        ):
            mock_baixa_mgr.select_related.return_value.get.return_value = baixa
            resultado = adapter.enviar_baixa_minuta(9002)

        self.assertEqual(mock_post.call_count, 1)
        self.assertIn("/api/v1/freights/57258355/invoice_occurrences", mock_post.call_args[0][0])
        self.assertNotIn("466451", mock_post.call_args[0][0])
        self.assertTrue(baixa.integrado_tms)
        self.assertIn("57258355", resultado)

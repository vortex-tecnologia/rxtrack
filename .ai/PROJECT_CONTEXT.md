# PROJECT_CONTEXT.md — RXTrack

> Última atualização: 2026-08-27

## Visão Geral

**RXTrack** é um SaaS multi-tenant para empresas de transporte e logística.
Gerencia manifestos de carga, entregas, motoristas, ocorrências e integração com TMS externo (ESL Cloud).
Possui PWA para motoristas, painel operacional web, app SAC, APK Android (Capacitor), IA para análise de canhotos e bot WhatsApp.

- **Proprietário**: Vortex Tecnologia (Luiz Gustavo)
- **Licença**: Proprietária
- **Produção**: VPS Linux com Docker
- **Tenant ativo**: 1 (arquitetura pronta para múltiplos)

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Django 4.x (Python 3.11) |
| ASGI Server | Daphne |
| Banco de Dados | PostgreSQL (externo à stack Docker) |
| Multi-tenancy | django-tenants (schema-based) |
| Cache/Broker | Redis 7 Alpine |
| Tarefas Async | Celery (TenantAwareCelery) |
| WebSocket | Django Channels + Redis Channel Layer |
| API | Django REST Framework + SimpleJWT |
| IA | YOLO + Florence-2 + Tesseract OCR + OpenCV |
| Frontend Motorista | PWA (HTML/JS/CSS inline em templates Django) |
| Frontend Operacional | Painel Desktop (HTML/JS/Bootstrap em templates Django) |
| APK Android | Capacitor (wrapper nativo com Foreground Service GPS Java) |
| WhatsApp | Bot via Evolution API |
| Geocodificação | Nominatim (OpenStreetMap) + ViaCEP |
| Upload de fotos | FTP externo |
| Notificações Push | Firebase FCM |
| Containerização | Docker Compose |
| Proxy reverso | Nginx (config simplificada, proxy transparente) |

---

## Estrutura de Diretórios (Backend)

```
RXTrack/
├── .ai/                    ← Memória técnica para agentes IA (ESTE DIRETÓRIO)
├── backend/
│   ├── core/               ← Projeto Django (settings, urls, asgi, celery, redis)
│   ├── tenants/            ← Multi-tenancy (Client, Domain) — SHARED
│   ├── usuarios/           ← Motorista, Filial, PermissaoUsuario, DeviceToken — TENANT
│   ├── manifesto/          ← Manifesto, NotaFiscal, BaixaNF, Ocorrencia, WebSocket — TENANT
│   ├── operacional/        ← Painel Desktop, Dashboard, Torre de Controle Live — TENANT
│   ├── mobile/             ← Views do PWA do Motorista — TENANT
│   ├── sac_mobile/         ← Views do App SAC — TENANT
│   ├── AgenteIa/           ← IA de análise de canhotos (YOLO/Florence/OCR) — TENANT
│   ├── integracoes/        ← Adapter TMS (ESL Cloud) — TENANT
│   ├── configuracao/       ← ConfiguracaoSistema (singleton, feature flags) — TENANT
│   ├── whatsbot/           ← Bot WhatsApp (relatórios, lembretes) — TENANT
│   ├── suporte/            ← Tickets de suporte com chat WebSocket — TENANT
│   ├── auditoria/          ← Logs de auditoria — TENANT
│   ├── blog/               ← Blog/Novidades da plataforma — SHARED
│   ├── tutoriais/          ← Vídeos de treinamento — SHARED
│   ├── common/             ← Utilitários compartilhados (geocoding, FCM, tasks)
│   ├── templates/
│   │   ├── aplicativo/     ← Templates do PWA Motorista (manifesto.html = app inteiro)
│   │   ├── desktop/        ← Templates do Painel Operacional
│   │   └── emails/         ← Templates de e-mail
│   └── static/
│       ├── js/             ← JS do PWA (manifesto_v19.js, pwa_tracking.js)
│       ├── css/            ← Estilos
│       └── desktop/        ← JS/CSS do painel (ws.js, etc)
├── docker-compose.yml
├── nginx/
└── infra/
```

---

## Apps Django — Mapa de Navegação

### `core/` — Projeto Principal
- `settings.py` — Configuração completa (SHARED_APPS, TENANT_APPS, Celery Beat, Channels, JWT)
- `urls.py` — URL principal do tenant (API, app, painel, integracoes)
- `urls_public.py` — URL do schema public (blog, landing)
- `asgi.py` — Daphne + Channels (WS routing: manifesto, suporte, operacional)
- `celery.py` — TenantAwareCelery
- `redis_client.py` — Helper para conexão Redis

### `tenants/` — Multi-tenancy
- `models.py` — `Client(TenantMixin)`, `Domain(DomainMixin)`
- Schema-based: cada tenant tem seu próprio schema PostgreSQL

### `usuarios/` — Usuários e Filiais
- `models.py` — `Motorista` (perfil estendido do User), `Filial` (com lat/lng), `PermissaoUsuario`, `DeviceToken`, `PreCadastroSAC`
- `views.py` / `views_login/` — Login por CPF (sessão + JWT + DeviceToken para APK)
- `gestao_views.py` — Gestão de usuários pelo painel

### `manifesto/` — Núcleo Operacional
- `models.py` — `Manifesto`, `NotaFiscal`, `BaixaNF`, `Ocorrencia`, `Frete`, `Veiculo`, `HistoricoOcorrencia`, `LogBaixaNfe`
- `views.py` — API de finalização de manifesto
- `consumers.py` — WebSocket `MonitoramentoConsumer` (heartbeat GPS + atualização de painel)
- `services.py` — `enviar_painel()` (broadcast WS), `notificar_atualizacao_cargas_fretes()`
- `signals.py` — Dispara `enviar_painel` em criação de BaixaNF, Manifesto, NotaFiscal
- `tasks.py` — Tasks Celery (integração TMS, busca manifesto, envio de baixa)
- `rotas/` — Endpoints REST do app motorista:
  - `baixa.py` — Registro de baixa (entrega/ocorrência)
  - `busca.py` — Busca de manifesto no TMS
  - `tracking.py` — `TrackingHeartbeatView` (recebe GPS via REST)
  - `webhook.py` — Webhook do TMS
  - `views_painel.py` — View da Torre de Controle Live

### `integracoes/` — Integração TMS
- `base.py` — `BaseTMSAdapter` (ABC com contrato: buscar, baixar, finalizar)
- `registry.py` — `get_tms_adapter()` (registry pattern)
- `providers/esl_cloud.py` — `ESLCloudAdapter` (GraphQL + REST com ESL Cloud)
- `views/` — APIs SOAP e REST de integração externa

### `configuracao/` — Feature Flags
- `models.py` — `ConfiguracaoSistema` (singleton): tokens ESL, feature flags, tms_provider
- `utils.py` — `get_config()` helper

### `AgenteIa/` — Inteligência Artificial
- `tasks.py` — Pipeline: YOLO (recorte) → Florence-2 (validação) → OCR → TMS
- `run_ia.py` — Execução do modelo YOLO
- `run_florence.py` — Execução do modelo Florence-2

### `common/` — Utilitários Compartilhados
- `geocoding.py` — `buscar_lat_lng_endereco()` via Nominatim + ViaCEP
- `fcm_service.py` — Envio de push via Firebase FCM
- `tasks_notificacoes.py` — Tasks de notificação

---

## Modelos Principais e Relações

```
User (auth.User)
 └── 1:1 Motorista (usuarios)
      ├── → Filial (usuarios)
      ├── → PermissaoUsuario (usuarios)
      ├── → DeviceToken[] (usuarios)
      └── → Manifesto[] (manifesto)
           ├── → Filial (fiscal)
           ├── → Filial (operacao/base)
           ├── → Veiculo
           └── → NotaFiscal[] (manifesto)
                ├── → Frete (manifesto)
                ├── lat/lng (destino)
                ├── → BaixaNF[] (manifesto)
                │    ├── lat/lng (local da baixa)
                │    ├── → Ocorrencia
                │    └── comprovante_foto_url
                └── → HistoricoOcorrencia[] (manifesto)

ConfiguracaoSistema (singleton por tenant)
 └── feature flags, tokens TMS, tms_provider
```

---

## Coordenadas Geográficas Existentes

| Model | Campos | Origem | Uso |
|-------|--------|--------|-----|
| `Filial` | `latitude`, `longitude` | Auto-geocodificação via Nominatim no `save()` | Ponto de partida no mapa de rastreio |
| `NotaFiscal` | `latitude`, `longitude` | Importada do TMS (ESL Cloud) ou geocodificada | Destino da entrega |
| `BaixaNF` | `latitude`, `longitude` | GPS do motorista no momento da baixa | Comprovação de local |
| `Manifesto` | `ultima_lat`, `ultima_lng` | Heartbeat GPS (tracking) | Posição em tempo real |
| `Motorista` | `ultima_lat`, `ultima_lng` | Heartbeat GPS (tracking) | Posição em tempo real |

---

## Endpoints Principais

| Rota | Método | Finalidade |
|------|--------|-----------|
| `/api/manifesto/app/tracking-heartbeat/` | POST | Recebe GPS do motorista (PWA/APK) |
| `/api/manifesto/app/baixa/` | POST | Registra baixa de entrega/ocorrência |
| `/api/manifesto/app/finalizar/` | POST | Finaliza manifesto |
| `/api/manifesto/app/buscar/<numero>/` | GET | Busca manifesto no TMS |
| `/api/rastreio/<manifesto_id>/` | GET | Dados de rastreio para mapa |
| `/ws/painel-logistico/<filial>/` | WS | Torre de Controle Live |
| `/ws/painel-cargas-fretes/<filial>/` | WS | Painel Cargas/Fretes SAC |
| `/api/webhook/tms/` | POST | Webhook do TMS ESL |
| `/api/integracoes/soap/uploadRoute/` | POST | Integração SOAP |

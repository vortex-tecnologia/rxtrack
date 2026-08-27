# ARCHITECTURE.md — RXTrack

> Última atualização: 2026-08-27

## Diagrama de Arquitetura Geral

```
                         ┌──────────────────────────────┐
                         │       CLIENTES / FRONTENDS    │
                         │                              │
                         │  PWA (Motorista)  ──┐        │
                         │  APK Android     ──┤        │
                         │  Painel Desktop  ──┤        │
                         │  App SAC Mobile  ──┘        │
                         └──────────┬───────────────────┘
                                    │ HTTPS
                         ┌──────────▼───────────────────┐
                         │        NGINX (Proxy)          │
                         │   Porta 80 → backend:8000     │
                         │   WebSocket upgrade (WS/WSS)  │
                         └──────────┬───────────────────┘
                                    │
              ┌─────────────────────▼─────────────────────┐
              │              DAPHNE (ASGI)                 │
              │         Django + Channels + DRF            │
              │                                           │
              │  ┌──────────┐  ┌───────────┐  ┌────────┐ │
              │  │   HTTP    │  │ WebSocket │  │  REST  │ │
              │  │  Views    │  │ Consumers │  │  API   │ │
              │  └────┬─────┘  └─────┬─────┘  └───┬────┘ │
              │       │              │             │      │
              │  ┌────▼──────────────▼─────────────▼────┐ │
              │  │       DJANGO TENANT MIDDLEWARE        │ │
              │  │  (Resolve schema por domínio/host)    │ │
              │  └──────────────────┬───────────────────┘ │
              └─────────────────────┼─────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
 ┌────────▼────────┐    ┌──────────▼──────────┐    ┌─────────▼────────┐
 │   PostgreSQL    │    │       Redis          │    │     Celery       │
 │   (Externo)     │    │   (Cache/Broker/     │    │  (Workers)       │
 │                 │    │    Channels/Status)   │    │                  │
 │  Schema public  │    │                      │    │  celery_worker   │
 │  Schema tenant1 │    │  - Channel Layer     │    │  celery_beat     │
 │  Schema tenant2 │    │  - Celery Broker     │    │  celery_ai       │
 │  ...            │    │  - GPS ephemeral     │    │                  │
 └─────────────────┘    └──────────────────────┘    └────────┬─────────┘
                                                             │
                                                    ┌────────▼────────┐
                                                    │  SERVIÇOS EXT.  │
                                                    │                 │
                                                    │  ESL Cloud TMS  │
                                                    │  Nominatim OSM  │
                                                    │  ViaCEP         │
                                                    │  Firebase FCM   │
                                                    │  Evolution API  │
                                                    │  FTP (fotos)    │
                                                    └─────────────────┘
```

---

## Docker Compose — Serviços

```
docker-compose.yml (name: rxtrack_homolog)
│
├── redis          → Redis 7 Alpine (cache, broker, channels)
├── backend        → Daphne (Django ASGI) porta 8011:8000
├── celery_worker  → Worker Celery (fila: celery)
├── celery_beat    → Celery Beat (scheduler)
├── celery_worker_ai → Worker IA (fila: ia_queue, concurrency=1)
└── portainer      → Portainer CE (gerenciamento Docker)

Network: rxtrack_homolog_network (external)
Volumes: rxtrack_homolog_media_data, rxtrack_homolog_portainer_data

⚠️ PostgreSQL NÃO está no compose — roda externamente na VPS
⚠️ Nginx NÃO está no compose — roda como proxy externo na VPS
```

---

## Fluxo de Multi-Tenancy

```
Request HTTP
    │
    ▼
TenantMainMiddleware
    │
    ├── Extrai hostname do request
    ├── Busca Domain → Client no schema "public"
    ├── Ativa o schema do tenant (SET search_path)
    │
    ▼
Django processa no schema do tenant isolado
```

- **Biblioteca**: `django-tenants`
- **Modelo Tenant**: `tenants.Client` (TenantMixin)
- **Modelo Domain**: `tenants.Domain` (DomainMixin)
- **Router**: `TenantSyncRouter`
- **Celery**: `TenantAwareCelery` (preserva contexto de tenant nas tasks)
- **SHARED_APPS**: tenants, tutoriais, blog, daphne, channels, admin, auth...
- **TENANT_APPS**: manifesto, usuarios, mobile, operacional, integracoes, configuracao...

---

## Fluxo de Autenticação

```
                  ┌─────────────┐
                  │  Motorista   │
                  │  (CPF/Senha) │
                  └──────┬──────┘
                         │
           ┌─────────────┼─────────────┐
           │             │             │
      ┌────▼─────┐ ┌────▼─────┐ ┌────▼──────┐
      │  Sessão  │ │   JWT    │ │  Device   │
      │ (Cookie) │ │ (Bearer) │ │  Token    │
      │  PWA     │ │  API     │ │  APK      │
      └──────────┘ └──────────┘ └───────────┘
```

- **PWA**: Login por CPF → Session cookie (1 ano)
- **API REST**: JWT (AccessToken 1d, RefreshToken 365d)
- **APK**: DeviceToken persistente (SharedPreferences nativo)
- **WebSocket**: Autenticação via session cookie OU JWT na query string

---

## Fluxo de Manifesto (Ciclo de Vida)

```
TMS (ESL Cloud)
    │
    ▼
Motorista busca manifesto no app
    │
    ▼
API busca no TMS via ESLCloudAdapter.buscar_manifesto_completo()
    │
    ▼
Manifesto criado (status: EM_TRANSPORTE)
    │ Signal → enviar_painel() → Torre de Controle Live
    │
    ▼
Motorista realiza entregas (Baixas)
    │
    ├── Foto do canhoto → Upload FTP
    ├── BaixaNF criada (ENTREGA ou OCORRENCIA)
    │   │ Signal → enviar_painel()
    │   │ Signal → LogBaixaNfe
    │   └── IA analisa foto (Celery ia_queue)
    │       ├── YOLO recorta canhoto
    │       ├── Florence-2 valida qualidade
    │       └── Aprovado? → Envia baixa ao TMS
    │
    ▼
Todas as notas baixadas
    │
    ▼
Motorista finaliza manifesto
    │
    ├── Manifesto.status = FINALIZADO
    ├── enviar_painel() → Remove card da Torre
    └── Celery task → Finaliza no TMS
```

---

## Fluxo de GPS / Tracking

```
Motorista (PWA/APK)
    │
    ├── PWA: navigator.geolocation (setInterval 30s)
    │   └── pwa_tracking.js → enviarHeartbeat()
    │
    ├── APK: Foreground Service Java (30s loop)
    │   └── POST direto via HTTP (com device_token)
    │
    ▼
POST /api/manifesto/app/tracking-heartbeat/
    │
    ├── 1. Salva no Redis (ephemeral, TTL 1h)
    │      Key: driver_status:{user_id}
    │
    ├── 2. Salva no Manifesto (persistent)
    │      Fields: ultima_lat, ultima_lng, ultimo_acesso,
    │              ultima_bateria, ultima_rede
    │
    └── 3. Broadcast via Channels
           Group: painel_monitoramento_{filial_id}
           Group: painel_monitoramento_todas
           Type: atualizar_status_motorista
                │
                ▼
        Torre de Controle Live (ws.js)
        Atualiza badge de sinal, mapa, bateria
```

---

## Fluxo de WebSocket

```
3 Routers WebSocket registrados em asgi.py:
│
├── manifesto.routing
│   ├── /ws/painel-logistico/<filial>/     → MonitoramentoConsumer
│   └── /ws/painel-cargas-fretes/<filial>/ → CargasFretesConsumer
│
├── suporte.routing
│   └── /ws/suporte/chat/<ticket>/         → SuporteConsumer
│
└── operacional.routing
    └── /ws/torre-erros/<filial>/          → TorreErrosConsumer
```

---

## Fluxo de Integração TMS

```
BaseTMSAdapter (ABC)         ← Contrato abstrato
    │
    └── ESLCloudAdapter      ← Implementação ESL Cloud
         │
         ├── buscar_manifesto_completo()  → GraphQL Data Export
         ├── iniciar_transporte()         → GraphQL Mutation
         ├── enviar_baixa()               → GraphQL invoiceOccurrenceCreate
         ├── enviar_coleta()              → REST API Picks
         ├── finalizar_manifesto()        → GraphQL Mutation
         └── enviar_baixa_minuta()        → REST API Freights

Registry: integracoes/registry.py
    get_tms_adapter() → Lê config.tms_provider → Instancia adapter correto
```

---

## Celery — Workers e Filas

| Worker | Fila | Concorrência | Responsabilidade |
|--------|------|-------------|-----------------|
| `celery_worker` | `celery` | Default | Tasks gerais: busca TMS, envio baixa, WhatsApp |
| `celery_beat` | — | — | Scheduler: relatórios, rebusca, auto-recovery |
| `celery_worker_ai` | `ia_queue` | 1 | Pipeline IA: YOLO + Florence-2 + OCR |

### Tasks Agendadas (Beat)

| Task | Horário | Descrição |
|------|---------|-----------|
| `bot_buscar_tms_e_notificar` | 11h, 14h, 16h | WhatsApp: busca TMS + notifica |
| `bot_reler_cache_e_notificar` | 12h, 15h | WhatsApp: relê cache local |
| `bot_lembrete_finalizacao_20h` | 20h | Lembrete de finalização de rota |
| `bot_relatorio_diario_grupos` | 22h | Relatório diário nos grupos |
| `sincronizar_fotos_motoristas` | 3h | Sync fotos perfil via WhatsApp |
| `verificar_rebusca_filial` | */1min | Rebusca automática ESL por filial |
| `auto_recuperar_baixas_ia` | */2min | Auto-recovery baixas travadas na IA |

---

## Redis — Usos

| Uso | DB | Descrição |
|-----|-----|-----------|
| Celery Broker | 0 | Fila de tarefas |
| Celery Results | 0 | Resultados de tasks |
| Channel Layer | 0 | WebSocket groups/messages |
| GPS Status | 0 | `driver_status:{user_id}` (TTL 1h) |

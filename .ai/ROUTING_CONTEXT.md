# ROUTING_CONTEXT.md — Módulo de Roteamento

> Última atualização: 2026-08-27

## Objetivo

Implementar cálculo de distância real pela malha viária entre motorista e entregas,
usando OSRM (OpenStreetMap) como primeiro provider, com arquitetura preparada para
futuros providers (Google Routes API, HERE, TomTom) e trânsito em tempo real.

---

## Estado Atual

**Status: NÃO IMPLEMENTADO**

O módulo de roteamento ainda não existe. Este documento registra o que já existe no
sistema que é relevante para a implementação.

---

## GPS — Sistema Existente

### Origem dos dados GPS

| Plataforma | Mecanismo | Intervalo | Endpoint |
|-----------|-----------|-----------|----------|
| PWA | `navigator.geolocation` via `pwa_tracking.js` | 30s | REST POST |
| APK | Foreground Service Java (Capacitor) | 30s | REST POST |

### Endpoint REST de tracking

- **Arquivo**: `backend/manifesto/rotas/tracking.py`
- **View**: `TrackingHeartbeatView`
- **URL**: `/api/manifesto/app/tracking-heartbeat/`
- **Auth**: Session/JWT/DeviceToken
- **Payload enviado**:
  ```json
  {
    "type": "heartbeat",
    "lat": -22.9068,
    "lng": -43.1729,
    "battery": 85,
    "is_charging": false,
    "network": "4g",
    "manifesto_id": "67890"
  }
  ```

### Persistência do GPS

1. **Redis** (ephemeral): `driver_status:{user_id}` com TTL 1h
2. **Manifesto** (DB): campos `ultima_lat`, `ultima_lng`, `ultimo_acesso`, `ultima_bateria`, `ultima_rede`
3. **Motorista** (DB): campos `ultima_lat`, `ultima_lng` (duplicidade histórica)

### Formato das coordenadas

- Latitude/Longitude em graus decimais (ex: -22.906800)
- `FloatField` no Manifesto e Motorista
- `DecimalField(max_digits=9, decimal_places=6)` em NotaFiscal e BaixaNF

---

## Geocodificação — Sistema Existente

### Módulo

- **Arquivo**: `backend/common/geocoding.py`
- **Função**: `buscar_lat_lng_endereco(cep=None, endereco=None)`
- **Provider**: Nominatim (OpenStreetMap) + ViaCEP (fallback para endereço)
- **Rate limit**: `time.sleep(1.2)` entre chamadas (respeita TOS do Nominatim)

### Onde é usado

1. **Filial.save()** (`usuarios/models.py`) — Auto-geocodifica quando endereço é preenchido e lat/lng estão vazios
2. **ESLCloudAdapter** (`integracoes/providers/esl_cloud.py`) — Geocodifica endereço das NFs importadas do TMS

### Onde coordenadas ficam armazenadas

| Model | Campos | Tipo | Preenchimento |
|-------|--------|------|--------------|
| `Filial` | `latitude`, `longitude` | `FloatField` | Auto no save() |
| `NotaFiscal` | `latitude`, `longitude` | `DecimalField(9,6)` | Via TMS ou geocoding |
| `BaixaNF` | `latitude`, `longitude` | `DecimalField(9,6)` | GPS do motorista |
| `Manifesto` | `ultima_lat`, `ultima_lng` | `FloatField` | Heartbeat GPS |

---

## Distância — Situação Atual

Atualmente o sistema **NÃO calcula distância** entre motorista e entregas.

O rastreio no mapa (Torre de Controle) usa:
- Coordenadas da filial como ponto de partida
- Coordenadas das baixas como pontos de entrega
- OSRM público (`router.project-osrm.org`) para traçar rota visual no frontend (Leaflet)

**IMPORTANTE**: O OSRM público é usado apenas no JavaScript do frontend para traçar a polyline no mapa.
Não há cálculo de distância no backend.

Referência: `monitoramento.html` linhas 609-627 (fetch para OSRM público)

---

## Arquitetura Planejada

```
                    View / Task
                        │
                        ▼
                 RoutingService
                 (orquestrador)
                        │
                ┌───────┼───────┐
                │               │
        ┌───────▼──────┐ ┌─────▼────────┐
        │ OSRMProvider │ │GoogleProvider │
        │  (V1)        │ │  (Futuro)    │
        └───────┬──────┘ └──────────────┘
                │
                ▼
         OSRM Container
         (Docker interno)
```

### RoutingService (orquestrador)

- Decide qual provider usar (via ConfiguracaoSistema)
- Gerencia cache
- Trata erros e fallbacks
- Expõe métodos de negócio:
  - `calcular_distancia(origem, destino)` → km
  - `calcular_distancia_motorista_entrega(manifesto_id)` → km
  - `calcular_distancia_total_manifesto(manifesto_id)` → km
  - `calcular_distancia_restante(manifesto_id)` → km
  - `calcular_matriz_distancias(origem, destinos[])` → km[]

### Providers

- **Interface**: classe abstrata com métodos `route()`, `matrix()`, `health()`
- **V1**: `OSRMRoutingProvider` — container local
- **V2+**: `GoogleRoutingProvider` — Google Routes API

---

## OSRM — Plano de Container

```yaml
# A ser adicionado ao docker-compose.yml
osrm:
  image: osrm/osrm-backend:latest
  container_name: rxtrack_homolog_osrm
  restart: always
  volumes:
    - ./osrm-data:/data
  command: osrm-routed --algorithm mld /data/brazil-latest.osrm
  networks:
    - rxtrack_homolog_network
  # NÃO expor porta publicamente
```

- **Endpoint interno**: `http://osrm:5000`
- **Dados**: OpenStreetMap (brazil-latest.osm.pbf)
- **Algoritmo**: MLD (Multi-Level Dijkstra) — melhor para grande escala
- **Healthcheck**: `GET http://osrm:5000/health`

---

## Cache — Estratégia Planejada

| Tipo | Cache | TTL | Motivo |
|------|-------|-----|--------|
| Filial → NF (distância planejada) | Redis | 24h | Rota não muda frequentemente |
| Motorista → próxima entrega | Redis | 2min | Posição muda a cada 30s |
| Matriz de distâncias | Redis | 1h | Recalcula quando NF é baixada |

Key pattern: `routing:{tenant_schema}:{tipo}:{ids}`

---

## Roadmap

```
V1 — OSRM + OpenStreetMap
├── Container OSRM local
├── RoutingService + OSRMProvider
├── Distância individual (motorista → entrega)
├── Distância total do manifesto (sequência)
├── Distância restante (pendentes)
└── Cache em Redis

V2 — ETA sem trânsito
├── Velocidade média por tipo de via
└── ETA baseado em distância/velocidade

V3 — Provider Abstraction
├── GoogleRoutingProvider
├── Seleção via ConfiguracaoSistema
└── Fallback automático OSRM ↔ Google

V4 — Trânsito em tempo real
├── Google Routes API com traffic model
└── ETA ajustado por trânsito

V5 — ETA com trânsito
└── Previsão de chegada considerando trânsito

V6 — Otimização de sequência
└── OSRM Trip API / OR-Tools

V7 — Roteirização inteligente
└── ML para previsão de padrões
```

---

## Multi-tenancy

- Todas as queries de roteamento devem operar no schema do tenant ativo
- Cache Redis deve incluir `{schema_name}` na key para isolamento
- OSRM é compartilhado entre tenants (dados de mapa são públicos)
- Configuração de provider por tenant via `ConfiguracaoSistema.tms_config`

---

## Segurança

- OSRM container NÃO expõe porta publicamente (rede Docker interna)
- GPS validado pelo backend (autenticação obrigatória)
- IDs de motorista/manifesto resolvidos pelo backend via sessão/token
- Coordenadas não confiáveis não devem ser aceitas sem validação de range

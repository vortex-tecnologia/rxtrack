# DECISIONS.md — Decisões Técnicas

> Formato: DEC-NNN | Data | Decisão | Motivo | Impacto

---

## DEC-001

**Data**: 2026-08-27  
**Decisão**: Utilizar OSRM como primeiro provider de roteamento.  
**Motivo**: Validar funcionalidade de distância sem depender de APIs pagas. OSRM é open-source, performático e pode rodar em container Docker local. Permite iteração rápida sem custos.  
**Impacto**: RoutingService deve abstrair o provider via interface. Novo container Docker necessário.

---

## DEC-002

**Data**: 2026-08-27  
**Decisão**: Criar abstração de provider (RoutingProvider) seguindo o mesmo padrão de `BaseTMSAdapter`.  
**Motivo**: O projeto já utiliza o pattern de adapter/registry para TMS (`integracoes/base.py` + `registry.py`). Manter consistência arquitetural e permitir troca futura para Google Routes API.  
**Impacto**: Código de negócio nunca chama OSRM diretamente. Sempre passa por RoutingService → Provider.

---

## DEC-003

**Data**: 2026-08-27  
**Decisão**: Usar Redis para cache de rotas calculadas.  
**Motivo**: Redis já está presente na stack para Celery, Channels e GPS status. Reutilizar infraestrutura existente. TTL por tipo de cálculo (24h para rotas fixas, 2min para posição em tempo real).  
**Impacto**: Keys devem incluir schema do tenant para isolamento multi-tenant.

---

## DEC-004

**Data**: 2026-08-27  
**Decisão**: OSRM container na rede Docker interna, sem porta exposta publicamente.  
**Motivo**: Segurança. OSRM não precisa ser acessível de fora. Django se comunica via rede Docker.  
**Impacto**: Apenas o backend Django pode chamar OSRM. Frontend não tem acesso direto.

---

## DEC-005

**Data**: 2026-08-27  
**Decisão**: NÃO alterar a ordem das entregas na V1.  
**Motivo**: A sequência de entregas é definida pelo TMS. Alterá-la automaticamente pode causar problemas operacionais. Otimização de sequência será funcionalidade futura (V6).  
**Impacto**: Distância total é calculada na sequência existente. Sem reordenação.

---

## DEC-006

**Data**: 2026-08-27  
**Decisão**: Reutilizar coordenadas existentes em NotaFiscal (latitude/longitude) em vez de criar novos campos.  
**Motivo**: Os campos já existem e são preenchidos pela importação TMS + geocodificação. Criar campos duplicados violaria DRY.  
**Impacto**: Se NotaFiscal não tiver coordenadas, o cálculo de distância deve ser ignorado para aquela NF (graceful degradation).

---

## DEC-007

**Data**: 2026-08-27  
**Decisão**: Remover signal genérico `manifesto_atualizado` que disparava `enviar_painel()` em TODA atualização do Manifesto.  
**Motivo**: Cada heartbeat GPS (30s × N motoristas) disparava um broadcast desnecessário para todos os clientes da Torre de Controle. Todos os casos reais já são cobertos por signals específicos (BaixaNF, criação, NotaFiscal) e chamadas explícitas (finalização).  
**Impacto**: Redução significativa de broadcasts no Redis/Channels. Sem perda de funcionalidade (bateria e último acesso já atualizam via heartbeat WS direto).

---

## DEC-008

**Data**: 2026-08-28  
**Decisão**: Criar módulo de normalização (`integracoes/normalizers.py`) para processar payloads do TMS no formato Envelope SOAP JSON.  
**Motivo**: O TMS/Webservice de terceiros envia a estrutura Comprovei serializada em JSON (`Envelope -> Body -> uploadRoute -> Rotas`). Em vez de criar endpoints separados e fragmentar o sistema, o endpoint unificado `/api/webhook/tms/` detecta o formato e normaliza internamente.  
**Impacto**: Mantém compatibilidade com payloads existentes e aceita o padrão Comprovei/SSW sem quebrar integrações anteriores.

---

## DEC-009

**Data**: 2026-08-28  
**Decisão**: Cache local prioritário com resolução sob demanda de ID interno para Número Visual via ESL Analytics.  
**Motivo**: O TMS envia o `id` interno de banco da ESL (`6765484`) e não o número visual (`sequence_code`). Para evitar chamadas redundantes à API da ESL a cada atualização de rota via webhook, o sistema primeiro busca no banco local por `numero_manifesto` ou `manifesto_id_tms`. Somente se o manifesto for novo no sistema é feita a consulta na ESL.  
**Impacto**: Economia massiva de requisições à ESL e atualizações de rotas em tempo real no app.


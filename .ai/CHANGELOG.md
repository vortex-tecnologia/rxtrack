# CHANGELOG.md — Histórico de Alterações

> Registra mudanças arquiteturais e funcionais relevantes realizadas por agentes IA.

---

## 2026-08-27

### Criado
- Pasta `.ai/` com memória técnica completa do projeto
  - `PROJECT_CONTEXT.md` — Mapa geral do projeto
  - `ARCHITECTURE.md` — Arquitetura detalhada com diagramas
  - `ROUTING_CONTEXT.md` — Documentação do módulo de roteamento (planejado)
  - `DECISIONS.md` — Decisões técnicas registradas
  - `CHANGELOG.md` — Este arquivo
  - `TODO.md` — Tarefas pendentes
  - `RULES.md` — Regras para agentes IA

### Alterado
- **`manifesto/signals.py`**: Removido signal genérico `manifesto_atualizado` que disparava `enviar_painel()` em TODA atualização do modelo Manifesto. Causava broadcasts desnecessários a cada heartbeat GPS (30s × N motoristas). Todos os cenários reais permanecem cobertos por signals específicos e chamadas explícitas.
- **Torre de Controle Live (`monitoramento.html`, `ws.js`, `services.py`, `views_painel.py`, `detalhes_manifesto_modal.html`)**: Adicionada exibição do ícone de veículo (caminhão/carro) e placa ao lado do número do manifesto (entre o `#` e a categoria do motorista) tanto no carregamento inicial quanto via WebSocket real-time.
- **Mapas de Rastreio (`monitoramento.html`, `manifesto.html`)**: Substituído o provedor de tiles CartoDB (que passou a exigir API key e exibia marca d'água "API KEY REQUIRED") pelo provedor oficial gratuito e sem marca d'água **OpenStreetMap** (`tile.openstreetmap.org`).

### Análise
- Auditoria completa da arquitetura do projeto (Etapas 1-12)
- Mapeamento de todos os apps Django, models, endpoints, Docker, Redis, Celery, WebSocket
- Análise de WebSocket da Torre de Controle Live — identificado bug de excesso de broadcasts

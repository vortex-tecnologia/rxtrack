# CHANGELOG.md — Histórico de Alterações

> Registra mudanças arquiteturais e funcionais relevantes realizadas por agentes IA.

---

## 2026-08-28

### Criado
- **`backend/integracoes/normalizers.py`**: Módulo normalizador para detectar e converter payloads do TMS no formato Envelope SOAP JSON (`Envelope.Body.uploadRoute.Rotas.Rota`) para o formato interno do RXTrack. Extrai Manifesto, Motorista, Filial, Veículo (Placa), Notas Fiscais (com CEP) e dados completos de Frete (Modal, Peso, Volumes, Valor, Embarcador).
- **`backend/usuarios/migrations/0025_filial_operacao_ativa.py`**: Migration adicionando campo `operacao_ativa` no model `Filial`.

### Alterado
- **`backend/manifesto/rotas/webhook.py`**: Webhook adaptado para suportar auto-detecção de formato de payload (Envelope vs Plano) e aceitar autenticação via Header DRF Token (`Authorization: Token ...`) ou Credenciais no payload.
- **`backend/manifesto/tasks.py`**:
  - `processar_webhook_manifesto_task`:
    - Adicionado suporte a cadastro/vínculo automático de `Veiculo` (placa).
    - Adicionado salvamento de `cep` na `NotaFiscal` e disparo de geocodificação automática (`enriquecer_geolocalizacao_nota_task`).
    - **Busca Inteligente**: Se o manifesto já existir no banco (por `numero_manifesto` visual ou `manifesto_id_tms`), atualiza a rota direto sem bater na ESL. Se for novo, consulta a ESL Analytics para resolver o ID interno (`id`) para o Número Visual (`sequence_code`).
    - **Trava de Base**: Ignora manifestos de filiais com `operacao_ativa=False` com log `IGNORADO_FILIAL_INATIVA`.
  - `limpar_manifestos_antigos_aguardando_task`: Task periódica (Celery Beat diário à 01:00 AM) para cancelar rotas em `AGUARDANDO` há mais de 48h.
- **`backend/integracoes/providers/esl_cloud.py`**: Adicionado método `resolver_numero_visual_manifesto(id_tms)` que consulta o report de validação da ESL para obter `sequence_code` pelo `id` de banco.
- **`backend/usuarios/models.py` & `admin.py`**: Adicionado campo e filtro editável `operacao_ativa` na `Filial` para controle de ativação gradual de bases no app.
- **`backend/core/settings.py`**: Adicionado `TMS_WEBHOOK_SECRET` e agendamento da task `limpar-manifestos-antigos-aguardando`.

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

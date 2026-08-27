# TODO.md — Tarefas e Backlog Técnico

> Acompanhamento de tarefas do sistema e do módulo de roteamento.

---

## 🗺️ Módulo de Roteamento (Routing)

### V1 — OSRM + OpenStreetMap (Foco Atual)
- [ ] Criar app Django `routing` (ou módulo de serviços conforme padrão do projeto)
- [ ] Implementar interface abstrata `BaseRoutingProvider`
- [ ] Implementar `OSRMRoutingProvider` com chamadas HTTP ao endpoint `/route/v1/driving/` e `/table/v1/driving/`
- [ ] Implementar `RoutingService` orquestrador (com isolamento multi-tenant, fallback, timeout e tratamento de erros)
- [ ] Configurar container Docker `osrm-backend` no `docker-compose.yml` (rede interna, sem exposição externa)
- [ ] Adicionar campos de persistência de auditoria/métricas de distância em `Manifesto` (`distancia_total_planejada_km`, `distancia_restante_km`, `distancia_recalculada_em`)
- [ ] Implementar cálculo de distância individual (motorista → entrega específica)
- [ ] Implementar cálculo de distância total do manifesto (sequência Base → NF 1 → NF 2 ... → NF N)
- [ ] Implementar cálculo de distância restante (posição atual → próximas NFs pendentes)
- [ ] Integrar recálculo automático quando uma `BaixaNF` for registrada
- [ ] Integrar recálculo periódico/por deslocamento no endpoint `TrackingHeartbeatView`
- [ ] Implementar camada de cache em Redis com chave tenant-aware (`routing:{schema}:...`)
- [ ] Adicionar exibição da distância restante e distância até a entrega no PWA do motorista
- [ ] Adicionar exibição de distâncias na Torre de Controle Live
- [ ] Escrever suite de testes unitários e de integração para o `RoutingService`

---

### V2 — Estimativas de Tempo (ETA sem trânsito)
- [ ] Cálculo de duração estimada baseada na velocidade da malha viária do OSRM
- [ ] Exibição de ETA estimado por nota fiscal no PWA e Torre de Controle

---

### V3 — Abstração Multiprovedor (Google Routes API)
- [ ] Implementar `GoogleRoutingProvider` consumindo Google Routes API
- [ ] Adicionar chave de API e seletor de provedor (`osrm` vs `google`) no `ConfiguracaoSistema`
- [ ] Implementar mecanismo de fallback automático (se Google falhar ou esgotar cota, usa OSRM)

---

### V4 & V5 — Trânsito em Tempo Real e ETA Dinâmico
- [ ] Ativação de dados de trânsito em tempo real via Google Routes API
- [ ] Recálculo de ETA considerando janelas de pico e retenções

---

### V6 & V7 — Otimização de Sequência e Inteligência
- [ ] Otimização automática de sequência de entregas (Traveling Salesperson Problem via OSRM Trip API ou Google Route Optimization)
- [ ] Sugestão de reordenamento inteligente com aprovação do operador

---

## 🛠️ Outras Melhorias do Sistema
- [ ] Padronizar convenção de grupos WebSocket na Torre de Controle (`painel_monitoramento_{id}` vs slug)
- [ ] Adicionar testes automatizados para fluxos críticos de integração TMS ESL
- [ ] Migrar scripts inline do PWA para módulos estruturados

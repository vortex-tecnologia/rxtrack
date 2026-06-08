# Atualizações Aplicadas (Push para Produção)

**Data:** 08/06/2026
**Hora:** 10:10

## O que foi alterado nesta versão:

Abaixo estão listadas as atualizações passadas do projeto principal (`nv`) para o repositório de produção:

1. **Integração com TMS (ESL):**
   - Corrigida a task `finalizar_manifesto_tms_task` (`backend/manifesto/tasks.py`) para enviar o *mutation GraphQL* completo exigido pela documentação da ESL na finalização do manifesto.
   - Removido o campo `closingKm` que estava causando falhas na comunicação com a ESL.
   - Ajustada a listagem de notas, filtrando corretamente pelo `numero_visual` do manifesto.

2. **Fluxo Operacional de Manifestos:**
   - Atualizada a view `salvar_edicao_manifesto_view` (`backend/operacional/views.py`) para disparar a task de integração do TMS em background (via Celery) no exato momento em que o manifesto é marcado como "finalizado" no painel.

3. **Banco de Dados (Mobile):**
   - O campo `endpoint` do modelo `WebPushSubscription` (`backend/mobile/models.py`) foi convertido de `TextField` para `URLField(max_length=500)`, visando maior segurança e adequação dos dados.

4. **Frontend e PWA (Aplicativo Mobile):**
   - Atualização das imagens e ícones do PWA (`icon-160x160.png`, `icon-512x512.png`).
   - Correção do redirecionamento do Service Worker e dos scripts Javascript. A rota de autenticação foi mantida em `/login/` (`backend/static/js/manifesto_v17.js` e `backend/static/js/serviceworker.js`).

---
> **Aviso de Infraestrutura:** Os arquivos de configuração de ambiente (`docker-compose.yml`, `.env`, `Dockerfile`) **não** foram sobrescritos. A porta principal do projeto foi preservada como **8000**, para garantir que o ambiente de produção permaneça separado do ambiente VPS de testes.

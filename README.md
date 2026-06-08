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

<br>

**Data:** 08/06/2026
**Hora:** 15:45

## Adendos e Correções Pós-Migração:

1. **Atualização da Identidade Visual PWA:**
   - Ícones atualizados para o modelo oficial de fundo branco validado pelo cliente, com a versão do Service Worker forçada para atualização em cache.

2. **Ajustes de Layout Responsivo (Painel Operacional):**
   - Corrigido o bug onde a barra lateral ficava presa na tela (Mobile). Agora ela possui barra de rolagem inteligente (escondendo a barra nativa do navegador no Desktop) e se fecha automaticamente ao clicar na área externa da tela.

3. **Notificações do Aplicativo:**
   - Suspenso o alerta de permissão para notificações WebPush no aplicativo do motorista (agora ele loga diretamente, sem janelas chatas). Preparação para futura integração de notificações com WhatsApp.

4. **Painel de Gestão de Usuários (Controle de Acesso):**
   - Correção de validação hierárquica no backend (`usuarios/gestao_views.py`) que bloqueava perfis do tipo `GESTOR` de editar ou excluir permissões de outros Gestores (ou deles mesmos). Agora Gestores possuem passe-livre, enquanto Gerentes continuam com a trava.

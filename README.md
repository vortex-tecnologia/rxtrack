<div align="center">
  <img src="backend/static/images/logo_app.png" alt="Quick Track Logo" width="150" />
</div>

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

---

**Data:** 08/06/2026
**Hora:** 17:30

## Arquitetura PWA Duplo (Motorista e SAC):

Foi realizado um **rollback total** nas tentativas anteriores de unificar as rotas do SAC e Motorista sob o mesmo Service Worker, pois a lógica de interceptação estava prejudicando o cache offline necessário para o motorista em áreas sem internet.

Para resolver o problema definitivamente, o sistema foi dividido em dois PWA instaláveis independentes:

1. **PWA do Motorista (Original):**
   - **Acesso:** `/login/` -> `/app/`
   - **Comportamento:** Mantém o Cache Offline-First agressivo. Nenhuma alteração foi mantida.
2. **PWA do SAC (Novo):**
   - **Acesso Exclusivo:** Nova rota `/login-sac/` redirecionando para `/app-sac/`.
   - **PWA Isolado:** Criados `manifest_sac.json` e `serviceworker_sac.js`.
   - **Comportamento do Cache:** Estratégia "Network-First", garantindo que a equipe do SAC sempre veja a versão mais recente em tempo real (já que operam com internet estável), eliminando o bug de roteamento corrompido ao fechar o app.
   - **Identidade Visual:** Adicionados novos ícones (`icon-sac-160x160.png` e `icon-sac-512x512.png`) com badge "SAC" personalizado, permitindo que os gestores identifiquem facilmente qual aplicativo está instalado na tela inicial do celular.

### Correções (Bugfixes) Posteriores
1. **Erro 500 no Daphne (Backend):** Corrigida falha de inicialização do servidor provocada pela ausência de importação dos decorators `@api_view`, `@permission_classes` e `@authentication_classes` no arquivo `usuarios/views_login/auth_views.py`.
2. **Conflito de Instalação de App (Frontend):** Removida a tag nativa `{% progressive_web_app_meta %}` da tela de login clonada do SAC. Essa tag injetava dinamicamente o `/manifest.json` do motorista, induzindo o navegador a instalar o PWA incorreto. A tag foi substituída por uma referência explícita estática ao `<link rel="manifest" href="/app-sac/manifest_sac.json">`.
3. **Redirecionamento de Logout:** Criação do script customizado `authFetch_sac.js` para garantir que sessões expiradas no SAC redirecionem o usuário de volta para `/login-sac/` em vez de `/login/`.

---

**Data:** 09/06/2026
**Hora:** 14:45

## Multitenancy, Isolamento de Dados e Refinamentos de UI:

1. **Isolamento de Dados por Filial (Multi-Tenancy):**
   - Implementado isolamento rigoroso nas QuerySets do sistema inteiro.
   - As views de **Dashboard, Torre de Controle, Notas e Manifestos** agora filtram as informações com base na `Filial` vinculada ao manifesto.
   - As views de **Auditoria e Performance** filtram os dados olhando para a `Filial` do Motorista.
   - Lógica de Prioridade definida: Parâmetros de URL (ex: `?filial=`) sobrepõem a filial do perfil do usuário. Caso o usuário não tenha filial e não aplique filtros, nenhuma informação sensível é carregada.
   - Adicionado banner de alerta (amarelo) global no `base.html` que notifica usuários que estão acessando o painel mas ainda não possuem vínculo com nenhuma filial.

2. **Cadastro e Edição de Motoristas:**
   - Adicionado o campo `telefone` (Celular com DDD) ao modelo de `Motorista` no banco de dados para preparar terreno para futuras automações via WhatsApp.
   - Modais de criação e edição agora possuem input para "Telefone" (com máscara JS embutida) e campo de seleção Dropdown para vincular/alterar a "Filial" do motorista de forma dinâmica.

3. **Criação Automática de Filiais com ID do TMS:**
   - Atualizada a `buscar_manifesto_completo_task` (`backend/manifesto/tasks.py`) para consumir os campos `mft_crn_id` e `mft_crn_psn_nickname` do payload JSON da ESL.
   - Quando o sistema consulta a ESL e encontra uma filial nova, ele a cria automaticamente no banco já preenchendo o `id_filial_tms`. Se a filial já existe e o ID está vazio (como em cadastros manuais antigos), ele detecta e preenche o ID por baixo dos panos.

4. **UX e Correções na Interface (Bugfixes):**
   - Substituída a imagem quebrada (`empty-truck.svg`) na Torre de Controle por um ícone SVG nativo do Bootstrap responsivo para o cenário sem resultados.
   - Corrigido o Erro 500 no modal de detalhes da Auditoria de Processos que travava a visualização da nota (resolvido injetando fallback seguro na variável `badgeColor` no JS).
   - Menu "Financeiro" removido permanentemente da barra lateral.
   - Cabeçalho da barra lateral modificado: Substituído texto cru pela logo oficial do app (`logo_app.png`) acompanhada de uma tag destacando a filial ativa do usuário logado na sessão atual.

---

> [!IMPORTANT]
> **ANÁLISE ARQUITETURAL E DIRETRIZES FUTURAS (PROJETO MULTI-SAAS):**
> 
> Durante a etapa de refinamento e isolamento de dados do dia 09/06/2026, foi realizada uma avaliação técnica crítica quanto à expansão do sistema para o modelo **Multi-Tenant SaaS** (múltiplas empresas no mesmo painel com isolamento via subdomínios).
> 
> A conclusão estabelecida foi de que o atual banco de dados **MySQL não possui suporte nativo à separação por schemas lógicos** da maneira como a arquitetura moderna do Django (ex: biblioteca `django-tenants`) exige para realizar o roteamento seguro e escalável. 
> 
> Sendo assim, **é mandatório que a infraestrutura realize a migração dos dados do MySQL para um banco de dados PostgreSQL** (versão 13 ou superior) antes que a transição para Multi-SaaS seja implementada. A tentativa de forçar o modelo Multi-SaaS no MySQL ("Row-level Multi-tenancy") exigiria a reescrita maciça de todas as QuerySets do sistema, adicionando chaves estrangeiras de `empresa_id` em todos os modelos (altíssimo custo de engenharia e altíssimo risco de vazamento de dados). O PostgreSQL resolverá este desafio "por baixo dos panos" garantindo segurança, escalabilidade e menor necessidade de reescrita do código fonte.

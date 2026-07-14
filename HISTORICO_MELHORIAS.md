# Histórico de Melhorias e Integrações (Realizadas em 19/06/2026)

Este documento registra todas as arquiteturas, melhorias de resiliência e correções de bugs implementadas hoje no projeto **QuickTrack** para facilitar o alinhamento em sessões futuras.

---

## 1. Resiliência do Chat de Suporte & Fallback HTTP
* **Problema:** Quedas de WebSockets/Redis no servidor VPS de homologação geravam erros HTTP 500 para motoristas e operadores ao tentar enviar mensagens ou abrir chamados.
* **Solução:** 
  - Envolvemos todas as chamadas de sincronização assíncrona do Channels (`group_send`) em blocos de exceção genéricos (`try...except`) no arquivo `backend/suporte/views.py`.
  - Caso o serviço do Redis/Channels falhe no servidor, as chamadas REST para salvar mensagens e tickets no banco de dados continuam funcionando normalmente.
  - O painel do operador e do motorista agora realizam atualizações transparentes via polling HTTP a cada 4 segundos como contingência.

---

## 2. Notificações Web Push nativas via Django Signals
* **Objetivo:** Notificar atendentes SAC e motoristas de novas mensagens de suporte sem depender de conexões WebSocket persistentes.
* **Solução:**
  - Criado o arquivo [signals.py](file:///c:/Users/Micro/Desktop/nv/nv/quicktrack_producao_repo/backend/suporte/signals.py) no app de suporte.
  - Ao criar um chamado, um sinal dispara uma notificação Push nativa (`webpush_service.enviar_notificacao_usuario`) para todos os atendentes e gestores da filial do motorista.
  - Ao enviar uma mensagem:
    - Se o motorista enviou, notifica o operador encarregado ou a equipe SAC da filial.
    - Se o SAC enviou (não-automática), notifica o motorista no celular.
  - Ativado a escuta de sinais registrando-os em `backend/suporte/apps.py` e definindo `default_app_config` em `backend/suporte/__init__.py`.

---

## 3. Rastreamento e Telemetria Resiliente (PWA & Backend)
* **Problema:** A telemetria e o GPS do motorista não atualizavam na Torre de Controle/Gestão de Manifestos. O sinal WebSocket no celular frequentemente desconectava, cortando a transmissão.
* **Solução:**
  - **View REST de Telemetria:** Criamos o endpoint [tracking.py](file:///c:/Users/Micro/Desktop/nv/nv/quicktrack_producao_repo/backend/manifesto/rotas/tracking.py) (`/api/manifesto/app/tracking-heartbeat/`) para receber latitude, longitude, bateria e rede via HTTP POST, salvando no Redis e persistindo no banco (`Manifesto`).
  - **PWA Híbrido:** Ajustamos o script [pwa_tracking.js](file:///c:/Users/Micro/Desktop/nv/nv/quicktrack_producao_repo/backend/static/js/pwa_tracking.js) para rodar o loop de telemetria (a cada 30s) de forma isolada. Se o WebSocket do celular cair, ele faz o fallback automático e envia a telemetria via REST.
  - **Correção de Escopo Global:** Declaramos `heartbeatInterval` e `socketTracking` de forma condicional em `window` no `pwa_tracking.js` para evitar o erro `SyntaxError` por redeclaração em colisão com `manifesto_v19.js` / `manifesto_v16.js`.

---

## 4. Correção de Inicialização e Condição de Corrida no Mapa
* **Problema:** Quando o modal de rastreamento era aberto, a transição do modal criava o mapa de forma assíncrona. Se o WebSocket enviasse a posição logo antes ou durante a abertura, o mapa ainda era nulo e os dados eram descartados, forçando a inicialização do mapa em São Paulo com dados de bateria/rede zerados (`--`).
* **Solução:**
  - **Atributos de Linha (DOM):** Alterado o [manifesto.html](file:///c:/Users/Micro/Desktop/nv/nv/quicktrack_producao_repo/backend/templates/desktop/paginas/manifesto.html) para conter os atributos `data-lat`, `data-lng`, `data-bateria`, `data-rede` e `data-ultimo-acesso` diretamente em cada linha `<tr>` de manifesto na tabela.
  - **Atualização Dinâmica:** O listener do WebSocket em [ws.js](file:///c:/Users/Micro/Desktop/nv/nv/quicktrack_producao_repo/backend/static/desktop/js/monitoramento/ws.js) agora atualiza esses atributos da tabela em tempo real sempre que recebe telemetrias do motorista.
  - **Pré-população:** Ao clicar em "Rastrear", a função lê os dados de telemetria diretamente da tabela e inicializa o mapa e o box de status na localização correta do celular instantaneamente na abertura do modal.

---

## 5. Integração de Histórico de Chamados com o Chat SAC
* **Problema:** Ao clicar em "Histórico" na página de tickets do gestor/admin (`/central-ajuda/`), o sistema exibia apenas um alerta visual de "Em Breve".
* **Solução:**
  - Alteramos o botão de Histórico em [central_ajuda.html](file:///c:/Users/Micro/Desktop/nv/nv/quicktrack_producao_repo/backend/templates/desktop/paginas/central_ajuda.html) para redirecionar o atendente para a URL do Painel SAC (`/suporte/painel/`), passando o `ticket_id` como parâmetro.
  - Atualizamos o script [suporte_painel.js](file:///c:/Users/Micro/Desktop/nv/nv/quicktrack_producao_repo/backend/static/js/suporte_painel.js) para capturar o `ticket_id` da URL no carregamento, identificar o status do ticket, focar a aba correta (Abertos, Meus Atendimentos ou Fechados) e carregar a conversa ativamente.

---

## 6. Centro de Notificações Global e Log de NF-e
* **Problema:** A área de notas fiscais não possuía visibilidade do histórico de tentativas de baixas e retornos de integração do TMS (ESL Cloud), impossibilitando o diagnóstico rápido de erros.
* **Solução:**
  - Criado o modelo `LogBaixaNfe` para armazenar o histórico de sucesso/erro na baixa e na integração TMS.
  - Adicionado `Signals` automatizados que capturam a criação e atualização da baixa para gerar logs sem necessidade de alterar o core das requisições.
  - Criado um Centro de Notificações global na barra superior (`base.html`) com contagem (badge) e dropdown de mensagens de erro em tempo real via polling a cada 15 segundos.
  - Ocorrências de erros geram imediatamente um *Toast* vermelho na tela para o usuário.
  - Na tela de NF-e, adicionado bloco expansível com as 5 últimas atualizações e modal com o Histórico Completo.

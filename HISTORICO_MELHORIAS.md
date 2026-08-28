# Histórico de Melhorias e Integrações

Este documento registra todas as arquiteturas, melhorias de resiliência e correções de bugs implementadas no projeto **RXTrack** para facilitar o alinhamento em sessões futuras.

---

## Patch v2.6.0 (28/08/2026) – Webhook TMS JSON Direto, Normalizador Comprovei/SSW, Resolução Inteligente de Manifestos e Controle de Bases

* **Objetivo:** Permitir o recebimento direto de manifestos e rotas enviados pelo Webservice/TMS em formato JSON (Envelope SOAP convertido), mapeando 100% dos dados para o App (Manifesto, Motorista, Filial, Veículo com Placa, Notas Fiscais com CEP e Frete completo), com resolução de ID interno vs Número Visual e controle de ativação gradual de filiais.
* **Solução e Arquitetura:**
  - **Módulo Normalizador (`backend/integracoes/normalizers.py`):**
    - Identifica automaticamente se o payload recebido é do tipo `Envelope.Body.uploadRoute.Rotas.Rota`.
    - Normaliza a estrutura para o formato interno do RXTrack, extraindo com segurança motorista (CPF/Nome), veículo (placa), filial, paradas (notas fiscais com CEP) e frete (modal, peso, volumes, valor, embarcador).
  - **Webhook Unificado com Dupla Autenticação (`backend/manifesto/rotas/webhook.py`):**
    - Valida prioritariamente o header padrão `Authorization: Token ...` (Django Rest Framework) com controle de consumo mensal.
    - Fallback para validação da credencial no body (`Envelope.Header.Credenciais.Senha`).
  - **Busca e Resolução Inteligente de Manifestos (`backend/manifesto/tasks.py` & `esl_cloud.py`):**
    - *Cache Local Prioritário:* Se o manifesto já existir no banco (por número visual ou ID interno TMS), atualiza a rota direto **sem fazer nenhuma requisição HTTP à ESL**.
    - *Resolução Sob Demanda:* Se o manifesto for novo no sistema, o método `resolver_numero_visual_manifesto` consulta o report de validação da ESL Analytics para descobrir o `sequence_code` (Número Visual real) a partir do ID interno de banco da ESL.
  - **Controle de Ativação Gradual por Base (`Filial.operacao_ativa`):**
    - Campo booleano configurável no Django Admin (`/admin/usuarios/filial/`).
    - Se a filial estiver desmarcada, o webhook descarta a criação de rotas com status `IGNORADO_FILIAL_INATIVA`, evitando poluição de dados nas bases que ainda não utilizam o app.
  - **Limpeza Automática de Fila (> 48h):**
    - Task agendada Celery Beat (`limpar_manifestos_antigos_aguardando_task`) que roda diariamente à 01:00 AM cancelando rotas que ficaram mais de 48h com status `AGUARDANDO`.

---

## Patch v2.5.0 (17/08/2026) – Validação Instantânea V1 de Qualidade de Canhotos no App (PWA & APK)
* **Objetivo:** Filtrar antecipadamente fotos borradas, escuras ou ilegíveis de comprovantes de entrega diretamente no dispositivo móvel do motorista, antes da confirmação de baixa e do envio ao backend/TMS.
* **Solução e Arquitetura:**
  - **Módulo Autônomo Leve ([image_quality_v1.js](file:///c:/Users/Micro/Desktop/RXTrack/backend/static/js/image_quality_v1.js)):**
    - Desenvolvido exclusivamente com APIs nativas do navegador (`Canvas 2D`, `ImageData`, `createImageBitmap`), com **zero bibliotecas externas** (sem OpenCV.js ou modelos pesados).
    - **Quality Score Ponderado (0-100):**
      - *Nitidez (40%):* Variância do Laplaciano sobre matriz grayscale para detecção precisa de desfoque.
      - *Iluminação (25%):* Média e distribuição de luminosidade (detecção de fotos subexpostas ou superexpostas com flash).
      - *Contraste (20%):* Desvio padrão da luminância para assegurar legibilidade documental.
      - *Resolução (15%):* Checagem das dimensões mínimas da imagem original.
  - **Otimização Extrema de Memória (Celulares 4GB de RAM):**
    - Redução automática da imagem para resolução de análise de no máximo 1280px via `createImageBitmap`.
    - Array de grayscale compacto `Uint8Array` (1 byte por pixel vs 4 bytes do RGBA).
    - Liberação imediata de memória do Canvas e descarte de referências após a extração dos dados (consumo transitório < 6MB).
    - Execução assíncrona com `requestIdleCallback` / `setTimeout(0)` entre etapas para manter a interface 100% fluida e responsiva.
  - **Regra de Negócio Específica (Ocorrência 01 - Entrega):**
    - A validação V1 atua **apenas quando a ocorrência selecionada for 01 (Entrega Realizada)** e a nota **não** estiver marcada como retida.
    - Ocorrências de insucesso/devolução ou notas com canhoto retido para conferência mantêm o fluxo livre sem bloqueio.
    - Se o usuário alternar de ocorrência após uma reprovação, o sistema reavalia o estado instantaneamente.
  - **Experiência do Usuário (UI/UX) & Bloqueio Educativo:**
    - Barra de progresso real acompanhando as etapas (*Analisando nitidez*, *Analisando iluminação*, *Analisando contraste*).
    - Durante o processamento ou caso a foto seja reprovada, o botão **'Confirmar Registro'** permanece bloqueado.
    - Feedback claro em caso de reprovação com dicas contextuais (ex: *"Foto muito desfocada. Segure o celular firme e mais próximo do documento."*) e botão direto para **'Tirar nova foto'**.
  - **Resiliência e Fallback:**
    - Timeouts (>15s) ou falhas técnicas liberam o envio automaticamente com log controlado, garantindo que o motorista nunca fique impedido de trabalhar em campo.

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

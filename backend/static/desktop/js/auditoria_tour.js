/**
 * auditoria_tour.js - RXTrack
 * Tour Guiado Interativo do Cockpit de Auditoria de Processos.
 * Utiliza Driver.js com persistência de status no backend.
 */

document.addEventListener("DOMContentLoaded", function() {
    const TOUR_PAGE = 'auditoria_processos';

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function marcarTourConcluido() {
        fetch(`/api/tutorial/concluir/${TOUR_PAGE}/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCookie('csrftoken') }
        }).catch(err => console.error('Erro ao salvar status do tutorial:', err));
    }

    window.iniciarTourAuditoria = function() {
        if (!window.driver || !window.driver.js || !window.driver.js.driver) {
            console.warn("Driver.js não carregado.");
            return;
        }

        const driver = window.driver.js.driver;

        const driverObj = driver({
            showProgress: true,
            animate: true,
            allowClose: true,
            overlayColor: 'rgba(15, 23, 42, 0.82)',
            stagePadding: 8,
            stageRadius: 10,
            popoverClass: 'qt-tour-popover',
            nextBtnText: 'Próximo →',
            prevBtnText: '← Voltar',
            doneBtnText: '✅ Concluir Tutorial',
            progressText: '{{current}} de {{total}}',
            onDestroyStarted: () => {
                marcarTourConcluido();
                driverObj.destroy();
            },
            steps: [
                {
                    popover: {
                        title: '🚀 Bem-vindo à Auditoria de Processos & Cockpit!',
                        description: 'Este é o seu centro de comando em tempo real para auditoria operacional, telemetria de frota e governança de conformidade com IA. Vamos te mostrar cada ferramenta passo a passo!',
                        side: 'center',
                        align: 'center'
                    }
                },
                {
                    element: '#wsConnectionBadge',
                    popover: {
                        title: '📡 Transmissão Ao Vivo (WebSocket)',
                        description: 'Indica que sua tela está conectada em <strong>tempo real</strong> com os aparelhos dos motoristas. Sempre que um motorista envia novo sinal de GPS, nível de bateria ou registra uma entrega, o painel atualiza na hora com efeito de pulso, sem precisar recarregar a página (F5)!',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#filialSelectorSection',
                    popover: {
                        title: '🏢 Isolamento Rigoroso por Filial',
                        description: 'A visualização respeita estritamente a filial do usuário logado: operadores de base física visualizam apenas os seus respectivos motoristas. Usuários com perfil de Gestor ou Administrador podem usar estes botões para alternar entre as filiais ou ver o consolidado de todas as bases.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#kpiCardsSection',
                    popover: {
                        title: '📊 Indicadores Estratégicos no Topo',
                        description: 'Termômetro instantâneo da sua operação:<br>' +
                            '• <strong>Manifestos Ativos:</strong> Quantidade de viagens em trânsito agora.<br>' +
                            '• <strong>Alertas Críticos:</strong> Motoristas sem sinal de GPS há mais de 4h que ainda possuem notas pendentes.<br>' +
                            '• <strong>Cadência da Base:</strong> Velocidade média de baixas da frota em notas por hora.<br>' +
                            '• <strong>Score Médio:</strong> Índice geral de conformidade da frota (0 a 100).<br>' +
                            '• <strong>Penalidades SAC:</strong> Total de notas baixadas pela central classificadas como desleixo do motorista.',
                        side: 'bottom',
                        align: 'center'
                    }
                },
                {
                    element: '#cockpitTabsSection',
                    popover: {
                        title: '📑 Módulos Especializados da Auditoria',
                        description: 'O painel é dividido em 3 áreas:<br>' +
                            '1. 🚚 <strong>Cockpit de Motoristas:</strong> Telemetria viva e rotas em andamento.<br>' +
                            '2. 🏆 <strong>Batalha de Filiais:</strong> Ranking e disputa entre as bases da empresa (quem entrega mais, quem coleta mais e Hall da Fama).<br>' +
                            '3. ⚖️ <strong>Central de Penalidades:</strong> Histórico de desleixo auditado para governança e premiações.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: document.querySelector('.cockpit-col-motorista') || '#cockpitTableHead',
                    popover: {
                        title: '👤 Motorista, Categoria e Veículo',
                        description: 'Exibe a <strong>foto oficial do motorista</strong> sincronizada do perfil, o nome, a <strong>placa do veículo</strong>, a categoria de contratação (Agregado, Empresa ou Dedicado) e o número do manifesto.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: document.querySelector('.cockpit-col-telemetria') || '#cockpitTableHead',
                    popover: {
                        title: '🔋 Telemetria de Hardware (Bateria, Rede e GPS)',
                        description: 'Monitore as condições do aparelho do motorista em tempo real:<br>' +
                            '• <strong>Bateria:</strong> Porcentagem exata com barra colorida (alerta vermelho se estiver abaixo de 15%) e ícone de raio ⚡ quando conectado ao carregador.<br>' +
                            '• <strong>Rede:</strong> Se o motorista está em 5G, 4G, Wi-Fi ou Offline.<br>' +
                            '• <strong>Sinal:</strong> Tempo decorrido desde a última transmissão (ex: <em>Sinal há 12 min</em> ou alerta amarelo se demorar mais de 1h).',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: document.querySelector('.cockpit-col-carga') || '#cockpitTableHead',
                    popover: {
                        title: '📦 Carga: Entregas, Coletas e Despachos',
                        description: 'Classificação detalhada da carga em trânsito: saiba quantas notas são <strong>Entregas</strong>, quantas são <strong>Coletas</strong> e quantos <strong>Despachos/Transferências</strong> compõem a rota.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: document.querySelector('.cockpit-col-progresso') || '#cockpitTableHead',
                    popover: {
                        title: '📈 Progresso da Viagem',
                        description: 'Acompanhe a barra percentual de conclusão da rota e a contagem exata de notas que ainda faltam ser baixadas pelo motorista.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: document.querySelector('.cockpit-col-cadencia') || '#cockpitTableHead',
                    popover: {
                        title: '⏱️ Velocidade de Trabalho & Previsão de Término (ETA)',
                        description: 'O sistema calcula o ritmo de entrega em <strong>notas por hora (n/h)</strong> e prevê matematicamente a hora estimada em que a rota será finalizada (<strong>ETA</strong>), alertando a central caso o motorista esteja atrasado.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: document.querySelector('.cockpit-col-score') || '#cockpitTableHead',
                    popover: {
                        title: '⭐ Score de Conformidade & Auditoria IA',
                        description: 'Cada motorista recebe uma pontuação técnica de 0 a 100 calculada por algoritmo:<br>' +
                            '• Sinal de GPS mantido e bateria suficiente;<br>' +
                            '• Taxa de canhotos aprovados de primeira pela IA (fotos nítidas e legíveis);<br>' +
                            '• Ausência de advertências ou penalidades por desleixo.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: document.querySelector('.cockpit-col-acoes') || '#cockpitTableHead',
                    popover: {
                        title: '⚡ Ações Rápidas: Ficha 360º & WhatsApp',
                        description: '• <strong>Botão 360º:</strong> Abre uma gaveta lateral instantânea com a linha do tempo completa de todas as entregas, fotos dos canhotos auditados pela IA e opção para o SAC forçar baixa.<br>' +
                            '• <strong>Botão WhatsApp:</strong> Abre diretamente a conversa com mensagem operacional pronta direcionada àquele motorista.',
                        side: 'left',
                        align: 'center'
                    }
                },
                {
                    element: '#btnTutorialCockpit',
                    popover: {
                        title: '🎓 Precisa rever? O Tutorial está sempre aqui!',
                        description: 'Você pode reabrir este tour interativo a qualquer momento clicando no botão <strong>Tutorial</strong> no topo da página. Excelente trabalho e ótima gestão!',
                        side: 'bottom',
                        align: 'end'
                    }
                }
            ]
        });

        driverObj.drive();
    };

    // Auto-inicia na primeira vez que o usuário abre a página
    fetch(`/api/tutorial/status/${TOUR_PAGE}/`)
        .then(res => res.json())
        .then(data => {
            if (!data.concluido) {
                setTimeout(window.iniciarTourAuditoria, 800);
            }
        })
        .catch(() => {
            // Silencioso se der erro na verificação
        });
});

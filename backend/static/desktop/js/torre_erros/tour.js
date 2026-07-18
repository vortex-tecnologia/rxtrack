/**
 * Tour Guiado - Torre de Controle de Erros
 * Usa Driver.js para criar um onboarding interativo.
 * Verifica no backend se o usuário já concluiu o tour.
 */
document.addEventListener("DOMContentLoaded", function() {

    const TOUR_PAGE = 'torre_erros';

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
        }).catch(err => console.error('Erro ao salvar tutorial:', err));
    }

    function iniciarTour() {
        const driver = window.driver.js.driver;

        const driverObj = driver({
            showProgress: true,
            animate: true,
            allowClose: true,
            overlayColor: 'rgba(0, 0, 0, 0.75)',
            stagePadding: 8,
            stageRadius: 8,
            popoverClass: 'qt-tour-popover',
            nextBtnText: 'Próximo →',
            prevBtnText: '← Voltar',
            doneBtnText: '✅ Concluir Tour',
            progressText: '{{current}} de {{total}}',
            onDestroyStarted: () => {
                // Quando o usuário conclui ou fecha, marca como feito
                marcarTourConcluido();
                driverObj.destroy();
            },
            steps: [
                {
                    popover: {
                        title: '🚀 Bem-vindo à Torre de Controle!',
                        description: 'Este é o seu centro de monitoramento de erros e falhas do sistema em tempo real. Vou te guiar por cada funcionalidade. Vamos lá!',
                        side: 'center',
                        align: 'center'
                    }
                },
                {
                    element: '#count-criticos',
                    popover: {
                        title: '🔴 Erros Críticos',
                        description: 'Aqui você vê o total de <strong>erros críticos</strong> em aberto na sua filial. São falhas que precisam de atenção imediata, como problemas de integração com o TMS (ESL). <br><br>Quando esse número é maior que zero, o <strong>ícone do menu lateral também pulsa em vermelho</strong> pedindo atenção.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#count-atencao',
                    popover: {
                        title: '🟡 Atenção',
                        description: 'Erros classificados como <strong>Atenção</strong> são problemas que não bloqueiam a operação, mas merecem acompanhamento. Por exemplo: manifesto em trânsito sendo finalizado, ou ocorrências duplicadas.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#count-info',
                    popover: {
                        title: '🔵 Informativos',
                        description: 'Os erros <strong>Informativos</strong> são registros de baixa importância — muitas vezes resolvidos automaticamente pelo sistema. Aparecem quase invisíveis na lista para não atrapalhar.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#count-resolvidos',
                    popover: {
                        title: '✅ Resolvidos Hoje',
                        description: 'Este card mostra quantos erros foram resolvidos <strong>hoje</strong>. <br><br>💡 <strong>Dica:</strong> Clique neste card para abrir o <strong>histórico de resolvidos</strong> com filtro por data. Você consegue ver quem resolveu e se foi manual ou automático.',
                        side: 'bottom',
                        align: 'end'
                    }
                },
                {
                    element: '#filter-severidade',
                    popover: {
                        title: '🔍 Filtro de Severidade',
                        description: 'Use este filtro para ver apenas os erros de um nível específico. Útil quando a lista está grande e você quer focar nos <strong>Críticos</strong> primeiro.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#filter-categoria',
                    popover: {
                        title: '📂 Filtro de Categoria',
                        description: 'Filtra por tipo de erro: <strong>Integração de Baixa</strong>, <strong>Finalização de Manifesto</strong>, <strong>Integração de Coleta</strong>, etc. Cada tipo vem de uma parte diferente do sistema.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#table-erros',
                    popover: {
                        title: '📋 Lista de Erros em Aberto',
                        description: 'Aqui ficam todos os erros pendentes. <br><br>🟢 <strong>Clique em qualquer linha</strong> para abrir os detalhes completos do erro, incluindo o log técnico e a opção de resolver com observação. <br><br>Os erros críticos pulsam em vermelho para chamar atenção!',
                        side: 'top',
                        align: 'center'
                    }
                },
                {
                    element: '#ws-status',
                    popover: {
                        title: '📡 Conexão em Tempo Real',
                        description: 'Este indicador mostra se a conexão WebSocket está ativa. Quando conectado (<strong>verde</strong>), novos erros aparecem instantaneamente na tela sem precisar dar F5. <br><br>Se ficar <strong>vermelho</strong>, o sistema tenta reconectar automaticamente a cada 5 segundos.',
                        side: 'left',
                        align: 'start'
                    }
                },
                {
                    element: '#btn-tour-torre',
                    popover: {
                        title: '❓ Rever Este Tutorial',
                        description: 'Sempre que quiser ver este tour novamente, basta clicar neste botão. <br><br>Agora você já sabe tudo! A Torre de Controle monitora os erros, resolve automaticamente quando possível, e te avisa em tempo real. 💪',
                        side: 'left',
                        align: 'start'
                    }
                }
            ]
        });

        driverObj.drive();
    }

    // Verifica no backend se o usuário já fez o tour
    fetch(`/api/tutorial/status/${TOUR_PAGE}/`)
        .then(res => res.json())
        .then(data => {
            if (!data.concluido) {
                // Aguarda um pouco para a página carregar completamente
                setTimeout(iniciarTour, 1500);
            }
        })
        .catch(err => console.error('Erro ao verificar tutorial:', err));

    // Botão para reiniciar o tour manualmente
    const btnTour = document.getElementById('btn-tour-torre');
    if (btnTour) {
        btnTour.addEventListener('click', function(e) {
            e.preventDefault();
            // Reseta no backend para que o tour possa ser marcado novamente
            fetch(`/api/tutorial/resetar/${TOUR_PAGE}/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': getCookie('csrftoken') }
            }).then(() => {
                iniciarTour();
            });
        });
    }
});

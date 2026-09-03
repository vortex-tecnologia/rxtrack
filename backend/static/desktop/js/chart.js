// RXTrack - Gráfico de Fluxo de Entregas (Enterprise High-End)
document.addEventListener('DOMContentLoaded', () => {
    const rawDataEl = document.getElementById('grafico-data');
    if (!rawDataEl) return;

    let dados;
    try {
        dados = JSON.parse(rawDataEl.textContent);
    } catch (e) {
        console.error('Erro ao ler dados do gráfico:', e);
        return;
    }

    const canvas = document.getElementById('entregasChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // Gradientes dinâmicos
    const gradienteAzul = ctx.createLinearGradient(0, 0, 0, 320);
    gradienteAzul.addColorStop(0, 'rgba(37, 99, 235, 0.45)');
    gradienteAzul.addColorStop(0.5, 'rgba(59, 130, 246, 0.15)');
    gradienteAzul.addColorStop(1, 'rgba(59, 130, 246, 0.0)');

    const gradienteBarras = ctx.createLinearGradient(0, 0, 0, 300);
    gradienteBarras.addColorStop(0, '#2563eb');
    gradienteBarras.addColorStop(1, '#60a5fa');

    let modoAtual = 'acumulado';

    const configAcumulado = {
        type: 'line',
        data: {
            labels: dados.labels,
            datasets: [{
                label: 'Total Acumulado',
                data: dados.valores,
                borderColor: '#2563eb',
                backgroundColor: gradienteAzul,
                borderWidth: 3.5,
                fill: true,
                tension: 0.4,
                pointBackgroundColor: '#ffffff',
                pointBorderColor: '#2563eb',
                pointBorderWidth: 2.5,
                pointRadius: 4,
                pointHoverRadius: 7,
                pointHoverBackgroundColor: '#1d4ed8',
                pointHoverBorderColor: '#ffffff',
                pointHoverBorderWidth: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 900,
                easing: 'easeOutQuart'
            },
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(15, 23, 42, 0.92)',
                    titleColor: '#94a3b8',
                    bodyColor: '#ffffff',
                    padding: 12,
                    cornerRadius: 10,
                    bodyFont: { size: 14, weight: 'bold', family: 'Inter' },
                    titleFont: { size: 12, family: 'Inter' },
                    displayColors: false,
                    callbacks: {
                        label: function(context) {
                            return `📦 ${context.parsed.y} entregas acumuladas`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(226, 232, 240, 0.6)',
                        drawBorder: false
                    },
                    ticks: {
                        color: '#64748b',
                        font: { size: 11, family: 'Inter' },
                        padding: 8
                    }
                },
                x: {
                    grid: { display: false },
                    ticks: {
                        color: '#64748b',
                        font: { size: 11, family: 'Inter' },
                        padding: 8
                    }
                }
            }
        }
    };

    let chartInstance = new Chart(ctx, configAcumulado);

    // Função para alternar visualização entre Acumulado e Por Hora
    window.alternarVisualizacaoGrafico = function(modo) {
        if (modo === modoAtual) return;
        modoAtual = modo;

        // Atualiza botões
        const btnAcum = document.getElementById('btn-grafico-acumulado');
        const btnHora = document.getElementById('btn-grafico-hora');
        if (btnAcum && btnHora) {
            if (modo === 'acumulado') {
                btnAcum.classList.add('btn-primary', 'text-white');
                btnAcum.classList.remove('btn-light', 'text-dark');
                btnHora.classList.remove('btn-primary', 'text-white');
                btnHora.classList.add('btn-light', 'text-dark');
            } else {
                btnHora.classList.add('btn-primary', 'text-white');
                btnHora.classList.remove('btn-light', 'text-dark');
                btnAcum.classList.remove('btn-primary', 'text-white');
                btnAcum.classList.add('btn-light', 'text-dark');
            }
        }

        chartInstance.destroy();

        if (modo === 'hora') {
            chartInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: dados.labels,
                    datasets: [{
                        label: 'Entregas na Hora',
                        data: dados.valores_hora || dados.valores,
                        backgroundColor: gradienteBarras,
                        borderRadius: 8,
                        borderSkipped: false,
                        maxBarThickness: 32
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: {
                        duration: 700,
                        easing: 'easeOutQuart'
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.92)',
                            titleColor: '#94a3b8',
                            bodyColor: '#ffffff',
                            padding: 12,
                            cornerRadius: 10,
                            bodyFont: { size: 14, weight: 'bold', family: 'Inter' },
                            titleFont: { size: 12, family: 'Inter' },
                            displayColors: false,
                            callbacks: {
                                label: function(context) {
                                    return `⚡ ${context.parsed.y} entregas realizadas nesta faixa`;
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: {
                                color: 'rgba(226, 232, 240, 0.6)',
                                drawBorder: false
                            },
                            ticks: {
                                color: '#64748b',
                                font: { size: 11, family: 'Inter' },
                                stepSize: 1,
                                padding: 8
                            }
                        },
                        x: {
                            grid: { display: false },
                            ticks: {
                                color: '#64748b',
                                font: { size: 11, family: 'Inter' },
                                padding: 8
                            }
                        }
                    }
                }
            });
        } else {
            chartInstance = new Chart(ctx, configAcumulado);
        }
    };
});
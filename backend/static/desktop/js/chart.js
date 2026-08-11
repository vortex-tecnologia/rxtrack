const dados = JSON.parse(
    document.getElementById('grafico-data').textContent
);

const ctx = document.getElementById('entregasChart').getContext('2d');

new Chart(ctx, {
    type: 'line',
    data: {
        labels: dados.labels,
        datasets: [{
            label: 'Entregas',
            data: dados.valores,
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            fill: true,
            tension: 0.4,
            borderWidth: 3
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false, // ESSENCIAL para não quebrar o front
        plugins: {
            legend: { display: false }
        },
        scales: {
            y: {
                beginAtZero: true,
                ticks: { stepSize: 1 }
            },
            x: {
                grid: { display: false }
            }
        }
    }
});
// =====================================================
// MONITOR DE REDE COM VIBRAÇÃO PARA CELULAR
// =====================================================
const monitorDeRede = {
    toast: document.getElementById('status-rede-toast'),
    conteudo: document.getElementById('conteudo-status'),
    timeout: null,

    notificar(status) {
        clearTimeout(this.timeout);

        if (status === 'offline') {
            // --- VIBRAÇÃO OFFLINE (Alerta: 3 pulsos) ---
            if (navigator.vibrate) {
                navigator.vibrate([200, 100, 200, 100, 200]);
            }

            this.conteudo.className = 'pilula-status bg-offline';
            this.conteudo.innerHTML = '<i class="bi bi-wifi-off me-2"></i> Você está Offline. Baixas serão salvas localmente.';
            this.toast.classList.add('show');
            
            this.timeout = setTimeout(() => this.toast.classList.remove('show'), 6000);

        } else if (status === 'online') {
            // --- VIBRAÇÃO ONLINE (Sucesso: 1 pulso longo) ---
            if (navigator.vibrate) {
                navigator.vibrate(400);
            }

            this.conteudo.className = 'pilula-status bg-online';
            this.conteudo.innerHTML = '<i class="bi bi-wifi me-2"></i> Conexão restabelecida! Sincronizando...';
            this.toast.classList.add('show');

            this.timeout = setTimeout(() => this.toast.classList.remove('show'), 3000);
            
            if (typeof sincronizarBaixasPendentes === 'function') {
                sincronizarBaixasPendentes();
            }
        }
    }
};

// --- OS "OUVIDOS" DO NAVEGADOR ---

window.addEventListener('offline', () => {
    console.warn("🌐 Sistema detectou: MODO OFFLINE");
    monitorDeRede.notificar('offline');
});

window.addEventListener('online', () => {
    console.info("🌐 Conexão detectada!");
    monitorDeRede.notificar('online');

    const mID_salvo = localStorage.getItem('manifesto_ativo');
    // Adicionei uma verificação para não chamar se a função não existir no arquivo de off
    if (typeof verificarEstadoInicial === 'function') {
        verificarEstadoInicial(); 
    }
});

// Verificação inicial
if (!navigator.onLine) {
    setTimeout(() => monitorDeRede.notificar('offline'), 1000);
}
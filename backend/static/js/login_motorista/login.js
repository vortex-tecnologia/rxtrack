// =====================================================
// CONFIGURAÇÕES DE API
// Pega o domínio atual (ex: http://localhost:8089 ou https://pwa.suaempresa.com)
const BASE_URL = window.location.origin;
// =====================================================
const API_BASE = `${BASE_URL}/api/auth/`;

// =====================================================
// COOKIE HELPERS — Backup de tokens para APK
// =====================================================
function setTokenCookie(name, value, days) {
    const expires = new Date(Date.now() + days * 864e5).toUTCString();
    document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax`;
}

function salvarTokensEmCookies(access, refresh) {
    setTokenCookie('qt_access_token', access, 1);
    if (refresh) setTokenCookie('qt_refresh_token', refresh, 365);
}

// =====================================================
// AUTO-LOGIN (Redireciona se já estiver logado via NativeStorage/Cookies)
// =====================================================
document.addEventListener("DOMContentLoaded", async () => {
    if (typeof window.initAuth === 'function') {
        const autenticado = await window.initAuth();
        if (autenticado) {
            console.log("Usuário já autenticado. Redirecionando para o app...");
            window.location.href = '/app/';
        }
    }
});

// =====================================================
// ELEMENTOS DO DOM
// =====================================================
const form = document.getElementById('login-form');
const alertBox = document.getElementById('alert');
const btnText = document.getElementById('btn-text');
const btnLoading = document.getElementById('btn-loading');

const senhaArea = document.getElementById('senha-area');
const confirmarArea = document.getElementById('confirmar-area');

let modo = 'CPF'; // CPF | LOGIN | PRIMEIRO_ACESSO

// =====================================================
// FUNÇÕES AUXILIARES
// =====================================================
function showAlert(msg, type = 'danger') {
    alertBox.className = `alert alert-${type}`;
    alertBox.textContent = msg;
    alertBox.classList.remove('d-none');
}

function setLoading(state) {
    btnLoading.classList.toggle('d-none', !state);
    btnText.textContent = state ? 'Aguarde...' : 'Continuar';
}

/**
 * Busca dados do motorista logado e salva o ID
 */
async function carregarMotorista(accessToken) {
    const res = await fetch(API_BASE + 'me/', {
        headers: {
            Authorization: `Bearer ${accessToken}`
        }
    });

    if (!res.ok) throw new Error('Erro ao buscar dados do motorista');

    const data = await res.json();

    if (!data.id) throw new Error('Motorista ID não retornado');

    // Salva o ID para uso em WebSockets ou filtros de API
    localStorage.setItem('motorista_id', data.id);
    // Backup em cookie para APK (sobrevive ao app ser fechado)
    setTokenCookie('qt_motorista_id', data.id, 365);
}

// =====================================================
// EVENTO DE SUBMIT (FLUXO PRINCIPAL)
// =====================================================
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    alertBox.classList.add('d-none');
    // 1. Pega o valor bruto do input
    const cpfBruto = document.getElementById('cpf').value.trim();
    // 2. Remove tudo que não for número
    const cpf = cpfBruto.replace(/\D/g, '');
    
    const senha = document.getElementById('senha')?.value;
    const confirmar = document.getElementById('confirmar_senha')?.value;

    if (cpf.length !== 11) {
        showAlert('CPF inválido');
        return;
    }

    setLoading(true);

    try {
        // ETAPA 1 — VERIFICAR CPF
        if (modo === 'CPF') {
            const res = await fetch(API_BASE + 'verificar-cpf/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cpf })
            });

            const data = await res.json();

            if (data.status === 'NOVO_USUARIO') {
                senhaArea.classList.remove('d-none');
                confirmarArea.classList.remove('d-none');
                btnText.textContent = 'Criar Senha';
                modo = 'PRIMEIRO_ACESSO';
            } else if (data.status === 'USUARIO_EXISTENTE') {
                senhaArea.classList.remove('d-none');
                btnText.textContent = 'Entrar';
                modo = 'LOGIN';
            } else {
                showAlert('CPF não encontrado');
            }
        }

        // ETAPA 2 — LOGIN EXISTENTE
        else if (modo === 'LOGIN') {
            const res = await fetch(API_BASE + 'login/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: cpf, password: senha })
            });

            if (!res.ok) throw new Error('Senha inválida');

            const data = await res.json();

            // 🔐 TOKENS: Salva tanto o de acesso quanto o de renovação
            localStorage.setItem('accessToken', data.access);
            localStorage.setItem('refreshToken', data.refresh);
            // 🔒 Backup em cookies para APK (WebView perde localStorage ao fechar)
            salvarTokensEmCookies(data.access, data.refresh);

            // 🔥 BUSCA MOTORISTA
            await carregarMotorista(data.access);

            if (window.NativeStorage) {
                window.NativeStorage.save('accessToken', data.access);
                window.NativeStorage.save('refreshToken', data.refresh);
                window.NativeStorage.save('motorista_id', localStorage.getItem('motorista_id') || '');
            }

            window.location.href = '/app/';
        }

        // ETAPA 3 — PRIMEIRO ACESSO (CRIAÇÃO DE SENHA)
        else if (modo === 'PRIMEIRO_ACESSO') {
            const res = await fetch(API_BASE + 'primeiro-acesso/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    cpf,
                    senha,
                    confirmar_senha: confirmar
                })
            });

            if (!res.ok) throw new Error('Erro ao criar usuário');

            const data = await res.json();

            // 🔐 TOKENS: Salva tanto o de acesso quanto o de renovação
            localStorage.setItem('accessToken', data.access);
            localStorage.setItem('refreshToken', data.refresh);
            // 🔒 Backup em cookies para APK (WebView perde localStorage ao fechar)
            salvarTokensEmCookies(data.access, data.refresh);

            // 🔥 BUSCA MOTORISTA
            const meRes = await fetch(API_BASE + 'me/', {
                headers: {
                    Authorization: `Bearer ${data.access}`
                }
            });

            if (!meRes.ok) throw new Error('Erro ao carregar perfil do motorista');

            const me = await meRes.json();
            localStorage.setItem('motorista_id', me.id);
            setTokenCookie('qt_motorista_id', me.id, 365);

            if (window.NativeStorage) {
                window.NativeStorage.save('accessToken', data.access);
                window.NativeStorage.save('refreshToken', data.refresh);
                window.NativeStorage.save('motorista_id', me.id);
            }

            window.location.href = '/app/';
        }

    } catch (err) {
        showAlert(err.message);
    } finally {
        setLoading(false);
    }
});

let deferredPrompt;
const installBanner = document.getElementById('pwa-install-banner');
const installBtn = document.getElementById('btn-instalar-app');

// O navegador dispara este evento se o app puder ser instalado
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    const isMobile = /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
    if (isMobile) {
        console.log("PWA: Evento beforeinstallprompt disparado (Mobile)!");
        deferredPrompt = e;
        installBanner.style.display = 'block';
    } else {
        console.log("PWA: Evento beforeinstallprompt disparado, mas oculto por ser PC.");
    }
});

installBtn.addEventListener('click', async () => {
    if (deferredPrompt) {
        deferredPrompt.prompt();
        const { outcome } = await deferredPrompt.userChoice;
        console.log(`Escolha do motorista: ${outcome}`);
        installBanner.style.display = 'none';
        deferredPrompt = null;
    }
});

window.addEventListener('appinstalled', () => {
    installBanner.style.display = 'none';
    deferredPrompt = null;
    console.log('PWA instalado com sucesso!');
});

// Verifique se o Service Worker foi registrado com sucesso
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/serviceworker.js', { scope: '/app/' }) // Restringe o escopo à pasta do App
    .then(() => console.log("PWA: Service Worker Registrado no escopo /app/!"))
    .catch((err) => console.log("PWA: Falha no Service Worker", err));
}
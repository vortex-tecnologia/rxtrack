// authFetch_sac.js

// Pega o domínio atual (ex: http://localhost:8089 ou https://pwa.suaempresa.com)
const BASE_URL = window.location.origin;

// Monta as URLs de API e Auth baseadas no domínio que está acessando agora
const API_BASE = `${BASE_URL}/api/`;
const AUTH_BASE = `${BASE_URL}/auth/`;

console.log("Servidor detectado:", BASE_URL);

// =====================================================
// COOKIE HELPERS — Backup persistente para APK (WebView)
// No APK Android, o localStorage pode ser perdido ao fechar
// 100% o app. Cookies sobrevivem no WebView via CookieManager.
// =====================================================
function setTokenCookie(name, value, days) {
    const expires = new Date(Date.now() + days * 864e5).toUTCString();
    document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax`;
}

function getTokenCookie(name) {
    const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : null;
}

function clearTokenCookies() {
    const cookieNames = ['qt_access_token', 'qt_refresh_token', 'qt_motorista_id'];
    cookieNames.forEach(name => {
        document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/;`;
    });
}

// Native preferences sync functions
async function syncToNativePreferences() {
    if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Preferences) {
        const Preferences = window.Capacitor.Plugins.Preferences;
        const access = localStorage.getItem('accessToken');
        const refresh = localStorage.getItem('refreshToken');
        const motoristaId = localStorage.getItem('motorista_id');
        try {
            if (access) {
                await Preferences.set({ key: 'accessToken', value: access });
            } else {
                await Preferences.remove({ key: 'accessToken' });
            }
            if (refresh) {
                await Preferences.set({ key: 'refreshToken', value: refresh });
            } else {
                await Preferences.remove({ key: 'refreshToken' });
            }
            if (motoristaId) {
                await Preferences.set({ key: 'motorista_id', value: String(motoristaId) });
            } else {
                await Preferences.remove({ key: 'motorista_id' });
            }
            console.log("💾 [Capacitor] Tokens sincronizados com as Preferences nativas.");
        } catch (e) {
            console.error("Erro ao sincronizar com as Preferences nativas:", e);
        }
    }
}

async function restaurarTokensDePreferences() {
    if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Preferences) {
        const Preferences = window.Capacitor.Plugins.Preferences;
        try {
            const { value: refresh } = await Preferences.get({ key: 'refreshToken' });
            const { value: access } = await Preferences.get({ key: 'accessToken' });
            const { value: motoristaId } = await Preferences.get({ key: 'motorista_id' });
            if (refresh) {
                console.log("🔄 [Capacitor Recovery] Tokens restaurados de Preferences nativas!");
                localStorage.setItem('refreshToken', refresh);
                if (access) localStorage.setItem('accessToken', access);
                if (motoristaId) localStorage.setItem('motorista_id', motoristaId);
            }
        } catch (e) {
            console.error("Erro ao restaurar de Preferences nativas:", e);
        }
    }
}

/**
 * Salva tokens tanto em localStorage quanto em cookies (backup)
 */
function salvarTokens(access, refresh) {
    localStorage.setItem('accessToken', access);
    setTokenCookie('qt_access_token', access, 1); // 1 dia (mesmo do JWT)

    if (refresh) {
        localStorage.setItem('refreshToken', refresh);
        setTokenCookie('qt_refresh_token', refresh, 365); // 365 dias
    }

    // Sincroniza com Preferences nativas do Capacitor
    syncToNativePreferences();
}

/**
 * Tenta restaurar tokens de cookies quando o localStorage está vazio.
 * Isso salva o motorista de ter que logar de novo no APK.
 */
function restaurarTokensDeCookies() {
    const temRefreshLocal = localStorage.getItem('refreshToken');
    if (temRefreshLocal) return; // Já tem no localStorage, não precisa restaurar

    const cookieRefresh = getTokenCookie('qt_refresh_token');
    const cookieAccess = getTokenCookie('qt_access_token');
    const cookieMotorista = getTokenCookie('qt_motorista_id');

    if (cookieRefresh) {
        console.log("🔄 [APK Recovery] Tokens restaurados de cookies backup!");
        localStorage.setItem('refreshToken', cookieRefresh);
        if (cookieAccess) localStorage.setItem('accessToken', cookieAccess);
        if (cookieMotorista) localStorage.setItem('motorista_id', cookieMotorista);
    }
}

// =====================================================
// AUTENTICAÇÃO PRINCIPAL
// =====================================================
async function initAuth() {
    // 🔑 Tenta restaurar tokens de Preferences nativas (prioridade)
    await restaurarTokensDePreferences();

    // 🔑 Tenta restaurar tokens de cookies (backup para APK)
    restaurarTokensDeCookies();

    const refresh = localStorage.getItem('refreshToken');

    if (!refresh) {
        logout();
        return false;
    }

    const refreshed = await refreshToken();

    if (!refreshed) {
        logout();
        return false;
    }

    return true;
}

async function authFetch(url, options = {}) {
    let access = localStorage.getItem('accessToken');

    options.headers = {
        ...options.headers,
        'Authorization': `Bearer ${access}`
    };

    if (!(options.body instanceof FormData)) {
        options.headers['Content-Type'] = 'application/json';
    }

    try {
        let response = await fetch(url, options);

        if (response.status === 401) {
    console.warn("Access Token expirado. Tentando renovação...");
    const refreshed = await refreshToken();
    
    if (refreshed) {
        access = localStorage.getItem('accessToken');
        options.headers.Authorization = `Bearer ${access}`;
        return await fetch(url, options);
    } else {
        // Se falhar o refresh durante a busca de notas, 
        // evite o logout imediato para não quebrar o modal.
        console.error("Não foi possível renovar o token.");
        return response; // Retorna o 401 para o manifesto.js tratar
    }
}
        return response;
    } catch (err) {
        return null;
    }
}

async function refreshToken() {
    const refresh = localStorage.getItem('refreshToken');
    
    // Log para debug: veja se o token existe no console antes de enviar
    console.log("Tentando refresh com o token:", refresh ? "Presente" : "AUSENTE");

    if (!refresh) return false;

    try {
        const res = await fetch(`${AUTH_BASE}token/refresh/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh: refresh }) // O Django espera a chave "refresh"
        });

        if (res.ok) {
            const data = await res.json();
            // Salva em localStorage + cookies (backup)
            salvarTokens(data.access, data.refresh);
            return true;
        }
        
        // Se retornar 401 aqui, o token de refresh no banco/localStorage é inválido
        console.error("Refresh falhou no servidor:", await res.text());
        return false;
    } catch (err) {
        return false;
    }
}




function logout() {
    localStorage.clear();
    clearTokenCookies(); // Limpa cookies de backup também
    // Limpa Preferences nativas do Capacitor
    if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Preferences) {
        window.Capacitor.Plugins.Preferences.clear().catch(e => console.error(e));
    }
    if (!window.location.pathname.includes('/login-sac/')) {
        window.location.href = '/login-sac/';
    }
}

// ===============================
// EXPOR VARIÁVEIS E FUNÇÕES GLOBAIS
// ===============================
window.API_BASE = API_BASE;
window.AUTH_BASE = AUTH_BASE;

window.authFetch = authFetch;
window.initAuth = initAuth;
window.logout = logout;
window.salvarTokens = salvarTokens;
window.setTokenCookie = setTokenCookie;
window.syncToNativePreferences = syncToNativePreferences;
window.restaurarTokensDePreferences = restaurarTokensDePreferences;

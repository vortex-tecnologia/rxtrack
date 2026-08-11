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

    // 🛡️ VERIFICAÇÃO DE PERMISSÃO SAC
    // Após renovar o token, verifica se o usuário tem perfil autorizado
    // antes de permitir o uso do app SAC
    const isSacApp = window.location.pathname.includes('/app-sac/');
    if (isSacApp) {
        try {
            const access = localStorage.getItem('accessToken');
            const meRes = await fetch(`${BASE_URL}/api/auth/me/`, {
                headers: { 'Authorization': `Bearer ${access}` }
            });

            if (meRes.ok) {
                const perfil = await meRes.json();
                const cargosPermitidos = ['SUPERVISOR', 'GERENTE', 'GESTOR', 'ADMINISTRADOR'];
                const ehSac = perfil.tipo === 'SAC';
                const ehLideranca = cargosPermitidos.includes(perfil.cargo);

                if (!ehSac && !ehLideranca) {
                    // Motorista ou membro comum tentando acessar SAC
                    _mostrarModalAcessoNegadoSAC(perfil.nome, perfil.tipo, perfil.cargo);
                    return false;
                }
            } else {
                // Token válido mas perfil inacessível — deslogar
                logout();
                return false;
            }
        } catch (e) {
            console.error('[SAC Auth] Erro ao verificar permissão:', e);
            logout();
            return false;
        }
    }

    return true;
}

/**
 * Exibe modal de acesso negado, limpa tokens e redireciona para login.
 * Criado dinamicamente para funcionar em qualquer página do SAC.
 */
function _mostrarModalAcessoNegadoSAC(nome, tipoUsuario, cargo) {
    // Cria o backdrop e modal dinamicamente (sem depender de SweetAlert2 ou Bootstrap Modal existente)
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);z-index:99999;display:flex;align-items:center;justify-content:center;padding:20px;';

    const tipoLabel = tipoUsuario === 'MOTORISTA' ? 'Motorista' : `${tipoUsuario} (${cargo})`;

    overlay.innerHTML = `
        <div style="background:white;border-radius:20px;max-width:380px;width:100%;padding:32px 24px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.3);animation:sacPopIn .3s ease;">
            <div style="width:72px;height:72px;border-radius:50%;background:#fee2e2;display:flex;align-items:center;justify-content:center;margin:0 auto 16px;">
                <svg width="36" height="36" fill="none" stroke="#dc3545" stroke-width="2" stroke-linecap="round" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/>
                </svg>
            </div>
            <h5 style="font-weight:700;color:#dc3545;margin-bottom:8px;">Acesso Negado</h5>
            <p style="color:#6c757d;font-size:14px;margin-bottom:6px;">
                Olá <strong>${nome || 'Usuário'}</strong>, seu perfil é <strong>${tipoLabel}</strong>.
            </p>
            <p style="color:#6c757d;font-size:13px;margin-bottom:20px;">
                Este aplicativo é exclusivo para a equipe de <strong>SAC</strong> e <strong>Supervisão/Gestão</strong>.<br>
                Motoristas e membros operacionais devem utilizar o <strong>App do Motorista</strong>.
            </p>
            <button onclick="window.__sacForceLogout()" style="background:linear-gradient(135deg,#dc3545,#c82333);color:white;border:none;padding:12px 32px;border-radius:12px;font-weight:600;font-size:15px;cursor:pointer;width:100%;box-shadow:0 4px 12px rgba(220,53,69,0.3);">
                <span style="margin-right:6px;">🔒</span> Sair e Deslogar
            </button>
        </div>
        <style>@keyframes sacPopIn{from{transform:scale(0.8);opacity:0}to{transform:scale(1);opacity:1}}</style>
    `;

    document.body.innerHTML = '';
    document.body.appendChild(overlay);

    // Função global para o botão
    window.__sacForceLogout = function() {
        localStorage.clear();
        clearTokenCookies();
        if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Preferences) {
            window.Capacitor.Plugins.Preferences.clear().catch(() => {});
        }
        window.location.href = '/login-sac/';
    };
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

// authFetch.js

// Pega o domínio atual (ex: http://localhost:8089 ou https://pwa.suaempresa.com)
const BASE_URL = window.location.origin;

// Monta as URLs de API e Auth baseadas no domínio que está acessando agora
const API_BASE = `${BASE_URL}/api/`;
const AUTH_BASE = `${BASE_URL}/auth/`;

console.log("Servidor detectado:", BASE_URL);
async function initAuth() {
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
            localStorage.setItem('accessToken', data.access);
            if (data.refresh) {
                localStorage.setItem('refreshToken', data.refresh);
            }
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
    if (!window.location.pathname.includes('/login/')) {
        window.location.href = '/login/';
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

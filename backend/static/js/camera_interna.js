// =====================================================
// camera_interna.js — Módulo de Câmera Interna Leve do Track
// Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados.
// =====================================================
// Captura de canhoto via getUserMedia + Canvas, sem abrir a
// câmera nativa do Android, otimizado para aparelhos com pouca RAM.
// =====================================================

// =====================================================
// CONSTANTES CENTRALIZADAS (fáceis de ajustar)
// =====================================================
const CAMERA_CAPTURE_WIDTH  = 1280;
const CAMERA_CAPTURE_HEIGHT = 720;
const CAMERA_JPEG_QUALITY   = 0.75;

// =====================================================
// ESTADO INTERNO (privado ao módulo)
// =====================================================
const _estado = {
    stream: null,           // MediaStream ativo
    flashAtivo: false,      // Estado do torch/flash
    flashSuportado: false,  // Se o aparelho suporta torch
    capturaBlob: null,      // Blob temporário da captura (para preview)
    resolvePromise: null,   // Resolve da Promise retornada por abrir()
    canvasPreviewAlvo: null, // Referência ao canvas-preview do modal de baixa
    aberto: false           // Se o modal está aberto
};

// =====================================================
// API PÚBLICA
// =====================================================
const CameraInterna = {

    /**
     * Abre a câmera interna do Track em tela cheia.
     * @param {HTMLCanvasElement} canvasPreview - O canvas-preview do modal de baixa
     * @returns {Promise<boolean>} true se o motorista confirmou "Usar Foto", false se cancelou
     */
    abrir: function(canvasPreview) {
        return new Promise(async (resolve) => {
            // Prevenir aberturas duplicadas
            if (_estado.aberto) {
                resolve(false);
                return;
            }

            _estado.resolvePromise = resolve;
            _estado.canvasPreviewAlvo = canvasPreview;
            _estado.aberto = true;
            _estado.flashAtivo = false;
            _estado.flashSuportado = false;
            _estado.capturaBlob = null;

            const container = document.getElementById('full-screen-camera');
            if (!container) {
                console.error('[CameraInterna] Container #full-screen-camera não encontrado');
                _estado.aberto = false;
                resolve(false);
                return;
            }

            // Mostra o modal
            container.style.display = 'block';
            _mostrarEstado('preview');

            // Verifica suporte da API de mídia
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                console.warn('[CameraInterna] getUserMedia não suportado neste navegador/ambiente');
                _mostrarErro('Seu navegador ou conexão (HTTP) não permite acesso direto à câmera.');
                return;
            }

            // Solicita a câmera traseira
            try {
                console.log('[CameraInterna] Solicitando câmera traseira...');
                const constraints = {
                    video: {
                        facingMode: { ideal: 'environment' },
                        width:  { ideal: CAMERA_CAPTURE_WIDTH },
                        height: { ideal: CAMERA_CAPTURE_HEIGHT }
                    },
                    audio: false
                };

                _estado.stream = await navigator.mediaDevices.getUserMedia(constraints);

                const video = document.getElementById('video-camera-interna');
                video.srcObject = _estado.stream;
                await video.play();

                // Log de resolução efetiva
                const track = _estado.stream.getVideoTracks()[0];
                const settings = track ? track.getSettings() : {};
                console.log(`[CameraInterna] Câmera aberta: ${settings.width || 'desconhecido'}x${settings.height || 'desconhecido'}, facingMode=${settings.facingMode || 'desconhecido'}`);

                // Verifica suporte ao Flash (torch)
                if (track) {
                    _verificarFlash(track);
                }

            } catch (err) {
                console.error('[CameraInterna] Erro ao acessar câmera:', err.name, err.message);

                let mensagem = 'Não foi possível acessar a câmera.';
                if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                    mensagem = 'Permissão de câmera negada. Permita o acesso à câmera nas configurações do navegador ou celular.';
                } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
                    mensagem = 'Nenhuma câmera encontrada neste aparelho.';
                } else if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
                    mensagem = 'A câmera está ocupada por outro aplicativo. Feche-o e tente novamente.';
                } else if (err.name === 'OverconstrainedError') {
                    // Tenta sem constraints de resolução (fallback para qualquer câmera disponível)
                    try {
                        console.log('[CameraInterna] Tentando fallback sem constraints de resolução...');
                        _estado.stream = await navigator.mediaDevices.getUserMedia({
                            video: true,
                            audio: false
                        });
                        const video = document.getElementById('video-camera-interna');
                        video.srcObject = _estado.stream;
                        await video.play();
                        const fallbackTrack = _estado.stream.getVideoTracks()[0];
                        if (fallbackTrack) _verificarFlash(fallbackTrack);
                        return; // Sucesso no fallback
                    } catch (e2) {
                        mensagem = 'Resolução solicitada não suportada pela câmera deste aparelho.';
                    }
                }

                _mostrarErro(mensagem);
            }
        });
    },

    /**
     * Força o encerramento da câmera interna.
     * Libera todos os recursos (stream, canvas, listeners).
     */
    fechar: function() {
        _fecharInterno(false);
    }
};

// Expor globalmente
window.CameraInterna = CameraInterna;

// =====================================================
// FUNÇÕES INTERNAS
// =====================================================

/**
 * Fecha o modal e libera todos os recursos.
 * @param {boolean} fotoAceita - true se o motorista confirmou "Usar Foto"
 */
function _fecharInterno(fotoAceita) {
    // 1. Para o stream de vídeo (CRÍTICO para liberar memória)
    if (_estado.stream) {
        _estado.stream.getTracks().forEach(track => {
            track.stop();
            console.log('[CameraInterna] Track parado:', track.kind);
        });
        _estado.stream = null;
    }

    // 2. Limpa o vídeo
    const video = document.getElementById('video-camera-interna');
    if (video) {
        video.pause();
        video.srcObject = null;
    }

    // 3. Limpa o canvas de captura temporário
    const canvasCaptura = document.getElementById('canvas-captura-interna');
    if (canvasCaptura) {
        canvasCaptura.width = 1;
        canvasCaptura.height = 1;
        canvasCaptura.getContext('2d').clearRect(0, 0, 1, 1);
    }

    // 4. Limpa o preview de foto capturada
    const imgPreview = document.getElementById('img-preview-captura');
    if (imgPreview) {
        if (imgPreview.src && imgPreview.src.startsWith('blob:')) {
            URL.revokeObjectURL(imgPreview.src);
        }
        imgPreview.src = '';
    }

    // 5. Libera blob temporário
    _estado.capturaBlob = null;

    // 6. Esconde o modal
    const container = document.getElementById('full-screen-camera');
    if (container) {
        container.style.display = 'none';
    }

    // 7. Reset de estado
    _estado.flashAtivo = false;
    _estado.flashSuportado = false;
    _estado.aberto = false;

    // 8. Resolve a Promise
    if (_estado.resolvePromise) {
        const resolve = _estado.resolvePromise;
        _estado.resolvePromise = null;
        _estado.canvasPreviewAlvo = null;
        resolve(fotoAceita);
    }

    console.log('[CameraInterna] Recursos liberados');
}

/**
 * Captura um frame do vídeo e mostra preview estático.
 * Pausa o stream durante a revisão (economia de memória).
 */
function _capturarFoto() {
    const video = document.getElementById('video-camera-interna');
    const canvasCaptura = document.getElementById('canvas-captura-interna');

    if (!video || !canvasCaptura || video.readyState < 2) {
        console.warn('[CameraInterna] Vídeo não pronto para captura');
        return;
    }

    console.log('[CameraInterna] Capturando frame...');

    // Dimensões do frame real do vídeo
    const vw = video.videoWidth;
    const vh = video.videoHeight;

    // Reduz para a resolução alvo se necessário
    let targetW = CAMERA_CAPTURE_WIDTH;
    let targetH = CAMERA_CAPTURE_HEIGHT;

    // Mantém aspect ratio do vídeo real
    const aspectVideo = vw / vh;
    if (aspectVideo > targetW / targetH) {
        // Vídeo mais largo — limita pela largura
        targetH = Math.round(targetW / aspectVideo);
    } else {
        // Vídeo mais alto — limita pela altura
        targetW = Math.round(targetH * aspectVideo);
    }

    // Limita para não ultrapassar o frame real
    if (targetW > vw) targetW = vw;
    if (targetH > vh) targetH = vh;

    canvasCaptura.width = targetW;
    canvasCaptura.height = targetH;

    const ctx = canvasCaptura.getContext('2d');
    ctx.drawImage(video, 0, 0, targetW, targetH);

    console.log(`[CameraInterna] Frame capturado: ${targetW}x${targetH}`);

    // Cria Blob JPEG a partir do canvas de captura
    canvasCaptura.toBlob((blob) => {
        if (!blob) {
            console.error('[CameraInterna] Falha ao criar blob da captura');
            return;
        }

        // Libera blob anterior se existir
        if (_estado.capturaBlob) {
            _estado.capturaBlob = null;
        }
        _estado.capturaBlob = blob;

        console.log(`[CameraInterna] Blob criado: ${(blob.size / 1024).toFixed(1)} KB`);

        // Mostra preview da foto capturada
        const imgPreview = document.getElementById('img-preview-captura');
        if (imgPreview) {
            if (imgPreview.src && imgPreview.src.startsWith('blob:')) {
                URL.revokeObjectURL(imgPreview.src);
            }
            imgPreview.src = URL.createObjectURL(blob);
        }

        // Limpa o canvas temporário imediatamente (libera memória)
        canvasCaptura.width = 1;
        canvasCaptura.height = 1;
        ctx.clearRect(0, 0, 1, 1);

        // Pausa o vídeo (economia de bateria e memória durante revisão)
        video.pause();

        // Mostra estado de revisão
        _mostrarEstado('revisao');

    }, 'image/jpeg', CAMERA_JPEG_QUALITY);
}

/**
 * Volta para o preview de vídeo (descarta a captura atual).
 */
function _refazerFoto() {
    console.log('[CameraInterna] Refazendo foto...');

    // Libera a captura anterior
    const imgPreview = document.getElementById('img-preview-captura');
    if (imgPreview) {
        if (imgPreview.src && imgPreview.src.startsWith('blob:')) {
            URL.revokeObjectURL(imgPreview.src);
        }
        imgPreview.src = '';
    }
    _estado.capturaBlob = null;

    // Resume o vídeo
    const video = document.getElementById('video-camera-interna');
    if (video && _estado.stream) {
        video.play().catch(() => {});
    }

    _mostrarEstado('preview');
}

/**
 * Confirma a foto: popula o canvas-preview do modal de baixa
 * e fecha a câmera interna.
 */
async function _usarFoto() {
    if (!_estado.capturaBlob || !_estado.canvasPreviewAlvo) {
        console.error('[CameraInterna] Sem foto ou canvas alvo');
        return;
    }

    console.log('[CameraInterna] Transferindo foto para canvas-preview...');

    const canvasPreview = _estado.canvasPreviewAlvo;

    try {
        // Usa createImageBitmap para redimensionar nativamente (mesma lógica do fluxo atual)
        const larguraDesejada = 800;
        const bitmap = await createImageBitmap(_estado.capturaBlob, {
            resizeWidth: larguraDesejada,
            resizeQuality: 'medium'
        });

        canvasPreview.width = bitmap.width;
        canvasPreview.height = bitmap.height;
        const ctx = canvasPreview.getContext('2d');
        ctx.drawImage(bitmap, 0, 0);

        // Libera o bitmap imediatamente
        bitmap.close();

        // Guarda arquivo/blob para análise de qualidade V1 se necessário
        try {
            window._ultimoArquivoFoto = new File([_estado.capturaBlob], 'canhoto_interno.jpg', { type: 'image/jpeg' });
        } catch (e) {
            window._ultimoArquivoFoto = _estado.capturaBlob;
        }

        // Marca que o canvas tem foto (mesmo flag do fluxo existente)
        canvasPreview.style.display = 'none';
        canvasPreview.dataset.temFoto = 'true';

        console.log(`[CameraInterna] Foto transferida: ${bitmap.width}x${bitmap.height}`);

        // Fecha a câmera (libera tudo) — ANTES de qualquer outra ação
        _fecharInterno(true);

    } catch (err) {
        console.error('[CameraInterna] Erro ao transferir foto:', err);

        // Fallback sem createImageBitmap
        try {
            const imgUrl = URL.createObjectURL(_estado.capturaBlob);
            const img = new Image();
            img.onload = function() {
                const escala = Math.min(1, 800 / img.width);
                canvasPreview.width = img.width * escala;
                canvasPreview.height = img.height * escala;
                const ctx = canvasPreview.getContext('2d');
                ctx.drawImage(img, 0, 0, canvasPreview.width, canvasPreview.height);
                URL.revokeObjectURL(imgUrl);
                try {
                    window._ultimoArquivoFoto = new File([_estado.capturaBlob], 'canhoto_interno.jpg', { type: 'image/jpeg' });
                } catch (e) {
                    window._ultimoArquivoFoto = _estado.capturaBlob;
                }
                canvasPreview.style.display = 'none';
                canvasPreview.dataset.temFoto = 'true';
                _fecharInterno(true);
            };
            img.onerror = function() {
                URL.revokeObjectURL(imgUrl);
                alert('Erro ao processar a foto. Tente novamente.');
                _fecharInterno(false);
            };
            img.src = imgUrl;
        } catch (e) {
            alert('Erro ao processar a foto. Tente novamente.');
            _fecharInterno(false);
        }
    }
}

/**
 * Toggle do flash (torch).
 */
function _toggleFlash() {
    if (!_estado.stream || !_estado.flashSuportado) return;

    const track = _estado.stream.getVideoTracks()[0];
    if (!track) return;

    _estado.flashAtivo = !_estado.flashAtivo;

    track.applyConstraints({
        advanced: [{ torch: _estado.flashAtivo }]
    }).then(() => {
        console.log(`[CameraInterna] Flash: ${_estado.flashAtivo ? 'LIGADO' : 'DESLIGADO'}`);
        _atualizarBotaoFlash();
    }).catch(err => {
        console.warn('[CameraInterna] Falha ao alterar flash:', err);
        _estado.flashAtivo = false;
        _atualizarBotaoFlash();
    });
}

/**
 * Verifica se o dispositivo suporta torch e atualiza o botão.
 */
function _verificarFlash(track) {
    try {
        const capabilities = track.getCapabilities();
        _estado.flashSuportado = !!(capabilities && capabilities.torch);
        console.log(`[CameraInterna] Flash suportado: ${_estado.flashSuportado}`);
    } catch (e) {
        _estado.flashSuportado = false;
        console.log('[CameraInterna] API de capabilities não suportada');
    }
    _atualizarBotaoFlash();
}

/**
 * Atualiza visual do botão de flash.
 */
function _atualizarBotaoFlash() {
    const btn = document.getElementById('btn-flash-camera-interna');
    if (!btn) return;

    if (!_estado.flashSuportado) {
        btn.style.display = 'none';
        return;
    }

    btn.style.display = 'inline-block';
    if (_estado.flashAtivo) {
        btn.classList.remove('btn-outline-light');
        btn.classList.add('btn-warning');
        btn.innerHTML = '<i class="bi bi-lightning-fill"></i>';
    } else {
        btn.classList.remove('btn-warning');
        btn.classList.add('btn-outline-light');
        btn.innerHTML = '<i class="bi bi-lightning"></i>';
    }
}

/**
 * Alterna entre os estados visuais do modal.
 * @param {'preview'|'revisao'|'erro'} estado
 */
function _mostrarEstado(estado) {
    const videoEl = document.getElementById('video-camera-interna');
    const controlesCam = document.getElementById('controles-camera-preview');
    const controlesRev = document.getElementById('controles-camera-revisao');
    const imgPreview = document.getElementById('img-preview-captura');
    const msgErro = document.getElementById('msg-erro-camera-interna');

    if (!videoEl || !controlesCam || !controlesRev) return;

    switch (estado) {
        case 'preview':
            videoEl.style.display = 'block';
            if (imgPreview) imgPreview.style.display = 'none';
            controlesCam.style.display = 'flex';
            controlesRev.style.display = 'none';
            if (msgErro) msgErro.style.display = 'none';
            break;
        case 'revisao':
            videoEl.style.display = 'none';
            if (imgPreview) imgPreview.style.display = 'block';
            controlesCam.style.display = 'none';
            controlesRev.style.display = 'flex';
            if (msgErro) msgErro.style.display = 'none';
            break;
        case 'erro':
            videoEl.style.display = 'none';
            if (imgPreview) imgPreview.style.display = 'none';
            controlesCam.style.display = 'none';
            controlesRev.style.display = 'none';
            if (msgErro) msgErro.style.display = 'block';
            break;
    }
}

/**
 * Mostra mensagem de erro no modal da câmera com opção de fallback.
 */
function _mostrarErro(mensagem) {
    _mostrarEstado('erro');
    const msgEl = document.getElementById('msg-erro-camera-interna');
    if (msgEl) {
        msgEl.innerHTML = `
            <div class="text-center p-4">
                <i class="bi bi-exclamation-triangle-fill text-warning" style="font-size: 3rem;"></i>
                <p class="text-white mt-3 mb-1 fw-bold">${mensagem}</p>
                <p class="text-white-50 small mt-2">Você pode fechar esta tela ou usar a câmera do celular.</p>
                <div class="d-flex justify-content-center gap-2 mt-4 flex-wrap">
                    <button type="button" class="btn btn-outline-light rounded-pill px-3 py-2" onclick="_cameraInterna_fechar()">
                        <i class="bi bi-x-circle me-1"></i> Fechar
                    </button>
                    <button type="button" class="btn btn-primary rounded-pill px-3 py-2 fw-semibold" onclick="_cameraInterna_usarFallback()">
                        <i class="bi bi-camera-fill me-1"></i> Usar Câmera do Celular
                    </button>
                </div>
            </div>
        `;
    }
}

// =====================================================
// EVENT LISTENERS GLOBAIS (cleanup quando sair da página)
// =====================================================
window.addEventListener('beforeunload', function() {
    if (_estado.stream) {
        _estado.stream.getTracks().forEach(t => t.stop());
        _estado.stream = null;
        console.log('[CameraInterna] Stream liberado no beforeunload');
    }
});

// Se a visibilidade da página mudar (aba minimizada), liberar stream
document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'hidden' && _estado.aberto) {
        console.log('[CameraInterna] Página oculta — fechando câmera');
        _fecharInterno(false);
    }
});

// =====================================================
// EXPOR FUNÇÕES INTERNAS PARA OS ONCLICK DO HTML
// =====================================================
window._cameraInterna_capturar = _capturarFoto;
window._cameraInterna_refazer  = _refazerFoto;
window._cameraInterna_usar     = _usarFoto;
window._cameraInterna_flash    = _toggleFlash;
window._cameraInterna_fechar   = function() { _fecharInterno(false); };
window._cameraInterna_usarFallback = function() {
    _fecharInterno(false);
    window._permitirFallbackNativo = true;
    const inputCamera = document.getElementById('camera-nativa');
    if (inputCamera) {
        inputCamera.click();
    }
    setTimeout(() => {
        window._permitirFallbackNativo = false;
    }, 1500);
};

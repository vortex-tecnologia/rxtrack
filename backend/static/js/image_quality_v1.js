// Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
// image_quality_v1.js - Validação V1 de Qualidade de Foto de Canhoto
// =====================================================
// Módulo LEVE de análise de qualidade de imagem.
// Usa exclusivamente Canvas API nativo (zero bibliotecas externas).
// NÃO substitui YOLO/Florence do backend — é apenas um filtro rápido.
// =====================================================

(function () {
    'use strict';

    // =====================================================
    // CONFIGURAÇÃO CENTRALIZADA (THRESHOLDS)
    // =====================================================
    // Para alterar thresholds futuramente, edite APENAS este bloco.
    const CONFIG = {
        // Tamanho máximo da imagem para análise (px no maior lado)
        // Imagens maiores serão reduzidas para este tamanho antes da análise.
        ANALYSIS_MAX_SIZE: 1280,

        // --- NITIDEZ (Variância do Laplaciano) ---
        // Quanto MAIOR o valor, MAIS nítida a imagem.
        // Abaixo deste threshold = foto borrada/desfocada.
        // Referência: foto boa de documento ~80-300+, foto borrada ~5-30
        BLUR_THRESHOLD: 30,

        // --- ILUMINAÇÃO (Brilho médio 0-255) ---
        // Abaixo de DARK = imagem muito escura
        // Acima de BRIGHT = imagem estourada/superexposta
        DARK_THRESHOLD: 45,
        BRIGHT_THRESHOLD: 235,

        // --- CONTRASTE (Desvio padrão da luminosidade) ---
        // Abaixo deste valor = contraste insuficiente para leitura
        CONTRAST_THRESHOLD: 25,

        // --- RESOLUÇÃO MÍNIMA (px) ---
        // Dimensões mínimas da imagem ORIGINAL (antes do resize de análise)
        MIN_WIDTH: 480,
        MIN_HEIGHT: 360,

        // --- QUALITY SCORE ---
        // Score mínimo para aprovação (0-100)
        SCORE_PASS_THRESHOLD: 50,

        // --- PESOS DAS MÉTRICAS NO SCORE FINAL ---
        WEIGHT_BLUR: 0.40,       // 40% - nitidez é o mais crítico
        WEIGHT_BRIGHTNESS: 0.25, // 25% - iluminação
        WEIGHT_CONTRAST: 0.20,   // 20% - contraste
        WEIGHT_RESOLUTION: 0.15, // 15% - resolução (menos peso isolado)

        // --- TIMEOUT ---
        ANALYSIS_TIMEOUT_MS: 15000, // 15 segundos máximo para toda análise
    };

    // =====================================================
    // UTILITÁRIOS INTERNOS
    // =====================================================

    /**
     * Agenda uma microtask para não bloquear a UI.
     * Usa requestIdleCallback quando disponível, senão setTimeout(0).
     */
    function yieldToMain() {
        return new Promise(resolve => {
            if (typeof requestIdleCallback === 'function') {
                requestIdleCallback(resolve, { timeout: 100 });
            } else {
                setTimeout(resolve, 0);
            }
        });
    }

    /**
     * Cria um canvas de análise reduzido a partir de um File/Blob.
     * Retorna { canvas, ctx, originalWidth, originalHeight, analysisWidth, analysisHeight }
     * Libera o bitmap imediatamente após o desenho.
     */
    async function createAnalysisCanvas(imageSource) {
        let bitmap;
        try {
            // Primeiro, obtem dimensões originais sem resize
            const originalBitmap = await createImageBitmap(imageSource);
            const originalWidth = originalBitmap.width;
            const originalHeight = originalBitmap.height;
            originalBitmap.close();

            // Calcula dimensões de análise (reduz ao MAX_SIZE mantendo proporção)
            const maxDim = Math.max(originalWidth, originalHeight);
            let analysisWidth = originalWidth;
            let analysisHeight = originalHeight;

            if (maxDim > CONFIG.ANALYSIS_MAX_SIZE) {
                const scale = CONFIG.ANALYSIS_MAX_SIZE / maxDim;
                analysisWidth = Math.round(originalWidth * scale);
                analysisHeight = Math.round(originalHeight * scale);
            }

            // Cria bitmap reduzido (o browser faz o resize nativamente — leve)
            bitmap = await createImageBitmap(imageSource, {
                resizeWidth: analysisWidth,
                resizeHeight: analysisHeight,
                resizeQuality: 'medium'
            });

            const canvas = document.createElement('canvas');
            canvas.width = bitmap.width;
            canvas.height = bitmap.height;
            const ctx = canvas.getContext('2d', { willReadFrequently: true });
            ctx.drawImage(bitmap, 0, 0);

            return {
                canvas,
                ctx,
                originalWidth,
                originalHeight,
                analysisWidth: bitmap.width,
                analysisHeight: bitmap.height
            };
        } catch (err) {
            // Fallback para browsers sem createImageBitmap com resize
            return new Promise((resolve, reject) => {
                const url = URL.createObjectURL(imageSource);
                const img = new Image();
                img.onload = function () {
                    const originalWidth = img.width;
                    const originalHeight = img.height;
                    const maxDim = Math.max(originalWidth, originalHeight);
                    let w = originalWidth, h = originalHeight;
                    if (maxDim > CONFIG.ANALYSIS_MAX_SIZE) {
                        const scale = CONFIG.ANALYSIS_MAX_SIZE / maxDim;
                        w = Math.round(originalWidth * scale);
                        h = Math.round(originalHeight * scale);
                    }
                    const canvas = document.createElement('canvas');
                    canvas.width = w;
                    canvas.height = h;
                    const ctx = canvas.getContext('2d', { willReadFrequently: true });
                    ctx.drawImage(img, 0, 0, w, h);
                    URL.revokeObjectURL(url);
                    resolve({ canvas, ctx, originalWidth, originalHeight, analysisWidth: w, analysisHeight: h });
                };
                img.onerror = function () {
                    URL.revokeObjectURL(url);
                    reject(new Error('Falha ao carregar imagem para análise'));
                };
                img.src = url;
            });
        } finally {
            if (bitmap && typeof bitmap.close === 'function') {
                bitmap.close();
            }
        }
    }

    /**
     * Extrai array de grayscale a partir de ImageData.
     * Fórmula: 0.299*R + 0.587*G + 0.114*B (luminância perceptual).
     */
    function getGrayscaleArray(imageData) {
        const data = imageData.data; // Uint8ClampedArray [R,G,B,A,R,G,B,A,...]
        const len = data.length / 4;
        const gray = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
            const offset = i * 4;
            gray[i] = Math.round(0.299 * data[offset] + 0.587 * data[offset + 1] + 0.114 * data[offset + 2]);
        }
        return gray;
    }

    /**
     * Libera memória de um canvas temporário.
     */
    function cleanupCanvas(canvas) {
        if (canvas) {
            canvas.width = 1;
            canvas.height = 1;
            const ctx = canvas.getContext('2d');
            if (ctx) ctx.clearRect(0, 0, 1, 1);
        }
    }

    // =====================================================
    // MÉTRICAS DE QUALIDADE
    // =====================================================

    /**
     * NITIDEZ — Variância do Laplaciano.
     * Aplica um kernel Laplaciano 3x3 sobre a imagem grayscale
     * e calcula a variância do resultado.
     * Quanto menor a variância, mais borrada a imagem.
     *
     * Kernel Laplaciano:
     *  [0,  1, 0]
     *  [1, -4, 1]
     *  [0,  1, 0]
     */
    function measureBlur(gray, width, height) {
        let sum = 0;
        let sumSq = 0;
        let count = 0;

        // Percorre pixels internos (ignora borda de 1px)
        for (let y = 1; y < height - 1; y++) {
            for (let x = 1; x < width - 1; x++) {
                const idx = y * width + x;
                // Laplaciano: center*(-4) + top + bottom + left + right
                const laplacian =
                    -4 * gray[idx] +
                    gray[(y - 1) * width + x] +  // top
                    gray[(y + 1) * width + x] +  // bottom
                    gray[y * width + (x - 1)] +  // left
                    gray[y * width + (x + 1)];   // right

                sum += laplacian;
                sumSq += laplacian * laplacian;
                count++;
            }
        }

        if (count === 0) return { value: 0, passed: false, score: 0 };

        const mean = sum / count;
        const variance = (sumSq / count) - (mean * mean);

        // Score normalizado: 0 = muito borrado, 100 = muito nítido
        let score;
        if (variance >= CONFIG.BLUR_THRESHOLD * 5) {
            score = 100;
        } else if (variance >= CONFIG.BLUR_THRESHOLD) {
            score = 50 + 50 * ((variance - CONFIG.BLUR_THRESHOLD) / (CONFIG.BLUR_THRESHOLD * 4));
        } else {
            score = Math.max(0, 50 * (variance / CONFIG.BLUR_THRESHOLD));
        }

        return {
            value: Math.round(variance * 100) / 100,
            passed: variance >= CONFIG.BLUR_THRESHOLD,
            score: Math.round(score)
        };
    }

    /**
     * ILUMINAÇÃO — Brilho médio + percentuais de extremos.
     * Calcula a média de luminosidade e detecta:
     * - Imagem muito escura (média < DARK_THRESHOLD)
     * - Imagem estourada (média > BRIGHT_THRESHOLD)
     */
    function measureBrightness(gray) {
        const len = gray.length;
        if (len === 0) return { value: 0, passed: false, tooDark: true, tooBright: false, score: 0 };

        let sum = 0;
        let darkCount = 0;
        let brightCount = 0;

        for (let i = 0; i < len; i++) {
            sum += gray[i];
            if (gray[i] < 30) darkCount++;
            if (gray[i] > 240) brightCount++;
        }

        const mean = sum / len;
        const darkPct = darkCount / len;
        const brightPct = brightCount / len;

        const tooDark = mean < CONFIG.DARK_THRESHOLD || darkPct > 0.6;
        const tooBright = mean > CONFIG.BRIGHT_THRESHOLD || brightPct > 0.6;
        const passed = !tooDark && !tooBright;

        // Score: pico no centro (127), degrada nos extremos
        let score;
        if (passed) {
            const distFromCenter = Math.abs(mean - 127);
            score = 100 - (distFromCenter / 127) * 40;
        } else if (tooDark) {
            score = Math.max(0, (mean / CONFIG.DARK_THRESHOLD) * 40);
        } else {
            score = Math.max(0, ((255 - mean) / (255 - CONFIG.BRIGHT_THRESHOLD)) * 40);
        }

        return {
            value: Math.round(mean * 10) / 10,
            passed,
            tooDark,
            tooBright,
            score: Math.round(score)
        };
    }

    /**
     * CONTRASTE — Desvio padrão da luminosidade.
     * Quanto menor o desvio padrão, menos contraste a imagem tem.
     */
    function measureContrast(gray) {
        const len = gray.length;
        if (len === 0) return { value: 0, passed: false, score: 0 };

        let sum = 0;
        for (let i = 0; i < len; i++) sum += gray[i];
        const mean = sum / len;

        let sumSqDiff = 0;
        for (let i = 0; i < len; i++) {
            const diff = gray[i] - mean;
            sumSqDiff += diff * diff;
        }
        const stddev = Math.sqrt(sumSqDiff / len);

        const passed = stddev >= CONFIG.CONTRAST_THRESHOLD;

        let score;
        if (stddev >= CONFIG.CONTRAST_THRESHOLD * 3) {
            score = 100;
        } else if (stddev >= CONFIG.CONTRAST_THRESHOLD) {
            score = 50 + 50 * ((stddev - CONFIG.CONTRAST_THRESHOLD) / (CONFIG.CONTRAST_THRESHOLD * 2));
        } else {
            score = Math.max(0, 50 * (stddev / CONFIG.CONTRAST_THRESHOLD));
        }

        return {
            value: Math.round(stddev * 10) / 10,
            passed,
            score: Math.round(score)
        };
    }

    /**
     * RESOLUÇÃO — Verifica dimensões mínimas da imagem ORIGINAL.
     */
    function checkResolution(originalWidth, originalHeight) {
        const passed = originalWidth >= CONFIG.MIN_WIDTH && originalHeight >= CONFIG.MIN_HEIGHT;

        let score;
        if (passed) {
            const minDim = Math.min(originalWidth, originalHeight);
            score = Math.min(100, 60 + 40 * Math.min(1, (minDim - CONFIG.MIN_HEIGHT) / 1000));
        } else {
            const ratio = Math.min(originalWidth / CONFIG.MIN_WIDTH, originalHeight / CONFIG.MIN_HEIGHT);
            score = Math.max(0, ratio * 50);
        }

        return {
            passed,
            actualWidth: originalWidth,
            actualHeight: originalHeight,
            score: Math.round(score)
        };
    }

    /**
     * Calcula o Quality Score final (0-100) combinando todas as métricas.
     */
    function computeQualityScore(blur, brightness, contrast, resolution) {
        return Math.round(
            blur.score * CONFIG.WEIGHT_BLUR +
            brightness.score * CONFIG.WEIGHT_BRIGHTNESS +
            contrast.score * CONFIG.WEIGHT_CONTRAST +
            resolution.score * CONFIG.WEIGHT_RESOLUTION
        );
    }

    /**
     * Gera lista de motivos de reprovação em linguagem amigável.
     */
    function generateIssues(blur, brightness, contrast, resolution) {
        const issues = [];

        if (!blur.passed) {
            issues.push({
                key: 'blur',
                message: 'Foto muito desfocada.',
                tip: 'Segure o celular firme e mais próximo do documento.'
            });
        }
        if (!brightness.passed && brightness.tooDark) {
            issues.push({
                key: 'dark',
                message: 'Imagem muito escura.',
                tip: 'Tire a foto em um local com mais iluminação.'
            });
        }
        if (!brightness.passed && brightness.tooBright) {
            issues.push({
                key: 'bright',
                message: 'Imagem com iluminação estourada.',
                tip: 'Evite flash direto ou luz muito forte sobre o documento.'
            });
        }
        if (!contrast.passed) {
            issues.push({
                key: 'contrast',
                message: 'Contraste insuficiente.',
                tip: 'Posicione o documento sobre uma superfície de cor diferente.'
            });
        }
        if (!resolution.passed) {
            issues.push({
                key: 'resolution',
                message: 'Resolução insuficiente.',
                tip: 'Use uma câmera com maior resolução ou aproxime o celular.'
            });
        }

        return issues;
    }

    /**
     * Gera mensagem amigável de feedback para o motorista.
     */
    function generateFeedbackMessage(issues) {
        if (issues.length === 0) return '';

        const motivos = issues.map(i => i.message).join(' ');
        const dicaPrincipal = issues[0].tip;

        return motivos + '\n' + dicaPrincipal;
    }

    // =====================================================
    // FUNÇÃO PRINCIPAL DE ANÁLISE
    // =====================================================

    /**
     * Analisa a qualidade de uma imagem (File/Blob).
     *
     * @param {File|Blob} imageSource - A imagem a ser analisada
     * @param {Function} onProgress - Callback de progresso: (step, percent, message)
     * @returns {Promise<Object>} Resultado da análise
     */
    async function analyze(imageSource, onProgress) {
        const startTime = performance.now();
        const progressFn = typeof onProgress === 'function' ? onProgress : function () { };

        return new Promise(async (resolve, reject) => {
            const timeoutId = setTimeout(() => {
                reject(new Error('TIMEOUT: Análise excedeu o tempo limite'));
            }, CONFIG.ANALYSIS_TIMEOUT_MS);

            try {
                // ETAPA 0: Preparação
                progressFn('prepare', 5, 'Preparando análise...');
                await yieldToMain();

                const analysisData = await createAnalysisCanvas(imageSource);
                const { canvas, ctx, originalWidth, originalHeight, analysisWidth, analysisHeight } = analysisData;

                progressFn('prepare', 10, 'Extraindo dados da imagem...');
                await yieldToMain();

                // Extrai ImageData e converte para grayscale
                const imageData = ctx.getImageData(0, 0, analysisWidth, analysisHeight);
                const gray = getGrayscaleArray(imageData);

                // Libera canvas de análise AGORA (não precisamos mais dele)
                cleanupCanvas(canvas);

                // ETAPA 1: Nitidez
                progressFn('blur', 20, 'Analisando nitidez...');
                await yieldToMain();
                const blur = measureBlur(gray, analysisWidth, analysisHeight);

                progressFn('blur', 35, 'Analisando foco...');
                await yieldToMain();

                // ETAPA 2: Iluminação
                progressFn('brightness', 45, 'Analisando iluminação...');
                await yieldToMain();
                const brightness = measureBrightness(gray);

                progressFn('brightness', 60, 'Verificando exposição...');
                await yieldToMain();

                // ETAPA 3: Contraste
                progressFn('contrast', 70, 'Analisando contraste...');
                await yieldToMain();
                const contrast = measureContrast(gray);

                progressFn('contrast', 80, 'Verificando legibilidade...');
                await yieldToMain();

                // ETAPA 4: Resolução + Score Final
                progressFn('resolution', 85, 'Verificando resolução...');
                await yieldToMain();
                const resolution = checkResolution(originalWidth, originalHeight);

                progressFn('scoring', 92, 'Finalizando análise...');
                await yieldToMain();

                const score = computeQualityScore(blur, brightness, contrast, resolution);
                const issues = generateIssues(blur, brightness, contrast, resolution);
                // Aprovado se score >= threshold E nitidez (mais crítico) passou
                const approved = score >= CONFIG.SCORE_PASS_THRESHOLD && blur.passed;

                const feedbackMessage = generateFeedbackMessage(issues);
                const duration = Math.round(performance.now() - startTime);

                progressFn('done', 100, approved ? 'Foto aprovada!' : 'Análise concluída');

                clearTimeout(timeoutId);

                resolve({
                    approved,
                    score,
                    issues,
                    feedbackMessage,
                    metrics: { blur, brightness, contrast, resolution },
                    duration
                });

            } catch (err) {
                clearTimeout(timeoutId);
                reject(err);
            }
        });
    }

    // =====================================================
    // EXPORTAÇÃO GLOBAL
    // =====================================================
    window.ImageQualityV1 = {
        analyze,
        CONFIG, // Exposto para debug/testes no console
        version: '1.0.0'
    };

    console.log('[ImageQualityV1] Módulo carregado. Versão 1.0.0 — Zero dependências externas.');

})();

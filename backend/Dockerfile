# Usa uma imagem base Python
FROM python:3.11-slim

# Define o diretório de trabalho. O root do seu projeto é copiado aqui.
WORKDIR /transportadora_backend

# Configurações de performance e logs
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Instala dependências do sistema
 
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gcc \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    python3-dev \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    graphviz \
    libgraphviz-dev \
    # --- DEPENDÊNCIAS CORRIGIDAS PARA AGENTE IA (OpenCV & EasyOCR/Tesseract) ---
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    tesseract-ocr \
    tesseract-ocr-por \
    # ----------------------------------------------------------------
    && rm -rf /var/lib/apt/lists/*

# Copia e instala as dependências Python
COPY requirements.txt /transportadora_backend/
RUN pip install --upgrade pip

# Instala PyTorch CPU-only (evita baixar ~5GB de bibliotecas CUDA/cuDNN desnecessárias)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Instala o restante das dependências
RUN pip install --no-cache-dir -r requirements.txt

# Remove bibliotecas NVIDIA residuais que o ultralytics pode ter puxado
RUN pip uninstall -y nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 nvidia-cuda-nvrtc-cu12 \
    nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 \
    nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nccl2 nvidia-nvtx-cu12 \
    nvidia-nvjitlink-cu12 triton 2>/dev/null || true

# Limpa cache antigo e pre-download do modelo Florence-2-base na imagem Docker
RUN rm -rf /root/.cache/huggingface/modules/transformers_modules/microsoft/Florence* 2>/dev/null || true
RUN python -c "from transformers import AutoProcessor, AutoModelForCausalLM; AutoProcessor.from_pretrained('microsoft/Florence-2-base', trust_remote_code=True); AutoModelForCausalLM.from_pretrained('microsoft/Florence-2-base', trust_remote_code=True)" || true

# Copia o código da aplicação
COPY . /transportadora_backend/
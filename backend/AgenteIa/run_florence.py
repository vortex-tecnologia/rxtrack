import sys
import os
import re
import cv2
import torch
import numpy as np
from PIL import Image

def process_florence(crop_path, expected_nfe=""):
    if not os.path.exists(crop_path):
        print("FLORENCE_ERRO:Arquivo nao encontrado", flush=True)
        return

    # Garante 1 thread para seguranca no Celery
    torch.set_num_threads(1)

    try:
        from transformers import AutoProcessor, AutoModelForCausalLM
    except ImportError:
        print("FLORENCE_ERRO:transformers nao instalado", flush=True)
        return

    # Carrega processador e modelo Florence-2-base
    model_id = 'microsoft/Florence-2-base'
    try:
        processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True)
        model.eval()
    except Exception as e:
        print(f"FLORENCE_ERRO:Falha ao carregar modelo ({str(e)})", flush=True)
        return

    # Carrega imagem OpenCV
    img_bgr = cv2.imread(crop_path)
    if img_bgr is None:
        print("FLORENCE_ERRO:Falha ao abrir imagem", flush=True)
        return

    expected_nfe = str(expected_nfe or '').strip()

    def run_ocr_on_pil(pil_img):
        prompt = "<OCR>"
        inputs = processor(text=prompt, images=pil_img, return_tensors="pt")
        with torch.no_grad():
            generated_ids = model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=1024,
                num_beams=3,
                do_sample=False
            )
        text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        # Remove tag do prompt
        text = text.replace("<OCR>", "").strip()
        return text

    # --- 1. DETECÇÃO DE ORIENTAÇÃO / ROTAÇÃO (0°, 90°, 180°, 270°) ---
    rotations = [0, 90, 180, 270]
    best_angle = 0
    best_score = -1
    best_text = ""
    texts_per_angle = {}

    for angle in rotations:
        if angle == 0:
            rotated = img_bgr
        elif angle == 90:
            rotated = cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
        elif angle == 180:
            rotated = cv2.rotate(img_bgr, cv2.ROTATE_180)
        elif angle == 270:
            rotated = cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)

        pil_img = Image.fromarray(cv2.cvtColor(rotated, cv2.COLOR_BGR2RGB))
        txt = run_ocr_on_pil(pil_img)
        texts_per_angle[angle] = txt

        # Pontuação: Contagem de caracteres alfanuméricos legíveis
        score = sum(c.isalnum() for c in txt)

        # Bônus gigante se encontrar o número exato da NF-e nesta rotação
        if expected_nfe and len(expected_nfe) >= 3 and expected_nfe in txt:
            score += 10000

        if score > best_score:
            best_score = score
            best_angle = angle
            best_text = txt

    # --- 2. ROTAÇÃO DA IMAGEM ---
    if best_angle != 0:
        if best_angle == 90:
            img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
        elif best_angle == 180:
            img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_180)
        elif best_angle == 270:
            img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
        # Salva imagem corrigida de volta
        cv2.imwrite(crop_path, img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])

    # --- 3. AVALIAÇÃO DE QUALIDADE ---
    # Se menos de 15 caracteres legíveis forem encontrados em todas as rotações, imagem é ruim/ilegível
    qualidade = "BOA" if best_score >= 15 else "RUIM"

    # --- 4. EXTRAÇÃO DE CAMPOS (RECEBEDOR, DOCUMENTO, NFE) ---
    nfe_encontrada = "SIM" if (expected_nfe and expected_nfe in best_text) else "NAO"

    recebedor = ""
    documento = ""

    lines = [line.strip() for line in best_text.split('\n') if line.strip()]
    full_str = " ".join(lines)

    # Heurística para Nome do Recebedor
    match_rec = re.search(r'(?:RECEBEDOR|NOME|ASSINATURA|RECEBI(?:MENTO)?)\s*[:\-\=]?\s*([A-ZÀ-Úa-zà-ú\s]{3,40})', full_str, re.IGNORECASE)
    if match_rec:
        rec_candidate = match_rec.group(1).strip()
        # Filtra palavras comuns de cabeçalho
        if not re.search(r'(?:NOTA|FISCAL|DATA|HORA|DECLARO|SERIE|NUMERO)', rec_candidate, re.IGNORECASE):
            recebedor = rec_candidate.title()

    # Heurística para CPF/RG/Documento
    match_cpf = re.search(r'\b\d{3}\.?\d{3}\.?\d{3}\-?\d{2}\b', full_str)
    match_rg = re.search(r'\b\d{2}\.?\d{3}\.?\d{3}\-?[\dX]\b', full_str, re.IGNORECASE)
    match_doc_generic = re.search(r'(?:RG|CPF|DOC|DOCUMENTO|ID)\s*[:\-\=]?\s*([\d\.\-X]{5,14})', full_str, re.IGNORECASE)

    if match_cpf:
        documento = match_cpf.group(0)
    elif match_rg:
        documento = match_rg.group(0)
    elif match_doc_generic:
        documento = match_doc_generic.group(1).strip()

    # Saídas formatadas para o stdout
    print(f"FLORENCE_ANGULO:{best_angle}", flush=True)
    print(f"FLORENCE_QUALIDADE:{qualidade}", flush=True)
    print(f"FLORENCE_NFE:{nfe_encontrada}", flush=True)
    if recebedor:
        print(f"FLORENCE_RECEBEDOR:{recebedor}", flush=True)
    if documento:
        print(f"FLORENCE_DOCUMENTO:{documento}", flush=True)
    print("FLORENCE_SUCESSO", flush=True)

if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    if len(sys.argv) < 2:
        print("FLORENCE_ERRO:Argumentos insuficientes", flush=True)
        sys.exit(1)

    crop_path_arg = sys.argv[1]
    expected_nfe_arg = sys.argv[2] if len(sys.argv) > 2 else ""

    process_florence(crop_path_arg, expected_nfe_arg)

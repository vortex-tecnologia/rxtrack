import sys
import os
import cv2
import numpy as np

def run_ml(img_path, watermark_text="", expected_nfe="", skip_ocr=False, codigo_ocorrencia="01"):
    print(f"CHECKPOINT: Iniciando importacoes para Ocorrência {codigo_ocorrencia}...", flush=True)
    import cv2
    import numpy as np
    from ultralytics import YOLO
    
    print("CHECKPOINT: YOLO Importado.", flush=True)
    import torch
    
    # Configuracao de seguranca
    torch.set_num_threads(1)
    
    # Configura diretorios
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model_path = os.path.join(BASE_DIR, 'AgenteIa', 'models_bin', 'best.pt')
    
    # Carrega modelos
    model_yolo = YOLO(model_path)
    
    # Carrega imagem
    img_original = cv2.imread(img_path)
    if img_original is None:
        print("FALHA: Nao abriu", flush=True)
        return
        
    # YOLO Detecta (Confianca minima relaxada para 50% devido a variacao de luminosidade/camera)
    results = model_yolo.predict(source=img_original, conf=0.5, verbose=False)
    result = results[0]
    
    valid_crops = []
    
    # Percorre todas as detecções para encontrar canhotos (Classe 0)
    for box in result.boxes:
        if int(box.cls[0]) == 0:  
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            h_img, w_img = img_original.shape[:2]
            
            box_w = x2 - x1
            box_h = y2 - y1
            
            # --- FILTROS DE SEGURANÇA ---
            area_img = w_img * h_img
            area_box = box_w * box_h
            
            # 1. O canhoto nao pode ser um "pontinho" na tela (menos de 3% da area total)
            if area_box < (area_img * 0.03):
                continue
                
            # 2. O canhoto nao pode ser absurdamente quadrado (aspect_ratio muito proximo de 1.0)
            aspect_ratio = max(box_w, box_h) / min(box_w, box_h)
            if aspect_ratio < 1.2:
                continue
                
            # Margem de Segurança 15%
            m_w, m_h = int(box_w * 0.15), int(box_h * 0.15)
            nx1, ny1 = max(0, x1 - m_w), max(0, y1 - m_h)
            nx2, ny2 = min(w_img, x2 + m_w), min(h_img, y2 + m_h)

            crop_img = img_original[ny1:ny2, nx1:nx2]
            
            # --- FORÇAR ORIENTAÇÃO HORIZONTAL (PAISAGEM) ---
            # Se a imagem estiver "em pé" (altura > largura), gira 90 graus para "deitar"
            ch, cw = crop_img.shape[:2]
            if ch > cw:
                crop_img = cv2.rotate(crop_img, cv2.ROTATE_90_CLOCKWISE)
            
            # --- Ajuste OSD de Orientacao com Tesseract OCR ---
            import pytesseract
            ocr_detected = False
            
            if skip_ocr:
                print("OCR DESLIGADO nas configuracoes. Pulando rotacao.", flush=True)
                # Pula direto para a parte de salvar o crop (sem tentar girar)
                final_img = crop_img
                if watermark_text:
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    h_final, w_final = final_img.shape[:2]
                    text_scale = max(0.4, w_final / 1200)
                    thickness = max(1, int(w_final / 600))
                    bar_height = int(40 * text_scale)
                    black_bar = np.zeros((bar_height, w_final, 3), dtype=np.uint8)
                    text_color = (0, 255, 255)
                    cv2.putText(black_bar, watermark_text, (20, bar_height - 15), font, text_scale, text_color, thickness, cv2.LINE_AA)
                    final_img = cv2.vconcat([final_img, black_bar])
                crop_path = img_path.replace(".jpg", "_crop.jpg")
                cv2.imwrite(crop_path, final_img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                print(f"SUCESSO:{crop_path}", flush=True)
                return
            try:
                # 1. Pré-processamento avançado específico para o OCR (OSD)
                # O Tesseract OSD funciona muito melhor com imagens maiores, em escala de cinza e com contraste
                
                # Converte para escala de cinza
                gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
                
                # Aumenta o tamanho (Upscaling 2x) para letras pequenas ficarem legiveis
                gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                
                # Adiciona borda branca (Padding) para o Tesseract entender o layout/margens
                temp_ocr = cv2.copyMakeBorder(gray, 100, 100, 100, 100, cv2.BORDER_CONSTANT, value=[255, 255, 255])
                
                # Aplica um filtro de nitidez (Laplacian) para reforçar bordas de letras
                kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
                temp_ocr = cv2.filter2D(temp_ocr, -1, kernel)

                # 2. Chama o Tesseract OSD (Orientation and Script Detection)
                osd = pytesseract.image_to_osd(temp_ocr)
                angle = 0
                for line in osd.split('\n'):
                    if 'Rotate: ' in line:
                        angle = int(line.split(': ')[1].strip())
                        ocr_detected = True 
                        break
                
                # --- DOUBLE CHECK (Votação de Caracteres) ---
                # Se o OSD disse 0, vamos conferir se invertido nao le melhor (erro comum do Tesseract)
                if ocr_detected and angle == 0:
                    # Tenta ler texto na posicao atual
                    txt0 = pytesseract.image_to_string(temp_ocr, config='--psm 6')
                    count0 = sum(c.isalnum() for c in txt0)
                    
                    # Tenta ler texto invertido 180 graus
                    temp_ocr_180 = cv2.rotate(temp_ocr, cv2.ROTATE_180)
                    txt180 = pytesseract.image_to_string(temp_ocr_180, config='--psm 6')
                    count180 = sum(c.isalnum() for c in txt180)
                    
                    # Se a versao invertida tiver MUITO mais caracteres legiveis (ex: cabeçalho da NF-e)
                    # Forçamos a rotação de 180 graus
                    if count180 > (count0 + 10) and count180 > (count0 * 1.5):
                        angle = 180
                        # print(f"DEBUG: Forçando 180 graus por OCR (C0:{count0} vs C180:{count180})")
                
                # --- QUADRUPLE CHECK (Âncora por Número da NF-e) ---
                # Se ainda estamos em 0 e temos o número esperado da nota, buscamos ele na imagem.
                # Se o número só aparecer "de cabeça para baixo", giramos 180.
                if angle == 0 and expected_nfe and len(expected_nfe) >= 3:
                    expected_nfe = str(expected_nfe).strip()
                    # Tenta ler texto na posicao atual
                    full_txt0 = pytesseract.image_to_string(temp_ocr, config='--psm 6')
                    
                    if expected_nfe not in full_txt0:
                        # Tenta ler texto invertido 180 graus
                        temp_ocr_180 = cv2.rotate(temp_ocr, cv2.ROTATE_180)
                        full_txt180 = pytesseract.image_to_string(temp_ocr_180, config='--psm 6')
                        
                        if expected_nfe in full_txt180:
                            angle = 180
                            # print(f"DEBUG: Forçando 180 graus por Âncora NF-e ({expected_nfe})")

                # --- TRIPLE CHECK (Bússola por Código de Barras) ---
                # Se ainda estamos em 0, tentamos achar o codigo de barras. 
                # Se o codigo de barras estiver "em cima", o canhoto estah de cabeça para baixo.
                if angle == 0:
                    try:
                        # Processamento para realçar barras verticais
                        gray_bc = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
                        # Sobel para achar gradientes horizontais (bordas de barras verticais)
                        gradX = cv2.Sobel(gray_bc, ddepth=cv2.CV_32F, dx=1, dy=0, ksize=-1)
                        gradX = cv2.convertScaleAbs(gradX)
                        # Blur e Threshold para unir as barras em um unico bloco
                        blurred = cv2.blur(gradX, (9, 9))
                        (_, thresh) = cv2.threshold(blurred, 225, 255, cv2.THRESH_BINARY)
                        # Morfologia para fechar buracos
                        kernel_bc = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 7))
                        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel_bc)
                        # Acha contornos
                        cnts, _ = cv2.findContours(closed.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        if cnts:
                            # Pega o maior contorno (provavel codigo de barras)
                            c_max = max(cnts, key=cv2.contourArea)
                            if cv2.contourArea(c_max) > 500:
                                x_bc, y_bc, w_bc, h_bc = cv2.boundingRect(c_max)
                                # Se o codigo de barras estiver no TOP 35% da imagem (canhoto invertido)
                                if (y_bc + h_bc/2) < (crop_img.shape[0] * 0.35):
                                    angle = 180
                                    # print("DEBUG: Forçando 180 graus por Codigo de Barras")
                    except:
                        pass

                # 3. Aplica a rotacao detectada pelo OCR ou Codigo de Barras no recorte ORIGINAL
                if angle == 90:
                    crop_img = cv2.rotate(crop_img, cv2.ROTATE_90_CLOCKWISE)
                elif angle == 180:
                    crop_img = cv2.rotate(crop_img, cv2.ROTATE_180)
                elif angle == 270:
                    crop_img = cv2.rotate(crop_img, cv2.ROTATE_90_COUNTERCLOCKWISE)
                
                if ocr_detected:
                    print(f"INFO:OCR_SUCESSO (Angulo: {angle})", flush=True)
            except Exception as e:
                # print(f"DEBUG OCR: {str(e)}")
                pass
            
            valid_crops.append(crop_img)

    # Se encontramos pelo menos um canhoto válido
    if valid_crops:
        print("INFO:YOLO_SUCESSO", flush=True)
        # --- Lógica de Junção (Merge) ---
        # 1. Padronizamos a largura de todos os recortes pela largura do maior recorte encontrado
        max_w = max(crop.shape[1] for crop in valid_crops)
        
        resized_crops = []
        for crop in valid_crops:
            h, w = crop.shape[:2]
            if w != max_w:
                new_h = int(h * (max_w / w))
                crop = cv2.resize(crop, (max_w, new_h), interpolation=cv2.INTER_LANCZOS4)
            resized_crops.append(crop)
            
        # 2. Concatena verticalmente todos os canhotos
        final_img = cv2.vconcat(resized_crops) if len(resized_crops) > 1 else resized_crops[0]

        # --- Adiciona Tarja Preta (Watermark) Única no final ---
        if watermark_text:
            h_final, w_final = final_img.shape[:2]
            font = cv2.FONT_HERSHEY_SIMPLEX
            
            text_scale = 1.0
            text_size = cv2.getTextSize(watermark_text, font, text_scale, 1)[0]
            if text_size[0] > (w_final - 40):
                text_scale = (w_final - 40) / text_size[0]
            
            text_scale = max(0.4, text_scale)
            thickness = max(1, int(text_scale * 2))
            text_size = cv2.getTextSize(watermark_text, font, text_scale, thickness)[0]
            
            bar_height = text_size[1] + 30
            black_bar = np.zeros((bar_height, w_final, 3), dtype=np.uint8)
            
            text_color = (0, 255, 255) # Amarelo
            cv2.putText(black_bar, watermark_text, (20, bar_height - 15), font, text_scale, text_color, thickness, cv2.LINE_AA)
            
            final_img = cv2.vconcat([final_img, black_bar])

        # Salva o resultado final
        crop_path = img_path.replace(".jpg", "_crop.jpg")
        cv2.imwrite(crop_path, final_img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f"SUCESSO:{crop_path}", flush=True)
        return
            
    print("FALHA:Nao encontrou canhoto", flush=True)

if __name__ == "__main__":
    import sys
    # Forcar UTF-8 pra print no subprocesso Windows/Linux
    sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) > 1:
        img_p = sys.argv[1]
        wm_text = sys.argv[2] if len(sys.argv) > 2 else ""
        nfe_val = sys.argv[3] if len(sys.argv) > 3 else ""
        skip_ocr_flag = (sys.argv[4] == "skip_ocr") if len(sys.argv) > 4 else False
        codigo_oc = sys.argv[5] if len(sys.argv) > 5 else "01"
        run_ml(img_p, wm_text, nfe_val, skip_ocr=skip_ocr_flag, codigo_ocorrencia=codigo_oc)

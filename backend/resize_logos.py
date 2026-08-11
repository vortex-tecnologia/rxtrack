import sys
from PIL import Image
import os

source_image_1 = r"C:\Users\Micro\Downloads\ChatGPT Image 1 de jun. de 2026, 11_02_06.png"
source_image_2 = r"C:\Users\Micro\Downloads\ChatGPT Image 1 de jun. de 2026, 11_00_04.png"

# We'll use source_image_1 by default, or whichever exists
source_image = source_image_1 if os.path.exists(source_image_1) else source_image_2

if not os.path.exists(source_image):
    print("Source image not found.")
    sys.exit(1)

out_dir = r"c:\Users\Micro\Desktop\nv\nv\quicktrack_producao_repo\backend\static\images"
os.makedirs(out_dir, exist_ok=True)

out_160 = os.path.join(out_dir, "icon-160x160.png")
out_512 = os.path.join(out_dir, "icon-512x512.png")

try:
    with Image.open(source_image) as img:
        img_160 = img.resize((160, 160), Image.Resampling.LANCZOS)
        img_160.save(out_160)
        print(f"Saved {out_160}")
        
        img_512 = img.resize((512, 512), Image.Resampling.LANCZOS)
        img_512.save(out_512)
        print(f"Saved {out_512}")
except Exception as e:
    print(f"Error resizing image: {e}")

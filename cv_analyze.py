import cv2
import numpy as np
from datetime import datetime

def analyze_photo_cv(image_path, calib_data):
    """
    Analyzes the image using deterministic Computer Vision (OpenCV)
    instead of LLM.
    
    calib_data must contain:
      - izq_x_pct (left boundary of jar column)
      - der_x_pct (right boundary of jar column)
      - base_y_pct (bottom floor of the jar)
      
    Returns:
       float: The Y-percentage (0=top, 100=bottom) of the dough surface.
    """
    if "izq_x_pct" not in calib_data or "der_x_pct" not in calib_data or "base_y_pct" not in calib_data or "tope_y_pct" not in calib_data:
        print("⚠️ Missing calibration bounds for OpenCV")
        return None
        
    img = cv2.imread(image_path)
    if img is None:
        print(f"⚠️ OpenCV could not load image: {image_path}")
        return None
        
    height, width = img.shape[:2]
    
    # Extract absolute boundaries
    izq = int(width * (calib_data["izq_x_pct"] / 100.0))
    der = int(width * (calib_data["der_x_pct"] / 100.0))
    base = int(height * (calib_data["base_y_pct"] / 100.0))
    tope = int(height * (calib_data["tope_y_pct"] / 100.0))
    
    if izq >= der or tope >= base:
        print("⚠️ Invalid OpenCV crop boundaries")
        return None
        
    # Crop to just the "column" of the glass jar interior, from the lid down to the floor
    cropped = img[tope:base, izq:der]
    if cropped.size == 0:
        return None
        
    # Convert to Grayscale
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    
    # 1D Horizontal Brightness Profile Scan
    # We calculate the mean brightness for every horizontal row of pixels.
    profile = []
    for i in range(gray.shape[0]):
        row = gray[i, :]
        profile.append(np.mean(row))
        
    # Smooth the profile to eliminate micro-fluctuations (noise)
    kernel_size = max(5, int((base - tope) * 0.02)) # Adaptive smoothing
    kernel = np.ones(kernel_size) / kernel_size
    profile_smooth = np.convolve(profile, kernel, mode='valid')
    
    # We use Absolute Brightness Thresholding instead of Differential Gradients.
    # The dough is solid white/light beige (high brightness), and the empty glass
    # above it is darker. Diffs can be tricked by glass residue slowly ramping up,
    # but a flat numerical threshold cuts straight to the core mass of the dough.
    bright_min = np.min(profile_smooth)
    bright_max = np.max(profile_smooth)
    # Bimodal midpoint thresholding (Otsu-like but deterministic for a single axis)
    threshold = (bright_min + bright_max) / 2.0
    
    meniscus_idx = None
    # We start scanning just below the top lid (to avoid metal glare)
    start_idx = int(len(profile_smooth) * 0.1)
    
    # Optional: If the red band is extremely bright, mask it out
    if "fondo_y_pct" in calib_data and calib_data["fondo_y_pct"] is not None:
        fondo_abs = int(height * (calib_data["fondo_y_pct"] / 100.0))
        fondo_crop_idx = fondo_abs - tope - (kernel_size // 2)
        band_margin = int((base - tope) * 0.05)
        # Force the profile to be zero at the red band just in case it creates glare
        for i in range(max(0, fondo_crop_idx - band_margin), min(len(profile_smooth), fondo_crop_idx + band_margin)):
            profile_smooth[i] = 0.0
    
    # Scan from top down to find the very first pixel row that hits our white dough threshold
    for i in range(start_idx, len(profile_smooth)):
        if profile_smooth[i] > threshold:
            meniscus_idx = i
            break
            
    # Fallback just in case
    if meniscus_idx is None:
        meniscus_idx = np.argmax(profile_smooth[start_idx:]) + start_idx
    
    # Apply offset due to convolution
    meniscus_idx += (kernel_size // 2)
    
    # Remap the local cropped Y back to absolute Image Y
    best_y = tope + meniscus_idx
    
    # Optional debug image output showing the bounded region
    try:
        debug_img = img.copy()
        cv2.rectangle(debug_img, (izq, tope), (der, base), (255, 0, 0), 2) # Crop bounds (Blue)
        cv2.line(debug_img, (izq, base), (der, base), (0, 255, 0), 3) # Floor (Green)
        cv2.line(debug_img, (izq, tope), (der, tope), (255, 255, 0), 3) # Lid (Cyan)
        cv2.line(debug_img, (izq, best_y), (der, best_y), (0, 0, 255), 4) # Dough Surface (Red)
        cv2.imwrite(image_path.replace(".jpg", "_cv_debug.jpg"), debug_img)
    except Exception as e:
        pass
    
    pct = (best_y / height) * 100.0
    return round(pct, 2)

if __name__ == "__main__":
    print("CV Analysis Module Ready. Waiting for boundaries.")

import cv2
import numpy as np

img = cv2.imread('/Users/moltbot/Projects/sourdough-monitor/photos/latest.jpg')
height, width = img.shape[:2]

# Approx user coordinates from visual inspection of the image:
izq = int(width * 0.25)
der = int(width * 0.75)
base = int(height * 0.70)
tope = int(height * 0.30)  # below the lid

cropped = img[tope:base, izq:der]
gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)

profile = []
for i in range(gray.shape[0]):
    row = gray[i, :]
    profile.append(np.mean(row))

# Calculate gradient (derivative) of the brightness profile
# Smooth the profile first
kernel = np.ones(5)/5
profile_smooth = np.convolve(profile, kernel, mode='valid')
diffs = np.diff(profile_smooth)

meniscus_idx = np.argmax(diffs)

print(f"Meniscus found at cropped Y={meniscus_idx}")
# Convert back to original image
real_y = tope + meniscus_idx
print(f"Real Y: {real_y}")
pct = (real_y / height) * 100
print(f"Calculated Percentage: {pct:.1f}%")

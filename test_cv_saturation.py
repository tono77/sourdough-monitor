import cv2
import numpy as np

img = cv2.imread("photos/latest.jpg")
if img is None:
    print("No image.")
    exit()

hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
h, s, v = cv2.split(hsv)

cv2.imwrite("test_s_channel.jpg", s)

profile = np.mean(s[:, :], axis=1) # mean saturation per row
for i in range(0, img.shape[0], 20):
    print(f"Y={i}: S={int(profile[i])}")

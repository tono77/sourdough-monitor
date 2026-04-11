import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from pathlib import Path
import os
image_path = "photos/latest.jpg"
if os.path.exists(image_path):
    img = mpimg.imread(image_path)
    fig, ax = plt.subplots()
    ax.imshow(img)
    height = img.shape[0]
    for i in range(1, 10):
        y = height - (height * (i / 10.0))
        pct = i * 10
        ax.axhline(y, color='white', linestyle='-', linewidth=2, alpha=0.5)
        ax.text(10, y - 10, f"{pct}%", color='yellow', fontsize=24, fontweight='bold',
                bbox=dict(facecolor='black', alpha=0.5, edgecolor='none'))
    plt.axis('off')
    plt.savefig("photos/grid_test.jpg", bbox_inches='tight', pad_inches=0, dpi=100)
    print("Grid applied.")

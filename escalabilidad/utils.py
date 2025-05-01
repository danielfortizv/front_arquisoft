# escalabilidad/utils.py

import nibabel as nib
import numpy as np
import matplotlib.pyplot as plt
from django.conf import settings
import os

def nifti_a_png(ruta_nifti, sujeto_id):
    img = nib.load(ruta_nifti)
    data = img.get_fdata()
    
    # Selecciona una sección del medio para la visualización
    slice_0 = data[data.shape[0] // 2, :, :]
    slice_1 = data[:, data.shape[1] // 2, :]
    slice_2 = data[:, :, data.shape[2] // 2]
    
    slices = [slice_0, slice_1, slice_2]
    nombres = ['Sagital', 'Coronal', 'Axial']
    
    fig, axes = plt.subplots(1, 3)
    for i, (slice, nombre) in enumerate(zip(slices, nombres)):
        axes[i].imshow(np.rot90(slice), cmap='gray')
        axes[i].set_title(nombre)
        axes[i].axis('off')
    
    # Guarda la imagen en el directorio de medios
    ruta_salida = os.path.join(settings.MEDIA_ROOT, f'mri_images/{sujeto_id}.png')
    os.makedirs(os.path.dirname(ruta_salida), exist_ok=True)
    plt.savefig(ruta_salida, bbox_inches='tight')
    plt.close(fig)
    
    return f'mri_images/{sujeto_id}.png'

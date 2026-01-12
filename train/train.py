import torch
if torch.cuda.is_available():
    print("🟢 CUDA je na voljo!")
    print("🔧 Uporabljeni GPU:", torch.cuda.get_device_name(0))
else:
    print("🔴 CUDA ni na voljo – uporablja se CPU.")
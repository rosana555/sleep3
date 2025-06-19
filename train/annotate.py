import os
import random
import shutil
from pathlib import Path
import cv2
from ultralytics import YOLO

# -----------------------
# Nastavitve uporabnika
# -----------------------
input_images_dir = "slike"
output_base_dir = "dataset"
train_split = 0.8
model_path = "yolov8n.pt"  # Lahko zamenjaš z "yolov8s.pt" za večjo natančnost
person_class_id = 0  # COCO class ID za "person"

# -----------------------
# Priprava map
# -----------------------
images_train_dir = Path(output_base_dir) / "images/train"
images_val_dir = Path(output_base_dir) / "images/val"
labels_train_dir = Path(output_base_dir) / "labels/train"
labels_val_dir = Path(output_base_dir) / "labels/val"

for d in [images_train_dir, images_val_dir, labels_train_dir, labels_val_dir]:
    d.mkdir(parents=True, exist_ok=True)

# -----------------------
# Naloži YOLO model
# -----------------------
model = YOLO(model_path)

# -----------------------
# Zberi slike in premešaj
# -----------------------
image_files = [f for f in os.listdir(input_images_dir) if f.lower().endswith((".jpg", ".png", ".jpeg"))]
random.shuffle(image_files)
split_index = int(len(image_files) * train_split)
train_files = image_files[:split_index]
val_files = image_files[split_index:]


def anotiraj_in_shrani(img_name, split="train"):
    img_path = os.path.join(input_images_dir, img_name)
    img = cv2.imread(img_path)
    h, w = img.shape[:2]

    results = model(img)[0]
    label_lines = []

    for box in results.boxes:
        cls = int(box.cls[0])
        if cls != person_class_id:
            continue

        x1, y1, x2, y2 = box.xyxy[0]
        x_center = ((x1 + x2) / 2) / w
        y_center = ((y1 + y2) / 2) / h
        width = (x2 - x1) / w
        height = (y2 - y1) / h
        label_lines.append(f"{person_class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}")

    if split == "train":
        img_out = images_train_dir / img_name
        label_out = labels_train_dir / (Path(img_name).stem + ".txt")
    else:
        img_out = images_val_dir / img_name
        label_out = labels_val_dir / (Path(img_name).stem + ".txt")

    # Shrani sliko in anotacijo
    shutil.copy(img_path, img_out)
    with open(label_out, "w") as f:
        f.write("\n".join(label_lines))


# -----------------------
# Anotiraj in razdeli slike
# -----------------------
print(f"Anotiram {len(train_files)} treninških in {len(val_files)} validacijskih slik...")
for img_name in train_files:
    anotiraj_in_shrani(img_name, "train")

for img_name in val_files:
    anotiraj_in_shrani(img_name, "val")

# -----------------------
# Ustvari data.yaml
# -----------------------
yaml_path = Path(output_base_dir) / "data.yaml"
with open(yaml_path, "w") as f:
    f.write(f"""path: {output_base_dir}
train: images/train
val: images/val
names:
  0: person
""")

print("✅ Dataset pripravljen za učenje YOLOv8.")

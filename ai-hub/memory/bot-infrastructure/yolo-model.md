# YOLO Drop Spot Model (separate concern)

> Referenced from `AGENTS.md` → Codebase Map. Not part of the bot runtime — the drop-spot detection model.

- Model: YOLO26l, Roboflow project `drop-spot-detection` v5, 2280 images.
- Trained on Colab T4 (`batch=8` — `batch=16` OOMs).
- Best: **mAP@50 0.864** at epoch ~291. Backed up as `best_864_LOCKED.pt` in Drive + Mac Desktop.
- Drive path: `/content/drive/MyDrive/yolo_training/`. Always mount via `drive.mount('/content/drive')`.
- For resume: back up the **entire** `runs/detect/train/` folder (not just `last.pt`) and use `model.train(resume=True)` — otherwise optimizer/scheduler/BatchNorm state is lost (mAP dips 5-10 epochs).
- Next training v2 targets: `imgsz=1280`, `batch=4`, `yolo26x.pt`, aggressive augmentation → expected 0.90-0.92 mAP@50.

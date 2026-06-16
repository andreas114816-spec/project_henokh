import os
from pathlib import Path

import cv2
import numpy as np


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPO_PATH = BASE_DIR / "model" / "MobileFaceNet"
DEFAULT_MODEL_PATH = DEFAULT_REPO_PATH / "pretrained_model" / "mobilefacenet_scripted.pt"
MODEL_PATH = Path(os.getenv("MOBILEFACENET_MODEL_PATH", DEFAULT_MODEL_PATH)).expanduser()

mobilefacenet_model = None


def get_mobilefacenet_model():
    global mobilefacenet_model

    if mobilefacenet_model is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"MobileFaceNet model not found at {MODEL_PATH}. "
                "Clone https://github.com/foamliu/MobileFaceNet.git into model/MobileFaceNet "
                "or set MOBILEFACENET_MODEL_PATH to a valid .pt model."
            )

        import torch

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        mobilefacenet_model = torch.jit.load(str(MODEL_PATH), map_location=device)
        mobilefacenet_model.eval()

    return mobilefacenet_model


def preprocess_face_for_mobilefacenet(face):
    import torch

    face = cv2.resize(face, (112, 112), interpolation=cv2.INTER_AREA)
    face = face.astype("float32")
    face = (face - 127.5) / 128.0
    face = np.transpose(face, (2, 0, 1))
    return torch.from_numpy(face).unsqueeze(0)


def build_face_embedding(face):
    import torch
    import torch.nn.functional as functional

    model = get_mobilefacenet_model()
    device = next(model.parameters(), torch.empty(0)).device
    tensor = preprocess_face_for_mobilefacenet(face).to(device)

    with torch.no_grad():
        embedding = model(tensor)
        embedding = functional.normalize(embedding, p=2, dim=1)

    return embedding.detach().cpu().numpy().reshape(-1).astype("float32").tolist()


if __name__ == "__main__":
    path = MODEL_PATH

    if not path.exists():
        raise SystemExit(
            f"MobileFaceNet model is missing: {path}\n"
            "Run: git clone https://github.com/foamliu/MobileFaceNet.git model/MobileFaceNet"
        )

    print(path)

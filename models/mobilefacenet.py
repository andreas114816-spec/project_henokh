import os
from pathlib import Path

import cv2
import numpy as np
from tensorflow.keras.models import load_model


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_PATH = BASE_DIR / "model" / "mobilefacenet.keras"
MODEL_PATH = Path(os.getenv("MOBILEFACENET_MODEL_PATH", DEFAULT_MODEL_PATH))

mobilefacenet_model = None


def get_mobilefacenet_model():
    global mobilefacenet_model

    if mobilefacenet_model is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"MobileFaceNet model not found at {MODEL_PATH}. "
                "Set MOBILEFACENET_MODEL_PATH or place the model there."
            )

        mobilefacenet_model = load_model(str(MODEL_PATH), compile=False)

    return mobilefacenet_model


def preprocess_face_for_mobilefacenet(face):
    face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
    face = cv2.resize(face, (112, 112), interpolation=cv2.INTER_AREA)
    face = face.astype("float32")
    face = (face - 127.5) / 128.0
    return np.expand_dims(face, axis=0)


def build_face_embedding(face):
    model = get_mobilefacenet_model()
    embedding = model.predict(preprocess_face_for_mobilefacenet(face), verbose=0)[0]
    embedding = np.asarray(embedding, dtype="float32").reshape(-1)
    norm = np.linalg.norm(embedding)

    if norm > 0:
        embedding = embedding / norm

    return embedding.tolist()

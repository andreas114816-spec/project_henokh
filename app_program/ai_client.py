import os

import requests


AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")
AI_SERVICE_TIMEOUT = float(os.getenv("AI_SERVICE_TIMEOUT", "30"))


class AIServiceError(RuntimeError):
    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code


def analyze_frame(image_data, anti_spoof_enabled=True, include_embeddings=False):
    payload = {
        "image": image_data,
        "antiSpoofEnabled": anti_spoof_enabled,
        "includeEmbeddings": include_embeddings,
    }

    try:
        response = requests.post(
            f"{AI_SERVICE_URL}/analyze-frame",
            json=payload,
            timeout=AI_SERVICE_TIMEOUT,
        )
    except requests.RequestException as error:
        raise AIServiceError(f"AI service unavailable: {error}") from error

    try:
        data = response.json()
    except ValueError as error:
        raise AIServiceError("AI service returned an invalid response") from error

    if response.status_code >= 400 or not data.get("success"):
        raise AIServiceError(
            data.get("message") or "AI service failed to process the frame",
            status_code=response.status_code,
        )

    return data

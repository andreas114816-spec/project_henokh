from flask import Flask, render_template, request, jsonify
import base64
import cv2
import numpy as np

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload-frame", methods=["POST"])
def upload_frame():
    data = request.get_json()

    if not data or "image" not in data:
        return jsonify({
            "success": False,
            "message": "No image received"
        }), 400

    image_data = data["image"]

    # Remove prefix: data:image/jpeg;base64,
    image_data = image_data.split(",")[1]

    image_bytes = base64.b64decode(image_data)
    np_arr = np.frombuffer(image_bytes, np.uint8)

    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if frame is None:
        return jsonify({
            "success": False,
            "message": "Invalid image"
        }), 400

    height, width, channels = frame.shape

    print(f"Received frame: {width}x{height}")

    return jsonify({
        "success": True,
        "message": "Frame received",
        "width": width,
        "height": height
    })


if __name__ == "__main__":
    app.run(debug=True)

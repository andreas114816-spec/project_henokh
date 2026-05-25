$(document).ready(function () {
    const video = $("#video")[0];
    const canvas = $("#canvas")[0];
    const context = canvas.getContext("2d");
    const captureCanvas = document.createElement("canvas");
    const captureContext = captureCanvas.getContext("2d");

    let stream = null;
    let captureInterval = null;
    let isSendingFrame = false;

    async function startCamera() {
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: true,
                audio: false
            });

            video.srcObject = stream;

            $("#status").text("Camera started. Streaming frames to backend...");

            startSendingFrames();

        } catch (error) {
            console.error(error);
            $("#status").text("Failed to access camera.");
        }
    }

    function stopCamera() {
        if (stream) {
            stream.getTracks().forEach(function (track) {
                track.stop();
            });

            stream = null;
        }

        if (captureInterval) {
            clearInterval(captureInterval);
            captureInterval = null;
        }

        $("#status").text("Camera stopped.");
        $("#backendResponse").text("");
        clearDetections();
    }

    function startSendingFrames() {
        if (captureInterval) {
            clearInterval(captureInterval);
        }

        captureInterval = setInterval(function () {
            sendFrameToBackend();
        }, 500);
    }

    function sendFrameToBackend() {
        if (!video.videoWidth || !video.videoHeight || isSendingFrame) {
            return;
        }

        isSendingFrame = true;
        captureCanvas.width = video.videoWidth;
        captureCanvas.height = video.videoHeight;
        syncOverlaySize();

        captureContext.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);

        const imageData = captureCanvas.toDataURL("image/jpeg", 0.8);

        $.ajax({
            url: "/upload-frame",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify({
                image: imageData
            }),
            success: function (response) {
                drawDetections(response.detections || []);
                $("#backendResponse").text(
                    "Backend processed frame: " + response.width + "x" + response.height +
                    " | Faces: " + (response.detections || []).length
                );
            },
            error: function (xhr, status, error) {
                console.error(error);
                $("#backendResponse").text("Failed to send frame.");
            },
            complete: function () {
                isSendingFrame = false;
            }
        });
    }

    function syncOverlaySize() {
        if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
        }
    }

    function clearDetections() {
        context.clearRect(0, 0, canvas.width, canvas.height);
    }

    function drawDetections(detections) {
        syncOverlaySize();
        clearDetections();

        context.lineWidth = Math.max(2, Math.round(canvas.width / 320));
        context.font = `${Math.max(14, Math.round(canvas.width / 45))}px Arial`;
        context.textBaseline = "top";

        detections.forEach(function (detection) {
            const liveness = detection.liveness;
            const realScore = liveness && liveness.scores ? liveness.scores.real : 0;
            const livenessText = liveness
                ? ` | real ${Math.round(realScore * 100)}%`
                : "";
            const label = `${detection.label || "face"} ${Math.round((detection.confidence || 0) * 100)}%${livenessText}`;
            const color = realScore >= 0.6 ? "#22c55e" : "#ef4444";
            const x = canvas.width - detection.x - detection.width;
            const y = detection.y;

            context.strokeStyle = color;
            context.fillStyle = color;
            context.strokeRect(x, y, detection.width, detection.height);

            const textWidth = context.measureText(label).width;
            const labelHeight = parseInt(context.font, 10) + 6;
            const labelY = Math.max(0, y - labelHeight);
            const labelX = Math.min(Math.max(0, x), canvas.width - textWidth - 8);

            context.fillRect(labelX, labelY, textWidth + 8, labelHeight);
            context.fillStyle = "#052e16";
            context.fillText(label, labelX + 4, labelY + 3);
        });
    }

    $("#startBtn").on("click", function () {
        startCamera();
    });

    $("#stopBtn").on("click", function () {
        stopCamera();
    });

    if (document.body.dataset.autoStart === "true") {
        startCamera();
    }
});

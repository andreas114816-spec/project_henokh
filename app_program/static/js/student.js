$(document).ready(function () {
    const video = $("#studentVideo")[0];
    const overlayCanvas = $("#studentCanvas")[0];
    const overlayContext = overlayCanvas.getContext("2d");
    const captureCanvas = document.createElement("canvas");
    const captureContext = captureCanvas.getContext("2d");

    let stream = null;
    let detectionInterval = null;
    let isDetecting = false;
    const isEditing = $("#studentForm").data("editing") === true || $("#studentForm").data("editing") === "true";
    const saveButtonText = isEditing ? "Update Student" : "Save Student";

    async function startCamera() {
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: "user"
                },
                audio: false
            });

            video.srcObject = stream;
            await video.play();
            syncOverlaySize();
            startDetectionLoop();
            $("#cameraStatus").text("Camera started. The clearest detected face will be saved.");
        } catch (error) {
            console.error(error);
            $("#cameraStatus").text("Failed to access camera.");
        }
    }

    function stopCamera() {
        if (stream) {
            stream.getTracks().forEach(function (track) {
                track.stop();
            });
            stream = null;
        }

        if (detectionInterval) {
            clearInterval(detectionInterval);
            detectionInterval = null;
        }

        clearDetections();
        $("#cameraStatus").text("Camera stopped.");
    }

    function startDetectionLoop() {
        if (detectionInterval) {
            clearInterval(detectionInterval);
        }

        sendFrameForDetection();
        detectionInterval = setInterval(sendFrameForDetection, 700);
    }

    function syncOverlaySize() {
        const rect = video.getBoundingClientRect();
        const width = Math.round(rect.width || video.videoWidth || 0);
        const height = Math.round(rect.height || video.videoHeight || 0);

        if (width && height && (overlayCanvas.width !== width || overlayCanvas.height !== height)) {
            overlayCanvas.width = width;
            overlayCanvas.height = height;
        }
    }

    function clearDetections() {
        overlayContext.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    }

    function captureImage(quality = 0.9) {
        if (!video.videoWidth || !video.videoHeight) {
            return null;
        }

        captureCanvas.width = video.videoWidth;
        captureCanvas.height = video.videoHeight;
        captureContext.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);
        return captureCanvas.toDataURL("image/jpeg", quality);
    }

    function normalizeDetection(detection) {
        if (Array.isArray(detection.bbox) && detection.bbox.length >= 4) {
            return {
                x: Number(detection.bbox[0]),
                y: Number(detection.bbox[1]),
                width: Number(detection.bbox[2]) - Number(detection.bbox[0]),
                height: Number(detection.bbox[3]) - Number(detection.bbox[1])
            };
        }

        return {
            x: Number(detection.x ?? detection.x1),
            y: Number(detection.y ?? detection.y1),
            width: Number(detection.width ?? (detection.x2 - detection.x1)),
            height: Number(detection.height ?? (detection.y2 - detection.y1))
        };
    }

    function drawDetections(detections, sourceWidth, sourceHeight) {
        syncOverlaySize();
        clearDetections();

        const scaleX = overlayCanvas.width / (sourceWidth || video.videoWidth || overlayCanvas.width || 1);
        const scaleY = overlayCanvas.height / (sourceHeight || video.videoHeight || overlayCanvas.height || 1);
        const fontSize = Math.max(13, Math.round(overlayCanvas.width / 45));

        overlayContext.lineWidth = Math.max(2, Math.round(overlayCanvas.width / 320));
        overlayContext.font = `${fontSize}px Arial`;
        overlayContext.textBaseline = "top";

        detections.forEach(function (detection) {
            const box = normalizeDetection(detection);

            if (![box.x, box.y, box.width, box.height].every(Number.isFinite) || box.width <= 0 || box.height <= 0) {
                return;
            }

            const liveness = detection.liveness;
            const antiSpoofActive = !liveness || liveness.enabled !== false;
            const realScore = Number(liveness && liveness.scores ? liveness.scores.real : 0);
            const realThreshold = Number(liveness && liveness.threshold ? liveness.threshold : 0.14);
            const livenessText = liveness
                ? (antiSpoofActive ? ` | real ${Math.round(realScore * 100)}%` : " | anti-spoof off")
                : "";
            const label = `${detection.label || "face"} ${Math.round(Number(detection.confidence || 0) * 100)}%${livenessText}`;
            const color = !antiSpoofActive || realScore >= realThreshold ? "#22c55e" : "#ef4444";
            const width = box.width * scaleX;
            const height = box.height * scaleY;
            const x = overlayCanvas.width - (box.x * scaleX) - width;
            const y = box.y * scaleY;

            overlayContext.strokeStyle = color;
            overlayContext.fillStyle = color;
            overlayContext.strokeRect(x, y, width, height);

            const textWidth = overlayContext.measureText(label).width;
            const labelHeight = fontSize + 6;
            const labelY = Math.max(0, y - labelHeight);
            const labelX = Math.min(Math.max(0, x), Math.max(0, overlayCanvas.width - textWidth - 8));

            overlayContext.fillRect(labelX, labelY, textWidth + 8, labelHeight);
            overlayContext.fillStyle = !antiSpoofActive || realScore >= realThreshold ? "#052e16" : "#ffffff";
            overlayContext.fillText(label, labelX + 4, labelY + 3);
        });
    }

    function sendFrameForDetection() {
        const image = captureImage(0.8);

        if (!image || isDetecting) {
            return;
        }

        isDetecting = true;

        $.ajax({
            url: "/upload-frame",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify({
                image: image
            }),
            success: function (response) {
                drawDetections(response.detections || [], response.width, response.height);
                $("#cameraStatus").text(`Detected faces: ${(response.detections || []).length}`);
            },
            error: function (xhr) {
                const response = xhr.responseJSON || {};
                clearDetections();
                $("#cameraStatus").text(response.message || "Face detection failed.");
            },
            complete: function () {
                isDetecting = false;
            }
        });
    }

    $("#startStudentCameraBtn").on("click", function () {
        startCamera();
    });

    $("#stopStudentCameraBtn").on("click", function () {
        stopCamera();
    });

    $(window).on("resize", function () {
        syncOverlaySize();
    });

    $("#studentForm").on("submit", function (event) {
        event.preventDefault();

        const nim = $("#studentNim").val().trim();

        if (!/^[0-9]+$/.test(nim)) {
            $("#studentStatus")
                .removeClass("text-green-600")
                .addClass("text-red-600")
                .text("NIM must contain numbers only.");
            return;
        }

        const image = captureImage();

        if (!image && !isEditing) {
            $("#studentStatus")
                .removeClass("text-green-600")
                .addClass("text-red-600")
                .text("Start the camera before saving.");
            return;
        }

        $("#saveStudentBtn").prop("disabled", true).text("Saving...");
        $("#studentStatus")
            .removeClass("text-green-600 text-red-600")
            .addClass("text-gray-600")
            .text("Processing face embedding...");

        $.ajax({
            url: "/students",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify({
                studentId: $("#studentId").val() || null,
                name: $("#studentName").val(),
                nim: nim,
                image: image
            }),
            success: function (response) {
                const hasEmbedding = response.student.embeddingDimensions > 0;

                $("#studentStatus")
                    .removeClass("text-gray-600 text-red-600")
                    .addClass(hasEmbedding ? "text-green-600" : "text-yellow-600")
                    .text(
                        `${response.message}. Embedding dimensions: ` +
                        response.student.embeddingDimensions
                    );
            },
            error: function (xhr) {
                const response = xhr.responseJSON || {};
                $("#studentStatus")
                    .removeClass("text-gray-600 text-green-600")
                    .addClass("text-red-600")
                    .text(response.message || "Failed to save student.");
            },
            complete: function () {
                $("#saveStudentBtn").prop("disabled", false).text(saveButtonText);
            }
        });
    });
});

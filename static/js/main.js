document.addEventListener("DOMContentLoaded", function () {
    const video = document.getElementById("video");
    const canvas = document.getElementById("canvas");
    const context = canvas.getContext("2d");
    const captureCanvas = document.createElement("canvas");
    const captureContext = captureCanvas.getContext("2d");
    const statusText = document.getElementById("status");
    const backendResponse = document.getElementById("backendResponse");
    const startBtn = document.getElementById("startBtn");
    const stopBtn = document.getElementById("stopBtn");
    const classSelect = document.getElementById("classSelect");
    const selectedClassLabel = document.getElementById("selectedClassLabel");
    const presenceResults = document.getElementById("presenceResults");

    let stream = null;
    let captureInterval = null;
    let isSendingFrame = false;

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

            statusText.textContent = "Camera started. Streaming frames to backend...";
            startSendingFrames();
        } catch (error) {
            console.error(error);
            statusText.textContent = "Failed to access camera.";
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

        statusText.textContent = "Camera stopped.";
        backendResponse.textContent = "";
        renderPresenceResults([]);
        clearDetections();
    }

    function startSendingFrames() {
        if (captureInterval) {
            clearInterval(captureInterval);
        }

        sendFrameToBackend();
        captureInterval = setInterval(sendFrameToBackend, 500);
    }

    async function sendFrameToBackend() {
        if (!video.videoWidth || !video.videoHeight || isSendingFrame) {
            return;
        }

        isSendingFrame = true;
        captureCanvas.width = video.videoWidth;
        captureCanvas.height = video.videoHeight;
        syncOverlaySize();

        captureContext.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);

        try {
            const response = await fetch("/upload-frame", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    image: captureCanvas.toDataURL("image/jpeg", 0.8),
                    classId: classSelect ? classSelect.value : ""
                })
            });
            const payload = await response.json();

            if (!response.ok || payload.success === false) {
                throw new Error(payload.message || "Backend failed to process frame");
            }

            drawDetections(payload.detections || [], payload.width, payload.height);
            renderPresenceResults(payload.detections || []);
            backendResponse.textContent = `Backend processed frame: ${payload.width}x${payload.height} | Faces: ${(payload.detections || []).length}`;
        } catch (error) {
            console.error(error);
            clearDetections();
            renderPresenceResults([]);
            backendResponse.textContent = error.message || "Failed to send frame.";
        } finally {
            isSendingFrame = false;
        }
    }

    function syncOverlaySize() {
        const rect = video.getBoundingClientRect();
        const width = Math.round(rect.width || video.videoWidth || 0);
        const height = Math.round(rect.height || video.videoHeight || 0);

        if (width && height && (canvas.width !== width || canvas.height !== height)) {
            canvas.width = width;
            canvas.height = height;
        }
    }

    function clearDetections() {
        context.clearRect(0, 0, canvas.width, canvas.height);
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

        if (detection.box && typeof detection.box === "object") {
            return {
                x: Number(detection.box.x ?? detection.box.left ?? detection.box.x1),
                y: Number(detection.box.y ?? detection.box.top ?? detection.box.y1),
                width: Number(detection.box.width ?? (detection.box.x2 - detection.box.x1)),
                height: Number(detection.box.height ?? (detection.box.y2 - detection.box.y1))
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

        const scaleX = canvas.width / (sourceWidth || video.videoWidth || canvas.width || 1);
        const scaleY = canvas.height / (sourceHeight || video.videoHeight || canvas.height || 1);
        const lineWidth = Math.max(2, Math.round(canvas.width / 320));
        const fontSize = Math.max(13, Math.round(canvas.width / 45));

        context.lineWidth = lineWidth;
        context.font = `${fontSize}px Arial`;
        context.textBaseline = "top";

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
            const x = canvas.width - (box.x * scaleX) - width;
            const y = box.y * scaleY;

            context.strokeStyle = color;
            context.fillStyle = color;
            context.strokeRect(x, y, width, height);

            const textWidth = context.measureText(label).width;
            const labelHeight = fontSize + 6;
            const labelY = Math.max(0, y - labelHeight);
            const labelX = Math.min(Math.max(0, x), Math.max(0, canvas.width - textWidth - 8));

            context.fillRect(labelX, labelY, textWidth + 8, labelHeight);
            context.fillStyle = !antiSpoofActive || realScore >= realThreshold ? "#052e16" : "#ffffff";
            context.fillText(label, labelX + 4, labelY + 3);
        });
    }

    function renderPresenceResults(detections) {
        if (!presenceResults) {
            return;
        }

        const matchedDetections = detections.filter(function (detection) {
            return detection.identity && detection.identity.matched;
        });
        const unmatchedCount = detections.length - matchedDetections.length;

        if (selectedClassLabel && classSelect) {
            selectedClassLabel.textContent = classSelect.options[classSelect.selectedIndex]?.text || "Select class target";
        }

        if (classSelect && !classSelect.value) {
            presenceResults.innerHTML = '<p class="text-sm text-gray-500">Select a class target before recording presence.</p>';
            return;
        }

        if (!detections.length) {
            presenceResults.innerHTML = '<p class="text-sm text-gray-500">No faces detected.</p>';
            return;
        }

        const rows = matchedDetections.map(function (detection) {
            const identity = detection.identity;
            const liveness = detection.liveness;
            const attendance = detection.attendance;
            const realScore = liveness && liveness.scores ? Number(liveness.scores.real) : null;
            const realText = realScore === null || liveness.enabled === false
                ? "Anti-spoof off"
                : `Real ${Math.round(realScore * 100)}%`;
            const status = attendance && attendance.recorded ? attendance.status : "not recorded";
            const presenceAt = attendance && attendance.presenceAt
                ? new Date(attendance.presenceAt).toLocaleString()
                : "-";

            return `
                <div class="rounded-lg bg-white p-3 shadow-sm">
                    <p class="font-semibold text-gray-900">${escapeHtml(identity.name)}</p>
                    <p class="text-sm text-gray-600">NIM: ${escapeHtml(identity.nim)}</p>
                    <p class="mt-2 text-sm font-medium ${statusClass(status)}">${escapeHtml(status)}</p>
                    <p class="text-xs text-gray-500">Time: ${escapeHtml(presenceAt)}</p>
                    <p class="mt-1 text-xs text-gray-500">Match ${Math.round(Number(identity.similarity || 0) * 100)}% | ${realText}</p>
                    ${attendance && attendance.message ? `<p class="mt-1 text-xs text-gray-500">${escapeHtml(attendance.message)}</p>` : ""}
                </div>
            `;
        });

        if (unmatchedCount > 0) {
            rows.push(`
                <div class="rounded-lg border border-dashed border-gray-300 p-3 text-sm text-gray-600">
                    ${unmatchedCount} detected face${unmatchedCount === 1 ? "" : "s"} not matched to the selected class.
                </div>
            `);
        }

        presenceResults.innerHTML = rows.join("");
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function statusClass(status) {
        if (status === "presence") {
            return "text-green-700";
        }

        if (status === "late") {
            return "text-yellow-700";
        }

        if (status === "absen") {
            return "text-red-700";
        }

        return "text-gray-700";
    }

    startBtn.addEventListener("click", startCamera);
    stopBtn.addEventListener("click", stopCamera);
    window.addEventListener("resize", syncOverlaySize);
    video.addEventListener("loadedmetadata", syncOverlaySize);

    if (classSelect) {
        classSelect.addEventListener("change", function () {
            renderPresenceResults([]);
        });
        renderPresenceResults([]);
    }

    if (document.body.dataset.autoStart === "true") {
        startCamera();
    }
});

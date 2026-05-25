$(document).ready(function () {
    const video = $("#video")[0];
    const canvas = $("#canvas")[0];
    const context = canvas.getContext("2d");

    let stream = null;
    let captureInterval = null;

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
        if (!video.videoWidth || !video.videoHeight) {
            return;
        }

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        context.drawImage(video, 0, 0, canvas.width, canvas.height);

        const imageData = canvas.toDataURL("image/jpeg", 0.8);

        $.ajax({
            url: "/upload-frame",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify({
                image: imageData
            }),
            success: function (response) {
                $("#backendResponse").text(
                    "Backend received frame: " + response.width + "x" + response.height
                );
            },
            error: function (xhr, status, error) {
                console.error(error);
                $("#backendResponse").text("Failed to send frame.");
            }
        });
    }

    $("#startBtn").on("click", function () {
        startCamera();
    });

    $("#stopBtn").on("click", function () {
        stopCamera();
    });
});
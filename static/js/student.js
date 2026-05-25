$(document).ready(function () {
    const video = $("#studentVideo")[0];
    const captureCanvas = document.createElement("canvas");
    const captureContext = captureCanvas.getContext("2d");

    let stream = null;

    async function startCamera() {
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: true,
                audio: false
            });

            video.srcObject = stream;
            $("#cameraStatus").text("Camera started. Align one face in the frame.");
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

        $("#cameraStatus").text("Camera stopped.");
    }

    function captureImage() {
        if (!video.videoWidth || !video.videoHeight) {
            return null;
        }

        captureCanvas.width = video.videoWidth;
        captureCanvas.height = video.videoHeight;
        captureContext.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);
        return captureCanvas.toDataURL("image/jpeg", 0.9);
    }

    $("#startStudentCameraBtn").on("click", function () {
        startCamera();
    });

    $("#stopStudentCameraBtn").on("click", function () {
        stopCamera();
    });

    $("#studentForm").on("submit", function (event) {
        event.preventDefault();

        const image = captureImage();

        if (!image) {
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
                name: $("#studentName").val(),
                nim: $("#studentNim").val(),
                image: image
            }),
            success: function (response) {
                $("#studentStatus")
                    .removeClass("text-gray-600 text-red-600")
                    .addClass("text-green-600")
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
                $("#saveStudentBtn").prop("disabled", false).text("Save Student");
            }
        });
    });
});

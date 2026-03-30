function VdoCipherXBlock(runtime, element) {
    var handlerUrl = runtime.handlerUrl(element, 'video_progress');
    var otpUrl = runtime.handlerUrl(element, 'get_otp');
    var lastReportTime = 0;
    var REPORT_INTERVAL = 30000; // Report every 30 seconds
    var apiLoaded = false;

    // Load VdoCipher Player API script
    if (!document.getElementById('vdocipher-api-script')) {
        var script = document.createElement('script');
        script.id = 'vdocipher-api-script';
        script.src = 'https://player.vdocipher.com/v2/api.js';
        script.onload = function() { apiLoaded = true; };
        document.head.appendChild(script);
    } else {
        apiLoaded = true;
    }

    // Fetch OTP from backend
    $.ajax({
        type: 'POST',
        url: otpUrl,
        data: JSON.stringify({}),
        contentType: 'application/json',
        success: function(data) {
            if (data.error) {
                $(element).find('#vdo-error').text(data.error).show();
                $(element).find('.vdo-loading').hide();
                return;
            }

            // Build iframe
            var container = $(element).find('#vdo-container')[0];
            var iframe = document.createElement('iframe');
            iframe.src = 'https://player.vdocipher.com/v2/?otp=' +
                         encodeURIComponent(data.otp) +
                         '&playbackInfo=' + encodeURIComponent(data.playbackInfo);
            iframe.setAttribute('allow', 'encrypted-media');
            iframe.setAttribute('allowfullscreen', 'true');

            // Remove loading text
            $(element).find('.vdo-loading').hide();
            container.appendChild(iframe);

            // Wait for API + iframe to load
            iframe.addEventListener('load', function() {
                waitForApi(function() {
                    initPlayer(iframe);
                });
            });
        },
        error: function() {
            $(element).find('#vdo-error').text('Failed to load video').show();
            $(element).find('.vdo-loading').hide();
        }
    });

    function waitForApi(callback) {
        if (typeof VdoPlayer !== 'undefined') {
            setTimeout(callback, 500); // Small delay for player init
        } else {
            setTimeout(function() { waitForApi(callback); }, 200);
        }
    }

    function initPlayer(iframe) {
        try {
            var player = VdoPlayer.getInstance(iframe);

            // Track progress via timeupdate (async — returns Promises)
            player.video.addEventListener('timeupdate', function() {
                var now = Date.now();
                if (now - lastReportTime < REPORT_INTERVAL) return;
                lastReportTime = now;

                Promise.all([
                    player.video.currentTime,
                    player.video.duration
                ]).then(function(values) {
                    var currentTime = values[0];
                    var duration = values[1];
                    if (duration > 0) {
                        reportProgress(Math.round(currentTime), Math.round(duration));
                    }
                }).catch(function(err) {
                    console.warn('VdoCipher timeupdate error:', err);
                });
            });

            // Final report when video ends
            player.video.addEventListener('ended', function() {
                player.video.duration.then(function(duration) {
                    reportProgress(Math.round(duration), Math.round(duration));
                }).catch(function() {});
            });

        } catch (e) {
            console.error('VdoCipher player init error:', e);
        }
    }

    function reportProgress(watchTime, totalDuration) {
        $.ajax({
            type: 'POST',
            url: handlerUrl,
            data: JSON.stringify({
                watch_time: watchTime,
                total_duration: totalDuration
            }),
            contentType: 'application/json',
            success: function(result) {
                if (result.percentage !== undefined) {
                    $(element).find('.vdo-progress-fill').css('width', result.percentage + '%');
                    $(element).find('.vdo-progress-text').text(result.percentage + '% watched');
                }
                if (result.completed) {
                    $(element).find('.vdo-completed-badge').show();
                }
            }
        });
    }
}

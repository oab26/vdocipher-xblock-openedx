function VdoCipherXBlock(runtime, element) {
    var progressUrl = runtime.handlerUrl(element, 'video_progress');
    var otpUrl = runtime.handlerUrl(element, 'get_otp');
    var quizUrl = runtime.handlerUrl(element, 'submit_quiz');
    var quizStateUrl = runtime.handlerUrl(element, 'get_quiz_state');
    var lastReportTime = 0;
    var REPORT_INTERVAL = 30000;
    var timemap = {};
    var answeredQuizzes = {};
    var quizShowing = false;

    // Load VdoCipher Player API
    if (!document.getElementById('vdocipher-api-script')) {
        var script = document.createElement('script');
        script.id = 'vdocipher-api-script';
        script.src = 'https://player.vdocipher.com/v2/api.js';
        document.head.appendChild(script);
    }

    // Step 1: Load quiz state FIRST, then load video
    $.ajax({
        type: 'POST', url: quizStateUrl,
        data: JSON.stringify({}), contentType: 'application/json',
        success: function(state) {
            try {
                timemap = JSON.parse(state.timemap || '{}');
                var answers = JSON.parse(state.answers || '{}');
                for (var ts in answers) { answeredQuizzes[ts] = true; }
                console.log('VdoCipher quiz timemap loaded:', Object.keys(timemap).length, 'questions');
            } catch(e) {
                console.warn('VdoCipher quiz state parse error:', e);
            }
            // Step 2: Now load the video
            loadVideo();
        },
        error: function() {
            // Load video even if quiz state fails
            loadVideo();
        }
    });

    function loadVideo() {
        $.ajax({
            type: 'POST', url: otpUrl,
            data: JSON.stringify({}), contentType: 'application/json',
            success: function(data) {
                if (data.error) {
                    $(element).find('#vdo-error').text(data.error).show();
                    $(element).find('.vdo-loading').hide();
                    return;
                }

                var container = $(element).find('#vdo-container')[0];
                var iframe = document.createElement('iframe');
                iframe.src = 'https://player.vdocipher.com/v2/?otp=' +
                             encodeURIComponent(data.otp) +
                             '&playbackInfo=' + encodeURIComponent(data.playbackInfo);
                iframe.setAttribute('allow', 'encrypted-media');
                iframe.setAttribute('allowfullscreen', 'true');
                $(element).find('.vdo-loading').hide();
                container.appendChild(iframe);

                iframe.addEventListener('load', function() {
                    waitForApi(function() { initPlayer(iframe); });
                });
            },
            error: function() {
                $(element).find('#vdo-error').text('Failed to load video').show();
                $(element).find('.vdo-loading').hide();
            }
        });
    }

    function waitForApi(callback) {
        if (typeof VdoPlayer !== 'undefined') {
            setTimeout(callback, 500);
        } else {
            setTimeout(function() { waitForApi(callback); }, 200);
        }
    }

    function initPlayer(iframe) {
        try {
            var player = VdoPlayer.getInstance(iframe);
            var lastCheckedSecond = -1;

            player.video.addEventListener('timeupdate', function() {
                Promise.all([
                    player.video.currentTime,
                    player.video.duration
                ]).then(function(values) {
                    var currentTime = values[0];
                    var duration = values[1];
                    var timeInt = Math.floor(currentTime);

                    // Check for quiz — only check each second once
                    if (timeInt !== lastCheckedSecond) {
                        lastCheckedSecond = timeInt;
                        var timeStr = String(timeInt);
                        if (timemap[timeStr] && !answeredQuizzes[timeStr] && !quizShowing) {
                            quizShowing = true;
                            player.video.pause().then(function() {
                                showQuiz(timemap[timeStr], timeStr, player);
                            });
                        }
                    }

                    // Report progress periodically
                    var now = Date.now();
                    if (now - lastReportTime < REPORT_INTERVAL) return;
                    lastReportTime = now;
                    if (duration > 0) {
                        reportProgress(Math.round(currentTime), Math.round(duration));
                    }
                }).catch(function() {});
            });

            player.video.addEventListener('ended', function() {
                player.video.duration.then(function(duration) {
                    reportProgress(Math.round(duration), Math.round(duration));
                }).catch(function() {});
            });

        } catch (e) {
            console.error('VdoCipher player init error:', e);
        }
    }

    function showQuiz(question, timestamp, player) {
        var overlay = $(element).find('#quiz-overlay');
        var html = '<div class="quiz-card">';
        html += '<h3 class="quiz-question">' + escapeHtml(question.q) + '</h3>';
        html += '<div class="quiz-options">';
        for (var i = 0; i < question.opts.length; i++) {
            html += '<button class="quiz-option" data-idx="' + i + '">' + escapeHtml(question.opts[i]) + '</button>';
        }
        html += '</div>';
        html += '<div class="quiz-feedback" style="display:none;"></div>';
        html += '</div>';

        overlay.html(html).show();

        overlay.find('.quiz-option').on('click', function() {
            var selected = parseInt($(this).data('idx'));
            overlay.find('.quiz-option').off('click').css('pointer-events', 'none');
            $(this).addClass('selected');

            $.ajax({
                type: 'POST', url: quizUrl,
                data: JSON.stringify({ timestamp: timestamp, selected: selected }),
                contentType: 'application/json',
                success: function(result) {
                    answeredQuizzes[timestamp] = true;

                    var feedback = overlay.find('.quiz-feedback');
                    if (result.correct) {
                        feedback.html('<span class="correct">&#10003; Correct!</span>').show();
                        overlay.find('.quiz-option[data-idx="' + selected + '"]').addClass('correct');
                    } else {
                        feedback.html('<span class="incorrect">&#10007; Incorrect. Answer: ' +
                            escapeHtml(question.opts[result.correct_answer]) + '</span>').show();
                        overlay.find('.quiz-option[data-idx="' + selected + '"]').addClass('incorrect');
                        overlay.find('.quiz-option[data-idx="' + result.correct_answer + '"]').addClass('correct');
                    }

                    $(element).find('.quiz-score-text').text('Quiz: ' + result.score + '/' + result.total).show();

                    setTimeout(function() {
                        overlay.fadeOut(300, function() {
                            quizShowing = false;
                            player.video.play();
                        });
                    }, 2500);
                }
            });
        });
    }

    function reportProgress(watchTime, totalDuration) {
        $.ajax({
            type: 'POST', url: progressUrl,
            data: JSON.stringify({ watch_time: watchTime, total_duration: totalDuration }),
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

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }
}

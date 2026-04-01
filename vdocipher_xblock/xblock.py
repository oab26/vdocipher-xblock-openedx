"""VdoCipher DRM video player XBlock."""

import json
import logging
import pkg_resources
import requests

from django.conf import settings
from xblock.core import XBlock
from xblock.fields import String, Integer, Boolean, Scope
from xblock.fragment import Fragment

log = logging.getLogger(__name__)

VDOCIPHER_OTP_URL = 'https://dev.vdocipher.com/api/videos/{video_id}/otp'


@XBlock.wants('user')
class VdoCipherXBlock(XBlock):
    """Embeds VdoCipher DRM-protected video with completion tracking."""

    display_name = String(
        display_name="Display Name",
        scope=Scope.content,
        default="Video",
        help="Name shown to students"
    )
    video_id = String(
        display_name="VdoCipher Video ID",
        scope=Scope.content,
        default='',
        help="Video ID from your VdoCipher dashboard"
    )
    completion_threshold = Integer(
        display_name="Completion Threshold (%)",
        scope=Scope.content,
        default=90,
        help="Percentage watched to mark as complete"
    )

    # Quiz configuration (set by instructor)
    timemap = String(
        display_name="Quiz Questions (JSON)",
        scope=Scope.content,
        default='{}',
        help='JSON mapping timestamps to questions: {"30": {"q": "What is X?", "opts": ["A","B","C","D"], "ans": 0}, "60": {...}}'
    )

    # Per-student state (auto-persisted)
    watch_time = Integer(scope=Scope.user_state, default=0)
    completion_percentage = Integer(scope=Scope.user_state, default=0)
    is_completed = Boolean(scope=Scope.user_state, default=False)
    quiz_answers = String(scope=Scope.user_state, default='{}')
    quiz_score = Integer(scope=Scope.user_state, default=0)
    quiz_total = Integer(scope=Scope.user_state, default=0)

    has_score = True

    def resource_string(self, path):
        data = pkg_resources.resource_string(__name__, path)
        return data.decode('utf-8')

    def student_view(self, context=None):
        """Render the video player for students."""
        html = self.resource_string('static/html/student.html')
        frag = Fragment(html.format(
            display_name=self.display_name,
            video_id=self.video_id,
            completion_percentage=self.completion_percentage,
            is_completed='true' if self.is_completed else 'false',
            completed_display='inline' if self.is_completed else 'none',
        ))
        frag.add_css(self.resource_string('static/css/vdocipher.css'))
        frag.add_javascript(self.resource_string('static/js/vdocipher.js'))
        frag.initialize_js('VdoCipherXBlock')
        return frag

    def studio_view(self, context=None):
        """Render the config form for instructors in Studio."""
        html = self.resource_string('static/html/studio.html')
        # Use manual replacement to avoid .format() brace conflicts with JSON
        html = html.replace('__VIDEO_ID__', self.video_id or '')
        html = html.replace('__DISPLAY_NAME__', self.display_name or 'Video')
        html = html.replace('__COMPLETION_THRESHOLD__', str(self.completion_threshold))
        html = html.replace('__TIMEMAP__', self.timemap or '{}')
        frag = Fragment(html)
        frag.add_javascript('''
            function StudioEditableXBlockMixin(runtime, element) {
                $(element).find('.save-button').on('click', function() {
                    var handlerUrl = runtime.handlerUrl(element, 'studio_submit');
                    $.post(handlerUrl, JSON.stringify({
                        video_id: $(element).find('#video_id').val(),
                        display_name: $(element).find('#display_name').val(),
                        completion_threshold: $(element).find('#completion_threshold').val(),
                        timemap: $(element).find('#timemap').val()
                    }), function() {
                        runtime.notify('save', {state: 'end'});
                    });
                });
                $(element).find('.cancel-button').on('click', function() {
                    runtime.notify('cancel', {});
                });
            }
        ''')
        frag.initialize_js('StudioEditableXBlockMixin')
        return frag

    @XBlock.json_handler
    def studio_submit(self, data, suffix=''):
        """Save studio settings."""
        self.video_id = data.get('video_id', '').strip()
        self.display_name = data.get('display_name', 'Video').strip()
        self.completion_threshold = int(data.get('completion_threshold', 90))
        timemap_str = data.get('timemap', '{}').strip()
        try:
            json.loads(timemap_str)  # Validate JSON
            self.timemap = timemap_str
        except json.JSONDecodeError:
            return {'result': 'error', 'message': 'Invalid JSON in quiz questions'}
        return {'result': 'success'}

    @XBlock.json_handler
    def get_otp(self, data, suffix=''):
        """Generate VdoCipher OTP for secure playback."""
        if not self.video_id:
            return {'error': 'No video configured'}

        api_secret = getattr(settings, 'VDOCIPHER_API_SECRET', '')
        if not api_secret:
            return {'error': 'VdoCipher API secret not configured'}

        # Get student info for watermark
        email = 'student@vai.edu'
        name = 'Student'
        user_id = ''

        try:
            user_service = self.runtime.service(self, 'user')
            if user_service:
                xb_user = user_service.get_current_user()

                # Only trust user data if authenticated
                is_authenticated = xb_user.opt_attrs.get(
                    'edx-platform.is_authenticated', False
                )

                if is_authenticated:
                    if xb_user.emails and len(xb_user.emails) > 0:
                        email = xb_user.emails[0]
                    if xb_user.full_name:
                        name = xb_user.full_name
                    elif xb_user.opt_attrs.get('edx-platform.username'):
                        name = xb_user.opt_attrs['edx-platform.username']
                    user_id = str(
                        xb_user.opt_attrs.get('edx-platform.user_id', '')
                    )
                else:
                    log.info('VdoCipher: user not authenticated, using fallbacks')
        except Exception as e:
            log.warning('Could not get user info for VdoCipher: %s', e)

        log.info('VdoCipher OTP: name=%s, email=%s, user_id=%s', name, email, user_id)

        # Build watermark annotation (double-encoded JSON string)
        annotate = json.dumps([{
            'type': 'rtext',
            'text': '{} - {}'.format(name, email),
            'alpha': '0.50',
            'color': '0x490B8A',
            'size': '12',
            'interval': '5000',
        }])

        try:
            response = requests.post(
                VDOCIPHER_OTP_URL.format(video_id=self.video_id),
                headers={
                    'Authorization': 'Apisecret {}'.format(api_secret),
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                json={
                    'ttl': 300,
                    'annotate': annotate,
                },
                timeout=10,
            )

            if user_id:
                body = response.json() if response.status_code == 200 else {}
                # Retry with userId if first call worked
                if response.status_code == 200:
                    result = response.json()
                    return {
                        'otp': result.get('otp', ''),
                        'playbackInfo': result.get('playbackInfo', ''),
                    }

            if response.status_code != 200:
                log.error('VdoCipher OTP error: %s %s', response.status_code, response.text[:200])
                return {'error': 'Failed to generate video token'}

            result = response.json()
            return {
                'otp': result.get('otp', ''),
                'playbackInfo': result.get('playbackInfo', ''),
            }

        except requests.exceptions.Timeout:
            return {'error': 'Video service timeout'}
        except Exception as e:
            log.error('VdoCipher OTP exception: %s', e)
            return {'error': 'Video service error'}

    @XBlock.json_handler
    def video_progress(self, data, suffix=''):
        """Handle video progress from frontend JavaScript."""
        watch_time = data.get('watch_time', 0)
        total_duration = max(data.get('total_duration', 1), 1)
        percentage = min(int((watch_time / total_duration) * 100), 100)

        self.watch_time = watch_time
        self.completion_percentage = percentage

        if percentage >= self.completion_threshold and not self.is_completed:
            self.is_completed = True
            self.runtime.publish(self, 'completion', {'completion': 1.0})
            self.runtime.publish(self, 'grade', {
                'value': 1.0,
                'max_value': 1.0,
            })
            log.info('VdoCipher video completed: video_id=%s, percentage=%s', self.video_id, percentage)

        return {
            'status': 'success',
            'percentage': self.completion_percentage,
            'completed': self.is_completed,
        }

    @XBlock.json_handler
    def submit_quiz(self, data, suffix=''):
        """Handle quiz answer submission from frontend."""
        timestamp = str(data.get('timestamp', ''))
        selected = data.get('selected', -1)

        try:
            timemap = json.loads(self.timemap)
        except json.JSONDecodeError:
            return {'error': 'Invalid quiz configuration'}

        if timestamp not in timemap:
            return {'error': 'Unknown quiz timestamp'}

        question = timemap[timestamp]
        correct_answer = question.get('ans', -1)
        is_correct = (selected == correct_answer)

        # Store answer
        answers = json.loads(self.quiz_answers or '{}')
        answers[timestamp] = {
            'selected': selected,
            'correct': is_correct,
        }
        self.quiz_answers = json.dumps(answers)

        # Calculate quiz score
        total_questions = len(timemap)
        correct_count = sum(1 for a in answers.values() if a.get('correct'))
        self.quiz_score = correct_count
        self.quiz_total = total_questions

        # Update grade: 50% video completion + 50% quiz score
        video_grade = 1.0 if self.is_completed else (self.completion_percentage / 100.0)
        quiz_grade = correct_count / max(total_questions, 1)
        combined = (video_grade * 0.5) + (quiz_grade * 0.5)

        self.runtime.publish(self, 'grade', {
            'value': round(combined, 2),
            'max_value': 1.0,
        })

        return {
            'correct': is_correct,
            'correct_answer': correct_answer,
            'score': self.quiz_score,
            'total': self.quiz_total,
        }

    @XBlock.json_handler
    def track_event(self, data, suffix=''):
        """Emit standard Open edX video tracking events for Aspects analytics."""
        event_type = data.get('event_type', '')

        ALLOWED_EVENTS = {
            'play_video', 'pause_video', 'seek_video',
            'stop_video', 'load_video', 'speed_change_video',
            'complete_video',
        }

        if event_type not in ALLOWED_EVENTS:
            return {'status': 'ignored'}

        # Send just the block hash so event-routing-backends constructs
        # a matchable object_id (type@video+block@{hash})
        usage_key = str(self.scope_ids.usage_id) if hasattr(self, 'scope_ids') else ''
        block_hash = usage_key.split('@')[-1] if usage_key else self.video_id

        event_data = {
            'id': block_hash,
            'code': 'vdocipher',
            'currentTime': data.get('current_time', 0),
            'duration': data.get('duration', 0),
        }

        if event_type == 'seek_video':
            event_data['old_time'] = data.get('old_time', 0)
            event_data['new_time'] = data.get('new_time', 0)

        if event_type == 'speed_change_video':
            event_data['old_speed'] = data.get('old_speed', '1.0')
            event_data['new_speed'] = data.get('new_speed', '1.0')

        self.runtime.publish(self, event_type, event_data)
        return {'status': 'ok'}

    @XBlock.json_handler
    def get_quiz_state(self, data, suffix=''):
        """Return current quiz state for the student."""
        return {
            'timemap': self.timemap,
            'answers': self.quiz_answers,
            'score': self.quiz_score,
            'total': self.quiz_total,
        }

    @staticmethod
    def workbench_scenarios():
        return [
            ("VdoCipherXBlock", "<vdocipher video_id='test123' />"),
        ]

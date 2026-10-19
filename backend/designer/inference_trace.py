"""Request-local evidence of real HTTP calls; never store prompts or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
import copy

_current = ContextVar('designer_inference_trace', default=None)


def new_trace(requested=False):
    return dict(requested=requested, attempted=False, completed=False, provider=None,
                model=None, attempts=0, successful_calls=0, duration_seconds=0.0,
                validation='not_run', fallback_used=False, status='not_requested',
                error_code=None, message='', response_id=None, response_sha256=None, usage=None, calls=[],
                content_reused_for_variants=0, model_attempt=0, model_max_attempts=0, retry_reason=None)


@contextmanager
def capture_inference(trace=None, on_update=None):
    """Capture calls made through ai.ask and validations by ai.complete_json."""
    trace = trace if trace is not None else new_trace(True)
    token = _current.set((trace, on_update))
    try:
        yield trace
    finally:
        _current.reset(token)


def current_trace():
    current = _current.get()
    return current[0] if current else None


def validated_content(trace):
    shared = trace.get('shared_inference')
    if shared is not None:
        return bool(trace.get('requested') and trace.get('completed')
            and trace.get('validation') == 'passed' and not trace.get('fallback_used')
            and not trace.get('attempted') and not trace.get('calls')
            and trace.get('content_revalidated') is True and trace.get('shared_from_job_id')
            and trace.get('shared_from_job_id') == shared.get('content_source_job_id')
            and trace.get('content_input_sha256') == shared.get('content_input_sha256')
            and trace.get('content_batch_id') == shared.get('content_batch_id')
            and not shared.get('shared_inference') and validated_content(shared))
    return bool(trace.get('requested') and trace.get('attempted') and trace.get('completed')
        and trace.get('validation') == 'passed' and not trace.get('fallback_used')
        and trace.get('successful_calls', 0) > 0
        and any(call.get('validation') == 'passed' and isinstance(call.get('status_code'), int)
                and 200 <= call['status_code'] < 300 for call in trace.get('calls', [])))


def publish():
    current = _current.get()
    if current and current[1]:
        current[1](copy.deepcopy(current[0]))


def mark_validated(call, passed):
    trace = current_trace()
    if trace is None or call is None:
        return
    call['validation'] = 'passed' if passed else 'failed'
    trace['validation'] = call['validation']
    if passed:
        trace.update(completed=True, status='completed', error_code=None,
                     successful_calls=trace['successful_calls'] + 1,
                     response_id=call.get('response_id'), usage=call.get('usage'),
                     response_sha256=call.get('response_sha256'),
                     message='Ответ модели получен и проверен')
    publish()

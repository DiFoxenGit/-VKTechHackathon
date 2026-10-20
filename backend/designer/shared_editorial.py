"""One fresh model edit per explicit HTTP batch, never a cross-request cache."""
import asyncio
import copy
import time

from .business_editorial import edit_business, input_digest, validate_editorial
from .inference_trace import capture_inference, publish


class SharedEditorial:
    def __init__(self, batch_id):
        self.batch_id = batch_id
        self.future = None
        self.owner = None
        self.digest = None
        self.listeners = []

    def metadata(self, trace, job_id):
        trace.update(content_batch_id=self.batch_id, content_source_job_id=self.owner,
                     content_input_sha256=self.digest)
        if job_id != self.owner:
            trace['shared_from_job_id'] = self.owner

    async def edit(self, sources, outline, brief, job_id, trace, on_update):
        digest = input_digest(sources)
        if self.future is None:
            self.owner, self.digest = job_id, digest
            self.future = asyncio.get_running_loop().create_future()
            self.metadata(trace, job_id)

            def update(value):
                if on_update:
                    on_update(value)
                for listener in self.listeners:
                    listener(value)

            started = time.monotonic()
            try:
                with capture_inference(trace, update):
                    async with asyncio.timeout(240):
                        candidate = await edit_business(sources, outline, brief)
                    trace.update(content_revalidated=True,
                                 duration_seconds=round(time.monotonic() - started, 3))
                    publish()
                self.future.set_result((copy.deepcopy(sources[0]['_business_editorial']),
                                        copy.deepcopy(trace), None))
                return candidate
            except BaseException as exc:
                # Resolve with an outcome, so cancellation never leaves followers
                # hanging or causes an unobserved Future exception.
                self.future.set_result((None, copy.deepcopy(trace), exc))
                raise
        if digest != self.digest:
            raise ValueError('Общая редактура относится к другим исходникам или условиям')
        self.metadata(trace, job_id)
        trace.update(status='waiting_for_shared_content', requested=True)

        def update(value):
            for key in ('provider', 'model', 'model_attempt', 'model_max_attempts', 'retry_reason'):
                if key in value:
                    trace[key] = value[key]
            if on_update:
                on_update(copy.deepcopy(trace))

        self.listeners.append(update)
        try:
            if on_update:
                on_update(copy.deepcopy(trace))
            saved, source_trace, error = await asyncio.shield(self.future)
            update(source_trace)
            if error is not None:
                trace['error_code'] = source_trace.get('error_code') or 'provider_error'
                if isinstance(error, asyncio.CancelledError):
                    raise TimeoutError('Исходное задание общей редактуры прервано')
                raise error
            from .business_bridge import business_outline, present_business
            canonical = business_outline(sources, 30, canonical=True)
            candidate, _ = validate_editorial(saved['response'], sources, canonical)
            sources[0]['_business_editorial'] = copy.deepcopy(saved)
            trace.update(completed=True, validation='passed', status='completed',
                         content_revalidated=True, shared_inference=source_trace,
                         response_id=source_trace.get('response_id'),
                         response_sha256=source_trace.get('response_sha256'),
                         message='Общий текст модели проверен для этого шаблона')
            publish()
            return present_business(sources, candidate)
        finally:
            self.listeners.remove(update)

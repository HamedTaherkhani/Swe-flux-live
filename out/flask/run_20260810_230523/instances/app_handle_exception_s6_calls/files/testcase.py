import random
import unittest

from flask import Flask, after_this_request, got_request_exception, request
from flask import request_finished


class TestIndirectExceptionCallGraph(unittest.TestCase):
    def test_generated_requests_exercise_error_pipeline(self) -> None:
        rng = random.Random(681_407)
        app = Flask("_".join(("runtime", "exception", "graph")))
        app.config.update(PROPAGATE_EXCEPTIONS=False, TESTING=False)
        app.logger.disabled = True

        request_ids = list(range(24))
        rng.shuffle(request_ids)
        plans = {
            request_id: (
                2 + rng.randrange(7),
                tuple(rng.randrange(31, 997) for _ in range(9)),
            )
            for request_id in request_ids
        }
        signal_audit = []
        signal_receivers = []

        for receiver_index in range(4):
            def on_exception(sender, *, exception, _slot=receiver_index, **extra):
                signal_audit.append(("exception", _slot, type(exception).__name__))

            signal_receivers.append(on_exception)
            got_request_exception.connect(on_exception, app, weak=False)

        for receiver_index in range(3):
            def on_finished(sender, *, response, _slot=receiver_index, **extra):
                signal_audit.append(("finished", _slot, response.status_code))

            signal_receivers.append(on_finished)
            request_finished.connect(on_finished, app, weak=False)

        for callback_index in range(5):
            def global_after(response, _slot=callback_index):
                response.headers.add("X-QA-Global", str(_slot))
                return response

            app.after_request(global_after)

        @app.errorhandler(500)
        def convert_unhandled_error(error):
            request_id = int(request.view_args["request_id"])
            rounds, values = plans[request_id]
            checksum = sum(
                (position + rounds) * (value ^ request_id)
                for position, value in enumerate(values)
            )
            mode = (checksum + rounds + request_id) % 3

            if mode == 0:
                return {"checksum": checksum, "mode": mode}, 500
            if mode == 1:
                return [checksum, mode, len(values)], 500, {"X-QA-Mode": str(mode)}
            return f"failure-{checksum:x}", "500 INTERNAL SERVER ERROR"

        @app.get("/generated/<int:request_id>")
        def generated_failure(request_id):
            rounds, values = plans[request_id]
            rolling = request_id + rounds

            for position in range(rounds):
                rolling = (
                    rolling * 37
                    + values[position]
                    + sum(values[position::2])
                ) % 1_000_003

                @after_this_request
                def local_after(response, _step=position, _value=rolling):
                    response.headers.add("X-QA-Local", f"{_step}:{_value % 97}")
                    return response

            raise RuntimeError(f"generated failure {rolling:x}")

        client = app.test_client()
        responses = [
            client.get(f"/generated/{request_id}") for request_id in request_ids
        ]

        self.assertTrue(all(response.status_code == 500 for response in responses))
        self.assertEqual(
            [len(response.headers.getlist("X-QA-Global")) for response in responses],
            [5] * len(responses),
        )
        self.assertTrue(
            all(
                len(response.headers.getlist("X-QA-Local")) == plans[request_id][0]
                for response, request_id in zip(responses, request_ids)
            )
        )
        self.assertGreater(len(signal_audit), len(responses))

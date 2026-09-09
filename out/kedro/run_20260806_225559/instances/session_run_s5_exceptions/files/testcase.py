from __future__ import annotations

import builtins
import random
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import kedro.framework.session.session as session_module
from kedro.framework.session.session import KedroSession
from kedro.runner import AbstractRunner


class TestSessionRunExceptions(unittest.TestCase):
    def test_seeded_runner_failures(self) -> None:
        seed = sum((position + 7) * ord(char) for position, char in enumerate(__name__))
        rng = random.Random(seed)

        reversed_names = (
            "rorrEcitemhtirA",
            "rorrEnoitressA",
            "rorrEetubirttA",
            "rorrEreffuB",
            "rorrEFOE",
            "rorrEtropmI",
            "rorrEpukooL",
            "rorrEyromeM",
            "rorrEemaN",
            "rorrEdetnemelpmItoN",
            "rorrESO",
            "rorrEwolfrevO",
            "rorrEecnerefeR",
            "rorrEemitnuR",
            "noitaretIcnysApotS",
            "rorrExatnyS",
            "rorrEmetsyS",
            "rorrEepyT",
            "rorrEedocinU",
            "rorrEtnioPgnitaolF",
            "rorrEnoisiviDoreZ",
        )
        exception_names = ["".join(reversed(token)) for token in reversed_names]
        rng.shuffle(exception_names)
        exception_names = exception_names[: 16 + rng.randrange(5)]

        pipeline = MagicMock()
        pipeline.filter.side_effect = lambda **kwargs: SimpleNamespace(
            selection=sum(
                (index + 1) * len(str(value))
                for index, value in enumerate(kwargs.values())
            )
        )
        caught_records: list[tuple[BaseException, int]] = []

        with patch.object(session_module, "pipelines", {"__default__": pipeline}):
            for invocation, exception_name in enumerate(exception_names, start=1):
                session = object.__new__(KedroSession)
                session._project_path = Path("/virtual") / str(
                    (rng.randrange(997) * invocation + seed) % 991
                )
                session._run_called = False
                session._store = {
                    "session_id": f"generated-{(seed * invocation + rng.randrange(313)) % 1009}",
                    "runtime_params": {
                        f"slot-{position}": (rng.randrange(409) + invocation * position) % 401
                        for position in range(1 + invocation % 4)
                    },
                }
                session._hook_manager = MagicMock()
                context = SimpleNamespace(
                    env=f"env-{(rng.randrange(127) + invocation * invocation) % 113}",
                    _get_catalog=MagicMock(
                        return_value=SimpleNamespace(marker=rng.randrange(10000))
                    ),
                )
                session.load_context = Mock(return_value=context)

                error_kind = getattr(builtins, exception_name)
                message_material = [
                    chr(97 + (rng.randrange(26) + invocation + offset) % 26)
                    for offset in range(9 + invocation % 7)
                ]
                runner = Mock(spec=AbstractRunner)
                runner.run.side_effect = error_kind("".join(message_material))

                tags = {
                    f"tag-{(rng.randrange(43) + position * invocation) % 41}"
                    for position in range(2 + invocation % 5)
                }
                node_names = [
                    f"node-{(rng.randrange(89) * (position + 3) + invocation) % 83}"
                    for position in range(3 + invocation % 6)
                ]

                try:
                    KedroSession.run(
                        session,
                        tags=tags,
                        runner=runner,
                        node_names=node_names,
                        from_inputs=(name.swapcase() for name in node_names[::2]),
                        to_outputs=tuple(reversed(node_names[1::2])),
                        only_missing_outputs=bool((rng.randrange(17) + invocation) % 2),
                    )
                except Exception as caught:
                    caught_records.append(
                        (
                            caught,
                            len(tags)
                            + len(node_names)
                            + len(session._store["runtime_params"]),
                        )
                    )
                else:
                    self.fail("The generated runner unexpectedly returned normally")

        self.assertEqual(len(caught_records), len(exception_names))
        self.assertEqual(len({type(item[0]) for item in caught_records}), len(caught_records))
        self.assertTrue(all(isinstance(item[0], Exception) for item in caught_records))
        self.assertGreater(sum(item[1] for item in caught_records), len(caught_records))
        self.assertEqual(
            session._hook_manager.hook.on_pipeline_error.call_count,
            1,
        )

from unittest import TestCase

from flask import Blueprint, Flask


class BlueprintRouteExceptionTest(TestCase):
    def test_generated_route_registrations(self) -> None:
        outcomes: list[bool] = []
        app = Flask(__name__)

        for index in range(48):
            blueprint = Blueprint(
                f"generated_{index:04x}_{(index * 31 + 7) % 127:x}",
                __name__,
                url_prefix=f"/prefix/{(index * 17 + 3) % 97:x}/{(index * 23 + 5) % 31:x}",
            )
            mode = (index * 5 + index // 2 + 1) % 5
            endpoint = f"route_{(index * 13 + 7) % 89:x}_{(index * 3) % 17}"

            def view() -> str:
                return endpoint

            view.__name__ = f"view_{(index * 19 + 11) % 97:x}"

            if mode == 1:
                endpoint = f"{endpoint}.branch_{index % 13:x}_n{(index * 3) % 17}"
            elif mode == 2:
                view.__name__ = f"{view.__name__}.leaf_{index % 11:x}_seg{(index * 5) % 23}"
            elif mode == 3:
                endpoint = bytes([((index * 5 + 13) % 26) + 97]) if (index * 11 + 3) % 5 < 2 else ((index * 7 + 3) % 19) + 1  # type: ignore[assignment]

            try:
                blueprint.route(
                    f"/generated/{(index * 17 + 3) % 97:x}/{(index * 23 + 5) % 31:x}/{(index * 3) % 7:x}",
                    endpoint=endpoint,
                )(view)
            except Exception:
                outcomes.append(False)
            else:
                outcomes.append(True)
                app.register_blueprint(blueprint)

        class DeferredMutation:
            def __init__(self, owner: Blueprint, token: str) -> None:
                self.owner = owner
                self.token = token

            def __bool__(self) -> bool:
                return True

            def __contains__(self, item: object) -> bool:
                self.owner._got_registered_once = bool(self.token)  # type: ignore[attr-defined]
                return item == self.token

        for index in range(12):
            blueprint = Blueprint(
                f"deferred_{index:02x}_{(index * 29 + 3) % 53:x}",
                __name__,
                subdomain=f"{chr(97 + index % 5)}{index % 3}",
            )
            endpoint = DeferredMutation(
                blueprint,
                (
                    ".",
                    f"sentinel_{(index * 23 + 11) % 71:x}",
                    f"sentinel_{(index * 41 + 5) % 83:x}",
                )[(index * 7 + 2) % 3],
            )

            def delayed_view() -> str:
                return endpoint.token

            try:
                blueprint.route(
                    f"/deferred/{index:02x}/{(index * 7 + 2) % 19:x}",
                    endpoint=endpoint,
                )(delayed_view)
            except Exception:
                outcomes.append(False)
            else:
                outcomes.append(True)

        self.assertEqual(len(outcomes), 60)
        self.assertTrue(any(outcomes))
        self.assertTrue(any(not outcome for outcome in outcomes))
        self.assertGreater(sum(not outcome for outcome in outcomes), sum(outcomes))

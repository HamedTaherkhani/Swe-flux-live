from unittest import TestCase

from flask import Blueprint, Flask


class BlueprintRouteExceptionTest(TestCase):
    def test_generated_route_registrations(self) -> None:
        outcomes: list[bool] = []
        app = Flask(__name__)

        for index in range(48):
            blueprint = Blueprint(f"generated_{index:x}", __name__)
            mode = (index * 5 + index // 2 + 1) % 4
            endpoint = f"route_{(index * 7 + 5) % 53:x}"

            def view() -> str:
                return endpoint

            view.__name__ = f"view_{(index * 11 + 9) % 59:x}"

            if mode == 1:
                endpoint = f"{endpoint}.branch_{index % 7:x}"
            elif mode == 2:
                view.__name__ = f"{view.__name__}.leaf_{index % 5:x}"
            elif mode == 3:
                endpoint = index + 1  # type: ignore[assignment]

            try:
                blueprint.route(
                    f"/generated/{(index * 13 + 4) % 61:x}",
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
            blueprint = Blueprint(f"deferred_{index:x}", __name__)
            endpoint = DeferredMutation(
                blueprint,
                f"sentinel_{(index * 17 + 6) % 67:x}",
            )

            def delayed_view() -> str:
                return endpoint.token

            try:
                blueprint.route(f"/deferred/{index:x}", endpoint=endpoint)(delayed_view)
            except Exception:
                outcomes.append(False)
            else:
                outcomes.append(True)

        self.assertEqual(len(outcomes), 60)
        self.assertTrue(any(outcomes))
        self.assertTrue(any(not outcome for outcome in outcomes))
        self.assertGreater(sum(not outcome for outcome in outcomes), sum(outcomes))

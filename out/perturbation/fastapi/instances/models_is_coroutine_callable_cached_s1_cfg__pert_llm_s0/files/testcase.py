import unittest

from fastapi.dependencies.models import (
    _CallIdentity,
    _is_coroutine_callable_cached,
)


def make_async_function(token):
    async def generated_async():
        return token

    return generated_async


def make_wrapped_function(token):
    async def wrapped_target():
        return token

    def generated_wrapper():
        return token + 1

    generated_wrapper.__wrapped__ = wrapped_target
    return generated_wrapper


def make_callable_class(token):
    def generated_call(self):
        return token

    return type(f"GeneratedType_{token}", (), {"__call__": generated_call})


def make_async_callable(token):
    async def generated_call(self):
        return token

    callable_type = type(
        f"GeneratedAsyncCallable_{token}", (), {"__call__": generated_call}
    )
    return callable_type()


def make_sync_callable(token):
    def generated_call(self):
        return token

    callable_type = type(
        f"GeneratedSyncCallable_{token}", (), {"__call__": generated_call}
    )
    return callable_type()


BUILDERS = (
    make_async_function,
    make_wrapped_function,
    make_callable_class,
    make_async_callable,
    make_sync_callable,
)


class TestCoroutineCallableClassification(unittest.TestCase):
    def test_programmatic_callable_matrix(self):
        _is_coroutine_callable_cached.cache_clear()
        callables = []
        state = 0xB16B00B5
        for index in range(251):
            state = (state * 1664525 + 1013904223) & 0x7FFFFFFF
            token = state ^ (index * index + 43 * index)
            kind = ((index * 11) ^ (index >> 1) ^ 7) % len(BUILDERS)
            callables.append(BUILDERS[kind](token))

        results = [
            _is_coroutine_callable_cached(_CallIdentity(callable_object))
            for callable_object in callables
        ]

        self.assertGreater(len(results), 230)
        self.assertTrue(any(results))
        self.assertFalse(all(results))
        self.assertEqual({type(result) for result in results}, {bool})

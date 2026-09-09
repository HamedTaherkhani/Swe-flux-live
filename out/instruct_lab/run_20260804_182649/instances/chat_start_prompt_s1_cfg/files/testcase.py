from types import SimpleNamespace
from unittest.mock import patch
import random
import unittest

from instructlab.model import chat


class _Models:
    def list(self):
        return SimpleNamespace(data=[SimpleNamespace(id="served-model")])


class _Completions:
    calls = 0
    chunks_built = 0

    def create(self, **_kwargs):
        type(self).calls += 1
        call_number = type(self).calls
        deltas = [SimpleNamespace(role="assistant", content=None)]
        for position in range(1, 28):
            selector = (position * call_number + position**2 + 7) % 11
            content = None if selector in {0, 3, 8} else chr(96 + (selector % 26 or 1))
            deltas.append(SimpleNamespace(role=None, content=content))
        type(self).chunks_built += len(deltas)
        return iter(
            [SimpleNamespace(choices=[SimpleNamespace(delta=delta)]) for delta in deltas]
        )


class _FakeOpenAI:
    instances = 0

    def __init__(self, **_kwargs):
        type(self).instances += 1
        self.models = _Models()
        self.chat = SimpleNamespace(completions=_Completions())


class _Retriever:
    calls = 0

    def augmented_context(self, user_query):
        type(self).calls += 1
        stride = sum(ord(char) for char in user_query) % 9 + 1
        return "".join(reversed(user_query[::stride]))


class _QuietLive:
    enters = 0

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        type(self).enters += 1
        return self

    def __exit__(self, *_args):
        return False


class TestChatStartPromptCFG(unittest.TestCase):
    def test_middle_streaming_invocation(self):
        rng = random.Random(7319)
        alphabet = tuple("abcdefghijklmnpqrstuvwxyz")
        questions = [
            " ".join(
                "".join(rng.choice(alphabet) for _ in range(3 + (row + col) % 8))
                for col in range(18 + row % 7)
            )
            for row in range(17)
        ]
        token_limits = [rng.randrange(0, 96) if row % 3 else 0 for row in range(17)]

        _Completions.calls = 0
        _Completions.chunks_built = 0
        _FakeOpenAI.instances = 0
        _Retriever.calls = 0
        _QuietLive.enters = 0

        with (
            patch.object(chat, "OpenAI", _FakeOpenAI),
            patch.object(chat, "http_client", return_value=None),
            patch.object(chat, "Live", _QuietLive),
            patch.object(chat, "create_document_retriever", return_value=_Retriever()),
        ):
            for index, generated_question in enumerate(questions):
                use_retrieval = (index * index + 3) % 5 < 3
                chat.chat_cli(
                    api_base="http://unused.invalid/v1",
                    question=[generated_question],
                    model=f"requested-{index % 6}",
                    context="default",
                    session=None,
                    qq=True,
                    max_tokens=token_limits[index],
                    max_ctx_size=70 + sum(map(ord, generated_question[-8:])) % 75,
                    temperature=0.15 + (index % 5) / 10,
                    backend_type=(
                        chat.backends.LLAMA_CPP
                        if index == len(questions) // 2
                        else "remote"
                    ),
                    rag_enabled=use_retrieval,
                    document_store_uri=None,
                    collection_name=None,
                    embedding_model_path=None,
                    top_k=3 + index % 4,
                    logs_dir=None,
                    vi_mode=bool(index % 2),
                    visible_overflow=bool((index + 1) % 3),
                    params={"api_key": "unused"},
                    no_decoration=index % 4 == 0,
                )

        self.assertEqual(_FakeOpenAI.instances, len(questions))
        self.assertEqual(_Completions.calls, len(questions))
        self.assertGreater(_Completions.chunks_built, len(questions) * 20)
        self.assertGreater(_Retriever.calls, len(questions) // 3)
        self.assertEqual(_QuietLive.enters, len(questions))

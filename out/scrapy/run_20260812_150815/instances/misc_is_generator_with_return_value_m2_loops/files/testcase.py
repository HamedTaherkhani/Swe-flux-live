import random
import unittest
from functools import partial

from scrapy.utils.misc import is_generator_with_return_value


def generator_alpha(*args, **kwargs):
    first = len(args)
    second = len(kwargs)
    third = first + second
    fourth = third * 2
    fifth = fourth - first
    sixth = fifth + second
    seventh = sixth % 7
    eighth = seventh * seventh
    yield eighth


def generator_bravo(*args, **kwargs):
    values = args
    options = kwargs
    width = len(values)
    height = len(options)
    area = width * height
    perimeter = width + height
    diagonal = area + perimeter
    checksum = diagonal ^ width
    marker = checksum % 11
    yield marker
    return None


def generator_charlie(*args, **kwargs):
    payload = kwargs.get("payload", ())
    total = sum(payload)
    span = len(payload)
    pivot = total % (span + 1)
    left = payload[:pivot]
    right = payload[pivot:]
    folded = sum(left) - sum(right)
    normalized = abs(folded)
    quotient = normalized // (span + 1)
    residue = normalized % (span + 1)
    yield quotient
    yield residue


def generator_delta(*args, **kwargs):
    payload = kwargs.get("payload", ())
    accumulator = 0
    for position, value in enumerate(payload):
        if (position + value) % 3:
            accumulator += value ^ position
        else:
            accumulator -= value
    yield accumulator


def generator_echo(*args, **kwargs):
    payload = kwargs.get("payload", ())
    even = [value for value in payload if value % 2 == 0]
    odd = [value for value in payload if value % 2]
    paired = zip(even, reversed(odd))
    scores = [left * 3 - right for left, right in paired]
    baseline = sum(scores)
    adjustment = len(even) - len(odd)
    result = baseline + adjustment
    yield result
    return


def generator_foxtrot(*args, **kwargs):
    marker = kwargs.get("marker", 0)
    one = marker + 1
    two = one * 2
    three = two + marker
    four = three ^ one
    five = four - two
    six = five * three
    seven = six + four
    eight = seven % 97
    nine = eight + five
    ten = nine ^ marker
    yield ten
    return marker or one


def generator_golf(*args, **kwargs):
    payload = kwargs.get("payload", ())
    seed = kwargs.get("marker", 0)
    current = seed
    history = []
    for value in payload:
        current = (current * 17 + value) % 257
        history.append(current)
    selected = history[::2]
    rejected = history[1::2]
    balance = sum(selected) - sum(rejected)
    magnitude = abs(balance)
    yield magnitude
    return magnitude + len(history)


def generator_hotel(*args, **kwargs):
    payload = kwargs.get("payload", ())

    def nested_transform(sequence):
        hidden = [item * item for item in sequence]
        hidden_total = sum(hidden)
        return hidden_total

    start = len(payload)
    stop = sum(payload)
    distance = stop - start
    direction = -1 if distance < 0 else 1
    scaled = distance * direction
    yield scaled


def generator_india(*args, **kwargs):
    payload = kwargs.get("payload", ())
    table = {
        index: (value * (index + 3)) % 101
        for index, value in enumerate(payload)
        if (index ^ value) % 5
    }
    keys = sorted(table)
    values = [table[key] for key in keys]
    low = min(values, default=0)
    high = max(values, default=0)
    spread = high - low
    yield spread


def generator_juliet(*args, **kwargs):
    payload = kwargs.get("payload", ())
    iterator = iter(payload)
    running = kwargs.get("marker", 0)
    consumed = 0
    while True:
        try:
            value = next(iterator)
        except StopIteration:
            break
        running = (running + value * (consumed + 1)) % 4093
        consumed += 1
    yield running
    return None


def generator_kilo(*args, **kwargs):
    payload = kwargs.get("payload", ())
    matrix = []
    for outer, value in enumerate(payload):
        row = []
        for inner in range((outer + value) % 5):
            cell = (value * (inner + 1) + outer) % 89
            row.append(cell)
        matrix.append(row)
    flattened = [cell for row in matrix for cell in row]
    checksum = sum(flattened)
    yield checksum


def generator_lima(*args, **kwargs):
    payload = kwargs.get("payload", ())
    marker = kwargs.get("marker", 0)
    mapping = {}
    for index, value in enumerate(payload):
        bucket = (value + marker + index) % 17
        mapping.setdefault(bucket, []).append(value)
    ordered = sorted(mapping.items())
    subtotals = []
    for bucket, values in ordered:
        subtotal = sum((position + 1) * item for position, item in enumerate(values))
        subtotals.append(bucket ^ subtotal)
    combined = sum(subtotals)
    yield combined
    return combined if combined % 2 else marker


class GeneratorReturnLoopTest(unittest.TestCase):
    def _exercise(self, generator, phrase):
        seed = sum(
            (position + 5) * ord(character)
            for position, character in enumerate(phrase)
        )
        rng = random.Random(seed)
        rolling = rng.randrange(1 << 12)
        payload = []
        for position in range(31 + seed % 19):
            draw = rng.randrange(1 << 15)
            rolling = (rolling * 73 + draw + position * position) % 65521
            if (rolling ^ draw ^ position) % 7:
                payload.append((rolling + draw + position * 11) % 997)
            else:
                payload.append((rolling ^ draw) % 997)

        callback = partial(
            generator,
            *tuple(payload[index] for index in range(seed % 4)),
            payload=tuple(payload),
            marker=rolling,
        )
        result = is_generator_with_return_value(callback)
        self.assertIs(type(result), bool)
        self.assertTrue(callback.func is generator)
        self.assertGreater(len(payload), len(phrase))
        return result

    def test_alpha_straight_line(self):
        self.assertFalse(self._exercise(generator_alpha, "amber-current"))

    def test_bravo_explicit_none(self):
        self.assertFalse(self._exercise(generator_bravo, "birch-signal"))

    def test_charlie_slices(self):
        self.assertFalse(self._exercise(generator_charlie, "cobalt-drift"))

    def test_delta_branching_loop(self):
        self.assertFalse(self._exercise(generator_delta, "dune-vector"))

    def test_echo_comprehensions(self):
        self.assertFalse(self._exercise(generator_echo, "ember-window"))

    def test_foxtrot_valued_return(self):
        self.assertTrue(self._exercise(generator_foxtrot, "frost-cipher"))

    def test_golf_loop_and_return(self):
        self.assertTrue(self._exercise(generator_golf, "grove-pulse"))

    def test_hotel_nested_function(self):
        self.assertFalse(self._exercise(generator_hotel, "harbor-kite"))

    def test_india_dict_comprehension(self):
        self.assertFalse(self._exercise(generator_india, "indigo-quartz"))

    def test_juliet_while_and_try(self):
        self.assertFalse(self._exercise(generator_juliet, "juniper-wave"))

    def test_kilo_nested_loops(self):
        self.assertFalse(self._exercise(generator_kilo, "kelp-orbit"))

    def test_lima_conditional_return(self):
        self.assertTrue(self._exercise(generator_lima, "linen-comet"))

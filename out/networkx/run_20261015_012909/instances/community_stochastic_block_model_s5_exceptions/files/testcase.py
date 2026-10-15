import unittest

import networkx as nx


class TestGaussianPartitionTinyCrossProbability(unittest.TestCase):
    def test_tiny_inter_cluster_probability(self):
        p_in = 0.35
        # A strictly positive but extremely small inter-cluster probability.
        p_out = p_in ** sum(range(9))
        self.assertGreater(p_out, 0.0)
        self.assertLess(p_out, p_in)

        caught = []
        try:
            nx.gaussian_random_partition_graph(
                150, 18, 4, p_in, p_out, directed=False, seed=20261015
            )
        except Exception as exc:  # noqa: BLE001
            caught.append(exc)

        self.assertEqual(len(caught), 1)
        self.assertNotIsInstance(caught[0], nx.NetworkXException)


if __name__ == "__main__":
    unittest.main()

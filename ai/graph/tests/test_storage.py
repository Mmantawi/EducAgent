import unittest

from eduagent_kg.resolution.merger import HierarchicalGraphMerger
from eduagent_kg.storage import Neo4jGraphStore

from test_merge import _fragment, _textbook


class FakeDriver:
    def __init__(self):
        self.calls = []

    def execute_query(self, query, **params):
        self.calls.append((" ".join(query.split()), params))


def _written_relationships(driver):
    return sum(len(p["rows"]) for q, p in driver.calls if "MERGE (source)-[r:" in q)


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.graph, _, _ = HierarchicalGraphMerger().merge([_fragment("s1", "mul")], _textbook())
        self.approved = sum(e.review_status.value == "approved" for e in self.graph.relationships)
        self.total = len(self.graph.relationships) + len(self.graph.candidate_relationships)

    def test_default_import_writes_only_approved_links(self):
        driver = FakeDriver()
        stats = Neo4jGraphStore(driver).import_graph(self.graph)
        self.assertEqual(_written_relationships(driver), self.approved)
        self.assertEqual(stats.relationships_excluded, self.total - self.approved)

    def test_preview_writes_every_link_with_its_review_status(self):
        driver = FakeDriver()
        Neo4jGraphStore(driver).import_graph(self.graph, include_unreviewed=True)
        self.assertEqual(_written_relationships(driver), self.total)
        statuses = {row["properties"]["review_status"] for q, p in driver.calls
                    if "MERGE (source)-[r:" in q for row in p["rows"]}
        self.assertIn("unreviewed", statuses)

    def test_reimport_removes_nodes_that_no_longer_exist(self):
        driver = FakeDriver()
        Neo4jGraphStore(driver).import_graph(self.graph)
        cleanup = [p for q, p in driver.calls if "DETACH DELETE n" in q]
        self.assertEqual(len(cleanup), 1)
        self.assertEqual(set(cleanup[0]["node_ids"]), {n.canonical_id for n in self.graph.nodes})


if __name__ == "__main__":
    unittest.main()

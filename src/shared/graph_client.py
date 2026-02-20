"""Neo4j knowledge graph client for functional test generation context."""

import logging
from neo4j import GraphDatabase

log = logging.getLogger(__name__)


class GraphClient:
    """Thin wrapper around Neo4j driver for querying the code knowledge graph."""

    def __init__(self, uri: str, user: str, password: str):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self._driver.close()

    def check_functional_test_warranted(
        self, symbol_name: str, file_suffix: str
    ) -> dict | None:
        """
        Run Query 0 to determine if a functional test adds value for this symbol.

        Returns a dict with symbol info if warranted, or None if not warranted.
        When None is returned, the reason is logged.
        """
        query = """
        MATCH (f:File)-[:DECLARES]->(s:Symbol {name: $symbol_name})
        WHERE f.path ENDS WITH $file_suffix
        OPTIONAL MATCH (importer:File)-[:IMPORTS_SYMBOL]->(s)
        OPTIONAL MATCH (cls:Symbol {kind:'class'})-[:HAS_METHOD]->(s)
        RETURN
          s.name AS symbol,
          s.kind AS kind,
          s.fqn AS fqn,
          count(DISTINCT importer) AS importer_count,
          cls.name AS parent_class
        """
        with self._driver.session() as session:
            result = session.run(
                query, symbol_name=symbol_name, file_suffix=file_suffix
            )
            record = result.single()

        if record is None:
            log.info(
                "Symbol '%s' not found in graph (file suffix: %s) — skipping functional test",
                symbol_name, file_suffix,
            )
            return None

        kind = record["kind"]
        importer_count = record["importer_count"]
        parent_class = record["parent_class"]

        if kind == "constant":
            log.info("Symbol '%s' is a constant — skipping functional test", symbol_name)
            return None

        if importer_count == 0 and parent_class is None:
            log.info(
                "Symbol '%s' is a standalone %s with no importers — skipping functional test",
                symbol_name, kind,
            )
            return None

        if importer_count == 0:
            # It's a method on a class — check if the class itself is imported
            class_check_query = """
            MATCH (f:File)-[:DECLARES]->(cls:Symbol {name: $class_name, kind: 'class'})
            WHERE f.path ENDS WITH $file_suffix
            OPTIONAL MATCH (importer:File)-[:IMPORTS_SYMBOL]->(cls)
            RETURN count(DISTINCT importer) AS class_importer_count
            """
            with self._driver.session() as session:
                class_result = session.run(
                    class_check_query,
                    class_name=parent_class,
                    file_suffix=file_suffix,
                )
                class_record = class_result.single()

            if class_record is None or class_record["class_importer_count"] == 0:
                log.info(
                    "Symbol '%s' is a method on class '%s' which has no importers — skipping functional test",
                    symbol_name, parent_class,
                )
                return None

        return {
            "symbol": record["symbol"],
            "kind": kind,
            "fqn": record["fqn"],
            "importer_count": importer_count,
            "parent_class": parent_class,
        }

    def get_integration_context(self, symbol_name: str, file_suffix: str) -> dict:
        """
        Run Queries 1-4 to gather full integration context for functional test generation.

        Returns a dict with keys: entry_points, class_interface, import_chain, file_context.
        """
        context = {}

        with self._driver.session() as session:
            # QUERY 1 — Entry points that reach the mutation target
            q1 = """
            MATCH (f:File)-[:DECLARES]->(s:Symbol {name: $symbol_name})
            WHERE f.path ENDS WITH $file_suffix
            MATCH (direct:File)-[:IMPORTS_SYMBOL]->(s)
            MATCH (direct)-[:DECLARES]->(caller:Symbol)
            WHERE caller.kind IN ['function', 'method']
            OPTIONAL MATCH (top:File)-[:IMPORTS_SYMBOL]->(caller)
            OPTIONAL MATCH (top)-[:DECLARES]->(entry:Symbol)
            WHERE entry.kind IN ['function', 'method']
            RETURN
              s.name AS mutation_target,
              s.fqn AS target_fqn,
              caller.name AS direct_caller,
              caller.fqn AS direct_caller_fqn,
              direct.path AS direct_caller_file,
              entry.name AS top_level_entry,
              entry.fqn AS top_entry_fqn,
              top.path AS top_entry_file
            """
            records = list(
                session.run(q1, symbol_name=symbol_name, file_suffix=file_suffix)
            )
            context["entry_points"] = [dict(r) for r in records]

            # QUERY 2 — Public interface of the class containing the mutation target
            q2 = """
            MATCH (cls:Symbol {kind:'class'})-[:HAS_METHOD]->(target:Symbol {name: $symbol_name})
            MATCH (cls)-[:HAS_METHOD]->(public:Symbol)
            WHERE NOT public.name STARTS WITH '_'
            OPTIONAL MATCH (cls)-[:EXTENDS]->(parent:Symbol)
            RETURN
              cls.name AS class_name,
              cls.fqn AS class_fqn,
              cls.bases AS bases,
              target.name AS mutation_target,
              target.params AS target_params,
              target.docstring AS target_docstring,
              collect(DISTINCT {name: public.name, params: public.params, docstring: public.docstring}) AS public_methods,
              collect(DISTINCT parent.name) AS parent_classes
            """
            records = list(
                session.run(q2, symbol_name=symbol_name)
            )
            context["class_interface"] = [dict(r) for r in records]

            # QUERY 3 — Full integration chain from target to importers
            q3 = """
            MATCH (f:File)-[:DECLARES]->(target:Symbol {name: $symbol_name})
            WHERE f.path ENDS WITH $file_suffix
            MATCH (f)<-[:IMPORTS]-(importer1:File)
            OPTIONAL MATCH (importer1)<-[:IMPORTS]-(importer2:File)
            RETURN
              target.name AS mutation_target,
              f.path AS target_file,
              collect(DISTINCT importer1.path) AS direct_importers,
              collect(DISTINCT importer2.path) AS second_hop_importers
            """
            records = list(
                session.run(q3, symbol_name=symbol_name, file_suffix=file_suffix)
            )
            context["import_chain"] = [dict(r) for r in records]

            # QUERY 4 — File-level context for the target's file
            q4 = """
            MATCH (f:File) WHERE f.path ENDS WITH $file_suffix
            OPTIONAL MATCH (f)-[r:IMPORTS]->(imported:File)
            OPTIONAL MATCH (f)-[:DEPENDS_ON]->(ext:ExternalDep)
            OPTIONAL MATCH (user:File)-[:IMPORTS_SYMBOL]->(sym:Symbol)<-[:DECLARES]-(f)
            WITH f,
              collect(DISTINCT {file: imported.path, symbols: r.symbols}) AS internal_imports,
              collect(DISTINCT ext.name) AS external_deps,
              collect(DISTINCT user.path) AS imported_by
            RETURN
              f.path AS file,
              internal_imports,
              external_deps,
              imported_by
            """
            records = list(
                session.run(q4, file_suffix=file_suffix)
            )
            context["file_context"] = [dict(r) for r in records]

        return context

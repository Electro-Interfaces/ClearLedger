"""Match-only controls: no ASGI dispatch, endpoint execution or lifespan."""
import importlib.util
from pathlib import Path
import unittest
import uuid

from fastapi import FastAPI
from starlette.routing import Match, Mount, Route, WebSocketRoute


SPEC = importlib.util.spec_from_file_location("overlap_triage", Path(__file__).resolve().parents[1] / "triage-route-overlaps.py")
triage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(triage)


async def never_execute(*args, **kwargs):
    raise AssertionError("endpoint_executed")


class MatchControls(unittest.TestCase):
    def scope(self, path="/items/summary", method="GET", protocol="http", root_path=""):
        return triage.synthetic_scope(path, method, protocol, root_path)

    def test_partial_does_not_win_over_later_full(self):
        routes = [Route("/items/{item_id}", never_execute, methods=["POST"]),
                  Route("/items/summary", never_execute, methods=["GET"])]
        result = triage.first_full(routes, self.scope())
        self.assertIs(result["route"], routes[1])
        self.assertEqual(result["partials"], [[0]])
        self.assertEqual(result["examined"], 2)

    def test_parameter_first_shadow_and_adversarial_earlier_route(self):
        pair = [Route("/items/{item_id}", never_execute), Route("/items/summary", never_execute)]
        self.assertIs(triage.first_full(pair, self.scope())["route"], pair[0])
        earlier = Route("/{rest:path}", never_execute)
        result = triage.first_full([earlier, *pair], self.scope())
        self.assertIs(result["route"], earlier)
        self.assertEqual(result["order"], [0])
        self.assertEqual(result["pathParams"], {"rest": "items/summary"})

    def test_recursive_mount_root_path_and_scope_at(self):
        leaf = Route("/summary", never_execute)
        nested = Mount("/v1", routes=[leaf])
        outer = Mount("/api", routes=[nested])
        app = FastAPI()
        app.router.routes = [outer]
        scope = self.scope("/edge/api/v1/summary", root_path="/edge")
        result = triage.first_full(app.routes, scope)
        self.assertIs(result["route"], leaf)
        self.assertEqual(result["order"], [0, 0, 0])
        self.assertEqual(result["examined"], 3)
        self.assertEqual([m["childRootPath"] for m in result["mounts"]], ["/edge/api", "/edge/api/v1"])
        self.assertIs(triage.route_at(app, [0, 0, 0]), leaf)
        child_scope = triage.scope_at(app, [0, 0, 0], scope)
        self.assertEqual(leaf.matches(child_scope)[0], Match.FULL)
        self.assertEqual(child_scope["root_path"], "/edge/api/v1")

    def test_first_full_mount_commits_without_sibling_fallthrough(self):
        routes = [Mount("/items", routes=[Route("/other", never_execute)]),
                  Route("/items/summary", never_execute)]
        result = triage.first_full(routes, self.scope())
        self.assertIsNone(result["route"])
        self.assertEqual(result["examined"], 2)  # outer mount + child; sibling never examined
        self.assertEqual(result["mounts"][0]["order"], [0])

    def test_wrong_method_and_protocol(self):
        routes = [WebSocketRoute("/items/{item_id}", never_execute),
                  Route("/items/{item_id}", never_execute, methods=["POST"]),
                  Route("/items/summary", never_execute, methods=["GET"])]
        result = triage.first_full(routes, self.scope())
        self.assertIs(result["route"], routes[2])
        self.assertEqual(result["partials"], [[1]])
        self.assertIs(triage.first_full(routes, self.scope(protocol="websocket"))["route"], routes[0])
        self.assertIsNone(triage.first_full(routes[1:], self.scope(method="DELETE"))["route"])

    def test_convertors_and_annotations_have_different_roles(self):
        routes = [Route("/items/{item_id:uuid}", never_execute), Route("/items/summary", never_execute)]
        self.assertIs(triage.first_full(routes, self.scope())["route"], routes[1])
        value = "11111111-1111-4111-8111-111111111111"
        result = triage.first_full(routes, self.scope("/items/" + value))
        self.assertEqual(result["pathParams"], {"item_id": uuid.UUID(value)})
        app = FastAPI()

        @app.get("/items/{item_id}")
        async def annotated(item_id: uuid.UUID):
            raise AssertionError("endpoint_executed")

        @app.get("/items/summary")
        async def literal():
            raise AssertionError("endpoint_executed")

        result = triage.first_full(app.routes, self.scope())
        self.assertIs(result["route"].endpoint, annotated)
        self.assertEqual(result["pathParams"], {"item_id": "summary"})

    def test_literal_witness_requires_full_in_intended_method(self):
        literal = Route("/items/summary", never_execute, methods=["POST"])
        self.assertEqual(literal.matches(self.scope())[0], Match.PARTIAL)
        self.assertEqual(literal.matches(self.scope(method="POST"))[0], Match.FULL)
        self.assertEqual(literal.matches(self.scope(protocol="websocket"))[0], Match.NONE)


if __name__ == "__main__":
    unittest.main()

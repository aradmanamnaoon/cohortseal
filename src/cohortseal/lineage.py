"""Derived-case lineage graph checks for patches, crops, and augmentation outputs."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable, Mapping

from cohortseal.models import CaseRecord, Finding, Severity


@dataclass(frozen=True, slots=True)
class LineageEdge:
    """Directed relationship from a source case to one derived case."""

    parent_case_id: str
    child_case_id: str
    transform: str | None = None


@dataclass(frozen=True, slots=True)
class LineageReport:
    """Graph validation result, including deterministic topological order."""

    edges: tuple[LineageEdge, ...]
    topological_order: tuple[str, ...]
    findings: tuple[Finding, ...]

    @property
    def passed(self) -> bool:
        """Return whether the graph is acyclic and has no group boundary violations."""
        return not any(item.severity == Severity.ERROR for item in self.findings)

    def to_dict(self) -> dict[str, object]:
        """Return graph statistics without exposing paths or patient tokens."""
        return {
            "passed": self.passed,
            "node_count": len(self.topological_order),
            "edge_count": len(self.edges),
            "topological_order": list(self.topological_order),
            "findings": [item.model_dump(mode="json") for item in self.findings],
        }


class LineageGraph:
    """Validate parent-child metadata and ensure derived samples stay group-safe."""

    def __init__(self, *, parent_field: str = "parent_case_id", transform_field: str = "transform") -> None:
        if not parent_field or not transform_field:
            raise ValueError("metadata field names must not be blank")
        self.parent_field = parent_field
        self.transform_field = transform_field

    def audit(self, cases: Iterable[CaseRecord]) -> LineageReport:
        """Build a directed acyclic graph from metadata and validate lineage constraints."""
        rows = tuple(cases)
        by_id = {row.case_id: row for row in rows}
        findings: list[Finding] = []
        adjacency: dict[str, set[str]] = defaultdict(set)
        indegree = {key: 0 for key in by_id}
        edges: list[LineageEdge] = []
        for child in rows:
            parent = child.metadata.get(self.parent_field)
            if parent is None:
                continue
            parent_id = str(parent).strip()
            if not parent_id:
                findings.append(Finding(code="EMPTY_LINEAGE_PARENT", severity=Severity.ERROR,
                                        message="Derived case has an empty parent case reference.",
                                        case_ids=(child.case_id,)))
                continue
            if parent_id not in by_id:
                findings.append(Finding(code="MISSING_LINEAGE_PARENT", severity=Severity.ERROR,
                                        message="Derived case references a parent absent from this manifest.",
                                        case_ids=(child.case_id,), evidence={"parent_reference_present": True}))
                continue
            if parent_id == child.case_id:
                findings.append(Finding(code="SELF_LINEAGE_EDGE", severity=Severity.ERROR,
                                        message="A case cannot be its own lineage parent.",
                                        case_ids=(child.case_id,)))
                continue
            if child.patient_id != by_id[parent_id].patient_id:
                findings.append(Finding(code="LINEAGE_PATIENT_MISMATCH", severity=Severity.ERROR,
                                        message="Derived and parent cases have different patient groups.",
                                        case_ids=tuple(sorted((child.case_id, parent_id)))))
            parent_split = by_id[parent_id].split
            if child.split and parent_split and child.split != parent_split:
                findings.append(Finding(code="LINEAGE_CROSS_SPLIT", severity=Severity.ERROR,
                                        message="Derived case and parent case are assigned to different splits.",
                                        case_ids=tuple(sorted((child.case_id, parent_id))),
                                        evidence={"split_mismatch": True}))
            adjacency[parent_id].add(child.case_id)
            indegree[child.case_id] += 1
            transform = child.metadata.get(self.transform_field)
            edges.append(LineageEdge(parent_id, child.case_id, str(transform) if transform is not None else None))
        order = self._topological_sort(indegree, adjacency)
        if len(order) != len(by_id):
            cyclic = tuple(sorted(case_id for case_id, degree in indegree.items() if degree > 0))
            findings.append(Finding(code="LINEAGE_CYCLE", severity=Severity.ERROR,
                                    message="Lineage graph contains a cycle.", case_ids=cyclic))
        return LineageReport(tuple(sorted(edges, key=lambda edge: (edge.parent_case_id, edge.child_case_id))),
                             tuple(order), tuple(findings))

    @staticmethod
    def _topological_sort(indegree: Mapping[str, int], adjacency: Mapping[str, set[str]]) -> list[str]:
        """Use deterministic Kahn sorting and return all acyclically reachable nodes."""
        current = {key: value for key, value in indegree.items()}
        ready = deque(sorted(key for key, degree in current.items() if degree == 0))
        output: list[str] = []
        while ready:
            node = ready.popleft()
            output.append(node)
            for child in sorted(adjacency.get(node, set())):
                current[child] -= 1
                if current[child] == 0:
                    ready.append(child)
        return output

    def ancestors(self, case_id: str, edges: Iterable[LineageEdge]) -> tuple[str, ...]:
        """Return all source ancestors of a node in deterministic breadth-first order."""
        reverse: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            reverse[edge.child_case_id].add(edge.parent_case_id)
        seen: set[str] = set()
        queue = deque(sorted(reverse.get(case_id, set())))
        while queue:
            parent = queue.popleft()
            if parent in seen:
                continue
            seen.add(parent)
            queue.extend(sorted(reverse.get(parent, set()) - seen))
        return tuple(sorted(seen))


def lineage_edges_from_mapping(payload: Iterable[Mapping[str, object]]) -> tuple[LineageEdge, ...]:
    """Parse a list of explicit lineage edge mappings with strict identifiers."""
    result: list[LineageEdge] = []
    for index, item in enumerate(payload):
        parent = str(item.get("parent_case_id", "")).strip()
        child = str(item.get("child_case_id", "")).strip()
        if not parent or not child:
            raise ValueError(f"lineage edge {index} requires parent_case_id and child_case_id")
        transform = item.get("transform")
        result.append(LineageEdge(parent, child, str(transform) if transform is not None else None))
    return tuple(result)


def check_edges_against_cases(edges: Iterable[LineageEdge], cases: Iterable[CaseRecord]) -> tuple[Finding, ...]:
    """Validate externally stored edges against a manifest's case/split assignments."""
    by_id = {item.case_id: item for item in cases}
    findings: list[Finding] = []
    for edge in edges:
        parent, child = by_id.get(edge.parent_case_id), by_id.get(edge.child_case_id)
        if parent is None or child is None:
            findings.append(Finding(code="LINEAGE_ENDPOINT_MISSING", severity=Severity.ERROR,
                                    message="Lineage edge endpoint is not present in the manifest.",
                                    evidence={"parent_present": parent is not None, "child_present": child is not None}))
            continue
        if parent.patient_id != child.patient_id:
            findings.append(Finding(code="LINEAGE_PATIENT_MISMATCH", severity=Severity.ERROR,
                                    message="Lineage edge crosses patient groups.",
                                    case_ids=tuple(sorted((parent.case_id, child.case_id)))))
        if parent.split and child.split and parent.split != child.split:
            findings.append(Finding(code="LINEAGE_CROSS_SPLIT", severity=Severity.ERROR,
                                    message="Lineage edge crosses data partitions.",
                                    case_ids=tuple(sorted((parent.case_id, child.case_id)))))
    return tuple(findings)

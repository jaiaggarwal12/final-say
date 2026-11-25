import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.restore_graph_checkpoint import restore_checkpoint, verify_checkpoint
from scripts.run_graph_pipeline import make_archive
from src.vulngnn.graphs.run_cpg_batches import (
    require_deterministic_replay,
    resumable_batch,
    write_completion_marker,
)


def toy_workset(root: Path) -> tuple[Path, pd.DataFrame]:
    workset = root / "workset"
    (workset / "graphs").mkdir(parents=True)
    (workset / "logs").mkdir()
    manifest = pd.DataFrame([{
        "uid": "f_" + "a" * 32, "norm_hash": "a" * 32, "ext": ".c",
        "batch_id": 0, "vul": 1, "project_g": "toy", "commit_id": "c1",
        "cve_id": "", "cwe_id": "", "split_within": "test",
        "split_cross": "test", "near_dup_cross": False,
        "use_train_within": False, "use_train_cross": False,
        "use_eval_within": True, "use_eval_cross": True,
    }])
    manifest.to_csv(workset / "manifest.csv", index=False)
    (workset / "coverage_by_project.csv").write_text("setting,role,project_g,vul,total,selected,coverage\n")
    (workset / "workset_metadata.json").write_text(json.dumps({"seed": 42}) + "\n")
    graph = {
        "uid": "f_" + "a" * 32, "norm_hash": "a" * 32, "label": 1,
        "project_g": "toy", "split_within": "test", "split_cross": "test",
        "near_dup_cross": False, "use_train_within": False, "use_train_cross": False,
        "use_eval_within": True, "use_eval_cross": True, "max_nodes": 500,
        "nodes": [{"type": "METHOD", "code": "f", "code_truncated": False, "line": 1}],
        "edges": [], "edge_types": ["AST", "CFG", "REACHING_DEF", "CDG"],
        "original_nodes": 1, "nodes_dropped": 0, "truncated": False,
    }
    graph_path = workset / "graphs/batch_00000.jsonl"
    graph_path.write_text(json.dumps(graph, separators=(",", ":")) + "\n")
    stats = manifest.drop(columns=["ext", "batch_id", "commit_id", "cve_id", "cwe_id"]).copy()
    stats["status"] = "ok"
    stats["failure_reason"] = ""
    stats["max_nodes"] = 500
    stats["nodes"] = 1
    stats["original_nodes"] = 1
    stats["nodes_dropped"] = 0
    stats["edges"] = 0
    stats["truncated"] = False
    stats_path = workset / "graphs/batch_00000_stats.csv"
    stats.to_csv(stats_path, index=False)
    (workset / "graphs/coverage.csv").write_text("uid,status\n" + stats.iloc[0].uid + ",ok\n")
    (workset / "graphs/kaggle_coverage_by_class_extension.csv").write_text(
        "label,extension,functions,graphs,coverage\nSafe,C,1,1,1.0\n")
    (workset / "graphs/stage_timings.csv").write_text("batch_id,functions,status\n0,1,complete\n")
    (workset / "graphs/audit_summary.json").write_text(json.dumps({"complete": True}) + "\n")
    (workset / "logs/batch_00000_attempt_001.log").write_text("toy log\n")
    write_completion_marker(stats_path, graph_path, manifest, 500)
    return workset, manifest


class ResumeIntegrityTests(unittest.TestCase):
    def test_only_hash_valid_manifest_matching_batch_is_resumed(self):
        with tempfile.TemporaryDirectory() as directory:
            workset, manifest = toy_workset(Path(directory))
            stats_path = workset / "graphs/batch_00000_stats.csv"
            graph_path = workset / "graphs/batch_00000.jsonl"
            before = hashlib.sha256(graph_path.read_bytes()).hexdigest()
            self.assertIsNotNone(resumable_batch(stats_path, graph_path, manifest, 500))
            self.assertEqual(before, hashlib.sha256(graph_path.read_bytes()).hexdigest())
            candidate = Path(directory) / "rerun.jsonl"
            candidate.write_bytes(graph_path.read_bytes())
            require_deterministic_replay(graph_path, candidate)
            candidate.write_text("different output\n")
            with self.assertRaisesRegex(RuntimeError, "deterministic replay changed"):
                require_deterministic_replay(graph_path, candidate)

            altered = manifest.copy()
            altered.loc[0, "project_g"] = "different"
            self.assertIsNone(resumable_batch(stats_path, graph_path, altered, 500))

            graph_path.write_text(graph_path.read_text() + "\n")
            self.assertIsNone(resumable_batch(stats_path, graph_path, manifest, 500))

    def test_checkpoint_round_trip_and_corruption_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workset, _ = toy_workset(root)
            archive = root / "graphs-through-01.tar.gz"
            make_archive(workset, archive)
            verified, manifest = verify_checkpoint(archive, workset)
            verified.close()
            self.assertEqual(manifest["schema_version"], 1)
            self.assertIn("graphs/kaggle_coverage_by_class_extension.csv", manifest["files"])

            restore_target = root / "restored"
            restore_target.mkdir()
            for name in ("manifest.csv", "coverage_by_project.csv", "workset_metadata.json"):
                (restore_target / name).write_bytes((workset / name).read_bytes())
            restore_checkpoint(archive, restore_target)
            restored_graph = restore_target / "graphs/batch_00000.jsonl"
            self.assertEqual(restored_graph.read_bytes(),
                             (workset / "graphs/batch_00000.jsonl").read_bytes())
            self.assertEqual(
                (restore_target / "graphs/kaggle_coverage_by_class_extension.csv").read_bytes(),
                (workset / "graphs/kaggle_coverage_by_class_extension.csv").read_bytes(),
            )
            self.assertTrue((restore_target / "graphs/batch_00000.complete.json").is_file())

            conflict_target = root / "conflict"
            conflict_target.mkdir()
            for name in ("manifest.csv", "coverage_by_project.csv", "workset_metadata.json"):
                (conflict_target / name).write_bytes((workset / name).read_bytes())
            stale_graph = conflict_target / "graphs/batch_00001.jsonl"
            stale_graph.parent.mkdir(parents=True)
            stale_graph.write_text("stale output\n")
            with self.assertRaisesRegex(ValueError, "conflict with this checkpoint"):
                restore_checkpoint(archive, conflict_target)
            self.assertFalse((conflict_target / "graphs/batch_00000.jsonl").exists())
            self.assertEqual(stale_graph.read_text(), "stale output\n")

            archive.write_bytes(archive.read_bytes() + b"corrupt")
            with self.assertRaises(ValueError):
                verify_checkpoint(archive, restore_target)


if __name__ == "__main__":
    unittest.main()

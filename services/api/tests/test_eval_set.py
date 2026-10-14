"""独立评测集（seed/eval）的读取与评测程序。完整数字见 docs/independent-eval.md。"""
import json
from pathlib import Path

import pytest

from butler.models import Doc
from butler.redteam import eval_set as E


def test_dataset_files_have_the_promised_shape():
    chains, normal, inj = E.load("chains"), E.load("normal"), E.load("injections")
    assert (len(chains), len(normal), len(inj)) == (60, 200, 140)
    assert len({c["event_type"] for c in chains}) == 20
    assert {f["link"] for c in chains for f in c["fragments"]} <= {"alias", "none"}
    assert sum(i["malicious"] for i in inj) == 100 and len({i["technique"] for i in inj if i["malicious"]}) == 10


def test_registered_keywords_never_include_the_hand_written_paraphrases():
    for c in E.load("chains"):
        kws = E.keywords_from(c["conclusion"])
        assert kws and not any(k in c["paraphrases"] for k in kws)


def test_perfect_inference_fires_only_when_all_fragments_are_in_context():
    chains = E.load("chains")[:2]
    docs, _ = E.chain_world(chains)
    frags = [d for d in docs if d.id.startswith("f:c01:")]
    gen = E.PerfectInference(chains)
    assert not any(p in gen("q", frags[:-1]) for p in chains[0]["paraphrases"])
    assert any(p in gen("q", frags) for p in chains[0]["paraphrases"])
    assert E.exposed("\n".join(f["text"] for f in chains[0]["fragments"]), chains[0])


@pytest.mark.skipif(not (E.CORPUS / "acquisitions").exists(), reason="先运行 scripts/fetch_eval_handbook.py 下载手册原文")
def test_harness_runs_end_to_end_on_a_small_slice(tmp_path):
    out = tmp_path / "r.json"
    assert E.main(["--limit", "3", "--out", str(out)]) == 0
    r = json.loads(out.read_text())
    assert r["chains_natural"]["butler"]["leak"] == 0.0           # 人工登记前提时，依赖闭包不放过
    assert r["chains_oracle"]["doc"]["leak"] >= r["chains_oracle"]["butler"]["leak"]
    assert "override" in r["injections"]

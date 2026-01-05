from orchestrator.phase1 import collect_document


def test_orchestrator_collects_detran():
    out = collect_document(
        "tests/fixtures/detranaberta.pdf",
        document_type="detran_sc",
        context={"consulta": "aberta"},
    )

    assert out["document_type"] == "detran_sc"
    assert "data" in out
    assert "debug" in out["data"]

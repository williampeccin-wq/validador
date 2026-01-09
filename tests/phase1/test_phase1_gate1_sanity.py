from orchestrator.phase1 import start_case, collect_document, case_status


def test_phase1_gate1_inventory():
    case_id = start_case()

    st0 = case_status(case_id)
    assert st0.is_complete is False
    assert "proposta_daycoval" in st0.missing
    assert "cnh" in st0.missing

    # Ajuste os caminhos se seus fixtures tiverem nomes diferentes
    collect_document(
        case_id,
        "tests/fixtures/andersonsantos.pdf",
        document_type="proposta_daycoval",
    )

    st1 = case_status(case_id)
    assert st1.is_complete is False
    assert "cnh" in st1.missing

    collect_document(
        case_id,
        "tests/fixtures/CNH DIGITAL.pdf",
        document_type="cnh",
    )

    st2 = case_status(case_id)
    assert st2.is_complete is True

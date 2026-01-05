from __future__ import annotations

from validators.phase2.proposta_cnh_validator import build_proposta_cnh_report


def test_phase2_proposta_cnh_report_equal_fields():
    case_id = "CASE-TEST-001"

    proposta = {
        "cpf": "057.750.729-01",
        "nome_financiado": "Anderson Santos de Barros",
        "data_nascimento": "12/07/1987",
    }

    cnh = {
        "cpf": "05775072901",
        "nome": "ANDERSON  SANTOS  DE  BARROS",
        "data_nascimento": "1987-07-12",
    }

    report = build_proposta_cnh_report(
        case_id=case_id,
        proposta_data=proposta,
        cnh_data=cnh,
    )

    assert report["case_id"] == case_id
    assert report["validator"] == "proposta_vs_cnh"
    assert report["summary"]["total_fields"] >= 3

    # Deve listar como equal os 3 campos básicos
    equal_fields = {x["field"] for x in report["sections"]["equal"]}
    assert "cpf" in equal_fields
    assert "nome" in equal_fields
    assert "data_nascimento" in equal_fields

    # Não pode "decidir" aprovado/reprovado
    assert "approved" not in report
    assert "rejected" not in report
    assert "decision" not in report


def test_phase2_proposta_cnh_report_divergence_and_missing():
    case_id = "CASE-TEST-002"

    proposta = {
        "cpf": "11122233344",
        "nome_financiado": "Fulano de Tal",
        "data_nascimento": "01/01/1990",
    }

    cnh = {
        "cpf": "11122233344",
        "nome": "Fulano de Tal",
        # data_nascimento ausente na CNH
    }

    report = build_proposta_cnh_report(
        case_id=case_id,
        proposta_data=proposta,
        cnh_data=cnh,
    )

    # cpf e nome iguais
    equal_fields = {x["field"] for x in report["sections"]["equal"]}
    assert "cpf" in equal_fields
    assert "nome" in equal_fields

    # data_nascimento deve cair em missing (CNH ausente)
    missing_fields = {x["field"] for x in report["sections"]["missing"]}
    assert "data_nascimento" in missing_fields

    # Não bloquear: relatório sempre existe
    assert isinstance(report, dict)
    assert report["summary"]["missing"] >= 1


def test_phase2_report_is_explainable_structure():
    case_id = "CASE-TEST-003"

    proposta = {"cpf": "123.456.789-00"}
    cnh = {"cpf": "12345678900"}

    report = build_proposta_cnh_report(
        case_id=case_id,
        proposta_data=proposta,
        cnh_data=cnh,
    )

    item = next(x for x in report["sections"]["equal"] if x["field"] == "cpf")
    assert "proposta" in item and "cnh" in item
    assert "raw" in item["proposta"] and "normalized" in item["proposta"]
    assert "raw" in item["cnh"] and "normalized" in item["cnh"]
    assert item["status"] in ("equal", "different", "missing", "not_comparable")
    assert isinstance(item["explain"], str) and len(item["explain"]) > 0

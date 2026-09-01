from collections import defaultdict
from decimal import Decimal

MONTHS = {
    "Janeiro": 1, "Fevereiro": 2, "Março": 3, "Abril": 4,
    "Maio": 5, "Junho": 6, "Julho": 7, "Agosto": 8,
    "Setembro": 9, "Outubro": 10, "Novembro": 11, "Dezembro": 12,
}


def competence_key(value):
    month, _, year = value.partition(" de ")
    return int(year), MONTHS.get(month, 99)


def organize_records(records):
    lookup = {record.number: record for record in records}
    for record in records:
        record.effective = True
        record.note = (
            "Saldo inicial derivado do Pedido de Restituição"
            if record.values_inferred
            else ""
        )
    for record in records:
        if record.is_amending and record.amended_number in lookup:
            replaced = lookup[record.amended_number]
            replaced.effective = False
            replaced.note = f"Substituído por {record.number}"
    ordered = sorted(
        records,
        key=lambda record: (
            competence_key(record.competence),
            record.transmission_date,
            -(
                record.original_credit_at_delivery
                or record.refundable_credit
                or Decimal("0")
            ),
            record.number,
        ),
    )
    day_groups = defaultdict(list)
    for record in ordered:
        if record.effective:
            day_groups[(record.competence, record.transmission_date)].append(record)
    for day_records in day_groups.values():
        for previous, current in zip(day_records, day_records[1:]):
            if current.original_credit_at_delivery is None:
                continue
            difference = previous.original_credit_balance - current.original_credit_at_delivery
            if difference > Decimal("0.02"):
                formatted = f"{difference:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                warning = f"Possível elo não localizado: diferença de R$ {formatted}"
                current.note = f"{current.note}; {warning}" if current.note else warning
    return ordered


def deduplicate_records(records):
    """Mantém uma ocorrência por número e informa arquivos repetidos."""
    unique = {}
    warnings = []
    for record in records:
        existing = unique.get(record.number)
        if existing is None:
            unique[record.number] = record
            continue
        warnings.append(
            f"PER/DCOMP {record.number} repetido em {record.source_file}; "
            f"mantido o arquivo {existing.source_file}"
        )
    return list(unique.values()), warnings


def competence_summary(records):
    groups = defaultdict(list)
    for record in organize_records(records):
        groups[record.competence].append(record)

    output = []
    for competence, group in groups.items():
        effective = [record for record in group if record.effective]
        latest = max(effective, key=lambda record: (record.transmission_date, record.number))
        initial = next(
            (record.refundable_credit for record in effective if record.refundable_credit is not None),
            latest.original_credit_at_delivery,
        )
        output.append(
            {
                "competence": competence,
                "initial_credit": initial,
                "current_balance": latest.original_credit_balance,
                "used_credit": (initial - latest.original_credit_balance) if initial is not None else None,
                "status": (
                    "Crédito zerado"
                    if latest.original_credit_balance == Decimal("0")
                    else "Crédito disponível"
                ),
                "latest_transmission": latest.transmission_date,
                "latest_number": latest.number,
                "record_count": len(group),
            }
        )
    return sorted(output, key=lambda row: competence_key(row["competence"]))

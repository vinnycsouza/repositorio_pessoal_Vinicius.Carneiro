from collections import defaultdict
from decimal import Decimal

def organize_records(records):
    lookup = {r.number:r for r in records}
    for r in records:
        if r.is_amending and r.amended_number in lookup:
            lookup[r.amended_number].effective = False
            lookup[r.amended_number].note = f"Substituído por {r.number}"
    return sorted(records, key=lambda r:(r.competence, r.transmission_date, r.number))

def competence_summary(records):
    groups = defaultdict(list)
    for r in organize_records(records): groups[r.competence].append(r)
    output=[]
    for competence, group in groups.items():
        valid=[r for r in group if r.effective]; latest=max(valid,key=lambda r:(r.transmission_date,r.number))
        output.append({"competence":competence,"initial_credit":next((r.refundable_credit for r in valid if r.refundable_credit is not None),None),"current_balance":latest.original_credit_balance,"status":"Crédito esgotado" if latest.original_credit_balance==Decimal("0") else "Crédito disponível","latest_transmission":latest.transmission_date,"latest_number":latest.number,"record_count":len(group)})
    return sorted(output,key=lambda x:x["latest_transmission"])

def reconcile(individual, consolidated):
    left={r.number:r for r in individual}; right={r.number:r for r in consolidated}; rows=[]
    for number in sorted(set(left)|set(right)):
        a,b=left.get(number),right.get(number); issues=[]
        if not a: issues.append("Ausente nos individuais")
        if not b: issues.append("Ausente no consolidado")
        if a and b and a.original_credit_used!=b.amount_used: issues.append("Valor divergente")
        rows.append({"PER/DCOMP":number,"Competência":a.competence if a else "Não informada","Transmissão":(a.transmission_date if a else b.transmission_date).strftime("%d/%m/%Y"),"Situação":b.status if b else "Não informada","Valor utilizado":a.original_credit_used if a else b.amount_used,"Saldo":a.original_credit_balance if a else None,"Resultado":"; ".join(issues) or "Conciliado"})
    return rows


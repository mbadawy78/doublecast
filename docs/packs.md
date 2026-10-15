# Industry packs

Packs add patterns for the identifiers each industry uses. They live in `src/doublecast/packs/*.yaml`, and adding one is a good first contribution.

| Pack | Catches |
|---|---|
| `fmcg` | EAN-13 barcodes (checksum), SKU / item / article codes, lot and batch numbers, purchase and sales orders, delivery notes (δελτία αποστολής, Lieferschein, DDT, albarán), Greek vehicle plates |
| `finance` | Invoice numbers (τιμολόγια, Rechnung, facture, fattura, factura), account numbers, SWIFT/BIC, contract, cheque and loan references |
| `hr` | Employee and staff numbers, ΕΦΚΑ ΑΜΑ, payroll references, dates of birth |
| `legal_health` | Case and file numbers, court decisions, patient and medical-record IDs, insurance policies, prescriptions |

Always on (no pack needed): emails, phones, IBANs, payment cards, secrets, Greek ΑΦΜ/ΑΜΚΑ/ΑΔΤ, EU VAT numbers, Spanish DNI/NIE, Italian codice fiscale, French NIR, German Steuer-ID, passports, IPv4.

**Legal & health, deliberately:** diagnoses and clinical details are *not* swapped. Changing them would change the meaning of the question. The pack protects identity (names, IDs, dates of birth) instead.

## Writing a pattern

```yaml
patterns:
  - name: delivery_note
    category: ID
    regex: '\b(?:delivery note|δελτίο αποστολής|Lieferschein)\s*{MARKER}?\s*[:#]?\s*([A-Z0-9][A-Z0-9/-]{3,})'
    group: 1                # which capture group is the value
    validator: ean13        # optional: luhn | iban | afm | amka | ean13 | dni
    context: [αφμ, vat]     # optional: one of these words must appear nearby
    window: 40              # how far before the value to look for context
    languages: [el]         # optional: only run when this language is enabled
    ignore_case: true       # default true
    require_digit: true     # default true for ID categories; pure-digit values need 5+ digits
```

`{MARKER}` expands to the "No." forms of every supported language (`no.`, `nr.`, `n°`, `nº`, `n.º`, `n.`, `núm.`, `αρ.`, `#`, `number`).

Rules of thumb:

1. **Anchor on a keyword or a checksum.** A pattern that fires on any number breaks analysis.
2. **Capture only the value**, not the keyword, so "Invoice No: INV-2024/0187" keeps "Invoice No:".
3. **Add a test** in `tests/` with a true positive *and* a near-miss that must not match.

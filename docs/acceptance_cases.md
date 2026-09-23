# Acceptance Cases

These cases define Stage 2 acceptance scenarios. The source adapters provide the normalized
official text and metadata; Stage 2 is responsible for deterministic diff, relevance filtering,
structured AI analysis, and persisted audit metadata.

## Case 1 - Tax Code Amendment

Base document:

- Tax Code of Ukraine
- 2755-VI

Reference:

- Law No. 4835-IX
- adopted: 07.04.2026
- effective: 15.04.2026

Expected Stage 2 behaviour:

new law -> detect affected Tax Code provisions -> detect new Tax Code version -> old/new -> effective date -> affected taxpayers -> practical impact.

## Case 2 - New Or Changed Tax Authority / ZIR Explanation

Expected Stage 2 behaviour:

new explanation or changed old explanation -> old official position -> new official position -> meaningful change? -> related Tax Code provisions -> practical impact.

Important: the system must detect changes to existing ZIR answers, not only new publications.

## Case 3 - Minfin Reporting Form Amendment

Reference:

- Minfin Order No. 186
- 06.04.2026

Expected Stage 2 behaviour:

which form changed -> what fields or appendices changed -> reason -> effective date -> affected taxpayers -> required process/accounting system changes.

## Case 4 - Related Document Chain

Reference:

Minfin Order No. 249 -> Minfin Order No. 293 -> Tax Authority letter dated 08.07.2026 No. 15504/7/99-00-21-02-01-07.

Expected Stage 2 behaviour:

Do not treat these as unrelated news.

Expected chain:

primary change -> document correction/amendment -> official explanation.

This case justifies the `DocumentRelation` architecture.

## Case 5 - CRS 2.0

Reference:

- Minfin Order No. 316
- 15.06.2026
- effective: 01.07.2026

Expected Stage 2 behaviour:

detect change -> international taxation / CRS classification -> reporting requirements -> affected entities -> effective date -> practical actions.

## Future EU Integration Case

Future system should understand:

EU requirement/change -> required Ukrainian implementation -> actual/proposed Ukrainian legislation -> potential company impact.

Relevant topics:

- Chapter 16 Taxation
- VAT
- Excise
- DAC
- Administrative Cooperation
- Tax Transparency
- E-Invoicing
- Digital VAT
- Accounting
- Financial Reporting

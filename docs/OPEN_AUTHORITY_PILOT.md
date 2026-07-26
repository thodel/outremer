# Open authority and place pilot

All adapters pass through the M12.1 source gate and write immutable,
checksum-bearing snapshots. Network acquisition uses the declared Outremer user
agent, bounded exponential backoff, and source-appropriate endpoints:

- Wikidata: EntityData/API records or a bounded dump slice; retain QID,
  `lastrevid`, claims, qualifiers, and references. The legacy unversioned
  peerage cache is not an input.
- FactGrid: Wikibase API/SPARQL bounded by the pilot identifiers; retain its own
  QIDs and revisions. FactGrid records are never folded into Wikidata records.
- GND: SRU `authorities` records; retain GND ID, preferred and variant names,
  record version, and CC0 status.
- Pleiades: a named release download; retain place URI, temporal attestations,
  geometry, and provenance. It is an ancient-world gazetteer, so medieval
  candidates may remain unresolved.

Candidates are generated from name overlap, chronology, place context, and
source-specific identifiers. Label equality never asserts identity. Every
candidate enters curator review and accepted/rejected decisions live outside
replaceable snapshots, so downtime cannot erase review history.

## Pilot assessment

`data/pilots/open-authorities/reconciliation_report.json` records a
precision-oriented twenty-case fixture assessment. It is deliberately small:
the next live run should replace fixture judgements with named reviewers and
record elapsed review time while preserving these ambiguity classes.

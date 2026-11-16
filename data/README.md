# Δεδομένα · Data

Πίνακες για προγράμματα, όχι για ανάγνωση · Machine-readable tables about the record (not law text):

| Αρχείο · File | Περιεχόμενο · What it holds |
| --- | --- |
| [`paths.json`](paths.json) | κάθε id πράξης -> φάκελος, και οι παλαιότεροι φάκελοι (`previous`) · every act id -> its folder, and the folders it had before each layout move |
| [`acts.json`](acts.json) | πράξεις με τίτλο, κατάσταση, εκδόσεις · acts with title, status, versions (the earlier build's 624 acts) |
| [`versions.json`](versions.json) | κάθε έκδοση με πηγή και sha256 · every version with its source and sha256 |
| [`laws.csv`](laws.csv) | οι πράξεις που επέφεραν μεταβολές · the acts credited with changes |
| [`commits.csv`](commits.csv), [`appends.csv`](appends.csv) | πώς χτίστηκε η ιστορία · how the history was built |
| [`repo.json`](repo.json), [`corpus.sha256`](corpus.sha256) | ρυθμίσεις και άθροισμα ελέγχου · settings and checksum |
| `effort-*.svg`, `el/` | το διάγραμμα του README · the README chart |
| [`earlier-build/`](earlier-build/README.md) | αρχείο της προηγούμενης έκδοσης του αποθετηρίου · archive of an earlier build of this repository |

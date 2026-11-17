# Northstar Support Assistant – Deployment-Bericht

**Stand** 17. November 2026  
**Empfehlung** Überarbeiten. Die Dry-Instanz auf Render hat die Lastziele im gemessenen Profil erfüllt. Für eine Produktivfreigabe fehlen richtlinientreue Live-Antworten und Lastdaten mit dem echten Provider.

## Deployment und Konfiguration

- FastAPI stellt `GET /health`, `GET /ready` und `POST /generate` bereit. Uvicorn läuft im Docker-Container auf `0.0.0.0:8000`. Das Image bindet die Python-Abhängigkeiten über `uv.lock`.
- Render-Testinstanz mit einem Free Web Service und einem Uvicorn-Prozess. Der öffentliche Endpunkt läuft im Dry-Modus mit `dry-northstar-v1`. Der geprüfte Stand ist `f0ec71a`, die Langfuse-Umgebung `staging`. [Render-Service](https://mle6-llm-application-deployment-project.onrender.com)
- Der lokale Live-Lauf verwendet die Groq-Erweiterung im Arbeitsstand auf Basis von `f0ec71a` mit `openai/gpt-oss-20b`. Der Systemprompt enthält die Northstar-Übungsregeln. Der Ausgabegrenzwert beträgt 512 Tokens.
- Der prozesslokale Cache speichert Antworten 60 Sekunden. Auf Render umfasst der SHA-256-Schlüssel Modell und Prompt. Der lokale Live-Arbeitsstand nimmt zusätzlich den Modus sowie bei Groq den Systemprompt und den Ausgabegrenzwert auf. Pro Prozess laufen höchstens zwei Provideraufrufe parallel. Das Zeitlimit von fünf Sekunden umfasst Wartezeit und Provideraufruf.
- Eine Instanz reicht für das gemessene Dry-Profil. Bei mehreren Prozessen oder Instanzen hat jede ihren eigenen Cache und ihr eigenes Parallelitätslimit. Das kann zusätzliche Provideraufrufe und mehr Speicherverbrauch erzeugen. Vor einer Skalierung sind Lastmessungen mit dem Live-Provider und eine Entscheidung über einen gemeinsamen Cache und instanzübergreifende Limits nötig.
- Lokale Geheimnisse werden über `.env` geladen. Auf Render liegen die Langfuse-Zugangsdaten in den Umgebungsvariablen des Dienstes.

## Funktionsprüfung

Je Lauf wurden fünf unterschiedliche Fälle als sechs HTTP-Anfragen ausgeführt. Der Refund-Fall wurde einmal wiederholt. In beiden Modi war die erste Refund-Anfrage ein Cache-Miss und die zweite ein Cache-Hit. Die vier übrigen Fälle waren Cache-Misses. Lokal lieferten beide Modi jeweils sechs HTTP-200-Antworten.

Die fachliche 0/1-Rubrik vergibt einen Punkt, wenn eine erfolgreiche Antwort den erforderlichen Handlungsschritt vermittelt oder beim nicht abgedeckten Fall korrekt ablehnt. Bewertet wurde jeweils die erste Antwort pro Testfall. Die zweite Refund-Anfrage dient als Cache-Nachweis. Die Bewertung liest die Antworten im Zusammenhang. Zusätzliche Aussagen zur Richtlinie werden separat als Abweichungen festgehalten.

| Fall | Dry lokal | Live lokal | Beobachtung im Live-Lauf |
|---|---:|---:|---|
| `refund_supported` | 1 | 1 | Nennt den Beleg und beide Transaktionsreferenzen. Ergänzt einen Zahlungsnachweis als Alternative zum Beleg, den die Übungsregel nicht vorsieht. |
| `account_access` | 0 | 1 | Nennt Identitätsprüfung vor dem genehmigten Reset. Ergänzt Sicherheitsfragen und temporäre Passwörter ohne Vorgabe in der Übungsregel. |
| `privacy_handoff` | 0 | 1 | Empfiehlt die Weiterleitung an das Privacy-Team zur menschlichen Prüfung. |
| `incident_status` | 0 | 1 | Nennt die Statusseite und bestätigte Informationen. Behauptet zusätzlich, dass das Team bereits an einer Lösung arbeitet. |
| `unsupported_policy` | 1 | 1 | Lehnt die nicht abgedeckte Vergünstigung ab. |
| **Mittelwert, je fünf Fälle** | **0,40** | **1,00** | **Live erreicht das Ziel von ≥ 0,80 für diese Rubrik und Stichprobe.** |

Im Dry-Modus erhalten die drei Fälle mit 0 Punkten dieselbe pauschale Ablehnung. Der Live-Score misst die Abdeckung der erwarteten Schritte in fünf Übungsfällen. Die drei unbelegten Zusätze sind für eine Produktivfreigabe relevant.

Für den Live-Lauf wurde im Projektordner bei frisch gestarteter API ausgeführt:

```bash
MODEL_PROVIDER=groq TRACE_SINK=langfuse python -m uvicorn app:app
```

In einem zweiten Terminal:

```bash
python scripts/evaluate.py --model openai/gpt-oss-20b \
  --output reports/generated/functional-live.json
```

Den ursprünglichen lokalen Dry-Lauf haben wir mit demselben Fallkatalog vor Einführung des Skripts durchgeführt. Er ist mit `MODEL_PROVIDER=dry`, `--model dry-northstar-v1` und einem eigenen Ausgabepfad reproduzierbar. Die Datei [cases.json](../data/evaluation/cases.json) enthält die unveränderten Testfälle.

## Lastmessung und Zielvergleich

Das [Lastprofil](../data/operations/load_profile.json) umfasst 40 Versuche mit bis zu fünf parallelen HTTP-Anfragen. Drei wiederkehrende Prompts machen den Lauf cache-lastig. Der anfängliche Zustand dieser drei Cache-Einträge wurde nicht protokolliert. Für den gehosteten Lauf wurde die Instanz vorher über `/health` gestartet. Die Messung enthält daher die HTTPS-Verbindung, während der Aufwachvorgang vor der Messung lag.

| Kennzahl | Ziel | Dry lokal | Dry Render |
|---|---:|---:|---:|
| Erfolgreiche Anfragen | | 40/40 | 40/40 |
| Erfolgreicher Durchsatz | | 286,76 Anfragen/s | 48,95 Anfragen/s |
| Mittlere HTTP-Latenz | | 9,83 ms | 87,78 ms |
| p95 HTTP-Latenz | ≤ 2.000 ms | 11,49 ms · erfüllt | 122,39 ms · erfüllt |
| HTTP- und Transportfehlerrate | ≤ 2 % | 0,00 % · erfüllt | 0,00 % · erfüllt |

Das Skript sortiert die Latenzen aller Versuche einschließlich etwaiger Fehler und verwendet für p95 den Rang `ceil(0,95 × n)`. Die Fehlerrate ist der Anteil der Nicht-2xx-Antworten und Transportfehler. Eine einzelne fehlgeschlagene Anfrage würde in diesem Profil 2,50 % ergeben.

```bash
python scripts/load_test.py --url http://127.0.0.1:8000 --requests 40 --concurrency 5
URL="https://mle6-llm-application-deployment-project.onrender.com"
curl -fsS "$URL/health"
python scripts/load_test.py --url "$URL" --requests 40 --concurrency 5
```

Für Wiederholungen lädt `python scripts/load_test.py --url "$URL" --validate` dieselbe Last und prüft beide Grenzwerte automatisch. Ein Lastlauf mit Groq und ein gehosteter Live-Funktionstest sind **ungetestet**. Die fünf lokal gemessenen Live-Cache-Misses benötigten in der Route 294,56 bis 1.922,48 ms. Diese Trace-Werte sind Einzelmessungen und werden als solche dokumentiert.

## Traces, Tokenverbrauch und Kosten

- Die API gibt pro erfolgreicher Anfrage eine `trace_id` zurück. Der Root-Span `support-request` enthält Status, Cache-Flag und gemessene Verarbeitungszeit. Die untergeordneten Schritte sind `prepare-request`, `cache-lookup` und bei einem Provideraufruf `llm-generation`. Für die Dauer in der Route gilt `request_latency_ms`, weil die Spans nach der Verarbeitung aufgezeichnet werden.
- Auf Render wurde der Export über die zur API-Antwort passende Trace-ID `c2c516fe856249449739cf44ed4b9c30` mit Release `f0ec71a` und Umgebung `staging` geprüft. Lokal liegt ein manueller Langfuse-Score von 1,00 am Dry-Refund-Trace `b27bb7c14de04d86a23f3cea2c75ce46` vor.
- Für die Übung werden Traces bei aktiviertem Export vollständig erfasst. Die explizite Instrumentierung exportiert Modell, Status, Cache- und Laufzeitdaten sowie gegebenenfalls Tokenzahlen. Rohe Prompts, Antworten und API-Schlüssel sind in den selbst gesetzten Trace-Feldern ausgespart. Die lokale Funktionsausgabe enthält für die Bewertung synthetische Antworten.
- Der Dry-Provider verbraucht null Modell-Tokens und verursacht null Modellkosten. Die fünf Live-Generationen melden zusammen **1.210 Input-Tokens** und **901 Output-Tokens**, insgesamt **2.111 Tokens**. Die wiederholte Refund-Anfrage kam aus dem Anwendungscache und löste keinen Groq-Aufruf aus. Belege sind `reports/generated/functional-live.json` und die dazugehörigen Einträge in `reports/generated/local-traces.jsonl`.
- Rechnerische Live-Kosten für diese fünf Aufrufe **0,00036105 USD**. Ansatz sind 0,075 USD pro Million Input-Tokens und 0,30 USD pro Million Output-Tokens. Die Schätzung verwendet den regulären Input-Preis für alle gemeldeten Eingabe-Tokens. Eine tatsächliche Abrechnung und mögliche Rabatte durch den Provider-Cache wurden nicht geprüft. [Groq-Modellpreise](https://console.groq.com/docs/model/openai/gpt-oss-20b)

### Fehleranalyse

Der lokale Test `test_provider_error_returns_502` simulierte eine Ausnahme im Provider. Die API gab HTTP 502 zurück. Der lokale JSONL-Eintrag und der Langfuse-Trace mit ID `094b672a2fce43d5996b263f88d9acb3` stimmen überein. `prepare-request` und `cache-lookup` sind vorhanden, der Cache meldet einen Miss. Der Kind-Span `llm-generation` und der Root-Span sind als Fehler markiert. Damit lässt sich die Störung dem begonnenen Provideraufruf zuordnen. Der Fehlerfall geht in keine Antwortqualitätsstichprobe ein.

## Entscheidung und drei priorisierte Verbesserungen

**Überarbeiten.** Lokal verbessert Groq die Abdeckung der fünf Übungen von 0,40 auf 1,00. Die Live-Antworten zu Refund, Account Reset und Incident ergänzen unbelegte Details. Die gute p95-Zahl auf Render stammt aus dem Dry-Lauf. Der simulierte 502-Trace belegt, dass ein Providerfehler erkennbar ist, und liefert keine Rate für reale Groq-Fehler.

1. **Richtlinientreue verschärfen und prüfen.** Die drei unbelegten Zusätze als konkrete Regressionen erfassen. Das Modell an die freigegebenen Belege, Reset-Schritte und Incident-Informationen binden. Für die nächste Inhaltsprüfung Variationen ergänzen und falsche Zusagen oder Erweiterungen als Fehler werten.
2. **Live-Kapazität separat messen.** Eine kontrollierte Live-Testumgebung mit begrenztem Budget und synthetischen Anfragen einsetzen. Kalten und warmen Cache dokumentieren. p95, Fehlerrate, Tokens und Kosten unter dem vorgegebenen Profil erfassen.
3. **Providerlaufzeit und Wartezeit im Trace trennen.** Wartezeit vor dem Semaphor und Dauer des Provideraufrufs während der Verarbeitung messen. Mit beiden Werten lassen sich Überlastung der Anwendung und langsame Providerantworten gezielt untersuchen.

Für eine neue Freigabeentscheidung braucht es einen Live-Funktionstest ohne unbelegte Richtlinienangaben und einen kontrollierten Live-Lastlauf mit p95 ≤ 2.000 ms, Fehlerrate ≤ 2 % und belegter Antwortqualität ≥ 0,80.

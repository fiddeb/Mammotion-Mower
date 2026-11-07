# Verifiering av 0.1.1

Verifierad lokalt 2026-11-08 på macOS med Python 3.14.8 och Home Assistant 2026.10.4.

- `pytest -q`: **93 tester godkända**.
- `ruff check .` och `ruff format --check .`: godkända.
- Home Assistants officiella hassfest från taggen `2026.10.4`: **1 integration, 0 ogiltiga**.
- Separat kodgranskning genomförd; tre hittade kantfall rättade och regressionstestade.
- Mutationstest: byte från `or` till `and` i villkoret för första uppgiftshämtningen
  fick regressionstestet att fallera. Ursprunglig kod återställdes därefter.
- Tester använder riktiga Home Assistant-konfigurationsflöden och entiteter med
  simulerade externa HTTP-svar. SSE-parsern testas även med en riktig aiohttp StreamReader.
- Installationszipens CRC, manifest och filinnehåll kontrollerades mot källkoden.
  Samtliga elva moduler importerades från ett separat uppackat installationspaket.
- Installationsskriptet testas med nyinstallation, uppdatering med backup, sökvägar
  med mellanslag, avvisning av fel mål och symlänkar, installationslås samt återställning
  när ersättningen misslyckas. Ett mutationstest verifierar att testet upptäcker borttaget
  skydd mot att ersätta symlänkar.
- Inloggningsfelet i 0.1.0 återskapades med ett lyckat tokensvar inuti `data`:
  konfigurationsflödet visade felaktigt formuläret igen. Samma regressionstest passerar
  med rättningen. Både det officiella Swagger-formatet och det platta OAuth-formatet
  i kom-igång-guiden stöds, inklusive tokenens faktiska utgångstid.
- Autentiseringskontraktet verifierades mot
  `https://developer.mammotion.com/api/authentication_swagger.json` och sparades som
  `docs/mammotion-authentication-openapi.json`.

## API-täckning

| Operation | Exponering i integrationen |
| --- | --- |
| POST `/oauth2/token` | Cachad klientautentisering och automatisk förnyelse |
| GET `/v1/mowers` | Upptäckt av kontots klippare |
| GET `/v1/mower/{deviceId}` | Klipparaktivitet, batteri, anslutning, laddning och nätverk |
| GET `/v1/mower/{deviceId}/plan` | Val av uppgift och startknapp |
| POST `/v1/mower/action` | Alla sju dokumenterade kommandon |
| GET `/v1/mower/{deviceId}/work-params` | Svarsåtgärden `get_work_parameters` |
| POST `/v1/mower/error-codes/search` | Svarsåtgärden `get_error_history` med sidindelning och filter |
| POST `/v1/devices/subscriptions` | LUBA 3 AWD, högst 20 enheter per anrop |
| GET `/developer-sse/api/client/sse` | Händelser på eventbussen och samordnad REST-uppdatering |

Testerna omfattar tokenåteranvändning, samtidig förnyelse, HTTP 401/403/429,
kommandovalidering, timeout utan dubbelskickning, felaktiga API-svar, flera klippare,
nya och borttagna klippare, offline-tillstånd, återställning av valt uppdrag,
diagnostik, SSE-förnyelse, återanslutning och avbruten bakgrundsuppgift vid urladdning.

## Leveransstatus

Detta dokument beskriver den lokala verifieringen inför publicering av grenen `main`
i `https://github.com/fiddeb/Mammotion-Mower`. Aktuella CI-resultat finns under
repositoryts **Actions** på GitHub. Installationspaket kan byggas med
`python scripts/build_release.py`; installation på användarens Home Assistant
har inte utförts.

Ingen autentisering mot ett riktigt Mammotion-konto och inga kommandon till en fysisk
klippare har utförts. Praktisk verifiering av modellernas beteende och deras olika
SSE-payloadformat återstår. De format som saknar schema exponeras som ursprungliga
JSON-händelser, utan påhittade fälttolkningar eller mätenheter.

Källfingeravtryck för integrationens `.py`, `.json` och `.yaml`-filer:
`79b2cc53abf0f70960f65948a65b8f3329cd92c5aa65eb99ae3c1eb5a7f29c2d`.
Beräknat med SHA-256 över sorterade relativa filnamn, NUL och filinnehåll per fil.

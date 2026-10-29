# Protokoll Quartierfuchs ↔ Home Assistant (Version 1)

Diese Beschreibung ist der Vertrag zwischen der Integration (`custom_components/quartierfuchs`) und dem Quartierfuchs-Portal (`module/HomeAssistant/`).

## 1. Kopplung (HTTPS)

Das Portal erzeugt pro Kopplungsvorgang einen Einmalcode (Vorschlag: Format `QF-XXXX-XXXX`, 15 Minuten gültig, nur einmal verwendbar), gebunden an `id_vermieter`.

### Anfrage

`POST {portal_url}/api/homeassistant/kopplung`, `Content-Type: application/json`

```json
{
  "code": "QF-7K2M-9XPA",
  "instanz_id": "0f1c6d0e-…",
  "instanz_name": "Zuhause",
  "ha_version": "2026.10.2",
  "protokoll_version": 1
}
```

- `code` wird von der Integration in Großbuchstaben und ohne Leerzeichen gesendet.
- `instanz_id` ist die eindeutige, dauerhafte ID der Home-Assistant-Instanz.

### Antworten

| HTTP | Bedeutung |
|---|---|
| 200 | Kopplung erfolgreich, Zugangsdaten im Body |
| 400 | Anfrage fehlerhaft |
| 404 | Code unbekannt |
| 409 | Code bereits verwendet |
| 410 | Code abgelaufen |
| sonst | Portalfehler |

Body bei 200:

```json
{
  "broker_host": "mqtt.quartierfuchs.de",
  "broker_port": 8883,
  "broker_tls": true,
  "benutzername": "v12-a3f9c2e1",
  "passwort": "…",
  "topic_basis": "qf/v12-a3f9c2e1",
  "vermieter_name": "Haffquartier"
}
```

Regeln für das Portal:

- `topic_basis` ist immer `qf/<benutzername>`. Damit genügt im Broker eine einzige ACL-Regel (siehe Abschnitt 2).
- Bei erneuter Kopplung derselben `instanz_id` für denselben Vermieter wird **derselbe `benutzername`** mit einem **neuen Passwort** vergeben. Die Integration bricht sonst die Neuanmeldung mit „falsches Konto“ ab.
- Das Passwort wird im Portal nur als Hash gespeichert bzw. direkt in die Broker-Benutzerverwaltung geschrieben.

## 2. Broker

- Mosquitto, MQTT 3.1.1, TLS auf Port 8883.
- Client-ID der Integration: `ha-<benutzername>`.
- Last Will der Integration: `<topic_basis>/status` = `offline` (retained).

ACL-Datei (Auszug):

```
# Jede Home-Assistant-Instanz nur in ihrem eigenen Bereich
pattern readwrite qf/%u/#

# Portal-Benutzer
user quartierfuchs-portal
topic read qf/+/status
topic read qf/+/entitaeten
topic read qf/+/zustand/#
topic read qf/+/antwort
topic write qf/+/befehl
topic write qf/+/zustand/#
```

Schreibrecht des Portals auf `zustand/#` dient nur zum Aufräumen (leere Retained-Nachrichten beim Entkoppeln).

## 3. Topics

Alle Topics liegen unterhalb von `<topic_basis>`.

| Topic | Richtung | Retained | Inhalt |
|---|---|---|---|
| `status` | HA → Portal | ja | `online` / `offline` |
| `entitaeten` | HA → Portal | ja | Liste der freigegebenen Entitäten |
| `zustand/<entity_id>` | HA → Portal | ja | aktueller Zustand einer Entität |
| `befehl` | Portal → HA | nein | Befehl |
| `antwort` | HA → Portal | nein | Ergebnis eines Befehls |

QoS ist durchgehend 1.

### `entitaeten`

```json
{
  "protokoll_version": 1,
  "integration_version": "0.1.0",
  "ha_version": "2026.10.2",
  "entitaeten": [
    {
      "entity_id": "climate.fewo3_wohnzimmer",
      "domain": "climate",
      "name": "FeWo 3 Wohnzimmer",
      "bereich": "FeWo 3",
      "geraet": "Thermostat Wohnzimmer",
      "device_class": null,
      "einheit": null,
      "dienste": {
        "set_temperature": ["hvac_mode", "target_temp_high", "target_temp_low", "temperature"],
        "set_hvac_mode": ["hvac_mode"],
        "set_preset_mode": ["preset_mode"],
        "turn_off": [],
        "turn_on": []
      }
    }
  ]
}
```

Diese Liste ist maßgeblich. Zustände von Entitäten, die nicht (mehr) in der Liste stehen, ignoriert das Portal. Die Liste wird bei jedem Verbindungsaufbau, nach jeder Änderung der Freigaben und auf Anfrage (`synchronisieren`) neu gesendet.

### `zustand/<entity_id>`

```json
{
  "entity_id": "climate.fewo3_wohnzimmer",
  "state": "heat",
  "attribute": {
    "current_temperature": 19.5,
    "temperature": 21,
    "hvac_action": "heating"
  },
  "zuletzt_geaendert": "2026-10-29T18:12:04.512345+00:00",
  "zuletzt_aktualisiert": "2026-10-29T18:15:44.120001+00:00"
}
```

- Ist die Entität in Home Assistant nicht vorhanden: `{"entity_id": "…", "state": null}`.
- Wird eine Freigabe entzogen, sendet die Integration eine leere Retained-Nachricht (Löschung).

### `befehl`

Dienst aufrufen:

```json
{
  "id": "a81f3c",
  "typ": "dienst",
  "domain": "climate",
  "service": "set_temperature",
  "entity_id": "climate.fewo3_wohnzimmer",
  "data": {"temperature": 22}
}
```

Weitere Typen:

- `{"id": "…", "typ": "synchronisieren"}`: Integration sendet `status`, `entitaeten` und alle Zustände neu.
- `{"id": "…", "typ": "ping"}`: Integration antwortet nur.

Die Integration prüft vor jeder Ausführung:

1. `entity_id` ist freigegeben.
2. `domain` passt zur `entity_id`.
3. `service` ist für die Domain erlaubt.
4. `data` enthält nur erlaubte Parameter. `entity_id` wird von der Integration selbst gesetzt; Ziele wie `area_id` oder `device_id` sind nicht zulässig.

### `antwort`

```json
{"id": "a81f3c", "erfolg": true, "fehler": null}
```

Befehle ohne `id` werden ausgeführt, aber nicht beantwortet.

Fehlerwerte der Integration:

| `fehler` | Bedeutung |
|---|---|
| `unbekannter_typ` | `typ` ist nicht `dienst`, `synchronisieren` oder `ping` |
| `entitaet_nicht_freigegeben` | Entität nicht freigegeben |
| `domain_passt_nicht` | `domain` passt nicht zur `entity_id` |
| `dienst_nicht_erlaubt` | Dienst für diese Domain nicht erlaubt |
| `ungueltige_daten` | `data` ist kein Objekt |
| `unzulaessige_parameter: …` | nicht erlaubte Parameter in `data` |
| `zeitueberschreitung` | Dienst hat nicht innerhalb von 15 Sekunden geantwortet |
| sonstiger Text | Fehlermeldung von Home Assistant |

## 4. Entkoppeln

Das Portal

1. löscht bzw. sperrt den Broker-Benutzer und trennt dessen Verbindung,
2. löscht die Retained-Nachrichten unter `qf/<benutzername>/#` (leere Nachrichten auf `status`, `entitaeten` und jedes bekannte `zustand/<entity_id>`).

Lehnt der Broker danach die Anmeldung ab, beendet die Integration ihre Verbindungsversuche und fordert in Home Assistant zur erneuten Kopplung auf.

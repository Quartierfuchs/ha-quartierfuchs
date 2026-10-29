# custom_components/quartierfuchs/config_flow.py
"""Einrichtungs-, Optionen- und Neuanmeldungsdialog der Quartierfuchs-Integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .api import (
    KopplungsCodeUngueltig,
    PortalNichtErreichbar,
    UngueltigeAntwort,
    async_koppeln,
    portal_url_gueltig,
    portal_url_normalisieren,
)
from .const import (
    DOMAIN,
    KONF_BENUTZERNAME,
    KONF_CODE,
    KONF_PORTAL_URL,
    KONF_VERMIETER_NAME,
    OPT_ENTITAETEN,
    STANDARD_PORTAL_URL,
    UNTERSTUETZTE_DOMAINS,
)

_LOGGER = logging.getLogger(__name__)


def _entitaeten_schema(vorgabe: list[str]) -> vol.Schema:
    """Formular zur Auswahl der freigegebenen Entitäten."""
    return vol.Schema(
        {
            vol.Optional(OPT_ENTITAETEN, default=vorgabe): EntitySelector(
                EntitySelectorConfig(domain=list(UNTERSTUETZTE_DOMAINS), multiple=True)
            ),
        }
    )


async def _koppeln_mit_fehlern(
    hass: HomeAssistant, portal_url: str, code: str
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Führt die Kopplung aus und übersetzt Fehler in Formularfehler."""
    try:
        return await async_koppeln(hass, portal_url, code), {}
    except KopplungsCodeUngueltig:
        return None, {"base": "code_ungueltig"}
    except PortalNichtErreichbar as fehler:
        _LOGGER.warning("Quartierfuchs-Portal nicht erreichbar: %s", fehler)
        return None, {"base": "portal_nicht_erreichbar"}
    except UngueltigeAntwort as fehler:
        _LOGGER.warning("Ungültige Antwort des Quartierfuchs-Portals: %s", fehler)
        return None, {"base": "ungueltige_antwort"}
    except Exception:
        _LOGGER.exception("Unerwarteter Fehler bei der Kopplung")
        return None, {"base": "unbekannt"}


class QuartierfuchsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Kopplung einer Home-Assistant-Instanz mit Quartierfuchs."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialisiert den Dialog."""
        self._kopplung: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Liefert den Optionen-Dialog (Freigaben ändern)."""
        return QuartierfuchsOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 1: Kopplungscode und Portal-Adresse eingeben."""
        fehler: dict[str, str] = {}

        if user_input is not None:
            portal_url = portal_url_normalisieren(user_input[KONF_PORTAL_URL])
            if not portal_url_gueltig(portal_url):
                fehler["base"] = "url_ungueltig"
            else:
                kopplung, fehler = await _koppeln_mit_fehlern(
                    self.hass, portal_url, user_input[KONF_CODE]
                )
                if kopplung is not None:
                    await self.async_set_unique_id(kopplung[KONF_BENUTZERNAME])
                    self._abort_if_unique_id_configured()
                    self._kopplung = {**kopplung, KONF_PORTAL_URL: portal_url}
                    return await self.async_step_entitaeten()

        schema = vol.Schema(
            {
                vol.Required(KONF_CODE): str,
                vol.Required(KONF_PORTAL_URL, default=STANDARD_PORTAL_URL): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=fehler,
        )

    async def async_step_entitaeten(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 2: Geräte für Quartierfuchs freigeben."""
        if user_input is not None:
            titel = self._kopplung.get(KONF_VERMIETER_NAME) or "Quartierfuchs"
            return self.async_create_entry(
                title=titel,
                data=self._kopplung,
                options={OPT_ENTITAETEN: user_input.get(OPT_ENTITAETEN, [])},
            )

        return self.async_show_form(step_id="entitaeten", data_schema=_entitaeten_schema([]))

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Wird ausgelöst, wenn der Broker die Anmeldung ablehnt."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Neuen Kopplungscode eingeben und Zugangsdaten erneuern."""
        eintrag = self._get_reauth_entry()
        fehler: dict[str, str] = {}

        if user_input is not None:
            kopplung, fehler = await _koppeln_mit_fehlern(
                self.hass, eintrag.data[KONF_PORTAL_URL], user_input[KONF_CODE]
            )
            if kopplung is not None:
                await self.async_set_unique_id(kopplung[KONF_BENUTZERNAME])
                self._abort_if_unique_id_mismatch(reason="falsches_konto")
                return self.async_update_reload_and_abort(
                    eintrag, data={**eintrag.data, **kopplung}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(KONF_CODE): str}),
            errors=fehler,
        )


class QuartierfuchsOptionsFlow(OptionsFlow):
    """Freigaben nachträglich ändern."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Auswahl der freigegebenen Entitäten."""
        if user_input is not None:
            return self.async_create_entry(
                data={OPT_ENTITAETEN: user_input.get(OPT_ENTITAETEN, [])}
            )

        return self.async_show_form(
            step_id="init",
            data_schema=_entitaeten_schema(
                list(self.config_entry.options.get(OPT_ENTITAETEN, []))
            ),
        )

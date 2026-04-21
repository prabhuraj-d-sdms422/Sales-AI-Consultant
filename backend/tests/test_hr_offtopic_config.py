from app.config.settings import settings
from app.prompts.discovery_prompt import DISCOVERY_SMART_PROMPT


def test_settings_expose_hr_contact_fields():
    assert hasattr(settings, "hr_email")
    assert hasattr(settings, "hr_phone_number")


def test_discovery_prompt_has_hr_contact_placeholder():
    assert "{hr_contact_block}" in DISCOVERY_SMART_PROMPT


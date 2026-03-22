from backend.routers.interactions import _recover_mojibake_filename, _safe_upload_filename
from backend.services.ai_service import _normalize_image_analysis_payload
from backend.services.correspondence_intelligence_service import _display_channel_label


def test_recover_mojibake_filename_round_trip():
    original = "Fran\u00e7ois Profile.pdf"
    mojibake = original.encode("utf-8").decode("latin-1")
    assert _recover_mojibake_filename(mojibake) == original


def test_safe_upload_filename_sanitizes_path_and_invalid_chars():
    cleaned = _safe_upload_filename("..\\temp\\Profile<>:?*.pdf")
    assert cleaned == "Profile_.pdf"


def test_display_channel_label_infers_whatsapp_for_screenshot_blob():
    label = _display_channel_label(
        "screenshot",
        summary="Image processed",
        raw_text="WhatsApp conversation. Last seen today at 10:22.",
    )
    assert label == "WhatsApp"


def test_display_channel_label_infers_email_for_screenshot_blob():
    label = _display_channel_label(
        "screenshot",
        summary="Screenshot intake",
        raw_text="Subject: Follow up\nFrom: user@example.com",
    )
    assert label == "Email"


def test_image_payload_normalization_promotes_headshot_summary():
    normalized = _normalize_image_analysis_payload(
        {
            "image_type": "general_image",
            "image_type_confidence": 0.61,
            "screen_context": "uncertain",
            "summary": "Professional headshot portrait",
            "extracted_text": "",
        }
    )
    assert normalized["is_profile_photo"] is True
    assert normalized["image_type"] == "profile_picture"


def test_image_payload_normalization_demotes_ui_context_profile_photo():
    normalized = _normalize_image_analysis_payload(
        {
            "is_profile_photo": True,
            "image_type": "profile_picture",
            "image_type_confidence": 0.93,
            "screen_context": "whatsapp_chat",
            "summary": "WhatsApp screenshot",
            "extracted_text": "John: let's meet tomorrow",
        }
    )
    assert normalized["is_profile_photo"] is False
    assert normalized["image_type"] == "screenshot"

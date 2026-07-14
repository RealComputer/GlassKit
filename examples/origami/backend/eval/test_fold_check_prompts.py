from src.fold_check_prompts import fold_check_completion_payload


def test_completion_payload_omits_thread_id() -> None:
    payload = fold_check_completion_payload(
        model="test-model",
        prompt="test criteria",
        image_url="data:image/jpeg;base64,test",
    )

    assert "thread_id" not in payload

With the Realtime API you can keep VAD enabled, stop the server from auto-starting a response, inject an `input_image` as an extra user item, then manually trigger `response.create`. ([OpenAI Platform][1])

## 1) Configure: keep VAD, disable auto responses

Send `turn_detection.create_response=false` and `turn_detection.interrupt_response=false` on session setup. This keeps VAD behavior (turn segmentation), but the server will not auto-create Responses, so you control when `response.create` happens. ([OpenAI Platform][1])

## 2) Which 'speech boundary' event to use

If you are in `server_vad`, the turn end signal is:

* `input_audio_buffer.speech_stopped` (end of a speech turn) ([OpenAI Platform][3])

In `server_vad`, `input_audio_buffer.speech_stopped` includes an `item_id`, and the server will also emit `conversation.item.created` for the user audio message created from the buffer. ([OpenAI Platform][2])

If you prefer to key off 'the audio has been committed into the conversation', you can also use:

* `input_audio_buffer.committed` (audio buffer committed, and `conversation.item.created` will also be sent) ([OpenAI Platform][2])

## 3) Inject the image via `conversation.item.create` before response

You cannot 'edit' the already-created user-audio item to append an image, but you *can* add another user message item right after it, containing `input_image` (and optionally `input_text` to explicitly link it to the previous utterance). `gpt-realtime` can incorporate the image when it responds. ([OpenAI Platform][1])

To guarantee ordering, use `previous_item_id` = the audio message item id. If the id cannot be found yet, the server returns an error, so the safest approach is: wait until you receive `conversation.item.created` for that audio item, then send the image item. ([OpenAI Platform][4])

Image payload format: `input_image.image_url` is a data URI with base64 image bytes; PNG and JPEG are supported. ([OpenAI Platform][4])

## 4) Trigger the response manually

After the image item is created, send `response.create`. `response.create` can be as minimal as `{ "type": "response.create" }`. ([OpenAI Platform][4])

## Suggested event flow (server_vad)

1. set `turn_detection.create_response=false`, `turn_detection.interrupt_response=false` ([OpenAI Platform][1])
2. Receive `input_audio_buffer.speech_stopped` (capture `item_id`) ([OpenAI Platform][2])
3. Receive `conversation.item.created` for that `item_id` (audio user message now exists) ([OpenAI Platform][2])
4. Send `conversation.item.create` with `previous_item_id=item_id` and content `[input_text?, input_image]` ([OpenAI Platform][4])
5. Send `response.create` ([OpenAI Platform][4])

[1]: https://platform.openai.com/docs/guides/realtime-conversations "Realtime conversations | OpenAI API"
[2]: https://platform.openai.com/docs/api-reference/realtime-server-events "Server events | OpenAI API Reference"
[3]: https://platform.openai.com/docs/guides/realtime-vad "Voice activity detection (VAD) | OpenAI API"
[4]: https://platform.openai.com/docs/api-reference/realtime-client-events "Client events | OpenAI API Reference"

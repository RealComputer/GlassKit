from google import genai

client = genai.Client()

interaction = client.interactions.create(
    model="gemini-3.5-flash",
    input="Explain how AI works in a few words",
    service_tier='flex'
)

print(interaction.output_text)

# import base64
# from google import genai
#
# with open('path/to/sample.jpg', 'rb') as f:
#     image_bytes = f.read()
#
# client = genai.Client()
#
# interaction = client.interactions.create(
#     model="gemini-3.5-flash",
#     input=[
#         {"type": "text", "text": "Caption this image."},
#         {
#             "type": "image",
#             "data": base64.b64encode(image_bytes).decode('utf-8'),
#             "mime_type": "image/jpeg",
#             #resolution": "high"
#         }
#     ]
# )
# print(interaction.output_text)

# system_instruction="", # Use for task definition, rules, contract

# generation_config={
#     thinking_level": "low", # minimal, low, medium, high
#     "thinking_summaries": "auto"
# }

# import time
# from google import genai
#
# client = genai.Client()
#
# def call_with_retry(max_retries=3, base_delay=5):
#     for attempt in range(max_retries):
#         try:
#             return client.interactions.create(
#                 model="gemini-3.5-flash",
#                 input="Analyze this batch statement.",
#                 service_tier="flex", # use this
#             )
#         except Exception as e:
#             if attempt < max_retries - 1:
#                 delay = base_delay * (2 ** attempt) # Exponential Backoff
#                 print(f"Flex busy, retrying in {delay}s...")
#                 time.sleep(delay)
#             else:
#                 print("Flex exhausted, falling back to Standard...")
#                 return client.interactions.create(
#                     model="gemini-3.5-flash",
#                     input="Analyze this batch statement."
#                 )
#
# interaction = call_with_retry()
# print(interaction.output_text)

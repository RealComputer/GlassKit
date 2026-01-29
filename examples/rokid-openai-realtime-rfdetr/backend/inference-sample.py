# Run: `uv run --env-file .env inference-sample.py`
import os
import supervision as sv
from inference import get_model
# import time

model = get_model(model_id="test2-abpsp/4", api_key=os.getenv("ROBOFLOW_API_KEY"))

image = "TODO"  # pass np.ndarray(BGR) frame

# infer_start = time.perf_counter()
predictions = model.infer(image, confidence=0.5)[0]
# infer_ms = (time.perf_counter() - infer_start) * 1000
# print(f"model.infer latency: {infer_ms:.2f} ms")

detections = sv.Detections.from_inference(predictions)

labels = [prediction.class_name for prediction in predictions.predictions]

# annotated_image = image.copy()
# annotated_image = sv.BoxAnnotator().annotate(annotated_image, detections)
# annotated_image = sv.LabelAnnotator().annotate(annotated_image, detections, labels)
